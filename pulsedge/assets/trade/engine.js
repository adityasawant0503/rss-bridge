/* PulsEdge Trade: paper-trading engine.
   Orders (market, limit, stop-loss, stop-loss-market, optional bracket), fills against the latest
   quote, positions with average price and realised/unrealised P&L, NSE charges on every fill and a
   simple margin check. No DOM: the terminal saves and syncs the state, tests run it in Node. */
(function (root) {
  "use strict";
  const QL = typeof module !== "undefined" && module.exports ? require("./quant.js") : root.QL;

  // margin as a fraction of position value (paper-trading approximation of broker margins)
  const MARGIN = { equity_MIS: 0.2, equity_CNC: 1, future: 0.12, option_buy: 1, option_sell: 0.12 };

  function chargeKind(inst, product) {
    if (inst.kind === "option") return "options";
    if (inst.kind === "future") return "futures";
    return product === "CNC" ? "equity_delivery" : "equity_intraday";
  }

  function Engine(opts = {}) {
    this.capital = opts.capital ?? 1000000;
    this.brokerage = opts.brokerage ?? 20;
    this.listeners = [];
    this.reset(this.capital);
  }
  Engine.prototype.reset = function (capital = this.capital) {
    this.capital = capital;
    this.state = { capital, realised: 0, charges: 0, orders: [], trades: [], positions: {}, insts: {}, last: {}, seq: 0 };
    this.emit("reset");
  };
  Engine.prototype.on = function (fn) { this.listeners.push(fn); };
  Engine.prototype.emit = function (what, data) { for (const fn of this.listeners) fn(what, data); };
  Engine.prototype.toJSON = function () { return this.state; };
  Engine.prototype.load = function (s) { if (s && s.orders) { this.state = s; this.capital = s.capital; this.emit("load"); } };

  Engine.prototype.ltp = function (key) { return this.state.last[key]; };
  Engine.prototype.register = function (inst) { this.state.insts[inst.key] = inst; };

  // money tied up by open positions, at the latest prices.
  // Options are margined per underlying and expiry on their combined worst-case loss at expiry
  // (so spreads and iron condors need only their maximum loss); open-ended short options fall back
  // to a fixed share of the underlying's value, like a broker's SPAN + exposure margin.
  Engine.prototype.usedMargin = function (positions = this.state.positions) {
    let m = 0;
    const groups = {};
    for (const p of Object.values(positions)) {
      if (!p.qty) continue;
      const inst = this.state.insts[p.key], px = this.ltp(p.key) ?? p.avg;
      if (inst.kind === "option") (groups[inst.underlyingKey + "|" + inst.expiry] ||= []).push({ inst, qty: p.qty, avg: p.avg, px });
      else m += this.marginFor(inst, p.product, p.qty, px);
    }
    for (const legs of Object.values(groups)) m += this.optionGroupMargin(legs);
    return m;
  };
  Engine.prototype.optionGroupMargin = function (legs) {
    const spot = this.ltp(legs[0].inst.underlyingKey) ?? legs[0].inst.strike;
    const pay = (ST) => legs.reduce((a, L) => a + L.qty * ((L.inst.type === "CE" ? Math.max(ST - L.inst.strike, 0) : Math.max(L.inst.strike - ST, 0)) - L.px), 0);
    const strikes = legs.map((L) => L.inst.strike), hi = Math.max(spot, ...strikes) * 3;
    const netCalls = legs.reduce((a, L) => a + (L.inst.type === "CE" ? L.qty : 0), 0);
    let worst = Math.min(pay(0), pay(hi), ...strikes.map(pay));
    if (netCalls < 0) {                                      // losses keep growing as the market rises
      const naked = legs.filter((L) => L.qty < 0).reduce((a, L) => a + Math.abs(L.qty) * spot * MARGIN.option_sell, 0);
      return naked + legs.filter((L) => L.qty > 0).reduce((a, L) => a + L.qty * L.px, 0);
    }
    const shortPutsUncovered = legs.reduce((a, L) => a + (L.inst.type === "PE" ? L.qty : 0), 0) < 0;
    const naive = legs.filter((L) => L.qty < 0).reduce((a, L) => a + Math.abs(L.qty) * spot * MARGIN.option_sell, 0)
      + legs.filter((L) => L.qty > 0).reduce((a, L) => a + L.qty * L.px, 0);
    // bounded risk: margin is the worst loss plus what was paid for long options
    const bounded = Math.max(-worst, 0) + legs.filter((L) => L.qty > 0).reduce((a, L) => a + L.qty * L.px, 0);
    return shortPutsUncovered ? Math.min(naive, Math.max(bounded, naive * 0.5)) : bounded;
  };
  Engine.prototype.marginFor = function (inst, product, qty, px) {
    if (inst.kind === "option") {
      if (qty > 0) return qty * px * MARGIN.option_buy;
      const spot = this.ltp(inst.underlyingKey) ?? inst.strike;
      return Math.abs(qty) * spot * MARGIN.option_sell;
    }
    if (inst.kind === "future") return Math.abs(qty) * px * MARGIN.future;
    return Math.abs(qty) * px * (product === "CNC" ? MARGIN.equity_CNC : MARGIN.equity_MIS);
  };
  Engine.prototype.unrealised = function () {
    let u = 0;
    for (const p of Object.values(this.state.positions)) {
      if (p.qty) u += p.qty * ((this.ltp(p.key) ?? p.avg) - p.avg);
    }
    return u;
  };
  Engine.prototype.funds = function () {
    const s = this.state, used = this.usedMargin(), unreal = this.unrealised();
    const equity = s.capital + s.realised - s.charges + unreal;
    return { capital: s.capital, realised: s.realised, unrealised: unreal, charges: s.charges, equity, used, available: equity - used };
  };

  // ---------------- orders ----------------
  // o: {key, side: "BUY"|"SELL", qty, type: "MARKET"|"LIMIT"|"SL"|"SL-M", price, trigger, product: "MIS"|"CNC"|"NRML", sl, target}
  Engine.prototype.place = function (o) {
    const inst = this.state.insts[o.key];
    const reject = (reason) => { const r = { ...o, id: ++this.state.seq, status: "REJECTED", reason, time: o.time ?? Date.now() }; this.state.orders.unshift(r); this.emit("order", r); return r; };
    if (!inst) return reject("Unknown instrument");
    if (inst.kind === "index" || inst.kind === "vix") return reject(`${inst.name} can't be traded directly. Use Nifty futures or options.`);
    if (!(o.qty > 0) || !Number.isInteger(o.qty)) return reject("Quantity must be a whole number above zero");
    if (inst.lot > 1 && o.qty % inst.lot) return reject(`Quantity must be a multiple of the lot size (${inst.lot})`);
    if ((o.type === "LIMIT" || o.type === "SL") && !(o.price > 0)) return reject("Enter a limit price");
    if ((o.type === "SL" || o.type === "SL-M") && !(o.trigger > 0)) return reject("Enter a trigger price");
    if (inst.kind === "equity" && o.side === "SELL" && o.product === "CNC") {
      const held = this.state.positions[o.key + "|CNC"]?.qty ?? 0;
      if (held < o.qty) return reject("Delivery (CNC) sells need shares you hold. Short selling is intraday (MIS) only.");
    }
    const px = this.ltp(o.key) ?? o.price ?? o.trigger;
    if (!(px > 0)) return reject("No price yet for this instrument");
    // margin check on the extra exposure this order would add
    const pk = o.key + "|" + (o.product || "MIS"), pos = this.state.positions[pk];
    const cur = pos?.qty ?? 0, next = cur + (o.side === "BUY" ? o.qty : -o.qty);
    const after = { ...this.state.positions, [pk]: { ...(pos || { key: o.key, product: o.product || "MIS", avg: px }), qty: next, avg: pos?.qty ? pos.avg : px } };
    const extra = this.usedMargin(after) - this.usedMargin();
    if (extra > 0 && extra > this.funds().available) return reject(`Not enough funds: needs ₹${Math.round(extra).toLocaleString("en-IN")}, available ₹${Math.round(this.funds().available).toLocaleString("en-IN")}`);
    const ord = { ...o, product: o.product || "MIS", id: ++this.state.seq, status: o.type === "SL" || o.type === "SL-M" ? "TRIGGER_PENDING" : "OPEN", time: o.time ?? Date.now(), filled: 0 };
    this.state.orders.unshift(ord);
    this.emit("order", ord);
    this.process(o.key, ord.time);
    return ord;
  };
  Engine.prototype.cancel = function (id) {
    const o = this.state.orders.find((x) => x.id === id);
    if (o && (o.status === "OPEN" || o.status === "TRIGGER_PENDING")) { o.status = "CANCELLED"; this.emit("order", o); }
    return o;
  };
  Engine.prototype.squareOff = function (posKey, time) {
    const p = this.state.positions[posKey];
    if (!p || !p.qty) return null;
    for (const o of this.state.orders) if (o.key === p.key && o.product === p.product && o.oco && (o.status === "OPEN" || o.status === "TRIGGER_PENDING")) this.cancel(o.id);
    return this.place({ key: p.key, side: p.qty > 0 ? "SELL" : "BUY", qty: Math.abs(p.qty), type: "MARKET", product: p.product, time });
  };
  Engine.prototype.squareOffAll = function (time) {
    for (const o of this.state.orders) if (o.status === "OPEN" || o.status === "TRIGGER_PENDING") this.cancel(o.id);
    return Object.keys(this.state.positions).map((k) => this.squareOff(k, time)).filter(Boolean);
  };

  // ---------------- quotes and fills ----------------
  Engine.prototype.quote = function (key, ltp, time) {
    if (!(ltp > 0)) return;
    this.state.last[key] = ltp;
    this.process(key, time);
  };
  Engine.prototype.process = function (key, time = Date.now()) {
    const ltp = this.state.last[key];
    if (!(ltp > 0)) return;
    for (const o of [...this.state.orders].reverse()) {           // oldest first
      if (o.key !== key) continue;
      if (o.status === "TRIGGER_PENDING") {
        const hit = o.side === "BUY" ? ltp >= o.trigger : ltp <= o.trigger;
        if (!hit) continue;
        o.status = "OPEN";
        if (o.type === "SL-M") o.type = "MARKET";
        else o.type = "LIMIT";
      }
      if (o.status !== "OPEN") continue;
      let px = null;
      if (o.type === "MARKET") px = ltp;
      else if (o.type === "LIMIT") {
        if (o.side === "BUY" && ltp <= o.price) px = Math.min(ltp, o.price);
        if (o.side === "SELL" && ltp >= o.price) px = Math.max(ltp, o.price);
      }
      if (px != null) this.fill(o, px, time);
    }
  };
  Engine.prototype.fill = function (o, px, time) {
    const s = this.state, inst = s.insts[o.key], pk = o.key + "|" + o.product;
    const ch = QL.orderCharges(chargeKind(inst, o.product), o.side === "BUY" ? "buy" : "sell", px * o.qty, this.brokerage);
    o.status = "COMPLETE"; o.avg = px; o.filled = o.qty; o.filledAt = time; o.charges = ch.total;
    const p = s.positions[pk] || (s.positions[pk] = { key: o.key, product: o.product, qty: 0, avg: 0, realised: 0, charges: 0, buyQty: 0, sellQty: 0, buyVal: 0, sellVal: 0 });
    const signed = o.side === "BUY" ? o.qty : -o.qty;
    if (o.side === "BUY") { p.buyQty += o.qty; p.buyVal += o.qty * px; } else { p.sellQty += o.qty; p.sellVal += o.qty * px; }
    if (p.qty === 0 || Math.sign(p.qty) === Math.sign(signed)) {       // opening or adding
      p.avg = (p.avg * Math.abs(p.qty) + px * o.qty) / (Math.abs(p.qty) + o.qty);
      p.qty += signed;
    } else {                                                           // reducing, closing or flipping
      const closing = Math.min(Math.abs(p.qty), o.qty);
      const pnl = closing * (px - p.avg) * Math.sign(p.qty);
      p.realised += pnl; s.realised += pnl;
      const left = o.qty - closing;
      p.qty += signed;
      if (p.qty === 0) p.avg = 0;
      else if (left > 0) p.avg = px;                                   // flipped: the remainder opens at this price
    }
    p.charges += ch.total; s.charges += ch.total;
    const tr = { id: s.trades.length + 1, order: o.id, key: o.key, side: o.side, qty: o.qty, price: px, product: o.product, charges: ch.total, breakdown: ch, time };
    s.trades.unshift(tr);
    this.emit("fill", tr);
    // bracket: protective stop and target, one cancels the other
    if ((o.sl > 0 || o.target > 0) && !o.oco) {
      const exit = o.side === "BUY" ? "SELL" : "BUY", grp = "oco" + o.id;
      if (o.sl > 0) this.place({ key: o.key, side: exit, qty: o.qty, type: "SL-M", trigger: o.sl, product: o.product, oco: grp, time });
      if (o.target > 0) this.place({ key: o.key, side: exit, qty: o.qty, type: "LIMIT", price: o.target, product: o.product, oco: grp, time });
    } else if (o.oco) {
      for (const x of s.orders) if (x.oco === o.oco && x.id !== o.id && (x.status === "OPEN" || x.status === "TRIGGER_PENDING")) this.cancel(x.id);
    }
  };

  const api = { Engine, MARGIN, chargeKind };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PETrade = Object.assign(root.PETrade || {}, api);
})(typeof globalThis !== "undefined" ? globalThis : this);
