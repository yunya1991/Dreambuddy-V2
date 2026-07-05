import { create } from 'zustand';

export interface MemoryRecord {
  id: string;
  chain: 'D' | 'Z' | 'E';
  title: string;
  content: string;
  tags: string[];
  createdAt: string;
  compressed: boolean;
}

export interface UserPreference {
  id: string;
  key: string;
  value: string | number | boolean;
  category: string;
  updatedAt: string;
}

export interface DZEChainStatus {
  status: 'idle' | 'running' | 'done' | 'error';
  records: MemoryRecord[];
  lastRunAt?: string;
}

interface MemoryState {
  dzeChains: {
    D: DZEChainStatus;
    Z: DZEChainStatus;
    E: DZEChainStatus;
  };
  preferences: UserPreference[];
  stats: {
    totalMemories: number;
    compressionRatio: number;
    lastEvolutionAt: string;
  };
  isLoading: boolean;

  updateDZEChain: (chain: 'D' | 'Z' | 'E', update: Partial<DZEChainStatus>) => void;
  addMemoryRecord: (chain: 'D' | 'Z' | 'E', record: MemoryRecord) => void;
  setPreferences: (prefs: UserPreference[]) => void;
  setStats: (stats: Partial<MemoryState['stats']>) => void;
  setLoading: (loading: boolean) => void;
}

export const useMemoryStore = create<MemoryState>((set) => ({
  dzeChains: {
    D: { status: 'idle', records: [] },
    Z: { status: 'idle', records: [] },
    E: { status: 'idle', records: [] },
  },
  preferences: [],
  stats: { totalMemories: 0, compressionRatio: 0, lastEvolutionAt: '' },
  isLoading: false,

  updateDZEChain: (chain, update) => set((s) => ({
    dzeChains: { ...s.dzeChains, [chain]: { ...s.dzeChains[chain], ...update } },
  })),
  addMemoryRecord: (chain, record) => set((s) => ({
    dzeChains: {
      ...s.dzeChains,
      [chain]: {
        ...s.dzeChains[chain],
        records: [record, ...s.dzeChains[chain].records].slice(0, 200),
      },
    },
  })),
  setPreferences: (prefs) => set({ preferences: prefs }),
  setStats: (stats) => set((s) => ({ stats: { ...s.stats, ...stats } })),
  setLoading: (loading) => set({ isLoading: loading }),
}));
