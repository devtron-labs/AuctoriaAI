import { useState } from 'react';
import {
  CheckCircle,
  XCircle,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  ShieldCheck,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { cn } from '@/lib/utils';
import type { ValidationReport } from '@/types/document';

// ─── Summary card ──────────────────────────────────────────────────────────────

function SummaryCard({ report }: { report: ValidationReport }) {
  const stats = [
    {
      label: 'Total Claims',
      value: report.total_claims,
      color: 'text-foreground',
      bg: 'bg-muted/60',
    },
    {
      label: 'Valid',
      value: report.valid_claims,
      color: 'text-green-600',
      bg: 'bg-green-50 border border-green-200',
    },
    {
      label: 'Blocked',
      value: report.blocked_claims,
      color: 'text-red-600',
      bg: 'bg-red-50 border border-red-200',
    },
    {
      label: 'Warnings',
      value: report.warnings,
      color: 'text-amber-600',
      bg: 'bg-amber-50 border border-amber-200',
    },
  ];

  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      {stats.map(({ label, value, color, bg }) => (
        <div key={label} className={cn('rounded-lg p-3 text-center', bg)}>
          <p className={cn('text-2xl font-bold tabular-nums', color)}>{value}</p>
          <p className="text-xs text-muted-foreground mt-0.5">{label}</p>
        </div>
      ))}
    </div>
  );
}

// ─── Single claim row ──────────────────────────────────────────────────────────

function ClaimRow({
  result,
  index,
}: {
  result: ValidationReport['results'][number];
  index: number;
}) {
  const [open, setOpen] = useState(false);

  return (
    <div className="rounded-lg border overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className={cn(
          'flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/40',
          open && 'bg-muted/40',
        )}
      >
        {/* Valid / invalid icon */}
        {result.is_valid ? (
          <CheckCircle className="h-4 w-4 shrink-0 text-green-500" />
        ) : (
          <XCircle className="h-4 w-4 shrink-0 text-red-500" />
        )}

        <div className="flex flex-1 items-center gap-2 min-w-0">
          <span className="text-xs font-mono text-muted-foreground shrink-0">#{index + 1}</span>
          <span className="text-sm truncate text-foreground">{result.claim.claim_text}</span>
        </div>

        <div className="flex items-center gap-2 shrink-0">
          {/* Claim type badge */}
          <Badge variant="secondary" className="text-xs hidden sm:inline-flex">
            {result.claim.claim_type}
          </Badge>

          {/* Expired warning */}
          {result.is_expired && (
            <Badge
              variant="outline"
              className="text-xs border-amber-300 bg-amber-50 text-amber-600 gap-1"
            >
              <AlertTriangle className="h-3 w-3" />
              Expired
            </Badge>
          )}

          {/* Expand chevron */}
          {open ? (
            <ChevronDown className="h-4 w-4 text-muted-foreground" />
          ) : (
            <ChevronRight className="h-4 w-4 text-muted-foreground" />
          )}
        </div>
      </button>

      {open && (
        <div className="border-t bg-muted/20 px-4 py-3 space-y-2 text-sm">
          <div className="flex gap-2">
            <span className="text-muted-foreground w-24 shrink-0">Type</span>
            <span className="font-medium">{result.claim.claim_type}</span>
          </div>
          <div className="flex gap-2">
            <span className="text-muted-foreground w-24 shrink-0">Status</span>
            <span
              className={cn(
                'font-medium',
                result.is_valid ? 'text-green-600' : 'text-red-600',
              )}
            >
              {result.is_valid ? 'Valid' : 'Invalid'}
            </span>
          </div>
          {result.is_expired && (
            <div className="flex gap-2">
              <span className="text-muted-foreground w-24 shrink-0">Expiry</span>
              <span className="text-amber-600 font-medium">Claim data may be expired</span>
            </div>
          )}
          {result.error_message && (
            <div className="flex gap-2">
              <span className="text-muted-foreground w-24 shrink-0">Error</span>
              <span className="text-red-600">{result.error_message}</span>
            </div>
          )}
          <div className="pt-1">
            <p className="text-xs text-muted-foreground mb-1">Full claim text</p>
            <p className="text-sm leading-relaxed">{result.claim.claim_text}</p>
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Main component ────────────────────────────────────────────────────────────

interface ValidationResultsProps {
  report: ValidationReport | null;
}

export default function ValidationResults({ report }: ValidationResultsProps) {
  if (!report) {
    return (
      <Card>
        <CardContent className="flex flex-col items-center justify-center gap-3 py-10 text-center text-muted-foreground">
          <ShieldCheck className="h-10 w-10 opacity-25" />
          <p className="text-sm">No validation run yet. Click &ldquo;Validate Claims&rdquo; to check this draft.</p>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader className="pb-4">
        <CardTitle className="flex items-center gap-2 text-base">
          {report.is_valid ? (
            <CheckCircle className="h-5 w-5 text-green-500" />
          ) : (
            <XCircle className="h-5 w-5 text-red-500" />
          )}
          Validation {report.is_valid ? 'Passed' : 'Failed'}
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        <SummaryCard report={report} />

        {report.results.length > 0 && (
          <div className="space-y-2">
            <p className="text-sm font-medium text-muted-foreground">
              Claims ({report.results.length})
            </p>
            <div className="space-y-2">
              {report.results.map((result, i) => (
                <ClaimRow key={i} result={result} index={i} />
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
