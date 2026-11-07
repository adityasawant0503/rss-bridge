"""Offline tests for optbt.py on synthetic index data."""
import importlib.util
import math
import os
import sys
import unittest
from datetime import date, datetime, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("optbt", os.path.join(ROOT, "ict-india", "optbt.py"))
O = importlib.util.module_from_spec(spec)
spec.loader.exec_module(O)


def trading_days(start, n):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    return out


class TestPieces(unittest.TestCase):
    def test_weekly_expiry_rules(self):
        self.assertEqual(O.weekly_expiry("NIFTY", date(2025, 8, 20), 4), date(2025, 8, 28))   # Thursday, old rule
        self.assertEqual(O.weekly_expiry("NIFTY", date(2025, 9, 8), 4), date(2025, 9, 16))    # Tuesday from Sep 2025
        self.assertEqual(O.weekly_expiry("SENSEX", date(2025, 8, 4), 4), date(2025, 8, 12))   # Tuesday, old rule
        self.assertEqual(O.weekly_expiry("SENSEX", date(2025, 9, 8), 4), date(2025, 9, 18))   # Thursday from Sep 2025

    def test_lot_sizes(self):
        self.assertEqual(O.lot_size("NIFTY", date(2025, 6, 2)), 75)
        self.assertEqual(O.lot_size("NIFTY", date(2026, 2, 2)), 65)
        self.assertEqual(O.lot_size("SENSEX", date(2026, 2, 2)), 20)

    def test_put_call_parity(self):
        S, K, tau, vol, r = 25000.0, 25100.0, 5 / 365, 0.12, 0.065
        c, p = O.bs(S, K, tau, vol, "CE", r), O.bs(S, K, tau, vol, "PE", r)
        self.assertAlmostEqual(c - p, S - K * math.exp(-r * tau), places=6)
        self.assertEqual(O.bs(S, K, 0, vol, "PE"), 100.0)

    def test_bias(self):
        days = trading_days(date(2026, 3, 2), 8)
        d = {day: (datetime.combine(day, datetime.min.time()), 0, 0, 0, 100.0 + k) for k, day in enumerate(days)}
        self.assertEqual(O.bias_for(days, d, 7, "fade"), "PE")         # five days up: fade with puts
        self.assertEqual(O.bias_for(days, d, 7, "with"), "CE")


class TestSimulate(unittest.TestCase):
    def build(self, last_day_path):
        """Seven rising days, then a day whose hourly closes follow last_day_path."""
        days = trading_days(date(2026, 3, 2), 8)
        d, hourly = {}, []
        for k, day in enumerate(days):
            base = 22000.0 + 50 * k
            path = last_day_path if k == len(days) - 1 else [base] * 7
            for h, close in enumerate(path):
                t = datetime.combine(day, datetime.min.time()).replace(hour=9 + h, minute=15)
                o = path[h - 1] if h else close
                hourly.append((t, o, max(o, close), min(o, close), close))
            d[day] = (datetime.combine(day, datetime.min.time()), path[0], max(path), min(path), path[-1])
        vix = {day: (None, 0, 0, 0, 12.0) for day in days}
        return days, d, hourly, vix

    def test_fade_put_hits_target_on_a_drop(self):
        days, d, hourly, vix = self.build([22350, 22350, 22100, 21900, 21800, 21800, 21800])
        p = dict(O.DEFAULTS, stop=0.3, target=0.5)
        trades = O.simulate("NIFTY", hourly, d, vix, p, start=days[-1])
        self.assertEqual(len(trades), 1)
        t = trades[0]
        self.assertEqual((t["kind"], t["strike"], t["why"], t["lot"]), ("PE", 22350.0, "target", 65))
        self.assertGreater(t["pnl"], 0)

    def test_fade_put_stopped_on_a_rally(self):
        days, d, hourly, vix = self.build([22350, 22350, 22600, 22800, 22900, 22900, 22900])
        trades = O.simulate("NIFTY", hourly, d, vix, dict(O.DEFAULTS), start=days[-1])
        self.assertEqual(trades[0]["why"], "stop")
        self.assertAlmostEqual(trades[0]["pnl"], (trades[0]["entry"] * 0.7 - 1.0 - trades[0]["entry"]) * 65 - 40, delta=1.0)


class TestAdding(unittest.TestCase):
    P = dict(O.DEFAULTS, stop=0.2, target=0.4, slippage=0.0)

    def run_path(self, prices, **kw):
        """Bars whose worst/best/close premiums are given directly: (worst, best, close)."""
        p = dict(self.P, **kw)
        price = lambda S, tau: S
        bars = [((None, 0, best, worst, close), 1.0) for worst, best, close in prices]   # CE: low=worst, high=best
        return O.manage(p, 100.0, bars, price, "CE")

    def test_pyramid_adds_then_protects_at_break_even(self):
        exit_px, why, fills = self.run_path([(99, 116, 115), (114, 120, 118), (107, 109, 108)],
                                            add_mode="up", max_lots=2, add_step=0.15)
        self.assertEqual([round(f, 6) for f in fills], [100.0, 115.0])
        self.assertEqual((why, round(exit_px, 6)), ("stop", 107.5))             # stop moved to the average of 100 and 115

    def test_pyramid_target_is_from_the_first_price(self):
        exit_px, why, fills = self.run_path([(99, 116, 115), (114, 141, 140)], add_mode="up", max_lots=2, add_step=0.15)
        self.assertEqual((why, round(exit_px, 6), len(fills)), ("target", 140.0, 2))

    def test_average_down_adds_and_uses_one_hard_stop(self):
        exit_px, why, fills = self.run_path([(84, 101, 85), (69, 86, 70), (54, 71, 55)],
                                            add_mode="down", max_lots=3, add_step=0.15, hard_stop=0.45)
        self.assertEqual([round(f, 6) for f in fills], [100.0, 85.0, 70.0])
        self.assertEqual((why, round(exit_px, 6)), ("stop", 55.0))

    def test_no_adding_is_the_plain_trade(self):
        self.assertEqual(self.run_path([(79, 101, 80)]), (80.0, "stop", [100.0]))


if __name__ == "__main__":
    unittest.main()
