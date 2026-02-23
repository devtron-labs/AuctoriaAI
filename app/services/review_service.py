"""
Service layer for EPIC 7 — Human Review & Approval.

Provides four operations for the human review workflow:
  - get_pending_reviews:  Paginated list of documents awaiting review.
  - get_review_details:   Full context (draft, score, validation, fact sheet, audit).
  - approve_document:     Transition to APPROVED; admin force-approve override supported.
  - reject_document:      Transition to BLOCKED with rejection reason.

Production notes:
- All write operations (approve/reject) are atomic: status update + review
  metadata + audit log entry commit together; rollback on any DB error.
- Force approve is an admin override that bypasses status requirements.
  It MUST include a non-empty override_reason for audit trail compliance.
  Force-approve actions are logged with a prominent "FORCE APPROVED" prefix.
- Days in review is derived from the governance-check audit log entry that
  first set the document to HUMAN_REVIEW. Falls back to 0 if not found.
- Pagination uses LIMIT/OFFSET ordered by updated_at ASC (oldest-first) for
  SLA tracking — reviewers see documents that have waited longest first.
- Audit log for review-details is capped at the 20 most recent entries.
- Webhook notifications are sent after each approval/rejection via
  notification_service. Configure NOTIFICATION_WEBHOOK_URL to enable.
  Notifications are best-effort and never block review operations.
- Concurrent review protection: in this MVP, no optimistic locking is applied.
  For production, add a check that reviewed_at is still NULL before committing.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy.orm import Session

from app.models.models import (
    AuditLog,
    Document,
    DocumentStatus,
    DraftVersion,
    FactSheet,
)
from app.schemas.schemas import (
    ApproveDocumentResponse,
    AuditLogRead,
    DocumentRead,
    DraftVersionRead,
    FactSheetRead,
    PendingReviewItem,
    PendingReviewResponse,
    RejectDocumentResponse,
    ReviewDetailsResponse,
)
from app.services.exceptions import (
    InvalidReviewStatusError,
    MissingOverrideReasonError,
    NotFoundError,
)
from app.services import notification_service, settings_service

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _days_since(timestamp: datetime) -> int:
    """Return the number of full days elapsed since the given timestamp.

    Treats naive timestamps as UTC. Always returns >= 0.
    """
    now = datetime.now(timezone.utc)
    if timestamp.tzinfo is None:
        timestamp = timestamp.replace(tzinfo=timezone.utc)
    return max(0, (now - timestamp).days)


def _get_review_started_at(db: Session, document_id: str) -> Optional[datetime]:
    """Find when the document last entered HUMAN_REVIEW status.

    Searches audit_logs for the most recent entry whose action contains
    'HUMAN_REVIEW' — written by the governance service on a PASSED decision.

    Returns None if no matching entry exists (e.g., status was set manually).
    """
    entry = (
        db.query(AuditLog)
        .filter(
            AuditLog.document_id == document_id,
            AuditLog.action.contains("HUMAN_REVIEW"),
        )
        .order_by(AuditLog.timestamp.desc())
        .first()
    )
    return entry.timestamp if entry else None


def _parse_validation_summary(validation_report) -> tuple[Optional[bool], int]:
    """Safely extract (claims_valid, total_issues) from a validation_report dict.

    Returns (None, 0) when the report is absent or not a dict.
    """
    if not isinstance(validation_report, dict):
        return None, 0
    is_valid: bool = bool(validation_report.get("is_valid", False))
    blocked_claims: int = int(validation_report.get("blocked_claims", 0))
    return is_valid, blocked_claims


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_pending_reviews(
    db: Session,
    page: int = 1,
    page_size: int = 20,
) -> PendingReviewResponse:
    """Return a paginated list of documents with status=HUMAN_REVIEW.

    Results are ordered by updated_at ascending (oldest first) to surface
    documents that have been waiting longest, supporting SLA tracking.

    For each document the response includes:
    - Latest draft preview (first 200 chars) and composite score.
    - Validation summary: claims_valid flag and blocked-claim count.
    - Days elapsed since the document entered HUMAN_REVIEW.

    Args:
        db:        Active SQLAlchemy session.
        page:      1-based page number (default 1).
        page_size: Results per page (default 20).

    Returns:
        PendingReviewResponse with total count and document summaries.
    """
    offset = (page - 1) * page_size

    base_query = db.query(Document).filter(
        Document.status == DocumentStatus.HUMAN_REVIEW
    )
    total: int = base_query.count()
    docs = (
        base_query
        .order_by(Document.updated_at.asc())
        .offset(offset)
        .limit(page_size)
        .all()
    )

    items: list[PendingReviewItem] = []
    for doc in docs:
        # Latest draft for preview and score
        latest_draft: Optional[DraftVersion] = (
            db.query(DraftVersion)
            .filter(DraftVersion.document_id == doc.id)
            .order_by(DraftVersion.iteration_number.desc())
            .first()
        )
        draft_preview: Optional[str] = None
        score: Optional[float] = None
        if latest_draft is not None:
            draft_preview = latest_draft.content_markdown[:200]
            score = latest_draft.score

        claims_valid, total_issues = _parse_validation_summary(doc.validation_report)

        # Days in review from audit log
        review_started_at = _get_review_started_at(db, doc.id)
        days_in_review = _days_since(review_started_at) if review_started_at else 0

        items.append(
            PendingReviewItem(
                id=doc.id,
                title=doc.title,
                status=doc.status,
                draft_preview=draft_preview,
                score=score,
                claims_valid=claims_valid,
                total_issues=total_issues,
                days_in_review=days_in_review,
                created_at=doc.created_at,
                updated_at=doc.updated_at,
            )
        )

    return PendingReviewResponse(
        total=total,
        page=page,
        page_size=page_size,
        documents=items,
    )


def get_review_details(db: Session, document_id: str) -> ReviewDetailsResponse:
    """Return the complete review context for a single document.

    Fetches all data a reviewer needs to make an informed decision:
    - Full document metadata.
    - Latest draft (complete content_markdown, score, feedback).
    - All draft versions in iteration order (history).
    - Raw validation_report JSON.
    - Latest fact sheet.
    - 20 most recent audit log entries (newest first).

    Args:
        db:          Active SQLAlchemy session.
        document_id: UUID string of the target document.

    Returns:
        ReviewDetailsResponse with all review context.

    Raises:
        NotFoundError: Document does not exist.
    """
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # All draft versions ordered by iteration ascending (show history)
    all_draft_rows = (
        db.query(DraftVersion)
        .filter(DraftVersion.document_id == document_id)
        .order_by(DraftVersion.iteration_number.asc())
        .all()
    )
    latest_draft_row: Optional[DraftVersion] = (
        all_draft_rows[-1] if all_draft_rows else None
    )

    # Latest fact sheet
    fact_sheet_row: Optional[FactSheet] = (
        db.query(FactSheet)
        .filter(FactSheet.document_id == document_id)
        .order_by(FactSheet.created_at.desc())
        .first()
    )

    # Recent audit log (20 entries, newest first)
    audit_rows = (
        db.query(AuditLog)
        .filter(AuditLog.document_id == document_id)
        .order_by(AuditLog.timestamp.desc())
        .limit(20)
        .all()
    )

    return ReviewDetailsResponse(
        document=DocumentRead.model_validate(doc),
        latest_draft=(
            DraftVersionRead.model_validate(latest_draft_row)
            if latest_draft_row is not None
            else None
        ),
        all_drafts=[DraftVersionRead.model_validate(d) for d in all_draft_rows],
        validation_report=doc.validation_report,
        fact_sheet=(
            FactSheetRead.model_validate(fact_sheet_row)
            if fact_sheet_row is not None
            else None
        ),
        audit_log=[AuditLogRead.model_validate(a) for a in audit_rows],
    )


def approve_document(
    db: Session,
    document_id: str,
    reviewer_name: str,
    notes: Optional[str] = None,
    force_approve: bool = False,
    override_reason: Optional[str] = None,
) -> ApproveDocumentResponse:
    """Approve a document, transitioning it to APPROVED status.

    Normal approval:
      - Document must be in HUMAN_REVIEW status.
      - Raises InvalidReviewStatusError otherwise.

    Force approval (admin override):
      - Allowed from any status (BLOCKED, VALIDATING, DRAFT, etc.).
      - Requires a non-empty override_reason for compliance.
      - Audit log entry is prefixed with "FORCE APPROVED" for visibility.

    Side effects (atomic commit):
      - document.status          → APPROVED
      - document.reviewed_by     → reviewer_name
      - document.reviewed_at     → current UTC timestamp
      - document.review_notes    → notes (may be None)
      - document.force_approved  → force_approve flag
      - AuditLog entry created

    Args:
        db:              Active SQLAlchemy session.
        document_id:     UUID string of the target document.
        reviewer_name:   Name of the approving reviewer.
        notes:           Optional approval notes.
        force_approve:   If True, bypass HUMAN_REVIEW status requirement.
        override_reason: Required (non-empty) when force_approve=True.

    Returns:
        ApproveDocumentResponse with updated status and review metadata.

    Raises:
        NotFoundError:             Document does not exist.
        MissingOverrideReasonError: force_approve=True but override_reason empty.
        InvalidReviewStatusError:  Document not in HUMAN_REVIEW and force_approve=False.
    """
    doc = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    if force_approve:
        if not override_reason or not override_reason.strip():
            raise MissingOverrideReasonError(
                "override_reason is required and cannot be empty when force_approve=True. "
                "Provide a documented reason for the admin override."
            )
    else:
        if doc.status != DocumentStatus.HUMAN_REVIEW:
            raise InvalidReviewStatusError(
                f"Document {document_id} is in '{doc.status.value}' status. "
                "Only documents in HUMAN_REVIEW status can be approved. "
                "Set force_approve=True with an override_reason to bypass this check."
            )

    reviewed_at = datetime.now(timezone.utc)

    if force_approve:
        audit_action = (
            f"FORCE APPROVED by {reviewer_name}: "
            f"override_reason='{override_reason}'; "
            f"previous_status={doc.status.value}"
            + (f"; notes='{notes}'" if notes else "")
        )[:512]
    else:
        audit_action = (
            f"approved by {reviewer_name}"
            + (f"; notes='{notes}'" if notes else "")
        )[:512]

    try:
        doc.status = DocumentStatus.APPROVED
        doc.reviewed_by = reviewer_name
        doc.reviewed_at = reviewed_at
        doc.review_notes = notes
        doc.force_approved = force_approve
        db.add(AuditLog(document_id=document_id, action=audit_action))
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Approval commit failed: document_id=%s", document_id)
        raise

    logger.info(
        "Document approved: document_id=%s reviewer=%s force=%s",
        document_id,
        reviewer_name,
        force_approve,
    )

    # Send webhook notification (best-effort — never blocks the response)
    # Fetch webhook URL from DB settings so admin changes take effect immediately.
    webhook_url = settings_service.get_settings(db).notification_webhook_url
    notification_service.notify_approved(
        document_id=document_id,
        reviewer_name=reviewer_name,
        reviewed_at=reviewed_at,
        force_approved=force_approve,
        notes=notes,
        webhook_url=webhook_url,
    )

    return ApproveDocumentResponse(
        document_id=document_id,
        status=DocumentStatus.APPROVED,
        reviewed_by=reviewer_name,
        reviewed_at=reviewed_at,
        force_approved=force_approve,
        message="Document approved successfully",
    )


def reject_document(
    db: Session,
    document_id: str,
    reviewer_name: str,
    rejection_reason: str,
    suggested_action: Optional[str] = None,
) -> RejectDocumentResponse:
    """Reject a document, transitioning it to BLOCKED status.

    The document must be in HUMAN_REVIEW status. Unlike approve_document,
    reject_document does not support a force override — a document can only
    be rejected from HUMAN_REVIEW.

    Side effects (atomic commit):
      - document.status       → BLOCKED
      - document.reviewed_by  → reviewer_name
      - document.reviewed_at  → current UTC timestamp
      - document.review_notes → rejection_reason
      - AuditLog entry created with rejection details and optional suggested_action

    Args:
        db:               Active SQLAlchemy session.
        document_id:      UUID string of the target document.
        reviewer_name:    Name of the reviewer rejecting the document.
        rejection_reason: Reason for rejection (stored in audit log).
        suggested_action: Optional revision guidance for the document author.

    Returns:
        RejectDocumentResponse with updated status and rejection details.

    Raises:
        NotFoundError:           Document does not exist.
        InvalidReviewStatusError: Document not in HUMAN_REVIEW status.
    """
    doc = (
        db.query(Document)
        .filter(Document.id == document_id)
        .with_for_update()
        .first()
    )
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    if doc.status != DocumentStatus.HUMAN_REVIEW:
        raise InvalidReviewStatusError(
            f"Document {document_id} is in '{doc.status.value}' status. "
            "Only documents in HUMAN_REVIEW status can be rejected."
        )

    reviewed_at = datetime.now(timezone.utc)

    audit_action = (
        f"rejected by {reviewer_name}: reason='{rejection_reason}'"
        + (f"; suggested_action='{suggested_action}'" if suggested_action else "")
    )[:512]

    try:
        doc.status = DocumentStatus.BLOCKED
        doc.reviewed_by = reviewer_name
        doc.reviewed_at = reviewed_at
        doc.review_notes = rejection_reason
        db.add(AuditLog(document_id=document_id, action=audit_action))
        db.commit()
    except Exception:
        db.rollback()
        logger.error("Rejection commit failed: document_id=%s", document_id)
        raise

    logger.info(
        "Document rejected: document_id=%s reviewer=%s",
        document_id,
        reviewer_name,
    )

    # Send webhook notification (best-effort — never blocks the response)
    # Fetch webhook URL from DB settings so admin changes take effect immediately.
    webhook_url = settings_service.get_settings(db).notification_webhook_url
    notification_service.notify_rejected(
        document_id=document_id,
        reviewer_name=reviewer_name,
        reviewed_at=reviewed_at,
        rejection_reason=rejection_reason,
        suggested_action=suggested_action,
        webhook_url=webhook_url,
    )

    return RejectDocumentResponse(
        document_id=document_id,
        status=DocumentStatus.BLOCKED,
        rejection_reason=rejection_reason,
        suggested_action=suggested_action,
        message="Document rejected and returned for revision",
    )
