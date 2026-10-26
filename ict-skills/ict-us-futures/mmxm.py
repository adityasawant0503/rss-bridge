#!/usr/bin/env python3
"""ICT 2022 Mentorship model (MMXM) toolkit: levels, bias, setup check, backtest, sizing, rules, journal.

The same file ships in ict-india/ and ict-us-futures/. The market it trades comes from profile.json
next to it (session times, instruments, point values). Your own settings live in ict/config-<market>.json
in the folder you run it from.

  python3 mmxm.py levels NQ                       # PDH/PDL, session highs/lows, opens, dealing range, open FVGs
  python3 mmxm.py bias NQ                         # yesterday-vs-day-before reading, suggests a bias
  python3 mmxm.py bias NQ --set bearish           # write today's bias down (the gate needs it)
  python3 mmxm.py check NQ                        # sweep -> MSS -> FVG -> retrace, right now
  python3 mmxm.py watch NQ --every 60             # check every 60 s until triggered, invalid or expired
  python3 mmxm.py backtest NQ --days 59           # the same model over past sessions
  python3 mmxm.py size --entry 21010 --stop 21030 --target 20950 --instrument MNQ
  python3 mmxm.py gate                            # PASS / BLOCK the plan from the last check
  python3 mmxm.py journal add|close|list|review   # the live journal

Every command takes --file PATH to read bars from a CSV or a saved Yahoo chart JSON instead of the web.
Standard library only, Python 3.8+.
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import time
import urllib.error
import urllib.request
from collections import namedtuple
from datetime import date, datetime, time as dtime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.environ.get("ICT_DIR", "ict")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

Bar = namedtuple("Bar", "t o h l c v")

DEFAULTS = {
    "account": None,
    "risk_pct": 1.0,
    "profitable": False,
    "unprofitable_risk_pct": 0.5,
    "size_factor": 1.0,
    "max_trades_per_day": 2,
    "stop_after_losses": 2,
    "pm_after_am_trade": False,
    "avoid_fridays": True,
    "walk_away_after_profitable_wednesday": True,
    "events": [],
    "entry_tf": "5m",
    "entry_mode": "confirm",
    "confirm_bars": 2,
    "fvg_pick": "nearest",
    "stop_mode": "swing",
    "min_rr": 1.0,
    "dr_filter": "half",
    "displacement_mult": 1.5,
    "instrument": None,
    "option_delta": 0.5,
}


# ---------------------------------------------------------------- profile, config, time

def load_profile(path=None):
    with open(path or os.path.join(HERE, "profile.json")) as f:
        return json.load(f)


def config_path(profile):
    return os.path.join(STATE_DIR, "config-%s.json" % profile["market"])


def load_config(profile, path=None):
    cfg = dict(DEFAULTS)
    cfg.update(profile.get("config_defaults", {}))
    p = path or config_path(profile)
    if os.path.exists(p):
        with open(p) as f:
            cfg.update({k: v for k, v in json.load(f).items() if not k.startswith("_")})
    return cfg


def hm(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def _nth_sunday(y, month, n):
    d = date(y, month, 1)
    return d + timedelta(days=(6 - d.weekday()) % 7 + 7 * (n - 1))


def utc_offset(tz, ts):
    """Offset for the two zones the skills use, without needing tzdata (Windows has none)."""
    if tz == "Asia/Kolkata":
        return timedelta(hours=5, minutes=30)
    if tz == "America/New_York":
        u = datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None)
        start = datetime.combine(_nth_sunday(u.year, 3, 2), dtime(7))   # 2 am EST
        end = datetime.combine(_nth_sunday(u.year, 11, 1), dtime(6))    # 2 am EDT
        return timedelta(hours=-4) if start <= u < end else timedelta(hours=-5)
    raise ValueError("unsupported time zone %s" % tz)


def to_local(ts, tz):
    return datetime.fromtimestamp(ts, timezone.utc).replace(tzinfo=None) + utc_offset(tz, ts)


def from_local(dt, tz):
    guess = (dt - datetime(1970, 1, 1)).total_seconds()
    ts = guess - utc_offset(tz, guess).total_seconds()
    return int(guess - utc_offset(tz, ts).total_seconds())


class Market:
    def __init__(self, profile, cfg=None):
        self.p = profile
        self.cfg = cfg or load_config(profile)
        self.tz = profile["tz"]
        self.day_start = hm(profile["day_start"])
        self.range_start = hm(profile["range_start"])
        self.anchor = hm(profile.get("anchor", "00:00"))
        self.flat_by = hm(profile["flat_by"])
        self.sessions = {k: (hm(a), hm(b)) for k, (a, b) in profile["sessions"].items()}
        self.killzones = profile["killzones"]

    def local(self, ts):
        return to_local(ts, self.tz)

    def minute(self, ts):
        lt = self.local(ts)
        return lt.hour * 60 + lt.minute

    def rel(self, minute):
        """Minutes since the trading day began, so overnight sessions sort before the morning."""
        return (minute - self.day_start) % 1440

    def trading_day(self, ts):
        lt = self.local(ts)
        if self.day_start >= 720 and lt.hour * 60 + lt.minute >= self.day_start:
            return lt.date() + timedelta(days=1)
        return lt.date()

    def in_window(self, ts, window):
        a, b = window
        m = self.minute(ts)
        return a <= m < b if a <= b else (m >= a or m < b)

    def session_of(self, ts):
        for name, w in self.sessions.items():
            if self.in_window(ts, w):
                return name
        return None

    def instrument(self, name=None):
        name = (name or self.cfg.get("instrument") or self.p["default_symbol"]).upper()
        if name not in self.p["instruments"]:
            sys.exit("unknown instrument %s, choose from %s" % (name, ", ".join(self.p["instruments"])))
        return name, self.p["instruments"][name]


# ---------------------------------------------------------------- data

YAHOO_NATIVE = {"1m": "1m", "2m": "2m", "5m": "5m", "15m": "15m", "30m": "30m", "60m": "60m", "1h": "60m", "1d": "1d"}
YAHOO_MAX_DAYS = {"1m": 7, "2m": 59, "5m": 59, "15m": 59, "30m": 59, "60m": 729, "1d": 3650}


def tf_minutes(tf):
    tf = tf.lower()
    if tf.endswith("m"):
        return int(tf[:-1])
    if tf.endswith("h"):
        return int(tf[:-1]) * 60
    if tf == "1d":
        return 1440
    raise ValueError("timeframe %s" % tf)


def parse_yahoo(doc):
    res = doc["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    out = []
    for i, t in enumerate(res.get("timestamp") or []):
        o, h, l, c = q["open"][i], q["high"][i], q["low"][i], q["close"][i]
        if None in (o, h, l, c):
            continue
        out.append(Bar(int(t), float(o), float(h), float(l), float(c), float((q.get("volume") or [0] * (i + 1))[i] or 0)))
    return out


def yahoo(symbol, interval, days):
    rng = "%dd" % max(1, min(days, YAHOO_MAX_DAYS.get(interval, 59)))
    last = None
    for host in ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com"):
        url = "%s/v8/finance/chart/%s?interval=%s&range=%s&includePrePost=true" % (
            host, urllib.request.quote(symbol), interval, rng)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return parse_yahoo(json.load(r))
        except (urllib.error.URLError, ValueError, KeyError, IndexError, TypeError) as e:
            last = e
    sys.exit("could not fetch %s %s from Yahoo (%s). Use --file with a CSV export from your broker." % (symbol, interval, last))


def parse_time(s, mkt):
    s = s.strip()
    if s.replace(".", "", 1).isdigit():
        v = float(s)
        return int(v / 1000 if v > 1e11 else v)
    s = s.replace("T", " ").replace("Z", "+00:00")
    for fmt in ("%Y-%m-%d %H:%M:%S%z", "%Y-%m-%d %H:%M%z", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M", "%Y-%m-%d"):
        try:
            dt = datetime.strptime(s[:-3] + s[-2:] if fmt.endswith("%z") and s[-3:-2] == ":" else s, fmt)
        except ValueError:
            continue
        if dt.tzinfo:
            return int(dt.timestamp())
        return from_local(dt, mkt.tz)
    raise ValueError("unreadable time %r" % s)


def load_file(path, mkt):
    if path.endswith(".gz"):
        import gzip
        with gzip.open(path, "rt") as f:
            return parse_yahoo(json.load(f))
    if path.endswith(".json"):
        with open(path) as f:
            doc = json.load(f)
        if "chart" in doc:
            return parse_yahoo(doc)
        return [Bar(int(b[0]), *map(float, b[1:6])) for b in doc["bars"]]
    out = []
    with open(path, newline="") as f:
        rows = csv.DictReader(f)
        key = {k.lower().strip(): k for k in rows.fieldnames}
        tcol = next(key[k] for k in ("time", "datetime", "date", "timestamp") if k in key)
        for r in rows:
            g = lambda n: float(r[key[n]])
            out.append(Bar(parse_time(r[tcol], mkt), g("open"), g("high"), g("low"), g("close"),
                           float(r[key["volume"]] or 0) if "volume" in key else 0.0))
    return sorted(out)


def get_bars(mkt, symbol, tf, days, file=None):
    """Bars at timeframe tf. Yahoo-native intervals are fetched directly, others built from 1m/5m."""
    if file:
        bars = load_file(file, mkt)
    else:
        native = YAHOO_NATIVE.get(tf)
        src = native or ("1m" if tf_minutes(tf) < 5 else "5m")
        bars = yahoo(mkt.p["instruments"][symbol]["yahoo"], src, days + 3)
    m = tf_minutes(tf)
    if bars and len(bars) > 1 and m > (bars[1].t - bars[0].t) // 60:
        bars = resample(bars, m, mkt)
    return bars


def resample(bars, minutes, mkt):
    out, cur, key = [], None, None
    for b in bars:
        if minutes >= 1440:
            k = mkt.trading_day(b.t)
        else:
            off = (mkt.minute(b.t) - mkt.anchor) % minutes
            k = b.t - off * 60 - (b.t % 60)
        if k != key:
            if cur:
                out.append(Bar(*cur))
            key = k
            cur = [b.t if minutes >= 1440 else k, b.o, b.h, b.l, b.c, b.v]
        else:
            cur[2] = max(cur[2], b.h)
            cur[3] = min(cur[3], b.l)
            cur[4] = b.c
            cur[5] += b.v
    if cur:
        out.append(Bar(*cur))
    return out


def days_of(bars, mkt):
    """{trading_day: (first_index, last_index_exclusive)} in order."""
    out = {}
    for i, b in enumerate(bars):
        d = mkt.trading_day(b.t)
        if d not in out:
            out[d] = [i, i + 1]
        else:
            out[d][1] = i + 1
    return {d: tuple(v) for d, v in out.items()}


def daily(bars, mkt):
    out = []
    for d, (a, z) in days_of(bars, mkt).items():
        seg = bars[a:z]
        out.append({"day": d, "o": seg[0].o, "h": max(b.h for b in seg), "l": min(b.l for b in seg), "c": seg[-1].c})
    return out


# ---------------------------------------------------------------- price-action primitives

def mirror(bars):
    """Flip prices so a bullish setup can be found with the bearish code."""
    return [Bar(b.t, -b.o, -b.l, -b.h, -b.c, b.v) for b in bars]


def avg_body(bars, i, n=20):
    seg = bars[max(0, i - n):i]
    return sum(abs(b.c - b.o) for b in seg) / len(seg) if seg else 0.0


def avg_range(bars, i, n=20):
    seg = bars[max(0, i - n):i]
    return sum(b.h - b.l for b in seg) / len(seg) if seg else 0.0


def bearish_displacement(bars, i, mult):
    b = bars[i]
    body, rng = b.o - b.c, b.h - b.l
    ref = avg_body(bars, i)
    return body > 0 and rng > 0 and body >= mult * ref and body / rng >= 0.5


def swing_highs(bars, a, z):
    """3-candle swing highs (ICT short-term highs) with index in [a, z); each needs the next bar to confirm."""
    return [i for i in range(max(a, 1), min(z, len(bars) - 1)) if bars[i].h > bars[i - 1].h and bars[i].h >= bars[i + 1].h]


def swing_lows(bars, a, z):
    return [i for i in range(max(a, 1), min(z, len(bars) - 1)) if bars[i].l < bars[i - 1].l and bars[i].l <= bars[i + 1].l]


def bearish_fvgs(bars, a, z, min_size=0.0):
    """SIBI: candle 1 low above candle 3 high. Returned by the index of candle 3, in [a, z)."""
    out = []
    for i in range(max(a, 2), min(z, len(bars))):
        lo, hi = bars[i].h, bars[i - 2].l
        if hi - lo > min_size:
            out.append({"i": i, "lo": lo, "hi": hi, "c1_high": bars[i - 2].h, "t": bars[i - 1].t})
    return out


def open_fvgs(bars, upto, lookback):
    """FVGs of both directions not yet fully filled at bar `upto`."""
    res = []
    for sign, bs, kind in ((1, bars, "bearish"), (-1, mirror(bars), "bullish")):
        for g in bearish_fvgs(bs, upto - lookback, upto + 1):
            top = max(b.h for b in bs[g["i"] + 1:upto + 1]) if g["i"] < upto else -1e18
            if top < g["hi"]:
                lo, hi = (g["lo"], g["hi"]) if sign == 1 else (-g["hi"], -g["lo"])
                res.append({"kind": kind, "lo": lo, "hi": hi, "t": g["t"], "touched": top >= g["lo"]})
    return res


# ---------------------------------------------------------------- liquidity pools

def pools(mkt, bars, day, upto_kz, days_idx, htf_bars=None):
    """Buy-side pools (highs) that exist before killzone `upto_kz` on trading day `day`.

    Returned as dicts {name, price, formed} where formed is the timestamp from which the level is known.
    Works on mirrored bars too (then these are sell-side pools as negative prices)."""
    out = []
    a, z = days_idx[day]
    keys = list(days_idx)
    k = keys.index(day)
    if k > 0:
        pa, pz = days_idx[keys[k - 1]]
        out.append({"name": "PDH", "price": max(b.h for b in bars[pa:pz]), "formed": bars[a].t})
    kz_start = mkt.rel(mkt.sessions[upto_kz][0])
    for s in mkt.p.get("liquidity_sessions", []):
        sa, sb = mkt.sessions[s]
        if mkt.rel(sb) > kz_start or s == upto_kz:
            continue
        seg = [b for b in bars[a:z] if mkt.in_window(b.t, (sa, sb))]
        if seg:
            out.append({"name": "%s high" % s, "price": max(b.h for b in seg), "formed": seg[-1].t + 60})
    hb = htf_bars if htf_bars is not None else bars
    hd = days_of(hb, mkt)
    if day in hd:
        ha, hz = hd[day]
        for i in swing_highs(hb, ha, hz):
            out.append({"name": "15m swing high", "price": hb[i].h, "formed": hb[i + 1].t + 60 * 15})
    # relative equal highs on the entry timeframe (within 10% of the average candle range)
    sh = swing_highs(bars, a, z)
    for x, y in zip(sh, sh[1:]):
        tol = 0.1 * max(avg_range(bars, y), 1e-9)
        if abs(bars[x].h - bars[y].h) <= tol:
            out.append({"name": "equal highs", "price": max(bars[x].h, bars[y].h), "formed": bars[y + 1].t})
    return out


# ---------------------------------------------------------------- the model

def scan(mkt, bars, day, kz, days_idx, htf_bars, cfg, upto=None):
    """Run the bearish MMXM sequence through one killzone. Bullish = call it with mirrored bars.

    Returns a list of setups. Each has a status: waiting, swept, mss, armed, tapped, open, tp1, stop,
    be, managed (stopped after the stop was trailed), flat, expired, missed, invalid, skipped."""
    a, z = days_idx[day]
    end = len(bars) if upto is None else min(upto + 1, len(bars))
    kzw = mkt.sessions[kz]
    kz_idx = [i for i in range(a, min(z, end)) if mkt.in_window(bars[i].t, kzw)]
    if not kz_idx:
        return []
    ks, ke = kz_idx[0], kz_idx[-1] + 1
    plist = pools(mkt, bars, day, kz, days_idx, htf_bars)
    mult = cfg["displacement_mult"]
    setups = []
    st = None

    def live_pools(j):
        alive = []
        for p in plist:
            if p["formed"] > bars[j].t:
                continue
            first = next((i for i in range(a, j) if bars[i].t >= p["formed"]), j)
            if first < j and max(b.h for b in bars[first:j]) > p["price"]:
                continue
            alive.append(p)
        return alive

    def new_state():
        return {"status": "waiting", "kz": kz, "day": str(day)}

    st = new_state()
    j = ks
    while j < end:
        b = bars[j]
        in_kz = j < ke
        s = st["status"]
        if s == "waiting":
            if not in_kz:
                break
            hit = [p for p in live_pools(j) if b.h > p["price"]]
            if hit:
                top = max(hit, key=lambda p: p["price"])
                st.update(status="swept", sweep_i=j, hi_i=j, pools=sorted({p["name"] for p in hit}), pool_price=top["price"])
        elif s == "swept":
            if b.h > bars[st["hi_i"]].h:
                st["hi_i"] = j
            hi_i = st["hi_i"]
            lows = swing_lows(bars, a, hi_i)
            ref = bars[lows[-1]].l if lows else min(x.l for x in bars[max(a, hi_i - 6):hi_i + 1])
            st["mss_level"] = ref
            if j > hi_i and b.c < ref:
                if any(bearish_displacement(bars, x, mult) for x in range(hi_i + 1, j + 1)):
                    st.update(status="mss", mss_i=j)
                else:
                    setups.append(dict(st, status="skipped", reason="lethargic break, no displacement"))
                    st = new_state()
            elif not in_kz:
                break
        if st["status"] == "mss" and j > st["mss_i"]:
            gaps = [g for g in bearish_fvgs(bars, st["hi_i"] + 2, j + 1) if g["i"] <= st["mss_i"] + 2]
            if gaps:
                pick = min(gaps, key=lambda g: g["lo"]) if cfg["fvg_pick"] == "nearest" else max(gaps, key=lambda g: g["hi"])
                arm(mkt, bars, st, pick, j, day, days_idx, cfg)
                if st["status"] == "skipped":
                    setups.append(st)
                    st = new_state()
            elif j >= st["mss_i"] + 2:
                setups.append(dict(st, status="skipped", reason="no FVG in the displacement leg"))
                st = new_state()
        elif st["status"] == "armed" and j > st["arm_i"]:
            if b.l <= st["tp1"] and b.h < st["entry"]:
                st.update(status="missed", reason="ran to target without retracing")
            elif b.h >= st["entry"]:
                st["tap_i"] = j
                st["tap_t"] = b.t
                if b.c > st["fvg_hi"]:
                    st.update(status="invalid", reason="candle closed through the FVG")
                elif cfg["entry_mode"] == "limit":
                    fill(st, j, st["entry"])
                    if b.h >= st["stop"]:
                        close(st, j, st["stop"], "stop")
                else:
                    st["status"] = "tapped"
            elif not in_kz:
                st.update(status="expired", reason="no retrace into the FVG before the killzone ended")
        elif st["status"] == "tapped" and j > st["tap_i"]:
            if b.c > st["fvg_hi"] or b.h >= st["stop"]:
                st.update(status="invalid", reason="a body closed through the FVG, or the stop traded, during confirmation")
            elif j - st["tap_i"] >= cfg["confirm_bars"]:
                if b.c <= st["tp1"]:
                    st.update(status="missed", reason="confirmation closed beyond the target")
                else:
                    fill(st, j, b.c)
        elif st["status"] == "open" and j > st["fill_i"]:
            manage(mkt, st, b, j)
        if st["status"] in ("tp1", "stop", "be", "managed", "flat", "missed", "invalid", "expired"):
            setups.append(st)
            if st["status"] in ("tp1", "stop", "be", "managed", "flat"):
                return setups
            st = new_state()
            if not in_kz:
                break
        j += 1
    if st["status"] in ("swept", "mss", "armed", "tapped") and end > ke:
        st.update(status="expired", reason="the killzone ended before the setup completed")
    if st["status"] != "waiting":
        setups.append(st)
    return setups


def target_levels(mkt, bars, day, days_idx, hi_i, j):
    """Sell-side liquidity still resting below at bar j: the displacement low, old swing lows, session lows, PDL."""
    a, _ = days_idx[day]
    keys = list(days_idx)
    k = keys.index(day)
    start = days_idx[keys[k - 1]][0] if k > 0 else a
    leg = range(hi_i, j + 1)
    out = [{"name": "displacement low", "i": min(leg, key=lambda x: bars[x].l)}]
    if k > 0:
        pa, pz = days_idx[keys[k - 1]]
        out.append({"name": "PDL", "i": min(range(pa, pz), key=lambda x: bars[x].l)})
    for s, w in mkt.sessions.items():
        idx = [x for x in range(a, hi_i) if mkt.in_window(bars[x].t, w)]
        if idx:
            out.append({"name": "%s low" % s, "i": min(idx, key=lambda x: bars[x].l)})
    for i in swing_lows(bars, start, hi_i):
        out.append({"name": "swing low", "i": i})
    res = {}
    for c in out:
        i = c["i"]
        price = bars[i].l
        if i < j and min(b.l for b in bars[i + 1:j + 1]) < price:
            continue        # already run (equal lows are still resting liquidity)
        res.setdefault(price, {"name": c["name"], "price": price})
    return sorted(res.values(), key=lambda c: -c["price"])


def arm(mkt, bars, st, g, j, day, days_idx, cfg):
    hi_i = st["hi_i"]
    a = days_idx[day][0]
    entry = g["lo"]
    stop = (bars[hi_i].h if cfg["stop_mode"] == "swing" else g["c1_high"]) + cfg.get("_buffer", 0.0)
    risk = stop - entry
    st.update(status="armed", arm_i=j, fvg_lo=g["lo"], fvg_hi=g["hi"], fvg_t=g["t"], entry=entry, stop=stop, risk=risk)
    if risk <= 0:
        st.update(status="skipped", reason="stop not beyond entry")
        return
    cands = [c for c in target_levels(mkt, bars, day, days_idx, hi_i, j) if c["price"] < entry]
    good = [c for c in cands if entry - c["price"] >= cfg["min_rr"] * risk]
    if not good:
        st.update(status="skipped", reason="no liquidity target %.1fR or more away" % cfg["min_rr"])
        if cands:
            st.update(tp1=cands[-1]["price"], tp1_name=cands[-1]["name"])
        return
    st.update(tp1=good[0]["price"], tp1_name=good[0]["name"], rr=round((entry - good[0]["price"]) / risk, 2))
    rest = [c for c in cands if c["price"] < good[0]["price"]]
    if rest:
        st.update(tp2=rest[0]["price"], tp2_name=rest[0]["name"])
    # Dealing range from the day's range start to now. dr_extreme is how deep into premium a short sits
    # (for a long, computed on mirrored prices, how deep into discount): 1.0 = at the extreme.
    seg = [b for b in bars[a:j + 1] if mkt.rel(mkt.minute(b.t)) >= mkt.rel(mkt.range_start)] or bars[a:j + 1]
    lo_, hi_ = min(b.l for b in seg), max(b.h for b in seg)
    pos = (entry - lo_) / (hi_ - lo_) if hi_ > lo_ else 1.0
    st.update(dr_lo=lo_, dr_hi=hi_, dr_extreme=round(pos, 3))
    need = {"extreme": 0.75, "half": 0.5}.get(cfg["dr_filter"])
    if need is not None and pos < need:
        st.update(status="skipped", reason=("entry %.0f%% into the dealing range: on the wrong side of equilibrium" if need == 0.5 else
                                            "entry %.0f%% into the dealing range: inside the 0.25-0.75 no-trade zone") % (pos * 100))


def fill(st, j, price):
    st.update(status="open", fill_i=j, fill=price, cur_stop=st["stop"], stage=0, risk_fill=st["stop"] - price)


def close(st, j, price, why):
    st.update(status=why, exit_i=j, exit=price, r=round((st["fill"] - price) / st["risk_fill"], 2))


def manage(mkt, st, b, j):
    """The EP-41 rule: at 50% of the way to TP1 cut the stop distance by 25%, at 75% move it to break-even."""
    if mkt.rel(mkt.minute(b.t)) >= mkt.rel(mkt.flat_by):
        return close(st, j, b.o, "flat")
    if b.h >= st["cur_stop"]:
        why = "stop" if st["stage"] == 0 else ("be" if st["stage"] == 2 else "managed")
        return close(st, j, st["cur_stop"], why)
    if b.l <= st["tp1"]:
        return close(st, j, st["tp1"], "tp1")
    progress = (st["fill"] - b.l) / (st["fill"] - st["tp1"]) if st["fill"] > st["tp1"] else 0
    if progress >= 0.75 and st["stage"] < 2:
        st.update(cur_stop=st["fill"], stage=2)
    elif progress >= 0.5 and st["stage"] < 1:
        st.update(cur_stop=st["stop"] - 0.25 * (st["stop"] - st["fill"]), stage=1)


def unmirror(st):
    st = dict(st)
    for k in ("entry", "stop", "tp1", "tp2", "fill", "exit", "cur_stop", "pool_price", "mss_level"):
        if k in st and st[k] is not None:
            st[k] = -st[k]
    if "fvg_lo" in st:
        st["fvg_lo"], st["fvg_hi"] = -st["fvg_hi"], -st["fvg_lo"]
    if "dr_lo" in st:
        st["dr_lo"], st["dr_hi"] = -st["dr_hi"], -st["dr_lo"]
    for k in ("tp1_name", "tp2_name"):
        if k in st:
            st[k] = flip_name(st[k])
    st["pools"] = [flip_name(p) for p in st.get("pools", [])]
    return st


def flip_name(s):
    for a, b in (("high", "\0"), ("low", "high"), ("\0", "low"), ("PDH", "\1"), ("PDL", "PDH"), ("\1", "PDL")):
        s = s.replace(a, b)
    return s


def run_day(mkt, bars, day, days_idx, htf, cfg, directions, upto=None):
    """All setups of one trading day for the given directions, in time order, with the daily trade rules."""
    found = []
    taken = 0
    for kz in mkt.killzones:
        per_kz = []
        for d in directions:
            bs, hs = (bars, htf) if d == "short" else (mirror(bars), mirror(htf) if htf else None)
            for s in scan(mkt, bs, day, kz, days_idx, hs, cfg, upto):
                s = s if d == "short" else unmirror(s)
                s["dir"] = d
                for k in ("sweep_i", "mss_i", "arm_i", "tap_i", "fill_i", "exit_i"):
                    if k in s:
                        s[k.replace("_i", "_t")] = bars[s[k]].t
                per_kz.append(s)
        per_kz.sort(key=lambda s: s.get("fill_t") or s.get("arm_t") or s.get("sweep_t") or 0)
        traded = [s for s in per_kz if "fill_t" in s]
        if traded:
            first = traded[0]
            per_kz = [s for s in per_kz if "fill_t" not in s or s is first]
            if taken >= cfg["max_trades_per_day"] or (taken and not cfg["pm_after_am_trade"]):
                first.update(status="skipped", reason="already traded today (morning trade rule)")
                for k in ("fill_t", "exit_t", "r"):
                    first.pop(k, None)
            else:
                taken += 1
        found.extend(per_kz)
    return found


def auto_bias(dly, k):
    """Yesterday vs the day before, the common ICT previous-day reading. Returns (bias, reason)."""
    if k < 2:
        return None, "need two finished days"
    y, p = dly[k - 1], dly[k - 2]
    if y["c"] > p["h"]:
        return "long", "yesterday closed above the prior day's high (%.2f): draw on its high %.2f" % (p["h"], y["h"])
    if y["c"] < p["l"]:
        return "short", "yesterday closed below the prior day's low (%.2f): draw on its low %.2f" % (p["l"], y["l"])
    if y["h"] > p["h"] and y["c"] <= p["h"]:
        return "short", "yesterday swept the prior day's high %.2f and closed back inside" % p["h"]
    if y["l"] < p["l"] and y["c"] >= p["l"]:
        return "long", "yesterday swept the prior day's low %.2f and closed back inside" % p["l"]
    return None, "inside day: no bias, wait for one side to be taken"


# ---------------------------------------------------------------- sizing

def size(mkt, cfg, entry, stop, target=None, instrument=None, risk_pct=None, account=None, option=False):
    name, inst = mkt.instrument(instrument)
    account = account or cfg.get("account")
    if not account:
        sys.exit("set \"account\" in %s or pass --account" % config_path(mkt.p))
    cap = cfg["risk_pct"] if cfg["profitable"] else min(cfg["risk_pct"], cfg["unprofitable_risk_pct"])
    pct = min(risk_pct, cap) if risk_pct else cap
    rpt = account * pct / 100.0 * cfg["size_factor"]
    pts = abs(entry - stop)
    pv = inst["point_value"]
    unit_risk = pts * pv * (cfg["option_delta"] if option else 1.0)
    qty = int(rpt // unit_risk) if unit_risk > 0 else 0
    out = {"instrument": name, "unit": inst.get("unit", "contract"), "account": account, "risk_pct": pct,
           "size_factor": cfg["size_factor"], "rpt": round(rpt, 2), "stop_points": round(pts, 4),
           "per_unit_risk": round(unit_risk, 2), "qty": qty, "max_loss": round(qty * unit_risk, 2),
           "option_approx": option}
    if qty == 0 and inst.get("micro"):
        mname = inst["micro"]
        mq = int(rpt // (pts * mkt.p["instruments"][mname]["point_value"]))
        out["micro_hint"] = "%d %s fits instead" % (mq, mname) if mq else "even one %s is over your risk" % mname
    if target is not None:
        side = 1 if stop > entry else -1   # 1 = short
        reward = abs(entry - target)
        out.update(target=target, rr=round(reward / pts, 2) if pts else None,
                   at_50pct=round(entry - side * 0.5 * reward, 4),
                   stop_after_50pct=round(stop - side * 0.25 * pts, 4),
                   at_75pct=round(entry - side * 0.75 * reward, 4), stop_after_75pct=entry)
    return out


# ---------------------------------------------------------------- journal and gate

def journal_path():
    return os.path.join(STATE_DIR, "journal.jsonl")


def read_journal():
    if not os.path.exists(journal_path()):
        return []
    with open(journal_path()) as f:
        return [json.loads(x) for x in f if x.strip()]


def write_journal(rows):
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(journal_path(), "w") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def third_friday(y, m):
    d = date(y, m, 1)
    return d + timedelta(days=(4 - d.weekday()) % 7 + 14)


def gate(mkt, cfg, plan, now_ts, journal, bias_doc, a_plus=False):
    """PASS only if every rule from the notes holds. Returns (verdict, [(level, rule, detail)])."""
    out = []
    add = lambda lvl, rule, detail: out.append((lvl, rule, detail))
    lt = mkt.local(now_ts)
    today = str(mkt.trading_day(now_ts))
    dname = lt.strftime("%A")
    side = plan["dir"]

    b = (bias_doc or {}).get(mkt.p["market"], {})
    if b.get("day") != today:
        add("BLOCK", "Always write down your bias", "no bias written for %s: run bias --set long|short|none" % today)
    elif b.get("bias") in (None, "none"):
        add("BLOCK", "Knowing when not to do anything", "today's bias is none")
    elif b["bias"] != side:
        add("BLOCK", "Work with your bias, not against it", "bias is %s, plan is %s" % (b["bias"], side))
    else:
        add("ok", "Bias written", "%s, matches the plan" % b["bias"])

    kz = mkt.session_of(now_ts)
    if kz not in mkt.killzones:
        add("BLOCK", "Enter only in killzones", "now is %s %s, outside %s" % (lt.strftime("%H:%M"), kz or "", "/".join(mkt.killzones)))
    else:
        add("ok", "Killzone", kz)

    rows = [r for r in journal if r.get("market") == mkt.p["market"] and r.get("day") == today]
    closed = [r for r in rows if r.get("r") is not None]
    losses = [r for r in closed if r["r"] < 0]
    if len(rows) >= cfg["max_trades_per_day"]:
        add("BLOCK", "2 trades a day", "%d trades already today" % len(rows))
    if len(losses) >= cfg["stop_after_losses"]:
        add("BLOCK", "Stop after losses", "%d losing trades today" % len(losses))
    am = [r for r in rows if r.get("kz") == mkt.killzones[0]]
    if am and kz != mkt.killzones[0] and not cfg["pm_after_am_trade"] and not a_plus:
        add("BLOCK", "Morning trade taken: no afternoon unless it is an easy, perfect setup",
            "pass --a-plus only if it truly is")
    for r in [x for x in journal if x.get("market") == mkt.p["market"] and x.get("status") == "open"]:
        if r.get("symbol") == plan.get("symbol"):
            risk_free = r["stop"] <= r["entry"] if r["side"] == "short" else r["stop"] >= r["entry"]
            if r["side"] != side:
                add("BLOCK", "One position at a time", "an open %s %s is still running" % (r["side"], r["symbol"]))
            elif not risk_free:
                add("BLOCK", "Never add to a loser (your journal: 'added quantity', 'holding in loss')",
                    "the open %s from %.2f still has its stop at %.2f: move it to break-even before adding" % (r["side"], r["entry"], r["stop"]))
    for r in rows:
        tol = 0.1 * plan["risk"]
        if r.get("side") == side and abs(r.get("entry", 1e18) - plan["entry"]) <= tol:
            add("BLOCK", "Do not take multiple entries at the same level", "already entered %.2f today" % r["entry"])

    if cfg["avoid_fridays"] and dname == "Friday":
        add("BLOCK", "Avoid Fridays for new positions", dname)
    for ev in cfg.get("events", []):
        if ev.get("date") == str(lt.date()):
            act = ev.get("action", "avoid")
            add("BLOCK" if act == "avoid" else "WARN", "Calendar: %s" % ev.get("name", "event"),
                "avoid today" if act == "avoid" else "trade only with strong conviction")
    if cfg.get("walk_away_after_profitable_wednesday") and mkt.p["market"] == "us-futures":
        monday = lt.date() - timedelta(days=lt.weekday())
        week = [r for r in journal if r.get("market") == mkt.p["market"] and r.get("r") is not None and r.get("day", "") >= str(monday)]
        if sum(r["r"] for r in week) > 0 and (lt.weekday() > 2 or (lt.weekday() == 2 and mkt.minute(now_ts) >= hm("12:00"))):
            add("BLOCK", "Profitable week: walk away after Wednesday's NY session", "+%.2fR this week" % sum(r["r"] for r in week))

    if plan.get("rr", 0) < cfg["min_rr"]:
        add("BLOCK", "Standard R:R", "%.2fR to the first target" % plan.get("rr", 0))
    ext = plan.get("dr_extreme")
    zone = "premium" if side == "short" else "discount"
    if ext is not None and ext < 0.5:
        add("BLOCK", "Sell in premium, buy in discount", "entry is %.0f%% into the range, on the wrong side of equilibrium" % (ext * 100))
    elif ext is not None and ext < 0.75:
        add("BLOCK" if cfg["dr_filter"] == "extreme" else "WARN", "No-trade zone between 0.25 and 0.75 of the dealing range",
            "entry only %.0f%% into %s, the notes want the extreme 25%%" % (ext * 100, zone))
    if plan.get("status") not in ("armed", "tapped", "open"):
        add("BLOCK", "Do not take any trade until you have a setup", "setup status is %s" % plan.get("status"))
    elif cfg["entry_mode"] == "confirm" and plan["status"] != "open":
        add("BLOCK", "Once price touches the FVG, wait for the next 2 candles",
            "status is %s: run check again after the confirmation candles close" % plan["status"])

    for w in expiry_warnings(mkt, lt):
        add("WARN", w[0], w[1])
    verdict = "BLOCK" if any(x[0] == "BLOCK" for x in out) else "PASS"
    return verdict, out


def expiry_warnings(mkt, lt):
    out = []
    if mkt.p["market"] == "us-futures":
        for m in (3, 6, 9, 12):
            tf = third_friday(lt.year, m)
            if 0 <= (tf - lt.date()).days <= 8:
                out.append(("Third Friday expiry: be in the month with more open interest",
                            "%s contract expires %s, roll to the next one" % (tf.strftime("%b"), tf)))
    else:
        for name, inst in mkt.p["instruments"].items():
            wd = inst.get("expiry_weekday")
            if wd is not None and lt.weekday() == wd:
                out.append(("Do not wait for expiry to expire", "%s expiry day: options are flat by %s" % (name, mkt.p["flat_by"])))
    return out


# ---------------------------------------------------------------- output

def fmt_t(mkt, ts):
    return mkt.local(ts).strftime("%a %d %b %H:%M") if ts else "-"


def describe(mkt, s, dp=2):
    f = lambda v: ("%." + str(dp) + "f") % v if isinstance(v, (int, float)) else str(v)
    lines = ["%s %s, %s killzone: %s%s" % (s["day"], s["dir"].upper(), s["kz"], s["status"].upper(),
                                           (" (" + s["reason"] + ")") if s.get("reason") else "")]
    if "sweep_t" in s:
        lines.append("  1 sweep   %s took %s at %s" % (fmt_t(mkt, s["sweep_t"]), ", ".join(s["pools"]), f(s["pool_price"])))
    if "mss_t" in s:
        lines.append("  2 MSS     %s closed through %s with displacement" % (fmt_t(mkt, s["mss_t"]), f(s["mss_level"])))
    if "fvg_lo" in s:
        lines.append("  3 FVG     %s to %s (formed %s)" % (f(s["fvg_lo"]), f(s["fvg_hi"]), fmt_t(mkt, s.get("fvg_t"))))
    if "entry" in s:
        lines.append("  4 plan    entry %s  stop %s  risk %s pts" % (f(s["entry"]), f(s["stop"]), f(abs(s["stop"] - s["entry"]))))
    if "tp1" in s:
        lines.append("            TP1 %s (%s)%s%s" % (f(s["tp1"]), s.get("tp1_name", ""),
                                                   "  %.2fR" % s["rr"] if "rr" in s else "",
                                                   "   TP2 %s (%s)" % (f(s["tp2"]), s["tp2_name"]) if "tp2" in s else ""))
    if "dr_extreme" in s:
        lines.append("            dealing range %s to %s, entry %.0f%% of the way into %s" % (
            f(s["dr_lo"]), f(s["dr_hi"]), s["dr_extreme"] * 100, "premium" if s["dir"] == "short" else "discount"))
    if "tap_t" in s:
        lines.append("  5 tapped  %s" % fmt_t(mkt, s["tap_t"]))
    if "fill_t" in s:
        lines.append("  6 filled  %s at %s" % (fmt_t(mkt, s["fill_t"]), f(s["fill"])))
    if "exit_t" in s:
        lines.append("  7 exit    %s at %s: %+.2fR" % (fmt_t(mkt, s["exit_t"]), f(s["exit"]), s["r"]))
    return "\n".join(lines)


def save_json(name, doc):
    os.makedirs(STATE_DIR, exist_ok=True)
    p = os.path.join(STATE_DIR, name)
    with open(p, "w") as f:
        json.dump(doc, f, indent=1, default=str)
    return p


def clean(s):
    return {k: v for k, v in s.items() if not k.endswith("_i")}


# ---------------------------------------------------------------- commands

def prepare(mkt, args, days):
    name, inst = mkt.instrument(args.symbol)
    cfg = mkt.cfg
    cfg["_buffer"] = inst.get("buffer", 0.0)
    bars = get_bars(mkt, name, cfg["entry_tf"], days, args.file)
    if not bars:
        sys.exit("no bars")
    htf = resample(bars, 15, mkt) if tf_minutes(cfg["entry_tf"]) < 15 else None
    return name, inst, bars, htf


def directions_for(mkt, args, bars, day):
    if args.bias in ("long", "short"):
        return [args.bias]
    if args.bias == "both":
        return ["short", "long"]
    if args.bias == "written":
        doc = load_bias()
        b = doc.get(mkt.p["market"], {})
        if b.get("day") == str(day) and b.get("bias") in ("long", "short"):
            return [b["bias"]]
        return []
    dly = daily(bars, mkt)
    k = next(i for i, d in enumerate(dly) if d["day"] == day)
    b, _ = auto_bias(dly, k)
    return [b] if b else []


def load_bias():
    p = os.path.join(STATE_DIR, "bias.json")
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def cmd_levels(mkt, args):
    name, inst, bars, htf = prepare(mkt, args, 10)
    di = days_of(bars, mkt)
    keys = list(di)
    day = keys[-1]
    a, z = di[day]
    dly = daily(bars, mkt)
    print("%s %s  last %s  %s" % (name, mkt.p["title"], fmt_t(mkt, bars[-1].t), mkt.p["tz"]))
    if len(dly) >= 2:
        print("  PDH %.2f  PDL %.2f  (%s)" % (dly[-2]["h"], dly[-2]["l"], dly[-2]["day"]))
    week = [d for d in dly[:-1] if d["day"].isocalendar()[1] != day.isocalendar()[1]][-5:]
    if week:
        print("  PWH %.2f  PWL %.2f" % (max(d["h"] for d in week), min(d["l"] for d in week)))
    for label, t in mkt.p.get("opens", {}).items():
        b = next((x for x in bars[a:z] if mkt.minute(x.t) == hm(t)), None)
        if b:
            print("  %-14s %.2f  (price is %s it)" % (label + " open", b.o, "above" if bars[-1].c > b.o else "below"))
    for s, (sa, sb) in mkt.sessions.items():
        seg = [b for b in bars[a:z] if mkt.in_window(b.t, (sa, sb))]
        if seg:
            print("  %-14s high %.2f  low %.2f" % (s, max(b.h for b in seg), min(b.l for b in seg)))
    seg = [b for b in bars[a:z] if mkt.rel(mkt.minute(b.t)) >= mkt.rel(mkt.range_start)] or bars[a:z]
    hi, lo = max(b.h for b in seg), min(b.l for b in seg)
    pos = (bars[-1].c - lo) / (hi - lo) if hi > lo else 0.5
    print("  dealing range since %s: %.2f to %.2f, equilibrium %.2f, price at %.0f%% (%s)" % (
        mkt.p["range_start"], lo, hi, (hi + lo) / 2, pos * 100, "premium" if pos > 0.5 else "discount"))
    h1 = resample(bars, 60, mkt)
    gaps = open_fvgs(h1, len(h1) - 1, 40)
    if gaps:
        print("  open 1h FVGs:")
        for g in sorted(gaps, key=lambda g: -g["hi"])[:8]:
            print("    %-8s %.2f to %.2f%s" % (g["kind"], g["lo"], g["hi"], "  (touched)" if g["touched"] else ""))


def cmd_bias(mkt, args):
    if args.set:
        doc = load_bias()
        day = args.day or str(mkt.trading_day(time.time()))
        doc[mkt.p["market"]] = {"day": day, "bias": args.set, "note": args.note or "", "written": datetime.now().isoformat(timespec="seconds")}
        print("bias for %s written: %s -> %s" % (day, args.set, save_json("bias.json", doc)))
        return
    name, inst, bars, htf = prepare(mkt, args, 10)
    dly = daily(bars, mkt)
    k = len(dly) - 1
    b, why = auto_bias(dly, k)
    for d in dly[-3:]:
        print("  %s  O %.2f  H %.2f  L %.2f  C %.2f" % (d["day"], d["o"], d["h"], d["l"], d["c"]))
    print("suggested bias for %s: %s (%s)" % (dly[-1]["day"], b or "none", why))
    print("This is a suggestion from one rule. Check the weekly candle, the 1h FVGs (levels) and SMT, then write it down:")
    print("  python3 mmxm.py bias %s --set long|short|none --note \"why\"" % name)


def cmd_check(mkt, args):
    name, inst, bars, htf = prepare(mkt, args, 5)
    di = days_of(bars, mkt)
    day = list(di)[-1]
    dirs = directions_for(mkt, args, bars, day)
    if not dirs:
        print("No bias for %s (mode %s). Knowing when not to do anything is important." % (day, args.bias))
        return
    dp = 2
    setups = run_day(mkt, bars, day, di, htf, mkt.cfg, dirs)
    now = bars[-1].t
    print("%s  last bar %s  (%s, bias mode %s: %s)" % (name, fmt_t(mkt, now), mkt.cfg["entry_tf"], args.bias, "/".join(dirs)))
    if not setups:
        kz = mkt.session_of(now)
        print("waiting: no liquidity taken yet%s" % ("" if kz in mkt.killzones else ", and it is outside the killzones (%s)" % ", ".join(
            "%s %s-%s" % (k, *mkt.p["sessions"][k]) for k in mkt.killzones)))
        return
    for s in setups:
        s["symbol"] = name
        print(describe(mkt, s, dp))
    live = [s for s in setups if s["status"] in ("armed", "tapped", "open")]
    if live:
        s = live[-1]
        try:
            sz = size(mkt, mkt.cfg, s.get("fill", s["entry"]), s["stop"], s.get("tp1"), name)
            s["size"] = sz
            print("  size: %d %s, max loss %s %s (%.2f%% of %s)%s" % (
                sz["qty"], sz["unit"] + ("s" if sz["qty"] != 1 else ""), mkt.p["currency"], sz["max_loss"], sz["risk_pct"],
                sz["account"], ("  " + sz["micro_hint"]) if "micro_hint" in sz else ""))
            if "at_50pct" in sz:
                print("  manage: at %.2f move stop to %.2f; at %.2f move stop to break-even %.2f" % (
                    sz["at_50pct"], sz["stop_after_50pct"], sz["at_75pct"], sz["stop_after_75pct"]))
        except SystemExit as e:
            print("  size: %s" % e)
        p = save_json("plan-%s.json" % mkt.p["market"], clean(s))
        print("plan saved to %s, run gate before you place anything" % p)
    return setups


def cmd_watch(mkt, args):
    while True:
        setups = cmd_check(mkt, args) or []
        last = setups[-1]["status"] if setups else "waiting"
        if last in ("open", "tp1", "stop", "be", "managed", "flat") or (last in ("expired", "invalid", "missed") and not any(
                mkt.session_of(time.time()) == k for k in mkt.killzones)):
            return
        print("-- next check in %ds --" % args.every)
        time.sleep(args.every)


def cmd_backtest(mkt, args):
    name, inst, bars, htf = prepare(mkt, args, args.days)
    di = days_of(bars, mkt)
    slip = inst.get("slippage", 0.0)
    keys = list(di)[-args.days:]
    allsetups = []
    for day in keys:
        dirs = directions_for(mkt, args, bars, day)
        if not dirs:
            continue
        for s in run_day(mkt, bars, day, di, htf, mkt.cfg, dirs):
            if "r" in s and slip:
                s["r"] = round(s["r"] - 2 * slip / s["risk_fill"], 2)
            s["symbol"] = name
            allsetups.append(s)
    trades = [s for s in allsetups if "r" in s]
    print("%s backtest: %d sessions %s to %s, entry %s, bias %s, entry mode %s, FVG %s, stop %s, dealing-range filter %s" % (
        name, len(keys), keys[0], keys[-1], mkt.cfg["entry_tf"], args.bias, mkt.cfg["entry_mode"], mkt.cfg["fvg_pick"],
        mkt.cfg["stop_mode"], mkt.cfg["dr_filter"]))
    print("slippage %.2f pts each side, costs and commissions not included" % slip)
    by = {}
    for s in allsetups:
        key = s["status"] + (": " + re.sub(r"^entry \d+% into the dealing range: ", "", s["reason"]) if s.get("reason") else "")
        by[key] = by.get(key, 0) + 1
    for k in sorted(by, key=lambda k: -by[k]):
        print("  %4d  %s" % (by[k], k))
    if not trades:
        print("no trades filled")
        return {"trades": 0}
    wins = [t for t in trades if t["r"] > 0]
    total = sum(t["r"] for t in trades)
    print("\n  trades %d   won %d (%.0f%%)   total %+.2fR   average %+.2fR per trade" % (
        len(trades), len(wins), 100.0 * len(wins) / len(trades), total, total / len(trades)))
    for grp, key in (("direction", "dir"), ("killzone", "kz")):
        vals = sorted({t[key] for t in trades})
        print("  by %s: %s" % (grp, "   ".join("%s %d trades %+.2fR" % (v, len([t for t in trades if t[key] == v]),
                                                                       sum(t["r"] for t in trades if t[key] == v)) for v in vals)))
    eq, peak, dd = 0.0, 0.0, 0.0
    for t in trades:
        eq += t["r"]
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    print("  worst drawdown %.2fR" % dd)
    if args.list:
        print()
        for t in trades:
            print("  %s %-5s %-6s entry %.2f stop %.2f tp1 %.2f -> %-7s %+.2fR" % (
                t["day"], t["dir"], t["kz"], t["fill"], t["stop"], t["tp1"], t["status"], t["r"]))
    if len(trades) < 30:
        print("\nOnly %d trades: too few to trust a win rate either way. The notes ask for 6 months of backtesting." % len(trades))
    save_json("backtest-%s-%s.json" % (mkt.p["market"], name), {"setups": [clean(s) for s in allsetups]})
    return {"trades": len(trades), "total_r": total}


def cmd_size(mkt, args):
    sz = size(mkt, mkt.cfg, args.entry, args.stop, args.target, args.instrument, args.risk_pct, args.account, args.option)
    cur = mkt.p["currency"]
    print("%s: risk %s %.2f (%.2f%% of %s%s)" % (sz["instrument"], cur, sz["rpt"], sz["risk_pct"], sz["account"],
                                               ", size factor %.2f" % sz["size_factor"] if sz["size_factor"] != 1 else ""))
    print("  stop %.2f pts x %s per point%s = %s %.2f per %s" % (
        sz["stop_points"], mkt.p["instruments"][sz["instrument"]]["point_value"],
        " x delta %.2f" % mkt.cfg["option_delta"] if args.option else "", cur, sz["per_unit_risk"], sz["unit"]))
    print("  -> %d %s, max loss at the stop %s %.2f" % (sz["qty"], sz["unit"] + "s", cur, sz["max_loss"]))
    if "micro_hint" in sz:
        print("  %s" % sz["micro_hint"])
    if "rr" in sz:
        print("  target %.2f = %.2fR" % (sz["target"], sz["rr"]))
        print("  at %.2f (50%%) move stop to %.2f; at %.2f (75%%) move stop to break-even %.2f" % (
            sz["at_50pct"], sz["stop_after_50pct"], sz["at_75pct"], sz["stop_after_75pct"]))
    if args.option:
        print("  option sizing uses delta %.2f: the premium will not move 1:1 with the index. Use the option's own stop if you have one." % mkt.cfg["option_delta"])


def cmd_gate(mkt, args):
    p = os.path.join(STATE_DIR, "plan-%s.json" % mkt.p["market"])
    if not os.path.exists(p):
        sys.exit("no plan yet: run check first")
    with open(p) as f:
        plan = json.load(f)
    now = args.now and parse_time(args.now, mkt) or time.time()
    verdict, rows = gate(mkt, mkt.cfg, plan, now, read_journal(), load_bias(), args.a_plus)
    for lvl, rule, detail in rows:
        print("  %-5s %s: %s" % (lvl, rule, detail))
    print("\n%s" % verdict)
    print("Before you click: breathe. Not trading for anyone else. Not entering with all your profits. "
          "If the size feels heavy, cut it by a quarter.")
    return verdict


EMOTIONS = ["calm", "anxious", "not-breathing", "heavy-breathing", "panic-booking", "greed-waiting-for-more",
            "holding-loser", "added-to-loser", "all-profits-in", "counter-bias", "trading-for-others",
            "waiting-for-expiry", "revenge", "fomo", "excited", "shivers"]


def cmd_journal(mkt, args):
    rows = read_journal()
    if args.action == "add":
        now = time.time()
        r = {"id": "%s-%d" % (mkt.p["market"], len(rows) + 1), "market": mkt.p["market"], "day": args.day or str(mkt.trading_day(now)),
             "kz": args.kz or mkt.session_of(now), "symbol": args.symbol.upper(), "side": args.side, "entry": args.entry,
             "stop": args.stop, "orig_stop": args.stop, "qty": args.qty, "bias": args.bias_note, "setup": args.setup, "status": "open", "r": None,
             "emotions": [e.strip() for e in (args.emotions or "").split(",") if e.strip()], "notes": args.notes or ""}
        if args.exit is not None:
            r.update(exit=args.exit, status="closed", r=round((args.entry - args.exit) / (args.stop - args.entry), 2) if args.side == "short"
                     else round((args.exit - args.entry) / (args.entry - args.stop), 2))
        rows.append(r)
        write_journal(rows)
        print("journal: %s %s %s %s at %.2f%s" % (r["id"], r["day"], r["side"], r["symbol"], r["entry"],
                                                ", %+.2fR" % r["r"] if r["r"] is not None else " (open)"))
    elif args.action in ("close", "move-stop"):
        r = next((x for x in rows if x["id"] == args.id), None)
        if not r:
            sys.exit("no trade %s" % args.id)
        if args.action == "move-stop":
            r["stop"] = args.stop
        else:
            risk = abs(r["entry"] - r.get("orig_stop", r["stop"]))
            r.update(exit=args.exit, status="closed",
                     r=round(((r["entry"] - args.exit) if r["side"] == "short" else (args.exit - r["entry"])) / risk, 2))
        if args.emotions:
            r["emotions"] = sorted(set(r.get("emotions", []) + [e.strip() for e in args.emotions.split(",")]))
        if args.notes:
            r["notes"] = (r.get("notes", "") + " | " + args.notes).strip(" |")
        write_journal(rows)
        print("journal: %s %s" % (r["id"], "closed %+.2fR" % r["r"] if r["status"] == "closed" else "stop now %.2f" % r["stop"]))
    elif args.action == "list":
        for r in rows[-20:]:
            print("%s %s %-5s %-9s %-5s entry %.2f stop %.2f %s %s" % (
                r["id"], r["day"], r.get("kz") or "", r["symbol"], r["side"], r["entry"], r["stop"],
                "%+.2fR" % r["r"] if r["r"] is not None else "OPEN", ",".join(r.get("emotions", []))))
    else:
        done = [r for r in rows if r.get("r") is not None]
        if not done:
            print("no closed trades yet")
            return
        tot = sum(r["r"] for r in done)
        print("%d closed trades, %+.2fR total, %.0f%% winners, average %+.2fR" % (
            len(done), tot, 100.0 * len([r for r in done if r["r"] > 0]) / len(done), tot / len(done)))
        tags = {}
        for r in done:
            for e in r.get("emotions", []):
                tags.setdefault(e, []).append(r["r"])
        if tags:
            print("feelings and habits, with the result of the trades they showed up in:")
            for e, rs in sorted(tags.items(), key=lambda kv: sum(kv[1])):
                print("  %-24s %2d trades  %+.2fR" % (e, len(rs), sum(rs)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", help=argparse.SUPPRESS)
    ap.add_argument("--config", help="config file (default ict/config-<market>.json)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def sym(p, bias=False):
        p.add_argument("symbol", nargs="?")
        p.add_argument("--file", help="bars from a CSV (time,open,high,low,close[,volume]) or Yahoo chart JSON")
        p.add_argument("--tf", help="entry timeframe, default from config (5m)")
        if bias:
            p.add_argument("--bias", default="written", choices=["written", "auto", "long", "short", "both"],
                           help="written = what you set with bias --set (default)")
        return p

    sym(sub.add_parser("levels"))
    pb = sym(sub.add_parser("bias"))
    pb.add_argument("--set", choices=["long", "short", "none"])
    pb.add_argument("--note")
    pb.add_argument("--day")
    sym(sub.add_parser("check"), True)
    pw = sym(sub.add_parser("watch"), True)
    pw.add_argument("--every", type=int, default=60)
    pt = sym(sub.add_parser("backtest"), True)
    pt.set_defaults(bias="both")
    pt.add_argument("--days", type=int, default=59)
    pt.add_argument("--list", action="store_true")
    for k in ("entry-mode", "fvg-pick", "stop-mode", "dr-filter"):
        pt.add_argument("--" + k)
    pt.add_argument("--min-rr", type=float)
    ps = sub.add_parser("size")
    ps.add_argument("--entry", type=float, required=True)
    ps.add_argument("--stop", type=float, required=True)
    ps.add_argument("--target", type=float)
    ps.add_argument("--instrument")
    ps.add_argument("--risk-pct", type=float)
    ps.add_argument("--account", type=float)
    ps.add_argument("--option", action="store_true", help="size an option on the index using option_delta")
    pg = sub.add_parser("gate")
    pg.add_argument("--a-plus", action="store_true", help="the afternoon setup is an easy, perfect one")
    pg.add_argument("--now", help=argparse.SUPPRESS)
    pj = sub.add_parser("journal")
    pj.add_argument("action", choices=["add", "close", "move-stop", "list", "review"])
    pj.add_argument("--id")
    pj.add_argument("--symbol", default="")
    pj.add_argument("--side", choices=["long", "short"])
    pj.add_argument("--entry", type=float)
    pj.add_argument("--stop", type=float)
    pj.add_argument("--exit", type=float)
    pj.add_argument("--qty", type=float)
    pj.add_argument("--kz")
    pj.add_argument("--day")
    pj.add_argument("--setup", default="MMXM 2022")
    pj.add_argument("--bias-note")
    pj.add_argument("--emotions", help="comma list, e.g. " + ",".join(EMOTIONS[:6]))
    pj.add_argument("--notes")
    args = ap.parse_args(argv)

    profile = load_profile(args.profile)
    cfg = load_config(profile, args.config)
    if getattr(args, "tf", None):
        cfg["entry_tf"] = args.tf
    for k in ("entry_mode", "fvg_pick", "stop_mode", "dr_filter", "min_rr"):
        v = getattr(args, k, None)
        if v is not None:
            cfg[k] = v
    mkt = Market(profile, cfg)
    return {"levels": cmd_levels, "bias": cmd_bias, "check": cmd_check, "watch": cmd_watch, "backtest": cmd_backtest,
            "size": cmd_size, "gate": cmd_gate, "journal": cmd_journal}[args.cmd](mkt, args)


if __name__ == "__main__":
    main()
