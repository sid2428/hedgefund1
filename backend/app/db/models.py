"""SQLAlchemy 2.0 ORM models — single source of truth for the database schema.

Mirrors the schema in Section 4 of the Mosaic context document.
Uses `JSON` type which maps to JSONB on Postgres and JSON on SQLite (for tests).
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON, TypeDecorator

# pgvector is only available when the postgres driver is loaded; importing
# defensively so SQLite-based tests still work.
try:
    from pgvector.sqlalchemy import Vector  # type: ignore[import-not-found]
except Exception:  # noqa: BLE001
    Vector = None  # type: ignore[assignment]


class _GUID(TypeDecorator):
    """Cross-DB UUID column: native UUID on Postgres, 36-char string on SQLite."""

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(UUID(as_uuid=True))
        return dialect.type_descriptor(String(36))

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value if dialect.name == "postgresql" else str(value)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if isinstance(value, uuid.UUID):
            return value
        return uuid.UUID(str(value))


class _StrArray(TypeDecorator):
    """ARRAY(String) on Postgres, JSON list on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(String))
        return dialect.type_descriptor(JSON)


class _UUIDArray(TypeDecorator):
    """ARRAY(UUID) on Postgres, JSON list of strings on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(UUID(as_uuid=True)))
        return dialect.type_descriptor(JSON)

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return [str(v) for v in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return value
        return [uuid.UUID(v) if isinstance(v, str) else v for v in value]


class _JSONBType(TypeDecorator):
    """JSONB on Postgres, JSON on SQLite."""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB)
        return dialect.type_descriptor(JSON)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class TimestampMixin:
    # Both columns keep a `server_default` so rows written outside the ORM
    # (migrations, raw SQL, bulk loads) still get timestamps, and add a
    # Python-side default so the ORM knows the value it wrote.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        server_default=func.now(),
        # Python-side, deliberately not `onupdate=func.now()`. A SQL-side
        # onupdate computes the value in the database, so the ORM does not know
        # what was written and expires the attribute. The next read triggers a
        # lazy refresh — synchronous IO from an async context, which raises
        # MissingGreenlet the moment anything serialises the object after an
        # update. Computing it here keeps the instance consistent without a
        # round trip.
        onupdate=_utcnow,
        nullable=False,
    )


# ---------------------------------------------------------------------------
# companies
# ---------------------------------------------------------------------------
class Company(Base, TimestampMixin):
    __tablename__ = "companies"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    ticker: Mapped[str] = mapped_column(String(10), unique=True, nullable=False, index=True)
    cik: Mapped[str] = mapped_column(String(20), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    sector: Mapped[str | None] = mapped_column(String(100))
    industry: Mapped[str | None] = mapped_column(String(100))
    market_cap: Mapped[int | None] = mapped_column(BigInteger)

    filings: Mapped[list["Filing"]] = relationship(
        "Filing", back_populates="company", cascade="all, delete-orphan"
    )


# ---------------------------------------------------------------------------
# filings
# ---------------------------------------------------------------------------
class Filing(Base):
    __tablename__ = "filings"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    filing_type: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    accession_number: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    filed_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    period_of_report: Mapped[date | None] = mapped_column(Date, index=True)
    raw_text: Mapped[str | None] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    edgar_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped[Company] = relationship("Company", back_populates="filings")
    facts: Mapped[list["ExtractedFact"]] = relationship(
        "ExtractedFact",
        back_populates="filing",
        cascade="all, delete-orphan",
        foreign_keys="ExtractedFact.filing_id",
    )


# ---------------------------------------------------------------------------
# extracted_facts
# ---------------------------------------------------------------------------
class ExtractedFact(Base):
    __tablename__ = "extracted_facts"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    filing_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    fact_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    subject: Mapped[str | None] = mapped_column(String(255))
    value: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float | None] = mapped_column(Float)
    source_section: Mapped[str | None] = mapped_column(String(100))
    source_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    filing: Mapped[Filing] = relationship(
        "Filing", back_populates="facts", foreign_keys=[filing_id]
    )


# ---------------------------------------------------------------------------
# company_relationships (graph edges)
# ---------------------------------------------------------------------------
class CompanyRelationship(Base):
    __tablename__ = "company_relationships"
    __table_args__ = (
        UniqueConstraint(
            "source_company_id",
            "target_company_id",
            "relationship_type",
            name="uq_company_rel",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    source_company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relationship_type: Mapped[str] = mapped_column(String(50), nullable=False)
    strength: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)
    source_filing_id: Mapped[uuid.UUID | None] = mapped_column(
        _GUID(), ForeignKey("filings.id", ondelete="SET NULL")
    )
    evidence_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# filing_deltas
# ---------------------------------------------------------------------------
class FilingDelta(Base):
    __tablename__ = "filing_deltas"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    current_filing_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("filings.id", ondelete="CASCADE"), nullable=False, index=True
    )
    prior_filing_id: Mapped[uuid.UUID | None] = mapped_column(
        _GUID(), ForeignKey("filings.id", ondelete="SET NULL")
    )
    delta_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    section: Mapped[str | None] = mapped_column(String(100))
    description: Mapped[str] = mapped_column(Text, nullable=False)
    significance_score: Mapped[float | None] = mapped_column(Float, index=True)
    previous_text: Mapped[str | None] = mapped_column(Text)
    current_text: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# theses
# ---------------------------------------------------------------------------
class Thesis(Base, TimestampMixin):
    __tablename__ = "theses"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    thesis_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    direction: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    confidence_score: Mapped[float] = mapped_column(Float, nullable=False, index=True)

    trigger_company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )
    affected_company_ids: Mapped[list[uuid.UUID]] = mapped_column(
        _UUIDArray(), nullable=False, default=list
    )

    evidence_chain: Mapped[list[dict[str, Any]]] = mapped_column(
        _JSONBType(), nullable=False, default=list
    )
    competing_thesis: Mapped[str | None] = mapped_column(Text)
    invalidation_criteria: Mapped[list[str]] = mapped_column(_StrArray(), default=list)

    catalyst: Mapped[str | None] = mapped_column(Text)
    time_horizon: Mapped[str | None] = mapped_column(String(50))

    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False, index=True)
    pm_notes: Mapped[str | None] = mapped_column(Text)

    trigger_delta_ids: Mapped[list[uuid.UUID]] = mapped_column(_UUIDArray(), default=list)
    trigger_fact_ids: Mapped[list[uuid.UUID]] = mapped_column(_UUIDArray(), default=list)


# ---------------------------------------------------------------------------
# embeddings
# ---------------------------------------------------------------------------
class Embedding(Base):
    __tablename__ = "embeddings"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    source_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    source_id: Mapped[uuid.UUID] = mapped_column(_GUID(), nullable=False, index=True)
    chunk_index: Mapped[int | None] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text, nullable=False)

    # On Postgres this is a real `vector(3072)` column; on SQLite we fall back to JSON.
    if Vector is not None:
        embedding: Mapped[list[float] | None] = mapped_column(Vector(3072), nullable=True)
    else:  # pragma: no cover - SQLite test fallback
        embedding: Mapped[list[float] | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ---------------------------------------------------------------------------
# agent_jobs
# ---------------------------------------------------------------------------
class AgentJob(Base):
    __tablename__ = "agent_jobs"

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False, index=True)
    payload: Mapped[dict[str, Any] | None] = mapped_column(_JSONBType())
    result: Mapped[dict[str, Any] | None] = mapped_column(_JSONBType())
    error: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
