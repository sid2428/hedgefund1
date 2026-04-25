"""Pytest fixtures: in-memory SQLite session, factories, mocked Anthropic client."""
from __future__ import annotations

import os
import uuid
from datetime import date
from typing import AsyncIterator
from unittest.mock import AsyncMock

# IMPORTANT: configure SQLite *before* importing app modules so config picks it up.
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("GROQ_API_KEY", "test-key")
os.environ.setdefault("OPENAI_API_KEY", "test-key")
os.environ.setdefault("EDGAR_USER_AGENT", "Mosaic Tests test@example.com")
os.environ.setdefault("ENVIRONMENT", "development")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine  # noqa: E402

from app.db.models import Base, Company, Filing  # noqa: E402


@pytest_asyncio.fixture
async def async_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:", echo=False, future=True
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def async_session(async_engine) -> AsyncIterator[AsyncSession]:
    SessionLocal = async_sessionmaker(
        bind=async_engine, expire_on_commit=False, autoflush=False
    )
    async with SessionLocal() as session:
        yield session


@pytest_asyncio.fixture
async def test_company(async_session: AsyncSession) -> Company:
    company = Company(
        id=uuid.uuid4(),
        ticker="NVDA",
        cik="1045810",
        name="NVIDIA Corporation",
        sector="Semiconductors",
        industry="Semiconductors",
    )
    async_session.add(company)
    await async_session.commit()
    return company


@pytest_asyncio.fixture
async def test_filing(async_session: AsyncSession, test_company: Company) -> Filing:
    filing = Filing(
        id=uuid.uuid4(),
        company_id=test_company.id,
        filing_type="10-K",
        accession_number=f"test-{uuid.uuid4()}",
        filed_date=date(2025, 2, 15),
        period_of_report=date(2025, 1, 26),
        raw_text="Sample filing text for testing.",
        processed=False,
        edgar_url="https://example.com/filing",
    )
    async_session.add(filing)
    await async_session.commit()
    return filing


@pytest.fixture
def mock_groq_response():
    """Returns a callable that builds an AsyncMock chat.completions.create
    response shaped like Groq / OpenAI chat completions.
    """

    def _mock(text: str) -> AsyncMock:
        mock_client = AsyncMock()
        mock_response = AsyncMock()
        mock_message = AsyncMock()
        mock_message.content = text
        mock_choice = AsyncMock()
        mock_choice.message = mock_message
        mock_response.choices = [mock_choice]
        mock_response.usage = AsyncMock(prompt_tokens=100, completion_tokens=50)
        mock_client.chat.completions.create = AsyncMock(return_value=mock_response)
        return mock_client

    return _mock
