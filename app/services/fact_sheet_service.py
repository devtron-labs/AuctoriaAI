from typing import Any

from sqlalchemy.orm import Session

from app.models.models import Document, FactSheet
from app.services.exceptions import NotFoundError


def create_fact_sheet(db: Session, document_id: str, structured_data: dict[str, Any]) -> FactSheet:
    if not db.query(Document).filter(Document.id == document_id).first():
        raise NotFoundError(f"Document {document_id} not found")
    fact_sheet = FactSheet(document_id=document_id, structured_data=structured_data)
    db.add(fact_sheet)
    db.commit()
    db.refresh(fact_sheet)
    return fact_sheet


def get_fact_sheet(db: Session, fact_sheet_id: str, document_id: str | None = None) -> FactSheet:
    fs = db.query(FactSheet).filter(FactSheet.id == fact_sheet_id).first()
    if fs is None or (document_id is not None and fs.document_id != document_id):
        raise NotFoundError(f"Fact sheet {fact_sheet_id} not found")
    return fs


def list_fact_sheets(db: Session, document_id: str) -> list[FactSheet]:
    if not db.query(Document).filter(Document.id == document_id).first():
        raise NotFoundError(f"Document {document_id} not found")
    return db.query(FactSheet).filter(FactSheet.document_id == document_id).all()
