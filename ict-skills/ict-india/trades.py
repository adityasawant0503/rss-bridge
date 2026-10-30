#!/usr/bin/env python3
"""Your real trades, read through the ICT structure.

Reads a broker tradebook (Dhan's Excel/CSV export, or any CSV with date, time, symbol, buy/sell,
quantity and price columns), pairs every fill into round trips, and reports where the money came from:
by killzone and session, hour, weekday, days to expiry, instrument, call/put, direction, holding time and
size. Then it replays the rules from the notes (killzones only, 2 trades a day, stop after 2 losses,
no Fridays, no afternoon after a morning trade, no expiry day) against the trades you actually took,
and shows what each rule would have kept or cost you.

  python3 trades.py report ict/dhan-2025/*.xlsx ict/dhan-2025/*.csv
  python3 trades.py report tradebook.csv --bars banknifty-5m.csv   # also check for a sweep/MSS/FVG before each entry
  python3 trades.py report tradebook.csv --months 2025-06,2025-08,2025-09,2025-10,2025-11 --json out.json
  DHAN_PDF_PASSWORD=XXXXX1234X python3 trades.py report contract-notes.zip   # locked contract notes, unlocked in bulk

Raw files stay on your machine (keep them in ict/, which is git-ignored). Standard library only.
"""
import argparse
import csv
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from collections import OrderedDict, defaultdict
from datetime import date, datetime, timedelta
from xml.etree import ElementTree

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm  # noqa: E402  (same folder)

MONTHS = {m: i + 1 for i, m in enumerate("JAN FEB MAR APR MAY JUN JUL AUG SEP OCT NOV DEC".split())}
UNDERLYINGS = ["MIDCPNIFTY", "NIFTYNXT50", "BANKNIFTY", "FINNIFTY", "BANKEX", "SENSEX", "NIFTY"]

COLS = OrderedDict([
    ("datetime", ["trade date time", "trade datetime", "date time", "datetime", "timestamp", "exchange time"]),
    ("date", ["trade date", "date", "order date", "txn date"]),
    ("time", ["trade time", "time", "order time", "exch time"]),
    ("symbol", ["trading symbol", "tradingsymbol", "symbol", "contract", "instrument", "security", "scrip", "name", "description"]),
    ("side", ["buy/sell", "buy / sell", "b/s", "side", "transaction type", "txn type", "trade type", "action", "type"]),
    ("qty", ["traded qty", "trade qty", "filled qty", "quantity", "qty"]),
    ("price", ["trade price", "traded price", "avg price", "average price", "price", "rate"]),
])


# ---------------------------------------------------------------- reading files

def read_xlsx(path):
    """First worksheet of an .xlsx as a list of rows (strings), without openpyxl."""
    with zipfile.ZipFile(path) as z:
        ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ElementTree.fromstring(z.read("xl/sharedStrings.xml"))
            for si in root.findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter("{%s}t" % ns["m"])))
        sheets = sorted(n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n))
        root = ElementTree.fromstring(z.read(sheets[0]))
        rows = []
        for r in root.iter("{%s}row" % ns["m"]):
            cells = {}
            for c in r.findall("m:c", ns):
                ref = re.match(r"([A-Z]+)", c.get("r", "A")).group(1)
                col = 0
                for ch in ref:
                    col = col * 26 + ord(ch) - 64
                v = c.find("m:v", ns)
                t = c.get("t")
                if t == "s" and v is not None:
                    val = shared[int(v.text)]
                elif t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % ns["m"]))
                else:
                    val = v.text if v is not None else ""
                cells[col - 1] = val
            if cells:
                rows.append([cells.get(i, "") for i in range(max(cells) + 1)])
        return rows


def read_rows(path):
    if path.lower().endswith((".xlsx", ".xlsm")):
        return read_xlsx(path)
    with open(path, newline="", encoding="utf-8-sig", errors="replace") as f:
        text = f.read()
    head = text[:8192]
    delim = max(",;\t|", key=head.count)
    return [r for r in csv.reader(io.StringIO(text), delimiter=delim)]


def find_header(rows):
    """The first row that names a symbol, a side, a quantity and a price; returns (index, {field: column})."""
    for i, row in enumerate(rows[:60]):
        low = [str(c).strip().lower() for c in row]
        found = {}
        for field, names in COLS.items():
            for name in names:
                hit = next((k for k, c in enumerate(low) if c == name and k not in found.values()), None)
                if hit is None:
                    hit = next((k for k, c in enumerate(low) if name in c and k not in found.values()), None)
                if hit is not None:
                    found[field] = hit
                    break
        if {"symbol", "side", "qty", "price"} <= set(found) and ({"date", "datetime"} & set(found)):
            return i, found
    raise ValueError("could not find a header row with date, symbol, buy/sell, quantity and price columns")


def parse_dt(d, t=""):
    d, t = str(d).strip(), str(t).strip()
    if re.fullmatch(r"\d+(\.\d+)?", t) and float(t) < 1:                 # Excel time as a fraction of a day
        secs = round(float(t) * 86400)
        t = "%02d:%02d:%02d" % (secs // 3600, secs // 60 % 60, secs % 60)
    if re.fullmatch(r"\d+(\.\d+)?", d) and float(d) > 20000:            # Excel serial date (maybe with time)
        dt = datetime(1899, 12, 30) + timedelta(seconds=round(float(d) * 86400))
        d = dt.strftime("%Y-%m-%d") if t else dt.strftime("%Y-%m-%d %H:%M:%S")
    s = (d + " " + t).strip().replace("T", " ")
    s = re.sub(r"\s+", " ", s)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M:%S", "%d/%m/%Y %H:%M:%S", "%d-%m-%Y %H:%M",
                "%d/%m/%Y %H:%M", "%d %b %Y %H:%M:%S", "%d-%b-%Y %H:%M:%S", "%d %b %Y %I:%M:%S %p",
                "%d-%m-%Y %I:%M:%S %p", "%d/%m/%Y %I:%M:%S %p", "%Y-%m-%d %I:%M:%S %p", "%d-%b-%Y %I:%M:%S %p",
                "%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d %b %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    raise ValueError("unreadable date/time %r" % s)


def num(v):
    return float(str(v).replace(",", "").replace("₹", "").strip() or 0)


def parse_contract(sym, trade_day):
    """Underlying, kind (CE/PE/FUT/EQ), strike and expiry date (when the symbol carries one)."""
    s = re.sub(r"[-_/]", " ", str(sym).upper())
    s = re.sub(r"\s+", " ", s).strip()
    und = next((u for u in UNDERLYINGS if re.search(r"(^|[^A-Z])" + u + r"(?![A-Z])", s) or s.startswith(u)), None)
    kind = "CE" if re.search(r"(CE|CALL)\b", s) else "PE" if re.search(r"(PE|PUT)\b", s) else "FUT" if "FUT" in s else "EQ"
    strike = None
    m = re.search(r"(\d{4,6}(?:\.\d+)?)\s*(CE|PE|CALL|PUT)\b", s)
    if m:
        strike = float(m.group(1))
    exp = None
    m = re.search(r"\b(\d{1,2})\s?(JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC)[A-Z]*\s?(\d{4}|\d{2})?\b", s)
    if m:
        y = int(m.group(3)) if m.group(3) else trade_day.year
        y = y + 2000 if y < 100 else y
        try:
            exp = date(y, MONTHS[m.group(2)], int(m.group(1)))
        except ValueError:
            exp = None
    if exp is None and und:
        rest = s.replace(" ", "")[len(und):] if s.replace(" ", "").startswith(und) else ""
        m = re.match(r"(\d{2})([1-9OND])(\d{2})\d{4,6}(CE|PE)$", rest)   # NSE weekly: YY M DD strike CE
        if m:
            mon = {"O": 10, "N": 11, "D": 12}.get(m.group(2)) or int(m.group(2))
            try:
                exp = date(2000 + int(m.group(1)), mon, int(m.group(3)))
            except ValueError:
                exp = None
    return {"underlying": und or s.split(" ")[0], "kind": kind, "strike": strike, "expiry": exp}


def pdf_text(path, password=None):
    """Text of a PDF, unlocked with the password when it has one: pdftotext (poppler) first, then pypdf."""
    name = os.path.basename(path)
    exe = shutil.which("pdftotext")
    if exe:
        out = subprocess.run([exe, "-layout"] + (["-upw", password] if password else []) + [path, "-"],
                             capture_output=True, timeout=120)
        if out.returncode == 0:
            return out.stdout.decode("utf-8", "replace")
        if b"assword" in out.stderr:
            raise ValueError("%s is password-protected: pass --password or set DHAN_PDF_PASSWORD" % name)
    try:
        import pypdf
    except ImportError:
        raise ValueError("reading %s needs pdftotext (poppler) or the pypdf package" % name)
    reader = pypdf.PdfReader(path)
    if reader.is_encrypted and (not password or not reader.decrypt(password)):
        raise ValueError("%s is password-protected and the password did not open it" % name)
    pages = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text(extraction_mode="layout") or "")
        except TypeError:
            pages.append(page.extract_text() or "")
    return "\n".join(pages)


NOTE_DATE = re.compile(r"trade\s*date\s*[:\-]?\s*(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{2,4}|\d{1,2}[ \-][A-Za-z]{3}[ \-]\d{2,4}|\d{4}-\d{2}-\d{2})", re.I)
TIME_RE = re.compile(r"\b(\d{1,2}:\d{2}:\d{2})\b")
SIDE_RE = re.compile(r"(?<![A-Z])(BUY|SELL|B|S)(?![A-Z])")
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
UND_RE = re.compile(r"(?<![A-Z])(" + "|".join(UNDERLYINGS) + r")")


def parse_contract_note(text, name):
    """Trade rows from a contract note's text: a line with a time, an index contract, B/S, quantity and price.

    Returns (fills, unparsed lines that looked like trades)."""
    m = NOTE_DATE.search(text)
    if not m:
        raise ValueError("%s: no 'Trade Date' found, so this may not be a contract note" % name)
    day = parse_dt(m.group(1).replace(".", "-")).date()
    fills, misses = [], []
    for line in text.splitlines():
        up = line.upper()
        und = UND_RE.search(up)
        if not und or not TIME_RE.search(up):
            continue
        tail = up[und.start():]
        side = None
        for x in SIDE_RE.finditer(tail):
            if len(NUM_RE.findall(tail[x.end():])) >= 2:
                side = x
                break
        if not side:
            misses.append(line.strip())
            continue
        nums = NUM_RE.findall(tail[side.end():])
        before = TIME_RE.findall(up[:und.start()]) or TIME_RE.findall(up)
        try:
            qty, price = num(nums[0]), num(nums[1])
            when = datetime.combine(day, datetime.strptime(before[-1], "%H:%M:%S").time())
        except ValueError:
            misses.append(line.strip())
            continue
        if qty <= 0 or price <= 0:
            misses.append(line.strip())
            continue
        fills.append({"t": when, "symbol": re.sub(r"\s+", " ", tail[:side.start()].strip()), "side": side.group(1)[0],
                      "qty": qty, "price": price, "file": name})
    return fills, misses


def expand(paths, workdir):
    """Zip files are unpacked (only PDF/CSV/Excel members) into workdir; everything else passes through."""
    out = []
    for p in paths:
        if p.lower().endswith(".zip"):
            with zipfile.ZipFile(p) as z:
                for k, info in enumerate(z.infolist()):
                    base = os.path.basename(info.filename)
                    if info.is_dir() or not base.lower().endswith((".pdf", ".csv", ".xlsx", ".xlsm")):
                        continue
                    dest = os.path.join(workdir, "%04d-%s" % (k, re.sub(r"[^A-Za-z0-9._-]", "_", base)))
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    out.append(dest)
        else:
            out.append(p)
    return out


LAST_MISSES = []


def load_fills(paths, password=None):
    fills = []
    del LAST_MISSES[:]
    work = tempfile.mkdtemp(prefix="trades-")
    try:
        files = expand(paths, work)
        for p in files:
            if p.lower().endswith(".pdf"):
                got, misses = parse_contract_note(pdf_text(p, password), os.path.basename(p))
                fills.extend(got)
                LAST_MISSES.extend((os.path.basename(p), x) for x in misses)
                continue
            fills.extend(load_table(p))
    finally:
        shutil.rmtree(work, ignore_errors=True)
    fills.sort(key=lambda f: (f["t"], f["symbol"]))
    # the same fill exported twice (overlapping reports) counts once
    seen, out = set(), []
    for f in fills:
        k = (f["t"], f["symbol"], f["side"], f["qty"], f["price"])
        if k not in seen:
            seen.add(k)
            out.append(f)
    return out


def load_table(p):
    fills = []
    rows = read_rows(p)
    h, col = find_header(rows)
    for r in rows[h + 1:]:
        if len(r) <= max(col.values()) or not str(r[col["symbol"]]).strip():
            continue
        side = str(r[col["side"]]).strip().upper()
        if side[:1] not in ("B", "S"):
            continue
        try:
            when = parse_dt(r[col["datetime"]]) if "datetime" in col else parse_dt(r[col["date"]], r[col["time"]] if "time" in col else "")
            qty, price = abs(num(r[col["qty"]])), num(r[col["price"]])
        except ValueError:
            continue
        if qty <= 0:
            continue
        fills.append({"t": when, "symbol": re.sub(r"\s+", " ", str(r[col["symbol"]]).strip()),
                      "side": side[0], "qty": qty, "price": price, "file": os.path.basename(p)})
    return fills


# ---------------------------------------------------------------- round trips

def round_trips(fills):
    """Flat -> position -> flat, per contract. P&L is gross (before charges)."""
    open_, trips = {}, []
    for f in fills:
        sign = 1 if f["side"] == "B" else -1
        tr = open_.get(f["symbol"])
        if tr is None:
            tr = open_[f["symbol"]] = {"symbol": f["symbol"], "entry_t": f["t"], "pos": 0.0, "cash": 0.0, "max_qty": 0.0,
                                       "fills": 0, "first_side": f["side"], "buy_qty": 0.0, "buy_val": 0.0, "sell_val": 0.0}
        tr["pos"] += sign * f["qty"]
        tr["cash"] -= sign * f["qty"] * f["price"]
        tr["fills"] += 1
        tr["max_qty"] = max(tr["max_qty"], abs(tr["pos"]))
        if f["side"] == "B":
            tr["buy_qty"] += f["qty"]
            tr["buy_val"] += f["qty"] * f["price"]
        else:
            tr["sell_val"] += f["qty"] * f["price"]
        if abs(tr["pos"]) < 1e-9:
            tr["exit_t"] = f["t"]
            trips.append(open_.pop(f["symbol"]))
    for tr in open_.values():
        tr["exit_t"] = None
        trips.append(tr)
    for tr in trips:
        c = parse_contract(tr["symbol"], tr["entry_t"].date())
        tr.update(c)
        tr["pnl"] = round(tr["cash"], 2) if tr["exit_t"] else None
        tr["hold_min"] = round((tr["exit_t"] - tr["entry_t"]).total_seconds() / 60, 1) if tr["exit_t"] else None
        bought = tr["first_side"] == "B"
        if tr["kind"] in ("CE", "FUT", "EQ"):
            tr["view"] = "long" if bought else "short"
        else:
            tr["view"] = "short" if bought else "long"
        tr["style"] = ("buy " if bought else "sell ") + tr["kind"]
        tr["dte"] = (tr["expiry"] - tr["entry_t"].date()).days if tr["expiry"] else None
        tr["entry_premium"] = round(tr["buy_val"] / tr["buy_qty"], 2) if tr["buy_qty"] else None
    trips.sort(key=lambda t: t["entry_t"])
    return trips


# ---------------------------------------------------------------- ICT tagging

def window_of(mkt, dt):
    m = dt.hour * 60 + dt.minute
    for name, (a, b) in mkt.sessions.items():
        if a <= m < b:
            return name
    return "outside" if m < mkt.sessions["opening_range"][0] or m >= mkt.sessions["close"][1] else "between"


def tag(mkt, trips):
    for t in trips:
        t["day"] = t["entry_t"].date()
        t["window"] = window_of(mkt, t["entry_t"])
        t["killzone"] = t["window"] in mkt.killzones
        t["weekday"] = t["entry_t"].strftime("%a")
        t["hour"] = t["entry_t"].strftime("%H:00")
        t["expiry_day"] = t["dte"] == 0
    by_day = defaultdict(list)
    for t in trips:
        by_day[t["day"]].append(t)
    for day, ts in by_day.items():
        losses = 0
        am_traded = False
        for k, t in enumerate(ts):
            t["nth_today"] = k + 1
            t["losses_before"] = losses
            t["after_am_trade"] = am_traded and t["window"] != mkt.killzones[0]
            if t["window"] == mkt.killzones[0]:
                am_traded = True
            if (t["pnl"] or 0) < 0:
                losses += 1


def ict_context(mkt, trips, bars, cfg):
    """For each trip on the underlying the bars belong to: was there a sweep / live MMXM setup in the trade's direction?"""
    di = mmxm.days_of(bars, mkt)
    htf = mmxm.resample(bars, 15, mkt)
    ts_index = [b.t for b in bars]
    import bisect
    for t in trips:
        day = t["day"]
        if day not in di:
            continue
        ts = mmxm.from_local(t["entry_t"].replace(second=0), mkt.tz)
        k = bisect.bisect_right(ts_index, ts) - 1
        if k < di[day][0]:
            continue
        setups = mmxm.run_day(mkt, bars, day, di, htf, cfg, [t["view"]], upto=k)
        recent = [s for s in setups if s.get("sweep_t") and ts - s["sweep_t"] <= 3600]
        t["after_sweep"] = bool(recent)
        t["mmxm_live"] = any(s["status"] in ("armed", "tapped", "open") for s in setups)
        t["ict_checked"] = True


# ---------------------------------------------------------------- report

def stats(ts):
    done = [t for t in ts if t["pnl"] is not None]
    wins = [t["pnl"] for t in done if t["pnl"] > 0]
    loss = [t["pnl"] for t in done if t["pnl"] <= 0]
    gross_win, gross_loss = sum(wins), -sum(loss)
    return {"trades": len(done), "pnl": round(sum(t["pnl"] for t in done), 2), "wins": len(wins), "losses": len(loss),
            "win_rate": round(100.0 * len(wins) / len(done), 1) if done else None,
            "avg_win": round(gross_win / len(wins), 2) if wins else None,
            "avg_loss": round(-gross_loss / len(loss), 2) if loss else None,
            "profit_factor": round(gross_win / gross_loss, 2) if gross_loss else None,
            "largest_loss": round(min(loss), 2) if loss else None}


def group(trips, key, order=None):
    g = defaultdict(list)
    for t in trips:
        g[key(t)].append(t)
    keys = order or sorted(g, key=lambda k: (str(type(k)), k))
    return [(k, stats(g[k])) for k in keys if k in g]


HOLD_BUCKETS = [(2, "under 2 min"), (5, "2-5 min"), (10, "5-10 min"), (30, "10-30 min"), (90, "30-90 min"), (1e9, "over 90 min")]


def hold_bucket(t):
    if t["hold_min"] is None:
        return "open"
    return next(label for lim, label in HOLD_BUCKETS if t["hold_min"] < lim)


def dte_bucket(t):
    if t["dte"] is None:
        return "unknown"
    return "expiry day" if t["dte"] == 0 else "1 day before" if t["dte"] == 1 else "2-3 days" if t["dte"] <= 3 else "4+ days"


RULES = [
    ("Killzones only (AM 09:30-11:00, PM 13:15-14:45)", lambda t: not t["killzone"]),
    ("No trades in the 09:15-09:30 opening range", lambda t: t["window"] == "opening_range"),
    ("Max 2 trades a day", lambda t: t["nth_today"] > 2),
    ("Stop after 2 losing trades", lambda t: t["losses_before"] >= 2),
    ("No afternoon trade after a morning trade", lambda t: t["after_am_trade"]),
    ("No new positions on Friday", lambda t: t["weekday"] == "Fri"),
    ("No trades on the contract's expiry day", lambda t: t["expiry_day"]),
]


def rule_impact(trips):
    out = []
    done = [t for t in trips if t["pnl"] is not None]
    for name, blocks in RULES:
        hit = [t for t in done if blocks(t)]
        out.append({"rule": name, "blocked": len(hit), "blocked_pnl": round(sum(t["pnl"] for t in hit), 2),
                    "blocked_losers": len([t for t in hit if t["pnl"] < 0])})
    allhit = [t for t in done if any(b(t) for _, b in RULES)]
    out.append({"rule": "All of the above together", "blocked": len(allhit), "blocked_pnl": round(sum(t["pnl"] for t in allhit), 2),
                "blocked_losers": len([t for t in allhit if t["pnl"] < 0])})
    return out


def inr(v):
    if v is None:
        return "-"
    s = "%.0f" % abs(v)
    head, tail = s[:-3], s[-3:]
    while len(head) > 2:
        tail = head[-2:] + "," + tail
        head = head[:-2]
    return ("-" if v < 0 else "") + "₹" + (head + "," + tail if head else tail)


def build(paths, months=None, bars=None, profile=None, password=None):
    prof = mmxm.load_profile(profile)
    cfg = mmxm.load_config(prof)
    mkt = mmxm.Market(prof, cfg)
    fills = load_fills(paths, password)
    if months:
        fills = [f for f in fills if f["t"].strftime("%Y-%m") in months]
    trips = round_trips(fills)
    tag(mkt, trips)
    if bars:
        cfg["_buffer"] = 0.0
        ict_context(mkt, trips, mmxm.load_file(bars, mkt), cfg)
    days = defaultdict(float)
    for t in trips:
        if t["pnl"] is not None:
            days[t["day"]] += t["pnl"]
    rep = {
        "fills": len(fills), "files": sorted({f["file"] for f in fills}),
        "unparsed": [{"file": f, "line": x} for f, x in LAST_MISSES],
        "overall": stats(trips),
        "open_positions": [t["symbol"] for t in trips if t["pnl"] is None],
        "by_month": group(trips, lambda t: t["entry_t"].strftime("%Y-%m")),
        "by_window": group(trips, lambda t: t["window"], ["opening_range", "am", "between", "lunch", "pm", "close", "outside"]),
        "by_hour": group(trips, lambda t: t["hour"]),
        "by_weekday": group(trips, lambda t: t["weekday"], ["Mon", "Tue", "Wed", "Thu", "Fri"]),
        "by_expiry": group(trips, dte_bucket, ["expiry day", "1 day before", "2-3 days", "4+ days", "unknown"]),
        "by_underlying": group(trips, lambda t: t["underlying"]),
        "by_style": group(trips, lambda t: t["style"]),
        "by_view": group(trips, lambda t: t["view"], ["long", "short"]),
        "by_hold": group(trips, hold_bucket, [b for _, b in HOLD_BUCKETS] + ["open"]),
        "by_nth_trade": group(trips, lambda t: "trade %d of the day" % min(t["nth_today"], 4) if t["nth_today"] < 4 else "4th or later"),
        "days": {"count": len(days), "green": len([v for v in days.values() if v > 0]),
                 "median": round(sorted(days.values())[len(days) // 2], 2) if days else None,
                 "best": sorted(((str(k), round(v, 2)) for k, v in days.items()), key=lambda kv: -kv[1])[:5],
                 "worst": sorted(((str(k), round(v, 2)) for k, v in days.items()), key=lambda kv: kv[1])[:5]},
        "rules": rule_impact(trips),
        "hold_minutes_median": sorted(t["hold_min"] for t in trips if t["hold_min"] is not None)[len([t for t in trips if t["hold_min"] is not None]) // 2] if any(t["hold_min"] is not None for t in trips) else None,
        "losers": [{"day": str(t["day"]), "time": t["entry_t"].strftime("%H:%M"), "symbol": t["symbol"], "pnl": t["pnl"],
                    "window": t["window"], "hold_min": t["hold_min"]} for t in trips if t["pnl"] is not None and t["pnl"] < 0],
    }
    if bars:
        checked = [t for t in trips if t.get("ict_checked")]
        rep["ict"] = {"checked": len(checked),
                      "after_sweep": group(checked, lambda t: "after a sweep (last 60 min)" if t["after_sweep"] else "no sweep before entry"),
                      "mmxm_live": group(checked, lambda t: "MMXM setup live at entry" if t["mmxm_live"] else "no live setup")}
    return rep, trips


def print_report(rep):
    o = rep["overall"]
    files = rep["files"]
    print("%d fills from %s -> %d round trips" % (rep["fills"], ", ".join(files) if len(files) <= 4 else "%d files" % len(files), o["trades"]))
    if rep["unparsed"]:
        print("%d lines looked like trades but could not be read, for example:" % len(rep["unparsed"]))
        for u in rep["unparsed"][:3]:
            print("  %s: %s" % (u["file"], u["line"][:140]))
    print("gross P&L %s   won %d / lost %d (%.0f%%)   avg win %s   avg loss %s   profit factor %s   largest loss %s" % (
        inr(o["pnl"]), o["wins"], o["losses"], o["win_rate"] or 0, inr(o["avg_win"]), inr(o["avg_loss"]),
        o["profit_factor"], inr(o["largest_loss"])))
    print("charges are not included: compare with the P&L statement's net figure")
    if rep["open_positions"]:
        print("still open at the end of the data: %s" % ", ".join(rep["open_positions"]))
    d = rep["days"]
    if d["count"]:
        print("%d trading days, %d green, median day %s, median hold %s min" % (d["count"], d["green"], inr(d["median"]), rep["hold_minutes_median"]))

    def table(title, rows):
        print("\n" + title)
        for k, s in rows:
            pf = "-" if s["profit_factor"] is None else s["profit_factor"]
            print("  %-26s %4d trades  %13s  win %5s%%  PF %s" % (k, s["trades"], inr(s["pnl"]), s["win_rate"], pf))

    for title, key in (("By month", "by_month"), ("By ICT window (IST)", "by_window"), ("By hour", "by_hour"),
                       ("By weekday", "by_weekday"), ("By days to expiry", "by_expiry"), ("By underlying", "by_underlying"),
                       ("By style", "by_style"), ("By index direction", "by_view"), ("By holding time", "by_hold"),
                       ("By trade number in the day", "by_nth_trade")):
        table(title, rep[key])
    if "ict" in rep:
        table("Sweep before entry (%d trades checked against index bars)" % rep["ict"]["checked"], rep["ict"]["after_sweep"])
        table("MMXM setup at entry", rep["ict"]["mmxm_live"])
    print("\nYour notes' rules, replayed on these trades (what each would have blocked)")
    for r in rep["rules"]:
        if not r["blocked"]:
            effect = "no effect"
        else:
            effect = ("would have cost you " if r["blocked_pnl"] > 0 else "would have saved you ") + inr(abs(r["blocked_pnl"]))
        print("  %-52s %4d trades (%d losers)  %s" % (r["rule"], r["blocked"], r["blocked_losers"], effect))
    print("\nBest days: %s" % ", ".join("%s %s" % (k, inr(v)) for k, v in d["best"]))
    print("Worst days: %s" % ", ".join("%s %s" % (k, inr(v)) for k, v in d["worst"]))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("report")
    r.add_argument("files", nargs="+")
    r.add_argument("--months", help="comma list like 2025-06,2025-08")
    r.add_argument("--bars", help="index bars (CSV time,open,high,low,close) to check for sweeps and MMXM setups")
    r.add_argument("--json", help="write the full report and every round trip here")
    r.add_argument("--password", help="contract-note PDF password (or set DHAN_PDF_PASSWORD, which keeps it out of shell history)")
    a = ap.parse_args(argv)
    rep, trips = build(a.files, set(a.months.split(",")) if a.months else None, a.bars,
                       password=a.password or os.environ.get("DHAN_PDF_PASSWORD"))
    print_report(rep)
    if a.json:
        os.makedirs(os.path.dirname(os.path.abspath(a.json)), exist_ok=True)
        with open(a.json, "w") as f:
            json.dump({"report": rep, "trips": [{k: v for k, v in t.items()} for t in trips]}, f, indent=1, default=str)
        print("\nfull report -> %s" % a.json)
    return rep


if __name__ == "__main__":
    main()
