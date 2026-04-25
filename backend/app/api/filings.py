"""Filings API: detail + agent pipeline trigger for a single filing."""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentJob
from app.db.repositories.filing_repo import FilingRepository
from app.db.session import get_db
from app.schemas.filing import FilingResponse

router = APIRouter()


@router.get("/{filing_id}", response_model=FilingResponse)
async def get_filing(
    filing_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> FilingResponse:
    row = await FilingRepository(session).get_by_id(filing_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Filing not found")
    return FilingResponse.model_validate(row)


@router.post("/{filing_id}/analyze", status_code=202)
async def analyze_filing(
    filing_id: uuid.UUID,
    session: AsyncSession = Depends(get_db),
) -> dict[str, str]:
    filing = await FilingRepository(session).get_by_id(filing_id)
    if filing is None:
        raise HTTPException(status_code=404, detail="Filing not found")

    job = AgentJob(
        job_type="extract_and_analyze",
        status="queued",
        payload={"filing_id": str(filing_id)},
    )
    session.add(job)
    await session.flush()

    try:
        from app.tasks.thesis_tasks import extract_and_analyze

        extract_and_analyze.apply_async(
            args=[str(filing_id), str(job.id)], queue="theses"
        )
    except Exception as e:  # noqa: BLE001
        job.status = "failed"
        job.error = f"celery_dispatch_failed: {e}"
        job.completed_at = datetime.utcnow()
        await session.flush()

    return {"job_id": str(job.id), "status": job.status}
