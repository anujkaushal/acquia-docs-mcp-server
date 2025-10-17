#!/bin/bash

python3 -m venv path/to/venv
source path/to/venv/bin/activate
python3 -m pip install -r requirements.txt

python3 main.py
