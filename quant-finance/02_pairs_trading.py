"""Project 2 - Pairs trading / statistical arbitrage.

India default: HDFCBANK vs ICICIBANK. US default: KO vs PEP.

1. Engle-Granger cointegration test: regress A on B, ADF-test the residuals.
2. Hedge ratio = regression slope (estimated on the formation window only).
3. Spread = A - beta*B, standardised as a rolling Z-score.
4. |z| > 2: short the rich leg, buy the cheap leg. Exit when z crosses 0.
5. Signals are lagged one day; buy/sell costs charged on both legs.
6. Out-of-sample period shows whether the relationship holds - or breaks.

India note: you cannot hold a short in the cash market overnight, so both legs
are costed as stock futures (STT 0.05% on sell). Real trading also means lot
sizes, monthly rollover, futures basis and F&O ban periods - not modelled here.

Usage: python 02_pairs_trading.py [--market in|us] [--a X --b Y] [--synthetic]
"""
import argparse

import numpy as np
import pandas as pd

from common import adf_stat, ols, load_prices
from markets import MARKETS, cost_per_side

ENTRY_Z, EXIT_Z = 2.0, 0.0
LOOKBACK = 60          # rolling window for z-score
# Engle-Granger 2-variable critical values (MacKinnon, constant, no trend)
EG_CRIT = {"1%": -3.90, "5%": -3.34, "10%": -3.04}


def synthetic_pair(names, n=2500, seed=7, level=1000):
    rng = np.random.default_rng(seed)
    b = level * np.exp(np.cumsum(0.0003 + 0.012 * rng.standard_normal(n)))
    spread = np.zeros(n)
    for t in range(1, n):  # mean-reverting OU spread
        spread[t] = 0.97 * spread[t - 1] + 0.012 * level * rng.standard_normal()
    a = 0.1 * level + 1.2 * b + spread
    idx = pd.bdate_range("2015-01-02", periods=n)
    print("[data] generated synthetic cointegrated pair")
    return pd.DataFrame({names[0]: a, names[1]: b}, index=idx)


def leg_cost(exposure, buy, sell):
    d = exposure.diff().fillna(exposure)
    return d.clip(lower=0) * buy + (-d).clip(lower=0) * sell


def backtest(px, beta, alpha, buy, sell):
    a, b = px.iloc[:, 0], px.iloc[:, 1]
    spread = a - beta * b - alpha
    z = (spread - spread.rolling(LOOKBACK).mean()) / spread.rolling(LOOKBACK).std()

    pos = np.zeros(len(z))  # +1 = long spread (long A, short B), -1 = short spread
    for t in range(1, len(z)):
        prev, zt = pos[t - 1], z.iloc[t]
        if np.isnan(zt):
            pos[t] = 0
        elif prev == 0:
            pos[t] = -1 if zt > ENTRY_Z else (1 if zt < -ENTRY_Z else 0)
        elif (prev == 1 and zt >= EXIT_Z) or (prev == -1 and zt <= EXIT_Z):
            pos[t] = 0
        else:
            pos[t] = prev
    pos = pd.Series(pos, index=z.index).shift(1).fillna(0)  # trade next day

    gross = a + beta * b                      # split capital in hedge-ratio proportion
    wa, wb = (a / gross).shift(1), (beta * b / gross).shift(1)
    exp_a, exp_b = (pos * wa).fillna(0), (-pos * wb).fillna(0)
    pnl = exp_a * a.pct_change().fillna(0) + exp_b * b.pct_change().fillna(0)
    costs = leg_cost(exp_a, buy, sell) + leg_cost(exp_b, buy, sell)
    return (pnl - costs).fillna(0), pos, costs.sum()


def stats(r, rf):
    ann, vol = r.mean() * 252, r.std() * np.sqrt(252)
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = (ann - rf) / vol if vol else 0
    return f"return {ann:6.1%}  vol {vol:5.1%}  Sharpe {sharpe:5.2f}  maxDD {dd:6.1%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=MARKETS, default="in")
    ap.add_argument("--a")
    ap.add_argument("--b")
    ap.add_argument("--cost-bps", type=float, help="override per-side cost model")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    m = MARKETS[args.market]
    names = (args.a or m["pair"][0], args.b or m["pair"][1])
    buy, sell = cost_per_side(args.market, m["pair_instrument"], args.cost_bps)
    level = 1000 if args.market == "in" else 50

    px = synthetic_pair(names, level=level) if args.synthetic else load_prices(list(names))
    if px.attrs.get("synthetic"):  # independent random walks can't be a pair
        px = synthetic_pair(names, level=level)

    split = int(len(px) * 0.6)
    train, test = px.iloc[:split], px.iloc[split:]

    coef, resid, _ = ols(train.iloc[:, 0].values, train.iloc[:, 1].values)
    alpha, beta = coef
    stat = adf_stat(resid, lags=1)
    print(f"\nPair {names[0]} / {names[1]}   costs: buy {buy*1e4:.1f} bps, "
          f"sell {sell*1e4:.1f} bps per leg")
    print(f"Formation period: {train.index[0].date()} -> {train.index[-1].date()}")
    print(f"Hedge ratio beta = {beta:.3f}, intercept = {alpha:.2f}")
    print(f"Engle-Granger ADF stat = {stat:.2f}  (crit 1% {EG_CRIT['1%']}, "
          f"5% {EG_CRIT['5%']}, 10% {EG_CRIT['10%']})")
    print("  ->", "cointegrated at 5%" if stat < EG_CRIT["5%"] else
          "NOT cointegrated at 5% - trade at your own risk")

    for name, data in [("in-sample", train), ("out-of-sample", test)]:
        r, pos, total_cost = backtest(data, beta, alpha, buy, sell)
        trades = int((pos.diff().abs() > 0).sum())
        print(f"  {name:14s} {stats(r, m['risk_free'])}  trades {trades}  "
              f"costs {total_cost:.1%}")

    _, resid_test, _ = ols(test.iloc[:, 0].values, test.iloc[:, 1].values)
    print(f"\nOut-of-sample ADF on re-fit residuals: {adf_stat(resid_test):.2f}")
    print("Lesson: mean reversion pays only while the relationship holds."
          " Re-test it; relationships break.")


if __name__ == "__main__":
    main()
