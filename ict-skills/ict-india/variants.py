#!/usr/bin/env python3
"""Side-by-side forward test of Morning Fade variants found in Aditya's own trades. Paper research only.

The rules were fixed on 17 Nov 2026, before the forward test, from two things in the trades:
  * 2025 (Dhan/Fyers, 260 index-option round trips): trades in the direction of the opening gap made money
    (PF 2.65); trades against the gap (PF 0.38) and on flat opens (PF 0.23) lost on most days.
  * Nov 2026 paper trades: the fade's puts kept running up after 10:15, then gave it back by midday.

  fade      the Morning Fade without the pyramid: puts after a 5-day rise, calls after a fall
  fade-gap  the fade only when today's opening gap (open vs previous close, at least 0.1%) points the same way
  gap       follow the gap: calls on a gap up, puts on a gap down, no trade on a flat open

All: 1 lot, at-the-money weekly option at least 4 days to expiry, stop -20%, target +40% of the entry price.
Each finished day is scored two ways, with no discretion:
  model  entry 10:15 on the 5m archive, Black-Scholes from the previous day's India VIX x 0.97 (as optbt),
         the stop counted first inside a bar, otherwise out at 15:15
  real   the exchange's daily prices (NSE/BSE bhavcopy): bought at the day's open, stop and target against the
         day's low and high (the stop counts first if both were touched), otherwise the close

Before the forward test (same scoring, PF): real Sep 2025-13 Nov 2026 fade 0.62 Nifty / 0.87 Sensex,
fade-gap 1.06 / 1.57, gap 1.03 / 1.27; model 2 years at 10:15 fade 1.21 / 1.28, fade-gap 1.36 / 1.29,
gap 1.21 / 1.19. None met the bar set beforehand (PF >= 1.15 on both indices in both tests), and the last
three months were about break-even or worse for all of them. Out-by-11:15 versions were worse and dropped.

  python3 variants.py today      # today's gap and what each version would buy
  python3 variants.py score      # fetch missing bhavcopies, score each finished day since 18 Nov 2026
  python3 variants.py summary    # forward results so far

Results go to ict/research/ (git-ignored). Standard library only.
"""
import argparse
import collections
import csv
import io
import json
import os
import sys
import time
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, time as T

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm    # noqa: E402
import optbt   # noqa: E402

INDICES = {"NIFTY": {"yahoo": "^NSEI", "ex": "nse", "step": 50}, "SENSEX": {"yahoo": "^BSESN", "ex": "bse", "step": 100}}
VERSIONS = ["fade", "fade-gap", "gap"]
FORWARD_START = date(2026, 11, 18)
STOP, TARGET, MIN_DTE, FLAT_GAP = 0.20, 0.40, 4, 0.001
ENTRY, EXIT = T(10, 15), T(15, 15)
OPT_DIR = os.path.join(optbt.MARKET_DIR, "options")
LOG = os.path.join(mmxm.STATE_DIR, "research", "variants-forward.jsonl")
URLS = {"nse": "https://nsearchives.nseindia.com/content/fo/BhavCopy_NSE_FO_0_0_0_%s_F_0000.csv.zip",
        "bse": "https://www.bseindia.com/download/Bhavcopy/Derivative/BhavCopy_BSE_FO_0_0_0_%s_F_0000.CSV"}
KEEP = ("TradDt", "XpryDt", "StrkPric", "OptnTp", "OpnPric", "HghPric", "LwPric", "ClsPric", "UndrlygPric",
        "SttlmPric", "TtlTradgVol", "OpnIntrst")


def sides(days, d, i):
    """{version: 'CE' | 'PE' | None} for trading day index i, and the gap as a fraction."""
    o, pc = d[days[i]][1], d[days[i - 1]][4]
    gap = (o - pc) / pc
    g = None if abs(gap) < FLAT_GAP else ("CE" if gap > 0 else "PE")
    f = optbt.bias_for(days, d, i, "fade")
    return {"fade": f, "fade-gap": f if g == f else None, "gap": g}, gap


def real_result(o, h, l, c):
    """(return as a fraction of the open price, how) for a long option bought at the open."""
    if l <= o * (1 - STOP):
        return -STOP, "stop"
    if h >= o * (1 + TARGET):
        return TARGET, "target"
    return c / o - 1, "close"


def model_result(bars, side, k, exp, vol, slippage=1.0):
    """bars: [(datetime, o, h, l, c)] of one day's 5m session. (entry, return, how) or None before 10:15."""
    et = datetime.combine(bars[0][0].date(), ENTRY)
    before = [b for b in bars if b[0] < et]
    after = [b for b in bars if b[0] >= et and (b[0] + timedelta(minutes=5)).time() <= EXIT]
    if not before or not after:
        return None
    px = lambda S, t: optbt.bs(S, k, optbt.tau_years(t, exp), vol, side)
    P0 = px(before[-1][4], et) + slippage
    last = P0
    for t, o, h, l, c in after:
        t5 = t + timedelta(minutes=5)
        if px(l if side == "CE" else h, t5) <= P0 * (1 - STOP):
            return P0, -STOP, "stop"
        if px(h if side == "CE" else l, t5) >= P0 * (1 + TARGET):
            return P0, TARGET, "target"
        last = px(c, t5)
    return P0, (last - slippage) / P0 - 1, "close"


def bhavcopy(day, ex):
    """Near-the-money index option rows for one day from the cache, downloading the exchange file if needed.
    None when the exchange hasn't published it (or the day had no trading)."""
    path = os.path.join(OPT_DIR, "%s-%s.csv" % (day, ex))
    if not os.path.exists(path):
        try:
            req = urllib.request.Request(URLS[ex] % day.strftime("%Y%m%d"),
                                         headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.bseindia.com/"})
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read()
            if ex == "nse":
                z = zipfile.ZipFile(io.BytesIO(raw))
                raw = z.read(z.namelist()[0])
        except Exception:
            return None
        sym = "NIFTY" if ex == "nse" else "SENSEX"
        rows = []
        for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace"))):
            try:
                u, k = float(r["UndrlygPric"]), float(r["StrkPric"])
                dte = (date.fromisoformat(r["XpryDt"]) - date.fromisoformat(r["TradDt"])).days
            except (KeyError, ValueError):
                continue
            if r.get("TckrSymb") == sym and r.get("OptnTp") in ("CE", "PE") and u > 0 and abs(k / u - 1) <= 0.04 and 0 <= dte <= 21:
                rows.append({c: r[c] for c in KEEP})
        if not rows:
            return None
        os.makedirs(OPT_DIR, exist_ok=True)
        with open(path + ".part", "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(KEEP))
            w.writeheader()
            w.writerows(rows)
        os.replace(path + ".part", path)
    out = []
    with open(path) as f:
        for r in csv.DictReader(f):
            try:
                out.append({"exp": date.fromisoformat(r["XpryDt"]), "k": float(r["StrkPric"]), "typ": r["OptnTp"],
                            "o": float(r["OpnPric"]), "h": float(r["HghPric"]), "l": float(r["LwPric"]),
                            "c": float(r["ClsPric"]), "vol": float(r["TtlTradgVol"] or 0)})
            except ValueError:
                pass
    return out


def sessions(symbol):
    """{date: [(datetime, o, h, l, c)]} from the 5m archive, full sessions only."""
    with open(optbt.archive_name(symbol, "5m")) as f:
        bars = json.load(f)["bars"]
    days = collections.defaultdict(list)
    for t, o, h, l, c, v in bars:
        lt = mmxm.to_local(t, "Asia/Kolkata")
        days[lt.date()].append((lt, o, h, l, c))
    return {d: b for d, b in days.items() if len(b) >= 60}


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(x) for x in f if x.strip()]


def cmd_today(args):
    today = mmxm.to_local(time.time(), "Asia/Kolkata").date()
    for name, ix in INDICES.items():
        d = optbt.daily(optbt.load(ix["yahoo"], "1d", max_age=600))
        days = sorted(x for x in d if x <= today)
        if days[-1] != today:
            print("%s: no bars for today yet" % name)
            continue
        sd, gap = sides(days, d, len(days) - 1)
        exp = optbt.weekly_expiry(name, today, MIN_DTE)
        print("%s gap %+.2f%%: %s  (expiry %s)" % (name, 100 * gap, ", ".join(
            "%s %s" % (v, "no trade" if sd[v] is None else "buys " + ("CALLS" if sd[v] == "CE" else "PUTS")) for v in VERSIONS),
            exp.strftime("%d %b").upper()))


def cmd_score(args):
    since = date.fromisoformat(args.since)
    today = mmxm.to_local(time.time(), "Asia/Kolkata").date()
    done = {(r["day"], r["index"], r["version"]) for r in read_log()}
    vix = optbt.daily(optbt.load(optbt.VIX, "1d"))
    new = []
    for name, ix in INDICES.items():
        d = optbt.daily(optbt.load(ix["yahoo"], "1d"))
        days = sorted(d)
        ses = sessions(ix["yahoo"])
        for day in sorted(ses):
            if day < since or day >= today or day not in d or days.index(day) < 6:
                continue
            if all((str(day), name, v) in done for v in VERSIONS):
                continue
            rows = bhavcopy(day, ix["ex"])
            if rows is None and (today - day).days < 7:
                continue                              # not published yet: try again next run
            sd, gap = sides(days, d, days.index(day))
            k_real = round(d[day][1] / ix["step"]) * ix["step"]
            exps = sorted({r["exp"] for r in rows or [] if (r["exp"] - day).days >= MIN_DTE})
            prev = [x for x in vix if x < day]
            vol = vix[max(prev)][4] / 100 * 0.97
            bars = ses[day]
            S0 = [b for b in bars if b[0].time() < ENTRY][-1][4]
            k_model = round(S0 / ix["step"]) * ix["step"]
            exp_model = optbt.weekly_expiry(name, day, MIN_DTE)
            for v in VERSIONS:
                if (str(day), name, v) in done:
                    continue
                row = {"day": str(day), "index": name, "version": v, "gap_pct": round(100 * gap, 3), "side": sd[v]}
                if sd[v]:
                    m = model_result(bars, sd[v], k_model, exp_model, vol)
                    if m:
                        row.update({"model_strike": k_model, "model_expiry": str(exp_model), "model_entry": round(m[0], 2),
                                    "model_ret": round(m[1], 4), "model_how": m[2]})
                    q = next((r for r in rows or [] if exps and r["exp"] == exps[0] and r["k"] == k_real and
                              r["typ"] == sd[v] and r["vol"] > 0 and r["o"] > 0), None)
                    if q:
                        ret, how = real_result(q["o"], q["h"], q["l"], q["c"])
                        row.update({"real_strike": k_real, "real_expiry": str(exps[0]), "real_open": q["o"],
                                    "real_ret": round(ret, 4), "real_how": how})
                new.append(row)
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        for row in new:
            f.write(json.dumps(row) + "\n")
    for r in new:
        if r["side"] is None:
            print("%s %-6s %-8s no trade (gap %+.2f%%)" % (r["day"], r["index"], r["version"], r["gap_pct"]))
        else:
            print("%s %-6s %-8s %s  model %s  real %s" % (
                r["day"], r["index"], r["version"], r["side"],
                "%+.0f%% (%s)" % (100 * r["model_ret"], r["model_how"]) if "model_ret" in r else "n/a",
                "%+.0f%% (%s)" % (100 * r["real_ret"], r["real_how"]) if "real_ret" in r else "n/a"))
    print("%d new rows -> %s" % (len(new), LOG))


def stats(v):
    if not v:
        return "  0 trades"
    w = sum(x for x in v if x > 0)
    l = -sum(x for x in v if x <= 0)
    return "%3d tr  win %3.0f%%  avg %+5.1f%%  PF %4.2f" % (
        len(v), 100.0 * sum(x > 0 for x in v) / len(v), 100.0 * sum(v) / len(v), w / l if l else float("inf"))


def cmd_summary(args):
    rows = read_log()
    days = sorted({r["day"] for r in rows})
    if not days:
        print("variants forward test: no days scored yet")
        return
    print("variants forward test %s to %s (%d days), rules fixed 17 Nov 2026; %% of the entry premium per trade" % (
        days[0], days[-1], len(days)))
    for v in VERSIONS:
        for name in INDICES:
            rs = [r for r in rows if r["version"] == v and r["index"] == name]
            print("  %-8s %-6s model %s | real %s" % (v, name, stats([r["model_ret"] for r in rs if "model_ret" in r]),
                                                      stats([r["real_ret"] for r in rs if "real_ret" in r])))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("today")
    s = sub.add_parser("score")
    s.add_argument("--since", default=str(FORWARD_START))
    sub.add_parser("summary")
    a = ap.parse_args(argv)
    return {"today": cmd_today, "score": cmd_score, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
