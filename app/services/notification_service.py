"""
Notification service for EPIC 7 — Human Review & Approval.

Sends webhook notifications on document approval and rejection.
Notifications are best-effort: failures are logged as warnings and never
propagate to the caller, so a misconfigured or unavailable webhook never
blocks a review operation.

Configuration:
    The webhook URL is now fetched dynamically from system_settings DB table
    (via settings_service) by the caller (review_service) and passed explicitly
    as the ``webhook_url`` parameter. This allows admin-configurable webhook URLs
    without redeploying the application.

    Pass an empty string (or None) to disable all notifications.

Webhook payload schema (JSON POST body):
    {
        "event":       "document.approved" | "document.rejected",
        "document_id": "<uuid>",
        "reviewer":    "<reviewer_name>",
        "timestamp":   "<ISO-8601 UTC string>",
        "details":     { ... event-specific fields ... }
    }
"""

import logging
from datetime import datetime
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

_WEBHOOK_TIMEOUT_SECONDS = 5.0


def _send_webhook(payload: dict[str, Any], webhook_url: str) -> None:
    """POST ``payload`` as JSON to the given webhook URL.

    Fails silently: any network or HTTP error is caught, logged as a warning,
    and swallowed so the caller is never affected.

    Args:
        payload:     JSON-serialisable dict to send in the request body.
        webhook_url: The target URL. If empty, returns immediately (disabled).
    """
    if not webhook_url:
        return  # Notifications disabled

    try:
        response = httpx.post(webhook_url, json=payload, timeout=_WEBHOOK_TIMEOUT_SECONDS)
        if response.is_success:
            logger.info(
                "Webhook notification sent: event=%s status=%d",
                payload.get("event"),
                response.status_code,
            )
        else:
            logger.warning(
                "Webhook notification returned non-2xx status: event=%s status=%d body=%s",
                payload.get("event"),
                response.status_code,
                response.text[:200],
            )
    except Exception as exc:
        logger.warning(
            "Webhook notification failed (non-fatal): event=%s error=%s",
            payload.get("event"),
            exc,
        )


def notify_approved(
    document_id: str,
    reviewer_name: str,
    reviewed_at: datetime,
    force_approved: bool,
    notes: Optional[str],
    webhook_url: str = "",
) -> None:
    """Send a webhook notification for a document approval.

    Args:
        document_id:    UUID of the approved document.
        reviewer_name:  Name of the approving reviewer.
        reviewed_at:    UTC timestamp of the approval decision.
        force_approved: True if an admin force-approve override was used.
        notes:          Optional approval notes.
        webhook_url:    Webhook target URL (fetched from DB settings by the caller).
                        Pass empty string to skip (notifications disabled).
    """
    payload: dict[str, Any] = {
        "event": "document.approved",
        "document_id": document_id,
        "reviewer": reviewer_name,
        "timestamp": reviewed_at.isoformat(),
        "details": {
            "force_approved": force_approved,
            "notes": notes,
        },
    }
    _send_webhook(payload, webhook_url)


def notify_rejected(
    document_id: str,
    reviewer_name: str,
    reviewed_at: datetime,
    rejection_reason: str,
    suggested_action: Optional[str],
    webhook_url: str = "",
) -> None:
    """Send a webhook notification for a document rejection.

    Args:
        document_id:      UUID of the rejected document.
        reviewer_name:    Name of the reviewer.
        reviewed_at:      UTC timestamp of the rejection decision.
        rejection_reason: Reason for the rejection.
        suggested_action: Optional guidance for the document author.
        webhook_url:      Webhook target URL (fetched from DB settings by the caller).
                          Pass empty string to skip (notifications disabled).
    """
    payload: dict[str, Any] = {
        "event": "document.rejected",
        "document_id": document_id,
        "reviewer": reviewer_name,
        "timestamp": reviewed_at.isoformat(),
        "details": {
            "rejection_reason": rejection_reason,
            "suggested_action": suggested_action,
        },
    }
    _send_webhook(payload, webhook_url)
