# LLM Model Configurability Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Allow admins to select any Claude model (from a curated dropdown) or enter a custom model ID via the Admin → System Settings UI, replacing the hardcoded two-model allowlist.

**Architecture:** Remove the strict `_ALLOWED_LLM_MODELS` frozenset validator in the backend Pydantic schema (replace with a `claude-` prefix pattern check), add a `GET /admin/settings/available-models` endpoint that returns known models with labels, and update the frontend `<select>` model pickers to a `ModelSelector` component that shows known models plus a "Custom..." option with a free-text fallback.

**Tech Stack:** FastAPI + Pydantic v2 (backend), React 19 + TypeScript + React Hook Form (frontend), Vitest (frontend tests), pytest (backend tests).

---

### Task 1: Relax backend model validation in schemas.py

**Files:**
- Modify: `app/schemas/schemas.py:16-71`
- Test: `app/tests/test_system_settings.py`

**Step 1: Read the current test file to understand existing test patterns**

Read `app/tests/test_system_settings.py` to understand how `SystemSettingsUpdate` is exercised.

**Step 2: Write a failing test for a valid non-allowlisted Claude model**

Add this test to `app/tests/test_system_settings.py`:

```python
def test_settings_update_accepts_claude_haiku():
    """Non-allowlisted Claude model should be accepted after relaxing validation."""
    from app.schemas.schemas import SystemSettingsUpdate
    data = SystemSettingsUpdate(
        registry_staleness_hours=24,
        llm_model_name="claude-haiku-4-5-20251001",
        max_draft_length=50000,
        qa_passing_threshold=9.0,
        max_qa_iterations=3,
        qa_llm_model="claude-haiku-4-5-20251001",
        governance_score_threshold=9.0,
        llm_timeout_seconds=120,
        notification_webhook_url="",
        updated_by="admin",
    )
    assert data.llm_model_name == "claude-haiku-4-5-20251001"
    assert data.qa_llm_model == "claude-haiku-4-5-20251001"


def test_settings_update_rejects_non_claude_model():
    """Non-Anthropic model strings must be rejected."""
    import pytest
    from pydantic import ValidationError
    from app.schemas.schemas import SystemSettingsUpdate
    with pytest.raises(ValidationError, match="must start with 'claude-'"):
        SystemSettingsUpdate(
            registry_staleness_hours=24,
            llm_model_name="gpt-4o",
            max_draft_length=50000,
            qa_passing_threshold=9.0,
            max_qa_iterations=3,
            qa_llm_model="claude-sonnet-4-6",
            governance_score_threshold=9.0,
            llm_timeout_seconds=120,
            notification_webhook_url="",
            updated_by="admin",
        )
```

**Step 3: Run to verify test fails**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_settings_update_accepts_claude_haiku app/tests/test_system_settings.py::test_settings_update_rejects_non_claude_model -v
```

Expected: Both FAIL (haiku is blocked by current frozenset; "gpt-4o" error message won't match new wording yet).

**Step 4: Update `app/schemas/schemas.py` — replace frozenset with prefix check**

Replace lines 14–71 in `app/schemas/schemas.py`:

```python
# ── System Settings ──────────────────────────────────────────────────────────

# Known Claude models with display labels. Kept here for the
# /admin/settings/available-models endpoint. Not used for validation.
KNOWN_LLM_MODELS: list[dict[str, str]] = [
    {"id": "claude-opus-4-6",          "label": "Claude Opus 4.6 (Most Capable)"},
    {"id": "claude-sonnet-4-6",        "label": "Claude Sonnet 4.6 (Balanced)"},
    {"id": "claude-haiku-4-5-20251001","label": "Claude Haiku 4.5 (Fast & Efficient)"},
]


class SystemSettingsResponse(BaseModel):
    """Current system settings returned by GET /admin/settings."""

    model_config = ConfigDict(from_attributes=True)

    id: str
    registry_staleness_hours: int
    llm_model_name: str
    max_draft_length: int
    qa_passing_threshold: float
    max_qa_iterations: int
    qa_llm_model: str
    governance_score_threshold: float
    llm_timeout_seconds: int
    notification_webhook_url: Optional[str]
    updated_by: Optional[str]
    updated_at: datetime


class SystemSettingsUpdate(BaseModel):
    """Request body for PUT /admin/settings.

    Validation rules enforced by Pydantic (before DB write):
    - registry_staleness_hours   : >= 1
    - llm_model_name/qa_llm_model: must start with 'claude-' (Anthropic models only)
    - max_draft_length           : 1 000 – 100 000 characters
    - qa_passing_threshold       : 5.0 – 10.0 (safety floor)
    - max_qa_iterations          : >= 1
    - governance_score_threshold : 0.0 – 10.0, AND must be >= qa_passing_threshold
    - notification_webhook_url   : valid HTTP/HTTPS URL or empty string
    - updated_by                 : non-empty name of the admin making the change
    """

    registry_staleness_hours: int = Field(ge=1)
    llm_model_name: str = Field(min_length=1)
    max_draft_length: int = Field(ge=1000, le=100_000)
    qa_passing_threshold: float = Field(ge=5.0, le=10.0)
    max_qa_iterations: int = Field(ge=1)
    qa_llm_model: str = Field(min_length=1)
    governance_score_threshold: float = Field(ge=0.0, le=10.0)
    llm_timeout_seconds: int = Field(ge=30, le=600, default=120)
    notification_webhook_url: Optional[str] = Field(default="")
    updated_by: str = Field(min_length=1, max_length=512)

    @field_validator("llm_model_name", "qa_llm_model")
    @classmethod
    def validate_model_name(cls, v: str) -> str:
        if not v.startswith("claude-"):
            raise ValueError(
                f"Model '{v}' must start with 'claude-' (Anthropic models only). "
                "Example: claude-opus-4-6, claude-sonnet-4-6, claude-haiku-4-5-20251001"
            )
        return v

    @field_validator("notification_webhook_url")
    @classmethod
    def validate_webhook_url(cls, v: Optional[str]) -> str:
        if not v:
            return ""
        parsed = urlparse(v)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(
                "notification_webhook_url must use http or https, or be empty."
            )
        if not parsed.netloc:
            raise ValueError(
                "notification_webhook_url must include a valid hostname."
            )
        return v

    @model_validator(mode="after")
    def validate_threshold_ordering(self) -> "SystemSettingsUpdate":
        if self.governance_score_threshold < self.qa_passing_threshold:
            raise ValueError(
                f"governance_score_threshold ({self.governance_score_threshold:.1f}) "
                f"cannot be lower than qa_passing_threshold ({self.qa_passing_threshold:.1f}). "
                "Lowering governance below QA would allow documents to skip proper QA validation."
            )
        return self
```

**Step 5: Run tests to verify both pass**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py -v
```

Expected: All tests PASS.

**Step 6: Run full backend test suite to check for regressions**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest -x -q
```

Expected: All tests pass (or pre-existing failures only).

**Step 7: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add app/schemas/schemas.py app/tests/test_system_settings.py && git commit -m "feat: relax LLM model validation to allow any claude-* model"
```

---

### Task 2: Add GET /admin/settings/available-models endpoint

**Files:**
- Modify: `app/api/admin_routes.py`

**Step 1: Write a failing test**

Add to `app/tests/test_system_settings.py`:

```python
def test_available_models_endpoint(client):
    """GET /api/v1/admin/settings/available-models returns list of known models."""
    response = client.get("/api/v1/admin/settings/available-models")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 3
    ids = [m["id"] for m in data]
    assert "claude-opus-4-6" in ids
    assert "claude-sonnet-4-6" in ids
    assert "claude-haiku-4-5-20251001" in ids
    # Each entry must have id and label
    for m in data:
        assert "id" in m
        assert "label" in m
```

**Step 2: Run to verify test fails**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_available_models_endpoint -v
```

Expected: FAIL with 404 or AttributeError.

**Step 3: Add the endpoint to `app/api/admin_routes.py`**

Add these imports at the top of `admin_routes.py` (after existing imports):

```python
from app.schemas.schemas import KNOWN_LLM_MODELS
```

Add the endpoint after the existing `get_system_settings` function:

```python
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
```

**Step 4: Run test to verify it passes**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest app/tests/test_system_settings.py::test_available_models_endpoint -v
```

Expected: PASS.

**Step 5: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add app/api/admin_routes.py app/tests/test_system_settings.py && git commit -m "feat: add GET /admin/settings/available-models endpoint"
```

---

### Task 3: Update frontend types to support free-text model IDs

**Files:**
- Modify: `frontend/src/types/admin.ts`

**Step 1: Update `frontend/src/types/admin.ts`**

Replace lines 1–21 of the System Settings section:

```typescript
// ── System Settings ──────────────────────────────────────────────────────────

export interface KnownLlmModel {
  id: string;
  label: string;
}

// Models known to be available. Fetched from GET /admin/settings/available-models.
// The type for model fields is plain `string` to allow custom model IDs.
export interface SystemSettings {
  id: string;
  registry_staleness_hours: number;
  llm_model_name: string;
  max_draft_length: number;
  qa_passing_threshold: number;
  max_qa_iterations: number;
  qa_llm_model: string;
  governance_score_threshold: number;
  llm_timeout_seconds: number;
  notification_webhook_url: string | null;
  updated_by: string | null;
  updated_at: string;
}

export interface SystemSettingsUpdate {
  registry_staleness_hours: number;
  llm_model_name: string;
  max_draft_length: number;
  qa_passing_threshold: number;
  max_qa_iterations: number;
  qa_llm_model: string;
  governance_score_threshold: number;
  llm_timeout_seconds: number;
  notification_webhook_url: string;
  updated_by: string;
}
```

Remove the old `ALLOWED_LLM_MODELS` and `AllowedLlmModel` exports entirely — they are no longer needed.

**Step 2: Check TypeScript still compiles**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check 2>&1 | head -40
```

Expected: Errors related to `ALLOWED_LLM_MODELS` and `AllowedLlmModel` being referenced in `SystemSettings.tsx` (that's expected — we fix those in the next task).

**Step 3: Commit (partial — types only, TypeScript errors expected)**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add frontend/src/types/admin.ts && git commit -m "refactor: broaden model field types from union to string for custom model support"
```

---

### Task 4: Add useAvailableModels hook

**Files:**
- Modify: `frontend/src/services/settings.ts`
- Modify: `frontend/src/hooks/index.ts` (or wherever hooks are exported)

**Step 1: Locate the hooks file**

Check `frontend/src/hooks/` to find where `useSystemSettings` is defined — this is where the new hook goes.

**Step 2: Add `getAvailableModels` to the settings service**

In `frontend/src/services/settings.ts`, add:

```typescript
import type { KnownLlmModel } from '@/types/admin';

export function getAvailableModels(): Promise<KnownLlmModel[]> {
  return apiRequest<KnownLlmModel[]>({
    method: 'GET',
    url: '/admin/settings/available-models',
  });
}
```

**Step 3: Add `useAvailableModels` hook**

In the same file as `useSystemSettings`, add:

```typescript
export function useAvailableModels() {
  return useQuery({
    queryKey: ['admin', 'available-models'],
    queryFn: getAvailableModels,
    staleTime: Infinity, // model list rarely changes
  });
}
```

Export it from the hooks index if there is one.

**Step 4: Verify TypeScript compiles for services**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check 2>&1 | grep "services\|hooks" | head -20
```

**Step 5: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add frontend/src/services/settings.ts frontend/src/hooks/ && git commit -m "feat: add useAvailableModels hook for fetching known Claude models"
```

---

### Task 5: Build ModelSelector component and update SystemSettings UI

**Files:**
- Modify: `frontend/src/pages/admin/SystemSettings.tsx`

**Step 1: Read the current SystemSettings.tsx to understand exact structure**

Read `frontend/src/pages/admin/SystemSettings.tsx` (already read — reference lines 25–28 for `MODEL_LABELS`, lines 414–426 and 529–542 for the existing `<select>` elements, line 17 for `ALLOWED_LLM_MODELS` import).

**Step 2: Make the following changes to `SystemSettings.tsx`**

**2a. Remove old imports**

Remove the line:
```typescript
import { ALLOWED_LLM_MODELS } from '@/types/admin';
```

Replace with:
```typescript
import { useAvailableModels } from '@/hooks';
```

**2b. Remove `MODEL_LABELS` constant and replace with a default fallback**

Delete the `MODEL_LABELS` constant block (lines 25–28). The labels now come from the API.

**2c. Add the `ModelSelector` component** (place it just before the `SectionHeader` function):

```tsx
// ─── ModelSelector component ─────────────────────────────────────────────────

const CUSTOM_VALUE = '__custom__';

function ModelSelector({
  id,
  value,
  onChange,
  label,
  required,
  error,
}: {
  id: string;
  value: string;
  onChange: (v: string) => void;
  label: string;
  required?: boolean;
  error?: string;
}) {
  const { data: knownModels = [] } = useAvailableModels();

  // Determine if the current value is a known model or a custom one
  const isCustom = value !== '' && !knownModels.some((m) => m.id === value);
  const [showCustom, setShowCustom] = useState(isCustom);
  const [customValue, setCustomValue] = useState(isCustom ? value : '');

  // Sync showCustom when value changes externally (e.g. form reset)
  useEffect(() => {
    const external = value !== '' && !knownModels.some((m) => m.id === value);
    setShowCustom(external);
    if (external) setCustomValue(value);
  }, [value, knownModels]);

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      setShowCustom(true);
      onChange(customValue); // keep whatever was typed before
    } else {
      setShowCustom(false);
      onChange(v);
    }
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const v = e.target.value;
    setCustomValue(v);
    onChange(v);
  };

  return (
    <div>
      <FieldLabel htmlFor={id} label={label} required={required} />
      <select
        id={id}
        value={showCustom ? CUSTOM_VALUE : value}
        onChange={handleSelectChange}
        className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
      >
        {knownModels.map((m) => (
          <option key={m.id} value={m.id}>
            {m.label}
          </option>
        ))}
        <option value={CUSTOM_VALUE}>Custom model ID...</option>
      </select>
      {showCustom && (
        <div className="mt-2">
          <input
            type="text"
            placeholder="e.g. claude-opus-4-6"
            value={customValue}
            onChange={handleCustomChange}
            className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          />
          <p className="text-xs text-gray-500 mt-1">
            Must start with <code>claude-</code>. Example: <code>claude-opus-4-6</code>
          </p>
        </div>
      )}
      {error && <FieldError message={error} />}
    </div>
  );
}
```

**2d. Replace the `llm_model_name` `<select>` block (lines ~413–426)**

Remove:
```tsx
<div>
  <FieldLabel htmlFor="llm_model_name" label="Draft Generation Model" required />
  <select
    id="llm_model_name"
    {...register('llm_model_name', { required: 'Required' })}
    className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
  >
    {ALLOWED_LLM_MODELS.map((model) => (
      <option key={model} value={model}>
        {MODEL_LABELS[model] ?? model}
      </option>
    ))}
  </select>
  <FieldError message={errors.llm_model_name?.message} />
</div>
```

Replace with a `Controller` that drives `ModelSelector`:
```tsx
<Controller
  name="llm_model_name"
  control={control}
  rules={{
    required: 'Required',
    validate: (v) =>
      v.startsWith('claude-') || "Model ID must start with 'claude-'",
  }}
  render={({ field }) => (
    <ModelSelector
      id="llm_model_name"
      label="Draft Generation Model"
      required
      value={field.value}
      onChange={field.onChange}
      error={errors.llm_model_name?.message}
    />
  )}
/>
```

**2e. Replace the `qa_llm_model` `<select>` block (lines ~529–542)**

Remove:
```tsx
<div>
  <FieldLabel htmlFor="qa_llm_model" label="QA Evaluation Model" required />
  <select
    id="qa_llm_model"
    {...register('qa_llm_model', { required: 'Required' })}
    className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent bg-white"
  >
    {ALLOWED_LLM_MODELS.map((model) => (
      <option key={model} value={model}>
        {MODEL_LABELS[model] ?? model}
      </option>
    ))}
  </select>
  <FieldError message={errors.qa_llm_model?.message} />
</div>
```

Replace with:
```tsx
<Controller
  name="qa_llm_model"
  control={control}
  rules={{
    required: 'Required',
    validate: (v) =>
      v.startsWith('claude-') || "Model ID must start with 'claude-'",
  }}
  render={({ field }) => (
    <ModelSelector
      id="qa_llm_model"
      label="QA Evaluation Model"
      required
      value={field.value}
      onChange={field.onChange}
      error={errors.qa_llm_model?.message}
    />
  )}
/>
```

**Step 3: Run TypeScript type check**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check 2>&1
```

Expected: No errors.

**Step 4: Run frontend lint**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run lint 2>&1
```

Expected: No errors.

**Step 5: Run frontend unit tests**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run test -- --run 2>&1 | tail -20
```

Expected: All pass (or pre-existing failures only).

**Step 6: Commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add frontend/src/pages/admin/SystemSettings.tsx && git commit -m "feat: replace hardcoded model dropdowns with ModelSelector supporting custom model IDs"
```

---

### Task 6: Update default form values to not rely on removed AllowedLlmModel type

**Files:**
- Modify: `frontend/src/pages/admin/SystemSettings.tsx` (form default values and reset calls)

This task is a cleanup pass. After Task 5, verify the `useForm` `defaultValues` and all `reset(...)` calls in `SystemSettings.tsx` use plain string literals (they already do — confirm no `AllowedLlmModel` type assertion is needed).

**Step 1: Verify no TypeScript errors remain**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI/frontend && npm run type-check 2>&1
```

Expected: Clean.

**Step 2: Run full test suite one final time**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && source venv/bin/activate && pytest -q && cd frontend && npm run test -- --run 2>&1 | tail -10
```

Expected: All tests pass.

**Step 3: Final commit**

```bash
cd /Users/deepakpanwar/Desktop/VS_Workspace/VeritasAI && git add -A && git commit -m "chore: verify type cleanup for LLM model configurability feature"
```

---

## Summary of all changed files

| File | Change |
|------|--------|
| `app/schemas/schemas.py` | Replace frozenset allowlist with `claude-` prefix validator; export `KNOWN_LLM_MODELS` |
| `app/api/admin_routes.py` | Add `GET /admin/settings/available-models` endpoint |
| `app/tests/test_system_settings.py` | Add tests for haiku model acceptance, non-claude rejection, and available-models endpoint |
| `frontend/src/types/admin.ts` | Remove `ALLOWED_LLM_MODELS`/`AllowedLlmModel`; add `KnownLlmModel` interface; model fields → `string` |
| `frontend/src/services/settings.ts` | Add `getAvailableModels()` function |
| `frontend/src/hooks/` | Add `useAvailableModels` hook |
| `frontend/src/pages/admin/SystemSettings.tsx` | Add `ModelSelector` component; replace both `<select>` model pickers with `Controller`+`ModelSelector` |
