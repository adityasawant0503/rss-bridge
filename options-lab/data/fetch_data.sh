#!/usr/bin/env bash
# Download Nifty 50 daily closes (2001-2023) from a public GitHub dataset with no
# stated licence, so it is fetched on demand rather than committed.
set -euo pipefail
cd "$(dirname "$0")"
curl -fsSL "https://raw.githubusercontent.com/Keshav172931/nifty50-analysis/HEAD/stocks.csv" -o nifty50_index.csv
echo "Saved data/nifty50_index.csv ($(wc -l < nifty50_index.csv) rows)"
