"""Offline tests for liquidity.py: the sweep -> IFVG -> retest entry and the multi-day spring, on hand-made bars."""
import importlib.util
import os
import sys
import unittest
from datetime import date, time as T, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("liquidity", os.path.join(ROOT, "ict-india", "liquidity.py"))
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def session(rows):
    """5m bars from 09:15 out of (o, h, l, c) rows."""
    out, m = [], 9 * 60 + 15
    for o, h, l, c in rows:
        out.append((T(m // 60, m % 60), o, h, l, c))
        m += 5
    return out


OR = [(105, 110, 100, 106), (106, 109, 101, 104), (104, 108, 102, 104)]          # opening range 100-110
DROP = [(104, 105, 101, 101),        # 09:30
        (101, 101, 97, 98),          # 09:35
        (98, 99, 94, 95),            # 09:40 sweeps 100; FVG 99-101 (09:30 low above 09:40 high)
        (95, 103, 95, 102)]          # 09:45 closes above 101: the FVG is inverted
RUN = [(102, 106, 102, 105),         # 09:50
       (105, 105, 100.5, 104),       # 09:55 back to the IFVG top 101: long fills at 101, stop 94 (risk 7)
       (104, 109, 103, 108),
       (108, 116, 107, 115)]         # 10:05 reaches 115 = 2R


class TestIntraday(unittest.TestCase):
    def test_sweep_inversion_and_retest_fill(self):
        bars = session(OR + DROP + RUN)
        self.assertEqual(L.long_setup(bars, 100, T(9, 30)), (8, 101, 94, None))
        tr = L.trade_day(bars, 110, 100, T(9, 30))
        self.assertEqual((tr["side"], tr["entry_time"], tr["entry"], tr["stop"], tr["exit"], tr["r"]),
                         ("long", "09:55", 101, 94, "target", 2.0))

    def test_entry_bar_can_only_stop(self):
        bars = session(OR + DROP + [(102, 106, 102, 105), (103, 104, 93, 95), (95, 130, 95, 128)])
        tr = L.trade_day(bars, 110, 100, T(9, 30))
        self.assertEqual((tr["entry"], tr["exit"], tr["r"]), (101, "stop", -1.0))

    def test_no_inversion_no_trade(self):
        flat = [(95, 99.5, 95, 99)] * 14                  # never closes above the FVG top of 101
        self.assertIsNone(L.long_setup(session(OR + DROP[:3] + flat), 100, T(9, 30)))

    def test_short_is_the_mirror(self):
        mirror = [(t, 200 - o, 200 - l, 200 - h, 200 - c) for t, o, h, l, c in session(OR + DROP + RUN)]
        tr = L.trade_day(mirror, 100, 90, T(9, 30))       # the mirrored opening range is 90-100
        self.assertEqual((tr["side"], tr["entry"], tr["stop"], tr["r"]), ("short", 99, 106, 2.0))

    def test_closes_at_the_last_bar_without_target_or_stop(self):
        bars = session(OR + DROP + RUN[:2] + [(104, 105, 103, 104.5)])
        self.assertAlmostEqual(L.trade_day(bars, 120, 100, T(9, 30))["r"], 3.5 / 7, places=3)


class TestSwingEntries(unittest.TestCase):
    """Aditya's two entries (27 Nov 2026): the inversion candle's close, or a tap of the IFVG top on the next candle;
    target the previous swing high, stop to break-even at +1R."""
    def test_close_entry_targets_the_high_before_the_sweep(self):
        bars = session(OR + DROP + RUN)
        self.assertEqual(L.long_setup(bars, 100, T(9, 30), "close"), (6, 102, 94, 110))
        tr = L.trade_day(bars, 120, 100, T(9, 30), "close")
        self.assertEqual((tr["entry_time"], tr["entry"], tr["target"], tr["exit"], tr["r"]), ("09:45", 102, 110, "target", 1.0))

    def test_tap_only_on_the_next_candle(self):
        self.assertIsNone(L.long_setup(session(OR + DROP + RUN), 100, T(9, 30), "tap"))      # 09:50 low 102 never taps 101
        bars = session(OR + DROP + [(102, 104, 100.8, 103)] + RUN[1:])
        tr = L.trade_day(bars, 120, 100, T(9, 30), "tap")
        self.assertEqual((tr["entry_time"], tr["entry"], tr["exit"]), ("09:50", 101, "target"))
        self.assertAlmostEqual(tr["r"], 9 / 7, places=2)

    def test_stop_moves_to_break_even_at_1r(self):
        bars = session(OR + DROP + [(102, 104, 100.8, 103), (103, 109, 103, 108), (108, 108, 99, 100)])
        tr = L.trade_day(bars, 120, 100, T(9, 30), "tap")
        self.assertEqual((tr["exit"], tr["r"]), ("breakeven", 0.0))

    def test_swing_target_is_the_latest_pivot_above_the_entry(self):
        bars = session([(0, h, 0, 0) for h in (100, 101, 105, 102, 101, 99, 98)])
        self.assertEqual(L.swing_target(bars, 6, 103), 105)
        self.assertIsNone(L.swing_target(bars, 6, 106))


class TestDaily(unittest.TestCase):
    def bars(self, last):
        d0 = date(2026, 1, 1)
        rows = [(d0 + timedelta(days=k), 102, 104, 100, 102) for k in range(25)]
        return rows + [(d0 + timedelta(days=25),) + last]

    def test_spring_needs_a_close_back_above_the_low(self):
        self.assertEqual(L.daily_events(self.bars((101, 102, 99, 101)), "spring-20"), [(25, 1)])
        self.assertEqual(L.daily_events(self.bars((101, 102, 99, 99.5)), "spring-20"), [])

    def test_upthrust_needs_a_tight_range(self):
        self.assertEqual(L.daily_events(self.bars((103, 105, 102, 103)), "upthrust-20"), [(25, -1)])
        wide = [(date(2026, 1, 1) + timedelta(days=k), 100, 120 if k == 10 else 104, 100, 102) for k in range(25)]
        wide.append((date(2026, 1, 26), 103, 125, 102, 103))
        self.assertEqual(L.daily_events(wide, "upthrust-20"), [])      # 20-day range 20% > 6%

    def test_one_hold_at_a_time(self):
        ev = [(30, 1), (31, 1), (39, 1), (40, 1), (52, 1)]
        self.assertEqual(L.one_at_a_time(ev), [(30, 1), (40, 1), (52, 1)])     # holds last HOLD = 10 sessions


if __name__ == "__main__":
    unittest.main()
