import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Star,
  Plug,
  Shield,
  BarChart2,
  AlertTriangle,
  FileSearch,
} from 'lucide-react';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { cn } from '@/lib/utils';
import type { FactSheet } from '@/types/document';

interface FactSheetViewerProps {
  factSheet: FactSheet | null;
  isLoading: boolean;
}

interface SectionProps {
  title: string;
  icon: React.ReactNode;
  count: number;
  children: React.ReactNode;
}

function Section({ title, icon, count, children }: SectionProps) {
  const [open, setOpen] = useState(true);

  return (
    <div className="border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        className="w-full flex items-center justify-between px-4 py-3 bg-muted/40 hover:bg-muted/60 transition-colors text-left"
      >
        <div className="flex items-center gap-2 font-medium text-sm">
          {icon}
          {title}
          <span className="ml-1 rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            {count}
          </span>
        </div>
        {open ? (
          <ChevronDown className="h-4 w-4 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 text-muted-foreground" />
        )}
      </button>
      {open && <div className="divide-y">{children}</div>}
    </div>
  );
}

function EmptyRow({ label }: { label: string }) {
  return (
    <div className="px-4 py-3 text-sm text-muted-foreground italic">No {label} recorded.</div>
  );
}

function Row({ children }: { children: React.ReactNode }) {
  return <div className="px-4 py-3 text-sm">{children}</div>;
}

function Field({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <span className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
        {label}
      </span>
      <p className="mt-0.5 text-foreground">{value}</p>
    </div>
  );
}

function StatusPill({ status }: { status: string }) {
  const s = status.toLowerCase();
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
        s === 'compliant' || s === 'passed' || s === 'active'
          ? 'bg-green-100 text-green-700'
          : s === 'partial' || s === 'in progress'
            ? 'bg-yellow-100 text-yellow-700'
            : 'bg-red-100 text-red-700',
      )}
    >
      {status}
    </span>
  );
}

export default function FactSheetViewer({ factSheet, isLoading }: FactSheetViewerProps) {
  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileSearch className="h-5 w-5" />
            Fact Sheet
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[1, 2, 3].map((i) => (
              <div key={i} className="h-16 rounded-lg bg-muted animate-pulse" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!factSheet) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileSearch className="h-5 w-5" />
            Fact Sheet
          </CardTitle>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground">
            No fact sheet available. Upload a file and click &ldquo;Extract Fact Sheet&rdquo; to
            generate one.
          </p>
        </CardContent>
      </Card>
    );
  }

  const { structured_data: sd } = factSheet;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <FileSearch className="h-5 w-5" />
          Fact Sheet
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Features */}
        <Section
          title="Features"
          icon={<Star className="h-4 w-4 text-yellow-500" />}
          count={sd.features.length}
        >
          {sd.features.length === 0 ? (
            <EmptyRow label="features" />
          ) : (
            sd.features.map((f, i) => (
              <Row key={i}>
                <div className="grid gap-1">
                  <Field label="Name" value={f.name} />
                  <Field label="Description" value={f.description} />
                </div>
              </Row>
            ))
          )}
        </Section>

        {/* Integrations */}
        <Section
          title="Integrations"
          icon={<Plug className="h-4 w-4 text-blue-500" />}
          count={sd.integrations.length}
        >
          {sd.integrations.length === 0 ? (
            <EmptyRow label="integrations" />
          ) : (
            sd.integrations.map((item, i) => (
              <Row key={i}>
                <div className="grid grid-cols-3 gap-3">
                  <Field label="System" value={item.system} />
                  <Field label="Method" value={item.method} />
                  <Field label="Notes" value={item.notes} />
                </div>
              </Row>
            ))
          )}
        </Section>

        {/* Compliance */}
        <Section
          title="Compliance"
          icon={<Shield className="h-4 w-4 text-purple-500" />}
          count={sd.compliance.length}
        >
          {sd.compliance.length === 0 ? (
            <EmptyRow label="compliance items" />
          ) : (
            sd.compliance.map((item, i) => (
              <Row key={i}>
                <div className="flex items-start justify-between gap-4">
                  <div className="grid gap-1 flex-1">
                    <Field label="Standard" value={item.standard} />
                    <Field label="Details" value={item.details} />
                  </div>
                  <div className="pt-4">
                    <StatusPill status={item.status} />
                  </div>
                </div>
              </Row>
            ))
          )}
        </Section>

        {/* Performance Metrics */}
        <Section
          title="Performance Metrics"
          icon={<BarChart2 className="h-4 w-4 text-green-500" />}
          count={sd.performance_metrics.length}
        >
          {sd.performance_metrics.length === 0 ? (
            <EmptyRow label="performance metrics" />
          ) : (
            <Row>
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b">
                    <th className="pb-2 text-left text-xs uppercase tracking-wide text-muted-foreground font-medium">
                      Metric
                    </th>
                    <th className="pb-2 text-right text-xs uppercase tracking-wide text-muted-foreground font-medium">
                      Value
                    </th>
                    <th className="pb-2 text-right text-xs uppercase tracking-wide text-muted-foreground font-medium">
                      Unit
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {sd.performance_metrics.map((m, i) => (
                    <tr key={i}>
                      <td className="py-2 font-medium">{m.metric}</td>
                      <td className="py-2 text-right tabular-nums">{m.value}</td>
                      <td className="py-2 text-right text-muted-foreground">{m.unit}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Row>
          )}
        </Section>

        {/* Limitations */}
        <Section
          title="Limitations"
          icon={<AlertTriangle className="h-4 w-4 text-orange-500" />}
          count={sd.limitations.length}
        >
          {sd.limitations.length === 0 ? (
            <EmptyRow label="limitations" />
          ) : (
            sd.limitations.map((item, i) => (
              <Row key={i}>
                <div className="grid gap-1">
                  <Field label="Category" value={item.category} />
                  <Field label="Description" value={item.description} />
                </div>
              </Row>
            ))
          )}
        </Section>
      </CardContent>
    </Card>
  );
}
