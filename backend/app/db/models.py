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
    Index,
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
# financial_facts (XBRL, bitemporal)
# ---------------------------------------------------------------------------
class FinancialFact(Base):
    """A structured financial value as reported in XBRL.

    Distinct from `ExtractedFact`, which holds narrative claims pulled out by a
    language model. These values are read directly from the SEC `companyfacts`
    endpoint: they are what the company filed, so there is nothing to infer and
    nothing to hallucinate.

    The table is **bitemporal**, and that is the point of it:

    * `period_end` (with `period_start`) is *valid time* — the period the number
      describes.
    * `filed_date` is *transaction time* — when the number became public.

    Restatements are stored as additional rows rather than updates, so a period
    reported twice keeps both values. Queries reconstructing a past view filter
    on `filed_date`; filtering on `period_end` instead would admit corrections
    that nobody had at the time, which is the mechanism behind lookahead bias.
    Rows are therefore never updated in place.
    """

    __tablename__ = "financial_facts"
    __table_args__ = (
        # A given filing reports a given period once. Two rows differing only by
        # accession number are an original and a restatement, and both are kept.
        UniqueConstraint(
            "company_id",
            "concept",
            "unit",
            "period_start",
            "period_end",
            "accession_number",
            name="uq_financial_facts_identity",
        ),
        # The dominant access pattern: one company's series for one concept,
        # restricted to what was known at a point in time.
        Index(
            "ix_financial_facts_lookup",
            "company_id",
            "concept",
            "filed_date",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(_GUID(), primary_key=True, default=_uuid)
    company_id: Mapped[uuid.UUID] = mapped_column(
        _GUID(), ForeignKey("companies.id", ondelete="CASCADE"), nullable=False, index=True
    )

    concept: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    """Canonical name, e.g. `revenue`. See app.data.xbrl.CONCEPT_TAGS."""

    tag: Mapped[str] = mapped_column(String(120), nullable=False)
    """Originating us-gaap/dei tag, kept so a value can be traced to its source."""

    taxonomy: Mapped[str] = mapped_column(String(20), nullable=False)
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)

    # Instant facts (balance-sheet items) have no true start date. Rather than
    # storing NULL, `period_start` is set equal to `period_end` and `is_instant`
    # records the distinction. NULLs are treated as distinct by UNIQUE
    # constraints on both Postgres and SQLite, which would let duplicate instant
    # facts through the constraint above.
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    is_instant: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    filed_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    """Transaction time. Every as-of query filters on this column."""

    accession_number: Mapped[str] = mapped_column(String(25), nullable=False, index=True)
    form: Mapped[str | None] = mapped_column(String(20))
    fiscal_year: Mapped[int | None] = mapped_column(Integer)
    fiscal_period: Mapped[str | None] = mapped_column(String(10))

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    company: Mapped[Company] = relationship("Company", foreign_keys=[company_id])


# ---------------------------------------------------------------------------
# company_relationships (graph edges)
# ---------------------------------------------------------------------------
class CompanyRelationship(Base):
    """A directed edge between two companies, valid over a period of time.

    Edges are **temporal**. A supplier relationship disclosed in a 2022 10-K and
    absent from the 2024 one did not cease to have existed — it ceased to be
    asserted, on a knowable date. Modelling that as an update would destroy the
    only record that the relationship was ever claimed, and would make any
    historical graph query silently wrong.

    So edges are closed rather than deleted: `known_until` is set on the row and
    a new row opens if the relationship is later re-asserted. A graph as of date
    D is every row where `known_from <= D` and `known_until` is either null or
    after D. This is the edge-level counterpart to the bitemporality in
    `financial_facts`, and it is what makes `GET /graph?as_of=` truthful rather
    than decorative.
    """

    __tablename__ = "company_relationships"
    __table_args__ = (
        # `known_from` participates in identity: the same relationship may be
        # asserted, closed, and asserted again by a later filing.
        UniqueConstraint(
            "source_company_id",
            "target_company_id",
            "relationship_type",
            "known_from",
            name="uq_company_rel",
        ),
        # Serves the dominant traversal: open edges for a node as of a date.
        Index(
            "ix_company_rel_temporal",
            "source_company_id",
            "known_from",
            "known_until",
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

    known_from: Mapped[date] = mapped_column(
        Date, nullable=False, index=True, default=lambda: date.today()
    )
    """Filing date of the document that asserted this edge.

    Callers should pass the filing date explicitly. The default exists so that
    a writer which does not yet supply one degrades to "known as of now" rather
    than failing the insert — wrong by at most the ingestion lag, instead of
    losing the edge entirely.
    """

    known_until: Mapped[date | None] = mapped_column(Date, index=True)
    """Filing date of the document in which the assertion disappeared.

    Null means still open. Half-open interval: an edge is live on date D when
    `known_from <= D < known_until`, so a close and a re-open on the same day do
    not both match.
    """

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    @property
    def is_open(self) -> bool:
        return self.known_until is None


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
