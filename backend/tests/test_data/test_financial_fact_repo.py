"""Repository tests for financial_facts.

Covers the two behaviours ingestion depends on: re-reading the same payload must
not duplicate rows, and every read must be bounded by the date a fact was filed.
"""
from __future__ import annotations

from datetime import date

from app.data.xbrl import XBRLFact
from app.db.repositories.financial_fact_repo import (
    FinancialFactRepository,
    as_reported_only,
    to_row,
)


def _xbrl(**overrides) -> XBRLFact:
    base = dict(
        concept="revenue",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy="us-gaap",
        unit="USD",
        value=26974000000.0,
        period_start=date(2022, 1, 31),
        period_end=date(2023, 1, 29),
        filed=date(2023, 2, 24),
        accession="0001045810-23-000017",
        form="10-K",
        fiscal_year=2023,
        fiscal_period="FY",
    )
    base.update(overrides)
    return XBRLFact(**base)


# --- mapping ----------------------------------------------------------------


def test_instant_fact_stores_start_equal_to_end():
    """A NULL start would be treated as distinct by the unique constraint."""
    row = to_row(_xbrl(concept="total_assets", tag="Assets", period_start=None,
                       period_end=date(2024, 1, 28)), company_id="c")
    assert row["period_start"] == date(2024, 1, 28)
    assert row["period_end"] == date(2024, 1, 28)
    assert row["is_instant"] is True


def test_duration_fact_preserves_start():
    row = to_row(_xbrl(), company_id="c")
    assert row["period_start"] == date(2022, 1, 31)
    assert row["is_instant"] is False


# --- writes -----------------------------------------------------------------


async def test_bulk_upsert_inserts_new_facts(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    inserted = await repo.bulk_upsert(test_company.id, [_xbrl()])
    await async_session.commit()

    assert inserted == 1
    assert await repo.count_for(test_company.id) == 1


async def test_bulk_upsert_is_idempotent(async_session, test_company):
    """Ingestion re-reads the whole payload every run."""
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(test_company.id, [_xbrl()])
    await async_session.commit()

    second = await repo.bulk_upsert(test_company.id, [_xbrl()])
    await async_session.commit()

    assert second == 0
    assert await repo.count_for(test_company.id) == 1


async def test_bulk_upsert_deduplicates_within_a_batch(async_session, test_company):
    """A payload can repeat the same fact; the batch must not self-conflict."""
    repo = FinancialFactRepository(async_session)
    inserted = await repo.bulk_upsert(test_company.id, [_xbrl(), _xbrl()])
    await async_session.commit()

    assert inserted == 1


async def test_restatement_is_inserted_as_a_new_row(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(test_company.id, [_xbrl()])
    await repo.bulk_upsert(
        test_company.id,
        [_xbrl(value=26900000000.0, filed=date(2024, 2, 21),
               accession="0001045810-24-000029")],
    )
    await async_session.commit()

    assert await repo.count_for(test_company.id) == 2


async def test_empty_input_is_a_no_op(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    assert await repo.bulk_upsert(test_company.id, []) == 0


# --- reads ------------------------------------------------------------------


async def test_series_excludes_facts_filed_after_cutoff(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(
        test_company.id,
        [
            _xbrl(),
            _xbrl(value=26900000000.0, filed=date(2024, 2, 21),
                  accession="0001045810-24-000029"),
        ],
    )
    await async_session.commit()

    visible = await repo.series(test_company.id, "revenue", as_of=date(2023, 6, 1))
    assert [f.value for f in visible] == [26974000000.0]


async def test_series_includes_restatement_once_it_is_filed(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(
        test_company.id,
        [
            _xbrl(),
            _xbrl(value=26900000000.0, filed=date(2024, 2, 21),
                  accession="0001045810-24-000029"),
        ],
    )
    await async_session.commit()

    visible = await repo.series(test_company.id, "revenue", as_of=date(2024, 6, 1))
    assert len(visible) == 2


async def test_as_reported_series_collapses_to_the_original(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(
        test_company.id,
        [
            _xbrl(),
            _xbrl(value=26900000000.0, filed=date(2024, 2, 21),
                  accession="0001045810-24-000029"),
        ],
    )
    await async_session.commit()

    series = await repo.as_reported_series(
        test_company.id, "revenue", as_of=date(2024, 6, 1)
    )
    assert len(series) == 1
    assert series[0].value == 26974000000.0


async def test_series_filters_by_unit(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(
        test_company.id,
        [_xbrl(), _xbrl(unit="EUR", value=1.0, accession="other-accn")],
    )
    await async_session.commit()

    usd = await repo.series(test_company.id, "revenue", as_of=date(2024, 6, 1), unit="USD")
    assert [f.unit for f in usd] == ["USD"]


async def test_concepts_for_lists_distinct_concepts(async_session, test_company):
    repo = FinancialFactRepository(async_session)
    await repo.bulk_upsert(
        test_company.id,
        [
            _xbrl(),
            _xbrl(concept="total_assets", tag="Assets", period_start=None,
                  period_end=date(2024, 1, 28), accession="a2"),
        ],
    )
    await async_session.commit()

    assert await repo.concepts_for(test_company.id) == ["revenue", "total_assets"]


def test_as_reported_only_keeps_earliest_filing():
    class Row:
        def __init__(self, value, filed):
            self.concept, self.unit = "revenue", "USD"
            self.period_start, self.period_end = date(2022, 1, 31), date(2023, 1, 29)
            self.value, self.filed_date = value, filed

    rows = [Row(26900000000.0, date(2024, 2, 21)), Row(26974000000.0, date(2023, 2, 24))]
    assert as_reported_only(rows)[0].value == 26974000000.0
