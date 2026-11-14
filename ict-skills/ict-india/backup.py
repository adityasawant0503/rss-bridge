#!/usr/bin/env python3
"""Back up the state that can't be rebuilt to Aditya's private repo, and restore it on a fresh machine.

The paper journal, the research logs, the config and the intraday candle archive live in the git-ignored
ict/ folder (they're personal or can't be downloaded again: Yahoo keeps 5m bars for 60 days only). This
mirrors them into a clone of the private repo adityasawant0503/ict-research and pushes.

Never backed up: ict/dhan-2025/ and ict/pdf/ (built from the 2025 statements, which stay out of every repo),
and the re-downloadable Yahoo caches in ict/market/.

  python3 backup.py push        # copy the files in, commit if anything changed, push
  python3 backup.py restore     # copy them back into ict/ (only files that are missing there)
"""
import argparse
import os
import shutil
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import mmxm  # noqa: E402

REPO = "https://github.com/adityasawant0503/ict-research"
CLONE = "/home/user/ict-research"
ITEMS = ["journal.jsonl", "config-india.json", "research", os.path.join("market", "archive")]
README = """# ict-research (private)

Backup of the paper-trading and research state from `ict/` in the rss-bridge ICT skills
(`ict-skills/ict-india/backup.py`). Written automatically after the 10:05 IST weekday task.

| Path | What |
|---|---|
| `journal.jsonl` | paper (and the few real) trades, one per line, from `mmxm.py journal` |
| `config-india.json` | personal rules and the Morning Fade settings |
| `research/` | sweep-and-reclaim forward test, PulsEdge pre-market log |
| `market/archive/` | every 5m and 1m bar kept since Aug 2026 (Yahoo only serves 60 / 7 days) |

Restore on a fresh machine: `python3 ict-skills/ict-india/backup.py restore` in the rss-bridge checkout.
Keep this repository private.
"""


def git(*args, check=True):
    return subprocess.run(["git", "-C", CLONE] + list(args), check=check, capture_output=True, text=True)


def ensure_clone():
    if not os.path.isdir(os.path.join(CLONE, ".git")):
        subprocess.run(["git", "clone", "-q", "--depth", "1", REPO, CLONE], check=True)
    git("config", "user.name", "Claude")
    git("config", "user.email", "noreply@anthropic.com")
    if git("rev-parse", "-q", "--verify", "HEAD", check=False).returncode:      # empty repo: start on main
        git("symbolic-ref", "HEAD", "refs/heads/main")


def copy(src, dst, only_missing=False):
    if os.path.isdir(src):
        for root, _, files in os.walk(src):
            for name in files:
                s = os.path.join(root, name)
                copy(s, os.path.join(dst, os.path.relpath(s, src)), only_missing)
    elif os.path.exists(src) and not (only_missing and os.path.exists(dst)):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)


def cmd_push():
    ensure_clone()
    for item in ITEMS:
        copy(os.path.join(mmxm.STATE_DIR, item), os.path.join(CLONE, item))
    with open(os.path.join(CLONE, "README.md"), "w") as f:
        f.write(README)
    git("add", "-A")
    if not git("status", "--porcelain").stdout.strip():
        print("backup: nothing changed")
        return
    stamp = time.strftime("%Y-%m-%d %H:%M", time.gmtime(time.time() + 19800)) + " IST"
    git("commit", "-q", "-m", "Backup %s\n\nCo-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>" % stamp)
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    r = git("-c", "push.negotiate=true", "push", "-q", "-u", "origin", branch, check=False)
    if r.returncode:
        sys.exit("backup: push failed: %s" % r.stderr.strip()[-300:])
    print("backup: pushed %s (%s)" % (git("rev-parse", "--short", "HEAD").stdout.strip(), stamp))


def cmd_restore():
    ensure_clone()
    for item in ITEMS:
        copy(os.path.join(CLONE, item), os.path.join(mmxm.STATE_DIR, item), only_missing=True)
    print("restore: copied missing files into %s" % os.path.abspath(mmxm.STATE_DIR))


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["push", "restore"])
    a = ap.parse_args(argv)
    cmd_push() if a.cmd == "push" else cmd_restore()


if __name__ == "__main__":
    main()
