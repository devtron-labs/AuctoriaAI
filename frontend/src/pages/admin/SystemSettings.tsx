import { useEffect, useState } from 'react';
import { useForm, Controller } from 'react-hook-form';
import {
  Save,
  RefreshCw,
  Webhook,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Clock,
  User,
  Loader2,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { useSystemSettings, useUpdateSystemSettings, useTestWebhook, useAvailableModels } from '@/hooks';
import { PROVIDER_LABELS, PROVIDER_KEY_FIELD } from '@/types/admin';
import type { SystemSettings, SystemSettingsUpdate } from '@/types/admin';
import { formatDateTime } from '@/lib/utils';
import { useToast } from '@/providers/ToastProvider';
// useToast provides: success(), error(), info(), warning(), toast(msg, type?)

// ─── ModelSelector sentinel value ────────────────────────────────────────────

const CUSTOM_VALUE = '__custom__';

// ─── ModelSelector component ──────────────────────────────────────────────────

// Sentinel written into the form field when "Custom..." is first selected.
// Starts with a space so showCustom immediately becomes true (value is
// non-empty and not in the known list). User replaces it with a real model ID.
const CUSTOM_STARTER = ' ';

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

  // Derive custom mode purely from value — no effect needed.
  // Custom input is shown when value is non-empty AND not in the known list.
  // On external form reset value returns to a known model → showCustom = false.
  const valueIsKnown = knownModels.some((m) => m.id === value);
  const showCustom = value !== '' && !valueIsKnown;

  const handleSelectChange = (e: React.ChangeEvent<HTMLSelectElement>) => {
    const v = e.target.value;
    if (v === CUSTOM_VALUE) {
      // Seed with CUSTOM_STARTER so showCustom immediately becomes true and
      // the user has a helpful prefix to type after.
      onChange(CUSTOM_STARTER);
    } else {
      onChange(v);
    }
  };

  const handleCustomChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    onChange(e.target.value);
  };

  return (
    <div>
      <label htmlFor={id} className="block text-sm font-medium text-gray-700 mb-1">
        {label}
        {required && <span className="text-red-500 ml-1" aria-hidden>*</span>}
      </label>
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
      {!showCustom && value && (() => {
        const model = knownModels.find((m) => m.id === value);
        return model ? (
          <p className="text-xs text-gray-500 mt-1">
            Provider: <span className="font-medium">{PROVIDER_LABELS[model.provider] ?? model.provider}</span>
          </p>
        ) : null;
      })()}
      {showCustom && (
        <div className="mt-2">
          <input
            type="text"
            placeholder="e.g. gpt-4o, gemini-2.0-flash, claude-opus-4-6"
            value={value.trim()}
            onChange={handleCustomChange}
            className="w-full max-w-sm px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
          />
          <p className="text-xs text-gray-500 mt-1">
            Enter any supported model ID (e.g. <code>gpt-4o</code>, <code>gemini-2.0-flash</code>, <code>claude-opus-4-6</code>).
          </p>
        </div>
      )}
      {error && (
        <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
          <AlertTriangle className="h-3 w-3" />
          {error}
        </p>
      )}
    </div>
  );
}

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

// ─── Shared UI primitives ────────────────────────────────────────────────────

function SectionHeader({ title, description }: { title: string; description?: string }) {
  return (
    <div className="mb-4">
      <h3 className="text-base font-semibold text-gray-900">{title}</h3>
      {description && <p className="text-sm text-gray-500 mt-0.5">{description}</p>}
    </div>
  );
}

function FieldError({ message }: { message?: string }) {
  if (!message) return null;
  return (
    <p className="text-xs text-red-600 mt-1 flex items-center gap-1">
      <AlertTriangle className="h-3 w-3" />
      {message}
    </p>
  );
}

function FieldLabel({ htmlFor, label, required }: { htmlFor: string; label: string; required?: boolean }) {
  return (
    <label htmlFor={htmlFor} className="block text-sm font-medium text-gray-700 mb-1">
      {label}
      {required && <span className="text-red-500 ml-1" aria-hidden>*</span>}
    </label>
  );
}

// ─── Slider component ─────────────────────────────────────────────────────────

function ThresholdSlider({
  id,
  value,
  onChange,
  min = 0,
  max = 10,
  step = 0.5,
  label,
  hint,
}: {
  id: string;
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
  label: string;
  hint?: string;
}) {
  const percentage = ((value - min) / (max - min)) * 100;

  return (
    <div>
      <FieldLabel htmlFor={id} label={label} />
      <div className="flex items-center gap-3">
        <input
          id={id}
          type="range"
          min={min}
          max={max}
          step={step}
          value={value}
          onChange={(e) => onChange(parseFloat(e.target.value))}
          className="flex-1 h-2 rounded-lg appearance-none cursor-pointer bg-gray-200"
          style={{
            background: `linear-gradient(to right, hsl(var(--primary)) 0%, hsl(var(--primary)) ${percentage}%, #e5e7eb ${percentage}%, #e5e7eb 100%)`,
          }}
        />
        <span className="w-12 text-right text-sm font-semibold text-gray-900 tabular-nums">
          {value.toFixed(1)}
        </span>
      </div>
      {hint && <p className="text-xs text-gray-500 mt-1">{hint}</p>}
    </div>
  );
}

// ─── Confirm dialog ───────────────────────────────────────────────────────────

function ConfirmDialog({
  open,
  onConfirm,
  onCancel,
  isLoading,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
  isLoading: boolean;
}) {
  if (!open) return null;
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="bg-white rounded-xl shadow-2xl p-6 max-w-sm w-full mx-4">
        <div className="flex items-start gap-3 mb-4">
          <AlertTriangle className="h-5 w-5 text-amber-500 mt-0.5 shrink-0" />
          <div>
            <h2 className="text-base font-semibold text-gray-900">Save System Settings?</h2>
            <p className="text-sm text-gray-600 mt-1">
              These changes will affect all active document workflows immediately.
              Changing QA or governance thresholds may alter which documents pass or fail.
            </p>
          </div>
        </div>
        <div className="flex gap-2 justify-end mt-4">
          <button
            type="button"
            onClick={onCancel}
            disabled={isLoading}
            className="px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={onConfirm}
            disabled={isLoading}
            className="px-4 py-2 text-sm font-medium text-white bg-primary rounded-md hover:bg-primary/90 disabled:opacity-50 flex items-center gap-2"
          >
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            Confirm & Save
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── Webhook test status ──────────────────────────────────────────────────────

function WebhookTestStatus({
  result,
}: {
  result: { success: boolean; status_code?: number; error?: string } | null;
}) {
  if (!result) return null;
  return (
    <div
      className={`flex items-start gap-2 p-3 rounded-md text-sm mt-2 ${
        result.success ? 'bg-green-50 text-green-800' : 'bg-red-50 text-red-800'
      }`}
    >
      {result.success ? (
        <CheckCircle className="h-4 w-4 mt-0.5 shrink-0 text-green-600" />
      ) : (
        <XCircle className="h-4 w-4 mt-0.5 shrink-0 text-red-600" />
      )}
      <div>
        {result.success ? (
          <span>Webhook reached successfully (HTTP {result.status_code}).</span>
        ) : (
          <span>Webhook test failed: {result.error ?? `HTTP ${result.status_code}`}</span>
        )}
      </div>
    </div>
  );
}

// ─── Main Component ───────────────────────────────────────────────────────────

export default function SystemSettings() {
  const { data: settings, isLoading, error } = useSystemSettings();
  const updateMutation = useUpdateSystemSettings();
  const testMutation = useTestWebhook();
  const { success: toastSuccess, error: toastError } = useToast();

  const [showConfirm, setShowConfirm] = useState(false);
  const [pendingData, setPendingData] = useState<SystemSettingsUpdate | null>(null);
  const [webhookTestResult, setWebhookTestResult] = useState<{
    success: boolean;
    status_code?: number;
    error?: string;
  } | null>(null);

  const {
    register,
    handleSubmit,
    control,
    reset,
    watch,
    formState: { errors, isDirty },
  } = useForm<SystemSettingsUpdate>({
    defaultValues: {
      registry_staleness_hours: 24,
      llm_model_name: 'claude-opus-4-6',
      max_draft_length: 50000,
      qa_passing_threshold: 9.0,
      max_qa_iterations: 3,
      qa_llm_model: 'claude-sonnet-4-6',
      governance_score_threshold: 9.0,
      llm_timeout_seconds: 120,
      notification_webhook_url: '',
      updated_by: '',
    },
  });

  // Sync form with server values when loaded
  useEffect(() => {
    if (settings) {
      reset({
        registry_staleness_hours: settings.registry_staleness_hours,
        llm_model_name: settings.llm_model_name,
        max_draft_length: settings.max_draft_length,
        qa_passing_threshold: settings.qa_passing_threshold,
        max_qa_iterations: settings.max_qa_iterations,
        qa_llm_model: settings.qa_llm_model,
        governance_score_threshold: settings.governance_score_threshold,
        llm_timeout_seconds: settings.llm_timeout_seconds ?? 120,
        notification_webhook_url: settings.notification_webhook_url ?? '',
        updated_by: '',
      });
    }
  }, [settings, reset]);

  const watchedQaThreshold = watch('qa_passing_threshold');
  const watchedGovThreshold = watch('governance_score_threshold');
  const watchedWebhook = watch('notification_webhook_url');

  // Client-side cross-field validation
  const govBelowQa =
    watchedGovThreshold !== undefined &&
    watchedQaThreshold !== undefined &&
    watchedGovThreshold < watchedQaThreshold;

  const onSubmit = (data: SystemSettingsUpdate) => {
    setPendingData(data);
    setShowConfirm(true);
  };

  const handleConfirm = () => {
    if (!pendingData) return;
    updateMutation.mutate(pendingData, {
      onSuccess: (updated) => {
        setShowConfirm(false);
        setPendingData(null);
        reset({
          ...pendingData,
          updated_by: '',
        });
        toastSuccess(
          `Settings saved — updated by ${updated.updated_by ?? 'admin'} at ${formatDateTime(updated.updated_at)}`
        );
      },
      onError: (err) => {
        setShowConfirm(false);
        const msg = (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail;
        toastError(msg ?? err.message ?? 'An unexpected error occurred.');
      },
    });
  };

  const handleTestWebhook = () => {
    setWebhookTestResult(null);
    testMutation.mutate(undefined, {
      onSuccess: (result) => {
        setWebhookTestResult(result);
      },
      onError: (err) => {
        setWebhookTestResult({ success: false, error: err.message });
      },
    });
  };

  // ── Loading / Error states ────────────────────────────────────────────────

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-8 w-8 animate-spin text-primary" />
      </div>
    );
  }

  if (error) {
    return (
      <Card className="border-red-200 bg-red-50">
        <CardContent className="pt-6">
          <p className="text-red-600 text-sm">
            Failed to load system settings. Please ensure the backend is running.
          </p>
        </CardContent>
      </Card>
    );
  }

  // ── Form ──────────────────────────────────────────────────────────────────

  return (
    <>
      <ConfirmDialog
        open={showConfirm}
        onConfirm={handleConfirm}
        onCancel={() => {
          setShowConfirm(false);
          setPendingData(null);
        }}
        isLoading={updateMutation.isPending}
      />

      <form onSubmit={handleSubmit(onSubmit)} noValidate>
        <div className="space-y-6">
          {/* Header */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-lg font-semibold text-gray-900">System Settings</h2>
              <p className="text-sm text-gray-500 mt-0.5">
                Admin-configurable AI governance parameters. Changes take effect within 60 seconds.
              </p>
            </div>
            <div className="flex flex-col items-end gap-1 shrink-0">
              {settings?.updated_at && (
                <div className="flex items-center gap-1.5 text-xs text-gray-400">
                  <Clock className="h-3 w-3" />
                  Last saved {formatDateTime(settings.updated_at)}
                </div>
              )}
              {settings?.updated_by && (
                <div className="flex items-center gap-1.5 text-xs text-gray-400">
                  <User className="h-3 w-3" />
                  by {settings.updated_by}
                </div>
              )}
            </div>
          </div>

          {/* Unsaved changes banner */}
          {isDirty && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-amber-50 border border-amber-200 rounded-lg text-sm text-amber-800">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              You have unsaved changes.
            </div>
          )}

          {/* Cross-field validation warning */}
          {govBelowQa && (
            <div className="flex items-center gap-2 px-4 py-2.5 bg-red-50 border border-red-200 rounded-lg text-sm text-red-800">
              <AlertTriangle className="h-4 w-4 shrink-0" />
              Governance threshold ({watchedGovThreshold?.toFixed(1)}) must be ≥ QA threshold (
              {watchedQaThreshold?.toFixed(1)}).
            </div>
          )}

          {/* ── Section: Registry ── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Registry</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <SectionHeader
                title="Claim Registry Freshness"
                description="How many hours before the claim registry is considered stale. Extraction will fail if the registry is older than this."
              />
              <div>
                <FieldLabel htmlFor="registry_staleness_hours" label="Registry Staleness (hours)" required />
                <input
                  id="registry_staleness_hours"
                  type="number"
                  min={1}
                  {...register('registry_staleness_hours', {
                    required: 'Required',
                    min: { value: 1, message: 'Must be at least 1 hour' },
                    valueAsNumber: true,
                  })}
                  className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                <FieldError message={errors.registry_staleness_hours?.message} />
              </div>
            </CardContent>
          </Card>

          {/* ── Section: Draft Generation ── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Draft Generation</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-4">
              <SectionHeader
                title="LLM Configuration"
                description="Model used for fact sheet extraction and whitepaper draft generation."
              />
              <Controller
                name="llm_model_name"
                control={control}
                rules={{
                  required: 'Required',
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

              <div>
                <FieldLabel htmlFor="max_draft_length" label="Max Draft Length (characters)" required />
                <input
                  id="max_draft_length"
                  type="number"
                  min={1000}
                  max={100000}
                  step={1000}
                  {...register('max_draft_length', {
                    required: 'Required',
                    min: { value: 1000, message: 'Minimum 1,000 characters' },
                    max: { value: 100000, message: 'Maximum 100,000 characters' },
                    valueAsNumber: true,
                  })}
                  className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">Between 1,000 and 100,000 characters.</p>
                <FieldError message={errors.max_draft_length?.message} />
              </div>

              <div>
                <FieldLabel htmlFor="llm_timeout_seconds" label="LLM Request Timeout (seconds)" required />
                <input
                  id="llm_timeout_seconds"
                  type="number"
                  min={30}
                  max={600}
                  step={30}
                  {...register('llm_timeout_seconds', {
                    required: 'Required',
                    min: { value: 30, message: 'Minimum 30 seconds' },
                    max: { value: 600, message: 'Maximum 600 seconds (10 minutes)' },
                    valueAsNumber: true,
                  })}
                  className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">
                  30–600 seconds. Applies to every LLM call (draft generation, QA, governance).
                  Increase for complex documents that require longer generation time.
                </p>
                <FieldError message={errors.llm_timeout_seconds?.message} />
              </div>
            </CardContent>
          </Card>

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

          {/* ── Section: QA Iteration ── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">QA + Iteration</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-5">
              <SectionHeader
                title="Quality Assurance"
                description="Rubric scoring and iteration settings. A draft must reach the passing threshold to proceed to governance."
              />

              <Controller
                name="qa_passing_threshold"
                control={control}
                rules={{
                  required: 'Required',
                  min: { value: 5.0, message: 'QA threshold must be ≥ 5.0 (safety floor)' },
                  max: { value: 10.0, message: 'QA threshold must be ≤ 10.0' },
                }}
                render={({ field }) => (
                  <div>
                    <ThresholdSlider
                      id="qa_passing_threshold"
                      label="QA Passing Threshold"
                      value={field.value}
                      onChange={field.onChange}
                      min={5.0}
                      max={10.0}
                      step={0.5}
                      hint="Minimum composite QA score required to pass (5.0–10.0). Floor of 5.0 prevents trivially weak quality gates."
                    />
                    <FieldError message={errors.qa_passing_threshold?.message} />
                  </div>
                )}
              />

              <div>
                <FieldLabel htmlFor="max_qa_iterations" label="Max QA Iterations" required />
                <input
                  id="max_qa_iterations"
                  type="number"
                  min={1}
                  {...register('max_qa_iterations', {
                    required: 'Required',
                    min: { value: 1, message: 'Must be at least 1 iteration' },
                    valueAsNumber: true,
                  })}
                  className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                />
                <p className="text-xs text-gray-500 mt-1">
                  Default: 3. Each iteration uses 2 LLM calls (evaluate + improve).
                </p>
                <FieldError message={errors.max_qa_iterations?.message} />
              </div>

              <Controller
                name="qa_llm_model"
                control={control}
                rules={{
                  required: 'Required',
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
            </CardContent>
          </Card>

          {/* ── Section: Governance ── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Governance Gate</CardTitle>
            </CardHeader>
            <CardContent className="pt-0">
              <SectionHeader
                title="Governance Threshold"
                description="Minimum composite score to pass the governance gate. Must be ≥ QA Passing Threshold."
              />
              <Controller
                name="governance_score_threshold"
                control={control}
                rules={{
                  required: 'Required',
                  min: { value: 0, message: 'Must be ≥ 0' },
                  max: { value: 10, message: 'Must be ≤ 10' },
                  validate: (v) =>
                    v >= watchedQaThreshold ||
                    `Governance (${v.toFixed(1)}) must be ≥ QA threshold (${watchedQaThreshold?.toFixed(1)})`,
                }}
                render={({ field }) => (
                  <div>
                    <ThresholdSlider
                      id="governance_score_threshold"
                      label="Governance Score Threshold"
                      value={field.value}
                      onChange={field.onChange}
                      min={0}
                      max={10}
                      step={0.5}
                      hint="Documents scoring below this are sent to HUMAN_REVIEW or BLOCKED. Cannot be lower than QA Passing Threshold."
                    />
                    <FieldError message={errors.governance_score_threshold?.message} />
                  </div>
                )}
              />
            </CardContent>
          </Card>

          {/* ── Section: Notifications ── */}
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">Notifications</CardTitle>
            </CardHeader>
            <CardContent className="pt-0 space-y-4">
              <SectionHeader
                title="Webhook Notifications"
                description="Receive POST notifications when documents are approved or rejected. Leave empty to disable."
              />
              <div>
                <FieldLabel htmlFor="notification_webhook_url" label="Webhook URL" />
                <div className="flex items-start gap-2">
                  <div className="flex-1">
                    <input
                      id="notification_webhook_url"
                      type="url"
                      placeholder="https://hooks.example.com/notify"
                      {...register('notification_webhook_url', {
                        validate: (v) => {
                          if (!v) return true; // empty is OK (disabled)
                          try {
                            const parsed = new URL(v);
                            return (
                              ['http:', 'https:'].includes(parsed.protocol) ||
                              'Must be an http:// or https:// URL'
                            );
                          } catch {
                            return 'Must be a valid URL or empty';
                          }
                        },
                      })}
                      className="w-full px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                    />
                    <FieldError message={errors.notification_webhook_url?.message} />
                  </div>
                  <button
                    type="button"
                    onClick={handleTestWebhook}
                    disabled={!watchedWebhook || testMutation.isPending}
                    className="shrink-0 flex items-center gap-2 px-3 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-50 disabled:cursor-not-allowed"
                  >
                    {testMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Webhook className="h-4 w-4" />
                    )}
                    Test
                  </button>
                </div>
                <WebhookTestStatus result={webhookTestResult} />
              </div>
            </CardContent>
          </Card>

          {/* ── Admin Attribution + Save ── */}
          <Card>
            <CardContent className="pt-6">
              <div className="flex flex-col sm:flex-row items-start sm:items-end gap-4">
                <div className="flex-1">
                  <FieldLabel htmlFor="updated_by" label="Your Name (for audit trail)" required />
                  <input
                    id="updated_by"
                    type="text"
                    placeholder="e.g. Jane Smith"
                    {...register('updated_by', {
                      required: 'Your name is required for the audit trail',
                      minLength: { value: 1, message: 'Cannot be empty' },
                    })}
                    className="w-full max-w-xs px-3 py-2 text-sm border border-gray-300 rounded-md focus:outline-none focus:ring-2 focus:ring-primary focus:border-transparent"
                  />
                  <FieldError message={errors.updated_by?.message} />
                </div>

                <div className="flex gap-2 shrink-0">
                  <button
                    type="button"
                    onClick={() => settings && reset({
                      registry_staleness_hours: settings.registry_staleness_hours,
                      llm_model_name: settings.llm_model_name,
                      max_draft_length: settings.max_draft_length,
                      qa_passing_threshold: settings.qa_passing_threshold,
                      max_qa_iterations: settings.max_qa_iterations,
                      qa_llm_model: settings.qa_llm_model,
                      governance_score_threshold: settings.governance_score_threshold,
                      llm_timeout_seconds: settings.llm_timeout_seconds ?? 120,
                      notification_webhook_url: settings.notification_webhook_url ?? '',
                      updated_by: '',
                    })}
                    disabled={!isDirty}
                    className="flex items-center gap-2 px-4 py-2 text-sm font-medium text-gray-700 bg-white border border-gray-300 rounded-md hover:bg-gray-50 disabled:opacity-40"
                  >
                    <RefreshCw className="h-4 w-4" />
                    Reset
                  </button>
                  <button
                    type="submit"
                    disabled={!isDirty || govBelowQa || updateMutation.isPending}
                    className="flex items-center gap-2 px-5 py-2 text-sm font-medium text-white bg-primary rounded-md hover:bg-primary/90 disabled:opacity-40 disabled:cursor-not-allowed"
                  >
                    {updateMutation.isPending ? (
                      <Loader2 className="h-4 w-4 animate-spin" />
                    ) : (
                      <Save className="h-4 w-4" />
                    )}
                    Save Settings
                  </button>
                </div>
              </div>

              {!isDirty && (
                <div className="flex items-center gap-1.5 mt-3 text-xs text-gray-400">
                  <CheckCircle className="h-3 w-3 text-green-500" />
                  All settings are saved and up to date.
                </div>
              )}

              {isDirty && (
                <Badge variant="outline" className="mt-3 text-xs text-amber-600 border-amber-300 bg-amber-50">
                  Unsaved changes
                </Badge>
              )}
            </CardContent>
          </Card>
        </div>
      </form>
    </>
  );
}
