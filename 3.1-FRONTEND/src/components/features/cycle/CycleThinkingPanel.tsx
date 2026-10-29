'use client';

import { useCallback, useEffect, useState } from 'react';

/**
 * 40-周期神经网络系统 周期思考卡片面板
 *
 * 复用 ThinkingCard 折叠卡片模式：头部摘要 + 展开分组详情
 * 红线约束（SPEC v0.8 路1 接入规格）：
 * - 呈现标注研究建议，与交易 UI 隔离
 * - 消费 effective_confidence 而非原始置信度
 */

interface CycleApiResponse {
  success: boolean;
  disclaimer?: string;
  research_only?: boolean;
  effective_confidence?: string | null;
  cycle_state?: CycleState;
  strategy_mapping?: StrategyMapping;
  execution_state?: ExecutionState;
  x1_metrics_status?: X1MetricsStatus;
  artifacts?: Array<{ file: string; size_bytes: number; modified_at: string }>;
  error?: string;
}

interface CycleState {
  generated_at?: string;
  real_cycle?: {
    anchor?: string;
    current_month?: string;
    current_rate?: number;
    state?: string;
    last_change?: string;
    confidence?: string;
  };
  technical_anchor?: {
    type?: string;
    assets?: Record<string, { last_close?: number; ma200?: number; above?: boolean; distance_pct?: number }>;
  };
  sector_transmission?: {
    state?: string;
    regime?: string;
    layer_median_momentum_3m_pct?: Record<string, number>;
  };
}

interface StrategyMapping {
  generated_at?: string;
  inputs?: {
    quadrant?: string;
    quadrant_confidence?: string;
    effective_confidence?: string;
    event_window_frozen?: boolean;
    clock_degraded?: boolean;
  };
  strategy_suggestion?: {
    stance?: string;
    position_band_pct?: [number, number];
    crypto_layer_focus?: string[];
    rationale?: string;
  };
  risk_notes?: string[];
  red_line?: string;
}

interface ExecutionState {
  updated_at?: string;
  stage?: string;
  signal_source?: string;
  intents_today?: number;
  written_today?: number;
}

interface X1MetricsStatus {
  stage?: string;
  gate?: {
    samples?: number;
    min_samples?: number;
    weeks?: number;
    min_weeks?: number;
    x1_ready?: boolean;
  };
}

const CONFIDENCE_STYLE: Record<string, string> = {
  high: 'bg-emerald-500/15 text-emerald-400 border-emerald-500/30',
  medium: 'bg-amber-500/15 text-amber-400 border-amber-500/30',
  low: 'bg-red-500/15 text-red-400 border-red-500/30',
};

function confidenceBadge(level?: string | null) {
  if (!level) return null;
  const cls = CONFIDENCE_STYLE[level] || 'bg-slate-500/15 text-slate-400 border-slate-500/30';
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-[10px] font-medium ${cls}`}>
      effective_confidence: {level}
    </span>
  );
}

function Card({
  title,
  icon,
  children,
  defaultOpen = false,
}: {
  title: string;
  icon: string;
  children: React.ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="rounded-xl border border-slate-800 bg-slate-900/60">
      <button
        onClick={() => setOpen(!open)}
        className="flex w-full items-center justify-between px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-medium text-slate-200">
          <span>{icon}</span>
          {title}
        </span>
        <span className={`text-xs text-slate-500 transition-transform ${open ? 'rotate-90' : ''}`}>▶</span>
      </button>
      {open && <div className="border-t border-slate-800 px-4 py-3">{children}</div>}
    </div>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between py-1 text-xs">
      <span className="text-slate-500">{label}</span>
      <span className="text-slate-300">{value}</span>
    </div>
  );
}

export function CycleThinkingPanel() {
  const [data, setData] = useState<CycleApiResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    try {
      const res = await fetch('/api/cycle', { cache: 'no-store' });
      const json = (await res.json()) as CycleApiResponse;
      if (!json.success) throw new Error(json.error || '加载失败');
      setData(json);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const timer = setInterval(load, 60000);
    return () => clearInterval(timer);
  }, [load]);

  if (loading) {
    return <div className="rounded-xl border border-slate-800 bg-slate-900/60 p-6 text-center text-xs text-slate-500">周期研究数据加载中…</div>;
  }

  if (error) {
    return (
      <div className="rounded-xl border border-red-900/50 bg-red-950/30 p-4 text-xs text-red-400">
        周期研究数据加载失败：{error}
      </div>
    );
  }

  const rc = data?.cycle_state?.real_cycle;
  const ta = data?.cycle_state?.technical_anchor;
  const st = data?.cycle_state?.sector_transmission;
  const sm = data?.strategy_mapping;
  const es = data?.execution_state;
  const x1 = data?.x1_metrics_status;
  const gate = x1?.gate;
  const gatePct = gate && gate.min_samples ? Math.min(100, Math.round(((gate.samples || 0) / gate.min_samples) * 100)) : 0;

  return (
    <div className="space-y-3">
      {/* 红线：研究建议标注，与交易 UI 隔离 */}
      <div className="rounded-lg border border-amber-700/40 bg-amber-950/30 px-4 py-2 text-[11px] text-amber-400">
        ⚠️ {data?.disclaimer || '研究建议，非交易信号'}（本面板与交易 UI 隔离，不触发任何下单动作）
      </div>

      {/* 头部摘要：象限 + 有效置信度 */}
      <div className="flex flex-wrap items-center gap-2 rounded-xl border border-slate-800 bg-slate-900/60 px-4 py-3">
        <span className="text-sm font-semibold text-slate-200">
          🧭 周期象限：{sm?.inputs?.quadrant || '未知'}
        </span>
        {confidenceBadge(data?.effective_confidence)}
        {sm?.inputs?.event_window_frozen && (
          <span className="rounded-md border border-sky-500/30 bg-sky-500/15 px-2 py-0.5 text-[10px] text-sky-400">事件窗口冻结</span>
        )}
        {sm?.inputs?.clock_degraded && (
          <span className="rounded-md border border-red-500/30 bg-red-500/15 px-2 py-0.5 text-[10px] text-red-400">时钟降级</span>
        )}
      </div>

      {/* 卡片 1：真实周期（美林时钟锚） */}
      <Card title="真实周期（美林时钟锚）" icon="🕰️" defaultOpen>
        <Row label="锚指标" value={rc?.anchor || '-'} />
        <Row label="当前月份" value={rc?.current_month || '-'} />
        <Row label="利率水平" value={rc?.current_rate ?? '-'} />
        <Row label="周期状态" value={rc?.state || '-'} />
        <Row label="最近变动" value={rc?.last_change || '-'} />
        <Row label="原始置信度" value={rc?.confidence || '-'} />
      </Card>

      {/* 卡片 2：技术锚（MA200） */}
      <Card title="技术锚（MA200）" icon="📐">
        {ta?.assets
          ? Object.entries(ta.assets).map(([symbol, a]) => (
              <Row
                key={symbol}
                label={symbol}
                value={
                  <span className={a.above ? 'text-emerald-400' : 'text-red-400'}>
                    {a.above ? '▲ 站上' : '▼ 跌破'} MA200（{a.distance_pct ?? '-'}%）
                  </span>
                }
              />
            ))
          : <div className="text-xs text-slate-500">暂无数据</div>}
      </Card>

      {/* 卡片 3：板块传导 */}
      <Card title="板块传导（L1-L4 层动量）" icon="📡">
        <Row label="传导状态" value={st?.state || '-'} />
        <Row label="市场体制" value={st?.regime || '-'} />
        {st?.layer_median_momentum_3m_pct
          ? Object.entries(st.layer_median_momentum_3m_pct).map(([layer, pct]) => (
              <Row key={layer} label={layer} value={`${pct}%`} />
            ))
          : null}
      </Card>

      {/* 卡片 4：P4 策略映射（研究建议） */}
      <Card title="P4 策略映射（研究建议）" icon="🧠" defaultOpen>
        <Row label="建议姿态" value={sm?.strategy_suggestion?.stance || '-'} />
        <Row
          label="建议仓位区间"
          value={
            sm?.strategy_suggestion?.position_band_pct
              ? `${sm.strategy_suggestion.position_band_pct[0]}% - ${sm.strategy_suggestion.position_band_pct[1]}%`
              : '-'
          }
        />
        <Row label="聚焦层级" value={sm?.strategy_suggestion?.crypto_layer_focus?.join(' / ') || '-'} />
        <div className="mt-2 rounded-lg bg-slate-800/60 px-3 py-2 text-[11px] leading-relaxed text-slate-400">
          {sm?.strategy_suggestion?.rationale || '-'}
        </div>
        {sm?.risk_notes && sm.risk_notes.length > 0 && (
          <div className="mt-2 space-y-1">
            {sm.risk_notes.map((note, i) => (
              <div key={i} className="rounded-md border border-amber-800/40 bg-amber-950/20 px-3 py-1.5 text-[11px] text-amber-400/90">
                ⚠️ {note}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* 卡片 5：X0 执行层（意图流采集） */}
      <Card title="X0 执行层（意图流采集，不下单）" icon="⚡">
        <Row label="阶段" value={es?.stage || '-'} />
        <Row label="信号源" value={es?.signal_source || '-'} />
        <Row label="今日意图数" value={es?.intents_today ?? '-'} />
        <Row label="今日落盘数" value={es?.written_today ?? '-'} />
        {gate && (
          <div className="mt-2">
            <div className="mb-1 flex items-center justify-between text-[10px] text-slate-500">
              <span>X1 门槛进度（样本 {gate.samples}/{gate.min_samples}，{gate.weeks}/{gate.min_weeks} 周）</span>
              <span>{gatePct}%</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-slate-800">
              <div className="h-full rounded-full bg-indigo-500 transition-all" style={{ width: `${gatePct}%` }} />
            </div>
          </div>
        )}
      </Card>

      {/* 卡片 6：产出物清单 */}
      <Card title="产出物清单（40 系统只读）" icon="📦">
        <div className="grid grid-cols-1 gap-1 sm:grid-cols-2">
          {data?.artifacts?.map((a) => (
            <div key={a.file} className="flex items-center justify-between rounded-md bg-slate-800/40 px-2.5 py-1.5 text-[11px]">
              <span className="truncate text-slate-300">{a.file}</span>
              <span className="ml-2 shrink-0 text-slate-500">{(a.size_bytes / 1024).toFixed(1)} KB</span>
            </div>
          ))}
        </div>
      </Card>

      <div className="text-right text-[10px] text-slate-600">
        数据每 60 秒自动刷新 · 更新时间：{sm?.generated_at || es?.updated_at || '-'}
      </div>
    </div>
  );
}
