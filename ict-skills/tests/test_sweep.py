"""Offline tests for sweep.py on hand-built 5m sessions."""
import importlib.util
import os
import sys
import unittest
from datetime import time as T

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("sweep", os.path.join(ROOT, "ict-india", "sweep.py"))
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)


def session(path):
    """75 five-minute bars from 09:15; path maps bar index -> (o, h, l, c), the rest are flat at 100."""
    out = []
    for k in range(75):
        m = 15 + 5 * k
        o, h, l, c = path.get(k, (100, 100.2, 99.8, 100))
        out.append((T(9 + m // 60, m % 60), o, h, l, c))
    return out


class TestSweep(unittest.TestCase):
    def test_sweep_and_reclaim_short_hits_target(self):
        bars = session({4: (100, 101.0, 99.9, 100.5),       # 09:35 sweeps the 100.2 high
                        5: (100.5, 100.6, 99.5, 99.6),       # 09:40 closes back below: short at 99.6
                        9: (99.6, 99.6, 96.0, 96.2)})        # 10:00 reaches the 2R target
        tr = S.trade_day(bars, 100.2, 99.8, 0.0, T(9, 30))
        self.assertEqual((tr["side"], tr["entry_time"], tr["entry"], tr["stop"]), ("short", "09:40", 99.6, 101.0))
        self.assertEqual((tr["exit"], tr["r"]), ("target", 2.0))

    def test_buffer_widens_the_stop(self):
        bars = session({4: (100, 101.0, 99.9, 99.9)})        # sweep and reclaim in one bar
        tr = S.trade_day(bars, 100.2, 99.8, 0.001, T(9, 30))
        self.assertAlmostEqual(tr["stop"], 101.1, places=2)

    def test_no_reclaim_within_six_bars_means_no_trade(self):
        path = {k: (101, 101.5, 100.9, 101.2) for k in range(4, 20)}      # breaks out and stays above
        tr = S.trade_day(session(path), 100.2, 99.8, 0.0, T(9, 30))
        self.assertIsNone(tr)

    def test_stop_is_taken_first_inside_a_bar(self):
        bars = session({4: (100, 101.0, 99.9, 99.9), 6: (99.9, 101.5, 96.0, 97.0)})
        tr = S.trade_day(bars, 100.2, 99.8, 0.0, T(9, 30))
        self.assertEqual((tr["exit"], tr["r"]), ("stop", -1.0))

    def test_no_entry_inside_the_opening_range(self):
        bars = session({1: (100, 101.0, 99.9, 99.9),         # 09:20: sweep and close back inside, too early
                        5: (100, 100.8, 99.9, 99.95)})        # 09:40: a new sweep and reclaim, tradable
        tr = S.trade_day(bars, 100.2, 99.8, 0.0, T(9, 15))  # previous-day level: sweeps count from 09:15
        self.assertEqual((tr["entry_time"], tr["stop"]), ("09:40", 100.8))

    def test_unresolved_trade_exits_at_1510(self):
        bars = session({4: (100, 101.0, 99.9, 99.9)})        # short at 99.9, risk 1.1, flat at 100 afterwards
        tr = S.trade_day(bars, 100.2, 99.8, 0.0, T(9, 30))
        self.assertEqual(tr["exit"], "close")
        self.assertAlmostEqual(tr["r"], (99.9 - 100) / 1.1, places=3)


if __name__ == "__main__":
    unittest.main()
