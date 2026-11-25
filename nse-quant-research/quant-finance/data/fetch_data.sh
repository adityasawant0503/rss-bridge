#!/usr/bin/env bash
# Download the public datasets used for the results in README.md.
# They are third-party GitHub repositories with no stated licence, so they are
# fetched on demand rather than committed. Run from the project root.
set -euo pipefail
cd "$(dirname "$0")"
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT

# Nifty 50 index, daily close, 2001-2023
curl -fsSL "https://raw.githubusercontent.com/Keshav172931/nifty50-analysis/HEAD/stocks.csv" -o nifty50_index.csv

# 50 Nifty 50 constituents, daily OHLCV, Oct 2020 - Sep 2025
git clone -q --depth 1 https://github.com/Kaldhen-Lepcha/historical-data "$tmp/stocks"
rm -rf nifty50_stocks && mkdir nifty50_stocks
cp "$tmp"/stocks/Assignment-2/*.csv nifty50_stocks/
echo "Saved data/nifty50_index.csv and $(ls nifty50_stocks | wc -l) files in data/nifty50_stocks/"
