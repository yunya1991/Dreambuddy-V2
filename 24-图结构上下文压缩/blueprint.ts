import {
  BlueprintGraph,
  BNode,
  BEdge,
  NodeId,
  NodeMetadata,
  DataFlow,
} from './types';

const ROOT_ID = 'bp_root';

function createDefaultMetadata(): NodeMetadata {
  return {
    tokenCost: 0,
    latencyMs: 0,
    status: 'completed',
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
 * 创建一个 Blueprint（顶层架构图）
 *
 * 描述系统的宏观组件和数据流向。
 */
export function createBlueprint(name: string, version = '1.0.0'): BlueprintGraph {
  const blueprint: BlueprintGraph = {
    id: `bp_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    name,
    version,
    nodes: new Map(),
    edges: [],
    rootId: ROOT_ID,
    createdAt: Date.now(),
  };

  const root: BNode = {
    id: ROOT_ID,
    type: 'module',
    name,
    description: '完整的图结构上下文压缩系统',
    metadata: createDefaultMetadata(),
    children: [],
  };
  blueprint.nodes.set(root.id, root);

  const components: BNode[] = [
    {
      id: 'intent_engine',
      type: 'service',
      name: '意图识别引擎',
      description: '识别用户意图并分类',
      metadata: createDefaultMetadata(),
    },
    {
      id: 'knowledge_base',
      type: 'service',
      name: '知识库检索',
      description: '检索相关知识和策略',
      metadata: createDefaultMetadata(),
    },
    {
      id: 'market_data',
      type: 'service',
      name: '行情数据服务',
      description: '获取实时和历史行情数据',
      metadata: createDefaultMetadata(),
    },
    {
      id: 'analysis_chain',
      type: 'module',
      name: '分析链',
      description: 'S1-S5 分析步骤',
      metadata: createDefaultMetadata(),
      children: [],
    },
    {
      id: 'strategy_engine',
      type: 'service',
      name: '策略引擎',
      description: '策略生成和验证',
      metadata: createDefaultMetadata(),
    },
    {
      id: 'report_generator',
      type: 'service',
      name: '报告生成器',
      description: '生成最终报告',
      metadata: createDefaultMetadata(),
    },
  ];

  components.forEach((c) => {
    blueprint.nodes.set(c.id, c);
    root.children!.push(c.id);
  });

  const edges: BEdge[] = [
    { source: ROOT_ID, target: 'intent_engine', dataFlow: createDataFlow('control', '触发意图识别') },
    { source: 'intent_engine', target: 'knowledge_base', dataFlow: createDataFlow('query', '意图驱动的知识检索') },
    { source: 'intent_engine', target: 'market_data', dataFlow: createDataFlow('query', '意图驱动的行情查询') },
    { source: 'intent_engine', target: 'analysis_chain', dataFlow: createDataFlow('control', '路由到分析链') },
    { source: 'knowledge_base', target: 'analysis_chain', dataFlow: createDataFlow('knowledge', '注入知识库数据') },
    { source: 'market_data', target: 'analysis_chain', dataFlow: createDataFlow('market', '注入行情数据') },
    { source: 'analysis_chain', target: 'strategy_engine', dataFlow: createDataFlow('analysis', '分析结果驱动策略') },
    { source: 'analysis_chain', target: 'report_generator', dataFlow: createDataFlow('result', '分析结果生成报告') },
    { source: 'strategy_engine', target: 'report_generator', dataFlow: createDataFlow('strategy', '策略建议生成报告') },
  ];

  blueprint.edges = edges;
  return blueprint;
}

/** 查找 Blueprint 中的组件节点 */
export function findComponent(blueprint: BlueprintGraph, id: NodeId): BNode | undefined {
  return blueprint.nodes.get(id);
}

/** 获取某个节点的下游依赖 */
export function getChildren(blueprint: BlueprintGraph, id: NodeId): BNode[] {
  const node = blueprint.nodes.get(id);
  if (!node?.children) return [];
  return node.children
    .map((childId) => blueprint.nodes.get(childId))
    .filter((n): n is BNode => n !== undefined);
}

/** 把 Blueprint 转为可序列化的对象（用于 JSON 存储） */
export function serializeBlueprint(bp: BlueprintGraph): object {
  return {
    ...bp,
    nodes: Array.from(bp.nodes.entries()),
  };
}

/** 从序列化对象恢复 Blueprint */
export function deserializeBlueprint(data: any): BlueprintGraph {
  return {
    ...data,
    nodes: new Map(data.nodes),
  };
}
