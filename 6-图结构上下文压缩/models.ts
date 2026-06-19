export type NodeId = string;

export interface DataFlow {
  type: string;
  schema: string;
  description: string;
}

export interface NodeMetadata {
  tokenCost: number;
  latencyMs: number;
  status: 'pending' | 'running' | 'completed' | 'skipped' | 'failed';
  skipReason?: string;
  outputSummary?: string;
  timestamp?: number;
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
