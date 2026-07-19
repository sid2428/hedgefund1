"""Point-in-time graph traversal over temporal edges.

Every read takes an `as_of` date and resolves the edge set that was live on it.
The temporal predicate is defined once, in `_live_on`, and reused everywhere —
applying it inconsistently across hops is the failure mode that would make a
historical graph quietly wrong rather than obviously broken.

Traversal is breadth-first with one query per hop, not a recursive CTE. At the
depths this graph is queried at (two, occasionally three) that is two or three
round trips, and in exchange the temporal filter, the cycle handling and the
shortest-path semantics are all plainly readable. Recursive CTEs over an
undirected, cycle-dense graph are where subtle wrong answers live.
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyRelationship


@dataclass(frozen=True)
class GraphNode:
    company_id: uuid.UUID
    ticker: str
    name: str
    sector: str | None
    degree: int
    """Hops from the seed. 0 is the seed itself."""


@dataclass(frozen=True)
class GraphEdge:
    source_id: uuid.UUID
    target_id: uuid.UUID
    source_ticker: str
    target_ticker: str
    relationship_type: str
    strength: float
    known_from: date
    known_until: date | None

    @property
    def is_open(self) -> bool:
        return self.known_until is None


class TemporalGraphRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ----- temporal predicate --------------------------------------------
    @staticmethod
    def _live_on(as_of: date):
        """Edges asserted and not yet retracted on `as_of`.

        Half-open interval: `known_from <= as_of < known_until`. A closed upper
        bound would match an edge twice where it was retracted and re-asserted
        on the same date.
        """
        return and_(
            CompanyRelationship.known_from <= as_of,
            or_(
                CompanyRelationship.known_until.is_(None),
                CompanyRelationship.known_until > as_of,
            ),
        )

    # ----- edges ----------------------------------------------------------
    def _edge_select(self):
        src = Company.__table__.alias("src")
        tgt = Company.__table__.alias("tgt")
        stmt = (
            select(
                CompanyRelationship.source_company_id,
                CompanyRelationship.target_company_id,
                src.c.ticker.label("source_ticker"),
                tgt.c.ticker.label("target_ticker"),
                CompanyRelationship.relationship_type,
                CompanyRelationship.strength,
                CompanyRelationship.known_from,
                CompanyRelationship.known_until,
            )
            .join(src, src.c.id == CompanyRelationship.source_company_id)
            .join(tgt, tgt.c.id == CompanyRelationship.target_company_id)
        )
        return stmt, src, tgt

    @staticmethod
    def _to_edge(r) -> GraphEdge:
        return GraphEdge(
            source_id=r.source_company_id,
            target_id=r.target_company_id,
            source_ticker=r.source_ticker,
            target_ticker=r.target_ticker,
            relationship_type=r.relationship_type,
            strength=float(r.strength),
            known_from=r.known_from,
            known_until=r.known_until,
        )

    async def edges_as_of(self, as_of: date) -> list[GraphEdge]:
        """Every edge live on `as_of`."""
        stmt, src, tgt = self._edge_select()
        stmt = stmt.where(self._live_on(as_of)).order_by(src.c.ticker, tgt.c.ticker)
        return [self._to_edge(r) for r in (await self.session.execute(stmt)).all()]

    async def edges_between(
        self, company_ids: set[uuid.UUID], *, as_of: date
    ) -> list[GraphEdge]:
        """Live edges with both endpoints inside `company_ids`.

        Used to render a neighbourhood: the induced subgraph, so the result has
        no edges dangling to nodes the caller was not given.
        """
        if not company_ids:
            return []
        stmt, src, tgt = self._edge_select()
        stmt = stmt.where(
            self._live_on(as_of),
            CompanyRelationship.source_company_id.in_(company_ids),
            CompanyRelationship.target_company_id.in_(company_ids),
        ).order_by(src.c.ticker, tgt.c.ticker)
        return [self._to_edge(r) for r in (await self.session.execute(stmt)).all()]

    # ----- traversal ------------------------------------------------------
    async def _adjacent(
        self, company_ids: set[uuid.UUID], *, as_of: date
    ) -> set[uuid.UUID]:
        """One hop out from a frontier, treating edges as undirected.

        Stored edges are directed, but a supply relationship is navigable from
        either end, so both columns are matched and both are collected.
        """
        if not company_ids:
            return set()

        stmt = select(
            CompanyRelationship.source_company_id,
            CompanyRelationship.target_company_id,
        ).where(
            self._live_on(as_of),
            or_(
                CompanyRelationship.source_company_id.in_(company_ids),
                CompanyRelationship.target_company_id.in_(company_ids),
            ),
        )

        found: set[uuid.UUID] = set()
        for source_id, target_id in (await self.session.execute(stmt)).all():
            found.add(source_id)
            found.add(target_id)
        return found

    async def neighbourhood(
        self,
        company_id: uuid.UUID,
        *,
        as_of: date,
        max_degree: int = 2,
    ) -> list[GraphNode]:
        """Companies within `max_degree` hops of the seed, as of a date.

        Breadth-first, so the first time a node is reached is by its shortest
        path — a company reachable at both one and two hops is reported once, at
        one. Nodes already seen are excluded from the next frontier, which is
        also what terminates traversal on a cyclic graph.
        """
        depth_by_id: dict[uuid.UUID, int] = {company_id: 0}
        frontier: set[uuid.UUID] = {company_id}

        for degree in range(1, max_degree + 1):
            if not frontier:
                break
            neighbours = await self._adjacent(frontier, as_of=as_of)
            frontier = neighbours - depth_by_id.keys()
            for node_id in frontier:
                depth_by_id[node_id] = degree

        rows = (
            await self.session.execute(
                select(Company).where(Company.id.in_(depth_by_id.keys()))
            )
        ).scalars().all()

        nodes = [
            GraphNode(
                company_id=c.id,
                ticker=c.ticker,
                name=c.name,
                sector=c.sector,
                degree=depth_by_id[c.id],
            )
            for c in rows
        ]
        return sorted(nodes, key=lambda n: (n.degree, n.ticker))

    # ----- lineage --------------------------------------------------------
    async def edge_history(
        self, source_id: uuid.UUID, target_id: uuid.UUID
    ) -> list[GraphEdge]:
        """Every assertion of an edge, open or closed, oldest first.

        When a relationship was first claimed, when it stopped being claimed,
        and whether it was ever re-asserted.
        """
        stmt, _, _ = self._edge_select()
        stmt = stmt.where(
            CompanyRelationship.source_company_id == source_id,
            CompanyRelationship.target_company_id == target_id,
        ).order_by(CompanyRelationship.known_from)
        return [self._to_edge(r) for r in (await self.session.execute(stmt)).all()]

    async def close_edge(
        self,
        source_id: uuid.UUID,
        target_id: uuid.UUID,
        relationship_type: str,
        *,
        on: date,
    ) -> int:
        """Retract an edge as of `on`, without deleting it.

        Closing rather than deleting is the whole reason a historical graph can
        be reconstructed. Returns the number of open rows closed.
        """
        rows = list(
            (
                await self.session.execute(
                    select(CompanyRelationship).where(
                        CompanyRelationship.source_company_id == source_id,
                        CompanyRelationship.target_company_id == target_id,
                        CompanyRelationship.relationship_type == relationship_type,
                        CompanyRelationship.known_until.is_(None),
                    )
                )
            )
            .scalars()
            .all()
        )
        for row in rows:
            row.known_until = on
        await self.session.flush()
        return len(rows)

    # ----- summary --------------------------------------------------------
    async def counts_as_of(self, as_of: date) -> tuple[int, int]:
        """`(node_count, edge_count)` for the graph live on a date.

        Node count is derived from endpoints of live edges, so it reflects the
        graph rather than the companies table — a company with no live edges is
        not part of the graph on that date.
        """
        edge_count = (
            await self.session.execute(
                select(func.count())
                .select_from(CompanyRelationship)
                .where(self._live_on(as_of))
            )
        ).scalar_one()

        endpoints = (
            await self.session.execute(
                select(
                    CompanyRelationship.source_company_id,
                    CompanyRelationship.target_company_id,
                ).where(self._live_on(as_of))
            )
        ).all()

        nodes: set[uuid.UUID] = set()
        for source_id, target_id in endpoints:
            nodes.add(source_id)
            nodes.add(target_id)

        return len(nodes), int(edge_count or 0)
