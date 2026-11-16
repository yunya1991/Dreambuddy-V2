'use client';

// 统计能力卡（TASKS-20261116 T8-2 / T8-5）
// - 展开才取数：折叠态不请求（懒加载）
// - 只渲染后端信封里的 visual，缺失时退回 answer / quality，不伪造图
// - － 删除只动看板配置，不动能力

import { useEffect, useMemo, useState } from 'react';
import { V3Badge } from '@/components/V3Badge';
import { runCapability, type CapabilityEnvelope } from '@/lib/visual/api';
import type { PanelSpec } from '@/lib/visual/panelKey';
import type { VisualSpec } from './types';
import { VisualRenderer } from './VisualRenderer';

interface CapabilityCardProps {
  panel: PanelSpec;
  onRemove?: (panel: PanelSpec) => void;
  defaultExpanded?: boolean;
  refreshKey?: number;
}

/** 纯函数能力缺输入序列时后端返 invalid_params；与真实故障区分开，避免误报「不可用」 */
function needsInputArgs(failure: string): boolean {
  return /invalid_params|missing \d+ required positional|invalid payload/i.test(failure);
}

export function CapabilityCard({
  panel,
  onRemove,
  defaultExpanded = true,
  refreshKey = 0,
}: CapabilityCardProps) {
  const [expanded, setExpanded] = useState(defaultExpanded && !panel.collapsed);
  const [envelope, setEnvelope] = useState<CapabilityEnvelope | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [loaded, setLoaded] = useState(false);

  const argsKey = useMemo(() => JSON.stringify(panel.args ?? {}), [panel.args]);

  useEffect(() => {
    setLoaded(false);
    setEnvelope(null);
    setFailure(null);
  }, [panel.capability_id, argsKey, refreshKey]);

  useEffect(() => {
    if (!expanded || loaded || loading) return;
    let alive = true;
    setLoading(true);
    runCapability(panel.capability_id, panel.args ?? {})
      .then((response) => {
        if (!alive) return;
        if (!response.ok) {
          setFailure(response.reason || 'capability_failed');
          setLoaded(true);
          return;
        }
        setEnvelope(response.result || null);
        setLoaded(true);
      })
      .catch((error: unknown) => {
        if (!alive) return;
        setFailure(error instanceof Error ? error.message : 'fetch_failed');
        setLoaded(true);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [expanded, loaded, loading, panel.capability_id, argsKey, refreshKey]); // eslint-disable-line react-hooks/exhaustive-deps

  const qualityStatus = envelope?.quality?.status;
  const degradedReason = envelope?.quality?.degraded_reason;
  // 信封把图规格放在 data.visual（部分旧出口放顶层 visual），两处都认
  const visual: VisualSpec | null =
    (envelope?.visual as VisualSpec | undefined) ??
    ((envelope?.data as Record<string, unknown> | undefined)?.visual as VisualSpec | undefined) ??
    null;
  const kind = visual?.kind ?? panel.kind;

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

      {expanded && (
        <div className="border-t border-slate-800/80 px-3.5 py-3">
          {loading && <div className="h-16 animate-pulse rounded-lg bg-slate-800/40" />}

          {!loading && failure && needsInputArgs(failure) && (
            <p className="text-[11px] text-amber-400" title={failure}>
              需要输入序列：该能力是纯函数入口，需在「＋ 能力库」预览并补齐参数后才取数（不伪造图）
            </p>
          )}

          {!loading && failure && !needsInputArgs(failure) && (
            <p className="text-[11px] text-rose-400">降级：{failure}（能力不可用时不伪造图）</p>
          )}

          {!loading && !failure && envelope && (
            <div className="space-y-2">
              {visual ? (
                <VisualRenderer visual={visual} showTitle={false} />
              ) : (
                <p className="text-[11px] text-slate-400">{envelope.answer || '无图输出'}</p>
              )}
              <div className="flex flex-wrap items-center gap-2 text-[10px] text-slate-500">
                <span>status {qualityStatus ?? '—'}</span>
                {qualityStatus === 'empty' && degradedReason && <span>· {degradedReason}</span>}
                {envelope.quality?.sample_n != null && <span>· n {envelope.quality.sample_n}</span>}
              </div>
            </div>
          )}

          {!loading && !failure && !envelope && (
            <p className="text-[11px] text-slate-500">尚未取数</p>
          )}
        </div>
      )}
    </section>
  );
}

export default CapabilityCard;
