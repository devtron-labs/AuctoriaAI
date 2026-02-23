import { Link, useParams } from 'react-router-dom';
import { ArrowLeft, ChevronRight } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import DecisionPanel from '@/components/review/DecisionPanel';
import { useReviewDetails } from '@/hooks';
import { formatDateTime } from '@/lib/utils';
import type { ValidationReport, FactSheet, AuditLog, DraftVersion } from '@/types/document';

// ---------------------------------------------------------------------------
// Sub-components for each tab
// ---------------------------------------------------------------------------

function DraftTab({ draft }: { draft: DraftVersion | null }) {
  if (!draft) {
    return <p className="text-sm text-gray-500 py-4">No draft available yet.</p>;
  }
  return (
    <div className="space-y-4">
      {/* Score card */}
      <div className="flex flex-wrap items-center gap-3">
        {draft.score !== null && (
          <Badge variant={draft.score >= 9 ? 'success' : 'warning'}>
            Score: {draft.score.toFixed(1)} / 10
          </Badge>
        )}
        <Badge variant="secondary">Iteration #{draft.iteration_number}</Badge>
        <span className="text-xs text-gray-400">{formatDateTime(draft.created_at)}</span>
      </div>

      {/* Feedback */}
      {draft.feedback_text && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
          <p className="text-xs font-semibold text-amber-700 mb-1 uppercase tracking-wide">
            AI Feedback
          </p>
          <p className="text-sm text-amber-800 leading-relaxed">{draft.feedback_text}</p>
        </div>
      )}

      {/* Markdown content */}
      <div className="prose prose-sm max-w-none border rounded-lg p-4 bg-white">
        <ReactMarkdown>{draft.content_markdown}</ReactMarkdown>
      </div>
    </div>
  );
}

function ValidationTab({ report }: { report: ValidationReport | null }) {
  if (!report) {
    return <p className="text-sm text-gray-500 py-4">No validation report available.</p>;
  }

  return (
    <div className="space-y-4">
      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Total Claims', value: report.total_claims },
          { label: 'Valid', value: report.valid_claims, color: 'text-green-600' },
          { label: 'Blocked', value: report.blocked_claims, color: 'text-red-600' },
          { label: 'Warnings', value: report.warnings, color: 'text-amber-600' },
        ].map(({ label, value, color }) => (
          <div key={label} className="rounded-lg border bg-gray-50 p-3 text-center">
            <p className="text-xs text-gray-500 font-medium">{label}</p>
            <p className={`text-xl font-bold mt-0.5 ${color ?? 'text-gray-900'}`}>{value}</p>
          </div>
        ))}
      </div>

      <div className={`text-sm font-semibold ${report.is_valid ? 'text-green-600' : 'text-red-600'}`}>
        Overall: {report.is_valid ? '✓ Valid' : '✗ Invalid'}
      </div>

      {/* Claims list */}
      <div className="space-y-2">
        {report.results.map((result, idx) => (
          <details key={idx} className="rounded-lg border">
            <summary className="flex items-center justify-between p-3 cursor-pointer select-none hover:bg-gray-50">
              <div className="flex items-center gap-2 min-w-0">
                <span className={result.is_valid ? 'text-green-500' : 'text-red-500'}>
                  {result.is_valid ? '✓' : '✗'}
                </span>
                <Badge variant="outline" className="text-xs shrink-0">
                  {result.claim.claim_type}
                </Badge>
                <span className="text-sm text-gray-700 truncate">{result.claim.claim_text}</span>
              </div>
              {result.is_expired && (
                <Badge variant="warning" className="shrink-0 ml-2">
                  Expired
                </Badge>
              )}
            </summary>
            {result.error_message && (
              <div className="px-3 pb-3 text-sm text-red-600">{result.error_message}</div>
            )}
          </details>
        ))}
      </div>
    </div>
  );
}

function FactSheetTab({ factSheet }: { factSheet: FactSheet | null }) {
  if (!factSheet) {
    return <p className="text-sm text-gray-500 py-4">No fact sheet extracted yet.</p>;
  }

  const { structured_data } = factSheet;

  return (
    <div className="space-y-6">
      {structured_data.features.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Features</h3>
          <div className="space-y-2">
            {structured_data.features.map((f, i) => (
              <div key={i} className="rounded-lg border p-3">
                <p className="text-sm font-medium text-gray-900">{f.name}</p>
                <p className="text-sm text-gray-600 mt-0.5">{f.description}</p>
              </div>
            ))}
          </div>
        </section>
      )}

      {structured_data.integrations.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Integrations</h3>
          <div className="space-y-2">
            {structured_data.integrations.map((intg, i) => (
              <div key={i} className="rounded-lg border p-3">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-gray-900">{intg.system}</p>
                  <Badge variant="outline" className="text-xs">{intg.method}</Badge>
                </div>
                {intg.notes && <p className="text-sm text-gray-600 mt-0.5">{intg.notes}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {structured_data.compliance.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Compliance</h3>
          <div className="space-y-2">
            {structured_data.compliance.map((c, i) => (
              <div key={i} className="rounded-lg border p-3">
                <div className="flex items-center justify-between">
                  <p className="text-sm font-medium text-gray-900">{c.standard}</p>
                  <Badge
                    variant={c.status.toLowerCase() === 'compliant' ? 'success' : 'warning'}
                    className="text-xs"
                  >
                    {c.status}
                  </Badge>
                </div>
                {c.details && <p className="text-sm text-gray-600 mt-0.5">{c.details}</p>}
              </div>
            ))}
          </div>
        </section>
      )}

      {structured_data.performance_metrics.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Performance Metrics</h3>
          <div className="grid grid-cols-2 gap-2">
            {structured_data.performance_metrics.map((m, i) => (
              <div key={i} className="rounded-lg border p-3 bg-gray-50">
                <p className="text-xs text-gray-500 font-medium">{m.metric}</p>
                <p className="text-lg font-bold text-gray-900">
                  {m.value}
                  <span className="text-xs font-normal text-gray-500 ml-1">{m.unit}</span>
                </p>
              </div>
            ))}
          </div>
        </section>
      )}

      {structured_data.limitations.length > 0 && (
        <section>
          <h3 className="text-sm font-semibold text-gray-700 mb-2">Limitations</h3>
          <div className="space-y-2">
            {structured_data.limitations.map((l, i) => (
              <div key={i} className="rounded-lg border border-amber-200 bg-amber-50 p-3">
                <p className="text-xs font-semibold text-amber-700">{l.category}</p>
                <p className="text-sm text-amber-800 mt-0.5">{l.description}</p>
              </div>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}

function HistoryTab({ logs }: { logs: AuditLog[] }) {
  if (logs.length === 0) {
    return <p className="text-sm text-gray-500 py-4">No audit history available.</p>;
  }

  return (
    <div className="space-y-2">
      {logs.map((log) => (
        <div
          key={log.id}
          className="flex items-start gap-3 rounded-lg border p-3 text-sm"
        >
          <div className="h-2 w-2 rounded-full bg-primary mt-1.5 shrink-0" />
          <div className="min-w-0">
            <p className="font-medium text-gray-900">{log.action}</p>
            <p className="text-xs text-gray-400 mt-0.5">{formatDateTime(log.timestamp)}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main ReviewDetail page
// ---------------------------------------------------------------------------

export default function ReviewDetail() {
  const { id } = useParams<{ id: string }>();
  const docId = id ?? '';

  const { data: reviewDetails, isLoading, error } = useReviewDetails(docId);

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (error || !reviewDetails) {
    return (
      <div className="space-y-4">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/review">
            <ArrowLeft className="h-4 w-4" />
            Back to Review Queue
          </Link>
        </Button>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-600">Failed to load review details. Document may not exist.</p>
          </CardContent>
        </Card>
      </div>
    );
  }

  const { document, latest_draft, validation_report, fact_sheet, audit_log } = reviewDetails;

  return (
    <div className="flex flex-col gap-4 h-full">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1 text-sm text-gray-500">
        <Link to="/review" className="hover:text-gray-900 transition-colors font-medium">
          Review Queue
        </Link>
        <ChevronRight className="h-4 w-4 shrink-0" />
        <span className="text-gray-900 font-medium truncate">{document.title}</span>
      </nav>

      {/* Split-pane layout */}
      <div className="flex gap-6 min-h-0 flex-1">
        {/* Left pane — 60% — Content viewer */}
        <div className="flex-[3] min-w-0 overflow-y-auto">
          <Card className="h-full">
            <CardHeader className="pb-0">
              <CardTitle className="text-base">Document Content</CardTitle>
            </CardHeader>
            <CardContent className="pt-4">
              <Tabs defaultValue="draft">
                <TabsList className="w-full justify-start">
                  <TabsTrigger value="draft">Draft</TabsTrigger>
                  <TabsTrigger value="validation">Validation</TabsTrigger>
                  <TabsTrigger value="factsheet">Fact Sheet</TabsTrigger>
                  <TabsTrigger value="history">History</TabsTrigger>
                </TabsList>

                <TabsContent value="draft" className="mt-4">
                  <DraftTab draft={latest_draft} />
                </TabsContent>

                <TabsContent value="validation" className="mt-4">
                  <ValidationTab report={validation_report} />
                </TabsContent>

                <TabsContent value="factsheet" className="mt-4">
                  <FactSheetTab factSheet={fact_sheet} />
                </TabsContent>

                <TabsContent value="history" className="mt-4">
                  <HistoryTab logs={audit_log} />
                </TabsContent>
              </Tabs>
            </CardContent>
          </Card>
        </div>

        {/* Right pane — 40% — Decision panel */}
        <div className="flex-[2] min-w-0 overflow-y-auto">
          <DecisionPanel reviewDetails={reviewDetails} />
        </div>
      </div>
    </div>
  );
}
