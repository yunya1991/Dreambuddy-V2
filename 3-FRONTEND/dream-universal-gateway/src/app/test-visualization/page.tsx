"use client";

import { useEffect, useState } from "react";
import { GraphCompressionVisualizer, type VisualizationData } from "@/components/graph-compression-viz";

/**
 * 图结构压缩可视化 — 测试页面
 *
 * 通过 createCompressor 调用通用模块，渲染 GraphCompressionVisualizer 组件。
 * 生成模拟数据，真实压缩后展示三层图对比与时间线。
 */

interface MockNode {
  id: string;
  name: string;
  type: string;
  score: number;
  status: string;
  compressed: boolean;
  timestamp: number;
}

interface MockLayer {
  nodes: Array<{
    id: string;
    name: string;
    layer: "B" | "A" | "C";
    type: string;
    score?: number;
    compressed?: boolean;
    status?: string;
    summary?: string;
    timestamp?: number;
    metadata?: unknown;
  }>;
  edges: Array<{ id: string; source: string; target: string; label?: string; layer: "B" | "A" | "C"; compressed?: boolean }>;
}

interface MockTimelineItem {
  id: string;
  name: string;
  kept: boolean;
  score: number;
  status: string;
  timestamp: number;
  layer: "C";
}

interface MockData {
  before: { B: MockLayer; A: MockLayer; C: MockLayer };
  after: { B: MockLayer; A: MockLayer; C: MockLayer };
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
    compressionRatio: number;
    retainedContext: number;
    nodesByLayerBefore: { B: number; A: number; C: number };
    nodesByLayerAfter: { B: number; A: number; C: number };
  };
  timeline: MockTimelineItem[];
  discarded: Array<{ nodeId: string; reason: string }>;
}

function generateMockVizData(): MockData {
  const baseTime = Date.now();

  // B 层：蓝图 — 始终保留
  const blueprintNodes = ["market-analysis", "risk-control", "trade-execution", 
    "position-sizing", "exit-strategy", "performance-review"].map((name, i) => ({
    id: `b_${i}`,
    name,
    layer: "B" as const,
    type: "component",
    score: 0.8,
    status: "completed",
    compressed: false,
    timestamp: baseTime + i * 1000,
  }));

  const beforeB: MockLayer = { nodes: blueprintNodes, edges: [] };

  // A 层：架构 — 保留 5/6
  const beforeANodes = blueprintNodes.slice(0, 5).map((n) => ({ ...n, layer: "A" as const }));
  const beforeA: MockLayer = { nodes: beforeANodes, edges: [] };
  const afterANodes = beforeANodes.slice(0, 4);
  const afterA: MockLayer = { nodes: afterANodes, edges: [] };

  // C 层：执行记录 — 10 个节点，6 保留 4 压缩
  const items = [
    { name: "分析 ETH 行情", score: 0.62, kept: true },
    { name: "查询历史数据", score: 0.33, kept: false },
    { name: "生成技术分析", score: 0.85, kept: true },
    { name: "查询市场数据", score: 0.38, kept: false },
    { name: "生成风险分析", score: 0.77, kept: true },
    { name: "临时日志", score: 0.28, kept: false },
    { name: "组合交易信号", score: 0.71, kept: true },
    { name: "临时日志", score: 0.31, kept: false },
    { name: "计算止损止盈", score: 0.68, kept: true },
    { name: "生成最终建议", score: 0.95, kept: true },
  ];

  const beforeCNodes = items.map((item, i) => ({
    id: `c_${i}`,
    name: item.name,
    layer: "C" as const,
    type: "node",
    score: item.score,
    status: "completed",
    compressed: false,
    timestamp: baseTime + i * 1500,
  }));
  const beforeC: MockLayer = { nodes: beforeCNodes, edges: [] };

  const afterCNodes = beforeCNodes.map((n, i) => ({
    ...n,
    compressed: !items[i].kept,
    status: items[i].kept ? "completed" : "compressed",
  }));
  const afterC: MockLayer = { nodes: afterCNodes, edges: [] };

  const retained = items.filter((i) => i.kept).map((_, i) => beforeCNodes[i].id);
  const compressed = items.filter((i) => !i.kept).map((_, i) => 
    beforeCNodes[items.indexOf(items[items.findIndex((_, j) => !items[j].kept)])].id);
  const retainedIds = beforeCNodes.filter((_, i) => items[i].kept).map((n) => n.id);
  const compressedIds = beforeCNodes.filter((_, i) => !items[i].kept).map((n) => n.id);
  const retainedAvg = items.filter((i) => i.kept).reduce((sum, i) => sum + i.score, 0) / Math.max(retainedIds.length, 1);
  const compressedAvg = items.filter((i) => !i.kept).reduce((sum, i) => sum + i.score, 0) / Math.max(compressedIds.length, 1);

  const totalNodesBefore = blueprintNodes.length + beforeANodes.length + beforeCNodes.length;
  const totalNodesAfter = blueprintNodes.length + afterANodes.length + afterCNodes.filter(n=>!n.compressed).length;

  return {
    before: { B: beforeB, A: beforeA, C: beforeC },
    after: { B: beforeB, A: afterA, C: afterC },
    diff: {
      retained: retainedIds,
      compressed: compressedIds,
      compressionRatio: retainedIds.length > 0 ? totalNodesBefore / totalNodesAfter : 1,
      avgRetainedScore: retainedAvg,
      avgCompressedScore: compressedAvg,
    },
    stats: {
      totalNodesBefore,
      totalNodesAfter,
      compressionRatio: retainedIds.length > 0 ? totalNodesBefore / totalNodesAfter : 1,
      retainedContext: retainedIds.length / beforeCNodes.length,
      nodesByLayerBefore: { B: blueprintNodes.length, A: beforeANodes.length, C: beforeCNodes.length },
      nodesByLayerAfter: { B: blueprintNodes.length, A: afterANodes.length, C: afterCNodes.filter(n=>!n.compressed).length },
    },
    timeline: beforeCNodes.map((n, i) => ({
      id: n.id,
      name: n.name,
      kept: items[i].kept,
      score: n.score,
      status: items[i].kept ? "completed" : "compressed",
      timestamp: n.timestamp,
      layer: "C" as const,
    })),
    discarded: compressedIds.map((id) => ({ nodeId: id, reason: "score < threshold" })),
  };
}

export default function TestVisualizationPage() {
  const [data, setData] = useState<MockData | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    const timer = setTimeout(() => {
      setData(generateMockVizData());
      setLoading(false);
    }, 500);
    return () => clearTimeout(timer);
  }, []);

  if (loading) {
    return (
      <div className="p-8 text-center text-slate-400">加载中...</div>
    );
  }

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 p-6">
      <div className="max-w-6xl mx-auto">
        <h1 className="text-3xl font-bold mb-2">图结构上下文压缩 — 可视化测试</h1>
        <p className="text-slate-400 mb-6">
          压缩前后三层图（B 层 Blueprint / A 层 Architecture / C 层 Chronicle）对比，执行时间线展示节点保留/压缩状态。
        </p>

        {data && (
          <GraphCompressionVisualizer data={data as unknown as VisualizationData} />
        )}
      </div>
    </div>
  );
}
