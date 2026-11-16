'use client';

// 技术图表（TASKS-20261116 T9-1 ~ T9-5）
// 8 个主视图 + 5 个链路子页（S1–S5，默认隐藏，开关关闭时菜单不出现）。
// 与「数据研究」单向承接：这里只读图与证据，不改推荐；无后端来源的层不画（不伪造）。

import { useEffect, useMemo, useState } from 'react';
import { V3Badge, V3Empty } from '@/components';
import { LightsTimeline, type LightsPeriod } from './LightsTimeline';
import { OverlayChart, type OverlaySource } from './OverlayChart';
import { SignalFeedback } from './SignalFeedback';
import { SignalMatrix } from './SignalMatrix';
import { VisualRenderer } from './VisualRenderer';
import type { VisualOverview, VisualPoint, VisualSpec } from './types';

const CHAIN_KEY = 'dreambuddy.visual.chain.v1';

interface TabDef {
  id: string;
  label: string;
  chain?: boolean;
}

const TABS: TabDef[] = [
  { id: 'signals', label: '信号点阵' },
  { id: 'lights', label: '点亮图影' },
  { id: 'overlay', label: '技术叠加' },
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
  targets: {
    stage: 'S1 目标与覆盖',
    detail: '覆盖资产池与缺口由后端 D-E12 / J29 产出，属流水线内部口径，不对外铺开。',
  },
  taxonomy: {
    stage: 'S2 算法分类',
    detail: '关系类型分类（趋势/形态/周期/惯性/前瞻）由发现流水线完成，前端不枚举候选。',
  },
  patterns: {
    stage: 'S3 现象归纳',
    detail: '同类现象去重与主类归并在 patterns.json；对外只在「数据研究」以推荐卡呈现。',
  },
  gates: {
    stage: 'S4 假设验证',
    detail: 'G0–G6 门禁与 BH-FDR 结果落在关系评估注册表；此处仅供研发核对，不对外解释。',
  },
  cards: {
    stage: 'S5 数据卡片',
    detail: '能力出口卡片在「数据研究」按需添加；技术图表只消费已产出的图规格。',
  },
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

export function TechnicalChartBoard() {
  const [overview, setOverview] = useState<VisualOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [active, setActive] = useState('signals');
  const [showChain, setShowChain] = useState(false);
  const [periods, setPeriods] = useState<LightsPeriod[]>([]);
  const [historyLoading, setHistoryLoading] = useState(false);
  const [historyError, setHistoryError] = useState('');

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

  const visuals = useMemo(() => overview?.visuals ?? [], [overview]);
  const byId = useMemo(
    () => new Map(visuals.map((visual) => [visual.id ?? '', visual])),
    [visuals],
  );
  const lightsRows = overview?.lights?.rows ?? [];

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
        if (history.length === 0) {
          setHistoryError(payload.lights?.history_error || '后端未回放出历史期（不补造）');
          return;
        }
        setPeriods(history.map((item) => ({ as_of: item.as_of, rows: item.rows })));
      })
      .catch((err: unknown) => {
        setHistoryError(err instanceof Error ? err.message : 'history_failed');
      })
      .finally(() => setHistoryLoading(false));
  }

  function toggleChain(next: boolean) {
    setShowChain(next);
    writeChainFlag(next);
    if (!next && TABS.find((tab) => tab.id === active)?.chain) setActive('signals');
  }

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
          // D-A04 的 percentile 是 0–100 口径，这里只做单位换算与截断，不改数值
          value: Math.max(0, Math.min(1, percentileRaw.value / 100)),
          lookback: percentileRaw.lookback ?? null,
          sample_n: percentileRaw.sample_n ?? null,
        }
      : null;

  const litDays = Array.from(
    new Set(lightsRows.map((row) => row.as_of).filter((day): day is string => Boolean(day))),
  );

  const overlaySources: OverlaySource[] = [
    {
      id: 'price',
      label: '价格',
      capability: 'D-E15',
      status: overlayPoints.length > 0 ? 'ok' : 'missing',
    },
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
      detail: '后端暂未提供 atr_upper/atr_lower，缺失时该层不画',
    },
    {
      id: 'percentile',
      label: '历史分位',
      capability: 'D-A04',
      status: percentile ? 'ok' : 'missing',
    },
    {
      id: 'lights',
      label: '点亮日',
      capability: 'D-E19',
      status: litDays.length > 0 ? 'ok' : 'missing',
    },
  ];

  return (
    <div className="space-y-4">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold text-slate-100">技术图表</h1>
          <p className="mt-1 text-xs text-slate-500">
            读图工作台：信号点阵 / 点亮影带 / 技术叠加 / 信号反馈；承接「数据研究」的推荐锚点，不给买卖方向
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {overview?.as_of && <V3Badge variant="info" label={`数据截至 ${overview.as_of}`} />}
          {overview?.degraded && <V3Badge variant="warning" label="部分降级" />}
          <label className="flex cursor-pointer items-center gap-1.5 rounded-full border border-slate-800 bg-slate-900 px-2.5 py-0.5 text-[11px] text-slate-400">
            <input
              type="checkbox"
              checked={showChain}
              onChange={(event) => toggleChain(event.target.checked)}
              className="h-3 w-3 accent-indigo-500"
            />
            链路子页（S1–S5）
          </label>
        </div>
      </header>

      {error && (
        <V3Empty title="图表服务暂不可用" description={`${error}；可稍后刷新重试`} />
      )}

      <nav className="flex items-center gap-1 overflow-x-auto border-b border-slate-800 pb-1">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActive(tab.id)}
            className={`shrink-0 rounded-t-md px-3 py-1.5 text-xs ${
              tab.id === active
                ? 'bg-indigo-500/10 text-indigo-200'
                : 'text-slate-400 hover:text-slate-200'
            } ${tab.chain ? 'opacity-80' : ''}`}
          >
            {tab.label}
            {tab.chain && <span className="ml-1 font-mono text-[9px] opacity-60">链路</span>}
          </button>
        ))}
      </nav>

      {loading && !overview && <div className="h-24 animate-pulse rounded-lg bg-slate-800/40" />}

      {active === 'signals' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-[12.5px] font-medium text-slate-200">
              加权信号点阵（资产 × 四轴 + 合成）
            </p>
            <span className="font-mono text-[10px] text-slate-500">D-E19 · 前端零重算</span>
          </div>
          {byId.get('matrix:signals') ? (
            <SignalMatrix visual={byId.get('matrix:signals') as VisualSpec} />
          ) : (
            <V3Empty
              title="点阵无数据"
              description="后端未产出 matrix:signals（点亮输入样本不足）"
            />
          )}
        </section>
      )}

      {active === 'lights' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-[12.5px] font-medium text-slate-200">点亮图影（标的 × as_of）</p>
            <span className="font-mono text-[10px] text-slate-500">D-E19 逐期回放</span>
          </div>
          <LightsTimeline
            periods={currentPeriods}
            loading={historyLoading}
            error={historyError}
            onRequestHistory={loadHistory}
            historyCount={24}
          />
        </section>
      )}

      {active === 'overlay' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-[12.5px] font-medium text-slate-200">
              技术分析叠加（价格 + MA + ATR 带 + 分位条 + 点亮日）
            </p>
            <span className="font-mono text-[10px] text-slate-500">
              {overview?.base ?? '—'} · 叠加层均标注来源
            </span>
          </div>
          <OverlayChart
            points={overlayPoints}
            smoothing={overlayMeta.smoothing}
            unit={overlayMeta.unit}
            percentile={percentile}
            litDays={litDays}
            sources={overlaySources}
          />
        </section>
      )}

      {active === 'feedback' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <div className="mb-2 flex items-center justify-between gap-2">
            <p className="text-[12.5px] font-medium text-slate-200">信号反馈（后 5 / 20 日）</p>
            <span className="font-mono text-[10px] text-slate-500">
              signal_journal · 非重叠 n_eff
            </span>
          </div>
          <SignalFeedback />
        </section>
      )}

      {active === 'cross' && (
        <div className="grid gap-3 xl:grid-cols-2">
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">共振网络（D-E05）</p>
            {renderVisual('graph')}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">对齐切片（D-E12）</p>
            {renderVisual('table:d-e12')}
          </section>
        </div>
      )}

      {active === 'risk' && (
        <div className="grid gap-3 xl:grid-cols-2">
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">回撤路径（D-E10）</p>
            {renderVisual('series:d-e10')}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">未纳入资产</p>
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
          </section>
        </div>
      )}

      {active === 'cycle' && (
        <div className="grid gap-3 xl:grid-cols-2">
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">资金流导图（D-E18）</p>
            {renderVisual('graph:d-e18')}
          </section>
          <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
            <p className="mb-2 text-[12.5px] font-medium text-slate-200">周期轴（D-E19 cycle）</p>
            <p className="text-[11px] text-slate-500">
              周期判断以「信号点阵」的 cycle 轴呈现；独立周期谱（D-J05）与变点（D-J04）需主标的输入序列，
              当前未在该页提供，缺失时不画。
            </p>
          </section>
        </div>
      )}

      {active === 'quality' && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <p className="mb-2 text-[12.5px] font-medium text-slate-200">数据口径</p>
          <dl className="grid grid-cols-2 gap-2 text-[11px] sm:grid-cols-4">
            {[
              ['资产数', String(overview?.assets?.length ?? 0)],
              ['图规格', String(visuals.length)],
              ['点亮标的', String(lightsRows.length)],
              ['基标的分位', percentile ? `${(percentile.value * 100).toFixed(0)}%` : '—'],
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
        </section>
      )}

      {CHAIN_HINT[active] && (
        <section className="rounded-xl border border-slate-800 bg-slate-900/40 p-3.5">
          <div className="mb-1 flex items-center gap-2">
            <V3Badge variant="default" label="链路内部" />
            <p className="text-[12.5px] font-medium text-slate-200">{CHAIN_HINT[active].stage}</p>
          </div>
          <p className="text-[11px] text-slate-500">{CHAIN_HINT[active].detail}</p>
          <p className="mt-2 text-[10px] text-slate-600">
            该子页默认隐藏（T9-5）；对外只暴露结论与能力，不暴露候选枚举与淘汰漏斗。
          </p>
        </section>
      )}
    </div>
  );
}

export default TechnicalChartBoard;
