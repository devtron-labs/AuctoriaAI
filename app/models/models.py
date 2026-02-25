import uuid
import enum
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger, Boolean, Column, String, Text, Float, Integer, DateTime,
    ForeignKey, Enum as SAEnum
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship

from app.database import Base


def _uuid():
    return str(uuid.uuid4())


def _now():
    return datetime.now(timezone.utc)


class DocumentStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    VALIDATING = "VALIDATING"
    PASSED = "PASSED"
    HUMAN_REVIEW = "HUMAN_REVIEW"
    APPROVED = "APPROVED"
    BLOCKED = "BLOCKED"


class ClaimType(str, enum.Enum):
    INTEGRATION = "INTEGRATION"
    COMPLIANCE = "COMPLIANCE"
    PERFORMANCE = "PERFORMANCE"


class DocumentClassification(str, enum.Enum):
    INTERNAL = "INTERNAL"
    CONFIDENTIAL = "CONFIDENTIAL"
    PUBLIC = "PUBLIC"


class Document(Base):
    __tablename__ = "documents"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    title = Column(String(512), nullable=False)
    status = Column(
        SAEnum(DocumentStatus, name="documentstatus", create_type=True),
        nullable=False,
        default=DocumentStatus.DRAFT,
    )
    # Populated by Ticket 2.1 — Document Upload
    file_path = Column(String(1024), nullable=True)
    file_hash = Column(String(64), nullable=True)          # SHA-256 hex digest
    classification = Column(
        SAEnum(DocumentClassification, name="documentclassification", create_type=True),
        nullable=True,
    )
    file_size = Column(BigInteger, nullable=True)          # bytes
    mime_type = Column(String(128), nullable=True)

    # Populated by EPIC 5 — Claim Extraction & Registry Validation
    validation_report = Column(JSONB, nullable=True)

    # Populated by EPIC 7 — Human Review & Approval
    reviewed_by = Column(String(512), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=True)
    review_notes = Column(Text, nullable=True)
    force_approved = Column(Boolean, nullable=False, default=False, server_default="false")

    # Pipeline state tracking — populated by each stage of the processing pipeline
    current_stage = Column(String, nullable=True)
    error_message = Column(String, nullable=True)
    validation_progress = Column(Integer, default=0, nullable=False, server_default="0")

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)

    draft_versions = relationship(
        "DraftVersion",
        back_populates="document",
        order_by="DraftVersion.iteration_number.desc()",
        cascade="all, delete-orphan",
    )
    fact_sheets = relationship("FactSheet", back_populates="document", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="document", cascade="all, delete-orphan")

    @property
    def has_fact_sheet(self) -> bool:
        return bool(self.fact_sheets)


class DraftVersion(Base):
    __tablename__ = "draft_versions"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    # Nullable to support prompt-first standalone drafts (no parent document required)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=True)
    iteration_number = Column(Integer, nullable=False)
    content_markdown = Column(Text, nullable=False)
    score = Column(Float, nullable=True)
    feedback_text = Column(Text, nullable=True)          # Populated by EPIC 4 — QA rubric evaluation
    tone = Column(String(64), nullable=False, server_default="formal")  # Prose tone used for generation
    # Prompt-first fields (added in migration 011)
    user_prompt = Column(Text, nullable=False, server_default="")  # The user's original prompt
    source_document_id = Column(UUID(as_uuid=False), nullable=True)  # Optional context document reference
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    document = relationship("Document", back_populates="draft_versions")


class FactSheet(Base):
    __tablename__ = "fact_sheets"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    structured_data = Column(JSONB, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)

    document = relationship("Document", back_populates="fact_sheets")


class ClaimRegistry(Base):
    __tablename__ = "claim_registry"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    claim_text = Column(Text, nullable=False)
    claim_type = Column(
        SAEnum(ClaimType, name="claimtype", create_type=True),
        nullable=False,
    )
    # Populated by Ticket 2.3 — Claim Registry enhancements
    expiry_date = Column(DateTime(timezone=True), nullable=True)
    approved_by = Column(String(512), nullable=True)
    approved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)
    document_id = Column(UUID(as_uuid=False), ForeignKey("documents.id", ondelete="CASCADE"), nullable=False)
    action = Column(String(512), nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False, default=_now)

    document = relationship("Document", back_populates="audit_logs")


class SystemSettings(Base):
    """Single-row table storing admin-configurable governance parameters.

    Exactly one row must always exist. Application code enforces this invariant
    by seeding a default row on first access (see settings_service.py).
    DB-level CHECK constraints enforce valid value ranges.
    """

    __tablename__ = "system_settings"

    id = Column(UUID(as_uuid=False), primary_key=True, default=_uuid)

    # Ticket 2.4 — Registry freshness gate
    registry_staleness_hours = Column(Integer, nullable=False, default=24)

    # EPIC 3 — Draft Generation
    llm_model_name = Column(String(128), nullable=False, default="claude-opus-4-6")
    max_draft_length = Column(Integer, nullable=False, default=50_000)

    # EPIC 4 — QA + Iteration
    qa_passing_threshold = Column(Float, nullable=False, default=9.0)
    max_qa_iterations = Column(Integer, nullable=False, default=3)
    qa_llm_model = Column(String(128), nullable=False, default="claude-sonnet-4-6")

    # EPIC 6 — Governance Gate
    governance_score_threshold = Column(Float, nullable=False, default=9.0)

    # LLM call timeout (seconds). Applies to every Anthropic API call.
    # Configurable via Admin → System Settings. Default 120 s.
    llm_timeout_seconds = Column(Integer, nullable=False, default=120, server_default="120")

    # EPIC 7 — Review Notifications
    notification_webhook_url = Column(String(2048), nullable=True, default="")

    # Per-provider API keys — stored in DB for admin-configured LLM routing.
    # anthropic_api_key falls back to ANTHROPIC_API_KEY env var if null.
    anthropic_api_key  = Column(String(512), nullable=True)
    openai_api_key     = Column(String(512), nullable=True)
    google_api_key     = Column(String(512), nullable=True)
    perplexity_api_key = Column(String(512), nullable=True)
    xai_api_key        = Column(String(512), nullable=True)

    # Audit trail — who last changed the settings
    updated_by = Column(String(512), nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=_now)
    updated_at = Column(DateTime(timezone=True), nullable=False, default=_now, onupdate=_now)
