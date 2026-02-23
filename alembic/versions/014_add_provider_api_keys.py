"""Add per-provider API key columns to system_settings.

Revision ID: 014
Revises: 013
Create Date: 2026-02-23

Changes to system_settings:
1. ADD anthropic_api_key  VARCHAR(512) NULL
2. ADD openai_api_key     VARCHAR(512) NULL
3. ADD google_api_key     VARCHAR(512) NULL
4. ADD perplexity_api_key VARCHAR(512) NULL
5. ADD xai_api_key        VARCHAR(512) NULL

anthropic_api_key falls back to the ANTHROPIC_API_KEY env var when null.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "014"
down_revision: Union[str, None] = "013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("system_settings", sa.Column("anthropic_api_key",  sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("openai_api_key",     sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("google_api_key",     sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("perplexity_api_key", sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("xai_api_key",        sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "xai_api_key")
    op.drop_column("system_settings", "perplexity_api_key")
    op.drop_column("system_settings", "google_api_key")
    op.drop_column("system_settings", "openai_api_key")
    op.drop_column("system_settings", "anthropic_api_key")
