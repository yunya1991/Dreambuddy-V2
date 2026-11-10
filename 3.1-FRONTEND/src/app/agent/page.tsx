'use client';

// ============================================
// 52-LobeHub 协议集成 Phase 1 — 内置协议层最小聊天页
// useChat → /api/agent/chat（模型路由 + cognition MCP 工具）
// ============================================

import { useState } from 'react';
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import { V3Button } from '@/components';
import { V3StatusDot } from '@/components';

export default function AgentPage() {
  const [input, setInput] = useState('');
  const { messages, sendMessage, status, error } = useChat({
    transport: new DefaultChatTransport({ api: '/api/agent/chat' }),
  });

  const busy = status === 'submitted' || status === 'streaming';

  const onSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const text = input.trim();
    if (!text || busy) return;
    sendMessage({ text });
    setInput('');
  };

  return (
    <div className="flex h-screen flex-col bg-[var(--color-bg-primary)]">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-indigo-400">DreamBuddy Agent 协议层</span>
          <V3StatusDot
            status={busy ? 'warning' : 'success'}
            size="sm"
            label={busy ? '生成中' : '就绪'}
          />
        </div>
        <span className="text-xs text-slate-500">52-LobeHub Phase 1 · MCP 只读</span>
      </header>

      <main className="flex-1 overflow-y-auto px-6 py-4 space-y-4">
        {messages.length === 0 && (
          <p className="text-sm text-slate-500">
            内置 LLM 协议层（模型路由 + cognition MCP 工具）。未配置模型时返回降级信封。
          </p>
        )}
        {messages.map((m) => (
          <div key={m.id} className="flex flex-col gap-1">
            <span className="text-xs text-slate-500">
              {m.role === 'user' ? '你' : 'Agent'}
            </span>
            <div className="rounded-lg border border-slate-800 bg-slate-900/40 px-3 py-2 text-sm text-slate-200 whitespace-pre-wrap">
              {m.parts.map((part, i) => {
                if (part.type === 'text') return <span key={i}>{part.text}</span>;
                if (part.type === 'tool-invocation' || part.type.startsWith('tool-')) {
                  return (
                    <span key={i} className="block text-xs text-indigo-300/80">
                      [MCP 工具调用] {part.type}
                    </span>
                  );
                }
                return null;
              })}
            </div>
          </div>
        ))}
        {error && (
          <p className="text-xs text-red-400">请求失败：{error.message}（已降级，不影响主链路）</p>
        )}
      </main>

      <form onSubmit={onSubmit} className="border-t border-slate-800 px-6 py-3 flex gap-2">
        <input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder="输入消息，例如：检索一下 LobeHub 协议集成的记忆"
          className="flex-1 rounded-lg border border-slate-700 bg-slate-900 px-3 py-2 text-sm text-slate-200 placeholder-slate-500 focus:outline-none focus:border-indigo-500"
        />
        <V3Button type="submit" variant="primary" size="md" disabled={busy || !input.trim()}>
          发送
        </V3Button>
      </form>
    </div>
  );
}
