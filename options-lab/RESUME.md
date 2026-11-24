# Putting this project on your resume

## Project title

**Option Pricing and Delta-Hedging Engine**
*Python, NumPy, pandas, Matplotlib, pytest*

## Three-bullet version

- Implemented Black-Scholes, binomial-tree (European and American) and Monte Carlo
  option pricers from scratch, with analytic Greeks and an implied-volatility
  solver. Cross-validated them with 36 unit tests (put-call parity, convergence,
  finite-difference Greeks).
- Cut Monte Carlo pricing error 5x (about 28x fewer paths for the same accuracy)
  using antithetic and control variates.
- Backtested 271 monthly delta-hedged Nifty 50 options (2001-2023) with NSE futures
  costs. Showed that hedged P&L tracks the implied-vs-realised volatility gap
  (correlation 0.63) and that selling at recent realised volatility loses money
  after costs, needing about a 2-point markup to break even.

## One-bullet version

- Built Black-Scholes, binomial and variance-reduced Monte Carlo option pricers with
  Greeks and implied volatility in Python, and backtested daily delta-hedging of
  Nifty options over 22 years to measure hedging error, costs and volatility risk.

## Interview talking points

1. **Why does a delta-hedged option still make or lose money?** Hedging removes
   the direction, not the gamma. The P&L is about 0.5·Γ·S²·(σ²implied − σ²realised)
   per unit time, so you are betting on volatility.
2. **Why hedge daily and not continuously?** Each trade costs money. Hedging
   error falls like 1/√N in the number of rebalances, while cost rises roughly
   with √N, so there is an optimum.
3. **Why do control variates work so well here?** The discounted terminal price
   has a known expectation and is highly correlated with the call payoff, so
   subtracting it removes most of the noise.
4. **When does American exercise matter?** For puts, and for calls on
   dividend-paying assets. Without dividends an American call equals the
   European one, and a test checks this.
5. **What's missing?** Real option prices (India VIX or NSE option chain), a
   volatility smile, jumps (the May 2009 gap), and option-leg costs.
