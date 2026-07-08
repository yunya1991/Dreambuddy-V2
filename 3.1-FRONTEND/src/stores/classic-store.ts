import { create } from 'zustand';

export type ClassicPhase = 'C0' | 'C1' | 'C2' | 'C3' | 'C4' | 'C5' | 'C6' | 'C7' | 'C8';
export type GovernanceStage = 'draft' | 'gate' | 'approval' | 'apply' | 'audit';

export interface PhaseState {
  phase: ClassicPhase;
  name: string;
  status: 'idle' | 'running' | 'done' | 'failed' | 'skipped';
  output?: string;
  startedAt?: number;
  completedAt?: number;
}

export interface GovernanceState {
  stage: GovernanceStage;
  status: 'pending' | 'active' | 'approved' | 'rejected';
  reviewer?: string;
  comment?: string;
  timestamp?: number;
}

export interface IndicatorConfig {
  name: string;
  enabled: boolean;
  params: Record<string, number>;
}

interface ClassicState {
  activePhase: ClassicPhase;
  phases: PhaseState[];
  governance: GovernanceState[];
  indicators: IndicatorConfig[];
  timeframe: string;

  setActivePhase: (phase: ClassicPhase) => void;
  updatePhase: (phase: ClassicPhase, update: Partial<PhaseState>) => void;
  setGovernance: (stages: GovernanceState[]) => void;
  updateGovernance: (stage: GovernanceStage, update: Partial<GovernanceState>) => void;
  toggleIndicator: (name: string) => void;
  setTimeframe: (tf: string) => void;
  runPhase: (phase: ClassicPhase) => void;
}

const PHASES: PhaseState[] = [
  { phase: 'C0', name: '环境扫描', status: 'idle' },
  { phase: 'C1', name: '品种筛选', status: 'idle' },
  { phase: 'C2', name: '信号识别', status: 'idle' },
  { phase: 'C3', name: '回测验证', status: 'idle' },
  { phase: 'C4', name: '风险评估', status: 'idle' },
  { phase: 'C5', name: '参数优化', status: 'idle' },
  { phase: 'C6', name: '计划生成', status: 'idle' },
  { phase: 'C7', name: '执行监控', status: 'idle' },
  { phase: 'C8', name: '绩效归因', status: 'idle' },
];

export const useClassicStore = create<ClassicState>((set) => ({
  activePhase: 'C0',
  phases: [...PHASES],
  governance: [],
  indicators: [
    { name: 'RSI', enabled: true, params: { period: 14 } },
    { name: 'MACD', enabled: true, params: { fast: 12, slow: 26, signal: 9 } },
    { name: 'BB', enabled: false, params: { period: 20, stdDev: 2 } },
    { name: 'EMA', enabled: true, params: { period: 21 } },
  ],
  timeframe: '1D',

  setActivePhase: (phase) => set({ activePhase: phase }),
  updatePhase: (phase, update) => set(s => ({
    phases: s.phases.map(p => p.phase === phase ? { ...p, ...update } : p),
  })),
  setGovernance: (stages) => set({ governance: stages }),
  updateGovernance: (stage, update) => set(s => ({
    governance: s.governance.map(g => g.stage === stage ? { ...g, ...update } : g),
  })),
  toggleIndicator: (name) => set(s => ({
    indicators: s.indicators.map(ind => ind.name === name ? { ...ind, enabled: !ind.enabled } : ind),
  })),
  setTimeframe: (tf) => set({ timeframe: tf }),
  runPhase: (phase) => set(s => ({
    activePhase: phase,
    phases: s.phases.map(p => p.phase === phase ? { ...p, status: 'running', startedAt: Date.now() } : p),
  })),
}));
