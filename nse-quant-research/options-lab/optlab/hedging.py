"""Discrete delta hedging: sell an option, hedge with the underlying, track P&L.

In continuous time with no costs, a delta-hedged option at the right volatility
has zero P&L. Hedging only at discrete times leaves an error that shrinks like
1/sqrt(rebalances); pricing at the wrong volatility leaves a P&L of roughly
0.5 * Gamma * S^2 * (sigma_implied^2 - sigma_realised^2) * dt summed over the life.
"""
from __future__ import annotations

import numpy as np

from . import bs


def gbm_paths(S0, T, mu, sigma, steps, n_paths, seed=0, q=0.0):
    """Simulated price paths, shape (n_paths, steps + 1)."""
    rng = np.random.default_rng(seed)
    dt = T / steps
    z = rng.standard_normal((n_paths, steps))
    log_inc = (mu - q - 0.5 * sigma**2) * dt + sigma * np.sqrt(dt) * z
    return S0 * np.exp(np.concatenate([np.zeros((n_paths, 1)), np.cumsum(log_inc, axis=1)], axis=1))


def hedge_pnl(paths, K, T, r, sigma_price, kind="call", q=0.0, hedge_every=1, cost=0.0):
    """P&L of a short option, delta-hedged every `hedge_every` steps.

    paths: (n_paths, steps+1) underlying prices over the option's life.
    sigma_price: volatility used to sell the option and compute deltas.
    cost: proportional cost per unit of underlying traded (e.g. 0.0005 = 5 bps).
    Returns P&L per path as a fraction of the initial spot.
    """
    paths = np.atleast_2d(paths)
    n, m = paths.shape
    steps = m - 1
    dt = T / steps
    S0 = paths[:, 0]
    premium = bs.price(S0, K, T, r, sigma_price, kind, q)
    cash = premium.copy()
    delta = np.zeros(n)
    traded = np.zeros(n)
    for i in range(steps):
        S = paths[:, i]
        if i % hedge_every == 0:
            new = bs.greeks(S, K, T - i * dt, r, sigma_price, kind, q)["delta"]
            trade = new - delta
            cash -= trade * S + np.abs(trade) * S * cost
            traded += np.abs(trade) * S
            delta = new
        cash = cash * np.exp(r * dt) + delta * S * (np.exp(q * dt) - 1)   # interest and dividends
    ST = paths[:, -1]
    payoff = np.maximum(ST - K, 0.0) if kind == "call" else np.maximum(K - ST, 0.0)
    cash += delta * ST - np.abs(delta) * ST * cost                        # unwind hedge
    return (cash - payoff) / S0


def realised_vol(prices, periods_per_year=252):
    r = np.diff(np.log(np.asarray(prices, dtype=float)))
    return float(r.std(ddof=1) * np.sqrt(periods_per_year))
