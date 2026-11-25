import numpy as np
import pytest

from optlab import binomial, bs, iv, mc

BASE = dict(S=100.0, K=100.0, T=1.0, r=0.05, sigma=0.2)


def test_textbook_values():
    # Hull, Options Futures and Other Derivatives: S=K=100, T=1, r=5%, vol=20%
    assert bs.price(**BASE) == pytest.approx(10.4506, abs=1e-4)
    assert bs.price(**BASE, kind="put") == pytest.approx(5.5735, abs=1e-4)


@pytest.mark.parametrize("K", [80, 100, 120])
@pytest.mark.parametrize("q", [0.0, 0.013])
def test_put_call_parity(K, q):
    a = dict(BASE, K=K, q=q)
    c, p = bs.price(**a), bs.price(**a, kind="put")
    assert abs(bs.parity_gap(c, p, a["S"], K, a["T"], a["r"], q)) < 1e-10


@pytest.mark.parametrize("kind", ["call", "put"])
def test_binomial_converges_to_black_scholes(kind):
    exact = bs.price(**BASE, kind=kind, q=0.013)
    errs = [abs(binomial.price(**BASE, kind=kind, q=0.013, steps=n) - exact) for n in (100, 400, 1600)]
    assert errs[2] < 0.005
    assert errs[2] < errs[0]


def test_american_put_premium_positive_and_call_without_dividends_equals_european():
    assert binomial.early_exercise_premium(**BASE, kind="put") > 0.4
    amer_call = binomial.price(**BASE, american=True)
    assert amer_call == pytest.approx(binomial.price(**BASE), abs=1e-10)


@pytest.mark.parametrize("kind", ["call", "put"])
def test_monte_carlo_within_three_standard_errors(kind):
    est, se = mc.price(**BASE, kind=kind, n_paths=200_000, seed=3)
    assert abs(est - bs.price(**BASE, kind=kind)) < 3 * se


def test_variance_reduction_shrinks_standard_error():
    _, se_plain = mc.price(**BASE, antithetic=False, control_variate=False, seed=1)
    _, se_both = mc.price(**BASE, antithetic=True, control_variate=True, seed=1)
    assert se_both < 0.5 * se_plain


@pytest.mark.parametrize("name,bump", [("delta", "S"), ("vega", "sigma"), ("rho", "r")])
@pytest.mark.parametrize("kind", ["call", "put"])
def test_greeks_match_finite_differences(name, bump, kind):
    h = 1e-4
    up, dn = dict(BASE), dict(BASE)
    up[bump] += h
    dn[bump] -= h
    fd = (bs.price(**up, kind=kind) - bs.price(**dn, kind=kind)) / (2 * h)
    assert bs.greeks(**BASE, kind=kind)[name] == pytest.approx(fd, rel=1e-5)


def test_gamma_and_theta_by_finite_difference():
    h = 1e-2
    g = (bs.price(**dict(BASE, S=100 + h)) - 2 * bs.price(**BASE) + bs.price(**dict(BASE, S=100 - h))) / h**2
    assert bs.greeks(**BASE)["gamma"] == pytest.approx(g, rel=1e-4)
    th = -(bs.price(**dict(BASE, T=1 + 1e-5)) - bs.price(**dict(BASE, T=1 - 1e-5))) / 2e-5
    assert bs.greeks(**BASE)["theta"] == pytest.approx(th, rel=1e-5)


@pytest.mark.parametrize("sigma", [0.05, 0.2, 0.8])
@pytest.mark.parametrize("K", [70, 100, 140])
def test_implied_vol_round_trip(sigma, K):
    p = bs.price(100, K, 0.5, 0.06, sigma, "put", 0.013)
    solved = iv.implied_vol(p, 100, K, 0.5, 0.06, "put", 0.013)
    assert bs.price(100, K, 0.5, 0.06, solved, "put", 0.013) == pytest.approx(p, abs=1e-7)
    if bs.greeks(100, K, 0.5, 0.06, sigma, "put", 0.013)["vega"] > 1e-2:
        assert solved == pytest.approx(sigma, abs=1e-6)   # only identifiable when price moves with vol


def test_implied_vol_rejects_arbitrage_price():
    with pytest.raises(ValueError):
        iv.implied_vol(150.0, 100, 100, 1, 0.05)


def test_expired_option_is_intrinsic():
    assert bs.price(110, 100, 0.0, 0.05, 0.2) == 10.0
    assert bs.price(110, 100, 0.0, 0.05, 0.2, kind="put") == 0.0
    assert np.allclose(bs.price(np.array([90.0, 110.0]), 100, 0.0, 0.05, 0.2), [0, 10])
