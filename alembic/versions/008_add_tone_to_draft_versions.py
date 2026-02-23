"""EPIC 4 — Add tone column to draft_versions

Stores the prose tone ('formal', 'conversational', 'technical') used when
generating or improving each DraftVersion. This allows the QA iteration loop
to preserve the original generation tone across rubric-driven improvement cycles
instead of defaulting to 'formal'.

New column:
  - tone: VARCHAR(64), NOT NULL, default 'formal'

Backfills all existing rows with 'formal' (the previous implicit default).

Revision ID: 008
Revises: 007
Create Date: 2026-02-20
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "008"
down_revision: Union[str, None] = "007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draft_versions",
        sa.Column(
            "tone",
            sa.String(64),
            nullable=False,
            server_default=sa.text("'formal'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("draft_versions", "tone")
