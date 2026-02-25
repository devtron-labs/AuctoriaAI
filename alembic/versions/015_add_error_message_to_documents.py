"""Add error_message column to documents table.

Revision ID: 015
Revises: 014
Create Date: 2026-02-25

"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "015"
down_revision: Union[str, None] = "014"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add error_message column to documents table
    op.add_column("documents", sa.Column("error_message", sa.Text(), nullable=True))


def downgrade() -> None:
    # Remove error_message column from documents table
    op.drop_column("documents", "error_message")
