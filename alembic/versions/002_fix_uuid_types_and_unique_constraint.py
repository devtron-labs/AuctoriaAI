"""Fix UUID column types and add UNIQUE constraint on draft_versions

Revision ID: 002
Revises: 001
Create Date: 2026-02-18
"""

from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "002"
down_revision: Union[str, None] = "001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Drop foreign key constraints before altering column types ─────────────
    op.drop_constraint("draft_versions_document_id_fkey", "draft_versions", type_="foreignkey")
    op.drop_constraint("fact_sheets_document_id_fkey", "fact_sheets", type_="foreignkey")
    op.drop_constraint("audit_logs_document_id_fkey", "audit_logs", type_="foreignkey")

    # ── Alter UUID columns to use postgresql.UUID(as_uuid=False) ─────────────

    op.alter_column(
        "documents", "id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="id::uuid",
        existing_type=sa.String(),
    )

    op.alter_column(
        "draft_versions", "id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="id::uuid",
        existing_type=sa.String(),
    )
    op.alter_column(
        "draft_versions", "document_id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="document_id::uuid",
        existing_type=sa.String(),
    )

    op.alter_column(
        "fact_sheets", "id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="id::uuid",
        existing_type=sa.String(),
    )
    op.alter_column(
        "fact_sheets", "document_id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="document_id::uuid",
        existing_type=sa.String(),
    )

    op.alter_column(
        "claim_registry", "id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="id::uuid",
        existing_type=sa.String(),
    )

    op.alter_column(
        "audit_logs", "id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="id::uuid",
        existing_type=sa.String(),
    )
    op.alter_column(
        "audit_logs", "document_id",
        type_=postgresql.UUID(as_uuid=False),
        postgresql_using="document_id::uuid",
        existing_type=sa.String(),
    )

    # ── Recreate foreign key constraints after altering column types ──────────
    op.create_foreign_key(
        "draft_versions_document_id_fkey", "draft_versions", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fact_sheets_document_id_fkey", "fact_sheets", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "audit_logs_document_id_fkey", "audit_logs", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )

    # ── Add UNIQUE constraint on (document_id, iteration_number) ─────────────
    op.create_unique_constraint(
        "uq_draft_versions_document_iteration",
        "draft_versions",
        ["document_id", "iteration_number"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_draft_versions_document_iteration", "draft_versions", type_="unique")

    # ── Drop foreign key constraints before altering column types ─────────────
    op.drop_constraint("draft_versions_document_id_fkey", "draft_versions", type_="foreignkey")
    op.drop_constraint("fact_sheets_document_id_fkey", "fact_sheets", type_="foreignkey")
    op.drop_constraint("audit_logs_document_id_fkey", "audit_logs", type_="foreignkey")

    op.alter_column(
        "audit_logs", "document_id",
        type_=sa.String(),
        postgresql_using="document_id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )
    op.alter_column(
        "audit_logs", "id",
        type_=sa.String(),
        postgresql_using="id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )

    op.alter_column(
        "claim_registry", "id",
        type_=sa.String(),
        postgresql_using="id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )

    op.alter_column(
        "fact_sheets", "document_id",
        type_=sa.String(),
        postgresql_using="document_id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )
    op.alter_column(
        "fact_sheets", "id",
        type_=sa.String(),
        postgresql_using="id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )

    op.alter_column(
        "draft_versions", "document_id",
        type_=sa.String(),
        postgresql_using="document_id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )
    op.alter_column(
        "draft_versions", "id",
        type_=sa.String(),
        postgresql_using="id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )

    op.alter_column(
        "documents", "id",
        type_=sa.String(),
        postgresql_using="id::text",
        existing_type=postgresql.UUID(as_uuid=False),
    )

    # ── Recreate foreign key constraints after altering column types ──────────
    op.create_foreign_key(
        "draft_versions_document_id_fkey", "draft_versions", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "fact_sheets_document_id_fkey", "fact_sheets", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
    op.create_foreign_key(
        "audit_logs_document_id_fkey", "audit_logs", "documents",
        ["document_id"], ["id"], ondelete="CASCADE",
    )
