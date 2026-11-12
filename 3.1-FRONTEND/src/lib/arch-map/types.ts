/**
 * 架构工程地图 — 数据契约（与 ARCH_ENGINEERING_MAP_SPEC.md §3 对应）
 *
 * 产物由 48-涌现架构/baselines/project_arch_map.py 生成，落在 src/data/arch-map/。
 * 本文件只做类型声明，不含逻辑。
 */

export type ArchLayerId = 'S' | 'A' | 'C' | 'G' | 'X';

export interface ArchMapLayer {
  id: string;
  label: string;
}

export interface ArchMapNode {
  id: string;
  label: string;
  layer: string;
  /** 聚合到该能力的源文件数（图仅含 .py/.md，TS 侧为空属预期） */
  files: number;
  loc: number;
  /** 静态连通性：至少一条入/出边 */
  hit: boolean;
  /** files > 0 且 hit === false */
  orphan: boolean;
  owner_paths: string[];
}

export interface ArchMapEdge {
  src: string;
  dst: string;
  kind: string;
  weight: number;
}

export interface ArchMapData {
  schema: 'ArchMap/v1';
  generated_at: string;
  source: {
    graph_sha256: string;
    node_count: number;
    edge_count: number;
  };
  layers: ArchMapLayer[];
  nodes: ArchMapNode[];
  edges: ArchMapEdge[];
  unmapped: {
    dirs: string[];
    files: number;
  };
}

export interface CapMapData {
  schema: 'CapMap/v1';
  generated_at: string;
  phase_map: Record<string, string[]>;
  layer_default: Record<string, string[]>;
  cap_ids: string[];
}

/** 节点运行态：idle（从未点亮）/ warm（<5min）/ active（<30s）/ failed（<30s 内失败） */
export type ArchNodeState = 'idle' | 'warm' | 'active' | 'failed';

export interface ArchCapRuntime {
  hits: number;
  completed: number;
  failed: number;
  lastAt: number;
  /** 最近一次失败时间（用于 failed 态保留 30s） */
  lastFailedAt?: number;
  lastDurationMs?: number;
}

/** 导出给 arch_map_review.py --runtime 的运行态文件 */
export interface ArchMapRuntimeExport {
  schema: 'ArchMapRuntime/v1';
  exported_at: string;
  since: string;
  caps: Record<
    string,
    {
      hits: number;
      completed: number;
      failed: number;
      last_at: string;
      last_duration_ms?: number;
    }
  >;
  /** 运行态出现但图中不存在的 cap（规则表过期信号） */
  ghosts: Record<string, number>;
}

export const LAYER_COLORS: Record<string, string> = {
  S: '#a855f7',
  A: '#3b82f6',
  C: '#22c55e',
  G: '#f59e0b',
  X: '#64748b',
};
