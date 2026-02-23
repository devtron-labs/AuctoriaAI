"""System Settings table for admin-configurable governance parameters.

Creates a single-row table (system_settings) that stores all admin-configurable
system parameters previously hardcoded in app/config.py. Seeded with defaults
matching the current config constants on first migration.

New table: system_settings
  - id                        : VARCHAR(36)   primary key (UUID)
  - registry_staleness_hours  : INTEGER       >= 1
  - llm_model_name            : VARCHAR(128)  non-empty
  - max_draft_length          : INTEGER       >= 1000
  - qa_passing_threshold      : FLOAT         0–10
  - max_qa_iterations         : INTEGER       >= 1
  - qa_llm_model              : VARCHAR(128)  non-empty
  - governance_score_threshold: FLOAT         0–10
  - notification_webhook_url  : VARCHAR(2048) nullable
  - updated_by                : VARCHAR(512)  nullable
  - created_at                : TIMESTAMPTZ   not null
  - updated_at                : TIMESTAMPTZ   not null

Revision ID: 009
Revises: 008
Create Date: 2026-02-20
"""

import uuid
from datetime import datetime, timezone
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "009"
down_revision: Union[str, None] = "008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "system_settings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("registry_staleness_hours", sa.Integer(), nullable=False),
        sa.Column("llm_model_name", sa.String(128), nullable=False),
        sa.Column("max_draft_length", sa.Integer(), nullable=False),
        sa.Column("qa_passing_threshold", sa.Float(), nullable=False),
        sa.Column("max_qa_iterations", sa.Integer(), nullable=False),
        sa.Column("qa_llm_model", sa.String(128), nullable=False),
        sa.Column("governance_score_threshold", sa.Float(), nullable=False),
        sa.Column("notification_webhook_url", sa.String(2048), nullable=True),
        sa.Column("updated_by", sa.String(512), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        # DB-level constraints — application-level Pydantic validation is also applied
        sa.CheckConstraint(
            "registry_staleness_hours >= 1",
            name="chk_ss_registry_staleness_hours",
        ),
        sa.CheckConstraint(
            "max_draft_length >= 1000",
            name="chk_ss_max_draft_length",
        ),
        sa.CheckConstraint(
            "qa_passing_threshold >= 0.0 AND qa_passing_threshold <= 10.0",
            name="chk_ss_qa_passing_threshold",
        ),
        sa.CheckConstraint(
            "max_qa_iterations >= 1",
            name="chk_ss_max_qa_iterations",
        ),
        sa.CheckConstraint(
            "governance_score_threshold >= 0.0 AND governance_score_threshold <= 10.0",
            name="chk_ss_governance_score_threshold",
        ),
    )

    # Seed the one-and-only default row with current configuration constants.
    now = datetime.now(timezone.utc).isoformat()
    settings_id = str(uuid.uuid4())
    op.execute(
        sa.text(
            "INSERT INTO system_settings ("
            "  id, registry_staleness_hours, llm_model_name, max_draft_length,"
            "  qa_passing_threshold, max_qa_iterations, qa_llm_model,"
            "  governance_score_threshold, notification_webhook_url,"
            "  created_at, updated_at"
            ") VALUES ("
            "  :id, :rsh, :llm, :mdl, :qat, :mqi, :qlm, :gst, :nwu, :cat, :uat"
            ")"
        ).bindparams(
            id=settings_id,
            rsh=24,
            llm="claude-opus-4-6",
            mdl=50000,
            qat=9.0,
            mqi=3,
            qlm="claude-sonnet-4-6",
            gst=9.0,
            nwu="",
            cat=now,
            uat=now,
        )
    )


def downgrade() -> None:
    op.drop_table("system_settings")
