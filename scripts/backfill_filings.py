"""Backfill recent SEC filings for every seeded company.

Pulls the last 4 quarters of 10-Q filings and the last 2 annual 10-K filings.
Stores raw text only; agent processing is a separate step (run scripts/demo_run.py
or POST /api/companies/{ticker}/ingest).

Usage:
  docker-compose exec backend python /scripts/backfill_filings.py [TICKER ...]
"""
from __future__ import annotations

import asyncio
import sys
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.data.edgar import EDGARClient, list_recent_filings  # noqa: E402
from app.db.repositories.company_repo import CompanyRepository  # noqa: E402
from app.db.repositories.filing_repo import FilingRepository  # noqa: E402
from app.db.session import AsyncSessionLocal  # noqa: E402
from app.utils.logger import configure_logging, get_logger  # noqa: E402

LIMIT_10K = 2
LIMIT_10Q = 4


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


async def backfill_one(edgar: EDGARClient, ticker: str) -> dict:
    fetched = 0
    skipped = 0
    async with AsyncSessionLocal() as session:
        company = await CompanyRepository(session).get_by_ticker(ticker)
        if company is None:
            return {"ticker": ticker, "error": "not_seeded"}

        try:
            submissions = await edgar.get_company_submissions(company.cik)
        except Exception as e:  # noqa: BLE001
            return {"ticker": ticker, "error": f"edgar: {e}"}

        target = (
            list_recent_filings(submissions, form_types=("10-K",), limit=LIMIT_10K)
            + list_recent_filings(submissions, form_types=("10-Q",), limit=LIMIT_10Q)
        )

        repo = FilingRepository(session)
        for entry in target:
            if await repo.get_by_accession(entry["accession_number"]) is not None:
                skipped += 1
                continue
            try:
                text = await edgar.get_filing_document(
                    company.cik, entry["accession_number"]
                )
            except Exception as e:  # noqa: BLE001
                continue
            await repo.create(
                {
                    "company_id": company.id,
                    "filing_type": entry["filing_type"],
                    "accession_number": entry["accession_number"],
                    "filed_date": _parse_date(entry["filed_date"]) or date.today(),
                    "period_of_report": _parse_date(entry.get("period_of_report")),
                    "raw_text": text,
                    "edgar_url": (
                        f"https://www.sec.gov/cgi-bin/browse-edgar?"
                        f"action=getcompany&CIK={company.cik}&type={entry['filing_type']}"
                    ),
                    "processed": False,
                }
            )
            fetched += 1
        await session.commit()

    return {"ticker": ticker, "fetched": fetched, "skipped": skipped}


async def main(argv: list[str]) -> int:
    configure_logging()
    log = get_logger("backfill")

    tickers = [t.upper() for t in argv[1:]] if len(argv) > 1 else None

    async with AsyncSessionLocal() as session:
        all_companies = await CompanyRepository(session).get_all()
    universe = [c.ticker for c in all_companies]
    if tickers:
        universe = [t for t in universe if t in tickers]
    if not universe:
        log.warning("no_companies_to_backfill")
        return 1

    log.info("backfill_start", n=len(universe))
    async with EDGARClient() as edgar:
        for ticker in universe:
            result = await backfill_one(edgar, ticker)
            log.info("backfill_company_done", **result)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv)))
