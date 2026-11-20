import numpy as np

from quantlab.risk import sim_paths, simulate, var_backtest, var_es


def test_var_es_of_standard_normal():
    pnl = np.random.default_rng(0).standard_normal(400_000)
    var, es = var_es(pnl, 0.95)
    assert abs(var - 1.645) < 0.02
    assert abs(es - 2.063) < 0.02   # phi(1.645) / 0.05
    assert es > var


def test_correlation_increases_portfolio_var():
    rng = np.random.default_rng(2)
    mu, vol, w = np.zeros(3), np.full(3, 0.01), np.full(3, 1 / 3)
    var = {}
    for rho in (0.0, 0.9):
        c = np.full((3, 3), rho) + np.eye(3) * (1 - rho)
        var[rho] = var_es(simulate(mu, np.outer(vol, vol) * c, w, 20_000, 21, rng), 0.95)[0]
    assert var[0.9] > 1.5 * var[0.0]


def test_student_t_shocks_have_unit_variance():
    hist = np.random.default_rng(3).standard_normal((500, 2)) * 0.01
    out = sim_paths(hist, "student-t", np.random.default_rng(4))
    assert np.allclose(out.std(0), 0.01 * np.sqrt(21), rtol=0.05)


def test_backtest_breach_rate_is_calibrated_on_iid_normal_data():
    logret = np.random.default_rng(5).standard_normal((252 + 21 * 300, 1)) * 0.01
    df, _ = var_backtest(logret, np.array([1.0]), methods=("normal",))
    rate = (df.actual < -df[("normal", 95)]).mean()
    assert 0.02 < rate < 0.09
