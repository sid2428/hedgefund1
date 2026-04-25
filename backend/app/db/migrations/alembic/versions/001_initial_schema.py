"""Initial schema: companies, filings, extracted_facts, company_relationships,
filing_deltas, theses, embeddings, agent_jobs.

Revision ID: 001_initial_schema
Revises:
Create Date: 2026-04-25

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "001_initial_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # pgvector extension for the embeddings table.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ---- companies ------------------------------------------------------
    op.create_table(
        "companies",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("ticker", sa.String(10), nullable=False, unique=True),
        sa.Column("cik", sa.String(20), nullable=False, unique=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("sector", sa.String(100)),
        sa.Column("industry", sa.String(100)),
        sa.Column("market_cap", sa.BigInteger),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_companies_ticker", "companies", ["ticker"])
    op.create_index("ix_companies_cik", "companies", ["cik"])

    # ---- filings --------------------------------------------------------
    op.create_table(
        "filings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("filing_type", sa.String(20), nullable=False),
        sa.Column("accession_number", sa.String(50), nullable=False, unique=True),
        sa.Column("filed_date", sa.Date, nullable=False),
        sa.Column("period_of_report", sa.Date),
        sa.Column("raw_text", sa.Text),
        sa.Column("processed", sa.Boolean, nullable=False, server_default=sa.text("false")),
        sa.Column("edgar_url", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_filings_company_id", "filings", ["company_id"])
    op.create_index("ix_filings_filing_type", "filings", ["filing_type"])
    op.create_index("ix_filings_filed_date", "filings", ["filed_date"])
    op.create_index("ix_filings_period", "filings", ["period_of_report"])
    op.create_index("ix_filings_processed", "filings", ["processed"])

    # ---- extracted_facts -----------------------------------------------
    op.create_table(
        "extracted_facts",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "filing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("filings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("fact_type", sa.String(50), nullable=False),
        sa.Column("subject", sa.String(255)),
        sa.Column("value", sa.Text, nullable=False),
        sa.Column("confidence", sa.Float),
        sa.Column("source_section", sa.String(100)),
        sa.Column("source_text", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_extracted_facts_filing_id", "extracted_facts", ["filing_id"])
    op.create_index("ix_extracted_facts_company_id", "extracted_facts", ["company_id"])
    op.create_index("ix_extracted_facts_type", "extracted_facts", ["fact_type"])

    # ---- company_relationships -----------------------------------------
    op.create_table(
        "company_relationships",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "source_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "target_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("relationship_type", sa.String(50), nullable=False),
        sa.Column("strength", sa.Float, nullable=False, server_default=sa.text("1.0")),
        sa.Column(
            "source_filing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("filings.id", ondelete="SET NULL"),
        ),
        sa.Column("evidence_text", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.UniqueConstraint(
            "source_company_id",
            "target_company_id",
            "relationship_type",
            name="uq_company_rel",
        ),
    )
    op.create_index("ix_rel_source", "company_relationships", ["source_company_id"])
    op.create_index("ix_rel_target", "company_relationships", ["target_company_id"])

    # ---- filing_deltas --------------------------------------------------
    op.create_table(
        "filing_deltas",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "current_filing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("filings.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "prior_filing_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("filings.id", ondelete="SET NULL"),
        ),
        sa.Column("delta_type", sa.String(50), nullable=False),
        sa.Column("section", sa.String(100)),
        sa.Column("description", sa.Text, nullable=False),
        sa.Column("significance_score", sa.Float),
        sa.Column("previous_text", sa.Text),
        sa.Column("current_text", sa.Text),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_deltas_company_id", "filing_deltas", ["company_id"])
    op.create_index("ix_deltas_current", "filing_deltas", ["current_filing_id"])
    op.create_index("ix_deltas_type", "filing_deltas", ["delta_type"])
    op.create_index("ix_deltas_significance", "filing_deltas", ["significance_score"])

    # ---- theses ---------------------------------------------------------
    op.create_table(
        "theses",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("summary", sa.Text, nullable=False),
        sa.Column("thesis_type", sa.String(50), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("confidence_score", sa.Float, nullable=False),
        sa.Column(
            "trigger_company_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("companies.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "affected_company_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            nullable=False,
            server_default="{}",
        ),
        sa.Column("evidence_chain", postgresql.JSONB, nullable=False, server_default="[]"),
        sa.Column("competing_thesis", sa.Text),
        sa.Column(
            "invalidation_criteria",
            postgresql.ARRAY(sa.String),
            server_default="{}",
        ),
        sa.Column("catalyst", sa.Text),
        sa.Column("time_horizon", sa.String(50)),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default="pending",
        ),
        sa.Column("pm_notes", sa.Text),
        sa.Column(
            "trigger_delta_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
        ),
        sa.Column(
            "trigger_fact_ids",
            postgresql.ARRAY(postgresql.UUID(as_uuid=True)),
            server_default="{}",
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_theses_status", "theses", ["status"])
    op.create_index("ix_theses_thesis_type", "theses", ["thesis_type"])
    op.create_index("ix_theses_direction", "theses", ["direction"])
    op.create_index("ix_theses_confidence", "theses", ["confidence_score"])
    op.create_index("ix_theses_trigger_company", "theses", ["trigger_company_id"])

    # ---- embeddings -----------------------------------------------------
    op.create_table(
        "embeddings",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("source_type", sa.String(50), nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("chunk_index", sa.Integer),
        sa.Column("text", sa.Text, nullable=False),
        sa.Column(
            "embedding",
            sa.dialects.postgresql.ARRAY(sa.Float),
            # Replaced below with a real `vector(3072)` column via raw SQL.
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    # Swap the placeholder ARRAY(Float) for a real pgvector column.
    op.execute("ALTER TABLE embeddings DROP COLUMN embedding")
    op.execute("ALTER TABLE embeddings ADD COLUMN embedding vector(3072)")
    op.create_index("ix_embeddings_source", "embeddings", ["source_type", "source_id"])
    op.execute(
        "CREATE INDEX ix_embeddings_vec ON embeddings "
        "USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100)"
    )

    # ---- agent_jobs -----------------------------------------------------
    op.create_table(
        "agent_jobs",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("job_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("payload", postgresql.JSONB),
        sa.Column("result", postgresql.JSONB),
        sa.Column("error", sa.Text),
        sa.Column("started_at", sa.DateTime(timezone=True)),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_jobs_status", "agent_jobs", ["status"])
    op.create_index("ix_jobs_type", "agent_jobs", ["job_type"])


def downgrade() -> None:
    op.drop_table("agent_jobs")
    op.drop_index("ix_embeddings_vec", table_name="embeddings")
    op.drop_table("embeddings")
    op.drop_table("theses")
    op.drop_table("filing_deltas")
    op.drop_table("company_relationships")
    op.drop_table("extracted_facts")
    op.drop_table("filings")
    op.drop_table("companies")
    op.execute("DROP EXTENSION IF EXISTS vector")
