"""API tests for the analytics and data-control endpoints."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db.models import Company, FinancialFact
from app.db.session import AsyncSessionLocal, create_all_tables
from app.main import app

TICKER = "ANLT"


def _fact(company_id, **kw):
    base = dict(
        company_id=company_id,
        concept="revenue",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy="us-gaap",
        unit="USD",
        is_instant=False,
        form="10-K",
        fiscal_period="FY",
    )
    base.update(kw)
    return FinancialFact(**base)


@pytest_asyncio.fixture
async def seeded():
    """Three fiscal years of revenue, with FY2023 restated downward later."""
    await create_all_tables()
    async with AsyncSessionLocal() as session:
        company = (
            await session.execute(select(Company).where(Company.ticker == TICKER))
        ).scalar_one_or_none()
        if company is None:
            company = Company(ticker=TICKER, cik="8888888", name="Analytics Test Corp")
            session.add(company)
            await session.flush()

        await session.execute(
            delete(FinancialFact).where(FinancialFact.company_id == company.id)
        )

        session.add(_fact(company.id, value=10000.0,
                          period_start=date(2021, 1, 1), period_end=date(2021, 12, 31),
                          filed_date=date(2022, 2, 1), accession_number="n-2021"))
        session.add(_fact(company.id, value=12000.0,
                          period_start=date(2022, 1, 1), period_end=date(2022, 12, 31),
                          filed_date=date(2023, 2, 1), accession_number="n-2022"))
        session.add(_fact(company.id, value=15000.0,
                          period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
                          filed_date=date(2024, 2, 1), accession_number="n-2023"))
        session.add(_fact(company.id, value=14000.0,
                          period_start=date(2023, 1, 1), period_end=date(2023, 12, 31),
                          filed_date=date(2025, 2, 1), accession_number="n-2024"))

        # Balance sheet for FY2023 that does not reconcile.
        bs = dict(is_instant=True, period_start=date(2023, 12, 31),
                  period_end=date(2023, 12, 31), filed_date=date(2024, 2, 1),
                  accession_number="n-bs")
        session.add(_fact(company.id, concept="total_assets", tag="Assets",
                          value=1000.0, **bs))
        session.add(_fact(company.id, concept="total_liabilities", tag="Liabilities",
                          value=600.0, **bs))
        session.add(_fact(company.id, concept="stockholders_equity",
                          tag="StockholdersEquity", value=250.0, **bs))

        await session.commit()
        return company


async def _get(url: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(url)


# --- growth -----------------------------------------------------------------


@pytest.mark.asyncio
async def test_growth_series(seeded):
    r = await _get(f"/api/analytics/{TICKER}/growth/revenue?as_of=2026-01-01")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 3

    by_period = {p["period_end"]: p for p in body["points"]}
    assert by_period["2022-12-31"]["growth"] == pytest.approx(0.2)
    # Measured against the originally reported 15000, not the restated 14000.
    assert by_period["2023-12-31"]["value"] == 15000.0


@pytest.mark.asyncio
async def test_growth_first_period_has_null_growth(seeded):
    r = await _get(f"/api/analytics/{TICKER}/growth/revenue?as_of=2026-01-01")
    first = r.json()["points"][0]
    assert first["growth"] is None
    assert first["prior_period_end"] is None


@pytest.mark.asyncio
async def test_growth_respects_as_of(seeded):
    r = await _get(f"/api/analytics/{TICKER}/growth/revenue?as_of=2023-06-01")
    assert [p["period_end"] for p in r.json()["points"]] == ["2021-12-31", "2022-12-31"]


@pytest.mark.asyncio
async def test_growth_unknown_concept_404s(seeded):
    assert (await _get(f"/api/analytics/{TICKER}/growth/nope")).status_code == 404


@pytest.mark.asyncio
async def test_growth_unknown_company_404s():
    assert (await _get("/api/analytics/NOPE/growth/revenue")).status_code == 404


# --- restatements -----------------------------------------------------------


@pytest.mark.asyncio
async def test_restatement_report(seeded):
    r = await _get(f"/api/analytics/{TICKER}/restatements/revenue?as_of=2026-01-01")
    body = r.json()
    assert body["total"] == 1

    row = body["restatements"][0]
    assert row["period_end"] == "2023-12-31"
    assert row["original_value"] == 15000.0
    assert row["latest_value"] == 14000.0
    assert row["delta"] == pytest.approx(-1000.0)
    assert row["original_accession"] == "n-2023"
    assert row["latest_accession"] == "n-2024"


@pytest.mark.asyncio
async def test_restatement_report_respects_as_of(seeded):
    """Before the restating filing exists there is nothing to report."""
    r = await _get(f"/api/analytics/{TICKER}/restatements/revenue?as_of=2024-06-01")
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_restatement_materiality_threshold(seeded):
    r = await _get(
        f"/api/analytics/{TICKER}/restatements/revenue?as_of=2026-01-01&min_delta_pct=0.10"
    )
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_negative_materiality_is_rejected(seeded):
    r = await _get(f"/api/analytics/{TICKER}/restatements/revenue?min_delta_pct=-1")
    assert r.status_code == 422


# --- coverage and controls --------------------------------------------------


@pytest.mark.asyncio
async def test_coverage_reports_per_concept(seeded):
    r = await _get(f"/api/analytics/{TICKER}/coverage?as_of=2026-01-01")
    assert r.status_code == 200
    by_concept = {c["concept"]: c for c in r.json()}

    assert by_concept["revenue"]["fact_count"] == 4    # includes the restatement
    assert by_concept["revenue"]["period_count"] == 3  # distinct periods
    assert "total_assets" in by_concept


@pytest.mark.asyncio
async def test_balance_sheet_control_reports_failure(seeded):
    """The seeded balance sheet is deliberately out by 150."""
    r = await _get(f"/api/analytics/{TICKER}/controls/balance-sheet?as_of=2026-01-01")
    assert r.status_code == 200
    body = r.json()

    assert body["failures"] == 1
    row = body["rows"][0]
    assert row["assets"] == 1000.0
    assert row["liabilities_plus_equity"] == 850.0
    assert row["difference"] == pytest.approx(150.0)
    assert row["passed"] is False


@pytest.mark.asyncio
async def test_balance_sheet_control_tolerance_is_validated(seeded):
    assert (
        await _get(f"/api/analytics/{TICKER}/controls/balance-sheet?tolerance=0")
    ).status_code == 422
