"""Graph API: full graph + ego-graph endpoints for the D3 visualization.

The `/as-of` routes read edges directly from the database rather than the
in-memory NetworkX graph. That cache holds a single snapshot — the current one —
so it cannot answer a historical question. Serving point-in-time queries from it
would return today's graph with a date attached to it, which is worse than
returning nothing.
"""
from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.repositories.company_repo import CompanyRepository
from app.db.repositories.temporal_graph_repo import TemporalGraphRepository
from app.db.session import get_db
from app.graph.builder import get_graph
from app.graph.exporter import to_d3_json, to_ego_json
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse

router = APIRouter()


class TemporalGraphNode(BaseModel):
    id: str
    ticker: str
    name: str
    sector: str | None = None
    degree: int


class TemporalGraphEdge(BaseModel):
    source: str
    target: str
    relationship_type: str
    strength: float
    known_from: date
    known_until: date | None = None


class TemporalGraphResponse(BaseModel):
    as_of: date
    nodes: list[TemporalGraphNode]
    links: list[TemporalGraphEdge]
    node_count: int
    edge_count: int


class EdgeHistoryResponse(BaseModel):
    source_ticker: str
    target_ticker: str
    assertions: list[TemporalGraphEdge]
    total: int


_AS_OF = Query(
    default=None,
    description=(
        "Reconstruct the graph as it was known on this date. An edge is "
        "included when it had been asserted by then and not yet retracted. "
        "Defaults to today."
    ),
)


@router.get("", response_model=GraphResponse)
async def get_full_graph(
    refresh: bool = Query(
        default=False, description="Reload from DB before responding."
    ),
    session: AsyncSession = Depends(get_db),
) -> GraphResponse:
    g = get_graph()
    if refresh or g.node_count() == 0:
        await g.load_from_db(session)
    payload = to_d3_json(g.graph)
    return GraphResponse(
        nodes=[GraphNode(**n) for n in payload["nodes"]],
        links=[GraphEdge(**e) for e in payload["links"]],
    )


@router.get("/as-of", response_model=TemporalGraphResponse)
async def get_graph_as_of(
    as_of: date | None = _AS_OF,
    session: AsyncSession = Depends(get_db),
) -> TemporalGraphResponse:
    """The whole graph as it stood on a given date."""
    cutoff = as_of or date.today()
    repo = TemporalGraphRepository(session)
    edges = await repo.edges_as_of(cutoff)

    tickers: dict[str, TemporalGraphNode] = {}
    for e in edges:
        for cid, ticker in ((e.source_id, e.source_ticker), (e.target_id, e.target_ticker)):
            tickers.setdefault(
                ticker,
                TemporalGraphNode(id=str(cid), ticker=ticker, name=ticker, degree=0),
            )

    return TemporalGraphResponse(
        as_of=cutoff,
        nodes=sorted(tickers.values(), key=lambda n: n.ticker),
        links=[
            TemporalGraphEdge(
                source=e.source_ticker,
                target=e.target_ticker,
                relationship_type=e.relationship_type,
                strength=e.strength,
                known_from=e.known_from,
                known_until=e.known_until,
            )
            for e in edges
        ],
        node_count=len(tickers),
        edge_count=len(edges),
    )


@router.get("/as-of/{ticker}", response_model=TemporalGraphResponse)
async def get_ego_graph_as_of(
    ticker: str,
    as_of: date | None = _AS_OF,
    radius: int = Query(default=2, ge=1, le=3),
    session: AsyncSession = Depends(get_db),
) -> TemporalGraphResponse:
    """A company's neighbourhood as it stood on a given date.

    Returns the induced subgraph: only edges whose endpoints are both in the
    returned node set, so nothing dangles off the edge of the result.
    """
    company = await CompanyRepository(session).get_by_ticker(ticker)
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")

    cutoff = as_of or date.today()
    repo = TemporalGraphRepository(session)

    nodes = await repo.neighbourhood(company.id, as_of=cutoff, max_degree=radius)
    edges = await repo.edges_between({n.company_id for n in nodes}, as_of=cutoff)

    return TemporalGraphResponse(
        as_of=cutoff,
        nodes=[
            TemporalGraphNode(
                id=str(n.company_id),
                ticker=n.ticker,
                name=n.name,
                sector=n.sector,
                degree=n.degree,
            )
            for n in nodes
        ],
        links=[
            TemporalGraphEdge(
                source=e.source_ticker,
                target=e.target_ticker,
                relationship_type=e.relationship_type,
                strength=e.strength,
                known_from=e.known_from,
                known_until=e.known_until,
            )
            for e in edges
        ],
        node_count=len(nodes),
        edge_count=len(edges),
    )


@router.get("/history/{source_ticker}/{target_ticker}", response_model=EdgeHistoryResponse)
async def get_edge_history(
    source_ticker: str,
    target_ticker: str,
    session: AsyncSession = Depends(get_db),
) -> EdgeHistoryResponse:
    """Every assertion of a relationship: when claimed, when retracted, re-opened."""
    repo = CompanyRepository(session)
    source = await repo.get_by_ticker(source_ticker)
    target = await repo.get_by_ticker(target_ticker)
    if source is None or target is None:
        raise HTTPException(status_code=404, detail="Company not found")

    history = await TemporalGraphRepository(session).edge_history(source.id, target.id)
    return EdgeHistoryResponse(
        source_ticker=source.ticker,
        target_ticker=target.ticker,
        assertions=[
            TemporalGraphEdge(
                source=e.source_ticker,
                target=e.target_ticker,
                relationship_type=e.relationship_type,
                strength=e.strength,
                known_from=e.known_from,
                known_until=e.known_until,
            )
            for e in history
        ],
        total=len(history),
    )


@router.get("/{ticker}", response_model=GraphResponse)
async def get_ego_graph(
    ticker: str,
    radius: int = Query(default=2, ge=1, le=3),
    session: AsyncSession = Depends(get_db),
) -> GraphResponse:
    g = get_graph()
    if g.node_count() == 0:
        await g.load_from_db(session)
    if ticker.upper() not in g.graph:
        raise HTTPException(status_code=404, detail="Company not in graph")
    payload = to_ego_json(g.graph, ticker.upper(), radius=radius)
    return GraphResponse(
        nodes=[GraphNode(**n) for n in payload["nodes"]],
        links=[GraphEdge(**e) for e in payload["links"]],
    )
