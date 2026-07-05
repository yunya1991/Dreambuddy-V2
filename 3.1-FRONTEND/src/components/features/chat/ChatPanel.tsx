'use client';

import React, { useCallback, useRef, useEffect } from 'react';
import { useSessionStore } from '@/stores';
import { useSSE } from '@/lib/use-sse';
import type { SSEProgressEvent, SSEDataCardEvent } from '@/lib/sse-client';
import { V3Button } from '@/components/V3Button';
import { V3Badge } from '@/components/V3Badge';
import { V3Spinner } from '@/components/V3Spinner';
import { IconSend, IconPlus } from '@/components/V3InlineSVG';

/**
 * ChatPanel — 聊天主面板
 *
 * 整合消息列表、流式输出、SSE 事件处理。
 * 布局：
 *   - 顶部：当前会话信息 + 链追踪 mini badge
 *   - 中间：消息列表（自动滚动到底部）
 *   - 底部：输入框 + 快捷命令按钮
 */
export function ChatPanel() {
  const {
    messages, isStreaming, currentStreamContent,
    inputValue, setInputValue, inputMode, setInputMode,
    addMessage, appendStreamDelta, setStreaming, setError, updateLastAssistantMessage,
    lastIntent,
  } = useSessionStore();

  // 消息列表底部锚点 & textarea 引用
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // 自动滚动到底部（新消息或流式内容更新时触发）
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [messages, currentStreamContent]);

  // SSE 事件处理回调
  const handlers = {
    /** 新链开始 — 添加占位 assistant 消息 */
    started: () => {
      addMessage({
        id: `msg-${Date.now()}`,
        role: 'assistant',
        content: '',
        timestamp: Date.now(),
      });
    },
    /** 文本增量 — 累积到流式缓冲区 */
    text_delta: (event: { delta: string }) => {
      appendStreamDelta(event.delta);
    },
    /** 步骤进度（可扩展为更新 ChainTracker） */
    progress: (_event: SSEProgressEvent) => {
      // TODO: 步骤进度更新
    },
    /** 数据卡片（可扩展为渲染 DataCard 组件） */
    data_card: (_event: SSEDataCardEvent) => {
      // TODO: 数据卡片渲染
    },
    /** 链完成 */
    done: () => {
      setStreaming(false);
    },
    /** 错误处理 */
    error: (event: { message: string }) => {
      setError(event.message);
      setStreaming(false);
    },
  };

  const { send } = useSSE({
    url: '/api/chat',
    handlers,
  });

  // 发送消息
  const handleSend = useCallback(() => {
    const content = inputValue.trim();
    if (!content || isStreaming) return;

    // 添加用户消息
    addMessage({
      id: `msg-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    });

    setInputValue('');
    setStreaming(true);

    // 发起 SSE 请求
    send({ message: content, sessionId: useSessionStore.getState().activeSessionId });
  }, [inputValue, isStreaming, addMessage, setInputValue, setStreaming, send]);

  // 键盘快捷键：Enter 发送，Shift+Enter 换行
  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  // 快捷命令列表
  const quickCommands = [
    { label: '/analyze', desc: '深度分析' },
    { label: '/signal', desc: '交易信号' },
    { label: '/risk', desc: '风控检查' },
    { label: '/status', desc: '系统状态' },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* ===== 顶部：会话信息栏 ===== */}
      <div className="shrink-0 px-4 py-2 border-b border-gray-700/20 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <V3Badge variant="info">{lastIntent || '等待输入'}</V3Badge>
        </div>
      </div>

      {/* ===== 消息列表 ===== */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* 空状态 */}
        {messages.length === 0 && (
          <div className="flex flex-col items-center justify-center h-full text-gray-500">
            <svg className="w-16 h-16 mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p className="text-sm">开始一段新对话</p>
            <p className="text-xs text-gray-600 mt-1">输入问题或使用快捷命令</p>
          </div>
        )}

        {/* 消息渲染 */}
        {messages.map((msg) => (
          <div key={msg.id} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div className={`
              max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed
              ${msg.role === 'user'
                ? 'bg-blue-600/20 text-blue-100 border border-blue-500/20'
                : 'bg-gray-800/60 text-gray-200 border border-gray-700/30'}
            `}>
              {msg.content || (msg.role === 'assistant' && isStreaming ? currentStreamContent : '')}
            </div>
          </div>
        ))}

        {/* 流式输出指示器 */}
        {isStreaming && (
          <div className="flex items-center gap-2 text-xs text-gray-400 px-2">
            <V3Spinner size="sm" />
            <span>思考中...</span>
          </div>
        )}

        {/* 滚动锚点 */}
        <div ref={messagesEndRef} />
      </div>

      {/* ===== 快捷命令栏（命令模式下显示） ===== */}
      {inputMode === 'command' && (
        <div className="px-4 py-2 border-t border-gray-700/30 flex gap-2 flex-wrap">
          {quickCommands.map((cmd) => (
            <button
              key={cmd.label}
              onClick={() => setInputValue(cmd.label)}
              className="px-2.5 py-1 text-xs rounded-md bg-gray-800/50 text-gray-300 border border-gray-700/30 hover:bg-gray-700/50 transition-colors"
            >
              {cmd.label} <span className="text-gray-500">{cmd.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* ===== 输入区 ===== */}
      <div className="px-4 py-3 border-t border-gray-700/30">
        <div className="flex items-end gap-2">
          {/* 模式切换按钮 */}
          <button
            onClick={() => setInputMode(inputMode === 'chat' ? 'command' : 'chat')}
            className="shrink-0 p-2 text-gray-400 hover:text-gray-200 transition-colors"
            title="切换输入模式"
          >
            <IconPlus className="w-5 h-5" />
          </button>

          {/* 输入框 */}
          <div className="flex-1 relative">
            <textarea
              ref={textareaRef}
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder={inputMode === 'chat' ? '输入你的问题...' : '输入命令...'}
              rows={1}
              className="w-full resize-none bg-gray-800/50 border border-gray-700/30 rounded-xl px-4 py-2.5 text-sm text-gray-100 placeholder-gray-500 focus:outline-none focus:border-blue-500/40 transition-colors"
              style={{ minHeight: '40px', maxHeight: '120px' }}
            />
          </div>

          {/* 发送按钮 */}
          <V3Button
            variant="primary"
            size="md"
            onClick={handleSend}
            disabled={!inputValue.trim() || isStreaming}
            loading={isStreaming}
            icon={<IconSend className="w-4 h-4" />}
          >
            发送
          </V3Button>
        </div>
      </div>
    </div>
  );
}

export default ChatPanel;
