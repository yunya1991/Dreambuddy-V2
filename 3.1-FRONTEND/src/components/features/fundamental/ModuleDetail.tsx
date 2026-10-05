'use client';

import { useState, useEffect, useCallback } from 'react';
import { V3Card, V3Badge } from '@/components';

// ============== 类型 ==============
interface Resistance3D {
  direction: string;
  direction_score: number;
  velocity?: number;
  acceleration?: number;
  confidence: number;
  data_points?: number;
  trend_summary?: string;
}

interface TradingSignal {
  type: string;
  strength?: number;
  confidence?: number;
  reason?: string;
  horizon?: string;
  module?: string;
}

interface ModuleSnapshot {
  module?: string;
  ts?: string;
  resistance_3d: Resistance3D;
  signals?: TradingSignal[];
  metrics?: {
    core?: Record<string, number | string>;
    breakdown?: Record<string, number>;
  };
  timeseries?: Array<{
    ts: string;
    direction_score: number;
    velocity?: number;
    acceleration?: number;
  }>;
}

// ============== 映射 ==============
const signalVariant = { bullish: 'success' as const, bearish: 'danger' as const, neutral: 'default' as const };
const signalLabel = { bullish: '看多', bearish: '看空', neutral: '中性' };

const SIGNAL_TYPE_LABEL: Record<string, string> = {
  strong_buy: '强烈买入', buy: '买入', hold: '观望',
  sell: '卖出', strong_sell: '强烈卖出',
  bullish: '看多', bearish: '看空', neutral: '中性',
};

function scoreToSignal(score: number): 'bullish' | 'bearish' | 'neutral' {
  if (score >= 0.1) return 'bullish';
  if (score <= -0.1) return 'bearish';
  return 'neutral';
}

function fmt(n: number): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '--';
  return Math.abs(n) >= 100 ? n.toFixed(0) : n.toFixed(3);
}

function fmtPct(n: number): string {
  if (n === undefined || n === null || Number.isNaN(n)) return '--';
  return `${(n * 100).toFixed(0)}%`;
}

// 各模块 metrics.core 字段中文标签
const METRIC_LABELS: Record<string, string> = {
  // onchain
  active_addresses: '活跃地址', hash_rate: '哈希率', tx_count_24h: '24h交易笔数',
  exchange_net_flow: '交易所净流', exchange_reserve_btc: '交易所储备',
  accumulation_signal: '积累信号', network_health: '网络健康', onchain_trend: '链上趋势',
  market_cap_usd: '市值',
  // flow
  etf_total_flow: 'ETF净流入', etf_net_flow: 'ETF净流入', flow_velocity_score: '流速得分', fund_flow_score: '资金得分',
  funding_rate: '资金费率', liquidation_pressure: '清算压力', long_short_ratio: '多空比',
  smart_money_direction: '聪明钱方向', stablecoin_supply_change: '稳定币变化', whale_activity: '鲸鱼活跃',
  stablecoin_dominance_usdt: 'USDT占比', stablecoin_dominance_usdc: 'USDC占比', flow_regime: '流向状态',
  // valuation
  mvrv_ratio: 'MVRV', mvrv_z_score: 'MVRV-Z', nvt_ratio: 'NVT', nvt_z_score: 'NVT-Z',
  valuation_zone: '估值区间', valuation_range: '估值区间', valuation_heat_level: '估值热度',
  ahr999_index: 'AHR999', mayer_multiple: '梅耶倍数', pi_cycle_top: '顶圆周',
  puell_multiple: '普尔倍数', sopr: 'SOPR', therm_index: '热度指数',
  output_volume_btc: '输出量(BTC)',
  // breadth
  advance_count: '上涨数', advance_decline_line: '涨跌线', breadth_confirmation: '广度确认',
  breadth_divergence_score: '广度背离', btc_dominance: 'BTC主导', decline_count: '下跌数',
  divergence_signal: '背离信号', market_participation_index: '参与指数', new_high_low_ratio: '新高新低比',
  global_change_24h: '全球24h涨跌', defi_tvl_bln: 'DeFi TVL',
  // macro
  policy_score: '政策得分', cpi_yoy: 'CPI同比', fed_funds_rate: '联邦基金利率',
  rate_cycle: '利率周期', cut_probability: '降息概率', hold_probability: '维持概率',
  hike_probability: '加息概率',
  // sentiment
  sentiment_index: '情绪指数', sentiment_classification: '情绪分类', sentiment_regime: '情绪周期',
  fear_greed_index: '恐惧贪婪', market_psychology: '市场心理', social_volume: '社交声量',
  // calendar
  high_impact_events: '高影响事件', impact_score: '影响得分', total_events: '事件总数',
  cpi_surprise: 'CPI超预期', nfp_surprise: '非农超预期', ppi_surprise: 'PPI超预期',
  cpi_actual: 'CPI实际', cpi_forecast: 'CPI预期',
  // intermarket
  btc_correlation_gold: 'BTC-黄金相关', btc_correlation_spx: 'BTC-标普相关',
  dxy: '美元指数', dxy_correlation: '美元相关', gold: '黄金', gold_price: '黄金价格',
  ndx: '纳指', risk_on_index: '风险偏好', spx: '标普500', spx_price: '标普价格',
  vix: 'VIX', wti: '原油', us10y_yield: '美债10Y', btc_price: 'BTC价格', risk_regime: '风险周期',
  // news
  avg_impact: '平均影响', avg_sentiment: '平均情绪', category_count: '分类数',
  high_impact_count: '高影响数', negative_count: '利空数', positive_count: '利好数',
  sentiment: '情绪值', sentiment_sum: '情绪总和', top_category: '头条分类', total_articles: '文章总数',
  // narrative
  avg_momentum: '平均动量', consensus: '共识度', market_consensus: '市场共识', total_narratives: '叙事数',
};

function labelOf(key: string): string {
  return METRIC_LABELS[key] || key;
}

function fmtMetric(v: number | string): string {
  if (typeof v === 'string') return v;
  if (typeof v !== 'number' || Number.isNaN(v)) return '--';
  return Math.abs(v) >= 100 ? v.toFixed(1) : v.toFixed(3);
}

// ============== 组件 ==============
export function ModuleDetail({ module: moduleKey, title }: { module: string; title: string }) {
  const [data, setData] = useState<ModuleSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`/api/fundamental/${moduleKey}/snapshot`, { cache: 'no-store' });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const body = await res.json();
      if (body && body.resistance_3d && !body.error) {
        setData(body as ModuleSnapshot);
      } else {
        throw new Error(body?.error || '数据格式异常');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : '获取数据失败');
    } finally {
      setLoading(false);
    }
  }, [moduleKey]);

  useEffect(() => {
    load();
  }, [load]);

  if (loading && !data) {
    return (
      <div className="flex items-center justify-center py-16">
        <p className="text-sm text-slate-500">加载{title}数据中…</p>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col items-center justify-center py-16 gap-3">
        <p className="text-sm text-rose-400">{title}数据加载失败：{error}</p>
        <button onClick={load} className="px-3 py-1.5 rounded-lg text-xs bg-indigo-600/20 text-indigo-400 hover:bg-indigo-600/30">
          重试
        </button>
      </div>
    );
  }

  const r3d = data!.resistance_3d;
  const sig = scoreToSignal(r3d.direction_score || 0);
  const core = data!.metrics?.core || {};
  const coreEntries = Object.entries(core);
  const signals = data!.signals || [];
  const ts = data!.timeseries || [];
  const tsLabel = data!.ts ? new Date(data!.ts).toLocaleString('zh-CN') : '--';

  // timeseries 统计
  const tsScores = ts.map((t) => t.direction_score).filter((v) => typeof v === 'number');
  const tsLatest = tsScores.length ? tsScores[tsScores.length - 1] : null;
  const tsMax = tsScores.length ? Math.max(...tsScores) : null;
  const tsMin = tsScores.length ? Math.min(...tsScores) : null;
  const tsTrend = tsScores.length >= 2 ? tsScores[tsScores.length - 1] - tsScores[0] : null;

  return (
    <div className="space-y-3">
      {/* 顶部方向卡 */}
      <V3Card padding="md">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <V3Badge variant={signalVariant[sig]} label={signalLabel[sig]} />
            <div>
              <p className="text-sm font-semibold text-slate-200">
                {title} · 方向 {r3d.direction || '--'} · 得分 {fmt(r3d.direction_score || 0)}
              </p>
              <p className="text-[10px] text-slate-500 mt-0.5">
                置信度 {fmtPct(r3d.confidence)} · {r3d.trend_summary || '--'}
                {r3d.velocity !== undefined && ` · 速度 ${fmt(r3d.velocity)}`}
                {r3d.acceleration !== undefined && ` · 加速度 ${fmt(r3d.acceleration)}`}
              </p>
            </div>
          </div>
          <span className="text-[10px] text-slate-600">更新：{tsLabel}</span>
        </div>
      </V3Card>

      {/* 核心指标网格 */}
      {coreEntries.length > 0 && (
        <div>
          <p className="text-[11px] text-slate-500 mb-2">核心指标</p>
          <div className="grid grid-cols-4 gap-2">
            {coreEntries.map(([k, v]) => (
              <V3Card key={k} padding="sm">
                <p className="text-[10px] text-slate-500 mb-0.5">{labelOf(k)}</p>
                <p className="text-sm font-semibold text-slate-200">{fmtMetric(v)}</p>
              </V3Card>
            ))}
          </div>
        </div>
      )}

      {/* 交易信号 */}
      {signals.length > 0 && (
        <div>
          <p className="text-[11px] text-slate-500 mb-2">交易信号（{signals.length}）</p>
          <div className="space-y-1.5">
            {signals.map((s, i) => {
              const sSig = scoreToSignal((s.strength ?? 0) > 0 ? s.strength ?? 0 : (s.type || '').includes('buy') || (s.type || '').includes('bull') ? 0.2 : (s.type || '').includes('sell') || (s.type || '').includes('bear') ? -0.2 : 0);
              return (
                <V3Card key={i} padding="sm">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <p className="text-xs text-slate-300">{s.reason || s.type || '信号'}</p>
                      {s.horizon && <p className="text-[10px] text-slate-600 mt-0.5">周期：{s.horizon}</p>}
                    </div>
                    <div className="flex items-center gap-2 flex-shrink-0">
                      {s.strength !== undefined && <span className="text-[10px] text-slate-500">强度 {fmt(s.strength)}</span>}
                      <V3Badge variant={signalVariant[sSig]} label={SIGNAL_TYPE_LABEL[s.type] || s.type || '信号'} />
                    </div>
                  </div>
                </V3Card>
              );
            })}
          </div>
        </div>
      )}

      {/* 时序趋势摘要 */}
      {tsScores.length > 0 && (
        <div>
          <p className="text-[11px] text-slate-500 mb-2">趋势时序（{tsScores.length} 点）</p>
          <div className="grid grid-cols-4 gap-2">
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-0.5">最新得分</p>
              <p className="text-sm font-semibold text-slate-200">{fmt(tsLatest ?? 0)}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-0.5">区间最高</p>
              <p className="text-sm font-semibold text-emerald-400">{fmt(tsMax ?? 0)}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-0.5">区间最低</p>
              <p className="text-sm font-semibold text-rose-400">{fmt(tsMin ?? 0)}</p>
            </V3Card>
            <V3Card padding="sm">
              <p className="text-[10px] text-slate-500 mb-0.5">区间变化</p>
              <p className={`text-sm font-semibold ${(tsTrend ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                {tsTrend !== null ? (tsTrend >= 0 ? '+' : '') + fmt(tsTrend) : '--'}
              </p>
            </V3Card>
          </div>
        </div>
      )}

      <div className="flex justify-end">
        <button
          onClick={load}
          disabled={loading}
          className="px-3 py-1.5 rounded-lg text-xs bg-slate-800 text-slate-400 hover:bg-slate-700 disabled:opacity-50"
        >
          {loading ? '刷新中…' : '刷新数据'}
        </button>
      </div>
    </div>
  );
}
