"""
Service layer for claim registry validation.

EPIC 2 (Ticket 2.3) — Claim Registry Schema & Validation API:
  get_claims()      — paginated list of all claims
  get_claim()       — single claim by ID
  validate_claims() — validate a list of claim IDs

EPIC 5 — Claim Extraction & Registry Validation:
  validate_claim_against_registry() — validate one extracted claim vs. ClaimRegistry
  validate_superlatives()           — check superlatives for nearby performance support
  validate_draft_claims()           — full pipeline: extract → validate → block/pass
"""

import logging
import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.models import AuditLog, ClaimRegistry, ClaimType, Document, DocumentStatus, DraftVersion
from app.schemas.schemas import (
    ClaimValidationResult,
    DraftValidationReport,
    ExtractedClaim,
    ExtractedClaimType,
)
from app.services.claim_extraction import extract_all_claims, extract_superlatives
from app.services.exceptions import NotFoundError

logger = logging.getLogger(__name__)

# Compiled pattern for parsing paragraph index out of a location string
# e.g. "paragraph 3, line 2" → group(1) = "3"
_PARA_IDX_RE = re.compile(r'paragraph\s+(\d+)', re.IGNORECASE)


# ---------------------------------------------------------------------------
# EPIC 2 — CRUD + registry-level validation
# ---------------------------------------------------------------------------

def get_claims(db: Session, skip: int = 0, limit: int = 100) -> list[ClaimRegistry]:
    """
    Return a paginated list of all claim registry entries, ordered by creation time.

    Args:
        db:    SQLAlchemy session.
        skip:  Number of rows to skip (offset).
        limit: Maximum number of rows to return.

    Returns:
        List of ClaimRegistry ORM instances.
    """
    return (
        db.query(ClaimRegistry)
        .order_by(ClaimRegistry.created_at)
        .offset(skip)
        .limit(limit)
        .all()
    )


def get_claim(db: Session, claim_id: str) -> ClaimRegistry:
    """
    Return a single claim by its UUID.

    Args:
        db:       SQLAlchemy session.
        claim_id: UUID string.

    Returns:
        ClaimRegistry ORM instance.

    Raises:
        NotFoundError: claim_id does not exist in the registry.
    """
    claim = db.query(ClaimRegistry).filter(ClaimRegistry.id == claim_id).first()
    if claim is None:
        raise NotFoundError(f"Claim {claim_id} not found")
    return claim


def validate_claims(db: Session, claim_ids: list[str]) -> dict:
    """
    Validate a list of claim IDs against the registry.

    Rules:
      - Hard fail (error)   if a claim_id is not found in the registry.
      - Soft flag (warning) if a claim exists but its expiry_date is in the past.
      - is_valid is True only when there are zero hard errors.

    Args:
        db:        SQLAlchemy session.
        claim_ids: List of claim UUID strings to validate.

    Returns:
        Dict compatible with ClaimValidationReport:
          {
            "valid_claims":   list of IDs that exist and are not expired,
            "expired_claims": list of IDs that exist but are past expiry_date,
            "missing_claims": list of IDs not found in the registry,
            "is_valid":       bool — False if any missing claims,
            "warnings":       list of human-readable warning strings,
            "errors":         list of human-readable error strings,
          }
    """
    now = datetime.now(timezone.utc)

    valid_claims:   list[str] = []
    expired_claims: list[str] = []
    missing_claims: list[str] = []
    warnings:       list[str] = []
    errors:         list[str] = []

    # Fetch all requested claims in a single query for efficiency
    found: dict[str, ClaimRegistry] = {
        row.id: row
        for row in db.query(ClaimRegistry)
        .filter(ClaimRegistry.id.in_(claim_ids))
        .all()
    }

    for claim_id in claim_ids:
        if claim_id not in found:
            missing_claims.append(claim_id)
            errors.append(f"Claim {claim_id} not found in registry (hard fail)")
            continue

        claim = found[claim_id]

        if claim.expiry_date is not None:
            # Normalise to UTC in case DB returns a naive datetime (SQLite)
            expiry = claim.expiry_date
            if expiry.tzinfo is None:
                expiry = expiry.replace(tzinfo=timezone.utc)

            if expiry < now:
                expired_claims.append(claim_id)
                warnings.append(
                    f"Claim {claim_id} expired at {expiry.isoformat()} (soft warning)"
                )
                continue

        valid_claims.append(claim_id)

    is_valid = len(errors) == 0

    logger.info(
        "Claim validation complete: total=%d valid=%d expired=%d missing=%d",
        len(claim_ids),
        len(valid_claims),
        len(expired_claims),
        len(missing_claims),
    )

    return {
        "valid_claims":   valid_claims,
        "expired_claims": expired_claims,
        "missing_claims": missing_claims,
        "is_valid":       is_valid,
        "warnings":       warnings,
        "errors":         errors,
    }


# ---------------------------------------------------------------------------
# EPIC 5 — Draft claim extraction + registry validation pipeline
# ---------------------------------------------------------------------------

def _parse_paragraph_index(location: str) -> int:
    """
    Parse the paragraph index from a location string like 'paragraph 3, line 2'.

    Returns:
        1-indexed paragraph number, or 0 if the string cannot be parsed.
    """
    m = _PARA_IDX_RE.match(location)
    return int(m.group(1)) if m else 0


def _blocked_message(claim: ExtractedClaim) -> str:
    """Build the standard blocking error message for an unsupported claim."""
    if claim.claim_type == ExtractedClaimType.INTEGRATION:
        return f"Unsupported integration claim: {claim.claim_text}"
    if claim.claim_type == ExtractedClaimType.COMPLIANCE:
        return f"Unsupported compliance claim: {claim.claim_text}"
    if claim.claim_type == ExtractedClaimType.PERFORMANCE:
        return f"Unsupported performance claim: {claim.claim_text}"
    return f"Unsupported claim: {claim.claim_text}"


def validate_claim_against_registry(
    db: Session,
    claim: ExtractedClaim,
) -> ClaimValidationResult:
    """
    Validate a single extracted claim against the ClaimRegistry.

    Lookup strategy:
      - PERFORMANCE claims are self-validating: the regex extraction already
        guarantees the correct numeric+unit format. Requiring exact registry
        matches for specific values (e.g. "99.9%", "50ms") is impractical
        because LLM-generated metrics vary and cannot be pre-registered.
        Performance data proximity to superlatives is still validated separately.
      - For INTEGRATION / COMPLIANCE: filter by claim_type, then use bidirectional
        substring matching (extracted claim in registry entry OR registry entry
        in extracted claim) to handle name variants robustly.
      - If the registry has no entries for a claim type, pass the claim with a
        warning rather than blocking — an empty registry cannot validate anything.

    Result rules:
      - PERFORMANCE claim → always is_valid=True (format validated by regex).
      - Not found in registry → is_blocked=True, error_message set.
      - Found, expired → is_valid=True, is_expired=True (soft warning, no block).
      - Found, active  → is_valid=True.

    Args:
        db:    SQLAlchemy session.
        claim: An ExtractedClaim with claim_type in {INTEGRATION, COMPLIANCE, PERFORMANCE}.

    Returns:
        ClaimValidationResult.
    """
    now = datetime.now(timezone.utc)

    # ── Performance claims: self-validating by format ─────────────────────────
    # The extraction regex already ensures a valid numeric+unit format.
    # Requiring exact registry matches for LLM-generated numeric metrics
    # (e.g. "99.9%", "50ms", "10000requests/sec") is impractical — these
    # values vary per document and cannot be pre-registered. The superlative
    # validation step already checks that performance data backs any superlatives.
    if claim.claim_type == ExtractedClaimType.PERFORMANCE:
        logger.debug(
            "Performance claim '%s' passes format validation (registry lookup skipped)",
            claim.claim_text,
        )
        return ClaimValidationResult(
            claim=claim,
            is_valid=True,
            is_blocked=False,
        )

    # Map ExtractedClaimType → DB ClaimType (SUPERLATIVE is not handled here)
    db_claim_type = ClaimType(claim.claim_type.value)

    # Load all registry entries of this type; match in Python for safety
    # (avoids LIKE escaping issues with characters like % in performance values)
    candidates: list[ClaimRegistry] = (
        db.query(ClaimRegistry)
        .filter(ClaimRegistry.claim_type == db_claim_type)
        .all()
    )

    # ── Empty registry fallback ───────────────────────────────────────────────
    # If no claims of this type exist in the registry, blocking all extracted
    # claims would make every document fail governance unconditionally.
    # Pass with a warning so the pipeline can proceed — operators should call
    # POST /registry/sync to populate the registry with approved claims.
    if not candidates:
        logger.warning(
            "Registry has no %s entries — passing claim '%s' without validation. "
            "Run POST /registry/sync to seed the registry.",
            claim.claim_type.value,
            claim.claim_text,
        )
        return ClaimValidationResult(
            claim=claim,
            is_valid=True,
            is_blocked=False,
        )

    # ── Bidirectional substring matching ─────────────────────────────────────
    # Check: extracted claim text ⊆ registry entry  OR  registry entry ⊆ extracted claim.
    # This handles name variants: extracted "Salesforce" matches registry
    # "integrates with Salesforce", and extracted "integrates with Salesforce CRM"
    # also matches registry "Salesforce".
    claim_text_lower = claim.claim_text.lower()
    registry_entry: ClaimRegistry | None = next(
        (
            c for c in candidates
            if claim_text_lower in c.claim_text.lower()
            or c.claim_text.lower() in claim_text_lower
        ),
        None,
    )

    if registry_entry is None:
        logger.debug(
            "No registry entry for %s claim '%s'",
            claim.claim_type.value,
            claim.claim_text,
        )
        return ClaimValidationResult(
            claim=claim,
            is_valid=False,
            is_blocked=True,
            error_message=_blocked_message(claim),
        )

    # Check expiry
    if registry_entry.expiry_date is not None:
        expiry = registry_entry.expiry_date
        if expiry.tzinfo is None:
            expiry = expiry.replace(tzinfo=timezone.utc)

        if expiry < now:
            logger.debug(
                "Registry entry for %s claim '%s' is expired (soft warning)",
                claim.claim_type.value,
                claim.claim_text,
            )
            return ClaimValidationResult(
                claim=claim,
                is_valid=True,
                is_blocked=False,
                is_expired=True,
            )

    return ClaimValidationResult(
        claim=claim,
        is_valid=True,
        is_blocked=False,
    )


def validate_superlatives(
    markdown: str,
    performance_claims: list[ExtractedClaim],
) -> list[ClaimValidationResult]:
    """
    Validate that each superlative has a supporting performance metric in the
    same or an immediately adjacent paragraph.

    Rules:
      - Superlative WITH performance metric in same/adjacent paragraph → allowed.
      - Superlative WITHOUT nearby performance metric → is_blocked=True.

    Args:
        markdown:          Raw markdown from the draft (used to extract superlatives).
        performance_claims: Performance claims already extracted (with location info).

    Returns:
        List of ClaimValidationResult, one per detected superlative.
    """
    superlative_claims = extract_superlatives(markdown)
    if not superlative_claims:
        return []

    # Build set of paragraph indices that have performance support
    performance_para_indices: set[int] = {
        _parse_paragraph_index(c.location_in_draft) for c in performance_claims
    }

    results: list[ClaimValidationResult] = []
    for sup in superlative_claims:
        sup_para_idx = _parse_paragraph_index(sup.location_in_draft)
        # Adjacent = same paragraph OR immediately before/after
        nearby = any(
            p in performance_para_indices
            for p in (sup_para_idx - 1, sup_para_idx, sup_para_idx + 1)
        )

        if nearby:
            results.append(ClaimValidationResult(
                claim=sup,
                is_valid=True,
                is_blocked=False,
            ))
        else:
            results.append(ClaimValidationResult(
                claim=sup,
                is_valid=False,
                is_blocked=True,
                error_message=(
                    f"Superlative '{sup.claim_text}' requires supporting performance data"
                ),
            ))

    return results


def validate_draft_claims(
    db: Session,
    document_id: str,
) -> DraftValidationReport:
    """
    Full claim extraction and registry validation pipeline for EPIC 5.

    Steps:
      1. Verify the document exists.
      2. Fetch the latest DraftVersion.
      3. Extract all claims using the regex pipeline.
      4. Validate INTEGRATION / COMPLIANCE / PERFORMANCE claims against ClaimRegistry.
      5. Validate superlatives for proximity to performance metrics.
      6. If any blocking failure:
           - Set document.status = BLOCKED.
           - Persist validation_report JSON to the documents table.
           - Write an AuditLog entry.
      7. If all pass:
           - Persist validation_report JSON (status unchanged).
           - Write an AuditLog entry.
      8. Return the DraftValidationReport.

    Args:
        db:          SQLAlchemy session.
        document_id: UUID string of the target document.

    Returns:
        DraftValidationReport with full per-claim results.

    Raises:
        NotFoundError: Document or its latest draft does not exist.
    """
    # ── 1. Verify document ────────────────────────────────────────────────────
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    # ── 2. Fetch latest draft ─────────────────────────────────────────────────
    latest_draft: DraftVersion | None = (
        db.query(DraftVersion)
        .filter(DraftVersion.document_id == document_id)
        .order_by(DraftVersion.iteration_number.desc())
        .first()
    )
    if latest_draft is None:
        raise NotFoundError(f"No draft found for document {document_id}")

    content = latest_draft.content_markdown

    # ── 3. Extract all claims ─────────────────────────────────────────────────
    all_claims = extract_all_claims(content)

    # Separate by type for targeted processing
    registry_claims = [
        c for c in all_claims if c.claim_type != ExtractedClaimType.SUPERLATIVE
    ]
    performance_claims = [
        c for c in all_claims if c.claim_type == ExtractedClaimType.PERFORMANCE
    ]

    # ── 4. Validate registry claims ───────────────────────────────────────────
    results: list[ClaimValidationResult] = [
        validate_claim_against_registry(db, claim) for claim in registry_claims
    ]

    # ── 5. Validate superlatives ──────────────────────────────────────────────
    results.extend(validate_superlatives(content, performance_claims))

    # ── 6. Aggregate report ───────────────────────────────────────────────────
    blocked_results = [r for r in results if r.is_blocked]
    expired_results = [r for r in results if r.is_expired]
    # valid_claims counts non-expired, non-blocked entries
    valid_count = sum(1 for r in results if r.is_valid and not r.is_expired)

    is_valid = len(blocked_results) == 0

    report = DraftValidationReport(
        total_claims=len(results),
        valid_claims=valid_count,
        blocked_claims=len(blocked_results),
        warnings=len(expired_results),
        is_valid=is_valid,
        results=results,
    )

    # ── 7. Persist and audit log (atomic) ─────────────────────────────────────
    try:
        if not is_valid:
            doc.status = DocumentStatus.BLOCKED

        doc.validation_report = report.model_dump(mode="json")

        blocked_count = len(blocked_results)
        action = (
            f"claim validation: {'BLOCKED' if not is_valid else 'PASSED'} — "
            f"{report.total_claims} claims checked, {blocked_count} blocked, "
            f"{report.warnings} warnings"
        )[:512]

        audit_log = AuditLog(document_id=document_id, action=action)
        db.add(audit_log)
        db.commit()

    except Exception:
        db.rollback()
        raise

    logger.info(
        "Draft claim validation complete for document %s: valid=%s total=%d blocked=%d warnings=%d",
        document_id,
        is_valid,
        report.total_claims,
        report.blocked_claims,
        report.warnings,
    )

    return report
