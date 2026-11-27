/* PulsEdge Trade: market data.
   DemoFeed simulates live prices so the terminal works without a broker account. Every window
   computes the same price for the same moment (prices are a deterministic function of the symbol
   and the clock), so pop-out windows on other monitors stay in step without a server.
   A live feed (Dhan, through the PulsEdge connector) implements the same three methods:
     price(key, tMs) · candles(key, minutes, count, tMs) · instrument(key)                       */
(function (root) {
  "use strict";
  const QL = typeof module !== "undefined" && module.exports ? require("./quant.js") : root.QL;

  const SESSION = 375;                    // market minutes per demo session (09:15-15:30)
  const R = 0.06, Q = 0.013;

  function hash(str) {                    // FNV-1a
    let h = 2166136261;
    for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619); }
    return h >>> 0;
  }

  // A stationary random-looking path: sum of sinusoids with Brownian-like spectrum
  // (amplitude ~ sqrt(period)), periods from 20 seconds to 5 sessions, seeded per symbol.
  function Wiggle(seed, n = 40) {
    const g = QL.rng(seed), comps = [];
    const pMin = 20, pMax = 5 * SESSION * 60;
    for (let k = 0; k < n; k++) {
      const period = pMin * Math.pow(pMax / pMin, k / (n - 1)) * (0.85 + 0.3 * g.uni());
      comps.push([2 * Math.PI / period, 2 * Math.PI * g.uni(), Math.sqrt(period) * (0.7 + 0.6 * g.uni())]);
    }
    this.comps = comps;
    this.scale = 1;
    // calibrate: standard deviation of the change over one session = 1
    let s = 0, s2 = 0;
    const N = 400, day = SESSION * 60;
    for (let i = 0; i < N; i++) { const t = i * 7919.3; const d = this.raw(t + day) - this.raw(t); s += d; s2 += d * d; }
    this.scale = 1 / Math.sqrt(s2 / N - (s / N) ** 2);
  }
  Wiggle.prototype.raw = function (sec) { let x = 0; for (const [w, ph, a] of this.comps) x += a * Math.sin(w * sec + ph); return x; };
  Wiggle.prototype.at = function (sec) { return this.raw(sec) * this.scale; };

  function nextTuesdays(fromDate, n) {    // NSE index options expire on Tuesdays
    const out = [], d = new Date(fromDate);
    d.setHours(15, 30, 0, 0);
    while (d.getDay() !== 2 || d < fromDate) d.setDate(d.getDate() + 1);
    for (let i = 0; i < n; i++) { out.push(new Date(d)); d.setDate(d.getDate() + 7); }
    return out;
  }
  const ymd = (d) => d.getFullYear() + "-" + String(d.getMonth() + 1).padStart(2, "0") + "-" + String(d.getDate()).padStart(2, "0");

  function DemoFeed({ symbols, base, lot = 65, epoch = Date.UTC(2026, 0, 1) }) {
    // symbols: [{sym, name, kind, sector}], base: {SYM: {close, vol}} from the latest real data
    this.meta = Object.fromEntries(symbols.map((s) => [s.sym, s]));
    this.base = base;
    this.lot = lot;
    this.epoch = epoch;
    this.w = {};
    this.insts = {};
    for (const s of symbols) {
      if (!base[s.sym]) continue;
      const key = "NSE:" + s.sym;
      this.insts[key] = { key, sym: s.sym, name: s.name, kind: s.kind === "stock" ? "equity" : s.kind, lot: 1, tick: 0.05 };
    }
    const fut = "NFO:NIFTY FUT";
    this.insts[fut] = { key: fut, sym: "NIFTY FUT", name: "Nifty futures (near month)", kind: "future", lot, tick: 0.05, underlyingKey: "NSE:NIFTY" };
  }
  DemoFeed.prototype.wiggle = function (sym) { return this.w[sym] || (this.w[sym] = new Wiggle(hash("pe:" + sym))); };
  DemoFeed.prototype.sec = function (t) { return (t - this.epoch) / 1000; };
  // session clock: demo market runs continuously in 375-minute sessions
  DemoFeed.prototype.session = function (t) {
    const m = this.sec(t) / 60, n = Math.floor(m / SESSION);
    return { n, minute: m - n * SESSION, start: this.epoch + n * SESSION * 60000 };
  };
  DemoFeed.prototype.spotPrice = function (sym, t) {
    const b = this.base[sym];
    if (!b) return NaN;
    const daily = b.vol / Math.sqrt(252);
    if (sym === "INDIAVIX") {               // VIX moves against Nifty, plus its own noise
      const x = -0.6 * this.wiggle("NIFTY").at(this.sec(t)) + 0.8 * this.wiggle("INDIAVIX").at(this.sec(t));
      return b.close * Math.exp(0.06 * x);
    }
    const common = sym === "NIFTY" ? 0 : this.wiggle("NIFTY").at(this.sec(t)) * 0.55;
    const own = this.wiggle(sym).at(this.sec(t));
    const x = sym === "NIFTY" ? own : common + own * 0.835;   // stocks share ~55% of Nifty's moves
    return b.close * Math.exp(daily * x);
  };
  DemoFeed.prototype.round = function (p, tick = 0.05) { return Math.round(p / tick) * tick; };

  // option and futures instruments are created on demand
  DemoFeed.prototype.expiries = function (t, n = 4) { return nextTuesdays(new Date(t), n).map(ymd); };
  DemoFeed.prototype.option = function (strike, type, expiry) {
    const key = `NFO:NIFTY ${expiry.replaceAll("-", "")} ${strike} ${type}`;
    return this.insts[key] || (this.insts[key] = { key, sym: `NIFTY ${strike} ${type}`, name: `Nifty ${strike} ${type === "CE" ? "call" : "put"}, expiry ${expiry}`,
      kind: "option", underlyingKey: "NSE:NIFTY", strike, type, expiry, lot: this.lot, tick: 0.05 });
  };
  DemoFeed.prototype.instrument = function (key) {
    if (this.insts[key]) return this.insts[key];
    const m = /^NFO:NIFTY (\d{8}) (\d+) (CE|PE)$/.exec(key);
    if (m) return this.option(+m[2], m[3], `${m[1].slice(0, 4)}-${m[1].slice(4, 6)}-${m[1].slice(6)}`);
    return null;
  };
  // implied volatility for a strike: India VIX with a downside skew
  DemoFeed.prototype.iv = function (strike, t, T) {
    const v = this.spotPrice("INDIAVIX", t) / 100, S = this.spotPrice("NIFTY", t);
    const z = Math.log(strike / S) / (v * Math.sqrt(Math.max(T, 1 / 365)));
    return Math.max(0.04, v - 0.012 * z);
  };
  DemoFeed.prototype.yearsTo = function (expiry, t) { return Math.max((new Date(expiry + "T15:30:00+05:30") - t) / 31557600000, 0.5 / 365); };
  DemoFeed.prototype.price = function (key, t = Date.now()) {
    const inst = this.instrument(key);
    if (!inst) return NaN;
    if (inst.kind === "option") {
      const S = this.spotPrice("NIFTY", t), T = this.yearsTo(inst.expiry, t);
      return Math.max(0.05, this.round(QL.bsPrice(S, inst.strike, T, R, this.iv(inst.strike, t, T), inst.type === "CE" ? "call" : "put", Q)));
    }
    if (inst.kind === "future") return this.round(this.spotPrice("NIFTY", t) * Math.exp((R - Q) * 30 / 365));
    return this.round(this.spotPrice(inst.sym, t));
  };
  DemoFeed.prototype.prevClose = function (key) {
    const inst = this.instrument(key);
    if (!inst) return NaN;
    if (inst.kind === "equity" || inst.kind === "index" || inst.kind === "vix") return this.base[inst.sym].close;
    return this.price(key, this.session(Date.now()).start - 1);
  };
  // OHLC candles of `minutes` length ending at t (6 samples per minute)
  DemoFeed.prototype.candles = function (key, minutes = 1, count = 120, t = Date.now()) {
    const out = [], step = minutes * 60000, end = Math.floor(t / step) * step;
    for (let i = count - 1; i >= 0; i--) {
      const s = end - i * step;
      let o = null, h = -Infinity, l = Infinity, c = null;
      const k = Math.max(6, minutes * 3);
      for (let j = 0; j <= k; j++) {
        const tt = Math.min(s + step * j / k, t);
        const p = this.price(key, tt);
        if (o === null) o = p;
        h = Math.max(h, p); l = Math.min(l, p); c = p;
      }
      out.push({ time: Math.floor(s / 1000), open: o, high: h, low: l, close: c });
    }
    return out;
  };

  const api = { DemoFeed, Wiggle, hash, nextTuesdays, SESSION };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PETrade = Object.assign(root.PETrade || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this);
