"""Monte Carlo Value at Risk / Expected Shortfall and VaR backtesting."""
from __future__ import annotations

import numpy as np
import pandas as pd

CONFIDENCE = 0.95


N_SIMS, HORIZON, WINDOW, DF, LAMBDA = 10_000, 21, 252, 4, 0.94


def simulate(mu, cov, weights, n_sims, horizon, rng):
    """Return simulated portfolio returns over the horizon (n_sims,)."""
    L = np.linalg.cholesky(cov)
    shocks = rng.standard_normal((n_sims, horizon, len(mu)))
    daily = mu + shocks @ L.T                     # correlated daily log returns
    asset_cum = np.exp(daily.sum(axis=1)) - 1     # per-asset horizon return
    return asset_cum @ weights


def var_es(pnl, confidence):
    cutoff = np.quantile(pnl, 1 - confidence)
    return -cutoff, -pnl[pnl <= cutoff].mean()


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


def var_backtest(logret, weights, methods=("normal", "student-t", "bootstrap", "ewma")):
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


def var_report(df, methods, dates):
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
