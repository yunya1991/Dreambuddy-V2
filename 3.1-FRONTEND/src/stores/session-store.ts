import { create } from 'zustand';
import type { ChatSession, ChatMessage, IntentRecognitionResult } from '@/types';

interface SessionState {
  // 会话列表
  sessions: ChatSession[];
  activeSessionId: string | null;
  // 当前会话消息
  messages: ChatMessage[];
  // 流式状态
  isStreaming: boolean;
  currentStreamContent: string;
  // 输入
  inputValue: string;
  inputMode: 'chat' | 'command';
  // S层意图识别
  lastIntent: IntentRecognitionResult | null;
  // 错误
  error: string | null;

  // Actions
  setSessions: (sessions: ChatSession[]) => void;
  addSession: (session: ChatSession) => void;
  switchSession: (id: string) => void;
  removeSession: (id: string) => void;
  setMessages: (messages: ChatMessage[]) => void;
  addMessage: (message: ChatMessage) => void;
  updateLastAssistantMessage: (content: string) => void;
  setStreaming: (streaming: boolean) => void;
  appendStreamDelta: (delta: string) => void;
  setInputValue: (value: string) => void;
  setInputMode: (mode: 'chat' | 'command') => void;
  setLastIntent: (intent: IntentRecognitionResult | null) => void;
  setError: (error: string | null) => void;
  clearCurrentSession: () => void;
}

export const useSessionStore = create<SessionState>((set) => ({
  sessions: [],
  activeSessionId: null,
  messages: [],
  isStreaming: false,
  currentStreamContent: '',
  inputValue: '',
  inputMode: 'chat',
  lastIntent: null,
  error: null,

  setSessions: (sessions) => set({ sessions }),
  addSession: (session) => set((s) => ({
    sessions: [session, ...s.sessions],
    activeSessionId: session.id,
    messages: session.messages || [],
  })),
  switchSession: (id) => set({ activeSessionId: id }),
  removeSession: (id) => set((s) => ({
    sessions: s.sessions.filter(s => s.id !== id),
    activeSessionId: s.activeSessionId === id ? null : s.activeSessionId,
  })),
  setMessages: (messages) => set({ messages }),
  addMessage: (message) => set((s) => ({ messages: [...s.messages, message] })),
  updateLastAssistantMessage: (content) => set((s) => {
    const msgs = [...s.messages];
    for (let i = msgs.length - 1; i >= 0; i--) {
      if (msgs[i].role === 'assistant') {
        msgs[i] = { ...msgs[i], content: msgs[i].content + content };
        break;
      }
    }
    return { messages: msgs };
  }),
  setStreaming: (streaming) => set({ isStreaming: streaming, currentStreamContent: streaming ? '' : '' }),
  appendStreamDelta: (delta) => set((s) => ({
    currentStreamContent: s.currentStreamContent + delta,
  })),
  setInputValue: (value) => set({ inputValue: value }),
  setInputMode: (mode) => set({ inputMode: mode }),
  setLastIntent: (intent) => set({ lastIntent: intent }),
  setError: (error) => set({ error }),
  clearCurrentSession: () => set({ messages: [], isStreaming: false, currentStreamContent: '', lastIntent: null, error: null }),
}));
