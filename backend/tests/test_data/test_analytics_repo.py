"""Tests for the SQL analytics layer.

The interesting cases are the ones where a naive query gives a plausible but
wrong answer: growth computed against a restated prior period, a ratio that
cross-matches a quarter against a fiscal year, and a reconciliation control
that has to actually fail when the books do not balance.
"""
from __future__ import annotations

from datetime import date

import pytest

from app.db.models import FinancialFact
from app.db.repositories.analytics_repo import AnalyticsRepository

USD = "USD"


def _add(session, company_id, **kw):
    base = dict(
        company_id=company_id,
        concept="revenue",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy="us-gaap",
        unit=USD,
        is_instant=False,
        form="10-K",
        fiscal_period="FY",
    )
    base.update(kw)
    session.add(FinancialFact(**base))


async def _seed_annual(session, company_id):
    """Three fiscal years, with FY2023 later restated downward."""
    _add(session, company_id, value=10000.0,
         period_start=date(2021, 1, 1), period_end=date(2021, 12, 31),
         filed_date=date(2022, 2, 1), accession_number="a-2021")
    _add(session, company_id, value=12000.0,
         period_start=date(2022, 1, 1), period_end=date(2022, 12, 31),
         filed_date=date(2023, 2, 1), accession_number="a-2022")
    _add(session, company_id, value=15000.0,
         period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
         filed_date=date(2024, 2, 1), accession_number="a-2023")
    # Restatement of FY2023, filed a year later.
    _add(session, company_id, value=14000.0,
         period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
         filed_date=date(2025, 2, 1), accession_number="a-2024")
    await session.commit()


# --- growth -----------------------------------------------------------------


async def test_growth_uses_as_reported_not_restated(async_session, test_company):
    """FY2023 was restated to 14000, but 15000 is what was reported."""
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)

    series = await repo.growth_series(
        test_company.id, "revenue", as_of=date(2026, 1, 1)
    )

    by_period = {p.period_end: p for p in series}
    assert by_period[date(2023, 12, 31)].value == 15000.0
    assert by_period[date(2023, 12, 31)].growth == pytest.approx(0.25)  # 12000 -> 15000


async def test_growth_first_period_has_no_prior(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)

    series = await repo.growth_series(test_company.id, "revenue", as_of=date(2026, 1, 1))
    assert series[0].growth is None
    assert series[0].prior_value is None


async def test_growth_links_to_the_prior_period(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)

    series = await repo.growth_series(test_company.id, "revenue", as_of=date(2026, 1, 1))
    fy2022 = next(p for p in series if p.period_end == date(2022, 12, 31))
    assert fy2022.prior_period_end == date(2021, 12, 31)
    assert fy2022.prior_value == 10000.0
    assert fy2022.growth == pytest.approx(0.2)


async def test_growth_respects_as_of(async_session, test_company):
    """A 2023 view cannot see FY2023, which was not filed until 2024."""
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)

    series = await repo.growth_series(test_company.id, "revenue", as_of=date(2023, 6, 1))
    assert [p.period_end for p in series] == [date(2021, 12, 31), date(2022, 12, 31)]


async def test_growth_against_zero_prior_is_null_not_an_error(async_session, test_company):
    _add(async_session, test_company.id, value=0.0,
         period_start=date(2021, 1, 1), period_end=date(2021, 12, 31),
         filed_date=date(2022, 2, 1), accession_number="z-1")
    _add(async_session, test_company.id, value=500.0,
         period_start=date(2022, 1, 1), period_end=date(2022, 12, 31),
         filed_date=date(2023, 2, 1), accession_number="z-2")
    await async_session.commit()

    series = await AnalyticsRepository(async_session).growth_series(
        test_company.id, "revenue", as_of=date(2026, 1, 1)
    )
    assert series[1].growth is None


async def test_growth_empty_for_unknown_concept(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)
    assert await repo.growth_series(test_company.id, "inventory", as_of=date(2026, 1, 1)) == []


# --- ratios -----------------------------------------------------------------


async def test_ratio_aligns_on_full_period_bounds(async_session, test_company):
    """A fiscal year and its Q4 share an end date and must not cross-match."""
    _add(async_session, test_company.id, concept="revenue", value=1000.0,
         period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
         filed_date=date(2024, 2, 1), accession_number="r-fy")
    _add(async_session, test_company.id, concept="net_income", tag="NetIncomeLoss",
         value=100.0,
         period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
         filed_date=date(2024, 2, 1), accession_number="r-fy")
    # Q4 shares the FY end date; different start. Must be ignored for FY.
    _add(async_session, test_company.id, concept="net_income", tag="NetIncomeLoss",
         value=40.0, fiscal_period="Q4",
         period_start=date(2023, 10, 1), period_end=date(2023, 12, 31),
         filed_date=date(2024, 2, 1), accession_number="r-q4")
    await async_session.commit()

    result = await AnalyticsRepository(async_session).ratio_series(
        test_company.id, "net_income", "revenue", as_of=date(2026, 1, 1)
    )
    assert result == [(date(2023, 12, 31), pytest.approx(0.1))]


# --- restatements -----------------------------------------------------------


async def test_restatement_report_finds_the_revision(async_session, test_company):
    await _seed_annual(async_session, test_company.id)

    report = await AnalyticsRepository(async_session).restatement_report(
        test_company.id, "revenue", as_of=date(2026, 1, 1)
    )

    assert len(report) == 1
    point = report[0]
    assert point.period_end == date(2023, 12, 31)
    assert point.original_value == 15000.0
    assert point.latest_value == 14000.0
    assert point.delta == pytest.approx(-1000.0)
    assert point.delta_pct == pytest.approx(-1000 / 15000)
    assert point.revision_count == 2
    assert point.original_accession == "a-2023"
    assert point.latest_accession == "a-2024"


async def test_restatement_report_ignores_unrevised_periods(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    report = await AnalyticsRepository(async_session).restatement_report(
        test_company.id, "revenue", as_of=date(2026, 1, 1)
    )
    assert {p.period_end for p in report} == {date(2023, 12, 31)}


async def test_restatement_report_respects_as_of(async_session, test_company):
    """Before the restating filing exists, there is nothing to report."""
    await _seed_annual(async_session, test_company.id)
    report = await AnalyticsRepository(async_session).restatement_report(
        test_company.id, "revenue", as_of=date(2024, 6, 1)
    )
    assert report == []


async def test_restatement_materiality_filter(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    repo = AnalyticsRepository(async_session)

    # The revision is ~6.7%; a 10% threshold should exclude it.
    assert await repo.restatement_report(
        test_company.id, "revenue", as_of=date(2026, 1, 1), min_delta_pct=0.10
    ) == []
    assert len(await repo.restatement_report(
        test_company.id, "revenue", as_of=date(2026, 1, 1), min_delta_pct=0.01
    )) == 1


# --- coverage and controls --------------------------------------------------


async def test_coverage_counts_facts_and_periods(async_session, test_company):
    await _seed_annual(async_session, test_company.id)
    coverage = await AnalyticsRepository(async_session).coverage(
        test_company.id, as_of=date(2026, 1, 1)
    )

    assert len(coverage) == 1
    row = coverage[0]
    assert row.concept == "revenue"
    assert row.fact_count == 4      # includes the restatement
    assert row.period_count == 3    # distinct periods
    assert row.earliest_period == date(2021, 12, 31)
    assert row.latest_period == date(2023, 12, 31)


async def test_balance_sheet_check_passes_when_identity_holds(async_session, test_company):
    common = dict(is_instant=True, fiscal_period="FY",
                  period_start=date(2023, 12, 31), period_end=date(2023, 12, 31),
                  filed_date=date(2024, 2, 1))
    _add(async_session, test_company.id, concept="total_assets", tag="Assets",
         value=1000.0, accession_number="bs-1", **common)
    _add(async_session, test_company.id, concept="total_liabilities", tag="Liabilities",
         value=600.0, accession_number="bs-1", **common)
    _add(async_session, test_company.id, concept="stockholders_equity",
         tag="StockholdersEquity", value=400.0, accession_number="bs-1", **common)
    await async_session.commit()

    result = await AnalyticsRepository(async_session).balance_sheet_check(
        test_company.id, as_of=date(2026, 1, 1)
    )
    assert len(result) == 1
    _, assets, rhs, diff, ok = result[0]
    assert (assets, rhs) == (1000.0, 1000.0)
    assert diff == pytest.approx(0.0)
    assert ok is True


async def test_balance_sheet_check_fails_when_books_do_not_balance(
    async_session, test_company
):
    """The control has to actually fire, or it is decoration."""
    common = dict(is_instant=True, fiscal_period="FY",
                  period_start=date(2023, 12, 31), period_end=date(2023, 12, 31),
                  filed_date=date(2024, 2, 1))
    _add(async_session, test_company.id, concept="total_assets", tag="Assets",
         value=1000.0, accession_number="bs-2", **common)
    _add(async_session, test_company.id, concept="total_liabilities", tag="Liabilities",
         value=600.0, accession_number="bs-2", **common)
    _add(async_session, test_company.id, concept="stockholders_equity",
         tag="StockholdersEquity", value=250.0, accession_number="bs-2", **common)
    await async_session.commit()

    result = await AnalyticsRepository(async_session).balance_sheet_check(
        test_company.id, as_of=date(2026, 1, 1)
    )
    _, _, _, diff, ok = result[0]
    assert diff == pytest.approx(150.0)
    assert ok is False
