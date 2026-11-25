"""Project 1b - Does Monte Carlo VaR actually work? Backtest it.

Each month, estimate the model from the trailing year of daily returns,
simulate 10,000 one-month outcomes and record the 95% and 99% VaR. Then
check what really happened next month. A good 95% VaR is breached about 5%
of the time - and the breaches should not all come at once.

Three ways to simulate the daily shocks:
  normal     - textbook Gaussian (the version in monte_carlo_var.py)
  student-t  - fat tails (df=4), scaled to the same volatility
  bootstrap  - resample actual past daily returns (historical simulation)
  ewma       - normal, but covariance weighted toward recent days
               (RiskMetrics, lambda=0.94), so it reacts to the current regime

Portfolio mode also shows how correlations change in sell-offs.

Usage:
  python scripts/var_backtest.py --csv nifty.csv                   # one series
  python scripts/var_backtest.py --dir prices/ --tickers RELIANCE HDFCBANK TCS INFY ITC
  python scripts/var_backtest.py --tickers RELIANCE.NS TCS.NS ...  # via yfinance
"""
import argparse

import numpy as np
import pandas as pd

import _path  # noqa: F401  (lets scripts run without `pip install -e .`)
from quantlab.data import load_csv, load_csv_dir, load_prices
from quantlab.risk import var_backtest, var_report


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

    df, methods = var_backtest(logret.values, w)
    var_report(df, methods, logret.index)

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
        print("  The VaR scenario table in monte_carlo_var.py shows what that costs.")


if __name__ == "__main__":
    main()
