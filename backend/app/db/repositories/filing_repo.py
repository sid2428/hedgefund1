"""Repository for the `filings` table."""
from __future__ import annotations

import uuid
from datetime import date
from typing import Any

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Filing


class FilingRepository:
    """Async data access for `Filing` records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, filing_id: uuid.UUID) -> Filing | None:
        result = await self.session.execute(select(Filing).where(Filing.id == filing_id))
        return result.scalar_one_or_none()

    async def get_by_accession(self, accession_number: str) -> Filing | None:
        result = await self.session.execute(
            select(Filing).where(Filing.accession_number == accession_number)
        )
        return result.scalar_one_or_none()

    async def get_for_company(
        self,
        company_id: uuid.UUID,
        filing_type: str | None = None,
        limit: int = 50,
    ) -> list[Filing]:
        stmt = select(Filing).where(Filing.company_id == company_id)
        if filing_type:
            stmt = stmt.where(Filing.filing_type == filing_type)
        stmt = stmt.order_by(desc(Filing.filed_date)).limit(limit)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def get_latest_for_company(
        self, company_id: uuid.UUID, filing_type: str
    ) -> Filing | None:
        stmt = (
            select(Filing)
            .where(Filing.company_id == company_id, Filing.filing_type == filing_type)
            .order_by(desc(Filing.filed_date))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_prior_period(
        self,
        company_id: uuid.UUID,
        filing_type: str,
        before_date: date,
    ) -> Filing | None:
        stmt = (
            select(Filing)
            .where(
                Filing.company_id == company_id,
                Filing.filing_type == filing_type,
                Filing.filed_date < before_date,
            )
            .order_by(desc(Filing.filed_date))
            .limit(1)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def create(self, data: dict[str, Any]) -> Filing:
        filing = Filing(**data)
        self.session.add(filing)
        await self.session.flush()
        return filing

    async def upsert(self, data: dict[str, Any]) -> Filing:
        existing = await self.get_by_accession(data["accession_number"])
        if existing is None:
            return await self.create(data)
        for k, v in data.items():
            if k != "id":
                setattr(existing, k, v)
        await self.session.flush()
        return existing

    async def mark_processed(self, filing_id: uuid.UUID) -> None:
        filing = await self.get_by_id(filing_id)
        if filing is not None:
            filing.processed = True
            await self.session.flush()

    async def list_unprocessed(self, limit: int = 100) -> list[Filing]:
        stmt = (
            select(Filing)
            .where(Filing.processed.is_(False))
            .order_by(Filing.filed_date)
            .limit(limit)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
