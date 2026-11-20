import pytest

from quantlab.costs import cost_per_side, india_cost, round_trip_bps


def test_delivery_round_trip_matches_statutory_charges():
    # STT 0.1% each side + 0.015% stamp + exchange/SEBI with GST + 5 bps slippage each side
    expected = (0.001 + 0.001 + 0.00015 + 2 * (0.0000297 + 0.000001) * 1.18 + 2 * 0.0005) * 1e4
    assert round_trip_bps("equity_delivery") == pytest.approx(expected)


def test_futures_stt_is_sell_side_only():
    assert india_cost("futures", "sell") - india_cost("futures", "buy") == pytest.approx(0.0005 - 0.00002)


def test_override_and_us_costs():
    assert cost_per_side("in", "etf", override_bps=10) == (0.001, 0.001)
    assert cost_per_side("us", None) == (0.0005, 0.0005)
