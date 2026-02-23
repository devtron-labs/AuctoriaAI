"""EPIC 5 — Add validation_report to documents

Adds a nullable JSONB column `validation_report` to the documents table.
This column stores the full claim validation report produced by the
claim extraction + registry validation pipeline.

Revision ID: 006
Revises: 005
Create Date: 2026-02-19
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "006"
down_revision: Union[str, None] = "005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "documents",
        sa.Column(
            "validation_report",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("documents", "validation_report")
