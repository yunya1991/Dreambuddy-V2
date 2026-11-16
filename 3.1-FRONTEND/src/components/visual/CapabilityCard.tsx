'use client';

// 统计能力卡（TASKS-20261116 T8-2 / T8-5；SPEC-54 R2/R3/R5）
// - 展开才取数：折叠态不请求（懒加载）
// - 走服务端装配（op=resolve），资产/基准/天数可改后重跑
// - 按返回 code 分级空态，不伪造图
// - － 删除只动看板配置，不动能力

import { useEffect, useMemo, useRef, useState } from 'react';
import { V3Badge } from '@/components/V3Badge';
import { resolveCapability, type CapabilityEnvelope, type ResolveResponse } from '@/lib/visual/api';
import type { PanelSpec } from '@/lib/visual/panelKey';
import type { VisualSpec } from './types';
import { VisualRenderer } from './VisualRenderer';

interface CapabilityCardProps {
  panel: PanelSpec;
  onRemove?: (panel: PanelSpec) => void;
  /** 参数变更回写看板配置（SPEC-54 R3b：服务端持久化的事实源） */
  onArgsChange?: (panel: PanelSpec, args: Record<string, unknown>) => void;
  defaultExpanded?: boolean;
  refreshKey?: number;
}

const CODE_HINT: Record<string, string> = {
  missing_args: '还缺参数',
  unsupported: '当前无数据源',
  product_missing: '上游产物未生成',
  no_signal: '当前无信号通过门禁',
  sample_insufficient: '样本不足',
  invalid_params: '参数不合法',
};

const DEFAULT_SYMBOL = 'BTC';
const DEFAULT_BENCHMARK = 'US500';
const DEFAULT_DAYS = 750;
// 与 config.ts / capability_resolve.py 同一口径（R2 决策 1）

export function CapabilityCard({
  panel,
  onRemove,
  onArgsChange,
  defaultExpanded = true,
  refreshKey = 0,
}: CapabilityCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded && !panel.collapsed);
  const [result, setResult] = useState<ResolveResponse | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [editing, setEditing] = useState(false);
  const [nonce, setNonce] = useState(0);
  const [symbol, setSymbol] = useState(String(panel.args?.symbol ?? DEFAULT_SYMBOL));
  const [benchmark, setBenchmark] = useState(String(panel.args?.benchmark ?? DEFAULT_BENCHMARK));
  const [days, setDays] = useState(String(panel.args?.days ?? DEFAULT_DAYS));

  const argsKey = useMemo(() => JSON.stringify(panel.args ?? {}), [panel.args]);
  const effectiveArgs = useMemo(
    () => ({ ...(panel.args ?? {}), symbol, benchmark, days: Number(days) || DEFAULT_DAYS }),
    [panel.args, symbol, benchmark, days],
  );
  // 最近一次已发起的查询签名；依赖变化才重取（不再用 loading 做 guard，避免 cleanup 后永久骨架）
  const lastQueryRef = useRef('');
  const requestIdRef = useRef(0);

  useEffect(() => {
    if (!expanded) return;
    const queryKey = [panel.capability_id, argsKey, refreshKey, nonce, symbol, benchmark, days].join('|');
    if (lastQueryRef.current === queryKey) return;
    lastQueryRef.current = queryKey;

    // 不用 cleanup 取消：被新请求取代的响应按 requestId 丢弃，
    // 保证最后发起的那次一定会关闭 loading（否则依赖变化会让骨架屏永不结束）。
    const requestId = ++requestIdRef.current;
    setLoading(true);
    setResult(null);
    setFailure(null);
    resolveCapability(panel.capability_id, effectiveArgs)
      .then((response) => {
        if (requestIdRef.current !== requestId) return;
        setResult(response);
        if (!response.ok) setFailure(response.reason || response.code || 'capability_failed');
      })
      .catch((error: unknown) => {
        if (requestIdRef.current !== requestId) return;
        setFailure(error instanceof Error ? error.message : 'fetch_failed');
      })
      .finally(() => {
        if (requestIdRef.current === requestId) setLoading(false);
      });
  }, [expanded, panel.capability_id, argsKey, refreshKey, nonce, symbol, benchmark, days, effectiveArgs]);

  const envelope: CapabilityEnvelope | null = result?.data ?? null;
  const code = result?.code ?? (failure ? 'error' : '');
  const qualityStatus = result?.quality?.status ?? envelope?.quality?.status;
  const degradedReason =
    result?.quality?.degraded_reason ?? envelope?.quality?.degraded_reason ?? result?.reason;
  // 信封把图规格放在 data.visual（部分旧出口放顶层 visual），两处都认
  const visual: VisualSpec | null =
    (envelope?.visual as VisualSpec | undefined) ??
    ((envelope?.data as Record<string, unknown> | undefined)?.visual as VisualSpec | undefined) ??
    null;
  const kind = visual?.kind ?? panel.kind;

  const rerun = () => {
    onArgsChange?.(panel, effectiveArgs);
    setEditing(false);
    setNonce((value) => value + 1);
  };

  return (
    <section className="rounded-xl border border-slate-800 bg-slate-900/40 min-w-0">
      <header className="flex items-center justify-between gap-2 px-3.5 py-2.5">
        <button
          type="button"
          onClick={() => setExpanded((value) => !value)}
          className="flex min-w-0 items-center gap-2 text-left"
          aria-expanded={expanded}
        >
          <span className="w-3 text-[11px] text-slate-500">{expanded ? '▾' : '▸'}</span>
          <span className="truncate text-[12.5px] font-medium text-slate-200">{panel.title}</span>
          <code className="rounded border border-slate-800 bg-slate-950/60 px-1.5 py-0.5 text-[10px] text-slate-500">
            {panel.capability_id}
          </code>
          {kind && <V3Badge variant="default" label={kind} />}
        </button>
        <div className="flex shrink-0 items-center gap-1">
          <button
            type="button"
            onClick={() => setEditing((value) => !value)}
            className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-800 hover:text-slate-200"
          >
            参数
          </button>
          <button
            type="button"
            onClick={() => setExpanded((value) => !value)}
            className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-slate-800 hover:text-slate-200"
          >
            {expanded ? '折叠' : '展开'}
          </button>
          {onRemove && (
            <button
              type="button"
              title="移除卡片（只删配置，不删能力）"
              onClick={() => onRemove(panel)}
              className="rounded-md px-1.5 py-0.5 text-[11px] text-slate-500 hover:bg-rose-500/10 hover:text-rose-400"
            >
              －
            </button>
          )}
        </div>
      </header>

      {editing && (
        <div className="flex flex-wrap items-end gap-2 border-t border-slate-800/80 px-3.5 py-2.5 text-[11px] text-slate-400">
          <label className="flex flex-col gap-1">
            资产
            <input
              value={symbol}
              onChange={(event) => setSymbol(event.target.value.toUpperCase())}
              className="w-24 rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-slate-200"
            />
          </label>
          <label className="flex flex-col gap-1">
            基准
            <input
              value={benchmark}
              onChange={(event) => setBenchmark(event.target.value.toUpperCase())}
              className="w-24 rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-slate-200"
            />
          </label>
          <label className="flex flex-col gap-1">
            天数
            <input
              value={days}
              onChange={(event) => setDays(event.target.value.replace(/[^0-9]/g, ''))}
              className="w-20 rounded border border-slate-700 bg-slate-950/60 px-2 py-1 text-slate-200"
            />
          </label>
          <button
            type="button"
            onClick={rerun}
            className="rounded-md border border-sky-500/40 bg-sky-500/10 px-2 py-1 text-sky-300 hover:bg-sky-500/20"
          >
            重跑
          </button>
        </div>
      )}

      {expanded && (
        <div className="border-t border-slate-800/80 px-3.5 py-3">
          {loading && <div className="h-16 animate-pulse rounded-lg bg-slate-800/40" />}

          {!loading && code && code !== 'ok' && (
            <div className="space-y-1">
              <p className="text-[11px] text-amber-400">
                {CODE_HINT[code] ?? '降级'}：{degradedReason || code}
              </p>
              {result?.missing_params && result.missing_params.length > 0 && (
                <p className="text-[10px] text-slate-500">缺参数：{result.missing_params.join('、')}</p>
              )}
            </div>
          )}

          {!loading && !code && failure && (
            <p className="text-[11px] text-rose-400">降级：{failure}（能力不可用时不伪造图）</p>
          )}

          {!loading && code === 'ok' && envelope && (
            <div className="space-y-2">
              {visual ? (
                <VisualRenderer visual={visual} showTitle={false} />
              ) : (
                <p className="text-[11px] text-slate-400">{envelope.answer || '无图输出'}</p>
              )}
              <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                <span>status {qualityStatus ?? '—'}</span>
                {qualityStatus === 'partial' && degradedReason && <span>· {degradedReason}</span>}
                {result?.quality?.n != null && <span>· n {result.quality.n}</span>}
                {result?.meta?.warmup_trimmed ? <span>· warmup {result.meta.warmup_trimmed}</span> : null}
              </div>
            </div>
          )}

          {!loading && !code && !failure && !envelope && (
            <p className="text-[11px] text-slate-500">尚未取数</p>
          )}
        </div>
      )}
    </section>
  );
}

export default CapabilityCard;
