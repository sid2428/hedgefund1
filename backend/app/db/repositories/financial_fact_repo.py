"""Repository for the `financial_facts` table.

Read methods here take an `as_of` argument rather than offering it as an option,
because the correct default is not obvious and getting it wrong is silent. A
query that forgets to bound `filed_date` returns restatements published after
the date being analysed, and nothing about the result looks wrong.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable, Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.data.xbrl import XBRLFact
from app.db.models import FinancialFact

# Columns forming the table's unique identity. Used for conflict resolution on
# bulk insert; mirrors uq_financial_facts_identity.
_IDENTITY = (
    "company_id",
    "concept",
    "unit",
    "period_start",
    "period_end",
    "accession_number",
)


def to_row(fact: XBRLFact, company_id: uuid.UUID) -> dict:
    """Map a parsed `XBRLFact` onto table columns.

    Instant facts carry no start date. They are stored with
    `period_start == period_end` and `is_instant=True`, because a NULL start
    would be treated as distinct by the unique constraint and let duplicates
    through.
    """
    return {
        "company_id": company_id,
        "concept": fact.concept,
        "tag": fact.tag,
        "taxonomy": fact.taxonomy,
        "unit": fact.unit,
        "value": fact.value,
        "period_start": fact.period_start or fact.period_end,
        "period_end": fact.period_end,
        "is_instant": fact.is_instant,
        "filed_date": fact.filed,
        "accession_number": fact.accession,
        "form": fact.form or None,
        "fiscal_year": fact.fiscal_year,
        "fiscal_period": fact.fiscal_period,
    }


class FinancialFactRepository:
    """Async data access for `FinancialFact` records."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----- writes --------------------------------------------------------
    async def bulk_upsert(
        self, company_id: uuid.UUID, facts: Iterable[XBRLFact]
    ) -> int:
        """Insert facts, ignoring any already recorded.

        Ingestion re-reads a company's full companyfacts payload each run, so
        the overwhelming majority of rows on any given pass already exist.
        Conflicts are skipped rather than updated: a row is a statement about
        what one filing reported, and that never changes retroactively. A
        corrected figure arrives as a new filing, and therefore a new row.

        Returns the number of rows actually inserted.
        """
        rows = [to_row(f, company_id) for f in facts]
        if not rows:
            return 0

        dialect = self.session.bind.dialect.name if self.session.bind else ""
        if dialect == "postgresql":
            stmt = pg_insert(FinancialFact).values(rows)
            stmt = stmt.on_conflict_do_nothing(index_elements=_IDENTITY)
            result = await self.session.execute(stmt)
            await self.session.flush()
            return result.rowcount or 0

        # SQLite (tests) has no equivalent that reports rowcount reliably
        # across versions, so fall back to filtering against what is already
        # stored. Correct, and the volumes here are small.
        return await self._insert_missing(company_id, rows)

    async def _insert_missing(self, company_id: uuid.UUID, rows: list[dict]) -> int:
        existing = {
            tuple(r)
            for r in (
                await self.session.execute(
                    select(
                        FinancialFact.company_id,
                        FinancialFact.concept,
                        FinancialFact.unit,
                        FinancialFact.period_start,
                        FinancialFact.period_end,
                        FinancialFact.accession_number,
                    ).where(FinancialFact.company_id == company_id)
                )
            ).all()
        }

        inserted = 0
        seen: set[tuple] = set()
        for row in rows:
            key = tuple(row[c] for c in _IDENTITY)
            # Guard against duplicates inside the incoming batch as well as
            # against the table; a payload can repeat a fact.
            if key in existing or key in seen:
                continue
            seen.add(key)
            self.session.add(FinancialFact(**row))
            inserted += 1

        await self.session.flush()
        return inserted

    # ----- reads ---------------------------------------------------------
    async def series(
        self,
        company_id: uuid.UUID,
        concept: str,
        *,
        as_of: date,
        unit: str | None = None,
    ) -> list[FinancialFact]:
        """All reported values for a concept, as known on `as_of`.

        Includes restatements filed on or before the cutoff. Call
        `as_reported_only` to collapse them to the originally reported figure.
        """
        stmt = select(FinancialFact).where(
            FinancialFact.company_id == company_id,
            FinancialFact.concept == concept,
            FinancialFact.filed_date <= as_of,
        )
        if unit is not None:
            stmt = stmt.where(FinancialFact.unit == unit)
        stmt = stmt.order_by(FinancialFact.period_end, FinancialFact.filed_date)
        return list((await self.session.execute(stmt)).scalars().all())

    async def as_reported_series(
        self,
        company_id: uuid.UUID,
        concept: str,
        *,
        as_of: date,
        unit: str | None = None,
    ) -> list[FinancialFact]:
        """One value per period — the figure originally reported for it.

        This is the series a backtest should use. Restated values encode
        information that did not exist when the period was first reported.
        """
        rows = await self.series(company_id, concept, as_of=as_of, unit=unit)
        return as_reported_only(rows)

    async def concepts_for(self, company_id: uuid.UUID) -> list[str]:
        stmt = (
            select(FinancialFact.concept)
            .where(FinancialFact.company_id == company_id)
            .distinct()
            .order_by(FinancialFact.concept)
        )
        return list((await self.session.execute(stmt)).scalars().all())

    async def count_for(self, company_id: uuid.UUID) -> int:
        stmt = select(FinancialFact.id).where(FinancialFact.company_id == company_id)
        return len((await self.session.execute(stmt)).scalars().all())


def as_reported_only(rows: Sequence[FinancialFact]) -> list[FinancialFact]:
    """Collapse restatements, keeping the earliest filing for each period."""
    chosen: dict[tuple, FinancialFact] = {}
    for row in rows:
        key = (row.concept, row.unit, row.period_start, row.period_end)
        current = chosen.get(key)
        if current is None or row.filed_date < current.filed_date:
            chosen[key] = row
    return sorted(chosen.values(), key=lambda r: (r.concept, r.period_end))
