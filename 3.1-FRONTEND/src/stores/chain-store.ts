import { create } from 'zustand';

export type ChainType = 'research' | 'trading' | 'fundamental' | 'risk' | 'custom';
export type ReflectorAction = 'CONTINUE' | 'REDO' | 'INSERT_BEFORE' | 'JUMP_TO' | 'EARLY_TERMINATE' | 'SKIP';
export type SACELayer = 'S' | 'A' | 'C' | 'G';

export interface ChainStep {
  id: string;
  index: number;
  name: string;
  layer: SACELayer;
  status: 'pending' | 'running' | 'done' | 'failed' | 'skipped';
  inputSummary?: string;
  outputSummary?: string;
  tokens?: number;
  latencyMs?: number;
  reflectorDecision?: ReflectorAction;
  reflectorReason?: string;
  startedAt?: number;
  completedAt?: number;
}

export interface DAGNode {
  id: string;
  label: string;
  layer: SACELayer;
  status: 'idle' | 'active' | 'done' | 'error';
  x?: number;
  y?: number;
}

export interface DAGEdge {
  from: string;
  to: string;
  label?: string;
}

export interface CrossValidation {
  chainId: string;
  result: 'pass' | 'fail' | 'partial';
  confidence: number;
  disagreements: string[];
}

// chain_trace 中的节点结构 (来自后端 /api/task/stream 的 done 事件)
export interface ChainTraceNode {
  id: string;
  name: string;
  icon?: string;
  layer: string;
  stage?: string;
  chain?: string;
  is_skill?: boolean;
  status: string;
  confidence?: number;
  tokens_used?: number;
  latency_ms?: number;
  reflect_action?: string;
}

export interface ChainTrace {
  intent?: { type: string; confidence: number; method: string; entities?: Record<string, unknown> };
  plan?: { chain_id: string; chain_name: string; planned_steps: Array<Record<string, unknown>>; complexity: string; total_budget: number; rationale: string };
  nodes: ChainTraceNode[];
  final?: { execution_chain: string; quality_score: number; risk_score: number; grade: string };
}

interface ChainState {
  activeChain: ChainType | null;
  chainId: string | null;
  steps: ChainStep[];
  currentStepIndex: number;
  reflectorHistory: Array<{ stepId: string; action: ReflectorAction; reason: string; timestamp: number }>;
  dagNodes: DAGNode[];
  dagEdges: DAGEdge[];
  crossValidations: CrossValidation[];
  artifacts: Array<{ id: string; type: string; title: string; createdAt: number }>;
  chainTrace: ChainTrace | null;
  qualityScore: number | null;

  startChain: (type: ChainType, steps: Omit<ChainStep, 'status'>[]) => void;
  updateStep: (stepId: string, update: Partial<ChainStep>) => void;
  reflectorDecision: (stepId: string, action: ReflectorAction, reason: string) => void;
  setDAG: (nodes: DAGNode[], edges: DAGEdge[]) => void;
  addCrossValidation: (cv: CrossValidation) => void;
  addArtifact: (artifact: { id: string; type: string; title: string }) => void;
  setChainTrace: (trace: ChainTrace) => void;
  resetChain: () => void;
}

export const useChainStore = create<ChainState>((set, get) => ({
  activeChain: null, chainId: null, steps: [], currentStepIndex: -1,
  reflectorHistory: [], dagNodes: [], dagEdges: [], crossValidations: [], artifacts: [],
  chainTrace: null, qualityScore: null,

  startChain: (type, steps) => set({
    activeChain: type, chainId: `chain_${Date.now()}`, currentStepIndex: 0,
    steps: steps.map(s => ({ ...s, status: 'pending' as const })),
    reflectorHistory: [], crossValidations: [], artifacts: [],
  }),

  updateStep: (stepId, update) => set(s => ({
    steps: s.steps.map(st => st.id === stepId ? { ...st, ...update } : st),
  })),

  reflectorDecision: (stepId, action, reason) => set(s => ({
    reflectorHistory: [...s.reflectorHistory, { stepId, action, reason, timestamp: Date.now() }],
  })),

  setDAG: (nodes, edges) => set({ dagNodes: nodes, dagEdges: edges }),
  addCrossValidation: (cv) => set(s => ({ crossValidations: [...s.crossValidations, cv] })),
  addArtifact: (artifact) => set(s => ({ artifacts: [...s.artifacts, { ...artifact, createdAt: Date.now() }] })),
  setChainTrace: (trace) => set({
    chainTrace: trace,
    qualityScore: trace.final?.quality_score ?? null,
    // 同步更新 DAG nodes
    dagNodes: trace.nodes.map(n => ({
      id: n.id,
      label: n.name,
      layer: (['S', 'A', 'C', 'G'].includes(n.layer) ? n.layer : 'A') as SACELayer,
      status: n.status === 'done' ? 'done' : n.status === 'active' ? 'active' : n.status === 'error' ? 'error' : 'idle',
    })),
    dagEdges: trace.nodes.slice(1).map((n, i) => ({
      from: trace.nodes[i].id,
      to: n.id,
    })),
  }),
  resetChain: () => set({ activeChain: null, chainId: null, steps: [], currentStepIndex: -1, reflectorHistory: [], dagNodes: [], dagEdges: [], crossValidations: [], artifacts: [], chainTrace: null, qualityScore: null }),
}));
