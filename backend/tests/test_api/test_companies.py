"""API tests for the companies endpoints."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.db.models import Company
from app.db.session import AsyncSessionLocal, create_all_tables
from app.main import app


@pytest_asyncio.fixture
async def setup_db_with_companies():
    await create_all_tables()
    async with AsyncSessionLocal() as session:
        session.add_all(
            [
                Company(ticker="NVDA", cik="1045810", name="NVIDIA", sector="Semiconductors"),
                Company(ticker="AMD", cik="2488", name="AMD", sector="Semiconductors"),
            ]
        )
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
