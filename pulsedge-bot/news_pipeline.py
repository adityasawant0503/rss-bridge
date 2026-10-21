#!/usr/bin/env python3
"""PulsEdge news pipeline: collect -> de-duplicate -> classify -> write pulsedge/data/feed.json.

Runs on a schedule in GitHub Actions (.github/workflows/pulsedge-news.yml).

  python pulsedge-bot/news_pipeline.py              # normal run
  python pulsedge-bot/news_pipeline.py --dry-run    # fetch + classify, print, write nothing

Classification uses Claude when ANTHROPIC_API_KEY is set (model from PULSEDGE_MODEL,
default claude-opus-5-5). Without a key it falls back to simple keyword rules so the
feed still updates.
"""
import argparse
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "pulsedge", "data")
STATE = os.path.join(HERE, "state", "seen.json")
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
MAX_AGE = timedelta(hours=36)        # ignore older headlines
KEEP_DAYS = 3                        # how long items stay in feed.json
BATCH = 25                           # headlines per Claude request
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


# ---------------------------------------------------------------- fetching
def get(url, accept="*/*", referer=None):
    headers = {"User-Agent": UA, "Accept": accept, "Accept-Language": "en-IN,en;q=0.9"}
    if referer:
        headers["Referer"] = referer
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=25) as r:
        return r.read()


def clean(text):
    text = re.sub(r"<[^>]+>", " ", html.unescape(text or ""))
    return re.sub(r"\s+", " ", text).strip()


def parse_time(s):
    if not s:
        return None
    s = s.strip()
    for fn in (parsedate_to_datetime, lambda v: datetime.fromisoformat(v.replace("Z", "+00:00"))):
        try:
            t = fn(s)
            return (t if t.tzinfo else t.replace(tzinfo=IST)).astimezone(IST)
        except Exception:
            pass
    for fmt in ("%d-%b-%Y %H:%M:%S", "%d-%m-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=IST)
        except ValueError:
            pass
    return None


def fetch_rss(src):
    root = ET.fromstring(get(src["url"], "application/rss+xml, application/xml, text/xml"))
    out = []
    for it in root.iter():
        tag = it.tag.split("}")[-1]
        if tag not in ("item", "entry"):
            continue
        f = {c.tag.split("}")[-1]: c for c in it}

        def txt(*names):
            for n in names:
                if n in f and (f[n].text or "").strip():
                    return f[n].text
            return ""
        title = clean(txt("title"))
        link = (txt("link") or (f["link"].get("href") if "link" in f else "") or "").strip()
        when = parse_time(txt("pubDate", "published", "updated", "date"))
        desc = clean(txt("description", "summary"))
        if title:
            out.append({"headline": title, "url": link, "time": when, "summary": desc[:400]})
    return out


def fetch_bse(src):
    url = src["url"].replace("{date}", NOW.strftime("%Y%m%d"))
    data = json.loads(get(url, "application/json", referer="https://www.bseindia.com/"))
    out = []
    for row in data.get("Table", []) or []:
        title = clean(row.get("HEADLINE") or row.get("NEWSSUB") or "")
        company = clean(row.get("SLONGNAME") or "")
        if not title:
            continue
        att = row.get("ATTACHMENTNAME")
        out.append({
            "headline": title if company.lower() in title.lower() else f"{company}: {title}" if company else title,
            "url": f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att}" if att else "",
            "time": parse_time(row.get("NEWS_DT") or row.get("DissemDT")),
            "summary": clean(row.get("CATEGORYNAME") or ""),
        })
    return out


def collect(sources):
    items = []
    for src in sources:
        if src.get("enabled") is False:
            continue
        try:
            got = (fetch_bse if src["kind"] == "bse" else fetch_rss)(src)
            for g in got:
                g["source"], g["section_hint"] = src["name"], src.get("section", "news")
            items += got
            log(f"  {src['name']}: {len(got)} items")
        except Exception as e:                       # one bad source never stops the run
            log(f"  {src['name']}: skipped ({type(e).__name__}: {e})")
    return items


# ---------------------------------------------------------------- de-dup
def key_of(headline):
    norm = re.sub(r"[^a-z0-9 ]", "", headline.lower())
    norm = " ".join(w for w in norm.split() if len(w) > 2)[:140]
    return hashlib.sha1(norm.encode()).hexdigest()[:16]


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------- universe / tickers
NIFTY500_CSV = "https://www.niftyindices.com/IndexConstituent/ind_nifty500list.csv"


def refresh_universe(dry):
    """Download the official Nifty 500 list weekly into data/universe.json."""
    path = os.path.join(DATA, "universe.json")
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < 6 * 86400:
        return
    try:
        import csv, io
        rows = list(csv.DictReader(io.StringIO(get(NIFTY500_CSV, "text/csv").decode("utf-8-sig"))))
        stocks = [{"symbol": r["Symbol"].strip().upper(), "name": r["Company Name"].strip(), "sector": r["Industry"].strip()}
                  for r in rows if r.get("Symbol")]
        if len(stocks) < 400:
            raise ValueError(f"only {len(stocks)} rows")
        log(f"  Nifty 500 list: {len(stocks)} stocks")
        if not dry:
            with open(path, "w", encoding="utf-8") as fh:
                json.dump({"name": "NIFTY 500", "updated": NOW.strftime("%Y-%m-%d"), "stocks": stocks}, fh, ensure_ascii=False, indent=1)
    except Exception as e:
        log(f"  Nifty 500 list: not refreshed ({type(e).__name__}: {e})")


def load_universe():
    for name in ("universe.json", "universe.sample.json"):
        u = load_json(os.path.join(DATA, name), None)
        if u:
            return u.get("stocks", [])
    return []


def match_tickers(text, universe):
    """Cheap name match used by the rule fallback and to cross-check Claude."""
    t = " " + re.sub(r"[^a-z0-9& ]", " ", text.lower()) + " "
    hits = []
    for s in universe:
        name = re.sub(r"\b(limited|ltd|india|industries|corporation|company|co)\b", "", s["name"].lower())
        name = re.sub(r"[^a-z0-9& ]", " ", name).strip()
        sym = s["symbol"].lower()
        if (len(name) > 3 and f" {name} " in t) or (len(sym) > 2 and f" {sym} " in t):
            hits.append(s["symbol"])
    return hits[:6]


# ---------------------------------------------------------------- classification
SCHEMA = {
    "type": "object",
    "properties": {"items": {"type": "array", "items": {
        "type": "object",
        "properties": {
            "i": {"type": "integer"},
            "section": {"type": "string", "enum": ["trading", "news", "macro"]},
            "call": {"type": "string", "enum": ["buy", "sell", "watch", "ignore"]},
            "horizon": {"type": "string", "enum": ["intraday", "swing", "positional"]},
            "direction": {"type": "string", "enum": ["up", "down", "mixed"]},
            "tickers": {"type": "array", "items": {
                "type": "object",
                "properties": {"symbol": {"type": "string"}, "direction": {"type": "string", "enum": ["up", "down"]}},
                "required": ["symbol", "direction"], "additionalProperties": False}},
            "sectors": {"type": "array", "items": {"type": "string"}},
            "impact": {"type": "integer"},
            "confidence": {"type": "integer"},
            "category": {"type": "string"},
            "action": {"type": "string"},
            "reason": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["i", "section", "call", "horizon", "direction", "tickers", "sectors", "impact",
                     "confidence", "category", "action", "reason", "risks"],
        "additionalProperties": False}}},
    "required": ["items"], "additionalProperties": False,
}

GUIDE = """You triage Indian stock market news for PulsEdge, an educational news-impact tool.
For each numbered headline, decide how it affects listed Indian stocks (NSE symbols from the list below).

- call: "ignore" for routine filings (Reg 74(5), trading window, investor meet intimations, duplicate wire copy), market colour with no new information, or anything with no clear listed-stock impact. "watch" when it could matter but needs confirmation. "buy"/"sell" only for clearly material, company- or sector-specific news with a direct price impact.
- tickers: only symbols from the list; direction per stock. Empty for broad-market items.
- impact and confidence: 0-100. impact is how much the news could move the named stocks; confidence is how sure you are of the direction.
- action: one short, conditional, educational line (e.g. "Watch for follow-through above the first 15-min high"). Never promise returns.
- reason: 1-2 short bullets. risks: 0-2 short bullets.
- horizon: intraday, swing (days-weeks) or positional (months).
Answer for every index i you were given.

NSE universe (SYMBOL|Company|Sector):
"""


def classify_claude(batch, universe):
    import anthropic                                   # installed in the workflow
    client = anthropic.Anthropic()
    model = os.environ.get("PULSEDGE_MODEL") or "claude-opus-5-5"
    uni = "\n".join(f"{s['symbol']}|{s['name']}|{s.get('sector', '')}" for s in universe)
    lines = "\n".join(f"{n}. [{b['source']}] {b['headline']}" + (f" — {b['summary'][:200]}" if b["summary"] else "") for n, b in enumerate(batch))
    kwargs = dict(
        model=model,
        max_tokens=16000,
        # stable universe first and cached; the headlines change every run
        system=[{"type": "text", "text": GUIDE + uni, "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": "Headlines:\n" + lines}],
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if model.startswith(("claude-opus-5", "claude-sonnet-5-5", "claude-fable-5")):
        # route a safety refusal to a fallback model automatically
        resp = client.beta.messages.create(betas=["server-side-fallback-2026-07-01"], extra_body={"fallbacks": "default"}, **kwargs)
    else:
        resp = client.messages.create(**kwargs)
    if resp.stop_reason in ("refusal", "max_tokens"):
        raise RuntimeError(f"Claude stopped: {resp.stop_reason}")
    text = next(b.text for b in resp.content if b.type == "text")
    u = resp.usage
    log(f"  claude {model}: in={u.input_tokens} cached={getattr(u, 'cache_read_input_tokens', 0)} out={u.output_tokens}")
    return {r["i"]: r for r in json.loads(text)["items"]}


ROUTINE = re.compile(r"74\s*\(5\)|trading window|closure of trading|investor meet|analyst meet|appeal no|"
                     r"recovery certificate|notice of demand|prohibitory order|attachment order|settlement order|"
                     r"adjudication order|summons|in the matter of|"
                     r"loss of share|duplicate share|newspaper (publication|advertisement)|compliance certificate|"
                     r"intimation of (board meeting|record date)|copy of newspaper", re.I)
SIGNAL = re.compile(r"order|contract|acquisition|merger|results?|profit|guidance|usfda|warning letter|"
                    r"downgrade|upgrade|pledge|resign|fraud|penalty|block deal|bulk deal|stake", re.I)


def classify_rules(batch, universe):
    out = {}
    for n, b in enumerate(batch):
        text = b["headline"] + " " + b["summary"]
        tk = [{"symbol": s, "direction": "up"} for s in match_tickers(text, universe)]
        routine = bool(ROUTINE.search(text))
        signal = bool(SIGNAL.search(text))
        # without AI, only stock-specific news or clear signals are worth a look
        noteworthy = not routine and (tk or signal)
        out[n] = {
            "i": n, "section": b["section_hint"], "call": "watch" if noteworthy else "ignore",
            "horizon": "swing", "direction": "mixed", "tickers": tk, "sectors": [],
            "impact": 45 if noteworthy and signal else 25 if noteworthy else 8, "confidence": 30,
            "category": "Routine filing" if routine else b["section_hint"].title() if noteworthy else "No listed-stock impact",
            "action": "Read the source before acting" if noteworthy else "No action",
            "reason": ["Keyword rules (AI classification is off)"], "risks": [],
        }
    return out


# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    sources = load_json(os.environ.get("PULSEDGE_SOURCES") or os.path.join(HERE, "sources.json"), {}).get("sources", [])
    refresh_universe(a.dry_run)
    universe = load_universe()
    seen = load_json(STATE, {})
    log(f"Collecting from {len(sources)} sources at {NOW:%Y-%m-%d %H:%M} IST")
    raw = collect(sources)

    fresh, batch_keys = [], set()
    for it in raw:
        k = key_of(it["headline"])
        t = it["time"] or NOW
        if k in seen or k in batch_keys or NOW - t > MAX_AGE:
            continue
        batch_keys.add(k)
        it["key"], it["time"] = k, t
        fresh.append(it)
    fresh.sort(key=lambda x: x["time"], reverse=True)
    fresh = fresh[:150]                                   # cap per run to bound cost
    log(f"{len(raw)} collected, {len(fresh)} new")

    use_ai = bool(os.environ.get("ANTHROPIC_API_KEY"))
    classified = []
    for start in range(0, len(fresh), BATCH):
        chunk = fresh[start:start + BATCH]
        try:
            res = classify_claude(chunk, universe) if use_ai else classify_rules(chunk, universe)
        except Exception as e:
            log(f"  AI classification failed ({type(e).__name__}: {e}); using keyword rules for this batch")
            res = classify_rules(chunk, universe)
        known = {s["symbol"] for s in universe}
        for n, it in enumerate(chunk):
            r = res.get(n) or classify_rules([it], universe)[0]
            tickers = [t for t in r["tickers"] if t["symbol"].upper() in known]
            classified.append({
                "id": it["key"], "time": it["time"].isoformat(timespec="seconds"), "headline": it["headline"],
                "source": it["source"], "url": it["url"] if it["url"].startswith("http") else "",
                "section": r["section"], "call": r["call"], "horizon": r["horizon"], "direction": r["direction"],
                "tickers": tickers, "sectors": r["sectors"][:4],
                "impact": max(0, min(100, int(r["impact"]))), "confidence": max(0, min(100, int(r["confidence"]))),
                "category": r["category"], "action": r["action"], "reason": r["reason"][:3], "risks": r["risks"][:3],
                "original": it["summary"][:300] or it["headline"],
            })
        if use_ai:
            time.sleep(1)

    if a.dry_run:
        for c in classified[:20]:
            log(f"  {c['call'].upper():6} {c['impact']:3} {','.join(t['symbol'] for t in c['tickers']) or '-':20} {c['headline'][:90]}")
        log(f"dry run: {len(classified)} items classified, nothing written")
        return

    # merge into feed.json (newest first, last KEEP_DAYS days, at most 300)
    feed_path = os.path.join(DATA, "feed.json")
    feed = load_json(feed_path, {"items": []})
    cutoff = NOW - timedelta(days=KEEP_DAYS)
    old = [x for x in feed.get("items", []) if not x.get("sample") and parse_time(x.get("time", "")) and parse_time(x["time"]) > cutoff]
    items = sorted(classified + old, key=lambda x: x["time"], reverse=True)[:300]
    today = [x for x in items if x["time"][:10] == NOW.strftime("%Y-%m-%d")]
    calls = {c: sum(1 for x in today if x["call"] == c) for c in ("buy", "sell", "watch", "ignore")}
    reasons = {}
    for x in today:
        if x["call"] == "ignore":
            reasons[x["category"] or "Other"] = reasons.get(x["category"] or "Other", 0) + 1
    out = {
        "updated": NOW.isoformat(timespec="seconds"),
        "items": items,
        "digest": {"date": NOW.strftime("%Y-%m-%d"), "act": calls["buy"] + calls["sell"], "watch": calls["watch"],
                   "ignored": calls["ignore"],
                   "reasons": [{"label": k, "count": v} for k, v in sorted(reasons.items(), key=lambda kv: -kv[1])[:6]]},
    }
    if classified or not os.path.exists(feed_path):
        with open(feed_path, "w", encoding="utf-8") as fh:
            json.dump(out, fh, ensure_ascii=False, indent=1)

    for c in classified:
        seen[c["id"]] = NOW.isoformat(timespec="seconds")
    week = (NOW - timedelta(days=7)).isoformat()
    seen = {k: v for k, v in seen.items() if v > week}
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    with open(STATE, "w", encoding="utf-8") as fh:
        json.dump(seen, fh)
    log(f"wrote {len(classified)} new items; feed has {len(items)}")


if __name__ == "__main__":
    main()
