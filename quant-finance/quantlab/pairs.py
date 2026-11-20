"""Pairs trading: Engle-Granger cointegration, z-score strategy, sector universe."""
from __future__ import annotations

import numpy as np
import pandas as pd

from .stats import adf_stat, ols



ENTRY_Z, EXIT_Z = 2.0, 0.0


LOOKBACK = 60


EG_CRIT = {"1%": -3.90, "5%": -3.34, "10%": -3.04}


CRIT_5 = -3.34


SECTORS = {
    "Private banks": ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK"],
    "Banks (incl. PSU)": ["SBIN", "ICICIBANK", "HDFCBANK", "AXISBANK"],
    "IT services": ["TCS", "INFY", "HCLTECH", "WIPRO", "TECHM"],
    "Autos": ["MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO", "HEROMOTOCO", "EICHERMOT"],
    "Metals": ["TATASTEEL", "JSWSTEEL", "HINDALCO"],
    "Pharma": ["SUNPHARMA", "CIPLA", "DRREDDY"],
    "FMCG": ["HINDUNILVR", "ITC", "NESTLEIND", "TATACONSUM"],
    "NBFC / insurance": ["BAJFINANCE", "BAJAJFINSV", "SHRIRAMFIN", "HDFCLIFE", "SBILIFE"],
    "Power / PSU energy": ["NTPC", "POWERGRID", "COALINDIA", "ONGC"],
    "Cement / materials": ["ULTRACEMCO", "GRASIM", "ASIANPAINT"],
}


def eg(a, b):
    coef, resid, _ = ols(np.log(a.values), np.log(b.values))   # log prices
    return adf_stat(resid), coef


def leg_cost(exposure, buy, sell):
    d = exposure.diff().fillna(exposure)
    return d.clip(lower=0) * buy + (-d).clip(lower=0) * sell


def backtest(px, beta, alpha, buy, sell):
    a, b = px.iloc[:, 0], px.iloc[:, 1]
    spread = a - beta * b - alpha
    z = (spread - spread.rolling(LOOKBACK).mean()) / spread.rolling(LOOKBACK).std()

    pos = np.zeros(len(z))  # +1 = long spread (long A, short B), -1 = short spread
    for t in range(1, len(z)):
        prev, zt = pos[t - 1], z.iloc[t]
        if np.isnan(zt):
            pos[t] = 0
        elif prev == 0:
            pos[t] = -1 if zt > ENTRY_Z else (1 if zt < -ENTRY_Z else 0)
        elif (prev == 1 and zt >= EXIT_Z) or (prev == -1 and zt <= EXIT_Z):
            pos[t] = 0
        else:
            pos[t] = prev
    pos = pd.Series(pos, index=z.index).shift(1).fillna(0)  # trade next day

    gross = a + beta * b                      # split capital in hedge-ratio proportion
    wa, wb = (a / gross).shift(1), (beta * b / gross).shift(1)
    exp_a, exp_b = (pos * wa).fillna(0), (-pos * wb).fillna(0)
    pnl = exp_a * a.pct_change().fillna(0) + exp_b * b.pct_change().fillna(0)
    costs = leg_cost(exp_a, buy, sell) + leg_cost(exp_b, buy, sell)
    return (pnl - costs).fillna(0), pos, costs.sum()


def summary_line(r, rf):
    ann, vol = r.mean() * 252, r.std() * np.sqrt(252)
    eq = (1 + r).cumprod()
    dd = (eq / eq.cummax() - 1).min()
    sharpe = (ann - rf) / vol if vol else 0
    return f"return {ann:6.1%}  vol {vol:5.1%}  Sharpe {sharpe:5.2f}  maxDD {dd:6.1%}"
