"""
Unit tests for:
  - Valid state transitions
  - Invalid state transitions
  - Iteration number auto-increment
  - AuditLog created on every state change
"""

import pytest
from sqlalchemy.orm import Session

from app.models.models import AuditLog, DocumentStatus
from app.services.document_service import (
    InvalidTransitionError,
    create_document,
    create_draft_version,
    list_draft_versions,
    transition_document,
)
from app.services.audit_service import list_audit_logs
from app.services.exceptions import NotFoundError
from app.services.fact_sheet_service import create_fact_sheet, get_fact_sheet, list_fact_sheets


# ── Helpers ──────────────────────────────────────────────────────────────────

def _audit_actions(db: Session, document_id: str) -> list[str]:
    return [
        log.action
        for log in db.query(AuditLog)
        .filter(AuditLog.document_id == document_id)
        .order_by(AuditLog.timestamp)
        .all()
    ]


# ── Document creation ─────────────────────────────────────────────────────────

def test_create_document_defaults_to_draft(db):
    doc = create_document(db, title="AI Policy v1")
    assert doc.status == DocumentStatus.DRAFT
    assert doc.title == "AI Policy v1"


def test_create_document_writes_audit_log(db):
    doc = create_document(db, title="Policy")
    actions = _audit_actions(db, doc.id)
    assert len(actions) == 1
    assert "created" in actions[0].lower()


# ── Valid state transitions ───────────────────────────────────────────────────

@pytest.mark.parametrize("path", [
    [DocumentStatus.VALIDATING],
    [DocumentStatus.VALIDATING, DocumentStatus.PASSED],
    [DocumentStatus.VALIDATING, DocumentStatus.PASSED, DocumentStatus.APPROVED],
    [DocumentStatus.VALIDATING, DocumentStatus.HUMAN_REVIEW],
    [DocumentStatus.VALIDATING, DocumentStatus.HUMAN_REVIEW, DocumentStatus.APPROVED],
    [DocumentStatus.VALIDATING, DocumentStatus.HUMAN_REVIEW, DocumentStatus.BLOCKED],
    [DocumentStatus.VALIDATING, DocumentStatus.BLOCKED],
    [DocumentStatus.VALIDATING, DocumentStatus.BLOCKED, DocumentStatus.DRAFT],
])
def test_valid_transition_paths(db, path):
    doc = create_document(db, "doc")
    for target in path:
        doc = transition_document(db, doc.id, target)
    assert doc.status == path[-1]


def test_draft_to_validating(db):
    doc = create_document(db, "doc")
    doc = transition_document(db, doc.id, DocumentStatus.VALIDATING)
    assert doc.status == DocumentStatus.VALIDATING


def test_validating_to_passed(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    doc = transition_document(db, doc.id, DocumentStatus.PASSED)
    assert doc.status == DocumentStatus.PASSED


def test_validating_to_human_review(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    doc = transition_document(db, doc.id, DocumentStatus.HUMAN_REVIEW)
    assert doc.status == DocumentStatus.HUMAN_REVIEW


def test_validating_to_blocked(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    doc = transition_document(db, doc.id, DocumentStatus.BLOCKED)
    assert doc.status == DocumentStatus.BLOCKED


def test_passed_to_approved(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.PASSED)
    doc = transition_document(db, doc.id, DocumentStatus.APPROVED)
    assert doc.status == DocumentStatus.APPROVED


def test_human_review_to_approved(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.HUMAN_REVIEW)
    doc = transition_document(db, doc.id, DocumentStatus.APPROVED)
    assert doc.status == DocumentStatus.APPROVED


def test_human_review_to_blocked(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.HUMAN_REVIEW)
    doc = transition_document(db, doc.id, DocumentStatus.BLOCKED)
    assert doc.status == DocumentStatus.BLOCKED


def test_blocked_to_draft(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.BLOCKED)
    doc = transition_document(db, doc.id, DocumentStatus.DRAFT)
    assert doc.status == DocumentStatus.DRAFT


# ── Invalid state transitions ─────────────────────────────────────────────────

@pytest.mark.parametrize("from_status,to_status", [
    (DocumentStatus.DRAFT,        DocumentStatus.APPROVED),
    (DocumentStatus.DRAFT,        DocumentStatus.PASSED),
    (DocumentStatus.DRAFT,        DocumentStatus.BLOCKED),
    (DocumentStatus.DRAFT,        DocumentStatus.HUMAN_REVIEW),
    (DocumentStatus.VALIDATING,   DocumentStatus.DRAFT),
    (DocumentStatus.VALIDATING,   DocumentStatus.APPROVED),
    (DocumentStatus.PASSED,       DocumentStatus.DRAFT),
    (DocumentStatus.PASSED,       DocumentStatus.VALIDATING),
    (DocumentStatus.PASSED,       DocumentStatus.BLOCKED),
    (DocumentStatus.PASSED,       DocumentStatus.HUMAN_REVIEW),
    (DocumentStatus.APPROVED,     DocumentStatus.DRAFT),
    (DocumentStatus.APPROVED,     DocumentStatus.VALIDATING),
    (DocumentStatus.APPROVED,     DocumentStatus.BLOCKED),
    (DocumentStatus.BLOCKED,      DocumentStatus.APPROVED),
    (DocumentStatus.BLOCKED,      DocumentStatus.PASSED),
    (DocumentStatus.BLOCKED,      DocumentStatus.VALIDATING),
])
def test_invalid_transitions(db, from_status, to_status):
    """Every illegal transition must raise InvalidTransitionError."""
    doc = create_document(db, "doc")

    # Drive document to the desired starting state via valid transitions
    valid_path_to = {
        DocumentStatus.DRAFT:        [],
        DocumentStatus.VALIDATING:   [DocumentStatus.VALIDATING],
        DocumentStatus.PASSED:       [DocumentStatus.VALIDATING, DocumentStatus.PASSED],
        DocumentStatus.HUMAN_REVIEW: [DocumentStatus.VALIDATING, DocumentStatus.HUMAN_REVIEW],
        DocumentStatus.APPROVED:     [DocumentStatus.VALIDATING, DocumentStatus.PASSED, DocumentStatus.APPROVED],
        DocumentStatus.BLOCKED:      [DocumentStatus.VALIDATING, DocumentStatus.BLOCKED],
    }
    for step in valid_path_to[from_status]:
        doc = transition_document(db, doc.id, step)

    assert doc.status == from_status

    with pytest.raises(InvalidTransitionError):
        transition_document(db, doc.id, to_status)


def test_approved_is_terminal(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.PASSED)
    transition_document(db, doc.id, DocumentStatus.APPROVED)

    for target in DocumentStatus:
        if target != DocumentStatus.APPROVED:
            with pytest.raises(InvalidTransitionError):
                transition_document(db, doc.id, target)


def test_transition_nonexistent_document_raises(db):
    with pytest.raises(NotFoundError):
        transition_document(db, "00000000-0000-0000-0000-000000000000", DocumentStatus.VALIDATING)


# ── Audit log on every state change ──────────────────────────────────────────

def test_audit_log_created_on_transition(db):
    doc = create_document(db, "doc")
    transition_document(db, doc.id, DocumentStatus.VALIDATING)
    transition_document(db, doc.id, DocumentStatus.PASSED)

    actions = _audit_actions(db, doc.id)
    # creation log + 2 transition logs
    assert len(actions) == 3
    assert "DRAFT" in actions[1] and "VALIDATING" in actions[1]
    assert "VALIDATING" in actions[2] and "PASSED" in actions[2]


# ── Iteration number auto-increment ──────────────────────────────────────────

def test_first_draft_is_iteration_one(db):
    doc = create_document(db, "doc")
    draft = create_draft_version(db, doc.id, "# First draft")
    assert draft.iteration_number == 1


def test_iteration_increments_sequentially(db):
    doc = create_document(db, "doc")
    d1 = create_draft_version(db, doc.id, "# v1")
    d2 = create_draft_version(db, doc.id, "# v2")
    d3 = create_draft_version(db, doc.id, "# v3")
    assert d1.iteration_number == 1
    assert d2.iteration_number == 2
    assert d3.iteration_number == 3


def test_iterations_are_independent_per_document(db):
    doc_a = create_document(db, "Doc A")
    doc_b = create_document(db, "Doc B")

    create_draft_version(db, doc_a.id, "A v1")
    create_draft_version(db, doc_a.id, "A v2")
    b1 = create_draft_version(db, doc_b.id, "B v1")

    assert b1.iteration_number == 1  # Doc B starts at 1 regardless of Doc A

    drafts_a = list_draft_versions(db, doc_a.id)
    assert [d.iteration_number for d in drafts_a] == [1, 2]


def test_draft_version_with_score(db):
    doc = create_document(db, "doc")
    draft = create_draft_version(db, doc.id, "# Content", score=0.87)
    assert draft.score == pytest.approx(0.87)


def test_draft_version_score_nullable(db):
    doc = create_document(db, "doc")
    draft = create_draft_version(db, doc.id, "# Content", score=None)
    assert draft.score is None


def test_draft_creation_writes_audit_log(db):
    doc = create_document(db, "doc")
    create_draft_version(db, doc.id, "# v1")
    create_draft_version(db, doc.id, "# v2")

    actions = _audit_actions(db, doc.id)
    draft_actions = [a for a in actions if "DraftVersion" in a]
    assert len(draft_actions) == 2
    assert "iteration=1" in draft_actions[0]
    assert "iteration=2" in draft_actions[1]


# ── Missing invalid transitions ───────────────────────────────────────────────

@pytest.mark.parametrize("from_status,to_status", [
    # HUMAN_REVIEW illegal targets
    (DocumentStatus.HUMAN_REVIEW, DocumentStatus.VALIDATING),
    (DocumentStatus.HUMAN_REVIEW, DocumentStatus.DRAFT),
    (DocumentStatus.HUMAN_REVIEW, DocumentStatus.PASSED),
    # BLOCKED illegal targets
    (DocumentStatus.BLOCKED,      DocumentStatus.HUMAN_REVIEW),
    (DocumentStatus.BLOCKED,      DocumentStatus.BLOCKED),
    # Self-transitions (every state → itself)
    (DocumentStatus.DRAFT,        DocumentStatus.DRAFT),
    (DocumentStatus.VALIDATING,   DocumentStatus.VALIDATING),
    (DocumentStatus.PASSED,       DocumentStatus.PASSED),
    (DocumentStatus.HUMAN_REVIEW, DocumentStatus.HUMAN_REVIEW),
    (DocumentStatus.APPROVED,     DocumentStatus.APPROVED),
    (DocumentStatus.BLOCKED,      DocumentStatus.BLOCKED),
])
def test_additional_invalid_transitions(db, from_status, to_status):
    """Additional illegal transitions must raise InvalidTransitionError."""
    doc = create_document(db, "doc")

    valid_path_to = {
        DocumentStatus.DRAFT:        [],
        DocumentStatus.VALIDATING:   [DocumentStatus.VALIDATING],
        DocumentStatus.PASSED:       [DocumentStatus.VALIDATING, DocumentStatus.PASSED],
        DocumentStatus.HUMAN_REVIEW: [DocumentStatus.VALIDATING, DocumentStatus.HUMAN_REVIEW],
        DocumentStatus.APPROVED:     [DocumentStatus.VALIDATING, DocumentStatus.PASSED, DocumentStatus.APPROVED],
        DocumentStatus.BLOCKED:      [DocumentStatus.VALIDATING, DocumentStatus.BLOCKED],
    }
    for step in valid_path_to[from_status]:
        doc = transition_document(db, doc.id, step)

    assert doc.status == from_status

    with pytest.raises(InvalidTransitionError):
        transition_document(db, doc.id, to_status)


# ── list_* with nonexistent document ─────────────────────────────────────────

_GHOST_ID = "00000000-0000-0000-0000-000000000000"


def test_list_draft_versions_nonexistent_document_raises(db):
    with pytest.raises(NotFoundError):
        list_draft_versions(db, _GHOST_ID)


def test_list_fact_sheets_nonexistent_document_raises(db):
    with pytest.raises(NotFoundError):
        list_fact_sheets(db, _GHOST_ID)


def test_list_audit_logs_nonexistent_document_raises(db):
    with pytest.raises(NotFoundError):
        list_audit_logs(db, _GHOST_ID)


# ── Fact sheet ownership mismatch ─────────────────────────────────────────────

def test_get_fact_sheet_ownership_mismatch_raises(db):
    doc_a = create_document(db, "Doc A")
    doc_b = create_document(db, "Doc B")

    fs = create_fact_sheet(db, doc_a.id, {"key": "value"})

    with pytest.raises(NotFoundError):
        get_fact_sheet(db, fs.id, document_id=doc_b.id)
