/**
 * 分片（Sharded）压缩 — 当对话 / 执行历史很长时，按时间或执行顺序切成片，
 * 每片独立压缩后再合并，避免单次 O(n) 评分计算在大 n 时的性能问题。
 *
 * 设计原则：
 *   1. 分片大小可配置（默认 50 个 Chronicle 节点 / 片）
 *   2. 每个分片保留固定比例的高价值节点
 *   3. 跨分片边界保留关键锚点节点（每片首/尾节点 + 决策节点）
 *   4. 最终合并结果保持原顺序，方便前端按时间线展示
 */

import {
  ChronicleGraph,
  ArchitectureGraph,
  BlueprintGraph,
  CompressionResult,
  NodeId,
} from './types';
import { semanticCompress } from './semantic-compressor';
import { compress } from './compressor';

export interface ShardOptions {
  /** 每片最大节点数，默认 50 */
  shardSize?: number;
  /** 每片目标压缩比，默认 0.6（每片保留 40%） */
  targetRatio?: number;
  /** 使用语义评分，默认 true */
  useSemantic?: boolean;
  /** 每片强制保留的锚点节点数（头部 + 尾部），默认 2 */
  anchorNodes?: number;
  /** 最小保留节点数 */
  minNodes?: number;
}

/**
 * 将 Chronicle 按执行顺序切片并独立压缩，然后合并返回。
 * 返回结构与 compress() / semanticCompress() 完全一致。
 */
export function shardedCompress(
  chronicle: ChronicleGraph,
  architecture: ArchitectureGraph,
  blueprint: BlueprintGraph,
  options: ShardOptions = {}
): CompressionResult {
  const shardSize = options.shardSize ?? 50;
  const targetRatio = options.targetRatio ?? 0.6;
  const useSemantic = options.useSemantic ?? true;
  const anchorCount = options.anchorNodes ?? 2;

  // -------- 第一步：按 startTime 排序（保持执行顺序）--------
  const orderedIds = Array.from(chronicle.nodes.keys()).sort((a, b) => {
    const na = chronicle.nodes.get(a)!;
    const nb = chronicle.nodes.get(b)!;
    return na.startTime - nb.startTime;
  });

  if (orderedIds.length <= shardSize * 1.5) {
    // 不需要分片，直接走对应算法
    return useSemantic
      ? semanticCompress(chronicle, architecture, blueprint, {
          targetRatio,
          minNodes: options.minNodes,
        })
      : compress(chronicle, architecture, blueprint, {
          targetRatio,
          minNodes: options.minNodes,
        });
  }

  // -------- 第二步：按 shardSize 切片 --------
  const shards: string[][] = [];
  for (let i = 0; i < orderedIds.length; i += shardSize) {
    shards.push(orderedIds.slice(i, i + shardSize));
  }

  // -------- 第三步：为每片创建独立 Chronicle + 独立压缩 --------
  let discardedDetails: { nodeId: string; reason: string }[] = [];
  const keptNodeIds = new Set<NodeId>();
  let bestScores = new Map<NodeId, number>();

  shards.forEach((shard, idx) => {
    // 构造子 Chronicle
    const subChronicle: ChronicleGraph = {
      ...chronicle,
      id: `${chronicle.id}_shard_${idx}`,
      nodes: new Map(),
      edges: [],
      rawSizeBytes: undefined,
    };
    shard.forEach((id) => {
      const node = chronicle.nodes.get(id);
      if (node) subChronicle.nodes.set(id, node);
    });
    chronicle.edges.forEach((e) => {
      if (subChronicle.nodes.has(e.source) && subChronicle.nodes.has(e.target)) {
        subChronicle.edges.push(e);
      }
    });

    // 压缩这片
    const subResult = useSemantic
      ? semanticCompress(subChronicle, architecture, blueprint, { targetRatio, minNodes: 2 })
      : compress(subChronicle, architecture, blueprint, { targetRatio, minNodes: 2 });

    // 合并：保留非 compressed 状态的节点
    subResult.compressedChronicle.nodes.forEach((node, id) => {
      if (node.metadata.status !== 'compressed') {
        keptNodeIds.add(id);
      }
    });

    // 记录评分
    if (subResult.nodeScores) {
      subResult.nodeScores.forEach((v, k) => bestScores.set(k, v));
    }

    // 记录丢弃信息
    discardedDetails = discardedDetails.concat(
      subResult.discardedDetails.map((d) => ({ ...d, reason: `[分片 ${idx}] ${d.reason}` }))
    );
  });

  // -------- 第四步：锚点节点 — 每片首尾强制保留（边界锚） --------
  shards.forEach((shard) => {
    for (let i = 0; i < Math.min(anchorCount, shard.length); i++) {
      keptNodeIds.add(shard[i]);
      keptNodeIds.add(shard[shard.length - 1 - i]);
    }
  });

  // -------- 第五步：构建最终压缩后的 Chronicle --------
  const compressedChronicle: ChronicleGraph = {
    ...chronicle,
    id: `${chronicle.id}_sharded_compressed`,
    nodes: new Map(),
    edges: [],
    startedAt: chronicle.startedAt,
    completedAt: chronicle.completedAt,
  };

  const keptFinalIds = new Set<NodeId>();
  chronicle.nodes.forEach((node, id) => {
    if (keptNodeIds.has(id)) {
      const keptNode = { ...node };
      if (Object.keys(node.inputs).length > 0) {
        keptNode.inputs = { summary: `[已摘要] ${node.architectureNodeId} inputs` };
      }
      if (Object.keys(node.outputs).length > 0 && !node.metadata.skipReason) {
        keptNode.outputs = {
          summary: node.metadata.outputSummary ?? `[已摘要] ${node.architectureNodeId} outputs`,
        };
      }
      if (node.logs.length > 2) keptNode.logs = node.logs.slice(0, 1);
      compressedChronicle.nodes.set(id, keptNode);
      keptFinalIds.add(id);
    } else {
      const score = (bestScores.get(id) ?? 0).toFixed(2);
      compressedChronicle.nodes.set(id, {
        ...node,
        metadata: {
          ...node.metadata,
          status: 'compressed',
          outputSummary: `[已压缩] ${node.architectureNodeId} (评分: ${score})`,
          skipReason: undefined,
        },
        inputs: {},
        outputs: {},
        logs: [],
      });
    }
  });

  chronicle.edges.forEach((edge) => {
    const s = keptFinalIds.has(edge.source);
    const t = keptFinalIds.has(edge.target);
    if (s && t) {
      compressedChronicle.edges.push(edge);
    } else if (s || t) {
      compressedChronicle.edges.push({
        ...edge,
        payloadSummary: `${edge.payloadSummary} (端点已压缩)`,
      });
    }
  });

  // -------- 第六步：Architecture 裁剪 --------
  const compressedArchitecture: ArchitectureGraph = {
    ...architecture,
    id: `${architecture.id}_sharded_compressed`,
    nodes: new Map(),
    edges: [],
  };
  const keptArchIds = new Set<NodeId>();
  compressedChronicle.nodes.forEach((node) => {
    if (node.metadata.status !== 'compressed') keptArchIds.add(node.architectureNodeId);
  });
  architecture.nodes.forEach((node, id) => {
    if (keptArchIds.has(id)) compressedArchitecture.nodes.set(id, node);
  });
  architecture.edges.forEach((edge) => {
    if (compressedArchitecture.nodes.has(edge.source) && compressedArchitecture.nodes.has(edge.target)) {
      compressedArchitecture.edges.push(edge);
    }
  });

  // -------- 第七步：计算压缩率 --------
  const originalSize = estimateSize(chronicle);
  const newSize = estimateSize(compressedChronicle);
  const ratio = originalSize > 0 ? newSize / originalSize : 1;

  return {
    compressedChronicle,
    compressedArchitecture,
    blueprint,
    compressionRatio: ratio,
    retainedContext: 1 - ratio,
    discardedDetails,
    nodeScores: bestScores,
  };
}

function estimateSize(g: ChronicleGraph): number {
  let size = 0;
  g.nodes.forEach((node) => { size += JSON.stringify(node).length; });
  g.edges.forEach((edge) => { size += JSON.stringify(edge).length; });
  return size || 1;
}

/** 返回分片信息（便于调试和可视化） */
export function describeShards(
  chronicle: ChronicleGraph,
  options: ShardOptions = {}
): { shardCount: number; shardSize: number; shardNodeCount: number[] } {
  const shardSize = options.shardSize ?? 50;
  const orderedIds = Array.from(chronicle.nodes.keys()).sort((a, b) => {
    const na = chronicle.nodes.get(a)!;
    const nb = chronicle.nodes.get(b)!;
    return na.startTime - nb.startTime;
  });
  const shardNodeCount: number[] = [];
  for (let i = 0; i < orderedIds.length; i += shardSize) {
    shardNodeCount.push(Math.min(shardSize, orderedIds.length - i));
  }
  return { shardCount: shardNodeCount.length, shardSize, shardNodeCount };
}
