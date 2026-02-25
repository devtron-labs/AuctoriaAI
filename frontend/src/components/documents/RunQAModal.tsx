import { useState, useEffect, useRef } from 'react';
import { RotateCcw, Play, AlertCircle, Loader2 } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useQAIteration } from '@/hooks';
import type { QAIterationResult } from '@/types/document';
import QAResults from './QAResults';

interface RunQAModalProps {
  documentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSuccess?: (result: QAIterationResult) => void;
  onClose?: (hasError: boolean) => void;
}

type ProgressPhase = 'Evaluating' | 'Improving' | 'Finalizing';

export default function RunQAModal({
  documentId,
  open,
  onOpenChange,
  onSuccess,
  onClose,
}: RunQAModalProps) {
  const [maxIterations, setMaxIterations] = useState(3);
  const [simulatedIteration, setSimulatedIteration] = useState(1);
  const [simulatedPhase, setSimulatedPhase] = useState<ProgressPhase>('Evaluating');
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { mutate: runQA, isPending, isSuccess, error, reset, data } = useQAIteration(documentId);

  // Simulate iteration progress messages while the API call is in flight
  useEffect(() => {
    if (isPending) {
      setSimulatedIteration(1);
      setSimulatedPhase('Evaluating');
      let currentIter = 1;
      let currentPhase: ProgressPhase = 'Evaluating';

      intervalRef.current = setInterval(() => {
        // Once we've shown all iterations, stop cycling and show Finalizing
        if (currentIter >= maxIterations && currentPhase !== 'Evaluating') {
          if (intervalRef.current) {
            clearInterval(intervalRef.current);
            intervalRef.current = null;
          }
          setSimulatedPhase('Finalizing');
          return;
        }

        if (currentPhase === 'Evaluating') {
          currentPhase = 'Improving';
          setSimulatedPhase('Improving');
        } else {
          currentIter = Math.min(currentIter + 1, maxIterations);
          currentPhase = 'Evaluating';
          setSimulatedIteration(currentIter);
          setSimulatedPhase('Evaluating');
        }
      }, 2500);
    } else {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
        intervalRef.current = null;
      }
    }

    return () => {
      if (intervalRef.current) {
        clearInterval(intervalRef.current);
      }
    };
  }, [isPending, maxIterations]);

  const handleRun = () => {
    runQA(maxIterations, {
      onSuccess: (result) => {
        onSuccess?.(result);
      },
    });
  };

  const handleIterationsChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const parsed = parseInt(e.target.value, 10);
    setMaxIterations(Math.min(10, Math.max(1, isNaN(parsed) ? 1 : parsed)));
  };

  const handleClose = () => {
    const hasError = !!error || (isSuccess && data?.final_status === 'BLOCKED');
    onOpenChange(false);
    onClose?.(hasError);
    // Reset state after dialog close animation
    setTimeout(() => {
      reset();
      setMaxIterations(3);
      setSimulatedIteration(1);
      setSimulatedPhase('Evaluating');
    }, 200);
  };

  const apiError =
    (error as { response?: { data?: { detail?: string } } } | null)?.response?.data?.detail ??
    error?.message ??
    null;

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <RotateCcw className="h-5 w-5 text-primary" />
            Run QA Iteration
          </DialogTitle>
          <DialogDescription>
            Automatically evaluate and improve the draft through multiple iterations.
          </DialogDescription>
        </DialogHeader>

        {isPending ? (
          /* ── Progress state ── */
          <div className="flex flex-col items-center gap-4 py-8 text-center">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <div>
              <p className="font-medium text-foreground">Running QA Iteration</p>
              <p className="text-sm text-muted-foreground mt-1">
                {simulatedPhase === 'Finalizing'
                  ? 'Finalizing results...'
                  : `Iteration ${simulatedIteration}/${maxIterations} — ${simulatedPhase}...`}
              </p>
            </div>
            <p className="text-xs text-muted-foreground">
              This may take a few minutes. Please do not close this window.
            </p>
          </div>
        ) : isSuccess && data ? (
          /* ── Success / Blocked state ── */
          <>
            <QAResults result={data} />
            <div className="flex justify-end gap-2 pt-2">
              {data.final_status !== 'PASSED' && (
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => {
                    reset();
                    setSimulatedIteration(1);
                    setSimulatedPhase('Evaluating');
                  }}
                >
                  <RotateCcw className="h-4 w-4" />
                  Re-run QA
                </Button>
              )}
              <Button onClick={handleClose}>Close</Button>
            </div>
          </>
        ) : (
          /* ── Form state ── */
          <>
            <div className="space-y-4 py-2">
              <div className="space-y-2">
                <Label htmlFor="max-iterations">Maximum Iterations</Label>
                <Input
                  id="max-iterations"
                  type="number"
                  min={1}
                  max={10}
                  value={maxIterations}
                  onChange={handleIterationsChange}
                  className="w-28"
                />
                <p className="text-xs text-muted-foreground">
                  The system will evaluate and improve the draft up to{' '}
                  <strong>{maxIterations}</strong> time{maxIterations !== 1 ? 's' : ''}. Each
                  iteration scores the current draft and applies LLM-generated improvements.
                </p>
              </div>
            </div>

            {apiError && (
              <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <div className="flex-1 min-w-0 break-all">
                  {apiError}
                </div>
              </div>
            )}

            <DialogFooter>
              <Button variant="outline" onClick={handleClose}>
                Cancel
              </Button>
              <Button onClick={handleRun} className="gap-2">
                <Play className="h-4 w-4" />
                Run QA
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
