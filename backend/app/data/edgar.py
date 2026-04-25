"""SEC EDGAR REST + full-text search client.

EDGAR is free but enforces 10 req/sec and requires a User-Agent identifying the
caller (see EDGAR ToS). This client centralizes:
  - rate limiting
  - retries
  - headers
  - HTML stripping for filing documents
"""
from __future__ import annotations

import re
from typing import Any

import httpx
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.utils.logger import get_logger
from app.utils.rate_limiter import RateLimiter

log = get_logger(__name__)


def _format_cik(cik: str | int) -> str:
    """EDGAR submissions API expects CIK zero-padded to 10 digits."""
    return str(cik).lstrip("0").zfill(10)


def _format_accession(accession_number: str) -> str:
    """Convert '0001045810-24-000123' -> '000104581024000123'."""
    return accession_number.replace("-", "")


class EDGARClient:
    """Async EDGAR client. Use as an async context manager."""

    def __init__(
        self,
        user_agent: str | None = None,
        timeout: float = 30.0,
        rate_limit_rps: float | None = None,
    ) -> None:
        self.user_agent = user_agent or settings.EDGAR_USER_AGENT
        self.headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json, text/html, */*",
            "Accept-Encoding": "gzip, deflate",
            "Host": "data.sec.gov",
        }
        self.base_url = settings.EDGAR_BASE_URL
        self.search_url = settings.EDGAR_SEARCH_URL
        self._rate_limiter = RateLimiter(
            rate_limit_rps if rate_limit_rps is not None else settings.EDGAR_RATE_LIMIT_RPS
        )
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout),
            headers={"User-Agent": self.user_agent, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=True,
        )

    async def __aenter__(self) -> "EDGARClient":
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        await self._client.aclose()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=10),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.RemoteProtocolError)),
        reraise=True,
    )
    async def _get(self, url: str, *, json_response: bool = False) -> Any:
        await self._rate_limiter.acquire()
        log.debug("edgar_request", url=url)
        try:
            resp = await self._client.get(url)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            log.warning(
                "edgar_http_error",
                url=url,
                status=e.response.status_code,
                body=e.response.text[:300],
            )
            raise
        return resp.json() if json_response else resp.text

    # ----- High-level API ------------------------------------------------
    async def get_company_submissions(self, cik: str | int) -> dict[str, Any]:
        url = f"{self.base_url}/submissions/CIK{_format_cik(cik)}.json"
        return await self._get(url, json_response=True)

    async def get_company_facts(self, cik: str | int) -> dict[str, Any]:
        """XBRL company facts: structured financials across all reported periods."""
        url = f"{self.base_url}/api/xbrl/companyfacts/CIK{_format_cik(cik)}.json"
        return await self._get(url, json_response=True)

    async def get_filing_index(
        self, cik: str | int, accession_number: str
    ) -> dict[str, Any]:
        """Fetch the JSON filing index, which lists all documents in a filing."""
        clean = _format_accession(accession_number)
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(_format_cik(cik))}/{clean}/index.json"
        )
        await self._rate_limiter.acquire()
        # The Archives endpoint requires a different Host header.
        resp = await self._client.get(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov",
            },
        )
        resp.raise_for_status()
        return resp.json()

    async def get_filing_document(
        self, cik: str | int, accession_number: str
    ) -> str:
        """Fetch the primary document of a filing as plain text."""
        index = await self.get_filing_index(cik, accession_number)
        items = index.get("directory", {}).get("item", [])
        primary = self._select_primary_document(items)
        if primary is None:
            raise ValueError(f"No primary document found for {accession_number}")
        clean = _format_accession(accession_number)
        url = (
            f"https://www.sec.gov/Archives/edgar/data/"
            f"{int(_format_cik(cik))}/{clean}/{primary}"
        )
        await self._rate_limiter.acquire()
        resp = await self._client.get(
            url,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "www.sec.gov",
            },
        )
        resp.raise_for_status()
        body = resp.text
        if primary.lower().endswith((".htm", ".html")):
            return self.extract_text_from_html(body)
        return body

    @staticmethod
    def _select_primary_document(items: list[dict[str, Any]]) -> str | None:
        """Pick the primary 10-K/10-Q/8-K document from a filing's index."""
        if not items:
            return None
        # Prefer .htm/.html files that look like the primary submission.
        candidates = [
            i["name"]
            for i in items
            if isinstance(i, dict)
            and i.get("name", "").lower().endswith((".htm", ".html"))
        ]
        if not candidates:
            return items[0].get("name")
        # Heuristic: shortest filename is usually the primary doc.
        candidates.sort(key=len)
        return candidates[0]

    async def search_filings(
        self,
        query: str,
        form_type: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any]:
        """EDGAR full-text search."""
        params: dict[str, str] = {"q": query}
        if form_type:
            params["forms"] = form_type
        if date_from:
            params["dateRange"] = "custom"
            params["startdt"] = date_from
        if date_to:
            params["enddt"] = date_to

        await self._rate_limiter.acquire()
        resp = await self._client.get(
            self.search_url,
            params=params,
            headers={
                "User-Agent": self.user_agent,
                "Accept-Encoding": "gzip, deflate",
                "Host": "efts.sec.gov",
            },
        )
        resp.raise_for_status()
        return resp.json()

    # ----- HTML / text helpers ------------------------------------------
    @staticmethod
    def extract_text_from_html(html: str) -> str:
        """Strip HTML tags, scripts, styles, and normalise whitespace."""
        soup = BeautifulSoup(html, "lxml")
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()
        text = soup.get_text(separator="\n")
        # Collapse repeated whitespace; keep paragraph breaks.
        text = re.sub(r"[ \t]+", " ", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


# Convenience for filing list helpers ----------------------------------------
def list_recent_filings(
    submissions: dict[str, Any],
    form_types: tuple[str, ...] = ("10-K", "10-Q", "8-K"),
    limit: int = 8,
) -> list[dict[str, Any]]:
    """Pluck the most recent filings of given types from a submissions JSON."""
    recent = submissions.get("filings", {}).get("recent", {})
    forms = recent.get("form", [])
    accessions = recent.get("accessionNumber", [])
    filed_dates = recent.get("filingDate", [])
    periods = recent.get("reportDate", [])
    primary_docs = recent.get("primaryDocument", [])

    out: list[dict[str, Any]] = []
    for i, form in enumerate(forms):
        if form not in form_types:
            continue
        out.append(
            {
                "filing_type": form,
                "accession_number": accessions[i],
                "filed_date": filed_dates[i],
                "period_of_report": periods[i] or None,
                "primary_document": primary_docs[i] if i < len(primary_docs) else None,
            }
        )
        if len(out) >= limit * len(form_types):
            break
    return out
