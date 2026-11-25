# Putting this portfolio on your resume

Every number here comes from the code in this repo. If you re-run on newer data,
update the numbers.

## Option A: one combined entry (best if space is tight)

**NSE Quant Research** · Python, NumPy, pandas, SciPy, JavaScript · github.com/&lt;you&gt;/nse-quant-research

- Built option pricing (Black-Scholes, binomial tree, Monte Carlo with variance
  reduction), Value at Risk, pairs-trading and trend-following libraries from
  scratch, with 53 unit tests and CI, using real NSE trading costs.
- Backtested 271 months of delta-hedged Nifty options and showed the P&L tracks
  the implied-vs-realised volatility gap (correlation 0.63). Vectorised the
  backtest for a 200x speed-up with identical results.
- Showed that standard methods fail out of sample: 99% VaR was breached at 3x
  its stated rate, none of 18 cointegrated pairs stayed cointegrated, and the
  50/200 moving-average crossover ranked 67th of 70 rules.
- Built an interactive browser dashboard that reruns the backtests live, with
  its JavaScript maths verified against the Python to 6 decimal places.

## Option B: two entries (best for quant, risk or trading roles)

**Option Pricing and Delta-Hedging Engine** · Python, NumPy, SciPy

- Implemented Black-Scholes, binomial (European and American) and Monte Carlo
  pricers with analytic Greeks and an implied-volatility solver, cross-validated
  by 36 unit tests.
- Cut Monte Carlo error 5x with antithetic and control variates (about 28x
  fewer simulations for the same accuracy).
- Backtested 271 monthly delta-hedged Nifty options with NSE futures costs.
  Selling at recent realised volatility lost 0.13% of spot a month, and hedging
  costs, not volatility, turned the trade negative. Vectorised the backtest for
  a 200x speed-up.

**Risk and Systematic Strategy Research, Indian Equities** · Python, pandas

- Backtested Monte Carlo VaR over 260 months of Nifty data. The 99% VaR was
  breached at 3x its stated rate (March 2020: -26% vs a -9% forecast), and
  volatility regimes, not fat tails, explained the misses.
- Tested 69 same-sector Nifty pairs for cointegration and traded them out of
  sample with futures costs. None of the 18 cointegrated pairs held up, and
  returns fell from 10.9% to 4.7% a year.
- Ran a walk-forward study of 70 SMA/EMA crossover rules. The famous 50/200
  ranked 67th, and in-sample winners trailed buy and hold out of sample.

## Skills line

Python (NumPy, pandas, SciPy, pytest), JavaScript, Monte Carlo simulation,
derivatives pricing, Greeks, Value at Risk, time-series econometrics (OLS, ADF,
cointegration), backtesting, vectorisation, CI.

## Where the dashboard link goes

The claude.ai link is private to you. For your resume, host the dashboard
publicly: push this repo, run `make dashboard`, and serve `dashboard/` with
GitHub Pages. Then put the Pages URL next to the project title, or as
"Live demo: …" on the first bullet line.

## Tips

- Lead with the result, not the tool. "Showed VaR breached 3x its stated rate"
  beats "Used Python to compute VaR".
- Keep the numbers. Interviewers ask about them, so use the cheat sheet in
  INTERVIEW_GUIDE.md.
- Don't claim anything you can't explain. Read INTERVIEW_GUIDE.md and run
  `make reproduce` yourself before the interview.
