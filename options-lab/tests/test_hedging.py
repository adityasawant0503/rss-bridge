import numpy as np

from optlab.hedging import gbm_paths, hedge_pnl, realised_vol


def test_hedging_error_shrinks_with_frequency():
    paths = gbm_paths(100, 0.25, 0.08, 0.2, 252, 4000, seed=1)
    sd = [hedge_pnl(paths, 100, 0.25, 0.05, 0.2, hedge_every=k).std() for k in (21, 5, 1)]
    assert sd[0] > sd[1] > sd[2]
    # error scales like 1/sqrt(number of rebalances): 21x more rebalances -> ~sqrt(21) smaller
    assert 2.5 < sd[0] / sd[2] < 7


def test_correctly_priced_hedge_has_near_zero_mean():
    paths = gbm_paths(100, 0.25, 0.10, 0.2, 252, 4000, seed=2)
    pnl = hedge_pnl(paths, 100, 0.25, 0.05, 0.2)
    assert abs(pnl.mean()) < 3 * pnl.std() / np.sqrt(len(pnl)) + 1e-4


def test_selling_above_realised_vol_earns_money():
    paths = gbm_paths(100, 0.25, 0.05, 0.15, 252, 2000, seed=3)
    assert hedge_pnl(paths, 100, 0.25, 0.05, 0.25).mean() > 0
    assert hedge_pnl(paths, 100, 0.25, 0.05, 0.10).mean() < 0


def test_costs_reduce_pnl():
    paths = gbm_paths(100, 0.25, 0.05, 0.2, 252, 1000, seed=4)
    free = hedge_pnl(paths, 100, 0.25, 0.05, 0.2)
    costly = hedge_pnl(paths, 100, 0.25, 0.05, 0.2, cost=0.001)
    assert (costly < free).all()


def test_realised_vol():
    p = gbm_paths(100, 10, 0.0, 0.3, 2520, 1, seed=5)[0]
    assert abs(realised_vol(p) - 0.3) < 0.02
