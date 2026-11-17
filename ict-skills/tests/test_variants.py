"""Offline tests for variants.py: which version trades, and how a trade is scored."""
import importlib.util
import os
import sys
import unittest
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("variants", os.path.join(ROOT, "ict-india", "variants.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)


def daily(closes, today_open):
    """Daily bars {date: (date, o, h, l, c)}: closes for earlier days, then today opening at today_open."""
    d, day = {}, date(2026, 11, 2)
    for c in closes:
        d[day] = (day, c, c, c, c)
        day += timedelta(days=1)
    d[day] = (day, today_open, today_open, today_open, today_open)
    return d


class TestVariants(unittest.TestCase):
    def test_versions_follow_the_fade_and_the_gap(self):
        d = daily([100, 101, 102, 103, 104, 105, 106], 105.5)     # 5-day rise, gap down 0.47%: fade puts, gap puts
        days = sorted(d)
        s, gap = V.sides(days, d, len(days) - 1)
        self.assertEqual(s, {"fade": "PE", "fade-gap": "PE", "gap": "PE"})
        self.assertAlmostEqual(gap, -0.5 / 106)
        d = daily([100, 101, 102, 103, 104, 105, 106], 106.5)     # gap up: fade still puts, the gap says calls
        s, _ = V.sides(sorted(d), d, len(d) - 1)
        self.assertEqual(s, {"fade": "PE", "fade-gap": None, "gap": "CE"})
        d = daily([100, 101, 102, 103, 104, 105, 106], 106.05)    # flat open: only the plain fade trades
        s, _ = V.sides(sorted(d), d, len(d) - 1)
        self.assertEqual(s, {"fade": "PE", "fade-gap": None, "gap": None})

    def test_real_result_counts_the_stop_first(self):
        self.assertEqual(V.real_result(100, 150, 79, 120), (-0.2, "stop"))
        self.assertEqual(V.real_result(100, 141, 85, 120), (0.4, "target"))
        r, how = V.real_result(100, 130, 85, 110)
        self.assertAlmostEqual(r, 0.10)
        self.assertEqual(how, "close")

    def test_model_put_on_a_falling_day_reaches_target(self):
        t0 = datetime(2026, 11, 17, 9, 15)
        bars = [(t0 + timedelta(minutes=5 * k), 25000 - 6 * k, 25000 - 6 * k, 25000 - 6 * k - 6, 25000 - 6 * k - 6)
                for k in range(75)]
        m = V.model_result(bars, "PE", 24950, date(2026, 11, 23), 0.12)
        self.assertEqual(m[2], "target")
        self.assertIsNone(V.model_result(bars[:10], "PE", 24950, date(2026, 11, 23), 0.12))   # data ends before 10:15


if __name__ == "__main__":
    unittest.main()
