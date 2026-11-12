'use client';

/**
 * 架构工程地图视图 — dev-only（M0 静态地图 + M1 运行时点亮 + M2 导出/载入）
 *
 * 设计约束（ARCH_ENGINEERING_MAP_SPEC.md）：
 *   - 不引入图可视化库：纯 Tailwind + 泳道卡片 + 聚合边排行
 *   - 拓扑来自投影产物（不手写），这里只做展示与运行态叠加
 */

import { useMemo, useRef } from 'react';
import {
  LAYER_COLORS,
  type ArchMapData,
  type ArchMapEdge,
  type ArchMapNode,
  type ArchMapRuntimeExport,
  type CapMapData,
} from '@/lib/arch-map/types';
import { useArchMapLive } from './useArchMapLive';

const STALE_DAYS = 7;
const EDGE_LIMIT = 30;

const stateRing: Record<string, string> = {
  active: 'border-emerald-400/80 bg-emerald-500/10 shadow-[0_0_0_1px_rgba(52,211,153,0.35)]',
  failed: 'border-rose-500/80 bg-rose-500/10 shadow-[0_0_0_1px_rgba(244,63,94,0.4)]',
  warm: 'border-amber-400/50 bg-amber-500/5',
  idle: 'border-slate-700/80 bg-slate-900/40',
};

const stateDot: Record<string, string> = {
  active: 'bg-emerald-400 animate-pulse',
  failed: 'bg-rose-500 animate-pulse',
  warm: 'bg-amber-400',
  idle: 'bg-slate-600',
};

const stateLabel: Record<string, string> = {
  active: '运行中',
  failed: '失败',
  warm: '近期',
  idle: '静默',
};

function fmtLoc(n: number): string {
  if (n >= 10000) return `${(n / 10000).toFixed(1)}w`;
  if (n >= 1000) return `${(n / 1000).toFixed(1)}k`;
  return String(n);
}

function ageDays(iso: string): number | null {
  const ts = Date.parse(iso);
  if (Number.isNaN(ts)) return null;
  return (Date.now() - ts) / 86_400_000;
}

export function ArchMapView({ data, capMap }: { data: ArchMapData; capMap: CapMapData }) {
  const { caps, ghosts, stateMap, connected, error, reset, hydrate, buildExport } =
    useArchMapLive(capMap);
  const fileRef = useRef<HTMLInputElement>(null);

  const layers = useMemo(() => {
    const ordered = ['S', 'A', 'C', 'G', 'X'];
    const labelOf = new Map(data.layers.map((l) => [l.id, l.label]));
    const present = Array.from(new Set(data.nodes.map((n) => n.layer)));
    const ids = [...ordered.filter((id) => present.includes(id)), ...present.filter((p) => !ordered.includes(p))];
    return ids.map((id) => ({
      id,
      label: labelOf.get(id) ?? id,
      nodes: data.nodes
        .filter((n) => n.layer === id)
        .sort((a, b) => b.files - a.files || a.id.localeCompare(b.id)),
    }));
  }, [data]);

  const degree = useMemo(() => {
    const inOut = new Map<string, { in: number; out: number }>();
    const bump = (id: string, key: 'in' | 'out') => {
      const cur = inOut.get(id) ?? { in: 0, out: 0 };
      cur[key] += 1;
      inOut.set(id, cur);
    };
    for (const e of data.edges) {
      bump(e.dst, 'in');
      bump(e.src, 'out');
    }
    return inOut;
  }, [data.edges]);

  const topEdges = useMemo(
    () => [...data.edges].sort((a, b) => b.weight - a.weight).slice(0, EDGE_LIMIT),
    [data.edges],
  );

  const litCaps = Object.keys(caps).length;
  const failedCaps = Object.entries(stateMap).filter(([, s]) => s === 'failed').map(([id]) => id);
  const stale = ageDays(data.generated_at);

  const onExport = () => {
    const payload = buildExport();
    const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `arch-map-runtime-${new Date().toISOString().replace(/[:.]/g, '-')}.json`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const onImport = (file: File | undefined) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = () => {
      try {
        hydrate(JSON.parse(String(reader.result)) as ArchMapRuntimeExport);
      } catch {
        // 静默失败：仅开发工具，不阻塞
      }
    };
    reader.readAsText(file);
  };

  return (
    <div className="min-h-screen bg-slate-950 px-4 py-5 text-slate-200">
      <header className="mb-4 flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-lg font-semibold tracking-wide">架构工程地图</h1>
          <p className="mt-1 text-xs text-slate-500">
            SACG 能力投影 · 拓扑自动生成 · 仅开发阶段使用
          </p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className="flex items-center gap-1.5">
            <span className={`h-2 w-2 rounded-full ${connected ? 'bg-emerald-400' : 'bg-slate-600'}`} />
            {connected ? 'SSE 已连接' : 'SSE 未连接'}
          </span>
          <span className="text-slate-500">
            能力 {data.nodes.length} · 边 {data.edges.length} · 图中文件 {data.source.node_count}
          </span>
          <span className={stale !== null && stale > STALE_DAYS ? 'text-amber-400' : 'text-slate-500'}>
            生成于 {data.generated_at.slice(0, 19).replace('T', ' ')}
            {stale !== null && stale > STALE_DAYS ? `（${Math.floor(stale)} 天未重建）` : ''}
          </span>
        </div>
      </header>

      <div className="mb-4 flex flex-wrap items-center gap-2 text-xs">
        <button
          type="button"
          onClick={onExport}
          className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 hover:border-slate-500"
        >
          导出本次点亮
        </button>
        <button
          type="button"
          onClick={() => fileRef.current?.click()}
          className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 hover:border-slate-500"
        >
          载入历史运行态
        </button>
        <button
          type="button"
          onClick={reset}
          className="rounded border border-slate-700 bg-slate-900 px-2.5 py-1 hover:border-slate-500"
        >
          重置
        </button>
        <input
          ref={fileRef}
          type="file"
          accept="application/json"
          className="hidden"
          onChange={(e) => onImport(e.target.files?.[0])}
        />
        <span className="ml-2 text-slate-500">
          已点亮 {litCaps} / {data.nodes.length}
          {failedCaps.length > 0 && <span className="ml-2 text-rose-400">失败 {failedCaps.length}</span>}
        </span>
        {error && <span className="text-amber-400">{error}</span>}
      </div>

      {Object.keys(ghosts).length > 0 && (
        <div className="mb-4 rounded border border-fuchsia-500/50 bg-fuchsia-500/10 px-3 py-2 text-xs text-fuchsia-200">
          ghost（运行态出现但图中不存在，规则表可能过期）：{Object.keys(ghosts).join(', ')}
        </div>
      )}

      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-5">
        {layers.map((lane) => (
          <section key={lane.id} className="rounded-lg border border-slate-800 bg-slate-900/30">
            <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
              <span className="flex items-center gap-2 text-sm font-medium">
                <span
                  className="h-2.5 w-2.5 rounded-full"
                  style={{ backgroundColor: LAYER_COLORS[lane.id] ?? '#64748b' }}
                />
                {lane.id} · {lane.label}
              </span>
              <span className="text-[10px] text-slate-500">{lane.nodes.length}</span>
            </div>
            <div className="flex flex-col gap-1.5 p-2">
              {lane.nodes.map((node) => (
                <CapCard
                  key={node.id}
                  node={node}
                  state={stateMap[node.id] ?? 'idle'}
                  hits={caps[node.id]?.hits ?? 0}
                  failed={caps[node.id]?.failed ?? 0}
                  duration={caps[node.id]?.lastDurationMs}
                  degree={degree.get(node.id)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>

      <section className="mt-4 rounded-lg border border-slate-800 bg-slate-900/30">
        <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2 text-sm">
          <span>聚合边 Top {topEdges.length}</span>
          <span className="text-[10px] text-slate-500">import / call / doc_ref 按能力聚合</span>
        </div>
        <div className="grid gap-x-6 gap-y-1 p-3 text-xs md:grid-cols-2 xl:grid-cols-3">
          {topEdges.map((edge) => (
            <EdgeRow
              key={`${edge.src}->${edge.dst}:${edge.kind}`}
              edge={edge}
              live={stateMap[edge.src] === 'active' || stateMap[edge.dst] === 'active'}
              failed={stateMap[edge.src] === 'failed' || stateMap[edge.dst] === 'failed'}
            />
          ))}
        </div>
      </section>

      <footer className="mt-4 flex flex-wrap gap-4 text-[10px] text-slate-600">
        <span>未映射目录 {data.unmapped.dirs.length} · 未映射文件 {data.unmapped.files}</span>
        <span>结构 sha {data.source.graph_sha256.slice(0, 12)}</span>
        <span title={data.unmapped.dirs.join('\n')} className="cursor-help underline decoration-dotted">
          查看未映射目录
        </span>
        <span>数据流为静态 import/call 聚合，非运行时链路</span>
      </footer>
    </div>
  );
}

function CapCard({
  node,
  state,
  hits,
  failed,
  duration,
  degree,
}: {
  node: ArchMapNode;
  state: string;
  hits: number;
  failed: number;
  duration?: number;
  degree?: { in: number; out: number };
}) {
  const empty = node.files === 0;
  return (
    <div
      className={`rounded border px-2 py-1.5 transition-colors ${stateRing[state] ?? stateRing.idle} ${
        node.orphan ? 'border-dashed border-amber-500/70' : ''
      }`}
      title={node.owner_paths.join('\n')}
    >
      <div className="flex items-center justify-between gap-2">
        <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${stateDot[state] ?? stateDot.idle}`} />
        <span className="flex-1 truncate text-xs font-medium">{node.label}</span>
        {empty && <span className="shrink-0 text-[9px] text-slate-500">未入图</span>}
        {node.orphan && <span className="shrink-0 text-[9px] text-amber-400">孤立</span>}
      </div>
      <div className="mt-0.5 flex items-center justify-between gap-2 text-[10px] text-slate-500">
        <span className="truncate font-mono">{node.id}</span>
        <span className="shrink-0">
          {node.files}f/{fmtLoc(node.loc)}
        </span>
      </div>
      <div className="mt-0.5 flex items-center justify-between text-[10px]">
        <span className="text-slate-600">
          ↓{degree?.in ?? 0} ↑{degree?.out ?? 0}
        </span>
        <span className="flex items-center gap-1.5">
          {hits > 0 && <span className="text-emerald-400">{hits} 次</span>}
          {failed > 0 && <span className="text-rose-400">{failed} 失败</span>}
          {typeof duration === 'number' && duration > 0 && (
            <span className="text-slate-600">{duration}ms</span>
          )}
          <span className="text-slate-600">{stateLabel[state] ?? state}</span>
        </span>
      </div>
    </div>
  );
}

function EdgeRow({ edge, live, failed }: { edge: ArchMapEdge; live: boolean; failed: boolean }) {
  return (
    <div className="flex items-center gap-2">
      <span
        className={`h-1.5 w-1.5 shrink-0 rounded-full ${
          failed ? 'bg-rose-500' : live ? 'bg-emerald-400' : 'bg-slate-700'
        }`}
      />
      <span className="truncate font-mono text-[10px] text-slate-400">
        {edge.src} → {edge.dst}
      </span>
      <span className="ml-auto shrink-0 text-[10px] text-slate-600">{edge.kind}</span>
      <span className="w-8 shrink-0 text-right font-mono text-[10px] text-slate-400">{edge.weight}</span>
    </div>
  );
}
