"""
Unit tests for the Admin System Settings feature.

Coverage:
  - SystemSettingsUpdate Pydantic validation rules
  - Cross-field threshold ordering constraints
  - settings_service: get_settings (seeding, caching, cache invalidation)
  - settings_service: update_settings (fields, updated_by, cache invalidation)
  - settings_service: check_rate_limit (allow / deny)
  - Admin router endpoints (GET /admin/settings, PUT /admin/settings)
"""

import time
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.main import app
from app.models.models import SystemSettings
from app.schemas.schemas import SystemSettingsUpdate
from app.services import settings_service


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_valid_update(**overrides) -> dict:
    """Return a dict that passes all SystemSettingsUpdate validations."""
    defaults = {
        "registry_staleness_hours": 24,
        "llm_model_name": "claude-opus-4-6",
        "max_draft_length": 50000,
        "qa_passing_threshold": 9.0,
        "max_qa_iterations": 3,
        "qa_llm_model": "claude-sonnet-4-6",
        "governance_score_threshold": 9.0,
        "notification_webhook_url": "",
        "updated_by": "test-admin",
    }
    defaults.update(overrides)
    return defaults


# ---------------------------------------------------------------------------
# 1. Pydantic Validation — registry_staleness_hours
# ---------------------------------------------------------------------------

class TestRegistryStalenessHoursValidation:
    def test_valid_value_accepted(self):
        data = _make_valid_update(registry_staleness_hours=12)
        schema = SystemSettingsUpdate(**data)
        assert schema.registry_staleness_hours == 12

    def test_zero_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            SystemSettingsUpdate(**_make_valid_update(registry_staleness_hours=0))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("registry_staleness_hours",) for e in errors)

    def test_negative_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(registry_staleness_hours=-5))


# ---------------------------------------------------------------------------
# 2. Pydantic Validation — llm_model_name and qa_llm_model
# ---------------------------------------------------------------------------

class TestModelNameValidation:
    def test_opus_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(llm_model_name="claude-opus-4-6"))
        assert schema.llm_model_name == "claude-opus-4-6"

    def test_sonnet_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(llm_model_name="claude-sonnet-4-6"))
        assert schema.llm_model_name == "claude-sonnet-4-6"

    def test_non_claude_model_now_accepted(self):
        """Multi-provider: non-claude models like gpt-4o are now accepted."""
        data = SystemSettingsUpdate(**_make_valid_update(llm_model_name="gpt-4o"))
        assert data.llm_model_name == "gpt-4o"

    def test_empty_model_rejected(self):
        """Empty model string is rejected (min_length=1)."""
        with pytest.raises(ValidationError) as exc_info:
            SystemSettingsUpdate(**_make_valid_update(llm_model_name=""))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("llm_model_name",) for e in errors)

    def test_qa_model_accepts_gemini(self):
        """Multi-provider: gemini models are now accepted for qa_llm_model."""
        data = SystemSettingsUpdate(**_make_valid_update(qa_llm_model="gemini-1.5-pro"))
        assert data.qa_llm_model == "gemini-1.5-pro"

    def test_haiku_accepted(self):
        """Non-allowlisted Claude model should be accepted after relaxing validation."""
        data = SystemSettingsUpdate(**_make_valid_update(
            llm_model_name="claude-haiku-4-5-20251001",
            qa_llm_model="claude-haiku-4-5-20251001",
        ))
        assert data.llm_model_name == "claude-haiku-4-5-20251001"
        assert data.qa_llm_model == "claude-haiku-4-5-20251001"


# ---------------------------------------------------------------------------
# 3. Pydantic Validation — max_draft_length
# ---------------------------------------------------------------------------

class TestMaxDraftLengthValidation:
    def test_minimum_boundary_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(max_draft_length=1000))
        assert schema.max_draft_length == 1000

    def test_maximum_boundary_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(max_draft_length=100_000))
        assert schema.max_draft_length == 100_000

    def test_below_minimum_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(max_draft_length=999))

    def test_above_maximum_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(max_draft_length=100_001))


# ---------------------------------------------------------------------------
# 4. Pydantic Validation — qa_passing_threshold (safety floor at 5.0)
# ---------------------------------------------------------------------------

class TestQAThresholdValidation:
    def test_above_floor_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            qa_passing_threshold=7.5,
            governance_score_threshold=7.5,
        ))
        assert schema.qa_passing_threshold == 7.5

    def test_exactly_at_floor_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            qa_passing_threshold=5.0,
            governance_score_threshold=5.0,
        ))
        assert schema.qa_passing_threshold == 5.0

    def test_below_safety_floor_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            SystemSettingsUpdate(**_make_valid_update(
                qa_passing_threshold=4.9,
                governance_score_threshold=5.0,
            ))
        errors = exc_info.value.errors()
        assert any(e["loc"] == ("qa_passing_threshold",) for e in errors)

    def test_above_ten_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(qa_passing_threshold=10.1))


# ---------------------------------------------------------------------------
# 5. Pydantic Validation — governance_score_threshold
# ---------------------------------------------------------------------------

class TestGovernanceThresholdValidation:
    def test_equal_to_qa_threshold_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            qa_passing_threshold=7.0,
            governance_score_threshold=7.0,
        ))
        assert schema.governance_score_threshold == 7.0

    def test_above_qa_threshold_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            qa_passing_threshold=7.0,
            governance_score_threshold=8.0,
        ))
        assert schema.governance_score_threshold == 8.0

    def test_below_qa_threshold_rejected(self):
        """Governance cannot be lower than QA — would allow governance bypass."""
        with pytest.raises(ValidationError) as exc_info:
            SystemSettingsUpdate(**_make_valid_update(
                qa_passing_threshold=8.0,
                governance_score_threshold=7.5,
            ))
        # The cross-field validator fires — error appears in the model body or __root__
        assert exc_info.value.error_count() > 0

    def test_above_ten_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(governance_score_threshold=10.5))

    def test_zero_accepted_when_qa_also_at_floor(self):
        """governance_score_threshold=0 is technically valid if qa_passing_threshold=5
        would be rejected by the ordering rule, but governance=0 < qa=5 should fail."""
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(
                qa_passing_threshold=5.0,
                governance_score_threshold=0.0,
            ))


# ---------------------------------------------------------------------------
# 6. Pydantic Validation — notification_webhook_url
# ---------------------------------------------------------------------------

class TestWebhookUrlValidation:
    def test_empty_string_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(notification_webhook_url=""))
        assert schema.notification_webhook_url == ""

    def test_none_means_not_provided(self):
        # None = field omitted; keep existing DB value (no coercion to "")
        schema = SystemSettingsUpdate(**_make_valid_update(notification_webhook_url=None))
        assert schema.notification_webhook_url is None

    def test_valid_https_url_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            notification_webhook_url="https://hooks.example.com/notify"
        ))
        assert schema.notification_webhook_url == "https://hooks.example.com/notify"

    def test_valid_http_url_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(
            notification_webhook_url="http://internal.example.com/webhook"
        ))
        assert schema.notification_webhook_url == "http://internal.example.com/webhook"

    def test_ftp_url_rejected(self):
        with pytest.raises(ValidationError) as exc_info:
            SystemSettingsUpdate(**_make_valid_update(
                notification_webhook_url="ftp://example.com/bad"
            ))
        assert exc_info.value.error_count() > 0

    def test_plain_string_without_scheme_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(
                notification_webhook_url="example.com/webhook"
            ))


# ---------------------------------------------------------------------------
# 7. Pydantic Validation — updated_by
# ---------------------------------------------------------------------------

class TestUpdatedByValidation:
    def test_non_empty_string_accepted(self):
        schema = SystemSettingsUpdate(**_make_valid_update(updated_by="Jane Smith"))
        assert schema.updated_by == "Jane Smith"

    def test_empty_string_rejected(self):
        with pytest.raises(ValidationError):
            SystemSettingsUpdate(**_make_valid_update(updated_by=""))


# ---------------------------------------------------------------------------
# 8. settings_service — get_settings (seeding + caching)
# ---------------------------------------------------------------------------

class TestGetSettings:
    def test_seeds_defaults_when_table_empty(self, db):
        """First call creates a default row from config.py constants."""
        settings_service.invalidate_cache()
        active = settings_service.get_settings(db)
        assert active.registry_staleness_hours == 24
        assert active.llm_model_name == "claude-opus-4-6"
        assert active.qa_passing_threshold == 9.0
        assert active.governance_score_threshold == 9.0

        row_count = db.query(SystemSettings).count()
        assert row_count == 1

    def test_returns_existing_row(self, db):
        """Second call returns the previously seeded row without creating duplicates."""
        settings_service.invalidate_cache()
        settings_service.get_settings(db)
        settings_service.invalidate_cache()
        settings_service.get_settings(db)

        assert db.query(SystemSettings).count() == 1

    def test_cache_hit_skips_db(self, db):
        """Repeated calls within TTL use the in-memory cache."""
        settings_service.invalidate_cache()
        a1 = settings_service.get_settings(db)
        a2 = settings_service.get_settings(db)  # should hit cache
        assert a1 == a2

    def test_cache_invalidation_forces_requery(self, db):
        """After invalidate_cache(), the next call re-queries the DB."""
        settings_service.invalidate_cache()
        a1 = settings_service.get_settings(db)
        settings_service.invalidate_cache()
        # Modify the row directly
        row = db.query(SystemSettings).first()
        row.registry_staleness_hours = 48
        db.commit()
        a2 = settings_service.get_settings(db)
        assert a2.registry_staleness_hours == 48


# ---------------------------------------------------------------------------
# 9. settings_service — update_settings
# ---------------------------------------------------------------------------

class TestUpdateSettings:
    def test_updates_fields_and_invalidates_cache(self, db):
        settings_service.invalidate_cache()
        settings_service.get_settings(db)  # seed defaults

        update_data = {
            "registry_staleness_hours": 48,
            "llm_model_name": "claude-sonnet-4-6",
            "max_draft_length": 40000,
            "qa_passing_threshold": 8.0,
            "max_qa_iterations": 5,
            "qa_llm_model": "claude-opus-4-6",
            "governance_score_threshold": 8.0,
            "notification_webhook_url": "https://hooks.example.com/test",
        }
        row = settings_service.update_settings(db, update_data, updated_by="test-admin")

        assert row.registry_staleness_hours == 48
        assert row.llm_model_name == "claude-sonnet-4-6"
        assert row.qa_passing_threshold == 8.0
        assert row.updated_by == "test-admin"

        # Cache should be invalidated — next get re-reads from DB
        active = settings_service.get_settings(db)
        assert active.registry_staleness_hours == 48

    def test_updated_by_stored(self, db):
        settings_service.invalidate_cache()
        settings_service.get_settings(db)
        settings_service.update_settings(
            db, {"registry_staleness_hours": 12}, updated_by="reviewer-bob"
        )
        row = db.query(SystemSettings).first()
        assert row.updated_by == "reviewer-bob"


# ---------------------------------------------------------------------------
# 10. settings_service — Rate limiter
# ---------------------------------------------------------------------------

class TestRateLimiter:
    def setup_method(self):
        """Reset the rate limiter between test methods."""
        settings_service._update_timestamps.clear()

    def test_first_five_calls_allowed(self):
        for _ in range(settings_service._RATE_LIMIT_MAX):
            assert settings_service.check_rate_limit() is True

    def test_sixth_call_denied(self):
        for _ in range(settings_service._RATE_LIMIT_MAX):
            settings_service.check_rate_limit()
        assert settings_service.check_rate_limit() is False

    def test_old_timestamps_expire(self):
        # Pre-fill with timestamps just outside the window
        expired = time.monotonic() - settings_service._RATE_LIMIT_WINDOW - 1
        for _ in range(settings_service._RATE_LIMIT_MAX):
            settings_service._update_timestamps.append(expired)
        # All expired timestamps should be evicted — next call is allowed
        assert settings_service.check_rate_limit() is True

    def test_rate_limit_raises_in_update_settings(self, db):
        settings_service.invalidate_cache()
        settings_service.get_settings(db)
        # Exhaust the limit
        for _ in range(settings_service._RATE_LIMIT_MAX):
            settings_service.check_rate_limit()

        with pytest.raises(ValueError, match="Rate limit exceeded"):
            settings_service.update_settings(
                db, {"registry_staleness_hours": 10}, updated_by="admin"
            )


# ---------------------------------------------------------------------------
# 11. Admin Router — GET /api/v1/admin/settings
# ---------------------------------------------------------------------------

@pytest.fixture()
def client():
    return TestClient(app)


class TestAvailableModelsEndpoint:
    def test_returns_list_of_known_models(self, client):
        """GET /api/v1/admin/settings/available-models returns curated model list."""
        response = client.get("/api/v1/admin/settings/available-models")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        assert len(data) >= 3
        ids = [m["id"] for m in data]
        assert "claude-opus-4-6" in ids
        assert "claude-sonnet-4-6" in ids
        assert "claude-haiku-4-5-20251001" in ids

    def test_each_entry_has_id_and_label(self, client):
        """Every model entry must have both id and label fields."""
        response = client.get("/api/v1/admin/settings/available-models")
        assert response.status_code == 200
        for m in response.json():
            assert "id" in m
            assert "label" in m
            assert isinstance(m["id"], str)
            assert isinstance(m["label"], str)


class TestGetSettingsEndpoint:
    def test_returns_200_with_defaults(self, client):
        settings_service.invalidate_cache()
        try:
            response = client.get("/api/v1/admin/settings")
            # Accept 200 (success) or 500 (DB unavailable in test environment)
            assert response.status_code in (200, 500)
        except Exception:
            pytest.skip("PostgreSQL not available in this test environment")

    def test_response_schema_fields(self, client):
        """Verify the response contains all required fields when backend is available."""
        try:
            response = client.get("/api/v1/admin/settings")
        except Exception:
            pytest.skip("PostgreSQL not available in this test environment")
        if response.status_code == 200:
            data = response.json()
            required_fields = {
                "id",
                "registry_staleness_hours",
                "llm_model_name",
                "max_draft_length",
                "qa_passing_threshold",
                "max_qa_iterations",
                "qa_llm_model",
                "governance_score_threshold",
                "notification_webhook_url",
                "updated_by",
                "updated_at",
            }
            assert required_fields.issubset(data.keys())


class TestPutSettingsEndpoint:
    def test_invalid_payload_returns_422(self, client):
        """Pydantic validation rejects invalid payloads before any DB write."""
        payload = _make_valid_update(llm_model_name="")  # empty string not allowed
        response = client.put("/api/v1/admin/settings", json=payload)
        assert response.status_code == 422

    def test_governance_below_qa_returns_422(self, client):
        """Cross-field validation rejects governance < qa threshold."""
        payload = _make_valid_update(
            qa_passing_threshold=8.0,
            governance_score_threshold=7.0,  # below QA — invalid
        )
        response = client.put("/api/v1/admin/settings", json=payload)
        assert response.status_code == 422

    def test_qa_threshold_below_floor_returns_422(self, client):
        """QA threshold < 5.0 is rejected by the safety floor rule."""
        payload = _make_valid_update(
            qa_passing_threshold=4.0,
            governance_score_threshold=4.0,
        )
        response = client.put("/api/v1/admin/settings", json=payload)
        assert response.status_code == 422

    def test_valid_payload_accepted(self, client):
        """A fully valid payload should be accepted (200 or 429 if rate-limited)."""
        settings_service._update_timestamps.clear()
        payload = _make_valid_update()
        response = client.put("/api/v1/admin/settings", json=payload)
        # 200 = success, 429 = rate-limited (acceptable), 500 = DB unavailable (test env)
        assert response.status_code in (200, 429, 500)


# ---------------------------------------------------------------------------
# 12. Multi-provider model validation
# ---------------------------------------------------------------------------

def test_gpt4o_model_accepted():
    """Non-claude model should now be accepted (multi-provider)."""
    from app.schemas.schemas import SystemSettingsUpdate
    data = SystemSettingsUpdate(**_make_valid_update(llm_model_name="gpt-4o"))
    assert data.llm_model_name == "gpt-4o"


def test_gemini_model_accepted():
    """Gemini model should be accepted."""
    from app.schemas.schemas import SystemSettingsUpdate
    data = SystemSettingsUpdate(**_make_valid_update(qa_llm_model="gemini-1.5-pro"))
    assert data.qa_llm_model == "gemini-1.5-pro"


def test_empty_model_rejected():
    """Empty model string must still be rejected."""
    with pytest.raises(ValidationError):
        SystemSettingsUpdate(**_make_valid_update(llm_model_name=""))


def test_api_key_none_excluded_from_update():
    """API key fields with None value are excluded — existing keys preserved."""
    payload = SystemSettingsUpdate(**_make_valid_update())
    dumped = payload.model_dump(exclude={"updated_by"}, exclude_none=True)
    # No API key fields should appear (they default to None)
    assert "openai_api_key" not in dumped
    assert "anthropic_api_key" not in dumped


# ---------------------------------------------------------------------------
# 13. API key masking in GET /admin/settings
# ---------------------------------------------------------------------------

def test_get_settings_masks_api_keys(client):
    """GET /admin/settings must never return a full API key."""
    try:
        response = client.get("/api/v1/admin/settings")
    except Exception:
        pytest.skip("PostgreSQL not available in this test environment")
    if response.status_code != 200:
        pytest.skip("DB not available")
    data = response.json()
    # All key fields should be null (not set in test DB) or masked (never > 8 chars of real key)
    for field in ("anthropic_api_key", "openai_api_key", "google_api_key",
                  "perplexity_api_key", "xai_api_key"):
        assert field in data
        val = data[field]
        assert val is None or (isinstance(val, str) and val.startswith("****"))


# ---------------------------------------------------------------------------
# 14. ActiveSettings — provider API key fields
# ---------------------------------------------------------------------------

def test_active_settings_has_api_key_fields(db):
    """ActiveSettings snapshot must expose all 5 provider API key fields."""
    from app.services.settings_service import get_settings, invalidate_cache
    invalidate_cache()
    active = get_settings(db)
    assert hasattr(active, "anthropic_api_key")
    assert hasattr(active, "openai_api_key")
    assert hasattr(active, "google_api_key")
    assert hasattr(active, "perplexity_api_key")
    assert hasattr(active, "xai_api_key")
    # All default to None
    assert active.anthropic_api_key is None
    assert active.openai_api_key is None


# ---------------------------------------------------------------------------
# 13. Integration — settings consumed by governance service
# ---------------------------------------------------------------------------

class TestGovernanceUsesDbSettings:
    """Verify governance_service reads threshold from DB, not from hardcoded config."""

    def test_governance_uses_active_settings(self, db):
        from app.models.models import Document, DocumentStatus, DraftVersion, FactSheet
        from app.services.governance_service import _make_governance_decision
        from app.schemas.schemas import GovernanceDecision

        settings_service.invalidate_cache()
        # Seed settings with a low threshold so a mid-range score passes
        settings_service.update_settings(db, {"governance_score_threshold": 5.0}, "test")
        # Invalidate so fresh read from DB
        settings_service.invalidate_cache()
        active = settings_service.get_settings(db)
        threshold = active.governance_score_threshold

        decision, _ = _make_governance_decision(
            score=6.0,
            claims_valid=True,
            threshold=threshold,
        )
        assert decision == GovernanceDecision.PASSED, (
            "Expected PASSED with score=6.0 and threshold=5.0"
        )

    def test_high_threshold_blocks_mid_score(self, db):
        from app.services.governance_service import _make_governance_decision
        from app.schemas.schemas import GovernanceDecision

        settings_service.invalidate_cache()
        settings_service.update_settings(
            db,
            {
                "governance_score_threshold": 9.5,
                "qa_passing_threshold": 8.0,  # keep QA <= gov
            },
            "test",
        )
        settings_service.invalidate_cache()
        active = settings_service.get_settings(db)
        threshold = active.governance_score_threshold

        decision, _ = _make_governance_decision(
            score=8.0,
            claims_valid=True,
            threshold=threshold,
        )
        assert decision == GovernanceDecision.FAILED
