#!/usr/bin/env python3
"""PulsEdge Telegram bot: renders PULSE signal cards and posts them to the channel.

Reads the same feed the terminal reads (pulsedge/data/feed.json, falling back to
feed.sample.json), so whatever shows in the terminal is what goes to Telegram.

  python pulse_bot.py render [--event ID] [--out DIR]   # write card PNGs, no network
  python pulse_bot.py post   [--event ID] [--dry-run]   # post new BUY/SELL signals to Telegram

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

# card palette, matches terminal.html (PULSE design)
BG, PANEL, LINE = (11, 11, 16), (18, 18, 25), (38, 37, 50)
FG, MUTE, DIM = (236, 235, 243), (142, 138, 158), (95, 92, 109)
PUR, PUR_L, PUR_BOX, PUR_EDGE = (139, 92, 246), (167, 139, 250), (26, 22, 48), (76, 61, 143)
GREEN, GREEN_L, RED, RED_L, AMBER, AMBER_L = (34, 197, 94), (74, 222, 128), (239, 68, 68), (248, 113, 113), (245, 158, 11), (251, 191, 36)
CALL_EDGE = {"buy": GREEN, "sell": RED, "watch": AMBER, "ignore": DIM}
CALL_BADGE = {"buy": ((20, 83, 45), GREEN_L), "sell": ((127, 29, 29), RED_L), "watch": ((120, 53, 15), AMBER_L), "ignore": ((63, 63, 70), MUTE)}
ARROW = {"up": "▲", "down": "▼", "mixed": "◆"}
HZ = {"intraday": "Intraday", "swing": "Swing", "positional": "Positional"}


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


def as_list(v):
    return [str(x) for x in v] if isinstance(v, list) else ([str(v)] if v else [])


def normalize(item):
    """Accepts the terminal's signal format and the older verdict/impacts format."""
    raw = item.get("tickers") or item.get("impacts") or []
    tickers = []
    for m in raw:
        if isinstance(m, str):
            tickers.append({"symbol": m.upper(), "direction": "up"})
        elif isinstance(m, dict) and m.get("symbol"):
            tickers.append({"symbol": str(m["symbol"]).upper(), "direction": "down" if m.get("direction") == "down" else "up"})
    dirs = {t["direction"] for t in tickers}
    direction = item.get("direction") if item.get("direction") in ARROW else ("mixed" if len(dirs) > 1 else (dirs.pop() if dirs else "mixed"))
    call = str(item.get("call", "")).lower()
    if call not in CALL_EDGE:
        v = str(item.get("verdict", "")).lower()
        call = ("sell" if direction == "down" else "buy") if v == "act" else ("ignore" if v == "ignore" else "watch")
    try:
        t = datetime.fromisoformat(str(item.get("time", "")).replace("Z", "+00:00")).astimezone(IST)
    except ValueError:
        t = None
    def score(k):
        v = item.get(k)
        return max(0, min(100, v)) if isinstance(v, (int, float)) else None
    return {
        "id": str(item.get("id") or item.get("headline", "")[:60]),
        "headline": str(item.get("headline", "")),
        "source": str(item.get("source", "")),
        "call": call,
        "horizon": str(item.get("horizon", "")).lower(),
        "direction": direction,
        "tickers": tickers,
        "sectors": as_list(item.get("sectors") or item.get("affected")),
        "impact": score("impact"),
        "confidence": score("confidence"),
        "category": str(item.get("category") or item.get("theme") or ""),
        "action": str(item.get("action", "")),
        "reason": as_list(item.get("reason")),
        "url": item.get("url") if str(item.get("url", "")).startswith(("http://", "https://")) else "",
        "time": t,
    }


def postable(ev):
    return ev["call"] in ("buy", "sell")


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


def flow(draw, items, fnt, x0, width, gap=12):
    """Lay out chips left to right, wrapping; returns [(x, row, text, style)] and row count."""
    out, x, row = [], x0, 0
    for text, style in items:
        w = draw.textlength(text, font=fnt) + 28
        if x + w > x0 + width and x > x0:
            x, row = x0, row + 1
        out.append((x, row, text, style, w))
        x += w + gap
    return out, (row + 1 if items else 0)


def render(ev):
    W, M, P = 1080, 36, 44          # canvas width, outer margin, card padding
    X0, inner = M + P + 8, W - 2 * M - 2 * P - 8
    f_meta, f_meta_b = font(28), font(28, True)
    f_head, f_chip, f_body, f_small = font(44, True), font(28, True), font(30), font(24)
    d0 = ImageDraw.Draw(Image.new("RGB", (W, 10)))

    head = wrap(d0, ev["headline"], f_head, inner)
    chips = [((("▼ " if t["direction"] == "down" else "") + t["symbol"]), "down" if t["direction"] == "down" else "tk") for t in ev["tickers"]]
    chips += [(s, "sec") for s in ev["sectors"]]
    chip_pos, chip_rows = flow(d0, chips, f_chip, X0, inner)
    action = wrap(d0, "→ " + ev["action"], f_body, inner - 40) if ev["action"] else []
    reason = wrap(d0, ev["reason"][0], f_body, inner) if ev["reason"] else []

    H = M + P + 50 + 18 + len(head) * 58 + 16 + chip_rows * 58 + (60 if ev["impact"] is not None or ev["confidence"] is not None else 0)
    H += (len(action) * 42 + 40 + 18) if action else 0
    H += (len(reason) * 42 + 20) if reason else 0
    H += 70 + P + M
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((M, M, W - M, H - M), radius=24, fill=PANEL, outline=LINE, width=2)
    d.rounded_rectangle((M, M, M + 10, H - M), radius=5, fill=CALL_EDGE[ev["call"]])

    # header: time · source · CALL · horizon · direction
    y, x = M + P, X0
    if ev["time"]:
        ts = ev["time"].strftime("%H:%M:%S")
        d.text((x, y), ts, font=f_meta, fill=MUTE)
        x += d.textlength(ts, font=f_meta) + 22
    if ev["source"]:
        w = d.textlength(ev["source"], font=f_meta) + 22
        d.rounded_rectangle((x, y - 4, x + w, y + 38), radius=6, fill=(26, 22, 48), outline=PUR_EDGE, width=2)
        d.text((x + 11, y), ev["source"], font=f_meta, fill=PUR_L)
        x += w + 18
    bg, fg = CALL_BADGE[ev["call"]]
    label = ev["call"].upper()
    w = d.textlength(label, font=f_meta_b) + 22
    d.rounded_rectangle((x, y - 4, x + w, y + 38), radius=6, fill=bg)
    d.text((x + 11, y), label, font=f_meta_b, fill=fg)
    x += w + 18
    tail = " · ".join(filter(None, [HZ.get(ev["horizon"], ev["horizon"].title()), ARROW[ev["direction"]] + " " + ev["direction"].upper()]))
    dir_col = GREEN_L if ev["direction"] == "up" else RED_L if ev["direction"] == "down" else MUTE
    if x + d.textlength(tail, font=f_meta) <= W - M - P:
        d.text((x, y), tail, font=f_meta, fill=dir_col)
    y += 50 + 18

    for line in head:
        d.text((X0, y), line, font=f_head, fill=FG)
        y += 58
    y += 16

    for cx, row, text, style, w in chip_pos:
        cy = y + row * 58
        if style == "sec":
            for dx in range(int(cx), int(cx + w), 12):   # dashed outline
                d.line((dx, cy, min(dx + 6, cx + w), cy), fill=LINE, width=2)
                d.line((dx, cy + 44, min(dx + 6, cx + w), cy + 44), fill=LINE, width=2)
            d.line((cx, cy, cx, cy + 44), fill=LINE, width=2)
            d.line((cx + w, cy, cx + w, cy + 44), fill=LINE, width=2)
            d.text((cx + 14, cy + 6), text, font=font(28), fill=MUTE)
        else:
            edge, col, fill = (RED, RED_L, (45, 20, 24)) if style == "down" else (PUR_EDGE, PUR_L, (26, 22, 48))
            d.rounded_rectangle((cx, cy, cx + w, cy + 44), radius=6, fill=fill, outline=edge, width=2)
            d.text((cx + 14, cy + 6), text, font=f_chip, fill=col)
    y += chip_rows * 58

    if ev["impact"] is not None or ev["confidence"] is not None:
        x = X0
        for name, v in (("Impact", ev["impact"]), ("Conf", ev["confidence"])):
            if v is None:
                continue
            d.text((x, y + 4), name, font=f_meta, fill=MUTE)
            x += d.textlength(name + " ", font=f_meta)
            d.text((x, y + 4), str(round(v)), font=f_meta_b, fill=FG)
            x += d.textlength(str(round(v)) + " ", font=f_meta_b)
            d.rounded_rectangle((x, y + 18, x + 120, y + 28), radius=5, fill=(42, 41, 53))
            d.rounded_rectangle((x, y + 18, x + max(10, int(120 * v / 100)), y + 28), radius=5, fill=PUR)
            x += 150
        if ev["category"] and x + d.textlength(ev["category"], font=f_meta) <= W - M - P:
            d.text((x, y + 4), ev["category"], font=f_meta, fill=MUTE)
        y += 60

    if action:
        box_h = len(action) * 42 + 40
        d.rounded_rectangle((X0, y, W - M - P, y + box_h), radius=14, fill=PUR_BOX, outline=PUR_EDGE, width=2)
        yy = y + 20
        for line in action:
            d.text((X0 + 20, yy), line, font=f_body, fill=FG)
            yy += 42
        y += box_h + 18

    for line in reason:
        d.text((X0, y), line, font=f_body, fill=MUTE)
        y += 42

    y = H - M - P - 30
    d.ellipse((X0, y + 8, X0 + 16, y + 24), fill=PUR)
    d.text((X0 + 28, y), "PULSE", font=font(26, True), fill=FG)
    note = "Not investment advice · t.me/pulsedgein"
    d.text((W - M - P - d.textlength(note, font=f_small), y + 3), note, font=f_small, fill=DIM)
    return img


# ---------- Telegram ----------

def caption(ev):
    head = f"<b>{ev['call'].upper()}</b>"
    if ev["horizon"]:
        head += f" · {HZ.get(ev['horizon'], ev['horizon'].title())}"
    if ev["source"]:
        head += f" · {html.escape(ev['source'])}"
    lines = [head, f"<b>{html.escape(ev['headline'])}</b>", ""]
    if ev["tickers"]:
        lines.append("  ".join(f"{ARROW[t['direction']]} <b>{html.escape(t['symbol'])}</b>" for t in ev["tickers"]))
    meters = [f"{k} {round(v)}" for k, v in (("Impact", ev["impact"]), ("Conf", ev["confidence"])) if v is not None]
    if meters:
        lines.append(" · ".join(meters))
    if ev["action"]:
        lines += ["", f"🎯 {html.escape(ev['action'])}"]
    if ev["url"]:
        lines += ["", f'<a href="{html.escape(ev["url"], quote=True)}">Source</a>']
    lines += ["", "<i>Not investment advice. AI analysis can be wrong — confirm on the chart.</i>"]
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
    todo = [e for e in events if (a.event or postable(e)) and e["id"] not in posted]
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
