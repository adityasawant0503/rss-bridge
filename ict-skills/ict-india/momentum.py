#!/usr/bin/env python3
"""Monthly momentum paper portfolio on the Nifty 50. Paper research only; rules fixed 20 Nov 2026.

Each month-end: rank the Nifty 50 stocks by their return over the last 12 months excluding the latest month
(close 21 trading days ago / close 252 trading days ago) and hold the top 10 in equal amounts until the next
month-end. If Nifty closes below its 200-day average on the month-end, hold cash (6% a year) instead.

Backtest Dec 2017 - Nov 2026 on today's members (so survivorship-biased): +21.2% a year, worst fall -15%,
74% of months up; Nifty itself +10.7%, -29%. Momentum beat the equal weight of the same 50 stocks by ~2.6% a
year in both halves; the 200-day filter halved the worst fall. Costs: 0.2% per round trip on the part of the
portfolio that changes. Short-term capital gains tax (20%) is not modelled.

  python3 momentum.py picks       # what the rule would hold if the month ended at the latest close
  python3 momentum.py rebalance   # first run of a new month: log last month-end's picks and score the month before
  python3 momentum.py summary     # the paper record against Nifty

The log is ict/research/momentum-paper.jsonl (git-ignored, backed up with the rest of ict/research).
The member list follows NSE's Nifty 50; update MEMBERS when NSE changes it (March and September).
"""
import argparse
import bisect
import json
import os
import statistics
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm    # noqa: E402
import optbt   # noqa: E402

MEMBERS = ("ADANIENT ADANIPORTS APOLLOHOSP ASIANPAINT AXISBANK BAJAJ-AUTO BAJFINANCE BAJAJFINSV BEL BHARTIARTL "
           "CIPLA COALINDIA DRREDDY EICHERMOT ETERNAL GRASIM HCLTECH HDFCBANK HDFCLIFE HEROMOTOCO HINDALCO "
           "HINDUNILVR ICICIBANK INDUSINDBK INFY ITC JIOFIN JSWSTEEL KOTAKBANK LT M&M MARUTI NESTLEIND NTPC ONGC "
           "POWERGRID RELIANCE SBILIFE SHRIRAMFIN SBIN SUNPHARMA TCS TATACONSUM TMPV TATASTEEL TECHM TITAN TRENT "
           "ULTRACEMCO WIPRO").split()
TOP, LOOKBACK, SKIP, MA_DAYS = 10, 252, 21, 200
CASH_MONTH, COST = 0.005, 0.002           # 6% a year in cash; 0.2% per round trip on turnover
FIRST_MONTH = "2026-11"                   # the paper record starts with the 30 Nov 2026 month-end
PAPER_CAPITAL = 100000.0
STOCK_DIR = os.path.join(optbt.MARKET_DIR, "stocks")
LOG = os.path.join(mmxm.STATE_DIR, "research", "momentum-paper.jsonl")


# ---------------------------------------------------------------- the rule (pure functions, tested offline)

def close_on(series, day):
    """Last close on or before day (within 10 calendar days), else None. series: ([dates], [closes])."""
    ds, cs = series
    k = bisect.bisect_right(ds, day) - 1
    return cs[k] if k >= 0 and (day - ds[k]).days < 10 else None


def rank(stocks, dates, i, top=TOP):
    """[(symbol, momentum)] best first, for the month-end at dates[i]. Needs 252 sessions of history."""
    if i < LOOKBACK:
        return []
    moms = {}
    for sym, series in stocks.items():
        p0, p_skip, p_back = close_on(series, dates[i]), close_on(series, dates[i - SKIP]), close_on(series, dates[i - LOOKBACK])
        if p0 and p_skip and p_back:
            moms[sym] = p_skip / p_back - 1
    return sorted(moms.items(), key=lambda kv: -kv[1])[:top]


def above_average(closes, i, days=MA_DAYS):
    return i >= days - 1 and closes[i] > sum(closes[i - days + 1:i + 1]) / days


def month_result(row, before, stocks, end_day):
    """Paper return of the month that started at `row` (a rebalance) and ended on end_day, after costs.
    `before` is the rebalance before it (or None) and sets the turnover."""
    if not row["invested"]:
        return CASH_MONTH
    held = [p["sym"] for p in row["picks"]]
    old = set(p["sym"] for p in before["picks"]) if before and before["invested"] else set()
    turnover = len(set(held) - old) / float(len(held))
    rets = []
    for p in row["picks"]:
        end = close_on(stocks[p["sym"]], end_day) if p["sym"] in stocks else None
        rets.append(end / p["close"] - 1 if end else 0.0)
    return statistics.mean(rets) - turnover * COST


# ---------------------------------------------------------------- data

def load_stock(sym, max_age=12 * 3600):
    os.makedirs(STOCK_DIR, exist_ok=True)
    path = os.path.join(STOCK_DIR, "%s-1d.json" % sym.replace("&", "_").lower())
    if not os.path.exists(path) or time.time() - os.path.getmtime(path) > max_age:
        try:
            doc = optbt.fetch(sym + ".NS", "1d", "2y", tries=2)
        except SystemExit:
            if not os.path.exists(path):
                return None
        else:
            with open(path + ".part", "w") as f:
                json.dump(doc, f)
            os.replace(path + ".part", path)
            time.sleep(0.3)
    with open(path) as f:
        bars = [(b[0].date(), b[4]) for b in optbt.ist_bars(json.load(f)) if b[4]]
    return ([d for d, _ in bars], [c for _, c in bars]) if bars else None


def load_all():
    stocks, missing = {}, []
    for sym in MEMBERS:
        s = load_stock(sym)
        if s:
            stocks[sym] = s
        else:
            missing.append(sym)
    nifty = optbt.ist_bars(optbt.fetch("^NSEI", "1d", "2y"))
    dates = [b[0].date() for b in nifty if b[4]]
    closes = [b[4] for b in nifty if b[4]]
    return stocks, missing, dates, closes


def read_log():
    if not os.path.exists(LOG):
        return []
    with open(LOG) as f:
        return [json.loads(x) for x in f if x.strip()]


def append_log(rows):
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    with open(LOG, "a") as f:
        for r in rows:
            f.write(json.dumps(r) + "\n")


def equity(rows):
    eq, nf = 1.0, 1.0
    for r in rows:
        if r["type"] == "result":
            eq *= 1 + r["portfolio"]
            nf *= 1 + r["nifty"]
    return eq, nf


# ---------------------------------------------------------------- commands

def make_rebalance(stocks, dates, closes, i, value):
    top = rank(stocks, dates, i)
    invested = above_average(closes, i)
    picks = []
    for sym, mom in top:
        c = close_on(stocks[sym], dates[i])
        picks.append({"sym": sym, "close": round(c, 2), "mom": round(mom, 4), "qty": int(value / TOP // c)})
    return {"type": "rebalance", "month": dates[i].strftime("%Y-%m"), "date": str(dates[i]), "invested": invested,
            "nifty": round(closes[i], 2), "nifty_avg200": round(sum(closes[i - MA_DAYS + 1:i + 1]) / MA_DAYS, 2),
            "picks": picks}


def show(r, value):
    print("Momentum paper portfolio, month-end %s (Nifty %.2f, 200-day average %.2f): %s" % (
        r["date"], r["nifty"], r["nifty_avg200"],
        "INVESTED in the top 10" if r["invested"] else "CASH (Nifty below its 200-day average); the top 10 for reference"))
    for p in r["picks"]:
        size = ("paper qty %4d (about Rs %.0f)" % (p["qty"], p["qty"] * p["close"]) if p["qty"]
                else "one share costs more than the Rs %.0f slot (scored at equal weight anyway)" % (value / TOP))
        print("  %-11s close %9.2f   12-1 month return %+6.1f%%   %s" % (p["sym"], p["close"], 100 * p["mom"], size))
    print("  paper value Rs %.0f, Rs %.0f per stock" % (value, value / TOP))


def cmd_picks(args):
    stocks, missing, dates, closes = load_all()
    eq, _ = equity(read_log())
    r = make_rebalance(stocks, dates, closes, len(dates) - 1, PAPER_CAPITAL * eq)
    show(r, PAPER_CAPITAL * eq)
    if missing:
        print("  no data for: %s" % ", ".join(missing))


def cmd_rebalance(args):
    rows = read_log()
    done = {r["month"] for r in rows if r["type"] == "rebalance"}
    stocks, missing, dates, closes = load_all()
    ends = [i for i in range(len(dates) - 1) if dates[i].month != dates[i + 1].month]   # finished months only
    ends = [i for i in ends if dates[i].strftime("%Y-%m") >= FIRST_MONTH and dates[i].strftime("%Y-%m") not in done]
    if not ends:
        print("momentum: nothing to do (next rebalance after the month-end close)")
        return
    for i in ends:
        rebs = [r for r in rows if r["type"] == "rebalance"]
        new = []
        if rebs:
            last = rebs[-1]
            before = rebs[-2] if len(rebs) > 1 else None
            port = month_result(last, before, stocks, dates[i])
            nifty = closes[i] / last["nifty"] - 1
            new.append({"type": "result", "month": last["month"], "from": last["date"], "to": str(dates[i]),
                        "portfolio": round(port, 5), "nifty": round(nifty, 5), "invested": last["invested"]})
            print("Paper result %s -> %s: portfolio %+.2f%%, Nifty %+.2f%%%s" % (
                last["date"], dates[i], 100 * port, 100 * nifty, "" if last["invested"] else " (in cash)"))
        eq, _ = equity(rows + new)
        r = make_rebalance(stocks, dates, closes, i, PAPER_CAPITAL * eq)
        new.append(r)
        append_log(new)
        rows += new
        show(r, PAPER_CAPITAL * eq)
    if missing:
        print("  no data for: %s" % ", ".join(missing))


def cmd_summary(args):
    rows = read_log()
    res = [r for r in rows if r["type"] == "result"]
    rebs = [r for r in rows if r["type"] == "rebalance"]
    if not rebs:
        print("momentum paper portfolio: no month-end logged yet (first one: %s)" % FIRST_MONTH)
        return
    eq, nf = equity(rows)
    print("momentum paper portfolio since %s: %d finished month%s; Rs %.0f -> Rs %.0f (%+.1f%%), Nifty %+.1f%%" % (
        rebs[0]["date"], len(res), "" if len(res) == 1 else "s", PAPER_CAPITAL, PAPER_CAPITAL * eq, 100 * (eq - 1), 100 * (nf - 1)))
    for r in res:
        print("  %s: portfolio %+5.2f%%  Nifty %+5.2f%%%s" % (r["month"], 100 * r["portfolio"], 100 * r["nifty"], "" if r["invested"] else "  (cash)"))
    last = rebs[-1]
    print("  holding now (from %s): %s" % (last["date"], ", ".join(p["sym"] for p in last["picks"]) if last["invested"] else "cash"))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["picks", "rebalance", "summary"])
    a = ap.parse_args(argv)
    return {"picks": cmd_picks, "rebalance": cmd_rebalance, "summary": cmd_summary}[a.cmd](a)


if __name__ == "__main__":
    main()
