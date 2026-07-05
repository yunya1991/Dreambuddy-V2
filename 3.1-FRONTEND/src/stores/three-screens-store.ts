import { create } from 'zustand';

export type ThreeScreenTab = 'overview' | 'screen1' | 'screen2' | 'screen3' | 'pipeline' | 'history';

// === Screen1 视图模型 ===
export interface DimensionScore {
  score: number;
  signal: string;
}

export interface DirectionAnchor {
  ma200Status: 'above' | 'below' | 'crossing';
  threeDayConfirm: boolean;
  direction: 'LONG' | 'SHORT';
  overallScore: number;
  confidence: number;
}

export interface DebatePanel {
  bullCase: string;
  bearCase: string;
  synthesis: string;
}

export interface Screen1Data {
  symbol: string;
  dimensions: {
    technical: DimensionScore;
    halving: DimensionScore;
    miner: DimensionScore;
    onchain: DimensionScore;
    macro: DimensionScore;
    intermarket: DimensionScore;
    sentiment: DimensionScore;
  };
  directionAnchor: DirectionAnchor;
  debate: DebatePanel;
  status: 'idle' | 'analyzing' | 'done' | 'error';
  updatedAt: string;
}

// === Screen2 视图模型 ===
export interface PresetPrice {
  entry: { price: number; strength: 'strong' | 'moderate' | 'weak' };
  addPosition: { price: number; size: number };
  takeProfit: { price: number; levels: number[] };
  stopLoss: { price: number; levels: number[] };
}

export interface BacktestResult {
  winRate: number;
  avgReturn: number;
  maxDrawdown: number;
  sampleSize: number;
}

export interface BayesianOptResult {
  bestParams: Record<string, number>;
  iterations: number;
  improvement: number;
}

export interface Screen2Data {
  symbol: string;
  directionConstraint: 'LONG' | 'SHORT';
  presets: PresetPrice;
  backtest: BacktestResult;
  bayesianOpt: BayesianOptResult;
  status: 'idle' | 'waiting_screen1' | 'computing' | 'done' | 'error';
}

// === Screen3 视图模型 ===
export type PipelineStepId = 'A7_GATE' | 'A4_VALIDATE' | 'C3_GATE' | 'A5_ENTRY' | 'A6_MONITOR' | 'A9_EXIT';
export type PipelineStepStatus = 'pending' | 'active' | 'passed' | 'failed' | 'skipped';

export interface PipelineStep {
  id: PipelineStepId;
  name: string;
  status: PipelineStepStatus;
  decision: string;
  timestamp: string | null;
  details: string;
}

export interface PositionState {
  isOpen: boolean;
  size: number;
  entryPrice: number;
  currentPrice: number;
  unrealizedPnl: number;
  leverage: number;
}

export interface Alert {
  id: string;
  type: string;
  message: string;
  severity: 'info' | 'warning' | 'critical';
  createdAt: string;
}

export interface Screen3Data {
  symbol: string;
  directionConstraint: 'LONG' | 'SHORT';
  presetConstraint: PresetPrice;
  pipeline: {
    steps: PipelineStep[];
    currentStep: PipelineStepId | null;
    triggeredAt: string | null;
  };
  position: PositionState;
  monitor: {
    alertCount: number;
    lastAlertAt: string;
    activeAlerts: Alert[];
  };
  status: 'idle' | 'waiting' | 'executing' | 'done' | 'error';
}

// === Store ===
interface ThreeScreensState {
  activeScreen: ThreeScreenTab;
  symbol: string;
  screen1: Screen1Data | null;
  screen2: Screen2Data | null;
  screen3: Screen3Data | null;

  directionConstraint: {
    direction: 'LONG' | 'SHORT' | null;
    source: 'screen1' | 'manual' | null;
    lockedAt: string | null;
  };
  presetConstraint: PresetPrice | null;

  setActiveScreen: (screen: ThreeScreenTab) => void;
  setSymbol: (symbol: string) => void;
  updateScreen1: (data: Partial<Screen1Data>) => void;
  setScreen1: (data: Screen1Data) => void;
  updateScreen2: (data: Partial<Screen2Data>) => void;
  setScreen2: (data: Screen2Data) => void;
  updateScreen3: (data: Partial<Screen3Data>) => void;
  setScreen3: (data: Screen3Data) => void;
  propagateDirection: (direction: 'LONG' | 'SHORT') => void;
  propagatePresets: (presets: PresetPrice) => void;
  resetAll: () => void;
}

const emptyPosition: PositionState = {
  isOpen: false, size: 0, entryPrice: 0, currentPrice: 0, unrealizedPnl: 0, leverage: 1,
};

const emptyPipeline = {
  steps: [
    { id: 'A7_GATE' as const, name: 'A7 风控门禁', status: 'pending' as const, decision: '', timestamp: null, details: '' },
    { id: 'A4_VALIDATE' as const, name: 'A4 方案验证', status: 'pending' as const, decision: '', timestamp: null, details: '' },
    { id: 'C3_GATE' as const, name: 'C3 门禁检查', status: 'pending' as const, decision: '', timestamp: null, details: '' },
    { id: 'A5_ENTRY' as const, name: 'A5 入场执行', status: 'pending' as const, decision: '', timestamp: null, details: '' },
    { id: 'A6_MONITOR' as const, name: 'A6 情报监控', status: 'pending' as const, decision: '', timestamp: null, details: '' },
    { id: 'A9_EXIT' as const, name: 'A9 离场评估', status: 'pending' as const, decision: '', timestamp: null, details: '' },
  ],
  currentStep: null,
  triggeredAt: null,
};

export const useThreeScreensStore = create<ThreeScreensState>((set) => ({
  activeScreen: 'overview',
  symbol: 'BTC/USDT',
  screen1: null,
  screen2: null,
  screen3: null,
  directionConstraint: { direction: null, source: null, lockedAt: null },
  presetConstraint: null,

  setActiveScreen: (screen) => set({ activeScreen: screen }),
  setSymbol: (symbol) => set({ symbol }),
  updateScreen1: (data) => set((s) => ({
    screen1: s.screen1 ? { ...s.screen1, ...data } : null,
  })),
  setScreen1: (data) => set({ screen1: data }),
  updateScreen2: (data) => set((s) => ({
    screen2: s.screen2 ? { ...s.screen2, ...data } : null,
  })),
  setScreen2: (data) => set({ screen2: data }),
  updateScreen3: (data) => set((s) => ({
    screen3: s.screen3 ? { ...s.screen3, ...data } : null,
  })),
  setScreen3: (data) => set({ screen3: data }),
  propagateDirection: (direction) => set({
    directionConstraint: { direction, source: 'screen1', lockedAt: new Date().toISOString() },
  }),
  propagatePresets: (presets) => set({
    presetConstraint: presets,
  }),
  resetAll: () => set({
    screen1: null, screen2: null, screen3: null,
    directionConstraint: { direction: null, source: null, lockedAt: null },
    presetConstraint: null,
  }),
}));
