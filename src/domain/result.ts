import type { ReportMeta } from './report-meta';

export interface ImportDiagnostic {
  severity: 'info' | 'warning' | 'error';
  code: string;
  message: string;
  row?: number;
  field?: string;
}

export interface ImportResult<T> {
  records: T[];
  diagnostics: ImportDiagnostic[];
  meta: ReportMeta;
}
