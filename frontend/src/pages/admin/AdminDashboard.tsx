import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  FileText,
  Clock,
  CheckCircle,
  AlertTriangle,
  Activity,
  TrendingUp,
  XCircle,
  ExternalLink,
  Settings,
} from 'lucide-react';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Cell,
  LineChart,
  Line,
  ResponsiveContainer,
  Legend,
} from 'recharts';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { MetricCard } from '@/components/admin/MetricCard';
import ClaimRegistry from '@/pages/admin/ClaimRegistry';
import SystemSettingsPage from '@/pages/admin/SystemSettings';
import {
  useAllDocumentsForAdmin,
  useMultipleAuditLogs,
} from '@/hooks';
import {
  computeSystemStats,
  getStatusDistribution,
  formatRecentActivity,
  computeApprovalTrend,
  getBlockedDocumentInfo,
} from '@/services/admin';
import { formatDateTime } from '@/lib/utils';
import type { DocumentStatus } from '@/types/document';

// ─── Chart color palette ────────────────────────────────────────────────────

const STATUS_COLORS: Record<DocumentStatus, string> = {
  DRAFT: '#6b7280',
  VALIDATING: '#f59e0b',
  PASSED: '#3b82f6',
  HUMAN_REVIEW: '#f97316',
  APPROVED: '#22c55e',
  BLOCKED: '#ef4444',
};

const STATUS_LABELS: Record<DocumentStatus, string> = {
  DRAFT: 'Draft',
  VALIDATING: 'Validating',
  PASSED: 'Passed QA',
  HUMAN_REVIEW: 'In Review',
  APPROVED: 'Approved',
  BLOCKED: 'Blocked',
};

// ─── Shared loading / error states ──────────────────────────────────────────

function LoadingSpinner() {
  return (
    <div className="flex items-center justify-center py-16">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
    </div>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <Card className="border-red-200 bg-red-50">
      <CardContent className="pt-6">
        <p className="text-red-600 text-sm">{message}</p>
      </CardContent>
    </Card>
  );
}

// ─── Overview Tab ────────────────────────────────────────────────────────────

function OverviewTab() {
  const { data: allDocs, isLoading, error } = useAllDocumentsForAdmin();

  // Top-5 recently updated doc IDs for activity feed
  const recentDocIds = useMemo(() => {
    if (!allDocs) return [];
    return [...allDocs]
      .sort((a, b) => new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime())
      .slice(0, 5)
      .map((d) => d.id);
  }, [allDocs]);

  const auditResults = useMultipleAuditLogs(recentDocIds);

  const titleMap = useMemo(() => {
    const m = new Map<string, string>();
    allDocs?.forEach((d) => m.set(d.id, d.title));
    return m;
  }, [allDocs]);

  const recentActivity = useMemo(() => {
    if (!allDocs || auditResults.some((r) => r.isLoading)) return [];
    const entries = auditResults.flatMap((result, i) => {
      const docId = recentDocIds[i];
      const documentTitle = titleMap.get(docId) ?? 'Unknown Document';
      return (result.data ?? []).map((log) => ({ log, documentTitle }));
    });
    return formatRecentActivity(entries);
  }, [allDocs, auditResults, recentDocIds, titleMap]);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorCard message="Failed to load statistics. Please ensure the backend is running." />;
  if (!allDocs || allDocs.length === 0) {
    return (
      <Card>
        <CardContent className="pt-6 text-center text-gray-500 text-sm">
          No documents yet. Start by creating documents.
        </CardContent>
      </Card>
    );
  }

  const stats = computeSystemStats(allDocs);
  const distribution = getStatusDistribution(allDocs);

  const pendingVariant =
    stats.pending_reviews > 10 ? 'danger' : stats.pending_reviews > 5 ? 'warning' : 'default';
  const approvalVariant =
    stats.approval_rate >= 80 ? 'success' : stats.approval_rate >= 60 ? 'warning' : 'danger';

  const chartData = distribution.map((d) => ({
    name: STATUS_LABELS[d.status],
    value: d.count,
    color: STATUS_COLORS[d.status],
  }));

  return (
    <div className="space-y-6">
      {/* Metric cards */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <MetricCard
          icon={FileText}
          label="Total Documents"
          value={stats.total_documents}
          description="All documents in system"
          colorVariant="default"
        />
        <MetricCard
          icon={Clock}
          label="Pending Reviews"
          value={stats.pending_reviews}
          description="Awaiting human review"
          colorVariant={pendingVariant}
        />
        <MetricCard
          icon={CheckCircle}
          label="Approval Rate"
          value={`${stats.approval_rate}%`}
          description={`${stats.approved} of ${stats.approved + stats.blocked} reviewed`}
          colorVariant={approvalVariant}
        />
        <MetricCard
          icon={TrendingUp}
          label="Avg Days to Approval"
          value={stats.avg_days_to_approval}
          description="From creation to approval"
          colorVariant="default"
        />
      </div>

      <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
        {/* Status distribution chart */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Status Distribution</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={chartData} layout="vertical" margin={{ left: 4, right: 24 }}>
                  <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                  <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                  <YAxis type="category" dataKey="name" width={88} tick={{ fontSize: 12 }} />
                  <Tooltip
                    formatter={(value: any) => [value, 'Documents']}
                    cursor={{ fill: 'rgba(0,0,0,0.04)' }}
                  />
                  <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                    {chartData.map((entry, idx) => (
                      <Cell key={idx} fill={entry.color} />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          </CardContent>
        </Card>

        {/* Recent activity feed */}
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Activity className="h-4 w-4 text-gray-500" />
              Recent Activity
            </CardTitle>
          </CardHeader>
          <CardContent>
            {auditResults.some((r) => r.isLoading) ? (
              <div className="flex justify-center py-6">
                <div className="animate-spin rounded-full h-5 w-5 border-b-2 border-primary" />
              </div>
            ) : recentActivity.length === 0 ? (
              <p className="text-sm text-gray-400 text-center py-6">No activity yet.</p>
            ) : (
              <ul className="space-y-3 divide-y divide-gray-100">
                {recentActivity.map((item) => (
                  <li key={item.id} className="pt-3 first:pt-0">
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <p className="text-sm text-gray-800 font-medium truncate">
                          {item.action}
                        </p>
                        <Link
                          to={`/documents/${item.documentId}`}
                          className="text-xs text-primary hover:underline flex items-center gap-1 mt-0.5"
                        >
                          {item.documentTitle}
                          <ExternalLink className="h-3 w-3" />
                        </Link>
                      </div>
                      <time className="text-xs text-gray-400 shrink-0">
                        {formatDateTime(item.timestamp)}
                      </time>
                    </div>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

// ─── Analytics Tab ───────────────────────────────────────────────────────────

function AnalyticsTab() {
  const { data: allDocs, isLoading, error } = useAllDocumentsForAdmin();

  const blockedDocIds = useMemo(
    () => allDocs?.filter((d) => d.status === 'BLOCKED').map((d) => d.id) ?? [],
    [allDocs],
  );

  const blockedAuditResults = useMultipleAuditLogs(blockedDocIds);

  const trendData = useMemo(
    () => (allDocs ? computeApprovalTrend(allDocs) : []),
    [allDocs],
  );

  const distributionData = useMemo(() => {
    if (!allDocs) return [];
    return getStatusDistribution(allDocs).map((d) => ({
      name: STATUS_LABELS[d.status],
      value: d.count,
      color: STATUS_COLORS[d.status],
    }));
  }, [allDocs]);

  const blockedInfo = useMemo(() => {
    if (!allDocs) return [];
    const auditLogsByDocId = new Map(
      blockedAuditResults.map((r, i) => [blockedDocIds[i], r.data ?? []]),
    );
    return getBlockedDocumentInfo(allDocs, auditLogsByDocId);
  }, [allDocs, blockedAuditResults, blockedDocIds]);

  if (isLoading) return <LoadingSpinner />;
  if (error) return <ErrorCard message="Failed to load analytics data." />;

  const hasApprovalData = trendData.some((p) => p.avgDays > 0);

  return (
    <div className="space-y-6">
      {/* Time-to-approval trend */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Time-to-Approval Trend (Last 30 Days)</CardTitle>
        </CardHeader>
        <CardContent>
          {!hasApprovalData ? (
            <p className="text-sm text-gray-400 text-center py-8">
              No approved documents in the last 30 days.
            </p>
          ) : (
            <div className="h-[250px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={trendData} margin={{ right: 16 }}>
                  <CartesianGrid strokeDasharray="3 3" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10 }}
                    interval={6}
                    tickLine={false}
                  />
                  <YAxis
                    tick={{ fontSize: 11 }}
                    tickLine={false}
                    axisLine={false}
                    unit=" d"
                  />
                  <Tooltip
                    formatter={(value: any) => [`${value} days`, 'Avg Time to Approval']}
                  />
                  <Legend />
                  <Line
                    type="monotone"
                    dataKey="avgDays"
                    name="Avg Days"
                    stroke="#3b82f6"
                    strokeWidth={2}
                    dot={false}
                    activeDot={{ r: 4 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Current distribution */}
      <Card>
        <CardHeader>
          <CardTitle className="text-base">Current Status Distribution</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="h-[220px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={distributionData} layout="vertical" margin={{ left: 4, right: 24 }}>
                <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                <XAxis type="number" tick={{ fontSize: 11 }} allowDecimals={false} />
                <YAxis type="category" dataKey="name" width={88} tick={{ fontSize: 12 }} />
                <Tooltip
                  formatter={(value: any) => [value, 'Documents']}
                  cursor={{ fill: 'rgba(0,0,0,0.04)' }}
                />
                <Bar dataKey="value" radius={[0, 4, 4, 0]}>
                  {distributionData.map((entry, idx) => (
                    <Cell key={idx} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </div>
        </CardContent>
      </Card>

      {/* Blocked documents */}
      <Card className={blockedInfo.length > 0 ? 'border-red-200' : undefined}>
        <CardHeader>
          <CardTitle className="text-base flex items-center gap-2">
            <AlertTriangle
              className={`h-4 w-4 ${blockedInfo.length > 0 ? 'text-red-500' : 'text-gray-400'}`}
            />
            Blocked Documents
            {blockedInfo.length > 0 && (
              <Badge variant="destructive" className="ml-1">
                {blockedInfo.length}
              </Badge>
            )}
          </CardTitle>
        </CardHeader>
        <CardContent>
          {blockedInfo.length === 0 ? (
            <p className="text-sm text-gray-400 flex items-center gap-2">
              <CheckCircle className="h-4 w-4 text-green-500" />
              No blocked documents.
            </p>
          ) : (
            <ul className="space-y-3 divide-y divide-gray-100">
              {blockedInfo.map((doc) => (
                <li key={doc.id} className="pt-3 first:pt-0">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="flex items-center gap-2">
                        <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                        <p className="text-sm font-medium text-gray-900 truncate">{doc.title}</p>
                      </div>
                      {doc.blockReason && (
                        <p className="text-xs text-gray-500 mt-0.5 ml-6">{doc.blockReason}</p>
                      )}
                      <p className="text-xs text-gray-400 mt-0.5 ml-6">
                        Blocked for {doc.daysBlocked} day{doc.daysBlocked !== 1 ? 's' : ''}
                      </p>
                    </div>
                    <Link
                      to={`/review/${doc.id}`}
                      className="shrink-0 text-xs text-primary hover:underline flex items-center gap-1"
                    >
                      Review
                      <ExternalLink className="h-3 w-3" />
                    </Link>
                  </div>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </div>
  );
}

// ─── Admin Dashboard (root) ──────────────────────────────────────────────────

export default function AdminDashboard() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-gray-900">Admin Dashboard</h1>
        <p className="text-gray-500 text-sm mt-1">
          Overview of document governance activity
        </p>
      </div>

      <Tabs defaultValue="overview">
        <TabsList className="mb-4">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="analytics">Analytics</TabsTrigger>
          <TabsTrigger value="claims">Claim Registry</TabsTrigger>
          <TabsTrigger value="settings" className="flex items-center gap-1.5">
            <Settings className="h-3.5 w-3.5" />
            System Settings
          </TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <OverviewTab />
        </TabsContent>

        <TabsContent value="analytics">
          <AnalyticsTab />
        </TabsContent>

        <TabsContent value="claims">
          <ClaimRegistry />
        </TabsContent>

        <TabsContent value="settings">
          <SystemSettingsPage />
        </TabsContent>
      </Tabs>
    </div>
  );
}
