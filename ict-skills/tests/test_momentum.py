"""Offline tests for momentum.py: ranking, the 200-day filter and the monthly paper result."""
import importlib.util
import os
import sys
import unittest
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("momentum", os.path.join(ROOT, "ict-india", "momentum.py"))
M = importlib.util.module_from_spec(spec)
spec.loader.exec_module(M)

DATES = [date(2025, 1, 1) + timedelta(days=k) for k in range(300)]


def series(daily_growth, jump_last_month=0.0):
    """A stock growing by daily_growth a day; jump_last_month is added over the last 21 days only."""
    cs, c = [], 100.0
    for k in range(300):
        c *= 1 + daily_growth + (jump_last_month if k >= 300 - 21 else 0)
        cs.append(c)
    return (DATES, cs)


class TestMomentum(unittest.TestCase):
    def test_rank_uses_12_months_and_skips_the_last_month(self):
        stocks = {"FAST": series(0.002), "SLOW": series(0.0005), "LATE": series(0.0, jump_last_month=0.02)}
        top = M.rank(stocks, DATES, 299, top=3)
        self.assertEqual([s for s, _ in top], ["FAST", "SLOW", "LATE"])   # LATE's jump is in the skipped month
        self.assertEqual(M.rank(stocks, DATES, 100), [])                   # not enough history

    def test_200_day_filter(self):
        up = [100 + k for k in range(250)]
        self.assertTrue(M.above_average(up, 249))
        self.assertFalse(M.above_average(list(reversed(up)), 249))
        self.assertFalse(M.above_average(up, 150))                         # not enough history

    def test_month_result_costs_and_cash(self):
        stocks = {"A": ([date(2026, 12, 31)], [110.0]), "B": ([date(2026, 12, 31)], [90.0])}
        row = {"invested": True, "picks": [{"sym": "A", "close": 100.0}, {"sym": "B", "close": 100.0}]}
        r = M.month_result(row, None, stocks, date(2026, 12, 31))       # both names new: turnover 100%
        self.assertAlmostEqual(r, 0.0 - M.COST)
        before = {"invested": True, "picks": [{"sym": "A"}, {"sym": "C"}]}
        self.assertAlmostEqual(M.month_result(row, before, stocks, date(2026, 12, 31)), -0.5 * M.COST)
        self.assertEqual(M.month_result({"invested": False, "picks": []}, None, stocks, date(2026, 12, 31)), M.CASH_MONTH)


if __name__ == "__main__":
    unittest.main()
