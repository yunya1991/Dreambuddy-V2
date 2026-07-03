import { create } from "zustand";
import type { ChainTrace, OrchestrationNode } from "@/types";

interface OrchestrationState {
  trace: ChainTrace | null;
  history: ChainTrace[];
  isExecuting: boolean;

  setTrace: (trace: ChainTrace | null) => void;
  startExecution: () => void;
  finishExecution: () => void;
  updateNode: (nodeId: string, patch: Partial<OrchestrationNode>) => void;
  clear: () => void;
}

export const useOrchestrationStore = create<OrchestrationState>((set) => ({
  trace: null,
  history: [],
  isExecuting: false,

  setTrace: (trace) => set({ trace }),

  startExecution: () => set({ isExecuting: true }),

  finishExecution: () =>
    set((state) => ({
      isExecuting: false,
      history: state.trace
        ? [state.trace, ...state.history].slice(0, 20)
        : state.history,
    })),

  updateNode: (nodeId, patch) =>
    set((state) => {
      if (!state.trace) return state;
      return {
        trace: {
          ...state.trace,
          nodes: state.trace.nodes.map((n) =>
            n.id === nodeId ? { ...n, ...patch } : n
          ),
        },
      };
    }),

  clear: () => set({ trace: null, isExecuting: false }),
}));
