"""Statistics: OLS, ADF test, performance metrics, money formatting."""
from __future__ import annotations

import numpy as np


def ols(y, X):
    """OLS with intercept. Returns (coefs, residuals, std_errors)."""
    X = np.column_stack([np.ones(len(X)), X])
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ coef
    sigma2 = resid @ resid / (len(y) - X.shape[1])
    se = np.sqrt(np.diag(sigma2 * np.linalg.inv(X.T @ X)))
    return coef, resid, se


def adf_stat(series, lags=1):
    """Augmented Dickey-Fuller t-statistic (constant, `lags` lagged diffs)."""
    x = np.asarray(series, dtype=float)
    dx = np.diff(x)
    y = dx[lags:]
    cols = [x[lags:-1]]
    for i in range(1, lags + 1):
        cols.append(dx[lags - i:-i])
    coef, _, se = ols(y, np.column_stack(cols))
    return coef[1] / se[1]


def perf_stats(r, rf):
    if len(r) < 60:
        return dict(CAGR=np.nan, Sharpe=np.nan, MaxDD=np.nan)
    eq = (1 + r).cumprod()
    cagr = eq.iloc[-1] ** (252 / len(r)) - 1
    vol = r.std() * np.sqrt(252)
    return dict(CAGR=cagr, Sharpe=(r.mean() * 252 - rf) / vol, MaxDD=(eq / eq.cummax() - 1).min())


def summary_metrics(r, rf):
    eq = (1 + r).cumprod()
    years = len(r) / 252
    cagr = eq.iloc[-1] ** (1 / years) - 1
    vol = r.std() * np.sqrt(252)
    sharpe = (r.mean() * 252 - rf) / vol if vol else 0.0
    mdd = (eq / eq.cummax() - 1).min()
    return {"CAGR": cagr, "Vol": vol, "Sharpe": sharpe, "MaxDD": mdd, "Final x": eq.iloc[-1]}


def fmt_money(x, currency):
    """Format money; rupees in lakh/crore, otherwise plain thousands."""
    if currency == "Rs":
        if abs(x) >= 1e7:
            return f"Rs {x/1e7:,.2f} cr"
        return f"Rs {x/1e5:,.2f} lakh"
    return f"{currency}{x:,.0f}"
