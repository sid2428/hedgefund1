"""Companies API: list, detail, filings, ingest trigger."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentJob
from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.filing_repo import FilingRepository
from app.db.session import get_db
from app.schemas.company import CompanyListResponse, CompanyResponse
from app.schemas.filing import FilingListResponse, FilingResponse

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
