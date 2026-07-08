import { create } from 'zustand';

export interface Screen1Data {
  directionAnchor: 'bullish' | 'bearish' | 'neutral' | null;
  dimensions: {
    macro: { score: number; label: string };
    onchain: { score: number; label: string };
    technical: { score: number; label: string };
    sentiment: { score: number; label: string };
    fundamental: { score: number; label: string };
    timing: { score: number; label: string };
    risk: { score: number; label: string };
  };
  debate: string;
  updatedAt?: number;
}

export interface Screen2Data {
  directionConstraint: 'bullish' | 'bearish' | 'neutral' | null;
  presets: Array<{ id: string; symbol: string; entry: number; stop: number; target: number; timeframe: string; confidence: number }>;
  backtest: { winRate: number; avgR: number; maxDD: number; sharpe: number };
  bayesianOpt: { iterations: number; bestParams: Record<string, number>; improvement: number };
  updatedAt?: number;
}

export interface PipelineStep {
  id: string;
  name: string;
  status: 'pending' | 'running' | 'done' | 'failed';
  output?: string;
}

export interface Screen3Data {
  pipeline: PipelineStep[];
  positionState: { symbol: string; side: string; size: number; entry: number; current: number; pnl: number } | null;
  monitorAlerts: Array<{ id: string; level: 'info' | 'warning' | 'critical'; message: string; timestamp: number }>;
  updatedAt?: number;
}

interface ThreeScreensState {
  screen1: Screen1Data | null;
  screen2: Screen2Data | null;
  screen3: Screen3Data | null;
  propagationStatus: 'idle' | 's1_complete' | 's2_complete' | 's3_running' | 'complete';

  setScreen1: (data: Screen1Data) => void;
  setScreen2: (data: Screen2Data) => void;
  setScreen3: (data: Screen3Data) => void;
  updatePipeline: (stepId: string, update: Partial<PipelineStep>) => void;
  reset: () => void;
}

export const useThreeScreensStore = create<ThreeScreensState>((set) => ({
  screen1: null, screen2: null, screen3: null, propagationStatus: 'idle',

  setScreen1: (data) => set({ screen1: data, propagationStatus: 's1_complete' }),
  setScreen2: (data) => set({ screen2: data, propagationStatus: 's2_complete' }),
  setScreen3: (data) => set({ screen3: data, propagationStatus: 's3_running' }),
  updatePipeline: (stepId, update) => set(s => {
    if (!s.screen3) return s;
    return { screen3: { ...s.screen3, pipeline: s.screen3.pipeline.map(p => p.id === stepId ? { ...p, ...update } : p) } };
  }),
  reset: () => set({ screen1: null, screen2: null, screen3: null, propagationStatus: 'idle' }),
}));
