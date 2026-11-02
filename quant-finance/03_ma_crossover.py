"""Project 3 - 50/200-day moving average crossover backtest, done honestly.

* Long when the 50-day SMA is above the 200-day SMA, else in cash.
* Signal is shifted one day: decided on today's close, traded tomorrow.
* Buy/sell costs charged on every position change (Indian statutory charges
  for --market in, flat bps for us), cash earns the risk-free rate.
* Compared against buy-and-hold, plus a deliberately broken look-ahead
  version so you can see how much "free" performance a bug creates.

India default: NIFTYBEES.NS (tradable Nifty 50 ETF; the ^NSEI index excludes
dividends and can't be bought). Try a stock with --ticker RELIANCE.NS
--instrument equity_delivery.

Usage: python 03_ma_crossover.py [--market in|us] [--ticker X] [--synthetic]
"""
import argparse

import numpy as np
import pandas as pd

from common import load_prices
from markets import INDIA_CHARGES, MARKETS, cost_per_side


def metrics(r, rf):
    eq = (1 + r).cumprod()
    years = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252 - rf) / vol if vol else 0.0
    mdd = (eq / eq.cummax() - 1).min()
    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MaxDD": mdd, "Final x": eq.iloc[-1]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=MARKETS, default="in")
    ap.add_argument("--ticker")
    ap.add_argument("--instrument", choices=list(INDIA_CHARGES), help="India cost model")
    ap.add_argument("--fast", type=int, default=50)
    ap.add_argument("--slow", type=int, default=200)
    ap.add_argument("--cost-bps", type=float, help="override per-side cost model")
    ap.add_argument("--no-cash-yield", action="store_true", help="cash earns 0")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    m = MARKETS[args.market]
    ticker = args.ticker or m["trend_ticker"]
    instrument = args.instrument or m["trend_instrument"]
    buy, sell = cost_per_side(args.market, instrument, args.cost_bps)
    rf = m["risk_free"]
    cash_daily = 0.0 if args.no_cash_yield else (1 + rf) ** (1 / 252) - 1

    px = load_prices([ticker], start="2005-01-01", synthetic=args.synthetic).iloc[:, 0]
    ret = px.pct_change().fillna(0)
    fast, slow = px.rolling(args.fast).mean(), px.rolling(args.slow).mean()
    signal = (fast > slow).astype(float)
    signal[slow.isna()] = 0

    position = signal.shift(1).fillna(0)              # honest: trade next day
    d = position.diff().fillna(0)
    cost = d.clip(lower=0) * buy + (-d).clip(lower=0) * sell
    strat = position * ret + (1 - position) * cash_daily - cost

    cheat = signal * ret + (1 - signal) * cash_daily   # look-ahead, no costs

    start = slow.first_valid_index()
    rows = {
        "Buy & hold": metrics(ret[start:], rf),
        "MA cross (honest)": metrics(strat[start:], rf),
        "MA cross (look-ahead bug)": metrics(cheat[start:], rf),
    }
    df = pd.DataFrame(rows).T
    print(f"\n{ticker}: {args.fast}/{args.slow} SMA crossover, costs buy {buy*1e4:.1f} / "
          f"sell {sell*1e4:.1f} bps, cash yield {0 if args.no_cash_yield else rf:.1%}, "
          f"{start.date()} -> {px.index[-1].date()}")
    print(df.to_string(formatters={
        "CAGR": "{:.1%}".format, "Vol": "{:.1%}".format, "Sharpe": "{:.2f}".format,
        "MaxDD": "{:.1%}".format, "Final x": "{:.2f}".format}))
    print(f"\nRound trips: {int((d > 0).sum())}   Time in market: {position[start:].mean():.0%}"
          f"   Total costs: {cost.sum():.2%}")
    print("Lesson: the crossover mostly trades return for lower drawdown. Remove the"
          " one-day lag and it looks great - that gap is a bug, not alpha.")


if __name__ == "__main__":
    main()
