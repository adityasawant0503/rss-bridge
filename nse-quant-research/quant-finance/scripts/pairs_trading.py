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

Usage: python scripts/pairs_trading.py [--market in|us] [--a X --b Y] [--synthetic]
"""
import argparse

import _path  # noqa: F401  (lets scripts run without `pip install -e .`)
from quantlab.costs import MARKETS, cost_per_side
from quantlab.data import load_prices, synthetic_pair
from quantlab.pairs import EG_CRIT, backtest, summary_line
from quantlab.stats import adf_stat, ols


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
        print(f"  {name:14s} {summary_line(r, m['risk_free'])}  trades {trades}  "
              f"costs {total_cost:.1%}")

    _, resid_test, _ = ols(test.iloc[:, 0].values, test.iloc[:, 1].values)
    print(f"\nOut-of-sample ADF on re-fit residuals: {adf_stat(resid_test):.2f}")
    print("Lesson: mean reversion pays only while the relationship holds."
          " Re-test it; relationships break.")


if __name__ == "__main__":
    main()
