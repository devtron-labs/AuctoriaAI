"""EPIC 4 — Add feedback_text to draft_versions

Adds a nullable TEXT column `feedback_text` to the draft_versions table.
This column stores the rubric evaluation feedback returned by the LLM
during each QA iteration so that improvement prompts are traceable.

Revision ID: 005
Revises: 004
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "005"
down_revision: Union[str, None] = "004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draft_versions",
        sa.Column("feedback_text", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("draft_versions", "feedback_text")
