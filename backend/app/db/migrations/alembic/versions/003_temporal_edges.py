"""Make company_relationships temporal.

Adds `known_from` / `known_until` so an edge records the window during which it
was asserted, and widens the unique constraint to include `known_from` so a
relationship can be closed and later re-asserted.

Existing rows are backfilled from `created_at` and left open. That is the only
honest interpretation available: the previous schema recorded no temporal
information, so all that can be said about a pre-existing edge is that it was
known by the time the row was written.

Revision ID: 003_temporal_edges
Revises: 002_financial_facts
Create Date: 2026-07-19

"""
from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "003_temporal_edges"
down_revision: Union[str, None] = "002_financial_facts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Added nullable so existing rows survive, then backfilled and tightened.
    op.add_column(
        "company_relationships", sa.Column("known_from", sa.Date(), nullable=True)
    )
    op.add_column(
        "company_relationships", sa.Column("known_until", sa.Date(), nullable=True)
    )

    op.execute(
        "UPDATE company_relationships "
        "SET known_from = CAST(created_at AS DATE) "
        "WHERE known_from IS NULL"
    )

    op.alter_column("company_relationships", "known_from", nullable=False)

    # The old constraint permitted exactly one row per edge, which is precisely
    # what makes history impossible. `known_from` joins the key so the same
    # relationship can be re-asserted by a later filing.
    op.drop_constraint("uq_company_rel", "company_relationships", type_="unique")
    op.create_unique_constraint(
        "uq_company_rel",
        "company_relationships",
        ["source_company_id", "target_company_id", "relationship_type", "known_from"],
    )

    op.create_index(
        "ix_company_relationships_known_from", "company_relationships", ["known_from"]
    )
    op.create_index(
        "ix_company_relationships_known_until", "company_relationships", ["known_until"]
    )
    op.create_index(
        "ix_company_rel_temporal",
        "company_relationships",
        ["source_company_id", "known_from", "known_until"],
    )


def downgrade() -> None:
    op.drop_index("ix_company_rel_temporal", table_name="company_relationships")
    op.drop_index("ix_company_relationships_known_until", table_name="company_relationships")
    op.drop_index("ix_company_relationships_known_from", table_name="company_relationships")

    op.drop_constraint("uq_company_rel", "company_relationships", type_="unique")

    # Reverting to a single row per edge is lossy: any relationship asserted
    # more than once will collide. Close duplicates before downgrading.
    op.execute(
        "DELETE FROM company_relationships WHERE id NOT IN ("
        "  SELECT MIN(id) FROM company_relationships"
        "  GROUP BY source_company_id, target_company_id, relationship_type"
        ")"
    )
    op.create_unique_constraint(
        "uq_company_rel",
        "company_relationships",
        ["source_company_id", "target_company_id", "relationship_type"],
    )

    op.drop_column("company_relationships", "known_until")
    op.drop_column("company_relationships", "known_from")
