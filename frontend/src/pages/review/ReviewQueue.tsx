import { useState } from 'react';
import { ClipboardList } from 'lucide-react';
import { Card, CardContent } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import ReviewCard from '@/components/review/ReviewCard';
import { useReviewQueue } from '@/hooks';
import type { PendingReviewItem } from '@/types/document';

type SortOrder = 'oldest' | 'newest';

const PAGE_SIZE = 20;

function sortItems(items: PendingReviewItem[], order: SortOrder): PendingReviewItem[] {
  return [...items].sort((a, b) => {
    const diff = new Date(a.created_at).getTime() - new Date(b.created_at).getTime();
    return order === 'oldest' ? diff : -diff;
  });
}

export default function ReviewQueue() {
  const [page, setPage] = useState(1);
  const [sort, setSort] = useState<SortOrder>('oldest');

  const { data, isLoading, error } = useReviewQueue(page, PAGE_SIZE);

  const items = data?.documents ?? [];
  const total = data?.total ?? 0;
  const hasNext = data ? page * PAGE_SIZE < total : false;
  const hasPrev = page > 1;

  const sortedItems = sortItems(items, sort);

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Pending Reviews</h1>
          <div className="mt-2">
            {total > 0 ? (
              <Badge variant="orange">
                {total} document{total !== 1 ? 's' : ''} awaiting review
              </Badge>
            ) : (
              !isLoading && <p className="text-sm text-gray-500">No documents awaiting review</p>
            )}
          </div>
        </div>

        {/* Sort controls */}
        {items.length > 0 && (
          <div className="flex items-center gap-1 rounded-lg border border-gray-200 p-1 shrink-0">
            <Button
              variant={sort === 'oldest' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setSort('oldest')}
            >
              Oldest First
            </Button>
            <Button
              variant={sort === 'newest' ? 'default' : 'ghost'}
              size="sm"
              onClick={() => setSort('newest')}
            >
              Newest First
            </Button>
          </div>
        )}
      </div>

      {/* Loading */}
      {isLoading && (
        <div className="flex items-center justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      )}

      {/* Error */}
      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-600 text-sm">
              Failed to load review queue. Please ensure the backend is running.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Empty state */}
      {!isLoading && !error && items.length === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <ClipboardList className="h-12 w-12 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-900">Queue is empty</h3>
            <p className="text-gray-500 text-sm mt-1">No documents are pending review.</p>
          </CardContent>
        </Card>
      )}

      {/* Document grid */}
      {!isLoading && !error && sortedItems.length > 0 && (
        <>
          <div className="grid grid-cols-1 gap-4">
            {sortedItems.map((item) => (
              <ReviewCard key={item.id} item={item} />
            ))}
          </div>

          {/* Pagination */}
          {(hasPrev || hasNext) && (
            <div className="flex items-center justify-center gap-4 pt-2">
              <Button
                variant="outline"
                size="sm"
                disabled={!hasPrev}
                onClick={() => setPage((p) => p - 1)}
              >
                Previous
              </Button>
              <span className="text-sm text-gray-500">
                Page {page} · {total} total
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={!hasNext}
                onClick={() => setPage((p) => p + 1)}
              >
                Next
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
