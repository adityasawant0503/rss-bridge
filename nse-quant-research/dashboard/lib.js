/* Quant maths for the dashboard: a line-for-line port of optlab and quantlab.
   Runs in the browser (window.QL) and in Node (module.exports) so test_lib.mjs
   can check it against the Python reference values in data/results.json. */
(function (root) {
  "use strict";

  // ---------- normal distribution ----------
  // erfc from Numerical Recipes (fractional error < 1.2e-7)
  function erfc(x) {
    const z = Math.abs(x), t = 1 / (1 + 0.5 * z);
    const r = t * Math.exp(-z * z - 1.26551223 + t * (1.00002368 + t * (0.37409196 + t * (0.09678418 +
      t * (-0.18628806 + t * (0.27886807 + t * (-1.13520398 + t * (1.48851587 +
      t * (-0.82215223 + t * 0.17087277)))))))));
    return x >= 0 ? r : 2 - r;
  }
  const normCdf = (x) => 0.5 * erfc(-x / Math.SQRT2);
  const normPdf = (x) => Math.exp(-0.5 * x * x) / Math.sqrt(2 * Math.PI);

  // ---------- seeded RNG (mulberry32 + Box-Muller) ----------
  function rng(seed) {
    let a = seed >>> 0, spare = null;
    const uni = () => {
      a = (a + 0x6d2b79f5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
    const normal = () => {
      if (spare !== null) { const s = spare; spare = null; return s; }
      let u = 0, v = 0;
      while (u === 0) u = uni();
      v = uni();
      const m = Math.sqrt(-2 * Math.log(u));
      spare = m * Math.sin(2 * Math.PI * v);
      return m * Math.cos(2 * Math.PI * v);
    };
    return { uni, normal };
  }

  // ---------- Black-Scholes-Merton ----------
  function d12(S, K, T, r, q, sig) {
    const vt = sig * Math.sqrt(T);
    const d1 = (Math.log(S / K) + (r - q + 0.5 * sig * sig) * T) / vt;
    return [d1, d1 - vt];
  }
  function bsPrice(S, K, T, r, sig, kind = "call", q = 0) {
    if (T <= 0) return kind === "call" ? Math.max(S - K, 0) : Math.max(K - S, 0);
    const [d1, d2] = d12(S, K, T, r, q, sig), dq = Math.exp(-q * T), dr = Math.exp(-r * T);
    return kind === "call" ? S * dq * normCdf(d1) - K * dr * normCdf(d2)
      : K * dr * normCdf(-d2) - S * dq * normCdf(-d1);
  }
  function bsGreeks(S, K, T, r, sig, kind = "call", q = 0) {
    const [d1, d2] = d12(S, K, T, r, q, sig), dq = Math.exp(-q * T), dr = Math.exp(-r * T);
    const sT = Math.sqrt(T), n1 = normPdf(d1);
    const gamma = dq * n1 / (S * sig * sT), vega = S * dq * n1 * sT, common = -S * dq * n1 * sig / (2 * sT);
    if (kind === "call") {
      return { delta: dq * normCdf(d1), gamma, vega,
        theta: common - r * K * dr * normCdf(d2) + q * S * dq * normCdf(d1), rho: K * T * dr * normCdf(d2) };
    }
    return { delta: -dq * normCdf(-d1), gamma, vega,
      theta: common + r * K * dr * normCdf(-d2) - q * S * dq * normCdf(-d1), rho: -K * T * dr * normCdf(-d2) };
  }

  // ---------- binomial (CRR) ----------
  function binomialPrice(S, K, T, r, sig, kind = "call", q = 0, steps = 300, american = false) {
    const dt = T / steps, u = Math.exp(sig * Math.sqrt(dt)), d = 1 / u;
    const p = (Math.exp((r - q) * dt) - d) / (u - d), disc = Math.exp(-r * dt);
    const pay = kind === "call" ? (s) => Math.max(s - K, 0) : (s) => Math.max(K - s, 0);
    const v = new Float64Array(steps + 1);
    for (let j = 0; j <= steps; j++) v[j] = pay(S * Math.pow(u, steps - j) * Math.pow(d, j));
    for (let n = steps - 1; n >= 0; n--) {
      for (let j = 0; j <= n; j++) {
        let x = disc * (p * v[j] + (1 - p) * v[j + 1]);
        if (american) x = Math.max(x, pay(S * Math.pow(u, n - j) * Math.pow(d, j)));
        v[j] = x;
      }
    }
    return v[0];
  }

  // ---------- Monte Carlo (antithetic + control variate) ----------
  function mcPrice(S, K, T, r, sig, kind = "call", q = 0, nPaths = 50000, seed = 1, anti = true, cv = true) {
    const g = rng(seed), n = anti ? nPaths >> 1 : nPaths, disc = Math.exp(-r * T);
    const drift = (r - q - 0.5 * sig * sig) * T, vol = sig * Math.sqrt(T);
    const ys = new Float64Array(n), xs = new Float64Array(n);
    const one = (z) => {
      const ST = S * Math.exp(drift + vol * z);
      return [disc * (kind === "call" ? Math.max(ST - K, 0) : Math.max(K - ST, 0)), disc * ST];
    };
    for (let i = 0; i < n; i++) {
      const z = g.normal();
      let [y, x] = one(z);
      if (anti) { const [y2, x2] = one(-z); y = 0.5 * (y + y2); x = 0.5 * (x + x2); }
      ys[i] = y; xs[i] = x;
    }
    if (cv) {
      let my = 0, mx = 0;
      for (let i = 0; i < n; i++) { my += ys[i]; mx += xs[i]; }
      my /= n; mx /= n;
      let cxy = 0, cxx = 0;
      for (let i = 0; i < n; i++) { cxy += (ys[i] - my) * (xs[i] - mx); cxx += (xs[i] - mx) ** 2; }
      const b = cxy / cxx, ex = S * Math.exp(-q * T);
      for (let i = 0; i < n; i++) ys[i] -= b * (xs[i] - ex);
    }
    let m = 0;
    for (let i = 0; i < n; i++) m += ys[i];
    m /= n;
    let v = 0;
    for (let i = 0; i < n; i++) v += (ys[i] - m) ** 2;
    return { price: m, se: Math.sqrt(v / (n - 1) / n) };
  }

  // ---------- implied volatility ----------
  function impliedVol(price, S, K, T, r, kind = "call", q = 0) {
    const dq = Math.exp(-q * T), dr = Math.exp(-r * T);
    const lo0 = kind === "call" ? Math.max(S * dq - K * dr, 0) : Math.max(K * dr - S * dq, 0);
    const hi0 = kind === "call" ? S * dq : K * dr;
    if (price < lo0 - 1e-12 || price > hi0 + 1e-12) return NaN;
    let lo = 1e-4, hi = 5;
    for (let i = 0; i < 200 && hi - lo > 1e-9; i++) {
      const mid = 0.5 * (lo + hi);
      if (bsPrice(S, K, T, r, mid, kind, q) > price) hi = mid; else lo = mid;
    }
    return 0.5 * (lo + hi);
  }

  // ---------- delta hedging ----------
  function realisedVol(prices, from, to) { // prices[from..to] inclusive
    const n = to - from;
    let m = 0;
    const lr = new Float64Array(n);
    for (let i = 0; i < n; i++) { lr[i] = Math.log(prices[from + i + 1] / prices[from + i]); m += lr[i]; }
    m /= n;
    let v = 0;
    for (let i = 0; i < n; i++) v += (lr[i] - m) ** 2;
    return Math.sqrt(v / (n - 1) * 252);
  }
  // short option, delta-hedged every `every` steps; returns P&L / initial spot
  function hedgePnl(path, K, T, r, sig, kind = "call", q = 0, every = 1, cost = 0) {
    const steps = path.length - 1, dt = T / steps, S0 = path[0];
    let cash = bsPrice(S0, K, T, r, sig, kind, q), delta = 0;
    for (let i = 0; i < steps; i++) {
      const S = path[i];
      if (i % every === 0) {
        const nd = bsGreeks(S, K, T - i * dt, r, sig, kind, q).delta, tr = nd - delta;
        cash -= tr * S + Math.abs(tr) * S * cost;
        delta = nd;
      }
      cash = cash * Math.exp(r * dt) + delta * S * (Math.exp(q * dt) - 1);
    }
    const ST = path[steps], payoff = kind === "call" ? Math.max(ST - K, 0) : Math.max(K - ST, 0);
    cash += delta * ST - Math.abs(delta) * ST * cost;
    return (cash - payoff) / S0;
  }
  // monthly short ATM call on real closes, priced at trailing realised vol + markup
  function hedgeBacktest(closes, { markup = 0, cost = 0.00078, every = 1, days = 21, r = 0.06, q = 0.013, kind = "call" } = {}) {
    const out = [];
    for (let s = days; s < closes.length - days; s += days) {
      const path = closes.slice(s, s + days + 1);
      const sigImp = realisedVol(closes, s - days, s) + markup;
      const sigReal = realisedVol(closes, s, s + days);
      const T = days / 252;
      out.push({ i: s, sigImp, sigReal, pnl: hedgePnl(path, path[0], T, r, sigImp, kind, q, every, cost),
        premium: bsPrice(path[0], path[0], T, r, sigImp, kind, q) / path[0] });
    }
    return out;
  }
  function gbmPath(S0, T, mu, sig, steps, g, q = 0) {
    const dt = T / steps, p = new Float64Array(steps + 1);
    p[0] = S0;
    for (let i = 1; i <= steps; i++) p[i] = p[i - 1] * Math.exp((mu - q - 0.5 * sig * sig) * dt + sig * Math.sqrt(dt) * g.normal());
    return p;
  }

  // ---------- trend rules ----------
  function movingAvg(px, n, kind) {
    const out = new Float64Array(px.length).fill(NaN);
    if (n === 1) { out.set(px); return out; }
    if (kind === "SMA") {
      let s = 0;
      for (let i = 0; i < px.length; i++) {
        s += px[i];
        if (i >= n) s -= px[i - n];
        if (i >= n - 1) out[i] = s / n;
      }
    } else {
      const a = 2 / (n + 1);
      let y = px[0];
      for (let i = 0; i < px.length; i++) {
        y = i === 0 ? px[0] : (1 - a) * y + a * px[i];
        if (i >= n - 1) out[i] = y;
      }
    }
    return out;
  }
  // long/flat crossover, traded the day after the signal; returns daily strategy returns
  function runRule(px, ret, fast, slow, kind, buy, sell, cashD, warmup) {
    const f = movingAvg(px, fast, kind), s = movingAvg(px, slow, kind), n = px.length;
    const r = [], pos = [];
    let prevPos = 0, prevSig = 0;
    for (let i = 0; i < n; i++) {
      const p = i === 0 ? 0 : prevSig;
      const d = i === 0 ? 0 : p - prevPos;
      const c = d > 0 ? d * buy : -d * sell;
      if (i >= warmup) { r.push(p * ret[i] + (1 - p) * cashD - c); pos.push(p); }
      prevSig = f[i] > s[i] ? 1 : 0;
      prevPos = p;
    }
    return { r, pos };
  }
  function perfStats(r, rf) {
    const n = r.length;
    let eq = 1, peak = 1, mdd = 0, m = 0;
    for (const x of r) { eq *= 1 + x; peak = Math.max(peak, eq); mdd = Math.min(mdd, eq / peak - 1); m += x; }
    m /= n;
    let v = 0;
    for (const x of r) v += (x - m) ** 2;
    const vol = Math.sqrt(v / (n - 1)) * Math.sqrt(252);
    return { CAGR: Math.pow(eq, 252 / n) - 1, Sharpe: (m * 252 - rf) / vol, MaxDD: mdd };
  }

  const QL = { erfc, normCdf, normPdf, rng, bsPrice, bsGreeks, binomialPrice, mcPrice, impliedVol,
    realisedVol, hedgePnl, hedgeBacktest, gbmPath, movingAvg, runRule, perfStats };
  if (typeof module !== "undefined" && module.exports) module.exports = QL;
  else root.QL = QL;
})(typeof globalThis !== "undefined" ? globalThis : this);
