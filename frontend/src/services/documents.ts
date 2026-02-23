import api, { apiRequest } from './api';

// ─── Download helpers ──────────────────────────────────────────────────────────

/** Trigger a browser file-save from a Blob and a suggested filename. */
function _triggerDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}
import type {
  Document,
  DocumentStatusResponse,
  DraftGenerateRequest,
  DraftGenerateResponse,
  FactSheet,
  AuditLog,
  DraftVersion,
  ValidationReport,
  QAIterationResult,
  GovernanceCheckResult,
} from '@/types/document';

export function getDocuments(): Promise<Document[]> {
  return apiRequest<Document[]>({ method: 'GET', url: '/documents' });
}

export function createDocument(title: string): Promise<Document> {
  return apiRequest<Document>({
    method: 'POST',
    url: '/documents',
    data: { title },
  });
}

export function getDocument(id: string): Promise<Document> {
  return apiRequest<Document>({ method: 'GET', url: `/documents/${id}` });
}

export function uploadFile(
  id: string,
  file: File,
  classification: string,
  onProgress?: (percent: number) => void,
): Promise<Document> {
  const formData = new FormData();
  formData.append('file', file);
  formData.append('classification', classification);
  return api
    .post<Document>(`/documents/${id}/upload`, formData, {
      headers: { 'Content-Type': 'multipart/form-data' },
      onUploadProgress: (event) => {
        if (onProgress && event.total) {
          onProgress(Math.round((event.loaded / event.total) * 100));
        }
      },
    })
    .then((r) => r.data);
}

export function extractFactSheet(id: string): Promise<FactSheet> {
  return apiRequest<FactSheet>({
    method: 'POST',
    url: `/documents/${id}/extract-factsheet`,
  });
}

export function getAuditLogs(id: string): Promise<AuditLog[]> {
  return apiRequest<AuditLog[]>({
    method: 'GET',
    url: `/documents/${id}/audit-logs`,
  });
}

/**
 * Legacy document-centric draft generation (FactSheet required).
 * Kept for backward compatibility — prefer generateDraftFromPrompt for new work.
 */
export function generateDraft(id: string, tone: string): Promise<DraftVersion> {
  return apiRequest<DraftVersion>({
    method: 'POST',
    url: `/documents/${id}/generate-draft`,
    data: { tone },
  });
}

/**
 * Prompt-first draft generation — POST /api/v1/drafts/generate.
 *
 * Returns 202 Accepted immediately. Generation runs in the background.
 * Poll getDocumentStatus() until current_stage is "DRAFT_GENERATED" or
 * "DRAFT_FAILED". The background task respects llm_timeout_seconds (total
 * budget) and max_qa_iterations (max attempts) from Admin → System Settings.
 */
export function generateDraftFromPrompt(
  request: DraftGenerateRequest,
): Promise<DraftGenerateResponse> {
  return apiRequest<DraftGenerateResponse>({
    method: 'POST',
    url: '/drafts/generate',
    data: request,
  });
}

/**
 * Lightweight status poll — GET /documents/{id}/status.
 *
 * Returns current_stage and validation_progress for the progress bar.
 * Designed for polling every 2 s during background generation.
 */
export function getDocumentStatus(id: string): Promise<DocumentStatusResponse> {
  return apiRequest<DocumentStatusResponse>({
    method: 'GET',
    url: `/documents/${id}/status`,
  });
}

export async function validateClaims(id: string): Promise<ValidationReport> {
  const response = await apiRequest<{ document_id: string; status: string; validation_report: ValidationReport }>({
    method: 'POST',
    url: `/documents/${id}/validate-claims`,
    data: {}, // Backend requires ValidateClaimsRequest body (even though it has no fields)
  });
  return response.validation_report;
}

export function runQAIteration(id: string, maxIterations?: number): Promise<QAIterationResult> {
  return apiRequest<QAIterationResult>({
    method: 'POST',
    url: `/documents/${id}/qa-iterate`,
    data: maxIterations !== undefined ? { max_iterations: maxIterations } : {},
  });
}

export function runGovernanceCheck(id: string): Promise<GovernanceCheckResult> {
  return apiRequest<GovernanceCheckResult>({
    method: 'POST',
    url: `/documents/${id}/governance-check`,
  });
}

/**
 * Stream a DraftVersion as PDF from the backend and trigger a browser download.
 * Calls GET /api/v1/drafts/{draftId}/download/pdf
 */
export async function downloadDraftPdf(draftId: string): Promise<void> {
  const response = await api.get<Blob>(`/drafts/${draftId}/download/pdf`, {
    responseType: 'blob',
  });
  _triggerDownload(
    new Blob([response.data], { type: 'application/pdf' }),
    `draft-${draftId}.pdf`,
  );
}

/**
 * Stream a DraftVersion as DOCX from the backend and trigger a browser download.
 * Calls GET /api/v1/drafts/{draftId}/download/docx
 */
export async function downloadDraftDocx(draftId: string): Promise<void> {
  const response = await api.get<Blob>(`/drafts/${draftId}/download/docx`, {
    responseType: 'blob',
  });
  _triggerDownload(
    new Blob([response.data], {
      type: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    }),
    `draft-${draftId}.docx`,
  );
}
