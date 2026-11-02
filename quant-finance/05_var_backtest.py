"""Project 1b - Does Monte Carlo VaR actually work? Backtest it.

Each month, estimate the model from the trailing year of daily returns,
simulate 10,000 one-month outcomes and record the 95% and 99% VaR. Then
check what really happened next month. A good 95% VaR is breached about 5%
of the time - and the breaches should not all come at once.

Three ways to simulate the daily shocks:
  normal     - textbook Gaussian (the version in 01_monte_carlo_var.py)
  student-t  - fat tails (df=4), scaled to the same volatility
  bootstrap  - resample actual past daily returns (historical simulation)
  ewma       - normal, but covariance weighted toward recent days
               (RiskMetrics, lambda=0.94), so it reacts to the current regime

Portfolio mode also shows how correlations change in sell-offs.

Usage:
  python 05_var_backtest.py --csv nifty.csv                   # one series
  python 05_var_backtest.py --dir prices/ --tickers RELIANCE HDFCBANK TCS INFY ITC
  python 05_var_backtest.py --tickers RELIANCE.NS TCS.NS ...  # via yfinance
"""
import argparse

import numpy as np
import pandas as pd

from common import load_csv, load_csv_dir, load_prices

N_SIMS, HORIZON, WINDOW, DF, LAMBDA = 10_000, 21, 252, 4, 0.94


def sim_paths(hist, method, rng):
    """hist: (days, assets) daily log returns. Returns (N_SIMS, assets) horizon log returns."""
    mu, cov = hist.mean(0), np.cov(hist, rowvar=False).reshape(hist.shape[1], -1)
    k = hist.shape[1]
    if method == "ewma":
        wts = LAMBDA ** np.arange(len(hist))[::-1]
        wts /= wts.sum()
        dm = hist - mu
        cov = (dm * wts[:, None]).T @ dm
    if method == "bootstrap":
        idx = rng.integers(0, len(hist), (N_SIMS, HORIZON))
        return hist[idx].sum(1)
    L = np.linalg.cholesky(cov + 1e-12 * np.eye(k))
    z = rng.standard_normal((N_SIMS, HORIZON, k))
    if method == "student-t":  # multivariate t with unit variance
        w = rng.chisquare(DF, (N_SIMS, HORIZON, 1)) / DF
        z = z / np.sqrt(w) * np.sqrt((DF - 2) / DF)
    return (mu + z @ L.T).sum(1)


def backtest(logret, weights, methods=("normal", "student-t", "bootstrap", "ewma")):
    rng = np.random.default_rng(1)
    rows = []
    for start in range(WINDOW, len(logret) - HORIZON, HORIZON):  # non-overlapping months
        hist = logret[start - WINDOW:start]
        actual = (np.exp(logret[start:start + HORIZON].sum(0)) - 1) @ weights
        row = {"i": start, "actual": actual}
        for m in methods:
            port = (np.exp(sim_paths(hist, m, rng)) - 1) @ weights
            row[(m, 95)] = -np.quantile(port, 0.05)
            row[(m, 99)] = -np.quantile(port, 0.01)
        rows.append(row)
    return pd.DataFrame(rows), methods


def report(df, methods, dates):
    n = len(df)
    print(f"\n{n} monthly forecasts, {dates[WINDOW].date()} -> {dates[-1].date()}")
    print(f"  {'method':10s} {'95% breaches':>14s} {'(expect 5%)':>11s} "
          f"{'99% breaches':>14s} {'(expect 1%)':>11s}  avg 95% VaR  worst miss")
    for m in methods:
        b95 = df.actual < -df[(m, 95)]
        b99 = df.actual < -df[(m, 99)]
        miss = (-df.actual - df[(m, 99)]).max()
        print(f"  {m:10s} {b95.sum():>8d} = {b95.mean():5.1%} {'':11s} "
              f"{b99.sum():>8d} = {b99.mean():5.1%} {'':11s}  {df[(m, 95)].mean():9.1%}"
              f"  {miss:+.1%}")
    years = pd.Series([dates[int(i)].year for i in df.i])
    b = years[(df.actual < -df[("normal", 95)]).values].value_counts().sort_index()
    print("  normal-model 95% breaches by year: "
          + ", ".join(f"{y}: {c}" for y, c in b.items()))
    worst = df.nsmallest(5, "actual")
    print("\n  Worst 5 months vs the normal model's 99% VaR forecast:")
    for _, r in worst.iterrows():
        d = dates[int(r.i)].date()
        print(f"    month from {d}: actual {r.actual:6.1%}   normal 99% VaR "
              f"{-r[('normal', 99)]:6.1%}   bootstrap 99% VaR {-r[('bootstrap', 99)]:6.1%}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--dir")
    ap.add_argument("--tickers", nargs="+")
    args = ap.parse_args()

    if args.csv:
        px = load_csv(args.csv).to_frame("asset")
    elif args.dir:
        px = load_csv_dir(args.dir, args.tickers)
    else:
        px = load_prices(args.tickers or ["^NSEI"], start="2001-01-01")
    logret = np.log(px).diff().dropna()
    w = np.full(px.shape[1], 1 / px.shape[1])
    print(f"Assets: {', '.join(px.columns)} (equal weight)")

    df, methods = backtest(logret.values, w)
    report(df, methods, logret.index)

    if px.shape[1] > 1:
        # Split time by market volatility (not by the returns themselves, which
        # would bias the comparison) and compare average pairwise correlation.
        win = 63
        port = pd.Series(logret.values @ w, index=logret.index)
        vol = port.rolling(win).std().iloc[win - 1::win]
        k = px.shape[1]
        corr = {d: logret.loc[:d].iloc[-win:].corr().values[np.triu_indices(k, 1)].mean()
                for d in vol.index}
        corr = pd.Series(corr)
        hi, lo = vol >= vol.median(), vol < vol.median()
        print(f"\nAverage pairwise correlation, {win}-day blocks: calm half {corr[lo].mean():.2f}, "
              f"volatile half {corr[hi].mean():.2f}")
        print("  The VaR scenario table in 01_monte_carlo_var.py shows what that costs.")

if __name__ == "__main__":
    main()
