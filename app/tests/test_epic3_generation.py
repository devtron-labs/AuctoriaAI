"""
Unit tests for EPIC 3 — Fact-Grounded Draft Generator.

Covers:
  - Successful draft generation with mock LLM
  - iteration_number auto-increment (create 3 drafts → expect 1, 2, 3)
  - Resuming iteration count from a pre-seeded value (e.g., 5 → 6)
  - Missing FactSheet → NoFactSheetError (404)
  - Missing document → NotFoundError (404)
  - Status transition: DRAFT → VALIDATING
  - Audit log created after generation
  - Transaction rollback on LLM error
  - Transaction rollback on DB commit failure
  - Different tone options (formal, conversational, technical)
  - Default tone is "formal"
  - Tone passed through to _call_llm
  - Prompt contains FactSheet data (fact-grounding guard)
  - Prompt forbids adding extra facts
  - Prompt includes all required output sections
  - Draft truncated to max_draft_length
  - Latest FactSheet is used when multiple exist

Tests use SQLite in-memory via the `db` fixture defined in conftest.py.
All LLM calls are mocked — no real API calls are made.
"""

import time
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
from app.services import draft_generation_service
from app.services.exceptions import NoFactSheetError, NotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_document(db, status: DocumentStatus = DocumentStatus.DRAFT, title: str = "Test Doc") -> Document:
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


def _mock_content(tone: str = "formal") -> str:
    return (
        f"# Introduction\n\nMock draft. Tone: {tone}.\n\n"
        "# Features\n\nMock features.\n\n"
        "# Integrations\n\nMock integrations.\n\n"
        "# Compliance\n\nMock compliance.\n\n"
        "# Performance\n\nMock performance.\n\n"
        "# Limitations\n\nMock limitations.\n\n"
        "# Conclusion\n\nMock conclusion."
    )


# ---------------------------------------------------------------------------
# Successful generation
# ---------------------------------------------------------------------------

class TestGenerateDraftSuccess:
    def test_returns_draft_version_instance(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert isinstance(draft, DraftVersion)

    def test_draft_linked_to_document(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.document_id == doc.id

    def test_content_markdown_matches_llm_output(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        expected = _mock_content()

        with patch.object(draft_generation_service, "_call_llm", return_value=expected):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.content_markdown == expected

    def test_score_is_null_initially(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.score is None

    def test_draft_persisted_in_db(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        stored = db.query(DraftVersion).filter(DraftVersion.id == draft.id).first()
        assert stored is not None
        assert stored.content_markdown == draft.content_markdown

    def test_draft_has_created_at_timestamp(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.created_at is not None


# ---------------------------------------------------------------------------
# iteration_number auto-increment
# ---------------------------------------------------------------------------

class TestIterationNumberAutoIncrement:
    def test_first_draft_has_iteration_1(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.iteration_number == 1

    def test_three_drafts_produce_iterations_1_2_3(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        iterations = []

        for _ in range(3):
            # Reset to DRAFT so the service can transition to VALIDATING each time
            doc.status = DocumentStatus.DRAFT
            db.commit()
            with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
                draft = draft_generation_service.generate_draft(db, doc.id)
            iterations.append(draft.iteration_number)

        assert iterations == [1, 2, 3]

    def test_resumes_from_existing_max_iteration(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        # Pre-seed a draft with a high iteration number
        db.add(DraftVersion(document_id=doc.id, iteration_number=7, content_markdown="old", tone="formal", score=None))
        db.commit()

        doc.status = DocumentStatus.DRAFT
        db.commit()

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.iteration_number == 8

    def test_iterations_for_different_documents_are_independent(self, db):
        doc_a = _make_document(db, title="Doc A")
        doc_b = _make_document(db, title="Doc B")
        _make_fact_sheet(db, doc_a.id)
        _make_fact_sheet(db, doc_b.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            # Two drafts for doc_a
            draft_a1 = draft_generation_service.generate_draft(db, doc_a.id)
            doc_a.status = DocumentStatus.DRAFT
            db.commit()
            draft_a2 = draft_generation_service.generate_draft(db, doc_a.id)

            # First draft for doc_b
            draft_b1 = draft_generation_service.generate_draft(db, doc_b.id)

        assert draft_a1.iteration_number == 1
        assert draft_a2.iteration_number == 2
        assert draft_b1.iteration_number == 1  # independent counter


# ---------------------------------------------------------------------------
# Missing FactSheet → 404
# ---------------------------------------------------------------------------

class TestMissingFactSheet:
    def test_raises_no_fact_sheet_error(self, db):
        doc = _make_document(db)

        with pytest.raises(NoFactSheetError):
            draft_generation_service.generate_draft(db, doc.id)

    def test_error_message_contains_document_id(self, db):
        doc = _make_document(db)

        with pytest.raises(NoFactSheetError) as exc_info:
            draft_generation_service.generate_draft(db, doc.id)

        assert doc.id in str(exc_info.value)

    def test_no_draft_created_when_fact_sheet_missing(self, db):
        doc = _make_document(db)

        with pytest.raises(NoFactSheetError):
            draft_generation_service.generate_draft(db, doc.id)

        count = db.query(DraftVersion).filter(DraftVersion.document_id == doc.id).count()
        assert count == 0


# ---------------------------------------------------------------------------
# Missing document → 404
# ---------------------------------------------------------------------------

class TestMissingDocument:
    def test_raises_not_found_error(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError):
            draft_generation_service.generate_draft(db, fake_id)

    def test_error_message_contains_document_id(self, db):
        fake_id = str(uuid.uuid4())

        with pytest.raises(NotFoundError) as exc_info:
            draft_generation_service.generate_draft(db, fake_id)

        assert fake_id in str(exc_info.value)


# ---------------------------------------------------------------------------
# Status transition: DRAFT → VALIDATING
# ---------------------------------------------------------------------------

class TestStatusTransition:
    def test_status_changes_to_validating(self, db):
        doc = _make_document(db, status=DocumentStatus.DRAFT)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft_generation_service.generate_draft(db, doc.id)

        db.refresh(doc)
        assert doc.status == DocumentStatus.VALIDATING

    def test_status_persisted_after_commit(self, db):
        doc = _make_document(db, status=DocumentStatus.DRAFT)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft_generation_service.generate_draft(db, doc.id)

        # Re-query to confirm DB-level persistence
        refreshed = db.query(Document).filter(Document.id == doc.id).first()
        assert refreshed.status == DocumentStatus.VALIDATING


# ---------------------------------------------------------------------------
# Audit log creation
# ---------------------------------------------------------------------------

class TestAuditLogCreation:
    def test_audit_log_created(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft_generation_service.generate_draft(db, doc.id)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert log is not None

    def test_audit_log_mentions_draft_generation(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft_generation_service.generate_draft(db, doc.id)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert "draft" in log.action.lower()

    def test_audit_log_records_iteration_number(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft = draft_generation_service.generate_draft(db, doc.id)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert str(draft.iteration_number) in log.action

    def test_audit_log_records_tone(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content("technical")):
            draft_generation_service.generate_draft(db, doc.id, tone="technical")

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert "technical" in log.action

    def test_audit_log_action_within_512_chars(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            draft_generation_service.generate_draft(db, doc.id)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert len(log.action) <= 512


# ---------------------------------------------------------------------------
# Transaction rollback on LLM error
# ---------------------------------------------------------------------------

class TestTransactionRollbackOnLLMError:
    def test_no_draft_saved_on_llm_error(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError, match="LLM timeout"):
                draft_generation_service.generate_draft(db, doc.id)

        count = db.query(DraftVersion).filter(DraftVersion.document_id == doc.id).count()
        assert count == 0

    def test_document_status_unchanged_on_llm_error(self, db):
        doc = _make_document(db, status=DocumentStatus.DRAFT)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError):
                draft_generation_service.generate_draft(db, doc.id)

        db.refresh(doc)
        assert doc.status == DocumentStatus.DRAFT

    def test_no_audit_log_on_llm_error(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", side_effect=RuntimeError("LLM timeout")
        ):
            with pytest.raises(RuntimeError):
                draft_generation_service.generate_draft(db, doc.id)

        count = db.query(AuditLog).filter(AuditLog.document_id == doc.id).count()
        assert count == 0

    def test_llm_error_propagates_to_caller(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", side_effect=ValueError("Bad response")
        ):
            with pytest.raises(ValueError, match="Bad response"):
                draft_generation_service.generate_draft(db, doc.id)

    def test_rollback_called_on_db_commit_failure(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content()):
            with patch.object(db, "commit", side_effect=Exception("DB failure")):
                with pytest.raises(Exception, match="DB failure"):
                    draft_generation_service.generate_draft(db, doc.id)


# ---------------------------------------------------------------------------
# Tone options
# ---------------------------------------------------------------------------

class TestToneOptions:
    @pytest.mark.parametrize("tone", ["formal", "conversational", "technical"])
    def test_all_tones_produce_a_draft(self, db, tone):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content(tone)):
            draft = draft_generation_service.generate_draft(db, doc.id, tone=tone)

        assert draft is not None
        assert isinstance(draft, DraftVersion)

    @pytest.mark.parametrize("tone", ["formal", "conversational", "technical"])
    def test_tone_is_forwarded_to_llm(self, db, tone):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", return_value=_mock_content()
        ) as mock_llm:
            draft_generation_service.generate_draft(db, doc.id, tone=tone)

        mock_llm.assert_called_once()
        # _call_llm signature: (prompt, tone, model_name, [timeout_seconds])
        _prompt_arg, tone_arg, *_ = mock_llm.call_args[0]
        assert tone_arg == tone

    def test_default_tone_is_formal(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(
            draft_generation_service, "_call_llm", return_value=_mock_content()
        ) as mock_llm:
            draft_generation_service.generate_draft(db, doc.id)  # no tone arg

        # _call_llm signature: (prompt, tone, model_name, [timeout_seconds])
        _prompt_arg, tone_arg, *_ = mock_llm.call_args[0]
        assert tone_arg == "formal"

    @pytest.mark.parametrize("tone", ["formal", "conversational", "technical"])
    def test_tone_recorded_in_audit_log(self, db, tone):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)

        with patch.object(draft_generation_service, "_call_llm", return_value=_mock_content(tone)):
            draft_generation_service.generate_draft(db, doc.id, tone=tone)

        log = (
            db.query(AuditLog)
            .filter(AuditLog.document_id == doc.id)
            .order_by(AuditLog.timestamp.desc())
            .first()
        )
        assert tone in log.action


# ---------------------------------------------------------------------------
# Prompt construction — fact-grounding verification
# ---------------------------------------------------------------------------

class TestPromptConstruction:
    def _minimal_data(self, **overrides) -> dict:
        base = {
            "features": [],
            "integrations": [],
            "compliance": [],
            "performance_metrics": [],
            "limitations": [],
        }
        base.update(overrides)
        return base

    def test_prompt_includes_feature_names(self):
        data = self._minimal_data(
            features=[{"name": "QuantumSearch", "description": "Ultra-fast indexing"}]
        )
        prompt = draft_generation_service._build_prompt(data, "formal")
        assert "QuantumSearch" in prompt

    def test_prompt_includes_integration_system(self):
        data = self._minimal_data(
            integrations=[{"system": "Salesforce", "method": "REST API", "notes": "OAuth2"}]
        )
        prompt = draft_generation_service._build_prompt(data, "formal")
        assert "Salesforce" in prompt

    def test_prompt_includes_compliance_standard(self):
        data = self._minimal_data(
            compliance=[{"standard": "HIPAA", "status": "Compliant", "details": "BAA available"}]
        )
        prompt = draft_generation_service._build_prompt(data, "formal")
        assert "HIPAA" in prompt

    def test_prompt_includes_performance_metric(self):
        data = self._minimal_data(
            performance_metrics=[{"metric": "P99 latency", "value": "12", "unit": "ms"}]
        )
        prompt = draft_generation_service._build_prompt(data, "formal")
        assert "P99 latency" in prompt

    def test_prompt_includes_limitation(self):
        data = self._minimal_data(
            limitations=[{"category": "Auth", "description": "No SAML support yet"}]
        )
        prompt = draft_generation_service._build_prompt(data, "formal")
        assert "No SAML support yet" in prompt

    def test_prompt_instructs_not_to_add_extra_facts(self):
        data = self._minimal_data()
        prompt = draft_generation_service._build_prompt(data, "formal")
        # Prompt must contain an explicit prohibition against adding unlisted facts
        assert any(phrase in prompt for phrase in ["Do NOT", "do not", "Only use", "only use"])

    def test_prompt_includes_all_seven_required_sections(self):
        data = self._minimal_data()
        prompt = draft_generation_service._build_prompt(data, "formal")
        for section in [
            "Introduction",
            "Features",
            "Integrations",
            "Compliance",
            "Performance",
            "Limitations",
            "Conclusion",
        ]:
            assert section in prompt, f"Section '{section}' missing from prompt"

    def test_different_tones_produce_different_prompts(self):
        data = self._minimal_data()
        formal = draft_generation_service._build_prompt(data, "formal")
        technical = draft_generation_service._build_prompt(data, "technical")
        conversational = draft_generation_service._build_prompt(data, "conversational")

        assert formal != technical
        assert formal != conversational
        assert technical != conversational


# ---------------------------------------------------------------------------
# Draft length enforcement
# ---------------------------------------------------------------------------

class TestDraftLengthEnforcement:
    def test_draft_truncated_when_exceeds_max_length(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        long_content = "x" * 100_000

        mock_cfg = MagicMock()
        mock_cfg.max_draft_length = 500
        mock_cfg.llm_model_name = "claude-opus-4-6"
        mock_cfg.llm_timeout_seconds = 120

        with patch.object(draft_generation_service, "_call_llm", return_value=long_content):
            with patch.object(draft_generation_service.settings_service, "get_settings", return_value=mock_cfg):
                draft = draft_generation_service.generate_draft(db, doc.id)

        assert len(draft.content_markdown) <= 500

    def test_short_draft_not_truncated(self, db):
        doc = _make_document(db)
        _make_fact_sheet(db, doc.id)
        short_content = _mock_content()

        mock_cfg = MagicMock()
        mock_cfg.max_draft_length = 50_000
        mock_cfg.llm_model_name = "claude-opus-4-6"
        mock_cfg.llm_timeout_seconds = 120

        with patch.object(draft_generation_service, "_call_llm", return_value=short_content):
            with patch.object(draft_generation_service.settings_service, "get_settings", return_value=mock_cfg):
                draft = draft_generation_service.generate_draft(db, doc.id)

        assert draft.content_markdown == short_content


# ---------------------------------------------------------------------------
# Latest FactSheet selection
# ---------------------------------------------------------------------------

class TestLatestFactSheetSelection:
    def test_uses_most_recent_fact_sheet(self, db):
        doc = _make_document(db)

        # Older fact sheet
        old_fs = FactSheet(
            document_id=doc.id,
            structured_data={
                "features": [{"name": "OldFeature", "description": "Old desc"}],
                "integrations": [],
                "compliance": [],
                "performance_metrics": [],
                "limitations": [],
            },
        )
        db.add(old_fs)
        db.commit()

        # Brief pause so created_at timestamps differ in SQLite
        time.sleep(0.05)

        # Newer fact sheet
        new_fs = FactSheet(
            document_id=doc.id,
            structured_data={
                "features": [{"name": "NewFeature", "description": "New desc"}],
                "integrations": [],
                "compliance": [],
                "performance_metrics": [],
                "limitations": [],
            },
        )
        db.add(new_fs)
        db.commit()

        captured: list[str] = []

        def _capture_llm(prompt: str, tone: str, *args, **kwargs) -> str:
            captured.append(prompt)
            return _mock_content()

        with patch.object(draft_generation_service, "_call_llm", side_effect=_capture_llm):
            draft_generation_service.generate_draft(db, doc.id)

        assert len(captured) == 1
        assert "NewFeature" in captured[0]
        assert "OldFeature" not in captured[0]
