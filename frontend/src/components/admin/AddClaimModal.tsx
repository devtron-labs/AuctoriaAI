import { useForm, Controller } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { Plus } from 'lucide-react';
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
import type { CreateClaimRequest } from '@/types/admin';

const schema = z.object({
  claim_text: z.string().min(1, 'Claim text is required'),
  claim_type: z.enum(['INTEGRATION', 'COMPLIANCE', 'PERFORMANCE']),
  expiry_date: z.string().optional(),
  approved_by: z.string().optional(),
});

type FormValues = z.infer<typeof schema>;

interface AddClaimModalProps {
  open: boolean;
  onClose: () => void;
  onSave: (data: CreateClaimRequest) => void;
  isLoading: boolean;
}

export default function AddClaimModal({
  open,
  onClose,
  onSave,
  isLoading,
}: AddClaimModalProps) {
  const {
    register,
    handleSubmit,
    control,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: { claim_type: 'INTEGRATION' },
  });

  const onSubmit = handleSubmit((data) => {
    onSave({
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
            <Plus className="h-5 w-5 text-primary" />
            Add Claim
          </DialogTitle>
          <DialogDescription>
            Add a new claim to the registry for validation use.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={(e) => void onSubmit(e)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="add-claim-text">Claim Text *</Label>
            <Textarea
              id="add-claim-text"
              placeholder="Enter the claim statement..."
              rows={3}
              {...register('claim_text')}
            />
            {errors.claim_text && (
              <p className="text-sm text-red-500">{errors.claim_text.message}</p>
            )}
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-claim-type">Claim Type *</Label>
            <Controller
              control={control}
              name="claim_type"
              render={({ field }) => (
                <Select onValueChange={field.onChange} value={field.value}>
                  <SelectTrigger id="add-claim-type">
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
            <Label htmlFor="add-expiry-date">Expiry Date (optional)</Label>
            <Input
              id="add-expiry-date"
              type="date"
              {...register('expiry_date')}
            />
          </div>

          <div className="space-y-2">
            <Label htmlFor="add-approved-by">Approved By (optional)</Label>
            <Input
              id="add-approved-by"
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
                  Saving...
                </span>
              ) : (
                <span className="flex items-center gap-2">
                  <Plus className="h-4 w-4" />
                  Save Claim
                </span>
              )}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
