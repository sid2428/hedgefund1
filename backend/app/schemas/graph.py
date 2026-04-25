"""Pydantic schemas for the company relationship graph (D3-friendly)."""
from __future__ import annotations

from pydantic import BaseModel, Field


class GraphNode(BaseModel):
    id: str  # ticker
    name: str
    sector: str | None = None
    market_cap: int | None = None


class GraphEdge(BaseModel):
    source: str  # source ticker
    target: str  # target ticker
    type: str
    strength: float = 1.0
    evidence: str | None = None


class GraphResponse(BaseModel):
    nodes: list[GraphNode] = Field(default_factory=list)
    links: list[GraphEdge] = Field(default_factory=list)


class JobStatusResponse(BaseModel):
    id: str
    job_type: str
    status: str  # queued | running | completed | failed
    payload: dict | None = None
    result: dict | None = None
    error: str | None = None
