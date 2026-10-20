#!/usr/bin/env python3
"""PulsEdge Telegram bot: renders news-impact cards and posts them to the channel.

Reads the same feed the terminal reads (pulsedge/data/feed.json, falling back to
feed.sample.json), so whatever shows in the terminal is what goes to Telegram.

  python pulse_bot.py render [--event ID] [--out DIR]   # write card PNGs, no network
  python pulse_bot.py post   [--event ID] [--dry-run]   # post new ACT events to Telegram

Posting needs TELEGRAM_BOT_TOKEN, and TELEGRAM_CHAT_ID (defaults to @pulsedgein).
Events already posted are recorded in posted.json so nothing is sent twice.
"""
import argparse
import html
import io
import json
import os
import sys
import urllib.request
import uuid
from datetime import datetime, timedelta, timezone

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "pulsedge", "data")
POSTED = os.path.join(HERE, "posted.json")
IST = timezone(timedelta(hours=5, minutes=30))

# card palette, matches terminal.html
BG, PANEL, LINE = (0, 0, 0), (13, 13, 17), (34, 34, 34)
FG, MUTE, DIM = (255, 255, 255), (170, 170, 178), (119, 119, 119)
AMBER, UP, DOWN, MIX = (255, 197, 51), (51, 209, 122), (255, 95, 87), (185, 164, 255)
DIR_COL = {"up": UP, "down": DOWN, "mixed": MIX}
ARROW = {"up": "▲", "down": "▼", "mixed": "◆"}
WORD = {"up": "positive", "down": "negative", "mixed": "mixed"}
STR = {1: "Mild", 2: "Moderate", 3: "Strong"}
VORD = {"act": 3, "watch": 2, "ignore": 1}


def font(size, bold=False):
    name = "JetBrainsMono-Bold.ttf" if bold else "JetBrainsMono-Regular.ttf"
    return ImageFont.truetype(os.path.join(HERE, "fonts", name), size)


# ---------- data ----------

def load_feed():
    for name in ("feed.json", "feed.sample.json"):
        path = os.path.join(DATA, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                return json.load(fh), name
    sys.exit("No feed file found in pulsedge/data/")


def normalize(item):
    impacts = item.get("impacts") or [
        {"symbol": s, "direction": "mixed", "strength": 1, "verdict": item.get("verdict", "watch")}
        for s in item.get("tickers", [])
    ]
    out = []
    for m in impacts:
        d = m.get("direction") if m.get("direction") in ARROW else "mixed"
        v = str(m.get("verdict", "watch")).lower()
        out.append({
            "symbol": str(m.get("symbol", "")).upper(),
            "dir": d,
            "str": max(1, min(3, int(m.get("strength") or 1))),
            "verdict": v if v in VORD else "watch",
        })
    out = [m for m in out if m["symbol"]]
    out.sort(key=lambda m: (-VORD[m["verdict"]], -m["str"]))
    verdict = str(item.get("verdict", "")).lower()
    if verdict not in VORD:
        verdict = max((m["verdict"] for m in out), key=VORD.get, default="ignore")
    try:
        t = datetime.fromisoformat(str(item.get("time", "")).replace("Z", "+00:00")).astimezone(IST)
    except ValueError:
        t = None
    return {
        "id": str(item.get("id") or item.get("headline", "")[:60]),
        "headline": str(item.get("headline", "")),
        "theme": str(item.get("theme") or item.get("category") or item.get("section") or ""),
        "reason": str(item.get("reason", "")),
        "url": item.get("url") if str(item.get("url", "")).startswith(("http://", "https://")) else "",
        "time": t,
        "verdict": verdict,
        "impacts": out,
    }


def card_impacts(ev):
    keep = [m for m in ev["impacts"] if m["verdict"] != "ignore"] or ev["impacts"]
    return keep[:6]


def stamp(ev):
    return ev["time"].strftime("%d %b · %H:%M IST").upper() if ev["time"] else ""


# ---------- card image ----------

def wrap(draw, text, fnt, width):
    lines, line = [], ""
    for word in text.split():
        trial = (line + " " + word).strip()
        if draw.textlength(trial, font=fnt) <= width:
            line = trial
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def render(ev):
    W, P = 1080, 64
    inner = W - 2 * P
    f_small, f_small_b = font(26), font(26, True)
    f_head, f_body, f_row, f_row_b = font(46, True), font(30), font(32), font(32, True)
    scratch = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    head = wrap(scratch, ev["headline"], f_head, inner)
    why = wrap(scratch, "Why: " + ev["reason"], f_body, inner) if ev["reason"] else []
    rows = card_impacts(ev)
    H = P + 40 + 36 + 56 + len(head) * 60 + 30 + 56 + len(rows) * 52 + 24 + (len(why) * 42 + 40 if why else 0) + 90 + P
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)

    y = P
    d.text((P, y), "PULSEDGE · MARKET PULSE", font=f_small_b, fill=AMBER)
    ts = stamp(ev)
    d.text((W - P - d.textlength(ts, font=f_small), y), ts, font=f_small, fill=MUTE)
    y += 40 + 36

    tag = (ev["theme"] or "news").upper()
    tw = d.textlength(tag, font=f_small_b)
    d.rounded_rectangle((P, y - 6, P + tw + 28, y + 36), radius=6, fill=AMBER)
    d.text((P + 14, y - 2), tag, font=f_small_b, fill=BG)
    y += 56

    for line in head:
        d.text((P, y), line, font=f_head, fill=FG)
        y += 60
    y += 30

    d.line((P, y, W - P, y), fill=LINE, width=2)
    y += 22
    d.text((P, y), "IMPACT ON NIFTY 500", font=f_small_b, fill=AMBER)
    y += 50

    for m in rows:
        col = DIR_COL[m["dir"]]
        d.text((P, y), ARROW[m["dir"]], font=f_row, fill=col)
        d.text((P + 44, y), m["symbol"], font=f_row_b, fill=FG)
        d.text((P + 300, y), f"{STR[m['str']]} {WORD[m['dir']]}", font=f_row, fill=col)
        label = m["verdict"].upper()
        lw = d.textlength(label, font=f_small_b)
        x1 = W - P
        if m["verdict"] == "act":
            d.rounded_rectangle((x1 - lw - 24, y + 2, x1, y + 38), radius=5, fill=AMBER)
            d.text((x1 - lw - 12, y + 5), label, font=f_small_b, fill=BG)
        else:
            d.rounded_rectangle((x1 - lw - 24, y + 2, x1, y + 38), radius=5, outline=AMBER if m["verdict"] == "watch" else LINE, width=2)
            d.text((x1 - lw - 12, y + 5), label, font=f_small_b, fill=AMBER if m["verdict"] == "watch" else DIM)
        y += 52
    y += 24

    if why:
        d.line((P, y, W - P, y), fill=LINE, width=2)
        y += 24
        for line in why:
            d.text((P, y), line, font=f_body, fill=(221, 221, 221))
            y += 42
        y += 16

    y = H - P - 30
    d.text((P, y), "Educational only. Not investment advice.", font=f_small, fill=DIM)
    link = "t.me/pulsedgein"
    d.text((W - P - d.textlength(link, font=f_small_b), y), link, font=f_small_b, fill=AMBER)
    return img


# ---------- Telegram ----------

def caption(ev):
    lines = [f"<b>{html.escape(ev['headline'])}</b>", ""]
    for m in card_impacts(ev):
        lines.append(f"{ARROW[m['dir']]} <b>{html.escape(m['symbol'])}</b> {STR[m['str']].lower()} {WORD[m['dir']]} · {m['verdict'].upper()}")
    if ev["reason"]:
        lines += ["", f"<i>Why:</i> {html.escape(ev['reason'])}"]
    if ev["url"]:
        lines += ["", f'<a href="{html.escape(ev["url"], quote=True)}">Source</a>']
    lines += ["", "Educational only. Not investment advice."]
    text = "\n".join(lines)
    return text if len(text) <= 1024 else text[:1000].rsplit("\n", 1)[0] + "\n…"


def send_photo(token, chat_id, png, text):
    boundary = uuid.uuid4().hex
    parts = []
    for k, v in (("chat_id", chat_id), ("caption", text), ("parse_mode", "HTML")):
        parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode())
    parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="photo"; filename="pulse.png"\r\nContent-Type: image/png\r\n\r\n'.encode() + png + b"\r\n")
    parts.append(f"--{boundary}--\r\n".encode())
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendPhoto",
        data=b"".join(parts),
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        body = json.load(r)
    if not body.get("ok"):
        raise RuntimeError(body.get("description", "Telegram rejected the post"))


def png_bytes(img):
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=True)
    return buf.getvalue()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["render", "post"])
    ap.add_argument("--event", help="only this event id")
    ap.add_argument("--out", default=os.path.join(HERE, "out"), help="render: output folder")
    ap.add_argument("--dry-run", action="store_true", help="post: show what would be sent")
    a = ap.parse_args()

    feed, source = load_feed()
    events = [normalize(x) for x in feed.get("items", []) if x.get("headline")]
    if a.event:
        events = [e for e in events if e["id"] == a.event]
        if not events:
            sys.exit(f"No event with id {a.event} in {source}")

    if a.cmd == "render":
        os.makedirs(a.out, exist_ok=True)
        for ev in events:
            path = os.path.join(a.out, f"{ev['id']}.png")
            render(ev).save(path, optimize=True)
            print("wrote", path)
        return

    if source != "feed.json" and not a.event and not a.dry_run:
        print("Only sample data is present (feed.sample.json); not posting it to the channel.")
        return
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat = os.environ.get("TELEGRAM_CHAT_ID") or "@pulsedgein"
    if not token and not a.dry_run:
        print("TELEGRAM_BOT_TOKEN isn't set; skipping. Add it as a repository secret to turn posting on.")
        return
    posted = json.load(open(POSTED)) if os.path.exists(POSTED) else []
    todo = [e for e in events if (a.event or e["verdict"] == "act") and e["id"] not in posted]
    todo.sort(key=lambda e: e["time"] or datetime.min.replace(tzinfo=IST))
    if not todo:
        print("Nothing new to post.")
        return
    for ev in todo:
        if a.dry_run:
            print(f"--- would post {ev['id']} to {chat}\n{caption(ev)}\n")
            continue
        send_photo(token, chat, png_bytes(render(ev)), caption(ev))
        posted.append(ev["id"])
        print("posted", ev["id"])
    if not a.dry_run:
        with open(POSTED, "w") as fh:
            json.dump(posted[-2000:], fh, indent=1)


if __name__ == "__main__":
    main()
