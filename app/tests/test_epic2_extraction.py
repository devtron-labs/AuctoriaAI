"""
Test skeletons for:
  Ticket 2.2 — Fact Sheet Extraction Engine
  Ticket 2.4 — Registry Sync Enforcement

Covers:
  check_registry_freshness():
    - fresh registry passes
    - stale registry raises RegistryStaleError
    - empty registry raises RegistryStaleError
    - exactly-at-threshold passes
    - threshold is configurable via settings

  extract_factsheet():
    - success path: fact sheet created + linked to document
    - blocked when registry is stale
    - NotFoundError when document missing
    - ExtractionError on malformed LLM output
    - ExtractionError on missing required nested fields
    - transaction rollback on DB commit failure

Tests use SQLite in-memory via the `db` fixture defined in conftest.py.
"""

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from app.models.models import ClaimRegistry, ClaimType, Document, DocumentStatus, FactSheet
from app.services import extraction_service
from app.services.exceptions import ExtractionError, NotFoundError, RegistryStaleError


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

def _make_document(db, title: str = "Test Doc") -> Document:
    doc = Document(title=title, status=DocumentStatus.DRAFT)
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return doc


def _make_claim(db, hours_old: int = 0) -> ClaimRegistry:
    claim = ClaimRegistry(
        claim_text="Registry entry",
        claim_type=ClaimType.COMPLIANCE,
        updated_at=datetime.now(timezone.utc) - timedelta(hours=hours_old),
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


VALID_EXTRACTION = {
    "features": [{"name": "Auth Module", "description": "Handles SSO and MFA"}],
    "integrations": [{"system": "LDAP", "method": "SAML 2.0", "notes": "AD integration"}],
    "compliance": [{"standard": "SOC 2 Type II", "status": "compliant", "details": "Audit 2025"}],
    "performance_metrics": [{"metric": "Throughput", "value": "10000", "unit": "req/s"}],
    "limitations": [{"category": "Scalability", "description": "Max 100 concurrent nodes"}],
}


def _patch_staleness(hours: int):
    """Patch settings.registry_staleness_hours for freshness tests."""
    mock_cfg = type("Settings", (), {"registry_staleness_hours": hours})()
    return patch.object(extraction_service, "settings", mock_cfg)


# ---------------------------------------------------------------------------
# Ticket 2.4 — Registry freshness gate
# ---------------------------------------------------------------------------

class TestCheckRegistryFreshness:
    def test_fresh_registry_does_not_raise(self, db):
        _make_claim(db, hours_old=0)
        # Should not raise
        extraction_service.check_registry_freshness(db)

    def test_stale_registry_raises(self, db):
        _make_claim(db, hours_old=48)
        with pytest.raises(RegistryStaleError, match="stale"):
            extraction_service.check_registry_freshness(db)

    def test_empty_registry_raises(self, db):
        with pytest.raises(RegistryStaleError, match="empty"):
            extraction_service.check_registry_freshness(db)

    def test_exactly_at_threshold_boundary_passes(self, db):
        """A claim updated 23h59m ago should pass the default 24h threshold."""
        claim = ClaimRegistry(
            claim_text="boundary claim",
            claim_type=ClaimType.PERFORMANCE,
            updated_at=datetime.now(timezone.utc) - timedelta(hours=23, minutes=59),
        )
        db.add(claim)
        db.commit()

        extraction_service.check_registry_freshness(db)  # must not raise

    def test_configurable_threshold_tighter(self, db):
        """With a 5h threshold, a 10h-old registry should be stale."""
        _make_claim(db, hours_old=10)

        with _patch_staleness(hours=5):
            with pytest.raises(RegistryStaleError):
                extraction_service.check_registry_freshness(db)

    def test_configurable_threshold_looser(self, db):
        """With a 48h threshold, a 10h-old registry should be fresh."""
        _make_claim(db, hours_old=10)

        with _patch_staleness(hours=48):
            extraction_service.check_registry_freshness(db)  # must not raise

    def test_most_recently_updated_row_is_used(self, db):
        """Only the most recently updated row matters for freshness."""
        # One very stale row and one fresh row
        _make_claim(db, hours_old=100)
        _make_claim(db, hours_old=1)

        extraction_service.check_registry_freshness(db)  # must not raise


# ---------------------------------------------------------------------------
# Ticket 2.2 — Fact sheet extraction
# ---------------------------------------------------------------------------

class TestExtractFactsheet:
    def test_creates_fact_sheet_linked_to_document(self, db):
        _make_claim(db, hours_old=0)
        doc = _make_document(db)

        with patch.object(extraction_service, "_call_llm", return_value=VALID_EXTRACTION):
            result = extraction_service.extract_factsheet(db, doc.id)

        assert result.document_id == doc.id
        assert result.id is not None
        assert result.structured_data["features"][0]["name"] == "Auth Module"
        assert "integrations" in result.structured_data
        assert "compliance" in result.structured_data
        assert "performance_metrics" in result.structured_data
        assert "limitations" in result.structured_data

    def test_fact_sheet_persisted_in_db(self, db):
        _make_claim(db, hours_old=0)
        doc = _make_document(db)

        with patch.object(extraction_service, "_call_llm", return_value=VALID_EXTRACTION):
            extraction_service.extract_factsheet(db, doc.id)

        stored = db.query(FactSheet).filter(FactSheet.document_id == doc.id).first()
        assert stored is not None
        assert stored.structured_data["compliance"][0]["standard"] == "SOC 2 Type II"

    def test_audit_log_entry_created(self, db):
        from app.models.models import AuditLog
        _make_claim(db, hours_old=0)
        doc = _make_document(db)

        with patch.object(extraction_service, "_call_llm", return_value=VALID_EXTRACTION):
            extraction_service.extract_factsheet(db, doc.id)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert log is not None
        assert "extracted" in log.action.lower()

    def test_blocked_when_registry_stale(self, db):
        _make_claim(db, hours_old=48)
        doc = _make_document(db)

        with pytest.raises(RegistryStaleError):
            extraction_service.extract_factsheet(db, doc.id)

    def test_not_found_when_document_missing(self, db):
        import uuid
        _make_claim(db, hours_old=0)

        with patch.object(extraction_service, "_call_llm", return_value=VALID_EXTRACTION):
            with pytest.raises(NotFoundError):
                extraction_service.extract_factsheet(db, str(uuid.uuid4()))

    def test_malformed_top_level_type_rejected(self, db):
        """features must be a list, not a string."""
        _make_claim(db, hours_old=0)
        doc = _make_document(db)
        bad = {"features": "not_a_list", "integrations": [], "compliance": [],
               "performance_metrics": [], "limitations": []}

        with patch.object(extraction_service, "_call_llm", return_value=bad):
            with pytest.raises(ExtractionError, match="validation"):
                extraction_service.extract_factsheet(db, doc.id)

    def test_missing_required_nested_field_rejected(self, db):
        """FeatureItem.description is required — omitting it should raise ExtractionError."""
        _make_claim(db, hours_old=0)
        doc = _make_document(db)
        bad = {
            "features": [{"name": "X"}],  # missing 'description'
            "integrations": [{"system": "Y", "method": "Z", "notes": ""}],
            "compliance": [{"standard": "A", "status": "ok", "details": ""}],
            "performance_metrics": [{"metric": "M", "value": "1", "unit": "s"}],
            "limitations": [{"category": "C", "description": "D"}],
        }

        with patch.object(extraction_service, "_call_llm", return_value=bad):
            with pytest.raises(ExtractionError):
                extraction_service.extract_factsheet(db, doc.id)

    def test_missing_top_level_key_rejected(self, db):
        """Omitting the 'limitations' key entirely should fail schema validation."""
        _make_claim(db, hours_old=0)
        doc = _make_document(db)
        bad = {
            "features": [],
            "integrations": [],
            "compliance": [],
            "performance_metrics": [],
            # 'limitations' intentionally omitted
        }

        with patch.object(extraction_service, "_call_llm", return_value=bad):
            with pytest.raises(ExtractionError):
                extraction_service.extract_factsheet(db, doc.id)

    def test_transaction_rolled_back_on_db_failure(self, db):
        """If the DB commit fails, no FactSheet row should be left behind."""
        _make_claim(db, hours_old=0)
        doc = _make_document(db)
        initial_count = db.query(FactSheet).count()

        with patch.object(extraction_service, "_call_llm", return_value=VALID_EXTRACTION):
            with patch.object(db, "commit", side_effect=RuntimeError("DB down")):
                with pytest.raises(RuntimeError, match="DB down"):
                    extraction_service.extract_factsheet(db, doc.id)

        db.rollback()
        assert db.query(FactSheet).count() == initial_count

    def test_llm_exception_wrapped_in_extraction_error(self, db):
        """Unexpected exception from _call_llm should become ExtractionError."""
        _make_claim(db, hours_old=0)
        doc = _make_document(db)

        with patch.object(extraction_service, "_call_llm", side_effect=ConnectionError("timeout")):
            with pytest.raises(ExtractionError, match="LLM extraction failed"):
                extraction_service.extract_factsheet(db, doc.id)
