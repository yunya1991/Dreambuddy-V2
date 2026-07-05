import { create } from 'zustand';
import type { StrategyView, TradingParamsView } from '@/types';

export type TradingMode = 'ai_skill' | 'classic';

export interface BalanceInfo {
  totalEquity: number;
  availableBalance: number;
  unrealizedPnl: number;
  currency: string;
  updatedAt: string;
}

export interface PositionInfo {
  id: string;
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entryPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  leverage: number;
  margin: number;
  liquidationPrice?: number;
  openedAt: string;
}

export interface TradingSignal {
  id: string;
  symbol: string;
  direction: 'BUY' | 'SHORT' | 'SKIP';
  confidence: number;
  strategy: string;
  price: number;
  timestamp: string;
}

export interface SChainTrace {
  sessionId: string;
  chainType: string; // S0-S5
  startedAt: string;
  completedAt?: string;
  steps: { id: string; name: string; status: string; result?: string }[];
  finalAnswer?: string;
}

interface TradingState {
  mode: TradingMode;
  aiSkill: {
    isConnected: boolean;
    activeStrategies: StrategyView[];
    balance: BalanceInfo | null;
    positions: PositionInfo[];
    recentSignals: TradingSignal[];
  };
  sChainTraces: SChainTrace[];
  params: TradingParamsView | null;
  isLoading: boolean;

  setMode: (mode: TradingMode) => void;
  setAiSkillConnected: (connected: boolean) => void;
  setActiveStrategies: (strategies: StrategyView[]) => void;
  updateBalance: (balance: BalanceInfo) => void;
  setPositions: (positions: PositionInfo[]) => void;
  addSignal: (signal: TradingSignal) => void;
  clearSignals: () => void;
  addSChainTrace: (trace: SChainTrace) => void;
  setParams: (params: TradingParamsView) => void;
  setLoading: (loading: boolean) => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  mode: 'ai_skill',
  aiSkill: {
    isConnected: false,
    activeStrategies: [],
    balance: null,
    positions: [],
    recentSignals: [],
  },
  sChainTraces: [],
  params: null,
  isLoading: false,

  setMode: (mode) => set({ mode }),
  setAiSkillConnected: (connected) => set((s) => ({
    aiSkill: { ...s.aiSkill, isConnected: connected },
  })),
  setActiveStrategies: (strategies) => set((s) => ({
    aiSkill: { ...s.aiSkill, activeStrategies: strategies },
  })),
  updateBalance: (balance) => set((s) => ({
    aiSkill: { ...s.aiSkill, balance },
  })),
  setPositions: (positions) => set((s) => ({
    aiSkill: { ...s.aiSkill, positions },
  })),
  addSignal: (signal) => set((s) => ({
    aiSkill: { ...s.aiSkill, recentSignals: [signal, ...s.aiSkill.recentSignals].slice(0, 50) },
  })),
  clearSignals: () => set((s) => ({
    aiSkill: { ...s.aiSkill, recentSignals: [] },
  })),
  addSChainTrace: (trace) => set((s) => ({
    sChainTraces: [trace, ...s.sChainTraces].slice(0, 100),
  })),
  setParams: (params) => set({ params }),
  setLoading: (loading) => set({ isLoading: loading }),
}));
