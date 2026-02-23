# Multi-Provider LLM Support Design

**Date:** 2026-02-23
**Status:** Approved

---

## Goal

Allow admins to configure API keys for multiple AI providers (Anthropic, OpenAI, Google, Perplexity, xAI) and select models from any provider for draft generation and QA evaluation via Admin → System Settings.

---

## Architecture

### Provider Routing

A new `app/services/llm_adapter.py` acts as the single LLM call boundary.

**Provider detection by model name prefix:**

| Prefix | Provider | SDK |
|--------|----------|-----|
| `claude-*` | Anthropic | `anthropic` SDK |
| `gpt-*`, `o1*`, `o3*` | OpenAI | `openai` SDK |
| `gemini-*` | Google | `openai` SDK (OpenAI-compatible endpoint) |
| `grok-*` | xAI | `openai` SDK (OpenAI-compatible endpoint) |
| anything else | Perplexity | `openai` SDK (OpenAI-compatible endpoint) |

**OpenAI-compatible base URLs:**

| Provider | base_url |
|----------|----------|
| OpenAI | `https://api.openai.com/v1` |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` |
| xAI Grok | `https://api.x.ai/v1` |
| Perplexity | `https://api.perplexity.ai` |

**Normalized interface:**

```python
def call_llm(prompt: str, model_name: str, settings: ActiveSettings, timeout: int) -> str:
    """Call the appropriate LLM provider and return the generated text."""
```

All three services (`draft_generation_service`, `qa_iteration_service`, `extraction_service`) replace direct Anthropic calls with `call_llm(...)`.

---

## Backend Changes

### 1. Database — `system_settings` table (new migration)

Add 5 nullable columns for provider API keys:

```
anthropic_api_key  VARCHAR(512)  NULL  -- fallback: ANTHROPIC_API_KEY env var
openai_api_key     VARCHAR(512)  NULL
google_api_key     VARCHAR(512)  NULL
perplexity_api_key VARCHAR(512)  NULL
xai_api_key        VARCHAR(512)  NULL
```

### 2. `app/models/models.py`

Add 5 new columns to `SystemSettings`.

### 3. `app/services/settings_service.py`

- Add key fields to `ActiveSettings` dataclass
- `_row_to_active()`: copy raw key values (full, unmasked — only masked at the API layer)
- Key resolution: `anthropic_api_key` falls back to `ANTHROPIC_API_KEY` env var if null

### 4. `app/schemas/schemas.py`

- Remove `claude-` prefix validator — replace with `min_length=1`
- Add 5 optional API key fields to `SystemSettingsResponse` — **masked** (`****abc1` or `null`)
- Add 5 optional API key fields to `SystemSettingsUpdate` — `Optional[str] = None`
  - `None` = don't change, `""` = clear, non-empty = update
- Update `KNOWN_LLM_MODELS` to include models from all 5 providers (with `provider` field)

### 5. `app/api/admin_routes.py`

- `GET /admin/settings`: mask key fields before returning (`****` + last 4 chars, or `null`)
- `PUT /admin/settings`: skip key fields that are `None` (not provided); clear if `""`

### 6. `app/services/llm_adapter.py` (new file)

```python
def detect_provider(model_name: str) -> str: ...
def call_llm(prompt: str, model_name: str, settings: ActiveSettings, timeout: int) -> str: ...
```

### 7. Service updates

Replace direct `anthropic.Anthropic(...)` calls in:
- `app/services/draft_generation_service.py` (2 call sites)
- `app/services/qa_iteration_service.py` (2 call sites)
- `app/services/extraction_service.py` (1 call site)

Each call site replaces the SDK-specific block with `call_llm(prompt, model_name, settings, timeout)`.

---

## Frontend Changes

### 1. `frontend/src/types/admin.ts`

- Add provider API key fields to `SystemSettings` (masked `string | null`)
- Add optional key fields to `SystemSettingsUpdate` (`string | undefined`)
- Add `provider` field to `KnownLlmModel`
- Add `PROVIDER_LABELS` and `PROVIDER_KEY_FIELD` maps

### 2. `frontend/src/pages/admin/SystemSettings.tsx`

**New "API Keys" card** (separate from main form to avoid key masking issues):

- One row per provider: Anthropic, OpenAI, Google (Gemini), Perplexity, xAI (Grok)
- `type="password"` inputs with show/hide toggle
- Shows masked value if key is set, placeholder if not
- "Clear" button to explicitly remove a key
- "Configured ✓" / "Not configured" badge per provider
- Own Save button — sends only changed/cleared keys

**Updated `ModelSelector`:**

- `KNOWN_LLM_MODELS` now includes models from all providers
- After model selection, show provider hint: "Requires [Provider] API key — ✓ Set / ✗ Not set"
- Link to API Keys section if key is missing

### 3. `frontend/src/services/settings.ts`

No changes needed (PUT /admin/settings handles the combined payload).

---

## Security Notes

- API keys are stored as plaintext in the DB (same security posture as existing settings)
- GET response always masks keys — full key never sent to browser after initial save
- `ANTHROPIC_API_KEY` env var acts as fallback for Anthropic so existing deployments keep working

---

## Known Limitations

- No per-request provider failover — if the configured key is invalid, the pipeline errors
- No key validation on save — keys are tested only when an LLM call is made
- Multi-worker caveat: API keys cached in-memory per worker (same as existing settings)
