#!/usr/bin/env python3
"""Morning sweep-and-reclaim: an ICT liquidity setup made mechanical, tested on the 5m archive.

The rules were fixed on 13 Nov 2026, before the first test, from Aditya's two Nifty shorts (11 and 13 Nov):

  1. Level: the opening range (high/low of 09:15-09:30, "or") or the previous day's high/low ("pd").
  2. Sweep: a 5m bar trades beyond the level (above the high for a short, below the low for a long).
  3. Reclaim: within 6 bars (30 minutes) a bar closes back inside. Enter at that close, 09:30-11:00.
     If it doesn't close back inside in time, that side is off for the day. Sweeps of the previous day's
     level count from 09:15, but a close back inside before 09:30 is no entry: wait for a new sweep.
  4. Stop: the sweep's extreme, plus a buffer (0, 0.05% or 0.10% of the price).
  5. Target: 2R. Otherwise exit at the 15:10 bar's close. Inside a bar the stop is assumed hit first.
     One trade per index per day (the first reclaim).

The bar set before testing: avg >= +0.2R over >= 15 trades on Aug-Oct 2026 data, on at least 2 of 3 indices.
Only the opening-range version without a buffer passed (Nifty and Sensex; its Nifty stops are often only
10-20 points, which may be too tight for options). All six versions are forward-tested from 16 Nov 2026,
each day scored after it closes with no discretion, so nothing is picked after the fact.

  python3 sweep.py backtest            # every version on the whole archive, Aug-Oct vs November
  python3 sweep.py score               # score each finished day since the forward test began (idempotent)
  python3 sweep.py summary             # forward-test results so far

Results are written to ict/research/ (git-ignored). Standard library only.
"""
import argparse
import collections
import json
import os
import sys
from datetime import date, datetime, time as T

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm    # noqa: E402
import optbt   # noqa: E402

INDICES = {"NIFTY": "^NSEI", "SENSEX": "^BSESN", "BANKNIFTY": "^NSEBANK"}
ALL_VERSIONS = [(lvl, buf) for lvl in ("or", "pd") for buf in (0.0, 0.0005, 0.001)]
CANDIDATES = [("or", 0.0)]                                     # passed the pre-set bar on Aug-Oct 2026
FORWARD_START = date(2026, 11, 16)                              # first day the rules had never seen
RECLAIM_BARS, FIRST_ENTRY, LAST_ENTRY, EXIT_BAR = 6, T(9, 30), T(10, 55), T(15, 10)
LOG = os.path.join(mmxm.STATE_DIR, "research", "sweep-forward.jsonl")


def vname(lvl, buf):
    return "%s-%.2f" % (lvl, buf * 100)


def load_days(symbol):
    """{date: [(time, o, h, l, c), ...]} from the 5m archive, full sessions only (special sessions dropped)."""
    with open(optbt.archive_name(symbol, "5m")) as f:
        bars = json.load(f)["bars"]
    days = collections.OrderedDict()
    for t, o, h, l, c, v in bars:
        lt = mmxm.to_local(t, "Asia/Kolkata")
        days.setdefault(lt.date(), []).append((lt.time(), o, h, l, c))
    return collections.OrderedDict((d, b) for d, b in days.items() if len(b) >= 60)


def levels(days, d, lvl):
    """(high, low, first bar time a sweep counts from) for day d, or None when there's no previous day."""
    bars = days[d]
    if lvl == "or":
        orb = [b for b in bars if b[0] < FIRST_ENTRY]
        return max(b[2] for b in orb), min(b[3] for b in orb), FIRST_ENTRY
    keys = list(days)
    k = keys.index(d)
    if k == 0:
        return None
    prev = days[keys[k - 1]]
    return max(b[2] for b in prev), min(b[3] for b in prev), T(9, 15)


def trade_day(bars, hi, lo, buf, start):
    """The day's trade as a dict, or None. bars: [(time, o, h, l, c)] in order."""
    st = {"short": None, "long": None}
    for i, (t, o, h, l, c) in enumerate(bars):
        if t < start:
            continue
        if t > LAST_ENTRY:
            return None
        for side in ("short", "long"):
            s = st[side]
            if s == "off":
                continue
            beyond = h > hi if side == "short" else l < lo
            if s is None and beyond:
                st[side] = s = {"i": i, "ext": h if side == "short" else l}
            elif isinstance(s, dict):
                s["ext"] = max(s["ext"], h) if side == "short" else min(s["ext"], l)
            if not isinstance(s, dict):
                continue
            if (c < hi) if side == "short" else (c > lo):
                if t < FIRST_ENTRY:          # back inside during the opening range: no entry, wait for a new sweep
                    st[side] = None
                    continue
                stop = s["ext"] * (1 + buf) if side == "short" else s["ext"] * (1 - buf)
                risk = abs(stop - c)
                if risk <= 0:
                    st[side] = "off"
                    continue
                target = c - 2 * risk if side == "short" else c + 2 * risk
                r, how = manage(bars[i + 1:], side, c, stop, target, risk)
                return {"side": side, "entry_time": t.strftime("%H:%M"), "entry": round(c, 2), "stop": round(stop, 2),
                        "target": round(target, 2), "r": round(r, 3), "exit": how}
            if i - s["i"] >= RECLAIM_BARS:
                st[side] = "off"
    return None


def manage(rest, side, entry, stop, target, risk):
    last = entry
    for t, o, h, l, c in rest:
        if t > EXIT_BAR:
            break
        if (h >= stop) if side == "short" else (l <= stop):
            return -1.0, "stop"
        if (l <= target) if side == "short" else (h >= target):
            return 2.0, "target"
        last = c
    return ((entry - last) if side == "short" else (last - entry)) / risk, "close"


def stats(rs):
    if not rs:
        return "  0 trades"
    wins = [r for r in rs if r > 0]
    loss = -sum(r for r in rs if r <= 0)
    pf = sum(wins) / loss if loss else float("inf")
    return "%3d trades  win %3.0f%%  avg %+5.2fR  total %+6.1fR  PF %4.2f" % (
        len(rs), 100.0 * len(wins) / len(rs), sum(rs) / len(rs), sum(rs), pf)


def cmd_backtest(args):
    split = date(2026, 11, 1)
    for name, sym in INDICES.items():
        days = load_days(sym)
        print("\n%s: %d full days, %s to %s" % (name, len(days), next(iter(days)), list(days)[-1]))
        for lvl, buf in ALL_VERSIONS:
            before, after = [], []
            for d in days:
                lv = levels(days, d, lvl)
                tr = lv and trade_day(days[d], lv[0], lv[1], buf, lv[2])
                if tr:
                    (before if d < split else after).append(tr["r"])
            print("  %-8s Aug-Oct: %s | Nov on: %s" % (vname(lvl, buf), stats(before), stats(after)))


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(line) for line in f if line.strip()]


def cmd_score(args):
    """Score every finished day from --since that isn't in the log yet. A day counts as finished once its
    15:10 bar is in the archive and it's before today (run `optbt.py archive` first)."""
    since = date.fromisoformat(args.since)
    today = mmxm.to_local(datetime.now().timestamp(), "Asia/Kolkata").date()
    done = {(r["day"], r["index"], r["version"]) for r in read_log()}
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    new = []
    for name, sym in INDICES.items():
        days = load_days(sym)
        for d in days:
            if d < since or d >= today or not any(b[0] == EXIT_BAR for b in days[d]):
                continue
            for lvl, buf in ALL_VERSIONS:
                key = (str(d), name, vname(lvl, buf))
                if key in done:
                    continue
                lv = levels(days, d, lvl)
                if lv is None:
                    continue
                tr = trade_day(days[d], lv[0], lv[1], buf, lv[2])
                row = {"day": str(d), "index": name, "version": vname(lvl, buf), "level_high": round(lv[0], 2),
                       "level_low": round(lv[1], 2)}
                row.update(tr or {"side": None, "r": None, "exit": "no trade"})
                new.append(row)
    with open(LOG, "a") as f:
        for row in new:
            f.write(json.dumps(row) + "\n")
    for row in new:
        print("%s %-9s %-8s %s" % (row["day"], row["index"], row["version"], "no trade" if row["r"] is None else
              "%s %s at %.2f, stop %.2f, target %.2f -> %s %+.2fR" % (row["side"], row["entry_time"], row["entry"],
                                                                      row["stop"], row["target"], row["exit"], row["r"])))
    print("%d new rows -> %s" % (len(new), LOG))


def cmd_summary(args):
    rows = read_log()
    days = sorted({r["day"] for r in rows})
    if not days:
        print("forward test: no days scored yet")
        return
    print("forward test %s to %s (%d days), rules fixed 13 Nov 2026; * = passed the pre-set bar" % (
        days[0], days[-1], len(days)))
    for lvl, buf in sorted(ALL_VERSIONS, key=lambda x: x not in CANDIDATES):
        v = vname(lvl, buf) + ("*" if (lvl, buf) in CANDIDATES else "")
        allr = []
        for name in INDICES:
            rs = [r["r"] for r in rows if r["version"] == v.rstrip("*") and r["index"] == name and r["r"] is not None]
            allr += rs
            print("  %-8s %-9s %s" % (v, name, stats(rs)))
        print("  %-8s %-9s %s" % (v, "all", stats(allr)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("backtest")
    s = sub.add_parser("score")
    s.add_argument("--since", default=str(FORWARD_START))
    sub.add_parser("summary")
    a = ap.parse_args(argv)
    return {"backtest": cmd_backtest, "score": cmd_score, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
