# Multi-Provider LLM Support Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow admins to configure API keys for Anthropic, OpenAI, Google, Perplexity, and xAI, and select models from any of those providers for draft generation and QA evaluation via Admin → System Settings.

**Architecture:** Add 5 `*_api_key` columns to `system_settings`, create `app/services/llm_adapter.py` that routes to the Anthropic SDK (Claude) or OpenAI-compatible SDK (everyone else) based on model name prefix, thread `ActiveSettings` through the existing `_call_llm*` helpers so they pick up the right key, and add an API Keys card to the frontend settings page.

**Tech Stack:** FastAPI + Pydantic v2 + Alembic (backend), `anthropic==0.40.0` + `openai>=1.0.0` (AI SDKs), React 19 + TypeScript + React Hook Form (frontend).

---

### Task 1: Add openai dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add `openai` to requirements**

Open `requirements.txt` and add after the `anthropic` line:

```
openai>=1.0.0
```

**Step 2: Install it**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pip install "openai>=1.0.0"
```

Expected: openai installs successfully.

**Step 3: Verify import works**

```bash
python -c "import openai; print(openai.__version__)"
```

Expected: prints version (e.g. `1.x.x`).

**Step 4: Commit**

```bash
git add requirements.txt && git commit -m "feat: add openai SDK dependency for multi-provider LLM support"
```

---

### Task 2: Alembic migration — add API key columns

**Files:**
- Create: `alembic/versions/014_add_provider_api_keys.py`

**Step 1: Autogenerate a new migration**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && alembic revision -m "add_provider_api_keys"
```

This creates `alembic/versions/014_add_provider_api_keys.py` (or similar).

**Step 2: Fill in the migration body**

Replace the generated `upgrade()` and `downgrade()` with:

```python
def upgrade() -> None:
    op.add_column("system_settings", sa.Column("anthropic_api_key", sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("openai_api_key",    sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("google_api_key",    sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("perplexity_api_key",sa.String(512), nullable=True))
    op.add_column("system_settings", sa.Column("xai_api_key",       sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("system_settings", "xai_api_key")
    op.drop_column("system_settings", "perplexity_api_key")
    op.drop_column("system_settings", "google_api_key")
    op.drop_column("system_settings", "openai_api_key")
    op.drop_column("system_settings", "anthropic_api_key")
```

Make sure the `import sqlalchemy as sa` line is present at the top (autogenerate adds it).

**Step 3: Run the migration**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && python -m alembic upgrade head
```

Expected: `Running upgrade ... -> ..., add_provider_api_keys`.

**Step 4: Commit**

```bash
git add alembic/versions/ && git commit -m "feat: migration — add per-provider API key columns to system_settings"
```

---

### Task 3: Update SystemSettings ORM model

**Files:**
- Modify: `app/models/models.py`

**Step 1: Add 5 columns to the `SystemSettings` class**

In `app/models/models.py`, find the `SystemSettings` class (around line 155) and add after the `notification_webhook_url` column:

```python
    # Per-provider API keys — stored in DB for admin-configured LLM routing.
    # anthropic_api_key falls back to ANTHROPIC_API_KEY env var if null.
    anthropic_api_key  = Column(String(512), nullable=True)
    openai_api_key     = Column(String(512), nullable=True)
    google_api_key     = Column(String(512), nullable=True)
    perplexity_api_key = Column(String(512), nullable=True)
    xai_api_key        = Column(String(512), nullable=True)
```

**Step 2: Verify the model loads without errors**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && python -c "from app.models.models import SystemSettings; print('OK')"
```

Expected: `OK`.

**Step 3: Commit**

```bash
git add app/models/models.py && git commit -m "feat: add provider API key columns to SystemSettings ORM model"
```

---

### Task 4: Update settings_service — add key fields to ActiveSettings

**Files:**
- Modify: `app/services/settings_service.py`

**Step 1: Write a failing test**

Add to `app/tests/test_system_settings.py`:

```python
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
```

**Step 2: Run to verify it fails**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_active_settings_has_api_key_fields -v
```

Expected: FAIL — `ActiveSettings has no attribute 'anthropic_api_key'`.

**Step 3: Update `settings_service.py`**

**3a. Add fields to `ActiveSettings` dataclass** (after `notification_webhook_url`):

```python
    anthropic_api_key:  Optional[str]
    openai_api_key:     Optional[str]
    google_api_key:     Optional[str]
    perplexity_api_key: Optional[str]
    xai_api_key:        Optional[str]
```

**3b. Update `_row_to_active()`** — add to the `ActiveSettings(...)` constructor call:

```python
        anthropic_api_key=row.anthropic_api_key,
        openai_api_key=row.openai_api_key,
        google_api_key=row.google_api_key,
        perplexity_api_key=row.perplexity_api_key,
        xai_api_key=row.xai_api_key,
```

**Step 4: Run test to verify it passes**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_active_settings_has_api_key_fields -v
```

Expected: PASS.

**Step 5: Run full settings tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py -q
```

Expected: same failures as before (only `test_valid_payload_accepted` failing due to pre-existing SQLite UUID issue).

**Step 6: Commit**

```bash
git add app/services/settings_service.py app/tests/test_system_settings.py && git commit -m "feat: add provider API key fields to ActiveSettings dataclass"
```

---

### Task 5: Update schemas.py — provider keys + expanded model list + remove claude- restriction

**Files:**
- Modify: `app/schemas/schemas.py`

**Step 1: Write failing tests**

Add to `app/tests/test_system_settings.py`:

```python
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
    import pytest
    from pydantic import ValidationError
    from app.schemas.schemas import SystemSettingsUpdate
    with pytest.raises(ValidationError):
        SystemSettingsUpdate(**_make_valid_update(llm_model_name=""))


def test_api_key_none_excluded_from_update(client):
    """API key fields with None value are excluded — existing keys preserved."""
    from app.schemas.schemas import SystemSettingsUpdate
    payload = SystemSettingsUpdate(**_make_valid_update())
    dumped = payload.model_dump(exclude={"updated_by"}, exclude_none=True)
    # No API key fields should appear (they default to None)
    assert "openai_api_key" not in dumped
    assert "anthropic_api_key" not in dumped
```

**Step 2: Run to verify they fail**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_gpt4o_model_accepted app/tests/test_system_settings.py::test_gemini_model_accepted -v
```

Expected: FAIL — `gpt-4o must start with 'claude-'`.

**Step 3: Update `app/schemas/schemas.py`**

**3a. Replace `KNOWN_LLM_MODELS`** with the multi-provider list:

```python
KNOWN_LLM_MODELS: list[dict[str, str]] = [
    # Anthropic
    {"id": "claude-opus-4-6",           "label": "Claude Opus 4.6 (Most Capable)",    "provider": "anthropic"},
    {"id": "claude-sonnet-4-6",         "label": "Claude Sonnet 4.6 (Balanced)",      "provider": "anthropic"},
    {"id": "claude-haiku-4-5-20251001", "label": "Claude Haiku 4.5 (Fast)",           "provider": "anthropic"},
    # OpenAI
    {"id": "gpt-4o",                    "label": "GPT-4o (OpenAI)",                   "provider": "openai"},
    {"id": "gpt-4o-mini",               "label": "GPT-4o Mini (OpenAI)",              "provider": "openai"},
    {"id": "o3-mini",                   "label": "o3 Mini (OpenAI)",                  "provider": "openai"},
    # Google Gemini
    {"id": "gemini-2.0-flash",          "label": "Gemini 2.0 Flash (Google)",         "provider": "google"},
    {"id": "gemini-1.5-pro",            "label": "Gemini 1.5 Pro (Google)",           "provider": "google"},
    # Perplexity
    {"id": "llama-3.1-sonar-large-128k-online", "label": "Sonar Large (Perplexity)", "provider": "perplexity"},
    {"id": "llama-3.1-sonar-small-128k-online", "label": "Sonar Small (Perplexity)", "provider": "perplexity"},
    # xAI Grok
    {"id": "grok-2",                    "label": "Grok 2 (xAI)",                      "provider": "xai"},
    {"id": "grok-2-vision-1212",        "label": "Grok 2 Vision (xAI)",               "provider": "xai"},
]
```

**3b. Remove the `validate_model_name` validator** from `SystemSettingsUpdate` — delete the entire `@field_validator("llm_model_name", "qa_llm_model")` block and replace it with nothing (just keep `min_length=1` on the `Field(...)`).

**3c. Add API key fields to `SystemSettingsResponse`** (these are masked at the router level, not here — just add the fields):

```python
    # Provider API keys — returned masked (****last4) or null by the router
    anthropic_api_key:  Optional[str] = None
    openai_api_key:     Optional[str] = None
    google_api_key:     Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key:        Optional[str] = None
```

**3d. Add API key fields to `SystemSettingsUpdate`**:

```python
    # Provider API keys — Optional[str]:
    #   None  = not provided, keep existing DB value
    #   ""    = explicitly clear the key
    #   "..." = new key value to store
    anthropic_api_key:  Optional[str] = None
    openai_api_key:     Optional[str] = None
    google_api_key:     Optional[str] = None
    perplexity_api_key: Optional[str] = None
    xai_api_key:        Optional[str] = None
```

**Step 4: Run tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_gpt4o_model_accepted app/tests/test_system_settings.py::test_gemini_model_accepted app/tests/test_system_settings.py::test_empty_model_rejected app/tests/test_system_settings.py::test_api_key_none_excluded_from_update -v
```

Expected: All 4 PASS.

**Step 5: Commit**

```bash
git add app/schemas/schemas.py app/tests/test_system_settings.py && git commit -m "feat: remove claude-only model restriction, add multi-provider known models and API key schema fields"
```

---

### Task 6: Update admin_routes.py — mask keys in GET, exclude_none in PUT

**Files:**
- Modify: `app/api/admin_routes.py`

**Step 1: Write failing test**

Add to `app/tests/test_system_settings.py`:

```python
def test_get_settings_masks_api_keys(client):
    """GET /admin/settings must never return a full API key."""
    response = client.get("/api/v1/admin/settings")
    if response.status_code != 200:
        pytest.skip("DB not available")
    data = response.json()
    # All key fields should be null (not set in test DB) or masked (never > 8 chars of real key)
    for field in ("anthropic_api_key", "openai_api_key", "google_api_key",
                  "perplexity_api_key", "xai_api_key"):
        assert field in data
        val = data[field]
        assert val is None or (isinstance(val, str) and val.startswith("****"))
```

**Step 2: Run to verify test fails**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_get_settings_masks_api_keys -v
```

Expected: FAIL (key fields not returned at all yet).

**Step 3: Update `app/api/admin_routes.py`**

**3a. Add masking helper** after the imports:

```python
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
```

**3b. Update `get_system_settings` endpoint** — instead of returning the ORM row directly, build a masked response dict:

Replace the function body with:

```python
def get_system_settings(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
) -> dict:
    row = db.query(SystemSettings).first()
    if row is None:
        raise HTTPException(status_code=404, detail="System settings row not found.")
    response = SystemSettingsResponse.model_validate(row).model_dump()
    for field in _API_KEY_FIELDS:
        response[field] = _mask_key(getattr(row, field, None))
    return response
```

Also change the return type annotation on the decorator to `response_model=None` and add `responses={200: {"model": SystemSettingsResponse}}` or simply remove `response_model` from the decorator and let FastAPI infer from the dict.

Actually the cleanest approach: keep `response_model=SystemSettingsResponse` but override the key fields after validation. Change to:

```python
@admin_router.get(
    "/settings",
    response_model=SystemSettingsResponse,
    summary="Get current system settings",
)
def get_system_settings(
    db: Session = Depends(get_db),
    _: None = Depends(_require_admin),
) -> SystemSettingsResponse:
    row = db.query(SystemSettings).first()
    if row is None:
        raise HTTPException(status_code=404, detail="System settings row not found.")
    data = SystemSettingsResponse.model_validate(row).model_dump()
    for field in _API_KEY_FIELDS:
        data[field] = _mask_key(data.get(field))
    return SystemSettingsResponse(**data)
```

**3c. Update `update_system_settings` endpoint** — change `model_dump` call to exclude None fields:

```python
    update_data = payload.model_dump(exclude={"updated_by"}, exclude_none=True)
```

This ensures API key fields that are `None` (not provided) are not touched in the DB. An empty string `""` IS included, which clears the key (sets it to `None` or `""` in the DB — handled by `update_settings`).

**3d. Update `settings_service.update_settings`** — convert empty-string API key values to `None` in DB:

In `app/services/settings_service.py`, inside `update_settings`, change the field-setting loop:

```python
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
```

**Step 4: Run test**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_get_settings_masks_api_keys -v
```

Expected: PASS (returns null for unset keys or masked if set).

**Step 5: Run all settings tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py -q
```

**Step 6: Commit**

```bash
git add app/api/admin_routes.py app/services/settings_service.py app/tests/test_system_settings.py && git commit -m "feat: mask API keys in GET /admin/settings, preserve keys on partial PUT"
```

---

### Task 7: Create llm_adapter.py

**Files:**
- Create: `app/services/llm_adapter.py`
- Test: `app/tests/test_llm_adapter.py`

**Step 1: Write failing tests**

Create `app/tests/test_llm_adapter.py`:

```python
"""Unit tests for LLM provider routing in llm_adapter.py."""
import pytest
from unittest.mock import MagicMock, patch
from app.services.llm_adapter import detect_provider, get_api_key, call_llm


class TestDetectProvider:
    def test_claude_is_anthropic(self):
        assert detect_provider("claude-opus-4-6") == "anthropic"
        assert detect_provider("claude-sonnet-4-6") == "anthropic"
        assert detect_provider("claude-haiku-4-5-20251001") == "anthropic"

    def test_gpt_is_openai(self):
        assert detect_provider("gpt-4o") == "openai"
        assert detect_provider("gpt-4o-mini") == "openai"

    def test_o_series_is_openai(self):
        assert detect_provider("o3-mini") == "openai"
        assert detect_provider("o1") == "openai"

    def test_gemini_is_google(self):
        assert detect_provider("gemini-2.0-flash") == "google"
        assert detect_provider("gemini-1.5-pro") == "google"

    def test_grok_is_xai(self):
        assert detect_provider("grok-2") == "xai"
        assert detect_provider("grok-2-vision-1212") == "xai"

    def test_unknown_is_perplexity(self):
        assert detect_provider("llama-3.1-sonar-large-128k-online") == "perplexity"
        assert detect_provider("sonar-pro") == "perplexity"


class TestGetApiKey:
    def _mock_settings(self, **kwargs):
        s = MagicMock()
        s.anthropic_api_key  = kwargs.get("anthropic_api_key", None)
        s.openai_api_key     = kwargs.get("openai_api_key", None)
        s.google_api_key     = kwargs.get("google_api_key", None)
        s.perplexity_api_key = kwargs.get("perplexity_api_key", None)
        s.xai_api_key        = kwargs.get("xai_api_key", None)
        return s

    def test_anthropic_uses_db_key(self):
        s = self._mock_settings(anthropic_api_key="sk-ant-db")
        assert get_api_key("anthropic", s) == "sk-ant-db"

    def test_anthropic_falls_back_to_env(self):
        s = self._mock_settings(anthropic_api_key=None)
        with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "sk-ant-env"}):
            assert get_api_key("anthropic", s) == "sk-ant-env"

    def test_openai_uses_db_key(self):
        s = self._mock_settings(openai_api_key="sk-openai")
        assert get_api_key("openai", s) == "sk-openai"

    def test_google_uses_db_key(self):
        s = self._mock_settings(google_api_key="AIza-google")
        assert get_api_key("google", s) == "AIza-google"

    def test_missing_key_returns_none(self):
        s = self._mock_settings()
        assert get_api_key("openai", s) is None
```

**Step 2: Run to verify they fail**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_llm_adapter.py -v
```

Expected: FAIL — module not found.

**Step 3: Create `app/services/llm_adapter.py`**

```python
"""
LLM provider adapter — routes generation calls to the correct SDK.

Supported providers:
  anthropic  → anthropic SDK  (claude-* models)
  openai     → openai SDK     (gpt-*, o1*, o3*)
  google     → openai SDK     (gemini-*, via OpenAI-compatible endpoint)
  xai        → openai SDK     (grok-*, via OpenAI-compatible endpoint)
  perplexity → openai SDK     (all others, via OpenAI-compatible endpoint)

Public API:
  detect_provider(model_name) -> str
  get_api_key(provider, settings) -> str | None
  call_llm(prompt, model_name, settings, timeout, max_tokens, temperature) -> str
"""

import os
import logging
from typing import Optional

import anthropic
import openai

from app.services.settings_service import ActiveSettings

logger = logging.getLogger(__name__)

# OpenAI-compatible base URLs per provider
_BASE_URLS: dict[str, str] = {
    "openai":     "https://api.openai.com/v1",
    "google":     "https://generativelanguage.googleapis.com/v1beta/openai/",
    "xai":        "https://api.x.ai/v1",
    "perplexity": "https://api.perplexity.ai",
}


def detect_provider(model_name: str) -> str:
    """Determine which provider owns a given model ID."""
    if model_name.startswith("claude-"):
        return "anthropic"
    if model_name.startswith("gpt-") or model_name.startswith("o1") or model_name.startswith("o3"):
        return "openai"
    if model_name.startswith("gemini-"):
        return "google"
    if model_name.startswith("grok-"):
        return "xai"
    return "perplexity"


def get_api_key(provider: str, settings: ActiveSettings) -> Optional[str]:
    """Return the API key for a provider.

    For 'anthropic', falls back to the ANTHROPIC_API_KEY environment variable
    when the DB key is not set, preserving backwards compatibility.
    """
    key_map = {
        "anthropic":  settings.anthropic_api_key,
        "openai":     settings.openai_api_key,
        "google":     settings.google_api_key,
        "perplexity": settings.perplexity_api_key,
        "xai":        settings.xai_api_key,
    }
    key = key_map.get(provider)
    if not key and provider == "anthropic":
        key = os.environ.get("ANTHROPIC_API_KEY")
    return key or None


def call_llm(
    prompt: str,
    model_name: str,
    settings: ActiveSettings,
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    """Call the appropriate LLM provider and return the generated text.

    Args:
        prompt:       Full prompt string to send.
        model_name:   Model ID (e.g. 'gpt-4o', 'claude-opus-4-6').
        settings:     ActiveSettings snapshot carrying provider API keys.
        timeout:      Request timeout in seconds.
        max_tokens:   Maximum tokens to generate.
        temperature:  Sampling temperature (0.0 = deterministic).

    Returns:
        Generated text string.

    Raises:
        ValueError: Required API key is not configured for the provider.
        anthropic.AuthenticationError / openai.AuthenticationError: Bad key.
        anthropic.RateLimitError / openai.RateLimitError: Rate limited.
    """
    provider = detect_provider(model_name)
    api_key = get_api_key(provider, settings)

    logger.info(
        "LLM call: provider=%s model=%s max_tokens=%d temperature=%.2f",
        provider, model_name, max_tokens, temperature,
    )

    if provider == "anthropic":
        return _call_anthropic(prompt, model_name, api_key, timeout, max_tokens, temperature)
    else:
        return _call_openai_compatible(
            prompt, model_name, provider, api_key, timeout, max_tokens, temperature
        )


def _call_anthropic(
    prompt: str,
    model_name: str,
    api_key: Optional[str],
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    client = anthropic.Anthropic(api_key=api_key, timeout=timeout)
    message = client.messages.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text


def _call_openai_compatible(
    prompt: str,
    model_name: str,
    provider: str,
    api_key: Optional[str],
    timeout: float,
    max_tokens: int,
    temperature: float,
) -> str:
    base_url = _BASE_URLS[provider]
    client = openai.OpenAI(api_key=api_key or "not-set", base_url=base_url, timeout=timeout)
    response = client.chat.completions.create(
        model=model_name,
        max_tokens=max_tokens,
        temperature=temperature,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""
```

**Step 4: Run tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_llm_adapter.py -v
```

Expected: All tests PASS.

**Step 5: Commit**

```bash
git add app/services/llm_adapter.py app/tests/test_llm_adapter.py && git commit -m "feat: add llm_adapter.py for multi-provider LLM routing"
```

---

### Task 8: Wire adapter into draft_generation_service.py

**Files:**
- Modify: `app/services/draft_generation_service.py`

There are **3** Anthropic call sites in this file:
- `_call_llm` at line ~201 (fact-grounded draft, max_tokens=8096, temperature=0.2)
- `_call_llm_optimize` at line ~705 (prompt optimizer, max_tokens=600, temperature=0.1)
- The third Anthropic client instantiation at line ~1078 (inline call in `generate_draft_from_prompt`
  — actually this just calls `_call_llm` again, so covered by #1)

**Step 1: Add import**

At the top of `draft_generation_service.py`, after `import anthropic`, add:

```python
from app.services import llm_adapter
```

**Step 2: Update `_call_llm` signature and body**

Change the function signature from:
```python
def _call_llm(prompt: str, tone: str, model_name: str, timeout_seconds: float = 120.0) -> str:
```
to:
```python
def _call_llm(prompt: str, tone: str, model_name: str, settings: "ActiveSettings", timeout_seconds: float = 120.0) -> str:
```

Add import at top of file:
```python
from app.services.settings_service import ActiveSettings
```

Replace the `client = anthropic.Anthropic(...)` block through `return message.content[0].text` with:

```python
    logger.info(
        "LLM call start: model=%s tone=%s prompt_length=%d",
        model_name, tone, len(prompt),
    )
    text = llm_adapter.call_llm(
        prompt=prompt,
        model_name=model_name,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=8096,
        temperature=0.2,
    )
    # Log a proxy for token usage (adapter handles internal logging)
    logger.info("LLM call complete: model=%s tone=%s output_length=%d", model_name, tone, len(text))
    return text
```

**Step 3: Update the callers of `_call_llm`**

In `generate_draft` (line ~333), change:
```python
content_markdown = _call_llm(prompt, tone, llm_model, timeout_seconds)
```
to:
```python
content_markdown = _call_llm(prompt, tone, llm_model, active, timeout_seconds)
```

In `generate_draft_from_prompt` (line ~1078), change:
```python
content_markdown = _call_llm(llm_prompt, tone, llm_model, _stage2_timeout)
```
to:
```python
content_markdown = _call_llm(llm_prompt, tone, llm_model, active, _stage2_timeout)
```

(Verify `active` is in scope at both call sites — it's set earlier in each function via `settings_service.get_settings(db)`.)

**Step 4: Update `_call_llm_optimize` signature and body**

Change:
```python
def _call_llm_optimize(
    raw_prompt: str,
    document_type: str,
    model_name: str,
    timeout_seconds: float = 60.0,
) -> str:
```
to:
```python
def _call_llm_optimize(
    raw_prompt: str,
    document_type: str,
    model_name: str,
    settings: "ActiveSettings",
    timeout_seconds: float = 60.0,
) -> str:
```

Replace the Anthropic client block with:
```python
    optimizer_prompt = _build_prompt_optimizer_prompt(raw_prompt, document_type)
    logger.info(
        "Prompt optimizer call: model=%s document_type=%s raw_prompt_length=%d",
        model_name, document_type, len(raw_prompt),
    )
    return llm_adapter.call_llm(
        prompt=optimizer_prompt,
        model_name=model_name,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=600,
        temperature=0.1,
    )
```

Update the caller at line ~1051:
```python
refined_prompt = _call_llm_optimize(prompt, document_type, llm_model, active, OPTIMIZER_TIMEOUT)
```

**Step 5: Run backend tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_epic3_generation.py -q
```

Expected: Same pass/fail ratio as before (no new failures).

**Step 6: Commit**

```bash
git add app/services/draft_generation_service.py && git commit -m "feat: route draft generation LLM calls through llm_adapter"
```

---

### Task 9: Wire adapter into qa_iteration_service.py

**Files:**
- Modify: `app/services/qa_iteration_service.py`

There are **2** Anthropic call sites:
- `_call_llm_evaluate` at line ~78 (evaluate, max_tokens=2048, temperature=0.0)
- `_call_llm_improve` at line ~166 (improve, max_tokens=8096, temperature=0.1)

**Step 1: Add imports**

At top of `qa_iteration_service.py`, add:

```python
from app.services import llm_adapter
from app.services.settings_service import ActiveSettings
```

**Step 2: Update `_call_llm_evaluate` signature and body**

Change signature:
```python
def _call_llm_evaluate(
    draft_content: str, fact_sheet_data: dict, qa_model: str, timeout_seconds: float = 120.0
) -> dict:
```
to:
```python
def _call_llm_evaluate(
    draft_content: str, fact_sheet_data: dict, qa_model: str,
    settings: "ActiveSettings", timeout_seconds: float = 120.0
) -> dict:
```

Replace the `client = anthropic.Anthropic(...)` block through `raw = message.content[0].text` with:

```python
    prompt = _build_evaluation_prompt(draft_content, fact_sheet_data)
    logger.info(
        "LLM evaluate call start: model=%s draft_length=%d prompt_length=%d",
        qa_model, len(draft_content), len(prompt),
    )
    raw = llm_adapter.call_llm(
        prompt=prompt,
        model_name=qa_model,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=2048,
        temperature=0.0,
    )
    logger.info("LLM evaluate raw response: model=%s raw_response=%s", qa_model, raw)
```

Update the caller in `evaluate_draft` (line ~670):
```python
raw_scores = _call_llm_evaluate(draft.content_markdown, fact_sheet_data, qa_model, active, timeout_seconds)
```

(Verify `active` is in scope via `settings_service.get_settings(db)` in `evaluate_draft`.)

**Step 3: Update `_call_llm_improve` signature and body**

Change:
```python
def _call_llm_improve(prompt: str, qa_model: str, timeout_seconds: float = 120.0) -> str:
```
to:
```python
def _call_llm_improve(prompt: str, qa_model: str, settings: "ActiveSettings", timeout_seconds: float = 120.0) -> str:
```

Replace the Anthropic client block with:
```python
    logger.info("LLM improve call start: model=%s prompt_length=%d", qa_model, len(prompt))
    return llm_adapter.call_llm(
        prompt=prompt,
        model_name=qa_model,
        settings=settings,
        timeout=timeout_seconds,
        max_tokens=8096,
        temperature=0.1,
    )
```

Update caller in `improve_draft` (line ~792):
```python
new_content = _call_llm_improve(prompt, qa_model, active, timeout_seconds)
```

(Verify `active` is in scope in `improve_draft`.)

**Step 4: Run QA tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_epic4_qa_iteration.py -q
```

Expected: same pass/fail as before.

**Step 5: Commit**

```bash
git add app/services/qa_iteration_service.py && git commit -m "feat: route QA iteration LLM calls through llm_adapter"
```

---

### Task 10: Wire adapter into extraction_service.py

**Files:**
- Modify: `app/services/extraction_service.py`

One Anthropic call site: `_call_llm` at line ~306.

**Step 1: Add imports**

```python
from app.services import llm_adapter
from app.services.settings_service import ActiveSettings
```

**Step 2: Update `_call_llm` in extraction_service.py**

Note: this `_call_llm` is **different** from the one in draft_generation_service — it returns a parsed dict (JSON).

Change signature:
```python
def _call_llm(document_id: str, document_content: str, model_name: str) -> dict[str, Any]:
```
to:
```python
def _call_llm(document_id: str, document_content: str, model_name: str, settings: "ActiveSettings") -> dict[str, Any]:
```

Replace the `client = anthropic.Anthropic(...)` through `return json.loads(raw_text)` with:

```python
    prompt = _build_extraction_prompt(_read_document_text(document_content))
    logger.info(
        "LLM extraction call start: model=%s document_id=%s prompt_length=%d",
        model_name, document_id, len(prompt),
    )
    raw_text = llm_adapter.call_llm(
        prompt=prompt,
        model_name=model_name,
        settings=settings,
        timeout=30.0,
        max_tokens=4096,
        temperature=0.0,
    )
    return json.loads(raw_text)
```

**Step 3: Update the caller in `extract_factsheet`** (line ~425):

First verify that `extract_factsheet` already calls `settings_service.get_settings(db)`. If it does, pass `active` to `_call_llm`:

```python
raw_extraction: dict[str, Any] = _call_llm(
    document_id, ..., model_name, active
)
```

If `active` is not in scope yet, add `active = settings_service.get_settings(db)` near the top of `extract_factsheet`.

**Step 4: Run extraction tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_epic2_extraction.py -q
```

Expected: same pass/fail ratio as before.

**Step 5: Commit**

```bash
git add app/services/extraction_service.py && git commit -m "feat: route fact-sheet extraction LLM calls through llm_adapter"
```

---

### Task 11: Update frontend types

**Files:**
- Modify: `frontend/src/types/admin.ts`

**Step 1: Update `KnownLlmModel`** — add `provider` field:

```typescript
export interface KnownLlmModel {
  id: string;
  label: string;
  provider: string;  // 'anthropic' | 'openai' | 'google' | 'perplexity' | 'xai'
}
```

**Step 2: Add API key fields to `SystemSettings`** — all optional/nullable since GET returns masked or null:

```typescript
export interface SystemSettings {
  // ... existing fields ...
  anthropic_api_key:  string | null;
  openai_api_key:     string | null;
  google_api_key:     string | null;
  perplexity_api_key: string | null;
  xai_api_key:        string | null;
}
```

**Step 3: Add optional API key fields to `SystemSettingsUpdate`** — `undefined` means "don't send":

```typescript
export interface SystemSettingsUpdate {
  // ... existing fields ...
  anthropic_api_key?:  string;
  openai_api_key?:     string;
  google_api_key?:     string;
  perplexity_api_key?: string;
  xai_api_key?:        string;
}
```

**Step 4: Add provider metadata constants** (for UI labeling):

```typescript
export const PROVIDER_LABELS: Record<string, string> = {
  anthropic:  'Anthropic',
  openai:     'OpenAI',
  google:     'Google',
  perplexity: 'Perplexity',
  xai:        'xAI (Grok)',
};

export const PROVIDER_KEY_FIELD: Record<string, keyof SystemSettingsUpdate> = {
  anthropic:  'anthropic_api_key',
  openai:     'openai_api_key',
  google:     'google_api_key',
  perplexity: 'perplexity_api_key',
  xai:        'xai_api_key',
};
```

**Step 5: TypeScript check**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check
```

Expected: errors in `SystemSettings.tsx` (model picker references — fixed in Task 12).

**Step 6: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add frontend/src/types/admin.ts && git commit -m "feat: add provider metadata and API key fields to admin types"
```

---

### Task 12: Add API Keys card and provider hints to SystemSettings UI

**Files:**
- Modify: `frontend/src/pages/admin/SystemSettings.tsx`

This is the largest frontend change. Make all edits in one pass.

**Step 1: Add import for new constants**

At top of `SystemSettings.tsx`, add to the existing admin import line:

```typescript
import { PROVIDER_LABELS, PROVIDER_KEY_FIELD } from '@/types/admin';
import type { SystemSettingsUpdate } from '@/types/admin';
```

**Step 2: Add `ApiKeyCard` component** — place it after the `ModelSelector` component and before `SectionHeader`:

```tsx
// ─── API Keys card ────────────────────────────────────────────────────────────

const PROVIDERS = ['anthropic', 'openai', 'google', 'perplexity', 'xai'] as const;
type Provider = typeof PROVIDERS[number];

function ApiKeysCard({
  settings,
  onSave,
  isSaving,
}: {
  settings: SystemSettings | undefined;
  onSave: (keys: Partial<SystemSettingsUpdate>) => void;
  isSaving: boolean;
}) {
  // null  = untouched (omit from payload)
  // ""    = user clicked Clear (send "" to clear the key)
  // "..." = new value typed by user
  const [keyValues, setKeyValues] = useState<Record<Provider, string | null>>(
    () => Object.fromEntries(PROVIDERS.map((p) => [p, null])) as Record<Provider, string | null>
  );
  const [showKey, setShowKey] = useState<Record<Provider, boolean>>(
    () => Object.fromEntries(PROVIDERS.map((p) => [p, false])) as Record<Provider, boolean>
  );
  const [adminName, setAdminName] = useState('');
  const [nameError, setNameError] = useState('');

  const handleChange = (provider: Provider, value: string) => {
    setKeyValues((prev) => ({ ...prev, [provider]: value }));
  };

  const handleClear = (provider: Provider) => {
    setKeyValues((prev) => ({ ...prev, [provider]: '' }));
  };

  const handleSave = () => {
    if (!adminName.trim()) {
      setNameError('Your name is required for the audit trail');
      return;
    }
    setNameError('');
    const changed: Partial<SystemSettingsUpdate> = { updated_by: adminName };
    for (const provider of PROVIDERS) {
      if (keyValues[provider] !== null) {
        const field = PROVIDER_KEY_FIELD[provider];
        (changed as Record<string, string>)[field] = keyValues[provider] as string;
      }
    }
    onSave(changed);
    // Reset dirty state after save
    setKeyValues(Object.fromEntries(PROVIDERS.map((p) => [p, null])) as Record<Provider, string | null>);
  };

  const anyDirty = Object.values(keyValues).some((v) => v !== null);
  const getMasked = (provider: Provider): string | null => {
    const field = PROVIDER_KEY_FIELD[provider];
    return settings?.[field as keyof SystemSettings] as string | null;
  };

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-sm">API Keys</CardTitle>
      </CardHeader>
      <CardContent className="pt-0 space-y-4">
        <SectionHeader
          title="Provider API Keys"
          description="Configure API keys for each AI provider. Keys are stored securely and displayed masked. Leave blank to keep the existing key."
        />
        <div className="space-y-3">
          {PROVIDERS.map((provider) => {
            const masked = getMasked(provider);
            const current = keyValues[provider];
            const isSet = !!masked;
            const isDirty = current !== null;
            return (
              <div key={provider} className="flex items-center gap-3">
                <div className="w-32 shrink-0">
                  <span className="text-sm font-medium text-gray-700">{PROVIDER_LABELS[provider]}</span>
                </div>
                <div className="flex-1 relative">
                  <input
                    type={showKey[provider] ? 'text' : 'password'}
                    value={current ?? ''}
                    placeholder={isSet ? masked ?? '●●●●●●●●' : 'Enter API key'}
                    onChange={(e) => handleChange(provider, e.target.value)}
                    className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent pr-10"
                  />
                  <button
                    type="button"
                    onClick={() => setShowKey((prev) => ({ ...prev, [provider]: !prev[provider] }))}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-gray-400 hover:text-gray-600 text-xs"
                    aria-label={showKey[provider] ? 'Hide key' : 'Show key'}
                  >
                    {showKey[provider] ? 'Hide' : 'Show'}
                  </button>
                </div>
                {isSet && !isDirty && (
                  <button
                    type="button"
                    onClick={() => handleClear(provider)}
                    className="shrink-0 text-xs text-red-500 hover:text-red-700 font-medium"
                  >
                    Clear
                  </button>
                )}
                <span className={`shrink-0 text-xs font-medium ${isSet ? 'text-green-600' : 'text-gray-400'}`}>
                  {isDirty ? (current === '' ? 'Will clear' : 'Will update') : (isSet ? '✓ Set' : '○ Not set')}
                </span>
              </div>
            );
          })}
        </div>

        {anyDirty && (
          <div className="flex flex-col sm:flex-row items-start sm:items-end gap-3 pt-2 border-t border-gray-100">
            <div className="flex-1">
              <FieldLabel htmlFor="api_key_admin_name" label="Your Name (audit trail)" required />
              <input
                id="api_key_admin_name"
                type="text"
                placeholder="e.g. Jane Smith"
                value={adminName}
                onChange={(e) => setAdminName(e.target.value)}
                className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary"
              />
              {nameError && <FieldError message={nameError} />}
            </div>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-white bg-primary rounded-md hover:bg-primary/90 disabled:opacity-40"
            >
              {isSaving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
              Save API Keys
            </button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
```

**Step 3: Update `ModelSelector`** — show provider badge when a known model is selected

In the `ModelSelector` component, add after the `<select>`:

```tsx
      {!showCustom && value && (() => {
        const model = knownModels.find((m) => m.id === value);
        return model ? (
          <p className="text-xs text-gray-500 mt-1">
            Provider: <span className="font-medium">{PROVIDER_LABELS[model.provider] ?? model.provider}</span>
          </p>
        ) : null;
      })()}
```

**Step 4: Wire up `ApiKeysCard` in the main `SystemSettings` component**

In the main `SystemSettings()` component:

**4a. Import `useAvailableModels` is already imported. Also import `PROVIDER_LABELS` — already done in step 1.**

**4b. Add `ApiKeysCard` to the form JSX**, between the "Draft Generation" card and the "QA + Iteration" card:

```tsx
          {/* ── Section: API Keys ── */}
          <ApiKeysCard
            settings={settings}
            onSave={(keys) => {
              updateMutation.mutate(
                { ...keys } as SystemSettingsUpdate,
                {
                  onSuccess: (updated) => {
                    toastSuccess(`API keys saved — updated by ${updated.updated_by ?? 'admin'}`);
                  },
                  onError: (err) => {
                    const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
                    toastError(msg ?? err.message ?? 'Failed to save API keys.');
                  },
                }
              );
            }}
            isSaving={updateMutation.isPending}
          />
```

**Step 5: TypeScript check**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check
```

Expected: Clean (exit 0).

**Step 6: Run frontend tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run test -- --run
```

Expected: 35/35 pass.

**Step 7: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add frontend/src/pages/admin/SystemSettings.tsx frontend/src/types/admin.ts && git commit -m "feat: add API Keys card to Admin System Settings with per-provider key management"
```

---

## Summary of all changed files

| File | Change |
|------|--------|
| `requirements.txt` | Add `openai>=1.0.0` |
| `alembic/versions/014_add_provider_api_keys.py` | Migration: 5 new API key columns |
| `app/models/models.py` | 5 new columns on `SystemSettings` |
| `app/services/settings_service.py` | 5 key fields in `ActiveSettings`; clear-empty-string logic in `update_settings` |
| `app/schemas/schemas.py` | Remove claude- validator; multi-provider `KNOWN_LLM_MODELS`; key fields in response/update schemas |
| `app/api/admin_routes.py` | Mask keys in GET; `exclude_none=True` in PUT |
| `app/services/llm_adapter.py` | **New** — provider detection, key resolution, unified `call_llm()` |
| `app/services/draft_generation_service.py` | Replace 3 Anthropic call sites with `llm_adapter.call_llm` |
| `app/services/qa_iteration_service.py` | Replace 2 Anthropic call sites with `llm_adapter.call_llm` |
| `app/services/extraction_service.py` | Replace 1 Anthropic call site with `llm_adapter.call_llm` |
| `app/tests/test_system_settings.py` | New tests: key fields, masking, multi-provider validation |
| `app/tests/test_llm_adapter.py` | **New** — provider detection + key resolution tests |
| `frontend/src/types/admin.ts` | `provider` on `KnownLlmModel`; key fields on interfaces; constants |
| `frontend/src/pages/admin/SystemSettings.tsx` | `ApiKeysCard` component; provider badge in `ModelSelector` |
