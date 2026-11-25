"""Project 1 - Monte Carlo portfolio risk: VaR and Expected Shortfall.

1. Estimate daily mean returns, volatilities and the correlation matrix.
2. Simulate 10,000 one-month (21-day) futures using correlated normal shocks
   (Cholesky decomposition of the covariance matrix).
3. Read Value at Risk and Expected Shortfall off the simulated P&L distribution.
4. Re-run with correlations forced to 0 and to 1 to see that correlation,
   not the individual stocks, drives portfolio risk.

Usage: python scripts/monte_carlo_var.py [--market in|us] [--tickers A B C] [--synthetic]
"""
import argparse

import numpy as np

import _path  # noqa: F401  (lets scripts run without `pip install -e .`)
from quantlab.costs import MARKETS
from quantlab.data import load_csv_dir, load_prices
from quantlab.risk import CONFIDENCE, HORIZON, N_SIMS, simulate, var_es
from quantlab.stats import fmt_money


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--market", choices=MARKETS, default="in")
    ap.add_argument("--tickers", nargs="+")
    ap.add_argument("--value", type=float, help="portfolio value in local currency")
    ap.add_argument("--dir", help="folder of <TICKER>_*.csv files instead of yfinance")
    ap.add_argument("--synthetic", action="store_true")
    args = ap.parse_args()
    m = MARKETS[args.market]
    tickers = args.tickers or m["var_tickers"]
    value = args.value or m["portfolio_value"]
    cur = m["currency"]
    weights = np.full(len(tickers), 1 / len(tickers))

    if args.dir:
        tickers = [t.removesuffix(".NS") for t in tickers]
        prices = load_csv_dir(args.dir, tickers)[tickers]
    else:
        prices = load_prices(tickers, synthetic=args.synthetic)
    print(f"[data] {prices.index[0].date()} -> {prices.index[-1].date()}")
    rets = np.log(prices).diff().dropna()
    mu, vol = rets.mean().values, rets.std().values
    corr = rets.corr().values

    print("\nAnnualised stats (equal weights)")
    for t, mu_i, v in zip(tickers, mu, vol, strict=True):
        print(f"  {t:14s} return {mu_i*252:6.1%}   vol {v*np.sqrt(252):6.1%}")
    print("\nCorrelation matrix\n", rets.corr().round(2))

    rng = np.random.default_rng(0)
    k = len(mu)
    scenarios = [("estimated", corr), ("zero corr", np.eye(k)),
                 ("perfect corr", np.full((k, k), 0.999) + np.eye(k) * 0.001)]
    print(f"\n{N_SIMS:,} simulations, {HORIZON}-day horizon, "
          f"{CONFIDENCE:.0%} confidence, portfolio {fmt_money(value, cur)}")
    print(f"  {'scenario':14s} {'VaR':>16s} {'Exp. Shortfall':>18s}")
    for label, c in scenarios:
        port = simulate(mu, np.outer(vol, vol) * c, weights, N_SIMS, HORIZON, rng)
        v, e = var_es(port * value, CONFIDENCE)
        print(f"  {label:14s} {fmt_money(v, cur):>16s} {fmt_money(e, cur):>18s}")
    print("\nLesson: same stocks, same volatilities - only correlation changed,"
          " and the risk moved dramatically.")


if __name__ == "__main__":
    main()
