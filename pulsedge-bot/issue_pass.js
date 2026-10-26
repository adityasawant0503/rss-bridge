#!/usr/bin/env node
// Issue a signed PulsEdge access link (the same links PulsEdge HQ makes).
//
//   PULSEDGE_SIGNING_KEY="$(cat key.json)" node pulsedge-bot/issue_pass.js --email a@b.com --plan trial14 [--start 2026-10-26]
//   node pulsedge-bot/issue_pass.js --key key.json --email a@b.com --plan monthly --until 2026-11-26
//
// Plans: trial7 (5 sessions), trial14 (10 sessions), monthly, yearly, founding, comp (until a date).
// The key is the private JWK whose public half is in pulsedge/assets/member.js. Never commit it.
const fs = require("fs");
const args = Object.fromEntries(process.argv.slice(2).reduce((a, v, i, all) => (v.startsWith("--") ? a.concat([[v.slice(2), all[i + 1]]]) : a), []));
const SITE = args.site || "https://adityasawant0503.github.io/rss-bridge/";
const PLANS = { trial7: 5, trial14: 10, monthly: 0, yearly: 0, founding: 0, comp: 0 };

function b64u(buf) { return Buffer.from(buf).toString("base64").replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, ""); }
function ist() { return new Date(Date.now() + 330 * 60000).toISOString().slice(0, 10); }

async function main() {
  const jwk = JSON.parse(args.key ? fs.readFileSync(args.key, "utf8") : process.env.PULSEDGE_SIGNING_KEY || "null");
  if (!jwk || !jwk.d) throw new Error("no signing key: pass --key file.json or set PULSEDGE_SIGNING_KEY");
  if (!(args.plan in PLANS)) throw new Error("--plan must be one of " + Object.keys(PLANS).join(", "));
  const p = { v: 1, k: args.kid || "ops1", i: b64u(require("crypto").randomBytes(6)), e: (args.email || "").toLowerCase(), p: args.plan, t: ist() };
  if (PLANS[args.plan]) { p.s = args.start || ist(); p.n = +(args.sessions || PLANS[args.plan]); }
  else if (args.until) p.x = args.until;
  else throw new Error("--until YYYY-MM-DD is needed for " + args.plan);
  const key = await crypto.subtle.importKey("jwk", { ...jwk, ext: true }, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const body = b64u(JSON.stringify(p));
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, new TextEncoder().encode(body));
  console.log(JSON.stringify({ id: p.i, payload: p, link: SITE + "terminal.html#pass=" + body + "." + b64u(sig) }, null, 1));
}
main().catch((e) => { console.error(e.message); process.exit(1); });
