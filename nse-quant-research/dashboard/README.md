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

`.github/workflows/pages.yml` publishes the dashboard automatically on every
push to `main`. It downloads the data, rebuilds the JSON, re-runs the JS check,
and `build_site.sh` wraps the page into a standalone site. To switch it on once,
go to the repo's Settings → Pages → Source and choose "GitHub Actions". The site
then appears at `https://<username>.github.io/<repo>/`.

`data/` is not committed, because `nifty.json` repackages a third-party dataset
with no stated licence. The workflow regenerates it on every build.
