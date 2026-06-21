/**
 * 图文笔记压缩模型 — 类型定义
 * B→A→C 三层模型: Blueprint (架构层) → Architecture (DAG层) → Chronicle (执行层)
 */

export type NodeId = string;

export type NodeStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'skipped'
  | 'compressed'
  | 'failed';

export interface DataFlow {
  type: string;
  schema: string;
  description: string;
}

export interface NodeMetadata {
  tokenCost: number;
  latencyMs: number;
  status: NodeStatus;
  skipReason?: string;
  outputSummary?: string;
  timestamp?: number;
  tags?: string[];
}

// ============= B 层: Blueprint =============
export interface BNode {
  id: NodeId;
  type: 'component' | 'module' | 'service';
  name: string;
  description: string;
  metadata: NodeMetadata;
  children?: NodeId[];
}

export interface BEdge {
  source: NodeId;
  target: NodeId;
  dataFlow: DataFlow;
  label?: string;
}

export interface BlueprintGraph {
  id: string;
  name: string;
  version: string;
  nodes: Map<NodeId, BNode>;
  edges: BEdge[];
  rootId: NodeId;
  createdAt: number;
}

// ============= A 层: Architecture (DAG) =============
export interface ANode {
  id: NodeId;
  type: 'step' | 'decision' | 'parallel';
  name: string;
  parentNodeId: NodeId;
  metadata: NodeMetadata;
  requires?: NodeId[];
  branches?: { condition: string; target: NodeId }[];
}

export interface AEdge {
  source: NodeId;
  target: NodeId;
  dataFlow: DataFlow;
  isConditional?: boolean;
}

export interface ArchitectureGraph {
  id: string;
  blueprintId: string;
  nodes: Map<NodeId, ANode>;
  edges: AEdge[];
  entryPoint: NodeId;
  createdAt: number;
}

// ============= C 层: Chronicle =============
export interface CNode {
  id: NodeId;
  architectureNodeId: NodeId;
  executionId: string;
  startTime: number;
  endTime?: number;
  metadata: NodeMetadata;
  inputs: Record<string, any>;
  outputs: Record<string, any>;
  logs: string[];
}

export interface CEdge {
  source: NodeId;
  target: NodeId;
  timestamp: number;
  dataFlow: DataFlow;
  payloadSummary: string;
}

export interface ChronicleGraph {
  id: string;
  architectureId: string;
  nodes: Map<NodeId, CNode>;
  edges: CEdge[];
  executionId: string;
  startedAt: number;
  completedAt?: number;
  /** 原始大小（字节）—— 用于压缩对比 */
  rawSizeBytes?: number;
}

// ============= 压缩结果 =============
export interface CompressionResult {
  compressedChronicle: ChronicleGraph;
  compressedArchitecture: ArchitectureGraph;
  blueprint: BlueprintGraph;
  /** 压缩后大小 / 原始大小 */
  compressionRatio: number;
  /** 保留的上下文信息比例 */
  retainedContext: number;
  /** 被丢弃的详细信息 */
  discardedDetails: { nodeId: string; reason: string }[];
  /** 价值评分（用于调试） */
  nodeScores?: Map<NodeId, number>;
}

export interface CompressionOptions {
  /** 目标压缩比 0-1，默认 0.5 */
  targetRatio?: number;
  /** 各指标权重 */
  weights?: {
    tokenCost: number;
    latency: number;
    structuralPosition: number;
    semanticImportance: number;
  };
  /** 是否保留所有边（即便源/目标被压缩） */
  keepAllEdges?: boolean;
  /** 最小保留节点数 */
  minNodes?: number;
}
