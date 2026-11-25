#!/usr/bin/env python3
"""PulsEdge pre-market reading next to the Morning Fade's direction, kept for research.

PulsEdge (Aditya's terminal, repo adityasawant0503/pulsedge) publishes a pre-market panel in
pulsedge/data/premarket.json: a sentiment ("Mildly bearish", ...) and a 6-point checklist whose items point
up, down or flat. This reads it, says whether it agrees with the day's fade (puts after a 5-day rise, calls
after a fall), and logs one row per day so we can later test whether agreement days are the better days.
It never changes the plan.

  python3 pulse.py show --refresh     # fetch the latest PulsEdge data and print today's reading
  python3 pulse.py log --refresh      # the same, and append today's row to ict/research/premarket-log.jsonl
"""
import argparse
import json
import os
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm    # noqa: E402
import optbt   # noqa: E402

REPO = "https://github.com/adityasawant0503/pulsedge"
CLONE = "/home/user/adityasawant0503/pulsedge"
LOG = os.path.join(mmxm.STATE_DIR, "research", "premarket-log.jsonl")


def refresh(path):
    """Shallow clone of the public PulsEdge repo, or bring an existing one up to date. Read-only use."""
    if os.path.isdir(os.path.join(path, ".git")):
        subprocess.run(["git", "-C", path, "fetch", "-q", "--depth", "1", "origin", "master"], check=True)
        subprocess.run(["git", "-C", path, "reset", "-q", "--hard", "origin/master"], check=True)
    else:
        env = dict(os.environ, GIT_LFS_SKIP_SMUDGE="1")
        subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, path], check=True, env=env)


def lean(sentiment):
    s = (sentiment or "").lower()
    return "bear" if "bear" in s else "bull" if "bull" in s else "neutral"


def reading(pm, fade_side):
    cl = pm.get("checklist") or []
    dirs = [c.get("dir", "flat") for c in cl]
    ln = lean(pm.get("sentiment"))
    agree = None if ln == "neutral" else (ln == "bear") == (fade_side == "PE")
    return {"pm_date": pm.get("date"), "pm_updated": pm.get("updated"), "sentiment": pm.get("sentiment"),
            "lean": ln, "up": dirs.count("up"), "down": dirs.count("down"), "flat": len(dirs) - dirs.count("up") - dirs.count("down"),
            "checklist": [[c.get("title", "")[:40], c.get("dir", "flat")] for c in cl], "fade_side": fade_side, "agree": agree}


def fade_side_today(today):
    d = optbt.daily(optbt.load("^BSESN", "1d", max_age=3600))
    days = sorted(x for x in d if x < today) + [today]
    return optbt.bias_for(days, d, len(days) - 1, "fade")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["show", "log"])
    ap.add_argument("--path", default=CLONE, help="PulsEdge checkout (default %(default)s)")
    ap.add_argument("--refresh", action="store_true", help="fetch the latest PulsEdge data first")
    a = ap.parse_args(argv)
    if a.refresh:
        refresh(a.path)
    with open(os.path.join(a.path, "pulsedge", "data", "premarket.json")) as f:
        pm = json.load(f)
    today = mmxm.to_local(time.time(), "Asia/Kolkata").date()
    r = reading(pm, fade_side_today(today))
    r["day"] = str(today)
    stale = r["pm_date"] != str(today)
    print("PulsEdge %s: %s (%d up, %d down, %d flat)%s | fade says %s | %s" % (
        r["pm_date"], r["sentiment"], r["up"], r["down"], r["flat"], "  [NOT TODAY'S]" if stale else "",
        "PUTS" if r["fade_side"] == "PE" else "CALLS",
        "agrees" if r["agree"] else "neutral" if r["agree"] is None else "disagrees"))
    if a.cmd == "log" and not stale:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        rows = []
        if os.path.exists(LOG):
            with open(LOG) as f:
                rows = [json.loads(x) for x in f if x.strip()]
        if any(x["day"] == r["day"] for x in rows):
            print("already logged today")
        else:
            with open(LOG, "a") as f:
                f.write(json.dumps(r) + "\n")
            print("logged -> %s" % LOG)


if __name__ == "__main__":
    main()
