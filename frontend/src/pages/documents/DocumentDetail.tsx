import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  ChevronRight,
  Calendar,
  Clock,
  FileText,
  Hash,
  Tag,
  Upload,
  Wand2,
  ClipboardCheck,
  History,
  RefreshCw,
  AlertCircle,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs';
import StatusBadge from '@/components/shared/StatusBadge';
import UploadTab from '@/components/documents/UploadTab';
import DraftsTabComponent from '@/components/documents/DraftsTab';
import { useDocument, useAuditLogs } from '@/hooks';
import { formatDateTime } from '@/lib/utils';
import type { Document, DocumentStatus, AuditLog } from '@/types/document';

// ─── Status timeline ──────────────────────────────────────────────────────────

const STATUS_STEPS: DocumentStatus[] = [
  'DRAFT',
  'VALIDATING',
  'PASSED',
  'HUMAN_REVIEW',
  'APPROVED',
];

const STATUS_LABELS: Record<DocumentStatus, string> = {
  DRAFT: 'Draft',
  VALIDATING: 'Validating',
  PASSED: 'Passed',
  HUMAN_REVIEW: 'Human Review',
  APPROVED: 'Approved',
  BLOCKED: 'Blocked',
};

function StatusTimeline({ document }: { document: Document }) {
  const current = document.status;

  const currentIdx = STATUS_STEPS.indexOf(current);

  // ─── Helper: Render failure details ───
  const renderFailure = () => {
    if (document.status !== 'BLOCKED' && document.current_stage !== 'DRAFT_FAILED' && document.current_stage !== 'QA_FAILED') {
      return null;
    }

    const isRateLimit = document.error_message?.toLowerCase().includes('rate limit') || 
                        document.error_message?.toLowerCase().includes('quota');
    
    let title = 'Process Blocked';
    let suggestion = 'Please check the logs or contact an administrator.';

    if (document.current_stage === 'DRAFT_FAILED') {
      title = 'Draft Generation Failed';
      suggestion = isRateLimit 
        ? 'The AI provider is currently rate-limited. Please wait a few minutes and try again.'
        : 'An error occurred during generation. Try adjusting your prompt or checking API configuration.';
    } else if (document.current_stage === 'QA_FAILED') {
      title = 'QA Evaluation Failed';
      suggestion = isRateLimit
        ? 'The AI provider is currently rate-limited. Please wait a few minutes and try again.'
        : 'An error occurred during the QA process. Check your system settings and API keys.';
    } else if (document.current_stage === 'QA_BLOCKED') {
      title = 'QA Quality Gate Blocked';
      suggestion = 'The draft could not reach the required passing threshold within the iteration limit. You may need to manually improve the draft or adjust the threshold.';
    } else if (document.status === 'BLOCKED' && !document.current_stage?.includes('FAILED')) {
      title = 'Governance Gate Blocked';
      suggestion = 'This document failed claim validation or governance checks. Review the "Drafts" tab for specific violations.';
    }

    return (
      <div className="flex items-start gap-3 rounded-md border border-red-200 bg-red-50 p-4 text-sm text-red-700 mt-4">
        <AlertCircle className="mt-0.5 h-5 w-5 shrink-0" />
        <div className="space-y-2 flex-1 min-w-0">
          <div>
            <p className="font-bold text-base leading-none mb-1">{title}</p>
            <p className="text-xs opacity-90 break-all font-mono bg-red-100/50 p-2 rounded mt-2 border border-red-200">
              {document.error_message || 'No specific error message provided.'}
            </p>
          </div>
          <div className="pt-1 text-red-800">
            <p className="font-semibold text-xs uppercase tracking-wider mb-1 opacity-70">Suggested Action</p>
            <p>{suggestion}</p>
          </div>
        </div>
      </div>
    );
  };

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-0 w-full overflow-x-auto pb-2">
        {STATUS_STEPS.map((step, idx) => {
          const isPast = idx < currentIdx;
          const isCurrent = idx === currentIdx;

          return (
            <div key={step} className="flex items-center flex-1 min-w-0">
              <div className="flex flex-col items-center flex-1 min-w-0">
                <div
                  className={`h-8 w-8 rounded-full flex items-center justify-center text-xs font-bold border-2 transition-colors ${
                    isPast
                      ? 'bg-primary border-primary text-primary-foreground'
                      : isCurrent
                        ? 'bg-primary/10 border-primary text-primary'
                        : 'bg-background border-muted-foreground/30 text-muted-foreground'
                  }`}
                >
                  {isPast ? '✓' : idx + 1}
                </div>
                <span
                  className={`mt-1.5 text-xs text-center whitespace-nowrap ${
                    isCurrent
                      ? 'font-semibold text-primary'
                      : isPast
                        ? 'text-foreground'
                        : 'text-muted-foreground'
                  }`}
                >
                  {STATUS_LABELS[step]}
                </span>
              </div>
              {idx < STATUS_STEPS.length - 1 && (
                <div
                  className={`h-0.5 flex-1 mx-1 transition-colors ${
                    idx < currentIdx ? 'bg-primary' : 'bg-muted-foreground/20'
                  }`}
                />
              )}
            </div>
          );
        })}
      </div>

      {renderFailure()}
    </div>
  );
}

// ─── Overview tab ─────────────────────────────────────────────────────────────

interface OverviewTabProps {
  document: Document;
  onSwitchTab: (tab: string) => void;
}

function OverviewTab({ document, onSwitchTab }: OverviewTabProps) {
  const hasFile = !!document.file_path;

  return (
    <div className="space-y-6">
      {/* Metadata */}
      <Card>
        <CardHeader>
          <CardTitle>Document Metadata</CardTitle>
        </CardHeader>
        <CardContent>
          <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
            <div className="flex items-start gap-2">
              <Hash className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
              <div>
                <dt className="text-muted-foreground">Document ID</dt>
                <dd className="font-mono text-xs mt-0.5 break-all">{document.id}</dd>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Tag className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
              <div>
                <dt className="text-muted-foreground">Status</dt>
                <dd className="mt-0.5">
                  <StatusBadge status={document.status} />
                </dd>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Calendar className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
              <div>
                <dt className="text-muted-foreground">Created</dt>
                <dd className="font-medium mt-0.5">{formatDateTime(document.created_at)}</dd>
              </div>
            </div>
            <div className="flex items-start gap-2">
              <Clock className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
              <div>
                <dt className="text-muted-foreground">Last Updated</dt>
                <dd className="font-medium mt-0.5">{formatDateTime(document.updated_at)}</dd>
              </div>
            </div>
          </dl>
        </CardContent>
      </Card>

      {/* File info */}
      {hasFile && (
        <Card>
          <CardHeader>
            <CardTitle>File Information</CardTitle>
          </CardHeader>
          <CardContent>
            <dl className="grid grid-cols-1 sm:grid-cols-2 gap-4 text-sm">
              <div className="flex items-start gap-2">
                <FileText className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
                <div>
                  <dt className="text-muted-foreground">Filename</dt>
                  <dd className="font-medium font-mono mt-0.5">
                    {document.file_path?.split('/').pop() ?? '—'}
                  </dd>
                </div>
              </div>
              <div className="flex items-start gap-2">
                <Tag className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
                <div>
                  <dt className="text-muted-foreground">Classification</dt>
                  <dd className="font-medium mt-0.5">{document.classification ?? '—'}</dd>
                </div>
              </div>
              {document.file_hash && (
                <div className="col-span-2 flex items-start gap-2">
                  <Hash className="h-4 w-4 mt-0.5 text-muted-foreground shrink-0" />
                  <div>
                    <dt className="text-muted-foreground">SHA-256 Hash</dt>
                    <dd className="font-mono text-xs break-all mt-0.5">{document.file_hash}</dd>
                  </div>
                </div>
              )}
            </dl>
          </CardContent>
        </Card>
      )}

      {/* Status timeline */}
      <Card>
        <CardHeader>
          <CardTitle>Pipeline Status</CardTitle>
          <CardDescription>Current position in the document processing pipeline.</CardDescription>
        </CardHeader>
        <CardContent>
          <StatusTimeline document={document} />
        </CardContent>
      </Card>

      {/* Quick actions */}
      <Card>
        <CardHeader>
          <CardTitle>Quick Actions</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap gap-3">
            <Button variant="outline" className="gap-2" onClick={() => onSwitchTab('upload')}>
              <Upload className="h-4 w-4" />
              Upload File
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => onSwitchTab('drafts')}>
              <Wand2 className="h-4 w-4" />
              Generate Draft
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => onSwitchTab('drafts')}>
              <ClipboardCheck className="h-4 w-4" />
              Run QA
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => onSwitchTab('history')}>
              <History className="h-4 w-4" />
              View History
            </Button>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}

// ─── History tab ──────────────────────────────────────────────────────────────

function HistoryTab({ documentId }: { documentId: string }) {
  const { data: logs, isLoading, error, refetch, isFetching } = useAuditLogs(documentId);

  const sorted = [...(logs ?? [])].sort(
    (a: AuditLog, b: AuditLog) =>
      new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-4">
        <div>
          <CardTitle>Activity History</CardTitle>
          <CardDescription>Audit log for this document, newest first.</CardDescription>
        </div>
        <Button variant="ghost" size="sm" onClick={() => void refetch()} disabled={isFetching}>
          <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
        </Button>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-14 rounded-md bg-muted animate-pulse" />
            ))}
          </div>
        ) : error ? (
          <div className="space-y-3">
            <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0 mt-0.5" />
              <div className="flex-1 min-w-0 break-all">
                Failed to load audit logs.
              </div>
            </div>
            <Button variant="outline" size="sm" onClick={() => void refetch()}>
              Retry
            </Button>
          </div>
        ) : sorted.length === 0 ? (
          <p className="text-sm text-muted-foreground">No activity recorded yet.</p>
        ) : (
          <ol className="relative border-l border-muted ml-3 space-y-0">
            {sorted.map((log: AuditLog) => (
              <li key={log.id} className="mb-6 ml-4">
                <div className="absolute -left-1.5 mt-1.5 h-3 w-3 rounded-full border-2 border-background bg-primary" />
                <p className="text-sm font-medium text-foreground">{log.action}</p>
                <time className="text-xs text-muted-foreground">{formatDateTime(log.timestamp)}</time>
              </li>
            ))}
          </ol>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function DocumentDetail() {
  const { id } = useParams<{ id: string }>();
  const { data: document, isLoading, error } = useDocument(id ?? '');
  const [activeTab, setActiveTab] = useState('overview');

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-16">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  if (error || !document) {
    const is404 =
      (error as { response?: { status?: number } })?.response?.status === 404;

    return (
      <div className="space-y-4">
        <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
          <Link to="/documents" className="hover:text-foreground transition-colors">
            Documents
          </Link>
          <ChevronRight className="h-4 w-4" />
          <span className="text-foreground">Not Found</span>
        </nav>
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6 space-y-3">
            <p className="text-red-700 font-medium">
              {is404 ? 'Document not found.' : 'Failed to load document.'}
            </p>
            <Button variant="outline" size="sm" asChild>
              <Link to="/documents">Back to Documents</Link>
            </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Breadcrumb */}
      <nav className="flex items-center gap-1.5 text-sm text-muted-foreground">
        <Link to="/documents" className="hover:text-foreground transition-colors">
          Documents
        </Link>
        <ChevronRight className="h-4 w-4" />
        <span className="text-foreground font-medium truncate max-w-[240px]">
          {document.title}
        </span>
      </nav>

      {/* Page header */}
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-bold text-foreground leading-tight">{document.title}</h1>
          <p className="text-xs text-muted-foreground mt-1 font-mono">{document.id}</p>
        </div>
        <StatusBadge status={document.status} />
      </div>

      {/* Tabs */}
      <Tabs value={activeTab} onValueChange={setActiveTab}>
        <TabsList>
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="upload">Upload</TabsTrigger>
          <TabsTrigger value="drafts">Drafts</TabsTrigger>
          <TabsTrigger value="history">History</TabsTrigger>
        </TabsList>

        <TabsContent value="overview" className="mt-4">
          <OverviewTab document={document} onSwitchTab={setActiveTab} />
        </TabsContent>

        <TabsContent value="upload" className="mt-4">
          <UploadTab documentId={id!} document={document} />
        </TabsContent>

        <TabsContent value="drafts" className="mt-4">
          <DraftsTabComponent documentId={id!} onSwitchTab={setActiveTab} />
        </TabsContent>

        <TabsContent value="history" className="mt-4">
          <HistoryTab documentId={id!} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
