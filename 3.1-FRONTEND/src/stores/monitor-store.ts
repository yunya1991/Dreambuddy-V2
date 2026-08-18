import { create } from 'zustand';
import type { SACELayer } from './chain-store';

export interface SACGLayerEvent {
  id: string;
  layer: SACELayer;
  type: string;
  description: string;
  timestamp: number;
  duration?: number;
}

export interface PipelineThroughput {
  totalProcessed: number;
  successRate: number;
  avgLatencyMs: number;
  activeCount: number;
}

export interface SSEConnectionState {
  status: 'disconnected' | 'connecting' | 'connected' | 'error';
  lastEventAt: number | null;
  reconnectCount: number;
}

interface MonitorState {
  sLayerEvents: SACGLayerEvent[];
  aLayerEvents: SACGLayerEvent[];
  cLayerEvents: SACGLayerEvent[];
  gLayerEvents: SACGLayerEvent[];
  pipelineThroughput: PipelineThroughput;
  sseConnection: SSEConnectionState;

  addEvent: (layer: SACELayer, event: SACGLayerEvent) => void;
  setThroughput: (tp: PipelineThroughput) => void;
  setSSEStatus: (status: SSEConnectionState['status']) => void;
  clearEvents: (layer?: SACELayer) => void;
}

const initialThroughput: PipelineThroughput = { totalProcessed: 0, successRate: 0, avgLatencyMs: 0, activeCount: 0 };

export const useMonitorStore = create<MonitorState>((set) => ({
  sLayerEvents: [], aLayerEvents: [], cLayerEvents: [], gLayerEvents: [],
  pipelineThroughput: initialThroughput,
  sseConnection: { status: 'disconnected', lastEventAt: null, reconnectCount: 0 },

  addEvent: (layer, event) => set(s => {
    const key = `${layer.toLowerCase()}LayerEvents` as keyof MonitorState;
    return { [key]: [...(s[key] as SACGLayerEvent[]), event] };
  }),
  setThroughput: (tp) => set({ pipelineThroughput: tp }),
  setSSEStatus: (status) => set(s => ({
    sseConnection: { ...s.sseConnection, status, lastEventAt: Date.now() },
  })),
  clearEvents: (layer) => {
    if (!layer) return set({ sLayerEvents: [], aLayerEvents: [], cLayerEvents: [], gLayerEvents: [] });
    const key = `${layer.toLowerCase()}LayerEvents` as keyof MonitorState;
    return set(s => ({ [key]: [] }));
  },
}));
