/**
 * 可视化数据模型（与前端可视化组件对接）
 *
 * 作用：把三层图（Blueprint/Architecture/Chronicle）+ 压缩前后对比
 * 转成前端组件可直接渲染的 JSON 格式。
 *
 * 输出结构：
 *   {
 *     before:   { nodes, edges, layer }     // 原始三层结构
 *     after:    { nodes, edges, layer }     // 压缩后三层结构
 *     diff:     { added, removed, compressed, retained } // 对比信息
 *     stats:    { 总节点数, 压缩率, 保留比例, 各层分布 }
 *     timeline: [{ id, name, kept, score, layer, status, timestamp }] // 时间线
 *   }
 */

import {
  BlueprintGraph,
  ArchitectureGraph,
  ChronicleGraph,
  CompressionResult,
  NodeId,
} from './types';

export interface VizNode {
  id: NodeId;
  name: string;
  layer: 'B' | 'A' | 'C';
  type: string;        // component / module / step / decision / parallel
  score?: number;      // 0-1 评分
  compressed?: boolean;
  status?: string;
  summary?: string;
  timestamp?: number;
  metadata?: any;
  // 布局坐标（初始化为自动计算）
  x?: number;
  y?: number;
}

export interface VizEdge {
  id: string;
  source: NodeId;
  target: NodeId;
  label?: string;
  layer: 'B' | 'A' | 'C';
  compressed?: boolean;
}

export interface VizLayer {
  nodes: VizNode[];
  edges: VizEdge[];
}

export interface TimelineItem {
  id: NodeId;
  name: string;
  kept: boolean;
  score: number;
  layer: 'C';
  status: string;
  timestamp: number;
  reason?: string;
}

export interface DiffSummary {
  retained: NodeId[];
  compressed: NodeId[];
  compressionRatio: number;
  avgRetainedScore: number;
  avgCompressedScore: number;
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
  diff: DiffSummary;
  stats: {
    totalNodesBefore: number;
    totalNodesAfter: number;
    compressionRatio: number;
    retainedContext: number;
    nodesByLayerBefore: { B: number; A: number; C: number };
    nodesByLayerAfter: { B: number; A: number; C: number };
  };
  timeline: TimelineItem[];
  discarded: { nodeId: string; reason: string }[];
}

/**
 * 构建可视化数据（核心入口）
 * 同时接收压缩前后的结果（before 可由原始对象重建）。
 */
export function buildVisualization(
  result: CompressionResult
): VisualizationData {
  // ------------ B: Blueprint ------------
  const bNodes: VizNode[] = [];
  result.blueprint.nodes.forEach((node) => {
    bNodes.push({
      id: node.id,
      name: node.name,
      layer: 'B',
      type: node.type,
      status: node.metadata?.status,
      summary: node.description,
    });
  });
  const bEdges: VizEdge[] = result.blueprint.edges.map((e, i) => ({
    id: `b-e-${i}`,
    source: e.source,
    target: e.target,
    label: e.label,
    layer: 'B',
  }));

  // ------------ A: Architecture（before = 原始）------------
  const aNodesBefore: VizNode[] = [];
  const originalArch = (result as any)._originalArchitecture ?? result.compressedArchitecture;
  // 压缩前的完整 architecture 没直接保存，这里用 compressedArchitecture + 被丢弃的推断
  // 简化：直接同时输出 compressed architecture 作为 before 的基线 — 这一步会在下方通过 C 层反推
  result.compressedArchitecture.nodes.forEach((node) => {
    aNodesBefore.push({
      id: node.id,
      name: node.name,
      layer: 'A',
      type: node.type,
      status: node.metadata?.status,
      score: result.nodeScores?.get(node.id),
    });
  });

  // ------------ C: Chronicle（before & after 有差异）------------
  const cNodesBefore: VizNode[] = [];
  const cNodesAfter: VizNode[] = [];

  // 原始 Chronicle 需要从压缩结果中重建：把 compressed 状态的也算作 "before"
  // 逻辑：result.compressedChronicle 中同时保留了保留节点和压缩节点
  const scoreMap = result.nodeScores ?? new Map<NodeId, number>();
  const orderedIds = Array.from(result.compressedChronicle.nodes.keys()).sort((a, b) => {
    const na = result.compressedChronicle.nodes.get(a)!;
    const nb = result.compressedChronicle.nodes.get(b)!;
    return na.startTime - nb.startTime;
  });

  const retainedIds: NodeId[] = [];
  const compressedIds: NodeId[] = [];

  orderedIds.forEach((id) => {
    const node = result.compressedChronicle.nodes.get(id)!;
    const isKept = node.metadata.status !== 'compressed';
    if (isKept) retainedIds.push(id);
    else compressedIds.push(id);

    // before: 所有节点标记为保留
    cNodesBefore.push({
      id,
      name: node.architectureNodeId,
      layer: 'C',
      type: 'chronicle',
      status: 'completed',
      score: scoreMap.get(id) ?? 0,
      summary: node.metadata.outputSummary,
      timestamp: node.startTime,
    });

    // after: 根据状态标记
    cNodesAfter.push({
      id,
      name: node.architectureNodeId,
      layer: 'C',
      type: 'chronicle',
      status: node.metadata.status,
      compressed: !isKept,
      score: scoreMap.get(id) ?? 0,
      summary: node.metadata.outputSummary,
      timestamp: node.startTime,
    });
  });

  // before A 层：用 C 层保留节点对应的 architectureNodeId 推断完整 A 层
  const archNodeIdSet = new Set<NodeId>();
  result.compressedChronicle.nodes.forEach((node) => {
    archNodeIdSet.add(node.architectureNodeId);
  });
  const aNodesFull: VizNode[] = [];
  archNodeIdSet.forEach((id) => {
    aNodesFull.push({
      id,
      name: id,
      layer: 'A',
      type: 'step',
      status: 'completed',
      score: scoreMap.get(id) ?? undefined,
    });
  });

  // before A 层 edges（简化：保留执行顺序 edges）
  const orderedArch = aNodesFull.sort((a, b) => (a.score ?? 0) - (b.score ?? 0));
  const aEdgesBefore: VizEdge[] = orderedArch.slice(0, -1).map((n, i) => ({
    id: `a-before-${i}`,
    source: n.id,
    target: orderedArch[i + 1].id,
    label: 'follow',
    layer: 'A',
  }));

  // after A 层：只保留 retainedIds 对应的 architectureNodeId
  const retainedArchIds = new Set<NodeId>();
  retainedIds.forEach((cid) => {
    const c = result.compressedChronicle.nodes.get(cid);
    if (c) retainedArchIds.add(c.architectureNodeId);
  });
  const aNodesAfter = aNodesFull.filter((n) => retainedArchIds.has(n.id));
  const aEdgesAfter: VizEdge[] = [];
  aNodesAfter.forEach((n, i) => {
    if (i > 0) {
      aEdgesAfter.push({
        id: `a-after-${i}`,
        source: aNodesAfter[i - 1].id,
        target: n.id,
        label: 'follow',
        layer: 'A',
      });
    }
  });

  // before / after C 层 edges
  const cEdgesBefore: VizEdge[] = [];
  const cEdgesAfter: VizEdge[] = [];
  for (let i = 1; i < orderedIds.length; i++) {
    cEdgesBefore.push({
      id: `c-before-${i}`,
      source: orderedIds[i - 1],
      target: orderedIds[i],
      label: '→',
      layer: 'C',
    });
    const srcKept = retainedIds.includes(orderedIds[i - 1]);
    const tgtKept = retainedIds.includes(orderedIds[i]);
    if (srcKept && tgtKept) {
      cEdgesAfter.push({
        id: `c-after-${i}`,
        source: orderedIds[i - 1],
        target: orderedIds[i],
        label: '→',
        layer: 'C',
      });
    } else if (srcKept || tgtKept) {
      cEdgesAfter.push({
        id: `c-after-${i}`,
        source: orderedIds[i - 1],
        target: orderedIds[i],
        label: '端点已压缩',
        layer: 'C',
        compressed: true,
      });
    }
  }

  // ------------ Timeline ------------
  const timeline: TimelineItem[] = orderedIds.map((id) => {
    const node = result.compressedChronicle.nodes.get(id)!;
    const isKept = node.metadata.status !== 'compressed';
    return {
      id,
      name: node.architectureNodeId,
      kept: isKept,
      score: scoreMap.get(id) ?? 0,
      layer: 'C',
      status: node.metadata.status,
      timestamp: node.startTime,
    };
  });

  // ------------ Stats ------------
  const totalC = cNodesBefore.length;
  const retainedC = cNodesAfter.filter((n) => !n.compressed).length;

  return {
    before: {
      B: { nodes: bNodes, edges: bEdges },
      A: { nodes: aNodesFull, edges: aEdgesBefore },
      C: { nodes: cNodesBefore, edges: cEdgesBefore },
    },
    after: {
      B: { nodes: bNodes, edges: bEdges }, // Blueprint 在压缩后不变
      A: { nodes: aNodesAfter, edges: aEdgesAfter },
      C: { nodes: cNodesAfter, edges: cEdgesAfter },
    },
    diff: {
      retained: retainedIds,
      compressed: compressedIds,
      compressionRatio: result.compressionRatio,
      avgRetainedScore: retainedIds.length > 0
        ? retainedIds.reduce((s, id) => s + (scoreMap.get(id) ?? 0), 0) / retainedIds.length
        : 0,
      avgCompressedScore: compressedIds.length > 0
        ? compressedIds.reduce((s, id) => s + (scoreMap.get(id) ?? 0), 0) / compressedIds.length
        : 0,
    },
    stats: {
      totalNodesBefore: totalC,
      totalNodesAfter: retainedC,
      compressionRatio: result.compressionRatio,
      retainedContext: result.retainedContext,
      nodesByLayerBefore: { B: bNodes.length, A: aNodesFull.length, C: totalC },
      nodesByLayerAfter: { B: bNodes.length, A: aNodesAfter.length, C: retainedC },
    },
    timeline,
    discarded: result.discardedDetails,
  };
}
