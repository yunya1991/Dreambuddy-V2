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
  annotations?: MatrixAnnotations;
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

// ── matrix 附加注解（SPEC-54 matrix：数值矩阵走 dataset.values，状态/符号走 annotations）
export interface MatrixAxis {
  key: string;
  label: string;
  weight?: number | null;
}

export interface MatrixCell {
  state: LightState | string;
  strength: number | null;
  bucket: string;
  sign: number;
  flags?: string[];
}

export interface MatrixRowMeta {
  label?: string;
  class?: string;
  as_of?: string | null;
  strength?: number | null;
  summary?: Record<string, number>;
}

export interface MatrixAnnotations {
  axes?: MatrixAxis[];
  cells?: Record<string, MatrixCell>;
  rows?: Record<string, MatrixRowMeta>;
  light_weights_hash?: string;
  thresholds?: { lit_pct?: number; warm_pct?: number };
  thresholds_uncalibrated?: boolean;
}

// ── D-E19 点亮投影（SPEC-54 §5.3）：五态 + 四轴，前端只读不重算
export type LightState = 'lit' | 'warm' | 'dim' | 'conflict' | 'unavailable';
export type LightBucket = 'high' | 'mid' | 'low' | 'none';
export type LightAxisKey = 'trend' | 'inertia' | 'cycle' | 'foresight';

export interface LightAxis {
  state: LightState;
  strength: number | null;
  bucket: LightBucket;
  evidence?: Record<string, unknown>;
  flags?: string[];
}

export interface LightRow {
  symbol: string;
  class: string;
  as_of?: string | null;
  axes: Partial<Record<LightAxisKey, LightAxis>>;
  strength: number | null;
  summary: {
    lit_n: number;
    warm_n: number;
    conflict_n: number;
    unavailable_n: number;
  };
  light_weights_hash?: string;
  n?: number;
  min_rows?: number;
  status?: string;
  flags?: string[];
}

export interface LightsMeta {
  light_weights?: Record<string, number>;
  light_weights_hash?: string;
  light_weights_mode?: string;
  thresholds?: { lit_pct?: number; warm_pct?: number };
  thresholds_uncalibrated?: boolean;
  min_rows?: number;
  flags?: string[];
  [key: string]: unknown;
}

export interface PersistenceRow {
  symbol: string;
  available: boolean;
  consecutive_lit: number | null;
  lit_ratio: number | null;
  flips: number | null;
  periods?: number;
  state?: LightState;
}

export interface PersistencePayload {
  available: boolean;
  periods?: number;
  rows: PersistenceRow[];
}

export interface LightsPayload {
  ok: boolean;
  rows: LightRow[];
  meta?: LightsMeta;
  answer?: string | null;
  quality?: Record<string, unknown> | null;
  /** T9-2 逐期回放（仅在 `?history=N` 时下发；缺期不补造） */
  history?: { as_of: string; rows: LightRow[] }[];
  /** 持续性（由逐期快照投影，仅在 `?history=N` 时下发） */
  persistence?: PersistencePayload;
  history_error?: string;
}

export interface SlopeRow {
  window: number;
  slope: number | null;
  se?: number | null;
  t?: number | null;
  r2?: number | null;
  n?: number | null;
  degraded?: boolean;
  degraded_reason?: string | null;
}

export interface PanelMetrics {
  trend?: {
    ema?: Record<string, number> | null;
    ema_order?: string | null;
    slope_table?: SlopeRow[];
    kalman?: { level?: number | null; band?: number[] | null; slope?: number | null; slope_se?: number | null };
  };
  volatility?: { annualized?: number | null; window?: number | null; sample_n?: number | null; capability?: string };
  drawdown?: {
    mdd?: number | null;
    current?: number | null;
    peak_date?: string | null;
    trough_price?: number | null;
    peak_price?: number | null;
    peak_to_trough_days?: number | null;
    duration_days?: number | null;
    recovery_days?: number | null;
    recovered?: boolean | null;
    capability?: string;
  };
  crowding?: {
    score?: number | null;
    percentile?: number | null;
    level?: string | null;
    n?: number | null;
    as_of?: string | null;
    capability?: string;
  };
}

export interface BaseMetrics {
  percentile?: {
    value: number | null;
    lookback?: number | null;
    sample_n?: number | null;
    capability?: string;
  } | null;
  panel_metrics?: PanelMetrics | null;
  as_of?: string | null;
}

export interface VisualOverview {
  ok: boolean;
  as_of?: string | null;
  base?: string;
  assets?: string[];
  unavailable?: { asset: string; reason: string }[];
  visuals?: VisualSpec[];
  lights?: LightsPayload | null;
  base_metrics?: BaseMetrics | null;
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
