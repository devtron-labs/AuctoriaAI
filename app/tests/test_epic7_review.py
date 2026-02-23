"""
EPIC 7 — Human Review & Approval Tests.

Coverage (33 tests):

  Pending Reviews Tests (5 tests):
    - List documents in HUMAN_REVIEW status
    - Pagination works correctly
    - Excludes documents in other statuses
    - Includes score and validation summary
    - Empty list when no pending reviews

  Review Details Tests (5 tests):
    - Returns complete document context
    - Includes all draft versions
    - Includes validation report
    - Includes fact sheet
    - Includes audit log

  Approve Tests (10 tests):
    - Normal approval from HUMAN_REVIEW → APPROVED
    - Status persisted in database
    - Reviewer name and timestamp recorded
    - Audit log created with details
    - Optional notes included in audit
    - Cannot approve from DRAFT without force
    - Cannot approve from BLOCKED without force
    - Force approve from BLOCKED works with reason
    - Force approve requires override_reason
    - Force approve flag recorded in database

  Reject Tests (8 tests):
    - Reject from HUMAN_REVIEW → BLOCKED
    - Status persisted in database
    - Rejection reason in audit log
    - Suggested action included if provided
    - Cannot reject from DRAFT
    - Cannot reject from APPROVED
    - Cannot reject already BLOCKED document
    - Descriptive error messages

  Edge Cases (5 tests):
    - Document not found raises NotFoundError
    - Empty reviewer_name is rejected by Pydantic
    - Empty rejection_reason is rejected by Pydantic
    - Transaction rollback on commit error
    - Force approve works from any status (VALIDATING)

All tests use the SQLite in-memory fixture from conftest.py.
No LLM calls are made.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion, FactSheet
from app.schemas.schemas import ApproveDocumentRequest, RejectDocumentRequest
from app.services.exceptions import (
    InvalidReviewStatusError,
    MissingOverrideReasonError,
    NotFoundError,
)
from app.services.review_service import (
    approve_document,
    get_pending_reviews,
    get_review_details,
    reject_document,
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


def _make_doc(
    db,
    status: DocumentStatus = DocumentStatus.HUMAN_REVIEW,
    title: str = "Test Document",
    validation_report: dict | None = None,
) -> Document:
    doc = Document(title=title, status=status, validation_report=validation_report)
    db.add(doc)
    db.flush()
    return doc


def _make_draft(
    db,
    doc_id: str,
    score: float | None = 9.5,
    iteration: int = 1,
    content: str = "# Draft\n\nContent here.",
) -> DraftVersion:
    draft = DraftVersion(
        document_id=doc_id,
        content_markdown=content,
        iteration_number=iteration,
        tone="formal",
        score=score,
        feedback_text="Good draft." if score else None,
    )
    db.add(draft)
    db.flush()
    return draft


def _make_fact_sheet(db, doc_id: str) -> FactSheet:
    fs = FactSheet(
        document_id=doc_id,
        structured_data={
            "features": [{"name": "Auth", "description": "SSO support"}],
            "integrations": [],
            "compliance": [],
            "performance_metrics": [],
            "limitations": [],
        },
    )
    db.add(fs)
    db.flush()
    return fs


def _make_audit_log(db, doc_id: str, action: str) -> AuditLog:
    entry = AuditLog(document_id=doc_id, action=action)
    db.add(entry)
    db.flush()
    return entry


# ===========================================================================
# Pending Reviews Tests (5 tests)
# ===========================================================================


class TestGetPendingReviews:
    def test_lists_documents_in_human_review_status(self, db):
        doc1 = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW, title="Doc A")
        doc2 = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW, title="Doc B")
        db.commit()

        result = get_pending_reviews(db)

        assert result.total == 2
        ids = {item.id for item in result.documents}
        assert doc1.id in ids
        assert doc2.id in ids

    def test_pagination_works_correctly(self, db):
        for i in range(5):
            _make_doc(db, title=f"Doc {i}")
        db.commit()

        page1 = get_pending_reviews(db, page=1, page_size=2)
        page2 = get_pending_reviews(db, page=2, page_size=2)
        page3 = get_pending_reviews(db, page=3, page_size=2)

        assert page1.total == 5
        assert page1.page == 1
        assert page1.page_size == 2
        assert len(page1.documents) == 2
        assert len(page2.documents) == 2
        assert len(page3.documents) == 1

        # No overlap between pages
        page1_ids = {d.id for d in page1.documents}
        page2_ids = {d.id for d in page2.documents}
        assert page1_ids.isdisjoint(page2_ids)

    def test_excludes_documents_in_other_statuses(self, db):
        _make_doc(db, status=DocumentStatus.HUMAN_REVIEW, title="In Review")
        _make_doc(db, status=DocumentStatus.DRAFT, title="Draft")
        _make_doc(db, status=DocumentStatus.APPROVED, title="Approved")
        _make_doc(db, status=DocumentStatus.BLOCKED, title="Blocked")
        _make_doc(db, status=DocumentStatus.VALIDATING, title="Validating")
        db.commit()

        result = get_pending_reviews(db)

        assert result.total == 1
        assert result.documents[0].title == "In Review"

    def test_includes_score_and_validation_summary(self, db):
        doc = _make_doc(db, validation_report=_FAILING_REPORT)
        _make_draft(db, doc.id, score=8.7, iteration=1)
        db.commit()

        result = get_pending_reviews(db)

        assert result.total == 1
        item = result.documents[0]
        assert item.score == 8.7
        assert item.claims_valid is False
        assert item.total_issues == 2  # blocked_claims from _FAILING_REPORT
        assert item.draft_preview is not None

    def test_empty_list_when_no_pending_reviews(self, db):
        _make_doc(db, status=DocumentStatus.APPROVED)
        _make_doc(db, status=DocumentStatus.DRAFT)
        db.commit()

        result = get_pending_reviews(db)

        assert result.total == 0
        assert result.documents == []
        assert result.page == 1


# ===========================================================================
# Review Details Tests (5 tests)
# ===========================================================================


class TestGetReviewDetails:
    def test_returns_complete_document_context(self, db):
        doc = _make_doc(db, validation_report=_PASSING_REPORT)
        db.commit()

        result = get_review_details(db, doc.id)

        assert result.document.id == doc.id
        assert result.document.title == doc.title
        assert result.document.status == DocumentStatus.HUMAN_REVIEW

    def test_includes_all_draft_versions(self, db):
        doc = _make_doc(db)
        _make_draft(db, doc.id, score=7.0, iteration=1, content="# Draft 1\n\nOld.")
        _make_draft(db, doc.id, score=8.5, iteration=2, content="# Draft 2\n\nBetter.")
        _make_draft(db, doc.id, score=9.2, iteration=3, content="# Draft 3\n\nBest.")
        db.commit()

        result = get_review_details(db, doc.id)

        assert len(result.all_drafts) == 3
        assert result.all_drafts[0].iteration_number == 1
        assert result.all_drafts[2].iteration_number == 3
        # latest_draft should be iteration 3
        assert result.latest_draft is not None
        assert result.latest_draft.iteration_number == 3
        assert result.latest_draft.score == 9.2

    def test_includes_validation_report(self, db):
        doc = _make_doc(db, validation_report=_PASSING_REPORT)
        db.commit()

        result = get_review_details(db, doc.id)

        assert result.validation_report is not None
        assert result.validation_report["is_valid"] is True
        assert result.validation_report["total_claims"] == 5

    def test_includes_fact_sheet(self, db):
        doc = _make_doc(db)
        _make_fact_sheet(db, doc.id)
        db.commit()

        result = get_review_details(db, doc.id)

        assert result.fact_sheet is not None
        assert result.fact_sheet.document_id == doc.id
        assert "features" in result.fact_sheet.structured_data

    def test_includes_audit_log(self, db):
        doc = _make_doc(db)
        _make_audit_log(db, doc.id, "governance check: PASSED → status=HUMAN_REVIEW")
        _make_audit_log(db, doc.id, "draft generated")
        db.commit()

        result = get_review_details(db, doc.id)

        assert len(result.audit_log) == 2
        # Newest first
        assert "HUMAN_REVIEW" in result.audit_log[0].action or "draft" in result.audit_log[0].action


# ===========================================================================
# Approve Tests (10 tests)
# ===========================================================================


class TestApproveDocument:
    def test_normal_approval_from_human_review_to_approved(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        result = approve_document(db, doc.id, reviewer_name="Alice")

        assert result.status == DocumentStatus.APPROVED
        assert result.reviewed_by == "Alice"
        assert result.force_approved is False
        assert result.message == "Document approved successfully"

    def test_status_persisted_in_database(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        approve_document(db, doc.id, reviewer_name="Alice")
        db.refresh(doc)

        assert doc.status == DocumentStatus.APPROVED

    def test_reviewer_name_and_timestamp_recorded(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        result = approve_document(db, doc.id, reviewer_name="Bob Smith")
        db.refresh(doc)

        assert doc.reviewed_by == "Bob Smith"
        assert doc.reviewed_at is not None
        # reviewed_at in response matches what was persisted
        assert result.reviewed_at is not None
        assert result.reviewed_by == "Bob Smith"

    def test_audit_log_created_with_details(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        approve_document(db, doc.id, reviewer_name="Carol")

        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 1
        assert "approved" in logs[0].action.lower()
        assert "Carol" in logs[0].action

    def test_optional_notes_included_in_audit(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        approve_document(db, doc.id, reviewer_name="Dave", notes="Looks great!")

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "Looks great!" in log.action

    def test_cannot_approve_from_draft_without_force(self, db):
        doc = _make_doc(db, status=DocumentStatus.DRAFT)
        db.commit()

        with pytest.raises(InvalidReviewStatusError) as exc_info:
            approve_document(db, doc.id, reviewer_name="Eve")

        assert "DRAFT" in str(exc_info.value)
        assert "HUMAN_REVIEW" in str(exc_info.value)

    def test_cannot_approve_from_blocked_without_force(self, db):
        doc = _make_doc(db, status=DocumentStatus.BLOCKED)
        db.commit()

        with pytest.raises(InvalidReviewStatusError) as exc_info:
            approve_document(db, doc.id, reviewer_name="Eve")

        assert "BLOCKED" in str(exc_info.value)

    def test_force_approve_from_blocked_works_with_reason(self, db):
        doc = _make_doc(db, status=DocumentStatus.BLOCKED)
        db.commit()

        result = approve_document(
            db,
            doc.id,
            reviewer_name="Admin",
            force_approve=True,
            override_reason="Exempted by CTO for launch deadline",
        )

        assert result.status == DocumentStatus.APPROVED
        assert result.force_approved is True

        db.refresh(doc)
        assert doc.status == DocumentStatus.APPROVED
        assert doc.force_approved is True

    def test_force_approve_requires_override_reason(self, db):
        doc = _make_doc(db, status=DocumentStatus.BLOCKED)
        db.commit()

        with pytest.raises(MissingOverrideReasonError):
            approve_document(
                db,
                doc.id,
                reviewer_name="Admin",
                force_approve=True,
                override_reason=None,
            )

    def test_force_approve_flag_recorded_in_database(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        approve_document(
            db,
            doc.id,
            reviewer_name="Admin",
            force_approve=True,
            override_reason="Manual override",
        )
        db.refresh(doc)

        assert doc.force_approved is True
        # Audit log should mention FORCE APPROVED
        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "FORCE APPROVED" in log.action


# ===========================================================================
# Reject Tests (8 tests)
# ===========================================================================


class TestRejectDocument:
    def test_reject_from_human_review_to_blocked(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        result = reject_document(
            db,
            doc.id,
            reviewer_name="Frank",
            rejection_reason="Claims need additional evidence",
        )

        assert result.status == DocumentStatus.BLOCKED
        assert result.rejection_reason == "Claims need additional evidence"
        assert result.message == "Document rejected and returned for revision"

    def test_status_persisted_in_database(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        reject_document(db, doc.id, reviewer_name="Frank", rejection_reason="Fails audit")
        db.refresh(doc)

        assert doc.status == DocumentStatus.BLOCKED

    def test_rejection_reason_in_audit_log(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        reject_document(
            db,
            doc.id,
            reviewer_name="Grace",
            rejection_reason="SOC 2 claim unverified",
        )

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "rejected" in log.action.lower()
        assert "Grace" in log.action
        assert "SOC 2 claim unverified" in log.action

    def test_suggested_action_included_if_provided(self, db):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        result = reject_document(
            db,
            doc.id,
            reviewer_name="Hank",
            rejection_reason="Missing references",
            suggested_action="Add citations for all performance claims",
        )

        assert result.suggested_action == "Add citations for all performance claims"
        # Also appears in the audit log
        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "Add citations" in log.action

    def test_cannot_reject_from_draft(self, db):
        doc = _make_doc(db, status=DocumentStatus.DRAFT)
        db.commit()

        with pytest.raises(InvalidReviewStatusError) as exc_info:
            reject_document(db, doc.id, reviewer_name="Ivy", rejection_reason="Bad")

        assert "DRAFT" in str(exc_info.value)

    def test_cannot_reject_from_approved(self, db):
        doc = _make_doc(db, status=DocumentStatus.APPROVED)
        db.commit()

        with pytest.raises(InvalidReviewStatusError) as exc_info:
            reject_document(db, doc.id, reviewer_name="Ivy", rejection_reason="Bad")

        assert "APPROVED" in str(exc_info.value)

    def test_cannot_reject_already_blocked_document(self, db):
        doc = _make_doc(db, status=DocumentStatus.BLOCKED)
        db.commit()

        with pytest.raises(InvalidReviewStatusError) as exc_info:
            reject_document(db, doc.id, reviewer_name="Ivy", rejection_reason="Bad")

        assert "BLOCKED" in str(exc_info.value)

    def test_descriptive_error_message_names_current_status(self, db):
        for bad_status in (
            DocumentStatus.DRAFT,
            DocumentStatus.VALIDATING,
            DocumentStatus.PASSED,
            DocumentStatus.APPROVED,
            DocumentStatus.BLOCKED,
        ):
            doc = _make_doc(db, status=bad_status)
            db.flush()

            with pytest.raises(InvalidReviewStatusError) as exc_info:
                reject_document(
                    db, doc.id, reviewer_name="Reviewer", rejection_reason="reason"
                )

            # The error message must name the actual current status
            assert bad_status.value in str(exc_info.value)
            assert len(str(exc_info.value)) > 20  # not a bare/empty message


# ===========================================================================
# Edge Cases (5 tests)
# ===========================================================================


class TestEdgeCases:
    def test_document_not_found_raises_not_found_error(self, db):
        missing_id = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(NotFoundError, match="not found"):
            approve_document(db, missing_id, reviewer_name="Alice")

        with pytest.raises(NotFoundError, match="not found"):
            reject_document(db, missing_id, reviewer_name="Alice", rejection_reason="x")

        with pytest.raises(NotFoundError, match="not found"):
            get_review_details(db, missing_id)

    def test_empty_reviewer_name_is_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            ApproveDocumentRequest(reviewer_name="")

        with pytest.raises(ValidationError):
            RejectDocumentRequest(reviewer_name="", rejection_reason="valid reason")

    def test_empty_rejection_reason_is_rejected_by_pydantic(self):
        with pytest.raises(ValidationError):
            RejectDocumentRequest(reviewer_name="Alice", rejection_reason="")

    def test_transaction_rollback_on_commit_error(self, db, monkeypatch):
        doc = _make_doc(db, status=DocumentStatus.HUMAN_REVIEW)
        db.commit()

        original_status = doc.status
        original_commit = db.commit

        def _fail_commit():
            raise RuntimeError("simulated DB commit failure")

        monkeypatch.setattr(db, "commit", _fail_commit)

        with pytest.raises(RuntimeError, match="simulated DB commit failure"):
            approve_document(db, doc.id, reviewer_name="Alice")

        # Restore commit so we can query
        monkeypatch.setattr(db, "commit", original_commit)
        db.rollback()

        db.refresh(doc)
        # Status must be unchanged after rollback
        assert doc.status == original_status
        # No audit log should have been persisted
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 0

    def test_force_approve_works_from_validating_status(self, db):
        doc = _make_doc(db, status=DocumentStatus.VALIDATING)
        db.commit()

        result = approve_document(
            db,
            doc.id,
            reviewer_name="Admin",
            force_approve=True,
            override_reason="Emergency bypass: pipeline failure, manual review complete",
        )

        assert result.status == DocumentStatus.APPROVED
        assert result.force_approved is True

        db.refresh(doc)
        assert doc.status == DocumentStatus.APPROVED

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "FORCE APPROVED" in log.action
        # Previous status captured in audit
        assert "VALIDATING" in log.action
