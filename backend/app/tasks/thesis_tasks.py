"""Celery tasks that run the agent pipeline against an already-stored filing."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

from app.agents.orchestrator import PipelineOrchestrator
from app.db.session import AsyncSessionLocal
from app.tasks.celery_app import celery
from app.utils.logger import get_logger

log = get_logger(__name__)


async def _run_pipeline(filing_id: str, job_id: str | None = None) -> dict[str, Any]:
    fid = uuid.UUID(filing_id)
    jid = uuid.UUID(job_id) if job_id else None
    orchestrator = PipelineOrchestrator()
    async with AsyncSessionLocal() as session:
        return await orchestrator.run_for_filing(fid, session, job_id=jid)


@celery.task(bind=True, name="app.tasks.thesis_tasks.extract_and_analyze", max_retries=2)
def extract_and_analyze(
    self,
    filing_id: str,
    job_id: str | None = None,
) -> dict[str, Any]:
    try:
        return asyncio.run(_run_pipeline(filing_id, job_id))
    except Exception as e:  # noqa: BLE001
        log.exception("extract_and_analyze_failed", filing_id=filing_id)
        raise self.retry(exc=e, countdown=60) from e


async def _run_for_company(ticker: str) -> dict[str, Any]:
    orchestrator = PipelineOrchestrator()
    async with AsyncSessionLocal() as session:
        return await orchestrator.run_for_company(ticker, session)


@celery.task(bind=True, name="app.tasks.thesis_tasks.analyze_company", max_retries=2)
def analyze_company(self, ticker: str) -> dict[str, Any]:
    try:
        return asyncio.run(_run_for_company(ticker))
    except Exception as e:  # noqa: BLE001
        log.exception("analyze_company_failed", ticker=ticker)
        raise self.retry(exc=e, countdown=60) from e
