# Interview guide: explaining NSE Quant Research

Read this once fully, then use the **pitches** and **cheat sheet** before each
interview. Each concept is explained in plain words first, then in the precise
terms an interviewer will expect.

---

## 1. The pitches

### 30 seconds (what you say when they ask "tell me about this project")

> "I built a set of quant tools from scratch for Indian equities: option
> pricing, Value at Risk, pairs trading and trend following. All of them use
> real NSE data and real trading costs. The main thing I learned is that most
> textbook methods look good in-sample and fail out of sample. For example, my
> 99% VaR broke three times as often as it should, and none of my cointegrated
> pairs stayed cointegrated. I also built an interactive dashboard that reruns
> the backtests in the browser, and I checked its maths against the Python to
> six decimal places."

### 2 minutes (when they say "walk me through it")

1. **Motivation.** I wanted to learn quant finance by building the core tools
   myself and testing them honestly, not by trusting library outputs.
2. **Risk.** Monte Carlo VaR on a five-stock portfolio. Then I backtested the
   VaR over 260 months of Nifty data and found it breaks 3x too often, mostly
   in clusters like 2008 and March 2020.
3. **Strategies.** Pairs trading with cointegration, and moving-average
   crossovers. Both looked fine in-sample and faded out of sample once I added
   NSE costs and a one-day trading lag.
4. **Options.** Three pricers that check each other (Black-Scholes, binomial
   tree, Monte Carlo), the Greeks, implied volatility, and a 22-year
   delta-hedging backtest. It showed that hedged option P&L is really a bet on
   implied versus realised volatility.
5. **Engineering.** Installable packages, 53 tests, CI, a vectorised backtest
   that's 200x faster, and a dashboard whose JavaScript I verified against
   the Python.

---

## 2. Project 1: Monte Carlo Value at Risk

### The idea in plain words
You hold ₹1 crore of stocks. How much could you lose in a bad month? You can't
see the future, so you **simulate 10,000 possible futures** and look at the
worst ones.

### How it works
1. Compute daily **log returns** for each stock.
2. Estimate each stock's **average return** and **volatility** (standard
   deviation of returns), plus the **correlation** between every pair of stocks.
3. Turn independent random numbers into **correlated** random numbers using a
   **Cholesky decomposition** of the covariance matrix.
   - *Plain words:* Cholesky is like a square root for matrices. If Σ = L·Lᵀ,
     then multiplying independent shocks by L gives shocks with exactly the
     covariance Σ.
4. Simulate 21 trading days, 10,000 times, and compound each path into a
   one-month portfolio return.
5. **VaR at 95%** = the loss you exceed only 5% of the time, the 5th percentile
   of the simulated P&L.
6. **Expected Shortfall (ES)** = the *average* loss in that worst 5%.

### VaR vs Expected Shortfall (asked very often)
- VaR tells you where the bad tail **starts**. ES tells you how bad it is
  **on average once you're in it**.
- ES is "coherent": diversifying never increases it. VaR can break that rule.
- Basel III / FRTB moved bank capital rules from VaR to ES (97.5%) for this
  reason.

### What I found
- **Correlation drives risk.** Five stocks, ₹1 crore, one-month 95% VaR:
  - ₹3.9 lakh with zero correlation
  - **₹5.9 lakh at the real correlation** (ES ₹7.4 lakh)
  - ₹9.5 lakh with perfect correlation

  Same stocks, same volatilities; only correlation changed.
- **Correlations rise in bad times:** 0.24 in calm quarters, 0.34 in volatile
  ones. Diversification shrinks exactly when you need it.
- **The VaR backtest.** Every month from 2002 to 2023 I refitted the model on
  the past year and checked next month:
  - The 99% VaR was breached **3.1%** of months (8 of 260), against the 1% promised.
  - **March 2020: -25.9% actual vs a -9.2% forecast.**
  - Student-t (fat-tailed) shocks didn't help over a month: adding up 21 daily
    shocks averages the fat tails out (the central limit theorem).
  - EWMA, which weights recent days more, was **worse** (10.4% breaches at 95%):
    markets are often calm right before a crash, so the model lowers its VaR at
    the wrong time.
- **Conclusion:** the real problem is **volatility regimes**, not the shape of
  the distribution. Use VaR as a minimum estimate of loss, and add stress tests
  (2008, March 2020).

### If they push deeper
- *How would you test VaR formally?* Kupiec's proportion-of-failures test
  checks the breach count. Christoffersen's test also checks whether breaches
  cluster (mine do).
- *Improvement?* A GARCH volatility model, a regime-switching model, or
  filtered historical simulation.

---

## 3. Project 2: Pairs trading (statistical arbitrage)

### The idea in plain words
Two stocks that are economically tied, like HDFC Bank and ICICI Bank, should
move together. When the gap between them gets unusually wide, bet that it
closes: **short the expensive one, buy the cheap one.**

### Correlation vs cointegration (the key interview question)
- **Correlation:** the *daily moves* go the same way. Two stocks can be highly
  correlated and still drift apart forever.
- **Cointegration:** a *combination of the price levels* (A − β·B) is
  **stationary**, meaning it keeps returning to an average. That's what you
  need for pairs trading.
- *Analogy:* a drunk person and their dog. Each wanders randomly, but the leash
  keeps the distance between them stable. The leash is cointegration.

### How it works
1. **Formation period** (Oct 2020 – Sep 2023): regress A on B. The slope β is
   the **hedge ratio**.
2. **Engle-Granger test:** run an **ADF (Augmented Dickey-Fuller) test** on the
   regression residuals (the spread). ADF tests whether a series has a "unit
   root" (a random walk). Rejecting that means the spread mean-reverts.
   - Critical value about **-3.34** at 5%. This is stricter than a normal ADF
     test because β was estimated from the same data.
3. **Trading:** z-score = (spread − 60-day mean) / 60-day standard deviation.
   - Enter when |z| > 2.
   - Exit when z crosses 0.
   - Trade the day **after** the signal.
4. **India-specific:** you can't hold a cash-market short overnight in India,
   so both legs are costed as **stock futures**, with STT of 0.05% on sells
   after Budget 2026.

### What I found
- I tested **69 same-sector pairs** and 18 passed, against about 3.5 expected
  by pure chance.
  - I restricted the search to same-sector pairs to limit **multiple testing**.
    Testing about 1,000 random pairs at 5% would give about 50 false positives.
- **None of the 18 were still cointegrated** in the next two years.
- Average return fell from **10.9% to 4.7%** a year, and only 6 of 18 beat the
  6% risk-free rate.
- Without a stop-loss, a broken pair is a disaster: Hero MotoCorp / Tata Motors
  lost **52% a year**.
- *Be honest about this:* two years of data gives the ADF test little power,
  so "not cointegrated" partly means "can't prove it". But every relationship
  weakened.

### Improvements to mention
A Kalman filter (time-varying hedge ratio), the half-life of mean reversion,
stop-losses, and re-testing every quarter.

---

## 4. Project 3: Trend following (moving-average crossovers)

### The idea in plain words
Hold the index while it's trending up: when the short-term average price is
above the long-term average. Otherwise sit in cash.

### SMA vs EMA
- **SMA** (simple moving average) weights the last N days equally.
- **EMA** (exponential moving average) gives recent days more weight, so it
  reacts faster.
- *Result:* EMA was slightly better on average (Sharpe 0.57 vs 0.54). **The
  lookback length matters much more than the type of average.**

### The three testing rules (this is the real skill)
1. **Lag the signal one day.** You only know today's close after the market
   closes, so you can trade tomorrow at the earliest. Skipping this is
   **look-ahead bias**. The dashboard has a checkbox that shows the effect.
2. **Include costs.** ETF round trip about 12 bps. Delivery equity about
   32 bps, driven by STT of 0.1% on both buy and sell.
3. **Compare against buy and hold, then test out of sample.** Choose the best
   rule on 2002-2012, then see how it does on 2013-2023 (**walk-forward**).

### What I found (Nifty 50, 2002-2023, 70 rules)
- Buy and hold: 16.4% a year, Sharpe 0.54, worst drawdown **-59%** (2008).
- Best in-sample: price vs 50-day SMA, 18.4% a year, Sharpe 0.85.
- **The famous 50/200 cross ranked 67th of 70** (Sharpe 0.41). It's too slow.
- **Out of sample, no rule beat buy and hold on return** (11-13% vs 14.3%).
  What they did reliably was **cut crashes**: worst drawdown -11% to -21% vs
  -38%.
- On individual stocks, delivery costs made crossovers lose to buy and hold
  by about 7% a year.
- **Conclusion:** a trend filter is a risk-management tool, not a source of
  extra return.

### Sharpe ratio (be ready to define it)
Sharpe = (annual return − risk-free rate) / annual volatility.

I use 6% for the Indian risk-free rate. That's a high bar: a strategy earning
8% a year is barely beating T-bills.

---

## 5. Project 4: Options (options-lab)

### Black-Scholes in plain words
The fair price of an option is the cost of a **portfolio of the stock and cash
that copies its payoff**. If you can copy it, the price can't be anything else,
or there's free money. You only need **one unknown input: volatility**.

**Formula (call):** C = S·e^(−qT)·N(d1) − K·e^(−rT)·N(d2), where
- d1 = [ln(S/K) + (r − q + σ²/2)·T] / (σ√T)
- d2 = d1 − σ√T

**Assumptions:**
- the stock follows a lognormal random walk (geometric Brownian motion)
- volatility and interest rates are constant
- you can trade continuously, with no costs
- no jumps

Real markets break every one of these. That's why the hedging study is
interesting.

### Example from the dashboard
Nifty at 24,000, a 24,000 call, 30 days to expiry, 14% volatility, r = 6%,
q = 1.3%:
- price **₹431**
- delta **0.55**
- theta **−₹7.97 a day**
- vega **₹27 per volatility point**

### The Greeks (know each one in one sentence)
| Greek | Meaning | ATM 30-day example |
|---|---|---|
| **Delta** | How much the option moves per ₹1 move in the index. Also the hedge ratio. | 0.55: a 50-point Nifty move ≈ ₹27 |
| **Gamma** | How fast delta changes. Highest at-the-money near expiry. | Why you have to re-hedge |
| **Vega** | Value change per 1 point of volatility | ₹27 |
| **Theta** | Value lost per day from time passing | −₹8 a day |
| **Rho** | Sensitivity to interest rates | Small for short options |

### Three pricers and why
- **Binomial tree:** the price moves up or down each step, and you work
  backwards from expiry. It handles **American** options (early exercise).
  Error shrinks like 1/steps (under 0.001 at 2,000 steps).
- **Monte Carlo:** simulate many final prices, average the discounted payoffs.
  Flexible for complex payoffs, but noisy: the error shrinks like 1/√paths.
- **Variance reduction:**
  - *Antithetic variates* pair each random draw z with −z.
  - A *control variate* subtracts something correlated with a known average
    (the discounted final price).
  - Together they cut the error from 0.046 to **0.0088** at 100,000 paths.
    That's **5x more accurate, or about 28x fewer paths** for the same accuracy.
  - A bug story to tell: my first version combined the two tricks in the
    wrong order and was *worse* than using one. A test caught it.
- **Why three?** If they agree, the code is probably right. The tests check
  Hull's textbook prices, put-call parity and that every Greek matches a
  finite difference.

### Put-call parity
C − P = S·e^(−qT) − K·e^(−rT).

A call minus a put with the same strike is the same as owning the stock
forward. Holds without any model.

### Implied volatility
The market gives you the price; you solve the Black-Scholes formula backwards
for σ. I used Newton-Raphson (which uses vega as the slope), with a bisection
fallback. Implied volatility is how traders quote options. In India, **India
VIX** is the implied volatility of Nifty options.

### Delta hedging: the main insight
- Sell an option and hold delta units of Nifty futures, so small index moves
  don't hurt you. Re-hedge daily as delta changes.
- **You've removed the direction, not the volatility.** Each day:
  - you *collect* theta (time decay);
  - you *lose* on gamma when the index moves a lot.
- They balance exactly when realised volatility equals the volatility you sold at.
- **Formula to know:** daily P&L of a short, delta-hedged option is roughly
  ½·Γ·S²·(σ²_implied·dt − (ΔS/S)²).
- In plain words: **you profit if the market moves less than the volatility
  you sold, and lose if it moves more.**

### What I found (271 months, Nifty 2001-2023, daily hedging with futures)
- Selling at recent realised volatility: **−0.13% of spot a month**, winning
  only 33% of months.
  - Without costs it would be **+0.06%**, so hedging costs (0.19% a month)
    decide the outcome.
- Hedged P&L correlates **0.63** with the gamma formula above. The theory
  works on real data.
- **Break-even needs selling about 1-2 volatility points above** recent
  realised volatility (+1 pt: −0.02%, +2 pts: +0.08% a month).
- Worst month: **May 2009 election-result gap, −4.7%**. Overnight jumps can't
  be hedged.
- Hedge frequency on real data:

  | Hedging | Monthly P&L volatility | Worst month |
  |---|---|---|
  | Daily | 1.0% | −4.7% |
  | Weekly | 1.5% | −9.1% |
  | Never | 2.3% | −11.6% |

  In simulation, hedging error falls like 1/√(rebalances) while cost rises,
  which is a real trade-off.
- **Limitation to state upfront:** I had no historical option prices, so
  implied volatility is modelled as recent realised volatility plus a markup.
  India VIX usually sits above realised volatility, the "volatility risk
  premium", which my markup sweep estimates.

---

## 6. Engineering (for software-leaning interviewers)

- **Structure.** Two installable packages (`quantlab`, `optlab`), thin scripts,
  and tests next to the code.
- **Testing.** 53 Python tests, including cross-checks between pricers,
  finite-difference Greeks, VaR calibration on simulated data, and a test that
  changing tomorrow's price can't change today's position (no look-ahead).
- **Vectorisation.** The hedging backtest originally looped over 271 months.
  I rewrote it so all months form one matrix and hedge together. That's
  **about 200x faster** (0.29 s → 0.0014 s), and the output is byte-for-byte
  identical, which I checked against saved outputs.
- **Dashboard.** No framework and hand-written SVG charts. The maths lives in
  a separate `lib.js`, and a Node test checks it against values exported from
  Python (22 checks, matching to about 6 decimal places).
- **Reproducibility.**
  - `make setup && make data && make reproduce` rebuilds everything.
  - CI runs lint and all the tests.
  - Data is downloaded, not committed, because the source has no licence.

---

## 7. Likely questions and good answers

**Why did you choose these projects?**
They cover the three core areas of quant work: risk (VaR), strategies (pairs
and trend) and derivatives (options). Each one teaches a testing lesson.

**What was the hardest part?**
Making the backtests honest: the one-day lag, real Indian costs, and
out-of-sample tests. Without them every strategy looked profitable.

**What surprised you most?**
That the option P&L matched the textbook gamma formula on real data
(correlation 0.63), and that transaction costs, not volatility, decided
whether selling options made money.

**Is your VaR model wrong?**
It's the standard model, working as designed. The design assumes volatility
is stable, and markets switch regimes. That's why the industry adds stress
tests and moved to Expected Shortfall.

**Why log returns?**
They add up over time, which makes compounding simple. For daily moves they're
almost the same as simple returns.

**How do you avoid overfitting?**
- Test out of sample (walk-forward).
- Limit the number of things tested (same-sector pairs only).
- Report how the best in-sample rule ranks out of sample.
- Prefer robust conclusions ("trend filters reduce drawdowns") over "the best
  parameter is 47".

**Why futures for the short leg in India?**
For retail traders, a cash-market short sale has to be squared off the same day. To
hold a short overnight you need stock futures or securities lending (SLB).

**What's the volatility risk premium?**
Implied volatility usually exceeds the volatility that's later realised,
because option buyers pay for insurance. Option sellers earn it, but take
crash risk (my May 2009 month).

**American vs European options?**
American options can be exercised early. That's worth something for puts and
for calls on dividend-paying stocks. Nifty index options are European.

**What would you do next?**
- Use real option-chain data and India VIX.
- Fit a GARCH model for VaR.
- Use a Kalman filter for the pairs hedge ratio.
- Use survivorship-free index constituents.
- Model lot sizes and margin.

**Did you use AI tools?**
Answer honestly. For example: "I used an AI coding assistant to speed up the
build, the same way engineers use Copilot. But I designed the tests, I can
explain every result, and I verified the maths myself, for example the
JavaScript-to-Python check and the textbook price tests." Only say this if
it's true for you, so make sure it is: read the code and run it yourself.

---

## 8. Cheat sheet: numbers to remember

| Topic | Number |
|---|---|
| VaR backtest | 260 months; 99% VaR breached **3.1%** (promised 1%); March 2020 **−26% vs −9%** forecast |
| Correlation effect | ₹1 crore: VaR ₹3.9 L (zero) / **₹5.9 L** (actual) / ₹9.5 L (perfect) |
| Pairs | 69 tested, **18** cointegrated, **0** stayed; returns 10.9% → 4.7% |
| Trend | 70 rules; 50/200 ranked **67th**; buy and hold drawdown −59%; out of sample, filters cut −38% to −11%/−21% |
| NSE costs (round trip) | delivery **32 bps**, ETF 12 bps, futures 16 bps |
| Options check | Hull: call **10.4506**, put **5.5735** (S=K=100, T=1, r=5%, σ=20%) |
| Monte Carlo | error 0.046 → **0.0088** (5x; about 28x fewer paths) |
| Hedging | 271 months; **−0.13%** a month; costs −0.19%; corr **0.63**; break-even +1-2 vol pts |
| Engineering | **53** tests; **200x** vectorisation speed-up; JS port verified to 6 decimal places |

---

## 9. Before the interview

1. Run `make setup && make data && make test && make reproduce` yourself and
   watch the numbers appear.
2. Open the dashboard (`make serve`) and practise the demo:
   - Move volatility in the pricer and watch vega.
   - Drag the markup slider in the Hedging lab to find break-even.
   - Untick the one-day lag in the Trend explorer.
3. Practise the 30-second pitch out loud until it's natural.
4. Pick one function you can walk through line by line, for example
   `hedge_pnl` in `options-lab/optlab/hedging.py`. Interviewers often ask you
   to explain one piece of code in depth.
