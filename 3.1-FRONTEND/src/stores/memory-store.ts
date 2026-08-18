import { create } from 'zustand';

export interface MemoryRecord {
  id: string;
  chain: 'D' | 'Z' | 'E';
  category: string;
  content: string;
  importance: number;
  createdAt: number;
  compressed: boolean;
}

export interface CompressionStats {
  blueprintCount: number;
  architectureCount: number;
  chronicleCount: number;
  compressionRatio: number;
  lastCompressedAt: number | null;
}

export interface DZEChainStatus {
  chain: 'D' | 'Z' | 'E';
  label: string;
  currentStep: number;
  totalSteps: number;
  status: 'idle' | 'running' | 'done' | 'error';
}

interface MemoryState {
  dzeChains: DZEChainStatus[];
  records: MemoryRecord[];
  preferences: Record<string, string>;
  compressionStats: CompressionStats;

  updateChainStatus: (chain: 'D' | 'Z' | 'E', update: Partial<DZEChainStatus>) => void;
  addRecord: (record: Omit<MemoryRecord, 'id' | 'createdAt'>) => void;
  setPreferences: (prefs: Record<string, string>) => void;
  setCompressionStats: (stats: Partial<CompressionStats>) => void;
}

export const useMemoryStore = create<MemoryState>((set) => ({
  dzeChains: [
    { chain: 'D', label: '设计链 D1-D4', currentStep: 0, totalSteps: 4, status: 'idle' },
    { chain: 'Z', label: '工程链 Z1-Z4', currentStep: 0, totalSteps: 4, status: 'idle' },
    { chain: 'E', label: '评估链 E1-E3', currentStep: 0, totalSteps: 3, status: 'idle' },
  ],
  records: [],
  preferences: {},
  compressionStats: { blueprintCount: 0, architectureCount: 0, chronicleCount: 0, compressionRatio: 0, lastCompressedAt: null },

  updateChainStatus: (chain, update) => set(s => ({
    dzeChains: s.dzeChains.map(c => c.chain === chain ? { ...c, ...update } : c),
  })),
  addRecord: (record) => set(s => ({
    records: [...s.records, { ...record, id: `mem_${Date.now()}`, createdAt: Date.now() }],
  })),
  setPreferences: (prefs) => set(s => ({ preferences: { ...s.preferences, ...prefs } })),
  setCompressionStats: (stats) => set(s => ({ compressionStats: { ...s.compressionStats, ...stats } })),
}));
