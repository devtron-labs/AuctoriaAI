"""
Test skeletons for Ticket 2.3 — Claim Registry Schema & Validation API.

Covers:
  get_claims():
    - empty registry returns []
    - multiple claims returned with pagination

  get_claim():
    - existing claim returned with all fields
    - NotFoundError on missing claim

  validate_claims():
    - all valid claims → is_valid=True, no warnings, no errors
    - missing claim → hard fail, is_valid=False
    - expired claim → soft warning, is_valid=True (if no missing)
    - mix of valid / expired / missing
    - not-yet-expired claim treated as valid
    - approval metadata (approved_by, approved_at) stored and readable
    - empty claim_ids handled gracefully

Tests use SQLite in-memory via the `db` fixture defined in conftest.py.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

from app.models.models import ClaimRegistry, ClaimType
from app.services import claim_validation_service
from app.services.exceptions import NotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_claim(
    db,
    claim_text: str = "Default claim",
    claim_type: ClaimType = ClaimType.COMPLIANCE,
    expiry_date: datetime | None = None,
    approved_by: str | None = None,
    approved_at: datetime | None = None,
) -> ClaimRegistry:
    claim = ClaimRegistry(
        claim_text=claim_text,
        claim_type=claim_type,
        expiry_date=expiry_date,
        approved_by=approved_by,
        approved_at=approved_at,
        updated_at=datetime.now(timezone.utc),
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


def _expired_at(hours_ago: int = 1) -> datetime:
    return datetime.now(timezone.utc) - timedelta(hours=hours_ago)


def _future_at(days: int = 365) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


# ---------------------------------------------------------------------------
# get_claims()
# ---------------------------------------------------------------------------

class TestGetClaims:
    def test_empty_registry_returns_empty_list(self, db):
        assert claim_validation_service.get_claims(db) == []

    def test_returns_all_claims(self, db):
        _make_claim(db, "Claim A")
        _make_claim(db, "Claim B", claim_type=ClaimType.INTEGRATION)
        result = claim_validation_service.get_claims(db)
        assert len(result) == 2

    def test_pagination_skip(self, db):
        for i in range(5):
            _make_claim(db, f"Claim {i}")
        result = claim_validation_service.get_claims(db, skip=3, limit=10)
        assert len(result) == 2

    def test_pagination_limit(self, db):
        for i in range(5):
            _make_claim(db, f"Claim {i}")
        result = claim_validation_service.get_claims(db, skip=0, limit=2)
        assert len(result) == 2

    def test_claim_has_enhanced_fields(self, db):
        now = datetime.now(timezone.utc)
        _make_claim(
            db,
            claim_text="Approved claim",
            approved_by="alice@example.com",
            approved_at=now,
            expiry_date=_future_at(),
        )
        result = claim_validation_service.get_claims(db)
        assert len(result) == 1
        claim = result[0]
        assert claim.approved_by == "alice@example.com"
        assert claim.expiry_date is not None
        assert claim.updated_at is not None


# ---------------------------------------------------------------------------
# get_claim()
# ---------------------------------------------------------------------------

class TestGetClaim:
    def test_existing_claim_returned(self, db):
        claim = _make_claim(db, "Specific claim")
        result = claim_validation_service.get_claim(db, claim.id)
        assert result.id == claim.id
        assert result.claim_text == "Specific claim"

    def test_approval_fields_readable(self, db):
        now = datetime.now(timezone.utc)
        claim = _make_claim(db, approved_by="bob@example.com", approved_at=now)
        result = claim_validation_service.get_claim(db, claim.id)
        assert result.approved_by == "bob@example.com"

    def test_nonexistent_claim_raises_not_found(self, db):
        with pytest.raises(NotFoundError):
            claim_validation_service.get_claim(db, str(uuid4()))

    def test_expiry_field_readable(self, db):
        expiry = _future_at(30)
        claim = _make_claim(db, expiry_date=expiry)
        result = claim_validation_service.get_claim(db, claim.id)
        assert result.expiry_date is not None


# ---------------------------------------------------------------------------
# validate_claims()
# ---------------------------------------------------------------------------

class TestValidateClaims:
    def test_all_valid_no_expiry(self, db):
        c1 = _make_claim(db, "Claim 1")
        c2 = _make_claim(db, "Claim 2", claim_type=ClaimType.PERFORMANCE)
        report = claim_validation_service.validate_claims(db, [c1.id, c2.id])

        assert report["is_valid"] is True
        assert set(report["valid_claims"]) == {c1.id, c2.id}
        assert report["expired_claims"] == []
        assert report["missing_claims"] == []
        assert report["warnings"] == []
        assert report["errors"] == []

    def test_missing_claim_hard_fail(self, db):
        fake_id = str(uuid4())
        report = claim_validation_service.validate_claims(db, [fake_id])

        assert report["is_valid"] is False
        assert fake_id in report["missing_claims"]
        assert len(report["errors"]) == 1
        assert report["valid_claims"] == []

    def test_expired_claim_soft_warning(self, db):
        claim = _make_claim(db, expiry_date=_expired_at(hours_ago=48))
        report = claim_validation_service.validate_claims(db, [claim.id])

        assert report["is_valid"] is True         # no hard error
        assert claim.id in report["expired_claims"]
        assert len(report["warnings"]) == 1
        assert report["errors"] == []

    def test_not_yet_expired_is_valid(self, db):
        claim = _make_claim(db, expiry_date=_future_at())
        report = claim_validation_service.validate_claims(db, [claim.id])

        assert report["is_valid"] is True
        assert claim.id in report["valid_claims"]
        assert report["expired_claims"] == []
        assert report["warnings"] == []

    def test_no_expiry_date_counts_as_valid(self, db):
        claim = _make_claim(db, expiry_date=None)
        report = claim_validation_service.validate_claims(db, [claim.id])

        assert claim.id in report["valid_claims"]

    def test_mixed_valid_expired_missing(self, db):
        valid = _make_claim(db, "Valid")
        expired = _make_claim(db, "Expired", expiry_date=_expired_at())
        missing_id = str(uuid4())

        report = claim_validation_service.validate_claims(
            db, [valid.id, expired.id, missing_id]
        )

        assert valid.id in report["valid_claims"]
        assert expired.id in report["expired_claims"]
        assert missing_id in report["missing_claims"]
        assert report["is_valid"] is False        # missing claim → hard fail
        assert len(report["warnings"]) == 1
        assert len(report["errors"]) == 1

    def test_all_missing_returns_all_errors(self, db):
        ids = [str(uuid4()) for _ in range(3)]
        report = claim_validation_service.validate_claims(db, ids)

        assert report["is_valid"] is False
        assert set(report["missing_claims"]) == set(ids)
        assert len(report["errors"]) == 3

    def test_single_item_list_valid(self, db):
        claim = _make_claim(db)
        report = claim_validation_service.validate_claims(db, [claim.id])
        assert report["is_valid"] is True

    def test_deduplication_not_required_but_stable(self, db):
        """Passing the same ID twice should work without crashing."""
        claim = _make_claim(db)
        # Duplicate IDs in the input — behaviour should be deterministic
        report = claim_validation_service.validate_claims(db, [claim.id, claim.id])
        # Both iterations of the same ID are valid
        assert report["is_valid"] is True

    def test_approval_metadata_tracked(self, db):
        """Approval fields are stored and returned alongside claim data."""
        now = datetime.now(timezone.utc)
        claim = _make_claim(
            db,
            claim_text="Approved claim",
            approved_by="approver@example.com",
            approved_at=now,
        )
        result = claim_validation_service.get_claim(db, claim.id)

        assert result.approved_by == "approver@example.com"
        assert result.approved_at is not None

    def test_expiry_check_uses_utc_now(self, db):
        """A claim expiring in the past should be in expired_claims regardless of timezone."""
        past = datetime(2000, 1, 1, tzinfo=timezone.utc)
        claim = _make_claim(db, expiry_date=past)
        report = claim_validation_service.validate_claims(db, [claim.id])

        assert claim.id in report["expired_claims"]
