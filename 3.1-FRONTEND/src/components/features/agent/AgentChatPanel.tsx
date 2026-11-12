'use client';

// ============================================
// AgentChatPanel — 协议层对话面板（SPEC-20261111-B §3.6 ~ §3.9）
// ============================================
// T-B6：/api/agent/chat 的 UIMessage.parts 经 ui-message-to-parts 映射后由 PartRenderer 渲染。
// T-B7：会话消息由 agent-session-store 持久化，切换会话重新挂载 useChat。
// T-B8：>50 条消息启用 content-visibility 虚拟化。
// T-B9：ChatInput 增强（停止/重生成/草稿/历史/@ 候选/附件文件名）。

import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useChat } from '@ai-sdk/react';
import { DefaultChatTransport } from 'ai';
import type { UIMessage } from 'ai';
import { PartList } from './PartRenderer';
import { ChatInput, type ChatInputSuggestion } from '@/components/features/chat/ChatInput';
import { uiMessageToParts, type LooseUIMessage } from '@/lib/adapters/ui-message-to-parts';
import { shouldVirtualize, VIRTUALIZED_ROW_STYLE } from '@/lib/virtualization';
import { useAgentSessionStore, type AgentSession } from '@/stores/agent-session-store';
import type { AgentMessage } from '@/types/agent-message';

/** 静态技能候选（无 skills API 时的降级清单，SPEC-B §3.9） */
const STATIC_SUGGESTIONS: ChatInputSuggestion[] = [
  { label: '行情分析', value: '@行情分析', hint: '技能' },
  { label: '风控检查', value: '@风控检查', hint: '技能' },
  { label: '基本面', value: '@基本面', hint: '技能' },
  { label: '报告生成', value: '@报告生成', hint: '技能' },
];

function toUiMessages(session: AgentSession | undefined): UIMessage[] {
  if (!session) return [];
  return session.messages.map(
    (m) => ({ id: m.id, role: m.role, parts: m.parts }) as unknown as UIMessage,
  );
}

function toAgentMessages(messages: UIMessage[], isError: boolean): AgentMessage[] {
  const now = Date.now();
  return messages.map((m) => ({
    id: m.id,
    role: m.role,
    parts: uiMessageToParts(m as unknown as LooseUIMessage),
    createdAt: now,
    status: isError ? 'error' : 'done',
  }));
}

export interface AgentChatPanelProps {
  sessionId: string;
  /** 会话标题（用于头部展示） */
  title?: string;
}

function AgentChatPanelInner({ sessionId, title }: AgentChatPanelProps) {
  const setMessages = useAgentSessionStore((s) => s.setMessages);
  const storedSession = useAgentSessionStore((s) => s.sessions.find((item) => item.id === sessionId));
  const initialMessages = useMemo(() => toUiMessages(storedSession), [sessionId]); // eslint-disable-line react-hooks/exhaustive-deps
  const [input, setInput] = useState('');
  const endRef = useRef<HTMLDivElement>(null);

  const transport = useMemo(() => new DefaultChatTransport({ api: '/api/agent/chat' }), []);
  const { messages, sendMessage, status, error, stop, regenerate } = useChat({
    id: sessionId,
    messages: initialMessages,
    transport,
    onFinish: ({ messages: finalMessages, isError }) => {
      setMessages(sessionId, toAgentMessages(finalMessages, isError));
    },
  });

  const busy = status === 'submitted' || status === 'streaming';
  const virtualize = shouldVirtualize(messages.length);

  // 断网续流：流被网络中断时记下「待恢复」，联网恢复后自动重试该轮一次
  const [online, setOnline] = useState(true);
  const interruptedRef = useRef(false);
  const retriedRef = useRef(false);

  useEffect(() => {
    if (status === 'submitted' || status === 'streaming') {
      // 新一轮请求已发出且仍在进行：清除中断标记，允许下次中断再续
      interruptedRef.current = false;
      retriedRef.current = false;
    } else if (status === 'error') {
      interruptedRef.current = true;
    }
  }, [status]);

  useEffect(() => {
    setOnline(navigator.onLine);
    const handleOffline = () => setOnline(false);
    const handleOnline = () => {
      setOnline(true);
      // 仅对「因断网中断的一轮」自动续一次，避免服务端持续报错时无限重试
      // messages 为空时 regenerate 会抛 "message not found"，故先判空
      if (messages.length > 0 && interruptedRef.current && !retriedRef.current) {
        retriedRef.current = true;
        interruptedRef.current = false;
        void regenerate().catch(() => {
          // 续流失败保持原样，由用户手动「重生成」
        });
      }
    };
    window.addEventListener('offline', handleOffline);
    window.addEventListener('online', handleOnline);
    return () => {
      window.removeEventListener('offline', handleOffline);
      window.removeEventListener('online', handleOnline);
    };
  }, [regenerate, messages.length]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages.length, status]);

  const handleSend = (attachments?: string[]) => {
    const text = input.trim();
    if (!text || busy) return;
    const composed =
      attachments && attachments.length > 0
        ? `${text}\n\n[附件] ${attachments.join(', ')}`
        : text;
    setInput('');
    interruptedRef.current = false;
    retriedRef.current = false;
    void sendMessage({ text: composed });
  };

  return (
    <div className="flex h-full flex-col">
      <header className="shrink-0 border-b border-slate-800 px-4 py-2 text-xs text-slate-400">
        {title || '新会话'}
        <span className="ml-2 text-[10px] text-slate-600">协议层 · 只读</span>
      </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.length === 0 && !busy && (
          <div className="flex h-full flex-col items-center justify-center text-slate-500">
            <p className="text-sm">Agent 工作台已就绪</p>
            <p className="mt-1 text-xs text-slate-600">输入问题，或输入 @ 选择技能</p>
          </div>
        )}

        {messages.map((message) => {
          const parts = uiMessageToParts(message as unknown as LooseUIMessage);
          return (
            <div
              key={message.id}
              data-testid="agent-message-row"
              style={virtualize ? VIRTUALIZED_ROW_STYLE : undefined}
              className={message.role === 'user' ? 'flex justify-end' : 'flex justify-start'}
            >
              <div className="max-w-[85%]">
                {message.role === 'user' ? (
                  <div className="rounded-xl border border-slate-700/40 bg-slate-800/60 px-4 py-2.5 text-sm text-slate-200 whitespace-pre-wrap">
                    {parts
                      .filter((p) => p.type === 'text')
                      .map((p) => (p.type === 'text' ? p.text : ''))
                      .join('\n')}
                  </div>
                ) : (
                  <PartList parts={parts} />
                )}
              </div>
            </div>
          );
        })}

        {busy && (
          <div className="flex items-center gap-2 px-2 text-xs text-slate-500">
            <span className="inline-block h-1.5 w-1.5 animate-pulse rounded-full bg-indigo-400" />
            {status === 'submitted' ? '正在提交…' : '正在生成…'}
          </div>
        )}

        {!online && (
          <div className="rounded-lg border border-amber-800/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            网络已断开{busy ? '，正在等待重连…' : '，恢复联网后将自动重试'}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
            请求失败：{error.message}
          </div>
        )}

        <div ref={endRef} />
      </div>

      <div className="shrink-0 border-t border-slate-800 px-4 py-3">
        <ChatInput
          value={input}
          onChange={setInput}
          onSend={handleSend}
          disabled={busy}
          loading={busy}
          draftKey={`agent:${sessionId}`}
          historyKey={`agent:${sessionId}`}
          suggestions={STATIC_SUGGESTIONS}
          onAttachFiles={() => {
            /* 仅文件名引用，发送时随消息携带 */
          }}
          onStop={stop}
          onRegenerate={() => void regenerate()}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行，@ 选择技能"
        />
      </div>
    </div>
  );
}

/** 外层按 sessionId 重挂载：useChat 的初始 messages 只在挂载时生效 */
export function AgentChatPanel({ sessionId, title }: AgentChatPanelProps) {
  return <AgentChatPanelInner key={sessionId} sessionId={sessionId} title={title} />;
}

export default AgentChatPanel;
