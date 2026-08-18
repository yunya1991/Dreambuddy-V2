import { create } from 'zustand';

export interface ChatMessage {
  id: string;
  role: 'system' | 'user' | 'assistant';
  content: string;
  timestamp: number;
  tokens?: number;
  artifacts?: Array<{ type: string; title: string; ref: string }>;
}

export interface ChatSession {
  id: string;
  title: string;
  createdAt: number;
  updatedAt: number;
  messageCount: number;
}

export interface IntentInfo {
  type: string;
  confidence: number;
  method: string;
  entities?: Record<string, unknown>;
}

interface SessionState {
  sessions: ChatSession[];
  activeSessionId: string | null;
  messages: Record<string, ChatMessage[]>;
  isStreaming: boolean;
  streamingContent: string;
  sLayerIntent: string | null;
  currentTaskId: string | null;
  lastIntent: IntentInfo | null;
  lastTaskStatus: string | null;
  lastReportId: string | null;

  createSession: (title?: string) => string;
  setActiveSession: (id: string) => void;
  deleteSession: (id: string) => void;
  addMessage: (sessionId: string, msg: ChatMessage) => void;
  setStreaming: (isStreaming: boolean, content?: string) => void;
  appendStreamingContent: (delta: string) => void;
  finalizeStreaming: (sessionId: string) => void;
  setSLayerIntent: (intent: string) => void;
  setCurrentTaskId: (taskId: string | null) => void;
  setLastIntent: (intent: IntentInfo | null) => void;
  setLastTaskStatus: (status: string | null) => void;
  setLastReportId: (reportId: string | null) => void;
}

export const useSessionStore = create<SessionState>((set, get) => ({
  sessions: [],
  activeSessionId: null,
  messages: {},
  isStreaming: false,
  streamingContent: '',
  sLayerIntent: null,
  currentTaskId: null,
  lastIntent: null,
  lastTaskStatus: null,
  lastReportId: null,

  createSession: (title = '新会话') => {
    const id = `sess_${Date.now()}`;
    const session: ChatSession = {
      id, title, createdAt: Date.now(), updatedAt: Date.now(), messageCount: 0,
    };
    set(s => ({ sessions: [session, ...s.sessions], activeSessionId: id, messages: { ...s.messages, [id]: [] }, isStreaming: false, streamingContent: '' }));
    return id;
  },

  setActiveSession: (id) => set({ activeSessionId: id }),

  deleteSession: (id) => set(s => {
    const { [id]: _, ...rest } = s.messages;
    return { sessions: s.sessions.filter(sess => sess.id !== id), messages: rest, activeSessionId: s.activeSessionId === id ? null : s.activeSessionId };
  }),

  addMessage: (sessionId, msg) => set(s => ({
    messages: { ...s.messages, [sessionId]: [...(s.messages[sessionId] || []), msg] },
    sessions: s.sessions.map(sess => sess.id === sessionId ? { ...sess, updatedAt: Date.now(), messageCount: sess.messageCount + 1 } : sess),
  })),

  setStreaming: (isStreaming, content = '') => set({ isStreaming, streamingContent: content }),
  appendStreamingContent: (delta) => set(s => ({ streamingContent: s.streamingContent + delta })),
  finalizeStreaming: (sessionId) => set(s => {
    const msg: ChatMessage = { id: `msg_${Date.now()}`, role: 'assistant', content: s.streamingContent, timestamp: Date.now() };
    return {
      messages: { ...s.messages, [sessionId]: [...(s.messages[sessionId] || []), msg] },
      isStreaming: false, streamingContent: '',
      sessions: s.sessions.map(sess => sess.id === sessionId ? { ...sess, updatedAt: Date.now(), messageCount: sess.messageCount + 1 } : sess),
    };
  }),
  setSLayerIntent: (intent) => set({ sLayerIntent: intent }),
  setCurrentTaskId: (taskId) => set({ currentTaskId: taskId }),
  setLastIntent: (intent) => set({ lastIntent: intent }),
  setLastTaskStatus: (status) => set({ lastTaskStatus: status }),
  setLastReportId: (reportId) => set({ lastReportId: reportId }),
}));
