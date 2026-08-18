export type NodeId = string;

export interface DataFlow {
  type: string;
  schema: string;
  description: string;
}

/** OKR 时间维度（与 intent-gateway 对齐） */
export type OKRHorizon = 'long' | 'mid' | 'short';

export interface NodeMetadata {
  tokenCost: number;
  latencyMs: number;
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed' | 'compressed';
  skipReason?: string;
  outputSummary?: string;
  timestamp?: number;
  tags?: string[];
  /**
   * OKR 时间维度：
   *   long  = B 层目标节点（跨多轮持久，由意图识别写入）
   *   mid   = A 层执行步骤（当轮计划，由 Planner 生成）
   *   short = C 层执行记录（当步实际执行，Chronicle 节点）
   */
  horizon?: OKRHorizon;
  /** 所属意图目标 ID（来自 IntentGateway） */
  intentGoalId?: string;
  /** 笔记本标题（当节点被作为笔记使用时） */
  noteTitle?: string;
  /** 笔记内容摘要（短任务便签） */
  noteContent?: string;
}

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
}

export interface CompressionResult {
  compressedChronicle: ChronicleGraph;
  compressedArchitecture: ArchitectureGraph;
  blueprint: BlueprintGraph;
  compressionRatio: number;
  retainedContext: number;
  discardedDetails: { nodeId: string; reason: string }[];
}

export interface ExpansionResult {
  expandedArchitecture: ArchitectureGraph;
  expandedChronicle: ChronicleGraph;
  expansionDepth: number;
}
