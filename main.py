#!/usr/bin/env python3
import asyncio
import requests
import time
import logging
import hashlib
from collections import OrderedDict
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent, Resource
import hashlib

# ========== CONFIGURATION - ONLY UPDATE THESE ==========
DRUPAL_BASE_URL   = "https://docs.acquia.com/"
DRUPAL_DOCS_START = f"{DRUPAL_BASE_URL}"  # Main docs page
MAIN_DOC_URLS     = [
  "https://docs.acquia.com/acquia-source/overview",
  "https://docs.acquia.com/campaign-studio/overview",
  "https://docs.acquia.com/content-optimization/overview",
  "https://docs.acquia.com/conversion-optimization/overview",
  "https://docs.acquia.com/customer-data-platform/overview-0",
  "https://docs.acquia.com/acquia-cloud-platform/overview",
  "https://docs.acquia.com/acquia-dam/overview",
  "https://docs.acquia.com/drupal-starter-kits/overview",
  "https://docs.acquia.com/site-factory/overview",
  "https://docs.acquia.com/web-governance/overview"
]
MAX_CRAWL_DEPTH       = 5    # Increased depth for better deep page discovery
CACHE_SIZE            = 1000 # Larger cache for more comprehensive coverage
REQUEST_DELAY         = 0.5  # Conservative rate limiting
MAX_PAGES_PER_PRODUCT = 75   # Increased limit for better coverage

# Demo-specific Memcached documentation - Pre-loaded for instant access
MEMCACHED_DOC_URL = "https://docs.acquia.com/acquia-cloud-platform/enabling-memcached-cloud-platform"
MEMCACHED_DOC_CONTENT = """# Enabling Memcached on Cloud Platform

To enable Memcached on your website hosted by Cloud Platform, you must install the Memcache API and Integration module in your codebase, and configure the module for use.

## Configuration for the current Drupal version

For Memcached to function, you must provide additional configuration code that enables autoloading, and identifies Memcached as an alternative cache back-end.

To configure your website for Memcached, make the following changes to your codebase, depending on your subscription type:

### For Cloud Classic:

1. Download the Memcache API and Integration module, and then add the module to your codebase in the modules/contrib/memcache directory. Acquia recommends that you use Composer to install the module:
   ```
   composer require drupal/memcache
   ```

2. For Cloud Classic, do the following:
   
   a. Add the Composer package that contains the Acquia Memcache settings to your project:
   ```
   composer require acquia/memcache-settings
   ```
   
   b. For each website that requires Memcached, edit the Cloud Platform database require line in settings.php with a PHP require_once statement, similar to the following example:
   ```php
   if (file_exists('/var/www/site-php')) {
      require('/var/www/site-php/mysite/mysite-settings.inc');
      // Memcached settings for Acquia Hosting
      $memcache_settings_file = DRUPAL_ROOT . "/../vendor/acquia/memcache-settings/memcache.settings.php";
      if (file_exists($memcache_settings_file)) {
        require_once $memcache_settings_file;
      }
   }
   ```

3. Rebuild caches by running the following command, replacing [example.com] with the domain name of your website:
   ```
   drush cr --uri=[example.com]
   ```

4. Truncate all cache_ tables in the database for the website.

### For Cloud Next:
For Cloud Next, you do not need to add anything to your settings.php file as the configuration logic is already included in Cloud Next. If you already have code in settings.php that enables Memcache integration with Cloud Platform, you can opt to remove it.

## Important Notes:
- Do not edit the memcache_key_prefix or memcache_servers settings, as Cloud Platform adds the correct values in Acquia-specific code.
- Test any procedures on a non-production environment before implementing them on production.
- The same steps must be used for CD environments because CD environments are not supported in Cloud Next.

Source: https://docs.acquia.com/acquia-cloud-platform/enabling-memcached-cloud-platform
"""

# Additional tool to get source links for any query
def get_source_links_for_query(query: str) -> str:
  """Get the official source documentation links for a given query"""
  if is_memcached_related_query(query):
      return MEMCACHED_DOC_URL
  
  # For other queries, try to find the most relevant documentation URL
  results = direct_search_docs(query)
  if results and results[0]['url']:
      return results[0]['url']
  
  # Fallback to general search
  return f"https://docs.acquia.com/search/?q={requests.utils.quote(query)}"
# =======================================================

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

app = Server("drupal-docs")

# In-memory cache for crawled pages
page_cache = {}  # URL -> page_data mapping
url_to_cache_key = {}  # URL -> cache_key mapping for quick lookup
discovered_urls = set()

def is_docs_url(url: str) -> bool:
  """Check if URL is an Acquia documentation page - more inclusive for deep pages"""
  parsed = urlparse(url)
  
  # Basic domain check
  if parsed.netloc != urlparse(DRUPAL_BASE_URL).netloc:
    return False
  
  path_lower = parsed.path.lower()
  
  # Quick exclusions - be more specific to avoid blocking legitimate docs
  excluded_patterns = [
    '/user/login', '/user/register', '/user/password', '/user/logout',
    '/admin/', '/taxonomy/term/', '/node/add',
    '/contact', '/rss.xml', '/sitemap.xml'
  ]
  
  excluded_extensions = ['.jpg', '.jpeg', '.png', '.gif', '.pdf', '.zip', '.tar.gz', '.css', '.js']
  
  # Check for exact excluded patterns (not just contains)
  for pattern in excluded_patterns:
    if pattern in path_lower:
      return False
  
  if any(path_lower.endswith(ext) for ext in excluded_extensions):
    return False
  
  # Remove fragment and query parameters but keep the URL valid
  if path_lower.startswith('/') and len(path_lower) > 1:
    # Much more inclusive - accept most paths under docs.acquia.com
    # Exclude only specific problem patterns, include everything else
    problem_patterns = ['/themes/', '/modules/', '/core/', '/sites/default']
    if not any(pattern in path_lower for pattern in problem_patterns):
      return True
  
  return False

def add_to_cache(url: str, page_data: dict):
    """Add page to cache with FIFO eviction when cache is full"""
    if len(page_cache) >= CACHE_SIZE:
        # Remove oldest entry (FIFO)
        oldest_url = next(iter(page_cache))
        del page_cache[oldest_url]
        if oldest_url in url_to_cache_key:
            del url_to_cache_key[oldest_url]
    
    page_cache[url] = page_data
    url_to_cache_key[url] = hashlib.md5(url.encode()).hexdigest()[:8]

def fetch_page(url: str) -> dict:
  """Fetch and parse a page"""
  try:
    if url in page_cache:
      return page_cache[url]
        
    headers = {
      'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
      'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      'Accept-Language': 'en-US,en;q=0.9',
      'Referer': DRUPAL_BASE_URL,
    }
    
    response = requests.get(url, headers=headers, timeout=15)
    response.raise_for_status()
    
    # Add response size check to prevent memory issues
    if len(response.content) > 5 * 1024 * 1024:  # 5MB limit
      raise ValueError("Response too large")
        
    soup = BeautifulSoup(response.text, 'html.parser')
    
    for element in soup(['script', 'style', 'nav', 'footer', 'header', 'aside', 'iframe']):
      element.decompose()
        
    # Try multiple content selectors for better content extraction
    content_elem = (
      soup.find('div', class_='node__content') or
      soup.find('div', class_='field--name-body') or
      soup.find('div', class_='field-item') or
      soup.find('article') or
      soup.find('main') or
      soup.find('div', class_='content') or
      soup.find('div', id='content') or
      soup.find('div', class_='region-content') or
      soup.find('div', class_='block-system-main-block') or
      soup.find('div', class_='layout-content') or
      soup.find('section', class_='block-layout-builder') or
      soup.find('div', class_='views-element-container')
    )
    
    content_text = content_elem.get_text(strip=True, separator='\n') if content_elem else soup.get_text(strip=True, separator='\n')
    
    # Better title extraction
    title_elem = (
      soup.find('h1', class_='page-title') or
      soup.find('h1', class_='title') or
      soup.find('h1') or
      soup.find('title')
    )
    title = title_elem.get_text(strip=True) if title_elem else "Untitled"
    if " | " in title:
      title = title.split(" | ")[0].strip()
        
    # Enhanced link extraction - look for more types of navigation
    links = []
    
    # Main content links
    for a_tag in soup.find_all('a', href=True):
      href = a_tag['href']
      full_url = urljoin(url, href)
      # Clean URL but preserve query params that might be important
      full_url = full_url.split('#')[0]
      if is_docs_url(full_url) and full_url != url:
          links.append(full_url)
          discovered_urls.add(full_url)
            
    # Enhanced navigation selectors for better link discovery
    nav_selectors = [
      'nav a', '.menu a', '.sidebar a', '.navigation a', 
      '.toc a', '.table-of-contents a', '.book-navigation a',
      '.region-sidebar a', '.block-menu a', '.breadcrumb a',
      '.pager a', '.item-list a', '.view-content a',
      '.field--name-field-related-content a',
      '.block-views a', '.views-row a'
    ]
    
    for selector in nav_selectors:
      for a_tag in soup.select(selector):
        if a_tag.get('href'):
          href = a_tag['href']
          full_url = urljoin(url, href)
          full_url = full_url.split('#')[0]
          if is_docs_url(full_url) and full_url != url and full_url not in links:
            links.append(full_url)
            discovered_urls.add(full_url)
                    
    result = {
      'url': url,
      'title': title,
      'content': content_text,
      'links': list(set(links)),
      'success': True
    }
    
    add_to_cache(url, result)
    return result
  except requests.exceptions.RequestException as e:
    return {
      'url': url,
      'title': 'Network Error',
      'content': f"Network error: {str(e)}",
      'links': [],
      'success': False
    }
  except Exception as e:
    return {
      'url': url,
      'title': 'Parse Error',
      'content': f"Parse error: {str(e)}",
      'links': [],
      'success': False
    }

def crawl_docs(start_urls: list = None, max_depth: int = 4) -> dict:
  """Crawl documentation site comprehensively"""
  if start_urls is None:
      start_urls = [DRUPAL_DOCS_START] + MAIN_DOC_URLS
  visited = set()
  to_visit = [(url, 0, 'main') for url in start_urls]
  all_pages = {}
  product_page_counts = {}
  logger.info(f"Starting comprehensive crawl of {len(start_urls)} product areas...")
  while to_visit:
    url, depth, product_hint = to_visit.pop(0)
    if url in visited or depth > max_depth:
      continue
    product_area = get_product_area(url)
    if product_area not in product_page_counts:
        product_page_counts[product_area] = 0
    if product_page_counts[product_area] >= MAX_PAGES_PER_PRODUCT:
      continue
    visited.add(url)
    product_page_counts[product_area] += 1
    logger.info(f"Crawling [{product_area}]: {url} (depth {depth}, page {product_page_counts[product_area]})")
    
    if len(visited) > 1:
      time.sleep(REQUEST_DELAY)
    page_data = fetch_page(url)
    if page_data['success']:
      all_pages[url] = page_data
        
      # Prioritize links from the same product area for deeper crawling
      if depth < max_depth:
        same_product_links = []
        other_links = []
        for link in page_data['links']:
          if link not in visited and link not in [item[0] for item in to_visit]:
            link_product = get_product_area(link)
            if link_product == product_area:
              same_product_links.append(link)
            else:
              other_links.append(link)
        
        # Add more links from same product, fewer from others
        for link in same_product_links[:25]:  # Increased from 20
          to_visit.append((link, depth + 1, product_area))
        for link in other_links[:8]:  # Increased from 5
          to_visit.append((link, depth + 1, get_product_area(link)))
      else:
        logger.warning(f"Failed to fetch: {url} - {page_data['content']}")
  
  logger.info(f"Crawling completed! Summary:")
  for product, count in product_page_counts.items():
    logger.info(f"  {product}: {count} pages")
  return all_pages

def get_product_area(url: str) -> str:
  """Determine which product area a URL belongs to"""
  path = urlparse(url).path.lower()
  if '/acquia-source' in path:
    return 'acquia-source'
  elif '/campaign-studio' in path:
    return 'campaign-studio'
  elif '/content-optimization' in path:
    return 'content-optimization'
  elif '/conversion-optimization' in path:
    return 'conversion-optimization'
  elif '/customer-data-platform' in path:
    return 'customer-data-platform'
  elif '/acquia-cloud-platform' in path:
    return 'acquia-cloud-platform'
  elif '/acquia-dam' in path:
    return 'acquia-dam'
  elif '/drupal-starter-kits' in path:
    return 'drupal-starter-kits'
  elif '/site-factory' in path:
    return 'site-factory'
  elif '/web-governance' in path:
    return 'web-governance'
  else:
    return 'general'

def is_memcached_related_query(query: str) -> bool:
  """Detect if a query is related to Memcached configuration"""
  query_lower = query.lower()
  
  # Primary indicators for Memcached queries
  memcache_indicators = [
    'memcache', 'memcached', 'cache', 'caching'
  ]
  
  # Settings.php file indicators
  settings_indicators = [
    'settings.php', 'settings', 'configuration', 'config'
  ]
  
  # Cloud platform indicators
  platform_indicators = [
    'cloud classic', 'cloud platform', 'acquia', 'hosting'
  ]
  
  # Action indicators
  action_indicators = [
    'enable', 'enabling', 'configure', 'setup', 'install', 'add', 'integration'
  ]
  
  # Check for combinations that indicate Memcached configuration
  has_memcache = any(indicator in query_lower for indicator in memcache_indicators)
  has_settings = any(indicator in query_lower for indicator in settings_indicators)
  has_action = any(indicator in query_lower for indicator in action_indicators)
  
  # High confidence: memcache + settings.php
  if has_memcache and has_settings:
    return True
  
  # Medium confidence: memcache + enable/configure
  if has_memcache and has_action:
    return True
  
  # Check for specific phrases that indicate our demo scenario
  demo_phrases = [
    'enable memcached',
    'memcache integration',
    'memcached settings',
    'cache backend',
    'acquia memcache',
    'cloud classic memcache'
  ]
  
  if any(phrase in query_lower for phrase in demo_phrases):
    return True
  
  return False

def get_memcached_doc_data() -> dict:
  """Return pre-loaded Memcached documentation data"""
  return {
    'url': MEMCACHED_DOC_URL,
    'title': 'Enabling Memcached on Cloud Platform',
    'content': MEMCACHED_DOC_CONTENT,
    'links': [],
    'success': True
  }

def calculate_relevance(query: str, page_data: dict) -> int:
  """Calculate relevance score for a page based on query"""
  query_lower   = query.lower()
  query_words   = query_lower.split()
  content_lower = page_data['content'].lower()
  title_lower   = page_data['title'].lower()
  
  # Base scoring
  title_exact_match   = 10 if query_lower in title_lower else 0
  title_word_matches  = sum(1 for word in query_words if word in title_lower) * 5
  content_exact_match = content_lower.count(query_lower) * 2
  content_word_matches = sum(content_lower.count(word) for word in query_words)
  
  base_score = title_exact_match + title_word_matches + content_exact_match + content_word_matches
  
  # Boost score significantly for Memcached-related content when query is Memcached-related
  if is_memcached_related_query(query):
    # Check if this is the Memcached documentation
    if page_data.get('url') == MEMCACHED_DOC_URL or 'memcached' in title_lower:
      base_score += 1000  # Very high boost for exact Memcached docs
    
    # Additional boost for pages containing relevant Memcached keywords
    memcache_keywords = ['memcache', 'settings.php', 'cloud classic', 'require_once', 'composer require']
    memcache_boost = sum(content_lower.count(keyword) * 50 for keyword in memcache_keywords)
    base_score += memcache_boost
  
  return base_score

def extract_snippet(query: str, content: str, max_length: int = 300) -> str:
  """Extract relevant snippet from content based on query"""
  query_words = query.lower().split()
  sentences = content.split('.')
  relevant_sentences = []
  
  for sentence in sentences:
    sentence_lower = sentence.lower()
    if any(word in sentence_lower for word in query_words):
      relevant_sentences.append(sentence.strip())
      if len(relevant_sentences) >= 2:
        break
  
  snippet = '. '.join(relevant_sentences) + '.' if relevant_sentences else ""
  return snippet[:max_length] + "..." if len(snippet) > max_length else snippet

def search_in_pages(query: str, pages: dict) -> list:
  """Search across all crawled pages with improved scoring"""
  results = []
  for url, page_data in pages.items():
    score = calculate_relevance(query, page_data)
    if score > 0:
      results.append({
        'url': url,
        'title': page_data['title'],
        'relevance': score,
        'excerpts': extract_relevant_paragraphs(query, page_data['content'])
      })
  results.sort(key=lambda x: x['relevance'], reverse=True)
  return results[:10]

def extract_relevant_paragraphs(query: str, content: str, max_paragraphs: int = 3) -> list:
  """Extract relevant paragraphs from content based on query"""
  query_words = query.lower().split()
  paragraphs = [p.strip() for p in content.split('\n') if len(p.strip()) > 30]
  relevant_paras = []
  
  for para in paragraphs:
    para_lower = para.lower()
    if any(word in para_lower for word in query_words):
      relevant_paras.append(para)
      if len(relevant_paras) >= max_paragraphs:
        break

  return relevant_paras

# ========== MCP RESOURCES (Auto-exposed to Copilot) ==========
def initialize_memcached_cache():
  """Initialize cache with Memcached documentation for instant access"""
  memcached_data = get_memcached_doc_data()
  add_to_cache(MEMCACHED_DOC_URL, memcached_data)

@app.list_resources()
async def list_resources() -> list[Resource]:
  # Ensure Memcached doc is always available
  if MEMCACHED_DOC_URL not in page_cache:
    initialize_memcached_cache()
  
  resources = []
  for url, page_data in page_cache.items():
    resources.append(
      Resource(
        uri=f"drupal://{url}",
        name=page_data['title'],
        mimeType="text/plain",
        description=f"Documentation: {page_data['title']}"
      )
    )
  return resources

@app.read_resource()
async def read_resource(uri: str) -> str:
  url = uri.replace("drupal://", "")
  
  # Handle Memcached documentation specially
  if url == MEMCACHED_DOC_URL:
    if url not in page_cache:
      initialize_memcached_cache()
    page_data = page_cache[url]
    return f"# {page_data['title']}\n\nSource: {url}\n\n{page_data['content']}"
  
  if url in page_cache:
    page_data = page_cache[url]
    return f"# {page_data['title']}\n\nSource: {url}\n\n{page_data['content']}"
  
  page_data = fetch_page(url)
  if page_data['success']:
    return f"# {page_data['title']}\n\nSource: {url}\n\n{page_data['content']}"
  return f"Content not available for {url}"

# ========== TOOLS (For explicit searches) ==========
@app.list_tools()
async def list_tools() -> list[Tool]:
  """Tools for explicit searches if needed"""
  return [
    Tool(
      name="get_acquia_guidance",
      description="Get intelligent Acquia documentation guidance based on code context and requirements. Automatically detects Memcached, settings.php, and other Acquia configuration needs.",
      inputSchema={
        "type": "object",
        "properties": {
          "context": {"type": "string", "description": "The code context or development scenario"},
          "requirements": {"type": "string", "description": "What you're trying to achieve (e.g., 'enable Memcached', 'configure settings.php')"}
        },
        "required": ["context", "requirements"]
      }
    ),
    Tool(
      name="search_docs",
      description="Directly search Acquia documentation (fast, real-time search)",
      inputSchema={
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "Search query"}
        },
        "required": ["query"]
      }
    ),
    Tool(
      name="crawl_docs",
      description="Dynamically crawl Acquia documentation to discover and cache new pages",
      inputSchema={
        "type": "object",
        "properties": {
          "max_depth": {"type": "integer", "description": "Maximum crawl depth", "default": MAX_CRAWL_DEPTH}
        },
        "required": []
      }
    ),
    Tool(
      name="refresh_docs",
      description="Clear cache (not needed for direct search)",
      inputSchema={
        "type": "object",
        "properties": {},
        "required": []
      }
    ),
    Tool(
      name="list_cached_urls",
      description="Show all currently cached documentation URLs",
      inputSchema={
        "type": "object",
        "properties": {},
        "required": []
      }
    ),
    Tool(
      name="crawl_stats",
      description="Show crawling statistics by product area",
      inputSchema={
        "type": "object",
        "properties": {},
        "required": []
      }
    ),
    Tool(
      name="get_source_link",
      description="Get the official Acquia documentation source link for any topic or query",
      inputSchema={
        "type": "object",
        "properties": {
          "query": {"type": "string", "description": "The topic or query to get the source documentation link for"}
        },
        "required": ["query"]
      }
    )
  ]

def smart_memcached_injection(query: str, results: list) -> list:
  """Intelligently inject Memcached documentation when relevant"""
  if is_memcached_related_query(query):
    memcached_data = get_memcached_doc_data()
    
    # Check if Memcached doc is already in results
    memcached_already_included = any(result.get('url') == MEMCACHED_DOC_URL for result in results)
    
    if not memcached_already_included:
      # Calculate relevance score for Memcached doc
      relevance_score = calculate_relevance(query, memcached_data)
      
      memcached_result = {
        'title': memcached_data['title'],
        'url': memcached_data['url'],
        'snippet': extract_snippet(query, memcached_data['content']),
        'content': memcached_data['content'],
        'relevance': relevance_score
      }
      
      # Insert at the beginning since it's highly relevant for Memcached queries
      results.insert(0, memcached_result)
      logger.info(f"🎯 Auto-injected Memcached documentation for query: '{query}' (score: {relevance_score})")
  
  return results

def direct_search_docs(query: str) -> list:
  """Direct search using fetch_page function with comprehensive URL coverage"""
  try:
    # Comprehensive list of documentation entry points
    doc_urls = MAIN_DOC_URLS + [
      "https://docs.acquia.com/acquia-cloud-platform",
      "https://docs.acquia.com/acquia-dam",
      "https://docs.acquia.com/campaign-studio",
      "https://docs.acquia.com/content-optimization",
      "https://docs.acquia.com/conversion-optimization",
      "https://docs.acquia.com/customer-data-platform",
      "https://docs.acquia.com/acquia-source",
      "https://docs.acquia.com/drupal-starter-kits",
      "https://docs.acquia.com/site-factory",
      "https://docs.acquia.com/web-governance"
    ]
    
    # Use Acquia's own search functionality to discover relevant pages
    search_url = f"https://docs.acquia.com/search/?q={requests.utils.quote(query)}"
    logger.info(f"Attempting to fetch search results from Acquia search: {search_url}")
    
    # Try to extract search results from Acquia's search page
    try:
      headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
      }
      search_response = requests.get(search_url, headers=headers, timeout=10)
      if search_response.status_code == 200:
        search_soup = BeautifulSoup(search_response.text, 'html.parser')
        
        # Extract search result links
        search_result_links = []
        for link in search_soup.find_all('a', href=True):
          href = link['href']
          full_url = urljoin(DRUPAL_BASE_URL, href)
          if is_docs_url(full_url) and full_url not in doc_urls:
            search_result_links.append(full_url)
            if len(search_result_links) >= 20:  # Limit to top 20 search results
              break
        
        if search_result_links:
          logger.info(f"Found {len(search_result_links)} additional URLs from Acquia search")
          doc_urls.extend(search_result_links)
    except Exception as search_error:
      logger.warning(f"Could not fetch from Acquia search page: {search_error}")
    
    results = []
    logger.info(f"Searching for '{query}' in {len(doc_urls)} documentation pages...")
    
    # First pass: search known URLs
    for url in doc_urls:
      logger.debug(f"Checking: {url}")
      page_data = fetch_page(url)
      
      if page_data['success']:
        score = calculate_relevance(query, page_data)
        if score > 0:
          results.append({
            'title': page_data['title'],
            'url': url,
            'snippet': extract_snippet(query, page_data['content']),
            'content': page_data['content'],
            'relevance': score
          })
          logger.info(f"Found relevant content in: {page_data['title']} (score: {score})")
            
          # Second pass: check linked pages from high-scoring results
          if score > 50 and page_data.get('links'):
            logger.info(f"Exploring {len(page_data['links'])} linked pages from high-scoring result...")
            for linked_url in page_data['links'][:20]:  # Increased to check more links
              if linked_url not in doc_urls:  # Avoid duplicates
                linked_page = fetch_page(linked_url)
                if linked_page['success']:
                  linked_score = calculate_relevance(query, linked_page)
                  if linked_score > 0:
                    results.append({
                      'title': linked_page['title'],
                      'url': linked_url,
                      'snippet': extract_snippet(query, linked_page['content']),
                      'content': linked_page['content'],
                      'relevance': linked_score
                    })
        # Even for low-scoring or non-matching pages, explore their links if they're product overview pages
        elif page_data['success'] and page_data.get('links') and any(product in url for product in ['overview', 'web-governance']):
          logger.info(f"Exploring links from overview page: {page_data['title']}")
          for linked_url in page_data['links'][:30]:  # Check more links from overview pages
            if linked_url not in [r.get('url') for r in results]:  # Avoid duplicates
              linked_page = fetch_page(linked_url)
              if linked_page['success']:
                linked_score = calculate_relevance(query, linked_page)
                if linked_score > 0:
                  results.append({
                    'title': linked_page['title'],
                    'url': linked_url,
                    'snippet': extract_snippet(query, linked_page['content']),
                    'content': linked_page['content'],
                    'relevance': linked_score
                  })
      else:
        logger.warning(f"Failed to fetch: {url} - {page_data['content']}")
    
    results.sort(key=lambda x: x['relevance'], reverse=True)
    
    # Apply smart Memcached injection
    results = smart_memcached_injection(query, results)
    
    if not results:
      return [{
        'title': f'No results found for "{query}"',
        'url': f'https://docs.acquia.com/search/?q={requests.utils.quote(query)}',
        'snippet': f'No matching content found in the documentation for "{query}". Try the manual search link or use different keywords.',
        'content': '',
        'relevance': 0
      }]
    return results[:10]
  except Exception as e:
    logger.error(f"Error in direct search: {str(e)}")
    return [{
      'title': f'Search Error for "{query}"',
      'url': f'https://docs.acquia.com/search/?q={requests.utils.quote(query)}',
      'snippet': f'Search encountered an error: {str(e)}. You can try the search manually at the provided URL.',
      'content': '',
      'relevance': 0
    }]

@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
  """Handle tool calls"""
  if name == "get_acquia_guidance":
    context = arguments["context"]
    requirements = arguments["requirements"]
    
    # Combine context and requirements into a comprehensive query
    combined_query = f"{context} {requirements}"
    
    logger.info(f"🎯 Intelligent guidance request - Context: '{context}', Requirements: '{requirements}'")
    
    # Use the enhanced search with auto-injection
    results = direct_search_docs(combined_query)
    
    if not results:
      return [TextContent(
          type="text",
          text=f"No specific guidance found for your requirements. Try rephrasing or check the Acquia documentation manually."
      )]
    
    # Format the response with intelligent context
    output = f"🎯 **Acquia Guidance for: {requirements}**\n\n"
    output += f"📋 **Context Analysis:** {context}\n\n"
    
    # Check if this is a Memcached-related request
    if is_memcached_related_query(combined_query):
      output += "🚀 **Detected: Memcached Configuration Request**\n\n"
      output += "**Quick Solution for Cloud Classic Memcached Integration:**\n\n"
      # Extract the most relevant code snippet for settings.php
      memcached_data = get_memcached_doc_data()
      output += f"📖 **Source Documentation:** {MEMCACHED_DOC_URL}\n\n"
      
      if 'require_once' in memcached_data['content']:
        code_start = memcached_data['content'].find('```php')
        code_end = memcached_data['content'].find('```', code_start + 6)
        if code_start != -1 and code_end != -1:
          code_snippet = memcached_data['content'][code_start:code_end + 3]
          output += f"{code_snippet}\n\n"
    output += f"📚 **Found {len(results)} relevant documentation sources:**\n\n"
    
    for i, result in enumerate(results, 1):
      output += f"{i}. **{result['title']}**\n"
      output += f"   🔗 **Source:** {result['url']}\n"
      if result['snippet']:
        output += f"   📝 **Key Info:** {result['snippet']}\n"
      
      # For Memcached results, include step-by-step instructions
      if 'memcached' in result['title'].lower() or result['url'] == MEMCACHED_DOC_URL:
        output += f"\n   🔧 **Implementation Steps:**\n"
        output += f"   1. Install memcache module: `composer require drupal/memcache`\n"
        output += f"   2. Add memcache settings: `composer require acquia/memcache-settings`\n"
        output += f"   3. Update settings.php with the require_once statement shown above\n"
        output += f"   4. Clear caches: `drush cr`\n"
        output += f"   📖 **Complete Documentation:** {result['url']}\n"

      output += "\n" + "="*50 + "\n"
    return [TextContent(type="text", text=output)]
      
  elif name == "search_docs":
    query = arguments["query"]
    logger.info(f"Searching directly for: {query}")
    results = direct_search_docs(query)
    if not results:
      return [TextContent(
          type="text",
          text=f"No results found for '{query}'. The search service might be unavailable or try different keywords."
      )]
    output = f"🔍 Found {len(results)} results for '{query}':\n\n"
    for i, result in enumerate(results, 1):
      output += f"{i}. **{result['title']}**\n"
      output += f"   🔗 **Source:** {result['url']}\n"
      if result['snippet']:
          output += f"   📝 **Summary:** {result['snippet']}\n"
      if result['content']:
        query_words = query.lower().split()
        paragraphs = [p.strip() for p in result['content'].split('\n') if len(p.strip()) > 50]
        relevant_paras = []
        for para in paragraphs:
          para_lower = para.lower()
          if any(word in para_lower for word in query_words):
            relevant_paras.append(para)
            if len(relevant_paras) >= 2:
              break
        if relevant_paras:
          output += f"\n   📄 **Key Content:**\n"
          for excerpt in relevant_paras:
            truncated = excerpt[:400] + "..." if len(excerpt) > 400 else excerpt
            output += f"   • {truncated}\n"
      output += f"\n   📖 **Complete Documentation:** {result['url']}\n"
      output += "\n" + "="*60 + "\n"
    return [TextContent(type="text", text=output)]
  elif name == "crawl_docs":
    max_depth = arguments.get("max_depth", MAX_CRAWL_DEPTH)
    logger.info(f"Starting dynamic crawl with max_depth={max_depth}...")
    crawled_pages = crawl_docs(max_depth=max_depth)
    added_count = 0
    for url, page_data in crawled_pages.items():
      if url not in page_cache and len(page_cache) < CACHE_SIZE:
        page_cache[url] = page_data
        added_count += 1
    summary = f"✅ Crawled {len(crawled_pages)} pages. Added {added_count} new pages to cache. Cache now has {len(page_cache)} pages."
    return [TextContent(type="text", text=summary)]
  elif name == "refresh_docs":
    page_cache.clear()
    url_to_cache_key.clear()
    discovered_urls.clear()
    return [TextContent(
      type="text",
      text="✅ Cache cleared! Using direct search - no pre-crawling needed."
    )]
  elif name == "list_cached_urls":
    if not page_cache:
      return [TextContent(
        type="text",
        text="No cached pages. Run refresh_docs or crawl_docs first."
      )]
    output = f"📚 **Cached Documentation Pages ({len(page_cache)} total):**\n\n"
    for i, (url, page_data) in enumerate(page_cache.items(), 1):
      output += f"{i}. **{page_data['title']}**\n"
      output += f"   🔗 {url}\n"
      content_preview = page_data['content'][:100].replace('\n', ' ')
      output += f"   📄 {content_preview}...\n\n"
    return [TextContent(type="text", text=output)]
  elif name == "crawl_stats":
    if not page_cache:
      return [TextContent(
        type="text",
        text="No cached pages. Run refresh_docs or crawl_docs first."
      )]
    product_stats = {}
    for url, page_data in page_cache.items():
      product = get_product_area(url)
      if product not in product_stats:
        product_stats[product] = []
      product_stats[product].append({
        'url': url,
        'title': page_data['title']
      })
    output = f"📊 **Crawling Statistics ({len(page_cache)} total pages):**\n\n"
    for product, pages in sorted(product_stats.items()):
      output += f"**{product.title().replace('-', ' ')}** ({len(pages)} pages):\n"
      for page in pages[:5]:
          output += f"  • {page['title']}\n    {page['url']}\n"
      if len(pages) > 5:
          output += f"  ... and {len(pages) - 5} more pages\n"
      output += "\n"
    return [TextContent(type="text", text=output)]
  elif name == "get_source_link":
    query = arguments["query"]
    source_url = get_source_links_for_query(query)
    
    output = f"🔗 **Official Acquia Documentation Source:**\n\n"
    output += f"**Query:** {query}\n"
    output += f"**Source Link:** {source_url}\n\n"
    
    # If it's a Memcached-related query, provide additional context
    if is_memcached_related_query(query):
      output += f"**Topic:** Memcached Integration for Cloud Classic\n"
      output += f"**Documentation Title:** Enabling Memcached on Cloud Platform\n"
      output += f"**Direct Link:** {MEMCACHED_DOC_URL}\n\n"
      output += "This documentation contains the official Acquia guidance for:\n"
      output += "• Installing the Memcache module via Composer\n"
      output += "• Adding acquia/memcache-settings package\n"
      output += "• Configuring settings.php with the proper require_once statement\n"
      output += "• Cloud Classic vs Cloud Next differences\n"
    
    return [TextContent(type="text", text=output)]
  raise ValueError(f"Unknown tool: {name}")

async def main():
  """Run the MCP server"""
  # Initialize Memcached documentation for instant access
  initialize_memcached_cache()
  
  logger.info("🚀 Acquia Docs MCP server started! Using direct search - ready for instant documentation queries.")
  logger.info("🔌 Connect to this MCP server at: stdio://drupal-docs")
  
  async with stdio_server() as (read_stream, write_stream):
    await app.run(
      read_stream,
      write_stream,
      app.create_initialization_options()
    )

if __name__ == "__main__":
  asyncio.run(main())