"""Celery tasks for fetching SEC filings and triggering the agent pipeline."""
from __future__ import annotations

import asyncio
import uuid
from datetime import date
from typing import Any

from app.data.edgar import EDGARClient, list_recent_filings
from app.data.xbrl import parse_company_facts
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.filing_repo import FilingRepository
from app.db.repositories.financial_fact_repo import FinancialFactRepository
from app.db.session import AsyncSessionLocal
from app.tasks.celery_app import celery
from app.utils.logger import get_logger

log = get_logger(__name__)


def _parse_date(s: str | None) -> date | None:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        return None


async def _ingest_async(
    ticker: str, filing_types: tuple[str, ...] = ("10-K", "10-Q")
) -> dict[str, Any]:
    fetched = 0
    new_filing_ids: list[str] = []

    async with EDGARClient() as edgar:
        async with AsyncSessionLocal() as session:
            company = await CompanyRepository(session).get_by_ticker(ticker)
            if company is None:
                return {"error": "company_not_found", "ticker": ticker}

            try:
                submissions = await edgar.get_company_submissions(company.cik)
            except Exception as e:  # noqa: BLE001
                log.error("edgar_submissions_failed", ticker=ticker, error=str(e))
                return {"error": f"edgar: {e}", "ticker": ticker}

            recent = list_recent_filings(submissions, form_types=filing_types, limit=4)
            filing_repo = FilingRepository(session)

            for entry in recent:
                accession = entry["accession_number"]
                if await filing_repo.get_by_accession(accession) is not None:
                    continue
                try:
                    text = await edgar.get_filing_document(company.cik, accession)
                except Exception as e:  # noqa: BLE001
                    log.warning(
                        "edgar_document_failed",
                        ticker=ticker,
                        accession=accession,
                        error=str(e),
                    )
                    continue

                filing = await filing_repo.create(
                    {
                        "company_id": company.id,
                        "filing_type": entry["filing_type"],
                        "accession_number": accession,
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
                new_filing_ids.append(str(filing.id))
                fetched += 1

            # Structured financials, read straight from XBRL rather than
            # inferred from the document text. One extra request per company
            # returns every value the filer has ever tagged.
            #
            # Deliberately independent of the loop above: companyfacts failing
            # must not discard filings that were fetched successfully, and a
            # company with no XBRL history is not an ingestion error.
            xbrl_inserted = 0
            try:
                payload = await edgar.get_company_facts(company.cik)
            except Exception as e:  # noqa: BLE001
                log.warning("edgar_companyfacts_failed", ticker=ticker, error=str(e))
            else:
                parsed = parse_company_facts(payload)
                xbrl_inserted = await FinancialFactRepository(session).bulk_upsert(
                    company.id, parsed
                )
                log.info(
                    "xbrl_facts_ingested",
                    ticker=ticker,
                    parsed=len(parsed),
                    inserted=xbrl_inserted,
                    # Re-reading the full payload each run is expected; most
                    # rows already exist and are skipped on conflict.
                    already_known=len(parsed) - xbrl_inserted,
                )

            await session.commit()

    # Kick off agent pipeline for each new filing (separate queue).
    for fid in new_filing_ids:
        extract_and_analyze.apply_async(args=[fid], queue="theses")

    return {
        "ticker": ticker,
        "filings_fetched": fetched,
        "new_filing_ids": new_filing_ids,
        "xbrl_facts_inserted": xbrl_inserted,
    }


@celery.task(bind=True, name="app.tasks.ingest_tasks.ingest_company_filings", max_retries=3)
def ingest_company_filings(
    self,
    ticker: str,
    filing_types: list[str] | None = None,
) -> dict[str, Any]:
    types = tuple(filing_types) if filing_types else ("10-K", "10-Q")
    try:
        return asyncio.run(_ingest_async(ticker, types))
    except Exception as e:  # noqa: BLE001
        log.exception("ingest_failed", ticker=ticker)
        raise self.retry(exc=e, countdown=30) from e


# Forward declaration: imported here to avoid a circular import at module load.
from app.tasks.thesis_tasks import extract_and_analyze  # noqa: E402
