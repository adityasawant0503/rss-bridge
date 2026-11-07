#!/usr/bin/env python3
"""Weekly index-option strategy: backtest it on years of index data, and get today's plan.

The strategy is one rule from the ICT notes, made mechanical: the morning move against the recent trend is
the trap ("the trend is not your friend when it's at the end"). Each day:

  1. Bias from the last 5 days: if the index closed higher than 5 sessions ago, fade it (buy puts),
     otherwise buy calls. --mode with does the opposite (trend-continuation), for comparison.
  2. At the entry time (default 10:15 IST) buy the at-the-money weekly option, at least --min-dte days out.
  3. Exit at --stop (default -30% of premium) or --target (+50%), else at the close.

Option prices are modelled with Black-Scholes from the index and India VIX (volatility = VIX x --ivm), so
they are estimates: no bid-ask, no skew, no volatility spikes. Treat results as a test of the idea, then
paper-trade it.

  python3 optbt.py fetch                       # download 2 years of Nifty, Sensex and VIX (hourly + daily) once
  python3 optbt.py backtest NIFTY              # the default strategy over the cached history, by year
  python3 optbt.py backtest SENSEX --mode with --entry 11:15 --stop 0.2 --target 0.4
  python3 optbt.py today NIFTY                 # today's plan, sized for the account in ict/config-india.json

Standard library only.
"""
import argparse
import collections
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm  # noqa: E402  (same folder)

MARKET_DIR = os.path.join(mmxm.STATE_DIR, "market")
INDICES = {
    "NIFTY": {"yahoo": "^NSEI", "step": 50, "exchange": "NSE"},
    "SENSEX": {"yahoo": "^BSESN", "step": 100, "exchange": "BSE"},
    "BANKNIFTY": {"yahoo": "^NSEBANK", "step": 100, "exchange": "NSE"},
}
VIX = "^INDIAVIX"
# Exchange lot sizes over time (from, lot). Revised by the exchanges; check your broker for the current one.
LOTS = {"NIFTY": [(date(2024, 11, 20), 75), (date(2026, 1, 1), 65)],
        "SENSEX": [(date(2024, 11, 20), 20)],
        "BANKNIFTY": [(date(2024, 11, 20), 30), (date(2025, 4, 24), 35), (date(2026, 1, 1), 30)]}
DEFAULTS = {"mode": "fade", "entry": "10:15", "stop": 0.30, "target": 0.50, "min_dte": 4, "ivm": 0.97,
            "slippage": 1.0, "charges": 40.0, "rate": 0.065}


# ---------------------------------------------------------------- data

def fetch(symbol, interval, rng, tries=5):
    """Yahoo chart JSON, with backoff on rate limits (HTTP 429)."""
    last = None
    for k in range(tries):
        for host in ("https://query1.finance.yahoo.com", "https://query2.finance.yahoo.com"):
            url = "%s/v8/finance/chart/%s?interval=%s&range=%s" % (host, urllib.request.quote(symbol), interval, rng)
            try:
                req = urllib.request.Request(url, headers={"User-Agent": mmxm.UA, "Accept": "application/json"})
                with urllib.request.urlopen(req, timeout=30) as r:
                    return json.load(r)
            except (urllib.error.URLError, ValueError) as e:
                last = e
        time.sleep(10 * (k + 1))
    raise SystemExit("could not fetch %s %s from Yahoo (%s)" % (symbol, interval, last))


def cache_name(symbol, interval):
    return os.path.join(MARKET_DIR, "%s-%s.json" % (symbol.strip("^").lower(), interval))


def cmd_fetch(args):
    os.makedirs(MARKET_DIR, exist_ok=True)
    jobs = [(VIX, "1d", "2y")]
    for name in args.indices:
        y = INDICES[name]["yahoo"]
        jobs += [(y, "60m", "2y"), (y, "1d", "2y"), (y, "5m", "60d")]
    for sym, iv, rng in jobs:
        doc = fetch(sym, iv, rng)
        with open(cache_name(sym, iv), "w") as f:
            json.dump(doc, f)
        n = len(doc["chart"]["result"][0].get("timestamp") or [])
        print("%-10s %-4s %5d bars -> %s" % (sym, iv, n, cache_name(sym, iv)))
        time.sleep(3)


def ist_bars(doc):
    """[(IST datetime, o, h, l, c)] from a Yahoo chart document."""
    out = []
    for b in mmxm.parse_yahoo(doc):
        out.append((mmxm.to_local(b.t, "Asia/Kolkata"), b.o, b.h, b.l, b.c))
    return out


def load(symbol, interval, refresh=False, max_age=None):
    """Bars from the local cache, downloading when asked, when missing, or when older than max_age seconds."""
    p = cache_name(symbol, interval)
    stale = max_age is not None and os.path.exists(p) and time.time() - os.path.getmtime(p) > max_age
    if refresh or stale or not os.path.exists(p):
        os.makedirs(MARKET_DIR, exist_ok=True)
        with open(p, "w") as f:
            json.dump(fetch(symbol, interval, "2y" if interval != "5m" else "60d"), f)
    with open(p) as f:
        return ist_bars(json.load(f))


def daily(bars):
    return {b[0].date(): b for b in bars}


# ---------------------------------------------------------------- options

def ncdf(x):
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def bs(S, K, tau, vol, kind, r=0.065):
    """Black-Scholes price of a European call ("CE") or put ("PE")."""
    if tau <= 0 or vol <= 0:
        return max(0.0, S - K) if kind == "CE" else max(0.0, K - S)
    d1 = (math.log(S / K) + (r + vol * vol / 2) * tau) / (vol * math.sqrt(tau))
    d2 = d1 - vol * math.sqrt(tau)
    if kind == "CE":
        return S * ncdf(d1) - K * math.exp(-r * tau) * ncdf(d2)
    return K * math.exp(-r * tau) * ncdf(-d2) - S * ncdf(-d1)


def tau_years(t, expiry):
    end = datetime.combine(expiry, datetime.min.time()).replace(hour=15, minute=30)
    return max((end - t).total_seconds(), 600) / (365 * 24 * 3600)


def weekly_expiry(name, day, min_dte):
    """Next weekly expiry at least min_dte calendar days out. NSE: Thursday until Aug 2025, Tuesday from Sep 2025.
    BSE: Tuesday until Aug 2025, Thursday from Sep 2025. Holiday shifts are ignored. Bank Nifty has monthly
    expiries only since late 2024; the weekly date is used as an approximation."""
    new = day >= date(2025, 9, 1)
    nse = INDICES[name]["exchange"] == "NSE"
    wd = (1 if new else 3) if nse else (3 if new else 1)
    d = day + timedelta(days=min_dte)
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d


def lot_size(name, day):
    lot = LOTS[name][0][1]
    for since, n in LOTS[name]:
        if day >= since:
            lot = n
    return lot


def vix_on(vix, day):
    if day in vix:
        return vix[day][4]
    earlier = [d for d in vix if d <= day]
    return vix[max(earlier)][4] if earlier else 15.0


# ---------------------------------------------------------------- the strategy

def bias_for(days, d, i, mode):
    """'CE' or 'PE' for trading day index i: fade (or follow) the close-to-close move of the last 5 sessions."""
    prev, five = d[days[i - 1]], d[days[i - 5]]
    up = prev[4] > five[4]
    call = (not up) if mode == "fade" else up
    return "CE" if call else "PE"


def simulate(name, hourly, d, vix, p, start=None, end=None):
    """One trade a day. Returns trades with modelled option prices (per lot, after slippage and charges)."""
    eh, em = map(int, p["entry"].split(":"))
    days = sorted(d)
    byday = collections.defaultdict(list)
    for b in hourly:
        byday[b[0].date()].append(b)
    trades = []
    for i, day in enumerate(days):
        if i < 6 or day not in byday or (start and day < start) or (end and day > end):
            continue
        bars = byday[day]
        entry_t = datetime.combine(day, datetime.min.time()).replace(hour=eh, minute=em)
        before = [b for b in bars if b[0] < entry_t]
        after = [b for b in bars if b[0] >= entry_t]
        if not before or not after:
            continue
        kind = bias_for(days, d, i, p["mode"])
        S0 = before[-1][4]
        K = round(S0 / INDICES[name]["step"]) * INDICES[name]["step"]
        exp = weekly_expiry(name, day, p["min_dte"])
        vol = vix_on(vix, day) / 100.0 * p["ivm"]
        P0 = bs(S0, K, tau_years(entry_t, exp), vol, kind, p["rate"]) + p["slippage"]
        stop_px, tgt_px = P0 * (1 - p["stop"]), P0 * (1 + p["target"])
        exit_px, why, last = None, "close", P0
        for b in after:
            t = b[0] + timedelta(minutes=59)
            tau = tau_years(t, exp)
            worst = bs(b[3] if kind == "CE" else b[2], K, tau, vol, kind, p["rate"])
            best = bs(b[2] if kind == "CE" else b[3], K, tau, vol, kind, p["rate"])
            if worst <= stop_px:                # the stop is checked first when one bar reaches both
                exit_px, why = stop_px, "stop"
                break
            if best >= tgt_px:
                exit_px, why = tgt_px, "target"
                break
            last = bs(b[4], K, tau, vol, kind, p["rate"])
        exit_px = (exit_px if exit_px is not None else last) - p["slippage"]
        lot = lot_size(name, day)
        trades.append({"day": day, "kind": kind, "strike": K, "expiry": exp, "entry": round(P0, 2), "exit": round(exit_px, 2),
                       "why": why, "lot": lot, "premium": round(P0 * lot, 2), "pnl": round((exit_px - P0) * lot - p["charges"], 2)})
    return trades


def summarize(trades):
    p = [t["pnl"] for t in trades]
    if not p:
        return None
    w = [x for x in p if x > 0]
    l = [x for x in p if x <= 0]
    eq = peak = dd = 0.0
    for x in p:
        eq += x
        peak = max(peak, eq)
        dd = min(dd, eq - peak)
    return {"trades": len(p), "pnl": round(sum(p), 2), "win_rate": round(100.0 * len(w) / len(p), 1),
            "profit_factor": round(sum(w) / -sum(l), 2) if l and sum(l) else None, "avg": round(sum(p) / len(p), 2),
            "max_drawdown": round(dd, 2), "avg_premium": round(sum(t["premium"] for t in trades) / len(p), 2)}


def params(cfg, args):
    p = dict(DEFAULTS)
    p.update(cfg.get("strategy") or {})
    for k in ("mode", "entry", "stop", "target", "min_dte", "ivm", "slippage"):
        v = getattr(args, k, None)
        if v is not None:
            p[k] = v
    return p


def cmd_backtest(args, cfg):
    name = args.index.upper()
    p = params(cfg, args)
    hourly = load(INDICES[name]["yahoo"], "60m", args.refresh)
    d = daily(load(INDICES[name]["yahoo"], "1d", args.refresh))
    vix = daily(load(VIX, "1d", args.refresh))
    trades = simulate(name, hourly, d, vix, p)
    if not trades:
        sys.exit("no trades: not enough data")
    print("%s weekly options, %s, entry %s, stop -%d%%, target +%d%%, >= %d days to expiry, IV = VIX x %.2f" % (
        name, "fade the 5-day move" if p["mode"] == "fade" else "follow the 5-day move", p["entry"], p["stop"] * 100,
        p["target"] * 100, p["min_dte"], p["ivm"]))
    print("%s to %s, 1 lot per trade, modelled prices, after %.1f pts slippage each side and Rs %.0f charges per trade" % (
        trades[0]["day"], trades[-1]["day"], p["slippage"], p["charges"]))
    rows = [("all", trades)]
    years = sorted({t["day"].year for t in trades})
    rows += [(str(y), [t for t in trades if t["day"].year == y]) for y in years]
    rows += [("calls", [t for t in trades if t["kind"] == "CE"]), ("puts", [t for t in trades if t["kind"] == "PE"])]
    for label, tr in rows:
        s = summarize(tr)
        if s:
            print("  %-6s %4d trades  P&L %+10.0f  win %4.1f%%  PF %-5s  avg %+7.0f  worst drawdown %+9.0f  avg premium %7.0f" % (
                label, s["trades"], s["pnl"], s["win_rate"], s["profit_factor"], s["avg"], s["max_drawdown"], s["avg_premium"]))
    exits = collections.Counter(t["why"] for t in trades)
    print("  exits: %s" % ", ".join("%s %d" % kv for kv in exits.most_common()))
    if args.json:
        with open(args.json, "w") as f:
            json.dump({"params": p, "trades": trades}, f, indent=1, default=str)
    return trades


def cmd_today(args, cfg):
    """Today's plan from the latest data: direction, strike, expiry, estimated premium, stop, target, lots."""
    name = args.index.upper()
    p = params(cfg, args)
    age = None if args.now else 300          # live: data at most 5 minutes old
    d = daily(load(INDICES[name]["yahoo"], "1d", args.refresh, age))
    vix = daily(load(VIX, "1d", args.refresh, age))
    intraday = load(INDICES[name]["yahoo"], "5m", args.refresh, age)
    now = mmxm.to_local(time.time(), "Asia/Kolkata") if not args.now else datetime.fromisoformat(args.now)
    today = now.date()
    if today.weekday() >= 5:                 # weekend: plan Monday from the last five sessions
        today += timedelta(days=7 - today.weekday())
        now = datetime.combine(today, datetime.min.time()).replace(hour=9)
    days = sorted(x for x in d if x < today) + [today]
    i = len(days) - 1
    if i < 6:
        sys.exit("not enough daily history")
    kind = bias_for(days, d, i, p["mode"])
    prev, five = d[days[i - 1]], d[days[i - 5]]
    eh, em = map(int, p["entry"].split(":"))
    entry_t = datetime.combine(today, datetime.min.time()).replace(hour=eh, minute=em)
    bars = [b for b in intraday if b[0].date() == today and b[0] <= now]
    S0 = bars[-1][4] if bars else prev[4]
    K = round(S0 / INDICES[name]["step"]) * INDICES[name]["step"]
    exp = weekly_expiry(name, today, p["min_dte"])
    vol = vix_on(vix, today) / 100.0 * p["ivm"]
    est = bs(S0, K, tau_years(max(now, entry_t), exp), vol, kind, p["rate"])
    lot = lot_size(name, today)
    print("%s plan for %s (%s)" % (name, today, "fade" if p["mode"] == "fade" else "follow"))
    print("  last 5 sessions: %.2f -> %.2f (%s), so buy %s" % (
        five[4], prev[4], "up" if prev[4] > five[4] else "down", "PUTS" if kind == "PE" else "CALLS"))
    print("  contract: %s %s %d %s  (at the money, expiry %s)" % (
        name, exp.strftime("%d %b").upper(), K, kind, exp.strftime("%a %d %b")))
    print("  entry at %s IST%s" % (p["entry"], "" if now >= entry_t else ": not yet, it is %s" % now.strftime("%H:%M")))
    print("  index now %.2f; model premium about %.1f (check the real price, the model has no skew or spread)" % (S0, est))
    print("  stop at -%d%% (about %.1f), target +%d%% (about %.1f), else exit by the close" % (
        p["stop"] * 100, est * (1 - p["stop"]), p["target"] * 100, est * (1 + p["target"])))
    try:
        mkt = mmxm.Market(mmxm.load_profile(), cfg)
        sz = mmxm.size(mkt, cfg, est, est * (1 - p["stop"]), est * (1 + p["target"]), name, premium=True)
        one_risk = est * p["stop"] * lot
        if sz["qty"] > 0:
            print("  size: %d lot%s of %d (premium about Rs %.0f, loss at the stop about Rs %.0f)" % (
                sz["qty"], "" if sz["qty"] == 1 else "s", lot, sz["premium_cost"], sz["max_loss"]))
        else:
            print("  size: 0 lots within your risk per trade (Rs %.0f). One lot (%d) costs about Rs %.0f and loses about Rs %.0f "
                  "at the stop = %.1f%% of your capital: paper-trade it, or raise risk_pct knowingly." % (
                      sz["rpt"], lot, est * lot, one_risk, 100.0 * one_risk / sz["account"]))
    except SystemExit as e:
        print("  size: %s" % e)
    print("  then: python3 mmxm.py gate --contract \"%s %s %d %s\" --premium <real premium x lot>" % (
        name, exp.strftime("%d %b").upper(), K, kind))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    f = sub.add_parser("fetch")
    f.add_argument("indices", nargs="*", default=["NIFTY", "SENSEX"])
    for name in ("backtest", "today"):
        s = sub.add_parser(name)
        s.add_argument("index", choices=sorted(INDICES), type=str.upper)
        s.add_argument("--mode", choices=["fade", "with"])
        s.add_argument("--entry", help="HH:MM IST, on an hourly bar boundary (09:15, 10:15, ...)")
        s.add_argument("--stop", type=float, help="fraction of premium, e.g. 0.3")
        s.add_argument("--target", type=float, help="fraction of premium, e.g. 0.5")
        s.add_argument("--min-dte", type=int)
        s.add_argument("--ivm", type=float, help="volatility = India VIX x this")
        s.add_argument("--slippage", type=float, help="premium points lost on each fill")
        s.add_argument("--refresh", action="store_true", help="download fresh data first")
        s.add_argument("--json")
        s.add_argument("--now", help=argparse.SUPPRESS)
    a = ap.parse_args(argv)
    if a.cmd == "fetch":
        return cmd_fetch(a)
    cfg = mmxm.load_config(mmxm.load_profile())
    return {"backtest": cmd_backtest, "today": cmd_today}[a.cmd](a, cfg)


if __name__ == "__main__":
    main()
