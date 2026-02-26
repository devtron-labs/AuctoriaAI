"""
Service layer for Admin-configurable System Settings.

Replaces hardcoded config constants (app/config.py) for governance-critical
parameters with DB-backed, admin-editable values.

Architecture:
  - Single-row PostgreSQL table (system_settings) holds all configurable values.
  - In-memory cache (60-second TTL) avoids per-request DB hits on hot paths.
  - Cache is invalidated immediately on every write.
  - If no row exists (e.g. fresh DB), a default row is seeded from config.py
    constants and persisted automatically.
  - Sliding-window rate limiter (5 updates / hour) prevents runaway mutations.
  - All callers receive an immutable ActiveSettings dataclass — safe to hold
    across a request without worrying about SQLAlchemy session expiry.

Thread-safety:
  Cache and rate-limiter state are protected by threading.Lock. This is safe
  for single-process uvicorn deployments. For multi-worker production, replace
  the cache with Redis or similar shared storage.
"""

import logging
import threading
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session
from sqlalchemy.exc import ProgrammingError

from app.config import settings as _config
from app.models.models import SystemSettings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Cache configuration
# ---------------------------------------------------------------------------

_CACHE_TTL_SECONDS: int = 60

_cache: dict[str, Any] = {}
_cache_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Rate limiter (sliding window)
# ---------------------------------------------------------------------------

_RATE_LIMIT_MAX: int = 5       # maximum updates allowed per window
_RATE_LIMIT_WINDOW: float = 3600.0  # window size in seconds (1 hour)

_update_timestamps: deque[float] = deque()
_rate_lock = threading.Lock()


# ---------------------------------------------------------------------------
# Immutable settings snapshot
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ActiveSettings:
    """Immutable snapshot of system settings values.

    Decoupled from the SQLAlchemy ORM so it can be safely cached across
    requests without session-expiry issues.
    """

    id: str
    registry_staleness_hours: int
    llm_model_name: str
    max_draft_length: int
    qa_passing_threshold: float
    max_qa_iterations: int
    qa_llm_model: str
    governance_score_threshold: float
    llm_timeout_seconds: int
    notification_webhook_url: str
    updated_by: Optional[str]
    updated_at: datetime
    anthropic_api_key:  Optional[str]
    openai_api_key:     Optional[str]
    google_api_key:     Optional[str]
    perplexity_api_key: Optional[str]
    xai_api_key:        Optional[str]


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

def _get_virtual_defaults() -> ActiveSettings:
    """Return an ActiveSettings snapshot populated from config.py constants.

    Used as a fallback when the system_settings table does not exist yet
    (e.g. during initial installation before migrations have run).
    """
    return ActiveSettings(
        id="virtual-default",
        registry_staleness_hours=_config.registry_staleness_hours,
        llm_model_name=_config.llm_model_name,
        max_draft_length=_config.max_draft_length,
        qa_passing_threshold=_config.qa_passing_threshold,
        max_qa_iterations=_config.max_qa_iterations,
        qa_llm_model=_config.qa_llm_model,
        governance_score_threshold=_config.governance_score_threshold,
        llm_timeout_seconds=120,
        notification_webhook_url=_config.notification_webhook_url,
        updated_by="system-default",
        updated_at=datetime.now(timezone.utc),
        anthropic_api_key=None,
        openai_api_key=None,
        google_api_key=None,
        perplexity_api_key=None,
        xai_api_key=None,
    )


def _row_to_active(row: SystemSettings) -> ActiveSettings:
    """Convert an ORM row to an immutable ActiveSettings snapshot."""
    return ActiveSettings(
        id=str(row.id),
        registry_staleness_hours=row.registry_staleness_hours,
        llm_model_name=row.llm_model_name,
        max_draft_length=row.max_draft_length,
        qa_passing_threshold=row.qa_passing_threshold,
        max_qa_iterations=row.max_qa_iterations,
        qa_llm_model=row.qa_llm_model,
        governance_score_threshold=row.governance_score_threshold,
        llm_timeout_seconds=row.llm_timeout_seconds if row.llm_timeout_seconds is not None else 120,
        notification_webhook_url=row.notification_webhook_url or "",
        updated_by=row.updated_by,
        updated_at=row.updated_at,
        anthropic_api_key=row.anthropic_api_key,
        openai_api_key=row.openai_api_key,
        google_api_key=row.google_api_key,
        perplexity_api_key=row.perplexity_api_key,
        xai_api_key=row.xai_api_key,
    )


def _seed_defaults(db: Session) -> SystemSettings:
    """Create and persist the initial settings row from config.py defaults.

    Called automatically when the table is empty (e.g. fresh database that
    hasn't run the migration yet in development).
    """
    row = SystemSettings(
        registry_staleness_hours=_config.registry_staleness_hours,
        llm_model_name=_config.llm_model_name,
        max_draft_length=_config.max_draft_length,
        qa_passing_threshold=_config.qa_passing_threshold,
        max_qa_iterations=_config.max_qa_iterations,
        qa_llm_model=_config.qa_llm_model,
        governance_score_threshold=_config.governance_score_threshold,
        llm_timeout_seconds=120,
        notification_webhook_url=_config.notification_webhook_url,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    logger.info("System settings seeded with config defaults: id=%s", row.id)
    return row


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_settings(db: Session) -> ActiveSettings:
    """Return the current system settings, backed by a 60-second in-memory cache.

    On cache miss or expiry, queries the DB. If the settings table is empty
    (fresh install), seeds a default row from app/config.py constants.

    If the table itself is missing (UndefinedTable), returns defaults from
    config.py without seeding (since the table cannot be written to).

    Args:
        db: Active SQLAlchemy session.

    Returns:
        Immutable ActiveSettings snapshot safe to use for the lifetime of the request.
    """
    now = time.monotonic()
    with _cache_lock:
        cached: Optional[ActiveSettings] = _cache.get("value")
        ts: float = _cache.get("ts", 0.0)
        if cached is not None and (now - ts) < _CACHE_TTL_SECONDS:
            return cached

    # Cache miss — query DB (outside the lock to avoid blocking other threads)
    try:
        row: Optional[SystemSettings] = db.query(SystemSettings).first()
    except ProgrammingError as e:
        # PostgreSQL: 42P01 is UndefinedTable.
        # SQLite: "no such table" in the error message.
        orig_msg = str(e.orig).lower()
        if (hasattr(e.orig, "pgcode") and e.orig.pgcode == "42P01") or "no such table" in orig_msg:
            logger.warning(
                "system_settings table does not exist yet — returning config defaults. "
                "Run 'alembic upgrade head' to initialize the database."
            )
            return _get_virtual_defaults()
        raise

    if row is None:
        row = _seed_defaults(db)

    active = _row_to_active(row)

    with _cache_lock:
        _cache["value"] = active
        _cache["ts"] = now

    return active


def invalidate_cache() -> None:
    """Immediately expire the in-memory cache.

    The next call to get_settings() will re-query the database.
    Called automatically after every successful update.
    """
    with _cache_lock:
        _cache.clear()
    logger.debug("Settings cache invalidated")


def check_rate_limit() -> bool:
    """Check whether a settings update is allowed under the sliding-window rate limit.

    Allows at most _RATE_LIMIT_MAX (5) updates per _RATE_LIMIT_WINDOW (3600 s).
    Records the current timestamp if the update is allowed.

    Returns:
        True  — update is permitted (timestamp recorded).
        False — rate limit exceeded; caller should return HTTP 429.
    """
    now = time.monotonic()
    window_start = now - _RATE_LIMIT_WINDOW

    with _rate_lock:
        # Evict timestamps older than the window
        while _update_timestamps and _update_timestamps[0] < window_start:
            _update_timestamps.popleft()

        if len(_update_timestamps) >= _RATE_LIMIT_MAX:
            return False

        _update_timestamps.append(now)
        return True


def update_settings(
    db: Session,
    update_data: dict[str, Any],
    updated_by: str,
) -> SystemSettings:
    """Apply a validated settings update, invalidate the cache, and persist.

    The caller (admin router) is responsible for Pydantic validation before
    invoking this function. This function applies field-level mutations, sets
    updated_by, commits, and clears the in-memory cache.

    Args:
        db:          Active SQLAlchemy session.
        update_data: Dict of {field_name: new_value} — must not include updated_by.
        updated_by:  Display name of the admin making the change (for audit trail).

    Returns:
        The refreshed SystemSettings ORM instance.

    Raises:
        ValueError: Rate limit exceeded (5 updates/hour).
        Exception:  DB commit failure — transaction is rolled back.
    """
    if not check_rate_limit():
        raise ValueError(
            f"Rate limit exceeded: at most {_RATE_LIMIT_MAX} settings updates "
            f"are allowed per hour. Please wait before making further changes."
        )

    row: Optional[SystemSettings] = db.query(SystemSettings).first()
    if row is None:
        row = _seed_defaults(db)

    _API_KEY_FIELDS = frozenset({
        "anthropic_api_key", "openai_api_key",
        "google_api_key", "perplexity_api_key", "xai_api_key",
    })

    for field, value in update_data.items():
        if hasattr(row, field):
            # Empty string on an API key field means "clear" → store None
            if field in _API_KEY_FIELDS and value == "":
                setattr(row, field, None)
            else:
                setattr(row, field, value)

    row.updated_by = updated_by
    row.updated_at = datetime.now(timezone.utc)

    try:
        db.commit()
        db.refresh(row)
    except Exception:
        db.rollback()
        logger.error("Settings commit failed — transaction rolled back")
        raise

    invalidate_cache()
    logger.info(
        "System settings updated: updated_by=%s llm=%s qa_threshold=%.1f gov_threshold=%.1f",
        updated_by,
        row.llm_model_name,
        row.qa_passing_threshold,
        row.governance_score_threshold,
    )
    return row
