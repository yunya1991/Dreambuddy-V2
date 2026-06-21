"use client";

import { useMemo, useState } from "react";

/**
 * 图结构压缩可视化组件
 *
 * 展示：
 *   1. 压缩前后三层图对比（Blueprint / Architecture / Chronicle）
 *   2. 节点时间线 + 保留/压缩状态 + 评分
 *   3. 统计摘要
 *
 * 数据来源：createCompressor().getVisualizationData() 或 buildVisualization()
 */

export interface VizNode {
  id: string;
  name: string;
  layer: "B" | "A" | "C";
  score?: number;
  compressed?: boolean;
  status?: string;
  summary?: string;
  timestamp?: number;
}

export interface VizLayer {
  nodes: VizNode[];
}

export interface VisualizationData {
  before: {
    B: VizLayer;
    A: VizLayer;
    C: VizLayer;
  };
  after: {
    B: VizLayer;
    A: VizLayer;
    C: VizLayer;
  };
  diff: {
    retained: string[];
    compressed: string[];
    compressionRatio: number;
    avgRetainedScore: number;
    avgCompressedScore: number;
  };
  stats: {
    totalNodesBefore: number;
    totalNodesAfter: number;
    nodesByLayerBefore: { B: number; A: number; C: number };
    nodesByLayerAfter: { B: number; A: number; C: number };
    retainedContext: number;
    compressionRatio: number;
  };
  timeline: Array<{
    id: string;
    name: string;
    kept: boolean;
    score: number;
    status: string;
    timestamp: number;
  }>;
  discarded?: Array<{ nodeId: string; reason: string }>;
}

interface Props {
  data: VisualizationData;
  title?: string;
  onClose?: () => void;
  defaultOpen?: boolean;
}

const COLORS = {
  retained: "#10b981",
  compressed: "#94a3b8",
  blueprint: "#6366f1",
  architecture: "#f59e0b",
  chronicle: "#0ea5e9",
};

export function GraphCompressionVisualizer({
  data,
  title = "图结构压缩可视化",
  onClose,
  defaultOpen = true,
}: Props) {
  const [isOpen, setIsOpen] = useState<boolean>(defaultOpen);
  const [showDiscarded, setShowDiscarded] = useState(false);

  const summary = useMemo(() => {
    const ratio = data.stats.compressionRatio;
    const retained = data.diff.retained.length;
    const compressed = data.diff.compressed.length;
    const total = retained + compressed;
    return {
      ratio: `${(ratio * 100).toFixed(0)}%`,
      retained,
      compressed,
      totalBefore: data.stats.totalNodesBefore,
      totalAfter: data.stats.totalNodesAfter,
      keptPct: total > 0 ? (retained / total) * 100 : 0,
    };
  }, [data]);

  if (!isOpen) {
    return (
      <div className="p-4 rounded-lg border bg-white/5 border-slate-800 text-slate-300 text-sm text-center">
        <span className="mr-2">📊 {title}</span>
        <button
          onClick={() => setIsOpen(true)}
          className="text-sky-400 hover:text-sky-300 underline">
          展开
        </button>
      </div>
    );
  }

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-900/50 text-slate-300 p-6">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-3">
          <span className="text-lg">📊</span>
          <h3 className="text-lg font-semibold text-white">{title}</h3>
        </div>
        {onClose && (
          <button
            onClick={() => {
              setIsOpen(false);
              onClose();
            }}
            className="text-slate-400 hover:text-white text-sm">
            关闭
          </button>
        )}
      </div>

      {/* 统计摘要 */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 mb-6">
        <SummaryCard
          label="压缩比"
          value={summary.ratio}
          sub={`保留 ${summary.retained} / ${summary.totalBefore} 节点`}
          color={COLORS.blueprint}
        />
        <SummaryCard
          label="保留节点"
          value={String(summary.retained)}
          sub={`${summary.keptPct.toFixed(0)}% 保留`}
          color={COLORS.retained}
        />
        <SummaryCard
          label="压缩节点"
          value={String(summary.compressed)}
          sub={`${(100 - summary.keptPct).toFixed(0)}% 压缩`}
          color={COLORS.compressed}
        />
        <SummaryCard
          label="三层节点分布（B / A / C）"
          value={`${data.stats.nodesByLayerBefore.B} / ${data.stats.nodesByLayerBefore.A} / ${data.stats.nodesByLayerBefore.C}`}
          sub={`压缩后 ${data.stats.nodesByLayerAfter.B} / ${data.stats.nodesByLayerAfter.A} / ${data.stats.nodesByLayerAfter.C}`}
          color={COLORS.blueprint}
        />
      </div>

      {/* 三层图对比 */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4 mb-6">
        <LayerPanel
          title="B 层 · Blueprint 架构"
          color={COLORS.blueprint}
          before={data.before.B}
          after={data.after.B}
        />
        <LayerPanel
          title="A 层 · Architecture DAG"
          color={COLORS.architecture}
          before={data.before.A}
          after={data.after.A}
        />
        <LayerPanel
          title="C 层 · Chronicle 执行"
          color={COLORS.chronicle}
          before={data.before.C}
          after={data.after.C}
        />
      </div>

      {/* 执行时间线 */}
      <div className="mb-6">
        <h4 className="text-white font-semibold mb-3 flex items-center gap-2">
          <span>⏱️</span>
          <span>执行时间线</span>
        </h4>
        <div className="bg-slate-800/40 rounded-lg p-4 overflow-x-auto">
          <div className="flex gap-2 min-w-[800px]">
            {data.timeline.slice(0, 30).map((item) => (
              <div
                key={item.id}
                className={`flex-shrink-0 w-[180px] rounded-lg border ${
                  item.kept
                    ? "border-emerald-500/30 bg-emerald-500/5"
                    : "border-slate-600/30 bg-slate-700/20"
                } p-3`}>
                <div className="flex items-center justify-between mb-2">
                  <span
                    className={`w-6 h-6 flex items-center justify-center rounded-full text-xs ${
                      item.kept ? "bg-emerald-600/30" : "bg-slate-500/20"
                    }`}
                    title={item.kept ? "保留" : "压缩"}>
                    {item.kept ? "✓" : "✗"}
                  </span>
                  <span className="text-[10px] text-slate-400">
                    score {(item.score * 100).toFixed(0)}
                  </span>
                </div>
                <div className="text-[11px] text-white/90 truncate mb-1">
                  {item.name}
                </div>
                <div className="text-[10px] text-slate-400">
                  {new Date(item.timestamp).toLocaleString()}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      {/* 丢弃详情（可折叠） */}
      <div className="border-t border-slate-700 pt-4">
        <button
          onClick={() => setShowDiscarded(!showDiscarded)}
          className="text-slate-400 hover:text-white text-sm w-full text-left">
          <span className="mr-2">{showDiscarded ? "▼" : "▶"}</span>
          <span>
            {data.discarded?.length || 0} 个节点被压缩（点击展开）
          </span>
        </button>
        {showDiscarded && data.discarded && data.discarded.length > 0 && (
          <ul className="mt-3 text-[11px] text-slate-300 font-mono max-h-80 overflow-y-auto">
            {data.discarded.slice(0, 20).map((item) => (
              <li key={item.nodeId} className="py-1 border-b border-slate-700/50">
                <span className="text-red-400 mr-2">•</span>
                <span className="text-slate-400">{item.nodeId}</span>
                <span className="ml-2 text-slate-500">{item.reason}</span>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

// ===== 内部小组件 =====

interface SummaryCardProps {
  label: string;
  value: string;
  sub: string;
  color: string;
}

function SummaryCard({ label, value, sub, color }: SummaryCardProps) {
  return (
    <div className="rounded-lg border border-slate-700/50 bg-slate-800 p-3">
      <div className="text-[11px] text-slate-400 mb-1">{label}</div>
      <div className="text-xl font-bold text-white mb-1" style={{ color }}>
        {value}
      </div>
      <div className="text-[11px] text-slate-500">{sub}</div>
    </div>
  );
}

interface LayerPanelProps {
  title: string;
  color: string;
  before: VizLayer;
  after: VizLayer;
}

function LayerPanel({ title, color, before, after }: LayerPanelProps) {
  const [view, setView] = useState<"before" | "after">("after");
  const nodes = view === "before" ? before.nodes : after.nodes;

  return (
    <div className="rounded-lg border border-slate-700 bg-slate-800/40 p-4">
      <div className="flex items-center justify-between mb-3">
        <div className="text-sm font-medium text-white/90 flex items-center gap-2">
          <span style={{ color }}>●</span>
          <span>{title}</span>
        </div>
        <div className="flex text-[10px] text-slate-400">
          <button
            onClick={() => setView("before")}
            className={`px-2 py-1 rounded ${
              view === "before"
                ? "bg-slate-700 text-white"
                : "hover:bg-slate-700/50 opacity-70"
            }`}>
            压缩前 ({before.nodes.length})
          </button>
          <button
            onClick={() => setView("after")}
            className={`px-2 py-1 rounded ${
              view === "after"
                ? "bg-slate-700 text-white"
                : "hover:bg-slate-700/50 opacity-70"
            }`}>
            压缩后 ({after.nodes.filter((n) => !n.compressed).length})
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        {nodes.slice(0, 20).map((node) => (
          <div
            key={node.id}
            className={`px-2 py-1 rounded text-[11px] text-white/90 border ${
              node.compressed
                ? "bg-slate-700/50 border-slate-500/30 text-slate-400"
                : "bg-emerald-600/20 border-emerald-500/30"
            }`}>
            <div className="truncate max-w-[160px]">{node.name || node.id}</div>
          </div>
        ))}
      </div>

      {nodes.length === 0 && (
        <div className="text-center py-4 text-slate-400 text-xs italic">
          （空）
        </div>
      )}
    </div>
  );
}
