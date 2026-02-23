class NotFoundError(Exception):
    """Raised when a requested resource does not exist."""


# ── Ticket 2.1 — Document Upload ─────────────────────────────────────────────

class DuplicateFileError(Exception):
    """Raised when a file with the same SHA-256 hash already exists in the system."""


class InvalidFileTypeError(Exception):
    """Raised when an uploaded file has an unsupported extension or MIME type."""


# ── Ticket 2.2 — Fact Sheet Extraction ───────────────────────────────────────

class ExtractionError(Exception):
    """Raised when LLM extraction fails or the result fails schema validation."""


# ── Ticket 2.4 — Registry Sync Enforcement ───────────────────────────────────

class RegistryNotInitializedError(Exception):
    """
    Raised when claim_registry has zero rows.

    Distinct from RegistryStaleError: the registry has never been seeded at all.
    Callers should return HTTP 503 with code="registry_not_initialized" and
    instruct operators to run POST /api/v1/registry/sync.
    """


class RegistryStaleError(Exception):
    """Raised when claim_registry data is older than the configured staleness threshold."""


# ── EPIC 3 — Draft Generation ─────────────────────────────────────────────────

class NoFactSheetError(Exception):
    """Raised when a document has no associated fact sheet."""


# ── EPIC 4 — QA + Iteration ───────────────────────────────────────────────────

class MaxIterationsReachedError(Exception):
    """Raised when the QA iteration limit is reached without the draft passing."""


class InvalidRubricScoreError(Exception):
    """Raised when the LLM returns rubric scores that are missing, out-of-range, or malformed."""


class LLMInvalidJSONError(Exception):
    """Raised when the LLM returns a response that cannot be parsed as valid JSON."""


# ── EPIC 5 — Claim Extraction & Registry Validation ───────────────────────────

class UnsupportedClaimError(Exception):
    """
    Raised when a claim extracted from a draft has no matching entry in the
    ClaimRegistry and therefore blocks document progression.
    """


# ── EPIC 6 — Governance Gate ───────────────────────────────────────────────

class DocumentNotReadyError(Exception):
    """
    Raised when a document is missing prerequisites for the governance check.
    Prerequisites: at least one DraftVersion with a non-NULL score, and a
    non-NULL validation_report on the Document.
    """


# ── EPIC 7 — Human Review & Approval ───────────────────────────────────────

class InvalidReviewStatusError(Exception):
    """
    Raised when a review action (approve/reject) is attempted on a document
    that is not in the required status (e.g., not in HUMAN_REVIEW).
    Maps to HTTP 422.
    """


class MissingOverrideReasonError(Exception):
    """
    Raised when force_approve=True is requested but override_reason is
    absent or empty. An override_reason is mandatory for audit trail compliance.
    Maps to HTTP 422.
    """
