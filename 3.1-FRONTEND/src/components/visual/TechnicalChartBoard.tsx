'use client';

// 技术图表（设计稿 v3 · 八子页严格对齐）
// 1 加权信号点阵 / 2 点亮图影 / 3 技术分析叠加 / 4 信号反馈
// 5 跨资产 / 6 波动与回撤 / 7 周期与资金 / 8 数据口径。
// 与「数据研究」单向承接：这里只读图与证据，不改推荐；无后端来源的层不画（不伪造）。

import { useEffect, useMemo, useState } from 'react';
import { V3Badge, V3Empty } from '@/components';
import { fetchResearch, type ResearchPayload } from '@/lib/visual/research';
import { LightsTimeline, type LightsPeriod } from './LightsTimeline';
import { OverlayChart, type OverlaySource } from './OverlayChart';
import { SignalFeedback, SignalFeedbackBuckets } from './SignalFeedback';
import { SignalMatrix } from './SignalMatrix';
import { VisualRenderer } from './VisualRenderer';
import type {
  BaseMetrics,
  LightRow,
  LightState,
  MatrixAnnotations,
  PersistencePayload,
  VisualOverview,
  VisualPoint,
  VisualSpec,
} from './types';

const CHAIN_KEY = 'dreambuddy.visual.chain.v1';

interface TabDef {
  id: string;
  label: string;
  chain?: boolean;
}

const TABS: TabDef[] = [
  { id: 'signals', label: '加权信号点阵' },
  { id: 'lights', label: '点亮图影' },
  { id: 'overlay', label: '技术分析叠加' },
  { id: 'feedback', label: '信号反馈' },
  { id: 'cross', label: '跨资产' },
  { id: 'risk', label: '波动与回撤' },
  { id: 'cycle', label: '周期与资金' },
  { id: 'quality', label: '数据口径' },
  { id: 'targets', label: '目标与覆盖', chain: true },
  { id: 'taxonomy', label: '算法分类', chain: true },
  { id: 'patterns', label: '现象归纳', chain: true },
  { id: 'gates', label: '假设验证', chain: true },
  { id: 'cards', label: '数据卡片', chain: true },
];

const CHAIN_HINT: Record<string, { stage: string; detail: string }> = {
  targets: { stage: 'S1 目标与覆盖', detail: '覆盖资产池与缺口由后端 D-E12 / D-J29 产出，属流水线内部口径，不对外铺开。' },
  taxonomy: { stage: 'S2 算法分类', detail: '关系类型分类由发现流水线完成，前端不枚举候选；对外见「数据研究 · 算法分类」。' },
  patterns: { stage: 'S3 现象归纳', detail: '同类现象去重与主类归并在 patterns.json；对外只在「数据研究」以推荐卡呈现。' },
  gates: { stage: 'S4 假设验证', detail: 'G0–G6 门禁与 BH-FDR 结果落在关系评估注册表；对外见「数据研究 · 假设验证」。' },
  cards: { stage: 'S5 数据卡片', detail: '能力出口卡片在「数据研究」按需添加；技术图表只消费已产出的图规格。' },
};

const STATE_STYLE: Record<string, string> = {
  lit: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  warm: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  dim: 'border-slate-700 bg-slate-800/40 text-slate-400',
  conflict: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
  unavailable: 'border-slate-800 bg-slate-900/60 text-slate-600',
  stable: 'border-emerald-500/30 bg-emerald-500/10 text-emerald-300',
  candidate: 'border-amber-500/30 bg-amber-500/10 text-amber-300',
  decayed: 'border-rose-500/30 bg-rose-500/10 text-rose-300',
};

function readChainFlag(): boolean {
  if (typeof window === 'undefined') return false;
  try {
    return window.localStorage.getItem(CHAIN_KEY) === '1';
  } catch {
    return false;
  }
}

function writeChainFlag(value: boolean): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(CHAIN_KEY, value ? '1' : '0');
  } catch {
    // FAIL-OPEN：隐私模式写入失败不阻断
  }
}

function num(value: number | null | undefined, digits = 3): string {
  return typeof value === 'number' && Number.isFinite(value) ? value.toFixed(digits) : '—';
}

function pct(value: number | null | undefined, digits = 1): string {
  return typeof value === 'number' && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : '—';
}

function syntheticState(row: LightRow | undefined, litPct = 0.7, warmPct = 0.4): LightState {
  if (!row) return 'unavailable';
  if (Object.values(row.axes ?? {}).some((axis) => axis?.state === 'conflict')) return 'conflict';
  if (row.strength === null || row.strength === undefined) return 'unavailable';
  if (row.strength >= litPct) return 'lit';
  if (row.strength >= warmPct) return 'warm';
  return 'dim';
}

function Panel({
  title,
  sub,
  right,
  children,
  note,
  className = '',
}: {
  title: string;
  sub?: string;
  right?: React.ReactNode;
  children: React.ReactNode;
  note?: React.ReactNode;
  className?: string;
}) {
  return (
    <section className={`min-w-0 rounded-xl border border-slate-800 bg-slate-900/40 p-3.5 ${className}`}>
      <header className="mb-2.5 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-[12.5px] font-medium text-slate-200">{title}</h2>
          {sub && <p className="mt-0.5 text-[10px] text-slate-500">{sub}</p>}
        </div>
        {right && <div className="flex shrink-0 items-center gap-1.5">{right}</div>}
      </header>
      {children}
      {note && <p className="mt-2 text-[10px] leading-relaxed text-slate-500">{note}</p>}
    </section>
  );
}

export function TechnicalChartBoard({ embedded = false }: { embedded?: boolean }) {
  const [overview, setOverview] = useState<VisualOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [active, setActive] = useState('signals');
  const [showChain, setShowChain] = useState(false);
  const [periods, setPeriods] = useState<LightsPeriod[]>([]);
  const [persistence, setPersistence] = useState<PersistencePayload | null>(null);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');
  const [selected, setSelected] = useState('');
  const [research, setResearch] = useState<ResearchPayload | null>(null);

  useEffect(() => {
    setShowChain(readChainFlag());
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    fetch('/api/visual/overview', { cache: 'no-store' })
      .then(async (response) => (await response.json()) as VisualOverview)
      .then((payload) => {
        if (alive) setOverview(payload);
      })
      .catch((err: unknown) => {
        if (alive) setError(err instanceof Error ? err.message : 'fetch_failed');
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  useEffect(() => {
    let alive = true;
    fetchResearch(5)
      .then((payload) => {
        if (alive && payload.ok) setResearch(payload);
      })
      .catch(() => {
        // FAIL-OPEN：研究出口不可用不影响读图
      });
    return () => {
      alive = false;
    };
  }, []);

  const visuals = useMemo(() => overview?.visuals ?? [], [overview]);
  const byId = useMemo(() => new Map(visuals.map((visual) => [visual.id ?? '', visual])), [visuals]);
  const lightsRows = overview?.lights?.rows ?? [];
  const lightMeta = overview?.lights?.meta ?? {};

  const currentPeriods = useMemo<LightsPeriod[]>(() => {
    if (periods.length > 0) return periods;
    if (!lightsRows.length) return [];
    const asOf = lightsRows.find((row) => row.as_of)?.as_of ?? overview?.as_of ?? '';
    return asOf ? [{ as_of: asOf, rows: lightsRows }] : [];
  }, [periods, lightsRows, overview?.as_of]);

  function loadHistory() {
    setHistoryLoading(true);
    setHistoryError('');
    fetch('/api/visual/overview?history=24', { cache: 'no-store' })
      .then(async (response) => (await response.json()) as VisualOverview)
      .then((payload) => {
        const history = payload.lights?.history ?? [];
        setPersistence(payload.lights?.persistence ?? null);
        if (history.length === 0) {
          setHistoryError(payload.lights?.history_error || '后端未回放出历史期（不补造）');
          return;
        }
        setPeriods(history.map((item) => ({ as_of: item.as_of, rows: item.rows })));
      })
      .catch((err: unknown) => {
        setHistoryError(err instanceof Error ? err.message : 'history_failed');
      })
      .finally(() => {
        setHistoryLoading(false);
      });
  }

  const matrix = byId.get('matrix:signals') as VisualSpec | undefined;
  const matrixAnnotations = (matrix?.annotations ?? {}) as MatrixAnnotations;
  const selectedRow = useMemo(() => {
    if (selected) return lightsRows.find((row) => row.symbol === selected);
    const ranked = [...lightsRows].sort((a, b) => (b.strength ?? -1) - (a.strength ?? -1));
    return ranked[0];
  }, [lightsRows, selected]);

  const visibleTabs = TABS.filter((tab) => showChain || !tab.chain);

  function renderVisual(visualId: string) {
    const visual = byId.get(visualId) as VisualSpec | undefined;
    if (!visual) {
      return (
        <V3Empty
          title={`暂无 ${visualId}`}
          description="后端本期未产出该图（门禁未通过或数据不足）；不做占位伪造。"
        />
      );
    }
    return <VisualRenderer visual={visual} />;
  }

  const overlayVisual = byId.get('series:d-e15');
  const overlayPoints = ((overlayVisual?.dataset as Record<string, unknown> | undefined)?.points ??
    []) as VisualPoint[];
  const overlayMeta = ((overlayVisual?.dataset as Record<string, unknown> | undefined)?.meta ??
    {}) as { smoothing?: { method?: string; window?: number }; unit?: string };

  const percentileRaw = overview?.base_metrics?.percentile;
  const percentile =
    percentileRaw && typeof percentileRaw.value === 'number'
      ? {
          value: Math.max(0, Math.min(1, percentileRaw.value / 100)),
          lookback: percentileRaw.lookback ?? null,
          sample_n: percentileRaw.sample_n ?? null,
        }
      : null;

  const metrics = (overview?.base_metrics as BaseMetrics | null | undefined)?.panel_metrics ?? null;
  const litPct = matrixAnnotations.thresholds?.lit_pct ?? lightMeta.thresholds?.lit_pct ?? 0.7;
  const warmPct = matrixAnnotations.thresholds?.warm_pct ?? lightMeta.thresholds?.warm_pct ?? 0.4;

  const litDays = Array.from(
    new Set(lightsRows.map((row) => row.as_of).filter((day): day is string => Boolean(day))),
  );

  const overlaySources: OverlaySource[] = [
    { id: 'price', label: '价格', capability: 'D-E15', status: overlayPoints.length > 0 ? 'ok' : 'missing' },
    {
      id: 'ma',
      label: overlayMeta.smoothing?.method ?? 'MA',
      capability: 'D-E15',
      status: overlayPoints.some((point) => typeof point.smoothed === 'number') ? 'ok' : 'missing',
    },
    {
      id: 'atr',
      label: 'ATR 带',
      capability: null,
      status: overlayPoints.some(
        (point) => typeof point.atr_upper === 'number' && typeof point.atr_lower === 'number',
      )
        ? 'ok'
        : 'missing',
      detail: metrics?.trend?.kalman?.band
        ? '后端仅提供 Kalman 置信带（D-E15），ATR 带未产出，缺失时该层不画'
        : '后端暂未提供 atr_upper/atr_lower，缺失时该层不画',
    },
    { id: 'percentile', label: '历史分位', capability: 'D-A04', status: percentile ? 'ok' : 'missing' },
    { id: 'lights', label: '点亮日', capability: 'D-E19', status: litDays.length > 0 ? 'ok' : 'missing' },
  ];

  const researchRows = research?.recommendations.length
    ? research.recommendations
    : research?.candidates ?? [];
  const cycleEvidence = lightsRows
    .map((row) => ({
      symbol: row.symbol,
      strength: row.axes.cycle?.strength ?? null,
      state: row.axes.cycle?.state ?? 'unavailable',
      evidence: (row.axes.cycle?.evidence ?? {}) as Record<string, unknown>,
    }))
    .sort((a, b) => (b.strength ?? -1) - (a.strength ?? -1));

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          {embedded ? (
            <p className="text-[11px] text-slate-500">八子页 · 只读图与证据，不改推荐</p>
          ) : (
            <>
              <h1 className="text-lg font-semibold text-slate-100">技术图表</h1>
              <p className="mt-1 text-xs text-slate-500">
                加权信号点阵 → 点亮图影 → 技术分析叠加 → 信号反馈；承接「数据研究」的推荐锚点，不给买卖方向
              </p>
            </>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {overview?.as_of && <V3Badge variant="info" label={`数据截至 ${overview.as_of}`} />}
          {overview?.degraded && <V3Badge variant="warning" label="部分降级" />}
          <label className="flex cursor-pointer items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900 px-2.5 py-0.5 text-[11px] text-slate-400">
            <input
              type="checkbox"
              checked={showChain}
              onChange={(event) => {
                setShowChain(event.target.checked);
                writeChainFlag(event.target.checked);
              }}
              className="h-3 w-3 accent-indigo-500"
            />
            链路子页（S1–S5）
          </label>
        </div>
      </header>

      {error && <V3Empty title="图表服务暂不可用" description={`${error}；可稍后刷新重试`} />}

      <nav className="flex items-center gap-1 overflow-x-auto border-b border-slate-800 pb-1">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActive(tab.id)}
            className={`shrink-0 rounded-t-md px-3 py-1.5 text-xs ${
              tab.id === active ? 'bg-indigo-500/10 text-indigo-200' : 'text-slate-400 hover:text-slate-200'
            } ${tab.chain ? 'opacity-80' : ''}`}
          >
            {tab.label}
            {tab.chain && <span className="ml-1 font-mono text-[9px] opacity-60">链路</span>}
          </button>
        ))}
      </nav>

      {loading && !overview && <div className="h-24 animate-pulse rounded-lg bg-slate-800/40" />}

      {overview && active === 'signals' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.85fr)]">
          <Panel
            title="加权信号点阵"
            sub="D-E19 · 四轴强度 × 合成强度 · 点径 = |v|/w"
            right={
              <>
                <V3Badge
                  variant={lightMeta.thresholds_uncalibrated ? 'warning' : 'success'}
                  label={lightMeta.thresholds_uncalibrated ? '阈值未标定' : '已标定 p70/p40'}
                />
                <V3Badge variant="default" label={`${lightsRows.length} 标的`} />
              </>
            }
            note="点径 = 轴归一强度 |v| / w，截断 [0,1]；合成 = Σ light_weights × 轴（缺轴剔除后按剩余权重重新归一）。状态词只用 lit/warm/dim/conflict/unavailable，不输出买卖方向。"
          >
            <div className="mb-2 flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
              {Object.entries(lightMeta.light_weights ?? {}).map(([axis, weight]) => (
                <span key={axis} className="flex items-center gap-1">
                  <span className="text-slate-400">{axis}</span>
                  <span className="h-1 w-10 overflow-hidden rounded-full bg-slate-800">
                    <span
                      className="block h-full rounded-full bg-indigo-500/60"
                      style={{ width: `${Math.round(Number(weight) * 100)}%` }}
                    />
                  </span>
                  <span className="font-mono">{num(Number(weight), 2)}</span>
                </span>
              ))}
              <span className="text-slate-600">light_weights · 与交易轴 / 展示轴互不共用</span>
            </div>
            {matrix ? (
              <SignalMatrix visual={matrix} />
            ) : (
              <V3Empty title="点阵无数据" description="后端未产出 matrix:signals（点亮输入样本不足）" />
            )}
          </Panel>

          <div className="space-y-3">
            <Panel
              title="点阵读数"
              sub={`Top 1: ${selectedRow?.symbol ?? '—'} ${Math.round((selectedRow?.strength ?? 0) * 100)}`}
              right={<V3Badge variant="default" label={`${Object.keys(selectedRow?.axes ?? {}).length} 轴`} />}
            >
              <div className="mb-2 flex flex-wrap gap-1">
                {lightsRows.map((row) => (
                  <button
                    key={row.symbol}
                    type="button"
                    onClick={() => setSelected(row.symbol)}
                    className={`rounded border px-1.5 py-0.5 font-mono text-[9px] ${
                      row.symbol === selectedRow?.symbol
                        ? 'border-indigo-500/50 bg-indigo-500/15 text-indigo-200'
                        : 'border-slate-800 bg-slate-950/40 text-slate-400 hover:text-slate-200'
                    }`}
                  >
                    {row.symbol}
                  </button>
                ))}
              </div>
              {selectedRow ? (
                <table className="w-full">
                  <tbody>
                    {(['trend', 'inertia', 'cycle', 'foresight'] as const).map((axis) => {
                      const cell = selectedRow.axes[axis];
                      return (
                        <tr key={axis} className="border-b border-slate-800/50 last:border-0">
                          <td className="py-1 text-[10.5px] text-slate-400">{axis} 轴</td>
                          <td className="py-1 text-right font-mono text-[10.5px] text-slate-200">
                            {num(cell?.strength ?? null, 3)}
                          </td>
                          <td className="py-1 pl-2 text-right font-mono text-[9px] text-slate-500">
                            {String(cell?.evidence?.capability ?? '—')} · {cell?.state ?? 'unavailable'}
                          </td>
                        </tr>
                      );
                    })}
                    <tr className="border-b border-slate-800/50">
                      <td className="py-1 text-[10.5px] text-slate-400">合成</td>
                      <td className="py-1 text-right font-mono text-[11px] text-slate-100">
                        {num(selectedRow.strength, 3)}
                      </td>
                      <td className="py-1 pl-2 text-right font-mono text-[9px] text-slate-500">
                        {Object.values(lightMeta.light_weights ?? {})
                          .map((item) => num(Number(item), 2))
                          .join(' / ') || '等权'}
                      </td>
                    </tr>
                    <tr>
                      <td className="py-1 text-[10.5px] text-slate-400">样本 n</td>
                      <td className="py-1 text-right font-mono text-[10.5px] text-slate-200">
                        {selectedRow.n ?? '—'}
                      </td>
                      <td className="py-1 pl-2 text-right font-mono text-[9px] text-slate-500">
                        ≥ min_rows {selectedRow.min_rows ?? lightMeta.min_rows ?? '—'}
                      </td>
                    </tr>
                  </tbody>
                </table>
              ) : (
                <p className="text-[11px] text-slate-500">无点亮行</p>
              )}
              <p className="mt-2 text-[10px] text-slate-500">点阵只投影能力层已算好的强度，不重算任何统计量。</p>
            </Panel>

            <Panel
              title="阈值来源"
              sub="chart_weights.yaml"
              right={<V3Badge variant="default" label={`${lightMeta.thresholds ? 2 : 0} 阈值`} />}
            >
              <div className="flex flex-wrap gap-1">
                {[
                  `lit_pct ${num(lightMeta.thresholds?.lit_pct ?? null, 4)}`,
                  `warm_pct ${num(lightMeta.thresholds?.warm_pct ?? null, 4)}`,
                  `min_rows ${lightMeta.min_rows ?? '—'}`,
                  `权重源 ${lightMeta.light_weights_mode ?? '—'}`,
                  `指纹 ${String(lightMeta.light_weights_hash ?? '—').slice(0, 8)}`,
                ].map((chip) => (
                  <span
                    key={chip}
                    className="rounded border border-slate-800 bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
                  >
                    {chip}
                  </span>
                ))}
              </div>
              <p className="mt-2 text-[10px] leading-relaxed text-slate-500">
                未标定 → thresholds_uncalibrated=true，前端明示；权重非法 → 降级等权 +
                weights_degraded=true，不整图消失。
              </p>
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'lights' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.85fr)]">
          <Panel
            title="点亮图影"
            sub="最近 24 个交易日 · 8 标的 × 四轴合成状态"
            right={<V3Badge variant="info" label="light_history.py" />}
            note="每列 = 一个 as_of 快照（逐日切片历史后重跑 D-E15 + I39，再经 D-E19 投影），无前视。影带用于看「点亮是否持续」，不用于计数胜率（胜率在「信号反馈」）。"
          >
            <LightsTimeline
              periods={currentPeriods}
              loading={historyLoading}
              error={historyError}
              onRequestHistory={loadHistory}
              historyCount={24}
            />
          </Panel>

          <div className="space-y-3">
            <Panel
              title="持续性"
              sub="当前点亮连续天数"
              right={
                <V3Badge
                  variant="default"
                  label={
                    persistence?.available
                      ? `${persistence.rows.filter((row) => (row.consecutive_lit ?? 0) > 0).length} / ${persistence.rows.length}`
                      : '待回放'
                  }
                />
              }
              note="翻转次数高 = 状态不稳，应在数据研究里查对应关系是否 decayed。"
            >
              {persistence?.available ? (
                <div className="overflow-x-auto">
                  <table className="w-full">
                    <thead>
                      <tr className="border-b border-slate-800">
                        {['标的', '连续 lit', '影带 lit 占比', '翻转'].map((head) => (
                          <th key={head} className="px-1 py-1 text-left text-[9px] font-normal text-slate-500">
                            {head}
                          </th>
                        ))}
                      </tr>
                    </thead>
                    <tbody>
                      {persistence.rows.slice(0, 10).map((row) => (
                        <tr key={row.symbol} className="border-b border-slate-800/50 last:border-0">
                          <td className="px-1 py-1 font-mono text-[10px] text-slate-300">{row.symbol}</td>
                          <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-200">
                            {row.available ? (row.consecutive_lit ?? 0) : '—'}
                          </td>
                          <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-300">
                            {pct(row.lit_ratio, 0)}
                          </td>
                          <td className="px-1 py-1 text-right">
                            <span
                              className={`rounded px-1 py-0.5 font-mono text-[9px] ${
                                (row.flips ?? 0) >= 3 ? 'bg-rose-500/10 text-rose-300' : 'bg-slate-800 text-slate-400'
                              }`}
                            >
                              {row.available ? row.flips : 'unavailable'}
                            </span>
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <p className="text-[11px] text-slate-500">
                  点击影带上的「加载历史期」后，由后端逐期回放计算连续点亮 / 占比 / 翻转（不补造）。
                </p>
              )}
            </Panel>

            <Panel title="图影读法" sub="三层都成立才进信号候选">
              <div className="space-y-2">
                {[
                  ['先看影带', '形态', 100],
                  ['再看点阵', '强度', 72],
                  ['最后看反馈', '命中', 46],
                ].map(([label, tag, width]) => (
                  <div key={String(label)} className="grid grid-cols-[88px_1fr_40px] items-center gap-2">
                    <span className="text-[10.5px] text-slate-400">{label}</span>
                    <span className="h-3 overflow-hidden rounded bg-slate-900">
                      <span className="block h-full rounded bg-indigo-500/45" style={{ width: `${width}%` }} />
                    </span>
                    <span className="text-right font-mono text-[9px] text-slate-500">{tag}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[10px] text-slate-500">任一层缺失即不生成信号；本页不判定买卖。</p>
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'overlay' && (
        <div className="space-y-3">
          <Panel
            title={`技术分析叠加 · ${overview?.base ?? '—'}`}
            sub="价格 + MA20/60 + 置信带 + 波动分位 + 拥挤标线"
            right={
              <>
                <V3Badge variant="default" label="D-A06 · D-A14 · D-B08" />
                <V3Badge variant="default" label={`${overlayPoints.length} 点`} />
              </>
            }
            note="叠加的作用是「把统计结论变成可看的数据处理」：均线定趋势状态、置信带定波动区间、波动分位定门控、拥挤标线定拥挤。本图不给方向、不给买卖点。"
          >
            <OverlayChart
              points={overlayPoints}
              smoothing={overlayMeta.smoothing}
              unit={overlayMeta.unit}
              percentile={percentile}
              litDays={litDays}
              sources={overlaySources}
            />
          </Panel>

          <div className="grid gap-3 md:grid-cols-3">
            <Panel
              title="斜率表"
              sub="D-B08 · 多窗口"
              right={<V3Badge variant="default" label={`${metrics?.trend?.slope_table?.length ?? 0} 窗口`} />}
              note="符号一致度 → trend 轴归一值；不一致即降权，不做人工修正。"
            >
              {metrics?.trend?.slope_table?.length ? (
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {['窗口', '斜率', 'R²', '符号'].map((head) => (
                        <th key={head} className="px-1 py-1 text-left text-[9px] font-normal text-slate-500">
                          {head}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {metrics.trend.slope_table.map((row) => (
                      <tr key={row.window} className="border-b border-slate-800/50 last:border-0">
                        <td className="px-1 py-1 text-[10px] text-slate-400">{row.window}d</td>
                        <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-200">
                          {row.slope === null ? '—' : `${(row.slope * 100).toFixed(2)}%`}
                        </td>
                        <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-300">
                          {num(row.r2, 2)}
                        </td>
                        <td className="px-1 py-1 text-right">
                          {row.slope === null ? (
                            <span className="text-[9px] text-slate-600">{row.degraded_reason ?? 'degraded'}</span>
                          ) : (
                            <span
                              className={`text-[9px] ${
                                row.slope > 0 ? 'text-emerald-300' : row.slope < 0 ? 'text-rose-300' : 'text-slate-400'
                              }`}
                            >
                              {row.slope > 0 ? '正' : row.slope < 0 ? '负' : '平'}
                            </span>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              ) : (
                <p className="text-[11px] text-slate-500">D-E15 未产出斜率表</p>
              )}
            </Panel>

            <Panel
              title="波动与拥挤"
              sub="分位口径"
              right={<V3Badge variant="default" label="D-A06 · D-A14" />}
              note="拥挤 > p85 + 点亮 → conflict 旗标，只读展示，不改状态。"
            >
              <table className="w-full">
                <tbody>
                  {[
                    ['年化波动', pct(metrics?.volatility?.annualized), `n ${metrics?.volatility?.sample_n ?? '—'}`],
                    ['历史分位', percentile ? pct(percentile.value) : '—', `lookback ${percentile?.lookback ?? '—'}`],
                    ['拥挤度', num(metrics?.crowding?.score, 3), `p${num(metrics?.crowding?.percentile, 0)}`],
                    ['拥挤等级', metrics?.crowding?.level ?? '—', `n ${metrics?.crowding?.n ?? '—'}`],
                  ].map(([label, value, ref]) => (
                    <tr key={String(label)} className="border-b border-slate-800/50 last:border-0">
                      <td className="py-1 text-[10.5px] text-slate-400">{label}</td>
                      <td className="py-1 text-right font-mono text-[10.5px] text-slate-200">{value}</td>
                      <td className="py-1 pl-2 text-right font-mono text-[9px] text-slate-500">{ref}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>

            <Panel
              title="承接自数据研究"
              sub="本图引用的推荐卡片"
              right={<V3Badge variant="info" label="来源 D-K01" />}
              note="关系 decayed → 本块置灰并提示「关系已失效」，不静默下线。"
            >
              {researchRows.length > 0 ? (
                <>
                  <div className="mb-2 flex flex-wrap gap-1">
                    {researchRows.slice(0, 3).map((row) => (
                      <span
                        key={row.eval_id}
                        className="rounded border border-slate-800 bg-slate-900 px-1.5 py-0.5 font-mono text-[9px] text-slate-400"
                      >
                        {String(row.eval_id).slice(0, 6)} · {row.relation} · h{row.horizon}
                      </span>
                    ))}
                  </div>
                  <table className="w-full">
                    <tbody>
                      <tr className="border-b border-slate-800/50">
                        <td className="py-1 text-[10.5px] text-slate-400">关系状态</td>
                        <td className="py-1 text-right">
                          <span
                            className={`rounded px-1 py-0.5 text-[9px] ${
                              STATE_STYLE[researchRows[0].status] ?? STATE_STYLE.dim
                            }`}
                          >
                            {researchRows[0].status}
                          </span>
                        </td>
                      </tr>
                      <tr className="border-b border-slate-800/50">
                        <td className="py-1 text-[10.5px] text-slate-400">最后复核</td>
                        <td className="py-1 text-right font-mono text-[10px] text-slate-300">
                          {String(researchRows[0].eval_at ?? '').slice(0, 10) || '—'}
                        </td>
                      </tr>
                      <tr>
                        <td className="py-1 text-[10.5px] text-slate-400">样本版本</td>
                        <td className="py-1 text-right font-mono text-[9px] text-slate-400">
                          {researchRows[0].data_version || '—'}
                        </td>
                      </tr>
                    </tbody>
                  </table>
                </>
              ) : (
                <p className="text-[11px] text-slate-500">数据研究暂无过门禁推荐；本图不引用未验证关系。</p>
              )}
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'feedback' && (
        <div className="grid gap-3 xl:grid-cols-[minmax(0,1.55fr)_minmax(300px,0.85fr)]">
          <Panel
            title="信号 → 结果 反馈表"
            sub="点亮日 + 合成强度分档 → 后续 5/20 日实现收益"
            right={<V3Badge variant="warning" label="只回写报告" />}
            note="conflict / unavailable 不生成信号，因此不进命中统计分母；分母必须与前端展示的样本严格一致。"
          >
            <SignalFeedback />
          </Panel>

          <div className="space-y-3">
            <Panel
              title="按强度分档命中率"
              sub="后 20 日 · 基线 50%"
              right={<V3Badge variant="default" label="n_eff 分母" />}
              note="单调性本身是证据：分档后不单调 → 合成权重需复核（回数据研究看轴权重）。"
            >
              <SignalFeedbackBuckets />
            </Panel>

            <Panel title="反馈去哪" sub="不写注册表" right={<V3Badge variant="success" label="只读闭环" />}>
              <div className="space-y-2">
                {[
                  ['信号记录', 'paper', 100],
                  ['结果回填', '5/20d', 78],
                  ['报告产出', 'json', 56],
                  ['反思建议', 'suggest', 34],
                ].map(([label, tag, width]) => (
                  <div key={String(label)} className="grid grid-cols-[82px_1fr_48px] items-center gap-2">
                    <span className="text-[10.5px] text-slate-400">{label}</span>
                    <span className="h-3 overflow-hidden rounded bg-slate-900">
                      <span className="block h-full rounded bg-indigo-500/45" style={{ width: `${width}%` }} />
                    </span>
                    <span className="text-right font-mono text-[9px] text-slate-500">{tag}</span>
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[10px] text-slate-500">
                反思只产 suggestions.json；状态迁移仍由 MERS 四门禁决定（P3 只读治理）。
              </p>
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'cross' && (
        <div className="space-y-3">
          <Panel
            title="跨资产 · D-E17 类别看板"
            sub="五类视图 + 组内排序 + 点亮计数"
            right={<V3Badge variant="info" label="D-E17" />}
            note="本子页只做展示；数据源 D-E17 + 美股龙头（pool_version 标注版本，rank_degraded 标注降级）。"
          >
            {renderVisual('table:d-e17')}
          </Panel>
          <div className="grid gap-3 xl:grid-cols-2">
            <Panel title="共振网络（D-E05）" sub="相关性投影，不画方向箭头">
              {renderVisual('graph')}
            </Panel>
            <Panel title="对齐切片（D-E12）" sub="有效观测 / 陈旧占比 / 区间收益">
              {renderVisual('table:d-e12')}
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'risk' && (
        <div className="space-y-3">
          <Panel
            title="回撤路径（D-E10）"
            sub={`${overview?.base ?? '—'} · MDD 口径同 D20`}
            right={<V3Badge variant="default" label="D-E10" />}
          >
            {renderVisual('series:d-e10')}
          </Panel>
          <div className="grid gap-3 md:grid-cols-2">
            <Panel title="回撤读数" sub="最大回撤 / 当前回撤 / 峰谷" right={<V3Badge variant="default" label="D-E10" />}>
              <table className="w-full">
                <tbody>
                  {[
                    ['最大回撤', pct(metrics?.drawdown?.mdd)],
                    ['当前回撤', pct(metrics?.drawdown?.current)],
                    ['峰值日', metrics?.drawdown?.peak_date ?? '—'],
                    ['峰→谷天数', String(metrics?.drawdown?.peak_to_trough_days ?? '—')],
                    ['回撤持续', String(metrics?.drawdown?.duration_days ?? '—')],
                    ['收复天数', metrics?.drawdown?.recovered ? String(metrics?.drawdown?.recovery_days ?? '—') : '未收复'],
                  ].map(([label, value]) => (
                    <tr key={label} className="border-b border-slate-800/50 last:border-0">
                      <td className="py-1 text-[10.5px] text-slate-400">{label}</td>
                      <td className="py-1 text-right font-mono text-[10.5px] text-slate-200">{value}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </Panel>
            <Panel title="未纳入资产" sub="缺数据或样本不足，不补造">
              {(overview?.unavailable ?? []).length === 0 ? (
                <p className="text-[11px] text-slate-500">全部资产均已纳入面板池</p>
              ) : (
                <ul className="space-y-1">
                  {(overview?.unavailable ?? []).map((row) => (
                    <li key={`${row.asset}-${row.reason}`} className="text-[11px] text-slate-400">
                      {row.asset}：{row.reason}
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </div>
      )}

      {overview && active === 'cycle' && (
        <div className="grid gap-3 xl:grid-cols-2">
          <Panel title="周期轴（I39 带通）" sub="n ≥ 750 才产周期事实" right={<V3Badge variant="default" label="D-E19 cycle" />}>
            {cycleEvidence.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {['标的', '周期强度', '状态', '周期(天)', '相位(°)'].map((head) => (
                        <th key={head} className="px-1 py-1 text-left text-[9px] font-normal text-slate-500">
                          {head}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {cycleEvidence.map((row) => (
                      <tr key={row.symbol} className="border-b border-slate-800/50 last:border-0">
                        <td className="px-1 py-1 font-mono text-[10px] text-slate-300">{row.symbol}</td>
                        <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-200">
                          {num(row.strength, 3)}
                        </td>
                        <td className="px-1 py-1">
                          <span className={`rounded px-1 py-0.5 text-[9px] ${STATE_STYLE[row.state] ?? STATE_STYLE.dim}`}>
                            {row.state}
                          </span>
                        </td>
                        <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-300">
                          {row.evidence?.period_days != null ? String(row.evidence.period_days) : '—'}
                        </td>
                        <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-400">
                          {row.evidence?.phase_deg != null ? num(Number(row.evidence.phase_deg), 0) : '—'}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <V3Empty title="周期轴无数据" description="I39 样本不足或未产出周期事实" />
            )}
            <p className="mt-2 text-[10px] text-slate-500">
              周期判断以「信号点阵」的 cycle 轴呈现；独立周期谱（D-J05）与变点（D-J04）需主标的输入序列，本页不伪造。
            </p>
          </Panel>

          <Panel title="资金流导图（D-E18）" sub="ETF 净流入 → BTC；无流数据降级相关网络" right={<V3Badge variant="default" label="D-E18" />}>
            {renderVisual('graph:d-e18')}
            <p className="mt-2 text-[10px] text-slate-500">
              资金流滚动和 / 稳定币供给 / 拥挤度在「技术分析叠加」的波动与拥挤卡呈现。
            </p>
          </Panel>
        </div>
      )}

      {overview && active === 'quality' && (
        <div className="space-y-3">
          <Panel
            title="数据口径与状态诚实"
            sub="n / gate / 状态三态；所有子页共享同一状态词表"
            right={<V3Badge variant="default" label={`${lightsRows.length} 标的`} />}
            note="前端不得自造「中性 / 观望」等新词；灰格与 unavailable 均给出原因，不补造。"
          >
            {lightsRows.length > 0 ? (
              <div className="overflow-x-auto">
                <table className="w-full">
                  <thead>
                    <tr className="border-b border-slate-800">
                      {['标的', 'n', 'min_rows', '状态', '四轴', '说明'].map((head) => (
                        <th key={head} className="px-1 py-1 text-left text-[9px] font-normal text-slate-500">
                          {head}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {lightsRows.map((row) => {
                      const state = syntheticState(row, litPct, warmPct);
                      return (
                        <tr key={row.symbol} className="border-b border-slate-800/50 last:border-0">
                          <td className="px-1 py-1 font-mono text-[10px] text-slate-300">{row.symbol}</td>
                          <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-300">{row.n ?? '—'}</td>
                          <td className="px-1 py-1 text-right font-mono text-[10px] text-slate-400">
                            {row.min_rows ?? lightMeta.min_rows ?? '—'}
                          </td>
                          <td className="px-1 py-1">
                            <span className={`rounded px-1 py-0.5 text-[9px] ${STATE_STYLE[state]}`}>{state}</span>
                          </td>
                          <td className="px-1 py-1 font-mono text-[9px] text-slate-400">
                            lit {row.summary?.lit_n ?? 0} / warm {row.summary?.warm_n ?? 0} / conflict{' '}
                            {row.summary?.conflict_n ?? 0}
                          </td>
                          <td className="px-1 py-1 text-[9px] text-slate-500">
                            {(row.flags ?? []).slice(0, 3).join(' · ') || '—'}
                          </td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            ) : (
              <V3Empty title="暂无状态行" description="点亮投影未产出" />
            )}
          </Panel>

          <Panel title="本页口径" sub="资产池 / 图规格 / 基标的分位">
            <dl className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
              {[
                ['资产数', String(overview?.assets?.length ?? 0)],
                ['图规格', String(visuals.length)],
                ['点亮标的', String(lightsRows.length)],
                ['基标的分位', percentile ? pct(percentile.value) : '—'],
              ].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-slate-800/80 bg-slate-950/40 px-2 py-1.5">
                  <dd className="font-mono text-[13px] text-slate-100">{value}</dd>
                  <dt className="mt-0.5 text-[9px] text-slate-500">{label}</dt>
                </div>
              ))}
            </dl>
            <p className="mt-2 text-[10px] text-slate-500">
              资产池：{(overview?.assets ?? []).join(' / ') || '—'}
            </p>
            <p className="mt-1 text-[10px] text-slate-500">
              降级：{overview?.degraded ? '部分能力未通过门禁' : '无'} · 图规格缺口不占位、不伪造
            </p>
          </Panel>
        </div>
      )}

      {CHAIN_HINT[active] && (
        <Panel
          title={CHAIN_HINT[active].stage}
          sub="链路内部子页（默认隐藏）"
          right={<V3Badge variant="default" label="链路内部" />}
        >
          <p className="text-[11px] text-slate-500">{CHAIN_HINT[active].detail}</p>
          <p className="mt-2 text-[10px] text-slate-600">
            该子页默认隐藏（T9-5）；对外只暴露结论与能力，不暴露候选枚举与淘汰漏斗。
          </p>
        </Panel>
      )}
    </div>
  );
}

export default TechnicalChartBoard;
