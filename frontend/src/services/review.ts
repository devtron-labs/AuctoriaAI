import { apiRequest } from './api';
import type {
  PendingReviewResponse,
  ApproveDocumentRequest,
  RejectDocumentRequest,
} from '@/types/document';
import type { ReviewDetails } from '@/types/review';

export function getPendingReviews(page: number, pageSize: number): Promise<PendingReviewResponse> {
  return apiRequest<PendingReviewResponse>({
    method: 'GET',
    url: '/documents/pending-review',
    params: { page, page_size: pageSize },
  });
}

export function getReviewDetails(id: string): Promise<ReviewDetails> {
  return apiRequest<ReviewDetails>({
    method: 'GET',
    url: `/documents/${id}/review-details`,
  });
}

export function approveDocument(id: string, data: ApproveDocumentRequest): Promise<void> {
  return apiRequest<void>({
    method: 'POST',
    url: `/documents/${id}/approve`,
    data,
  });
}

export function rejectDocument(id: string, data: RejectDocumentRequest): Promise<void> {
  return apiRequest<void>({
    method: 'POST',
    url: `/documents/${id}/reject`,
    data,
  });
}
