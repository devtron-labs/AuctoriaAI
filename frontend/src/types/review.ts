import type { Document, DraftVersion, ValidationReport, FactSheet, AuditLog } from '@/types/document';

export interface ReviewDetails {
  document: Document;
  latest_draft: DraftVersion | null;
  validation_report: ValidationReport | null;
  fact_sheet: FactSheet | null;
  audit_log: AuditLog[];
}
