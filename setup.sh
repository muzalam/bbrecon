#!/bin/bash
set -e
cd "$(dirname "$0")"
python3 -m pip install -r requirements.txt 2>/dev/null || true
python3 bbrecon.py init
echo "Setup complete. Run: python3 bbrecon.py scan --dry-run"
