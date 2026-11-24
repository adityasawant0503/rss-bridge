"""Implied volatility: invert Black-Scholes for sigma."""
from __future__ import annotations

import numpy as np

from . import bs


def implied_vol(market_price, S, K, T, r, kind="call", q=0.0, tol=1e-8, max_iter=100):
    """Newton-Raphson on vega, falling back to bisection on [1e-4, 5].

    Raises ValueError if the price is outside no-arbitrage bounds.
    """
    df_q, df_r = np.exp(-q * T), np.exp(-r * T)
    lower = max(S * df_q - K * df_r, 0.0) if kind == "call" else max(K * df_r - S * df_q, 0.0)
    upper = S * df_q if kind == "call" else K * df_r
    if not lower - 1e-12 <= market_price <= upper + 1e-12:
        raise ValueError(f"price {market_price:.4f} outside no-arbitrage bounds [{lower:.4f}, {upper:.4f}]")
    sigma = 0.2
    for _ in range(max_iter):
        diff = bs.price(S, K, T, r, sigma, kind, q) - market_price
        if abs(diff) < tol:
            return sigma
        vega = bs.greeks(S, K, T, r, sigma, kind, q)["vega"]
        if vega < 1e-10:
            break
        step = sigma - diff / vega
        if not 1e-4 < step < 5.0:
            break
        sigma = step
    lo, hi = 1e-4, 5.0                                   # bisection fallback
    for _ in range(200):
        mid = 0.5 * (lo + hi)
        if bs.price(S, K, T, r, mid, kind, q) > market_price:
            hi = mid
        else:
            lo = mid
        if hi - lo < tol:
            break
    return 0.5 * (lo + hi)
