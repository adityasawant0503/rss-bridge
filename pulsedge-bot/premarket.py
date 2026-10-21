#!/usr/bin/env python3
"""Build pulsedge/data/premarket.json (the terminal's pre-market panel) from free quotes.

  python pulsedge-bot/premarket.py            # write premarket.json
  python pulsedge-bot/premarket.py --dry-run  # print it instead

Quotes come from CNBC's public quote service, with Yahoo Finance's chart endpoint for anything
CNBC misses (both unofficial, personal use; swap for a licensed feed before charging for access). Stocks in focus come from today's feed.json.
Any quote that can't be fetched is left out rather than guessed.
"""
import argparse
import http.cookiejar
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "pulsedge", "data")
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

QUOTES = {
    "nifty": "^NSEI", "banknifty": "^NSEBANK", "vix": "^INDIAVIX",
    "dow": "^DJI", "spx": "^GSPC", "nasdaq": "^IXIC", "nqf": "NQ=F", "esf": "ES=F",
    "nikkei": "^N225", "hangseng": "^HSI", "kospi": "^KS11",
    "dxy": "DX-Y.NYB", "usdinr": "INR=X", "brent": "BZ=F", "wti": "CL=F", "gold": "GC=F", "us10y": "^TNX",
}


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# Same instruments on CNBC; anything missing or unparseable falls back to Yahoo.
CNBC = {
    "nifty": ".NSEI", "banknifty": ".NSEBANK", "vix": ".INVIXN",
    "dow": ".DJI", "spx": ".SPX", "nasdaq": ".IXIC", "nqf": "@ND.1", "esf": "@SP.1",
    "nikkei": ".N225", "hangseng": ".HSI", "kospi": ".KS11",
    "dxy": ".DXY", "usdinr": "INR=", "brent": "@LCO.1", "wti": "@CL.1", "gold": "@GC.1", "us10y": "US10Y",
}


def num(v):
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (TypeError, ValueError):
        return None


def cnbc_quotes():
    url = ("https://quote.cnbc.com/quote-html-webservice/restQuote/symbolType/symbol?symbols="
           + urllib.parse.quote("|".join(CNBC.values())) + "&requestMethod=itv&noform=1&partnerId=2&fund=1&exthrs=1&output=json")
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=20) as r:
        rows = json.load(r)["FormattedQuoteResult"]["FormattedQuote"]
    by_sym = {row.get("symbol"): row for row in rows}
    out = {}
    for k, sym in CNBC.items():
        row = by_sym.get(sym) or {}
        price, prev = num(row.get("last")), num(row.get("previous_day_closing"))
        if price and prev:
            out[k] = {"price": price, "prev": prev, "chg": (price / prev - 1) * 100}
    return out


_SESSION = {}


def session():
    # Yahoo rate-limits cookieless requests (HTTP 429), so pick up its consent cookie and crumb once.
    if "opener" not in _SESSION:
        jar = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        op.addheaders = [("User-Agent", UA), ("Accept", "*/*")]
        try:
            op.open("https://fc.yahoo.com", timeout=8).read()
        except Exception:
            pass  # fc.yahoo.com answers 404 but still sets the cookie
        try:
            _SESSION["crumb"] = op.open("https://query2.finance.yahoo.com/v1/test/getcrumb", timeout=8).read().decode().strip()
        except Exception as e:
            log(f"  crumb: none ({type(e).__name__}: {e})")
            _SESSION["crumb"] = ""
        _SESSION["opener"] = op
    return _SESSION["opener"], _SESSION["crumb"]


def quote(sym):
    op, crumb = session()
    path = "/v8/finance/chart/" + urllib.parse.quote(sym) + "?range=5d&interval=1d" + ("&crumb=" + urllib.parse.quote(crumb) if crumb else "")
    err = None
    for host in ("https://query2.finance.yahoo.com", "https://query1.finance.yahoo.com"):
        try:
            with op.open(host + path, timeout=8) as r:
                res = json.load(r)["chart"]["result"][0]
            break
        except urllib.error.HTTPError as e:
            err = e
            time.sleep(1)
    else:
        raise err
    meta = res["meta"]
    price = meta.get("regularMarketPrice")
    closes = [c for c in (res.get("indicators", {}).get("quote", [{}])[0].get("close") or []) if c is not None]
    prev = meta.get("chartPreviousClose") if len(closes) < 2 else closes[-2]
    if price is None or not prev:
        raise ValueError("no price")
    return {"price": float(price), "prev": float(prev), "chg": (float(price) / float(prev) - 1) * 100}


def fmt(v, d=2):
    return f"{v:,.{d}f}"


def pct(v):
    return f"{v:+.2f}%"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    dry = ap.parse_args().dry_run

    q = {}
    try:
        q = cnbc_quotes()
        log(f"  CNBC: {len(q)}/{len(QUOTES)}")
    except Exception as e:
        log(f"  CNBC: failed ({type(e).__name__}: {e})")
    misses = 0
    for k, sym in QUOTES.items():
        if k in q:
            continue
        if misses >= 3:
            log(f"  {sym}: skipped (Yahoo keeps failing)")
            continue
        try:
            q[k] = quote(sym)
            misses = 0
            time.sleep(0.3)
        except Exception as e:
            misses += 1
            log(f"  {sym}: skipped ({type(e).__name__}: {e})")
    log(f"quotes: {len(q)}/{len(QUOTES)}")
    if len(q) < 5:
        log("too few quotes; leaving premarket.json unchanged")
        return

    checklist, up, down = [], 0, 0

    def add(title, dir_, value, detail):
        nonlocal up, down
        up += dir_ == "up"
        down += dir_ == "down"
        checklist.append({"title": title, "dir": dir_, "value": value, "detail": detail})

    def tone(ch, inverse=False, band=0.25):
        if ch is None or abs(ch) < band:
            return "flat"
        good = ch > 0 if not inverse else ch < 0
        return "up" if good else "down"

    if "nifty" in q:
        n = q["nifty"]
        add("Nifty 50 last close (GIFT Nifty not available from free sources)", tone(n["chg"]),
            f"{fmt(n['price'])} ({pct(n['chg'])})", [f"Previous close {fmt(n['prev'])}"])
    us = [k for k in ("dow", "spx", "nasdaq") if k in q]
    if us:
        higher = sum(q[k]["chg"] > 0 for k in us)
        avg = sum(q[k]["chg"] for k in us) / len(us)
        label = "Higher" if higher == len(us) else "Lower" if higher == 0 else f"Mixed — {higher}/{len(us)} higher"
        names = {"dow": "Dow", "spx": "S&P", "nasdaq": "Nasdaq"}
        det = [f"{names[k]} {fmt(q[k]['price'])} {pct(q[k]['chg'])}" for k in us]
        if "nqf" in q:
            det.append(f"Nasdaq futures now {pct(q['nqf']['chg'])}")
        add("US close - Dow/S&P/Nasdaq direction", tone(avg), label, det)
    asia = [k for k in ("nikkei", "hangseng") if k in q]
    if asia:
        avg = sum(q[k]["chg"] for k in asia) / len(asia)
        names = {"nikkei": "Nikkei", "hangseng": "Hang Seng"}
        mixed = len(asia) == 2 and (q["nikkei"]["chg"] > 0) != (q["hangseng"]["chg"] > 0)
        add("Asian markets live - Nikkei, Hang Seng", "flat" if mixed else tone(avg),
            "Asia mixed" if mixed else ("Asia higher" if avg > 0 else "Asia lower"),
            [f"{names[k]} {fmt(q[k]['price'])} {pct(q[k]['chg'])}" for k in asia])
    if "dxy" in q or "usdinr" in q:
        fx = [q[k]["chg"] for k in ("dxy", "usdinr") if k in q]
        worst = max(fx)
        det = []
        if "dxy" in q:
            det.append(f"DXY {fmt(q['dxy']['price'])} {pct(q['dxy']['chg'])}")
        if "usdinr" in q:
            det.append(f"USD/INR {fmt(q['usdinr']['price'], 3)} {pct(q['usdinr']['chg'])}")
        add("DXY + USDINR move", tone(worst, inverse=True, band=0.3),
            "Rupee under pressure" if worst >= 0.3 else "No major currency pressure", det)
    if "brent" in q:
        b = q["brent"]
        add("Brent crude level", tone(b["chg"], inverse=True, band=1.0), f"${fmt(b['price'])} {pct(b['chg'])}",
            ["Rising crude hurts India (OMCs, paints, aviation); helps upstream"] if b["chg"] > 1 else [])
    if "vix" in q:
        v = q["vix"]
        level = "elevated" if v["price"] >= 18 else "normal" if v["price"] >= 11 else "low"
        add("India VIX", tone(v["chg"], inverse=True, band=5), f"{fmt(v['price'])} ({pct(v['chg'])}) — {level}", [])

    score = up - down
    sentiment = ("Bullish" if score >= 3 else "Mildly bullish" if score >= 1 else
                 "Bearish" if score <= -3 else "Mildly bearish" if score <= -1 else "Neutral")

    cues = []
    if "brent" in q and abs(q["brent"]["chg"]) >= 1:
        cues.append(f"Brent {'up' if q['brent']['chg'] > 0 else 'down'} {abs(q['brent']['chg']):.2f}%"
                    + (" — pressure on OMCs, paints and aviation" if q["brent"]["chg"] > 0 else " — relief for OMCs and paints"))
    if "nasdaq" in q:
        c = q["nasdaq"]["chg"]
        cues.append(f"NASDAQ closed {abs(c):.2f}% {'higher' if c > 0 else 'lower'}" + ("; IT may open soft" if c < -0.3 else "; supportive for IT" if c > 0.3 else ""))
    if asia:
        cues.append(", ".join(f"{ {'nikkei': 'Nikkei', 'hangseng': 'Hang Seng'}[k]} {'up' if q[k]['chg'] > 0 else 'down'}" for k in asia))

    feed = {}
    try:
        with open(os.path.join(DATA, "feed.json"), encoding="utf-8") as fh:
            feed = json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    today = NOW.strftime("%Y-%m-%d")
    picks = sorted((x for x in feed.get("items", []) if x.get("time", "")[:10] == today and x.get("tickers") and x.get("call") != "ignore"),
                   key=lambda x: -(x.get("impact") or 0))[:3]
    focus = [{"symbol": x["tickers"][0]["symbol"], "note": x["headline"][:70]} for x in picks]
    triggers = [f"{len([x for x in feed.get('items', []) if x.get('time', '')[:10] == today and x.get('call') != 'ignore'])} filings and headlines worth a look so far today"] if feed else []
    if "vix" in q and q["vix"]["chg"] >= 3:
        triggers.append(f"India VIX up {q['vix']['chg']:.1f}% — expect wider ranges")

    risks = []
    if "brent" in q and q["brent"]["chg"] > 1:
        risks.append("A further crude spike would hit OMCs and widen the INR move")
    if "nasdaq" in q and q["nasdaq"]["chg"] < -1:
        risks.append("Weak US tech could weigh on Indian IT at the open")
    if "vix" in q and q["vix"]["price"] >= 18:
        risks.append("Elevated VIX — gaps and reversals are more likely")

    also_keys = [("BANK NIFTY", "banknifty", 1), ("S&P FUT", "esf", 0), ("NASDAQ FUT", "nqf", 0), ("KOSPI", "kospi", 0),
                 ("WTI", "wti", 2), ("GOLD", "gold", 0), ("US 10Y", "us10y", 2)]
    out = {
        "date": today,
        "updated": NOW.isoformat(timespec="seconds"),
        "sentiment": sentiment,
        "breadth": {"up": up, "down": down},
        "checklist": checklist,
        "summary": f"{sentiment} setup. " + ("; ".join(cues[:2]) if cues else "No strong moves overnight") + ".",
        "global_cues": cues,
        "india_triggers": triggers,
        "focus": focus,
        "sector_tags": ([{"label": "Upstream oil", "tone": "positive"}, {"label": "OMCs", "tone": "negative"}] if "brent" in q and q["brent"]["chg"] > 1 else [])
                       + ([{"label": "IT", "tone": "watch"}] if "nasdaq" in q and abs(q["nasdaq"]["chg"]) > 0.3 else []),
        "key_risk": risks[0] if risks else "",
        "also": [{"name": n, "value": fmt(q[k]["price"], d), "change": round(q[k]["chg"], 2)} for n, k, d in also_keys if k in q],
        "source": "CNBC / Yahoo Finance (unofficial, delayed)",
    }
    if dry:
        print(json.dumps(out, indent=1, ensure_ascii=False))
        return
    with open(os.path.join(DATA, "premarket.json"), "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)
    log(f"wrote premarket.json: {sentiment}, {len(checklist)} checklist items")


if __name__ == "__main__":
    main()
