"""financial_facts: bitemporal store for XBRL-reported values.

Adds a table for structured financials read from the SEC `companyfacts`
endpoint, kept separate from `extracted_facts` (narrative claims produced by a
language model) because the two have different provenance and different trust
properties.

The table records both time axes. `period_start`/`period_end` is the period a
value describes; `filed_date` is when it became public. Restatements are
inserted as new rows rather than updating existing ones, so a period reported
twice retains both values and a query can reconstruct what was known on any past
date by filtering on `filed_date`.

Revision ID: 002_financial_facts
Revises: 001_initial_schema
Create Date: 2026-07-19

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "002_financial_facts"
down_revision: Union[str, None] = "001_initial_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "financial_facts",
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
        sa.Column("concept", sa.String(50), nullable=False),
        sa.Column("tag", sa.String(120), nullable=False),
        sa.Column("taxonomy", sa.String(20), nullable=False),
        sa.Column("unit", sa.String(30), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        # Instant facts store period_start = period_end and set is_instant.
        # A NULL start would defeat the unique constraint below, because NULLs
        # compare as distinct.
        sa.Column("period_start", sa.Date, nullable=False),
        sa.Column("period_end", sa.Date, nullable=False),
        sa.Column(
            "is_instant",
            sa.Boolean,
            nullable=False,
            server_default=sa.text("false"),
        ),
        # Transaction time. Every point-in-time query filters on this.
        sa.Column("filed_date", sa.Date, nullable=False),
        sa.Column("accession_number", sa.String(25), nullable=False),
        sa.Column("form", sa.String(20)),
        sa.Column("fiscal_year", sa.Integer),
        sa.Column("fiscal_period", sa.String(10)),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        # One filing reports a given period once. Rows differing only by
        # accession number are an original and its restatement; both are kept.
        sa.UniqueConstraint(
            "company_id",
            "concept",
            "unit",
            "period_start",
            "period_end",
            "accession_number",
            name="uq_financial_facts_identity",
        ),
    )

    op.create_index("ix_financial_facts_company_id", "financial_facts", ["company_id"])
    op.create_index("ix_financial_facts_concept", "financial_facts", ["concept"])
    op.create_index("ix_financial_facts_period_end", "financial_facts", ["period_end"])
    op.create_index("ix_financial_facts_filed_date", "financial_facts", ["filed_date"])
    op.create_index(
        "ix_financial_facts_accession_number", "financial_facts", ["accession_number"]
    )
    # Dominant access pattern: one company's series for one concept, restricted
    # to what had been filed by a given date.
    op.create_index(
        "ix_financial_facts_lookup",
        "financial_facts",
        ["company_id", "concept", "filed_date"],
    )


def downgrade() -> None:
    op.drop_index("ix_financial_facts_lookup", table_name="financial_facts")
    op.drop_index("ix_financial_facts_accession_number", table_name="financial_facts")
    op.drop_index("ix_financial_facts_filed_date", table_name="financial_facts")
    op.drop_index("ix_financial_facts_period_end", table_name="financial_facts")
    op.drop_index("ix_financial_facts_concept", table_name="financial_facts")
    op.drop_index("ix_financial_facts_company_id", table_name="financial_facts")
    op.drop_table("financial_facts")
