"""Earnings call transcript fetcher (best-effort, optional for MVP).

Real transcript pipelines integrate with paid APIs (S&P, AlphaSense). For the
MVP we just provide a hook — return None gracefully and let the rest of the
pipeline proceed.
"""
from __future__ import annotations

from app.utils.logger import get_logger

log = get_logger(__name__)


async def search_transcript(ticker: str, quarter: str, year: int) -> str | None:
    """Return raw transcript text or None.

    MVP returns None; replace with a real provider when transcripts become
    important. The orchestrator never blocks on this call.
    """
    log.debug("transcript_lookup_skipped", ticker=ticker, quarter=quarter, year=year)
    return None
