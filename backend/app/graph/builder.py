"""In-memory NetworkX company-relationship graph (singleton)."""
from __future__ import annotations

import asyncio
import uuid
from typing import Any

import networkx as nx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Company, CompanyRelationship
from app.db.session import AsyncSessionLocal
from app.utils.logger import get_logger

log = get_logger(__name__)


class MosaicGraph:
    """Process-local DiGraph hydrated from Postgres on startup.

    Reads are O(neighbors); writes go through `add_relationship` (and through
    the DB via `GraphRepository`). The orchestrator/agents own DB writes; this
    class is a fast read cache for the API layer.
    """

    def __init__(self) -> None:
        self.graph: nx.DiGraph = nx.DiGraph()
        self._lock = asyncio.Lock()

    # ---- mutators --------------------------------------------------------
    def add_company(self, company: Company) -> None:
        self.graph.add_node(
            company.ticker,
            company_id=str(company.id),
            name=company.name,
            sector=company.sector,
            market_cap=company.market_cap,
        )

    def add_relationship(
        self,
        source_ticker: str,
        target_ticker: str,
        rel_type: str,
        strength: float = 1.0,
        evidence: str | None = None,
    ) -> None:
        if source_ticker not in self.graph or target_ticker not in self.graph:
            return
        self.graph.add_edge(
            source_ticker,
            target_ticker,
            type=rel_type,
            strength=strength,
            evidence=evidence,
        )

    # ---- queries ---------------------------------------------------------
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    def get_neighbors(
        self, ticker: str, max_degree: int = 2
    ) -> list[dict[str, Any]]:
        """BFS up to max_degree, return rich dicts including degree and the
        relationship that brought us there."""
        if ticker not in self.graph:
            return []
        out: list[dict[str, Any]] = []
        visited: set[str] = {ticker}
        frontier: list[tuple[str, int]] = [(ticker, 0)]

        while frontier:
            current, degree = frontier.pop(0)
            if degree >= max_degree:
                continue
            for neighbor in self.graph.successors(current):
                if neighbor in visited:
                    continue
                visited.add(neighbor)
                edge = self.graph.get_edge_data(current, neighbor) or {}
                node = self.graph.nodes[neighbor]
                out.append(
                    {
                        "ticker": neighbor,
                        "name": node.get("name", neighbor),
                        "company_id": node.get("company_id"),
                        "sector": node.get("sector"),
                        "relationship_type": edge.get("type"),
                        "strength": edge.get("strength", 1.0),
                        "degree": degree + 1,
                    }
                )
                frontier.append((neighbor, degree + 1))
        return out

    # ---- hydration -------------------------------------------------------
    async def load_from_db(self, session: AsyncSession | None = None) -> None:
        async with self._lock:
            self.graph.clear()
            owned = session is None
            if owned:
                session = AsyncSessionLocal()
            try:
                companies = (await session.execute(select(Company))).scalars().all()
                for c in companies:
                    self.add_company(c)
                edges = (
                    await session.execute(select(CompanyRelationship))
                ).scalars().all()
                # Resolve company_id -> ticker once.
                id_to_ticker: dict[uuid.UUID, str] = {c.id: c.ticker for c in companies}
                for e in edges:
                    src = id_to_ticker.get(e.source_company_id)
                    tgt = id_to_ticker.get(e.target_company_id)
                    if not src or not tgt:
                        continue
                    self.add_relationship(
                        src,
                        tgt,
                        rel_type=e.relationship_type,
                        strength=e.strength,
                        evidence=e.evidence_text,
                    )
                log.info(
                    "graph_hydrated", nodes=self.node_count(), edges=self.edge_count()
                )
            finally:
                if owned:
                    await session.close()


_singleton: MosaicGraph | None = None


def get_graph() -> MosaicGraph:
    global _singleton
    if _singleton is None:
        _singleton = MosaicGraph()
    return _singleton
