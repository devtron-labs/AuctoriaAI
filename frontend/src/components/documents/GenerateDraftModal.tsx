import { useState } from 'react';
import { Wand2, CheckCircle, AlertCircle, Loader2, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { useGenerateDraft } from '@/hooks';
import type { DocumentType } from '@/types/document';

const DOCUMENT_TYPES: { value: DocumentType; label: string; description: string }[] = [
  {
    value: 'whitepaper',
    label: 'Whitepaper',
    description: 'Comprehensive enterprise whitepaper with executive summary and deep technical analysis',
  },
  {
    value: 'blog',
    label: 'Blog Post',
    description: 'Engaging tech blog post with a compelling hook and key takeaways',
  },
  {
    value: 'technical_doc',
    label: 'Technical Documentation',
    description: 'Official product docs with architecture, setup, API reference and examples',
  },
  {
    value: 'case_study',
    label: 'Case Study',
    description: 'Customer story with challenge, solution, and measurable results',
  },
  {
    value: 'product_brief',
    label: 'Product Brief',
    description: 'Concise product brief covering features, specs, and use cases',
  },
  {
    value: 'research_report',
    label: 'Research Report',
    description: 'Data-driven analytical report with findings and recommendations',
  },
];

interface GenerateDraftModalProps {
  documentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function GenerateDraftModal({
  documentId,
  open,
  onOpenChange,
}: GenerateDraftModalProps) {
  const [prompt, setPrompt] = useState('');
  const [documentType, setDocumentType] = useState<DocumentType>('whitepaper');

  const { mutate: generate, isPending, isSuccess, error, reset, progress, currentStage } = useGenerateDraft(documentId);

  const handleGenerate = () => {
    if (!prompt.trim()) return;
    generate({ prompt: prompt.trim(), document_type: documentType });
  };

  const handleClose = () => {
    onOpenChange(false);
    // Reset state after dialog close transition finishes
    setTimeout(() => {
      reset();
      setPrompt('');
      setDocumentType('whitepaper');
    }, 200);
  };

  // Safely extract a human-readable error string — never render a raw object.
  const apiError = (() => {
    if (!error) return null;
    const axiosDetail = (
      error as { response?: { data?: { detail?: unknown } } }
    )?.response?.data?.detail;

    if (typeof axiosDetail === 'string') return axiosDetail;

    if (axiosDetail && typeof axiosDetail === 'object') {
      const d = axiosDetail as Record<string, unknown>;
      if (typeof d['message'] === 'string') return d['message'];
      return JSON.stringify(d);
    }

    return error.message ?? 'An unexpected error occurred.';
  })();

  const canGenerate = prompt.trim().length > 0 && !isPending;
  const selectedType = DOCUMENT_TYPES.find((t) => t.value === documentType);

  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <Wand2 className="h-5 w-5 text-primary" />
            Generate Draft
          </DialogTitle>
          <DialogDescription>
            Choose a document type and describe what you want to create. The AI will build the
            draft around your prompt. The current document (if it has content) will be used as
            optional supporting context.
          </DialogDescription>
        </DialogHeader>

        {isPending ? (
          /* Progress panel — shown while background generation is in flight */
          <div className="flex flex-col items-center gap-4 py-6 text-center">
            <Loader2 className="h-10 w-10 animate-spin text-primary" />
            <div className="space-y-1">
              <p className="font-medium text-foreground">Generating draft…</p>
              <p className="text-sm text-muted-foreground">
                {currentStage === 'DRAFT_GENERATING'
                  ? 'The AI is writing your draft. This may take a moment.'
                  : 'Starting generation…'}
              </p>
            </div>
            {progress > 0 && (
              <div className="w-full space-y-1.5">
                <div className="flex justify-between text-xs text-muted-foreground">
                  <span>Progress</span>
                  <span>{progress}%</span>
                </div>
                <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                  <div
                    className="h-2 rounded-full bg-primary transition-all duration-500"
                    style={{ width: `${progress}%` }}
                  />
                </div>
              </div>
            )}
            <p className="text-xs text-muted-foreground">
              Generation runs within your configured timeout and retry limits
              (Admin → System Settings).
            </p>
          </div>
        ) : isSuccess ? (
          <div className="flex flex-col items-center gap-3 py-6 text-center">
            <CheckCircle className="h-10 w-10 text-green-500" />
            <p className="font-medium text-foreground">Draft generated successfully!</p>
            <p className="text-sm text-muted-foreground">
              The new iteration has been added to the drafts list.
            </p>
            <Button onClick={handleClose} className="mt-2">
              Close
            </Button>
          </div>
        ) : (
          <>
            <div className="space-y-4 py-2">
              {/* Document type selector */}
              <div className="space-y-1.5">
                <label
                  htmlFor="document-type"
                  className="text-sm font-medium text-foreground"
                >
                  Document type{' '}
                  <span className="text-red-500" aria-hidden="true">
                    *
                  </span>
                </label>
                <select
                  id="document-type"
                  value={documentType}
                  onChange={(e) => setDocumentType(e.target.value as DocumentType)}
                  disabled={isPending}
                  className="w-full rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {DOCUMENT_TYPES.map((t) => (
                    <option key={t.value} value={t.value}>
                      {t.label}
                    </option>
                  ))}
                </select>
                {selectedType && (
                  <p className="text-xs text-muted-foreground">{selectedType.description}</p>
                )}
              </div>

              {/* Prompt textarea */}
              <div className="space-y-1.5">
                <label
                  htmlFor="draft-prompt"
                  className="text-sm font-medium text-foreground"
                >
                  Your request{' '}
                  <span className="text-red-500" aria-hidden="true">
                    *
                  </span>
                </label>
                <textarea
                  id="draft-prompt"
                  value={prompt}
                  onChange={(e) => setPrompt(e.target.value)}
                  disabled={isPending}
                  placeholder="e.g. Write a technical whitepaper covering our product's compliance posture, integration capabilities, and key performance metrics. Focus on enterprise buyers."
                  rows={5}
                  className="w-full resize-none rounded-md border border-input bg-background px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring disabled:cursor-not-allowed disabled:opacity-50"
                />
                <p className="text-xs text-muted-foreground">
                  {prompt.trim().length === 0
                    ? 'Prompt is required to generate a draft.'
                    : `${prompt.trim().length} characters`}
                </p>
              </div>

              {/* Document context hint */}
              {documentId && (
                <div className="flex items-start gap-2 rounded-md border border-border bg-muted/40 p-3 text-xs text-muted-foreground">
                  <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0" />
                  <span>
                    The current document will be used as optional supporting context. If it has no
                    uploaded content or fact sheet, your prompt alone drives the output.
                  </span>
                </div>
              )}
            </div>

            {/* Error display — always a string, never an object */}
            {apiError && (
              <div className="flex items-start gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                <AlertCircle className="mt-0.5 h-4 w-4 shrink-0" />
                <span>{apiError}</span>
              </div>
            )}

            <DialogFooter>
              <Button variant="outline" onClick={handleClose} disabled={isPending}>
                Cancel
              </Button>
              <Button
                onClick={handleGenerate}
                disabled={!canGenerate}
                className="gap-2"
              >
                <Wand2 className="h-4 w-4" />
                Generate
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
