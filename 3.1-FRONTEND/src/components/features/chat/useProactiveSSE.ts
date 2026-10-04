'use client';

import { useEffect, useRef } from 'react';
import { useSessionStore } from '@/stores';

// 主动推送的 phase 集合
const PROACTIVE_PHASES = new Set([
  'trade_pending',
  'wb_completed',
  'artifact_synced',
  'feed_ready',
]);

const PHASE_TITLES: Record<string, string> = {
  trade_pending: '交易待确认',
  wb_completed: '后台任务完成',
  artifact_synced: '产物已同步',
  feed_ready: '情报就绪',
};

/**
 * useProactiveSSE — 监听 /api/monitor/stream 的主动推送事件
 *
 * 连接 EventSource，过滤 proactive phase 事件，
 * 将关键事件注入 chat 会话作为 system 消息。
 */
export function useProactiveSSE() {
  const seenIds = useRef<Set<string>>(new Set());
  const addMessage = useSessionStore(s => s.addMessage);
  const activeSessionId = useSessionStore(s => s.activeSessionId);

  useEffect(() => {
    if (!activeSessionId) return;

    let es: EventSource | null = null;

    try {
      es = new EventSource('/api/monitor/stream');
    } catch {
      return;
    }

    const handleMessage = (e: MessageEvent) => {
      try {
        const event = JSON.parse(e.data);
        if (event.type === 'connected' || event.type === 'system') return;

        // 只处理 proactive phase 事件
        if (!PROACTIVE_PHASES.has(event.phase)) return;

        // 去重
        if (event.id && seenIds.current.has(event.id)) return;
        if (event.id) {
          seenIds.current.add(event.id);
          if (seenIds.current.size > 200) {
            const arr = Array.from(seenIds.current);
            seenIds.current = new Set(arr.slice(-100));
          }
        }

        // 注入 system 消息到当前会话
        const title = PHASE_TITLES[event.phase] || event.phase;
        const desc = event.message_preview || '';
        const content = `🔔 ${title}${desc ? `: ${desc}` : ''}`;

        const sessionId = useSessionStore.getState().activeSessionId;
        if (sessionId) {
          useSessionStore.getState().addMessage(sessionId, {
            id: `sys-${event.id || Date.now()}`,
            role: 'system',
            content,
            timestamp: Date.now(),
          });
        }
      } catch {
        // ignore parse errors
      }
    };

    es.onmessage = handleMessage;

    return () => {
      es?.close();
    };
  }, [activeSessionId, addMessage]);
}
