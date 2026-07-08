import { create } from 'zustand';

export type TradingMode = 'ai_skill' | 'classic';

export interface Position {
  symbol: string;
  side: 'long' | 'short';
  size: number;
  entryPrice: number;
  currentPrice: number;
  pnl: number;
  pnlPercent: number;
  leverage: number;
}

export interface Signal {
  id: string;
  symbol: string;
  direction: 'bullish' | 'bearish' | 'neutral';
  confidence: number;
  source: string;
  timestamp: number;
}

export interface Balance {
  total: number;
  available: number;
  marginUsed: number;
  unrealizedPnl: number;
  currency: string;
}

interface TradingState {
  mode: TradingMode;
  balance: Balance | null;
  positions: Position[];
  signals: Signal[];
  sChainTraces: Array<{ step: string; layer: string; output: string; timestamp: number }>;

  setMode: (mode: TradingMode) => void;
  setBalance: (balance: Balance) => void;
  setPositions: (positions: Position[]) => void;
  addSignal: (signal: Signal) => void;
  addSChainTrace: (trace: { step: string; layer: string; output: string }) => void;
  resetTraces: () => void;
}

export const useTradingStore = create<TradingState>((set) => ({
  mode: 'ai_skill', balance: null, positions: [], signals: [], sChainTraces: [],

  setMode: (mode) => set({ mode }),
  setBalance: (balance) => set({ balance }),
  setPositions: (positions) => set({ positions }),
  addSignal: (signal) => set(s => ({ signals: [signal, ...s.signals] })),
  addSChainTrace: (trace) => set(s => ({ sChainTraces: [...s.sChainTraces, { ...trace, timestamp: Date.now() }] })),
  resetTraces: () => set({ sChainTraces: [] }),
}));
