export interface ReportMeta {
  sourceName: string;
  importedAt: string;
  reportGeneratedAt: string | null;
  periodStart: string | null;
  periodEnd: string | null;
  recommendationHorizonDays: number | null;
}
