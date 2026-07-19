"""Tests for point-in-time graph reconstruction."""
from __future__ import annotations

import uuid
from datetime import date

from app.db.models import Company, CompanyRelationship
from app.db.repositories.temporal_graph_repo import TemporalGraphRepository


async def _company(session, ticker: str) -> Company:
    c = Company(id=uuid.uuid4(), ticker=ticker, cik=f"cik-{ticker}", name=f"{ticker} Inc")
    session.add(c)
    await session.flush()
    return c


def _edge(source, target, *, known_from, known_until=None, rel="supplier"):
    return CompanyRelationship(
        id=uuid.uuid4(),
        source_company_id=source.id,
        target_company_id=target.id,
        relationship_type=rel,
        strength=1.0,
        known_from=known_from,
        known_until=known_until,
    )


# --- point-in-time edges ----------------------------------------------------


async def test_edge_absent_before_it_was_asserted(async_session, test_company):
    other = await _company(async_session, "AAA")
    async_session.add(_edge(test_company, other, known_from=date(2023, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    assert await repo.edges_as_of(date(2022, 6, 1)) == []
    assert len(await repo.edges_as_of(date(2023, 6, 1))) == 1


async def test_closed_edge_disappears_after_retraction(async_session, test_company):
    """The edge existed, then stopped being asserted. History must survive."""
    other = await _company(async_session, "BBB")
    async_session.add(
        _edge(test_company, other, known_from=date(2022, 1, 1), known_until=date(2024, 1, 1))
    )
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    assert len(await repo.edges_as_of(date(2023, 1, 1))) == 1
    assert await repo.edges_as_of(date(2024, 6, 1)) == []


async def test_interval_is_half_open(async_session, test_company):
    """Live on known_from, not live on known_until."""
    other = await _company(async_session, "CCC")
    async_session.add(
        _edge(test_company, other, known_from=date(2023, 1, 1), known_until=date(2024, 1, 1))
    )
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    assert len(await repo.edges_as_of(date(2023, 1, 1))) == 1
    assert await repo.edges_as_of(date(2024, 1, 1)) == []


async def test_reasserted_edge_has_a_gap(async_session, test_company):
    """Closed, then claimed again by a later filing."""
    other = await _company(async_session, "DDD")
    async_session.add(
        _edge(test_company, other, known_from=date(2021, 1, 1), known_until=date(2022, 1, 1))
    )
    async_session.add(_edge(test_company, other, known_from=date(2023, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    assert len(await repo.edges_as_of(date(2021, 6, 1))) == 1
    assert await repo.edges_as_of(date(2022, 6, 1)) == []  # the gap
    assert len(await repo.edges_as_of(date(2023, 6, 1))) == 1


async def test_close_edge_preserves_history(async_session, test_company):
    other = await _company(async_session, "EEE")
    async_session.add(_edge(test_company, other, known_from=date(2022, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    closed = await repo.close_edge(
        test_company.id, other.id, "supplier", on=date(2024, 1, 1)
    )
    await async_session.commit()

    assert closed == 1
    assert await repo.edges_as_of(date(2024, 6, 1)) == []
    # The row is still there, and still says what it once said.
    history = await repo.edge_history(test_company.id, other.id)
    assert len(history) == 1
    assert history[0].known_from == date(2022, 1, 1)
    assert history[0].known_until == date(2024, 1, 1)


async def test_edge_history_is_chronological(async_session, test_company):
    other = await _company(async_session, "FFF")
    async_session.add(
        _edge(test_company, other, known_from=date(2023, 1, 1))
    )
    async_session.add(
        _edge(test_company, other, known_from=date(2021, 1, 1), known_until=date(2022, 1, 1))
    )
    await async_session.commit()

    history = await TemporalGraphRepository(async_session).edge_history(
        test_company.id, other.id
    )
    assert [h.known_from for h in history] == [date(2021, 1, 1), date(2023, 1, 1)]
    assert history[0].is_open is False
    assert history[1].is_open is True


# --- traversal --------------------------------------------------------------


async def test_neighbourhood_respects_degree(async_session, test_company):
    a = await _company(async_session, "N1")
    b = await _company(async_session, "N2")
    c = await _company(async_session, "N3")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(_edge(a, b, known_from=date(2020, 1, 1)))
    async_session.add(_edge(b, c, known_from=date(2020, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    nodes = await repo.neighbourhood(test_company.id, as_of=date(2024, 1, 1), max_degree=2)

    by_ticker = {n.ticker: n.degree for n in nodes}
    assert by_ticker[test_company.ticker] == 0
    assert by_ticker["N1"] == 1
    assert by_ticker["N2"] == 2
    assert "N3" not in by_ticker  # three hops away


async def test_traversal_is_undirected(async_session, test_company):
    """Edges are stored directed but navigable from either end."""
    upstream = await _company(async_session, "UP")
    async_session.add(_edge(upstream, test_company, known_from=date(2020, 1, 1)))
    await async_session.commit()

    nodes = await TemporalGraphRepository(async_session).neighbourhood(
        test_company.id, as_of=date(2024, 1, 1), max_degree=1
    )
    assert {n.ticker for n in nodes} == {test_company.ticker, "UP"}


async def test_traversal_terminates_on_a_cycle(async_session, test_company):
    a = await _company(async_session, "C1")
    b = await _company(async_session, "C2")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(_edge(a, b, known_from=date(2020, 1, 1)))
    async_session.add(_edge(b, test_company, known_from=date(2020, 1, 1)))
    await async_session.commit()

    nodes = await TemporalGraphRepository(async_session).neighbourhood(
        test_company.id, as_of=date(2024, 1, 1), max_degree=3
    )
    assert len(nodes) == 3
    assert {n.ticker: n.degree for n in nodes}[test_company.ticker] == 0


async def test_shortest_path_wins(async_session, test_company):
    """Reachable at one hop and two; must be reported at one."""
    a = await _company(async_session, "S1")
    b = await _company(async_session, "S2")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(_edge(test_company, b, known_from=date(2020, 1, 1)))
    async_session.add(_edge(a, b, known_from=date(2020, 1, 1)))
    await async_session.commit()

    nodes = await TemporalGraphRepository(async_session).neighbourhood(
        test_company.id, as_of=date(2024, 1, 1), max_degree=2
    )
    assert {n.ticker: n.degree for n in nodes}["S2"] == 1


async def test_neighbourhood_changes_with_as_of(async_session, test_company):
    """The point of the whole design: the graph is different on different dates."""
    a = await _company(async_session, "T1")
    b = await _company(async_session, "T2")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(_edge(a, b, known_from=date(2023, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    early = await repo.neighbourhood(test_company.id, as_of=date(2021, 1, 1), max_degree=2)
    late = await repo.neighbourhood(test_company.id, as_of=date(2024, 1, 1), max_degree=2)

    assert {n.ticker for n in early} == {test_company.ticker, "T1"}
    assert {n.ticker for n in late} == {test_company.ticker, "T1", "T2"}


async def test_isolated_seed_returns_only_itself(async_session, test_company):
    nodes = await TemporalGraphRepository(async_session).neighbourhood(
        test_company.id, as_of=date(2024, 1, 1)
    )
    assert [n.ticker for n in nodes] == [test_company.ticker]


async def test_induced_subgraph_has_no_dangling_edges(async_session, test_company):
    a = await _company(async_session, "I1")
    outside = await _company(async_session, "I2")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(_edge(a, outside, known_from=date(2020, 1, 1)))
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    edges = await repo.edges_between({test_company.id, a.id}, as_of=date(2024, 1, 1))
    assert len(edges) == 1


# --- summary ----------------------------------------------------------------


async def test_counts_reflect_the_live_graph(async_session, test_company):
    a = await _company(async_session, "K1")
    b = await _company(async_session, "K2")
    async_session.add(_edge(test_company, a, known_from=date(2020, 1, 1)))
    async_session.add(
        _edge(a, b, known_from=date(2020, 1, 1), known_until=date(2022, 1, 1))
    )
    await async_session.commit()

    repo = TemporalGraphRepository(async_session)
    assert await repo.counts_as_of(date(2021, 1, 1)) == (3, 2)
    assert await repo.counts_as_of(date(2023, 1, 1)) == (2, 1)
