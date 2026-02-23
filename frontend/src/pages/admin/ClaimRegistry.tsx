import { useState, useMemo } from 'react';
import { Search, Plus, Pencil, Trash2, ChevronUp, ChevronDown } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent } from '@/components/ui/card';
import AddClaimModal from '@/components/admin/AddClaimModal';
import EditClaimModal from '@/components/admin/EditClaimModal';
import { useClaims, useCreateClaim, useUpdateClaim, useDeleteClaim } from '@/hooks';
import { useToast } from '@/providers/ToastProvider';
import { formatDate } from '@/lib/utils';
import { cn } from '@/lib/utils';
import type { Claim, ClaimType, CreateClaimRequest, UpdateClaimRequest } from '@/types/admin';

type FilterTab = 'ALL' | ClaimType;
type SortField = 'claim_type' | 'expiry_date' | 'created_at';
type SortDir = 'asc' | 'desc';

const CLAIM_TYPE_LABELS: Record<ClaimType, string> = {
  INTEGRATION: 'Integration',
  COMPLIANCE: 'Compliance',
  PERFORMANCE: 'Performance',
};

const CLAIM_TYPE_BADGE: Record<ClaimType, string> = {
  INTEGRATION: 'bg-blue-100 text-blue-700',
  COMPLIANCE: 'bg-green-100 text-green-700',
  PERFORMANCE: 'bg-orange-100 text-orange-700',
};

function isExpired(expiryDate: string | null): boolean {
  if (!expiryDate) return false;
  return new Date(expiryDate) < new Date();
}

interface SortButtonProps {
  field: SortField;
  label: string;
  current: SortField;
  dir: SortDir;
  onClick: (f: SortField) => void;
}

function SortButton({ field, label, current, dir, onClick }: SortButtonProps) {
  const active = current === field;
  return (
    <button
      onClick={() => onClick(field)}
      className="flex items-center gap-1 text-xs font-semibold text-gray-500 uppercase tracking-wider hover:text-gray-900 transition-colors"
    >
      {label}
      {active ? (
        dir === 'asc' ? (
          <ChevronUp className="h-3.5 w-3.5" />
        ) : (
          <ChevronDown className="h-3.5 w-3.5" />
        )
      ) : (
        <ChevronDown className="h-3.5 w-3.5 opacity-30" />
      )}
    </button>
  );
}

export default function ClaimRegistry() {
  const { toast } = useToast();
  const { data: claims = [], isLoading, error } = useClaims();
  const createClaim = useCreateClaim();
  const updateClaim = useUpdateClaim();
  const deleteClaim = useDeleteClaim();

  const [filter, setFilter] = useState<FilterTab>('ALL');
  const [search, setSearch] = useState('');
  const [sortField, setSortField] = useState<SortField>('created_at');
  const [sortDir, setSortDir] = useState<SortDir>('desc');
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [editingClaim, setEditingClaim] = useState<Claim | null>(null);

  const handleSort = (field: SortField) => {
    if (sortField === field) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortField(field);
      setSortDir('asc');
    }
  };

  const filteredClaims = useMemo(() => {
    let result = claims;

    if (filter !== 'ALL') {
      result = result.filter((c) => c.claim_type === filter);
    }

    if (search.trim()) {
      const q = search.toLowerCase();
      result = result.filter(
        (c) =>
          c.claim_text.toLowerCase().includes(q) ||
          c.claim_type.toLowerCase().includes(q) ||
          (c.approved_by ?? '').toLowerCase().includes(q),
      );
    }

    return [...result].sort((a, b) => {
      let valA: string;
      let valB: string;
      if (sortField === 'claim_type') {
        valA = a.claim_type;
        valB = b.claim_type;
      } else if (sortField === 'expiry_date') {
        valA = a.expiry_date ?? '';
        valB = b.expiry_date ?? '';
      } else {
        valA = a.created_at;
        valB = b.created_at;
      }
      const cmp = valA.localeCompare(valB);
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [claims, filter, search, sortField, sortDir]);

  const handleCreate = (data: CreateClaimRequest) => {
    createClaim.mutate(data, {
      onSuccess: () => {
        toast('Claim created successfully', 'success');
        setAddModalOpen(false);
      },
      onError: () => toast('Failed to create claim', 'error'),
    });
  };

  const handleUpdate = (id: string, data: UpdateClaimRequest) => {
    updateClaim.mutate(
      { id, data },
      {
        onSuccess: () => {
          toast('Claim updated successfully', 'success');
          setEditingClaim(null);
        },
        onError: () => toast('Failed to update claim', 'error'),
      },
    );
  };

  const handleDelete = (claim: Claim) => {
    if (!window.confirm(`Delete this ${CLAIM_TYPE_LABELS[claim.claim_type]} claim?`)) return;
    deleteClaim.mutate(claim.id, {
      onSuccess: () => toast('Claim deleted', 'success'),
      onError: () => toast('Failed to delete claim', 'error'),
    });
  };

  const filterTabs: FilterTab[] = ['ALL', 'INTEGRATION', 'COMPLIANCE', 'PERFORMANCE'];
  const filterLabels: Record<FilterTab, string> = {
    ALL: 'All',
    INTEGRATION: 'Integration',
    COMPLIANCE: 'Compliance',
    PERFORMANCE: 'Performance',
  };

  return (
    <div className="space-y-4">
      {/* Header row */}
      <div className="flex items-center justify-between">
        <div className="relative flex-1 max-w-sm">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-gray-400" />
          <Input
            placeholder="Search claims..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="pl-9"
          />
        </div>
        <Button size="sm" onClick={() => setAddModalOpen(true)}>
          <Plus className="h-4 w-4 mr-1" />
          Add Claim
        </Button>
      </div>

      {/* Filter tabs */}
      <div className="flex border-b border-gray-200">
        {filterTabs.map((tab) => (
          <button
            key={tab}
            onClick={() => setFilter(tab)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              filter === tab
                ? 'border-primary text-primary'
                : 'border-transparent text-gray-500 hover:text-gray-700',
            )}
          >
            {filterLabels[tab]}
            {tab !== 'ALL' && (
              <span className="ml-1.5 text-xs text-gray-400">
                ({claims.filter((c) => c.claim_type === tab).length})
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Table */}
      {isLoading && (
        <div className="flex justify-center py-12">
          <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
        </div>
      )}

      {error && (
        <Card className="border-red-200 bg-red-50">
          <CardContent className="pt-6">
            <p className="text-red-600 text-sm">
              Failed to load claims. Please ensure the backend is running.
            </p>
          </CardContent>
        </Card>
      )}

      {!isLoading && !error && (
        <div className="rounded-md border border-gray-200 overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-gray-50 border-b border-gray-200">
              <tr>
                <th className="px-4 py-3 text-left w-32">
                  <SortButton
                    field="claim_type"
                    label="Type"
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                </th>
                <th className="px-4 py-3 text-left">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Claim Text
                  </span>
                </th>
                <th className="px-4 py-3 text-left w-36">
                  <SortButton
                    field="expiry_date"
                    label="Expiry Date"
                    current={sortField}
                    dir={sortDir}
                    onClick={handleSort}
                  />
                </th>
                <th className="px-4 py-3 text-left w-36">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Approved By
                  </span>
                </th>
                <th className="px-4 py-3 text-right w-24">
                  <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                    Actions
                  </span>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-gray-100 bg-white">
              {filteredClaims.length === 0 ? (
                <tr>
                  <td colSpan={5} className="px-4 py-10 text-center text-gray-400 text-sm">
                    {search || filter !== 'ALL' ? 'No claims match your filter.' : 'No claims yet. Add your first claim.'}
                  </td>
                </tr>
              ) : (
                filteredClaims.map((claim) => {
                  const expired = isExpired(claim.expiry_date);
                  return (
                    <tr key={claim.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-4 py-3">
                        <span
                          className={cn(
                            'inline-flex items-center px-2 py-0.5 rounded text-xs font-medium',
                            CLAIM_TYPE_BADGE[claim.claim_type],
                          )}
                        >
                          {CLAIM_TYPE_LABELS[claim.claim_type]}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-gray-800 max-w-xs">
                        <p className="line-clamp-2">{claim.claim_text}</p>
                      </td>
                      <td className="px-4 py-3">
                        {claim.expiry_date ? (
                          <span className={cn('text-sm', expired && 'text-red-600 font-medium')}>
                            {formatDate(claim.expiry_date)}
                            {expired && (
                              <Badge variant="destructive" className="ml-1.5 text-xs py-0">
                                Expired
                              </Badge>
                            )}
                          </span>
                        ) : (
                          <span className="text-gray-400">—</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-gray-600">
                        {claim.approved_by ?? <span className="text-gray-400">—</span>}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => setEditingClaim(claim)}
                            className="p-1.5 rounded hover:bg-gray-100 text-gray-500 hover:text-gray-900 transition-colors"
                            title="Edit claim"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => handleDelete(claim)}
                            disabled={deleteClaim.isPending}
                            className="p-1.5 rounded hover:bg-red-50 text-gray-400 hover:text-red-600 transition-colors disabled:opacity-50"
                            title="Delete claim"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      )}

      {!isLoading && !error && filteredClaims.length > 0 && (
        <p className="text-xs text-gray-400 text-right">
          {filteredClaims.length} claim{filteredClaims.length !== 1 ? 's' : ''}
          {filter !== 'ALL' || search ? ' (filtered)' : ''}
        </p>
      )}

      <AddClaimModal
        open={addModalOpen}
        onClose={() => setAddModalOpen(false)}
        onSave={handleCreate}
        isLoading={createClaim.isPending}
      />

      <EditClaimModal
        open={editingClaim !== null}
        claim={editingClaim}
        onClose={() => setEditingClaim(null)}
        onSave={handleUpdate}
        isLoading={updateClaim.isPending}
      />
    </div>
  );
}
