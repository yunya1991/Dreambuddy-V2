// SPEC-54 图规格前端类型（与 contracts/capability_result.schema.json $defs.visual 对齐）

export type VisualKind = 'table' | 'series' | 'matrix' | 'tree' | 'graph';

export interface VisualNodeMeta {
  capability?: string;
  series_id?: string;
  unit?: string;
  reason?: string;
  proxy?: boolean;
  sign_flip?: number;
}

export interface VisualNode {
  id: string;
  label: string;
  value: number | null;
  children?: VisualNode[];
  meta: VisualNodeMeta;
}

export interface VisualPoint {
  x: string | number;
  y: number | null;
  [key: string]: string | number | null | undefined;
}

export interface VisualColumn {
  key: string;
  label: string;
  type?: 'string' | 'number' | 'percent' | 'date';
}

export interface VisualSpec {
  id?: string;
  kind: VisualKind;
  spec_version: string;
  title: string;
  source_capability: string;
  n_scope: 'global' | 'per_row' | 'per_cell';
  dataset: Record<string, unknown>;
  encodings: Record<string, string>;
  quality_ref: string;
  truncated: boolean;
  caveat: string;
}

export interface RecommendItem {
  id: string;
  title: string;
  kind: string;
  reason: string;
}

export interface VisualOverview {
  ok: boolean;
  as_of?: string | null;
  base?: string;
  assets?: string[];
  unavailable?: { asset: string; reason: string }[];
  visuals?: VisualSpec[];
  recommended?: RecommendItem[];
  degraded?: boolean;
  generated_at?: string;
  error?: string;
}

/** 单位 → 展示格式（后端只给原始值，前端只做格式化，不做统计） */
export function formatValue(value: number | null | undefined, unit?: string): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '—';
  switch (unit) {
    case 'rate':
    case 'ratio':
      return `${(value * 100).toFixed(2)}%`;
    case 'percent':
      return `${value.toFixed(2)}%`;
    case 'rho':
      return value.toFixed(3);
    case 'q':
      return Math.abs(value) < 1e-4 ? value.toExponential(1) : value.toFixed(4);
    case 't':
      return value.toFixed(2);
    case 'obs':
    case 'bar':
      return value.toFixed(0);
    default:
      return Math.abs(value) >= 1000
        ? value.toLocaleString('en-US', { maximumFractionDigits: 2 })
        : value.toFixed(3);
  }
}

export function formatCell(value: unknown, type?: string): string {
  if (value === null || value === undefined) return '—';
  if (type === 'percent' && typeof value === 'number') return `${(value * 100).toFixed(2)}%`;
  if (type === 'number' && typeof value === 'number') {
    return Number.isInteger(value) ? String(value) : value.toFixed(4);
  }
  return String(value);
}
