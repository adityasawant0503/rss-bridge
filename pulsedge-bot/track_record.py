#!/usr/bin/env python3
"""Track how PulsEdge calls did: pulsedge/data/track.json for the "How our calls did" page.

  python pulsedge-bot/track_record.py            # update track.json
  python pulsedge-bot/track_record.py --dry-run  # print the summary instead

Every Watch/Act/Buy/Sell call that names a stock is recorded the first time it is seen in
feed.json (the feed only keeps three days, so this runs on every pipeline run). Prices are
NSE's official end-of-day closes from the daily bhavcopy on nsearchives.nseindia.com.

  entry = close of the last session that had ended when the news came out (15:30 IST)
  1D / 5D = close of the 1st / 5th session after that

A call counts towards the hit rate only when the AI gave the stock a direction (up/down).
Keyword-rule calls have no real direction, so they show the price move but are never scored.
"""
import argparse
import csv
import io
import json
import os
import sys
import urllib.error
import urllib.request
import zipfile
from datetime import date, datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "pulsedge", "data")
STATE = os.path.join(HERE, "state")
CLOSES = os.path.join(STATE, "closes.json")
TRACK = os.path.join(DATA, "track.json")
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

KEEP_SESSIONS = 30     # closes kept per symbol: enough for 5D on calls up to ~5 weeks old
KEEP_DAYS = 120        # calls kept on the page
LOOKBACK_DAYS = 14     # how far back to fill missing bhavcopies
TRACKED_CALLS = {"watch", "act", "buy", "sell"}
CLOSE_TIME = (15, 30)


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def load(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save(path, obj):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(obj, fh, ensure_ascii=False, separators=(",", ":") if path == CLOSES else None,
                  indent=None if path == CLOSES else 1)


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": "https://www.nseindia.com/"})
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.read()


def bhavcopy(d):
    """{symbol: close} for EQ/BE/BZ series on date d, or None if NSE has no file (holiday / not out yet)."""
    rows = None
    try:
        raw = get(f"https://nsearchives.nseindia.com/products/content/sec_bhavdata_full_{d:%d%m%Y}.csv")
        rows = [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(raw.decode("utf-8", "replace")))]
        sym_k, ser_k, cls_k = "SYMBOL", "SERIES", "CLOSE_PRICE"
    except urllib.error.HTTPError as e:
        if e.code not in (403, 404):
            raise
    if rows is None:  # newer UDiFF format
        try:
            raw = get(f"https://nsearchives.nseindia.com/content/cm/BhavCopy_NSE_CM_0_0_0_{d:%Y%m%d}_F_0000.csv.zip")
        except urllib.error.HTTPError as e:
            if e.code in (403, 404):
                return None
            raise
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            text = z.read(z.namelist()[0]).decode("utf-8", "replace")
        rows = [{k.strip(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(io.StringIO(text))]
        sym_k, ser_k, cls_k = "TckrSymb", "SctySrs", "ClsPric"
    out = {}
    for r in rows:
        if r.get(ser_k) in ("EQ", "BE", "BZ"):
            try:
                out[r[sym_k]] = float(r[cls_k])
            except (KeyError, ValueError):
                pass
    return out or None


def refresh_closes(closes, wanted):
    """Fill in missing sessions from the last LOOKBACK_DAYS. closes = {"sessions": {date: {sym: px}}, "holidays": [...]}."""
    sessions, holidays = closes.setdefault("sessions", {}), set(closes.setdefault("holidays", []))
    today = NOW.date()
    published = NOW.hour * 60 + NOW.minute >= 19 * 60  # bhavcopy is usually out by ~18:30 IST
    added = 0
    for back in range(LOOKBACK_DAYS, -1, -1):
        d = today - timedelta(days=back)
        key = d.isoformat()
        if d.weekday() >= 5 or key in sessions or key in holidays:
            continue
        if d == today and not published:
            continue
        try:
            px = bhavcopy(d)
        except Exception as e:
            log(f"  bhavcopy {key}: failed ({type(e).__name__}: {e})")
            continue
        if px is None:
            if d < today:
                holidays.add(key)  # no file for a past weekday: market holiday
            log(f"  bhavcopy {key}: none")
            continue
        sessions[key] = {s: p for s, p in px.items() if s in wanted}
        added += 1
        log(f"  bhavcopy {key}: {len(px)} stocks, kept {len(sessions[key])}")
    for k in sorted(sessions)[:-KEEP_SESSIONS]:
        del sessions[k]
    cutoff = (today - timedelta(days=LOOKBACK_DAYS + 7)).isoformat()
    closes["holidays"] = sorted(h for h in holidays if h >= cutoff)
    return added


def ai_classified(item):
    return not any("Keyword rules" in r for r in item.get("reason") or [])


def add_calls(track, feed):
    have = {(c["id"], c["symbol"]) for c in track["calls"]}
    new = 0
    for it in feed.get("items", []):
        if (it.get("call") or "").lower() not in TRACKED_CALLS or not it.get("tickers") or not it.get("time"):
            continue
        for t in it["tickers"][:2]:
            sym = t["symbol"] if isinstance(t, dict) else str(t)
            if (it["id"], sym) in have:
                continue
            d = (t.get("direction") if isinstance(t, dict) else None) or it.get("direction")
            scored = ai_classified(it) and d in ("up", "down")
            track["calls"].append({
                "id": it["id"], "symbol": sym, "time": it["time"], "call": it["call"].lower(),
                "dir": d if scored else None, "scored": scored, "source": it.get("source", ""),
                "headline": (it.get("headline") or "")[:160], "url": it.get("url", ""),
            })
            have.add((it["id"], sym))
            new += 1
    return new


def entry_session(t, days):
    """Index into sorted session days of the last session that had closed by time t."""
    cut = t.date().isoformat()
    closed_today = (t.hour, t.minute) >= CLOSE_TIME
    idx = None
    for i, d in enumerate(days):
        if d < cut or (d == cut and closed_today):
            idx = i
        else:
            break
    return idx


def score(track, closes):
    sessions = closes.get("sessions", {})
    days = sorted(sessions)
    for c in track["calls"]:
        t = datetime.fromisoformat(c["time"])
        i = entry_session(t, days)
        if i is None:
            continue  # news is older than our price history
        c["entry_date"] = days[i]
        entry = sessions[days[i]].get(c["symbol"])
        if not entry:
            continue
        c["entry"] = entry
        for n, k in ((1, "r1"), (5, "r5")):
            if i + n < len(days):
                px = sessions[days[i + n]].get(c["symbol"])
                if px:
                    c[k] = round((px / entry - 1) * 100, 2)
                    if c["scored"]:
                        c["hit" + str(n)] = (c[k] > 0) == (c["dir"] == "up") and c[k] != 0


def summarise(calls):
    def rate(n):
        done = [c for c in calls if c["scored"] and f"hit{n}" in c]
        hits = sum(c[f"hit{n}"] for c in done)
        signed = [c[f"r{n}"] * (1 if c["dir"] == "up" else -1) for c in done]
        return {"scored": len(done), "hits": hits,
                "hit_rate": round(hits / len(done) * 100) if done else None,
                "avg_return": round(sum(signed) / len(signed), 2) if signed else None}

    moved = [abs(c["r1"]) for c in calls if "r1" in c]
    return {
        "calls": len(calls),
        "scored_calls": sum(c["scored"] for c in calls),
        "d1": rate(1), "d5": rate(5),
        "avg_abs_move_1d": round(sum(moved) / len(moved), 2) if moved else None,
        "since": min((c["time"][:10] for c in calls), default=None),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run

    feed = load(os.path.join(DATA, "feed.json"), {})
    universe = load(os.path.join(DATA, "universe.json"), {})
    track = load(TRACK, {"calls": []})
    closes = load(CLOSES, {})

    new = add_calls(track, feed)
    cutoff = (NOW - timedelta(days=KEEP_DAYS)).isoformat()
    track["calls"] = [c for c in track["calls"] if c["time"] >= cutoff]
    wanted = {s.get("symbol") for s in universe.get("stocks", []) if isinstance(s, dict)} | {c["symbol"] for c in track["calls"]}
    added = refresh_closes(closes, wanted)
    score(track, closes)
    track["calls"].sort(key=lambda c: c["time"], reverse=True)
    out = {
        "updated": NOW.isoformat(timespec="seconds"),
        "summary": summarise(track["calls"]),
        "method": "Entry is the NSE close of the last session that had ended when the news came out; 1D and 5D are the "
                  "closes 1 and 5 sessions later. Only AI calls with an up/down direction count towards the hit rate.",
        "source": "NSE end-of-day bhavcopy",
        "calls": track["calls"],
    }
    log(f"track: {new} new calls, {added} new sessions, {len(closes.get('sessions', {}))} sessions stored")
    log("summary: " + json.dumps(out["summary"]))
    if dry:
        return
    save(CLOSES, closes)
    save(TRACK, out)


if __name__ == "__main__":
    main()
