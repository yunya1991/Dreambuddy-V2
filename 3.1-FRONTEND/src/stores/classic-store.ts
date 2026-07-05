import { create } from 'zustand';

export type ClassicPhase = 'C0_DIRECT_ANSWER' | 'C1_MACRO_SCAN' | 'C2_UNIVERSE_SCAN' | 'C3_GATE_CHECK' | 'C4_ARENA_REVIEW' | 'C5_STRATEGY_SELECT' | 'C6_SIGNAL_REVIEW' | 'C7_EXIT_MONITOR' | 'C8_TRACKING_AUDIT';

export type PhaseStatus = 'idle' | 'running' | 'done' | 'failed' | 'skipped';

export interface PhaseState {
  status: PhaseStatus;
  startedAt?: string;
  completedAt?: string;
  result?: string;
  error?: string;
}

export type GovernanceStage = 'draft' | 'gate' | 'approval' | 'apply' | 'audit';

export interface GovernanceProposal {
  id: string;
  title: string;
  description: string;
  stage: GovernanceStage;
  votes: { approved: boolean; voter: string; reason?: string }[];
  createdAt: string;
  updatedAt: string;
}

export interface ClassicIndicator {
  id: string;
  name: string;
  category: string;
  parameters: Record<string, number | string | boolean>;
  isEnabled: boolean;
}

interface ClassicState {
  // C0-C8 阶段
  phases: Record<ClassicPhase, PhaseState>;
  activePhase: ClassicPhase | null;
  // 治理
  governance: {
    proposals: GovernanceProposal[];
    activeProposalId: string | null;
    currentStage: GovernanceStage;
  };
  // 配置
  config: {
    knowledgeSource: number;
    indicatorSet: ClassicIndicator[];
    timeframe: string;
  };
  isLoading: boolean;

  setPhaseStatus: (phase: ClassicPhase, status: PhaseStatus) => void;
  updatePhase: (phase: ClassicPhase, update: Partial<PhaseState>) => void;
  setActivePhase: (phase: ClassicPhase | null) => void;
  addProposal: (proposal: GovernanceProposal) => void;
  updateProposalStage: (id: string, stage: GovernanceStage) => void;
  setGovernanceStage: (stage: GovernanceStage) => void;
  setIndicators: (indicators: ClassicIndicator[]) => void;
  toggleIndicator: (id: string) => void;
  setTimeframe: (tf: string) => void;
  setLoading: (loading: boolean) => void;
  resetPhases: () => void;
}

const initialPhases: Record<ClassicPhase, PhaseState> = {
  C0_DIRECT_ANSWER: { status: 'idle' },
  C1_MACRO_SCAN: { status: 'idle' },
  C2_UNIVERSE_SCAN: { status: 'idle' },
  C3_GATE_CHECK: { status: 'idle' },
  C4_ARENA_REVIEW: { status: 'idle' },
  C5_STRATEGY_SELECT: { status: 'idle' },
  C6_SIGNAL_REVIEW: { status: 'idle' },
  C7_EXIT_MONITOR: { status: 'idle' },
  C8_TRACKING_AUDIT: { status: 'idle' },
};

export const useClassicStore = create<ClassicState>((set) => ({
  phases: { ...initialPhases },
  activePhase: null,
  governance: { proposals: [], activeProposalId: null, currentStage: 'draft' },
  config: { knowledgeSource: 10, indicatorSet: [], timeframe: '1d' },
  isLoading: false,

  setPhaseStatus: (phase, status) => set((s) => ({
    phases: { ...s.phases, [phase]: { ...s.phases[phase], status } },
  })),
  updatePhase: (phase, update) => set((s) => ({
    phases: { ...s.phases, [phase]: { ...s.phases[phase], ...update } },
  })),
  setActivePhase: (phase) => set({ activePhase: phase }),
  addProposal: (proposal) => set((s) => ({
    governance: { ...s.governance, proposals: [proposal, ...s.governance.proposals] },
  })),
  updateProposalStage: (id, stage) => set((s) => ({
    governance: {
      ...s.governance,
      proposals: s.governance.proposals.map(p => p.id === id ? { ...p, stage, updatedAt: new Date().toISOString() } : p),
    },
  })),
  setGovernanceStage: (stage) => set((s) => ({
    governance: { ...s.governance, currentStage: stage },
  })),
  setIndicators: (indicators) => set((s) => ({
    config: { ...s.config, indicatorSet: indicators },
  })),
  toggleIndicator: (id) => set((s) => ({
    config: {
      ...s.config,
      indicatorSet: s.config.indicatorSet.map(ind =>
        ind.id === id ? { ...ind, isEnabled: !ind.isEnabled } : ind
      ),
    },
  })),
  setTimeframe: (tf) => set((s) => ({ config: { ...s.config, timeframe: tf } })),
  setLoading: (loading) => set({ isLoading: loading }),
  resetPhases: () => set({ phases: { ...initialPhases }, activePhase: null }),
}));
