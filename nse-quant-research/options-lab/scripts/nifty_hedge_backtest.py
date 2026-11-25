"""Delta-hedging backtest on real Nifty 50 paths.

Each month from 2002 to 2023: sell a one-month (21 trading day) at-the-money
Nifty call, priced at an assumed implied volatility, and delta-hedge it daily
with Nifty futures along the price path that actually happened. Record the
P&L as a % of spot.

We have no historical option prices, so implied volatility is modelled as
trailing 21-day realised volatility plus a markup (in vol points). The sweep
over markups answers: how far above recent realised volatility must you sell
options just to break even after hedging costs and crashes?

Usage:
  python scripts/nifty_hedge_backtest.py --csv data/nifty50_index.csv
"""
import argparse

import numpy as np
import pandas as pd

import _path  # noqa: F401
from optlab import bs
from optlab.hedging import hedge_pnl

R, Q, DAYS = 0.06, 0.013, 21
FUT_COST = 0.00078          # NSE futures, average of buy 5.4 and sell 10.2 bps per side


def load(path):
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    s = pd.Series(df[cols["close"]].values, index=pd.to_datetime(df[cols.get("date", "Date")]))
    return s[~s.index.duplicated()].sort_index().astype(float)


def backtest(px, markup=0.0, cost=FUT_COST, hedge_every=1):
    """All months at once: each row of `paths` is one month's 22 daily closes."""
    v = px.values
    starts = np.arange(DAYS, len(v) - DAYS, DAYS)
    paths = v[starts[:, None] + np.arange(DAYS + 1)]              # (months, DAYS + 1)
    hist = v[starts[:, None] + np.arange(-DAYS, 1)]               # trailing window per month
    vol = lambda w: np.diff(np.log(w), axis=1).std(axis=1, ddof=1) * np.sqrt(252)
    sigma_imp, sigma_real = vol(hist) + markup, vol(paths)
    S0, T = paths[:, 0], DAYS / 252
    pnl = hedge_pnl(paths, S0, T, R, sigma_imp, "call", Q, hedge_every, cost)
    gamma = bs.greeks(S0, S0, T, R, sigma_imp, "call", Q)["gamma"]
    return pd.DataFrame({
        "sigma_imp": sigma_imp, "sigma_real": sigma_real,
        "premium": bs.price(S0, S0, T, R, sigma_imp, "call", Q) / S0,
        "pnl": pnl, "approx": 0.5 * gamma * S0 * (sigma_imp**2 - sigma_real**2) * T,   # % of spot
        "move": paths[:, -1] / S0 - 1,
    }, index=pd.Index(px.index[starts], name="date"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    args = ap.parse_args()
    px = load(args.csv)
    base = backtest(px)
    print(f"{len(base)} monthly short ATM calls, {base.index[0].date()} -> {base.index[-1].date()}, "
          f"hedged daily, futures cost {FUT_COST*1e4:.1f} bps/side\n")
    print("Implied vol = trailing 21-day realised vol (no markup):")
    print(f"  avg premium received    {base.premium.mean():.2%} of spot")
    print(f"  avg hedged P&L          {base.pnl.mean():+.3%} of spot per month "
          f"(std {base.pnl.std():.2%}, win rate {(base.pnl > 0).mean():.0%})")
    print(f"  worst month             {base.pnl.min():+.2%} starting {base.pnl.idxmin().date()}")
    print(f"  corr(P&L, gamma approx) {base.pnl.corr(base.approx):.2f}  "
          "-> you are trading implied vs realised volatility")
    free = backtest(px, 0.0, 0.0)
    print(f"  of which hedging costs  {base.pnl.mean() - free.pnl.mean():+.3%} "
          f"(P&L with zero costs {free.pnl.mean():+.3%})")
    print(f"  realised vol exceeded trailing vol in {(base.sigma_real > base.sigma_imp).mean():.0%} of months\n")

    print("Markup sweep (sell at trailing realised vol + markup):")
    print(f"  {'markup':>7s} {'avg P&L/month':>14s} {'win rate':>9s} {'worst':>8s} {'Sharpe (ann.)':>14s}")
    for mk in [0.0, 0.01, 0.02, 0.03, 0.05]:
        b = base if mk == 0 else backtest(px, mk)
        sh = b.pnl.mean() / b.pnl.std() * np.sqrt(12)
        print(f"  {mk*100:5.0f} pt {b.pnl.mean():+13.3%} {(b.pnl > 0).mean():9.0%} {b.pnl.min():+8.2%} {sh:14.2f}")

    print("\nHedge frequency (no markup):")
    for k, lab in [(1, "daily"), (5, "weekly"), (21, "never (static)")]:
        b = backtest(px, 0.0, FUT_COST, k)
        print(f"  {lab:15s} avg {b.pnl.mean():+.3%}  std {b.pnl.std():.2%}  worst {b.pnl.min():+.2%}")


if __name__ == "__main__":
    main()
