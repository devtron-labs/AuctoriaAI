import { useCallback, useRef, useState } from 'react';
import { Upload, FileText, CheckCircle, AlertCircle, X, Sparkles } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import { useUploadFile, useExtractFactSheet } from '@/hooks';
import FactSheetViewer from './FactSheetViewer';
import type { Document, FactSheet } from '@/types/document';
import { cn } from '@/lib/utils';

const ALLOWED_TYPES: Record<string, string> = {
  'application/pdf': 'PDF',
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': 'DOCX',
  'text/plain': 'TXT',
};

const MAX_SIZE_BYTES = 50 * 1024 * 1024; // 50 MB

type Classification = 'INTERNAL' | 'CONFIDENTIAL' | 'PUBLIC';

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function validateFile(file: File): string | null {
  if (!Object.keys(ALLOWED_TYPES).includes(file.type)) {
    return 'Only PDF, DOCX, and TXT files are allowed.';
  }
  if (file.size > MAX_SIZE_BYTES) {
    return `File must be under 50 MB (current: ${formatBytes(file.size)}).`;
  }
  return null;
}

interface UploadTabProps {
  documentId: string;
  document: Document;
}

export default function UploadTab({ documentId, document }: UploadTabProps) {
  const [file, setFile] = useState<File | null>(null);
  const [classification, setClassification] = useState<Classification>('INTERNAL');
  const [validationError, setValidationError] = useState<string | null>(null);
  const [isDragging, setIsDragging] = useState(false);
  const [factSheet, setFactSheet] = useState<FactSheet | null>(null);

  const fileInputRef = useRef<HTMLInputElement>(null);

  const {
    mutate: upload,
    isPending: isUploading,
    isSuccess: uploadSuccess,
    error: uploadError,
    data: uploadedDoc,
    progress,
    reset: resetUpload,
  } = useUploadFile(documentId);

  const {
    mutate: extract,
    isPending: isExtracting,
    error: extractError,
  } = useExtractFactSheet(documentId);

  const pickFile = useCallback((picked: File) => {
    const err = validateFile(picked);
    setValidationError(err);
    if (!err) {
      setFile(picked);
      resetUpload();
      setFactSheet(null);
    }
  }, [resetUpload]);

  const handleDrop = useCallback(
    (e: React.DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setIsDragging(false);
      const dropped = e.dataTransfer.files[0];
      if (dropped) pickFile(dropped);
    },
    [pickFile],
  );

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragging(true);
  };

  const handleDragLeave = () => setIsDragging(false);

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const picked = e.target.files?.[0];
    if (picked) pickFile(picked);
    // Reset input so the same file can be re-selected after clearing
    e.target.value = '';
  };

  const clearFile = () => {
    setFile(null);
    setValidationError(null);
    resetUpload();
    setFactSheet(null);
  };

  const handleUpload = () => {
    if (!file) return;
    upload(
      { file, classification },
      {
        onSuccess: () => {
          // keep file info visible for success state
        },
      },
    );
  };

  const handleExtract = () => {
    extract(undefined, {
      onSuccess: (data) => setFactSheet(data),
    });
  };

  // Determine if the document already has a file from a previous upload
  const existingFile = document.file_path ?? null;

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle>Upload File</CardTitle>
          <CardDescription>
            Upload a PDF, DOCX, or TXT file (max 50 MB) and set its classification.
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-5">
          {/* Existing file notice */}
          {existingFile && !uploadSuccess && (
            <div className="flex items-center gap-2 rounded-md border border-blue-200 bg-blue-50 p-3 text-sm text-blue-700">
              <FileText className="h-4 w-4 shrink-0" />
              <span>
                Current file:{' '}
                <span className="font-medium font-mono">{existingFile.split('/').pop()}</span>
                {document.classification && (
                  <span className="ml-2 text-blue-500">({document.classification})</span>
                )}
              </span>
            </div>
          )}

          {/* Drop zone */}
          {!uploadSuccess && (
            <div
              role="button"
              tabIndex={0}
              onDrop={handleDrop}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => e.key === 'Enter' && fileInputRef.current?.click()}
              className={cn(
                'flex cursor-pointer flex-col items-center justify-center gap-3 rounded-lg border-2 border-dashed p-10 text-center transition-colors',
                isDragging
                  ? 'border-primary bg-primary/5'
                  : 'border-muted-foreground/25 hover:border-primary/50 hover:bg-muted/50',
                file && 'border-primary/50 bg-primary/5',
              )}
            >
              <Upload className="h-8 w-8 text-muted-foreground" />
              {file ? (
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" />
                  <span className="text-sm font-medium text-foreground">{file.name}</span>
                  <span className="text-xs text-muted-foreground">({formatBytes(file.size)})</span>
                </div>
              ) : (
                <>
                  <p className="text-sm font-medium">
                    Drag &amp; drop a file here, or{' '}
                    <span className="text-primary underline-offset-2 hover:underline">browse</span>
                  </p>
                  <p className="text-xs text-muted-foreground">PDF, DOCX, TXT &mdash; max 50 MB</p>
                </>
              )}
              <input
                ref={fileInputRef}
                type="file"
                accept=".pdf,.docx,.txt,application/pdf,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain"
                className="hidden"
                onChange={handleFileInput}
              />
            </div>
          )}

          {/* Validation error */}
          {validationError && (
            <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {validationError}
            </div>
          )}

          {/* Upload error */}
          {uploadError && (
            <div className="flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
              <AlertCircle className="h-4 w-4 shrink-0" />
              {(uploadError as { response?: { data?: { detail?: string } } })?.response?.data
                ?.detail ?? 'Upload failed. Please try again.'}
            </div>
          )}

          {/* Progress bar */}
          {isUploading && (
            <div className="space-y-1">
              <div className="flex justify-between text-xs text-muted-foreground">
                <span>Uploading…</span>
                <span>{progress}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-200"
                  style={{ width: `${progress}%` }}
                />
              </div>
            </div>
          )}

          {/* Success state */}
          {uploadSuccess && uploadedDoc && (
            <div className="rounded-md border border-green-200 bg-green-50 p-4 space-y-3">
              <div className="flex items-center gap-2 text-green-700">
                <CheckCircle className="h-5 w-5" />
                <span className="font-medium">File uploaded successfully</span>
              </div>
              <dl className="grid grid-cols-2 gap-x-6 gap-y-2 text-sm">
                <div>
                  <dt className="text-muted-foreground">Filename</dt>
                  <dd className="font-medium font-mono truncate">
                    {uploadedDoc.file_path?.split('/').pop() ?? file?.name ?? '—'}
                  </dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Size</dt>
                  <dd className="font-medium">{file ? formatBytes(file.size) : '—'}</dd>
                </div>
                <div>
                  <dt className="text-muted-foreground">Classification</dt>
                  <dd className="font-medium">{uploadedDoc.classification ?? classification}</dd>
                </div>
                {uploadedDoc.file_hash && (
                  <div className="col-span-2">
                    <dt className="text-muted-foreground">SHA-256 hash</dt>
                    <dd className="font-mono text-xs break-all mt-0.5">
                      {uploadedDoc.file_hash}
                    </dd>
                  </div>
                )}
              </dl>
              <Button variant="outline" size="sm" onClick={clearFile} className="gap-1.5">
                <X className="h-3.5 w-3.5" />
                Replace file
              </Button>
            </div>
          )}

          {/* Controls row */}
          {!uploadSuccess && (
            <div className="flex flex-wrap items-end gap-3">
              <div className="flex-1 min-w-[180px] space-y-1.5">
                <label className="text-sm font-medium">Classification</label>
                <Select
                  value={classification}
                  onValueChange={(v) => setClassification(v as Classification)}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="INTERNAL">Internal</SelectItem>
                    <SelectItem value="CONFIDENTIAL">Confidential</SelectItem>
                    <SelectItem value="PUBLIC">Public</SelectItem>
                  </SelectContent>
                </Select>
              </div>
              <Button
                onClick={handleUpload}
                disabled={!file || !!validationError || isUploading}
                className="gap-2"
              >
                <Upload className="h-4 w-4" />
                {isUploading ? 'Uploading…' : 'Upload'}
              </Button>
            </div>
          )}

          {/* Extract fact sheet button */}
          {(uploadSuccess || existingFile) && (
            <div className="border-t pt-4">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-sm font-medium">Fact Sheet Extraction</p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    Run AI extraction to generate structured data from the uploaded file.
                  </p>
                </div>
                <Button
                  variant="secondary"
                  onClick={handleExtract}
                  disabled={isExtracting}
                  className="gap-2"
                >
                  <Sparkles className="h-4 w-4" />
                  {isExtracting ? 'Extracting…' : 'Extract Fact Sheet'}
                </Button>
              </div>
              {extractError && (
                <div className="mt-3 flex items-center gap-2 rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700">
                  <AlertCircle className="h-4 w-4 shrink-0" />
                  {(extractError as { response?: { data?: { detail?: string } } })?.response?.data
                    ?.detail ?? 'Extraction failed. Please try again.'}
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Fact sheet display */}
      {(isExtracting || factSheet) && (
        <FactSheetViewer factSheet={factSheet} isLoading={isExtracting} />
      )}
    </div>
  );
}
