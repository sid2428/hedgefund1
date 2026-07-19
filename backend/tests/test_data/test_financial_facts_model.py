"""Schema tests for the bitemporal financial_facts table.

These run against SQLite via the shared `async_session` fixture. They assert the
two properties the table exists to provide: restatements are retained rather
than overwritten, and a point-in-time query filtering on `filed_date` returns
only what had actually been reported by that date.
"""
from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.db.models import FinancialFact


def _fact(company_id, **overrides):
    base = dict(
        company_id=company_id,
        concept="revenue",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy="us-gaap",
        unit="USD",
        value=26974000000.0,
        period_start=date(2022, 1, 31),
        period_end=date(2023, 1, 29),
        is_instant=False,
        filed_date=date(2023, 2, 24),
        accession_number="0001045810-23-000017",
        form="10-K",
        fiscal_year=2023,
        fiscal_period="FY",
    )
    base.update(overrides)
    return FinancialFact(**base)


async def test_fact_round_trips(async_session, test_company):
    async_session.add(_fact(test_company.id))
    await async_session.commit()

    row = (await async_session.execute(select(FinancialFact))).scalar_one()
    assert row.concept == "revenue"
    assert row.period_end == date(2023, 1, 29)
    assert row.filed_date == date(2023, 2, 24)
    assert row.is_instant is False


async def test_restatement_is_stored_alongside_the_original(async_session, test_company):
    """Same period, different filing. Both rows must survive."""
    async_session.add(_fact(test_company.id))
    async_session.add(
        _fact(
            test_company.id,
            value=26900000000.0,
            filed_date=date(2024, 2, 21),
            accession_number="0001045810-24-000029",
        )
    )
    await async_session.commit()

    rows = (await async_session.execute(select(FinancialFact))).scalars().all()
    assert len(rows) == 2
    assert {r.value for r in rows} == {26974000000.0, 26900000000.0}


async def test_same_filing_cannot_report_a_period_twice(async_session, test_company):
    """The uniqueness guarantee: identical identity, same accession."""
    async_session.add(_fact(test_company.id))
    await async_session.commit()

    async_session.add(_fact(test_company.id, value=999.0))
    with pytest.raises(IntegrityError):
        await async_session.commit()
    await async_session.rollback()


async def test_instant_facts_are_constrained(async_session, test_company):
    """Instant facts store start == end, so the constraint still applies.

    A nullable `period_start` would defeat it — NULLs compare as distinct in
    unique constraints, so duplicate balance-sheet rows would slip through.
    """
    common = dict(
        concept="total_assets",
        tag="Assets",
        period_start=date(2024, 1, 28),
        period_end=date(2024, 1, 28),
        is_instant=True,
        filed_date=date(2024, 2, 21),
        accession_number="0001045810-24-000029",
    )
    async_session.add(_fact(test_company.id, value=65728000000.0, **common))
    await async_session.commit()

    async_session.add(_fact(test_company.id, value=1.0, **common))
    with pytest.raises(IntegrityError):
        await async_session.commit()
    await async_session.rollback()


async def test_as_of_query_filters_on_filed_date(async_session, test_company):
    """The reason the table is bitemporal.

    FY2023 ended January 2023. Its restatement was not filed until February
    2024, so a view taken in mid-2023 must not see it — even though the period
    it describes was long over by then.
    """
    async_session.add(_fact(test_company.id))
    async_session.add(
        _fact(
            test_company.id,
            value=26900000000.0,
            filed_date=date(2024, 2, 21),
            accession_number="0001045810-24-000029",
        )
    )
    await async_session.commit()

    cutoff = date(2023, 6, 1)
    visible = (
        (
            await async_session.execute(
                select(FinancialFact).where(FinancialFact.filed_date <= cutoff)
            )
        )
        .scalars()
        .all()
    )

    assert len(visible) == 1
    assert visible[0].value == 26974000000.0


async def test_period_end_filter_would_admit_the_restatement(async_session, test_company):
    """Demonstrates the bug the design avoids.

    Filtering on `period_end` rather than `filed_date` returns both rows,
    including a correction published a year later. This test exists to pin down
    *why* the query above uses the column it does.
    """
    async_session.add(_fact(test_company.id))
    async_session.add(
        _fact(
            test_company.id,
            value=26900000000.0,
            filed_date=date(2024, 2, 21),
            accession_number="0001045810-24-000029",
        )
    )
    await async_session.commit()

    leaky = (
        (
            await async_session.execute(
                select(FinancialFact).where(FinancialFact.period_end <= date(2023, 6, 1))
            )
        )
        .scalars()
        .all()
    )

    assert len(leaky) == 2  # the restatement leaks in
