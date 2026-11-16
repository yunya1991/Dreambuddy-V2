// 「数据研究」聚合出口（设计稿 v3 五子页）— 只读快照的类型与客户端
// 数值全部来自后端 visual_research.py 投影，前端不做统计重算。

export type CellState = 'ok' | 'partial' | 'missing' | 'unknown';

export interface CoverageCell {
  state: CellState;
  n?: number;
  scope?: string;
}

export interface CoverageRow {
  target: string;
  label: string;
  n: number;
  rows: number;
  gate_pass: number;
  domains: Record<string, CoverageCell>;
}

export interface SpaceBlock {
  available: boolean;
  version?: number;
  updated?: string;
  seed?: number;
  series_count: number;
  series: string[];
  transform_count: number;
  transforms: string[];
  method_count: number;
  methods: string[];
  horizons: number[];
  max_units: number;
  max_minutes: number;
  max_findings: number;
  max_pairs: number;
  alpha?: number | null;
  corr_threshold?: number | null;
  screen_ratio?: number | null;
  holdout_ratio?: number | null;
  min_holdout_agreement?: number | null;
}

export interface RelationClass {
  id: string;
  name: string;
  question: string;
  hypothesis: string;
  enabled: boolean;
  blocked_by: string;
  judge: string[];
  members: string[];
  packages: number;
  gate_pass: number;
  mean_abs_rank_ic: number | null;
  mean_hit: number | null;
  states: { stable: number; candidate: number; decayed: number; other: number };
  top_horizon: number | null;
  rows: number;
}

export interface PatternRow {
  id: string;
  relation: string;
  horizon: number | null;
  support: number;
  oppose: number;
  agreement: number | null;
  p_adj: number | null;
  status: string;
}

export interface GateRow {
  id: string;
  name: string;
  rule: string;
  status: string;
  pass: number;
  total: number;
}

export interface FunnelStep {
  step: string;
  count: number;
  ratio: number | null;
}

export interface RecommendationRow {
  eval_id: string;
  relation: string;
  target: string;
  method: string;
  transform: string;
  horizon: number;
  rank_ic: number | null;
  hit_rate: number | null;
  hit_rate_lb: number | null;
  holdout_hit_rate: number | null;
  n: number;
  n_eff: number;
  p_adj: number | null;
  status: string;
  gate_pass: number;
  stability: number | null;
  eval_at: string;
  data_version: string;
}

export interface EvidenceNode {
  id: string;
  label: string;
  group: string;
}

export interface EvidenceEdge {
  src: string;
  dst: string;
  weight?: number | null;
}

export interface ResearchPayload {
  ok: boolean;
  as_of?: string | null;
  degraded?: boolean;
  reason?: string;
  source: {
    registry?: string | null;
    registry_exists?: boolean;
    registry_rows?: number;
    data_version?: string;
    run_id?: string;
    eval_at?: string;
    report?: string | null;
  };
  space: SpaceBlock;
  coverage: {
    available: boolean;
    domains: { key: string; label: string }[];
    rows: CoverageRow[];
    notes: string[];
  };
  latest: {
    available: boolean;
    report?: string | null;
    eval_at?: string;
    data_version?: string;
    registry_rows?: number;
    evaluable?: number;
    significant?: number;
    holdout_agree?: number;
    gate_pass?: number;
    stable?: number;
    reason?: string;
  };
  classes: RelationClass[];
  patterns: {
    available: boolean;
    source: 'report' | 'derived' | 'none';
    report?: string | null;
    rows: PatternRow[];
  };
  gates: GateRow[];
  funnel: FunnelStep[];
  holdout: { available: boolean; reason?: string; points: { period: string; value: number }[] };
  recommendations: RecommendationRow[];
  candidates: RecommendationRow[];
  distribution: { relations: string[]; horizons: number[]; values: number[][] };
  evidence: {
    available: boolean;
    nodes: EvidenceNode[];
    edges: EvidenceEdge[];
    headline?: string;
  };
}

export async function fetchResearch(top = 12): Promise<ResearchPayload> {
  const response = await fetch(`/api/visual/research?top=${top}`, { cache: 'no-store' });
  return (await response.json()) as ResearchPayload;
}
