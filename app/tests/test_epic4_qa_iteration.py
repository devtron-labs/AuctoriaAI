"""
Unit tests for EPIC 4 — Rubric QA + Iteration Controller.

Covers:
  - Passing draft (score >= 9.0):
      * Status transitions to PASSED
      * No additional iterations attempted
      * Audit log created per iteration
      * Returns correct iterations_completed and final_score
  - Improvement loop:
      * Score < 9.0 triggers a new DraftVersion
      * iteration_number increments correctly
      * feedback_text stored on draft after evaluation
      * Second iteration can pass (returns PASSED)
      * Score is persisted on the evaluated draft
  - Max iterations reached (default 3 and custom):
      * Status transitions to BLOCKED
      * MaxIterationsReachedError is raised
      * No extra iteration is attempted beyond the limit
      * Custom max_iterations (5) is respected
      * max_iterations=1 blocks immediately on failure
  - Missing draft → NotFoundError (404)
  - Missing FactSheet → NoFactSheetError
  - Missing Document → NotFoundError
  - Transaction rollback:
      * On LLM evaluate error: no score, no audit log, status unchanged
      * On LLM improve error: score/feedback_text rolled back, no audit log
      * On DB commit error: exception propagates
  - Audit logs:
      * One log per QA iteration
      * Log action contains iteration number and score
  - evaluate_draft helper:
      * Updates draft.score and draft.feedback_text in-memory
      * Raises NotFoundError for unknown draft_id
      * Raises InvalidRubricScoreError on malformed LLM output
  - improve_draft helper:
      * Creates new DraftVersion with iteration_number + 1
      * Raises NotFoundError for unknown draft_id
  - max_iterations validation:
      * ValueError raised when max_iterations < 1

Tests use SQLite in-memory via the `db` fixture from conftest.py.
All LLM calls are mocked — no real API calls are made.
"""

import uuid
from unittest.mock import MagicMock, patch

import pytest

from app.models.models import (
    AuditLog,
    Document,
    DocumentStatus,
    DraftVersion,
    FactSheet,
)
from app.services import qa_iteration_service
from app.services.exceptions import (
    InvalidRubricScoreError,
    MaxIterationsReachedError,
    NotFoundError,
)

# ---------------------------------------------------------------------------
# Auto-pipeline fixture — disable claim validation + governance for QA tests
# ---------------------------------------------------------------------------

def _auto_pipeline_disabled(*args, **kwargs):
    """Raises so the auto-pipeline's try/except catches it and leaves doc at PASSED."""
    raise RuntimeError("auto-pipeline disabled in QA unit test")


@pytest.fixture(autouse=True)
def _disable_auto_pipeline(monkeypatch):
    """Prevent the auto-pipeline (claim validation + governance) from running.

    evaluate_and_iterate automatically triggers claim validation and governance
    after QA passes. These tests validate QA logic only; the downstream pipeline
    is tested in test_epic5_claim_validation.py and test_epic6_governance.py.
    Making claim validation raise keeps documents at PASSED status so QA
    assertions remain clean and unambiguous.
    """
    import app.services.claim_validation_service as _cvc
    monkeypatch.setattr(_cvc, "validate_draft_claims", _auto_pipeline_disabled)


# ---------------------------------------------------------------------------
# Mock score payloads
# ---------------------------------------------------------------------------

_PASSING_SCORES = {
    "factual_correctness": 9.5,
    "technical_depth": 9.2,
    "clarity": 9.8,
    "composite_score": 9.5,
    "improvement_suggestions": ["Excellent draft. All rubric criteria met."],
}

_FAILING_SCORES = {
    "factual_correctness": 7.0,
    "technical_depth": 6.5,
    "clarity": 8.0,
    "composite_score": 7.17,
    "improvement_suggestions": [
        "Needs more technical depth and specific metrics.",
        "Add concrete performance benchmarks with exact values.",
    ],
}

_BORDERLINE_SCORES = {
    "factual_correctness": 9.0,
    "technical_depth": 9.0,
    "clarity": 9.0,
    "composite_score": 9.0,  # exactly at threshold — should PASS (>=)
    "improvement_suggestions": ["Meets the minimum threshold."],
}

_MOCK_IMPROVED_CONTENT = (
    "# Introduction\n\nImproved draft.\n\n"
    "# Conclusion\n\nImproved conclusion."
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_document(
    db,
    status: DocumentStatus = DocumentStatus.DRAFT,
    title: str = "Test Doc",
) -> Document:
    doc = Document(title=title, status=status)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _make_fact_sheet(db, document_id: str, data: dict | None = None) -> FactSheet:
    structured_data = data or {
        "features": [{"name": "Fast Search", "description": "Sub-second query latency"}],
        "integrations": [{"system": "Slack", "method": "Webhook", "notes": "Real-time alerts"}],
        "compliance": [{"standard": "SOC 2 Type II", "status": "Certified", "details": "Annual audit"}],
        "performance_metrics": [{"metric": "Throughput", "value": "10000", "unit": "req/s"}],
        "limitations": [{"category": "Storage", "description": "Max 1TB per tenant"}],
    }
    fs = FactSheet(document_id=document_id, structured_data=structured_data)
    db.add(fs)
    db.commit()
    db.refresh(fs)
    return fs


def _make_draft(
    db,
    document_id: str,
    iteration: int = 1,
    content: str = "# Introduction\n\nInitial draft content.",
    score: float | None = None,
    feedback_text: str | None = None,
    tone: str = "formal",
) -> DraftVersion:
    draft = DraftVersion(
        document_id=document_id,
        iteration_number=iteration,
        content_markdown=content,
        tone=tone,
        score=score,
        feedback_text=feedback_text,
    )
    db.add(draft)
    db.commit()
    db.refresh(draft)
    return draft


def _patch_evaluate(scores: dict):
    """Return a context manager that mocks _call_llm_evaluate."""
    return patch.object(qa_iteration_service, "_call_llm_evaluate", return_value=scores)


def _patch_improve(content: str = _MOCK_IMPROVED_CONTENT):
    """Return a context manager that mocks _call_llm_improve."""
    return patch.object(qa_iteration_service, "_call_llm_improve", return_value=content)


# ---------------------------------------------------------------------------
# TestPassingDraft — score >= threshold on first attempt
# ---------------------------------------------------------------------------

class TestPassingDraft:
    def test_status_changes_to_passed(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(doc)
        assert doc.status == DocumentStatus.PASSED

    def test_returns_passed_status_in_result(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["final_status"] == DocumentStatus.PASSED

    def test_no_additional_iterations_after_pass(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert call_count["n"] == 1

    def test_improve_not_called_when_passing(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            with patch.object(
                qa_iteration_service, "_call_llm_improve"
            ) as mock_improve:
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        mock_improve.assert_not_called()

    def test_iterations_completed_is_one(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["iterations_completed"] == 1

    def test_final_score_matches_composite(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["final_score"] == _PASSING_SCORES["composite_score"]

    def test_final_draft_id_in_result(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        draft = _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["final_draft_id"] == draft.id

    def test_audit_log_created_on_pass(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .first()
        )
        assert log is not None

    def test_score_exactly_at_threshold_passes(self, db):
        """composite_score == qa_passing_threshold (9.0) should PASS (>= comparison)."""
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_BORDERLINE_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["final_status"] == DocumentStatus.PASSED


# ---------------------------------------------------------------------------
# TestImprovementLoop — score < threshold, multi-iteration path
# ---------------------------------------------------------------------------

class TestImprovementLoop:
    def test_failing_score_triggers_new_draft_version(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        drafts = (
            db.query(DraftVersion)
            .filter(DraftVersion.document_id == doc.id)
            .all()
        )
        assert len(drafts) == 2

    def test_iteration_number_increments(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        drafts = (
            db.query(DraftVersion)
            .filter(DraftVersion.document_id == doc.id)
            .order_by(DraftVersion.iteration_number)
            .all()
        )
        assert drafts[0].iteration_number == 1
        assert drafts[1].iteration_number == 2

    def test_feedback_stored_in_feedback_text(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        draft = _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(draft)
        assert draft.feedback_text == "\n".join(_FAILING_SCORES["improvement_suggestions"])

    def test_score_persisted_on_evaluated_draft(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        draft = _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(draft)
        assert draft.score == _FAILING_SCORES["composite_score"]

    def test_second_iteration_passes(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert result["final_status"] == DocumentStatus.PASSED
        assert result["iterations_completed"] == 2

    def test_improved_draft_content_comes_from_llm(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        custom_content = "# Introduction\n\nCustom improved content."
        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve(custom_content):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        improved = (
            db.query(DraftVersion)
            .filter(DraftVersion.document_id == doc.id)
            .order_by(DraftVersion.iteration_number.desc())
            .first()
        )
        assert improved.content_markdown == custom_content

    def test_iteration_history_contains_all_iterations(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 2 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert len(result["iteration_history"]) == 2
        assert result["iteration_history"][0]["passed"] is False
        assert result["iteration_history"][1]["passed"] is True


# ---------------------------------------------------------------------------
# TestMaxIterationsReached — default max (3) and custom
# ---------------------------------------------------------------------------

class TestMaxIterationsReached:
    def test_status_blocked_after_3_failures(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED

    def test_raises_max_iterations_reached_error(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

    def test_error_message_contains_document_id(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError) as exc_info:
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert doc.id in str(exc_info.value)

    def test_no_fourth_iteration_with_max_3(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate):
            with _patch_improve():
                with pytest.raises(MaxIterationsReachedError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert call_count["n"] == 3

    def test_improve_not_called_on_last_iteration(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        improve_count = {"n": 0}

        def counting_improve(prompt, *args, **kwargs):
            improve_count["n"] += 1
            return _MOCK_IMPROVED_CONTENT

        with _patch_evaluate(_FAILING_SCORES):
            with patch.object(qa_iteration_service, "_call_llm_improve", side_effect=counting_improve):
                with pytest.raises(MaxIterationsReachedError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        # 3 evaluations but only 2 improvements (no improve after last eval)
        assert improve_count["n"] == 2

    def test_three_audit_logs_created_for_max_3(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 3


# ---------------------------------------------------------------------------
# TestCustomMaxIterations
# ---------------------------------------------------------------------------

class TestCustomMaxIterations:
    def test_custom_max_5_blocks_after_5_iterations(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate):
            with _patch_improve():
                with pytest.raises(MaxIterationsReachedError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=5)

        assert call_count["n"] == 5

    def test_custom_max_5_creates_correct_number_of_drafts(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=5)

        # 1 original + 4 improvements (no improvement after 5th evaluation)
        count = db.query(DraftVersion).filter(DraftVersion.document_id == doc.id).count()
        assert count == 5

    def test_max_iterations_1_blocks_immediately_on_failure(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED

    def test_max_iterations_1_only_one_evaluation(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate):
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        assert call_count["n"] == 1

    def test_max_iterations_1_improve_never_called(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with patch.object(qa_iteration_service, "_call_llm_improve") as mock_improve:
                with pytest.raises(MaxIterationsReachedError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        mock_improve.assert_not_called()

    def test_max_iterations_1_passes_if_score_meets_threshold(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        assert result["final_status"] == DocumentStatus.PASSED

    def test_custom_max_overrides_config_default(self, db):
        """Passing max_iterations=2 uses 2, not the config default of 3."""
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate):
            with _patch_improve():
                with pytest.raises(MaxIterationsReachedError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=2)

        assert call_count["n"] == 2


# ---------------------------------------------------------------------------
# TestMissingDraft
# ---------------------------------------------------------------------------

class TestMissingDraft:
    def test_raises_not_found_when_no_drafts_exist(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with pytest.raises(NotFoundError):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

    def test_error_message_contains_document_id(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with pytest.raises(NotFoundError) as exc_info:
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        assert doc.id in str(exc_info.value)

    def test_no_audit_log_when_no_draft(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with pytest.raises(NotFoundError):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 0


# ---------------------------------------------------------------------------
# TestMissingFactSheet
# ---------------------------------------------------------------------------
# FactSheet is now optional for QA (supports prompt-first drafts with no fact
# sheet). When absent, evaluate_and_iterate proceeds with empty fact_sheet_data
# so the evaluator falls back to its training knowledge as ground truth.
# ---------------------------------------------------------------------------

class TestMissingFactSheet:
    def test_no_error_when_fact_sheet_missing(self, db):
        """evaluate_and_iterate must not raise any error when FactSheet is absent."""
        doc = _make_document(db)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        assert result["final_status"] == DocumentStatus.PASSED

    def test_passes_when_fact_sheet_missing_and_score_sufficient(self, db):
        """Missing FactSheet + passing score → document reaches PASSED status."""
        doc = _make_document(db)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(doc)
        assert doc.status == DocumentStatus.PASSED

    def test_blocked_when_fact_sheet_missing_and_score_insufficient(self, db):
        """Missing FactSheet + failing score within 1 iteration → BLOCKED."""
        doc = _make_document(db)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=1)

        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED


# ---------------------------------------------------------------------------
# TestMissingDocument
# ---------------------------------------------------------------------------

class TestMissingDocument:
    def test_raises_not_found_for_unknown_document(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError):
            qa_iteration_service.evaluate_and_iterate(db, fake_id, max_iterations=3)

    def test_error_message_contains_document_id(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError) as exc_info:
            qa_iteration_service.evaluate_and_iterate(db, fake_id, max_iterations=3)

        assert fake_id in str(exc_info.value)


# ---------------------------------------------------------------------------
# TestTransactionRollback
# ---------------------------------------------------------------------------

class TestTransactionRollback:
    def test_on_evaluate_llm_error_score_not_persisted(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        draft = _make_draft(db, doc.id)

        with patch.object(
            qa_iteration_service, "_call_llm_evaluate", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError, match="LLM timeout"):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(draft)
        assert draft.score is None
        assert draft.feedback_text is None

    def test_on_evaluate_llm_error_status_unchanged(self, db):
        doc = _make_document(db, status=DocumentStatus.DRAFT)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with patch.object(
            qa_iteration_service, "_call_llm_evaluate", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        db.refresh(doc)
        assert doc.status == DocumentStatus.DRAFT

    def test_on_evaluate_llm_error_no_audit_log(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with patch.object(
            qa_iteration_service, "_call_llm_evaluate", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 0

    def test_on_improve_llm_error_score_rolled_back(self, db):
        """Score update from evaluate_draft is rolled back when improve_draft LLM fails."""
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        draft = _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with patch.object(
                qa_iteration_service, "_call_llm_improve", side_effect=RuntimeError("LLM failure")
            ):
                with pytest.raises(RuntimeError, match="LLM failure"):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        # Rollback means score and feedback_text are not committed
        db.refresh(draft)
        assert draft.score is None
        assert draft.feedback_text is None

    def test_on_improve_llm_error_no_new_draft_created(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with patch.object(
                qa_iteration_service, "_call_llm_improve", side_effect=RuntimeError("LLM failure")
            ):
                with pytest.raises(RuntimeError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(DraftVersion).filter(DraftVersion.document_id == doc.id).count()
        assert count == 1  # only the original draft

    def test_on_improve_llm_error_no_audit_log(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES):
            with patch.object(
                qa_iteration_service, "_call_llm_improve", side_effect=RuntimeError("LLM failure")
            ):
                with pytest.raises(RuntimeError):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 0

    def test_on_db_commit_error_exception_propagates(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            with patch.object(db, "commit", side_effect=Exception("DB failure")):
                with pytest.raises(Exception, match="DB failure"):
                    qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)


# ---------------------------------------------------------------------------
# TestAuditLogs
# ---------------------------------------------------------------------------

class TestAuditLogs:
    def test_one_log_per_qa_iteration(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def alternating(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _PASSING_SCORES if call_count["n"] >= 3 else _FAILING_SCORES

        with patch.object(qa_iteration_service, "_call_llm_evaluate", side_effect=alternating):
            with _patch_improve():
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=5)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 3  # iterations 1, 2, 3

    def test_audit_log_contains_iteration_number(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert "1" in log.action  # iteration 1

    def test_audit_log_contains_score(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert str(_PASSING_SCORES["composite_score"]) in log.action

    def test_audit_log_action_within_512_chars(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        log = db.query(AuditLog).filter(AuditLog.document_id == doc.id).first()
        assert len(log.action) <= 512

    def test_three_logs_for_blocked_document(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        with _patch_evaluate(_FAILING_SCORES), _patch_improve():
            with pytest.raises(MaxIterationsReachedError):
                qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=3)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 3


# ---------------------------------------------------------------------------
# TestEvaluateDraftHelper — unit tests for the evaluate_draft function
# ---------------------------------------------------------------------------

class TestEvaluateDraftHelper:
    def test_updates_draft_score_in_memory(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_draft(db, draft.id, {})

        assert draft.score == _PASSING_SCORES["composite_score"]

    def test_updates_draft_feedback_text_in_memory(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            qa_iteration_service.evaluate_draft(db, draft.id, {})

        assert draft.feedback_text == "\n".join(_PASSING_SCORES["improvement_suggestions"])

    def test_returns_rubric_scores_instance(self, db):
        from app.schemas.schemas import RubricScores

        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        with _patch_evaluate(_PASSING_SCORES):
            result = qa_iteration_service.evaluate_draft(db, draft.id, {})

        assert isinstance(result, RubricScores)
        assert result.composite_score == _PASSING_SCORES["composite_score"]

    def test_raises_not_found_for_unknown_draft(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError):
            qa_iteration_service.evaluate_draft(db, fake_id, {})

    def test_raises_invalid_rubric_score_on_malformed_output(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        malformed = {"factual_correctness": "not_a_number", "improvement_suggestions": ["ok"]}

        with patch.object(qa_iteration_service, "_call_llm_evaluate", return_value=malformed):
            with pytest.raises(InvalidRubricScoreError):
                qa_iteration_service.evaluate_draft(db, draft.id, {})

    def test_raises_invalid_rubric_score_on_out_of_range(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        out_of_range = {
            "factual_correctness": 11.0,  # > 10, invalid
            "technical_depth": 5.0,
            "clarity": 5.0,
            "composite_score": 7.0,
            "feedback": "Some feedback.",
        }

        with patch.object(qa_iteration_service, "_call_llm_evaluate", return_value=out_of_range):
            with pytest.raises(InvalidRubricScoreError):
                qa_iteration_service.evaluate_draft(db, draft.id, {})

    def test_score_not_mutated_when_llm_fails(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        with patch.object(
            qa_iteration_service, "_call_llm_evaluate", side_effect=RuntimeError("timeout")
        ):
            with pytest.raises(RuntimeError):
                qa_iteration_service.evaluate_draft(db, draft.id, {})

        assert draft.score is None


# ---------------------------------------------------------------------------
# TestImproveDraftHelper — unit tests for the improve_draft function
# ---------------------------------------------------------------------------

class TestImproveDraftHelper:
    def test_creates_new_draft_version(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id, iteration=1)

        with _patch_improve():
            new_draft = qa_iteration_service.improve_draft(
                db, draft.id, "needs improvement", {}, "formal"
            )
            db.commit()
            db.refresh(new_draft)

        assert new_draft is not None
        assert isinstance(new_draft, DraftVersion)

    def test_new_draft_iteration_number_incremented(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id, iteration=1)

        with _patch_improve():
            new_draft = qa_iteration_service.improve_draft(
                db, draft.id, "needs improvement", {}, "formal"
            )
            db.commit()
            db.refresh(new_draft)

        assert new_draft.iteration_number == 2

    def test_new_draft_linked_to_same_document(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id, iteration=3)

        with _patch_improve():
            new_draft = qa_iteration_service.improve_draft(
                db, draft.id, "needs improvement", {}, "formal"
            )
            db.commit()
            db.refresh(new_draft)

        assert new_draft.document_id == doc.id
        assert new_draft.iteration_number == 4

    def test_new_draft_score_is_none(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)

        with _patch_improve():
            new_draft = qa_iteration_service.improve_draft(
                db, draft.id, "needs improvement", {}, "formal"
            )
            db.commit()

        assert new_draft.score is None
        assert new_draft.feedback_text is None

    def test_raises_not_found_for_unknown_draft(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError):
            qa_iteration_service.improve_draft(db, fake_id, "feedback", {}, "formal")

    def test_content_comes_from_llm(self, db):
        doc = _make_document(db)
        draft = _make_draft(db, doc.id)
        expected = "# Introduction\n\nBrand new content."

        with _patch_improve(expected):
            new_draft = qa_iteration_service.improve_draft(
                db, draft.id, "feedback text", {}, "formal"
            )
            db.commit()
            db.refresh(new_draft)

        assert new_draft.content_markdown == expected


# ---------------------------------------------------------------------------
# TestMaxIterationsValidation
# ---------------------------------------------------------------------------

class TestMaxIterationsValidation:
    def test_zero_max_iterations_raises_value_error(self, db):
        doc = _make_document(db)

        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=0)

    def test_negative_max_iterations_raises_value_error(self, db):
        doc = _make_document(db)

        with pytest.raises(ValueError, match="max_iterations must be >= 1"):
            qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=-1)

    def test_none_max_iterations_uses_config_default(self, db):
        """max_iterations=None should fall back to settings.max_qa_iterations."""
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        _make_draft(db, doc.id)

        call_count = {"n": 0}

        def counting_evaluate(draft_content, fact_sheet_data, *args, **kwargs):
            call_count["n"] += 1
            return _FAILING_SCORES

        mock_cfg = MagicMock()
        mock_cfg.max_qa_iterations = 2
        mock_cfg.qa_passing_threshold = 9.0
        mock_cfg.qa_llm_model = "claude-sonnet-4-6"
        mock_cfg.max_draft_length = 50_000
        mock_cfg.llm_timeout_seconds = 120

        with patch.object(qa_iteration_service.settings_service, "get_settings", return_value=mock_cfg):
            with patch.object(
                qa_iteration_service, "_call_llm_evaluate", side_effect=counting_evaluate
            ):
                with _patch_improve():
                    with pytest.raises(MaxIterationsReachedError):
                        qa_iteration_service.evaluate_and_iterate(db, doc.id, max_iterations=None)

        assert call_count["n"] == 2  # used mock config default of 2, not real config of 3
