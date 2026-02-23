"""
Service layer for Document lifecycle management.

State machine (valid transitions):
  DRAFT        → VALIDATING
  VALIDATING   → PASSED | HUMAN_REVIEW | BLOCKED
  PASSED       → APPROVED
  HUMAN_REVIEW → APPROVED | BLOCKED
  BLOCKED      → DRAFT
  APPROVED     → (terminal — no outgoing transitions)
"""

from sqlalchemy import func
from sqlalchemy.orm import Session, selectinload

from app.models.models import AuditLog, Document, DocumentStatus, DraftVersion, FactSheet
from app.services.exceptions import NotFoundError


# ---------------------------------------------------------------------------
# State machine definition
# ---------------------------------------------------------------------------

VALID_TRANSITIONS: dict[DocumentStatus, set[DocumentStatus]] = {
    DocumentStatus.DRAFT:        {DocumentStatus.VALIDATING},
    DocumentStatus.VALIDATING:   {DocumentStatus.PASSED, DocumentStatus.HUMAN_REVIEW, DocumentStatus.BLOCKED},
    DocumentStatus.PASSED:       {DocumentStatus.APPROVED},
    DocumentStatus.HUMAN_REVIEW: {DocumentStatus.APPROVED, DocumentStatus.BLOCKED},
    DocumentStatus.BLOCKED:      {DocumentStatus.DRAFT},
    DocumentStatus.APPROVED:     set(),  # terminal
}


class InvalidTransitionError(Exception):
    """Raised when an illegal state transition is attempted."""


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _audit(db: Session, document_id: str, action: str) -> None:
    log = AuditLog(document_id=document_id, action=action[:512])
    db.add(log)


def _next_iteration(db: Session, document_id: str) -> int:
    """Return the next iteration number for a document's draft versions."""
    # Lock the Document row to prevent concurrent draft creation racing.
    db.query(Document).filter(Document.id == document_id).with_for_update().first()
    max_iter = (
        db.query(func.max(DraftVersion.iteration_number))
        .filter(DraftVersion.document_id == document_id)
        .scalar()
    )
    return 1 if max_iter is None else max_iter + 1


# ---------------------------------------------------------------------------
# Document CRUD
# ---------------------------------------------------------------------------

def create_document(db: Session, title: str) -> Document:
    doc = Document(title=title, status=DocumentStatus.DRAFT)
    db.add(doc)
    db.flush()  # populate doc.id before audit log
    _audit(db, doc.id, f"Document created with title='{title}'")
    db.commit()
    db.refresh(doc)
    return doc


def get_document(db: Session, document_id: str) -> Document | None:
    return (
        db.query(Document)
        .options(
            selectinload(Document.draft_versions),
            selectinload(Document.fact_sheets),
        )
        .filter(Document.id == document_id)
        .first()
    )


def list_documents(
    db: Session,
    skip: int = 0,
    limit: int = 100,
    status: DocumentStatus | None = None,
) -> list[Document]:
    query = db.query(Document)
    if status is not None:
        query = query.filter(Document.status == status)
    return query.offset(skip).limit(limit).all()


def transition_document(db: Session, document_id: str, target: DocumentStatus) -> Document:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    allowed = VALID_TRANSITIONS[doc.status]
    if target not in allowed:
        raise InvalidTransitionError(
            f"Cannot transition from {doc.status.value} to {target.value}. "
            f"Allowed: {[s.value for s in allowed] or 'none (terminal state)'}"
        )

    old_status = doc.status
    doc.status = target
    _audit(db, doc.id, f"Status changed: {old_status.value} → {target.value}")
    db.commit()
    db.refresh(doc)
    return doc


# ---------------------------------------------------------------------------
# DraftVersion CRUD
# ---------------------------------------------------------------------------

def create_draft_version(
    db: Session,
    document_id: str,
    content_markdown: str,
    score: float | None = None,
) -> DraftVersion:
    doc = db.query(Document).filter(Document.id == document_id).first()
    if doc is None:
        raise NotFoundError(f"Document {document_id} not found")

    iteration = _next_iteration(db, document_id)
    draft = DraftVersion(
        document_id=document_id,
        iteration_number=iteration,
        content_markdown=content_markdown,
        score=score,
        user_prompt="",   # Manual drafts have no user prompt
    )
    db.add(draft)
    _audit(db, document_id, f"DraftVersion created: iteration={iteration}")
    db.commit()
    db.refresh(draft)
    return draft


def list_draft_versions(db: Session, document_id: str) -> list[DraftVersion]:
    if not db.query(Document).filter(Document.id == document_id).first():
        raise NotFoundError(f"Document {document_id} not found")
    return (
        db.query(DraftVersion)
        .filter(DraftVersion.document_id == document_id)
        .order_by(DraftVersion.iteration_number)
        .all()
    )


def get_draft_version(db: Session, draft_id: str, document_id: str | None = None) -> DraftVersion:
    draft = db.query(DraftVersion).filter(DraftVersion.id == draft_id).first()
    if draft is None or (document_id is not None and draft.document_id != document_id):
        raise NotFoundError(f"Draft version {draft_id} not found")
    return draft
