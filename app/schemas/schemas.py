from __future__ import annotations

import enum as _enum
from datetime import datetime
from typing import Any, List, Optional
from urllib.parse import urlparse
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field, field_validator, model_validator

from app.models.models import ClaimType, DocumentClassification, DocumentStatus


# ── System Settings ──────────────────────────────────────────────────────────

# Known LLM models with display labels and provider. Used by the
# /admin/settings/available-models endpoint. Not used for validation.
KNOWN_LLM_MODELS: list[dict[str, str]] = [
    # Anthropic
    {"id": "claude-opus-4-6",           "label": "Claude Opus 4.6 (Most Capable)",    "provider": "anthropic"},
    {"id": "claude-sonnet-4-6",         "label": "Claude Sonnet 4.6 (Balanced)",      "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (Fast)",           "provider": "anthropic"},
    # OpenAI
    {"id": "gpt-4o",                    "label": "GPT-4o (OpenAI)",                   "provider": "openai"},
    {"id": "gpt-4o-mini",               "label": "GPT-4o Mini (OpenAI)",              "provider": "openai"},
    {"id": "o3-mini",                   "label": "o3 Mini (OpenAI)",                  "provider": "openai"},
    # Google Gemini
    {"id": "gemini-2.0-flash",          "label": "Gemini 2.0 Flash (Google)",         "provider": "google"},
    {"id": "gemini-1.5-pro",            "label": "Gemini 1.5 Pro (Google)",           "provider": "google"},
    # Perplexity
    {"id": "llama-3.1-sonar-large-128k-online", "label": "Sonar Large (Perplexity)", "provider": "perplexity"},
    {"id": "llama-3.1-sonar-small-128k-online", "label": "Sonar Small (Perplexity)", "provider": "perplexity"},
    # xAI Grok
    {"id": "grok-2",                    "label": "Grok 2 (xAI)",                      "provider": "xai"},
    {"id": "grok-2-vision-1212",        "label": "Grok 2 Vision (xAI)",               "provider": "xai"},
]


class SystemSettingsResponse(BaseModel):
    """Current system settings returned by GET /admin/settings."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    registry_staleness_hours: int
    llm_model_name: str
    max_draft_length: int
    qa_passing_threshold: float
    max_qa_iterations: int
    qa_llm_model: str
    governance_score_threshold: float
    llm_timeout_seconds: int
    notification_webhook_url: Optional[str]
    updated_by: Optional[str]
    updated_at: datetime
    # Provider API keys — returned masked (****last4) or null by the router
    anthropic_api_key:  Optional[str] = None
    openai_api_key:     Optional[str] = None
    google_api_key:     Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key:        Optional[str] = None


class SystemSettingsUpdate(BaseModel):
    """Request body for PUT /admin/settings.

    All settings fields are optional — only provided fields are written to the DB.
    This allows partial updates (e.g. updating only API keys without resending
    all threshold values).

    Validation rules enforced by Pydantic (before DB write):
    - registry_staleness_hours   : >= 1 (when provided)
    - max_draft_length           : 1 000 – 100 000 characters (when provided)
    - qa_passing_threshold       : 5.0 – 10.0 safety floor (when provided)
    - max_qa_iterations          : >= 1 (when provided)
    - governance_score_threshold : 0.0 – 10.0, must be >= qa_passing_threshold
                                   (only checked when BOTH are provided together)
    - notification_webhook_url   : valid HTTP/HTTPS URL or empty string (when provided)
    - updated_by                 : non-empty name of the admin making the change
    """

    registry_staleness_hours: Optional[int] = Field(default=None, ge=1)
    llm_model_name: Optional[str] = Field(default=None, min_length=1)
    max_draft_length: Optional[int] = Field(default=None, ge=1000, le=100_000)
    qa_passing_threshold: Optional[float] = Field(default=None, ge=5.0, le=10.0)
    max_qa_iterations: Optional[int] = Field(default=None, ge=1)
    qa_llm_model: Optional[str] = Field(default=None, min_length=1)
    governance_score_threshold: Optional[float] = Field(default=None, ge=0.0, le=10.0)
    llm_timeout_seconds: Optional[int] = Field(default=None, ge=30, le=600)
    notification_webhook_url: Optional[str] = Field(default=None)
    updated_by: str = Field(min_length=1, max_length=512)
    # Provider API keys — Optional[str]:
    #   None  = not provided, keep existing DB value
    #   ""    = explicitly clear the key
    #   "..." = new key value to store
    anthropic_api_key:  Optional[str] = None
    openai_api_key:     Optional[str] = None
    google_api_key:     Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key:        Optional[str] = None

    @field_validator("notification_webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v  # None or "" both accepted
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                "notification_webhook_url must use http or https, or be empty."
            )
        if not parsed.netloc:
            raise ValueError(
                "notification_webhook_url must include a valid hostname."
            )
        return v

    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> "SystemSettingsUpdate":
        gov = self.governance_score_threshold
        qa = self.qa_passing_threshold
        # Only enforce ordering when both thresholds are supplied in the same request.
        if gov is not None and qa is not None and gov < qa:
            raise ValueError(
                f"governance_score_threshold ({gov:.1f}) "
                f"cannot be lower than qa_passing_threshold ({qa:.1f}). "
                "Lowering governance below QA would allow documents to skip proper QA validation."
            )
        return self


# ── Document ────────────────────────────────────────────────────────────────

class DocumentCreate(BaseModel):
    title: str = Field(min_length=1, max_length=512)


class DocumentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: DocumentStatus
    current_stage: Optional[str] = None
    error_message: Optional[str] = None
    validation_progress: int = 0
    draft_versions: List["DraftVersionRead"] = []
    has_fact_sheet: bool = False
    created_at: datetime
    updated_at: datetime


class DocumentTransition(BaseModel):
    target_status: DocumentStatus


class DocumentStatusResponse(BaseModel):
    """Lightweight status response for GET /documents/{id}/status polling."""

    model_config = ConfigDict(from_attributes=True)

    status: DocumentStatus
    current_stage: Optional[str]
    error_message: Optional[str] = None
    validation_progress: int


# ── Ticket 2.1 — Document Upload ─────────────────────────────────────────────

class DocumentUploadResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    title: str
    status: DocumentStatus
    file_path: str
    file_hash: str
    classification: DocumentClassification
    file_size: int
    mime_type: str
    created_at: datetime
    updated_at: datetime


# ── DraftVersion ─────────────────────────────────────────────────────────────

class DraftVersionCreate(BaseModel):
    content_markdown: str
    score: float | None = None


class DraftVersionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: Optional[str]   # Nullable for prompt-first standalone drafts
    iteration_number: int
    content_markdown: str
    tone: str
    score: float | None
    feedback_text: str | None    # Populated by EPIC 4 — QA rubric evaluation
    user_prompt: str = ""        # The user's original generation prompt (empty for legacy fact-sheet drafts)
    source_document_id: Optional[str]  # Optional context document reference
    created_at: datetime

    @field_validator("tone", mode="before")
    @classmethod
    def _coerce_tone(cls, v: Any) -> str:
        """Coerce None to 'formal' for legacy drafts created before the tone column existed."""
        return v if v is not None else "formal"

    @field_validator("user_prompt", mode="before")
    @classmethod
    def _coerce_user_prompt(cls, v: Any) -> str:
        """Coerce None to empty string for legacy drafts that pre-date the prompt-first path."""
        return v if v is not None else ""

    @computed_field
    @property
    def content_preview(self) -> str:
        return self.content_markdown[:200]


# ── FactSheet ─────────────────────────────────────────────────────────────────

class FactSheetCreate(BaseModel):
    structured_data: dict[str, Any]


class FactSheetRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    structured_data: dict[str, Any]
    created_at: datetime


# ── Ticket 2.2 — Fact Sheet Extraction schemas ────────────────────────────────

class FeatureItem(BaseModel):
    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class IntegrationItem(BaseModel):
    system: str = Field(min_length=1)
    method: str = Field(min_length=1)
    notes: str


class ComplianceItem(BaseModel):
    standard: str = Field(min_length=1)
    status: str = Field(min_length=1)
    details: str


class PerformanceMetricItem(BaseModel):
    metric: str = Field(min_length=1)
    value: str = Field(min_length=1)
    unit: str


class LimitationItem(BaseModel):
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)


class FactSheetData(BaseModel):
    """
    Validated schema for LLM-extracted fact sheet content.
    All list fields must be present; individual items are fully validated.
    """
    features: list[FeatureItem]
    integrations: list[IntegrationItem]
    compliance: list[ComplianceItem]
    performance_metrics: list[PerformanceMetricItem]
    limitations: list[LimitationItem]


class FactSheetExtractionRequest(BaseModel):
    """
    Request body for the extract-factsheet endpoint.
    Reserved for future parameters (e.g., extraction hints, model override).
    """
    pass


class FactSheetExtractionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    structured_data: dict[str, Any]
    created_at: datetime


# ── Registry Sync (Ticket 2.4 — initialization path) ─────────────────────────

class RegistrySyncResponse(BaseModel):
    """Response returned by POST /registry/sync."""
    message: str
    registry_count: int
    seeded: bool = Field(
        description="True when bootstrap claims were inserted (first-time init). "
                    "False when existing rows were refreshed."
    )
    updated_at: datetime


# ── ClaimRegistry ─────────────────────────────────────────────────────────────

class ClaimCreate(BaseModel):
    claim_text: str = Field(min_length=1, max_length=512)
    claim_type: ClaimType
    expiry_date: datetime | None = None


class ClaimRead(BaseModel):
    """Backward-compatible claim response (EPIC 1)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_text: str
    claim_type: ClaimType
    created_at: datetime


# ── Ticket 2.3 — Claim Registry enhancements ─────────────────────────────────

class ClaimResponse(BaseModel):
    """Enhanced claim response including approval metadata and expiry (EPIC 2)."""
    model_config = ConfigDict(from_attributes=True)

    id: str
    claim_text: str
    claim_type: ClaimType
    expiry_date: datetime | None
    approved_by: str | None
    approved_at: datetime | None
    created_at: datetime
    updated_at: datetime


class ClaimValidationRequest(BaseModel):
    claim_ids: list[str] = Field(min_length=1)


class ClaimValidationReport(BaseModel):
    """Structured validation report returned by POST /claims/validate."""
    valid_claims: list[str]
    expired_claims: list[str]
    missing_claims: list[str]
    is_valid: bool
    warnings: list[str]
    errors: list[str]


# ── AuditLog ──────────────────────────────────────────────────────────────────

class AuditLogRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    document_id: str
    action: str
    timestamp: datetime


# ── EPIC 3 — Draft Generation ──────────────────────────────────────────────

class GenerateDraftRequest(BaseModel):
    tone: str = Field(
        default="formal",
        pattern="^(formal|conversational|technical)$",
        description="Prose tone for the generated whitepaper.",
    )


class GenerateDraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    draft_version_id: str
    document_id: str
    iteration_number: int
    content_preview: str = Field(description="First 200 characters of the generated draft.")
    created_at: datetime


# ── Prompt-First Draft Generation (new endpoint: POST /api/v1/drafts/generate) ──

class DraftGenerateRequest(BaseModel):
    """
    Request body for POST /api/v1/drafts/generate.

    prompt is the primary driver. document_type selects the output format and
    structural template. document_id is optional context. tone controls the
    prose register of the generated document.
    """
    prompt: str = Field(
        min_length=1,
        description="User's request or topic description. Required.",
    )
    document_type: str = Field(
        default="whitepaper",
        description=(
            "Type of document to generate. Controls structure and tone. "
            "Allowed: whitepaper, blog, technical_doc, case_study, "
            "product_brief, research_report."
        ),
    )
    tone: str = Field(
        default="formal",
        pattern="^(formal|conversational|technical)$",
        description="Prose register for the generated document: formal | conversational | technical.",
    )
    document_id: Optional[UUID] = Field(
        default=None,
        description="Optional UUID of a document to use as additional context.",
    )

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        allowed = {
            "whitepaper", "blog", "technical_doc",
            "case_study", "product_brief", "research_report",
        }
        if v not in allowed:
            raise ValueError(f"document_type must be one of {sorted(allowed)}")
        return v


class DraftGenerateResponse(BaseModel):
    """Response returned by POST /api/v1/drafts/generate."""

    draft_version_id: str
    document_id: Optional[str] = Field(
        default=None,
        description="The context document ID (source_document_id), if one was provided.",
    )
    iteration_number: int
    content_preview: str = Field(description="First 200 characters of the generated draft.")
    created_at: datetime


class DraftGenerateAcceptedResponse(BaseModel):
    """Response returned by POST /api/v1/drafts/generate (202 Accepted).

    Draft generation runs in a background task bounded by llm_timeout_seconds
    (total budget) and max_qa_iterations (max attempts). Poll
    GET /documents/{id}/status until current_stage is "DRAFT_GENERATED"
    (success) or "DRAFT_FAILED" (all attempts exhausted).
    """

    status: str = "generating"
    document_id: Optional[str] = None
    message: str = "Draft generation started. Poll /documents/{id}/status for progress."


# ── EPIC 4 — QA + Iteration ──────────────────────────────────────────────────

class RubricScores(BaseModel):
    """Structured rubric evaluation output from the LLM.

    Six scored dimensions:
      factual_correctness — accuracy against fact sheet or training knowledge
      technical_depth     — specificity of technical content and metrics
      clarity             — logical structure, flow, and absence of ambiguity
      readability         — sentence length, paragraph rhythm, and prose flow
      formatting          — headings, bullets, tables, spacing, visual hierarchy
      style_adherence     — brand tone, colour/font guidelines, template compliance

    composite_score is the arithmetic mean of all six dimensions (0–10).
    improvement_suggestions contains one actionable item per dimension that
    scored below 9, in the order the dimensions appear above.
    """

    factual_correctness: float = Field(ge=0.0, le=10.0, description="Score for factual accuracy (0–10).")
    technical_depth: float = Field(ge=0.0, le=10.0, description="Score for technical depth (0–10).")
    clarity: float = Field(ge=0.0, le=10.0, description="Score for clarity and structure (0–10).")
    readability: float = Field(ge=0.0, le=10.0, description="Score for sentence/paragraph readability (0–10).")
    formatting: float = Field(ge=0.0, le=10.0, description="Score for visual formatting and layout (0–10).")
    style_adherence: float = Field(ge=0.0, le=10.0, description="Score for template/brand style compliance (0–10).")
    composite_score: float = Field(ge=0.0, le=10.0, description="Arithmetic mean of all six dimension scores (0–10).")
    improvement_suggestions: list[str] = Field(
        default_factory=list,
        description=(
            "Actionable improvement suggestions, one per dimension scoring below 9. "
            "Empty list is valid when all six dimensions score 9 or above."
        ),
    )

    @computed_field
    @property
    def feedback(self) -> str:
        """Derived single-string feedback for backward compatibility (joins improvement_suggestions)."""
        return "\n".join(self.improvement_suggestions)


class QAEvaluateRequest(BaseModel):
    """Request body for the qa-iterate endpoint."""

    max_iterations: Optional[int] = Field(
        default=None,
        ge=1,
        description=(
            "Maximum QA iterations. Must be >= 1 if provided. "
            "Falls back to the server-side default (max_qa_iterations config) when None."
        ),
    )
    document_type: str = Field(
        default="whitepaper",
        description=(
            "Document type of the draft being evaluated. Controls the section structure "
            "that the improvement LLM enforces when generating revised drafts. "
            "Allowed: whitepaper, blog, technical_doc, case_study, product_brief, research_report."
        ),
    )

    @field_validator("document_type")
    @classmethod
    def validate_document_type(cls, v: str) -> str:
        allowed = {
            "whitepaper", "blog", "technical_doc",
            "case_study", "product_brief", "research_report",
        }
        if v not in allowed:
            raise ValueError(f"document_type must be one of {sorted(allowed)}")
        return v


class QAIterationRecord(BaseModel):
    """Record of a single QA iteration within the evaluate-and-iterate cycle."""

    iteration: int = Field(description="Iteration number (1-based).")
    draft_id: str = Field(description="UUID of the DraftVersion evaluated in this iteration.")
    # ── Six rubric dimensions ──────────────────────────────────────────────
    factual_correctness: float = Field(ge=0.0, le=10.0, description="Factual accuracy score (0–10).")
    technical_depth: float = Field(ge=0.0, le=10.0, description="Technical depth score (0–10).")
    clarity: float = Field(ge=0.0, le=10.0, description="Clarity and structure score (0–10).")
    readability: float = Field(ge=0.0, le=10.0, description="Sentence/paragraph readability score (0–10).")
    formatting: float = Field(ge=0.0, le=10.0, description="Visual formatting and layout score (0–10).")
    style_adherence: float = Field(ge=0.0, le=10.0, description="Template/brand style compliance score (0–10).")
    # ── Composite & delta ─────────────────────────────────────────────────
    score: float = Field(ge=0.0, le=10.0, description="Composite score (arithmetic mean of all six dimensions, 0–10).")
    score_delta: float | None = Field(
        default=None,
        description="Change in composite score vs the previous iteration. None for the first iteration.",
    )
    feedback: str = Field(description="Joined improvement feedback string (backward compatible).")
    improvement_suggestions: list[str] = Field(
        default_factory=list,
        description="Structured list of actionable improvement suggestions from the LLM evaluator.",
    )
    passed: bool = Field(description="Whether this iteration's score met the passing threshold.")


class QAEvaluateResponse(BaseModel):
    """Response returned after the QA iteration cycle completes."""

    document_id: str
    final_status: DocumentStatus
    iterations_completed: int
    final_score: float | None
    final_draft_id: str
    iteration_history: list[QAIterationRecord] = Field(
        default_factory=list,
        description=(
            "Per-iteration breakdown of scores, feedback, and pass/fail result. "
            "Includes individual rubric scores and score delta vs the prior iteration."
        ),
    )
    quality_trend: str = Field(
        default="N/A",
        description=(
            "Overall quality trajectory across iterations: "
            "IMPROVING (score rose > 0.1), DECLINING (score fell > 0.1), "
            "STABLE (change <= 0.1), or N/A (single iteration)."
        ),
    )


# ── EPIC 5 — Claim Extraction & Registry Validation ───────────────────────────

class ExtractedClaimType(str, _enum.Enum):
    """
    Claim types recognised by the regex extraction pipeline.

    SUPERLATIVE is intentionally not persisted to the ClaimRegistry (which uses
    the DB-level ClaimType enum). It exists only in extraction results to allow
    superlative claims to travel through the same validation report structure.
    """
    INTEGRATION = "INTEGRATION"
    COMPLIANCE = "COMPLIANCE"
    PERFORMANCE = "PERFORMANCE"
    SUPERLATIVE = "SUPERLATIVE"


class ExtractedClaim(BaseModel):
    """A single claim extracted from a draft by the regex pipeline."""
    claim_type: ExtractedClaimType
    claim_text: str = Field(min_length=1, description="The extracted claim text or system/metric name.")
    location_in_draft: str = Field(description="Human-readable location, e.g. 'paragraph 2, line 3'.")


class ClaimValidationResult(BaseModel):
    """Validation outcome for a single extracted claim."""
    claim: ExtractedClaim
    is_valid: bool = Field(description="True when the claim passes validation (including expired soft-warns).")
    is_blocked: bool = Field(description="True when this claim causes the document to be blocked.")
    error_message: str | None = Field(default=None, description="Set when is_blocked=True.")
    is_expired: bool = Field(default=False, description="True when the registry entry exists but is expired (soft warning).")


class DraftValidationReport(BaseModel):
    """
    Full validation report produced by POST /documents/{id}/validate-claims.

    Named DraftValidationReport to distinguish from the registry-level
    ClaimValidationReport used by POST /claims/validate (EPIC 2).
    """
    total_claims: int
    valid_claims: int
    blocked_claims: int
    warnings: int = Field(description="Number of expired-claim soft warnings.")
    is_valid: bool = Field(description="False if any claim caused a blocking failure.")
    results: list[ClaimValidationResult]


class ValidateClaimsRequest(BaseModel):
    """
    Request body for POST /documents/{id}/validate-claims.
    Reserved for future per-request overrides (e.g., strict_mode).
    """
    pass


class ValidateClaimsResponse(BaseModel):
    """Response returned by POST /documents/{id}/validate-claims."""
    document_id: str
    status: DocumentStatus
    validation_report: DraftValidationReport


# ── EPIC 6 — Governance Gate ───────────────────────────────────────────────

class GovernanceDecision(str, _enum.Enum):
    """Final governance gate outcome."""
    PASSED = "PASSED"
    FAILED = "FAILED"


class GovernanceCheckRequest(BaseModel):
    """
    Request body for POST /documents/{id}/governance-check.
    Reserved for future per-request overrides (e.g., custom threshold).
    """
    pass


class GovernanceCheckResponse(BaseModel):
    """Response returned by POST /documents/{id}/governance-check."""
    document_id: str
    decision: GovernanceDecision
    final_status: DocumentStatus
    score: float
    claims_valid: bool
    reason: str
    details: dict[str, Any]


# ── EPIC 7 — Human Review & Approval ──────────────────────────────────────────

class PendingReviewItem(BaseModel):
    """Summary of a single document awaiting human review."""
    id: str
    title: str
    status: DocumentStatus
    draft_preview: Optional[str] = Field(
        default=None, description="First 200 characters of the latest draft."
    )
    score: Optional[float] = Field(
        default=None, description="Latest draft composite QA score."
    )
    claims_valid: Optional[bool] = Field(
        default=None, description="Whether the validation report passed."
    )
    total_issues: int = Field(
        default=0, description="Number of blocked claims in the validation report."
    )
    days_in_review: int = Field(
        default=0, description="Days elapsed since the document entered HUMAN_REVIEW status."
    )
    created_at: datetime
    updated_at: datetime


class PendingReviewResponse(BaseModel):
    """Paginated list of documents currently awaiting human review."""
    total: int
    page: int
    page_size: int
    documents: list[PendingReviewItem]


class ReviewDetailsResponse(BaseModel):
    """Complete context required to make a human review decision."""
    document: DocumentRead
    latest_draft: Optional[DraftVersionRead] = None
    all_drafts: list[DraftVersionRead]
    validation_report: Optional[dict[str, Any]] = None
    fact_sheet: Optional[FactSheetRead] = None
    audit_log: list[AuditLogRead]


class ApproveDocumentRequest(BaseModel):
    """Request body for POST /documents/{id}/approve."""
    reviewer_name: str = Field(
        min_length=1,
        max_length=512,
        description="Name of the reviewer approving the document.",
    )
    notes: Optional[str] = Field(
        default=None, description="Optional approval notes."
    )
    force_approve: bool = Field(
        default=False,
        description="Admin override: permit approval from any document status.",
    )
    override_reason: Optional[str] = Field(
        default=None,
        description="Required and non-empty when force_approve=True. Documented for audit.",
    )


class ApproveDocumentResponse(BaseModel):
    """Response returned after a successful document approval."""
    document_id: str
    status: DocumentStatus
    reviewed_by: str
    reviewed_at: datetime
    force_approved: bool
    message: str


class RejectDocumentRequest(BaseModel):
    """Request body for POST /documents/{id}/reject."""
    reviewer_name: str = Field(
        min_length=1,
        max_length=512,
        description="Name of the reviewer rejecting the document.",
    )
    rejection_reason: str = Field(
        min_length=1,
        description="Reason for rejection. Stored in the audit log.",
    )
    suggested_action: Optional[str] = Field(
        default=None,
        description="Optional guidance to help the author revise the document.",
    )


class RejectDocumentResponse(BaseModel):
    """Response returned after a successful document rejection."""
    document_id: str
    status: DocumentStatus
    rejection_reason: str
    suggested_action: Optional[str] = None
    message: str


# Resolve forward references — DocumentRead.draft_versions references DraftVersionRead
# which is defined later in the same module. model_rebuild() re-evaluates annotations
# now that all types are available.
DocumentRead.model_rebuild()
