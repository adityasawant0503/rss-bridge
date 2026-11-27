// Tests for PulsEdge Trade's paper-trading engine and demo feed. Run: node pulsedge-bot/test_trade.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { Engine } = require("../pulsedge/assets/trade/engine.js");
const { DemoFeed, nextTuesdays } = require("../pulsedge/assets/trade/feed.js");
const QL = require("../pulsedge/assets/trade/quant.js");
const IDEAS = require("../pulsedge/assets/trade/ideas.js");

let fails = 0, n = 0;
const ok = (name, cond, detail = "") => { n++; if (!cond) fails++; console.log(`${cond ? "ok  " : "FAIL"} ${name}${cond ? "" : "  " + detail}`); };
const near = (a, b, tol = 1e-6) => Math.abs(a - b) <= tol;

function setup(capital = 1000000) {
  const e = new Engine({ capital });
  e.register({ key: "NSE:TCS", sym: "TCS", name: "TCS", kind: "equity", lot: 1 });
  e.register({ key: "NSE:NIFTY", sym: "NIFTY", name: "Nifty 50", kind: "index", lot: 1 });
  e.register({ key: "NFO:NIFTY FUT", sym: "NIFTY FUT", kind: "future", lot: 65, underlyingKey: "NSE:NIFTY" });
  e.register({ key: "NFO:NIFTY 20260106 24000 CE", sym: "NIFTY 24000 CE", kind: "option", lot: 65, strike: 24000, type: "CE", underlyingKey: "NSE:NIFTY" });
  return e;
}

// ---- market order, charges, round trip P&L
{
  const e = setup(); e.quote("NSE:TCS", 4000, 1);
  const o = e.place({ key: "NSE:TCS", side: "BUY", qty: 10, type: "MARKET", product: "MIS", time: 1 });
  ok("market order fills at last price", o.status === "COMPLETE" && o.avg === 4000);
  const expCh = QL.orderCharges("equity_intraday", "buy", 40000, 20).total;
  ok("buy charges = NSE intraday schedule", near(o.charges, expCh), `${o.charges} vs ${expCh}`);
  e.quote("NSE:TCS", 4050, 2);
  ok("unrealised P&L marks to market", near(e.funds().unrealised, 500));
  e.squareOff("NSE:TCS|MIS", 3);
  const f = e.funds();
  ok("square-off books realised P&L", near(f.realised, 500) && near(f.unrealised, 0));
  ok("equity = capital + P&L - charges", near(f.equity, 1000000 + 500 - f.charges));
  ok("position flat after square-off", e.state.positions["NSE:TCS|MIS"].qty === 0);
}
// ---- limit orders wait, then fill at the limit or better
{
  const e = setup(); e.quote("NSE:TCS", 4000);
  const o = e.place({ key: "NSE:TCS", side: "BUY", qty: 5, type: "LIMIT", price: 3990, product: "MIS" });
  ok("buy limit below market stays open", o.status === "OPEN");
  e.quote("NSE:TCS", 3995); ok("not filled above the limit", o.status === "OPEN");
  e.quote("NSE:TCS", 3985); ok("fills when price trades through, at the better price", o.status === "COMPLETE" && o.avg === 3985);
}
// ---- stop-loss market triggers
{
  const e = setup(); e.quote("NSE:TCS", 4000);
  e.place({ key: "NSE:TCS", side: "BUY", qty: 5, type: "MARKET", product: "MIS" });
  const sl = e.place({ key: "NSE:TCS", side: "SELL", qty: 5, type: "SL-M", trigger: 3950, product: "MIS" });
  ok("stop waits for its trigger", sl.status === "TRIGGER_PENDING");
  e.quote("NSE:TCS", 3960); ok("not triggered above the stop", sl.status === "TRIGGER_PENDING");
  e.quote("NSE:TCS", 3948); ok("triggers and fills at market", sl.status === "COMPLETE" && sl.avg === 3948);
}
// ---- bracket: target fill cancels the stop
{
  const e = setup(); e.quote("NSE:TCS", 4000);
  e.place({ key: "NSE:TCS", side: "BUY", qty: 4, type: "MARKET", product: "MIS", sl: 3960, target: 4080 });
  const legs = e.state.orders.filter((o) => o.oco);
  ok("bracket creates stop and target", legs.length === 2);
  e.quote("NSE:TCS", 4085);
  const tgt = legs.find((o) => o.type === "LIMIT"), stop = legs.find((o) => o.type !== "LIMIT");
  ok("target fills", tgt.status === "COMPLETE");
  ok("stop is cancelled when target fills", stop.status === "CANCELLED");
  ok("position closed with profit", e.state.positions["NSE:TCS|MIS"].qty === 0 && e.funds().realised > 0);
}
// ---- position maths: adding, partial close, flipping
{
  const e = setup(); e.quote("NSE:TCS", 100);
  e.place({ key: "NSE:TCS", side: "BUY", qty: 10, type: "MARKET", product: "MIS" });
  e.quote("NSE:TCS", 110);
  e.place({ key: "NSE:TCS", side: "BUY", qty: 10, type: "MARKET", product: "MIS" });
  const p = e.state.positions["NSE:TCS|MIS"];
  ok("average price after adding", near(p.avg, 105) && p.qty === 20);
  e.place({ key: "NSE:TCS", side: "SELL", qty: 30, type: "MARKET", product: "MIS" });
  ok("flip books P&L on the closed part", near(p.realised, 20 * (110 - 105)));
  ok("flip leaves a short at the fill price", p.qty === -10 && near(p.avg, 110));
}
// ---- rejections
{
  const e = setup(10000); e.quote("NSE:TCS", 4000); e.quote("NFO:NIFTY FUT", 24000); e.quote("NSE:NIFTY", 24000);
  ok("lot size enforced", e.place({ key: "NFO:NIFTY FUT", side: "BUY", qty: 50, type: "MARKET" }).status === "REJECTED");
  ok("insufficient funds rejected", /Not enough funds/.test(e.place({ key: "NFO:NIFTY FUT", side: "BUY", qty: 65, type: "MARKET" }).reason));
  ok("index itself not tradable", e.place({ key: "NSE:NIFTY", side: "BUY", qty: 1, type: "MARKET" }).status === "REJECTED");
  ok("CNC short rejected", /intraday/.test(e.place({ key: "NSE:TCS", side: "SELL", qty: 1, type: "MARKET", product: "CNC" }).reason));
  ok("limit without price rejected", e.place({ key: "NSE:TCS", side: "BUY", qty: 1, type: "LIMIT" }).status === "REJECTED");
}
// ---- option sell uses options STT; state survives a save/load round trip
{
  const e = setup(); e.quote("NSE:NIFTY", 24000); e.quote("NFO:NIFTY 20260106 24000 CE", 200);
  const o = e.place({ key: "NFO:NIFTY 20260106 24000 CE", side: "SELL", qty: 65, type: "MARKET", product: "NRML" });
  ok("option sell fills", o.status === "COMPLETE");
  ok("option sell pays 0.15% STT on premium", near(e.state.trades[0].breakdown.stt, 0.0015 * 200 * 65));
  ok("short option margin uses the underlying", near(e.usedMargin(), 65 * 24000 * 0.12));
  const e2 = setup(); e2.load(JSON.parse(JSON.stringify(e.toJSON())));
  ok("save/load keeps positions and funds", near(e2.funds().equity, e.funds().equity) && e2.state.positions["NFO:NIFTY 20260106 24000 CE|NRML"].qty === -65);
}
// ---- risk-based option margin: an iron condor needs about its max loss, a naked short much more
{
  const e = new Engine({ capital: 1000000 });
  e.register({ key: "NSE:NIFTY", sym: "NIFTY", name: "Nifty 50", kind: "index", lot: 1 });
  e.quote("NSE:NIFTY", 26000);
  const opt = (k, t, p) => { const key = `NFO:NIFTY 20261201 ${k} ${t}`; e.register({ key, sym: key, kind: "option", lot: 65, strike: k, type: t, expiry: "2026-12-01", underlyingKey: "NSE:NIFTY" }); e.quote(key, p); return key; };
  const sc = opt(26200, "CE", 60), lc = opt(26400, "CE", 20), sp = opt(25800, "PE", 70), lp = opt(25600, "PE", 25);
  for (const [k, side] of [[lc, "BUY"], [lp, "BUY"], [sc, "SELL"], [sp, "SELL"]]) e.place({ key: k, side, qty: 65, type: "MARKET", product: "NRML" });
  const credit = (60 - 20 + 70 - 25) * 65, maxLoss = 200 * 65 - credit;
  ok("all four condor legs fill", Object.values(e.state.positions).filter((p) => p.qty).length === 4);
  ok("condor margin ~ max loss + premium paid", Math.abs(e.usedMargin() - (maxLoss + (20 + 25) * 65)) < 1, `${e.usedMargin()} vs ${maxLoss + 45 * 65}`);
  const n = new Engine({ capital: 1000000 }); n.register({ key: "NSE:NIFTY", sym: "NIFTY", name: "Nifty", kind: "index", lot: 1 }); n.quote("NSE:NIFTY", 26000);
  n.register({ key: sc, sym: sc, kind: "option", lot: 65, strike: 26200, type: "CE", expiry: "2026-12-01", underlyingKey: "NSE:NIFTY" }); n.quote(sc, 60);
  n.place({ key: sc, side: "SELL", qty: 65, type: "MARKET", product: "NRML" });
  ok("naked short call keeps the full short-option margin", Math.abs(n.usedMargin() - 65 * 26000 * 0.12) < 1);
}
// ---- demo feed
{
  const base = { NIFTY: { close: 26000, vol: 0.12 }, INDIAVIX: { close: 11, vol: 0.6 }, TCS: { close: 4000, vol: 0.22 } };
  const syms = [{ sym: "NIFTY", name: "Nifty 50", kind: "index" }, { sym: "INDIAVIX", name: "India VIX", kind: "vix" }, { sym: "TCS", name: "TCS", kind: "stock" }];
  const f1 = new DemoFeed({ symbols: syms, base }), f2 = new DemoFeed({ symbols: syms, base });
  const t = Date.UTC(2026, 10, 27, 6, 0, 0);
  ok("two windows compute the same price", f1.price("NSE:TCS", t) === f2.price("NSE:TCS", t));
  ok("prices move over time", f1.price("NSE:TCS", t) !== f1.price("NSE:TCS", t + 600000));
  // one-session moves should have roughly the target daily volatility
  const day = 375 * 60000, rets = [];
  for (let i = 0; i < 300; i++) rets.push(Math.log(f1.price("NSE:NIFTY", t + i * day * 1.37 + day) / f1.price("NSE:NIFTY", t + i * day * 1.37)));
  const sd = Math.sqrt(rets.reduce((a, b) => a + b * b, 0) / rets.length) * Math.sqrt(252);
  ok("simulated Nifty volatility close to target (12%)", sd > 0.08 && sd < 0.16, sd.toFixed(3));
  const exp = f1.expiries(t)[0], K = 26000;
  const ce = f1.price(f1.option(K, "CE", exp).key, t), pe = f1.price(f1.option(K, "PE", exp).key, t);
  ok("option prices are positive", ce > 0 && pe > 0);
  const T = f1.yearsTo(exp, t), S = f1.spotPrice("NIFTY", t);
  const deep = f1.price(f1.option(Math.round(S / 50) * 50 - 2000, "PE", exp).key, t);
  ok("far OTM put cheap but at least the minimum tick", deep >= 0.05 && deep < ce);
  ok("expiries fall on Tuesdays", f1.expiries(t).every((d) => new Date(d + "T12:00:00").getDay() === 2));
  ok("nextTuesdays from a Tuesday after 15:30 rolls to next week", nextTuesdays(new Date("2026-12-01T16:00:00"), 1)[0].getDate() === 8);
  const c = f1.candles("NSE:TCS", 5, 10, t);
  ok("candles are consistent", c.length === 10 && c.every((b) => b.high >= Math.max(b.open, b.close) && b.low <= Math.min(b.open, b.close)));
  void T;
}
// ---- option analytics and ideas
{
  const flatIv = (iv) => () => iv;
  const series = (n, start, drift, wob) => Array.from({ length: n }, (_, i) => start * Math.exp(drift * i + wob * Math.sin(i * 1.7)));
  const base = { T: 7 / 365, expiry: "2026-12-01", vixHist: Array.from({ length: 252 }, (_, i) => 10 + 8 * (i % 50) / 50), vixAvg10: 14, lot: 65 };
  // indicators
  ok("RSI of a steady rise is high", IDEAS.rsi(series(60, 100, 0.01, 0)) > 90);
  ok("realised vol of a flat series is ~0", IDEAS.realisedVol(Array(30).fill(100), 21) < 1e-9);
  const rk = IDEAS.ivRank([10, 20, 30], 25, 3); ok("IV rank is position in range", near(rk.rank, 0.75) && near(rk.pctile, 2 / 3));
  const k = IDEAS.strikeByDelta(26000, 30 / 365, flatIv(0.14), "CE", 0.2);
  ok("20-delta call is above spot", k > 26000 && Math.abs(QL.bsGreeks(26000, k, 30 / 365, 0.06, 0.14, "call", 0.013).delta - 0.2) < 0.05);
  // rich IV + sideways -> iron condor first
  const sideways = Array.from({ length: 261 }, (_, i) => 26000 + (i % 2 ? 40 : -40) + (i % 7) * 3);   // choppy, no trend
  const A1 = IDEAS.analyse({ ...base, S: sideways.at(-1), ivFn: flatIv(0.16), closes: sideways, vix: 16, vixAvg10: 16 });
  const I1 = IDEAS.ideas(A1, flatIv(0.16));
  ok("sideways market is classed as range", A1.trend === "range", A1.trend);
  ok("IV above realised is classed rich", A1.ivRegime === "rich", A1.ivRegime);
  ok("rich IV + range -> iron condor ranked first", I1.ideas[0].name === "Iron condor", I1.ideas[0].name);
  const ic = I1.ideas[0];
  ok("condor short strikes straddle spot", ic.legs.find((l) => l.side < 0 && l.opt === "CE").strike > A1.S && ic.legs.find((l) => l.side < 0 && l.opt === "PE").strike < A1.S);
  ok("condor max loss is bounded", Number.isFinite(ic.stats.maxLoss) && ic.stats.maxLoss < 0);
  ok("rich IV says avoid buying outright options", I1.avoid.some((a) => /Buying outright/.test(a)));
  // cheap IV + uptrend -> debit spread, no premium selling
  const rising = series(260, 22000, 0.0015, 0.003);
  const A2 = IDEAS.analyse({ ...base, S: rising.at(-1), ivFn: flatIv(0.03), closes: rising, vix: 10, vixAvg10: 10 });
  const I2 = IDEAS.ideas(A2, flatIv(0.03));
  ok("steady rise is classed uptrend", A2.trend === "up", A2.trend);
  ok("cheap IV + uptrend -> bull call spread first", I2.ideas[0].name === "Bull call spread", I2.ideas[0].name);
  ok("cheap IV -> no credit spreads suggested", !I2.ideas.some((i) => /put spread|call spread/.test(i.name) && i.bias.includes("sell")));
  // VIX spike -> defensive first, no naked short straddle
  const A3 = IDEAS.analyse({ ...base, S: sideways.at(-1), ivFn: flatIv(0.22), closes: sideways, vix: 22, vixAvg10: 15 });
  ok("choppy market stays 'range' whichever day it ends on", [260, 261, 262, 263].every((n) => IDEAS.analyse({ ...base, S: sideways.slice(0, n).at(-1), ivFn: flatIv(0.16), closes: sideways.slice(0, n), vix: 16, vixAvg10: 16 }).trend === "range"));
  const I3 = IDEAS.ideas(A3, flatIv(0.22));
  ok("VIX spike detected", A3.spike);
  ok("spike -> protective put ranked first", /Protective put/.test(I3.ideas[0].name));
  ok("spike -> no short straddle or condor", !I3.ideas.some((i) => /Short straddle|Iron condor/.test(i.name)));
  // VIX at its 1-year low but still above realised: "cheap" for the right reason, with the caution shown
  const A4 = IDEAS.analyse({ ...base, S: sideways.at(-1), ivFn: flatIv(0.20), closes: sideways, vix: Math.min(...base.vixHist), vixAvg10: Math.min(...base.vixHist) });
  const I4 = IDEAS.ideas(A4, flatIv(0.20));
  ok("low VIX rank above realised -> cheap because of rank", A4.ivRegime === "cheap" && A4.cheapWhy === "low rank", A4.ivRegime + "/" + A4.cheapWhy);
  ok("avoid text names the 1-year low, not 'below realised'", I4.avoid.some((a) => /1-year low/.test(a)) && !I4.avoid.some((a) => /below realised/.test(a)));
  ok("expected move = S x IV x sqrt(T)", near(A1.move, A1.S * 0.16 * Math.sqrt(7 / 365), 1e-6));
}
console.log(fails ? `\n${fails} of ${n} FAILED` : `\nall ${n} checks passed`);
process.exit(fails ? 1 : 0);
