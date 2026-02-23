"""
Service layer for EPIC 6 — Governance Gate.

Evaluates the final governance checkpoint by combining:
  - Quality score from EPIC 4 (DraftVersion.score on the latest iteration)
  - Claim validation result from EPIC 5 (Document.validation_report.is_valid)

Governance logic:
  IF score >= governance_score_threshold AND validation_report.is_valid:
      document.status → HUMAN_REVIEW   (decision = PASSED)
  ELSE:
      document.status → BLOCKED        (decision = FAILED)

Production notes:
- Governance check is idempotent: calling it multiple times safely re-evaluates
  and updates the status based on the current score + validation_report.
- Status is written directly (same pattern as EPIC 4/5) without going through
  the generic state-machine transition helper, because this gate is authoritative.
- Transaction is atomic: status update + audit log commit together; rollback on any error.
- validation_report is parsed defensively — malformed or missing fields default to
  failing the check rather than silently passing.
"""

import logging
from typing import Any

from sqlalchemy.orm import Session

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion
from app.schemas.schemas import GovernanceCheckResponse, GovernanceDecision
from app.services import settings_service
from app.services.exceptions import DocumentNotReadyError, NotFoundError

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _check_prerequisites(document: Document, latest_draft: DraftVersion | None) -> None:
    """
    Validate all prerequisites for a governance check.

    Raises DocumentNotReadyError with a descriptive message if any prerequisite
    is not met. Callers should map this to HTTP 422.

    Prerequisites:
      1. Document must have at least one DraftVersion.
      2. Latest DraftVersion must have a non-NULL score.
      3. Document must have a non-NULL validation_report.

    Args:
        document:     The Document ORM instance.
        latest_draft: The latest DraftVersion (by iteration_number), or None.

    Raises:
        DocumentNotReadyError: If any prerequisite is missing.
    """
    if latest_draft is None:
        raise DocumentNotReadyError(
            f"Document {document.id} has no draft versions. "
            "Run POST /generate-draft and POST /qa-iterate before the governance check."
        )
    if latest_draft.score is None:
        raise DocumentNotReadyError(
            f"Document {document.id}'s latest draft (iteration "
            f"{latest_draft.iteration_number}) has no QA score. "
            "Run POST /qa-iterate to evaluate the draft first."
        )
    if document.validation_report is None:
        raise DocumentNotReadyError(
            f"Document {document.id} has no claim validation report. "
            "Run POST /validate-claims before the governance check."
        )


def _parse_validation_report(report: Any) -> tuple[bool, int, str]:
    """
    Safely parse the validation_report JSONB field from the Document.

    Handles malformed, incomplete, or unexpected report structures by
    defaulting to a failing outcome rather than masking errors.

    Args:
        report: The raw value of Document.validation_report (expected dict).

    Returns:
        Tuple of:
          - is_valid (bool):      True when all claims passed.
          - blocked_claims (int): Number of claims that caused blocking.
          - summary (str):        Human-readable summary of the validation outcome.
    """
    if not isinstance(report, dict):
        logger.warning(
            "validation_report is not a dict (type=%s); treating as invalid",
            type(report).__name__,
        )
        return False, 0, "Malformed validation report (unexpected type)"

    is_valid: bool = bool(report.get("is_valid", False))
    blocked_claims: int = int(report.get("blocked_claims", 0))
    total_claims: int = int(report.get("total_claims", 0))
    warnings: int = int(report.get("warnings", 0))

    if is_valid:
        summary = f"All {total_claims} claims validated successfully"
        if warnings > 0:
            summary += f" ({warnings} expired-claim warning(s))"
    else:
        summary = (
            f"{blocked_claims} unsupported claim(s) found out of {total_claims} total"
        )

    return is_valid, blocked_claims, summary


def _make_governance_decision(
    score: float,
    claims_valid: bool,
    threshold: float,
) -> tuple[GovernanceDecision, str]:
    """
    Pure function that applies the governance decision logic.

    Both conditions must be true for a PASSED decision:
      - score >= threshold
      - claims_valid is True

    Args:
        score:        Composite QA score from the latest DraftVersion.
        claims_valid: Whether the claim validation report passed (is_valid).
        threshold:    Minimum composite score required to pass governance.

    Returns:
        Tuple of (GovernanceDecision, reason_string) where reason_string is a
        human-readable explanation of the decision suitable for the API response.
    """
    score_passed = score >= threshold

    if score_passed and claims_valid:
        reason = (
            f"Document meets all governance requirements: "
            f"score {score:.2f} >= {threshold:.1f} and all claims validated"
        )
        return GovernanceDecision.PASSED, reason

    # Build a combined failure reason that names every failing condition
    failure_parts: list[str] = []
    if not score_passed:
        failure_parts.append(f"score {score:.2f} below threshold {threshold:.1f}")
    if not claims_valid:
        failure_parts.append("claim validation failed")

    reason = "Document blocked: " + " and ".join(failure_parts)
    return GovernanceDecision.FAILED, reason


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def enforce_governance(db: Session, document_id: str) -> GovernanceCheckResponse:
    """
    Run the governance gate for a document and persist the outcome.

    Workflow:
      1. Fetch document — NotFoundError if missing.
      2. Fetch latest DraftVersion (highest iteration_number).
      3. Check prerequisites — DocumentNotReadyError if any condition not met.
      4. Read score from latest DraftVersion.
      5. Parse validation_report safely to extract is_valid and blocked_claims.
      6. Apply governance decision logic (_make_governance_decision).
      7. Update document.status to HUMAN_REVIEW or BLOCKED.
      8. Write AuditLog entry with full decision rationale.
      9. Commit atomically (rollback on any DB error, then re-raise).
      10. Return GovernanceCheckResponse.

    Idempotency:
      Calling this multiple times on the same document is safe. Each call
      re-evaluates the current score and validation_report, updates the status,
      and appends a new audit log entry.

    Args:
        db:          Active SQLAlchemy session.
        document_id: UUID string of the target document.

    Returns:
        GovernanceCheckResponse with decision, final_status, score, and details.

    Raises:
        NotFoundError:         Document does not exist.
        DocumentNotReadyError: Prerequisites not met (no draft, no score, no report).
        Exception:             DB commit failure — transaction is rolled back.
    """
    # ── 0. Fetch active settings (60-second cache) ─────────────────────────
    active = settings_service.get_settings(db)
    threshold = active.governance_score_threshold

    # ── 1. Fetch document ──────────────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 2. Fetch latest DraftVersion ───────────────────────────────────────
    latest_draft: DraftVersion | None = (
        db.query(DraftVersion)
        .filter(DraftVersion.document_id == document_id)
        .order_by(DraftVersion.iteration_number.desc())
        .first()
    )

    # ── 3. Check prerequisites ─────────────────────────────────────────────
    _check_prerequisites(doc, latest_draft)

    # ── 4. Extract score (guaranteed non-None after prerequisites check) ───
    score: float = latest_draft.score  # type: ignore[assignment]

    # ── 5. Parse validation report ─────────────────────────────────────────
    claims_valid, blocked_count, validation_summary = _parse_validation_report(
        doc.validation_report
    )

    # ── 6. Apply governance logic ──────────────────────────────────────────
    decision, reason = _make_governance_decision(score, claims_valid, threshold)
    score_passed = score >= threshold

    # ── 7 & 8. Update status + audit log ──────────────────────────────────
    new_status = (
        DocumentStatus.HUMAN_REVIEW
        if decision == GovernanceDecision.PASSED
        else DocumentStatus.BLOCKED
    )

    details: dict[str, Any] = {
        "score": score,
        "score_threshold": threshold,
        "score_passed": score_passed,
        "claims_valid": claims_valid,
        "validation_summary": validation_summary,
    }
    if not claims_valid:
        details["blocked_claims"] = blocked_count

    audit_action = (
        f"governance check: {decision.value} — "
        f"score={score:.2f} threshold={threshold:.1f} "
        f"claims_valid={claims_valid} → status={new_status.value}"
    )[:512]

    # ── 9. Atomic commit ───────────────────────────────────────────────────
    try:
        doc.status = new_status
        db.add(AuditLog(document_id=document_id, action=audit_action))
        db.commit()
    except Exception:
        db.rollback()
        logger.error(
            "Governance check commit failed: document_id=%s", document_id
        )
        raise

    logger.info(
        "Governance check complete: document_id=%s decision=%s score=%.2f "
        "claims_valid=%s new_status=%s",
        document_id,
        decision.value,
        score,
        claims_valid,
        new_status.value,
    )

    return GovernanceCheckResponse(
        document_id=document_id,
        decision=decision,
        final_status=new_status,
        score=score,
        claims_valid=claims_valid,
        reason=reason,
        details=details,
    )
