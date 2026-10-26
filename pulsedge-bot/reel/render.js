#!/usr/bin/env node
// Render the daily PulsEdge reel (1080x1920 MP4) from pulsedge/data/feed.json and premarket.json.
//
//   node pulsedge-bot/reel/render.js [--out pulsedge-bot/reel/out/reel.mp4] [--fps 30]
//
// Needs ffmpeg with libx264 and playwright (or playwright-core with CHROME_PATH pointing at a Chromium).
// Writes next to the video: a cover image, the timed voice-over script and a ready-to-paste caption.
const fs = require("fs");
const path = require("path");
const { spawn } = require("child_process");
let pw;
try { pw = require("playwright"); } catch (e) { pw = require("playwright-core"); }

const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? a.concat([[v.slice(2), all[i + 1]]]) : a), []));
const HERE = __dirname;
const DATA = path.join(HERE, "..", "..", "pulsedge", "data");
const OUT = path.resolve(args.out || path.join(HERE, "out", "reel.mp4"));
const FPS = +(args.fps || 30);

function load(f) { try { return JSON.parse(fs.readFileSync(path.join(DATA, f), "utf8")); } catch (e) { return null; } }

function spokenList(names) {
  if (names.length <= 1) return names.join("");
  return names.slice(0, -1).join(", ") + " and " + names[names.length - 1];
}
function company(headline) {
  const m = String(headline || "").match(/^(.+?)(?: Limited| Ltd\.?)?:/);
  return m ? m[1].trim() : "";
}

async function main() {
  const feed = load("feed.json") || load("feed.sample.json");
  const pm = load("premarket.json") || load("premarket.sample.json");
  if (!feed || !feed.digest) throw new Error("feed.json has no digest yet; run the news pipeline first");
  const items = (feed.items || []).filter((x) => x && x.headline).sort((a, b) => (Date.parse(b.time) || 0) - (Date.parse(a.time) || 0));
  const day = feed.digest.date || new Date().toISOString().slice(0, 10);
  const dateLabel = new Date(day + "T12:00:00+05:30").toLocaleDateString("en-IN", { weekday: "short", day: "numeric", month: "short", timeZone: "Asia/Kolkata" }).toUpperCase();

  const chrome = process.env.CHROME_PATH;
  const browser = await pw.chromium.launch(chrome ? { executablePath: chrome, headless: false, args: ["--headless=new"] } : {});
  const page = await browser.newPage({ viewport: { width: 1080, height: 1920 }, deviceScaleFactor: 1 });
  await page.goto("file://" + path.join(HERE, "reel.html"));
  const sum = await page.evaluate((d) => init(d), { digest: feed.digest, items, premarket: pm, dateLabel });
  await page.evaluate(() => document.fonts.ready);
  await page.waitForFunction(() => Array.from(document.images).every((i) => i.complete));
  const duration = await page.evaluate(() => REEL.duration);

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const ff = spawn("ffmpeg", ["-y", "-loglevel", "error", "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "mjpeg", "-i", "-",
    "-c:v", "libx264", "-preset", "medium", "-crf", "18", "-pix_fmt", "yuv420p", "-r", String(FPS), "-movflags", "+faststart", OUT], { stdio: ["pipe", "inherit", "inherit"] });
  const done = new Promise((res, rej) => ff.on("close", (c) => (c === 0 ? res() : rej(new Error("ffmpeg exited " + c)))));
  const frames = Math.round(duration * FPS);
  for (let i = 0; i < frames; i++) {
    await page.evaluate((t) => render(t), i / FPS);
    const buf = await page.screenshot({ type: "jpeg", quality: 92 });
    if (!ff.stdin.write(buf)) await new Promise((r) => ff.stdin.once("drain", r));
    if (i % 90 === 0) process.stderr.write(`frame ${i}/${frames}\n`);
  }
  ff.stdin.end();
  await done;

  // cover: the hook with its number fully counted
  await page.evaluate(() => render(2.3));
  const cover = OUT.replace(/\.mp4$/, "-cover.jpg");
  await page.screenshot({ path: cover, type: "jpeg", quality: 92 });
  await browser.close();

  const names = items.filter((x) => sum.picked.includes(((x.tickers || [])[0] || {}).symbol)).map((x) => company(x.headline) || ((x.tickers || [])[0] || {}).symbol);
  const uniq = [...new Set(names)].slice(0, 3);
  const n = (v) => Number(v).toLocaleString("en-IN");
  const vo = [
    `[0:00] ${n(sum.read)} market headlines hit Indian markets today. Only ${n(sum.worth)} were worth a look.`,
    `[0:03] PulsEdge read every single one.`,
    `[0:05] Sorted in seconds: ${n(sum.ignored)} set aside, ${n(sum.worth - sum.act)} to watch${sum.act ? ", " + n(sum.act) + " to act on" : ""}.`,
    `[0:09] Most were routine filings. And every one keeps its reason.`,
    `[0:12] These made the cut${uniq.length ? ": " + spokenList(uniq) : ""}.`,
    `[0:16] And the market setup? ${sum.sentiment}.`,
    `[0:20] PulsEdge. Market news, triaged for the stocks you own. Try it free. Link in bio.`,
  ].join("\n");
  const caption = [
    `${n(sum.read)} headlines today. ${n(sum.worth)} worth a look. Here's what PulsEdge flagged 👇`,
    ``,
    uniq.length ? `On the watchlist today: ${uniq.join(", ")}.` : ``,
    `Market setup: ${sum.sentiment}.`,
    ``,
    `Try the full terminal free for 5 trading sessions. Link in bio.`,
    ``,
    `Educational information only. Not investment advice. Do your own research.`,
    ``,
    `#stockmarketindia #nifty50 #sharemarket #nse #investing #stockmarketnews #trading #fintech`,
  ].filter((l, i, a) => !(l === "" && a[i - 1] === "")).join("\n");
  fs.writeFileSync(OUT.replace(/\.mp4$/, "-voiceover.txt"), vo + "\n");
  fs.writeFileSync(OUT.replace(/\.mp4$/, "-caption.txt"), caption + "\n");
  console.log(JSON.stringify({ video: OUT, cover, frames, seconds: duration, summary: sum }, null, 1));
}
main().catch((e) => { console.error(e.message); process.exit(1); });
