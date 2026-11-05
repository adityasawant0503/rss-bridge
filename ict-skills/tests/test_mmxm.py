"""Offline tests for the MMXM engine, on hand-built sessions that follow the notes step by step.

    python3 -m unittest discover -s ict-skills/tests -v
"""
import importlib.util
import json
import os
import shutil
import tempfile
import unittest
from datetime import date, datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read(path):
    with open(path) as f:
        return f.read()


def utc(ts):
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)


def load(folder):
    spec = importlib.util.spec_from_file_location("mmxm_" + folder.replace("-", "_"), os.path.join(ROOT, folder, "mmxm.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    prof = mod.load_profile(os.path.join(ROOT, folder, "profile.json"))
    return mod, prof


US, US_P = load("ict-us-futures")
IN, IN_P = load("ict-india")

FLAT = (107.0, 107.2, 106.8, 107.0)

# The killzone: run above the London high, MSS with displacement, two FVGs, retrace, two confirmation
# candles, then the run to the London low. (o, h, l, c) every 5 minutes.
KILLZONE = [
    (107.0, 107.5, 106.8, 107.3),
    (107.3, 107.6, 106.9, 107.0),
    (107.0, 107.1, 106.5, 106.7),   # swing low 106.5, the MSS level
    (106.7, 108.0, 106.6, 107.9),
    (107.9, 108.8, 107.8, 108.7),
    (108.7, 109.6, 108.6, 109.4),   # takes the London high 109.0
    (109.4, 109.7, 109.0, 109.1),   # the high, 109.7
    (109.1, 109.2, 108.2, 108.3),
    (108.3, 108.4, 106.0, 106.2),   # displacement, closes below 106.5: MSS
    (106.2, 107.5, 105.6, 105.8),   # completes the lower FVG 107.5-108.2
    (105.8, 106.4, 105.7, 106.3),
    (106.3, 107.6, 106.2, 107.4),   # taps 107.5
    (107.4, 107.9, 107.0, 107.2),   # confirmation 1
    (107.2, 107.4, 106.6, 106.8),   # confirmation 2: enter at 106.8
    (106.8, 106.9, 105.9, 106.0),
    (106.0, 106.1, 105.4, 105.5),   # 70% of the way: stop cut by 25%
    (105.5, 105.6, 104.8, 104.9),   # London low 104.8: TP1
]
AFTER = (105.0, 105.3, 104.9, 105.0)


def us_bars(mod, prof, mirror_at=None):
    """Prior trading day Mon 19 Oct 2026 (Sun 18:00 to Mon 17:00 ET), then Tue 20 Oct."""
    tz = prof["tz"]
    bars = []

    def put(dt, o, h, l, c):
        if mirror_at:
            o, h, l, c = mirror_at - o, mirror_at - l, mirror_at - h, mirror_at - c
        bars.append(mod.Bar(mod.from_local(dt, tz), o, h, l, c, 0.0))

    t = datetime(2026, 10, 18, 18, 0)
    while t < datetime(2026, 10, 19, 17, 0):
        hl = (110.0, 105.0) if t.hour == 10 and t.minute == 0 else (106.0, 100.0) if t.hour == 14 and t.minute == 0 else (106.0, 105.0)
        put(t, 105.5, hl[0], hl[1], 105.5)
        t += timedelta(minutes=5)
    t = datetime(2026, 10, 19, 18, 0)
    while t < datetime(2026, 10, 20, 17, 0):
        m = t.hour * 60 + t.minute
        if 19 * 60 <= m < 21 * 60:
            put(t, 105.0, 105.5, 104.0, 105.0)            # Asia
        elif m == 120:
            put(t, 107.0, 109.0, 106.5, 107.0)            # London high
        elif m == 125:
            put(t, 107.0, 107.5, 104.8, 105.5)            # London low
        elif 510 <= m < 510 + 5 * len(KILLZONE):
            put(t, *KILLZONE[(m - 510) // 5])
        elif m >= 510 + 5 * len(KILLZONE) and t.day == 20:
            put(t, *AFTER)
        else:
            put(t, *FLAT)
        t += timedelta(minutes=5)
    return bars


def india_bars(mod, prof):
    tz = prof["tz"]
    bars = []
    put = lambda dt, o, h, l, c: bars.append(mod.Bar(mod.from_local(dt, tz), o, h, l, c, 0.0))
    t = datetime(2026, 10, 19, 9, 15)
    while t < datetime(2026, 10, 19, 15, 30):
        hl = (110.0, 105.0) if (t.hour, t.minute) == (10, 0) else (106.0, 100.0) if (t.hour, t.minute) == (14, 0) else (106.0, 105.0)
        put(t, 105.5, hl[0], hl[1], 105.5)
        t += timedelta(minutes=5)
    t = datetime(2026, 10, 20, 9, 15)
    while t < datetime(2026, 10, 20, 15, 30):
        m = t.hour * 60 + t.minute
        if m == 555:
            put(t, 107.0, 109.0, 106.5, 107.0)
        elif m == 560:
            put(t, 107.0, 107.5, 104.8, 105.5)
        elif 570 <= m < 570 + 5 * len(KILLZONE):
            put(t, *KILLZONE[(m - 570) // 5])
        elif m >= 570 + 5 * len(KILLZONE):
            put(t, *AFTER)
        else:
            put(t, *FLAT)
        t += timedelta(minutes=5)
    return bars


def run(mod, prof, bars, cfg_over=None, dirs=("short",), upto=None):
    cfg = dict(mod.DEFAULTS)
    cfg.update(prof.get("config_defaults", {}))
    cfg.update(cfg_over or {})
    mkt = mod.Market(prof, cfg)
    if upto is not None:
        bars = bars[:upto]
    di = mod.days_of(bars, mkt)
    day = list(di)[-1]
    htf = mod.resample(bars, 15, mkt)
    return mkt, mod.run_day(mkt, bars, day, di, htf, cfg, list(dirs))


class TestTime(unittest.TestCase):
    def test_new_york_dst(self):
        summer = US.from_local(datetime(2026, 10, 20, 9, 30), "America/New_York")
        winter = US.from_local(datetime(2026, 12, 1, 9, 30), "America/New_York")
        self.assertEqual(utc(summer).hour, 13)
        self.assertEqual(utc(winter).hour, 14)
        self.assertEqual(US.to_local(summer, "America/New_York"), datetime(2026, 10, 20, 9, 30))
        # DST ends Sunday 1 Nov 2026
        self.assertEqual(US.utc_offset("America/New_York", US.from_local(datetime(2026, 11, 2, 9, 0), "America/New_York")).total_seconds(), -5 * 3600)

    def test_ist(self):
        ts = IN.from_local(datetime(2026, 10, 20, 9, 15), "Asia/Kolkata")
        self.assertEqual(utc(ts), datetime(2026, 10, 20, 3, 45))

    def test_cme_trading_day(self):
        mkt = US.Market(US_P, dict(US.DEFAULTS))
        sun_evening = US.from_local(datetime(2026, 10, 18, 19, 0), mkt.tz)
        self.assertEqual(mkt.trading_day(sun_evening), date(2026, 10, 19))
        self.assertEqual(mkt.session_of(sun_evening), "asia")

    def test_india_15m_buckets_start_at_915(self):
        mkt = IN.Market(IN_P, dict(IN.DEFAULTS))
        h = IN.resample(india_bars(IN, IN_P), 15, mkt)
        firsts = [IN.to_local(b.t, mkt.tz) for b in h[:3]]
        self.assertEqual([(t.hour, t.minute) for t in firsts], [(9, 15), (9, 30), (9, 45)])


class TestPrimitives(unittest.TestCase):
    def test_fvg_three_candles(self):
        B = US.Bar
        bars = [B(0, 10, 11, 9.5, 10.5, 0), B(1, 10.5, 10.6, 8, 8.2, 0), B(2, 8.2, 9.0, 7.5, 7.8, 0)]
        g = US.bearish_fvgs(bars, 0, 3)
        self.assertEqual(len(g), 1)
        self.assertEqual((g[0]["lo"], g[0]["hi"]), (9.0, 9.5))
        bull = US.bearish_fvgs(US.mirror(list(reversed([B(0, *[20 - x for x in (b.o, b.l, b.h, b.c)], 0) for b in bars]))), 0, 3)
        self.assertEqual(len(bull), 0)

    def test_auto_bias(self):
        d = lambda h, l, c: {"h": h, "l": l, "c": c, "o": c}
        self.assertEqual(US.auto_bias([d(10, 5, 7), d(12, 6, 11)], 2)[0], "long")
        self.assertEqual(US.auto_bias([d(10, 5, 7), d(9, 4, 4.5)], 2)[0], "short")
        self.assertEqual(US.auto_bias([d(10, 5, 7), d(11, 6, 9)], 2)[0], "short")   # swept the high, closed inside
        self.assertEqual(US.auto_bias([d(10, 5, 7), d(9, 4, 8)], 2)[0], "long")     # swept the low, closed inside
        self.assertIsNone(US.auto_bias([d(10, 5, 7), d(9, 6, 8)], 2)[0])            # inside day


class TestModelUS(unittest.TestCase):
    def setUp(self):
        self.bars = us_bars(US, US_P)

    def trade(self, setups):
        t = [s for s in setups if "r" in s]
        self.assertEqual(len(t), 1, [(s["status"], s.get("reason")) for s in setups])
        return t[0]

    def test_full_sequence_confirm_mode(self):
        mkt, setups = run(US, US_P, self.bars)
        s = self.trade(setups)
        self.assertEqual(s["kz"], "ny_am")
        self.assertIn("london high", s["pools"])
        self.assertEqual(s["mss_level"], 106.5)
        self.assertEqual((s["fvg_lo"], s["fvg_hi"]), (107.5, 108.2))       # the nearer of the two FVGs
        self.assertEqual((s["entry"], s["stop"]), (107.5, 109.7))
        self.assertEqual((s["tp1"], s["tp1_name"]), (104.8, "london low"))
        self.assertEqual((s["tp2"], s["tp2_name"]), (104.0, "asia low"))
        self.assertEqual(s["fill"], 106.8)                                  # close of the 2nd candle after the tap
        self.assertEqual(s["status"], "tp1")
        self.assertAlmostEqual(s["r"], round(2.0 / 2.9, 2))
        self.assertEqual(US.to_local(s["fill_t"], mkt.tz).strftime("%H:%M"), "09:35")

    def test_limit_mode_and_trailing(self):
        _, setups = run(US, US_P, self.bars, {"entry_mode": "limit"})
        s = self.trade(setups)
        self.assertEqual(s["fill"], 107.5)
        self.assertEqual(s["stage"], 2)                                     # stop at break-even before TP1
        self.assertAlmostEqual(s["r"], round(2.7 / 2.2, 2))

    def test_deepest_fvg_and_fvg_stop(self):
        _, setups = run(US, US_P, self.bars, {"fvg_pick": "deepest", "stop_mode": "fvg", "entry_mode": "limit"})
        s = [x for x in setups if "fvg_lo" in x][0]
        self.assertEqual((s["fvg_lo"], s["fvg_hi"]), (108.4, 109.0))
        self.assertEqual(s["stop"], 109.7)                                  # high of the FVG's first candle (the 09:00 bar)

    def test_extreme_premium_filter_skips(self):
        _, setups = run(US, US_P, self.bars, {"dr_filter": "extreme"})
        self.assertFalse([s for s in setups if "r" in s])
        self.assertTrue(any("dealing range" in s.get("reason", "") for s in setups))

    def test_break_even_exit(self):
        bars = list(self.bars)
        i = next(k for k, b in enumerate(bars) if US.to_local(b.t, "America/New_York").strftime("%m%d%H%M") == "10200945")
        B = US.Bar
        bars[i] = B(bars[i].t, 106.0, 106.1, 105.2, 105.5, 0)             # 80%: stop to break-even
        bars[i + 1] = B(bars[i + 1].t, 105.5, 107.0, 105.4, 106.9, 0)     # back up through entry
        _, setups = run(US, US_P, bars)
        s = self.trade(setups)
        self.assertEqual(s["status"], "be")
        self.assertEqual(s["r"], 0.0)

    def test_body_through_fvg_invalidates(self):
        bars = list(self.bars)
        i = next(k for k, b in enumerate(bars) if US.to_local(b.t, "America/New_York").strftime("%m%d%H%M") == "10200930")
        bars[i] = US.Bar(bars[i].t, 107.4, 108.5, 107.3, 108.4, 0)          # closes above 108.2
        _, setups = run(US, US_P, bars)
        self.assertFalse([s for s in setups if "r" in s])
        self.assertTrue(any(s["status"] == "invalid" for s in setups))

    def test_live_states(self):
        tz = "America/New_York"
        idx = {US.to_local(b.t, tz).strftime("%m%d%H%M"): k for k, b in enumerate(self.bars)}
        expect = [("10200900", "swept"), ("10200910", "mss"), ("10200915", "armed"), ("10200925", "tapped"), ("10200935", "open")]
        for stamp, status in expect:
            _, setups = run(US, US_P, self.bars, upto=idx[stamp] + 1)
            self.assertEqual(setups[-1]["status"], status, stamp)

    def test_bullish_is_the_mirror(self):
        bars = us_bars(US, US_P, mirror_at=200.0)
        _, setups = run(US, US_P, bars, dirs=("long",))
        s = self.trade(setups)
        self.assertEqual(s["dir"], "long")
        self.assertAlmostEqual(s["entry"], 92.5)
        self.assertAlmostEqual(s["stop"], 90.3)
        self.assertAlmostEqual(s["fill"], 93.2)
        self.assertAlmostEqual(s["tp1"], 95.2)
        self.assertEqual(s["tp1_name"], "london high")
        self.assertIn("london low", s["pools"])
        self.assertAlmostEqual(s["r"], round(2.0 / 2.9, 2))

    def test_both_directions_one_trade_a_killzone(self):
        _, setups = run(US, US_P, self.bars, dirs=("short", "long"))
        self.assertEqual(len([s for s in setups if "r" in s]), 1)


class TestModelIndia(unittest.TestCase):
    def test_same_model_in_ist(self):
        mkt, setups = run(IN, IN_P, india_bars(IN, IN_P))
        t = [s for s in setups if "r" in s]
        self.assertEqual(len(t), 1, [(s["status"], s.get("reason")) for s in setups])
        s = t[0]
        self.assertEqual(s["kz"], "am")
        self.assertIn("opening_range high", s["pools"])
        self.assertEqual((s["entry"], s["stop"], s["fill"]), (107.5, 109.7, 106.8))
        self.assertEqual((s["tp1"], s["tp1_name"]), (104.8, "opening_range low"))
        self.assertEqual(s["tp2_name"], "PDL")
        self.assertEqual(IN.to_local(s["fill_t"], mkt.tz).strftime("%H:%M"), "10:35")


class TestSizing(unittest.TestCase):
    def test_notes_ep41_example(self):
        # 50,000 USD, 1% = 500 USD, 500 / SL / 5 = micro E-mini S&P contracts
        cfg = dict(US.DEFAULTS, account=50000, risk_pct=1.0, profitable=True)
        mkt = US.Market(US_P, cfg)
        sz = US.size(mkt, cfg, 5000, 5020, 4960, "MES")
        self.assertEqual(sz["rpt"], 500.0)
        self.assertEqual(sz["qty"], 5)
        self.assertEqual(sz["max_loss"], 500.0)
        self.assertEqual(sz["rr"], 2.0)
        self.assertEqual(sz["stop_after_50pct"], 5015.0)
        self.assertEqual(sz["stop_after_75pct"], 5000)

    def test_half_percent_until_profitable(self):
        cfg = dict(US.DEFAULTS, account=50000, risk_pct=1.0, profitable=False)
        sz = US.size(US.Market(US_P, cfg), cfg, 21000, 21020, None, "NQ")
        self.assertEqual(sz["risk_pct"], 0.5)
        self.assertEqual(sz["qty"], 0)
        self.assertIn("MNQ", sz["micro_hint"])

    def test_banknifty_lots_and_option_delta(self):
        cfg = dict(IN.DEFAULTS, account=500000, risk_pct=1.0, profitable=True)
        mkt = IN.Market(IN_P, cfg)
        fut = IN.size(mkt, cfg, 56000, 56100, None, "BANKNIFTY")
        self.assertEqual(fut["qty"], 1)                                    # 5000 / (100 x 30)
        opt = IN.size(mkt, cfg, 56000, 56100, None, "BANKNIFTY", option=True)
        self.assertEqual(opt["qty"], 3)                                    # 5000 / (100 x 0.5 x 30)


class TestGateAndJournal(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        US.STATE_DIR = self.tmp
        self.cfg = dict(US.DEFAULTS, account=50000)
        self.cfg.update(US_P["config_defaults"])
        self.mkt = US.Market(US_P, self.cfg)
        self.now = US.from_local(datetime(2026, 10, 20, 9, 40), US_P["tz"])   # a Tuesday, in ny_am
        self.plan = {"dir": "short", "symbol": "NQ", "entry": 107.5, "stop": 109.7, "risk": 2.2, "rr": 1.23,
                     "dr_extreme": 0.8, "status": "open"}
        self.bias = {"us-futures": {"day": "2026-10-20", "bias": "short"}}

    def tearDown(self):
        shutil.rmtree(self.tmp)

    def verdict(self, **kw):
        args = dict(cfg=self.cfg, plan=self.plan, now_ts=self.now, journal=[], bias_doc=self.bias)
        args.update(kw)
        return US.gate(self.mkt, args.pop("cfg"), args.pop("plan"), args.pop("now_ts"), args.pop("journal"), args.pop("bias_doc"))

    def test_pass(self):
        v, rows = self.verdict()
        self.assertEqual(v, "PASS", rows)

    def test_needs_written_bias(self):
        self.assertEqual(self.verdict(bias_doc={})[0], "BLOCK")
        self.assertEqual(self.verdict(bias_doc={"us-futures": {"day": "2026-10-20", "bias": "long"}})[0], "BLOCK")

    def test_outside_killzone_and_friday(self):
        self.assertEqual(self.verdict(now_ts=US.from_local(datetime(2026, 10, 20, 12, 30), US_P["tz"]))[0], "BLOCK")
        fri = US.from_local(datetime(2026, 10, 23, 9, 40), US_P["tz"])
        v, rows = self.verdict(now_ts=fri, bias_doc={"us-futures": {"day": "2026-10-23", "bias": "short"}})
        self.assertEqual(v, "BLOCK")
        self.assertTrue(any("Friday" in r[1] for r in rows))

    def test_cpi_day(self):
        cfg = dict(self.cfg, events=[{"date": "2026-10-20", "name": "CPI", "action": "avoid"}])
        self.assertEqual(self.verdict(cfg=cfg)[0], "BLOCK")
        cfg = dict(self.cfg, events=[{"date": "2026-10-20", "name": "FOMC", "action": "conviction"}])
        self.assertEqual(self.verdict(cfg=cfg)[0], "PASS")

    def test_no_adding_to_loser_or_same_level(self):
        open_loser = {"market": "us-futures", "day": "2026-10-20", "symbol": "NQ", "side": "short", "entry": 106.0,
                      "stop": 109.7, "status": "open", "r": None, "kz": "ny_am"}
        v, rows = self.verdict(journal=[open_loser])
        self.assertTrue(any("loser" in r[1] for r in rows if r[0] == "BLOCK"))
        same = dict(open_loser, entry=107.5, status="closed", r=-1.0)
        v, rows = self.verdict(journal=[same])
        self.assertTrue(any("same level" in r[1] for r in rows if r[0] == "BLOCK"))

    def test_morning_trade_blocks_afternoon(self):
        am = {"market": "us-futures", "day": "2026-10-20", "symbol": "NQ", "side": "short", "entry": 120.0, "stop": 121.0,
              "status": "closed", "r": 1.0, "kz": "ny_am"}
        pm = US.from_local(datetime(2026, 10, 20, 13, 45), US_P["tz"])
        self.assertEqual(self.verdict(now_ts=pm, journal=[am])[0], "BLOCK")

    def test_profitable_week_walks_away_after_wednesday(self):
        win = {"market": "us-futures", "day": "2026-10-19", "symbol": "NQ", "side": "long", "entry": 1.0, "stop": 0.0,
               "status": "closed", "r": 2.0, "kz": "ny_am"}
        thu = US.from_local(datetime(2026, 10, 22, 9, 40), US_P["tz"])
        v, rows = self.verdict(now_ts=thu, journal=[win], bias_doc={"us-futures": {"day": "2026-10-22", "bias": "short"}})
        self.assertTrue(any("Wednesday" in r[1] for r in rows if r[0] == "BLOCK"))

    def test_journal_round_trip(self):
        US.main(["--config", os.path.join(self.tmp, "none.json"), "journal", "add", "--symbol", "nq", "--side", "short",
                 "--entry", "107.5", "--stop", "109.7", "--kz", "ny_am", "--emotions", "anxious,not-breathing"])
        rows = US.read_journal()
        US.main(["--config", os.path.join(self.tmp, "none.json"), "journal", "move-stop", "--id", rows[0]["id"], "--stop", "107.5"])
        US.main(["--config", os.path.join(self.tmp, "none.json"), "journal", "close", "--id", rows[0]["id"], "--exit", "104.8"])
        r = US.read_journal()[0]
        self.assertEqual(r["status"], "closed")
        self.assertAlmostEqual(r["r"], round(2.7 / 2.2, 2))                # R against the original stop


class TestRepo(unittest.TestCase):
    def test_engines_identical(self):
        a, b = (read(os.path.join(ROOT, f, "mmxm.py")) for f in ("ict-india", "ict-us-futures"))
        self.assertEqual(a, b, "copy ict-us-futures/mmxm.py over ict-india/mmxm.py after editing")

    def test_skill_frontmatter(self):
        for folder in ("ict-india", "ict-us-futures"):
            text = read(os.path.join(ROOT, folder, "SKILL.md"))
            self.assertTrue(text.startswith("---\nname: %s\n" % folder))

    def test_config_examples_are_valid(self):
        for folder in ("ict-india", "ict-us-futures"):
            cfg = json.loads(read(os.path.join(ROOT, folder, "config.example.json")))
            unknown = set(k for k in cfg if not k.startswith("_")) - set(US.DEFAULTS)
            self.assertFalse(unknown, unknown)


if __name__ == "__main__":
    unittest.main()
