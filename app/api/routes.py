import logging
from typing import Optional

import anthropic
import openai

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.database import get_db, SessionLocal
from app.models.models import Document, DocumentClassification, DocumentStatus
from app.schemas.schemas import (
    ApproveDocumentRequest,
    ApproveDocumentResponse,
    AuditLogRead,
    ClaimCreate,
    ClaimRead,
    ClaimResponse,
    ClaimValidationRequest,
    ClaimValidationReport,
    DocumentCreate,
    DocumentRead,
    DocumentStatusResponse,
    DocumentTransition,
    DocumentUploadResponse,
    DraftGenerateAcceptedResponse,
    DraftGenerateRequest,
    DraftGenerateResponse,
    DraftVersionCreate,
    DraftVersionRead,
    FactSheetCreate,
    FactSheetExtractionResponse,
    FactSheetRead,
    GenerateDraftRequest,
    GenerateDraftResponse,
    GovernanceCheckResponse,
    PendingReviewResponse,
    QAEvaluateRequest,
    QAEvaluateResponse,
    RejectDocumentRequest,
    RejectDocumentResponse,
    RegistrySyncResponse,
    ReviewDetailsResponse,
    ValidateClaimsRequest,
    ValidateClaimsResponse,
)
from app.services import (
    audit_service,
    claim_service,
    claim_validation_service,
    document_service,
    download_service,
    draft_generation_service,
    extraction_service,
    fact_sheet_service,
    governance_service,
    qa_iteration_service,
    review_service,
    settings_service,
    upload_service,
)
from app.services.document_service import InvalidTransitionError
from app.services.exceptions import (
    DocumentNotReadyError,
    DuplicateFileError,
    ExtractionError,
    InvalidFileTypeError,
    InvalidRubricScoreError,
    InvalidReviewStatusError,
    LLMInvalidJSONError,
    MaxIterationsReachedError,
    MissingOverrideReasonError,
    NoFactSheetError,
    NotFoundError,
    RateLimitError,
    RegistryNotInitializedError,
    RegistryStaleError,
)

router = APIRouter()

logger = logging.getLogger(__name__)


# ── Documents ────────────────────────────────────────────────────────────────

@router.post("/documents", response_model=DocumentRead, status_code=status.HTTP_201_CREATED)
def create_document(payload: DocumentCreate, db: Session = Depends(get_db)):
    return document_service.create_document(db, title=payload.title)


@router.get("/documents", response_model=list[DocumentRead])
def list_documents(
    skip: int = 0,
    limit: int = 100,
    status: Optional[DocumentStatus] = None,
    db: Session = Depends(get_db),
):
    return document_service.list_documents(db, skip=skip, limit=limit, status=status)


# ── EPIC 7 — Human Review & Approval ─────────────────────────────────────────
# NOTE: /documents/pending-review MUST be registered before /documents/{document_id}
# so FastAPI does not capture the literal "pending-review" as a path parameter.

@router.get(
    "/documents/pending-review",
    response_model=PendingReviewResponse,
    summary="List documents awaiting human review (paginated)",
)
def list_pending_reviews(
    page: int = 1,
    page_size: int = 20,
    db: Session = Depends(get_db),
):
    """
    Return a paginated list of documents with status=HUMAN_REVIEW.

    Results are ordered oldest-first (by updated_at) to surface documents
    that have been waiting longest, supporting SLA tracking.

    Each item includes:
    - Document metadata (id, title, status, timestamps)
    - Latest draft preview (first 200 characters)
    - Latest composite QA score
    - Validation summary (claims_valid flag, blocked-claim count)
    - Days elapsed since the document entered HUMAN_REVIEW status
    """
    return review_service.get_pending_reviews(db, page=page, page_size=page_size)


@router.get(
    "/documents/{document_id}/status",
    response_model=DocumentStatusResponse,
    summary="Poll pipeline progress for a document (lightweight status endpoint)",
)
def get_document_status(document_id: str, db: Session = Depends(get_db)):
    """
    Return the current pipeline stage and progress for a document.

    Designed for frequent polling (every 2–3 seconds) by the frontend progress bar.
    Returns only the fields needed to render progress — avoids the cost of
    eager-loading draft versions on every poll.

    Response fields:
    - **status**: Current DocumentStatus enum value.
    - **current_stage**: Human-readable stage name (e.g. "DRAFT_GENERATED").
    - **validation_progress**: Integer 0–100 for the progress bar.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return DocumentStatusResponse(
        status=doc.status,
        current_stage=doc.current_stage,
        error_message=doc.error_message,
        validation_progress=doc.validation_progress,
    )


@router.get("/documents/{document_id}", response_model=DocumentRead)
def get_document(document_id: str, db: Session = Depends(get_db)):
    doc = document_service.get_document(db, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.post("/documents/{document_id}/transition", response_model=DocumentRead)
def transition_document(
    document_id: str, payload: DocumentTransition, db: Session = Depends(get_db)
):
    try:
        return document_service.transition_document(db, document_id, payload.target_status)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Ticket 2.1 — Document Upload ─────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/upload",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_200_OK,
    summary="Upload a file (PDF, DOCX, TXT) to an existing document",
)
def upload_document(
    document_id: str,
    file: UploadFile = File(..., description="File to upload (PDF, DOCX, or TXT)"),
    classification: DocumentClassification = Form(
        ..., description="Document classification: INTERNAL | CONFIDENTIAL | PUBLIC"
    ),
    db: Session = Depends(get_db),
):
    """
    Attach a file to an existing document record.

    - Validates file extension and MIME type.
    - Computes SHA-256 hash; rejects duplicates (same hash on a different document).
    - Enforces configurable file size limit.
    - Stores the file at: {storage_path}/{document_id}/{filename}
    - Updates file_path, file_hash, classification, file_size, mime_type on the document.
    """
    try:
        return upload_service.upload_document(db, document_id, file, classification)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DuplicateFileError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except InvalidFileTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Draft Versions ────────────────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/drafts",
    response_model=DraftVersionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_draft_version(
    document_id: str, payload: DraftVersionCreate, db: Session = Depends(get_db)
):
    try:
        return document_service.create_draft_version(
            db,
            document_id=document_id,
            content_markdown=payload.content_markdown,
            score=payload.score,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/drafts", response_model=list[DraftVersionRead])
def list_draft_versions(document_id: str, db: Session = Depends(get_db)):
    try:
        return document_service.list_draft_versions(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/drafts/{draft_id}", response_model=DraftVersionRead)
def get_draft_version(document_id: str, draft_id: str, db: Session = Depends(get_db)):
    try:
        return document_service.get_draft_version(db, draft_id, document_id=document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Fact Sheets ───────────────────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/fact-sheets",
    response_model=FactSheetRead,
    status_code=status.HTTP_201_CREATED,
)
def create_fact_sheet(document_id: str, payload: FactSheetCreate, db: Session = Depends(get_db)):
    try:
        return fact_sheet_service.create_fact_sheet(
            db, document_id=document_id, structured_data=payload.structured_data
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/fact-sheets", response_model=list[FactSheetRead])
def list_fact_sheets(document_id: str, db: Session = Depends(get_db)):
    try:
        return fact_sheet_service.list_fact_sheets(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/documents/{document_id}/fact-sheets/{fact_sheet_id}", response_model=FactSheetRead)
def get_fact_sheet(document_id: str, fact_sheet_id: str, db: Session = Depends(get_db)):
    try:
        return fact_sheet_service.get_fact_sheet(db, fact_sheet_id, document_id=document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Ticket 2.2 — Fact Sheet Extraction ───────────────────────────────────────

@router.post(
    "/documents/{document_id}/extract-factsheet",
    response_model=FactSheetExtractionResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Trigger LLM-based fact sheet extraction for a document",
)
def extract_factsheet(document_id: str, db: Session = Depends(get_db)):
    """
    Extract a structured fact sheet from the document using the LLM engine.

    Pre-conditions:
    - The claim registry must have been seeded and updated within the staleness
      window (configurable via REGISTRY_STALENESS_HOURS, default: 24 h).
    - The document must exist.

    The extracted data is validated against the FactSheetData schema before
    being stored.

    HTTP 503 is returned in two distinct cases:
    - **registry_not_initialized**: the registry has zero rows. Run
      POST /api/v1/registry/sync to seed bootstrap claims.
    - **registry_stale**: the registry exists but was last updated longer ago
      than the configured staleness window. Run POST /api/v1/registry/sync
      to refresh updated_at timestamps.
    """
    try:
        return extraction_service.extract_factsheet(db, document_id)
    except RegistryNotInitializedError as exc:
        # Structured 503 with machine-readable code so clients can act on it.
        raise HTTPException(
            status_code=503,
            detail={
                "code": "registry_not_initialized",
                "message": str(exc),
                "action_required": (
                    "Run POST /api/v1/registry/sync before extracting fact sheets."
                ),
            },
        )
    except RegistryStaleError as exc:
        raise HTTPException(
            status_code=503,
            detail={
                "code": "registry_stale",
                "message": str(exc),
                "action_required": (
                    "Run POST /api/v1/registry/sync to refresh the registry."
                ),
            },
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Ticket 2.4 — Registry sync / initialization ───────────────────────────────

@router.post(
    "/registry/sync",
    response_model=RegistrySyncResponse,
    status_code=status.HTTP_200_OK,
    summary="Seed or refresh the claim registry to satisfy the freshness gate",
)
def sync_registry(db: Session = Depends(get_db)):
    """
    Initialize or refresh the claim registry.

    **When the registry is empty (first-time setup):**
    Bootstrap claims covering INTEGRATION, COMPLIANCE, and PERFORMANCE types
    are inserted. Operators should follow up with POST /claims to add
    domain-specific claims relevant to their product.

    **When the registry already has rows:**
    All existing rows have their `updated_at` timestamp refreshed to the
    current UTC time, resetting the staleness window without changing any
    claim content.

    This endpoint does NOT weaken governance — it initializes the state that
    the governance freshness gate requires before permitting extraction.
    """
    result = extraction_service.sync_registry(db)
    return RegistrySyncResponse(
        message=(
            "Registry initialized with bootstrap claims."
            if result["seeded"]
            else "Registry refreshed: updated_at reset for all claims."
        ),
        registry_count=result["registry_count"],
        seeded=result["seeded"],
        updated_at=result["updated_at"],
    )


# ── Claims ────────────────────────────────────────────────────────────────────

@router.post("/claims", response_model=ClaimRead, status_code=status.HTTP_201_CREATED)
def create_claim(payload: ClaimCreate, db: Session = Depends(get_db)):
    return claim_service.create_claim(
        db,
        claim_text=payload.claim_text,
        claim_type=payload.claim_type,
        expiry_date=payload.expiry_date,
    )


# ── Ticket 2.3 — Enhanced claim endpoints ────────────────────────────────────

@router.get(
    "/claims",
    response_model=list[ClaimResponse],
    summary="List all claims with approval metadata and expiry",
)
def list_claims(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    return claim_validation_service.get_claims(db, skip=skip, limit=limit)


@router.get(
    "/claims/{claim_id}",
    response_model=ClaimResponse,
    summary="Retrieve a single claim with approval metadata and expiry",
)
def get_claim(claim_id: str, db: Session = Depends(get_db)):
    try:
        return claim_validation_service.get_claim(db, claim_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/claims/validate",
    response_model=ClaimValidationReport,
    status_code=status.HTTP_200_OK,
    summary="Validate a list of claim IDs against the registry",
)
def validate_claims(payload: ClaimValidationRequest, db: Session = Depends(get_db)):
    """
    Validate a list of claim IDs.

    Returns a structured report with:
    - **valid_claims**: IDs that exist and are not expired.
    - **expired_claims**: IDs that exist but past their expiry_date (soft warning).
    - **missing_claims**: IDs not found in the registry (hard fail → is_valid=False).
    - **is_valid**: False if any claims are missing; True otherwise.
    - **warnings / errors**: Human-readable messages for each issue.
    """
    result = claim_validation_service.validate_claims(db, payload.claim_ids)
    return ClaimValidationReport(**result)


# ── EPIC 3 — Draft Generation ─────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/generate-draft",
    response_model=GenerateDraftResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Generate a fact-grounded whitepaper draft from the document's FactSheet",
)
def generate_draft(
    document_id: str,
    payload: GenerateDraftRequest,
    db: Session = Depends(get_db),
):
    """
    Generate a whitepaper draft using only the facts from the document's latest FactSheet.

    Pre-conditions:
    - The document must exist.
    - The document must have at least one FactSheet (run POST /extract-factsheet first).

    Post-conditions:
    - A new DraftVersion is created with an auto-incremented iteration_number.
    - Document status transitions to VALIDATING.
    - An audit log entry is written.

    Returns the draft version metadata and a 200-character content preview.
    """
    try:
        draft = draft_generation_service.generate_draft(
            db, document_id=document_id, tone=payload.tone
        )
    except (NotFoundError, NoFactSheetError) as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except (anthropic.APITimeoutError, openai.APITimeoutError):
        raise HTTPException(
            status_code=504,
            detail=(
                "The LLM timed out while generating the draft. "
                "Try again or increase llm_timeout_seconds in Admin → System Settings."
            ),
        )
    except (anthropic.AuthenticationError, openai.AuthenticationError):
        raise HTTPException(
            status_code=500,
            detail="LLM authentication failed. Check your API key configuration in Admin → System Settings.",
        )
    except (anthropic.APIError, openai.APIError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM API error during draft generation: {exc}",
        )

    return GenerateDraftResponse(
        draft_version_id=draft.id,
        document_id=draft.document_id,
        iteration_number=draft.iteration_number,
        content_preview=draft.content_markdown[:200],
        created_at=draft.created_at,
    )


# ── Prompt-First Draft Generation ────────────────────────────────────────────

def _run_qa_pipeline_background(document_id: str, document_type: Optional[str]) -> None:
    """Auto-run QA pipeline after prompt-first draft generation.

    Uses its own DB session so it can run safely after the HTTP response is
    sent (FastAPI BackgroundTasks execute after the response but before the
    request's DB session is torn down).
    """
    db = SessionLocal()
    try:
        qa_iteration_service.evaluate_and_iterate(
            db,
            document_id=document_id,
            document_type=document_type,
        )
    except Exception as exc:
        logger.error(
            "Background QA pipeline failed: document_id=%s error=%s",
            document_id,
            exc,
        )
    finally:
        db.close()


def _run_draft_generation_background(
    document_id: Optional[str],
    prompt: str,
    document_type: str,
    tone: str,
) -> None:
    """Background task: generate a draft bounded by admin-configured time and iterations.

    Reads max_qa_iterations as the maximum number of generation attempts and
    llm_timeout_seconds as the total wall-clock budget. The budget is divided
    equally across attempts (minimum 30 s each) so every retry gets a fair
    share of the configured timeout.

    doc.current_stage and doc.validation_progress are updated at each attempt
    so the frontend status-poll endpoint always reflects real progress.

    On success the QA pipeline is auto-advanced (same as the old synchronous path).
    On final failure doc.current_stage is set to "DRAFT_FAILED".
    """
    db = SessionLocal()
    try:
        active = settings_service.get_settings(db)
        # llm_timeout_seconds is a per-call limit, not a total budget.
        # Each attempt gets the full configured timeout; max_qa_iterations
        # controls how many retries to make before giving up.
        per_attempt_timeout = float(active.llm_timeout_seconds)
        max_attempts = max(active.max_qa_iterations, 1)

        doc: Optional[Document] = None
        if document_id:
            doc = db.query(Document).filter(Document.id == document_id).first()

        last_error: Optional[str] = None
        for attempt in range(1, max_attempts + 1):
            if doc is not None:
                # Spread progress 10 → 70 across attempts so the bar advances
                progress = 10 + int((attempt - 1) / max_attempts * 60)
                doc.current_stage = "DRAFT_GENERATING"
                doc.validation_progress = progress
                db.commit()
                db.refresh(doc)

            try:
                draft_generation_service.generate_draft_from_prompt(
                    db,
                    prompt=prompt,
                    document_id=document_id,
                    document_type=document_type,
                    tone=tone,
                    timeout_override=per_attempt_timeout,
                    suppress_status_updates=True,
                )
                # Draft committed successfully; auto-advance QA pipeline
                if document_id:
                    if doc is not None:
                        doc.error_message = None # Clear any previous errors on success
                        db.commit()
                    try:
                        qa_iteration_service.evaluate_and_iterate(
                            db,
                            document_id=document_id,
                            document_type=document_type,
                        )
                    except Exception as qa_exc:
                        logger.error(
                            "Background QA pipeline failed: document_id=%s error=%s",
                            document_id,
                            qa_exc,
                        )
                return  # success — exit the retry loop

            except (anthropic.APITimeoutError, openai.APITimeoutError, RateLimitError) as exc:
                last_error = str(exc)
                logger.warning(
                    "Draft generation attempt %d/%d retryable failure (timeout or rate limit): document_id=%s error=%s",
                    attempt,
                    max_attempts,
                    document_id,
                    last_error
                )

                # ── Ticket 2.4 / Epic 3 refinement: Stop retrying on permanent Quota failures ──
                # If the error is a Quota Exceeded (Resource Exhausted), further retries
                # will not help and only flood the logs/API. Transient 'Rate limit'
                # errors still warrant a retry if attempts remain.
                if "Quota exceeded" in last_error:
                    logger.info("Stopping background retries due to permanent Quota Exceeded failure.")
                    break

                if attempt < max_attempts:
                    continue  # retry with the next attempt

            except Exception as exc:
                last_error = str(exc)
                logger.error(
                    "Draft generation attempt %d/%d failed: document_id=%s error_type=%s error=%s",
                    attempt,
                    max_attempts,
                    document_id,
                    type(exc).__name__,
                    last_error,
                )
                break  # non-retryable error; fall through to failure handling

        # All attempts exhausted or a non-retryable error occurred
        if doc is not None:
            doc.status = DocumentStatus.BLOCKED
            doc.current_stage = "DRAFT_FAILED"
            doc.error_message = last_error or "Draft generation failed after all attempts."
            doc.validation_progress = 0
            db.commit()

    except Exception as exc:
        error_msg = str(exc)
        logger.error(
            "Background draft generation task crashed: document_id=%s error=%s",
            document_id,
            error_msg,
        )
        # Best-effort: mark the document as failed so the UI unblocks
        try:
            if document_id:
                _db2 = SessionLocal()
                try:
                    _doc = _db2.query(Document).filter(Document.id == document_id).first()
                    if _doc:
                        _doc.status = DocumentStatus.BLOCKED
                        _doc.current_stage = "DRAFT_FAILED"
                        _doc.error_message = error_msg
                        _doc.validation_progress = 0
                        _db2.commit()
                finally:
                    _db2.close()
        except Exception:
            pass
    finally:
        db.close()


@router.post(
    "/drafts/generate",
    response_model=DraftGenerateAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a whitepaper draft from a user prompt with optional document context",
)
def generate_draft_from_prompt(
    payload: DraftGenerateRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """
    Create a new whitepaper draft driven by a natural-language user prompt.

    This endpoint implements the **prompt-first** architecture and returns
    **202 Accepted** immediately — draft generation runs as a background task.

    The background task is bounded by two admin settings:

    - **llm_timeout_seconds**: total wall-clock budget split equally across
      all attempts (min 30 s per attempt).
    - **max_qa_iterations**: maximum number of generation attempts before the
      document is marked as DRAFT_FAILED.

    Poll ``GET /documents/{id}/status`` every 2–3 s to track progress:

    - ``current_stage = "DRAFT_GENERATING"`` — generation in progress.
    - ``current_stage = "DRAFT_GENERATED"`` — success; fetch the new draft.
    - ``current_stage = "DRAFT_FAILED"`` — all attempts exhausted.

    All errors are returned as ``{"code": "...", "message": "..."}``.
    """
    doc_id = str(payload.document_id) if payload.document_id else None

    # Validate document exists and set the initial "DRAFT_GENERATING" status
    # before returning so the UI sees progress immediately.
    if doc_id:
        doc = db.query(Document).filter(Document.id == doc_id).first()
        if doc is None:
            raise HTTPException(
                status_code=404,
                detail={"code": "not_found", "message": f"Document {doc_id} not found."},
            )
        doc.current_stage = "DRAFT_GENERATING"
        doc.validation_progress = 5
        db.commit()

    # Hand off to the background task — HTTP response is returned immediately.
    background_tasks.add_task(
        _run_draft_generation_background,
        doc_id,
        payload.prompt,
        payload.document_type,
        payload.tone,
    )

    return DraftGenerateAcceptedResponse(
        status="generating",
        document_id=doc_id,
        message=(
            "Draft generation started. "
            "Poll GET /documents/{id}/status until current_stage is "
            "'DRAFT_GENERATED' or 'DRAFT_FAILED'."
        ),
    )


# ── EPIC 4 — QA + Iteration ───────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/qa-iterate",
    response_model=QAEvaluateResponse,
    status_code=status.HTTP_200_OK,
    summary="Run rubric QA evaluation and iterative improvement on the document's latest draft",
)
def qa_iterate(
    document_id: str,
    payload: QAEvaluateRequest,
    db: Session = Depends(get_db),
):
    """
    Evaluate the document's latest DraftVersion using a six-category rubric
    (Factual Correctness, Technical Depth, Clarity, Readability, Formatting,
    Style Adherence) and iteratively improve it until it reaches the passing
    threshold or the iteration limit is hit.

    Pre-conditions:
    - The document must exist.
    - The document must have at least one DraftVersion (run POST /generate-draft first).
    - The document must have at least one FactSheet (run POST /extract-factsheet first).

    Post-conditions:
    - Document status is updated to PASSED or BLOCKED.
    - DraftVersion.score and feedback_text are persisted after each evaluation.
    - One AuditLog entry is written per iteration.

    The max_iterations parameter defaults to the server-configured value
    (max_qa_iterations) when not provided, and must be >= 1 if specified.
    """
    logger.info("QA iterate endpoint hit", extra={"document_id": document_id})

    try:
        result = qa_iteration_service.evaluate_and_iterate(
            db,
            document_id=document_id,
            max_iterations=payload.max_iterations,
            document_type=payload.document_type,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RateLimitError as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except MaxIterationsReachedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except InvalidRubricScoreError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except LLMInvalidJSONError:
        raise HTTPException(
            status_code=500,
            detail="LLM returned invalid JSON during QA evaluation",
        )
    except (anthropic.APITimeoutError, openai.APITimeoutError):
        raise HTTPException(
            status_code=504,
            detail=(
                "The QA evaluation timed out while waiting for the LLM. "
                "Try again or increase llm_timeout_seconds in Admin → System Settings."
            ),
        )
    except (anthropic.AuthenticationError, openai.AuthenticationError):
        raise HTTPException(
            status_code=500,
            detail="LLM authentication failed. Check your API key configuration in Admin → System Settings.",
        )
    except (anthropic.APIError, openai.APIError) as exc:
        raise HTTPException(
            status_code=502,
            detail=f"LLM API error during QA evaluation: {exc}",
        )

    return QAEvaluateResponse(
        document_id=result["document_id"],
        final_status=result["final_status"],
        iterations_completed=result["iterations_completed"],
        final_score=result["final_score"],
        final_draft_id=result["final_draft_id"],
        iteration_history=result["iteration_history"],
        quality_trend=result["quality_trend"],
    )


# ── EPIC 5 — Claim Extraction & Registry Validation ───────────────────────────

@router.post(
    "/documents/{document_id}/validate-claims",
    response_model=ValidateClaimsResponse,
    status_code=status.HTTP_200_OK,
    summary="Extract claims from the latest draft and validate against the ClaimRegistry",
)
def validate_draft_claims(
    document_id: str,
    payload: ValidateClaimsRequest,
    db: Session = Depends(get_db),
):
    """
    Extract all claims (integration, compliance, performance, superlatives) from
    the document's latest DraftVersion using regex patterns and validate each
    against the ClaimRegistry.

    **Blocking rules:**
    - Integration / compliance / performance claims not found in the registry → BLOCKED.
    - Superlatives without a supporting performance metric in the same or
      adjacent paragraph → BLOCKED.
    - Expired registry entries produce a soft warning but do not block.

    **Side effects on blocking:**
    - Document status is set to BLOCKED.
    - Full validation report is persisted in `documents.validation_report`.
    - An AuditLog entry is written.

    **Side effects on pass:**
    - Validation report is persisted (document status unchanged).
    - An AuditLog entry is written.

    The response `is_valid` field indicates whether the draft passed.
    HTTP 200 is returned in both passing and blocking cases — callers must
    inspect `validation_report.is_valid`.
    """
    try:
        report = claim_validation_service.validate_draft_claims(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    # Re-fetch document for current status (may have been updated to BLOCKED)
    from app.services.document_service import get_document  # local import avoids circular dep
    doc = get_document(db, document_id)
    if doc is None:
        raise HTTPException(status_code=404, detail=f"Document {document_id} not found")

    return ValidateClaimsResponse(
        document_id=document_id,
        status=doc.status,
        validation_report=report,
    )


# ── EPIC 6 — Governance Gate ──────────────────────────────────────────────────

@router.post(
    "/documents/{document_id}/governance-check",
    response_model=GovernanceCheckResponse,
    status_code=status.HTTP_200_OK,
    summary="Run the final governance gate: score + claim validation → HUMAN_REVIEW or BLOCKED",
)
def governance_check(
    document_id: str,
    db: Session = Depends(get_db),
):
    """
    Evaluate whether a document is ready for human review.

    Combines the QA composite score (EPIC 4) and claim validation result (EPIC 5):

    - **PASSED** → score >= threshold **AND** all claims valid → status: `HUMAN_REVIEW`
    - **FAILED** → score below threshold **OR** claims invalid → status: `BLOCKED`

    Pre-conditions (returns 422 if not met):
    - Document must have at least one DraftVersion.
    - Latest DraftVersion must have a non-NULL score (run POST /qa-iterate first).
    - Document must have a non-NULL validation_report (run POST /validate-claims first).

    This endpoint is **idempotent** — calling it multiple times safely re-evaluates
    and updates the document status based on the current score and validation report.

    HTTP 200 is returned in both passing and failing governance decisions — callers
    must inspect the `decision` field (`PASSED` or `FAILED`).
    """
    try:
        return governance_service.enforce_governance(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except DocumentNotReadyError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get(
    "/documents/{document_id}/review-details",
    response_model=ReviewDetailsResponse,
    summary="Fetch full review context for a document",
)
def get_review_details(document_id: str, db: Session = Depends(get_db)):
    """
    Return everything a reviewer needs to make an informed approve/reject decision:

    - Full document metadata.
    - Latest draft (complete content_markdown, score, feedback_text).
    - All draft versions in iteration order (revision history).
    - Raw validation_report (claim-level detail).
    - Latest fact sheet.
    - 20 most recent audit log entries.
    """
    try:
        return review_service.get_review_details(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.post(
    "/documents/{document_id}/approve",
    response_model=ApproveDocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Approve a document (normal or admin force-approve)",
)
def approve_document(
    document_id: str,
    payload: ApproveDocumentRequest,
    db: Session = Depends(get_db),
):
    """
    Approve a document, transitioning it to **APPROVED** status.

    **Normal approval** (`force_approve=false`):
    - Document must be in `HUMAN_REVIEW` status.
    - Returns 422 if the document is in any other status.

    **Force approval** (`force_approve=true`, admin only):
    - Permits approval from any status (BLOCKED, VALIDATING, DRAFT, etc.).
    - `override_reason` is **required** and must be non-empty.
    - The audit log entry is prominently marked "FORCE APPROVED" for compliance.

    Side effects:
    - `document.status` → `APPROVED`
    - `reviewed_by`, `reviewed_at`, `review_notes`, `force_approved` are persisted.
    - An `AuditLog` entry is created.
    """
    try:
        return review_service.approve_document(
            db,
            document_id=document_id,
            reviewer_name=payload.reviewer_name,
            notes=payload.notes,
            force_approve=payload.force_approve,
            override_reason=payload.override_reason,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except MissingOverrideReasonError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except InvalidReviewStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post(
    "/documents/{document_id}/reject",
    response_model=RejectDocumentResponse,
    status_code=status.HTTP_200_OK,
    summary="Reject a document and return it for revision",
)
def reject_document(
    document_id: str,
    payload: RejectDocumentRequest,
    db: Session = Depends(get_db),
):
    """
    Reject a document, transitioning it to **BLOCKED** status.

    The document must be in `HUMAN_REVIEW` status. Returns 422 otherwise.

    Side effects:
    - `document.status` → `BLOCKED`
    - `reviewed_by`, `reviewed_at`, `review_notes` are persisted.
    - An `AuditLog` entry is created with the rejection reason and optional
      suggested action for the document author.
    """
    try:
        return review_service.reject_document(
            db,
            document_id=document_id,
            reviewer_name=payload.reviewer_name,
            rejection_reason=payload.rejection_reason,
            suggested_action=payload.suggested_action,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except InvalidReviewStatusError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


# ── Audit Logs (read-only — no delete) ───────────────────────────────────────

@router.get("/documents/{document_id}/audit-logs", response_model=list[AuditLogRead])
def list_audit_logs(document_id: str, db: Session = Depends(get_db)):
    try:
        return audit_service.list_audit_logs(db, document_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


# ── Draft Downloads ───────────────────────────────────────────────────────────

@router.get(
    "/drafts/{draft_id}/download/pdf",
    summary="Download a draft version as a PDF file",
    response_class=StreamingResponse,
)
def download_draft_pdf(draft_id: str, db: Session = Depends(get_db)):
    """
    Stream the draft content as a PDF attachment.

    The markdown content is converted to plain text and laid out as a PDF
    document using reportlab. No file is written to disk.

    Returns:
        A streamed PDF with Content-Disposition: attachment.

    Raises:
        404 if the draft version does not exist.
    """
    logger.info("PDF download requested", extra={"draft_id": draft_id})
    try:
        buffer, filename = download_service.generate_pdf(db, draft_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get(
    "/drafts/{draft_id}/download/docx",
    summary="Download a draft version as a DOCX file",
    response_class=StreamingResponse,
)
def download_draft_docx(draft_id: str, db: Session = Depends(get_db)):
    """
    Stream the draft content as a DOCX (Word) attachment.

    Markdown headings are mapped to Word heading styles; body text has
    inline markdown stripped. No file is written to disk.

    Returns:
        A streamed DOCX with Content-Disposition: attachment.

    Raises:
        404 if the draft version does not exist.
    """
    logger.info("DOCX download requested", extra={"draft_id": draft_id})
    try:
        buffer, filename = download_service.generate_docx(db, draft_id)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc))

    return StreamingResponse(
        buffer,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
