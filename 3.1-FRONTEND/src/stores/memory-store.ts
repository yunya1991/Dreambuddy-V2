import { create } from 'zustand';
import { useCallback } from 'react';

// ============================================================
// 平台 VM 层记忆 store (P0 M2 + P3 双向交互)
// 复刻 dream-harness-bridge P0-5 模式 (VM-1789618914215):
//  - fetch action 调 /api/cognitive/* HTTP 端点
//  - FAIL-OPEN degraded: 后端不可达时降级 banner
//  - 自动刷新: record/verify 后自动 fetchRecall + fetchStats
// 硬约束 (VM-1786242777697): 平台层只读 VM, 不写用户层
// ============================================================

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

export type QualityLevel = 'S' | 'A' | 'B' | 'C' | 'D';

// P3 真实 VM 记录 (cognitive recall 返回结构)
export interface VmRecord {
  id: string;
  content: string;
  score?: number;
  quality_level?: QualityLevel;
  confidence?: number;
  verify_count?: number;
  source?: string;
  tags?: string[] | string;
  created_at?: number;
  [key: string]: unknown;
}

// P3 stats (cognitive stats 返回结构, 字段动态)
// 实际返回: { memory: {total_memories, quality_distribution, type_distribution, status}, distill: {...}, capacity: {...} }
export interface MemoryStats {
  memories_count?: number;
  count?: number;
  memory?: {
    total_memories?: number;
    quality_distribution?: Record<string, number>;
    type_distribution?: Record<string, number>;
    status?: string;
    [key: string]: unknown;
  };
  distill?: { status?: string; [key: string]: unknown };
  quality_distribution?: Record<string, number>;
  type_distribution?: Record<string, number>;
  layers?: Record<string, unknown>;
  health?: Record<string, unknown>;
  [key: string]: unknown;
}

interface MemoryState {
  // 静态 DZE 压缩链 (P0 前保留)
  dzeChains: DZEChainStatus[];
  records: MemoryRecord[];
  preferences: Record<string, string>;
  compressionStats: CompressionStats;
  // P0 M2 + P3 新增
  vmRecords: VmRecord[];
  stats: MemoryStats | null;
  degraded: boolean;
  loading: boolean;
  error: string | null;

  updateChainStatus: (chain: 'D' | 'Z' | 'E', update: Partial<DZEChainStatus>) => void;
  addRecord: (record: Omit<MemoryRecord, 'id' | 'createdAt'>) => void;
  setPreferences: (prefs: Record<string, string>) => void;
  setCompressionStats: (stats: Partial<CompressionStats>) => void;

  // P3 fetch actions
  fetchRecall: (context?: string, topK?: number, minQuality?: QualityLevel) => Promise<void>;
  recordExperience: (content: string, qualityLevel: QualityLevel, tags: string) => Promise<string | null>;
  verifyMemory: (memoryId: string, success: boolean) => Promise<boolean>;
  fetchStats: () => Promise<void>;
}

const COG_API = '/api/cognitive';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error((errBody as { error?: string }).error || `HTTP ${res.status}`);
    }
    return (await res.json()) as T;
  } catch {
    return null;
  }
}

export const useMemoryStore = create<MemoryState>((set, get) => ({
  dzeChains: [
    { chain: 'D', label: '设计链 D1-D4', currentStep: 0, totalSteps: 4, status: 'idle' },
    { chain: 'Z', label: '工程链 Z1-Z4', currentStep: 0, totalSteps: 4, status: 'idle' },
    { chain: 'E', label: '评估链 E1-E3', currentStep: 0, totalSteps: 3, status: 'idle' },
  ],
  records: [],
  preferences: {},
  compressionStats: { blueprintCount: 0, architectureCount: 0, chronicleCount: 0, compressionRatio: 0, lastCompressedAt: null },

  vmRecords: [],
  stats: null,
  degraded: false,
  loading: false,
  error: null,

  updateChainStatus: (chain, update) => set(s => ({
    dzeChains: s.dzeChains.map(c => c.chain === chain ? { ...c, ...update } : c),
  })),
  addRecord: (record) => set(s => ({
    records: [...s.records, { ...record, id: `mem_${Date.now()}`, createdAt: Date.now() }],
  })),
  setPreferences: (prefs) => set(s => ({ preferences: { ...s.preferences, ...prefs } })),
  setCompressionStats: (stats) => set(s => ({ compressionStats: { ...s.compressionStats, ...stats } })),

  fetchRecall: async (context = 'recent', topK = 20, minQuality: QualityLevel = 'C') => {
    set({ loading: true, error: null });
    const url = `${COG_API}/recall?context=${encodeURIComponent(context)}&top_k=${topK}&min_quality=${minQuality}`;
    const data = await fetchJson<{ memories?: VmRecord[]; count?: number }>(url);
    if (!data || !data.memories) {
      set({ degraded: true, loading: false, error: 'recall fetch failed' });
      return;
    }
    set({ vmRecords: data.memories, loading: false, degraded: false });
  },

  recordExperience: async (content, qualityLevel, tags) => {
    const data = await fetchJson<{ memory_id?: string; id?: string }>(`${COG_API}/record`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ content, quality_level: qualityLevel, tags }),
    });
    if (!data || (!data.memory_id && !data.id)) {
      set({ degraded: true });
      return null;
    }
    const memoryId = data.memory_id || data.id || '';
    // 自动刷新列表 + stats
    await get().fetchRecall();
    await get().fetchStats();
    return memoryId;
  },

  verifyMemory: async (memoryId, success) => {
    const data = await fetchJson<{ memory_id?: string; success?: boolean }>(`${COG_API}/verify`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ memory_id: memoryId, success }),
    });
    if (!data) {
      set({ degraded: true });
      return false;
    }
    // 自动刷新 stats 反映 confidence 变化
    await get().fetchStats();
    // 刷新列表以反映新的 verify_count/confidence
    await get().fetchRecall();
    return true;
  },

  fetchStats: async () => {
    const data = await fetchJson<MemoryStats>(`${COG_API}/stats`);
    if (!data) {
      set({ degraded: true });
      return;
    }
    set({ stats: data, degraded: false });
  },
}));

// ============================================================
// React Hook: 自动加载平台 VM 数据 (页面挂载时调用)
// 复刻 P0 useUserMemoryAutoLoad 模式
// ============================================================
export function useCognitiveAutoLoad() {
  const { fetchStats, fetchRecall } = useMemoryStore();
  return useCallback(() => {
    Promise.all([fetchStats(), fetchRecall('recent', 20, 'C')]);
  }, [fetchStats, fetchRecall]);
}
