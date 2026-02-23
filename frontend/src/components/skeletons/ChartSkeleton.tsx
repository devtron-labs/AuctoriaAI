import { Skeleton } from '@/components/ui/skeleton';

/**
 * Skeleton placeholder for analytics charts (bar/line).
 */
export function ChartSkeleton() {
  return (
    <div className="space-y-3" aria-hidden="true">
      {/* Chart title */}
      <Skeleton className="h-5 w-40" />

      {/* Chart area */}
      <div className="border border-gray-200 rounded-lg p-4">
        {/* Y-axis labels + bars */}
        <div className="flex items-end gap-3 h-48">
          {/* Y-axis */}
          <div className="flex flex-col justify-between h-full pb-4 shrink-0 space-y-2">
            {Array.from({ length: 5 }).map((_, i) => (
              <Skeleton key={i} className="h-3 w-8" />
            ))}
          </div>

          {/* Bars */}
          <div className="flex-1 flex items-end gap-2 h-full">
            {Array.from({ length: 7 }).map((_, i) => {
              const heights = ['h-24', 'h-32', 'h-20', 'h-40', 'h-28', 'h-36', 'h-16'];
              return (
                <div key={i} className="flex-1 flex flex-col justify-end">
                  <Skeleton className={`w-full ${heights[i % heights.length]} rounded-t`} />
                </div>
              );
            })}
          </div>
        </div>

        {/* X-axis labels */}
        <div className="flex gap-2 mt-2 ml-10">
          {Array.from({ length: 7 }).map((_, i) => (
            <Skeleton key={i} className="flex-1 h-3" />
          ))}
        </div>
      </div>
    </div>
  );
}
