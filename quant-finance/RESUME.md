# Putting this project on your resume

Use whichever version fits the space. Every number below comes from the results
in README.md. Re-check them if you re-run the analysis on newer data.

## Project title

**Quantitative Strategy Research on Indian Equities**
*Python, NumPy, pandas, Matplotlib, pytest, GitHub Actions*

## Three-bullet version (most resumes)

- Built a Python library from scratch for Monte Carlo Value at Risk, pairs trading
  and trend-following backtests on NSE equities. It models India's statutory trading
  costs (STT, stamp duty, GST) and lags every signal one day so no test uses future data.
- Backtested Monte Carlo VaR over 260 months of Nifty 50 data and showed the 99% VaR
  was breached 3x more often than promised (March 2020: -26% loss vs -9% forecast).
  Comparing normal, Student-t, bootstrap and EWMA models showed volatility regimes,
  not fat tails, drive the misses.
- Tested 69 same-sector pairs for cointegration and 70 SMA/EMA crossover rules with
  walk-forward validation. Found that none of the 18 cointegrated pairs held up out
  of sample and that the 50/200 crossover ranked 67th of 70, which shows how
  in-sample results overstate performance.

## One-bullet version (tight space)

- Built and stress-tested Monte Carlo VaR, pairs-trading and moving-average strategies
  on NSE data in Python with realistic Indian trading costs and walk-forward validation.
  Showed VaR breached 3x its stated rate and that in-sample "winners" fail out of sample.

## Skills this demonstrates

Monte Carlo simulation, Cholesky decomposition, VaR / Expected Shortfall, OLS
regression, Augmented Dickey-Fuller and Engle-Granger cointegration tests, backtesting
methodology (look-ahead bias, transaction costs, walk-forward testing, multiple
testing), Python packaging, unit testing, CI.

## Interview talking points

Be ready to explain each of these in a sentence or two:

1. **Why trade one day after the signal?** The signal uses today's close, so the
   earliest you can act is tomorrow. Skipping the lag is look-ahead bias.
2. **Why did fat tails not fix VaR?** Summing 21 daily draws averages out daily fat
   tails (the central limit theorem). Crashes come from volatility regimes changing,
   which a trailing-year estimate can't see coming.
3. **Why only same-sector pairs?** Testing about 1,000 random pairs at 5%
   significance finds about 50 "cointegrated" pairs by pure chance (multiple testing).
4. **Why cost pairs as futures?** In India you can't hold a short in the cash
   market overnight, so the short leg has to be a stock future (STT 0.05% on sell
   after Budget 2026).
5. **What would you do next?** GARCH or regime-switching volatility for VaR, a
   Kalman-filter hedge ratio and stop-losses for pairs, and survivorship-free
   constituent data.

## Where to link it

Put the GitHub link next to the project title. Recruiters usually open the README
first, so the key findings table and charts sit at the top of it.
