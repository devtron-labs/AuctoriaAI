"""Fix system_settings.id: alter VARCHAR(36) → native PostgreSQL UUID.

Migration 009 created system_settings.id as sa.String(36) (VARCHAR), but the
SQLAlchemy model defines it as UUID(as_uuid=False). This type drift causes:

    operator does not exist: character varying = uuid

The fix casts the existing column value to the native PostgreSQL uuid type using
the USING clause. The seed row inserted in migration 009 already contains a valid
UUID string, so the cast is safe.

Revision ID: 010
Revises: 009
Create Date: 2026-02-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "010"
down_revision: Union[str, None] = "009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Safety guard: abort if any id value is not a valid lowercase UUID string.
    # A malformed value would cause the USING cast to raise a PostgreSQL error.
    conn = op.get_bind()
    bad_rows = conn.execute(
        sa.text(
            "SELECT id FROM system_settings "
            "WHERE id !~ "
            "'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$'"
        )
    ).fetchall()
    if bad_rows:
        raise RuntimeError(
            f"Aborting migration 010: non-UUID values found in system_settings.id: "
            f"{[r[0] for r in bad_rows]}"
        )

    op.alter_column(
        "system_settings",
        "id",
        type_=UUID(as_uuid=False),
        postgresql_using="id::uuid",
    )


def downgrade() -> None:
    op.alter_column(
        "system_settings",
        "id",
        type_=sa.String(36),
        postgresql_using="id::text",
    )
