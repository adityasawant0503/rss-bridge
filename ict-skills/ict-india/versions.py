#!/usr/bin/env python3
"""Every candidate version of the Morning Fade (and its rivals) scored on the same days. Paper research only.

Rules fixed 25 Nov 2026, before any of these versions were scored together. Each finished day, for Nifty and
Sensex, the option the rule would buy at 10:15 is priced along the day with Black-Scholes on the 5m index bars,
using an implied volatility fitted to that contract's REAL exchange open and close (NSE/BSE bhavcopy) and kept
inside the real day's high and low. So the path is modelled, but its level and range are the real ones.
Costs: 0.5% of the entry premium per fill, plus Rs 40 per fill. One lot = the exchange lot (Nifty 65, Sensex 20).

Exits, all on the fade's at-the-money option (puts after a 5-day rise, calls after a fall), entry 10:15:
  V1 pyramid-avg   add 1 lot at +15%, then both stops to the average; target +40% (the current paper rule)
  V2 pyramid-keep  add 1 lot at +15%, keep the -20% stop; target +40%
  V3 plain         1 lot, stop -20%, target +40%
  V4 quick         1 lot, stop -20%, target +15% (negative risk-reward)
  V5 pyramid-trail as V2, but at +40% move both stops to +25% and ride to the close
  V6 plain-trail   1 lot, stop -20%; at +40% move the stop to +25% and ride to the close
  V7 plain-close   1 lot, stop -20%, no target, out at the close
  V8 itm           as V3, one strike in the money
Other entries, scored with the V3 exits:
  E1 fade-gap      the fade only when the opening gap (>= 0.1%) points the same way
  E2 gap           follow the opening gap
  E3 turn-short    puts only, when the index is up over 5 days but closed down yesterday (combined-rule search)
  E4 fade-pulse    the fade only when Aditya's PulsEdge pre-market reading agrees (from 16 Nov 2026)
Results are rupees per trade; the forward part (from 26 Nov 2026) is what counts, the backfill is context.

  python3 versions.py score [--since 2026-08-24]   # score every finished day not yet logged (idempotent)
  python3 versions.py summary                       # backfill and forward tables
"""
import argparse
import collections
import json
import math
import os
import statistics
import sys
import time
from datetime import date, datetime, timedelta, time as T

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm      # noqa: E402
import optbt     # noqa: E402
import variants  # noqa: E402

INDICES = {"NIFTY": {"yahoo": "^NSEI", "ex": "nse", "step": 50}, "SENSEX": {"yahoo": "^BSESN", "ex": "bse", "step": 100}}
FORWARD_START = date(2026, 11, 26)
BACKFILL_START = date(2026, 8, 24)
EXITS = ["V1 pyramid-avg", "V2 pyramid-keep", "V3 plain", "V4 quick", "V5 pyramid-trail", "V6 plain-trail", "V7 plain-close"]
ENTRIES = ["V8 itm", "E1 fade-gap", "E2 gap", "E3 turn-short", "E4 fade-pulse"]
SLIP, FEE = 0.005, 40.0
ENTRY, EXIT = T(10, 15), T(15, 15)
LOG = os.path.join(mmxm.STATE_DIR, "research", "versions.jsonl")
PULSE_LOG = os.path.join(mmxm.STATE_DIR, "research", "premarket-log.jsonl")


# ---------------------------------------------------------------- exits (pure, tested offline)

def run_exit(rule, P0, path):
    """path: [(worst, best, close)] option prices per bar after entry (worst first inside a bar).
    Returns (points summed over lots, number of fills), before costs."""
    pyramid = rule in ("V1 pyramid-avg", "V2 pyramid-keep", "V5 pyramid-trail")
    trail = rule in ("V5 pyramid-trail", "V6 plain-trail")
    target = {"V4 quick": 1.15}.get(rule, None if rule == "V7 plain-close" else 1.40)
    fills, stop, trailing = [P0], 0.8 * P0, False
    for k, (w, b, c) in enumerate(path):
        if w <= stop:
            return sum(stop - f for f in fills), len(fills) * 2
        added = False
        if pyramid and len(fills) == 1 and b >= 1.15 * P0:
            fills.append(1.15 * P0)
            added = True
            if rule == "V1 pyramid-avg":
                stop = max(stop, sum(fills) / 2)
        if target and not added and not trailing and b >= target * P0:
            if trail:
                trailing, stop = True, max(stop, 1.25 * P0)
                continue
            return sum(target * P0 - f for f in fills), len(fills) * 2
    return sum(path[-1][2] - f for f in fills), len(fills) * 2


# ---------------------------------------------------------------- pricing one day

def implied(price, S, K, tau, kind):
    lo, hi = 0.01, 2.0
    if price <= max(0.0, (S - K) if kind == "CE" else (K - S)) + 0.05:
        return None
    for _ in range(60):
        m = (lo + hi) / 2
        lo, hi = (m, hi) if optbt.bs(S, K, tau, m, kind) < price else (lo, m)
    return (lo + hi) / 2


def option_path(bars, row, K, kind, exp):
    """(entry price at 10:15, [(worst, best, close)] after it) for one contract, or None."""
    day = bars[0][0].date()
    t_open, t_close = datetime.combine(day, T(9, 15)), datetime.combine(day, T(15, 30))
    v0 = implied(row["o"], bars[0][1], K, optbt.tau_years(t_open, exp), kind)
    v1 = implied(row["c"], bars[-1][4], K, optbt.tau_years(t_close, exp), kind)
    if not v0 or not v1:
        return None
    n = len(bars)
    clip = lambda p: min(max(p, row["l"]), row["h"])
    def px(S, k, t):
        return clip(optbt.bs(S, K, optbt.tau_years(t, exp), v0 + (v1 - v0) * k / max(1, n - 1), kind))
    et = datetime.combine(day, ENTRY)
    before = [k for k, b in enumerate(bars) if b[0] < et]
    after = [k for k, b in enumerate(bars) if b[0] >= et and (b[0] + timedelta(minutes=5)).time() <= EXIT]
    if not before or not after:
        return None
    P0 = px(bars[before[-1]][4], before[-1], et)
    path = []
    for k in after:
        t = bars[k][0] + timedelta(minutes=5)
        a, b = px(bars[k][2], k, t), px(bars[k][3], k, t)
        path.append((min(a, b), max(a, b), px(bars[k][4], k, t)))
    return P0, path


def pulse_agree():
    out = {}
    if os.path.exists(PULSE_LOG):
        with open(PULSE_LOG) as f:
            for line in f:
                if line.strip():
                    r = json.loads(line)
                    out[r["day"]] = r.get("agree")
    return out


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(x) for x in f if x.strip()]


def cmd_score(args):
    since = date.fromisoformat(args.since)
    today = mmxm.to_local(time.time(), "Asia/Kolkata").date()
    done = {(r["day"], r["index"]) for r in read_log()}
    agree = pulse_agree()
    new = []
    for name, ix in INDICES.items():
        d = optbt.daily(optbt.load(ix["yahoo"], "1d", max_age=6 * 3600))
        days = sorted(d)
        ses = variants.sessions(ix["yahoo"])
        lot_of = lambda day: optbt.lot_size(name, day)
        for day in sorted(ses):
            if day < since or day >= today or (str(day), name) in done or day not in d or days.index(day) < 6:
                continue
            rows = variants.bhavcopy(day, ix["ex"])
            if rows is None:
                continue                                   # exchange file not out yet: next run
            i = days.index(day)
            sides, gap = variants.sides(days, d, i)
            fade = sides["fade"]
            c = lambda k: d[days[i - k]][4]
            turn = "PE" if c(1) > c(6) and c(1) < c(2) else None
            bars = ses[day]
            S0 = [b for b in bars if b[0].time() < ENTRY][-1][4]
            atm = round(S0 / ix["step"]) * ix["step"]
            exps = sorted({r["exp"] for r in rows if (r["exp"] - day).days >= 4})
            rec = {"day": str(day), "index": name, "fade": fade, "gap_pct": round(100 * gap, 3), "results": {}}
            if not exps:
                new.append(rec)
                continue
            exp = exps[0]
            lot = lot_of(day)

            def trade(kind, K, rules):
                q = next((r for r in rows if r["exp"] == exp and r["k"] == K and r["typ"] == kind and r["vol"] > 0 and r["o"] > 0), None)
                if not q:
                    return {}
                got = option_path(bars, q, K, kind, exp)
                if not got:
                    return {}
                P0, path = got
                out = {}
                for rule in rules:
                    pts, fills = run_exit(rule, P0, path)
                    out[rule] = round(pts * lot - fills * (SLIP * P0 * lot + FEE), 0)
                out["_entry"] = round(P0, 2)
                return out

            res = trade(fade, atm, EXITS)
            entry = res.pop("_entry", None)
            rec["results"].update(res)
            rec["entry"], rec["strike"], rec["expiry"] = entry, atm, str(exp)
            itm = atm - ix["step"] if fade == "CE" else atm + ix["step"]
            r8 = trade(fade, itm, ["V3 plain"])
            if "V3 plain" in r8:
                rec["results"]["V8 itm"] = r8["V3 plain"]
            if sides["fade-gap"] and "V3 plain" in res:
                rec["results"]["E1 fade-gap"] = res["V3 plain"]
            if sides["gap"]:
                r2 = res if sides["gap"] == fade else trade(sides["gap"], atm, ["V3 plain"])
                if "V3 plain" in r2:
                    rec["results"]["E2 gap"] = r2["V3 plain"]
            if turn:
                r3 = res if turn == fade else trade(turn, atm, ["V3 plain"])
                if "V3 plain" in r3:
                    rec["results"]["E3 turn-short"] = r3["V3 plain"]
            if agree.get(str(day)) is True and "V3 plain" in res:
                rec["results"]["E4 fade-pulse"] = res["V3 plain"]
            new.append(rec)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        for r in new:
            f.write(json.dumps(r) + "\n")
    for r in new[-6:]:
        print("%s %-6s %s entry %s: %s" % (r["day"], r["index"], r["fade"], r.get("entry"),
              ", ".join("%s %+.0f" % (k.split()[0], v) for k, v in sorted(r["results"].items()))))
    print("%d new days -> %s" % (len(new), LOG))


def table(rows, title):
    print(title)
    print("  %-18s %6s %6s %10s %8s %6s %10s" % ("version", "trades", "win", "total Rs", "avg Rs", "PF", "worst DD"))
    for v in EXITS + ENTRIES:
        series = [(r["day"], r["results"][v]) for r in rows if v in r["results"]]
        series.sort()
        p = [x for _, x in series]
        if not p:
            print("  %-18s %6d" % (v, 0))
            continue
        w = sum(x for x in p if x > 0)
        l = -sum(x for x in p if x <= 0)
        eq = pk = dd = 0.0
        for x in p:
            eq += x
            pk = max(pk, eq)
            dd = min(dd, eq - pk)
        print("  %-18s %6d %5.0f%% %+10.0f %+8.0f %6s %+10.0f" % (
            v, len(p), 100.0 * sum(x > 0 for x in p) / len(p), sum(p), sum(p) / len(p),
            "%.2f" % (w / l) if l else "inf", dd))


def cmd_summary(args):
    rows = read_log()
    if not rows:
        print("versions: nothing scored yet")
        return
    back = [r for r in rows if date.fromisoformat(r["day"]) < FORWARD_START]
    fwd = [r for r in rows if date.fromisoformat(r["day"]) >= FORWARD_START]
    if back:
        table(back, "BACKFILL %s to %s (%d index-days; modelled path on real prices; context only)" % (
            min(r["day"] for r in back), max(r["day"] for r in back), len(back)))
    table(fwd, "FORWARD from %s (%d index-days; this is what counts)" % (FORWARD_START, len(fwd)))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--since", default=str(BACKFILL_START))
    sub.add_parser("summary")
    a = ap.parse_args(argv)
    return {"score": cmd_score, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
