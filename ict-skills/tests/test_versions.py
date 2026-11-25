"""Offline tests for versions.py: the exit rules on hand-made option paths (entry 100)."""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("versions", os.path.join(ROOT, "ict-india", "versions.py"))
V = importlib.util.module_from_spec(spec)
spec.loader.exec_module(V)

UP_THEN_DIP = [(99, 117, 116), (106, 112, 107), (106, 145, 144), (130, 160, 150)]   # add, dip to 106, target
UP_AND_FADE = [(99, 117, 116), (101, 104, 102), (90, 95, 91)]                          # add, then back down


class TestExits(unittest.TestCase):
    def test_pyramid_avg_is_stopped_at_the_average(self):
        pts, fills = V.run_exit("V1 pyramid-avg", 100.0, UP_THEN_DIP)
        self.assertAlmostEqual(pts, 0.0)                      # (107.5-100) + (107.5-115)
        self.assertEqual(fills, 4)

    def test_pyramid_keep_rides_to_the_target(self):
        pts, _ = V.run_exit("V2 pyramid-keep", 100.0, UP_THEN_DIP)
        self.assertAlmostEqual(pts, (140 - 100) + (140 - 115))

    def test_quick_takes_15_percent(self):
        self.assertAlmostEqual(V.run_exit("V4 quick", 100.0, UP_AND_FADE)[0], 15.0)

    def test_plain_closes_at_the_last_price(self):
        self.assertAlmostEqual(V.run_exit("V3 plain", 100.0, UP_AND_FADE)[0], -9.0)

    def test_trail_moves_the_stop_to_25_percent_and_rides(self):
        path = [(99, 141, 140), (126, 160, 158), (124, 130, 125)]
        self.assertAlmostEqual(V.run_exit("V6 plain-trail", 100.0, path)[0], 25.0)      # stopped at +25%
        self.assertAlmostEqual(V.run_exit("V6 plain-trail", 100.0, path[:2])[0], 58.0)  # rode to the close
        self.assertAlmostEqual(V.run_exit("V3 plain", 100.0, path)[0], 40.0)

    def test_plain_close_has_no_target(self):
        path = [(99, 141, 140), (130, 160, 158)]
        self.assertAlmostEqual(V.run_exit("V7 plain-close", 100.0, path)[0], 58.0)

    def test_stop_comes_first_inside_a_bar(self):
        self.assertAlmostEqual(V.run_exit("V3 plain", 100.0, [(79, 150, 120)])[0], -20.0)


if __name__ == "__main__":
    unittest.main()
