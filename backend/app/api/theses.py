"""Theses API: list, detail, validate, dismiss, stats."""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.thesis_repo import ThesisRepository
from app.db.session import get_db
from app.schemas.thesis import (
    DismissRequest,
    ThesisDirection,
    ThesisListResponse,
    ThesisResponse,
    ThesisStatsResponse,
    ThesisStatus,
    ThesisType,
    ValidateRequest,
)

router = APIRouter()


async def _hydrate(thesis, session: AsyncSession) -> ThesisResponse:
    """Attach trigger/affected tickers to the response payload."""
    company_repo = CompanyRepository(session)
    trigger = await company_repo.get_by_id(thesis.trigger_company_id)
    affected_tickers: list[str] = []
    for cid in thesis.affected_company_ids or []:
        c = await company_repo.get_by_id(cid)
        if c is not None:
            affected_tickers.append(c.ticker)

    base = ThesisResponse.model_validate(thesis)
    base.trigger_ticker = trigger.ticker if trigger else None
    base.affected_tickers = affected_tickers
    return base


@router.get("/stats", response_model=ThesisStatsResponse)
async def thesis_stats(session: AsyncSession = Depends(get_db)) -> ThesisStatsResponse:
    s = await ThesisRepository(session).stats()
    return ThesisStatsResponse(**{k: s.get(k, 0) for k in (
        "total", "pending", "validated", "dismissed", "expired"
    )})


@router.get("", response_model=ThesisListResponse)
async def list_theses(
    status_filter: ThesisStatus | None = Query(default=None, alias="status"),
    direction: ThesisDirection | None = None,
    confidence_min: float | None = Query(default=None, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_db),
) -> ThesisListResponse:
    repo = ThesisRepository(session)
    rows = await repo.get_all(
        status=status_filter.value if status_filter else None,
        direction=direction.value if direction else None,
        confidence_min=confidence_min,
        limit=limit,
        offset=offset,
    )
    total = await repo.count(
        status=status_filter.value if status_filter else None,
        direction=direction.value if direction else None,
        confidence_min=confidence_min,
    )
    items = [await _hydrate(r, session) for r in rows]
    return ThesisListResponse(theses=items, total=total, limit=limit, offset=offset)


@router.get("/{thesis_id}", response_model=ThesisResponse)
async def get_thesis(
    thesis_id: uuid.UUID, session: AsyncSession = Depends(get_db)
) -> ThesisResponse:
    row = await ThesisRepository(session).get_by_id(thesis_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return await _hydrate(row, session)


@router.post(
    "/{thesis_id}/validate",
    response_model=ThesisResponse,
    status_code=status.HTTP_200_OK,
)
async def validate_thesis(
    thesis_id: uuid.UUID,
    body: ValidateRequest = ValidateRequest(),
    session: AsyncSession = Depends(get_db),
) -> ThesisResponse:
    repo = ThesisRepository(session)
    row = await repo.update_status(thesis_id, status="validated", notes=body.notes)
    if row is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return await _hydrate(row, session)


@router.post(
    "/{thesis_id}/dismiss",
    response_model=ThesisResponse,
    status_code=status.HTTP_200_OK,
)
async def dismiss_thesis(
    thesis_id: uuid.UUID,
    body: DismissRequest = DismissRequest(),
    session: AsyncSession = Depends(get_db),
) -> ThesisResponse:
    repo = ThesisRepository(session)
    row = await repo.update_status(
        thesis_id, status="dismissed", notes=body.reason
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Thesis not found")
    return await _hydrate(row, session)
