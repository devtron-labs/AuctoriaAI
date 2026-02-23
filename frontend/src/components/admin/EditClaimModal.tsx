import { useEffect } from 'react';
import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Pencil } from 'lucide-react';
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
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import type { Claim, UpdateClaimRequest } from '@/types/admin';

const schema = z.object({
  claim_text: z.string().min(1, 'Claim text is required'),
  claim_type: z.enum(['INTEGRATION', 'COMPLIANCE', 'PERFORMANCE']),
  expiry_date: z.string().optional(),
  approved_by: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

interface EditClaimModalProps {
  open: boolean;
  claim: Claim | null;
  onClose: () => void;
  onSave: (id: string, data: UpdateClaimRequest) => void;
  isLoading: boolean;
}

export default function EditClaimModal({
  open,
  claim,
  onClose,
  onSave,
  isLoading,
}: EditClaimModalProps) {
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  // Pre-fill form when claim changes
  useEffect(() => {
    if (claim) {
      reset({
        claim_text: claim.claim_text,
        claim_type: claim.claim_type,
        expiry_date: claim.expiry_date ?? '',
        approved_by: claim.approved_by ?? '',
      });
    }
  }, [claim, reset]);

  const onSubmit = handleSubmit((data) => {
    if (!claim) return;
    onSave(claim.id, {
      claim_text: data.claim_text,
      claim_type: data.claim_type,
      expiry_date: data.expiry_date || null,
      approved_by: data.approved_by || null,
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
            <Pencil className="h-5 w-5 text-primary" />
            Edit Claim
          </DialogTitle>
          <DialogDescription>
            Update the claim details in the registry.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="edit-claim-text">Claim Text *</Label>
            <Textarea
              id="edit-claim-text"
              placeholder="Enter the claim statement..."
              rows={3}
              {...register('claim_text')}
            />
            {errors.claim_text && (
              <p className="text-sm text-red-500">{errors.claim_text.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-claim-type">Claim Type *</Label>
            <Controller
              control={control}
              name="claim_type"
              render={({ field }) => (
                <Select onValueChange={field.onChange} value={field.value}>
                  <SelectTrigger id="edit-claim-type">
                    <SelectValue placeholder="Select type" />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="INTEGRATION">Integration</SelectItem>
                    <SelectItem value="COMPLIANCE">Compliance</SelectItem>
                    <SelectItem value="PERFORMANCE">Performance</SelectItem>
                  </SelectContent>
                </Select>
              )}
            />
            {errors.claim_type && (
              <p className="text-sm text-red-500">{errors.claim_type.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-expiry-date">Expiry Date (optional)</Label>
            <Input
              id="edit-expiry-date"
              type="date"
              {...register('expiry_date')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="edit-approved-by">Approved By (optional)</Label>
            <Input
              id="edit-approved-by"
              placeholder="Approver name"
              {...register('approved_by')}
            />
          </div>

          <DialogFooter className="pt-2">
            <Button type="button" variant="outline" onClick={handleClose} disabled={isLoading}>
              Cancel
            </Button>
            <Button type="submit" disabled={isLoading}>
              {isLoading ? (
                <span className="flex items-center gap-2">
                  <span className="animate-spin rounded-full h-4 w-4 border-b-2 border-white" />
                  Updating...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Pencil className="h-4 w-4" />
                  Update Claim
                </span>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
