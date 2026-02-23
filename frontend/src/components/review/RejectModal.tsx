import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { AlertTriangle, XCircle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Textarea } from '@/components/ui/textarea';
import type { RejectDocumentRequest } from '@/types/document';

const schema = z.object({
  reviewer_name: z.string().min(1, 'Reviewer name is required'),
  rejection_reason: z.string().min(1, 'Rejection reason is required'),
  suggested_action: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

interface RejectModalProps {
  open: boolean;
  onClose: () => void;
  onReject: (data: RejectDocumentRequest) => void;
  isLoading: boolean;
}

export default function RejectModal({ open, onClose, onReject, isLoading }: RejectModalProps) {
  const [confirmed, setConfirmed] = useState(false);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const onSubmit = handleSubmit((data) => {
    if (!confirmed) {
      setConfirmed(true);
      return;
    }
    onReject({
      reviewer_name: data.reviewer_name,
      rejection_reason: data.rejection_reason,
      suggested_action: data.suggested_action || undefined,
    });
  });

  const handleClose = () => {
    reset();
    setConfirmed(false);
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <XCircle className="h-5 w-5 text-red-600" />
            Reject Document
          </DialogTitle>
          <DialogDescription>
            This will block the document and prevent it from being published.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="reject-reviewer-name">Reviewer Name *</Label>
            <Input
              id="reject-reviewer-name"
              placeholder="Your full name"
              {...register('reviewer_name')}
            />
            {errors.reviewer_name && (
              <p className="text-sm text-red-500">{errors.reviewer_name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="rejection-reason">Rejection Reason *</Label>
            <Textarea
              id="rejection-reason"
              placeholder="Explain why this document is being rejected..."
              rows={4}
              {...register('rejection_reason')}
            />
            {errors.rejection_reason && (
              <p className="text-sm text-red-500">{errors.rejection_reason.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="suggested-action">Suggested Action (optional)</Label>
            <Textarea
              id="suggested-action"
              placeholder="What should the author do to fix the document?"
              rows={2}
              {...register('suggested_action')}
            />
          </div>

          {confirmed && (
            <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
              <AlertTriangle className="h-4 w-4 text-red-600 mt-0.5 shrink-0" />
              <p className="text-sm text-red-700">
                <strong>Are you sure?</strong> This will block the document. Click{' '}
                <strong>Confirm Reject</strong> to proceed.
              </p>
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" variant="destructive" disabled={isLoading}>
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  Rejecting...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <XCircle className="h-4 w-4" />
                  {confirmed ? 'Confirm Reject' : 'Reject'}
                </span>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
