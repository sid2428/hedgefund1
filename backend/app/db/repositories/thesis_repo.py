"""Repository for the `theses` table."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Thesis


class ThesisRepository:
    """Async data access for `Thesis` records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, thesis_id: uuid.UUID) -> Thesis | None:
        result = await self.session.execute(select(Thesis).where(Thesis.id == thesis_id))
        return result.scalar_one_or_none()

    async def get_all(
        self,
        status: str | None = None,
        direction: str | None = None,
        confidence_min: float | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> list[Thesis]:
        stmt = select(Thesis)
        if status:
            stmt = stmt.where(Thesis.status == status)
        if direction:
            stmt = stmt.where(Thesis.direction == direction)
        if confidence_min is not None:
            stmt = stmt.where(Thesis.confidence_score >= confidence_min)
        stmt = (
            stmt.order_by(desc(Thesis.confidence_score), desc(Thesis.created_at))
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def count(
        self,
        status: str | None = None,
        direction: str | None = None,
        confidence_min: float | None = None,
    ) -> int:
        stmt = select(func.count()).select_from(Thesis)
        if status:
            stmt = stmt.where(Thesis.status == status)
        if direction:
            stmt = stmt.where(Thesis.direction == direction)
        if confidence_min is not None:
            stmt = stmt.where(Thesis.confidence_score >= confidence_min)
        result = await self.session.execute(stmt)
        return int(result.scalar_one())

    async def stats(self) -> dict[str, int]:
        rows = await self.session.execute(
            select(Thesis.status, func.count()).group_by(Thesis.status)
        )
        out = {"total": 0, "pending": 0, "validated": 0, "dismissed": 0, "expired": 0}
        for status, n in rows.all():
            out[status] = int(n)
            out["total"] += int(n)
        return out

    async def create(self, data: dict[str, Any]) -> Thesis:
        thesis = Thesis(**data)
        self.session.add(thesis)
        await self.session.flush()
        return thesis

    async def update_status(
        self,
        thesis_id: uuid.UUID,
        status: str,
        notes: str | None = None,
    ) -> Thesis | None:
        thesis = await self.get_by_id(thesis_id)
        if thesis is None:
            return None
        thesis.status = status
        if notes is not None:
            thesis.pm_notes = notes
        await self.session.flush()
        return thesis
