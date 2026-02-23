import type { DocumentStatus } from '@/types/document';

export const queryKeys = {
  documents: {
    all: ['documents'] as const,
    list: (skip: number, limit: number) =>
      ['documents', 'list', skip, limit] as const,
    listByStatus: (status: DocumentStatus, skip: number, limit: number) =>
      ['documents', 'list', status, skip, limit] as const,
    detail: (id: string) => ['documents', id] as const,
    countByStatus: (status: DocumentStatus) =>
      ['documents', 'count', status] as const,
    status: (id: string) => ['documents', id, 'status'] as const,
  },
  pendingReview: {
    all: ['pending-review'] as const,
    list: (page: number, pageSize: number) =>
      ['pending-review', 'list', page, pageSize] as const,
  },
  factSheet: {
    detail: (id: string) => ['documents', id, 'factsheet'] as const,
  },
  auditLogs: {
    list: (id: string) => ['documents', id, 'audit-logs'] as const,
  },
  validation: {
    detail: (id: string) => ['documents', id, 'validation'] as const,
  },
  reviewDetails: {
    detail: (id: string) => ['review-details', id] as const,
  },
  claims: {
    all: ['claims'] as const,
    list: () => ['claims', 'list'] as const,
  },
  adminDocuments: {
    all: ['admin-documents'] as const,
  },
  settings: {
    all: ['admin', 'settings'] as const,
    detail: () => ['admin', 'settings'] as const,
  },
};
