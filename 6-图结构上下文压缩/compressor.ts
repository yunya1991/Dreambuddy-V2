import {
  ChronicleGraph,
  ArchitectureGraph,
  BlueprintGraph,
  CompressionResult,
  CompressionOptions,
  NodeId,
} from './types';
import { calculateSize } from './chronicle';

const DEFAULT_WEIGHTS = {
  tokenCost: 0.4,
  latency: 0.3,
  structuralPosition: 0.2,
  semanticImportance: 0.1,
};

/**
 * 计算节点的价值评分（0-1）
 * 分值越高，说明该节点越值得保留。
 */
function scoreNode(
  nodeId: NodeId,
  chronicle: ChronicleGraph,
  architecture: ArchitectureGraph,
  weights: Required<CompressionOptions>['weights']
): number {
  const node = chronicle.nodes.get(nodeId);
  if (!node) return 0;

  // 1. Token 消耗（归一化：相对最高消耗的比例）
  let maxTokenCost = 0;
  chronicle.nodes.forEach((n) => {
    if (n.metadata.tokenCost > maxTokenCost) maxTokenCost = n.metadata.tokenCost;
  });
  const tokenScore = maxTokenCost > 0 ? node.metadata.tokenCost / maxTokenCost : 0;

  // 2. 耗时（归一化）
  let maxLatency = 0;
  chronicle.nodes.forEach((n) => {
    if (n.metadata.latencyMs > maxLatency) maxLatency = n.metadata.latencyMs;
  });
  const latencyScore = maxLatency > 0 ? node.metadata.latencyMs / maxLatency : 0;

  // 3. 结构位置（入口/出口/条件分支 有特殊权重）
  let structuralScore = 0;
  const archNode = architecture.nodes.get(node.architectureNodeId);
  if (archNode) {
    // 入口节点
    if (archNode.id === architecture.entryPoint) structuralScore = 0.9;
    // 有分支（决策点）
    else if (archNode.branches && archNode.branches.length > 0) structuralScore = 0.7;
    // 被其他节点依赖
    else {
      let dependents = 0;
      architecture.nodes.forEach((n) => {
        if (n.requires?.includes(archNode.id)) dependents++;
      });
      structuralScore = Math.min(0.6, 0.2 + dependents * 0.1);
    }
  }

  // 4. 语义重要性（简化为：是否有输出内容）
  const outputCount = Object.keys(node.outputs).length;
  const inputCount = Object.keys(node.inputs).length;
  const semanticScore = Math.min(1, (outputCount + inputCount) / 4);

  // 加权组合
  const total =
    weights.tokenCost * tokenScore +
    weights.latency * latencyScore +
    weights.structuralPosition * structuralScore +
    weights.semanticImportance * semanticScore;

  return Math.min(1, total);
}

/**
 * C→A→B: 回溯压缩
 *
 * 算法:
 * 1. 计算每个节点的价值评分
 * 2. 按评分排序，保留前 (1 - targetRatio) 的节点
 * 3. 保留的节点保留完整信息
 * 4. 压缩的节点保留引用关系，但清空详细内容
 * 5. 生成压缩后的架构图（只保留"已执行"的节点）
 */
export function compress(
  chronicle: ChronicleGraph,
  architecture: ArchitectureGraph,
  blueprint: BlueprintGraph,
  options: CompressionOptions = {}
): CompressionResult {
  const targetRatio = options.targetRatio ?? 0.5;
  const weights = { ...DEFAULT_WEIGHTS, ...(options.weights ?? {}) };
  const keepAllEdges = options.keepAllEdges ?? false;
  const minNodes = options.minNodes ?? 1;

  // 1. 评分
  const nodeScores = new Map<NodeId, number>();
  const allNodeIds = Array.from(chronicle.nodes.keys());

  allNodeIds.forEach((id) => {
    const score = scoreNode(id, chronicle, architecture, weights);
    nodeScores.set(id, score);
  });

  // 2. 按评分排序
  const sortedIds = [...allNodeIds].sort((a, b) => {
    return (nodeScores.get(b) ?? 0) - (nodeScores.get(a) ?? 0);
  });

  // 3. 确定保留的节点数
  const totalNodes = allNodeIds.length;
  const targetKeep = Math.max(minNodes, Math.ceil(totalNodes * (1 - targetRatio)));
  const keepIds = new Set(sortedIds.slice(0, targetKeep));

  // 4. 创建压缩后的 Chronicle
  const compressedChronicle: ChronicleGraph = {
    ...chronicle,
    id: `${chronicle.id}_compressed`,
    nodes: new Map(),
    edges: [],
    startedAt: chronicle.startedAt,
    completedAt: chronicle.completedAt,
  };

  const discardedDetails: { nodeId: string; reason: string }[] = [];

  chronicle.nodes.forEach((node, id) => {
    if (keepIds.has(id)) {
      // 保留节点，但摘要化输入输出
      const keptNode = { ...node };
      if (Object.keys(node.inputs).length > 0) {
        keptNode.inputs = { summary: `[已摘要] ${node.architectureNodeId} inputs` };
      }
      if (Object.keys(node.outputs).length > 0 && !node.metadata.skipReason) {
        keptNode.outputs = { summary: node.metadata.outputSummary ?? `[已摘要] ${node.architectureNodeId} outputs` };
      }
      if (node.logs.length > 2) {
        keptNode.logs = node.logs.slice(0, 1);
      }
      compressedChronicle.nodes.set(id, keptNode);
    } else {
      // 压缩节点：保留引用关系，清空详细内容
      const compressedNode = {
        ...node,
        metadata: {
          ...node.metadata,
          status: 'compressed' as const,
          outputSummary: `[已压缩] ${node.architectureNodeId} (评分: ${(nodeScores.get(id) ?? 0).toFixed(2)})`,
          skipReason: undefined,
        },
        inputs: {},
        outputs: {},
        logs: [],
      };
      compressedChronicle.nodes.set(id, compressedNode);
      discardedDetails.push({
        nodeId: node.architectureNodeId,
        reason: `价值评分 ${(nodeScores.get(id) ?? 0).toFixed(2)}，低于保留阈值`,
      });
    }
  });

  // 5. 更新边
  chronicle.edges.forEach((edge) => {
    const sourceKept = keepIds.has(edge.source);
    const targetKept = keepIds.has(edge.target);

    if (keepAllEdges) {
      compressedChronicle.edges.push(edge);
    } else if (sourceKept || targetKept) {
      // 至少一端是保留节点，保留边
      // 如果另一端被压缩，标注边的状态
      const markedEdge = {
        ...edge,
        payloadSummary:
          sourceKept && targetKept
            ? edge.payloadSummary
            : `${edge.payloadSummary} (端点已压缩)`,
      };
      compressedChronicle.edges.push(markedEdge);
    }
  });

  compressedChronicle.rawSizeBytes = calculateSize(compressedChronicle);

  // 6. 创建压缩后的 Architecture（只保留对应的架构节点）
  const compressedArchitecture: ArchitectureGraph = {
    ...architecture,
    id: `${architecture.id}_compressed`,
    nodes: new Map(),
    edges: [],
  };

  const keptArchIds = new Set<string>();
  compressedChronicle.nodes.forEach((node) => {
    keptArchIds.add(node.architectureNodeId);
  });

  architecture.nodes.forEach((node, id) => {
    if (keptArchIds.has(id)) {
      compressedArchitecture.nodes.set(id, node);
    }
  });

  architecture.edges.forEach((edge) => {
    if (compressedArchitecture.nodes.has(edge.source) && compressedArchitecture.nodes.has(edge.target)) {
      compressedArchitecture.edges.push(edge);
    }
  });

  // 7. 计算压缩率
  const originalSize = chronicle.rawSizeBytes ?? calculateSize(chronicle);
  const newSize = compressedChronicle.rawSizeBytes ?? calculateSize(compressedChronicle);
  const compressionRatio = newSize / originalSize;
  const retainedContext = 1 - compressionRatio;

  return {
    compressedChronicle,
    compressedArchitecture,
    blueprint,
    compressionRatio,
    retainedContext,
    discardedDetails,
    nodeScores,
  };
}

/** 生成压缩报告（便于调试） */
export function generateCompressionReport(result: CompressionResult): string {
  const lines: string[] = [];
  lines.push('=== 压缩报告 ===');
  lines.push(`压缩率: ${(result.compressionRatio * 100).toFixed(1)}%`);
  lines.push(`保留上下文: ${(result.retainedContext * 100).toFixed(1)}%`);
  lines.push(`保留节点: ${result.compressedChronicle.nodes.size}`);
  lines.push(`压缩节点: ${result.discardedDetails.length}`);
  lines.push('');

  if (result.nodeScores) {
    lines.push('节点评分:');
    const sorted = Array.from(result.nodeScores.entries()).sort((a, b) => b[1] - a[1]);
    sorted.forEach(([id, score]) => {
      const node = result.compressedChronicle.nodes.get(id);
      const status = node?.metadata.status ?? 'unknown';
      const indicator = status === 'compressed' ? '□' : '■';
      lines.push(`  ${indicator} ${node?.architectureNodeId ?? id}: ${score.toFixed(3)} [${status}]`);
    });
  }

  lines.push('');
  lines.push('丢弃详情:');
  result.discardedDetails.forEach((d) => {
    lines.push(`  - ${d.nodeId}: ${d.reason}`);
  });

  return lines.join('\n');
}
