"""API tests for the point-in-time financials endpoints."""
from __future__ import annotations

from datetime import date

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db.models import Company, FinancialFact
from app.db.session import AsyncSessionLocal, create_all_tables
from app.main import app

ORIGINAL = 26974000000.0
RESTATED = 26900000000.0


def _fact(company_id, **overrides):
    base = dict(
        company_id=company_id,
        concept="revenue",
        tag="RevenueFromContractWithCustomerExcludingAssessedTax",
        taxonomy="us-gaap",
        unit="USD",
        value=ORIGINAL,
        period_start=date(2022, 1, 31),
        period_end=date(2023, 1, 29),
        is_instant=False,
        filed_date=date(2023, 2, 24),
        accession_number="0001045810-23-000017",
        form="10-K",
    )
    base.update(overrides)
    return FinancialFact(**base)


@pytest_asyncio.fixture
async def seeded_company():
    """Seed one company with an original figure and a later restatement."""
    await create_all_tables()
    async with AsyncSessionLocal() as session:
        company = (
            await session.execute(select(Company).where(Company.ticker == "FINT"))
        ).scalar_one_or_none()
        if company is None:
            company = Company(ticker="FINT", cik="9999999", name="Fin Test Corp")
            session.add(company)
            await session.flush()

        # Reset facts so repeated runs of this fixture stay deterministic.
        await session.execute(
            delete(FinancialFact).where(FinancialFact.company_id == company.id)
        )
        session.add(_fact(company.id))
        session.add(
            _fact(
                company.id,
                value=RESTATED,
                filed_date=date(2024, 2, 21),
                accession_number="0001045810-24-000029",
            )
        )
        await session.commit()
        return company


async def _get(url: str):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        return await c.get(url)


@pytest.mark.asyncio
async def test_as_of_before_restatement_returns_original(seeded_company):
    """The point of the endpoint: a 2023 view must not see a 2024 correction."""
    r = await _get("/api/companies/FINT/financials/revenue?as_of=2023-06-01")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1
    assert body["facts"][0]["value"] == ORIGINAL


@pytest.mark.asyncio
async def test_as_of_before_any_filing_is_empty(seeded_company):
    r = await _get("/api/companies/FINT/financials/revenue?as_of=2020-01-01")
    assert r.status_code == 200
    assert r.json()["total"] == 0


@pytest.mark.asyncio
async def test_as_reported_collapses_restatement(seeded_company):
    """Both versions are known by 2024, but as_reported keeps the original."""
    r = await _get(
        "/api/companies/FINT/financials/revenue?as_of=2024-06-01&basis=as_reported"
    )
    body = r.json()
    assert body["total"] == 1
    assert body["facts"][0]["value"] == ORIGINAL


@pytest.mark.asyncio
async def test_basis_all_returns_every_filed_version(seeded_company):
    r = await _get("/api/companies/FINT/financials/revenue?as_of=2024-06-01&basis=all")
    body = r.json()
    assert body["total"] == 2
    assert {f["value"] for f in body["facts"]} == {ORIGINAL, RESTATED}


@pytest.mark.asyncio
async def test_response_exposes_filed_date(seeded_company):
    """Without it, an original and a restatement are indistinguishable."""
    r = await _get("/api/companies/FINT/financials/revenue?as_of=2023-06-01")
    assert r.json()["facts"][0]["filed_date"] == "2023-02-24"


@pytest.mark.asyncio
async def test_invalid_basis_is_rejected(seeded_company):
    r = await _get("/api/companies/FINT/financials/revenue?basis=whatever")
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_unknown_concept_404s(seeded_company):
    r = await _get("/api/companies/FINT/financials/not_a_concept")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_unknown_company_404s():
    r = await _get("/api/companies/NOPE/financials/revenue")
    assert r.status_code == 404


@pytest.mark.asyncio
async def test_list_concepts_for_company(seeded_company):
    r = await _get("/api/companies/FINT/financials")
    assert r.status_code == 200
    assert r.json() == ["revenue"]
