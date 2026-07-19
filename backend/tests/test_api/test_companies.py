"""API tests for the companies endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.db.models import Company
from app.db.session import AsyncSessionLocal, create_all_tables
from app.main import app


@pytest_asyncio.fixture
async def setup_db_with_companies():
    """Seed the companies table, idempotently.

    This fixture writes through the *application's* session factory, whose
    engine is created at import and therefore shared by every test in the
    process. Rows survive from one test to the next, so a blind `add_all` here
    violates the unique constraint on `ticker` the second time the fixture
    runs. Insert only what is missing instead — non-destructive, so it cannot
    disturb rows another test's fixtures depend on.
    """
    await create_all_tables()
    seed = [
        Company(ticker="NVDA", cik="1045810", name="NVIDIA", sector="Semiconductors"),
        Company(ticker="AMD", cik="2488", name="AMD", sector="Semiconductors"),
    ]
    async with AsyncSessionLocal() as session:
        existing = set(
            (await session.execute(select(Company.ticker))).scalars().all()
        )
        missing = [c for c in seed if c.ticker not in existing]
        if missing:
            session.add_all(missing)
            await session.commit()


@pytest.mark.asyncio
async def test_list_companies(setup_db_with_companies):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/companies")
    assert r.status_code == 200
    body = r.json()
    tickers = {c["ticker"] for c in body["companies"]}
    assert "NVDA" in tickers and "AMD" in tickers


@pytest.mark.asyncio
async def test_get_company_by_ticker(setup_db_with_companies):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/companies/NVDA")
    assert r.status_code == 200
    assert r.json()["ticker"] == "NVDA"


@pytest.mark.asyncio
async def test_get_unknown_company_404(setup_db_with_companies):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/companies/FAKE")
    assert r.status_code == 404
