"""Jobs API: poll the status of any AgentJob."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import AgentJob
from app.db.session import get_db
from app.schemas.graph import JobStatusResponse

router = APIRouter()


@router.get("/{job_id}", response_model=JobStatusResponse)
async def get_job(
    job_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> JobStatusResponse:
    job = await session.get(AgentJob, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    return JobStatusResponse(
        id=str(job.id),
        job_type=job.job_type,
        status=job.status,
        payload=job.payload,
        result=job.result,
        error=job.error,
    )
