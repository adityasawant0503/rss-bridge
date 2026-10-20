#!/usr/bin/env python3
"""Build pulsedge/data/universe.json from NSE's index constituents CSV.

Download the Nifty 500 list from niftyindices.com (file ind_nifty500list.csv,
columns: Company Name, Industry, Symbol, Series, ISIN Code), then run:

  python pulsedge-bot/universe_from_nse.py ind_nifty500list.csv
"""
import csv
import json
import os
import sys

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "pulsedge", "data", "universe.json")

if len(sys.argv) != 2:
    sys.exit(__doc__)
with open(sys.argv[1], newline="", encoding="utf-8-sig") as fh:
    rows = list(csv.DictReader(fh))
stocks = [
    {"symbol": r["Symbol"].strip().upper(), "name": r["Company Name"].strip(), "sector": r["Industry"].strip()}
    for r in rows if r.get("Symbol")
]
if not stocks:
    sys.exit("No rows with a Symbol column found. Is this NSE's constituents CSV?")
with open(OUT, "w", encoding="utf-8") as fh:
    json.dump({"name": "NIFTY 500", "stocks": stocks}, fh, indent=1, ensure_ascii=False)
print(f"wrote {len(stocks)} stocks to {os.path.relpath(OUT)}")
