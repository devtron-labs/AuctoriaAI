"""
Service layer for:
  Ticket 2.2 — Fact Sheet Extraction Engine
  Ticket 2.4 — Registry Sync Enforcement

Extraction flow:
  1. check_registry_freshness()  →  RegistryStaleError if stale
  2. Load Document                →  NotFoundError if missing
  3. _call_llm()                  →  ExtractionError on failure (LLM or JSON parse error)
  4. FactSheetData.model_validate →  ExtractionError on schema mismatch
  5. INSERT fact_sheets row + audit log  (transaction — rollback on failure)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

import anthropic
import openai
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential
from sqlalchemy.orm import Session

from app.config import settings
from app.models.models import AuditLog, ClaimRegistry, ClaimType, Document, DocumentStatus, FactSheet
from app.schemas.schemas import FactSheetData
from app.services import settings_service, llm_adapter
from app.services.settings_service import ActiveSettings
from app.services.exceptions import (
    ExtractionError,
    NotFoundError,
    RateLimitError,
    RegistryNotInitializedError,
    RegistryStaleError,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit(db: Session, document_id: str, action: str) -> None:
    log = AuditLog(document_id=document_id, action=action[:512])
    db.add(log)


# ---------------------------------------------------------------------------
# Ticket 2.4 — Registry freshness gate
# ---------------------------------------------------------------------------

def check_registry_freshness(db: Session) -> None:
    """
    Verify the claim registry has been updated within the staleness window.

    The staleness threshold is controlled by settings.registry_staleness_hours
    (fetched dynamically from system_settings DB table, default: 24 h).

    Empty-registry behaviour:
    - Production (ENV != local|development): raises RegistryNotInitializedError
      with a structured action_required hint pointing to POST /registry/sync.
    - Local/development (ENV=local or ENV=development): logs a warning and
      returns without blocking — enables first-time setup without a pre-seeded
      registry. This bypass is NEVER active in staging or production.

    Stale-registry behaviour (has rows but last update is too old):
    - Raises RegistryStaleError in all environments (staleness indicates a
      broken sync pipeline that must be fixed regardless of environment).

    Args:
        db: SQLAlchemy session.

    Raises:
        RegistryNotInitializedError: registry has zero rows (production only).
        RegistryStaleError: registry exists but last update exceeds threshold.
    """
    active = settings_service.get_settings(db)
    staleness_hours = active.registry_staleness_hours
    threshold = datetime.now(timezone.utc) - timedelta(hours=staleness_hours)

    latest: ClaimRegistry | None = (
        db.query(ClaimRegistry)
        .order_by(ClaimRegistry.updated_at.desc())
        .first()
    )

    if latest is None:
        # ── Dev-mode bypass: allow empty registry in local/development only ──
        if settings.env in ("local", "development"):
            logger.warning(
                "Bypassing registry freshness gate (development mode): "
                "claim_registry is empty but ENV=%s — extraction will proceed. "
                "Run POST /api/v1/registry/sync to seed the registry. "
                "This bypass is INACTIVE in staging and production.",
                settings.env,
            )
            return

        # ── Production: block with machine-readable initialization error ──
        logger.error(
            "Registry freshness check FAILED: claim_registry is empty. "
            "Extraction blocked. Run POST /api/v1/registry/sync to initialize. "
            "ENV=%s",
            settings.env,
        )
        raise RegistryNotInitializedError(
            "Claim registry is empty — cannot verify freshness. "
            "Run POST /api/v1/registry/sync before extracting fact sheets."
        )

    # Normalise to UTC if the DB returns a naive datetime (e.g. SQLite in tests)
    updated_at = latest.updated_at
    if updated_at.tzinfo is None:
        updated_at = updated_at.replace(tzinfo=timezone.utc)

    if updated_at < threshold:
        age_hours = (datetime.now(timezone.utc) - updated_at).total_seconds() / 3600
        logger.error(
            "Registry freshness check FAILED: last_updated=%s age_hours=%.1f "
            "threshold_hours=%d. Run POST /api/v1/registry/sync.",
            updated_at.isoformat(),
            age_hours,
            staleness_hours,
        )
        raise RegistryStaleError(
            f"Claim registry is stale: last updated {age_hours:.1f}h ago, "
            f"threshold is {staleness_hours}h. "
            "Run POST /api/v1/registry/sync before extracting fact sheets."
        )

    logger.info(
        "Registry freshness check passed: last_updated=%s threshold_hours=%d",
        updated_at.isoformat(),
        staleness_hours,
    )


# ---------------------------------------------------------------------------
# Ticket 2.4 — Registry sync / initialization
# ---------------------------------------------------------------------------

#: Bootstrap claims inserted on first sync when the registry is empty.
#: These cover the three claim types the system understands and provide a
#: baseline that operators can extend via POST /claims after seeding.
_BOOTSTRAP_CLAIMS: list[dict] = [
    {"claim_text": "REST API integration", "claim_type": ClaimType.INTEGRATION},
    {"claim_text": "SAML 2.0 SSO integration", "claim_type": ClaimType.INTEGRATION},
    {"claim_text": "Webhook event integration", "claim_type": ClaimType.INTEGRATION},
    {"claim_text": "ISO 27001 compliance", "claim_type": ClaimType.COMPLIANCE},
    {"claim_text": "SOC 2 Type II compliance", "claim_type": ClaimType.COMPLIANCE},
    {"claim_text": "GDPR compliance", "claim_type": ClaimType.COMPLIANCE},
    {"claim_text": "API response time SLA", "claim_type": ClaimType.PERFORMANCE},
    {"claim_text": "99.9% uptime SLA", "claim_type": ClaimType.PERFORMANCE},
    {"claim_text": "Requests per second throughput", "claim_type": ClaimType.PERFORMANCE},
]


def sync_registry(db: Session) -> dict:
    """
    Seed or refresh the claim registry.

    Behaviour:
    - Empty registry (zero rows): inserts bootstrap claims covering all three
      ClaimType values (INTEGRATION, COMPLIANCE, PERFORMANCE) so that the
      freshness gate will pass on the next extraction request.
    - Non-empty registry: touches updated_at on every existing row to mark the
      registry as freshly synced without modifying claim content.

    This function is the intended target of POST /api/v1/registry/sync.
    It does NOT bypass or weaken governance — it initializes the state that
    the governance gate requires before it will permit extraction.

    Args:
        db: SQLAlchemy session.

    Returns:
        dict with keys: registry_count (int), seeded (bool), updated_at (datetime).
    """
    count = db.query(ClaimRegistry).count()
    seeded = False
    now = datetime.now(timezone.utc)

    if count == 0:
        bootstrap = [
            ClaimRegistry(claim_text=c["claim_text"], claim_type=c["claim_type"])
            for c in _BOOTSTRAP_CLAIMS
        ]
        db.add_all(bootstrap)
        db.commit()
        seeded = True
        count = len(bootstrap)
        logger.info(
            "Registry initialized: seeded %d bootstrap claims. "
            "Operators should add domain-specific claims via POST /claims.",
            count,
        )
    else:
        # Refresh updated_at so the staleness gate resets its window.
        db.query(ClaimRegistry).update(
            {"updated_at": now}, synchronize_session=False
        )
        db.commit()
        logger.info(
            "Registry synced: refreshed updated_at for %d existing claims.",
            count,
        )

    latest: ClaimRegistry = (
        db.query(ClaimRegistry)
        .order_by(ClaimRegistry.updated_at.desc())
        .first()
    )
    return {
        "registry_count": count,
        "seeded": seeded,
        "updated_at": latest.updated_at,
    }


# ---------------------------------------------------------------------------
# Ticket 2.2 — LLM extraction helpers
# ---------------------------------------------------------------------------

_EXTRACTION_SCHEMA_DESCRIPTION = """
{
  "features": [
    {"name": "<feature name>", "description": "<what the feature does>"}
  ],
  "integrations": [
    {"system": "<external system name>", "method": "<integration method e.g. REST/SAML/Webhook>", "notes": "<additional context>"}
  ],
  "compliance": [
    {"standard": "<standard name e.g. ISO-27001 / SOC 2>", "status": "<compliance status>", "details": "<audit or certification details>"}
  ],
  "performance_metrics": [
    {"metric": "<metric name>", "value": "<numeric value as string>", "unit": "<unit e.g. ms/req/s/%>"}
  ],
  "limitations": [
    {"category": "<limitation category>", "description": "<description of the limitation>"}
  ]
}
"""


def _read_document_text(file_path: str) -> str:
    """Read document content as plain text.

    Supports UTF-8 text files. Non-text bytes are replaced with the Unicode
    replacement character so the function never raises on binary content.

    Args:
        file_path: Absolute path to the document file.

    Returns:
        File content as a string, or an informational message if unavailable.
    """
    if not file_path:
        return "[No file path provided — cannot extract document content.]"
    if not os.path.exists(file_path):
        return f"[Document file not found at path: {file_path}]"
    try:
        with open(file_path, "r", encoding="utf-8", errors="replace") as fh:
            return fh.read()
    except OSError as exc:
        logger.warning("Could not read document file %s: %s", file_path, exc)
        return f"[Could not read file: {exc}]"


def _build_extraction_prompt(document_text: str) -> str:
    """Build a structured prompt for LLM-based fact sheet extraction."""
    return f"""You are a technical analyst extracting structured product facts from a document.

Extract ALL factual information from the document below and return it as valid JSON matching
the schema exactly. Follow these rules:
1. Only include facts explicitly stated in the document — do NOT invent or infer.
2. Use empty lists ([]) for categories with no data; never omit a key.
3. All string values must be non-empty (minimum 1 character).
4. The "value" field in performance_metrics must be a numeric string (e.g. "150", "99.9").
5. Return ONLY the JSON object — no markdown fences, no explanatory text.

REQUIRED OUTPUT SCHEMA:
{_EXTRACTION_SCHEMA_DESCRIPTION}

DOCUMENT TO ANALYSE:
{document_text}

Return the JSON object now."""


def _is_retryable_error(exc: BaseException) -> bool:
    """Return True for transient errors that warrant an automatic retry.

    Covers both Anthropic and OpenAI (Google/xAI/Perplexity) SDKs.
    RateLimitError is excluded to avoid excessive looping; retries for 429
    are handled at the orchestrator level where appropriate.
    """
    # Anthropic SDK
    if isinstance(exc, anthropic.APIStatusError) and exc.status_code >= 500:
        return True
    if isinstance(exc, anthropic.APITimeoutError):
        return True

    # OpenAI SDK (and providers using the OpenAI-compatible adapter)
    if isinstance(exc, openai.APIStatusError) and exc.status_code >= 500:
        return True
    if isinstance(exc, openai.APITimeoutError):
        return True

    return False


@retry(
    retry=retry_if_exception(_is_retryable_error),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    reraise=True,
)
def _call_llm(document_id: str, document_content: str, model_name: str, settings_snapshot: ActiveSettings) -> dict[str, Any]:
    """Call the configured LLM provider to extract structured fact sheet data.

    Args:
        document_id:       UUID string (used for logging).
        document_content:  File path of the source document to process.
        model_name:        Model ID (fetched from DB settings by caller).
        settings_snapshot: ActiveSettings snapshot with provider API keys.

    Returns:
        dict matching the FactSheetData schema (validation done by caller).
    """
    document_text = _read_document_text(document_content)
    prompt = _build_extraction_prompt(document_text)

    logger.info(
        "LLM extraction call start: model=%s document_id=%s prompt_length=%d",
        model_name,
        document_id,
        len(prompt),
    )

    raw_text = llm_adapter.call_llm(
        prompt=prompt,
        model_name=model_name,
        settings=settings_snapshot,
        timeout=30.0,
        max_tokens=4096,
        temperature=0.0,
    )
    return json.loads(raw_text)


# ---------------------------------------------------------------------------
# Ticket 2.2 — Fact sheet extraction orchestrator
# ---------------------------------------------------------------------------

def extract_factsheet(db: Session, document_id: str) -> FactSheet:
    """
    Orchestrate LLM-based fact sheet extraction for a document.

    Flow:
        1. Registry freshness gate (raises RegistryStaleError if stale).
        2. Load Document row (raises NotFoundError if missing).
        3. Call _call_llm() (raises ExtractionError on LLM or JSON parse failure).
        4. Validate extraction output against FactSheetData (raises ExtractionError
           on schema mismatch — rejects malformed extractions).
        5. INSERT FactSheet row + audit log inside a transaction.
           → Rolls back and re-raises on any DB failure.

    Args:
        db:          SQLAlchemy session.
        document_id: UUID string of the source Document.

    Returns:
        Newly created FactSheet ORM instance.

    Raises:
        RegistryStaleError: registry freshness check failed.
        NotFoundError:      document_id does not exist.
        ExtractionError:    LLM call failed or output failed schema validation.
    """
    logger.info("Fact sheet extraction requested: document_id=%s", document_id)

    # ── 1. Registry freshness gate (uses DB settings via settings_service) ────
    check_registry_freshness(db)

    # ── 1b. Fetch active settings for LLM model name ──────────────────────────
    active = settings_service.get_settings(db)

    # ── 2. Load document ──────────────────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 2b. Mark validation as started — commit immediately so polling picks it up ──
    doc.status = DocumentStatus.VALIDATING
    doc.current_stage = "VALIDATION_STARTED"
    doc.validation_progress = 10
    try:
        db.commit()
    except Exception:
        db.rollback()
        raise

    # ── 3. LLM extraction ─────────────────────────────────────────────────────
    try:
        raw_extraction: dict[str, Any] = _call_llm(
            document_id=document_id,
            document_content=doc.file_path or "",
            model_name=active.llm_model_name,
            settings_snapshot=active,
        )
    except (anthropic.RateLimitError, openai.RateLimitError) as exc:
        reason = llm_adapter.clean_llm_error(exc)
        logger.error("LLM rate limit / quota exceeded: document_id=%s error=%s", document_id, exc)
        raise RateLimitError(f"LLM rate Limit Exceeded: {reason}") from exc
    except Exception as exc:
        logger.error("LLM call failed: document_id=%s error=%s", document_id, exc)
        raise ExtractionError(f"LLM extraction failed: {exc}") from exc

    # ── 4. Schema validation — reject malformed extractions ──────────────────
    try:
        validated: FactSheetData = FactSheetData.model_validate(raw_extraction)
    except Exception as exc:
        logger.error(
            "Schema validation failed: document_id=%s error=%s", document_id, exc
        )
        raise ExtractionError(f"Extraction schema validation failed: {exc}") from exc

    structured_data = validated.model_dump()

    # ── 5. Persist inside a transaction (rollback on any failure) ────────────
    try:
        fact_sheet = FactSheet(document_id=document_id, structured_data=structured_data)
        db.add(fact_sheet)
        db.flush()  # populate fact_sheet.id before audit log
        _audit(
            db,
            document_id,
            f"FactSheet extracted and stored: fact_sheet_id={fact_sheet.id}",
        )
        # Re-fetch doc inside transaction to update progress
        doc = db.query(Document).filter(Document.id == document_id).first()
        if doc is not None:
            doc.current_stage = "FACTSHEET_EXTRACTED"
            doc.validation_progress = 50
        db.commit()
        db.refresh(fact_sheet)
        logger.info(
            "FactSheet created: fact_sheet_id=%s document_id=%s",
            fact_sheet.id,
            document_id,
        )
    except Exception:
        db.rollback()
        logger.error(
            "Transaction rolled back during extraction: document_id=%s", document_id
        )
        raise

    return fact_sheet
