"""Offline tests for pulse.py: reading a PulsEdge pre-market file against the fade's direction."""
import importlib.util
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "ict-india"))
spec = importlib.util.spec_from_file_location("pulse", os.path.join(ROOT, "ict-india", "pulse.py"))
P = importlib.util.module_from_spec(spec)
spec.loader.exec_module(P)

PM = {"date": "2026-11-13", "sentiment": "Mildly bearish",
      "checklist": [{"title": "Nifty 50 last close", "dir": "down"}, {"title": "US close", "dir": "down"},
                    {"title": "Asia", "dir": "flat"}, {"title": "DXY", "dir": "flat"},
                    {"title": "Brent", "dir": "flat"}, {"title": "India VIX", "dir": "up"}]}


class TestPulse(unittest.TestCase):
    def test_counts_and_agreement(self):
        r = P.reading(PM, "PE")
        self.assertEqual((r["lean"], r["up"], r["down"], r["flat"], r["agree"]), ("bear", 1, 2, 3, True))
        self.assertFalse(P.reading(PM, "CE")["agree"])

    def test_neutral_sentiment_neither_agrees_nor_disagrees(self):
        self.assertIsNone(P.reading(dict(PM, sentiment="Neutral"), "PE")["agree"])
        self.assertEqual(P.lean("Bullish"), "bull")


if __name__ == "__main__":
    unittest.main()
