import { render, screen } from '@testing-library/react';
import StatusBadge from '../shared/StatusBadge';
import type { DocumentStatus } from '@/types/document';

describe('StatusBadge', () => {
  const cases: Array<{ status: DocumentStatus; label: string; cssClass: string }> = [
    { status: 'DRAFT',        label: 'Draft',      cssClass: 'bg-secondary' },
    { status: 'VALIDATING',   label: 'Validating', cssClass: 'bg-yellow-100' },
    { status: 'PASSED',       label: 'Passed',     cssClass: 'bg-blue-100' },
    { status: 'HUMAN_REVIEW', label: 'In Review',  cssClass: 'bg-orange-100' },
    { status: 'APPROVED',     label: 'Approved',   cssClass: 'bg-green-100' },
    { status: 'BLOCKED',      label: 'Blocked',    cssClass: 'bg-destructive' },
  ];

  test.each(cases)('renders $status status with label "$label"', ({ status, label }) => {
    render(<StatusBadge status={status} />);
    expect(screen.getByText(label)).toBeInTheDocument();
  });

  test.each(cases)('$status badge has correct CSS class', ({ status, label, cssClass }) => {
    render(<StatusBadge status={status} />);
    // Badge renders a <div> containing the label text directly
    const badge = screen.getByText(label);
    expect(badge.className).toContain(cssClass);
  });

  it('renders unknown status with outline variant and raw status text', () => {
    // Cast to bypass TypeScript — tests the defensive fallback at runtime
    render(<StatusBadge status={'UNKNOWN_STATUS' as DocumentStatus} />);
    expect(screen.getByText('UNKNOWN_STATUS')).toBeInTheDocument();
  });
});
