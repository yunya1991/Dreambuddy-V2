// ============================================
// Agent 会话 store + localStorage 持久化 + 深链（SPEC-20261111-B §3.7 / T-B7）
// ============================================
// 与交易域 session-store 完全解耦：独立 key、独立类型、独立生命周期。
// 硬约束：最多 50 会话 / 单会话 500 条消息；写入节流 500ms；localStorage 不可用时静默降级。

import { create } from 'zustand';
import type { AgentMessage } from '@/types/agent-message';

export const AGENT_SESSION_STORAGE_KEY = 'dreambuddy.agent.sessions.v1';
export const MAX_SESSIONS = 50;
export const MAX_MESSAGES_PER_SESSION = 500;
export const PERSIST_THROTTLE_MS = 500;

export interface AgentSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messages: AgentMessage[];
}

export interface PersistedAgentSessions {
  sessions: AgentSession[];
  activeSessionId: string | null;
}

interface AgentSessionState {
  sessions: AgentSession[];
  activeSessionId: string | null;
  hydrated: boolean;
  hydrate: () => void;
  createSession: (title?: string) => string;
  renameSession: (id: string, title: string) => void;
  deleteSession: (id: string) => void;
  selectSession: (id: string) => void;
  appendMessage: (sessionId: string, message: AgentMessage) => void;
  setMessages: (sessionId: string, messages: AgentMessage[]) => void;
  clearAll: () => void;
}

/** 会话 id：时间戳 + 随机后缀，避免同毫秒碰撞 */
export function createAgentSessionId(now: number = Date.now()): string {
  return `sess-${now.toString(36)}-${Math.random().toString(36).slice(2, 6)}`;
}

/** 按 updatedAt 倒序保留最近 MAX_SESSIONS 个；每个会话只保留最后 MAX_MESSAGES_PER_SESSION 条 */
export function trimSessions(sessions: AgentSession[]): AgentSession[] {
  const sorted = [...sessions].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, MAX_SESSIONS);
  return sorted.map((session) =>
    session.messages.length > MAX_MESSAGES_PER_SESSION
      ? { ...session, messages: session.messages.slice(-MAX_MESSAGES_PER_SESSION) }
      : session,
  );
}

/** 反序列化持久化数据；非法/损坏一律返回 null（FAIL-OPEN） */
export function parsePersistedSessions(raw: string | null): PersistedAgentSessions | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<PersistedAgentSessions> | null;
    if (!parsed || !Array.isArray(parsed.sessions)) return null;
    const sessions = parsed.sessions.filter(
      (s): s is AgentSession =>
        !!s &&
        typeof s.id === 'string' &&
        typeof s.title === 'string' &&
        Array.isArray(s.messages),
    );
    if (sessions.length === 0) return null;
    const activeSessionId =
      typeof parsed.activeSessionId === 'string' && sessions.some((s) => s.id === parsed.activeSessionId)
        ? parsed.activeSessionId
        : sessions[0].id;
    return { sessions: trimSessions(sessions), activeSessionId };
  } catch {
    return null;
  }
}

/**
 * 深链解析：`?session=<id>` 命中返回该 id，未命中/空值返回 null（调用方回退新建）。
 * 输入为完整 search 字符串（含 "?" 或纯 query 均可）。
 */
export function resolveDeepLinkSessionId(
  search: string | null | undefined,
  sessions: AgentSession[],
): string | null {
  if (!search) return null;
  const params = new URLSearchParams(search.startsWith('?') ? search.slice(1) : search);
  const requested = params.get('session');
  if (!requested) return null;
  return sessions.some((s) => s.id === requested) ? requested : null;
}

function safeStorage(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    return window.localStorage;
  } catch {
    return null;
  }
}

function readPersisted(): PersistedAgentSessions | null {
  const storage = safeStorage();
  if (!storage) return null;
  try {
    return parsePersistedSessions(storage.getItem(AGENT_SESSION_STORAGE_KEY));
  } catch {
    return null;
  }
}

let persistTimer: ReturnType<typeof setTimeout> | null = null;
let pending: PersistedAgentSessions | null = null;

function flushPersist(): void {
  persistTimer = null;
  const snapshot = pending;
  pending = null;
  if (!snapshot) return;
  const storage = safeStorage();
  if (!storage) return;
  try {
    storage.setItem(
      AGENT_SESSION_STORAGE_KEY,
      JSON.stringify({
        sessions: trimSessions(snapshot.sessions),
        activeSessionId: snapshot.activeSessionId,
      }),
    );
  } catch {
    // 配额超限：静默降级为内存态（SPEC-B R-B4）
  }
}

/** 节流写入（500ms 内的多次变更合并为一次） */
export function schedulePersist(state: PersistedAgentSessions, throttleMs = PERSIST_THROTTLE_MS): void {
  pending = state;
  if (persistTimer) return;
  persistTimer = setTimeout(flushPersist, throttleMs);
}

/** 测试用：清空待写快照与定时器 */
export function resetPersistForTest(): void {
  if (persistTimer) clearTimeout(persistTimer);
  persistTimer = null;
  pending = null;
}

export const useAgentSessionStore = create<AgentSessionState>((set, get) => {
  const commit = (sessions: AgentSession[], activeSessionId: string | null) => {
    const trimmed = trimSessions(sessions);
    set({ sessions: trimmed, activeSessionId });
    schedulePersist({ sessions: trimmed, activeSessionId });
  };

  return {
    sessions: [],
    activeSessionId: null,
    hydrated: false,

    hydrate: () => {
      if (get().hydrated) return;
      const persisted = readPersisted();
      if (persisted) {
        set({ sessions: persisted.sessions, activeSessionId: persisted.activeSessionId, hydrated: true });
        return;
      }
      set({ hydrated: true });
    },

    createSession: (title) => {
      const now = Date.now();
      const id = createAgentSessionId(now);
      const session: AgentSession = {
        id,
        title: title || `会话 ${new Date(now).toLocaleString('zh-CN', { hour12: false })}`,
        createdAt: now,
        updatedAt: now,
        messages: [],
      };
      commit([session, ...get().sessions], id);
      return id;
    },

    renameSession: (id, title) => {
      const next = title.trim();
      if (!next) return;
      commit(
        get().sessions.map((s) => (s.id === id ? { ...s, title: next, updatedAt: Date.now() } : s)),
        get().activeSessionId,
      );
    },

    deleteSession: (id) => {
      const remaining = get().sessions.filter((s) => s.id !== id);
      const activeSessionId = get().activeSessionId === id ? remaining[0]?.id ?? null : get().activeSessionId;
      commit(remaining, activeSessionId);
    },

    selectSession: (id) => {
      if (!get().sessions.some((s) => s.id === id)) return;
      commit(get().sessions, id);
    },

    appendMessage: (sessionId, message) => {
      commit(
        get().sessions.map((s) =>
          s.id === sessionId
            ? { ...s, messages: [...s.messages, message], updatedAt: Date.now() }
            : s,
        ),
        get().activeSessionId,
      );
    },

    setMessages: (sessionId, messages) => {
      commit(
        get().sessions.map((s) =>
          s.id === sessionId ? { ...s, messages, updatedAt: Date.now() } : s,
        ),
        get().activeSessionId,
      );
    },

    clearAll: () => {
      commit([], null);
    },
  };
});

export type { AgentSessionState };
