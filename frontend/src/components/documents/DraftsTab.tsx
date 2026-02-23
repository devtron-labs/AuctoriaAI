import { useState, useEffect, useRef } from 'react';
import {
  Wand2,
  ShieldCheck,
  Loader2,
  AlertCircle,
  RefreshCw,
  RotateCcw,
  Scale,
  Play,
} from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { useDocument, useValidateClaims, useGovernanceCheck } from '@/hooks';
import GenerateDraftModal from './GenerateDraftModal';
import RunQAModal from './RunQAModal';
import DraftVersionList from './DraftVersionList';
import DraftViewer from './DraftViewer';
import ValidationResults from './ValidationResults';
import QAResults from './QAResults';
import GovernanceResults from './GovernanceResults';
import type { ValidationReport, QAIterationResult, GovernanceCheckResult } from '@/types/document';

interface DraftsTabProps {
  documentId: string;
}

export default function DraftsTab({ documentId }: DraftsTabProps) {
  const [showGenerateModal, setShowGenerateModal] = useState(false);
  const [showQAModal, setShowQAModal] = useState(false);
  const [selectedDraftId, setSelectedDraftId] = useState<string | null>(null);
  const [validationReport, setValidationReport] = useState<ValidationReport | null>(null);
  const [qaResult, setQAResult] = useState<QAIterationResult | null>(null);
  const [governanceResult, setGovernanceResult] = useState<GovernanceCheckResult | null>(null);

  const { data: document, isLoading, error, refetch, isFetching } = useDocument(documentId);

  const { mutate: validate, isPending: isValidating, error: validateError } = useValidateClaims(documentId);

  const {
    mutate: runGovernance,
    isPending: isGovernanceChecking,
    error: governanceError,
  } = useGovernanceCheck(documentId);

  // Backend returns draft_versions ordered by iteration_number DESC, so index 0 is newest.
  const drafts = document?.draft_versions ?? [];
  const newestDraft = drafts[0] ?? null;

  // Track previous draft count so we can auto-jump to newest when a new draft arrives.
  const prevDraftCountRef = useRef(drafts.length);
  useEffect(() => {
    if (drafts.length > prevDraftCountRef.current) {
      // A new draft was generated (via Generate or QA iteration) — show it immediately.
      setSelectedDraftId(null);
    }
    prevDraftCountRef.current = drafts.length;
  }, [drafts.length]);

  // Resolve which draft to display:
  //   1. If the user explicitly selected one that still exists → show it.
  //   2. Otherwise fall back to the newest (index 0).
  const selectedDraft = selectedDraftId ? (drafts.find((d) => d.id === selectedDraftId) ?? null) : null;
  const viewedDraft = selectedDraft ?? newestDraft;

  const handleSelect = (id: string) => setSelectedDraftId(id);

  const handleValidate = () => {
    validate(undefined, {
      onSuccess: (report) => {
        setValidationReport(report);
      },
    });
  };

  const handleGovernanceCheck = () => {
    setGovernanceResult(null);
    runGovernance(undefined, {
      onSuccess: (result) => {
        setGovernanceResult(result);
      },
    });
  };

  // Governance button is only enabled when the viewed draft has a score AND validation
  // has been run in this session
  const hasDraftScore = viewedDraft?.score !== null && viewedDraft?.score !== undefined;
  const hasValidationReport = validationReport !== null;
  const canRunGovernance = hasDraftScore && hasValidationReport && drafts.length > 0;

  const governanceDisabledReason = !hasDraftScore
    ? 'Draft must have a quality score — run QA Iteration first'
    : !hasValidationReport
      ? 'Run Validate Claims first before checking governance'
      : '';

  const validateApiError =
    (validateError as { response?: { data?: { detail?: string } } } | null)?.response?.data
      ?.detail ??
    validateError?.message ??
    null;

  const governanceApiError =
    (governanceError as { response?: { data?: { detail?: string } } } | null)?.response?.data
      ?.detail ??
    governanceError?.message ??
    null;

  // ─── Loading / error states ──────────────────────────────────────────────────

  if (isLoading) {
    return (
      <Card>
        <CardContent className="flex items-center justify-center py-12">
          <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-red-200">
        <CardContent className="pt-6 space-y-3">
          <div className="flex items-center gap-2 text-red-700 text-sm">
            <AlertCircle className="h-4 w-4 shrink-0" />
            Failed to load drafts.
          </div>
          <Button variant="outline" size="sm" onClick={() => void refetch()}>
            Retry
          </Button>
        </CardContent>
      </Card>
    );
  }

  // ─── Main layout ─────────────────────────────────────────────────────────────

  return (
    <div className="space-y-6">
      {/* Header toolbar */}
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <CardTitle>Drafts</CardTitle>
              <CardDescription className="mt-0.5">
                {drafts.length === 0
                  ? 'No drafts generated yet.'
                  : `${drafts.length} iteration${drafts.length === 1 ? '' : 's'} · select one to view`}
              </CardDescription>
            </div>
            <div className="flex items-center gap-2 shrink-0">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => void refetch()}
                disabled={isFetching}
                title="Refresh drafts"
              >
                <RefreshCw className={`h-4 w-4 ${isFetching ? 'animate-spin' : ''}`} />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="gap-2"
                onClick={handleValidate}
                disabled={isValidating || drafts.length === 0}
              >
                {isValidating ? (
                  <Loader2 className="h-4 w-4 animate-spin" />
                ) : (
                  <ShieldCheck className="h-4 w-4" />
                )}
                {isValidating ? 'Validating…' : 'Validate Claims'}
              </Button>
              <Button className="gap-2" size="sm" onClick={() => setShowGenerateModal(true)}>
                <Wand2 className="h-4 w-4" />
                Generate Draft
              </Button>
            </div>
          </div>
        </CardHeader>
      </Card>

      {/* Validate error */}
      {validateApiError && (
        <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
          <AlertCircle className="h-4 w-4 shrink-0" />
          {validateApiError}
        </div>
      )}

      {drafts.length === 0 ? (
        /* Empty state */
        <Card>
          <CardContent className="flex flex-col items-center justify-center gap-3 py-14 text-center text-muted-foreground">
            <Wand2 className="h-10 w-10 opacity-25" />
            <p className="text-sm">
              No drafts yet. Click <strong className="text-foreground">Generate Draft</strong> to
              create the first iteration.
            </p>
          </CardContent>
        </Card>
      ) : (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-[280px_1fr]">
          {/* Left: version timeline */}
          <div className="space-y-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground ml-3">
              Iterations
            </p>
            <DraftVersionList
              drafts={drafts}
              selectedId={viewedDraft?.id ?? null}
              onSelect={handleSelect}
            />
          </div>

          {/* Right: QA section + viewer + validation + governance */}
          <div className="space-y-6 min-w-0">
            {/* ── Quality Assurance section ── */}
            <Card>
              <CardHeader className="pb-3">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-base">
                      <RotateCcw className="h-4 w-4 text-primary" />
                      Quality Assurance
                    </CardTitle>
                    <CardDescription className="mt-0.5">
                      Automatically evaluate and improve the draft through multiple iterations.
                    </CardDescription>
                  </div>
                  <Button
                    size="sm"
                    variant="outline"
                    className="gap-2 shrink-0"
                    onClick={() => setShowQAModal(true)}
                    disabled={isGovernanceChecking}
                  >
                    <Play className="h-4 w-4" />
                    Run QA Iteration
                  </Button>
                </div>
              </CardHeader>

              {qaResult && (
                <CardContent className="pt-0">
                  <QAResults result={qaResult} />
                </CardContent>
              )}
            </Card>

            {viewedDraft ? (
              <>
                <DraftViewer draft={viewedDraft} />
                <ValidationResults report={validationReport} />

                {/* ── Governance Check section ── */}
                <Card>
                  <CardHeader className="pb-3">
                    <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                      <div>
                        <CardTitle className="flex items-center gap-2 text-base">
                          <Scale className="h-4 w-4 text-primary" />
                          Governance Check
                        </CardTitle>
                        <CardDescription className="mt-0.5">
                          Verify the document meets all governance requirements before human review.
                        </CardDescription>
                      </div>
                      <div title={!canRunGovernance ? governanceDisabledReason : undefined}>
                        <Button
                          size="sm"
                          variant="outline"
                          className="gap-2 shrink-0"
                          onClick={handleGovernanceCheck}
                          disabled={!canRunGovernance || isGovernanceChecking}
                        >
                          {isGovernanceChecking ? (
                            <>
                              <Loader2 className="h-4 w-4 animate-spin" />
                              Checking…
                            </>
                          ) : (
                            <>
                              <Scale className="h-4 w-4" />
                              Run Governance Check
                            </>
                          )}
                        </Button>
                      </div>
                    </div>

                    {/* Requirements hint when button is disabled */}
                    {!canRunGovernance && (
                      <p className="text-xs text-muted-foreground mt-1">
                        {governanceDisabledReason}
                      </p>
                    )}
                  </CardHeader>

                  {governanceApiError && (
                    <CardContent className="pt-0">
                      <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                        <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                        <span>{governanceApiError}</span>
                      </div>
                    </CardContent>
                  )}

                  {governanceResult && (
                    <CardContent className="pt-0">
                      <GovernanceResults result={governanceResult} />
                    </CardContent>
                  )}
                </Card>
              </>
            ) : null}
          </div>
        </div>
      )}

      {/* Generate draft modal */}
      <GenerateDraftModal
        documentId={documentId}
        open={showGenerateModal}
        onOpenChange={setShowGenerateModal}
      />

      {/* QA iteration modal */}
      <RunQAModal
        documentId={documentId}
        open={showQAModal}
        onOpenChange={setShowQAModal}
        onSuccess={(result) => setQAResult(result)}
      />
    </div>
  );
}
