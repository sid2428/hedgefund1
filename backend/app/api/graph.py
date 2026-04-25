"""Graph API: full graph + ego-graph endpoints for the D3 visualization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.graph.builder import get_graph
from app.graph.exporter import to_d3_json, to_ego_json
from app.schemas.graph import GraphEdge, GraphNode, GraphResponse

router = APIRouter()


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
