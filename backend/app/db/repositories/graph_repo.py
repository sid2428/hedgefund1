"""Repository for the `company_relationships` table."""
from __future__ import annotations

import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyRelationship


class GraphRepository:
    """Async data access for graph edges (`CompanyRelationship`)."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def upsert_relationship(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: str,
        strength: float = 1.0,
        evidence_text: str | None = None,
        source_filing_id: uuid.UUID | None = None,
    ) -> CompanyRelationship:
        stmt = select(CompanyRelationship).where(
            CompanyRelationship.source_company_id == source_id,
            CompanyRelationship.target_company_id == target_id,
            CompanyRelationship.relationship_type == relationship_type,
        )
        existing = (await self.session.execute(stmt)).scalar_one_or_none()
        if existing is not None:
            # Strengthen edge if evidence supports it; never weaken.
            if strength > existing.strength:
                existing.strength = strength
            if evidence_text:
                existing.evidence_text = evidence_text
            if source_filing_id:
                existing.source_filing_id = source_filing_id
            await self.session.flush()
            return existing

        edge = CompanyRelationship(
            source_company_id=source_id,
            target_company_id=target_id,
            relationship_type=relationship_type,
            strength=strength,
            evidence_text=evidence_text,
            source_filing_id=source_filing_id,
        )
        self.session.add(edge)
        await self.session.flush()
        return edge

    async def get_neighbors(
        self,
        company_id: uuid.UUID,
        max_degree: int = 2,
    ) -> list[dict[str, Any]]:
        """Return up to 2-degree neighbors as plain dicts.

        Heavy graph traversal lives in `app.graph.queries`; this is a DB-only,
        depth-bounded BFS used by repositories that don't have the in-memory
        graph available (e.g. inside Celery tasks).
        """
        if max_degree < 1:
            return []

        visited: set[uuid.UUID] = {company_id}
        frontier: list[tuple[uuid.UUID, int, str | None]] = [(company_id, 0, None)]
        out: list[dict[str, Any]] = []

        while frontier:
            current, degree, _ = frontier.pop(0)
            if degree >= max_degree:
                continue

            stmt = select(CompanyRelationship).where(
                CompanyRelationship.source_company_id == current
            )
            for edge in (await self.session.execute(stmt)).scalars():
                if edge.target_company_id in visited:
                    continue
                visited.add(edge.target_company_id)
                target = await self.session.get(Company, edge.target_company_id)
                if target is None:
                    continue
                out.append(
                    {
                        "ticker": target.ticker,
                        "name": target.name,
                        "company_id": target.id,
                        "relationship_type": edge.relationship_type,
                        "strength": edge.strength,
                        "degree": degree + 1,
                    }
                )
                frontier.append((target.id, degree + 1, edge.relationship_type))

        return out

    async def get_all_edges(self) -> list[CompanyRelationship]:
        result = await self.session.execute(select(CompanyRelationship))
        return list(result.scalars().all())
