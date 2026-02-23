import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { CheckCircle2, Star, XCircle } from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import StatusBadge from '@/components/shared/StatusBadge';
import ApproveModal from './ApproveModal';
import RejectModal from './RejectModal';
import { useToast } from '@/providers/ToastProvider';
import { useApproveDocument, useRejectDocument } from '@/hooks';
import { formatDate } from '@/lib/utils';
import type { ReviewDetails } from '@/types/review';
import type { ApproveDocumentRequest, RejectDocumentRequest } from '@/types/document';

// Hardcoded for now — will be replaced by auth context
const IS_ADMIN = true;

interface DecisionPanelProps {
  reviewDetails: ReviewDetails;
}

export default function DecisionPanel({ reviewDetails }: DecisionPanelProps) {
  const [approveOpen, setApproveOpen] = useState(false);
  const [rejectOpen, setRejectOpen] = useState(false);
  const navigate = useNavigate();
  const { toast } = useToast();

  const { document, latest_draft, validation_report } = reviewDetails;
  const approve = useApproveDocument(document.id);
  const reject = useRejectDocument(document.id);

  const score = latest_draft?.score ?? null;
  const claimsValid = validation_report?.is_valid ?? null;
  const iterations = document.draft_versions?.length ?? 0;
  const daysInReview = Math.floor(
    (Date.now() - new Date(document.created_at).getTime()) / (1000 * 60 * 60 * 24),
  );

  const handleApprove = (data: ApproveDocumentRequest) => {
    approve.mutate(data, {
      onSuccess: () => {
        toast('Document approved successfully', 'success');
        setApproveOpen(false);
        navigate('/review');
      },
      onError: () => {
        toast('Failed to approve document. Please try again.', 'error');
      },
    });
  };

  const handleReject = (data: RejectDocumentRequest) => {
    reject.mutate(data, {
      onSuccess: () => {
        toast('Document rejected', 'info');
        setRejectOpen(false);
        navigate('/review');
      },
      onError: () => {
        toast('Failed to reject document. Please try again.', 'error');
      },
    });
  };

  const anyPending = approve.isPending || reject.isPending;

  return (
    <>
      <div className="space-y-4">
        {/* Document Summary */}
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
              Document Info
            </CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            <div>
              <p className="font-semibold text-gray-900 text-sm leading-snug">{document.title}</p>
              <div className="mt-2">
                <StatusBadge status={document.status} />
              </div>
            </div>

            {/* Score display */}
            {score !== null && (
              <div className="text-center py-3 border rounded-lg bg-gray-50">
                <div className="flex items-center justify-center gap-2 mb-1">
                  <Star
                    className={`h-5 w-5 ${score >= 9 ? 'text-green-500' : 'text-amber-500'}`}
                  />
                  <span
                    className={`text-3xl font-bold ${
                      score >= 9 ? 'text-green-600' : 'text-amber-600'
                    }`}
                  >
                    {score.toFixed(1)}
                  </span>
                  <span className="text-gray-400 text-sm self-end pb-1">/10</span>
                </div>
                <Badge variant={score >= 9 ? 'success' : 'warning'} className="text-xs">
                  {score >= 9 ? 'High quality' : 'Below threshold'}
                </Badge>
              </div>
            )}

            {/* Claims validity */}
            <div className="text-sm">
              {claimsValid === true && (
                <span className="flex items-center gap-1.5 text-green-600 font-medium">
                  <CheckCircle2 className="h-4 w-4" />
                  All claims valid
                </span>
              )}
              {claimsValid === false && (
                <span className="flex items-center gap-1.5 text-red-600 font-medium">
                  <XCircle className="h-4 w-4" />
                  Invalid claims detected
                </span>
              )}
              {claimsValid === null && (
                <span className="text-gray-400">Claims not validated</span>
              )}
            </div>
          </CardContent>
        </Card>

        {/* Quick Stats */}
        <Card>
          <CardContent className="pt-4">
            <dl className="grid grid-cols-3 gap-2 text-center">
              <div className="rounded-md bg-gray-50 p-2">
                <dt className="text-xs text-gray-500 font-medium">Iterations</dt>
                <dd className="text-xl font-bold text-gray-900 mt-0.5">{iterations}</dd>
              </div>
              <div className="rounded-md bg-gray-50 p-2">
                <dt className="text-xs text-gray-500 font-medium">Days in Review</dt>
                <dd
                  className={`text-xl font-bold mt-0.5 ${
                    daysInReview > 7 ? 'text-red-600' : 'text-gray-900'
                  }`}
                >
                  {daysInReview}
                </dd>
              </div>
              <div className="rounded-md bg-gray-50 p-2">
                <dt className="text-xs text-gray-500 font-medium">Created</dt>
                <dd className="text-xs font-semibold text-gray-700 mt-1">
                  {formatDate(document.created_at)}
                </dd>
              </div>
            </dl>
          </CardContent>
        </Card>

        {/* Decision Buttons */}
        <Card>
          <CardContent className="pt-4 space-y-3">
            <p className="text-sm font-semibold text-gray-700">Make a decision</p>
            <Button
              className="w-full bg-green-600 hover:bg-green-700 text-white"
              size="lg"
              onClick={() => setApproveOpen(true)}
              disabled={anyPending}
            >
              <CheckCircle2 className="h-4 w-4" />
              Approve Document
            </Button>
            <Button
              variant="destructive"
              className="w-full"
              size="lg"
              onClick={() => setRejectOpen(true)}
              disabled={anyPending}
            >
              <XCircle className="h-4 w-4" />
              Reject Document
            </Button>
          </CardContent>
        </Card>
      </div>

      <ApproveModal
        open={approveOpen}
        onClose={() => setApproveOpen(false)}
        onApprove={handleApprove}
        isLoading={approve.isPending}
        isAdmin={IS_ADMIN}
      />
      <RejectModal
        open={rejectOpen}
        onClose={() => setRejectOpen(false)}
        onReject={handleReject}
        isLoading={reject.isPending}
      />
    </>
  );
}
