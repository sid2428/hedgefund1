"""Repository for the `companies` table."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company


class CompanyRepository:
    """Async data access for `Company` records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, company_id: uuid.UUID) -> Company | None:
        result = await self.session.execute(select(Company).where(Company.id == company_id))
        return result.scalar_one_or_none()

    async def get_by_ticker(self, ticker: str) -> Company | None:
        result = await self.session.execute(
            select(Company).where(Company.ticker == ticker.upper())
        )
        return result.scalar_one_or_none()

    async def get_by_cik(self, cik: str) -> Company | None:
        # CIKs in EDGAR responses may or may not be zero-padded; store unpadded but match either.
        cik = str(cik).lstrip("0") or "0"
        result = await self.session.execute(select(Company).where(Company.cik == cik))
        return result.scalar_one_or_none()

    async def get_all(self, sector: str | None = None) -> list[Company]:
        stmt = select(Company)
        if sector:
            stmt = stmt.where(Company.sector == sector)
        stmt = stmt.order_by(Company.ticker)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def create(self, data: dict[str, Any]) -> Company:
        company = Company(**data)
        self.session.add(company)
        await self.session.flush()
        return company

    async def upsert(self, data: dict[str, Any]) -> Company:
        """Insert or update a company by ticker. Postgres ON CONFLICT path; SQLite fallback."""
        ticker = data["ticker"].upper()
        data = {**data, "ticker": ticker}

        dialect = self.session.bind.dialect.name if self.session.bind else ""
        if dialect == "postgresql":
            stmt = pg_insert(Company).values(**data)
            update_cols = {k: stmt.excluded[k] for k in data if k != "ticker"}
            stmt = stmt.on_conflict_do_update(index_elements=["ticker"], set_=update_cols)
            await self.session.execute(stmt)
        else:
            existing = await self.get_by_ticker(ticker)
            if existing is None:
                self.session.add(Company(**data))
            else:
                for k, v in data.items():
                    if k != "id":
                        setattr(existing, k, v)
        await self.session.flush()
        company = await self.get_by_ticker(ticker)
        assert company is not None
        return company
