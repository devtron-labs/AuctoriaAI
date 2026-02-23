"""Add llm_timeout_seconds to system_settings.

Revision ID: 013
Revises: 012
Create Date: 2026-02-20

Changes to system_settings:
1. ADD llm_timeout_seconds INTEGER NOT NULL DEFAULT 120
   Configurable per-LLM-call timeout in seconds (30–600).
   Admin-editable via the System Settings UI.
   Existing rows receive 120 (2 minutes — previous hardcoded default).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "013"
down_revision: Union[str, None] = "012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "system_settings",
        sa.Column(
            "llm_timeout_seconds",
            sa.Integer(),
            nullable=False,
            server_default="120",
        ),
    )


def downgrade() -> None:
    op.drop_column("system_settings", "llm_timeout_seconds")
