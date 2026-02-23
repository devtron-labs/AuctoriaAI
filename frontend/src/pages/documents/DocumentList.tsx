import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Plus, FileText } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';
import StatusBadge from '@/components/shared/StatusBadge';
import CreateDocumentModal from '@/components/documents/CreateDocumentModal';
import { useDocuments } from '@/hooks';
import { formatDate } from '@/lib/utils';
import type { DocumentStatus } from '@/types/document';

type FilterStatus = 'ALL' | DocumentStatus;
type SortOrder = 'newest' | 'oldest' | 'title-asc' | 'title-desc';

export default function DocumentList() {
  const { data, isLoading, error } = useDocuments();
  const [filterStatus, setFilterStatus] = useState<FilterStatus>('ALL');
  const [sortOrder, setSortOrder] = useState<SortOrder>('newest');
  const [isModalOpen, setIsModalOpen] = useState(false);

  const filteredAndSorted = useMemo(() => {
    if (!data) return [];
    let result = [...data];

    if (filterStatus !== 'ALL') {
      result = result.filter((doc) => doc.status === filterStatus);
    }

    switch (sortOrder) {
      case 'newest':
        result.sort(
          (a, b) =>
            new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
        );
        break;
      case 'oldest':
        result.sort(
          (a, b) =>
            new Date(a.created_at).getTime() - new Date(b.created_at).getTime()
        );
        break;
      case 'title-asc':
        result.sort((a, b) => a.title.localeCompare(b.title));
        break;
      case 'title-desc':
        result.sort((a, b) => b.title.localeCompare(a.title));
        break;
    }

    return result;
  }, [data, filterStatus, sortOrder]);

  const totalCount = data?.length ?? 0;
  const filteredCount = filteredAndSorted.length;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-gray-900">Documents</h1>
          <p className="text-gray-500 text-sm mt-1">
            Manage and review your governance documents
          </p>
        </div>
        <Button onClick={() => setIsModalOpen(true)}>
          <Plus className="h-4 w-4" />
          Create Document
        </Button>
      </div>

      {/* Filters & Sorting */}
      {!isLoading && !error && totalCount > 0 && (
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500 whitespace-nowrap">Filter:</span>
            <Select
              value={filterStatus}
              onValueChange={(v) => setFilterStatus(v as FilterStatus)}
            >
              <SelectTrigger className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="ALL">All</SelectItem>
                <SelectItem value="DRAFT">Draft</SelectItem>
                <SelectItem value="VALIDATING">Validating</SelectItem>
                <SelectItem value="PASSED">Passed</SelectItem>
                <SelectItem value="HUMAN_REVIEW">Human Review</SelectItem>
                <SelectItem value="APPROVED">Approved</SelectItem>
                <SelectItem value="BLOCKED">Blocked</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <div className="flex items-center gap-2">
            <span className="text-sm text-gray-500 whitespace-nowrap">Sort:</span>
            <Select
              value={sortOrder}
              onValueChange={(v) => setSortOrder(v as SortOrder)}
            >
              <SelectTrigger className="w-44">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="newest">Newest First</SelectItem>
                <SelectItem value="oldest">Oldest First</SelectItem>
                <SelectItem value="title-asc">Title A–Z</SelectItem>
                <SelectItem value="title-desc">Title Z–A</SelectItem>
              </SelectContent>
            </Select>
          </div>

          <span className="text-sm text-gray-400 ml-auto">
            {filterStatus === 'ALL'
              ? `${totalCount} document${totalCount !== 1 ? 's' : ''}`
              : `${filteredCount} of ${totalCount} document${totalCount !== 1 ? 's' : ''}`}
          </span>
        </div>
      )}

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
              Failed to load documents. Please ensure the backend is running.
            </p>
          </CardContent>
        </Card>
      )}

      {/* Empty state — no documents at all */}
      {!isLoading && !error && totalCount === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-16">
            <FileText className="h-12 w-12 text-gray-300 mb-4" />
            <h3 className="text-lg font-medium text-gray-900">No documents yet</h3>
            <p className="text-gray-500 text-sm mt-1 text-center max-w-xs">
              Get started by creating your first governance document.
            </p>
            <Button className="mt-6" onClick={() => setIsModalOpen(true)}>
              <Plus className="h-4 w-4" />
              Create your first document
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Empty state — filter yields no results */}
      {!isLoading && !error && totalCount > 0 && filteredCount === 0 && (
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <FileText className="h-10 w-10 text-gray-300 mb-3" />
            <h3 className="text-base font-medium text-gray-900">
              No documents match this filter
            </h3>
            <p className="text-gray-500 text-sm mt-1">
              Try selecting a different status or clearing the filter.
            </p>
            <Button
              variant="outline"
              size="sm"
              className="mt-4"
              onClick={() => setFilterStatus('ALL')}
            >
              Clear filter
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Document grid */}
      {!isLoading && !error && filteredCount > 0 && (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {filteredAndSorted.map((doc) => (
            <Link key={doc.id} to={`/documents/${doc.id}`}>
              <Card className="h-full hover:shadow-md transition-shadow cursor-pointer">
                <CardHeader className="pb-2">
                  <div className="flex items-start justify-between gap-2">
                    <CardTitle className="text-sm font-semibold text-gray-900 leading-snug line-clamp-2">
                      {doc.title}
                    </CardTitle>
                    <StatusBadge status={doc.status} />
                  </div>
                </CardHeader>
                <CardContent>
                  <div className="flex flex-col gap-1 text-xs text-gray-500">
                    <span>Created {formatDate(doc.created_at)}</span>
                    <span>Updated {formatDate(doc.updated_at)}</span>
                  </div>
                </CardContent>
              </Card>
            </Link>
          ))}
        </div>
      )}

      <CreateDocumentModal open={isModalOpen} onOpenChange={setIsModalOpen} />
    </div>
  );
}
