"""Project 3b - Which moving-average crossover is "best"? SMA vs EMA sweep.

Tests every fast/slow pair (and price-vs-MA) for SMA and EMA, long/flat,
with a one-day signal lag, Indian ETF costs, cash earning the risk-free
rate and an approximate dividend yield added (the NSE price index excludes
dividends). Then checks whether the in-sample winner still wins
out of sample - which is the only question that matters.

Usage:
  python 04_ma_sweep.py --csv nifty.csv          # columns: Date, Close
  python 04_ma_sweep.py --ticker NIFTYBEES.NS    # via yfinance
"""
import argparse
import itertools

import numpy as np
import pandas as pd

from common import load_prices
from markets import MARKETS, cost_per_side

FAST = [1, 5, 10, 20, 30, 50, 100]          # 1 = price itself
SLOW = [20, 50, 100, 150, 200, 250]
PERIODS = [("2001-2007 bull", "2001", "2007"), ("2008-2012 crash/chop", "2008", "2012"),
           ("2013-2019 grind up", "2013", "2019"), ("2020-2023 covid/V", "2020", "2023")]


def ma(px, n, kind):
    if n == 1:
        return px
    return px.rolling(n).mean() if kind == "SMA" else px.ewm(span=n, adjust=False, min_periods=n).mean()


def run(px, ret, fast, slow, kind, buy, sell, cash_d, warmup):
    sig = (ma(px, fast, kind) > ma(px, slow, kind)).astype(float)
    pos = sig.shift(1).fillna(0)
    d = pos.diff().fillna(0)
    cost = d.clip(lower=0) * buy + (-d).clip(lower=0) * sell
    r = pos * ret + (1 - pos) * cash_d - cost
    return r.iloc[warmup:], pos.iloc[warmup:]


def stats(r, rf):
    if len(r) < 60:
        return dict(CAGR=np.nan, Sharpe=np.nan, MaxDD=np.nan)
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (252 / len(r)) - 1
    vol = r.std() * np.sqrt(252)
    return dict(CAGR=cagr, Sharpe=(r.mean() * 252 - rf) / vol, MaxDD=(eq / eq.cummax() - 1).min())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--ticker", default="NIFTYBEES.NS")
    ap.add_argument("--market", choices=MARKETS, default="in")
    ap.add_argument("--instrument", default="etf")
    ap.add_argument("--div-yield", type=float, default=0.013,
                    help="add to returns when using a price index (0 for TRI/ETF)")
    ap.add_argument("--split", default="2013-01-01", help="in-sample / out-of-sample split")
    args = ap.parse_args()
    m = MARKETS[args.market]
    rf = m["risk_free"]
    buy, sell = cost_per_side(args.market, args.instrument)

    if args.csv:
        df = pd.read_csv(args.csv, parse_dates=["Date"]).sort_values("Date").drop_duplicates("Date")
        px = df.set_index("Date")["Close"].astype(float)
    else:
        px = load_prices([args.ticker], start="2001-01-01").iloc[:, 0]
        args.div_yield = 0.0
    ret = px.pct_change().fillna(0) + args.div_yield / 252
    cash_d = (1 + rf) ** (1 / 252) - 1
    warm = max(SLOW)                                   # same start date for every rule

    rows, series = [], {}
    bh = ret.iloc[warm:]
    series["Buy & hold"] = bh
    for kind, f, s in itertools.product(["SMA", "EMA"], FAST, SLOW):
        if f >= s:
            continue
        r, pos = run(px, ret, f, s, kind, buy, sell, cash_d, warm)
        name = f"{kind} {'price' if f == 1 else f}/{s}"
        series[name] = r
        st = stats(r, rf)
        rows.append(dict(rule=name, kind=kind, fast=f, slow=s, **st,
                         trades_yr=(pos.diff().abs() > 0).sum() / (len(r) / 252) / 2,
                         in_mkt=pos.mean()))
    res = pd.DataFrame(rows).set_index("rule")
    b = stats(bh, rf)

    pct = lambda x: f"{x:.1%}"
    fmt = {"CAGR": pct, "MaxDD": pct, "in_mkt": "{:.0%}".format,
           "Sharpe": "{:.2f}".format, "trades_yr": "{:.1f}".format}
    print(f"Data {px.index[0].date()} -> {px.index[-1].date()} ({len(px)} days); "
          f"tested from {px.index[warm].date()}; costs {buy*1e4:.1f}/{sell*1e4:.1f} bps; "
          f"rf {rf:.0%}; div yield added {args.div_yield:.1%}")
    print(f"\nBuy & hold: CAGR {b['CAGR']:.1%}  Sharpe {b['Sharpe']:.2f}  MaxDD {b['MaxDD']:.1%}")
    cols = ["CAGR", "Sharpe", "MaxDD", "trades_yr", "in_mkt"]
    print("\nTop 10 by Sharpe (full period):")
    print(res.sort_values("Sharpe", ascending=False)[cols].head(10).to_string(formatters=fmt))
    print("\nClassic rules:")
    classic = [r for r in ["SMA 50/200", "EMA 50/200", "SMA 20/50", "EMA 20/50",
                           "SMA price/200", "EMA price/200", "SMA price/50", "EMA price/50"] if r in res.index]
    print(res.loc[classic, cols].to_string(formatters=fmt))

    print("\nSMA vs EMA, averaged over all fast/slow pairs:")
    print(res.groupby("kind")[["CAGR", "Sharpe", "MaxDD", "trades_yr"]].mean()
          .to_string(formatters=fmt))
    print(f"Rules beating buy & hold on Sharpe: {(res.Sharpe > b['Sharpe']).sum()}/{len(res)};"
          f" on CAGR: {(res.CAGR > b['CAGR']).sum()}/{len(res)}")

    # ---- out-of-sample check: pick the winner on data before the split
    ins = {k: stats(v[:args.split], rf)["Sharpe"] for k, v in series.items()}
    oos = {k: stats(v[args.split:], rf) for k, v in series.items()}
    rank_in = pd.Series(ins).drop("Buy & hold").sort_values(ascending=False)
    oos_sh = pd.Series({k: v["Sharpe"] for k, v in oos.items()}).drop("Buy & hold")
    print(f"\nWalk-forward: choose on data < {args.split}, trade after it")
    for name in rank_in.index[:5]:
        o = oos[name]
        print(f"  {name:16s} in-sample Sharpe {rank_in[name]:.2f} -> out-of-sample "
              f"Sharpe {o['Sharpe']:.2f}  CAGR {o['CAGR']:.1%}  MaxDD {o['MaxDD']:.1%}  "
              f"(OOS rank {int(oos_sh.rank(ascending=False)[name])}/{len(oos_sh)})")
    o = oos["Buy & hold"]
    print(f"  {'Buy & hold':16s} out-of-sample Sharpe {o['Sharpe']:.2f}  CAGR {o['CAGR']:.1%}"
          f"  MaxDD {o['MaxDD']:.1%}")
    print(f"  Rank correlation in-sample vs out-of-sample: "
          f"{rank_in.corr(oos_sh.reindex(rank_in.index), method='spearman'):.2f}")

    # ---- regime table
    print("\nCAGR by market regime:")
    pick = ["Buy & hold", "SMA 50/200", "EMA 50/200", "SMA price/200", "EMA 20/50", "SMA price/50", "EMA price/50"]
    pick += [rank_in.index[0]] if rank_in.index[0] not in pick else []
    tab = pd.DataFrame({lab: {k: stats(series[k][a:b_], rf)["CAGR"] for k in pick}
                        for lab, a, b_ in PERIODS})
    print(tab.to_string(float_format=lambda x: f"{x:.1%}"))


if __name__ == "__main__":
    main()
