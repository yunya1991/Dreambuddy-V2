import { create } from 'zustand';

// === 链路追踪类型 ===

export type ChainType = 'S' | 'C' | 'A' | 'F' | 'D' | 'Z' | 'E';
export type ChainStatus = 'idle' | 'running' | 'paused' | 'completed' | 'failed';
export type StepStatus = 'pending' | 'active' | 'done' | 'skipped' | 'failed';
export type ReflectorAction = 'CONTINUE' | 'REDO' | 'INSERT_BEFORE' | 'JUMP_TO' | 'EARLY_TERMINATE' | 'SKIP';

export interface ChainStep {
  id: string;
  name: string;
  chainType: ChainType;
  status: StepStatus;
  startedAt?: string;
  completedAt?: string;
  reflectorAction?: ReflectorAction;
  reflectorReason?: string;
  artifact?: string;
  tokensUsed?: number;
  latencyMs?: number;
}

export interface ReflectorDecision {
  stepId: string;
  action: ReflectorAction;
  reason: string;
  confidence: number;
  timestamp: string;
}

export interface DAGNode {
  id: string;
  label: string;
  status: StepStatus;
  layer: 'S' | 'A' | 'C' | 'G';
  isSkill?: boolean;
  confidence?: number;
}

export interface DAGEdge {
  from: string;
  to: string;
  label?: string;
}

export interface ChainArtifact {
  id: string;
  type: 'text' | 'data' | 'chart' | 'report';
  title: string;
  content: string;
  createdAt: string;
}

interface ChainState {
  // 活跃链
  activeChain: {
    chainId: string;
    chainType: ChainType;
    chainName: string;
    status: ChainStatus;
    startedAt: string;
    completedAt?: string;
  } | null;
  // 步骤
  steps: ChainStep[];
  activeStepIndex: number;
  // Reflector 历史
  reflectorHistory: ReflectorDecision[];
  // DAG (A层)
  dagNodes: DAGNode[];
  dagEdges: DAGEdge[];
  // 产物
  artifacts: ChainArtifact[];
  // 交叉验证
  crossValidation: {
    enabled: boolean;
    votes: { chainType: string; decision: string; confidence: number }[];
    finalDecision?: string;
  };

  // Actions
  setActiveChain: (chain: ChainState['activeChain']) => void;
  clearActiveChain: () => void;
  setSteps: (steps: ChainStep[]) => void;
  updateStep: (stepId: string, update: Partial<ChainStep>) => void;
  setActiveStepIndex: (index: number) => void;
  addReflectorDecision: (decision: ReflectorDecision) => void;
  setDAGNodes: (nodes: DAGNode[]) => void;
  setDAGEdges: (edges: DAGEdge[]) => void;
  updateDAGNode: (nodeId: string, update: Partial<DAGNode>) => void;
  addArtifact: (artifact: ChainArtifact) => void;
  setCrossValidation: (cv: Partial<ChainState['crossValidation']>) => void;
  reset: () => void;
}

export const useChainStore = create<ChainState>((set) => ({
  activeChain: null,
  steps: [],
  activeStepIndex: -1,
  reflectorHistory: [],
  dagNodes: [],
  dagEdges: [],
  artifacts: [],
  crossValidation: { enabled: false, votes: [] },

  setActiveChain: (chain) => set({ activeChain: chain, steps: [], activeStepIndex: -1, reflectorHistory: [], artifacts: [] }),
  clearActiveChain: () => set({ activeChain: null, steps: [], activeStepIndex: -1 }),
  setSteps: (steps) => set({ steps }),
  updateStep: (stepId, update) => set((s) => ({
    steps: s.steps.map(st => st.id === stepId ? { ...st, ...update } : st),
  })),
  setActiveStepIndex: (index) => set({ activeStepIndex: index }),
  addReflectorDecision: (decision) => set((s) => ({
    reflectorHistory: [...s.reflectorHistory, decision],
  })),
  setDAGNodes: (nodes) => set({ dagNodes: nodes }),
  setDAGEdges: (edges) => set({ dagEdges: edges }),
  updateDAGNode: (nodeId, update) => set((s) => ({
    dagNodes: s.dagNodes.map(n => n.id === nodeId ? { ...n, ...update } : n),
  })),
  addArtifact: (artifact) => set((s) => ({
    artifacts: [...s.artifacts, artifact],
  })),
  setCrossValidation: (cv) => set((s) => ({
    crossValidation: { ...s.crossValidation, ...cv },
  })),
  reset: () => set({
    activeChain: null, steps: [], activeStepIndex: -1,
    reflectorHistory: [], dagNodes: [], dagEdges: [],
    artifacts: [], crossValidation: { enabled: false, votes: [] },
  }),
}));
