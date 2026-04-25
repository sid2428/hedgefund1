"""yfinance wrapper. yfinance is sync; we offload to a thread."""
from __future__ import annotations

import asyncio

import yfinance as yf

from app.utils.logger import get_logger

log = get_logger(__name__)


async def get_current_price(ticker: str) -> float | None:
    """Latest close price for `ticker`, or None if unavailable."""
    return await asyncio.to_thread(_sync_price, ticker)


async def get_market_cap(ticker: str) -> int | None:
    """Latest market cap for `ticker`, or None."""
    return await asyncio.to_thread(_sync_market_cap, ticker)


def _sync_price(ticker: str) -> float | None:
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "fast_info", None) or {}
        price = info.get("last_price") or info.get("lastPrice")
        if price is None:
            hist = t.history(period="1d")
            if len(hist) > 0:
                price = float(hist["Close"].iloc[-1])
        return float(price) if price is not None else None
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance_price_failed", ticker=ticker, error=str(e))
        return None


def _sync_market_cap(ticker: str) -> int | None:
    try:
        t = yf.Ticker(ticker)
        info = getattr(t, "fast_info", None) or {}
        cap = info.get("market_cap") or info.get("marketCap")
        if cap is None:
            details = t.get_info() if hasattr(t, "get_info") else t.info
            cap = (details or {}).get("marketCap")
        return int(cap) if cap else None
    except Exception as e:  # noqa: BLE001
        log.warning("yfinance_marketcap_failed", ticker=ticker, error=str(e))
        return None
