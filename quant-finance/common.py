"""Shared helpers: price loading (real via yfinance, or synthetic fallback)."""
from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


def load_prices(tickers, start="2015-01-01", end=None, synthetic=False, seed=42, start_price=100):
    """Return a DataFrame of adjusted close prices, one column per ticker.

    Tries yfinance first; falls back to synthetic data if it is missing,
    offline, or `synthetic=True`.
    """
    if not synthetic:
        try:
            import yfinance as yf

            df = yf.download(list(tickers), start=start, end=end,
                             auto_adjust=True, progress=False)["Close"]
            if isinstance(df, pd.Series):
                df = df.to_frame(tickers[0])
            df = df[list(tickers)].dropna()
            if len(df) > 250:
                print(f"[data] loaded {len(df)} days of real prices from yfinance")
                return df
        except Exception as exc:  # noqa: BLE001
            print(f"[data] yfinance unavailable ({type(exc).__name__}); using synthetic data")
    return synthetic_prices(tickers, seed=seed, start_price=start_price)


def synthetic_prices(tickers, n_days=2500, seed=42, start_price=100):
    """Correlated geometric Brownian motion with a shared market factor."""
    rng = np.random.default_rng(seed)
    k = len(tickers)
    mu = rng.uniform(0.04, 0.14, k) / TRADING_DAYS
    vol = rng.uniform(0.15, 0.35, k) / np.sqrt(TRADING_DAYS)
    beta = rng.uniform(0.5, 0.9, k)
    market = rng.standard_normal(n_days)
    idio = rng.standard_normal((n_days, k))
    z = beta * market[:, None] + np.sqrt(1 - beta**2) * idio
    rets = mu - 0.5 * vol**2 + vol * z
    prices = start_price * np.exp(np.cumsum(rets, axis=0))
    idx = pd.bdate_range("2015-01-02", periods=n_days)
    print(f"[data] generated {n_days} days of synthetic prices")
    df = pd.DataFrame(prices, index=idx, columns=list(tickers))
    df.attrs["synthetic"] = True
    return df


def load_csv(path):
    """Read a price CSV with Date/Close or timestamp/close columns -> Series."""
    df = pd.read_csv(path)
    cols = {c.lower(): c for c in df.columns}
    date = df[cols.get("date", cols.get("timestamp"))].astype(str).str[:10]
    s = pd.Series(df[cols["close"]].astype(float).values, index=pd.to_datetime(date))
    return s[~s.index.duplicated()].sort_index()


def load_csv_dir(folder, tickers=None):
    """Load every <TICKER>_*.csv (or <TICKER>.csv) in a folder into one DataFrame."""
    import glob
    import os
    out = {}
    for path in sorted(glob.glob(os.path.join(folder, "*.csv"))):
        name = os.path.basename(path).split("_")[0].removesuffix(".csv")
        if tickers is None or name in tickers:
            out[name] = load_csv(path)
    df = pd.DataFrame(out)
    full = df.notna().sum() >= 0.9 * len(df)   # drop recent listings (e.g. JIOFIN)
    if (~full).any():
        print(f"[data] dropped short histories: {', '.join(df.columns[~full])}")
    return df.loc[:, full].dropna()


def fmt_money(x, currency):
    """Format money; rupees in lakh/crore, otherwise plain thousands."""
    if currency == "Rs":
        if abs(x) >= 1e7:
            return f"Rs {x/1e7:,.2f} cr"
        return f"Rs {x/1e5:,.2f} lakh"
    return f"{currency}{x:,.0f}"


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
