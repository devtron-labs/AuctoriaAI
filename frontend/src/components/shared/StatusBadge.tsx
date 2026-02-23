import { Badge } from '@/components/ui/badge';
import type { DocumentStatus } from '@/types/document';

const statusConfig: Record<
  DocumentStatus,
  {
    label: string;
    variant: 'default' | 'secondary' | 'destructive' | 'outline' | 'success' | 'warning' | 'info' | 'orange';
  }
> = {
  DRAFT:        { label: 'Draft',        variant: 'secondary' },
  VALIDATING:   { label: 'Validating',   variant: 'warning' },
  PASSED:       { label: 'Passed',       variant: 'info' },
  HUMAN_REVIEW: { label: 'In Review',    variant: 'orange' },
  APPROVED:     { label: 'Approved',     variant: 'success' },
  BLOCKED:      { label: 'Blocked',      variant: 'destructive' },
};

interface StatusBadgeProps {
  status: DocumentStatus;
}

export default function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status];
  if (!config) {
    // Defensive fallback: unknown status from backend does not crash the render
    return <Badge variant="outline">{status}</Badge>;
  }
  return <Badge variant={config.variant}>{config.label}</Badge>;
}
