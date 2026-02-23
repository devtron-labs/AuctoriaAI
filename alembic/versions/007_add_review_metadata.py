"""EPIC 7 — Add review metadata to documents

Adds human review tracking columns to the documents table to support the
Human Review & Approval workflow.

New columns:
  - reviewed_by:    VARCHAR(512), nullable — name of the reviewer
  - reviewed_at:    TIMESTAMPTZ, nullable  — when the review decision was made
  - review_notes:   TEXT, nullable         — approval notes or rejection reason
  - force_approved: BOOLEAN, default false — admin override flag

Revision ID: 007
Revises: 006
Create Date: 2026-02-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "007"
down_revision: Union[str, None] = "006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column("reviewed_by", sa.String(512), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("review_notes", sa.Text(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "force_approved",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "force_approved")
    op.drop_column("documents", "review_notes")
    op.drop_column("documents", "reviewed_at")
    op.drop_column("documents", "reviewed_by")
