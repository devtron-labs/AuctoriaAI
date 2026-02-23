import { useNavigate, Link } from 'react-router-dom';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { ArrowLeft } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { useCreateDocument } from '@/hooks';

// Backend DocumentCreate only accepts title — no content field
const schema = z.object({
  title: z.string().min(1, 'Title is required').max(512),
});

type FormValues = z.infer<typeof schema>;

export default function NewDocument() {
  const navigate = useNavigate();
  const { mutate: createDocument, isPending, error } = useCreateDocument();

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
  });

  const onSubmit = (data: FormValues) => {
    createDocument(data, {
      onSuccess: (doc) => {
        navigate(`/documents/${doc.id}`);
      },
    });
  };

  return (
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center gap-4">
        <Button variant="ghost" size="sm" asChild>
          <Link to="/documents">
            <ArrowLeft className="h-4 w-4" />
            Back
          </Link>
        </Button>
      </div>

      <div>
        <h1 className="text-2xl font-bold text-gray-900">New Document</h1>
        <p className="text-gray-500 text-sm mt-1">
          Create a new document for governance review. Upload a file and run the
          extraction pipeline after creation.
        </p>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Document Details</CardTitle>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit(onSubmit)} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="title">Title *</Label>
              <Input
                id="title"
                placeholder="Enter document title"
                {...register('title')}
              />
              {errors.title && (
                <p className="text-sm text-red-500">{errors.title.message}</p>
              )}
            </div>

            {error && (
              <p className="text-sm text-red-500">
                Failed to create document. Please try again.
              </p>
            )}

            <div className="flex gap-3 pt-2">
              <Button type="submit" disabled={isPending}>
                {isPending ? 'Creating...' : 'Create Document'}
              </Button>
              <Button variant="outline" asChild>
                <Link to="/documents">Cancel</Link>
              </Button>
            </div>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
