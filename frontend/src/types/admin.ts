import type { DocumentStatus } from '@/types/document';

// ── System Settings ──────────────────────────────────────────────────────────

export interface KnownLlmModel {
  id: string;
  label: string;
  provider: string;  // 'anthropic' | 'openai' | 'google' | 'perplexity' | 'xai'
}

// Model fields use plain `string` to support custom model IDs entered by admins.
// The curated list of known models is fetched from GET /admin/settings/available-models.
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
  anthropic_api_key:  string | null;
  openai_api_key:     string | null;
  google_api_key:     string | null;
  perplexity_api_key: string | null;
  xai_api_key:        string | null;
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
  anthropic_api_key?:  string;
  openai_api_key?:     string;
  google_api_key?:     string;
  perplexity_api_key?: string;
  xai_api_key?:        string;
}

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

export interface WebhookTestResult {
  success: boolean;
  status_code?: number;
  error?: string;
  webhook_url?: string;
  response_body?: string;
}

// ── Document Stats ───────────────────────────────────────────────────────────

export interface SystemStats {
  total_documents: number;
  pending_reviews: number;
  approved: number;
  blocked: number;
  approval_rate: number;
  avg_days_to_approval: number;
}

export interface StatusDistribution {
  status: DocumentStatus;
  count: number;
}

export type ClaimType = 'INTEGRATION' | 'COMPLIANCE' | 'PERFORMANCE';

export interface Claim {
  id: string;
  claim_text: string;
  claim_type: ClaimType;
  expiry_date: string | null;
  approved_by: string | null;
  approved_at: string | null;
  created_at: string;
}

export interface CreateClaimRequest {
  claim_text: string;
  claim_type: ClaimType;
  expiry_date?: string | null;
  approved_by?: string | null;
}

export interface UpdateClaimRequest {
  claim_text?: string;
  claim_type?: ClaimType;
  expiry_date?: string | null;
  approved_by?: string | null;
}

export interface FormattedActivity {
  id: string;
  action: string;
  documentId: string;
  documentTitle: string;
  timestamp: string;
}

export interface ApprovalTrendPoint {
  date: string;
  avgDays: number;
  count: number;
}

export interface BlockedDocumentInfo {
  id: string;
  title: string;
  daysBlocked: number;
  blockReason: string | null;
}
