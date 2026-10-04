import { create } from 'zustand';
import { useCallback } from 'react';
import type { UserPreference, UserNote, UserMemoryHealth } from '@/lib/user-memory-client';

// ============================================================
// 用户层记忆 store（与平台 VM 物理隔离）
// 复刻 P0 memory-store.ts 模式: Zustand + fetch + FAIL-OPEN degraded
// 硬约束 (VM-1786242777697): 用户层只存用户权威内容，禁止写 VM
// ============================================================

interface UserMemoryState {
  preferences: UserPreference[];
  notes: UserNote[];
  health: UserMemoryHealth | null;
  degraded: boolean;
  loading: boolean;
  error: string | null;

  fetchPreferences: (userId?: string) => Promise<void>;
  setPreference: (key: string, value: string, userId?: string) => Promise<boolean>;
  fetchNotes: (userId?: string) => Promise<void>;
  createNote: (title: string, content: string, tags: string, userId?: string) => Promise<string | null>;
  deleteNote: (id: string) => Promise<boolean>;
  markPromoted: (id: string, promotedTo: string) => Promise<boolean>;
  // P3 Step 5: 用户笔记沉淀审批流 (POST /api/user-memory/notes/[id]/promote)
  promoteNote: (id: string, qualityLevel: string, tags: string) => Promise<string | null>;
  fetchHealth: () => Promise<void>;
}

const API_BASE = '/api/user-memory';

async function fetchJson<T>(url: string, options?: RequestInit): Promise<T | null> {
  try {
    const res = await fetch(url, options);
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.error || `HTTP ${res.status}`);
    }
    return await res.json();
  } catch {
    return null;
  }
}

export const useUserMemoryStore = create<UserMemoryState>((set, get) => ({
  preferences: [],
  notes: [],
  health: null,
  degraded: false,
  loading: false,
  error: null,

  fetchPreferences: async (userId = 'default') => {
    set({ loading: true, error: null });
    const data = await fetchJson<{ preferences: UserPreference[]; count: number }>(
      `${API_BASE}/preferences?user_id=${encodeURIComponent(userId)}`
    );
    if (!data || !data.preferences) {
      set({ degraded: true, loading: false, error: 'preferences fetch failed' });
      return;
    }
    set({ preferences: data.preferences, loading: false, degraded: false });
  },

  setPreference: async (key, value, userId = 'default') => {
    const data = await fetchJson<{ user_id: string; key: string; value: string; updated_at: number }>(
      `${API_BASE}/preferences`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, key, value }),
      }
    );
    if (!data || !data.key) {
      set({ degraded: true });
      return false;
    }
    // 写入后刷新列表
    await get().fetchPreferences(userId);
    return true;
  },

  fetchNotes: async (userId = 'default') => {
    set({ loading: true, error: null });
    const data = await fetchJson<{ notes: UserNote[]; count: number }>(
      `${API_BASE}/notes?user_id=${encodeURIComponent(userId)}`
    );
    if (!data || !data.notes) {
      set({ degraded: true, loading: false, error: 'notes fetch failed' });
      return;
    }
    set({ notes: data.notes, loading: false, degraded: false });
  },

  createNote: async (title, content, tags, userId = 'default') => {
    const data = await fetchJson<{ id: string; created_at: number }>(
      `${API_BASE}/notes`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ user_id: userId, title, content, tags }),
      }
    );
    if (!data || !data.id) {
      set({ degraded: true });
      return null;
    }
    await get().fetchNotes(userId);
    return data.id;
  },

  deleteNote: async (id) => {
    const data = await fetchJson<{ id: string; deleted: number }>(
      `${API_BASE}/notes/${encodeURIComponent(id)}`,
      { method: 'DELETE' }
    );
    if (!data || data.deleted === 0) {
      set({ degraded: true });
      return false;
    }
    // 从本地 state 移除
    set(s => ({ notes: s.notes.filter(n => n.id !== id) }));
    return true;
  },

  markPromoted: async (id, promotedTo) => {
    const data = await fetchJson<{ id: string; promoted_to: string; updated: number }>(
      `${API_BASE}/notes/${encodeURIComponent(id)}`,
      {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ promoted_to: promotedTo }),
      }
    );
    if (!data || data.updated === 0) {
      set({ degraded: true });
      return false;
    }
    // 更新本地 state（标记 promoted_to）
    set(s => ({
      notes: s.notes.map(n => n.id === id ? { ...n, promoted_to: promotedTo } : n),
    }));
    return true;
  },

  // P3 Step 5: 用户笔记沉淀审批流
  // POST /api/user-memory/notes/[id]/promote (后端组合 cognitive record + mark_promoted)
  // 成功后仅同步本地 state (promote 端点已 mark, 不重复调 markPromoted)
  promoteNote: async (id, qualityLevel, tags) => {
    const data = await fetchJson<{ note_id?: string; promoted_to?: string }>(
      `${API_BASE}/notes/${encodeURIComponent(id)}/promote`,
      {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ quality_level: qualityLevel, tags }),
      }
    );
    if (!data || !data.promoted_to) {
      set({ degraded: true });
      return null;
    }
    // 本地同步 (promote 端点已调 mark_promoted, 这里仅更新前端 state)
    const promotedToVm = data.promoted_to ?? null;
    set(s => ({
      notes: s.notes.map(n => n.id === id ? { ...n, promoted_to: promotedToVm } : n),
    }));
    return data.promoted_to;
  },

  fetchHealth: async () => {
    const data = await fetchJson<UserMemoryHealth>(`${API_BASE}/health`);
    if (!data) {
      set(s => ({ degraded: true, health: s.health }));
      return;
    }
    set({ health: data, degraded: false });
  },
}));

// ============================================================
// React Hook: 自动加载用户层数据（页面挂载时调用）
// ============================================================
export function useUserMemoryAutoLoad() {
  const { fetchPreferences, fetchNotes, fetchHealth } = useUserMemoryStore();
  return useCallback(() => {
    Promise.all([fetchPreferences(), fetchHealth()]).then(() => fetchNotes());
  }, [fetchPreferences, fetchNotes, fetchHealth]);
}
