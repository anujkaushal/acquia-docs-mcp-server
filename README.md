# Acquia Docs MCP Server

A Model Context Protocol (MCP) server that provides intelligent access to Acquia's documentation. This server crawls, caches, and searches Acquia's documentation to provide developers with instant access to configuration guidance, best practices, and implementation details for all Acquia products.

## Features

### 🚀 Intelligent Documentation Search
- **Real-time search** across Acquia's complete documentation
- **Smart relevance scoring** with context-aware results
- **Auto-detection** of Memcached, settings.php, and configuration queries
- **Pre-loaded documentation** for instant access to critical content

### 📚 Comprehensive Coverage
- **Acquia Cloud Platform** - Hosting and infrastructure
- **Campaign Studio** - Marketing automation
- **Content Optimization** - Content management and optimization
- **Customer Data Platform** - Data analytics and insights
- **Acquia DAM** - Digital asset management
- **Site Factory** - Multi-site management
- **Web Governance** - Compliance and governance tools
- **Drupal Starter Kits** - Project templates and tools

### 🔧 Developer-Focused Tools
- **Intelligent guidance** with code context analysis
- **Configuration detection** for common Acquia setups
- **Source link resolution** for official documentation
- **Dynamic crawling** for discovering new content
- **Caching system** for improved performance

## Installation

### Prerequisites
- Python 3.8 or higher
- Virtual environment (recommended)

### Quick Setup

1. **Clone the repository:**
   ```bash
   git clone https://github.com/anujkaushal/acquia-docs-mcp-server.git
   cd acquia-docs-mcp-server
   ```

2. **Create and activate virtual environment:**
   ```bash
   python3 -m venv venv
   source venv/bin/activate  # On Windows: venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Run the server:**
   ```bash
   python3 main.py
   ```

   Or use the provided script:
   ```bash
   chmod +x run.sh
   ./run.sh
   ```

## Usage

### As an MCP Server

This server implements the Model Context Protocol and can be connected to any MCP-compatible client (like Claude Desktop, VS Code extensions, or custom applications).

**Connection URI:** `stdio://drupal-docs`

### Available Tools

#### 🎯 `get_acquia_guidance`
Get intelligent guidance based on your code context and requirements.

```json
{
  "context": "Working on Drupal site settings.php configuration",
  "requirements": "Enable Memcached for Cloud Classic environment"
}
```

#### 🔍 `search_docs`
Direct search across Acquia documentation with real-time results.

```json
{
  "query": "memcached configuration cloud classic"
}
```

#### 🕷️ `crawl_docs`
Dynamically crawl and discover new documentation pages.

```json
{
  "max_depth": 5
}
```

#### 🔗 `get_source_link`
Get official documentation source links for any topic.

```json
{
  "query": "memcached settings.php"
}
```

#### 📊 `crawl_stats`
View crawling statistics and coverage by product area.

#### 📋 `list_cached_urls`
List all currently cached documentation URLs.

#### 🔄 `refresh_docs`
Clear the cache for fresh crawling.

### Resources

The server automatically exposes cached documentation pages as MCP resources with URIs like:
- `drupal://https://docs.acquia.com/acquia-cloud-platform/overview`
- `drupal://https://docs.acquia.com/campaign-studio/getting-started`

## Configuration

### Core Settings

Edit the configuration section in `main.py`:

```python
# ========== CONFIGURATION - ONLY UPDATE THESE ==========
DRUPAL_BASE_URL   = "https://docs.acquia.com/"
MAX_CRAWL_DEPTH   = 5     # Maximum crawling depth
CACHE_SIZE        = 1000  # Number of pages to cache
REQUEST_DELAY     = 0.5   # Rate limiting delay (seconds)
MAX_PAGES_PER_PRODUCT = 75  # Per-product page limit
```

### Product Documentation URLs

The server covers these main product areas:
- Acquia Source
- Campaign Studio  
- Content Optimization
- Conversion Optimization
- Customer Data Platform
- Acquia Cloud Platform
- Acquia DAM
- Drupal Starter Kits
- Site Factory
- Web Governance

## Special Features

### 🧠 Memcached Intelligence
The server includes special handling for Memcached configuration queries:
- **Auto-detection** of Memcached-related questions
- **Pre-loaded content** for instant responses
- **Step-by-step guidance** for Cloud Classic configuration
- **Code snippets** for settings.php integration

### 📊 Smart Caching
- **FIFO cache eviction** to manage memory usage
- **Relevance-based scoring** for search results  
- **Dynamic discovery** of linked documentation
- **Product-aware crawling** for comprehensive coverage

### 🔍 Advanced Search
- **Multi-keyword matching** with relevance scoring
- **Content excerpt extraction** for quick insights
- **Cross-product link following** for comprehensive results
- **Fallback to Acquia's search** when needed

## API Reference

### MCP Resources
- **List Resources:** Returns all cached documentation pages
- **Read Resource:** Retrieves full content for a specific documentation page

### MCP Tools
All tools return structured responses with:
- Relevance scoring
- Source URLs
- Content excerpts
- Implementation guidance

## Development

### Project Structure
```
acquia-docs-mcp-server/
├── main.py              # Main server implementation
├── requirements.txt     # Python dependencies
├── run.sh              # Setup and run script
├── README.md           # This file
└── path/to/            # Virtual environment directory
```

### Key Components
- **Web Crawler:** BeautifulSoup-based documentation scraper
- **Cache Manager:** In-memory caching with FIFO eviction
- **Search Engine:** Multi-criteria relevance scoring
- **MCP Interface:** Standard MCP server implementation

### Contributing
1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Add tests if applicable
5. Submit a pull request

## Troubleshooting

### Common Issues

**Connection Issues:**
- Ensure Python 3.8+ is installed
- Check that all dependencies are installed
- Verify network connectivity to docs.acquia.com

**Performance Issues:**
- Adjust `CACHE_SIZE` for your memory constraints
- Increase `REQUEST_DELAY` if rate limiting occurs
- Reduce `MAX_CRAWL_DEPTH` for faster initial crawling

**Search Issues:**
- Try different keywords or phrases
- Use the `crawl_docs` tool to discover new content
- Check `crawl_stats` to see coverage by product area

### Logging
The server provides detailed logging for debugging:
```python
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
```

Set level to `DEBUG` for more verbose output.

## License

This project is open source. Please check the repository for license details.

## Support

For issues, questions, or contributions:
- **GitHub Issues:** [Report bugs or request features](https://github.com/anujkaushal/acquia-docs-mcp-server/issues)
- **Documentation:** [Acquia Documentation](https://docs.acquia.com/)
- **MCP Specification:** [Model Context Protocol](https://modelcontextprotocol.io/)

---

**Built for developers, by developers.** This MCP server makes Acquia's extensive documentation instantly accessible through intelligent search and contextual guidance.

## Question / Answers

**How does this help Acquia Cloud developers?**

Building Drupal sites is made easy by leveraging the comprehensive documentation available at docs.acquia.com. Acquia Docs contains extensive documentation that can significantly assist developers throughout their development process. This MCP server brings Acquia Docs directly into your coding environment, providing seamless access to relevant documentation without leaving your development workflow.


**Quick Start Guide**

1. Connect your MCP-compatible client (like VS Code) using:

Create `.vscode/mcp.json`

```json
{
  "mcp": {
    "server": "stdio://drupal-docs"
  }
}
```

2. Start searching Acquia documentation directly from your editor
3. Get instant access to configuration guides and best practices

That's it! The server handles everything else automatically.






