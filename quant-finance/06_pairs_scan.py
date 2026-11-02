"""Project 2b - Scan for pairs, then see if the "cointegrated" ones survive.

1. Formation period: Engle-Granger test every same-sector pair (both
   orderings, keep the stronger). Testing all ~1,000 cross-sector pairs
   would produce ~50 false positives at 5% by luck alone.
2. Trading period: trade the selected pairs with the hedge ratio frozen
   from formation (exactly as 02_pairs_trading.py), stock-futures costs.
3. Re-test cointegration in the trading period - did it hold?

Usage:
  python 06_pairs_scan.py --dir prices/ --split 2023-10-01
"""
import argparse
import importlib.util
import itertools

import numpy as np
import pandas as pd

from common import adf_stat, load_csv_dir, ols
from markets import MARKETS, cost_per_side

spec = importlib.util.spec_from_file_location("pairs", __file__.replace("06_pairs_scan", "02_pairs_trading"))
pairs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pairs)

SECTORS = {
    "Private banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Banks (incl. PSU)": ["SBIN", "ICICIBANK", "HDFCBANK", "AXISBANK"],
    "IT services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "Autos": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM"],
    "NBFC / insurance": ["BAJFINANCE", "BAJAJFINSV", "SHRIRAMFIN", "HDFCLIFE", "SBILIFE"],
    "Power / PSU energy": ["NTPC", "POWERGRID", "COALINDIA", "ONGC"],
    "Cement / materials": ["ULTRACEMCO", "GRASIM", "ASIANPAINT"],
}
CRIT_5 = -3.34


def eg(a, b):
    coef, resid, _ = ols(np.log(a.values), np.log(b.values))   # log prices
    return adf_stat(resid), coef


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--split", default="2023-10-01")
    ap.add_argument("--market", choices=MARKETS, default="in")
    args = ap.parse_args()
    m = MARKETS[args.market]
    buy, sell = cost_per_side(args.market, m["pair_instrument"])
    px = load_csv_dir(args.dir)
    form, trade = px[:args.split], px[args.split:]
    print(f"Formation {form.index[0].date()} -> {form.index[-1].date()} ({len(form)} d), "
          f"trading {trade.index[0].date()} -> {trade.index[-1].date()} ({len(trade)} d)")
    print(f"Costs per leg: buy {buy*1e4:.1f} / sell {sell*1e4:.1f} bps (stock futures)\n")

    seen, rows = set(), []
    for sector, names in SECTORS.items():
        names = [n for n in names if n in px]
        for x, y in itertools.combinations(names, 2):
            if frozenset((x, y)) in seen:
                continue
            seen.add(frozenset((x, y)))
            (s1, _), (s2, _) = eg(form[x], form[y]), eg(form[y], form[x])
            a, b = (x, y) if s1 <= s2 else (y, x)
            stat = min(s1, s2)
            # trade on price levels exactly like 02_pairs_trading.py
            coef, _, _ = ols(form[a].values, form[b].values)
            r, pos, cost = pairs.backtest(pd.concat([form[[a, b]], trade[[a, b]]]),
                                          coef[1], coef[0], buy, sell)
            r_in, r_out = r[:args.split], r[args.split:]
            ann = lambda q: q.mean() * 252
            oos_stat, _ = eg(trade[a], trade[b])
            rows.append(dict(pair=f"{a}/{b}", sector=sector, form_adf=stat,
                             coint=stat < CRIT_5, ret_in=ann(r_in), ret_out=ann(r_out),
                             sharpe_out=(ann(r_out) - m["risk_free"]) / (r_out.std() * np.sqrt(252)),
                             trades_out=int((pos[args.split:].diff().abs() > 0).sum()),
                             oos_adf=oos_stat, still=oos_stat < CRIT_5))
    res = pd.DataFrame(rows).sort_values("form_adf")
    pct = "{:.1%}".format
    print(res.to_string(index=False, formatters={
        "form_adf": "{:.2f}".format, "oos_adf": "{:.2f}".format, "ret_in": pct,
        "ret_out": pct, "sharpe_out": "{:.2f}".format}))

    sel = res[res.coint]
    print(f"\nPairs tested: {len(res)}; cointegrated in formation at 5%: {len(sel)} "
          f"(~{0.05*len(res):.1f} expected by chance alone)")
    if len(sel):
        print(f"  ...still cointegrated in trading period: {sel.still.sum()}/{len(sel)}")
        print(f"  avg return in formation (in-sample) {sel.ret_in.mean():.1%}, "
              f"in trading period {sel.ret_out.mean():.1%}; profitable out of sample: "
              f"{(sel.ret_out > 0).sum()}/{len(sel)}; beat risk-free: "
              f"{(sel.ret_out > m['risk_free']).sum()}/{len(sel)}")
    rest = res[~res.coint]
    print(f"  non-cointegrated pairs, avg trading-period return: {rest.ret_out.mean():.1%}")


if __name__ == "__main__":
    main()
