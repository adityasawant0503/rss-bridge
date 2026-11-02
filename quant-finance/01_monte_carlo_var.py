"""Project 1 - Monte Carlo portfolio risk: VaR and Expected Shortfall.

1. Estimate daily mean returns, volatilities and the correlation matrix.
2. Simulate 10,000 one-month (21-day) futures using correlated normal shocks
   (Cholesky decomposition of the covariance matrix).
3. Read Value at Risk and Expected Shortfall off the simulated P&L distribution.
4. Re-run with correlations forced to 0 and to 1 to see that correlation,
   not the individual stocks, drives portfolio risk.

Usage: python 01_monte_carlo_var.py [--synthetic]
"""
import argparse

import numpy as np

from common import load_prices

TICKERS = ["AAPL", "MSFT", "JPM", "XOM", "JNJ"]
WEIGHTS = np.array([0.2, 0.2, 0.2, 0.2, 0.2])
PORTFOLIO_VALUE = 1_000_000
N_SIMS = 10_000
HORIZON = 21  # trading days ~ one month
CONFIDENCE = 0.95


def simulate(mu, cov, weights, n_sims, horizon, rng):
    """Return simulated portfolio returns over the horizon (n_sims,)."""
    L = np.linalg.cholesky(cov)
    shocks = rng.standard_normal((n_sims, horizon, len(mu)))
    daily = mu + shocks @ L.T                     # correlated daily log returns
    asset_cum = np.exp(daily.sum(axis=1)) - 1     # per-asset horizon return
    return asset_cum @ weights


def var_es(pnl, confidence):
    cutoff = np.quantile(pnl, 1 - confidence)
    var = -cutoff
    es = -pnl[pnl <= cutoff].mean()
    return var, es


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()

    prices = load_prices(TICKERS, synthetic=args.synthetic)
    rets = np.log(prices).diff().dropna()
    mu, vol = rets.mean().values, rets.std().values
    corr = rets.corr().values
    cov = rets.cov().values

    print("\nAnnualised stats")
    for t, m, v in zip(TICKERS, mu, vol):
        print(f"  {t:5s} return {m*252:6.1%}   vol {v*np.sqrt(252):6.1%}")
    print("\nCorrelation matrix\n", rets.corr().round(2))

    rng = np.random.default_rng(0)
    results = {}
    for label, c in [("estimated", corr),
                     ("zero corr", np.eye(len(mu))),
                     ("perfect corr", np.ones_like(corr) * 0.999 + np.eye(len(mu)) * 0.001)]:
        cov_c = np.outer(vol, vol) * c
        port = simulate(mu, cov_c, WEIGHTS, N_SIMS, HORIZON, rng)
        pnl = port * PORTFOLIO_VALUE
        results[label] = var_es(pnl, CONFIDENCE)

    print(f"\n{N_SIMS:,} simulations, {HORIZON}-day horizon, "
          f"{CONFIDENCE:.0%} confidence, ${PORTFOLIO_VALUE:,.0f} portfolio")
    print(f"  {'scenario':14s} {'VaR':>12s} {'Exp. Shortfall':>16s}")
    for label, (v, e) in results.items():
        print(f"  {label:14s} ${v:>11,.0f} ${e:>15,.0f}")
    print("\nLesson: same stocks, same volatilities - only correlation changed,"
          " and the risk moved dramatically.")


if __name__ == "__main__":
    main()
