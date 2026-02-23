"""Add pipeline progress tracking columns to documents.

Revision ID: 012
Revises: 011
Create Date: 2026-02-20

Changes to documents:
1. ADD current_stage VARCHAR NULL
   Human-readable name of the current pipeline stage, e.g. "VALIDATION_STARTED",
   "FACTSHEET_EXTRACTED", "QA_COMPLETED", "DRAFT_GENERATED". NULL until the
   first pipeline step runs. Updated atomically with each stage transition.

2. ADD validation_progress INTEGER NOT NULL DEFAULT 0
   Integer 0–100 representing pipeline completion percentage.
   Polled by the frontend via GET /api/v1/documents/{id}/status to drive
   the progress bar. Existing rows receive 0 (no progress recorded yet).

No data is dropped. Both changes are backward-compatible.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "012"
down_revision: Union[str, None] = "011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add current_stage — nullable, no default needed
    op.add_column(
        "documents",
        sa.Column(
            "current_stage",
            sa.String(),
            nullable=True,
        ),
    )

    # 2. Add validation_progress — NOT NULL with server default 0
    op.add_column(
        "documents",
        sa.Column(
            "validation_progress",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "validation_progress")
    op.drop_column("documents", "current_stage")
