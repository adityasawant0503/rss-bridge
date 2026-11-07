#!/usr/bin/env python3
"""PulsEdge institutional flows: where the big money moved today.

Builds pulsedge/data/flows.json from NSE's end-of-day public data:
  - bulk and block deals (who bought or sold large blocks of which stock),
  - FII/FPI and DII net buying in the cash market (provisional),
  - FII positioning in index futures (participant-wise open interest),
  - Nifty and sector index closes, for 1-day and 5-day sector moves and a
    this-week summary of the Nifty against FII positioning.

Large deals by foreign funds and domestic institutions are also added to
pulsedge/data/feed.json as Watch items, so they show up under My stocks for
anyone holding that stock. These are facts about trades that already
happened, not predictions, and are never scored in the track record.

  python pulsedge-bot/flows.py [--dry-run]

Any source that fails is skipped; the rest are still written.
"""
import argparse
import csv
import hashlib
import http.cookiejar
import io
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "pulsedge", "data")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36"
ARCHIVES = ("https://nsearchives.nseindia.com", "https://archives.nseindia.com")
DEAL_SOURCE = "NSE bulk & block deals"
DEAL_URL = "https://www.nseindia.com/report-detail/display-bulk-and-block-deals"
MIN_INSTITUTION_CR = 5      # feed items for institutional deals at or above this size (₹ crore)
MIN_OTHER_CR = 50           # and for anyone else's deals in Nifty 500 stocks
MAX_FEED_DEALS = 20

# NSE index name (lower case) -> label used for sector chips in the terminal
INDICES = {"nifty 50": "Nifty 50", "nifty midcap 100": "Midcap 100", "nifty smallcap 100": "Smallcap 100",
           "nifty bank": "Banks", "nifty it": "IT", "nifty pharma": "Pharma", "nifty auto": "Auto", "nifty fmcg": "FMCG",
           "nifty metal": "Metals", "nifty realty": "Realty", "nifty energy": "Energy", "nifty oil & gas": "Oil & Gas",
           "nifty psu bank": "PSU Banks", "nifty financial services": "Financials", "nifty media": "Media",
           "nifty healthcare index": "Healthcare", "nifty consumer durables": "Consumer durables"}
BROAD = ("Nifty 50", "Midcap 100", "Smallcap 100")

# Trading firms whose bulk deals are same-day churn, not investment decisions
PROP = ("GRAVITON", "JUNOMONETA", "QE SECURITIES", "IRAGE", "ALPHAGREP", "HRTI", "NK SECURITIES", "SILVERLEAF",
        "MICROCURVES", "PACE STOCK", "TOWER RESEARCH", "JUMP TRADING", "CITADEL SECURITIES", "ELIXIR WEALTH",
        "SHARE INDIA", "BEELINE", "MANSI SHARE", "PURE BROKING", "DOLAT", "XTX", "TOPGAIN", "SPARKLE")
FOREIGN = ("FPI", "ODI", "PTE", "SINGAPORE", "MAURITIUS", "CAYMAN", "LUXEMBOURG", "FOREIGN", "GOLDMAN SACHS",
           "MORGAN STANLEY", "CITIGROUP", "BNP PARIBAS", "SOCIETE GENERALE", "JPMORGAN", "J.P. MORGAN", "NOMURA",
           "UBS ", "HSBC", "BARCLAYS", "VANGUARD", "BLACKROCK", "ISHARES", "NORGES", "ABU DHABI", "GOVERNMENT OF",
           "FIDELITY", "MERRILL LYNCH", "CLSA", "MACQUARIE", "COPTHALL", "SMALLCAP WORLD", "EMERGING MARKETS",
           "PLC", "INTEGRATED CORE", "GQG", "BOFA SECURITIES", "SEGANTII", "TT INTERNATIONAL")
DOMESTIC = ("MUTUAL FUND", " MF ", "LIFE INSURANCE", "GENERAL INSURANCE", "INSURANCE CO", "PENSION FUND",
            "ASSET MANAGEMENT", "PROVIDENT FUND", "ALTERNATIVE INVESTMENT", " AIF")


def log(msg):
    print(msg, file=sys.stderr)


def load_json(path, default):
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return default


def get(url, opener=None, referer="https://www.nseindia.com/"):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*", "Referer": referer,
                                               "Accept-Language": "en-US,en;q=0.9"})
    with (opener.open if opener else urllib.request.urlopen)(req, timeout=20) as r:
        return r.read()


def get_archive(path):
    last = None
    for host in ARCHIVES:
        try:
            return get(host + path)
        except Exception as e:  # noqa: BLE001 - try the next host
            last = e
    raise last


def num(s):
    try:
        return float(str(s).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def parse_date(s):
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%d %b %Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(str(s).strip(), fmt).date()
        except ValueError:
            pass
    return None


def _words(keys):
    return re.compile(r"\b(?:" + "|".join(re.escape(k.strip()) for k in keys) + r")(?![A-Z0-9])")


PROP_RE, FOREIGN_RE, DOMESTIC_RE = _words(PROP), _words(FOREIGN), _words(DOMESTIC)


def who(client):
    c = re.sub(r"\s+", " ", client.upper())
    if PROP_RE.search(c):
        return "prop"
    if FOREIGN_RE.search(c):
        return "foreign"
    if DOMESTIC_RE.search(c):
        return "domestic"
    return "other"


def col(header, *names):
    for i, h in enumerate(header):
        hl = h.lower()
        if any(n in hl for n in names):
            return i
    return None


# ---------- bulk and block deals ----------

def deals():
    out = []
    for kind in ("bulk", "block"):
        try:
            text = get_archive(f"/content/equities/{kind}.csv").decode("utf-8", "replace")
        except Exception as e:  # noqa: BLE001
            log(f"{kind} deals: unavailable ({type(e).__name__}: {e})")
            continue
        rows = [r for r in csv.reader(io.StringIO(text)) if any(x.strip() for x in r)]
        if len(rows) < 2:
            log(f"{kind} deals: none today")
            continue
        h = rows[0]
        i_date, i_sym, i_name = col(h, "date"), col(h, "symbol"), col(h, "security name")
        i_client, i_side, i_qty, i_px = col(h, "client"), col(h, "buy"), col(h, "quantity"), col(h, "price")
        if None in (i_date, i_sym, i_client, i_side, i_qty, i_px):
            log(f"{kind} deals: unexpected columns {h}")
            continue
        n = 0
        for r in rows[1:]:
            if len(r) <= max(i_date, i_sym, i_client, i_side, i_qty, i_px):
                continue
            side = "buy" if r[i_side].strip().upper().startswith("B") else "sell"
            qty, px = num(r[i_qty]), num(r[i_px])
            d = parse_date(r[i_date])
            if not d or qty <= 0 or px <= 0:
                continue
            out.append({"date": d.isoformat(), "symbol": r[i_sym].strip().upper(),
                        "name": (r[i_name].strip() if i_name is not None else "") or r[i_sym].strip(),
                        "client": re.sub(r"\s+", " ", r[i_client]).strip(), "side": side,
                        "qty": qty, "value": qty * px, "kind": kind})
            n += 1
        log(f"{kind} deals: {n} rows")
    # NSE can list one block-window trade in both files: keep the block copy
    blocks = {(x["date"], x["symbol"], x["client"].upper(), x["side"], x["qty"]) for x in out if x["kind"] == "block"}
    out = [x for x in out if x["kind"] == "block" or (x["date"], x["symbol"], x["client"].upper(), x["side"], x["qty"]) not in blocks]
    # one line per client, stock, side and day; drop same-day round trips
    agg = {}
    for x in out:
        k = (x["date"], x["symbol"], x["client"].upper(), x["kind"])
        a = agg.setdefault(k, {**x, "buy_qty": 0.0, "buy_val": 0.0, "sell_qty": 0.0, "sell_val": 0.0})
        a[x["side"] + "_qty"] += x["qty"]
        a[x["side"] + "_val"] += x["value"]
    universe = {s["symbol"] for s in load_json(os.path.join(DATA, "universe.json"), {}).get("stocks", [])}
    res = []
    for a in agg.values():
        gross = a["buy_val"] + a["sell_val"]
        net = a["buy_val"] - a["sell_val"]
        if gross <= 0 or abs(net) < 0.2 * gross:
            continue
        side = "buy" if net > 0 else "sell"
        qty = a["buy_qty"] - a["sell_qty"] if side == "buy" else a["sell_qty"] - a["buy_qty"]
        res.append({"date": a["date"], "symbol": a["symbol"], "name": a["name"], "client": a["client"],
                    "who": who(a["client"]), "side": side, "qty": round(qty), "price": round(abs(net) / qty, 2) if qty else None,
                    "value_cr": round(abs(net) / 1e7, 2), "kind": a["kind"], "nifty500": a["symbol"] in universe})
    res.sort(key=lambda x: -x["value_cr"])
    return res


# ---------- FII / DII cash market (provisional) ----------

def cash():
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    try:
        get("https://www.nseindia.com/", opener)
        data = json.loads(get("https://www.nseindia.com/api/fiidiiTradeReact", opener,
                              referer="https://www.nseindia.com/reports/fii-dii"))
    except Exception as e:  # noqa: BLE001
        log(f"FII/DII cash: unavailable ({type(e).__name__}: {e})")
        return None
    res = {}
    for row in data if isinstance(data, list) else []:
        cat = str(row.get("category", "")).upper()
        key = "fii" if "FII" in cat or "FPI" in cat else "dii" if "DII" in cat else None
        if not key:
            continue
        d = parse_date(row.get("date"))
        res["date"] = d.isoformat() if d else res.get("date")
        res[key] = {"buy": round(num(row.get("buyValue")), 2), "sell": round(num(row.get("sellValue")), 2),
                    "net": round(num(row.get("netValue")), 2)}
    if "fii" not in res or "dii" not in res:
        log(f"FII/DII cash: unexpected reply {str(data)[:200]}")
        return None
    log(f"FII/DII cash {res['date']}: FII net ₹{res['fii']['net']:,.0f} cr, DII net ₹{res['dii']['net']:,.0f} cr")
    return res


# ---------- FII positioning in index futures ----------

def participant_oi(day):
    text = get_archive(f"/content/nsccl/fao_participant_oi_{day:%d%m%Y}.csv").decode("utf-8", "replace")
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    hi = next(i for i, r in enumerate(rows) if r and "client type" in r[0].lower())
    h = [x.strip().lower() for x in rows[hi]]
    il, ish = h.index("future index long"), h.index("future index short")
    out = {}
    for r in rows[hi + 1:]:
        t = r[0].strip().upper()
        if t in ("FII", "DII", "PRO", "CLIENT"):
            lo, sh = num(r[il]), num(r[ish])
            out[t.lower()] = {"long": int(lo), "short": int(sh), "long_pct": round(100 * lo / (lo + sh), 1) if lo + sh else None}
    return out


def fno():
    found = []
    d = NOW.date()
    for _ in range(10):
        if d.weekday() < 5:
            try:
                found.append((d, participant_oi(d)))
            except Exception:  # noqa: BLE001 - not published yet, or a holiday
                pass
            if len(found) == 2:
                break
        d -= timedelta(days=1)
    if not found or "fii" not in found[0][1]:
        log("FII index futures: unavailable")
        return None
    day, oi = found[0]
    prev = found[1][1].get("fii", {}).get("long_pct") if len(found) > 1 else None
    res = {"date": day.isoformat(), "fii_long": oi["fii"]["long"], "fii_short": oi["fii"]["short"],
           "fii_long_pct": oi["fii"]["long_pct"], "prev_long_pct": prev,
           "prev_date": found[1][0].isoformat() if len(found) > 1 else None}
    log(f"FII index futures {res['date']}: {res['fii_long_pct']}% long (previous {prev})")
    return res


# ---------- Nifty and sector indices ----------

def index_day(day):
    text = get_archive(f"/content/indices/ind_close_all_{day:%d%m%Y}.csv").decode("utf-8", "replace")
    rows = [r for r in csv.reader(io.StringIO(text)) if r]
    h = rows[0]
    i_name, i_close, i_chg = col(h, "index name"), col(h, "closing index"), col(h, "change(%)")
    out = {}
    for r in rows[1:]:
        label = INDICES.get(r[i_name].strip().lower())
        if label:
            out[label] = [num(r[i_close]), round(num(r[i_chg]), 2)]
    if not out:
        raise ValueError("no known indices")
    return out


def indices(prev_hist):
    hist = dict(prev_hist or {})
    d, tried = NOW.date(), 0
    while tried < 8 and d.isoformat() not in hist:   # fetch only sessions not stored yet
        if d.weekday() < 5:
            tried += 1
            try:
                hist[d.isoformat()] = index_day(d)
            except Exception:  # noqa: BLE001 - not published yet, or a holiday
                pass
        d -= timedelta(days=1)
    days = sorted(hist)[-12:]
    hist = {k: hist[k] for k in days}
    if not days:
        log("indices: unavailable")
        return hist, [], None
    last = hist[days[-1]]
    base = hist[days[-6]] if len(days) >= 6 else None
    rows = []
    for label, (close, d1) in last.items():
        d5 = round(100 * (close / base[label][0] - 1), 2) if base and base.get(label, [0])[0] else None
        rows.append({"label": label, "close": close, "d1": d1, "d5": d5, "broad": label in BROAD})
    rows.sort(key=lambda x: -x["d1"])
    log(f"indices {days[-1]}: {len(rows)} ({', '.join(f'{x['label']} {x['d1']:+.2f}%' for x in rows[:3])} ...)")
    return hist, rows, days[-1]


def week_summary(sectors, fno_hist, cash_hist):
    nifty = next((x for x in sectors if x["label"] == "Nifty 50"), None)
    days = sorted(fno_hist)
    out = {}
    if nifty and nifty["d5"] is not None:
        out["nifty_5d"] = nifty["d5"]
    if days:
        out["fii_long_now"] = fno_hist[days[-1]]
        if len(days) >= 6:
            out["fii_long_5d_ago"] = fno_hist[days[-6]]
    if len(cash_hist) >= 2:
        out["fii_cash_5d"] = round(sum(h["fii"] for h in cash_hist[-5:]), 2)
        out["dii_cash_5d"] = round(sum(h["dii"] for h in cash_hist[-5:]), 2)
    return out or None


# ---------- feed items ----------

def lakh(q):
    return f"{q / 1e5:,.1f} lakh" if q >= 1e5 else f"{q:,.0f}"


def deal_items(rows):
    picks = [x for x in rows if (x["who"] in ("foreign", "domestic") and x["value_cr"] >= MIN_INSTITUTION_CR)
             or (x["who"] == "other" and x["nifty500"] and x["value_cr"] >= MIN_OTHER_CR)][:MAX_FEED_DEALS]
    items = []
    for x in picks:
        label = {"foreign": "Foreign fund", "domestic": "Domestic institution"}.get(x["who"], "Large investor")
        verb = "bought" if x["side"] == "buy" else "sold"
        name = x["name"].title() if x["name"].isupper() else x["name"]
        v = x["value_cr"]
        uid = hashlib.sha1(f"deal|{x['date']}|{x['symbol']}|{x['client'].upper()}|{x['kind']}".encode()).hexdigest()[:16]
        items.append({
            "id": uid, "kind": "deal", "time": f"{x['date']}T16:00:00+05:30",
            "headline": f"{x['kind'].title()} deal: {x['client'][:60]} {verb} {lakh(x['qty'])} shares of {name} at ₹{x['price']:,} (₹{v:,.1f} cr)",
            "source": DEAL_SOURCE, "url": DEAL_URL, "section": "trading", "call": "watch", "horizon": "positional",
            "direction": "up" if x["side"] == "buy" else "down", "tickers": [{"symbol": x["symbol"], "direction": "up" if x["side"] == "buy" else "down"}],
            "sectors": [], "impact": 75 if v >= 200 else 65 if v >= 50 else 55 if v >= 20 else 45, "confidence": 55,
            "category": "Institutional deal",
            "action": "See why before acting: check recent results and news. One deal isn't a trend.",
            "reason": [f"{label} {verb} ₹{v:,.1f} cr of {x['symbol']} in one {x['kind']} deal",
                       "Big trades by institutions can show conviction, but can also be rebalancing or an exit",
                       "From NSE's end-of-day bulk and block deal disclosures"],
            "risks": ["The other side of the trade may also be an institution"],
            "original": f"{x['client']} {verb} {x['qty']:,} shares of {x['symbol']} ({x['kind']} deal, {x['date']})",
        })
    return items


def merge_feed(items, dry):
    path = os.path.join(DATA, "feed.json")
    feed = load_json(path, None)
    if not feed or not isinstance(feed.get("items"), list):
        log("feed.json missing; deal items not added")
        return 0
    have = {x.get("id") for x in feed["items"]}
    new = [x for x in items if x["id"] not in have]
    if new and not dry:
        feed["items"] = sorted(feed["items"] + new, key=lambda x: x.get("time", ""), reverse=True)   # news_pipeline.py trims
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(feed, fh, ensure_ascii=False, indent=1)
    return len(new)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    path = os.path.join(DATA, "flows.json")
    prev = load_json(path, {})
    rows = deals()
    c = cash()
    f = fno()
    idx_hist, sectors, idx_date = indices(prev.get("index_history"))
    fno_hist = dict(prev.get("fno_history") or {})
    if f:
        fno_hist[f["date"]] = f["fii_long_pct"]
        if f.get("prev_date") and f.get("prev_long_pct") is not None:
            fno_hist.setdefault(f["prev_date"], f["prev_long_pct"])
    fno_hist = {k: fno_hist[k] for k in sorted(fno_hist)[-20:]}

    hist = {h["date"]: h for h in prev.get("cash_history", []) if h.get("date")}
    if c:
        hist[c["date"]] = {"date": c["date"], "fii": c["fii"]["net"], "dii": c["dii"]["net"]}
    hist = sorted(hist.values(), key=lambda h: h["date"])[-30:]

    by = {}
    for x in rows:
        if x["who"] not in ("foreign", "domestic"):
            continue
        s = by.setdefault(x["symbol"], {"symbol": x["symbol"], "name": x["name"], "foreign_cr": 0.0, "domestic_cr": 0.0})
        s[x["who"] + "_cr"] = round(s[x["who"] + "_cr"] + (x["value_cr"] if x["side"] == "buy" else -x["value_cr"]), 2)
    by_stock = sorted(by.values(), key=lambda s: -abs(s["foreign_cr"] + s["domestic_cr"]))[:15]

    out = {
        "updated": NOW.isoformat(timespec="seconds"),
        "source": "NSE (bulk and block deals, provisional FII/DII cash, participant-wise open interest)",
        "cash": c or prev.get("cash"),
        "cash_history": hist,
        "fno": f or prev.get("fno"),
        "deals_date": rows[0]["date"] if rows else prev.get("deals_date"),
        "deals": [x for x in rows if x["who"] != "prop"][:40] if rows else prev.get("deals", []),
        "by_stock": by_stock if rows else prev.get("by_stock", []),
        "sectors_date": idx_date or prev.get("sectors_date"),
        "sectors": sectors or prev.get("sectors", []),
        "index_history": idx_hist,
        "fno_history": fno_hist,
        "week": week_summary(sectors or prev.get("sectors", []), fno_hist, hist),
    }
    added = merge_feed(deal_items(rows), a.dry_run)
    inst = [x for x in rows if x["who"] in ("foreign", "domestic")]
    log(f"{len(rows)} deals after netting, {len(inst)} by institutions; {added} new feed items")
    for x in inst[:8]:
        log(f"  {x['who']:8} {x['side']:4} {x['symbol']:12} ₹{x['value_cr']:>8,.1f} cr  {x['client'][:50]}")
    if a.dry_run:
        log("dry run: nothing written")
        return
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
