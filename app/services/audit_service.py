from sqlalchemy.orm import Session

from app.models.models import AuditLog, Document
from app.services.exceptions import NotFoundError


def list_audit_logs(db: Session, document_id: str) -> list[AuditLog]:
    if not db.query(Document).filter(Document.id == document_id).first():
        raise NotFoundError(f"Document {document_id} not found")
    return (
        db.query(AuditLog)
        .filter(AuditLog.document_id == document_id)
        .order_by(AuditLog.timestamp)
        .all()
    )
