import {
  ChronicleGraph,
  CNode,
  CEdge,
  ArchitectureGraph,
  ANode,
  NodeMetadata,
  DataFlow,
} from './types';

function createDataFlow(type: string, description: string): DataFlow {
  return {
    type,
    schema: `${type}_v1`,
    description,
  };
}

/**
 * A→C: 把 Architecture 展开为 Chronicle（执行记录）
 *
 * 这是一个模拟执行函数，随机填充 token 消耗和耗时。
 * 真实场景下应该由调度器的实际执行产生。
 */
export function expandToChronicle(
  arch: ArchitectureGraph,
  executionId: string,
  options: { randomSeed?: number; skip?: string[] } = {}
): ChronicleGraph {
  const chronicle: ChronicleGraph = {
    id: `chr_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    architectureId: arch.id,
    nodes: new Map(),
    edges: [],
    executionId,
    startedAt: Date.now(),
  };

  const nodeOrder = Array.from(arch.nodes.keys());
  let currentTime = chronicle.startedAt;

  nodeOrder.forEach((archNodeId) => {
    const archNode = arch.nodes.get(archNodeId);
    if (!archNode) return;

    const startTime = currentTime;
    const latency = archNodeId === 'start' ? 10 : 100 + Math.random() * 200;
    currentTime += latency;

    const isSkipped = options.skip?.includes(archNodeId);

    const metadata: NodeMetadata = {
      tokenCost: archNodeId === 'start' ? 0 : 500 + Math.floor(Math.random() * 800),
      latencyMs: latency,
      status: isSkipped ? 'skipped' : 'completed',
      skipReason: isSkipped ? '模拟：用户意图不触发此步骤' : undefined,
      outputSummary: isSkipped ? '[跳过]' : `步骤 ${archNode.name} 执行结果摘要`,
      timestamp: startTime,
    };

    const cNode: CNode = {
      id: `${executionId}_${archNodeId}`,
      architectureNodeId: archNodeId,
      executionId,
      startTime,
      endTime: currentTime,
      metadata,
      inputs: archNode.requires && archNode.requires.length > 0
        ? { from: archNode.requires.join(',') }
        : {},
      outputs: isSkipped ? {} : { result: `output_from_${archNodeId}` },
      logs: isSkipped ? ['Step skipped'] : [`Step ${archNode.name} executed successfully`],
    };

    chronicle.nodes.set(cNode.id, cNode);
  });

  // 创建数据流边
  const cNodes = Array.from(chronicle.nodes.values());
  for (let i = 0; i < cNodes.length - 1; i++) {
    const edge: CEdge = {
      source: cNodes[i].id,
      target: cNodes[i + 1].id,
      timestamp: cNodes[i].endTime ?? currentTime,
      dataFlow: createDataFlow('execution', `${cNodes[i].architectureNodeId} → ${cNodes[i + 1].architectureNodeId}`),
      payloadSummary: '数据传递',
    };
    chronicle.edges.push(edge);
  }

  chronicle.completedAt = currentTime;
  chronicle.rawSizeBytes = calculateSize(chronicle);
  return chronicle;
}

/** 计算图结构的字节大小（近似） */
export function calculateSize(graph: ChronicleGraph): number {
  let size = 0;
  graph.nodes.forEach((node) => {
    size += JSON.stringify(node).length;
  });
  graph.edges.forEach((edge) => {
    size += JSON.stringify(edge).length;
  });
  return size;
}

/** 获取执行耗时（ms） */
export function getTotalLatency(chronicle: ChronicleGraph): number {
  if (chronicle.completedAt) {
    return chronicle.completedAt - chronicle.startedAt;
  }
  let max = 0;
  chronicle.nodes.forEach((n) => {
    if (n.endTime && n.endTime - chronicle.startedAt > max) {
      max = n.endTime - chronicle.startedAt;
    }
  });
  return max;
}

/** 获取总 token 消耗 */
export function getTotalTokens(chronicle: ChronicleGraph): number {
  let total = 0;
  chronicle.nodes.forEach((n) => {
    total += n.metadata.tokenCost;
  });
  return total;
}

/** 把 Chronicle 转为可序列化对象 */
export function serializeChronicle(chronicle: ChronicleGraph): object {
  return {
    ...chronicle,
    nodes: Array.from(chronicle.nodes.entries()),
  };
}

export function deserializeChronicle(data: any): ChronicleGraph {
  return {
    ...data,
    nodes: new Map(data.nodes),
  };
}
