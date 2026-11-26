#!/usr/bin/env python3
"""Liquidity models on two timeframes: intraday sweep -> inversion FVG -> retest, and the multi-day Wyckoff spring.

Both come from Aditya's read of 26 Nov 2026 (Nifty swept the opening-range low, a candle closed back through the
fair value gaps of the drop, the pullback held above them and price ran) and the Wyckoff idea that the same
"take the liquidity, reclaim, go" pattern works days apart. The rules were fixed on 26 Nov 2026, before the first
backtest, and must not be tuned during the forward test (from 27 Nov 2026).

Intraday (per index per day, bars of 5, 3 or 1 minutes; a long is described, a short is the mirror image):
  1. Level: the opening-range low (09:15-09:30; sweeps count from 09:30) or the previous day's low (from 09:15).
  2. Sweep: a bar trades below the level. The sweep low is the lowest low until the inversion.
  3. Bearish FVGs: three bars where bar 1's low is above bar 3's high, completed from 6 bars before the sweep on.
  4. Inversion: within 12 bars of the sweep, a bar closes above an FVG's top. That FVG (the highest one closed
     through) is the IFVG.
  5. Entry: the first later bar that trades back to the IFVG's top fills there (at the open if it opens below),
     bars up to 11:25. If the sweep low trades before the price returns, the setup is off.
  6. Stop at the sweep low; target 2R; otherwise out at the close of the 15:10 bar. Inside a bar the stop comes
     first, and the entry bar can only stop. One trade per index per day, the first fill of either side.

  Backtest before the forward test (5m, 17 Aug - 25 Nov 2026, 3 indices x 2 levels, 174 trades): 37% wins,
  +0.05R gross, -0.02R after 0.01% costs, PF 0.97; the same bracket the other way +0.17R. Longs -0.16R net (69),
  shorts +0.07R (105). No edge on its own yet; entries 09:40-09:59 did better (+0.35R, 37) but that slice was
  found after looking, so it is only a hypothesis for the forward test.

Multi-day (daily closes, index level, no stop):
  spring-20 / spring-60: the day trades below the lowest low of the previous 20 / 60 sessions and closes back
  above it. Buy at that close, hold 10 sessions. One hold at a time per index and rule: events inside an open
  hold are skipped (springs cluster on consecutive days in a falling market).
  upthrust-20: the mirror at the 20-session high, only when that 20-session range is at most 6% of the close.
  Sell at the close, hold 10 sessions.

  10-year check (Nov 2016 - Nov 2026, one hold at a time; the index's average 10-session move was about +0.7% in
  2017-21 and +0.3% to +0.5% in 2022-26): spring-20 made +0.5% to +1.9% a hold in 2022-26 on all three indices
  but about 0 in 2017-21 (below drift). spring-60 was strong in 2022-26 (+1.3% to +3.0%, 14-16 holds) and lost
  in 2017-21 (-0.6% to -2.6%). upthrust-20 shorts made about +0.5% in 2022-26 on Nifty and Sensex, lost in
  2017-21, and lost in both halves on Bank Nifty. It depends on the regime: worth tracking, not proven.

  python3 liquidity.py backtest          # intraday on the archive (Aug-Oct vs Nov), and the 10-year daily check
  python3 liquidity.py score             # score each finished day / finished 10-day hold since 27 Nov (idempotent)
  python3 liquidity.py summary           # forward-test results so far

Results go to ict/research/liquidity-forward.jsonl (git-ignored). Standard library only.
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
INTRADAY = [(tf, lvl) for tf in (5, 3, 1) for lvl in ("or", "pd")]
DAILY = {"spring-20": (20, None, 1), "spring-60": (60, None, 1), "upthrust-20": (20, 0.06, -1)}
HOLD = 10
FORWARD_START = date(2026, 11, 27)
OR_END, LAST_ENTRY, EXIT_BAR = T(9, 30), T(11, 25), T(15, 10)
FVG_BEFORE, INVERT_WITHIN = 6, 12
COST = 0.0001                                    # 0.01% of the price per round trip, for the net column
LOG = os.path.join(mmxm.STATE_DIR, "research", "liquidity-forward.jsonl")


# ---------------------------------------------------------------- intraday

def load_days(symbol, tf):
    """{date: [(time, o, h, l, c), ...]} of tf-minute bars, full sessions only (needs a bar at or after 15:10)."""
    src = "5m" if tf == 5 else "1m"
    with open(optbt.archive_name(symbol, src)) as f:
        raw = json.load(f)["bars"]
    days = collections.OrderedDict()
    for t, o, h, l, c, v in raw:
        lt = mmxm.to_local(t, "Asia/Kolkata")
        m = (lt.hour * 60 + lt.minute - 555) // tf * tf + 555
        key = T(m // 60, m % 60)
        b = days.setdefault(lt.date(), [])
        if b and b[-1][0] == key:
            b[-1] = (key, b[-1][1], max(b[-1][2], h), min(b[-1][3], l), c)
        else:
            b.append((key, o, h, l, c))
    return collections.OrderedDict((d, b) for d, b in days.items()
                                   if len(b) >= 240 // tf and any(x[0] >= EXIT_BAR for x in b))


def flip(bars):
    """Mirror prices so a short can be found and managed with the long code."""
    return [(t, -o, -l, -h, -c) for t, o, h, l, c in bars]


def long_setup(bars, level, start):
    """(entry bar index, entry price, stop) of the first long fill, or None."""
    s = next((i for i, b in enumerate(bars) if start <= b[0] <= LAST_ENTRY and b[3] < level), None)
    if s is None:
        return None
    low, ifvg = bars[s][3], None
    for j in range(s, min(len(bars), s + INVERT_WITHIN + 1)):
        t, o, h, l, c = bars[j]
        if t > LAST_ENTRY:
            return None
        low = min(low, l)
        gaps = [(bars[i][2], bars[i - 2][3]) for i in range(max(2, s - FVG_BEFORE), j) if bars[i - 2][3] > bars[i][2]]
        through = [g for g in gaps if c > g[1]]
        if through:
            ifvg, inv = max(through, key=lambda g: g[1]), j
            break
    if ifvg is None:
        return None
    top = ifvg[1]
    for k in range(inv + 1, len(bars)):
        t, o, h, l, c = bars[k]
        if t > LAST_ENTRY or o <= low:
            return None
        if l <= top:
            return k, min(o, top), low
    return None


def manage(bars, k, entry, stop):
    """(R, how) for a long from bar k: 2R target, stop first, the entry bar can only stop, out at the 15:10 bar."""
    risk = entry - stop
    if risk <= 0:
        return None
    target = entry + 2 * risk
    if bars[k][3] <= stop:
        return -1.0, "stop"
    last = bars[k][4]
    for t, o, h, l, c in bars[k + 1:]:
        if t > EXIT_BAR:
            break
        if l <= stop:
            return -1.0, "stop"
        if h >= target:
            return 2.0, "target"
        last = c
    return (last - entry) / risk, "close"


def levels(days, d, lvl):
    bars = days[d]
    if lvl == "or":
        orb = [b for b in bars if b[0] < OR_END]
        return max(b[2] for b in orb), min(b[3] for b in orb), OR_END
    keys = list(days)
    k = keys.index(d)
    if k == 0 or (d - keys[k - 1]).days > 5:     # no previous session in the data
        return None
    prev = days[keys[k - 1]]
    return max(b[2] for b in prev), min(b[3] for b in prev), T(9, 15)


def trade_day(bars, hi, lo, start):
    """The day's first fill of either side as a dict, or None."""
    found = []
    L = long_setup(bars, lo, start)
    if L:
        found.append(("long", L, bars))
    fb = flip(bars)
    S = long_setup(fb, -hi, start)
    if S:
        found.append(("short", S, fb))
    if not found:
        return None
    side, (k, entry, stop), bb = min(found, key=lambda x: x[1][0])
    m = manage(bb, k, entry, stop)
    if m is None:
        return None
    sign = 1 if side == "long" else -1
    return {"side": side, "entry_time": bb[k][0].strftime("%H:%M"), "entry": round(sign * entry, 2),
            "stop": round(sign * stop, 2), "risk_pct": round(100 * (entry - stop) / abs(entry), 3),
            "r": round(m[0], 3), "exit": m[1]}


def vname(tf, lvl):
    return "ifvg-%dm-%s" % (tf, lvl)


# ---------------------------------------------------------------- multi-day

def daily_events(bars, name_rule):
    """[(index, direction)] of the rule's event days in bars [(date, o, h, l, c)]."""
    n, max_range, direction = DAILY[name_rule]
    out = []
    for i in range(n, len(bars)):
        prev = bars[i - n:i]
        lo, hi = min(b[3] for b in prev), max(b[2] for b in prev)
        d, o, h, l, c = bars[i]
        if max_range is not None and (hi - lo) / c > max_range:
            continue
        if direction > 0 and l < lo and c > lo:
            out.append((i, 1))
        if direction < 0 and h > hi and c < hi:
            out.append((i, -1))
    return out


def one_at_a_time(events):
    """Drop events that come while the rule's previous hold is still open (springs cluster in falling markets)."""
    out, free = [], -1
    for i, d in events:
        if i >= free:
            out.append((i, d))
            free = i + HOLD
    return out


def daily_bars(symbol, rng=None):
    if rng:
        doc = optbt.fetch(symbol, "1d", rng)
        b = optbt.ist_bars(doc)
    else:
        b = optbt.load(symbol, "1d", max_age=6 * 3600)
    return [(x[0].date(), x[1], x[2], x[3], x[4]) for x in b if x[4]]


# ---------------------------------------------------------------- commands

def stats(rows):
    if not rows:
        return "  0 trades"
    rs = [r["r"] for r in rows]
    net = [r["r"] - 100 * COST / r["risk_pct"] for r in rows]
    w = sum(1 for r in rs if r > 0)
    pos, neg = sum(x for x in net if x > 0), -sum(x for x in net if x <= 0)
    return "%3d trades  win %3.0f%%  avg %+5.2fR  net %+5.2fR  total %+6.1fR  PF %4.2f" % (
        len(rs), 100.0 * w / len(rs), sum(rs) / len(rs), sum(net) / len(net), sum(net), pos / neg if neg else float("inf"))


def dstats(rows):
    if not rows:
        return "  0 events"
    rs = [r["ret_pct"] for r in rows]
    return "%3d events  win %3.0f%%  avg %+5.2f%%  total %+6.2f%%" % (
        len(rs), 100.0 * sum(1 for x in rs if x > 0) / len(rs), sum(rs) / len(rs), sum(rs))


def cmd_backtest(args):
    split = date(2026, 11, 1)
    for name, sym in INDICES.items():
        for tf, lvl in INTRADAY:
            days = load_days(sym, tf)
            before, after = [], []
            for d in days:
                lv = levels(days, d, lvl)
                tr = lv and trade_day(days[d], lv[0], lv[1], lv[2])
                if tr:
                    (before if d < split else after).append(tr)
            print("%-9s %-12s before Nov: %s | Nov on: %s" % (name, vname(tf, lvl), stats(before), stats(after)))
    if args.no_daily:
        return
    print("\nmulti-day, 10 years of daily bars, hold %d sessions (return in the trade's direction):" % HOLD)
    for name, sym in INDICES.items():
        bars = daily_bars(sym, "10y")
        for rule in DAILY:
            rows = [{"day": bars[i][0], "ret_pct": 100 * dr * (bars[i + HOLD][4] / bars[i][4] - 1)}
                    for i, dr in one_at_a_time(daily_events(bars, rule)) if i + HOLD < len(bars)]
            a = [r for r in rows if r["day"].year <= 2021]
            b = [r for r in rows if r["day"].year >= 2022]
            print("%-9s %-12s 2017-21: %s | 2022-26: %s" % (name, rule, dstats(a), dstats(b)))


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(line) for line in f if line.strip()]


def cmd_score(args):
    """Log every finished day (intraday) and every finished 10-session hold (multi-day) from --since.
    Run `optbt.py archive` first: the intraday part reads the 5m and 1m archive."""
    since = date.fromisoformat(args.since)
    today = mmxm.to_local(datetime.now().timestamp(), "Asia/Kolkata").date()
    done = {(r["day"], r["index"], r["version"]) for r in read_log()}
    new = []
    for name, sym in INDICES.items():
        for tf, lvl in INTRADAY:
            days = load_days(sym, tf)
            for d in days:
                key = (str(d), name, vname(tf, lvl))
                if d < since or d >= today or key in done:
                    continue
                lv = levels(days, d, lvl)
                if lv is None:
                    continue
                row = {"day": str(d), "index": name, "version": vname(tf, lvl)}
                row.update(trade_day(days[d], lv[0], lv[1], lv[2]) or {"side": None, "r": None, "exit": "no trade"})
                new.append(row)
        bars = [b for b in daily_bars(sym) if b[0] < today]
        for rule in DAILY:
            for i, dr in one_at_a_time(daily_events(bars, rule)):
                d = bars[i][0]
                key = (str(d), name, rule)
                if d < since or key in done or i + HOLD >= len(bars):
                    continue
                new.append({"day": str(d), "index": name, "version": rule, "side": "long" if dr > 0 else "short",
                            "entry": round(bars[i][4], 2), "exit_day": str(bars[i + HOLD][0]),
                            "exit": round(bars[i + HOLD][4], 2),
                            "ret_pct": round(100 * dr * (bars[i + HOLD][4] / bars[i][4] - 1), 3)})
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        for row in new:
            f.write(json.dumps(row) + "\n")
    for row in new:
        if "ret_pct" in row:
            print("%s %-9s %-12s %s at %.2f, %s %.2f -> %+.2f%%" % (row["day"], row["index"], row["version"], row["side"],
                                                                 row["entry"], row["exit_day"], row["exit"], row["ret_pct"]))
        else:
            print("%s %-9s %-12s %s" % (row["day"], row["index"], row["version"], "no trade" if row["r"] is None else
                  "%s %s at %.2f, stop %.2f -> %s %+.2fR" % (row["side"], row["entry_time"], row["entry"], row["stop"],
                                                            row["exit"], row["r"])))
    print("%d new rows -> %s" % (len(new), LOG))
    if args.watch:
        for name, sym in INDICES.items():
            bars = [b for b in daily_bars(sym) if b[0] < today]
            for rule in DAILY:
                for i, dr in one_at_a_time(daily_events(bars, rule)):
                    if i + HOLD >= len(bars) and bars[i][0] >= since:
                        print("open: %s %s %s from %s at %.2f, %d of %d sessions held" % (
                            name, rule, "long" if dr > 0 else "short", bars[i][0], bars[i][4], len(bars) - 1 - i, HOLD))


def cmd_summary(args):
    rows = read_log()
    if not rows:
        print("liquidity forward test: nothing scored yet (from %s)" % FORWARD_START)
        return
    days = sorted({r["day"] for r in rows})
    print("liquidity forward test %s to %s, rules fixed 26 Nov 2026" % (days[0], days[-1]))
    for tf, lvl in INTRADAY:
        v = vname(tf, lvl)
        allr = []
        for name in INDICES:
            rs = [r for r in rows if r["version"] == v and r["index"] == name and r.get("r") is not None]
            allr += rs
            print("  %-12s %-9s %s" % (v, name, stats(rs)))
        print("  %-12s %-9s %s" % (v, "all", stats(allr)))
    for rule in DAILY:
        rs = [r for r in rows if r["version"] == rule]
        print("  %-12s %-9s %s" % (rule, "all", dstats(rs)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("backtest")
    b.add_argument("--no-daily", action="store_true", help="skip the 10-year daily download")
    s = sub.add_parser("score")
    s.add_argument("--since", default=str(FORWARD_START))
    s.add_argument("--watch", action="store_true", help="also list multi-day holds still running")
    sub.add_parser("summary")
    a = ap.parse_args(argv)
    return {"backtest": cmd_backtest, "score": cmd_score, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
