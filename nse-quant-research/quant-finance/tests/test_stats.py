import numpy as np
import pandas as pd

from quantlab.stats import adf_stat, fmt_money, ols, perf_stats


def test_ols_recovers_known_coefficients():
    rng = np.random.default_rng(0)
    x = rng.standard_normal(5000)
    y = 2.0 + 3.0 * x + 0.1 * rng.standard_normal(5000)
    coef, resid, se = ols(y, x)
    assert np.allclose(coef, [2.0, 3.0], atol=0.01)
    assert abs(resid.mean()) < 1e-10


def test_adf_separates_stationary_from_random_walk():
    rng = np.random.default_rng(1)
    e = rng.standard_normal(2000)
    ar = np.zeros(2000)
    for t in range(1, 2000):
        ar[t] = 0.9 * ar[t - 1] + e[t]
    assert adf_stat(ar) < -3.5             # rejects unit root
    assert adf_stat(np.cumsum(e)) > -2.9   # cannot reject for a random walk


def test_perf_stats_constant_return():
    r = pd.Series([0.001] * 252 + [0.0011] * 252)
    s = perf_stats(r, rf=0.0)
    assert s["MaxDD"] == 0
    expected = np.sqrt(1.001 ** 252 * 1.0011 ** 252) - 1   # two years, compounded
    assert np.isclose(s["CAGR"], expected)


def test_fmt_money_uses_lakh_and_crore():
    assert fmt_money(5_88_000, "Rs") == "Rs 5.88 lakh"
    assert fmt_money(1_00_00_000, "Rs") == "Rs 1.00 cr"
