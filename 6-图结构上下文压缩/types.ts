/**
 * 图架构压缩模块 - 基础类型定义
 *
 * 位置: 6-图结构上下文压缩/types.ts
 *
 * 定义图架构压缩模块中使用的基础类型
 * 这些类型会在 enhanced-compressor.ts 中被扩展
 */

// ============================================================
// 节点类型
// ============================================================

/** 节点类型 */
export type NodeType =
  | 'blueprint'       // 蓝图节点
  | 'architecture'    // 架构节点
  | 'chronicle'       // 编年节点
  | 'thinking-step'   // 思维步骤节点
  | 'skill-call'      // 技能调用节点
  | 'cross-validation' // 交叉验证节点
  | 'decision'        // 决策节点
  | 'input'           // 输入节点
  | 'output';         // 输出节点

/** 节点层级 */
export type NodeLevel = 'B' | 'A' | 'C';

/** 节点状态 */
export type NodeStatus = 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'cancelled';

/**
 * 序列化节点
 * 用于存储到压缩图结构中
 */
export interface SerializedNode {
  /** 节点ID */
  id: string;

  /** 节点类型 */
  type: NodeType;

  /** 节点名称 */
  name: string;

  /** 节点层级 */
  level: NodeLevel;

  /** 节点状态 */
  status: NodeStatus;

  /** Token消耗 */
  tokens?: number;

  /** 执行延迟（毫秒） */
  latencyMs?: number;

  /** 摘要描述 */
  summary?: string;

  /** 节点元数据 */
  meta?: Record<string, unknown>;

  /** 父节点ID */
  parentId?: string;

  /** 子节点ID列表 */
  children?: string[];

  /** 创建时间 */
  createdAt?: number;

  /** 完成时间 */
  completedAt?: number;
}

// ============================================================
// 边类型
// ============================================================

/** 边类型 */
export type EdgeType =
  | 'flow'           // 执行流
  | 'requires'        // 依赖关系
  | 'supports'        // 支持关系
  | 'conflicts'       // 冲突关系
  | 'extends'         // 扩展关系
  | 'references';     // 引用关系

/**
 * 序列化边
 */
export interface SerializedEdge {
  /** 边ID */
  id: string;

  /** 源节点ID */
  sourceId: string;

  /** 目标节点ID */
  targetId: string;

  /** 边类型 */
  type: EdgeType;

  /** 权重 */
  weight?: number;

  /** 标签 */
  label?: string;

  /** 元数据 */
  meta?: Record<string, unknown>;
}

// ============================================================
// 图数据
// ============================================================

/**
 * 图数据
 */
export interface GraphData {
  /** 节点映射 */
  nodes: Map<string, SerializedNode>;

  /** 边列表 */
  edges: SerializedEdge[];

  /** 根节点ID */
  rootId?: string;

  /** 元数据 */
  meta?: Record<string, unknown>;
}

// ============================================================
// 压缩结果
// ============================================================

/**
 * 压缩结果
 */
export interface CompressResult {
  /** 是否成功 */
  ok: boolean;

  /** 压缩后的图数据 */
  graphData: GraphData;

  /** 压缩统计 */
  stats: CompressionStats;

  /** 错误信息 */
  error?: string;
}

/**
 * 压缩统计
 */
export interface CompressionStats {
  /** 原始节点数 */
  originalNodes: number;

  /** 压缩后节点数 */
  compressedNodes: number;

  /** 原始Token数 */
  originalTokens: number;

  /** 压缩后Token数 */
  compressedTokens: number;

  /** 压缩率 */
  compressionRatio: number;

  /** 保留的关键节点 */
  preservedCriticalNodes: string[];

  /** 丢弃的节点 */
  discardedNodes: string[];
}

// ============================================================
// 推理结果
// ============================================================

/**
 * 决策节点
 */
export interface DecisionNode {
  /** 节点ID */
  id: string;

  /** 决策类型 */
  type: 'entry' | 'branch' | 'conclusion' | 'reversal';

  /** 决策描述 */
  description: string;

  /** 决策置信度 */
  confidence: number;

  /** 关联的节点ID */
  relatedNodeIds: string[];
}

/**
 * 推理路径
 */
export interface ReasoningPath {
  /** 路径ID */
  id: string;

  /** 路径节点序列 */
  nodeIds: string[];

  /** 路径描述 */
  description: string;

  /** 路径置信度 */
  confidence: number;

  /** 路径权重 */
  weight: number;
}

/**
 * 冲突检测
 */
export interface ConflictDetection {
  /** 冲突ID */
  id: string;

  /** 冲突类型 */
  type: 'direction' | 'confidence' | 'logic' | 'data';

  /** 涉及的节点ID */
  involvedNodeIds: string[];

  /** 冲突描述 */
  description: string;

  /** 冲突严重程度 */
  severity: 'low' | 'medium' | 'high';

  /** 建议的解决方案 */
  suggestedResolution?: string;
}

/**
 * 下一步建议
 */
export interface NextStepSuggestion {
  /** 建议ID */
  id: string;

  /** 建议动作 */
  action: 'call_skill' | 'collect_data' | 'validate' | 'execute' | 'wait' | 'ask_user';

  /** 建议描述 */
  description: string;

  /** 建议的技能ID */
  suggestedSkillId?: string;

  /** 预期置信度提升 */
  expectedConfidenceBoost?: number;

  /** 优先级 */
  priority: 'high' | 'medium' | 'low';
}

/**
 * 推理结果
 */
export interface InferenceResult {
  /** 会话ID */
  sessionId: string;

  /** 关键决策节点 */
  keyDecisionNodes: DecisionNode[];

  /** 推理路径 */
  reasoningPaths: ReasoningPath[];

  /** 冲突检测 */
  conflicts: ConflictDetection[];

  /** 下一步建议 */
  nextSteps: NextStepSuggestion[];

  /** 综合风险评分 (0-100) */
  riskScore: number;

  /** 推理摘要 */
  summary: string;

  /** 生成时间 */
  generatedAt: number;
}

// ============================================================
// 工具函数
// ============================================================

/**
 * 创建空节点
 */
export function createEmptyNode(
  id: string,
  type: NodeType,
  name: string,
  level: NodeLevel = 'A'
): SerializedNode {
  return {
    id,
    type,
    name,
    level,
    status: 'pending',
    createdAt: Date.now(),
  };
}

/**
 * 创建空边
 */
export function createEmptyEdge(
  id: string,
  sourceId: string,
  targetId: string,
  type: EdgeType = 'flow'
): SerializedEdge {
  return {
    id,
    sourceId,
    targetId,
    type,
  };
}

/**
 * 节点状态转中文
 */
export function getNodeStatusLabel(status: NodeStatus): string {
  const labels: Record<NodeStatus, string> = {
    pending: '等待中',
    running: '执行中',
    completed: '已完成',
    skipped: '已跳过',
    failed: '失败',
    cancelled: '已取消',
  };
  return labels[status] || status;
}

/**
 * 节点类型转中文
 */
export function getNodeTypeLabel(type: NodeType): string {
  const labels: Record<NodeType, string> = {
    blueprint: '蓝图',
    architecture: '架构',
    chronicle: '编年',
    'thinking-step': '思维步骤',
    'skill-call': '技能调用',
    'cross-validation': '交叉验证',
    decision: '决策',
    input: '输入',
    output: '输出',
  };
  return labels[type] || type;
}
