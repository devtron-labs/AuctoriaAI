import type { Document, AuditLog } from '@/types/document';
import type {
  SystemStats,
  StatusDistribution,
  FormattedActivity,
  ApprovalTrendPoint,
  BlockedDocumentInfo,
} from '@/types/admin';

export function computeSystemStats(documents: Document[]): SystemStats {
  const total = documents.length;
  const approved = documents.filter((d) => d.status === 'APPROVED').length;
  const blocked = documents.filter((d) => d.status === 'BLOCKED').length;
  const pendingReviews = documents.filter((d) => d.status === 'HUMAN_REVIEW').length;

  const approvalRate =
    approved + blocked > 0
      ? Math.round((approved / (approved + blocked)) * 100)
      : 0;

  const approvedDocs = documents.filter((d) => d.status === 'APPROVED');
  const avgDaysRaw =
    approvedDocs.length > 0
      ? approvedDocs.reduce((sum, doc) => {
          const created = new Date(doc.created_at).getTime();
          const updated = new Date(doc.updated_at).getTime();
          return sum + Math.max(0, (updated - created) / (1000 * 60 * 60 * 24));
        }, 0) / approvedDocs.length
      : 0;

  return {
    total_documents: total,
    pending_reviews: pendingReviews,
    approved,
    blocked,
    approval_rate: approvalRate,
    avg_days_to_approval: Math.round(avgDaysRaw * 10) / 10,
  };
}

export function getStatusDistribution(documents: Document[]): StatusDistribution[] {
  const statuses = [
    'DRAFT',
    'VALIDATING',
    'PASSED',
    'HUMAN_REVIEW',
    'APPROVED',
    'BLOCKED',
  ] as const;
  return statuses.map((status) => ({
    status,
    count: documents.filter((d) => d.status === status).length,
  }));
}

export function formatRecentActivity(
  entries: Array<{ log: AuditLog; documentTitle: string }>,
): FormattedActivity[] {
  return entries
    .map(({ log, documentTitle }) => ({
      id: log.id,
      action: log.action,
      documentId: log.document_id,
      documentTitle,
      timestamp: log.timestamp,
    }))
    .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    .slice(0, 10);
}

export function computeApprovalTrend(documents: Document[]): ApprovalTrendPoint[] {
  const now = Date.now();
  const thirtyDaysAgo = now - 30 * 24 * 60 * 60 * 1000;

  const approvedDocs = documents.filter(
    (d) => d.status === 'APPROVED' && new Date(d.created_at).getTime() >= thirtyDaysAgo,
  );

  const byDay = new Map<string, { totalDays: number; count: number }>();
  for (const doc of approvedDocs) {
    const created = new Date(doc.created_at).getTime();
    const updated = new Date(doc.updated_at).getTime();
    const diffDays = Math.max(0, (updated - created) / (1000 * 60 * 60 * 24));
    const key = new Date(doc.created_at).toISOString().slice(0, 10);
    const existing = byDay.get(key) ?? { totalDays: 0, count: 0 };
    byDay.set(key, { totalDays: existing.totalDays + diffDays, count: existing.count + 1 });
  }

  const result: ApprovalTrendPoint[] = [];
  for (let i = 29; i >= 0; i--) {
    const d = new Date(now - i * 24 * 60 * 60 * 1000);
    const key = d.toISOString().slice(0, 10);
    const entry = byDay.get(key);
    result.push({
      date: key.slice(5), // MM-DD
      avgDays: entry ? Math.round((entry.totalDays / entry.count) * 10) / 10 : 0,
      count: entry?.count ?? 0,
    });
  }

  return result;
}

export function getBlockedDocumentInfo(
  documents: Document[],
  auditLogsByDocId: Map<string, AuditLog[]>,
): BlockedDocumentInfo[] {
  const now = Date.now();
  return documents
    .filter((d) => d.status === 'BLOCKED')
    .map((doc) => {
      const logs = auditLogsByDocId.get(doc.id) ?? [];
      const blockLog = [...logs]
        .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
        .find(
          (l) =>
            l.action.toLowerCase().includes('block') ||
            l.action.toLowerCase().includes('reject') ||
            l.action.toLowerCase().includes('governance'),
        );
      const daysBlocked = Math.round(
        (now - new Date(doc.updated_at).getTime()) / (1000 * 60 * 60 * 24),
      );
      return {
        id: doc.id,
        title: doc.title,
        daysBlocked,
        blockReason: blockLog?.action ?? null,
      };
    });
}
