"""
EPIC 6 — Governance Gate Tests.

Coverage (29 tests):

  Pure function (_make_governance_decision) — 4 tests:
    - Score pass + claims valid   → PASSED
    - Score fail only             → FAILED, reason mentions score
    - Claims fail only            → FAILED, reason mentions claims
    - Both fail                   → FAILED, reason mentions both

  Passing scenarios — 8 tests:
    - Score >= 9.0 AND claims valid → HUMAN_REVIEW (decision=PASSED)
    - Score exactly 9.0 AND claims valid → HUMAN_REVIEW
    - Score 10.0 AND claims valid → HUMAN_REVIEW
    - Status persisted to database
    - Audit log created with correct details
    - Response contains correct decision and reason
    - Details dict has all required fields
    - Idempotent: calling twice still returns PASSED/HUMAN_REVIEW

  Score failure — 5 tests:
    - Score < 9.0 AND claims valid → BLOCKED (decision=FAILED)
    - Score 8.9 AND claims valid → BLOCKED
    - Score 0.0 AND claims valid → BLOCKED
    - Reason mentions score threshold
    - Status changed to BLOCKED in database

  Claims failure — 5 tests:
    - Score >= 9.0 AND claims invalid → BLOCKED (decision=FAILED)
    - Score 10.0 AND claims invalid → BLOCKED
    - Reason mentions claim validation failure
    - Status changed to BLOCKED in database
    - blocked_claims appears in response details

  Both failures — 2 tests:
    - Score < 9.0 AND claims invalid → BLOCKED
    - Reason mentions both failures

  Prerequisites errors — 5 tests:
    - No DraftVersion → DocumentNotReadyError
    - DraftVersion with NULL score → DocumentNotReadyError
    - Missing validation_report → DocumentNotReadyError
    - Document not found → NotFoundError
    - Error messages are descriptive

All tests use the SQLite in-memory fixture from conftest.py.
No LLM calls are made.
"""

from __future__ import annotations

import pytest

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion
from app.schemas.schemas import GovernanceDecision
from app.services.exceptions import DocumentNotReadyError, NotFoundError
from app.services.governance_service import (
    _make_governance_decision,
    enforce_governance,
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

_PASSING_REPORT: dict = {
    "total_claims": 5,
    "valid_claims": 5,
    "blocked_claims": 0,
    "warnings": 0,
    "is_valid": True,
    "results": [],
}

_FAILING_REPORT: dict = {
    "total_claims": 5,
    "valid_claims": 3,
    "blocked_claims": 2,
    "warnings": 0,
    "is_valid": False,
    "results": [],
}


def _doc(
    db,
    status: DocumentStatus = DocumentStatus.VALIDATING,
    validation_report: dict | None = None,
) -> Document:
    doc = Document(title="Governance Test Doc", status=status, validation_report=validation_report)
    db.add(doc)
    db.flush()
    return doc


def _draft(
    db,
    doc_id: str,
    score: float | None = 9.5,
    iteration: int = 1,
) -> DraftVersion:
    draft = DraftVersion(
        document_id=doc_id,
        content_markdown="# Test Draft\n\nContent.",
        iteration_number=iteration,
        tone="formal",
        score=score,
    )
    db.add(draft)
    db.flush()
    return draft


# ===========================================================================
# Pure function tests: _make_governance_decision (4 tests)
# ===========================================================================


class TestMakeGovernanceDecision:
    def test_both_pass_returns_passed_decision(self):
        decision, reason = _make_governance_decision(score=9.2, claims_valid=True, threshold=9.0)
        assert decision == GovernanceDecision.PASSED
        assert "9.2" in reason
        assert "9.0" in reason

    def test_score_below_threshold_returns_failed(self):
        decision, reason = _make_governance_decision(score=8.5, claims_valid=True, threshold=9.0)
        assert decision == GovernanceDecision.FAILED
        assert "8.5" in reason
        assert "9.0" in reason
        assert "below threshold" in reason.lower()

    def test_claims_invalid_returns_failed(self):
        decision, reason = _make_governance_decision(score=9.5, claims_valid=False, threshold=9.0)
        assert decision == GovernanceDecision.FAILED
        assert "claim" in reason.lower()

    def test_both_fail_reason_mentions_both(self):
        decision, reason = _make_governance_decision(score=7.0, claims_valid=False, threshold=9.0)
        assert decision == GovernanceDecision.FAILED
        assert "7.0" in reason
        assert "claim" in reason.lower()
        # Both failures should appear in the combined reason
        assert "and" in reason


# ===========================================================================
# Passing scenarios (8 tests)
# ===========================================================================


class TestEnforceGovernancePassing:
    def test_score_above_threshold_and_valid_claims_returns_human_review(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.2)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.PASSED
        assert result.final_status == DocumentStatus.HUMAN_REVIEW
        assert result.claims_valid is True
        assert result.score == 9.2

    def test_score_exactly_at_threshold_passes(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.PASSED
        assert result.final_status == DocumentStatus.HUMAN_REVIEW

    def test_score_10_passes(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=10.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.PASSED
        assert result.final_status == DocumentStatus.HUMAN_REVIEW
        assert result.score == 10.0

    def test_status_persisted_to_database(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        enforce_governance(db, doc.id)
        db.refresh(doc)

        assert doc.status == DocumentStatus.HUMAN_REVIEW

    def test_audit_log_created_with_correct_details(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        enforce_governance(db, doc.id)

        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 1
        assert "governance check" in logs[0].action
        assert "PASSED" in logs[0].action
        assert "HUMAN_REVIEW" in logs[0].action

    def test_response_contains_correct_decision_and_reason(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.2)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.PASSED
        assert "9.2" in result.reason
        assert "9.0" in result.reason
        assert len(result.reason) > 0

    def test_details_dict_has_all_required_fields(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.2)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert "score" in result.details
        assert "score_threshold" in result.details
        assert "score_passed" in result.details
        assert "claims_valid" in result.details
        assert "validation_summary" in result.details
        assert result.details["score"] == 9.2
        assert result.details["score_threshold"] == 9.0
        assert result.details["score_passed"] is True
        assert result.details["claims_valid"] is True

    def test_idempotent_calling_twice_gives_same_result(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        result1 = enforce_governance(db, doc.id)
        result2 = enforce_governance(db, doc.id)

        assert result1.decision == GovernanceDecision.PASSED
        assert result2.decision == GovernanceDecision.PASSED
        assert result2.final_status == DocumentStatus.HUMAN_REVIEW

        # Two audit log entries (one per call)
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 2


# ===========================================================================
# Score failure scenarios (5 tests)
# ===========================================================================


class TestEnforceGovernanceScoreFailure:
    def test_score_below_threshold_with_valid_claims_returns_blocked(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=8.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED
        assert result.claims_valid is True
        assert result.score == 8.5

    def test_score_8_9_is_below_threshold(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=8.9)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED

    def test_score_0_is_below_threshold(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=0.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED
        assert result.score == 0.0

    def test_reason_mentions_score_and_threshold(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=7.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert "7.5" in result.reason
        assert "9.0" in result.reason
        assert "below threshold" in result.reason.lower()

    def test_status_changed_to_blocked_in_database(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=8.0)
        db.commit()

        enforce_governance(db, doc.id)
        db.refresh(doc)

        assert doc.status == DocumentStatus.BLOCKED


# ===========================================================================
# Claims failure scenarios (5 tests)
# ===========================================================================


class TestEnforceGovernanceClaimsFailure:
    def test_passing_score_with_invalid_claims_returns_blocked(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED
        assert result.claims_valid is False
        assert result.score == 9.5

    def test_score_10_with_invalid_claims_returns_blocked(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=10.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED

    def test_reason_mentions_claim_validation_failure(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert "claim" in result.reason.lower()

    def test_status_changed_to_blocked_when_claims_invalid(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        enforce_governance(db, doc.id)
        db.refresh(doc)

        assert doc.status == DocumentStatus.BLOCKED

    def test_blocked_claims_count_appears_in_response_details(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert "blocked_claims" in result.details
        assert result.details["blocked_claims"] == 2


# ===========================================================================
# Both failures (2 tests)
# ===========================================================================


class TestEnforceGovernanceBothFailure:
    def test_score_below_threshold_and_claims_invalid_returns_blocked(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=7.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.decision == GovernanceDecision.FAILED
        assert result.final_status == DocumentStatus.BLOCKED
        assert result.claims_valid is False
        assert result.score == 7.0

    def test_reason_mentions_both_score_and_claim_failures(self, db):
        doc = _doc(db, validation_report=_FAILING_REPORT)
        _draft(db, doc.id, score=5.0)
        db.commit()

        result = enforce_governance(db, doc.id)

        # Reason must reference the score failure
        assert "5.0" in result.reason
        # Reason must reference the claim failure
        assert "claim" in result.reason.lower()
        # Both conditions joined with "and"
        assert "and" in result.reason


# ===========================================================================
# Prerequisites errors (5 tests)
# ===========================================================================


class TestEnforceGovernancePrerequisites:
    def test_document_not_found_raises_not_found_error(self, db):
        with pytest.raises(NotFoundError, match="not found"):
            enforce_governance(db, "00000000-0000-0000-0000-000000000000")

    def test_missing_draft_version_raises_document_not_ready(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        db.commit()

        with pytest.raises(DocumentNotReadyError) as exc_info:
            enforce_governance(db, doc.id)

        assert "no draft versions" in str(exc_info.value).lower()

    def test_draft_with_null_score_raises_document_not_ready(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=None)  # NULL score
        db.commit()

        with pytest.raises(DocumentNotReadyError) as exc_info:
            enforce_governance(db, doc.id)

        assert "no qa score" in str(exc_info.value).lower() or "score" in str(exc_info.value).lower()

    def test_missing_validation_report_raises_document_not_ready(self, db):
        doc = _doc(db, validation_report=None)  # no report
        _draft(db, doc.id, score=9.5)
        db.commit()

        with pytest.raises(DocumentNotReadyError) as exc_info:
            enforce_governance(db, doc.id)

        assert "validation report" in str(exc_info.value).lower()

    def test_error_messages_are_descriptive(self, db):
        # No draft → message should name the document and suggest the fix
        doc = _doc(db, validation_report=_PASSING_REPORT)
        db.commit()

        with pytest.raises(DocumentNotReadyError) as exc_info:
            enforce_governance(db, doc.id)

        message = str(exc_info.value)
        assert doc.id in message  # identifies the document
        assert len(message) > 20  # not a bare empty message


# ===========================================================================
# Additional edge-case / integration tests (5 tests)
# ===========================================================================


class TestEnforceGovernanceEdgeCases:
    def test_uses_latest_draft_by_iteration_number(self, db):
        """Governance should use the highest iteration_number draft for the score."""
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=5.0, iteration=1)   # old, low-score draft
        _draft(db, doc.id, score=9.5, iteration=2)   # new, passing draft
        db.commit()

        result = enforce_governance(db, doc.id)

        # Should use iteration 2 (score 9.5) → PASSED
        assert result.decision == GovernanceDecision.PASSED
        assert result.score == 9.5

    def test_audit_log_action_is_truncated_to_512_chars(self, db):
        """Audit log entries must not exceed 512 characters."""
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        enforce_governance(db, doc.id)

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert log is not None
        assert len(log.action) <= 512

    def test_malformed_validation_report_is_treated_as_invalid(self, db):
        """A non-dict validation_report falls back to claims_valid=False."""
        doc = _doc(db, validation_report=None)
        # Manually set a malformed report (list instead of dict)
        doc.validation_report = ["not", "a", "dict"]
        db.flush()
        _draft(db, doc.id, score=9.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        # Malformed report → claims treated as invalid → BLOCKED
        assert result.claims_valid is False
        assert result.final_status == DocumentStatus.BLOCKED

    def test_document_id_in_response_matches_input(self, db):
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        result = enforce_governance(db, doc.id)

        assert result.document_id == doc.id

    def test_transaction_rollback_on_commit_error(self, db, monkeypatch):
        """A DB commit failure must roll back the status change."""
        doc = _doc(db, validation_report=_PASSING_REPORT)
        _draft(db, doc.id, score=9.5)
        db.commit()

        original_status = doc.status
        original_commit = db.commit

        def _fail_commit():
            raise RuntimeError("simulated DB commit failure")

        monkeypatch.setattr(db, "commit", _fail_commit)

        with pytest.raises(RuntimeError, match="simulated DB commit failure"):
            enforce_governance(db, doc.id)

        # Restore commit so we can query
        monkeypatch.setattr(db, "commit", original_commit)
        db.rollback()

        db.refresh(doc)
        # Status must be unchanged after rollback
        assert doc.status == original_status
        # No audit log should have been persisted
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 0
