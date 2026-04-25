"""Export the in-memory graph to D3-friendly JSON for the frontend."""
from __future__ import annotations

from typing import Any

import networkx as nx


def to_d3_json(graph: nx.DiGraph) -> dict[str, Any]:
    """Full graph -> { nodes: [...], links: [...] }."""
    nodes = [
        {
            "id": ticker,
            "name": attrs.get("name", ticker),
            "sector": attrs.get("sector"),
            "market_cap": attrs.get("market_cap"),
        }
        for ticker, attrs in graph.nodes(data=True)
    ]
    links = [
        {
            "source": src,
            "target": tgt,
            "type": data.get("type"),
            "strength": data.get("strength", 1.0),
            "evidence": data.get("evidence"),
        }
        for src, tgt, data in graph.edges(data=True)
    ]
    return {"nodes": nodes, "links": links}


def to_ego_json(graph: nx.DiGraph, ticker: str, radius: int = 2) -> dict[str, Any]:
    """Subgraph centred on `ticker` with given hop radius."""
    if ticker not in graph:
        return {"nodes": [], "links": []}
    # Use undirected radius to capture upstream + downstream neighbours.
    ego = nx.ego_graph(graph.to_undirected(), ticker, radius=radius)
    keep = set(ego.nodes())
    sub = graph.subgraph(keep).copy()
    return to_d3_json(sub)
