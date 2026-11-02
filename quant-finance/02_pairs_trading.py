"""Project 2 - Pairs trading / statistical arbitrage (e.g. KO vs PEP).

1. Engle-Granger cointegration test: regress A on B, ADF-test the residuals.
2. Hedge ratio = regression slope (estimated on the formation window only).
3. Spread = A - beta*B, standardised as a rolling Z-score.
4. |z| > 2: short the rich leg, buy the cheap leg. Exit when z crosses 0.
5. Signals are lagged one day; costs are charged on every position change.
6. Out-of-sample period shows whether the relationship holds - or breaks.

Usage: python 02_pairs_trading.py [--synthetic] [--a KO --b PEP]
"""
import argparse

import numpy as np
import pandas as pd

from common import adf_stat, ols, load_prices

ENTRY_Z, EXIT_Z = 2.0, 0.0
LOOKBACK = 60          # rolling window for z-score
COST_BPS = 5           # per leg, per unit of turnover
# Engle-Granger 2-variable critical values (MacKinnon, constant, no trend)
EG_CRIT = {"1%": -3.90, "5%": -3.34, "10%": -3.04}


def synthetic_pair(n=2500, seed=7):
    rng = np.random.default_rng(seed)
    b = 50 * np.exp(np.cumsum(0.0003 + 0.012 * rng.standard_normal(n)))
    spread = np.zeros(n)
    for t in range(1, n):  # mean-reverting OU spread
        spread[t] = 0.97 * spread[t - 1] + 0.6 * rng.standard_normal()
    a = 5 + 1.2 * b + spread
    idx = pd.bdate_range("2015-01-02", periods=n)
    print("[data] generated synthetic cointegrated pair")
    return pd.DataFrame({"A": a, "B": b}, index=idx)


def backtest(px, beta, alpha):
    spread = px.iloc[:, 0] - beta * px.iloc[:, 1] - alpha
    z = (spread - spread.rolling(LOOKBACK).mean()) / spread.rolling(LOOKBACK).std()

    pos = np.zeros(len(z))  # +1 = long spread (long A, short B), -1 = short spread
    for t in range(1, len(z)):
        prev, zt = pos[t - 1], z.iloc[t]
        if np.isnan(zt):
            pos[t] = 0
        elif prev == 0:
            pos[t] = -1 if zt > ENTRY_Z else (1 if zt < -ENTRY_Z else 0)
        elif prev == 1 and zt >= EXIT_Z:
            pos[t] = 0
        elif prev == -1 and zt <= EXIT_Z:
            pos[t] = 0
        else:
            pos[t] = prev
    pos = pd.Series(pos, index=z.index).shift(1).fillna(0)  # trade next day

    ra = px.iloc[:, 0].pct_change().fillna(0)
    rb = px.iloc[:, 1].pct_change().fillna(0)
    # dollar-neutral-ish: weight legs by hedge ratio in dollar terms
    gross = px.iloc[:, 0] + beta * px.iloc[:, 1]
    wa = (px.iloc[:, 0] / gross).shift(1)
    wb = (beta * px.iloc[:, 1] / gross).shift(1)
    strat = pos * (wa * ra - wb * rb)
    costs = pos.diff().abs().fillna(0) * 2 * COST_BPS / 1e4
    return (strat - costs).fillna(0), z, pos


def stats(r):
    ann = r.mean() * 252
    vol = r.std() * np.sqrt(252)
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    return f"return {ann:6.1%}  vol {vol:5.1%}  Sharpe {ann/vol if vol else 0:5.2f}  maxDD {dd:6.1%}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    ap.add_argument("--a", default="KO")
    ap.add_argument("--b", default="PEP")
    args = ap.parse_args()

    if args.synthetic:
        px = synthetic_pair()
    else:
        px = load_prices([args.a, args.b])
        if px.attrs.get("synthetic"):  # independent random walks can't be a pair
            px = synthetic_pair()

    split = int(len(px) * 0.6)
    train, test = px.iloc[:split], px.iloc[split:]

    coef, resid, _ = ols(train.iloc[:, 0].values, train.iloc[:, 1].values)
    alpha, beta = coef
    stat = adf_stat(resid, lags=1)
    print(f"\nFormation period: {train.index[0].date()} -> {train.index[-1].date()}")
    print(f"Hedge ratio beta = {beta:.3f}, intercept = {alpha:.2f}")
    print(f"Engle-Granger ADF stat = {stat:.2f}  (crit 1% {EG_CRIT['1%']}, "
          f"5% {EG_CRIT['5%']}, 10% {EG_CRIT['10%']})")
    print("  ->", "cointegrated at 5%" if stat < EG_CRIT["5%"] else
          "NOT cointegrated at 5% - trade at your own risk")

    for name, data in [("in-sample", train), ("out-of-sample", test)]:
        r, z, pos = backtest(data, beta, alpha)
        trades = int((pos.diff().abs() > 0).sum())
        print(f"  {name:14s} {stats(r)}  trades {trades}")

    # Does the relationship still hold out of sample?
    _, resid_test, _ = ols(test.iloc[:, 0].values, test.iloc[:, 1].values)
    print(f"\nOut-of-sample ADF on re-fit residuals: {adf_stat(resid_test):.2f}")
    print("Lesson: mean reversion pays only while the relationship holds."
          " Re-test it; relationships break.")


if __name__ == "__main__":
    main()
