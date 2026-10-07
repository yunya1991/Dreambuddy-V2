/**
 * BDSM 每日快照 API 客户端
 *
 * 调用 11-易经推理系统/data_server_fixed.py (端口 8765) 暴露的
 * BDSM 每日快照接口：
 *   - GET /api/bdsm/snapshot  返回最新 bdsm_snapshot_YYYYMMDD.json
 *
 * 返回结构含 §6 sector_valuation 5 字段：
 *   - 每币 4 字段: sector_waterline / multi_dim_valuation / undervalued_peers / overheat_signal
 *   - 顶层 1 字段: sector_valuation_summary
 *
 * 后端已设置 Access-Control-Allow-Origin: *，可直接从浏览器跨域调用。
 */

const BDSM_BASE = process.env.NEXT_PUBLIC_TREND_SYSTEM_URL || 'http://127.0.0.1:8765';

async function bdsmRequest<T = any>(endpoint: string): Promise<T> {
  const url = `${BDSM_BASE}${endpoint}`;
  // GET 请求不设置 Content-Type，避免触发 CORS 预检（OPTIONS）
  // 后端 BaseHTTPRequestHandler 不支持 OPTIONS 方法
  // 30s 超时：后端读 JSON 文件 + 30s 缓存，通常 < 100ms
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), 30_000);

  try {
    const response = await fetch(url, {
      method: 'GET',
      signal: controller.signal,
    });

    if (!response.ok) {
      throw new Error(`BDSM API Error: ${response.status} ${response.statusText}`);
    }

    return response.json();
  } finally {
    clearTimeout(timeoutId);
  }
}

// ============================================================
// 类型定义（后端返回结构，对应 SPEC §6）
// ============================================================

export interface SectorWaterline {
  sector: string;
  median_percentile: number;
  member_count?: number;
  overheated: boolean;
  undervalued: boolean;
  leader: string;
  leader_momentum_7d: number;
  timestamp?: string;
}

export interface MultiDimValuation {
  mc_fees_pct: number;
  mc_tvl_pct: number;
  peg_pct: number;
  multi_dim_score: number;
}

export interface UndervaluedPeer {
  coin: string;
  opportunity_score: number;
}

export interface OverheatSignal {
  triggered: boolean;
  waterline: number;
  confidence: number;
}

export interface BdsmCoinEntry {
  available: boolean;
  data_quality?: string;
  confidence: number;
  score: number;
  score_raw?: number;
  rank: string;
  e5: number;
  e6: number;
  e7: number;
  e8_cross_sector_valuation?: number;
  tactical_position_eligibility?: boolean;
  bds_score?: number;
  phase: string;
  phase_confidence?: number;
  valuation_percentile?: number;
  direction_constraint: string;
  cap_multiplier?: number;
  exit_action: string;
  exit_triggers: string[];
  // §6.1 sector_valuation 4 字段
  sector_waterline?: Partial<SectorWaterline> | Record<string, any>;
  multi_dim_valuation?: Partial<MultiDimValuation> | Record<string, any>;
  undervalued_peers?: UndervaluedPeer[];
  overheat_signal?: Partial<OverheatSignal> | Record<string, any>;
  _unavailable_reason?: string;
}

export interface SectorValuationSummary {
  generated_at?: string;
  waterlines: SectorWaterline[];
  top_opportunities: Array<{
    coin: string;
    sector?: string;
    opportunity_score: number;
    rank?: string;
  }>;
  overheat_sectors: string[];
}

export interface BdsmSnapshot {
  snapshot_date: string;
  generated_at?: string;
  version?: string;
  status: 'ok' | 'error';
  neutral_fallback_reason?: string;
  note?: string;
  coins: Record<string, BdsmCoinEntry>;
  // §6.2 顶层 sector_valuation_summary
  sector_valuation_summary?: SectorValuationSummary | Record<string, any>;
}

// ============================================================
// API 方法
// ============================================================

export const BdsmAPI = {
  /** 获取最新 BDSM 每日快照（含 §6 sector_valuation 全字段） */
  async fetchSnapshot(): Promise<BdsmSnapshot> {
    return bdsmRequest<BdsmSnapshot>('/api/bdsm/snapshot');
  },
};

export default BdsmAPI;
