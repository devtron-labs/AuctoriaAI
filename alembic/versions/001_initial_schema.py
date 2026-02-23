"""Initial schema

Revision ID: 001
Revises:
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Enums
    conn = op.get_bind()
    if not conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'documentstatus'")).scalar():
        postgresql.ENUM(
            "DRAFT", "VALIDATING", "PASSED", "HUMAN_REVIEW", "APPROVED", "BLOCKED",
            name="documentstatus",
        ).create(conn)
    if not conn.execute(sa.text("SELECT 1 FROM pg_type WHERE typname = 'claimtype'")).scalar():
        postgresql.ENUM(
            "INTEGRATION", "COMPLIANCE", "PERFORMANCE",
            name="claimtype",
        ).create(conn)

    op.create_table(
        "documents",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column(
            "status",
            postgresql.ENUM("DRAFT", "VALIDATING", "PASSED", "HUMAN_REVIEW", "APPROVED", "BLOCKED", name="documentstatus", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "draft_versions",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("iteration_number", sa.Integer(), nullable=False),
        sa.Column("content_markdown", sa.Text(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_draft_versions_document_id", "draft_versions", ["document_id"])

    op.create_table(
        "fact_sheets",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("structured_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_fact_sheets_document_id", "fact_sheets", ["document_id"])

    op.create_table(
        "claim_registry",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column(
            "claim_type",
            postgresql.ENUM("INTEGRATION", "COMPLIANCE", "PERFORMANCE", name="claimtype", create_type=False),
            nullable=False,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.String(), nullable=False),
        sa.Column("document_id", sa.String(), nullable=False),
        sa.Column("action", sa.String(512), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["document_id"], ["documents.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_document_id", "audit_logs", ["document_id"])


def downgrade() -> None:
    op.drop_index("ix_audit_logs_document_id", table_name="audit_logs")
    op.drop_table("audit_logs")
    op.drop_table("claim_registry")
    op.drop_index("ix_fact_sheets_document_id", table_name="fact_sheets")
    op.drop_table("fact_sheets")
    op.drop_index("ix_draft_versions_document_id", table_name="draft_versions")
    op.drop_table("draft_versions")
    op.drop_table("documents")

    op.execute("DROP TYPE IF EXISTS documentstatus")
    op.execute("DROP TYPE IF EXISTS claimtype")
