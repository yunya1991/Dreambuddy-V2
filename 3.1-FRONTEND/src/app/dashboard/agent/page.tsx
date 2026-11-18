"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { AgentChatPanel } from "@/components/features/agent/AgentChatPanel";
import { ChatPanel } from "@/components/features/chat/ChatPanel";
import { GateBar } from "@/components/features/task-board/GateBar";
import { GovernanceDrawer } from "@/components/features/task-board/GovernanceDrawer";
import { ScheduledTasksPanel } from "@/components/features/task-board/ScheduledTasksPanel";
import { SpecCard } from "@/components/features/task-board/SpecCard";
import { WorkflowMindmap } from "@/components/features/task-board/WorkflowMindmap";
import {
  useTaskBoard,
  type GateDecisionInput,
} from "@/lib/task-board/use-task-board";
import { useGovernanceInbox } from "@/lib/task-board/use-governance-inbox";
import type { TaskBoardListItem } from "@/lib/task-board/server-store";
import {
  TASK_STAGE_LABEL,
  type TaskBoardSnapshot,
} from "@/types/task-board";
import { V3StatusDot } from "@/components";
import { useTokenMonitorContext } from "@/lib/token-monitor-provider";
import {
  resolveDeepLinkSessionId,
  useAgentSessionStore,
} from "@/stores/agent-session-store";

// Agent 工作台：壳内页面（SPEC-20261111-A T-A1 / SPEC-B T-B6、T-B7）。
// SPEC-52 F1：全站唯一聊天入口。工作台内提供两种对话模式，二者共享同一路由：
//   - agent：协议层对话（/api/agent/chat，UIMessage.parts + 会话持久化）
//   - task ：交易任务对话（/api/task/stream + 择优脑暴开关，原 ChatPanel 能力，仅入口迁移）
// T-B7：会话由 agent-session-store 持久化，支持 ?session=<id> 深链。
//
// 三区布局：左栏（上=会话 / 下=治理待办抽屉）｜中=对话主区｜右=工作流思维导图 + 审批。
// 右侧与对话共用同一份看板快照，对话输出与任务规划同步推进。
type WorkbenchMode = "agent" | "task";

const MODE_LABELS: Record<WorkbenchMode, string> = {
  agent: "协议层对话",
  task: "交易任务",
};

const EMPTY_TASK_ID = "__none__";

export default function DashboardAgentPage() {
  const [mode, setMode] = useState<WorkbenchMode>("agent");

  const sessions = useAgentSessionStore((s) => s.sessions);
  const activeSessionId = useAgentSessionStore((s) => s.activeSessionId);
  const hydrated = useAgentSessionStore((s) => s.hydrated);
  const hydrate = useAgentSessionStore((s) => s.hydrate);
  const createSession = useAgentSessionStore((s) => s.createSession);
  const selectSession = useAgentSessionStore((s) => s.selectSession);
  const renameSession = useAgentSessionStore((s) => s.renameSession);
  const deleteSession = useAgentSessionStore((s) => s.deleteSession);
  const setAgentEnabled = useAgentSessionStore((s) => s.setAgentEnabled);
  const { state: tokenState, isLowBalance } = useTokenMonitorContext();
  const [confirmOpen, setConfirmOpen] = useState(false);

  // 主看板：activeTaskId 驱动；对话上报的快照只用于实时覆盖，服务端仍是权威
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [chatSnapshot, setChatSnapshot] = useState<TaskBoardSnapshot | null>(
    null,
  );
  const [streaming, setStreaming] = useState(false);
  const [specBusy, setSpecBusy] = useState(false);
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [recentTasks, setRecentTasks] = useState<TaskBoardListItem[]>([]);
  // 会话列表可折叠（多会话时释放空间）
  const [sessionsOpen, setSessionsOpen] = useState(true);
  // 定时任务草稿会话：在对话里描述，确认后落库
  const [draftSessionId, setDraftSessionId] = useState<string | null>(null);
  const [scheduledFormOpen, setScheduledFormOpen] = useState(false);
  const [scheduledTitle, setScheduledTitle] = useState("");
  const [scheduledPrompt, setScheduledPrompt] = useState("");
  const [scheduledInterval, setScheduledInterval] = useState(60);
  const [scheduledError, setScheduledError] = useState<string | null>(null);
  // 用户主动选中的任务不被对话新任务覆盖
  const pinnedTaskRef = useRef(false);

  const inbox = useGovernanceInbox({
    paused: streaming,
    excludeTaskIds: activeTaskId ? [activeTaskId] : [],
  });  const board = useTaskBoard(activeTaskId ?? EMPTY_TASK_ID);

  const loadTasks = useCallback(async () => {
    try {
      const response = await fetch("/api/tasks", { cache: "no-store" });
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; tasks?: TaskBoardListItem[] }
        | null;
      if (response.ok && data?.success && Array.isArray(data.tasks)) {
        setRecentTasks(data.tasks);
      }
    } catch {
      // 列表不可达不影响主看板
    }
  }, []);

  useEffect(() => {
    void loadTasks();
  }, [loadTasks, inbox.total]);

  // 有待办就展开抽屉（高优先级额外标亮）
  useEffect(() => {
    if (inbox.autoOpenSignal > 0) setDrawerOpen(true);
  }, [inbox.autoOpenSignal]);

  const handleTaskBoardSnapshot = useCallback(
    (snapshot: TaskBoardSnapshot | null, _traceId: string | null) => {
      setChatSnapshot(snapshot);
      if (snapshot?.task_id && snapshot.task_id !== EMPTY_TASK_ID) {
        if (!pinnedTaskRef.current) setActiveTaskId(snapshot.task_id);
      }
    },
    [],
  );

  // 右栏实时刷新：任务号已知时 2s 轮询，SPEC/意图一落盘就点亮
  useEffect(() => {
    if (!activeTaskId) return;
    let alive = true;
    const pull = async () => {
      try {
        const response = await fetch(
          `/api/task/${encodeURIComponent(activeTaskId)}`,
          { cache: "no-store" },
        );
        const data = (await response.json().catch(() => null)) as
          | { snapshot?: TaskBoardSnapshot }
          | null;
        if (alive && response.ok && data?.snapshot) {
          const next = data.snapshot;
          // 内容未变则复用旧对象，避免每 2s 触发整页重渲染
          setChatSnapshot((prev) =>
            prev &&
            prev.task_id === next.task_id &&
            prev.seq === next.seq &&
            prev.updated_at === next.updated_at
              ? prev
              : next,
          );
        }
      } catch {
        // 轮询失败保留上一次快照
      }
    };
    const timer = setInterval(() => void pull(), 2000);
    return () => {
      alive = false;
      clearInterval(timer);
    };
  }, [activeTaskId]);

  useEffect(() => {
    hydrate();
  }, [hydrate]);

  // 深链：?mode=task 直达交易任务模式
  useEffect(() => {
    if (typeof window === "undefined") return;
    const requestedMode = new URLSearchParams(window.location.search).get(
      "mode",
    );
    if (requestedMode === "task") setMode("task");
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const requested = resolveDeepLinkSessionId(
      window.location.search,
      sessions,
    );
    if (requested) {
      if (requested !== activeSessionId) selectSession(requested);
      return;
    }
    if (!activeSessionId) createSession("新会话");
  }, [hydrated, sessions, activeSessionId, selectSession, createSession]);

  const switchMode = (next: WorkbenchMode) => {
    setMode(next);
    if (typeof window === "undefined") return;
    const url = new URL(window.location.href);
    if (next === "task") url.searchParams.set("mode", "task");
    else url.searchParams.delete("mode");
    window.history.replaceState(null, "", `${url.pathname}${url.search}`);
  };

  const handleSelect = (id: string) => {
    selectSession(id);
    if (typeof window !== "undefined") {
      window.history.replaceState(
        null,
        "",
        `?session=${encodeURIComponent(id)}`,
      );
    }
  };

  const handleCreate = () => {
    const id = createSession();
    if (typeof window !== "undefined") {
      window.history.replaceState(
        null,
        "",
        `?session=${encodeURIComponent(id)}`,
      );
    }
  };

  const handleRename = (id: string, current: string) => {
    if (typeof window === "undefined") return;
    const next = window.prompt("重命名会话", current);
    if (next && next.trim()) renameSession(id, next);
  };

  const pickTask = (taskId: string) => {
    pinnedTaskRef.current = Boolean(taskId);
    setActiveTaskId(taskId || null);
  };

  const handleNewTask = () => {
    pinnedTaskRef.current = false;
    setActiveTaskId(null);
    setChatSnapshot(null);
    handleCreate();
  };

  // 「定时任务 +」：新开一个对话，用户在对话里描述，AI 协助改写后再确认落库
  const startScheduledDraft = () => {
    const id = createSession("定时任务 · 待设置");
    setDraftSessionId(id);
    pinnedTaskRef.current = false;
    setActiveTaskId(null);
    setChatSnapshot(null);
    handleSelect(id);
  };

  const openScheduledForm = () => {
    const session = sessions.find((item) => item.id === draftSessionId);
    const text =
      session?.messages
        .find((message) => message.role === "user")
        ?.parts.filter((part) => part.type === "text")
        .map((part) => (part.type === "text" ? part.text : ""))
        .join("\n") ?? "";
    setScheduledTitle(text.split("\n")[0]?.slice(0, 40) || "定时任务");
    setScheduledPrompt(text);
    setScheduledInterval(60);
    setScheduledError(null);
    setScheduledFormOpen(true);
  };

  const saveScheduledTask = async () => {
    if (!scheduledTitle.trim() || !scheduledPrompt.trim()) {
      setScheduledError("名称和指令都不能为空");
      return;
    }
    try {
      const response = await fetch("/api/scheduled-tasks", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          title: scheduledTitle.trim(),
          prompt: scheduledPrompt.trim(),
          interval_minutes: scheduledInterval,
        }),
      });
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; error?: string }
        | null;
      if (!response.ok || !data?.success) {
        setScheduledError(data?.error || "保存失败");
        return;
      }
      if (draftSessionId) renameSession(draftSessionId, scheduledTitle.trim());
      setDraftSessionId(null);
      setScheduledFormOpen(false);
    } catch {
      setScheduledError("network_error");
    }
  };

  const toggleDrawer = () => {
    const next = !drawerOpen;
    setDrawerOpen(next);
    if (next) inbox.markAllRead();
  };

  const handleDecideGate = useCallback(
    async (decision: GateDecisionInput) => {
      const result = await board.decideGate(decision);
      if (result.ok) {
        setChatSnapshot(result.snapshot ?? null);
        inbox.refresh();
        void loadTasks();
      }
      return { ok: result.ok, error: result.error };
    },
    [board, inbox, loadTasks],
  );

  // 对话内确认 SPEC：追加确认版，不产生门禁/治理待办
  const confirmSpec = async () => {
    if (!activeTaskId || specBusy) return;
    setSpecBusy(true);
    try {
      const response = await fetch(
        `/api/task/${encodeURIComponent(activeTaskId)}/spec/confirm`,
        { method: "POST" },
      );
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; snapshot?: TaskBoardSnapshot }
        | null;
      if (response.ok && data?.success && data.snapshot) {
        setChatSnapshot(data.snapshot);
      }
    } finally {
      setSpecBusy(false);
    }
  };

  const activeSession = sessions.find((s) => s.id === activeSessionId);
  const agentEnabled = Boolean(activeSession?.agentEnabled);
  const balanceKnown = tokenState.lastChecked > 0;
  // 管理员账号不设额度上限：余额为 0 也不锁定
  const insufficient = balanceKnown && !tokenState.unlimited && tokenState.balance <= 0;

  const handleToggleAgent = () => {
    if (!activeSession) return;
    if (agentEnabled) {
      setConfirmOpen(false);
      setAgentEnabled(activeSession.id, false);
      return;
    }
    // 已确认过且余额可用：直接开启；否则弹计费/充值提示
    if (activeSession.agentAcknowledged && !insufficient) {
      setAgentEnabled(activeSession.id, true);
      return;
    }
    setConfirmOpen((open) => !open);
  };

  // 切会话时收起上一个会话的计费提示，并清空看板，避免串会话
  useEffect(() => {
    setConfirmOpen(false);
    setChatSnapshot(null);
    setActiveTaskId(null);
    setStreaming(false);
    pinnedTaskRef.current = false;
  }, [activeSessionId]);

  // 服务端快照与对话实时快照取较新者，保证确认后立即生效
  const live =
    activeTaskId && chatSnapshot?.task_id === activeTaskId
      ? chatSnapshot
      : null;
  const displayed =
    live && live.updated_at >= board.snapshot.updated_at
      ? live
      : board.snapshot;
  const pendingGateCount = activeTaskId
    ? displayed.gates.filter(
        (gate) => gate.required && gate.status !== "approved",
      ).length
    : 0;

  return (
    <div className="flex h-full flex-col bg-[var(--color-bg-primary)]">
      <header className="flex flex-wrap items-center justify-between gap-2 border-b border-slate-800 px-6 py-3">
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold text-indigo-400">
            Agent 工作台
          </span>
          <V3StatusDot status="success" size="sm" label="在线" />
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          {agentEnabled && (
            <span
              className={`rounded-full border px-2 py-0.5 text-[10px] ${
                isLowBalance
                  ? "border-amber-700/60 text-amber-300"
                  : "border-slate-800 text-slate-400"
              }`}
              title="AI Agent 按 token 扣积分"
            >
              积分{" "}
              {tokenState.unlimited
                ? "不限"
                : balanceKnown
                  ? tokenState.balance.toLocaleString("zh-CN")
                  : "—"}
            </span>
          )}

          <div className="relative flex items-center gap-2 rounded-full border border-slate-800 bg-slate-900/60 px-2 py-1">
            <span className="text-[11px] text-slate-300">AI Agent</span>
            <button
              type="button"
              role="switch"
              aria-checked={agentEnabled}
              aria-label="启用 AI Agent"
              onClick={handleToggleAgent}
              disabled={!activeSession}
              className={`relative h-4 w-7 shrink-0 rounded-full transition-colors ${
                agentEnabled ? "bg-emerald-500" : "bg-slate-700"
              } disabled:opacity-50`}
            >
              <span
                className={`absolute top-0.5 left-0 h-3 w-3 rounded-full bg-white transition-transform ${
                  agentEnabled ? "translate-x-3.5" : "translate-x-0.5"
                }`}
              />
            </button>

            {confirmOpen && activeSession && (
              <div className="absolute right-0 top-full z-20 mt-2 w-64 rounded-xl border border-slate-700 bg-slate-900 p-3 shadow-xl">
                {insufficient ? (
                  <>
                    <p className="text-xs font-medium text-amber-300">
                      积分不足，无法启用 AI Agent
                    </p>
                    <p className="mt-1 text-[11px] text-slate-400">
                      当前余额 0，充值后再开启；默认模式仍可免费使用。
                    </p>
                    <div className="mt-3 flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setConfirmOpen(false)}
                        className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        取消
                      </button>
                      <Link
                        href="/recharge"
                        className="rounded-md bg-emerald-500 px-2 py-1 text-[11px] font-medium text-emerald-950"
                      >
                        去充值
                      </Link>
                    </div>
                  </>
                ) : (
                  <>
                    <p className="text-xs font-medium text-slate-200">
                      启用 AI Agent？
                    </p>
                    <p className="mt-1 text-[11px] text-slate-400">
                      启用后按 token 扣积分
                      {balanceKnown
                        ? `，当前余额 ${tokenState.balance.toLocaleString("zh-CN")}`
                        : ""}
                      ，预计每次 5–20 积分。
                    </p>
                    <div className="mt-3 flex justify-end gap-2">
                      <button
                        type="button"
                        onClick={() => setConfirmOpen(false)}
                        className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:text-slate-200"
                      >
                        暂不启用
                      </button>
                      <button
                        type="button"
                        onClick={() => {
                          setConfirmOpen(false);
                          setAgentEnabled(activeSession.id, true);
                        }}
                        className="rounded-md bg-emerald-500 px-2 py-1 text-[11px] font-medium text-emerald-950"
                      >
                        启用
                      </button>
                    </div>
                  </>
                )}
              </div>
            )}
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
                    ? "bg-indigo-600/25 text-indigo-200"
                    : "text-slate-400 hover:bg-slate-800/60 hover:text-slate-300"
                }`}
              >
                {MODE_LABELS[item]}
              </button>
            ))}
          </div>
        </div>
      </header>

      {mode === "agent" ? (
        <main className="flex flex-1 overflow-hidden">
          {/* 左栏：上半会话 / 下半治理抽屉 */}
          <aside className="hidden w-60 shrink-0 flex-col border-r border-slate-800 md:flex">
            <div className="flex min-h-0 flex-1 flex-col">
              <div className="flex items-center justify-between border-b border-slate-800 px-3 py-2">
                <button
                  type="button"
                  onClick={() => setSessionsOpen((value) => !value)}
                  aria-expanded={sessionsOpen}
                  className="flex min-w-0 flex-1 items-center gap-2 text-left"
                >
                  <span className="text-[11px] uppercase tracking-wider text-slate-500">
                    会话
                  </span>
                  <span className="rounded-full bg-slate-800 px-1.5 py-0.5 text-[10px] text-slate-400">
                    {sessions.length}
                  </span>
                  <span className="ml-auto text-[10px] text-slate-500">
                    {sessionsOpen ? "收起" : "展开"}
                  </span>
                </button>
                <button
                  onClick={handleCreate}
                  className="ml-2 rounded px-1.5 py-0.5 text-xs text-indigo-300 hover:bg-slate-800"
                  aria-label="新建会话"
                >
                  ＋
                </button>
              </div>
              <div
                className={`flex-1 space-y-1 overflow-y-auto p-2 ${
                  sessionsOpen ? "" : "hidden"
                }`}
              >
                {sessions.length === 0 && (
                  <p className="px-2 py-4 text-[11px] text-slate-600">
                    暂无会话
                  </p>
                )}
                {sessions.map((session) => (
                  <div
                    key={session.id}
                    className={`group flex items-center gap-1 rounded-lg px-2 py-1.5 text-xs ${
                      session.id === activeSessionId
                        ? "bg-indigo-600/20 text-indigo-200"
                        : "text-slate-400 hover:bg-slate-800/60"
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
            </div>

            <ScheduledTasksPanel onStartDraft={startScheduledDraft} />

            <GovernanceDrawer
              inbox={inbox}
              open={drawerOpen}
              onToggle={toggleDrawer}
              activeTaskId={activeTaskId}
              onSelectTask={pickTask}
            />
          </aside>

          {/* 中：对话主区 */}
          <section className="min-w-0 flex-1 overflow-hidden">
            {activeSessionId ? (
              <AgentChatPanel
                sessionId={activeSessionId}
                title={activeSession?.title}
                agentEnabled={agentEnabled}
                onTaskBoardSnapshot={handleTaskBoardSnapshot}
                onStreamingChange={setStreaming}
                onTaskStart={setActiveTaskId}
                headerAction={
                  activeSessionId === draftSessionId ? (
                    <button
                      type="button"
                      onClick={openScheduledForm}
                      className="rounded border border-indigo-700/60 bg-indigo-950/30 px-2 py-0.5 text-[10px] text-indigo-200 hover:bg-indigo-900/40"
                    >
                      设为定时任务
                    </button>
                  ) : undefined
                }
              />
            ) : (
              <div className="flex h-full items-center justify-center text-xs text-slate-600">
                正在准备会话…
              </div>
            )}
          </section>

          {/* 右：工作流思维导图 + 门禁审批（与对话同步） */}
          <aside className="hidden w-[380px] shrink-0 flex-col border-l border-slate-800 bg-slate-950/30 xl:flex">
            <div className="flex shrink-0 flex-wrap items-center gap-2 border-b border-slate-800 px-3 py-2">
              <span className="text-[10px] uppercase tracking-wider text-slate-500">
                当前任务
              </span>
              <select
                value={activeTaskId ?? ""}
                onChange={(event) => pickTask(event.target.value)}
                className="min-w-0 flex-1 rounded-md border border-slate-700 bg-slate-900/80 px-2 py-1 text-[11px] text-slate-200 outline-none focus:border-indigo-700"
                aria-label="切换任务"
              >
                <option value="">最近任务…</option>
                {recentTasks.map((task) => (
                  <option key={task.task_id} value={task.task_id}>
                    {task.title} · {TASK_STAGE_LABEL[task.stage]}
                    {task.pending_gates > 0
                      ? ` · 待确认 ${task.pending_gates}`
                      : ""}
                  </option>
                ))}
              </select>
              <button
                type="button"
                onClick={handleNewTask}
                className="rounded-md border border-slate-700 px-2 py-1 text-[11px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                新建任务
              </button>
            </div>

            <div className="min-h-0 flex-1 overflow-y-auto">
              {activeTaskId && displayed.spec && (
                <SpecCard
                  snapshot={displayed}
                  busy={specBusy}
                  onConfirm={() => void confirmSpec()}
                />
              )}
              {activeTaskId && pendingGateCount > 0 && (
                <div className="p-3 pb-0">
                  <GateBar
                    taskId={activeTaskId}
                    gates={displayed.gates}
                    busyGateId={board.busyGateId}
                    mode={board.mode}
                    onDecide={handleDecideGate}
                  />
                </div>
              )}
              <WorkflowMindmap
                snapshot={activeTaskId ? displayed : null}
                taskId={activeTaskId}
              />
            </div>
          </aside>
        </main>
      ) : (
        <main className="min-w-0 flex-1 overflow-hidden">
          {/* 交易任务对话：原 ChatPanel 原形态迁入（含择优脑暴开关，API 不改） */}
          <ChatPanel />
        </main>
      )}

      {scheduledFormOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <h3 className="text-sm font-semibold text-slate-100">
              设为定时任务
            </h3>
            <p className="mt-1 text-[11px] text-slate-400">
              确认下面这版指令后保存，AI 会按设定周期自动执行。
            </p>
            <div className="mt-3 space-y-2">
              <input
                value={scheduledTitle}
                onChange={(event) => setScheduledTitle(event.target.value)}
                placeholder="任务名称"
                className="w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 outline-none focus:border-indigo-700"
              />
              <textarea
                value={scheduledPrompt}
                onChange={(event) => setScheduledPrompt(event.target.value)}
                rows={4}
                placeholder="要执行的指令"
                className="w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 outline-none focus:border-indigo-700"
              />
              <div className="flex items-center gap-2">
                <span className="text-[11px] text-slate-400">每隔</span>
                <input
                  type="number"
                  min={5}
                  value={scheduledInterval}
                  onChange={(event) =>
                    setScheduledInterval(Number(event.target.value))
                  }
                  className="w-20 rounded-md border border-slate-700 bg-slate-950/80 px-2 py-1.5 text-xs text-slate-200 outline-none"
                />
                <span className="text-[11px] text-slate-400">分钟</span>
              </div>
              {scheduledError && (
                <p className="text-[11px] text-red-400">{scheduledError}</p>
              )}
            </div>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setScheduledFormOpen(false)}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
              >
                取消
              </button>
              <button
                type="button"
                onClick={() => void saveScheduledTask()}
                className="rounded-md bg-indigo-500 px-3 py-1.5 text-[11px] font-medium text-white"
              >
                保存定时任务
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
