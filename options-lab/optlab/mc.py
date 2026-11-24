"""Monte Carlo pricing of European options under geometric Brownian motion."""
from __future__ import annotations

import numpy as np


def price(S, K, T, r, sigma, kind="call", q=0.0, n_paths=100_000, seed=0,
          antithetic=True, control_variate=True):
    """Return (price, standard_error).

    antithetic: pairs each normal draw z with -z, cancelling odd moments.
    control_variate: uses the discounted terminal price, whose expectation
    (S e^{-qT}) is known exactly, to remove most of the remaining noise.
    """
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")
    rng = np.random.default_rng(seed)
    n = n_paths // 2 if antithetic else n_paths
    z = rng.standard_normal(n)
    if antithetic:
        z = np.concatenate([z, -z])
    ST = S * np.exp((r - q - 0.5 * sigma**2) * T + sigma * np.sqrt(T) * z)
    disc = np.exp(-r * T)
    y = disc * (np.maximum(ST - K, 0.0) if kind == "call" else np.maximum(K - ST, 0.0))
    x = disc * ST                                   # control: E[x] = S e^{-qT} exactly
    if antithetic:  # average each antithetic pair first so samples are independent
        y, x = 0.5 * (y[:n] + y[n:]), 0.5 * (x[:n] + x[n:])
    if control_variate:
        cov = np.cov(y, x)
        b = cov[0, 1] / cov[1, 1]
        y = y - b * (x - S * np.exp(-q * T))
    return float(y.mean()), float(y.std(ddof=1) / np.sqrt(len(y)))
