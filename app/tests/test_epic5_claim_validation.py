"""
EPIC 5 — Claim Extraction & Registry Validation Tests.

Coverage:
  Extraction (17 tests):
    - Integration claims: various phrasings + multi-word system names
    - Compliance claims: case-insensitive, standard name variants
    - Performance metrics: different units, comma-separated numbers
    - Superlatives: all keywords, case-insensitive
    - Edge cases: empty string, whitespace-only, no claims, combined extraction

  Validation (22 tests):
    - Valid / missing / expired claims for each type (INTEGRATION, COMPLIANCE, PERFORMANCE)
    - Superlatives: blocked without nearby metric, allowed with same/adjacent-paragraph metric
    - validate_draft_claims: document/draft not found, empty draft, document blocked,
      validation report persisted, audit log written, rollback on DB error,
      multiple claims with one invalid → BLOCKED

All tests use the SQLite in-memory fixture from conftest.py.
No LLM calls are made.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.models.models import (
    AuditLog,
    ClaimRegistry,
    ClaimType,
    Document,
    DocumentStatus,
    DraftVersion,
)
from app.schemas.schemas import ExtractedClaim, ExtractedClaimType
from app.services.claim_extraction import (
    extract_all_claims,
    extract_compliance_claims,
    extract_integration_claims,
    extract_performance_claims,
    extract_superlatives,
)
from app.services.claim_validation_service import (
    validate_claim_against_registry,
    validate_draft_claims,
    validate_superlatives,
)
from app.services.exceptions import NotFoundError


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(timezone.utc)


def _doc(db, status: DocumentStatus = DocumentStatus.VALIDATING) -> Document:
    doc = Document(title="Test Document", status=status)
    db.add(doc)
    db.flush()
    return doc


def _draft(db, doc_id: str, content: str, iteration: int = 1) -> DraftVersion:
    draft = DraftVersion(
        document_id=doc_id,
        content_markdown=content,
        iteration_number=iteration,
        tone="formal",
    )
    db.add(draft)
    db.flush()
    return draft


def _claim(
    db,
    text: str,
    claim_type: ClaimType,
    expiry_date: datetime | None = None,
) -> ClaimRegistry:
    entry = ClaimRegistry(
        claim_text=text,
        claim_type=claim_type,
        expiry_date=expiry_date,
    )
    db.add(entry)
    db.flush()
    return entry


def _extracted(
    claim_type: ExtractedClaimType,
    claim_text: str,
    location: str = "paragraph 1, line 1",
) -> ExtractedClaim:
    return ExtractedClaim(
        claim_type=claim_type,
        claim_text=claim_text,
        location_in_draft=location,
    )


# ===========================================================================
# EXTRACTION TESTS (17)
# ===========================================================================


class TestExtractIntegrationClaims:
    def test_integrates_with(self):
        claims = extract_integration_claims("Our product integrates with Salesforce.")
        assert len(claims) == 1
        assert claims[0].claim_text == "Salesforce"
        assert claims[0].claim_type == ExtractedClaimType.INTEGRATION

    def test_integration_with(self):
        claims = extract_integration_claims("It offers integration with Slack for teams.")
        assert len(claims) == 1
        assert claims[0].claim_text == "Slack"

    def test_connects_to(self):
        claims = extract_integration_claims("The service connects to MySQL databases.")
        assert len(claims) == 1
        assert claims[0].claim_text == "MySQL"

    def test_works_with(self):
        claims = extract_integration_claims("This module works with Stripe payments.")
        assert len(claims) == 1
        assert claims[0].claim_text == "Stripe"

    def test_case_insensitive(self):
        claims = extract_integration_claims("INTEGRATES WITH GitHub for source control.")
        assert len(claims) == 1
        assert claims[0].claim_text == "GitHub"

    def test_multi_word_system(self):
        claims = extract_integration_claims("integrates with AWS S3 for object storage.")
        assert len(claims) == 1
        assert claims[0].claim_text == "AWS S3"

    def test_location_in_draft_format(self):
        claims = extract_integration_claims("integrates with Stripe.")
        assert "paragraph 1" in claims[0].location_in_draft
        assert "line" in claims[0].location_in_draft

    def test_multiple_integration_claims(self):
        md = "integrates with Salesforce.\n\nintegration with Slack and connects to MySQL."
        claims = extract_integration_claims(md)
        systems = [c.claim_text for c in claims]
        assert "Salesforce" in systems
        assert "Slack" in systems
        assert "MySQL" in systems

    def test_no_integration_claims(self):
        assert extract_integration_claims("No integrations here.") == []

    def test_empty_string(self):
        assert extract_integration_claims("") == []


class TestExtractComplianceClaims:
    def test_gdpr(self):
        claims = extract_compliance_claims("We are GDPR compliant.")
        assert len(claims) == 1
        assert "GDPR" in claims[0].claim_text

    def test_soc_2_with_space(self):
        claims = extract_compliance_claims("We hold SOC 2 Type II certification.")
        assert len(claims) == 1
        assert "SOC" in claims[0].claim_text

    def test_iso_27001(self):
        claims = extract_compliance_claims("ISO 27001 certified infrastructure.")
        assert len(claims) == 1
        assert "ISO" in claims[0].claim_text

    def test_hipaa_case_insensitive(self):
        claims = extract_compliance_claims("hipaa compliant architecture.")
        assert len(claims) == 1
        assert "hipaa" in claims[0].claim_text.lower()

    def test_pci_dss(self):
        claims = extract_compliance_claims("PCI DSS Level 1 compliant.")
        assert len(claims) == 1

    def test_fedramp(self):
        claims = extract_compliance_claims("FedRAMP authorized solution.")
        assert len(claims) == 1

    def test_ccpa(self):
        claims = extract_compliance_claims("CCPA ready data platform.")
        assert len(claims) == 1

    def test_multiple_standards(self):
        md = "We are GDPR and HIPAA compliant.\n\nAlso CCPA ready."
        claims = extract_compliance_claims(md)
        types = [c.claim_text.upper() for c in claims]
        assert any("GDPR" in t for t in types)
        assert any("HIPAA" in t for t in types)
        assert any("CCPA" in t for t in types)

    def test_no_compliance_claims(self):
        assert extract_compliance_claims("No compliance mentioned.") == []


class TestExtractPerformanceClaims:
    def test_percentage(self):
        claims = extract_performance_claims("Delivers 99.9% uptime.")
        assert len(claims) == 1
        assert "99.9" in claims[0].claim_text
        assert "%" in claims[0].claim_text

    def test_milliseconds(self):
        claims = extract_performance_claims("Response time under 50ms.")
        assert len(claims) == 1
        assert "50" in claims[0].claim_text

    def test_seconds(self):
        claims = extract_performance_claims("Processes in 5 seconds.")
        assert len(claims) == 1
        assert "5" in claims[0].claim_text

    def test_requests_per_sec(self):
        claims = extract_performance_claims("Handles 10,000 requests/sec at peak.")
        assert len(claims) == 1
        assert "10000" in claims[0].claim_text  # commas normalised out

    def test_megabytes(self):
        claims = extract_performance_claims("Requires only 256 MB of RAM.")
        assert len(claims) == 1
        assert "256" in claims[0].claim_text

    def test_gigabytes(self):
        claims = extract_performance_claims("Stores up to 10 GB per node.")
        assert len(claims) == 1

    def test_no_performance_claims(self):
        assert extract_performance_claims("Fast and reliable.") == []


class TestExtractSuperlatives:
    def test_best(self):
        claims = extract_superlatives("The best solution on the market.")
        assert len(claims) == 1
        assert claims[0].claim_text == "best"
        assert claims[0].claim_type == ExtractedClaimType.SUPERLATIVE

    def test_industry_leading(self):
        claims = extract_superlatives("Our industry-leading platform.")
        assert len(claims) == 1
        assert claims[0].claim_text == "industry-leading"

    def test_case_insensitive(self):
        claims = extract_superlatives("The FASTEST engine available.")
        assert len(claims) == 1
        assert claims[0].claim_text == "fastest"

    def test_multiple_superlatives(self):
        claims = extract_superlatives("The best and most advanced product.")
        texts = [c.claim_text for c in claims]
        assert "best" in texts
        assert "most" in texts

    def test_no_superlatives(self):
        assert extract_superlatives("A reliable and consistent product.") == []


class TestExtractAllClaims:
    def test_empty_returns_empty(self):
        assert extract_all_claims("") == []

    def test_whitespace_only_returns_empty(self):
        assert extract_all_claims("   \n\n   ") == []

    def test_combined_extraction(self):
        md = (
            "integrates with Salesforce and we are GDPR compliant.\n\n"
            "Delivers 99.9% uptime. The best platform available."
        )
        claims = extract_all_claims(md)
        types = {c.claim_type for c in claims}
        assert ExtractedClaimType.INTEGRATION in types
        assert ExtractedClaimType.COMPLIANCE in types
        assert ExtractedClaimType.PERFORMANCE in types
        assert ExtractedClaimType.SUPERLATIVE in types

    def test_no_claims_returns_empty(self):
        assert extract_all_claims("A simple paragraph with no claims.") == []

    def test_order_integration_then_compliance_then_performance_then_superlatives(self):
        md = "best platform. integrates with Stripe. GDPR. 99ms response."
        claims = extract_all_claims(md)
        types_in_order = [c.claim_type for c in claims]
        # Integration before Compliance before Performance before Superlatives
        int_idx = next(i for i, t in enumerate(types_in_order) if t == ExtractedClaimType.INTEGRATION)
        comp_idx = next(i for i, t in enumerate(types_in_order) if t == ExtractedClaimType.COMPLIANCE)
        perf_idx = next(i for i, t in enumerate(types_in_order) if t == ExtractedClaimType.PERFORMANCE)
        sup_idx = next(i for i, t in enumerate(types_in_order) if t == ExtractedClaimType.SUPERLATIVE)
        assert int_idx < comp_idx < perf_idx < sup_idx


# ===========================================================================
# VALIDATION TESTS (22)
# ===========================================================================


class TestValidateClaimAgainstRegistry:
    # ── Integration ──────────────────────────────────────────────────────────

    def test_valid_integration_claim(self, db):
        _claim(db, "Salesforce CRM integration", ClaimType.INTEGRATION)
        claim = _extracted(ExtractedClaimType.INTEGRATION, "Salesforce")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_blocked is False
        assert result.is_expired is False

    def test_missing_integration_claim_blocks(self, db):
        claim = _extracted(ExtractedClaimType.INTEGRATION, "UnknownApp")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is False
        assert result.is_blocked is True
        assert "UnknownApp" in result.error_message
        assert "Unsupported integration claim" in result.error_message

    def test_expired_integration_claim_is_soft_warning(self, db):
        past = _now() - timedelta(days=30)
        _claim(db, "Salesforce integration", ClaimType.INTEGRATION, expiry_date=past)
        claim = _extracted(ExtractedClaimType.INTEGRATION, "Salesforce")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True   # soft warning, not blocked
        assert result.is_blocked is False
        assert result.is_expired is True

    def test_future_expiry_integration_claim_is_valid(self, db):
        future = _now() + timedelta(days=30)
        _claim(db, "Stripe payment integration", ClaimType.INTEGRATION, expiry_date=future)
        claim = _extracted(ExtractedClaimType.INTEGRATION, "Stripe")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_expired is False

    # ── Compliance ───────────────────────────────────────────────────────────

    def test_valid_compliance_claim(self, db):
        _claim(db, "GDPR compliance certification", ClaimType.COMPLIANCE)
        claim = _extracted(ExtractedClaimType.COMPLIANCE, "GDPR")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_blocked is False

    def test_missing_compliance_claim_blocks(self, db):
        claim = _extracted(ExtractedClaimType.COMPLIANCE, "SOC 2")
        result = validate_claim_against_registry(db, claim)
        assert result.is_blocked is True
        assert "Unsupported compliance claim" in result.error_message

    def test_expired_compliance_claim_is_soft_warning(self, db):
        past = _now() - timedelta(days=1)
        _claim(db, "HIPAA compliance", ClaimType.COMPLIANCE, expiry_date=past)
        claim = _extracted(ExtractedClaimType.COMPLIANCE, "HIPAA")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_expired is True
        assert result.is_blocked is False

    # ── Performance ──────────────────────────────────────────────────────────

    def test_valid_performance_claim(self, db):
        _claim(db, "99.9% uptime SLA", ClaimType.PERFORMANCE)
        claim = _extracted(ExtractedClaimType.PERFORMANCE, "99.9%")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_blocked is False

    def test_missing_performance_claim_blocks(self, db):
        claim = _extracted(ExtractedClaimType.PERFORMANCE, "50ms")
        result = validate_claim_against_registry(db, claim)
        assert result.is_blocked is True
        assert "Unsupported performance claim" in result.error_message
        assert "50ms" in result.error_message

    def test_expired_performance_claim_is_soft_warning(self, db):
        past = _now() - timedelta(hours=1)
        _claim(db, "50ms response time", ClaimType.PERFORMANCE, expiry_date=past)
        claim = _extracted(ExtractedClaimType.PERFORMANCE, "50ms")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True
        assert result.is_expired is True

    def test_case_insensitive_registry_match(self, db):
        _claim(db, "GDPR Compliance Certificate", ClaimType.COMPLIANCE)
        claim = _extracted(ExtractedClaimType.COMPLIANCE, "gdpr")
        result = validate_claim_against_registry(db, claim)
        assert result.is_valid is True


class TestValidateSuperlatives:
    def test_superlative_without_performance_metric_is_blocked(self):
        md = "The best solution available for enterprises."
        results = validate_superlatives(md, performance_claims=[])
        assert len(results) == 1
        assert results[0].is_blocked is True
        assert "best" in results[0].error_message
        assert "supporting performance data" in results[0].error_message

    def test_superlative_with_metric_same_paragraph_passes(self):
        # Both superlative and metric in paragraph 1
        md = "The fastest platform with 50ms response time."
        perf_claims = [_extracted(ExtractedClaimType.PERFORMANCE, "50ms", "paragraph 1, line 1")]
        results = validate_superlatives(md, performance_claims=perf_claims)
        assert len(results) == 1
        assert results[0].is_valid is True
        assert results[0].is_blocked is False

    def test_superlative_with_metric_adjacent_paragraph_passes(self):
        # Superlative in paragraph 1, metric in paragraph 2
        md = "The best solution.\n\nAchieves 99.9% uptime."
        perf_claims = [_extracted(ExtractedClaimType.PERFORMANCE, "99.9%", "paragraph 2, line 1")]
        results = validate_superlatives(md, performance_claims=perf_claims)
        assert len(results) >= 1
        # All superlatives should pass (adjacent paragraph)
        assert all(r.is_valid for r in results)

    def test_superlative_two_paragraphs_away_is_blocked(self):
        # Superlative in paragraph 1, metric in paragraph 3 → not adjacent to para 1
        md = "The best solution.\n\nSome other text.\n\n99.9% uptime."
        perf_claims = [_extracted(ExtractedClaimType.PERFORMANCE, "99.9%", "paragraph 3, line 1")]
        results = validate_superlatives(md, performance_claims=perf_claims)
        assert len(results) >= 1
        blocked = [r for r in results if r.is_blocked]
        assert len(blocked) >= 1

    def test_no_superlatives_returns_empty(self):
        md = "A reliable and consistent product."
        results = validate_superlatives(md, performance_claims=[])
        assert results == []

    def test_multiple_superlatives_all_blocked_without_metrics(self):
        md = "The best and fastest and most advanced tool."
        results = validate_superlatives(md, performance_claims=[])
        assert all(r.is_blocked for r in results)
        assert len(results) >= 2


class TestValidateDraftClaims:
    def test_document_not_found_raises(self, db):
        with pytest.raises(NotFoundError, match="not found"):
            validate_draft_claims(db, "00000000-0000-0000-0000-000000000000")

    def test_no_draft_raises(self, db):
        doc = _doc(db)
        db.commit()
        with pytest.raises(NotFoundError, match="No draft found"):
            validate_draft_claims(db, doc.id)

    def test_empty_draft_passes(self, db):
        doc = _doc(db)
        _draft(db, doc.id, "   ")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.total_claims == 0
        assert report.is_valid is True

    def test_all_valid_claims_pass(self, db):
        _claim(db, "Salesforce CRM integration", ClaimType.INTEGRATION)
        doc = _doc(db)
        _draft(db, doc.id, "integrates with Salesforce.")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is True
        assert report.blocked_claims == 0

    def test_unsupported_claim_blocks_document(self, db):
        doc = _doc(db)
        _draft(db, doc.id, "integrates with UnknownSystem.")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is False
        assert report.blocked_claims >= 1
        # Verify document status changed in DB
        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED

    def test_expired_claim_is_warning_not_blocked(self, db):
        past = _now() - timedelta(days=7)
        _claim(db, "GDPR compliance", ClaimType.COMPLIANCE, expiry_date=past)
        doc = _doc(db)
        _draft(db, doc.id, "We are GDPR compliant.")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is True
        assert report.warnings == 1
        assert report.blocked_claims == 0
        db.refresh(doc)
        assert doc.status != DocumentStatus.BLOCKED

    def test_validation_report_persisted_to_documents_table(self, db):
        _claim(db, "Salesforce CRM", ClaimType.INTEGRATION)
        doc = _doc(db)
        _draft(db, doc.id, "integrates with Salesforce.")
        db.commit()
        validate_draft_claims(db, doc.id)
        db.refresh(doc)
        assert doc.validation_report is not None
        assert "results" in doc.validation_report
        assert "is_valid" in doc.validation_report

    def test_audit_log_created_on_pass(self, db):
        _claim(db, "Salesforce", ClaimType.INTEGRATION)
        doc = _doc(db)
        _draft(db, doc.id, "integrates with Salesforce.")
        db.commit()
        validate_draft_claims(db, doc.id)
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) >= 1
        assert any("claim validation" in log.action for log in logs)

    def test_audit_log_created_on_block(self, db):
        doc = _doc(db)
        _draft(db, doc.id, "integrates with UnknownSystem.")
        db.commit()
        validate_draft_claims(db, doc.id)
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert any("BLOCKED" in log.action for log in logs)

    def test_multiple_claims_one_invalid_blocks_entire_doc(self, db):
        _claim(db, "Salesforce CRM", ClaimType.INTEGRATION)
        _claim(db, "GDPR compliance certificate", ClaimType.COMPLIANCE)
        # HIPAA is not in registry → should block
        doc = _doc(db)
        _draft(
            db,
            doc.id,
            "integrates with Salesforce and is GDPR compliant.\n\nAlso HIPAA compliant.",
        )
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is False
        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED

    def test_superlative_without_metric_blocks_doc(self, db):
        doc = _doc(db)
        _draft(db, doc.id, "The best platform for enterprises.")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is False
        db.refresh(doc)
        assert doc.status == DocumentStatus.BLOCKED

    def test_superlative_with_metric_same_paragraph_passes(self, db):
        _claim(db, "99.9% uptime SLA", ClaimType.PERFORMANCE)
        doc = _doc(db)
        _draft(db, doc.id, "The best platform with 99.9% uptime guaranteed.")
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.is_valid is True

    def test_uses_latest_draft_iteration(self, db):
        # Old draft has unsupported claim; new draft is clean
        _claim(db, "GDPR compliance", ClaimType.COMPLIANCE)
        doc = _doc(db)
        _draft(db, doc.id, "integrates with UnknownSystem.", iteration=1)
        _draft(db, doc.id, "We are GDPR compliant.", iteration=2)
        db.commit()
        report = validate_draft_claims(db, doc.id)
        # Should validate iteration 2 (GDPR only → passes)
        assert report.is_valid is True

    def test_report_counts_are_accurate(self, db):
        _claim(db, "Salesforce integration", ClaimType.INTEGRATION)
        past = _now() - timedelta(days=1)
        _claim(db, "GDPR compliance", ClaimType.COMPLIANCE, expiry_date=past)
        # HIPAA not in registry → blocked
        doc = _doc(db)
        _draft(
            db,
            doc.id,
            "integrates with Salesforce.\n\nGDPR and HIPAA compliant.",
        )
        db.commit()
        report = validate_draft_claims(db, doc.id)
        assert report.total_claims == 3        # Salesforce(valid), GDPR(expired), HIPAA(blocked)
        assert report.valid_claims == 1        # Salesforce
        assert report.warnings == 1            # GDPR expired
        assert report.blocked_claims == 1      # HIPAA missing
        assert report.is_valid is False

    def test_transaction_rollback_on_commit_error(self, db, monkeypatch):
        _claim(db, "Salesforce", ClaimType.INTEGRATION)
        doc = _doc(db)
        _draft(db, doc.id, "integrates with Salesforce.")
        db.commit()

        original_commit = db.commit

        def _fail_commit():
            raise RuntimeError("simulated DB commit failure")

        monkeypatch.setattr(db, "commit", _fail_commit)

        with pytest.raises(RuntimeError, match="simulated DB commit failure"):
            validate_draft_claims(db, doc.id)

        # Restore commit so we can query
        monkeypatch.setattr(db, "commit", original_commit)
        db.rollback()

        # Document status should be unchanged after rollback
        db.refresh(doc)
        assert doc.status == DocumentStatus.VALIDATING
        # No audit log should have been persisted
        logs = db.query(AuditLog).filter(AuditLog.document_id == doc.id).all()
        assert len(logs) == 0
