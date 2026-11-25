"""Black-Scholes-Merton for European options on an asset with continuous yield q.

Conventions: S spot, K strike, T years to expiry, r risk-free rate, q dividend
yield, sigma volatility (all annualised, continuously compounded). `kind` is
"call" or "put". Functions accept NumPy arrays and broadcast.
"""
from __future__ import annotations

from math import erf, sqrt

import numpy as np

_SQRT2 = sqrt(2.0)
try:  # SciPy's C implementation is ~50x faster; the pure-Python fallback keeps it optional
    from scipy.special import ndtr as _ndtr
except ImportError:  # pragma: no cover
    _ERF = np.vectorize(erf, otypes=[float])

    def _ndtr(x):
        return 0.5 * (1.0 + _ERF(np.asarray(x, dtype=float) / _SQRT2))


def norm_cdf(x):
    return _ndtr(np.asarray(x, dtype=float))


def norm_pdf(x):
    x = np.asarray(x, dtype=float)
    return np.exp(-0.5 * x * x) / np.sqrt(2.0 * np.pi)


def _d1_d2(S, K, T, r, q, sigma):
    S, K, T, sigma = (np.asarray(a, dtype=float) for a in (S, K, T, sigma))
    vt = sigma * np.sqrt(T)
    d1 = (np.log(S / K) + (r - q + 0.5 * sigma**2) * T) / vt
    return d1, d1 - vt


def _check(kind):
    if kind not in ("call", "put"):
        raise ValueError("kind must be 'call' or 'put'")


def price(S, K, T, r, sigma, kind="call", q=0.0):
    """Black-Scholes-Merton price. At T <= 0 returns intrinsic value."""
    _check(kind)
    T = np.asarray(T, dtype=float)
    intrinsic = np.maximum(S - K, 0.0) if kind == "call" else np.maximum(K - S, 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        d1, d2 = _d1_d2(S, K, np.maximum(T, 1e-12), r, q, sigma)
        df_q, df_r = np.exp(-q * T), np.exp(-r * T)
        if kind == "call":
            p = S * df_q * norm_cdf(d1) - K * df_r * norm_cdf(d2)
        else:
            p = K * df_r * norm_cdf(-d2) - S * df_q * norm_cdf(-d1)
    out = np.where(T <= 0, intrinsic, p)
    return float(out) if np.ndim(out) == 0 else out


def greeks(S, K, T, r, sigma, kind="call", q=0.0):
    """Analytic Greeks. Vega and rho are per 1.00 change (divide by 100 for per 1%).

    Theta is per year (divide by 365 for per calendar day).
    """
    _check(kind)
    d1, d2 = _d1_d2(S, K, T, r, q, sigma)
    df_q, df_r = np.exp(-q * T), np.exp(-r * T)
    sqrt_t = np.sqrt(T)
    gamma = df_q * norm_pdf(d1) / (S * sigma * sqrt_t)
    vega = S * df_q * norm_pdf(d1) * sqrt_t
    common = -S * df_q * norm_pdf(d1) * sigma / (2 * sqrt_t)
    if kind == "call":
        delta = df_q * norm_cdf(d1)
        theta = common - r * K * df_r * norm_cdf(d2) + q * S * df_q * norm_cdf(d1)
        rho = K * T * df_r * norm_cdf(d2)
    else:
        delta = -df_q * norm_cdf(-d1)
        theta = common + r * K * df_r * norm_cdf(-d2) - q * S * df_q * norm_cdf(-d1)
        rho = -K * T * df_r * norm_cdf(-d2)
    out = dict(delta=delta, gamma=gamma, vega=vega, theta=theta, rho=rho)
    return {k: float(v) if np.ndim(v) == 0 else v for k, v in out.items()}


def parity_gap(call, put, S, K, T, r, q=0.0):
    """Put-call parity residual C - P - (S e^{-qT} - K e^{-rT}); zero if consistent."""
    return call - put - (S * np.exp(-q * T) - K * np.exp(-r * T))
