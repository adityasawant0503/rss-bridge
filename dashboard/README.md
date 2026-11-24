# Nifty Quant Lab (interactive dashboard)

One static web page that presents both projects:
- **Option pricer**: live Black-Scholes, binomial tree and Monte Carlo prices,
  Greeks, implied volatility and a put-call parity check.
- **Hedging lab**: re-runs the 2001-2023 Nifty delta-hedging backtest in the
  browser as you change the volatility markup, futures cost, hedge frequency and
  option type. Includes a simulated hedging-error histogram.
- **Trend explorer**: any SMA/EMA rule on Nifty, with costs and a look-ahead
  toggle, plus clickable Sharpe heatmaps of all 70 rules.
- **Value at Risk**: the monthly VaR backtest for four shock models, and the
  effect of correlation on a Rs 1 crore portfolio.
- **Pairs trading**: in-sample vs out-of-sample returns for 69 same-sector
  pairs, with a filterable table.

There's no framework and no build step: `index.html`, `lib.js` (the maths) and
two JSON data files. The charts are hand-written SVG.

## Run locally

```bash
cd dashboard && python -m http.server 8000     # then open http://localhost:8000
```

Opening `index.html` straight from disk won't work, because browsers block
`fetch()` of local files.

## How the numbers stay honest

`lib.js` is a line-for-line JavaScript port of the Python libraries in
`../options-lab` and `../quant-finance`. `build_data.py` exports the Nifty prices
and the precomputed studies, along with Python reference values. `test_lib.mjs`
checks the port against those values: prices, Greeks, the American put, Monte
Carlo, implied volatility, all 271 hedging months and two trend rules all agree
to about 6 decimal places.

```bash
python dashboard/build_data.py   # needs both projects' data/fetch_data.sh run first
node dashboard/test_lib.mjs
```

## Hosting

The folder works as-is on GitHub Pages: point Pages at this folder, or copy it
to a `gh-pages` branch.
