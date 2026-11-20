"""Trend following: SMA/EMA crossover rules with lagged execution and costs."""
from __future__ import annotations




FAST = [1, 5, 10, 20, 30, 50, 100]


SLOW = [20, 50, 100, 150, 200, 250]


PERIODS = [("2001-2007 bull", "2001", "2007"), ("2008-2012 crash/chop", "2008", "2012"),
           ("2013-2019 grind up", "2013", "2019"), ("2020-2023 covid/V", "2020", "2023")]


def ma(px, n, kind):
    if n == 1:
        return px
    return px.rolling(n).mean() if kind == "SMA" else px.ewm(span=n, adjust=False, min_periods=n).mean()


def run_rule(px, ret, fast, slow, kind, buy, sell, cash_d, warmup):
    sig = (ma(px, fast, kind) > ma(px, slow, kind)).astype(float)
    pos = sig.shift(1).fillna(0)
    d = pos.diff().fillna(0)
    cost = d.clip(lower=0) * buy + (-d).clip(lower=0) * sell
    r = pos * ret + (1 - pos) * cash_d - cost
    return r.iloc[warmup:], pos.iloc[warmup:]
