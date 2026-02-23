import { useNavigate } from 'react-router-dom';
import { Clock, CheckCircle2, XCircle, ArrowRight } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import StatusBadge from '@/components/shared/StatusBadge';
import { truncate, formatDate } from '@/lib/utils';
import type { PendingReviewItem } from '@/types/document';

interface ReviewCardProps {
  item: PendingReviewItem;
}

export default function ReviewCard({ item }: ReviewCardProps) {
  const navigate = useNavigate();

  const scoreVariant = item.score !== null && item.score >= 9 ? 'success' : 'warning';

  return (
    <Card className="hover:shadow-md transition-shadow">
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-4">
          <CardTitle className="text-base font-semibold text-gray-900 leading-snug">
            {item.title}
          </CardTitle>
          <StatusBadge status={item.status} />
        </div>
      </CardHeader>

      <CardContent className="space-y-3">
        {item.draft_preview && (
          <p className="text-sm text-gray-600 leading-relaxed">
            {truncate(item.draft_preview, 150)}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3 text-sm">
          {item.score !== null && (
            <Badge variant={scoreVariant}>Score: {item.score.toFixed(1)}</Badge>
          )}

          {item.claims_valid === true && (
            <span className="flex items-center gap-1 text-green-600 font-medium">
              <CheckCircle2 className="h-4 w-4" />
              Claims Valid
            </span>
          )}
          {item.claims_valid === false && (
            <span className="flex items-center gap-1 text-red-600 font-medium">
              <XCircle className="h-4 w-4" />
              Claims Invalid
            </span>
          )}
          {item.claims_valid === null && (
            <span className="text-gray-400">Claims: —</span>
          )}

          <span
            className={`flex items-center gap-1 ${
              item.days_in_review > 7 ? 'text-red-600 font-medium' : 'text-gray-500'
            }`}
          >
            <Clock className="h-4 w-4" />
            {item.days_in_review}d in review
            {item.days_in_review > 7 && ' ⚠'}
          </span>
        </div>

        <div className="flex items-center justify-between pt-1">
          <span className="text-xs text-gray-400">Submitted {formatDate(item.created_at)}</span>
          <Button size="sm" onClick={() => navigate(`/review/${item.id}`)}>
            Review
            <ArrowRight className="h-4 w-4" />
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
