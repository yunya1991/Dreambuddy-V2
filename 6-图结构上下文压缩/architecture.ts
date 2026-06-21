import {
  ArchitectureGraph,
  ANode,
  AEdge,
  BlueprintGraph,
  NodeMetadata,
  DataFlow,
} from './types';

function createDefaultMetadata(status: NodeMetadata['status'] = 'pending'): NodeMetadata {
  return {
    tokenCost: 0,
    latencyMs: 0,
    status,
    timestamp: Date.now(),
  };
}

function createDataFlow(type: string, description: string): DataFlow {
  return {
    type,
    schema: `${type}_v1`,
    description,
  };
}

/**
 * B→A: 把 Blueprint 展开为 Architecture（DAG）
 *
 * 默认把 analysis_chain 模块展开为 S1-S5 的执行步骤，其他模块保留原样。
 */
export function expandToArchitecture(blueprint: BlueprintGraph): ArchitectureGraph {
  const arch: ArchitectureGraph = {
    id: `arch_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    blueprintId: blueprint.id,
    nodes: new Map(),
    edges: [],
    entryPoint: 'start',
    createdAt: Date.now(),
  };

  const entryNode: ANode = {
    id: 'start',
    type: 'step',
    name: '开始',
    parentNodeId: blueprint.rootId,
    metadata: createDefaultMetadata('completed'),
  };
  arch.nodes.set(entryNode.id, entryNode);

  const analysisChain = blueprint.nodes.get('analysis_chain');
  if (analysisChain) {
    const steps: ANode[] = [
      {
        id: 'S1_RESEARCH',
        type: 'step',
        name: 'S1 调研',
        parentNodeId: 'analysis_chain',
        metadata: createDefaultMetadata('pending'),
        requires: ['start'],
      },
      {
        id: 'S2_ANALYSIS',
        type: 'step',
        name: 'S2 分析',
        parentNodeId: 'analysis_chain',
        metadata: createDefaultMetadata('pending'),
        requires: ['S1_RESEARCH'],
      },
      {
        id: 'S3_DESIGN',
        type: 'step',
        name: 'S3 设计',
        parentNodeId: 'analysis_chain',
        metadata: createDefaultMetadata('pending'),
        requires: ['S2_ANALYSIS'],
      },
      {
        id: 'S4_VALIDATE',
        type: 'step',
        name: 'S4 验证',
        parentNodeId: 'analysis_chain',
        metadata: createDefaultMetadata('pending'),
        requires: ['S3_DESIGN'],
        branches: [
          { condition: '回测通过', target: 'S5_EXECUTE' },
          { condition: '回测失败', target: 'S3_DESIGN' },
        ],
      },
      {
        id: 'S5_EXECUTE',
        type: 'step',
        name: 'S5 执行',
        parentNodeId: 'analysis_chain',
        metadata: createDefaultMetadata('pending'),
        requires: ['S4_VALIDATE'],
      },
    ];

    steps.forEach((s) => arch.nodes.set(s.id, s));
    analysisChain.children = steps.map((s) => s.id);
  }

  const edges: AEdge[] = [
    { source: 'start', target: 'S1_RESEARCH', dataFlow: createDataFlow('control', '开始调研') },
    { source: 'S1_RESEARCH', target: 'S2_ANALYSIS', dataFlow: createDataFlow('research', '调研结果') },
    { source: 'S2_ANALYSIS', target: 'S3_DESIGN', dataFlow: createDataFlow('analysis', '分析结果') },
    { source: 'S3_DESIGN', target: 'S4_VALIDATE', dataFlow: createDataFlow('strategy', '策略设计') },
    { source: 'S4_VALIDATE', target: 'S5_EXECUTE', dataFlow: createDataFlow('validation', '验证结果') },
    {
      source: 'S4_VALIDATE',
      target: 'S3_DESIGN',
      dataFlow: createDataFlow('feedback', '失败反馈'),
      isConditional: true,
    },
  ];

  arch.edges = edges;
  return arch;
}

/** 获取架构图中某个节点的所有依赖节点 */
export function getDependencies(arch: ArchitectureGraph, nodeId: string): ANode[] {
  const node = arch.nodes.get(nodeId);
  if (!node?.requires) return [];
  return node.requires
    .map((id) => arch.nodes.get(id))
    .filter((n): n is ANode => n !== undefined);
}

/** 获取入口节点到目标节点的拓扑路径（BFS） */
export function getPathTo(arch: ArchitectureGraph, targetId: string): ANode[] {
  const path: ANode[] = [];
  const visited = new Set<string>();
  const queue: string[] = [targetId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    if (visited.has(current)) continue;
    visited.add(current);

    const node = arch.nodes.get(current);
    if (node) {
      path.unshift(node);
      if (node.requires) {
        queue.push(...node.requires);
      }
    }
  }

  return path;
}

/** 把 Architecture 转为可序列化对象 */
export function serializeArchitecture(arch: ArchitectureGraph): object {
  return {
    ...arch,
    nodes: Array.from(arch.nodes.entries()),
  };
}

export function deserializeArchitecture(data: any): ArchitectureGraph {
  return {
    ...data,
    nodes: new Map(data.nodes),
  };
}
