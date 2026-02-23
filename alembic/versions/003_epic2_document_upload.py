"""EPIC 2 Ticket 2.1 — Document upload columns + documentclassification ENUM

Adds to the documents table:
  file_path        VARCHAR(1024) NULLABLE
  file_hash        VARCHAR(64)   NULLABLE  (SHA-256 hex digest)
  classification   documentclassification ENUM NULLABLE
  file_size        BIGINT        NULLABLE  (bytes)
  mime_type        VARCHAR(128)  NULLABLE

Also creates the documentclassification PostgreSQL ENUM type.

Revision ID: 003
Revises: 002
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "003"
down_revision: Union[str, None] = "002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    conn = op.get_bind()

    # ── Create documentclassification ENUM (idempotent) ──────────────────────
    if not conn.execute(
        sa.text("SELECT 1 FROM pg_type WHERE typname = 'documentclassification'")
    ).scalar():
        postgresql.ENUM(
            "INTERNAL", "CONFIDENTIAL", "PUBLIC",
            name="documentclassification",
        ).create(conn)

    # ── Add new columns to documents ──────────────────────────────────────────
    op.add_column(
        "documents",
        sa.Column("file_path", sa.String(1024), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("file_hash", sa.String(64), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column(
            "classification",
            postgresql.ENUM(
                "INTERNAL", "CONFIDENTIAL", "PUBLIC",
                name="documentclassification",
                create_type=False,
            ),
            nullable=True,
        ),
    )
    op.add_column(
        "documents",
        sa.Column("file_size", sa.BigInteger(), nullable=True),
    )
    op.add_column(
        "documents",
        sa.Column("mime_type", sa.String(128), nullable=True),
    )

    # Index on file_hash for fast duplicate detection
    op.create_index("ix_documents_file_hash", "documents", ["file_hash"])


def downgrade() -> None:
    op.drop_index("ix_documents_file_hash", table_name="documents")

    op.drop_column("documents", "mime_type")
    op.drop_column("documents", "file_size")
    op.drop_column("documents", "classification")
    op.drop_column("documents", "file_hash")
    op.drop_column("documents", "file_path")

    op.execute("DROP TYPE IF EXISTS documentclassification")
