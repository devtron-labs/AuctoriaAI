import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { CheckCircle } from 'lucide-react';
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
import type { ApproveDocumentRequest } from '@/types/document';

const schema = z
  .object({
    reviewer_name: z.string().min(1, 'Reviewer name is required'),
    notes: z.string().optional(),
    force_approve: z.boolean(),
    override_reason: z.string().optional(),
  })
  .refine((d) => !d.force_approve || (d.override_reason && d.override_reason.length > 0), {
    message: 'Override reason is required when force approving',
    path: ['override_reason'],
  });

type FormValues = z.infer<typeof schema>;

interface ApproveModalProps {
  open: boolean;
  onClose: () => void;
  onApprove: (data: ApproveDocumentRequest) => void;
  isLoading: boolean;
  isAdmin?: boolean;
}

export default function ApproveModal({
  open,
  onClose,
  onApprove,
  isLoading,
  isAdmin = false,
}: ApproveModalProps) {
  const {
    register,
    handleSubmit,
    watch,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { force_approve: false },
  });

  const forceApprove = watch('force_approve');

  const onSubmit = handleSubmit((data) => {
    onApprove({
      reviewer_name: data.reviewer_name,
      notes: data.notes || undefined,
      force_approve: data.force_approve || undefined,
      override_reason: data.force_approve ? data.override_reason : undefined,
    });
  });

  const handleClose = () => {
    reset();
    onClose();
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && handleClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <CheckCircle className="h-5 w-5 text-green-600" />
            Approve Document
          </DialogTitle>
          <DialogDescription>
            This will mark the document as approved and make it available for publishing.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={onSubmit} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="approve-reviewer-name">Reviewer Name *</Label>
            <Input
              id="approve-reviewer-name"
              placeholder="Your full name"
              {...register('reviewer_name')}
            />
            {errors.reviewer_name && (
              <p className="text-sm text-red-500">{errors.reviewer_name.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="approve-notes">Notes (optional)</Label>
            <Textarea
              id="approve-notes"
              placeholder="Any additional notes or comments..."
              rows={3}
              {...register('notes')}
            />
          </div>

          {isAdmin && (
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 space-y-3">
              <label className="flex items-center gap-2 cursor-pointer select-none">
                <input
                  type="checkbox"
                  {...register('force_approve')}
                  className="h-4 w-4 rounded border-gray-300"
                />
                <span className="text-sm font-medium text-amber-800">
                  Force approve (override governance)
                </span>
              </label>
              {forceApprove && (
                <div className="space-y-2">
                  <Label htmlFor="override-reason" className="text-amber-800">
                    Override Reason *
                  </Label>
                  <Textarea
                    id="override-reason"
                    placeholder="Explain why you are overriding the governance check..."
                    rows={2}
                    {...register('override_reason')}
                  />
                  {errors.override_reason && (
                    <p className="text-sm text-red-500">{errors.override_reason.message}</p>
                  )}
                </div>
              )}
            </div>
          )}

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button
              type="submit"
              className="bg-green-600 hover:bg-green-700"
              disabled={isLoading}
            >
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  Approving...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <CheckCircle className="h-4 w-4" />
                  Approve
                </span>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
