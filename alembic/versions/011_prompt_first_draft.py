"""Prompt-first draft generation: add user_prompt, source_document_id; make document_id nullable.

Revision ID: 011
Revises: 010
Create Date: 2026-02-20

Changes to draft_versions:
1. ALTER document_id: NOT NULL → NULL
   Allows standalone drafts created via POST /api/v1/drafts/generate without a
   parent document. Existing rows are unaffected (all have valid document UUIDs).

2. ADD user_prompt TEXT NOT NULL DEFAULT ''
   Stores the user's original natural-language prompt. Server default '' ensures
   existing rows remain valid; application layer always supplies a real value for
   new rows.

3. ADD source_document_id UUID NULL
   References the document used as optional context during prompt-first generation.
   No foreign-key constraint — the source document may be deleted independently
   without affecting the draft. Existing rows receive NULL.

No data is dropped. All changes are backward-compatible.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID
from alembic import op

revision: str = "011"
down_revision: Union[str, None] = "010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Make document_id nullable (allows standalone prompt-first drafts)
    op.alter_column(
        "draft_versions",
        "document_id",
        existing_type=UUID(as_uuid=False),
        nullable=True,
    )

    # 2. Add user_prompt — server_default='' preserves existing rows
    op.add_column(
        "draft_versions",
        sa.Column(
            "user_prompt",
            sa.Text(),
            nullable=False,
            server_default="",
        ),
    )

    # 3. Add source_document_id — optional context document reference (no FK)
    op.add_column(
        "draft_versions",
        sa.Column(
            "source_document_id",
            UUID(as_uuid=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    # Remove new columns
    op.drop_column("draft_versions", "source_document_id")
    op.drop_column("draft_versions", "user_prompt")

    # Restore document_id NOT NULL constraint.
    # WARNING: this will fail if any rows have document_id = NULL.
    # Delete or reassign those rows before running downgrade.
    op.alter_column(
        "draft_versions",
        "document_id",
        existing_type=UUID(as_uuid=False),
        nullable=False,
    )
