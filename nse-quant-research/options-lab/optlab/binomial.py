"""Cox-Ross-Rubinstein binomial tree, European or American exercise."""
from __future__ import annotations

import numpy as np


def price(S, K, T, r, sigma, kind="call", q=0.0, steps=500, american=False):
    """Price by backward induction on a CRR tree.

    With american=True the holder may exercise at every node, which matters for
    puts (and for calls when q > 0). Converges to Black-Scholes at rate O(1/steps)
    for European options.
    """
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")
    dt = T / steps
    u = np.exp(sigma * np.sqrt(dt))
    d = 1.0 / u
    p = (np.exp((r - q) * dt) - d) / (u - d)
    if not 0.0 < p < 1.0:
        raise ValueError("arbitrage in tree: increase steps or check inputs")
    disc = np.exp(-r * dt)
    j = np.arange(steps + 1)
    spot = S * u ** (steps - j) * d ** j               # terminal prices, highest first
    payoff = (lambda s: np.maximum(s - K, 0.0)) if kind == "call" else (lambda s: np.maximum(K - s, 0.0))
    v = payoff(spot)
    for _ in range(steps - 1, -1, -1):
        v = disc * (p * v[:-1] + (1 - p) * v[1:])
        if american:
            spot = spot[:-1] / u                       # prices at step n
            v = np.maximum(v, payoff(spot))
    return float(v[0])


def early_exercise_premium(S, K, T, r, sigma, kind="put", q=0.0, steps=500):
    """American minus European price on the same tree."""
    return (price(S, K, T, r, sigma, kind, q, steps, american=True)
            - price(S, K, T, r, sigma, kind, q, steps, american=False))
