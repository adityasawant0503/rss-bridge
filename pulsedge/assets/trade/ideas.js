/* PulsEdge Trade: option analytics and trade ideas.
   Pure functions (no DOM) so the rules are testable in Node. The terminal passes in the market
   snapshot; this returns the indicators a derivatives desk checks and a ranked list of strategy
   ideas with strikes, risk and the reasons behind each. Rules, not predictions: every idea says
   what it needs to be true and what would invalidate it. */
(function (root) {
  "use strict";
  const QL = typeof module !== "undefined" && module.exports ? require("./quant.js") : root.QL;
  const R = 0.06, Q = 0.013, STEP = 50;

  // ---------------- indicators ----------------
  const sma = (a, n) => a.length < n ? NaN : a.slice(-n).reduce((s, x) => s + x, 0) / n;
  function realisedVol(closes, n) {
    if (closes.length < n + 1) return NaN;
    const c = closes.slice(-n - 1), lr = c.slice(1).map((x, i) => Math.log(x / c[i]));
    const m = lr.reduce((s, x) => s + x, 0) / lr.length;
    return Math.sqrt(lr.reduce((s, x) => s + (x - m) ** 2, 0) / (lr.length - 1) * 252);
  }
  function rsi(closes, n = 14) {                              // Wilder's RSI
    if (closes.length < n + 1) return NaN;
    let up = 0, dn = 0;
    for (let i = 1; i <= n; i++) { const d = closes[i] - closes[i - 1]; if (d > 0) up += d; else dn -= d; }
    up /= n; dn /= n;
    for (let i = n + 1; i < closes.length; i++) {
      const d = closes[i] - closes[i - 1];
      up = (up * (n - 1) + Math.max(d, 0)) / n; dn = (dn * (n - 1) + Math.max(-d, 0)) / n;
    }
    return dn === 0 ? 100 : 100 - 100 / (1 + up / dn);
  }
  // where x sits in the last `n` values: rank = (x - min) / (max - min), percentile = share below x
  function ivRank(hist, x, n = 252) {
    const h = hist.slice(-n), lo = Math.min(...h, x), hi = Math.max(...h, x);
    return { rank: hi > lo ? (x - lo) / (hi - lo) : 0.5, pctile: h.filter((v) => v < x).length / h.length, lo, hi };
  }

  // strike whose delta is closest to target (calls: +target, puts: -target)
  function strikeByDelta(S, T, ivFn, type, target) {
    let best = null;
    for (let k = Math.round(S * 0.8 / STEP) * STEP; k <= S * 1.2; k += STEP) {
      const d = QL.bsGreeks(S, k, T, R, ivFn(k), type === "CE" ? "call" : "put", Q).delta;
      const err = Math.abs(Math.abs(d) - target);
      if (!best || err < best.err) best = { k, d, err };
    }
    return best.k;
  }

  /* snapshot: {S, T, expiry, ivFn(K), closes (daily, ending with today's price), vixHist (daily, as %),
                vix (now, %), vixAvg10 (%), newsHigh (count of high-impact news today), lot} */
  function analyse(snap) {
    const { S, T, ivFn, closes, vixHist, vix, vixAvg10, lot = 65 } = snap;
    const atm = Math.round(S / STEP) * STEP, ivAtm = ivFn(atm);
    const rv10 = realisedVol(closes, 10), rv21 = realisedVol(closes, 21), rv63 = realisedVol(closes, 63);
    const vr = ivRank(vixHist, vix);
    const ma20 = sma(closes, 20), ma50 = sma(closes, 50), ma200 = sma(closes, 200);
    const ret20 = closes.length > 21 ? S / closes[closes.length - 21] - 1 : NaN;
    const r14 = rsi(closes.slice(-120));
    // expected move to expiry and the ATM straddle the market charges for it
    const move = S * ivAtm * Math.sqrt(T);
    const straddle = QL.bsPrice(S, atm, T, R, ivAtm, "call", Q) + QL.bsPrice(S, atm, T, R, ivAtm, "put", Q);
    // skew: 25-delta put IV minus 25-delta call IV (volatility points)
    const k25p = strikeByDelta(S, T, ivFn, "PE", 0.25), k25c = strikeByDelta(S, T, ivFn, "CE", 0.25);
    const skew = (ivFn(k25p) - ivFn(k25c)) * 100;
    // trend score -3 (down) .. +3 (up), with dead-bands so small wiggles around an average don't count:
    // price 0.5% away from its 20-day average, the 20-day average 0.25% away from the 50-day, 20-day return beyond 1.5%
    const sgn = (x, band) => (x > band) - (x < -band);
    const score = sgn(S / ma20 - 1, 0.005) + sgn(ma20 / ma50 - 1, 0.0025) + sgn(ret20, 0.015);
    const trend = score >= 2 ? "up" : score <= -2 ? "down" : "range";
    const spike = vix / vixAvg10 - 1 > 0.10;
    const gap = ivAtm - rv21;                                  // implied minus realised, decimal
    const ivRegime = spike ? "spiking" : gap > 0.015 && vr.rank > 0.35 ? "rich" : gap < 0 || vr.rank < 0.15 ? "cheap" : "fair";
    return { S, T, expiry: snap.expiry, atm, ivAtm, rv10, rv21, rv63, gap, vixRank: vr.rank, vixPctile: vr.pctile, vixLo: vr.lo, vixHi: vr.hi,
      vix, vixAvg10, spike, ma20, ma50, ma200, ret20, rsi: r14, trend, trendScore: score, move, straddle, skew, k25p, k25c,
      ivRegime, cheapWhy: gap < 0 ? "below realised" : "low rank", newsHigh: snap.newsHigh || 0, lot, vrpRule: vix / 100 > rv21 && !spike };
  }

  // ---------------- ideas ----------------
  function build(name, legs, A, ivFn) {
    const priced = legs.map(([side, type, strike]) => ({ side, type: type === "CE" ? "call" : "put", opt: type, strike, lots: 1,
      premium: Math.max(0.05, QL.bsPrice(A.S, strike, A.T, R, ivFn(strike), type === "CE" ? "call" : "put", Q)) }));
    const st = QL.strategyStats(priced, A.S, A.T, R, A.ivAtm, Q, A.lot);
    const g = QL.strategyGreeks(priced, A.S, A.T, R, A.ivAtm, Q, A.lot);
    const rr = Number.isFinite(st.maxProfit) && Number.isFinite(st.maxLoss) && st.maxLoss < 0 ? st.maxProfit / -st.maxLoss : null;
    return { name, legs: priced, stats: st, greeks: g, rewardRisk: rr };
  }

  function ideas(A, ivFn) {
    const S = A.S, r50 = (x) => Math.round(x / STEP) * STEP, W = 200;           // wing width in points
    const sc = strikeByDelta(S, A.T, ivFn, "CE", 0.20), sp = strikeByDelta(S, A.T, ivFn, "PE", 0.20);
    const c30 = strikeByDelta(S, A.T, ivFn, "CE", 0.30), p30 = strikeByDelta(S, A.T, ivFn, "PE", 0.30);
    const out = [];
    const add = (fit, name, bias, legs, why, invalid, extra = {}) => { if (fit > 0) out.push({ fit, bias, why, invalid, ...extra, ...build(name, legs, A, ivFn) }); };
    const rich = A.ivRegime === "rich", cheap = A.ivRegime === "cheap", spike = A.spike;
    const ivTxt = `ATM IV ${(A.ivAtm * 100).toFixed(1)}% vs ${(A.rv21 * 100).toFixed(1)}% realised (21d)`;
    const rankTxt = `VIX rank ${(A.vixRank * 100).toFixed(0)}/100 over a year`;
    const moveTxt = `Expected move to expiry ±${Math.round(A.move)} pts (${r50(S - A.move)}–${r50(S + A.move)})`;

    // short volatility, defined risk
    add(!spike && A.trend === "range" && !cheap ? (rich ? 3 : 2) : 0, "Iron condor", "Neutral · sell volatility",
      [[-1, "CE", sc], [1, "CE", sc + W], [-1, "PE", sp], [1, "PE", sp - W]],
      [ivTxt, `Trend is sideways: Nifty within its 20- and 50-day averages`, moveTxt + `; short strikes sit about 1 expected move out (20 delta)`],
      [`Nifty closes beyond ${sp} or ${sc}`, "India VIX jumps more than 10% above its 10-day average"], { evidence: "vrp" });
    add(!spike && A.trend === "up" && !cheap ? (rich ? 3 : 2) : 0, "Bull put spread", "Bullish · sell volatility",
      [[-1, "PE", p30], [1, "PE", p30 - W]],
      [ivTxt, `Uptrend: Nifty above its 20- and 50-day averages, ${(A.ret20 * 100).toFixed(1)}% over 20 sessions`, "Collects premium below the market; profits if Nifty holds or rises"],
      [`Nifty closes below ${p30}`, "Price falls back under the 20-day average"], { evidence: "vrp" });
    add(!spike && A.trend === "down" && !cheap ? (rich ? 3 : 2) : 0, "Bear call spread", "Bearish · sell volatility",
      [[-1, "CE", c30], [1, "CE", c30 + W]],
      [ivTxt, `Downtrend: Nifty below its 20- and 50-day averages, ${(A.ret20 * 100).toFixed(1)}% over 20 sessions`, "Collects premium above the market; profits if Nifty holds or falls"],
      [`Nifty closes above ${c30}`, "Price reclaims the 20-day average"], { evidence: "vrp" });
    // long volatility / directional debit
    add(A.trend === "up" && !rich ? (cheap ? 3 : 2) : 0, "Bull call spread", "Bullish · buy direction",
      [[1, "CE", A.atm], [-1, "CE", A.atm + W]],
      [ivTxt + (cheap ? ": options are cheap, so buying is favoured" : ""), `Uptrend with RSI ${A.rsi.toFixed(0)}`, "Loss capped at the premium paid; the sold call cuts the cost"],
      [`Nifty falls below ${r50(A.ma20)} (20-day average)`, "Little movement before expiry: time decay works against you"]);
    add(A.trend === "down" && !rich ? (cheap ? 3 : 2) : 0, "Bear put spread", "Bearish · buy direction",
      [[1, "PE", A.atm], [-1, "PE", A.atm - W]],
      [ivTxt + (cheap ? ": options are cheap, so buying is favoured" : ""), `Downtrend with RSI ${A.rsi.toFixed(0)}`, "Loss capped at the premium paid; the sold put cuts the cost"],
      [`Nifty rises above ${r50(A.ma20)} (20-day average)`, "Little movement before expiry"]);
    add(cheap || (A.rv10 > A.rv21 * 1.15 && !rich) || A.newsHigh >= 3 ? (cheap && A.trend === "range" ? 3 : cheap ? 2 : 1) : 0, "Long straddle", "Neutral · buy volatility",
      [[1, "CE", A.atm], [1, "PE", A.atm]],
      [ivTxt + (cheap ? (A.cheapWhy === "below realised" ? ": volatility is cheap" : `; ${rankTxt}, near the bottom`) : ""), A.rv10 > A.rv21 ? `Realised volatility is rising (10d ${(A.rv10 * 100).toFixed(1)}% > 21d ${(A.rv21 * 100).toFixed(1)}%)` : "Profits from a large move either way",
        A.newsHigh ? `${A.newsHigh} high-impact news items today` : `Needs a move beyond ±${Math.round(A.straddle)} pts (the straddle cost)`],
      ["Nifty stays near the strike into expiry", "Implied volatility falls (vega loss)"]);
    // the backtested rule (advanced, needs daily hedging)
    add(A.vrpRule ? 1 : 0, "Short straddle, delta-hedged daily", "Neutral · the backtested rule",
      [[-1, "CE", A.atm], [-1, "PE", A.atm]],
      [`India VIX ${A.vix.toFixed(2)} above Nifty's recent volatility ${(A.rv21 * 100).toFixed(1)}%, and not spiking`, "Matches the rule that held up on 2017–2025 data in the volatility study", "Hedge the delta daily with Nifty futures; losses are unlimited without that"].concat(cheap ? [`Caution: ${rankTxt}. Premium is thin and volatility tends to rise from here, so use small size`] : []),
      ["A gap move (results, policy, elections)", "India VIX spikes: close or cut size"], { evidence: "vrp", advanced: true });
    if (spike) {
      add(4, "Protective put (or stand aside)", "Defensive · volatility spiking",
        [[1, "PE", A.atm - 100]],
        [`India VIX is ${((A.vix / A.vixAvg10 - 1) * 100).toFixed(0)}% above its 10-day average: selling options into a spike is when sellers lose most`, "Hedge existing long positions, or wait for volatility to settle"],
        ["VIX falls back toward its 10-day average"]);
    }
    out.sort((a, b) => b.fit - a.fit || (b.stats.pop - a.stats.pop));
    const avoid = [];
    if (spike) avoid.push("Naked option selling: VIX is spiking");
    if (cheap) avoid.push(A.cheapWhy === "below realised" ? "Selling premium: implied volatility is below realised" : `Selling premium outright: India VIX is near its 1-year low (rank ${(A.vixRank * 100).toFixed(0)}), so there is little cushion if volatility jumps`);
    if (rich) avoid.push("Buying outright options: implied volatility is rich and will likely decay");
    if (A.rsi > 70) avoid.push(`Chasing calls: RSI ${A.rsi.toFixed(0)} is overbought`);
    if (A.rsi < 30) avoid.push(`Chasing puts: RSI ${A.rsi.toFixed(0)} is oversold`);
    return { ideas: out, avoid };
  }

  const api = { analyse, ideas, realisedVol, rsi, sma, ivRank, strikeByDelta };
  if (typeof module !== "undefined" && module.exports) module.exports = api;
  else root.PEIdeas = api;
})(typeof globalThis !== "undefined" ? globalThis : this);
