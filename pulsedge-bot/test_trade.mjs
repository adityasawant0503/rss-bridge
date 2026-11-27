// Tests for PulsEdge Trade's paper-trading engine and demo feed. Run: node pulsedge-bot/test_trade.mjs
import { createRequire } from "node:module";
const require = createRequire(import.meta.url);
const { Engine } = require("../pulsedge/assets/trade/engine.js");
const { DemoFeed, nextTuesdays } = require("../pulsedge/assets/trade/feed.js");
const QL = require("../pulsedge/assets/trade/quant.js");

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
console.log(fails ? `\n${fails} of ${n} FAILED` : `\nall ${n} checks passed`);
process.exit(fails ? 1 : 0);
