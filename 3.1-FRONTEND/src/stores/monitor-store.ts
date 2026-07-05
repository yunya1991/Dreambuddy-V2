import { create } from 'zustand';

export interface MonitorEvent {
  id: string;
  layer: 'S' | 'A' | 'C' | 'G';
  type: string;
  message: string;
  severity: 'info' | 'warning' | 'error';
  timestamp: string;
}

export interface PipelineStatus {
  pipelineId: string;
  name: string;
  status: 'idle' | 'running' | 'error';
  throughput: number;
  avgLatencyMs: number;
}

interface MonitorState {
  layers: {
    S: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    A: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    C: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
    G: { status: 'idle' | 'active' | 'error'; events: MonitorEvent[] };
  };
  pipeline: {
    activePipelines: PipelineStatus[];
    throughput: { rps: number; avgLatencyMs: number };
  };
  sseConnection: 'disconnected' | 'connecting' | 'connected' | 'error';

  pushEvent: (layer: 'S' | 'A' | 'C' | 'G', event: MonitorEvent) => void;
  setLayerStatus: (layer: 'S' | 'A' | 'C' | 'G', status: 'idle' | 'active' | 'error') => void;
  setSSEStatus: (status: MonitorState['sseConnection']) => void;
  updatePipeline: (pipelines: PipelineStatus[]) => void;
  setThroughput: (t: { rps: number; avgLatencyMs: number }) => void;
  clearEvents: (layer?: 'S' | 'A' | 'C' | 'G') => void;
}

export const useMonitorStore = create<MonitorState>((set) => ({
  layers: {
    S: { status: 'idle', events: [] },
    A: { status: 'idle', events: [] },
    C: { status: 'idle', events: [] },
    G: { status: 'idle', events: [] },
  },
  pipeline: { activePipelines: [], throughput: { rps: 0, avgLatencyMs: 0 } },
  sseConnection: 'disconnected',

  pushEvent: (layer, event) => set((s) => ({
    layers: {
      ...s.layers,
      [layer]: {
        ...s.layers[layer],
        events: [event, ...s.layers[layer].events].slice(0, 200),
      },
    },
  })),
  setLayerStatus: (layer, status) => set((s) => ({
    layers: { ...s.layers, [layer]: { ...s.layers[layer], status } },
  })),
  setSSEStatus: (status) => set({ sseConnection: status }),
  updatePipeline: (pipelines) => set((s) => ({
    pipeline: { ...s.pipeline, activePipelines: pipelines },
  })),
  setThroughput: (t) => set((s) => ({
    pipeline: { ...s.pipeline, throughput: t },
  })),
  clearEvents: (layer) => set((s) => {
    if (!layer) {
      return {
        layers: {
          S: { ...s.layers.S, events: [] },
          A: { ...s.layers.A, events: [] },
          C: { ...s.layers.C, events: [] },
          G: { ...s.layers.G, events: [] },
        },
      };
    }
    return {
      layers: { ...s.layers, [layer]: { ...s.layers[layer], events: [] } },
    };
  }),
}));
