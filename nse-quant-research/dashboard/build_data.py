"""Export results from quant-finance/ and options-lab/ for the dashboard.

Writes data/nifty.json (daily closes the browser recomputes on) and
data/results.json (precomputed studies + Python reference values that
test_lib.mjs checks the JavaScript port against).

Usage (from the repo root, after both projects' data/fetch_data.sh):
  python dashboard/build_data.py
"""
import itertools
import json
import os
import sys

import numpy as np
import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "quant-finance"), os.path.join(ROOT, "options-lab"),
                os.path.join(ROOT, "options-lab", "scripts")]

from nifty_hedge_backtest import backtest as hedge_backtest  # noqa: E402
from optlab import binomial, bs  # noqa: E402
from quantlab.costs import INDIA_CHARGES, cost_per_side, india_cost  # noqa: E402
from quantlab.data import load_csv, load_csv_dir  # noqa: E402
from quantlab.pairs import CRIT_5, SECTORS, eg  # noqa: E402
from quantlab.pairs import backtest as pairs_bt  # noqa: E402
from quantlab.risk import simulate, var_backtest, var_es  # noqa: E402
from quantlab.stats import ols, perf_stats  # noqa: E402
from quantlab.trend import FAST, SLOW, run_rule  # noqa: E402

QF = os.path.join(ROOT, "quant-finance", "data")
OUT = os.path.join(ROOT, "dashboard", "data")
RF, DIV = 0.06, 0.013
r4 = lambda x: None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), 4)


def main():
    os.makedirs(OUT, exist_ok=True)
    nifty = load_csv(os.path.join(QF, "nifty50_index.csv"))
    stocks = load_csv_dir(os.path.join(QF, "nifty50_stocks"))
    json.dump({"source": "Nifty 50 index daily close, public GitHub dataset (see README)",
               "dates": [d.strftime("%Y-%m-%d") for d in nifty.index],
               "close": [round(float(x), 2) for x in nifty.values]},
              open(os.path.join(OUT, "nifty.json"), "w"), separators=(",", ":"))

    res = {}
    # ---- risk: VaR backtest on Nifty, all four methods
    logret = np.log(nifty).diff().dropna()
    df, methods = var_backtest(logret.values[:, None], np.array([1.0]))
    dates = logret.index[df.i.astype(int)]
    res["var_backtest"] = {
        "dates": [d.strftime("%Y-%m-%d") for d in dates],
        "actual": [r4(x) for x in df.actual],
        "var99": {m: [r4(x) for x in df[(m, 99)]] for m in methods},
        "var95": {m: [r4(x) for x in df[(m, 95)]] for m in methods},
    }
    tick = ["RELIANCE", "HDFCBANK", "TCS", "INFY", "ITC"]
    r = np.log(stocks[tick]).diff().dropna()
    mu, vol, corr = r.mean().values, r.std().values, r.corr().values
    rng, k = np.random.default_rng(0), 5
    scen = []
    for label, c in [("Estimated", corr), ("Zero", np.eye(k)), ("Perfect", np.full((k, k), 0.999) + np.eye(k) * 0.001)]:
        v, e = var_es(simulate(mu, np.outer(vol, vol) * c, np.full(5, 0.2), 10_000, 21, rng) * 1e7, 0.95)
        scen.append({"label": label, "var_lakh": r4(v / 1e5), "es_lakh": r4(e / 1e5)})
    res["var_correlation"] = {"tickers": tick, "corr": [[r4(x) for x in row] for row in corr], "scenarios": scen}

    # ---- trend: Sharpe grid and walk-forward
    ret = nifty.pct_change().fillna(0) + DIV / 252
    buy, sell = cost_per_side("in", "etf")
    cash = (1 + RF) ** (1 / 252) - 1
    grid = {}
    for kind in ("SMA", "EMA"):
        rows = []
        for f, s in itertools.product(FAST, SLOW):
            if f < s:
                rr = run_rule(nifty, ret, f, s, kind, buy, sell, cash, 250)[0]
                st, oos = perf_stats(rr, RF), perf_stats(rr["2013":], RF)
                rows.append({"fast": f, "slow": s, "sharpe": r4(st["Sharpe"]), "cagr": r4(st["CAGR"]),
                             "maxdd": r4(st["MaxDD"]), "oos_cagr": r4(oos["CAGR"]), "oos_maxdd": r4(oos["MaxDD"])})
        grid[kind] = rows
    bh = perf_stats(ret.iloc[250:], RF)
    res["ma_grid"] = {"fast": FAST, "slow": SLOW, "grid": grid,
                      "buy_hold": {k: r4(v) for k, v in bh.items()},
                      "buy_hold_oos": {k: r4(v) for k, v in perf_stats(ret.iloc[250:]["2013":], RF).items()},
                      "costs_bps": [r4(buy * 1e4), r4(sell * 1e4)]}

    # ---- pairs scan
    fb, fs = cost_per_side("in", "futures")
    form, trade = stocks[:"2023-10-01"], stocks["2023-10-01":]
    seen, rows = set(), []
    for sector, names in SECTORS.items():
        for x, y in itertools.combinations([n for n in names if n in stocks], 2):
            if frozenset((x, y)) in seen:
                continue
            seen.add(frozenset((x, y)))
            (s1, _), (s2, _) = eg(form[x], form[y]), eg(form[y], form[x])
            a, b = (x, y) if s1 <= s2 else (y, x)
            coef, _, _ = ols(form[a].values, form[b].values)
            rr, pos, _ = pairs_bt(pd.concat([form[[a, b]], trade[[a, b]]]), coef[1], coef[0], fb, fs)
            rows.append({"pair": f"{a}/{b}", "sector": sector, "adf_form": r4(min(s1, s2)),
                         "coint": bool(min(s1, s2) < CRIT_5), "adf_trade": r4(eg(trade[a], trade[b])[0]),
                         "ret_form": r4(rr[:"2023-10-01"].mean() * 252),
                         "ret_trade": r4(rr["2023-10-01":].mean() * 252),
                         "trades": int((pos["2023-10-01":].diff().abs() > 0).sum())})
    res["pairs"] = rows

    # ---- costs table
    res["costs"] = [{"instrument": i, "buy_bps": r4(india_cost(i, "buy") * 1e4),
                     "sell_bps": r4(india_cost(i, "sell") * 1e4)} for i in INDIA_CHARGES]

    # ---- Python reference values for the JS port (checked by test_lib.mjs)
    hb = {f"{mk:.2f}": hedge_backtest(nifty, mk) for mk in (0.0, 0.02)}
    sma = run_rule(nifty, ret, 50, 200, "SMA", buy, sell, cash, 250)[0]
    ema = run_rule(nifty, ret, 20, 50, "EMA", buy, sell, cash, 250)[0]
    res["reference"] = {
        "bs_call": bs.price(100, 100, 1, 0.05, 0.2), "bs_put": bs.price(100, 100, 1, 0.05, 0.2, "put"),
        "greeks_call": bs.greeks(100, 100, 1, 0.05, 0.2, "call", 0.013),
        "binomial_american_put": binomial.price(100, 100, 1, 0.05, 0.2, "put", american=True, steps=500),
        "hedge": {k: {"n": len(v), "mean": float(v.pnl.mean()), "std": float(v.pnl.std()),
                      "min": float(v.pnl.min())} for k, v in hb.items()},
        "ma_sma_50_200": {k: float(v) for k, v in perf_stats(sma, RF).items()},
        "ma_ema_20_50": {k: float(v) for k, v in perf_stats(ema, RF).items()},
    }
    json.dump(res, open(os.path.join(OUT, "results.json"), "w"), separators=(",", ":"))
    for f in ("nifty.json", "results.json"):
        print(f, os.path.getsize(os.path.join(OUT, f)) // 1024, "KB")


if __name__ == "__main__":
    main()
