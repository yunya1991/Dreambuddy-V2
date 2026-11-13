'use client';

import { useEffect, useState } from 'react';
import { AgentChatPanel } from '@/components/features/agent/AgentChatPanel';
import { ChatPanel } from '@/components/features/chat/ChatPanel';
import { V3StatusDot } from '@/components';
import {
  resolveDeepLinkSessionId,
  useAgentSessionStore,
} from '@/stores/agent-session-store';

// Agent 工作台：壳内页面（SPEC-20261111-A T-A1 / SPEC-B T-B6、T-B7）。
// SPEC-52 F1：全站唯一聊天入口。工作台内提供两种对话模式，二者共享同一路由：
//   - agent：协议层对话（/api/agent/chat，UIMessage.parts + 会话持久化）
//   - task ：交易任务对话（/api/task/stream + 择优脑暴开关，原 ChatPanel 能力，仅入口迁移）
// T-B7：会话由 agent-session-store 持久化，支持 ?session=<id> 深链。
type WorkbenchMode = 'agent' | 'task';

const MODE_LABELS: Record<WorkbenchMode, string> = {
  agent: '协议层对话',
  task: '交易任务',
};

export default function DashboardAgentPage() {
  const [mode, setMode] = useState<WorkbenchMode>('agent');

  const sessions = useAgentSessionStore((s) => s.sessions);
  const activeSessionId = useAgentSessionStore((s) => s.activeSessionId);
  const hydrated = useAgentSessionStore((s) => s.hydrated);
  const hydrate = useAgentSessionStore((s) => s.hydrate);
  const createSession = useAgentSessionStore((s) => s.createSession);
  const selectSession = useAgentSessionStore((s) => s.selectSession);
  const renameSession = useAgentSessionStore((s) => s.renameSession);
  const deleteSession = useAgentSessionStore((s) => s.deleteSession);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // 深链：?mode=task 直达交易任务模式
  useEffect(() => {
    if (typeof window === 'undefined') return;
    const requestedMode = new URLSearchParams(window.location.search).get('mode');
    if (requestedMode === 'task') setMode('task');
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const requested = resolveDeepLinkSessionId(window.location.search, sessions);
    if (requested) {
      if (requested !== activeSessionId) selectSession(requested);
      return;
    }
    if (!activeSessionId) createSession('新会话');
  }, [hydrated, sessions, activeSessionId, selectSession, createSession]);

  const switchMode = (next: WorkbenchMode) => {
    setMode(next);
    if (typeof window === 'undefined') return;
    const url = new URL(window.location.href);
    if (next === 'task') url.searchParams.set('mode', 'task');
    else url.searchParams.delete('mode');
    window.history.replaceState(null, '', `${url.pathname}${url.search}`);
  };

  const handleSelect = (id: string) => {
    selectSession(id);
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `?session=${encodeURIComponent(id)}`);
    }
  };

  const handleCreate = () => {
    const id = createSession();
    if (typeof window !== 'undefined') {
      window.history.replaceState(null, '', `?session=${encodeURIComponent(id)}`);
    }
  };

  const handleRename = (id: string, current: string) => {
    if (typeof window === 'undefined') return;
    const next = window.prompt('重命名会话', current);
    if (next && next.trim()) renameSession(id, next);
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId);

  return (
    <div className="flex h-full flex-col bg-[var(--color-bg-primary)]">
      <header className="flex items-center justify-between border-b border-slate-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-indigo-400">Agent 工作台</span>
          <V3StatusDot status="success" size="sm" label="在线" />
        </div>
        <div className="flex items-center gap-1 rounded-lg border border-slate-800 bg-slate-900/60 p-0.5">
          {(Object.keys(MODE_LABELS) as WorkbenchMode[]).map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => switchMode(item)}
              aria-pressed={mode === item}
              className={`rounded-md px-3 py-1 text-xs transition-colors ${
                mode === item
                  ? 'bg-indigo-600/25 text-indigo-200'
                  : 'text-slate-400 hover:bg-slate-800/60 hover:text-slate-300'
              }`}
            >
              {MODE_LABELS[item]}
            </button>
          ))}
        </div>
      </header>

      {mode === 'agent' ? (
        <main className="flex flex-1 overflow-hidden">
          <aside className="hidden w-56 shrink-0 flex-col border-r border-slate-800 md:flex">
            <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
              <span className="text-[11px] uppercase tracking-wider text-slate-500">会话</span>
              <button
                onClick={handleCreate}
                className="rounded px-1.5 py-0.5 text-xs text-indigo-300 hover:bg-slate-800"
                aria-label="新建会话"
              >
                ＋
              </button>
            </div>
            <div className="flex-1 overflow-y-auto p-2 space-y-1">
              {sessions.length === 0 && (
                <p className="px-2 py-4 text-[11px] text-slate-600">暂无会话</p>
              )}
              {sessions.map((session) => (
                <div
                  key={session.id}
                  className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs ${
                    session.id === activeSessionId
                      ? 'bg-indigo-600/20 text-indigo-200'
                      : 'text-slate-400 hover:bg-slate-800/60'
                  }`}
                >
                  <button
                    onClick={() => handleSelect(session.id)}
                    className="min-w-0 flex-1 truncate text-left"
                    title={session.title}
                  >
                    {session.title}
                  </button>
                  <button
                    onClick={() => handleRename(session.id, session.title)}
                    className="hidden text-[10px] text-slate-500 hover:text-slate-300 group-hover:inline"
                    aria-label={`重命名 ${session.title}`}
                  >
                    改
                  </button>
                  <button
                    onClick={() => deleteSession(session.id)}
                    className="hidden text-[10px] text-slate-500 hover:text-red-400 group-hover:inline"
                    aria-label={`删除 ${session.title}`}
                  >
                    ×
                  </button>
                </div>
              ))}
            </div>
          </aside>
          <div className="min-w-0 flex-1 overflow-hidden">
            {activeSessionId ? (
              <AgentChatPanel sessionId={activeSessionId} title={activeSession?.title} />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-slate-600">
                正在准备会话…
              </div>
            )}
          </div>
        </main>
      ) : (
        <main className="min-w-0 flex-1 overflow-hidden">
          {/* 交易任务对话：原 ChatPanel 原形态迁入（含择优脑暴开关，API 不改） */}
          <ChatPanel />
        </main>
      )}
    </div>
  );
}
