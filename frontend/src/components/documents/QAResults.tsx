import { CheckCircle, XCircle, TrendingUp, TrendingDown, Minus } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import type { QAIterationResult } from '@/types/document';

interface QAResultsProps {
  result: QAIterationResult;
}

function ScoreColor({ score }: { score: number }) {
  if (score >= 7) return 'text-green-600';
  if (score >= 5) return 'text-yellow-600';
  return 'text-red-600';
}

function ScoreTrend({ score }: { score: number }) {
  if (score >= 7) return <TrendingUp className="h-4 w-4 text-green-500" />;
  if (score >= 5) return <Minus className="h-4 w-4 text-yellow-500" />;
  return <TrendingDown className="h-4 w-4 text-red-500" />;
}

export default function QAResults({ result }: QAResultsProps) {
  const isPassed = result.final_status === 'PASSED';
  const scoreColorClass = ScoreColor({ score: result.final_score });

  return (
    <div className="space-y-4">
      {/* Summary Card */}
      <Card className={isPassed ? 'border-green-200 bg-green-50/30' : 'border-red-200 bg-red-50/30'}>
        <CardHeader className="pb-2">
          <CardTitle className="text-sm flex items-center gap-2">
            {isPassed ? (
              <CheckCircle className="h-4 w-4 text-green-500" />
            ) : (
              <XCircle className="h-4 w-4 text-red-500" />
            )}
            QA Iteration Complete
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-3 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-foreground">{result.iterations_completed}</p>
              <p className="text-xs text-muted-foreground mt-0.5">Iterations</p>
            </div>
            <div>
              <div className="flex items-center justify-center gap-1">
                <p className={`text-2xl font-bold ${scoreColorClass}`}>
                  {result.final_score.toFixed(1)}
                </p>
                <ScoreTrend score={result.final_score} />
              </div>
              <p className="text-xs text-muted-foreground mt-0.5">Final Score</p>
            </div>
            <div className="flex flex-col items-center">
              <Badge
                variant={isPassed ? 'default' : 'destructive'}
                className={`mt-1 ${isPassed ? 'bg-green-100 text-green-800 border-green-200 hover:bg-green-100' : ''}`}
              >
                {result.final_status}
              </Badge>
              <p className="text-xs text-muted-foreground mt-1.5">Status</p>
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Iteration history summary */}
      <div className="space-y-1.5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
          Iteration Summary
        </p>
        <div className="space-y-1">
          {Array.from({ length: result.iterations_completed }).map((_, i) => {
            const isLast = i === result.iterations_completed - 1;
            return (
              <div
                key={i}
                className={`flex items-center justify-between rounded-md px-3 py-2 text-sm ${
                  isLast ? 'bg-muted/60 font-medium' : 'bg-muted/30'
                }`}
              >
                <span className="text-muted-foreground">
                  Iteration {i + 1}
                  {isLast ? ' (final)' : ''}
                </span>
                {isLast && (
                  <div className="flex items-center gap-1.5">
                    <span className={`font-semibold ${scoreColorClass}`}>
                      {result.final_score.toFixed(1)}
                    </span>
                    <ScoreTrend score={result.final_score} />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>

      {/* Outcome message */}
      <div
        className={`rounded-md border p-3 text-sm ${
          isPassed
            ? 'border-green-200 bg-green-50 text-green-800'
            : 'border-red-200 bg-red-50 text-red-800'
        }`}
      >
        {isPassed
          ? `Draft passed QA with a score of ${result.final_score.toFixed(1)} after ${result.iterations_completed} iteration${result.iterations_completed !== 1 ? 's' : ''}.`
          : `Draft blocked after ${result.iterations_completed} iteration${result.iterations_completed !== 1 ? 's' : ''} (score: ${result.final_score.toFixed(1)}). Consider revising the source content and running again.`}
      </div>
    </div>
  );
}
