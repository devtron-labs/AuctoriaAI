import { Skeleton } from '@/components/ui/skeleton';

/**
 * Skeleton placeholder for document cards in the list view.
 * Pass `count` to render multiple cards at once.
 */
export function CardSkeleton({ count = 1 }: { count?: number }) {
  return (
    <>
      {Array.from({ length: count }).map((_, i) => (
        <div
          key={i}
          className="bg-white rounded-lg border border-gray-200 p-5 space-y-4"
          aria-hidden="true"
        >
          {/* Header row: avatar + title */}
          <div className="flex items-start gap-3">
            <Skeleton className="h-10 w-10 rounded-full shrink-0" />
            <div className="flex-1 space-y-2">
              <Skeleton className="h-4 w-3/4" />
              <Skeleton className="h-3 w-1/2" />
            </div>
          </div>

          {/* Metadata row */}
          <div className="flex gap-4">
            <Skeleton className="h-3 w-20" />
            <Skeleton className="h-3 w-24" />
            <Skeleton className="h-3 w-16" />
          </div>

          {/* Status badge */}
          <Skeleton className="h-5 w-24 rounded-full" />

          {/* Action buttons */}
          <div className="flex gap-2 pt-1">
            <Skeleton className="h-8 w-20 rounded-md" />
            <Skeleton className="h-8 w-20 rounded-md" />
          </div>
        </div>
      ))}
    </>
  );
}
