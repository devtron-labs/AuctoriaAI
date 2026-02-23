// Matches backend DocumentStatus enum exactly
export type DocumentStatus =
  | 'DRAFT'
  | 'VALIDATING'
  | 'PASSED'
  | 'HUMAN_REVIEW'
  | 'APPROVED'
  | 'BLOCKED';

// Matches backend DocumentRead schema
export interface Document {
  id: string;
  title: string;
  status: DocumentStatus;
  created_at: string;
  updated_at: string;
  file_path?: string | null;
  file_hash?: string | null;
  classification?: string | null;
  draft_versions?: DraftVersion[];
  has_fact_sheet?: boolean;
}

// Matches backend DocumentCreate schema — no content field
export interface CreateDocumentRequest {
  title: string;
}

// Matches backend PendingReviewItem schema
export interface PendingReviewItem {
  id: string;
  title: string;
  status: DocumentStatus;
  draft_preview: string | null;
  score: number | null;
  claims_valid: boolean | null;
  total_issues: number;
  days_in_review: number;
  created_at: string;
  updated_at: string;
}

// Matches backend PendingReviewResponse schema
export interface PendingReviewResponse {
  total: number;
  page: number;
  page_size: number;
  documents: PendingReviewItem[];
}

// Matches backend ApproveDocumentRequest schema
export interface ApproveDocumentRequest {
  reviewer_name: string;
  notes?: string;
  force_approve?: boolean;
  override_reason?: string;
}

// Matches backend RejectDocumentRequest schema
export interface RejectDocumentRequest {
  reviewer_name: string;
  rejection_reason: string;
  suggested_action?: string;
}

// Admin stats derived from per-status document counts
export interface DerivedAdminStats {
  totalDocuments: number;
  draft: number;
  validating: number;
  passed: number;
  humanReview: number;
  approved: number;
  blocked: number;
}

// Matches backend FactSheet schema
export interface FactSheet {
  id: string;
  document_id: string;
  structured_data: {
    features: Array<{ name: string; description: string }>;
    integrations: Array<{ system: string; method: string; notes: string }>;
    compliance: Array<{ standard: string; status: string; details: string }>;
    performance_metrics: Array<{ metric: string; value: string; unit: string }>;
    limitations: Array<{ category: string; description: string }>;
  };
  created_at: string;
}

// Matches backend AuditLog schema
export interface AuditLog {
  id: string;
  document_id: string;
  action: string;
  timestamp: string;
}

// Matches backend DraftVersionRead schema
export interface DraftVersion {
  id: string;
  document_id: string | null;       // null for standalone prompt-first drafts
  iteration_number: number;
  content_markdown: string;
  tone: string;
  score: number | null;
  feedback_text: string | null;
  user_prompt: string;               // the user's original generation prompt
  source_document_id: string | null; // optional context document reference
  created_at: string;
}

export type DocumentType =
  | 'whitepaper'
  | 'blog'
  | 'technical_doc'
  | 'case_study'
  | 'product_brief'
  | 'research_report';

// Request body for POST /api/v1/drafts/generate
export interface DraftGenerateRequest {
  prompt: string;
  document_id?: string;
  document_type?: DocumentType;
}

// Response from POST /api/v1/drafts/generate (202 Accepted — async)
export interface DraftGenerateResponse {
  status: 'generating';
  document_id: string | null;
  message: string;
}

// Response from GET /documents/{id}/status
export interface DocumentStatusResponse {
  status: DocumentStatus;
  current_stage: string | null;
  validation_progress: number;
}

// Matches backend ValidationReport schema
export interface ValidationReport {
  is_valid: boolean;
  total_claims: number;
  valid_claims: number;
  blocked_claims: number;
  warnings: number;
  results: Array<{
    claim: {
      claim_type: string;
      claim_text: string;
    };
    is_valid: boolean;
    error_message: string | null;
    is_expired: boolean;
  }>;
}

// Matches backend QAIterationResult schema
export interface QAIterationResult {
  document_id: string;
  final_status: DocumentStatus;
  iterations_completed: number;
  final_score: number;
  final_draft_id: string;
}

// Matches backend GovernanceCheckResult schema
export interface GovernanceCheckResult {
  document_id: string;
  decision: 'PASSED' | 'FAILED';
  final_status: DocumentStatus;
  score: number;
  claims_valid: boolean;
  reason: string;
  details: {
    score: number;
    score_threshold: number;
    score_passed: boolean;
    claims_valid: boolean;
    validation_summary?: string;
    blocked_claims?: number;
  };
}
