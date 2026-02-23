"""EPIC 2 Ticket 2.3 — Claim registry approval metadata and expiry

Adds to the claim_registry table:
  expiry_date   TIMESTAMPTZ  NULLABLE
  approved_by   VARCHAR(512) NULLABLE
  approved_at   TIMESTAMPTZ  NULLABLE
  updated_at    TIMESTAMPTZ  NOT NULL  DEFAULT now()
                (required by Ticket 2.4 registry freshness check)

Revision ID: 004
Revises: 003
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "004"
down_revision: Union[str, None] = "003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Add approval metadata and expiry columns ──────────────────────────────
    op.add_column(
        "claim_registry",
        sa.Column("expiry_date", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "claim_registry",
        sa.Column("approved_by", sa.String(512), nullable=True),
    )
    op.add_column(
        "claim_registry",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )

    # ── Add updated_at required by Ticket 2.4 staleness check ────────────────
    # Back-fill existing rows with the current timestamp before adding NOT NULL.
    op.add_column(
        "claim_registry",
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=True,              # temporarily nullable for back-fill
        ),
    )
    op.execute(
        sa.text("UPDATE claim_registry SET updated_at = now() WHERE updated_at IS NULL")
    )
    op.alter_column(
        "claim_registry",
        "updated_at",
        nullable=False,
        existing_type=sa.DateTime(timezone=True),
    )

    # Index on updated_at to support efficient staleness queries
    op.create_index("ix_claim_registry_updated_at", "claim_registry", ["updated_at"])
    # Index on expiry_date for efficient expiry filtering
    op.create_index("ix_claim_registry_expiry_date", "claim_registry", ["expiry_date"])


def downgrade() -> None:
    op.drop_index("ix_claim_registry_expiry_date", table_name="claim_registry")
    op.drop_index("ix_claim_registry_updated_at", table_name="claim_registry")

    op.drop_column("claim_registry", "updated_at")
    op.drop_column("claim_registry", "approved_at")
    op.drop_column("claim_registry", "approved_by")
    op.drop_column("claim_registry", "expiry_date")
