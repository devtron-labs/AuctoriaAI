import ReactMarkdown from 'react-markdown';
import { FileText, FileDown, Loader2 } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import type { DraftVersion } from '@/types/document';
import { useDownloadDraft } from '@/hooks';

// ─── Rubric parsing ────────────────────────────────────────────────────────────

interface RubricScores {
  factual_correctness?: number;
  technical_depth?: number;
  clarity?: number;
  overall_feedback?: string;
}

function parseRubric(feedbackText: string | null): {
  rubric: RubricScores | null;
  plainText: string | null;
} {
  if (!feedbackText) return { rubric: null, plainText: null };
  try {
    const parsed: unknown = JSON.parse(feedbackText);
    if (parsed && typeof parsed === 'object') {
      return { rubric: parsed as RubricScores, plainText: null };
    }
  } catch {
    // not JSON
  }
  return { rubric: null, plainText: feedbackText };
}

// ─── Score helpers ─────────────────────────────────────────────────────────────

function scoreBarColor(score: number): string {
  if (score >= 7) return 'bg-green-500';
  if (score >= 4) return 'bg-amber-400';
  return 'bg-red-500';
}

function scoreTextColor(score: number): string {
  if (score >= 7) return 'text-green-600';
  if (score >= 4) return 'text-amber-600';
  return 'text-red-600';
}

// ─── Sub-components ────────────────────────────────────────────────────────────

function RubricBar({ label, score }: { label: string; score: number }) {
  const pct = Math.min(100, Math.max(0, (score / 10) * 100));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="text-muted-foreground">{label}</span>
        <span className={cn('font-semibold tabular-nums', scoreTextColor(score))}>
          {score.toFixed(1)}<span className="text-xs font-normal text-muted-foreground">/10</span>
        </span>
      </div>
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
        <div
          className={cn('h-full rounded-full transition-all duration-500', scoreBarColor(score))}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function ScoreCard({ draft }: { draft: DraftVersion }) {
  const { rubric, plainText } = parseRubric(draft.feedback_text);
  const score = draft.score ?? 0;
  const pct = Math.min(100, Math.max(0, (score / 10) * 100));

  const rubricItems: { label: string; key: keyof RubricScores }[] = [
    { label: 'Factual Correctness', key: 'factual_correctness' },
    { label: 'Technical Depth', key: 'technical_depth' },
    { label: 'Clarity', key: 'clarity' },
  ];

  const feedbackText = rubric?.overall_feedback ?? plainText;

  return (
    <Card>
      <CardHeader className="pb-2">
        <CardTitle className="text-base">Quality Score</CardTitle>
      </CardHeader>
      <CardContent className="space-y-5">
        {/* Composite score */}
        <div className="flex items-center gap-5">
          <div className="flex flex-col items-center justify-center">
            <span className={cn('text-5xl font-bold tabular-nums leading-none', scoreTextColor(score))}>
              {score.toFixed(1)}
            </span>
            <span className="mt-1 text-xs text-muted-foreground">out of 10</span>
          </div>
          <div className="flex-1 space-y-1">
            <div className="h-3 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={cn('h-full rounded-full transition-all duration-700', scoreBarColor(score))}
                style={{ width: `${pct}%` }}
              />
            </div>
            <p className="text-xs text-muted-foreground">Composite Score</p>
          </div>
        </div>

        {/* Rubric breakdown — shown only when feedback_text is a JSON rubric */}
        {rubric && (
          <div className="space-y-3 border-t pt-4">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Rubric Breakdown
            </p>
            {rubricItems.map(({ label, key }) => {
              const val = rubric[key];
              if (typeof val !== 'number') return null;
              return <RubricBar key={key} label={label} score={val} />;
            })}
          </div>
        )}

        {/* Feedback text */}
        {feedbackText && (
          <div className="rounded-md bg-muted/50 p-3 text-sm text-muted-foreground leading-relaxed border-t pt-4">
            <p className="mb-1 text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Feedback
            </p>
            {feedbackText}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ─── Markdown prose styles ─────────────────────────────────────────────────────

const markdownComponents: React.ComponentProps<typeof ReactMarkdown>['components'] = {
  h1: ({ children }) => (
    <h1 className="mt-6 mb-3 text-2xl font-bold tracking-tight text-foreground first:mt-0">
      {children}
    </h1>
  ),
  h2: ({ children }) => (
    <h2 className="mt-5 mb-2 text-xl font-semibold text-foreground">{children}</h2>
  ),
  h3: ({ children }) => (
    <h3 className="mt-4 mb-1.5 text-lg font-semibold text-foreground">{children}</h3>
  ),
  p: ({ children }) => (
    <p className="mb-4 leading-7 text-foreground last:mb-0">{children}</p>
  ),
  ul: ({ children }) => (
    <ul className="mb-4 ml-5 list-disc space-y-1 text-foreground">{children}</ul>
  ),
  ol: ({ children }) => (
    <ol className="mb-4 ml-5 list-decimal space-y-1 text-foreground">{children}</ol>
  ),
  li: ({ children }) => <li className="leading-7">{children}</li>,
  blockquote: ({ children }) => (
    <blockquote className="mb-4 border-l-4 border-primary/40 pl-4 italic text-muted-foreground">
      {children}
    </blockquote>
  ),
  hr: () => <hr className="my-6 border-border" />,
  strong: ({ children }) => <strong className="font-semibold text-foreground">{children}</strong>,
  em: ({ children }) => <em className="italic">{children}</em>,
  code: ({ className, children }) => {
    const isBlock = className?.startsWith('language-');
    if (isBlock) {
      return (
        <code className="block font-mono text-sm text-foreground">{children}</code>
      );
    }
    return (
      <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-sm text-foreground">
        {children}
      </code>
    );
  },
  pre: ({ children }) => (
    <pre className="mb-4 overflow-x-auto rounded-lg border bg-muted p-4 text-sm leading-6">
      {children}
    </pre>
  ),
  table: ({ children }) => (
    <div className="mb-4 overflow-x-auto">
      <table className="w-full border-collapse text-sm">{children}</table>
    </div>
  ),
  th: ({ children }) => (
    <th className="border border-border bg-muted px-3 py-2 text-left font-semibold">
      {children}
    </th>
  ),
  td: ({ children }) => (
    <td className="border border-border px-3 py-2">{children}</td>
  ),
};

// ─── Main component ────────────────────────────────────────────────────────────

interface DraftViewerProps {
  draft: DraftVersion;
}

export default function DraftViewer({ draft }: DraftViewerProps) {
  const { pdf, docx } = useDownloadDraft();

  return (
    <div className="space-y-4">
      {/* Score card — only when score exists */}
      {draft.score !== null && <ScoreCard draft={draft} />}

      {/* Markdown content */}
      <Card>
        <CardHeader className="pb-2">
          <div className="flex items-center justify-between gap-2">
            <CardTitle className="text-base">
              Draft — Iteration #{draft.iteration_number}
            </CardTitle>

            {/* Download actions */}
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={pdf.isPending}
                onClick={() => pdf.mutate(draft.id)}
                title="Download as PDF"
              >
                {pdf.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FileText className="h-3.5 w-3.5" />
                )}
                <span className="ml-1.5">PDF</span>
              </Button>

              <Button
                variant="outline"
                size="sm"
                disabled={docx.isPending}
                onClick={() => docx.mutate(draft.id)}
                title="Download as DOCX"
              >
                {docx.isPending ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <FileDown className="h-3.5 w-3.5" />
                )}
                <span className="ml-1.5">DOCX</span>
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="min-h-[200px]">
            <ReactMarkdown components={markdownComponents}>
              {draft.content_markdown}
            </ReactMarkdown>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
