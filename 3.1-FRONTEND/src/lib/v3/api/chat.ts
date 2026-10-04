// ============================================
// Chat 域客户端 — 聊天/对话 API
// ============================================

import api from '../../api-client';

export interface ChatMessage {
  id: string;
  role: 'user' | 'assistant' | 'system';
  content: string;
  timestamp?: string;
  charts?: unknown[];
  metadata?: Record<string, unknown>;
}

export interface ChatRequest {
  message: string;
  context?: Record<string, unknown>;
  intent_hint?: Record<string, unknown>;
}

export const chatApi = {
  /** 发送聊天消息（非流式） */
  send: (body: ChatRequest) =>
    api.post<ChatMessage>('/api/v1/chat', body),

  /** 获取对话历史 */
  getHistory: (sessionId: string) =>
    api.get<ChatMessage[]>(`/api/chat/history/${sessionId}`),

  /** 发送聊天消息（流式，返回 SSE URL） */
  streamUrl: '/api/task/stream',
};
