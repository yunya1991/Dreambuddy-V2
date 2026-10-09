'use client';

import React, { useCallback, useRef, useEffect, useState } from 'react';
import Link from 'next/link';
import { useSessionStore, useChainStore } from '@/stores';
import type { FinalSynthesisData } from '@/stores/session-store';
import { V3Badge } from '@/components';
import { createSSEConnection, type SSEConnection } from '@/lib/sse-client';
import { createTaskStreamHandlers } from '@/lib/sse-dispatcher';

// 9 个子组件
import { MessageItem } from './MessageItem';
import { ChatInput } from './ChatInput';
import { ThinkingCard } from './ThinkingCard';
import { StreamingIndicator } from './StreamingIndicator';
import { StepConfirmation } from './StepConfirmation';
import { ReportExport } from './ReportExport';
import { EnhancementHints } from './EnhancementHints';
import { InsightCard } from './InsightCard';
import { RecommendationCard } from './RecommendationCard';
import { SynthesisChart } from './SynthesisChart';

/**
 * ChatPanel — 聊天主面板 (DREAM OS 核心交互入口)
 *
 * 对接 /api/task/stream SSE 流式任务执行
 * 布局：
 *   - 顶部：当前会话信息 + 意图识别状态
 *   - 中间：消息列表（自动滚动到底部）+ 思考链 + 流式指示 + 步骤确认
 *   - 底部：快捷命令栏 + 输入框
 *
 * 接入 9 个 chat 子组件，消除孤儿状态。
 */
export function ChatPanel() {
  const {
    activeSessionId, messages, isStreaming, streamingContent,
    sLayerIntent, sessions, lastIntent, lastReportId, lastTaskStatus,
    pendingStepConfirmation, lastSynthesis, lastChartSpecs,
    createSession, setActiveSession, addMessage,
    setStreaming, setSLayerIntent,
    setCurrentTaskId, setLastIntent, setLastTaskStatus, setLastReportId,
    setPendingStepConfirmation, setLastChartSpecs,
  } = useSessionStore();

  const { resetChain } = useChainStore();

  const [inputValue, setInputValue] = useState('');
  const [inputMode, setInputMode] = useState<'chat' | 'command'>('chat');
  const [error, setError] = useState<string | null>(null);

  // 消息列表底部锚点
  const messagesEndRef = useRef<HTMLDivElement>(null);
  const sseConnectionRef = useRef<SSEConnection | null>(null);

  // 当前会话消息
  const currentMessages = activeSessionId ? (messages[activeSessionId] || []) : [];

  // 自动滚动到底部
  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [currentMessages.length, streamingContent]);

  // 如果没有活跃会话，自动创建一个
  useEffect(() => {
    if (!activeSessionId) {
      createSession('新会话');
    }
  }, [activeSessionId, createSession]);

  // 组件卸载时关闭 SSE 连接
  useEffect(() => {
    return () => {
      sseConnectionRef.current?.close();
      const state = useSessionStore.getState();
      if (state.isStreaming) {
        state.setStreaming(false, '');
      }
    };
  }, []);

  // 发送消息到 /api/task/stream
  const sendToTaskStream = useCallback(async (userContent: string, sessionId: string) => {
    setError(null);

    // 重置链路状态
    resetChain();

    // 创建 SSE 事件处理器
    const handlers = createTaskStreamHandlers({
      onDone: (data) => {
        sseConnectionRef.current = null;
      },
      onError: (err) => {
        setError(err.message);
        sseConnectionRef.current = null;
      },
    });

    // 通过 SSE 发送任务
    sseConnectionRef.current = createSSEConnection(
      '/api/task/stream',
      {
        message: userContent,
        thinking_mode: 'deep',
        session_id: sessionId,
        lang: 'zh',
        trading_mode: 'ai_skill',
      },
      handlers,
      {
        onError: (err) => {
          setError(err.message);
          useSessionStore.getState().setStreaming(false, '');
          sseConnectionRef.current = null;
        },
      }
    );
  }, [resetChain]);

  // 发送消息
  const handleSend = useCallback(() => {
    const content = inputValue.trim();
    if (!content || isStreaming) return;

    // 从 store 读取最新的 activeSessionId，避免闭包竞态
    const storeState = useSessionStore.getState();
    let sessionId = storeState.activeSessionId;
    if (!sessionId) {
      sessionId = storeState.createSession('新会话');
    }

    // 添加用户消息
    storeState.addMessage(sessionId, {
      id: `msg-${Date.now()}`,
      role: 'user',
      content,
      timestamp: Date.now(),
    });

    setInputValue('');

    // 设置流式状态
    storeState.setStreaming(true, '');

    // 通过 SSE 发送到后端
    sendToTaskStream(content, sessionId);
  }, [inputValue, isStreaming, sendToTaskStream]);

  // 取消流式请求
  const handleCancel = useCallback(() => {
    sseConnectionRef.current?.close();
    sseConnectionRef.current = null;
    const storeState = useSessionStore.getState();
    if (storeState.isStreaming) {
      const sessionId = storeState.activeSessionId;
      if (sessionId && storeState.streamingContent) {
        storeState.finalizeStreaming(sessionId);
      } else {
        storeState.setStreaming(false, '');
      }
    }
  }, []);

  // StepConfirmation 选择回调 — FAIL-OPEN: 当前仅 dismiss，实际 action 路由由 SSE 层处理
  const handleStepChoose = useCallback((action: 'continue' | 'finalize' | 'skip') => {
    setPendingStepConfirmation(null);
  }, [setPendingStepConfirmation]);

  // 快捷命令
  const quickCommands = [
    { label: '分析BTC行情', desc: '深度分析' },
    { label: '当前交易信号', desc: '信号扫描' },
    { label: '风控检查', desc: '风险评估' },
    { label: 'ETH基本面分析', desc: '基本面' },
  ];

  return (
    <div className="flex flex-col h-full">
      {/* 顶部：会话信息栏 */}
      <div className="shrink-0 px-4 py-2 border-b border-slate-700/20 flex items-center justify-between">
        <div className="flex items-center gap-2">
          {lastIntent ? (
            <>
              <V3Badge variant="sacg-s" dot>
                {lastIntent.type}
              </V3Badge>
              <span className="text-[10px] text-slate-500">
                置信度 {(lastIntent.confidence * 100).toFixed(0)}%
              </span>
            </>
          ) : (
            <V3Badge variant="info">{sLayerIntent || '等待输入'}</V3Badge>
          )}
          {isStreaming && (
            <V3Badge variant="warning" dot pulse>执行中</V3Badge>
          )}
          {lastTaskStatus === 'completed' && !isStreaming && (
            <V3Badge variant="success" dot>已完成</V3Badge>
          )}
          {lastTaskStatus === 'error' && !isStreaming && (
            <V3Badge variant="danger" dot>错误</V3Badge>
          )}
        </div>
        <div className="flex items-center gap-1">
          {/* 会话切换器 */}
          {sessions.length > 1 && (
            <select
              value={activeSessionId || ''}
              onChange={(e) => setActiveSession(e.target.value)}
              className="text-[10px] bg-slate-800/50 border border-slate-700/30 rounded px-1.5 py-0.5 text-slate-300"
            >
              {Array.from(new Map(sessions.map(s => [s.id, s])).values()).map(s => (
                <option key={s.id} value={s.id}>{s.title}</option>
              ))}
            </select>
          )}
        </div>
      </div>

      {/* 错误提示 */}
      {error && (
        <div className="shrink-0 px-4 py-2 bg-red-950/30 border-b border-red-800/30 flex items-center justify-between">
          <span className="text-xs text-red-300">⚠ {error}</span>
          <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300 text-xs">×</button>
        </div>
      )}

      {/* 消息列表 */}
      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {/* 空状态 */}
        {currentMessages.length === 0 && !isStreaming && (
          <div className="flex flex-col items-center justify-center h-full text-slate-500">
            <svg className="w-16 h-16 mb-4 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M8 12h.01M12 12h.01M16 12h.01M21 12c0 4.418-4.03 8-9 8a9.863 9.863 0 01-4.255-.949L3 20l1.395-3.72C3.512 15.042 3 13.574 3 12c0-4.418 4.03-8 9-8s9 3.582 9 8z" />
            </svg>
            <p className="text-sm">DREAM OS 已就绪</p>
            <p className="text-xs text-slate-600 mt-1">输入问题或使用快捷命令开始对话</p>
          </div>
        )}

        {/* 消息渲染 — MessageItem */}
        {currentMessages.map((msg, idx) => {
          const isLast = idx === currentMessages.length - 1;
          const isLastAssistant = isLast && msg.role === 'assistant';
          return (
            <React.Fragment key={msg.id}>
              <MessageItem
                message={msg}
                isLast={isLast}
                streamingContent={isLast && isStreaming ? streamingContent : undefined}
                onSelectClarifyOption={(optionKey, optionLabel) => {
                  // 把用户选项作为新消息发送
                  if (activeSessionId) {
                    addMessage(activeSessionId, {
                      id: `msg_${Date.now()}`,
                      role: 'user',
                      content: optionLabel,
                      timestamp: Date.now(),
                    });
                    // 用 optionLabel 作为新一轮输入触发任务流
                    sendToTaskStream(optionLabel, activeSessionId);
                  }
                }}
              />
              {/* 最后一条 assistant 消息之后：报告链接 + 综合卡片 + 导出按钮 */}
              {isLastAssistant && !isStreaming && (
                <div className="ml-9 mt-2 space-y-3">
                  {lastReportId && (
                    <div>
                      <Link
                        href="/dashboard/reports"
                        className="text-xs text-blue-400 hover:text-blue-300 flex items-center gap-1"
                      >
                        📋 查看完整报告 →
                      </Link>
                    </div>
                  )}
                  {lastChartSpecs && lastChartSpecs.length > 0 && (
                    <div className="grid grid-cols-2 gap-2 p-3 bg-gray-800/40 rounded-lg border border-gray-700/30">
                      {lastChartSpecs.map((chart, ci) => (
                        <SynthesisChart key={ci} chart={chart} />
                      ))}
                    </div>
                  )}
                  <InsightCard
                    insights={lastSynthesis?.insights || []}
                    defaultExpandFirst
                  />
                  <RecommendationCard
                    recommendations={lastSynthesis?.recommendations || []}
                  />
                  <EnhancementHints
                    hints={lastSynthesis?.enhancement_hints || []}
                  />
                  <ReportExport
                    synthesis={(lastSynthesis ?? {}) as FinalSynthesisData}
                  />
                </div>
              )}
            </React.Fragment>
          );
        })}

        {/* ThinkingCard — 流式中显示 S0-S5 / research→execute 思维链 */}
        <ThinkingCard isStreaming={isStreaming} />

        {/* 流式输出 */}
        {isStreaming && streamingContent && (
          <div className="flex justify-start">
            <div className="max-w-[80%] rounded-xl px-4 py-2.5 text-sm leading-relaxed bg-slate-800/60 text-slate-200 border border-slate-700/30">
              <div className="whitespace-pre-wrap">{streamingContent}</div>
            </div>
          </div>
        )}

        {/* 流式输出指示器 — StreamingIndicator */}
        {isStreaming && (
          <div className="flex items-center gap-2 px-2">
            <StreamingIndicator isActive={isStreaming} stepName="DREAM OS 执行中..." />
            <button
              onClick={handleCancel}
              className="text-red-400 hover:text-red-300 text-xs"
            >
              取消
            </button>
          </div>
        )}

        {/* StepConfirmation — 步骤确认对话框（从 useSessionStore.pendingStepConfirmation 读取） */}
        {pendingStepConfirmation && (
          <StepConfirmation
            data={pendingStepConfirmation}
            onChoose={handleStepChoose}
            disabled={isStreaming}
          />
        )}

        {/* 滚动锚点 */}
        <div ref={messagesEndRef} />
      </div>

      {/* 快捷命令栏 */}
      {inputMode === 'command' && (
        <div className="px-4 py-2 border-t border-slate-700/30 flex gap-2 flex-wrap">
          {quickCommands.map((cmd) => (
            <button
              key={cmd.label}
              onClick={() => setInputValue(cmd.label)}
              className="px-2.5 py-1 text-xs rounded-md bg-slate-800/50 text-slate-300 border border-slate-700/30 hover:bg-slate-700/50 transition-colors"
            >
              {cmd.label} <span className="text-slate-500">{cmd.desc}</span>
            </button>
          ))}
        </div>
      )}

      {/* 输入区 — ChatInput */}
      <div className="px-4 py-3 border-t border-slate-700/30">
        <ChatInput
          value={inputValue}
          onChange={setInputValue}
          onSend={handleSend}
          disabled={isStreaming}
          loading={isStreaming}
          mode={inputMode}
          onModeToggle={() => setInputMode(inputMode === 'chat' ? 'command' : 'chat')}
        />
      </div>
    </div>
  );
}

export default ChatPanel;
