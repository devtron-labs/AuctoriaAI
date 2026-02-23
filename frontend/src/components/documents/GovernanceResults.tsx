import { CheckCircle, XCircle, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { GovernanceCheckResult } from '@/types/document';

interface GovernanceResultsProps {
  result: GovernanceCheckResult;
}

export default function GovernanceResults({ result }: GovernanceResultsProps) {
  const isPassed = result.decision === 'PASSED';

  return (
    <div className="space-y-4">
      {/* Decision badge + status + reason */}
      <div className="flex items-start gap-3">
        {isPassed ? (
          <CheckCircle className="h-6 w-6 text-green-500 shrink-0 mt-0.5" />
        ) : (
          <XCircle className="h-6 w-6 text-red-500 shrink-0 mt-0.5" />
        )}
        <div className="min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <Badge
              variant={isPassed ? 'default' : 'destructive'}
              className={`text-sm px-3 py-0.5 ${
                isPassed
                  ? 'bg-green-100 text-green-800 border-green-200 hover:bg-green-100'
                  : ''
              }`}
            >
              {result.decision}
            </Badge>
            <span className="text-sm text-muted-foreground">{result.final_status}</span>
          </div>
          <p className="text-sm text-muted-foreground mt-1">{result.reason}</p>
        </div>
      </div>

      {/* Details card */}
      <Card>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm">Governance Details</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm">
          {/* Score vs threshold */}
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Quality Score</span>
            <div className="flex items-center gap-2">
              <span
                className={`font-medium ${
                  result.details.score_passed ? 'text-green-600' : 'text-red-600'
                }`}
              >
                {result.details.score.toFixed(1)}
              </span>
              <span className="text-muted-foreground text-xs">
                / threshold {result.details.score_threshold.toFixed(1)}
              </span>
              {result.details.score_passed ? (
                <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
              ) : (
                <XCircle className="h-4 w-4 text-red-500 shrink-0" />
              )}
            </div>
          </div>

          {/* Claims validity */}
          <div className="flex items-center justify-between">
            <span className="text-muted-foreground">Claims Valid</span>
            <div className="flex items-center gap-2">
              {result.details.claims_valid ? (
                <>
                  <span className="text-green-600 font-medium">Yes</span>
                  <CheckCircle className="h-4 w-4 text-green-500 shrink-0" />
                </>
              ) : (
                <>
                  <span className="text-red-600 font-medium">No</span>
                  <XCircle className="h-4 w-4 text-red-500 shrink-0" />
                </>
              )}
            </div>
          </div>

          {/* Blocked claims count (only if non-zero) */}
          {result.details.blocked_claims !== undefined && result.details.blocked_claims > 0 && (
            <div className="flex items-center justify-between">
              <span className="text-muted-foreground">Blocked Claims</span>
              <span className="text-red-600 font-medium">{result.details.blocked_claims}</span>
            </div>
          )}

          {/* Validation summary */}
          {result.details.validation_summary && (
            <div className="pt-2 border-t space-y-1">
              <p className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                Validation Summary
              </p>
              <p className="text-sm">{result.details.validation_summary}</p>
            </div>
          )}
        </CardContent>
      </Card>

      {/* Next steps */}
      <div
        className={`rounded-md border p-3 text-sm flex items-start gap-2 ${
          isPassed
            ? 'border-green-200 bg-green-50 text-green-800'
            : 'border-amber-200 bg-amber-50 text-amber-800'
        }`}
      >
        <ArrowRight className="h-4 w-4 mt-0.5 shrink-0" />
        <span>
          {isPassed
            ? 'Ready for human review. The document has passed all governance checks and can be submitted for approval.'
            : 'Address the issues above and try again. Ensure the quality score meets the threshold and all claims pass validation.'}
        </span>
      </div>
    </div>
  );
}
