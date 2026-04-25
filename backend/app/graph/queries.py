"""Graph traversal helpers operating on a NetworkX DiGraph."""
from __future__ import annotations

from typing import Any

import networkx as nx


def find_second_degree_connections(
    graph: nx.DiGraph, ticker: str
) -> list[dict[str, Any]]:
    """Return every node within 2 hops of `ticker`, with degree and path info."""
    if ticker not in graph:
        return []

    out: list[dict[str, Any]] = []
    visited: set[str] = {ticker}
    frontier: list[tuple[str, int, list[str]]] = [(ticker, 0, [ticker])]

    while frontier:
        current, degree, path = frontier.pop(0)
        if degree >= 2:
            continue
        for neighbor in graph.successors(current):
            if neighbor in visited:
                continue
            visited.add(neighbor)
            edge = graph.get_edge_data(current, neighbor) or {}
            node = graph.nodes[neighbor]
            out.append(
                {
                    "ticker": neighbor,
                    "name": node.get("name", neighbor),
                    "sector": node.get("sector"),
                    "relationship_type": edge.get("type"),
                    "strength": edge.get("strength", 1.0),
                    "degree": degree + 1,
                    "path": path + [neighbor],
                }
            )
            frontier.append((neighbor, degree + 1, path + [neighbor]))
    return out


def find_supply_chain_path(
    graph: nx.DiGraph, upstream_ticker: str, downstream_ticker: str
) -> list[str] | None:
    """Return a directed supplier->customer path if one exists."""
    if upstream_ticker not in graph or downstream_ticker not in graph:
        return None
    try:
        return nx.shortest_path(graph, upstream_ticker, downstream_ticker)
    except (nx.NodeNotFound, nx.NetworkXNoPath):
        return None


def get_sector_peers(graph: nx.DiGraph, ticker: str) -> list[str]:
    """All other nodes in the same sector (regardless of edges)."""
    if ticker not in graph:
        return []
    sector = graph.nodes[ticker].get("sector")
    if not sector:
        return []
    return [
        n
        for n, attrs in graph.nodes(data=True)
        if attrs.get("sector") == sector and n != ticker
    ]
