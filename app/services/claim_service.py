from datetime import datetime

from sqlalchemy.orm import Session

from app.models.models import ClaimRegistry, ClaimType


def create_claim(
    db: Session,
    claim_text: str,
    claim_type: ClaimType,
    expiry_date: datetime | None = None,
) -> ClaimRegistry:
    claim = ClaimRegistry(
        claim_text=claim_text,
        claim_type=claim_type,
        expiry_date=expiry_date,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def get_claim(db: Session, claim_id: str) -> ClaimRegistry | None:
    return db.query(ClaimRegistry).filter(ClaimRegistry.id == claim_id).first()


def list_claims(db: Session, skip: int = 0, limit: int = 100) -> list[ClaimRegistry]:
    return db.query(ClaimRegistry).offset(skip).limit(limit).all()
