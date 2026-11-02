"""Market presets and transaction-cost models (India / NSE and US).

Indian statutory charges change with budgets and SEBI/NSE circulars. The rates
below are as of Nov 2026 (post Budget 2026 STT revision, effective 1 Apr 2026).
Verify them against your broker's charges page before relying on results.
"""
from __future__ import annotations

# ---------------------------------------------------------------- India (NSE)
# All rates are fractions of traded value (0.001 = 0.1%).
INDIA_CHARGES = {
    # instrument: (STT buy, STT sell, stamp duty buy, exchange txn charge)
    "equity_delivery": (0.001, 0.001, 0.00015, 0.0000297),
    "etf":             (0.0,   0.00001, 0.00015, 0.0000297),  # equity ETFs: STT 0.001% on sell
    "futures":         (0.0,   0.0005,  0.00002, 0.0000183),  # STT 0.05% sell (Budget 2026)
}
SEBI_FEE = 0.000001      # Rs 10 per crore, both sides
GST = 0.18               # on brokerage + exchange charges + SEBI fee
BROKERAGE = 0.0          # fraction of value; discount brokers charge 0 for delivery,
                         # ~Rs 20/order for F&O (set e.g. 0.0002 to approximate)
SLIPPAGE = 0.0005        # 5 bps impact/spread per side - liquid large caps


def india_cost(instrument: str, side: str) -> float:
    """Total cost as a fraction of traded value for one side ('buy' or 'sell')."""
    stt_b, stt_s, stamp_b, txn = INDIA_CHARGES[instrument]
    taxable = BROKERAGE + txn + SEBI_FEE
    cost = taxable * (1 + GST) + SLIPPAGE
    cost += stt_b + stamp_b if side == "buy" else stt_s
    return cost


def round_trip_bps(instrument: str) -> float:
    return (india_cost(instrument, "buy") + india_cost(instrument, "sell")) * 1e4


MARKETS = {
    "in": {
        "currency": "Rs",
        "risk_free": 0.06,  # approx. 91-day T-bill yield; update as needed
        "portfolio_value": 10_000_000,  # Rs 1 crore
        "var_tickers": ["RELIANCE.NS", "HDFCBANK.NS", "TCS.NS", "INFY.NS", "ITC.NS"],
        "pair": ("HDFCBANK.NS", "ICICIBANK.NS"),
        "pair_instrument": "futures",   # overnight shorts in India need stock futures
        "trend_ticker": "NIFTYBEES.NS",  # tradable Nifty 50 ETF (^NSEI excludes dividends)
        "trend_instrument": "etf",
    },
    "us": {
        "currency": "$",
        "risk_free": 0.04,
        "portfolio_value": 1_000_000,
        "var_tickers": ["AAPL", "MSFT", "JPM", "XOM", "JNJ"],
        "pair": ("KO", "PEP"),
        "pair_instrument": None,
        "trend_ticker": "SPY",
        "trend_instrument": None,
    },
}

US_COST_BPS_PER_SIDE = 5.0


def cost_per_side(market: str, instrument: str | None, override_bps: float | None = None):
    """(buy_cost, sell_cost) as fractions of traded value."""
    if override_bps is not None:
        return override_bps / 1e4, override_bps / 1e4
    if market == "in":
        return india_cost(instrument, "buy"), india_cost(instrument, "sell")
    return US_COST_BPS_PER_SIDE / 1e4, US_COST_BPS_PER_SIDE / 1e4


if __name__ == "__main__":
    for inst in INDIA_CHARGES:
        print(f"{inst:16s} buy {india_cost(inst,'buy')*1e4:5.1f} bps  "
              f"sell {india_cost(inst,'sell')*1e4:5.1f} bps  "
              f"round trip {round_trip_bps(inst):5.1f} bps")
