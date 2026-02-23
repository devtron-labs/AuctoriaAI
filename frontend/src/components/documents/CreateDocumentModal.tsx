import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useCreateDocument } from '@/hooks';

const schema = z.object({
  title: z
    .string()
    .min(1, 'Title is required')
    .max(512, 'Title must be 512 characters or fewer'),
});

type FormValues = z.infer<typeof schema>;

interface CreateDocumentModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
}

export default function CreateDocumentModal({
  open,
  onOpenChange,
}: CreateDocumentModalProps) {
  const navigate = useNavigate();
  const { mutate: createDocument, isPending } = useCreateDocument();
  const [serverError, setServerError] = useState<string | null>(null);

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const handleOpenChange = (nextOpen: boolean) => {
    if (!isPending) {
      onOpenChange(nextOpen);
      if (!nextOpen) {
        reset();
        setServerError(null);
      }
    }
  };

  const onSubmit = (data: FormValues) => {
    setServerError(null);
    createDocument(data, {
      onSuccess: (doc) => {
        onOpenChange(false);
        reset();
        navigate(`/documents/${doc.id}`);
      },
      onError: () => {
        setServerError('Failed to create document. Please try again.');
      },
    });
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Create Document</DialogTitle>
          <DialogDescription>
            Enter a title for your new governance document.
          </DialogDescription>
        </DialogHeader>

        <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="modal-title">Title *</Label>
            <Input
              id="modal-title"
              placeholder="Enter document title"
              autoFocus
              {...register('title')}
            />
            {errors.title && (
              <p className="text-sm text-red-500">{errors.title.message}</p>
            )}
          </div>

          {serverError && (
            <p className="text-sm text-red-500">{serverError}</p>
          )}

          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={() => handleOpenChange(false)}
              disabled={isPending}
            >
              Cancel
            </Button>
            <Button type="submit" disabled={isPending}>
              {isPending ? 'Creating...' : 'Create Document'}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
