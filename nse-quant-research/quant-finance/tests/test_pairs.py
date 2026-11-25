import numpy as np
import pandas as pd

from quantlab.data import synthetic_pair
from quantlab.pairs import backtest, eg, leg_cost
from quantlab.stats import ols


def test_synthetic_pair_is_cointegrated_and_profitable():
    px = synthetic_pair(["A", "B"])
    stat, _ = eg(px["A"], px["B"])
    assert stat < -3.34
    coef, _, _ = ols(px["A"].values, px["B"].values)
    r, pos, _ = backtest(px, coef[1], coef[0], 0.0005, 0.0005)
    assert set(np.unique(pos)) <= {-1.0, 0.0, 1.0}
    assert r.mean() > 0


def test_positions_are_lagged_one_day():
    px = synthetic_pair(["A", "B"])
    coef, _, _ = ols(px["A"].values, px["B"].values)
    _, pos, _ = backtest(px, coef[1], coef[0], 0, 0)
    assert pos.iloc[0] == 0
    # perturbing the last price cannot change any position up to and including that day
    px2 = px.copy()
    px2.iloc[-1, 0] *= 1.5
    _, pos2, _ = backtest(px2, coef[1], coef[0], 0, 0)
    assert pos.equals(pos2)


def test_leg_cost_charges_buys_and_sells_separately():
    exp = pd.Series([0.0, 0.5, 0.5, -0.5])
    cost = leg_cost(exp, buy=0.01, sell=0.02)
    assert np.allclose(cost.values, [0, 0.005, 0, 0.02])
