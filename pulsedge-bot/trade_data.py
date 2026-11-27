"""Build the price files PulsEdge Trade reads in demo (paper-trading) mode.

Writes pulsedge/data/trade/:
  symbols.json        watchlist universe (index, VIX, Nifty 50 stocks) with names and sectors
  NIFTY.json, INDIAVIX.json, stocks/<SYMBOL>.json   daily OHLC(V) as compact arrays
  vrp.json            India volatility-premium study (from nse-quant-research)

Sources are public datasets downloaded by nse-quant-research's fetch_data.sh scripts.
Usage:
  python pulsedge-bot/trade_data.py --qf ../nse-quant-research/quant-finance/data \
      --ol ../nse-quant-research/options-lab/data --vrp ../nse-quant-research/options-lab/results/vrp_results.json
"""
import argparse
import glob
import json
import os

import pandas as pd

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "pulsedge", "data", "trade")


def pack(df, cols=("open", "high", "low", "close")):
    """Daily bars as column arrays; dates as YYYYMMDD integers to keep files small."""
    out = {"d": [int(d.strftime("%Y%m%d")) for d in df.index]}
    for c in cols:
        if c in df:
            out[c[0]] = [round(float(x), 2) for x in df[c]]
    return out


def stats(close):
    """Last close and annualised volatility of the last 60 sessions (seeds the demo prices)."""
    import numpy as np
    lr = np.log(close).diff().dropna().tail(60)
    return {"close": round(float(close.iloc[-1]), 2), "vol": round(float(lr.std() * np.sqrt(252)), 4),
            "asof": str(close.index[-1].date())}


def write(name, obj):
    path = os.path.join(OUT, name)
    with open(path, "w") as f:
        json.dump(obj, f, separators=(",", ":"))
    return os.path.getsize(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--qf", required=True, help="quant-finance/data folder")
    ap.add_argument("--ol", required=True, help="options-lab/data folder")
    ap.add_argument("--vrp", required=True, help="options-lab/results/vrp_results.json")
    a = ap.parse_args()
    os.makedirs(os.path.join(OUT, "stocks"), exist_ok=True)

    # Nifty 50: 2001-2023 file, then the 2015-2025 Yahoo export for later days
    n1 = pd.read_csv(os.path.join(a.ol, "nifty50_index.csv"))
    n1.index = pd.to_datetime(n1["Date"])
    n1 = n1.rename(columns=str.lower)[["open", "high", "low", "close"]]
    n2 = pd.read_csv(os.path.join(a.ol, "nifty50_2015_2025.csv"), parse_dates=["Date"]).set_index("Date")
    n2 = n2.rename(columns=str.lower)[["open", "high", "low", "close"]]
    nifty = pd.concat([n1, n2[n2.index > n1.index.max()]]).sort_index()
    nifty = nifty[~nifty.index.duplicated()].dropna()
    nifty = nifty[nifty.index >= "2008-01-01"]
    sizes = {"NIFTY.json": write("NIFTY.json", pack(nifty))}

    # India VIX
    v1 = pd.read_csv(os.path.join(a.ol, "india_vix_2008_2024.csv"), encoding="utf-8-sig")
    v1.index = pd.to_datetime(v1["Date"], format="%m/%d/%Y")
    v1 = v1.rename(columns={"vixOpen": "open", "vixHigh": "high", "vixLow": "low", "vixPrice": "close"})[["open", "high", "low", "close"]]
    v2 = pd.read_csv(os.path.join(a.ol, "india_vix_2015_2025.csv"), parse_dates=["Date"]).set_index("Date")
    v2 = v2.rename(columns=str.lower)[["open", "high", "low", "close"]]
    vix = pd.concat([v1[v1.index < v2.index.min()], v2]).sort_index().astype(float)
    vix = vix[~vix.index.duplicated()].dropna()
    sizes["INDIAVIX.json"] = write("INDIAVIX.json", pack(vix))

    # Nifty 50 stocks, Oct 2020 - Sep 2025
    uni = {s["symbol"]: s for s in json.load(open(os.path.join(OUT, "..", "universe.json")))["stocks"]}
    symbols = [{"sym": "NIFTY", "name": "Nifty 50", "kind": "index", "sector": "Index", "lot": 65, **stats(nifty["close"])},
               {"sym": "INDIAVIX", "name": "India VIX", "kind": "vix", "sector": "Volatility", **stats(vix["close"])}]
    for path in sorted(glob.glob(os.path.join(a.qf, "nifty50_stocks", "*.csv"))):
        sym = os.path.basename(path).split("_")[0]
        df = pd.read_csv(path)
        df.index = pd.to_datetime(df["timestamp"].astype(str).str[:10])
        df = df[["open", "high", "low", "close", "volume"]].dropna()
        df = df[~df.index.duplicated()].sort_index()
        sizes[f"stocks/{sym}.json"] = write(f"stocks/{sym}.json", pack(df, ("open", "high", "low", "close", "volume")))
        u = uni.get(sym, {})
        if len(df) < 120 or df.index.max() < pd.Timestamp("2025-06-01"):
            del sizes[f"stocks/{sym}.json"]
            os.remove(os.path.join(OUT, "stocks", f"{sym}.json"))
            continue                                      # too short or stale to seed demo prices
        symbols.append({"sym": sym, "name": u.get("name", sym), "kind": "stock", "sector": u.get("sector", ""), **stats(df["close"])})
    write("symbols.json", {"updated": str(nifty.index.max().date()), "symbols": symbols,
                           "note": "Demo data: daily prices from public datasets; intraday prices are simulated."})

    # Volatility-premium study, trimmed to what the terminal shows
    r = json.load(open(a.vrp))
    keep = {k: r[k] for k in ("period", "premium", "latest", "vix_history", "picks", "split", "margin_assumption", "curves")}
    keep["strategies"] = [s for s in r["strategies"] if s["filter"] == r["picks"][s["strategy"]] or s["filter"] == "always"]
    sizes["vrp.json"] = write("vrp.json", keep)
    total = sum(sizes.values())
    print(f"wrote {len(sizes)} files, {total / 1024:.0f} KB; Nifty {nifty.index.min().date()}..{nifty.index.max().date()}, "
          f"VIX {vix.index.min().date()}..{vix.index.max().date()}, {len(symbols) - 2} stocks")


if __name__ == "__main__":
    main()
