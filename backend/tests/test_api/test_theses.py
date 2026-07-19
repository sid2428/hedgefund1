"""API tests for the theses endpoints (no real DB writes; isolated SQLite)."""
from __future__ import annotations

import os
import uuid
from datetime import datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

# conftest.py sets DATABASE_URL=sqlite+aiosqlite for the whole test process,
# so the app uses an in-memory DB when imported here.
from app.db.models import Company, Thesis  # noqa: E402
from app.db.session import AsyncSessionLocal, create_all_tables  # noqa: E402
from app.main import app  # noqa: E402


@pytest_asyncio.fixture
async def setup_db():
    await create_all_tables()
    yield
    # In-memory SQLite goes away with the engine; nothing to drop.


async def _seed_thesis() -> tuple[uuid.UUID, uuid.UUID]:
    async with AsyncSessionLocal() as session:
        company = Company(
            ticker="TEST",
            cik="999999",
            name="Test Co",
            sector="Semiconductors",
        )
        session.add(company)
        await session.flush()
        thesis = Thesis(
            title="Test thesis",
            summary="Body",
            thesis_type="supply_chain_contagion",
            direction="long",
            confidence_score=0.8,
            trigger_company_id=company.id,
            affected_company_ids=[],
            evidence_chain=[
                {
                    "step": 1,
                    "description": "x",
                    "source_company": "TEST",
                    "source_filing": "10-K",
                    "quote": "q",
                }
            ],
            invalidation_criteria=["never"],
            status="pending",
        )
        session.add(thesis)
        await session.commit()
        return thesis.id, company.id


@pytest.mark.asyncio
async def test_list_theses_empty(setup_db):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.get("/api/theses")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] >= 0
    assert isinstance(body["theses"], list)


@pytest.mark.asyncio
async def test_validate_thesis_changes_status(setup_db):
    thesis_id, _ = await _seed_thesis()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(
            f"/api/theses/{thesis_id}/validate",
            json={"notes": "looks correct"},
        )
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "validated"
    assert body["pm_notes"] == "looks correct"


@pytest.mark.asyncio
async def test_dismiss_unknown_thesis_404(setup_db):
    fake = uuid.uuid4()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        r = await client.post(f"/api/theses/{fake}/dismiss", json={"reason": "nope"})
    assert r.status_code == 404
