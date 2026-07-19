"""Companies API: list, detail, filings, ingest trigger."""
from __future__ import annotations

import uuid
from datetime import date, datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.xbrl import CONCEPT_TAGS
from app.db.models import AgentJob
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.filing_repo import FilingRepository
from app.db.repositories.financial_fact_repo import FinancialFactRepository
from app.db.session import get_db
from app.schemas.company import CompanyListResponse, CompanyResponse
from app.schemas.filing import FilingListResponse, FilingResponse
from app.schemas.financials import FinancialFactResponse, FinancialSeriesResponse

router = APIRouter()


@router.get("", response_model=CompanyListResponse)
async def list_companies(
    sector: str | None = None,
    session: AsyncSession = Depends(get_db),
) -> CompanyListResponse:
    rows = await CompanyRepository(session).get_all(sector=sector)
    return CompanyListResponse(
        companies=[CompanyResponse.model_validate(c) for c in rows],
        total=len(rows),
    )


@router.get("/{ticker}", response_model=CompanyResponse)
async def get_company(
    ticker: str, session: AsyncSession = Depends(get_db)
) -> CompanyResponse:
    row = await CompanyRepository(session).get_by_ticker(ticker)
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return CompanyResponse.model_validate(row)


@router.get("/{ticker}/filings", response_model=FilingListResponse)
async def get_company_filings(
    ticker: str,
    filing_type: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    session: AsyncSession = Depends(get_db),
) -> FilingListResponse:
    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    rows = await FilingRepository(session).get_for_company(
        company.id, filing_type=filing_type, limit=limit
    )
    return FilingListResponse(
        filings=[FilingResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{ticker}/financials/{concept}", response_model=FinancialSeriesResponse)
async def get_company_financials(
    ticker: str,
    concept: str,
    as_of: date | None = Query(
        default=None,
        description=(
            "Reconstruct the series as it was known on this date. Filters on "
            "when each value was filed, not on the period it describes, so "
            "restatements published later are correctly excluded. "
            "Defaults to today."
        ),
    ),
    basis: str = Query(
        default="as_reported",
        pattern="^(as_reported|all)$",
        description=(
            "'as_reported' keeps the figure originally published for each "
            "period — the number the market actually had. 'all' returns every "
            "filed version, including restatements."
        ),
    ),
    unit: str | None = Query(default=None, description="e.g. USD, shares."),
    session: AsyncSession = Depends(get_db),
) -> FinancialSeriesResponse:
    """A financial series for one company, reconstructed at a point in time.

    Values come from XBRL as filed, not from model extraction.
    """
    if concept not in CONCEPT_TAGS:
        raise HTTPException(
            status_code=404,
            detail=f"Unknown concept. Known concepts: {sorted(CONCEPT_TAGS)}",
        )

    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    cutoff = as_of or date.today()
    repo = FinancialFactRepository(session)
    read = repo.as_reported_series if basis == "as_reported" else repo.series
    rows = await read(company.id, concept, as_of=cutoff, unit=unit)

    return FinancialSeriesResponse(
        ticker=company.ticker,
        concept=concept,
        as_of=cutoff,
        basis=basis,
        facts=[FinancialFactResponse.model_validate(r) for r in rows],
        total=len(rows),
    )


@router.get("/{ticker}/financials", response_model=list[str])
async def list_company_concepts(
    ticker: str, session: AsyncSession = Depends(get_db)
) -> list[str]:
    """Concepts with at least one stored value for this company."""
    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return await FinancialFactRepository(session).concepts_for(company.id)


@router.post("/{ticker}/ingest", status_code=202)
async def ingest_company(
    ticker: str,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    """Queue a Celery ingest task. Returns the AgentJob id for polling."""
    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    job = AgentJob(
        job_type="ingest_filing",
        status="queued",
        payload={"ticker": ticker.upper()},
    )
    session.add(job)
    await session.flush()
    job_id = str(job.id)

    # Defer the import: Celery may not be available in test contexts.
    try:
        from app.tasks.ingest_tasks import ingest_company_filings

        ingest_company_filings.apply_async(args=[ticker.upper()], queue="filings")
    except Exception as e:  # noqa: BLE001
        # If Celery isn't reachable, mark the job failed but still return 202
        # so the client can see the error in /api/jobs/{id}.
        job.status = "failed"
        job.error = f"celery_dispatch_failed: {e}"
        job.completed_at = datetime.utcnow()
        await session.flush()

    return {"job_id": job_id, "status": job.status}
