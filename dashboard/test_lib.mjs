// Checks the JavaScript port (lib.js) against the Python reference values that
// build_data.py wrote into data/results.json. Run: node dashboard/test_lib.mjs
import { createRequire } from "node:module";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));
const QL = createRequire(import.meta.url)(join(here, "lib.js"));
const res = JSON.parse(readFileSync(join(here, "data/results.json"), "utf8"));
const nifty = JSON.parse(readFileSync(join(here, "data/nifty.json"), "utf8"));
const ref = res.reference;
let fails = 0;
function close(name, got, want, tol) {
  const ok = Math.abs(got - want) <= tol;
  if (!ok) fails++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name}: js ${got.toPrecision(8)} python ${Number(want).toPrecision(8)}`);
}

close("BS call", QL.bsPrice(100, 100, 1, 0.05, 0.2), ref.bs_call, 1e-6);
close("BS put", QL.bsPrice(100, 100, 1, 0.05, 0.2, "put"), ref.bs_put, 1e-6);
const g = QL.bsGreeks(100, 100, 1, 0.05, 0.2, "call", 0.013);
for (const k of ["delta", "gamma", "vega", "theta", "rho"]) close(`greek ${k}`, g[k], ref.greeks_call[k], 1e-5 * Math.max(1, Math.abs(ref.greeks_call[k])));
close("binomial American put", QL.binomialPrice(100, 100, 1, 0.05, 0.2, "put", 0, 500, true), ref.binomial_american_put, 1e-9);
const mc = QL.mcPrice(100, 100, 1, 0.05, 0.2, "call", 0, 200000, 7);
close("Monte Carlo within 3 SE", mc.price, ref.bs_call, 3 * mc.se);
close("implied vol round trip", QL.impliedVol(ref.bs_call, 100, 100, 1, 0.05), 0.2, 1e-6);

const px = nifty.close;
for (const [mk, want] of Object.entries(ref.hedge)) {
  const bt = QL.hedgeBacktest(px, { markup: Number(mk) });
  const pnl = bt.map((d) => d.pnl), mean = pnl.reduce((a, b) => a + b) / pnl.length;
  close(`hedge markup ${mk} months`, bt.length, want.n, 0);
  close(`hedge markup ${mk} mean P&L`, mean, want.mean, 1e-6);
  close(`hedge markup ${mk} worst`, Math.min(...pnl), want.min, 1e-6);
}

const ret = px.map((p, i) => (i === 0 ? 0 : p / px[i - 1] - 1) + 0.013 / 252);
const [buy, sell] = res.ma_grid.costs_bps.map((x) => x / 1e4);
const cash = Math.pow(1.06, 1 / 252) - 1;
for (const [key, f, s, kind] of [["ma_sma_50_200", 50, 200, "SMA"], ["ma_ema_20_50", 20, 50, "EMA"]]) {
  const st = QL.perfStats(QL.runRule(px, ret, f, s, kind, buy, sell, cash, 250).r, 0.06);
  for (const m of ["CAGR", "Sharpe", "MaxDD"]) close(`${kind} ${f}/${s} ${m}`, st[m], ref[key][m], 2e-4);
}
console.log(fails ? `\n${fails} FAILED` : "\nall checks passed");
process.exit(fails ? 1 : 0);
