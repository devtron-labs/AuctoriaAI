import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient, useQueries } from '@tanstack/react-query';
import { apiRequest } from '@/services/api';
import {
  uploadFile,
  extractFactSheet,
  getAuditLogs,
  generateDraftFromPrompt,
  getDocumentStatus,
  validateClaims,
  runQAIteration,
  runGovernanceCheck,
  downloadDraftPdf,
  downloadDraftDocx,
} from '@/services/documents';
import { getReviewDetails } from '@/services/review';
import { getClaims, createClaim, updateClaim, deleteClaim } from '@/services/claims';
import { getAvailableModels, getSettings, updateSettings, testWebhook } from '@/services/settings';
import { queryKeys } from '@/lib/queryKeys';
import type {
  Document,
  DocumentStatusResponse,
  CreateDocumentRequest,
  ApproveDocumentRequest,
  RejectDocumentRequest,
  DerivedAdminStats,
  DocumentStatus,
  DocumentType,
  PendingReviewResponse,
  FactSheet,
  AuditLog,
  ValidationReport,
  QAIterationResult,
  GovernanceCheckResult,
} from '@/types/document';
import type { ReviewDetails } from '@/types/review';
import type {
  Claim,
  CreateClaimRequest,
  KnownLlmModel,
  UpdateClaimRequest,
  SystemSettings,
  SystemSettingsUpdate,
  WebhookTestResult,
} from '@/types/admin';

// All six backend statuses — must stay in sync with DocumentStatus type
const DOCUMENT_STATUS_LIST = [
  'DRAFT',
  'VALIDATING',
  'PASSED',
  'HUMAN_REVIEW',
  'APPROVED',
  'BLOCKED',
] as const satisfies readonly DocumentStatus[];

// Document hooks

export function useDocuments(page = 1, limit = 20) {
  const skip = (page - 1) * limit;
  const query = useQuery({
    queryKey: queryKeys.documents.list(skip, limit),
    queryFn: () =>
      apiRequest<Document[]>({
        method: 'GET',
        url: '/documents',
        params: { skip, limit },
      }),
  });
  return {
    ...query,
    // True when the returned page is full — may be a false positive on the exact
    // last page. Accurate total requires backend pagination envelope.
    hasNextPage: (query.data?.length ?? 0) >= limit,
  };
}

export function useDocument(id: string) {
  return useQuery({
    queryKey: queryKeys.documents.detail(id),
    queryFn: () =>
      apiRequest<Document>({
        method: 'GET',
        url: `/documents/${id}`,
      }),
    enabled: !!id,
  });
}

export function useCreateDocument() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateDocumentRequest) =>
      apiRequest<Document>({
        method: 'POST',
        url: '/documents',
        data,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    },
  });
}

// Review detail hook — backed by GET /documents/:id/review-details

export function useReviewDetails(id: string) {
  return useQuery<ReviewDetails>({
    queryKey: queryKeys.reviewDetails.detail(id),
    queryFn: () => getReviewDetails(id),
    enabled: !!id,
  });
}

// Review hooks — backed by GET /documents/pending-review

export function useReviewQueue(page = 1, limit = 20) {
  const query = useQuery({
    queryKey: queryKeys.pendingReview.list(page, limit),
    queryFn: () =>
      apiRequest<PendingReviewResponse>({
        method: 'GET',
        url: '/documents/pending-review',
        params: { page, page_size: limit },
      }),
  });
  return {
    ...query,
    // Backend returns total so pagination is accurate
    hasNextPage: query.data ? page * limit < query.data.total : false,
  };
}

export function useApproveDocument(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: ApproveDocumentRequest) =>
      apiRequest<Document>({
        method: 'POST',
        url: `/documents/${id}/approve`,
        data: payload,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.pendingReview.all });
    },
  });
}

export function useRejectDocument(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (payload: RejectDocumentRequest) =>
      apiRequest<Document>({
        method: 'POST',
        url: `/documents/${id}/reject`,
        data: payload,
      }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
      void queryClient.invalidateQueries({ queryKey: queryKeys.pendingReview.all });
    },
  });
}

// Upload hook — tracks per-request progress via onUploadProgress callback

export function useUploadFile(id: string) {
  const queryClient = useQueryClient();
  const [progress, setProgress] = useState(0);

  const mutation = useMutation({
    mutationFn: ({
      file,
      classification,
    }: {
      file: File;
      classification: string;
    }) => uploadFile(id, file, classification, (p) => setProgress(p)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.all });
    },
    onSettled: () => {
      setTimeout(() => setProgress(0), 1500);
    },
  });

  return { ...mutation, progress };
}

// Fact-sheet extraction hook

export function useExtractFactSheet(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => extractFactSheet(id),
    onSuccess: (data: FactSheet) => {
      queryClient.setQueryData(queryKeys.factSheet.detail(id), data);
    },
  });
}

// Audit logs hook

export function useAuditLogs(id: string) {
  return useQuery<AuditLog[]>({
    queryKey: queryKeys.auditLogs.list(id),
    queryFn: () => getAuditLogs(id),
    enabled: !!id,
  });
}

// Status polling hook — calls GET /documents/{id}/status every 2 s.
// Only active when enabled=true (i.e., generation is in flight).

export function useDocumentStatus(id: string, enabled: boolean) {
  return useQuery<DocumentStatusResponse>({
    queryKey: queryKeys.documents.status(id),
    queryFn: () => getDocumentStatus(id),
    enabled: enabled && !!id,
    refetchInterval: enabled ? 2000 : false,
  });
}

// Draft generation hook — prompt-first architecture.
// POST /api/v1/drafts/generate returns 202 immediately; this hook polls
// GET /documents/{id}/status until DRAFT_GENERATED or DRAFT_FAILED.

export function useGenerateDraft(id: string) {
  const queryClient = useQueryClient();
  const [isPolling, setIsPolling] = useState(false);
  const [pollError, setPollError] = useState<Error | null>(null);
  const [isDone, setIsDone] = useState(false);

  const statusQuery = useDocumentStatus(id, isPolling);

  useEffect(() => {
    if (!isPolling || !statusQuery.data) return;
    const { current_stage } = statusQuery.data;
    if (current_stage === 'DRAFT_GENERATED') {
      setIsPolling(false);
      setIsDone(true);
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
    } else if (current_stage === 'DRAFT_FAILED') {
      setIsPolling(false);
      const msg = statusQuery.data.error_message || 'Draft generation failed after all attempts. Please try again.';
      setPollError(new Error(msg));
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
    }
  }, [isPolling, statusQuery.data, id, queryClient]);

  const mutation = useMutation({
    mutationFn: ({ prompt, document_type }: { prompt: string; document_type?: DocumentType }) =>
      generateDraftFromPrompt({ prompt, document_id: id || undefined, document_type }),
    onSuccess: () => {
      setIsPolling(true);
      setIsDone(false);
      setPollError(null);
    },
  });

  const reset = () => {
    mutation.reset();
    setIsPolling(false);
    setPollError(null);
    setIsDone(false);
  };

  return {
    mutate: mutation.mutate,
    isPending: mutation.isPending || isPolling,
    isSuccess: isDone,
    error: mutation.error ?? pollError,
    reset,
    progress: statusQuery.data?.validation_progress ?? 0,
    currentStage: statusQuery.data?.current_stage ?? null,
  };
}

// Claim validation hook

export function useValidateClaims(id: string) {
  const queryClient = useQueryClient();
  return useMutation<ValidationReport, Error, void>({
    mutationFn: () => validateClaims(id),
    onSuccess: (data) => {
      queryClient.setQueryData(queryKeys.validation.detail(id), data);
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
    },
  });
}

// QA iteration hook

export function useQAIteration(id: string) {
  const queryClient = useQueryClient();
  return useMutation<QAIterationResult, Error, number | undefined>({
    mutationFn: (maxIterations?: number) => runQAIteration(id, maxIterations),
    onSettled: () => {
      // Invalidate on both success AND error: when QA is BLOCKED the backend
      // returns HTTP 422, so onSuccess never fires, but the document status and
      // new draft versions are already committed to the DB. We must refetch so
      // the UI reflects the real state (BLOCKED status + new draft iterations).
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
    },
  });
}

// Draft download hooks — call the streaming PDF/DOCX endpoints and trigger
// a browser file-save. No query-cache interaction needed (pure side-effect).

export function useDownloadDraft() {
  const pdf = useMutation<void, Error, string>({
    mutationFn: (draftId: string) => downloadDraftPdf(draftId),
  });
  const docx = useMutation<void, Error, string>({
    mutationFn: (draftId: string) => downloadDraftDocx(draftId),
  });
  return { pdf, docx };
}

// Governance check hook

export function useGovernanceCheck(id: string) {
  const queryClient = useQueryClient();
  return useMutation<GovernanceCheckResult, Error, void>({
    mutationFn: () => runGovernanceCheck(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.documents.detail(id) });
    },
  });
}

// Admin stats — derived from GET /documents?status=<each status>
// Requires backend status filter support on GET /documents.

export function useAdminStats(): {
  data: DerivedAdminStats | undefined;
  isLoading: boolean;
  error: Error | null;
} {
  const results = useQueries({
    queries: DOCUMENT_STATUS_LIST.map((status) => ({
      queryKey: queryKeys.documents.countByStatus(status),
      queryFn: (): Promise<Document[]> =>
        apiRequest<Document[]>({
          method: 'GET',
          url: '/documents',
          params: { status, skip: 0, limit: 1000 },
        }),
    })),
  });

  const isLoading = results.some((r) => r.isLoading);
  const error = results.find((r) => r.error !== null)?.error ?? null;

  const data: DerivedAdminStats | undefined =
    isLoading || error !== null
      ? undefined
      : {
          draft: results[0].data?.length ?? 0,
          validating: results[1].data?.length ?? 0,
          passed: results[2].data?.length ?? 0,
          humanReview: results[3].data?.length ?? 0,
          approved: results[4].data?.length ?? 0,
          blocked: results[5].data?.length ?? 0,
          totalDocuments: results.reduce(
            (sum, r) => sum + (r.data?.length ?? 0),
            0,
          ),
        };

  return { data, isLoading, error };
}

// Fetch all documents (high limit) for admin analytics — uses a dedicated cache key
// to avoid interfering with the paginated document list.

export function useAllDocumentsForAdmin() {
  return useQuery<Document[]>({
    queryKey: queryKeys.adminDocuments.all,
    queryFn: () =>
      apiRequest<Document[]>({
        method: 'GET',
        url: '/documents',
        params: { skip: 0, limit: 1000 },
      }),
    staleTime: 60_000,
  });
}

// Fetch audit logs for multiple document IDs in parallel.

export function useMultipleAuditLogs(documentIds: string[]) {
  return useQueries({
    queries: documentIds.map((id) => ({
      queryKey: queryKeys.auditLogs.list(id),
      queryFn: () => getAuditLogs(id),
      enabled: !!id,
    })),
  });
}

// Claims CRUD hooks

export function useClaims() {
  return useQuery<Claim[]>({
    queryKey: queryKeys.claims.list(),
    queryFn: getClaims,
  });
}

export function useCreateClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (data: CreateClaimRequest) => createClaim(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.all });
    },
  });
}

export function useUpdateClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: ({ id, data }: { id: string; data: UpdateClaimRequest }) =>
      updateClaim(id, data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.all });
    },
  });
}

export function useDeleteClaim() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => deleteClaim(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.claims.all });
    },
  });
}

// System Settings hooks

export function useAvailableModels() {
  return useQuery<KnownLlmModel[]>({
    queryKey: ['admin', 'available-models'],
    queryFn: getAvailableModels,
    staleTime: Infinity, // model list rarely changes
  });
}

export function useSystemSettings() {
  return useQuery<SystemSettings>({
    queryKey: queryKeys.settings.detail(),
    queryFn: getSettings,
    staleTime: 30_000, // 30 s — backend cache is 60 s, keep client slightly fresher
  });
}

export function useUpdateSystemSettings() {
  const queryClient = useQueryClient();
  return useMutation<SystemSettings, Error, SystemSettingsUpdate>({
    mutationFn: (data: SystemSettingsUpdate) => updateSettings(data),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.settings.all });
    },
  });
}

export function useTestWebhook() {
  return useMutation<WebhookTestResult, Error, void>({
    mutationFn: () => testWebhook(),
  });
}
