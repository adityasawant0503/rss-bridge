"""Project 3 - 50/200-day moving average crossover backtest, done honestly.

* Long when the 50-day SMA is above the 200-day SMA, else flat.
* Signal is shifted one day: decided on today's close, traded tomorrow.
* Transaction costs charged on every position change.
* Compared against buy-and-hold, plus a deliberately broken look-ahead
  version so you can see how much "free" performance a bug creates.

Usage: python 03_ma_crossover.py [--synthetic] [--ticker SPY] [--cost-bps 10]
"""
import argparse

import numpy as np
import pandas as pd

from common import load_prices


def metrics(r):
    eq = (1 + r).cumprod()
    years = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = r.mean() * 252 / vol if vol else 0.0
    mdd = (eq / eq.cummax() - 1).min()
    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MaxDD": mdd, "Final x": eq.iloc[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--ticker", default="SPY")
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--cost-bps", type=float, default=10)
    args = ap.parse_args()

    px = load_prices([args.ticker], start="2000-01-01", synthetic=args.synthetic).iloc[:, 0]
    ret = px.pct_change().fillna(0)
    fast, slow = px.rolling(args.fast).mean(), px.rolling(args.slow).mean()
    signal = (fast > slow).astype(float)
    signal[slow.isna()] = 0

    position = signal.shift(1).fillna(0)              # honest: trade next day
    trades = position.diff().abs().fillna(0)
    cost = trades * args.cost_bps / 1e4
    strat = position * ret - cost

    cheat = signal * ret                               # look-ahead, no costs
    bh = ret

    start = slow.first_valid_index()
    rows = {
        "Buy & hold": metrics(bh[start:]),
        "MA cross (honest)": metrics(strat[start:]),
        "MA cross (look-ahead bug)": metrics(cheat[start:]),
    }
    df = pd.DataFrame(rows).T
    print(f"\n{args.ticker}: {args.fast}/{args.slow} SMA crossover, "
          f"{args.cost_bps:.0f} bps per trade, {start.date()} -> {px.index[-1].date()}")
    print(df.to_string(formatters={
        "CAGR": "{:.1%}".format, "Vol": "{:.1%}".format, "Sharpe": "{:.2f}".format,
        "MaxDD": "{:.1%}".format, "Final x": "{:.2f}".format}))
    print(f"\nRound trips: {int(trades.sum() // 2)}   Time in market: {position[start:].mean():.0%}")
    print("Lesson: the crossover mostly trades return for lower drawdown. Remove the"
          " one-day lag and it looks great - that gap is a bug, not alpha.")


if __name__ == "__main__":
    main()
