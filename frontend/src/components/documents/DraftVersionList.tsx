import { Eye } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { formatDateTime } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { DraftVersion } from '@/types/document';

function scoreColor(score: number): string {
  if (score >= 7) return 'text-green-600 bg-green-50 border-green-200';
  if (score >= 4) return 'text-amber-600 bg-amber-50 border-amber-200';
  return 'text-red-600 bg-red-50 border-red-200';
}

interface DraftVersionListProps {
  drafts: DraftVersion[];
  selectedId: string | null;
  onSelect: (id: string) => void;
}

export default function DraftVersionList({ drafts, selectedId, onSelect }: DraftVersionListProps) {
  if (drafts.length === 0) {
    return null;
  }

  // Newest first
  const sorted = [...drafts].sort((a, b) => b.iteration_number - a.iteration_number);

  return (
    <ol className="relative border-l border-muted ml-3 space-y-0">
      {sorted.map((draft) => {
        const isSelected = draft.id === selectedId;

        return (
          <li key={draft.id} className="mb-5 ml-5">
            {/* Timeline dot */}
            <span
              className={cn(
                'absolute -left-2 flex h-4 w-4 items-center justify-center rounded-full border-2 border-background ring-2',
                isSelected ? 'bg-primary ring-primary/30' : 'bg-muted-foreground/40 ring-muted',
              )}
            />

            <div
              className={cn(
                'rounded-lg border p-3 transition-colors',
                isSelected ? 'border-primary bg-primary/5' : 'border-border bg-card',
              )}
            >
              <div className="flex items-center justify-between gap-2">
                <div className="flex items-center gap-2 min-w-0">
                  <span className="text-sm font-semibold text-foreground whitespace-nowrap">
                    Iteration #{draft.iteration_number}
                  </span>
                  {draft.score !== null ? (
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium',
                        scoreColor(draft.score),
                      )}
                    >
                      {draft.score.toFixed(1)}
                    </span>
                  ) : (
                    <span className="inline-flex items-center rounded-full border border-muted px-2 py-0.5 text-xs text-muted-foreground">
                      No score
                    </span>
                  )}
                </div>
                <Button
                  variant={isSelected ? 'default' : 'outline'}
                  size="sm"
                  className="gap-1.5 shrink-0"
                  onClick={() => onSelect(draft.id)}
                >
                  <Eye className="h-3.5 w-3.5" />
                  View
                </Button>
              </div>
              <time className="mt-1 block text-xs text-muted-foreground">
                {formatDateTime(draft.created_at)}
              </time>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
