import numpy as np
import pandas as pd

from quantlab.trend import ma, run_rule


def _prices(n=600, seed=0):
    rng = np.random.default_rng(seed)
    return pd.Series(100 * np.exp(np.cumsum(0.0005 + 0.01 * rng.standard_normal(n))),
                     index=pd.bdate_range("2020-01-01", periods=n))


def test_ema_and_sma_lengths():
    px = _prices()
    assert ma(px, 50, "SMA").isna().sum() == 49
    assert ma(px, 1, "EMA").equals(px)


def test_no_look_ahead():
    """Changing tomorrow's price must not change today's strategy return."""
    px = _prices()
    ret = px.pct_change().fillna(0)
    r1, _ = run_rule(px, ret, 20, 50, "SMA", 0.001, 0.001, 0.0, 50)
    px2 = px.copy()
    px2.iloc[-1] *= 2
    r2, _ = run_rule(px2, px2.pct_change().fillna(0), 20, 50, "SMA", 0.001, 0.001, 0.0, 50)
    assert np.allclose(r1.iloc[:-1], r2.iloc[:-1])


def test_costs_reduce_returns_and_cash_earns_yield():
    px = _prices()
    ret = px.pct_change().fillna(0)
    free, pos = run_rule(px, ret, 5, 20, "EMA", 0, 0, 0.0, 20)
    costly, _ = run_rule(px, ret, 5, 20, "EMA", 0.01, 0.01, 0.0, 20)
    assert costly.sum() < free.sum()
    flat = pos == 0
    with_cash, _ = run_rule(px, ret, 5, 20, "EMA", 0, 0, 0.0002, 20)
    assert np.allclose((with_cash - free)[flat], 0.0002)
