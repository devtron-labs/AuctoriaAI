"""
Admin API routes for system settings management.

Prefix: /api/v1/admin
Endpoints:
  GET  /admin/settings              — Retrieve current settings
  PUT  /admin/settings              — Update settings (validated + rate-limited)
  POST /admin/settings/test-webhook — Fire a test POST to the configured webhook URL

Security note:
  Authentication is intentionally omitted (the app has no auth layer yet).
  The dependency `_require_admin` is a placeholder stub that logs and passes through.
  Replace it with a real JWT/session check when the auth system is added.

Governance safety rules enforced:
  - QA threshold floor: 5.0 (prevents trivially low quality bar)
  - Governance must be >= QA threshold (prevents governance bypass)
  - Rate limit: 5 updates per hour (prevents runaway mutations)
  - Confirm-dialog and audit trail via updated_by field
"""

import logging
from typing import Any

import httpx
from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import SystemSettings
from app.schemas.schemas import KNOWN_LLM_MODELS, SystemSettingsResponse, SystemSettingsUpdate
from app.services import settings_service

logger = logging.getLogger(__name__)

admin_router = APIRouter(prefix="/admin", tags=["Admin — System Settings"])

_WEBHOOK_TEST_TIMEOUT_SECONDS: float = 5.0

_API_KEY_FIELDS = (
    "anthropic_api_key", "openai_api_key",
    "google_api_key", "perplexity_api_key", "xai_api_key",
)


def _mask_key(value: str | None) -> str | None:
    """Return last-4 masked representation, or None if unset."""
    if not value:
        return None
    if len(value) <= 4:
        return "****"
    return "****" + value[-4:]


# ---------------------------------------------------------------------------
# Auth placeholder — replace with real JWT dependency when auth is added
# ---------------------------------------------------------------------------

def _require_admin(request: Request) -> None:  # noqa: ARG001
    """Placeholder admin guard. Wire up real auth here when the auth system is ready.

    In production, validate the JWT/session token and confirm the user has the
    'admin' role. For now this is a no-op that allows all requests through.
    """
    logger.debug("Admin endpoint accessed from %s", request.client)


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@admin_router.get(
    "/settings",
    response_model=SystemSettingsResponse,
    summary="Get current system settings",
)
def get_system_settings(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
) -> SystemSettingsResponse:
    """Return the current admin-configurable system settings.

    The response includes all configurable parameters along with the timestamp
    and name of the last admin who made a change. API keys are masked.
    """
    row = db.query(SystemSettings).first()
    if row is None:
        raise HTTPException(status_code=404, detail="System settings row not found.")
    data = SystemSettingsResponse.model_validate(row).model_dump()
    for field in _API_KEY_FIELDS:
        data[field] = _mask_key(data.get(field))
    return SystemSettingsResponse(**data)


@admin_router.get(
    "/settings/available-models",
    summary="List known Claude models available for selection",
)
def get_available_models() -> list[dict[str, str]]:
    """Return the curated list of known Claude models with display labels.

    Admins may still supply a custom model ID not in this list via the UI.
    This list is informational only — it does not restrict what can be saved.
    """
    return KNOWN_LLM_MODELS


@admin_router.put(
    "/settings",
    response_model=SystemSettingsResponse,
    summary="Update system settings",
)
def update_system_settings(
    payload: SystemSettingsUpdate,
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
) -> SystemSettings:
    """Update admin-configurable system settings.

    All changes take effect on the next request (cache TTL: 60 s).

    Validation rules (enforced by Pydantic before the DB write):
    - registry_staleness_hours  : >= 1
    - llm_model_name/qa_llm_model: must be 'claude-opus-4-6' or 'claude-sonnet-4-6'
    - max_draft_length          : 1 000 – 100 000 characters
    - qa_passing_threshold      : 5.0 – 10.0 (safety floor)
    - max_qa_iterations         : >= 1
    - governance_score_threshold: 0.0 – 10.0, must be >= qa_passing_threshold
    - notification_webhook_url  : valid HTTP/HTTPS URL or empty string
    - updated_by                : non-empty name of the admin making the change

    Returns HTTP 429 if the rate limit (5 updates/hour) is exceeded.
    """
    updated_by = payload.updated_by
    # Exclude updated_by from the DB field map — it's stored separately.
    # exclude_none=True ensures API key fields that are None (not provided by the caller)
    # do not overwrite existing DB values. An empty string "" is included (clears the key).
    update_data = payload.model_dump(exclude={"updated_by"}, exclude_none=True)

    try:
        row = settings_service.update_settings(db, update_data, updated_by)
    except ValueError as exc:
        # Rate limit exceeded
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("Settings update failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to persist settings update.",
        ) from exc

    logger.info(
        "Admin settings updated: updated_by=%s llm=%s qa_threshold=%.1f gov_threshold=%.1f",
        updated_by,
        row.llm_model_name,
        row.qa_passing_threshold,
        row.governance_score_threshold,
    )
    return row


@admin_router.post(
    "/settings/test-webhook",
    summary="Send a test notification to the configured webhook URL",
)
def test_webhook(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
) -> dict[str, Any]:
    """Fire a test POST to the currently configured notification webhook URL.

    Returns:
        { "success": true, "status_code": 200, "webhook_url": "..." }   on HTTP success
        { "success": false, "error": "...", "webhook_url": "..." }       on any failure

    Returns HTTP 422 if no webhook URL is currently configured.
    """
    active = settings_service.get_settings(db)
    webhook_url = active.notification_webhook_url

    if not webhook_url:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="No webhook URL is configured. Set notification_webhook_url in settings first.",
        )

    test_payload: dict[str, Any] = {
        "event": "webhook.test",
        "source": "VeritasAI Admin Panel",
        "message": (
            "This is a test notification from VeritasAI. "
            "If you receive this, your webhook endpoint is correctly configured."
        ),
    }

    try:
        response = httpx.post(
            webhook_url,
            json=test_payload,
            timeout=_WEBHOOK_TEST_TIMEOUT_SECONDS,
        )
        success = response.is_success
        result: dict[str, Any] = {
            "success": success,
            "status_code": response.status_code,
            "webhook_url": webhook_url,
        }
        if not success:
            result["response_body"] = response.text[:200]
        return result
    except Exception as exc:
        logger.warning("Webhook test failed: url=%s error=%s", webhook_url, exc)
        return {
            "success": False,
            "error": str(exc),
            "webhook_url": webhook_url,
        }
