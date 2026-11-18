"use client";

// ============================================
// AgentChatPanel — 协议层对话面板（SPEC-20261111-B §3.6 ~ §3.9）
// ============================================
// T-B6：/api/agent/chat 的 UIMessage.parts 经 ui-message-to-parts 映射后由 PartRenderer 渲染。
// T-B7：会话消息由 agent-session-store 持久化，切换会话重新挂载 useChat。
// T-B8：>50 条消息启用 content-visibility 虚拟化。
// T-B9：ChatInput 增强（停止/重生成/草稿/历史/@ 候选/附件文件名）。

import React, { useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useChat } from "@ai-sdk/react";
import {
  DefaultChatTransport,
  createUIMessageStream,
  createUIMessageStreamResponse,
} from "ai";
import type { UIMessage } from "ai";
import { PartList } from "./PartRenderer";
import {
  ChatInput,
  type ChatInputSuggestion,
} from "@/components/features/chat/ChatInput";
import {
  uiMessageToParts,
  type LooseUIMessage,
} from "@/lib/adapters/ui-message-to-parts";
import { shouldVirtualize, VIRTUALIZED_ROW_STYLE } from "@/lib/virtualization";
import {
  useAgentSessionStore,
  type AgentSession,
} from "@/stores/agent-session-store";
import type { AgentMessage } from "@/types/agent-message";
import { TracePanel } from "./TracePanel";
import type { TraceSpan } from "@/types/run-trace";
import {
  TASK_EVENT_TYPES,
  type TaskBoardEvent,
  type TaskBoardSnapshot,
} from "@/types/task-board";
import { projectTaskEvents } from "@/lib/task-board/project-events";
import { applyEventsToStorage } from "@/lib/task-board/use-task-board";

/** 静态技能候选（无 skills API 时的降级清单，SPEC-B §3.9） */
const STATIC_SUGGESTIONS: ChatInputSuggestion[] = [
  { label: "行情分析", value: "@行情分析", hint: "技能" },
  { label: "风控检查", value: "@风控检查", hint: "技能" },
  { label: "基本面", value: "@基本面", hint: "技能" },
  { label: "报告生成", value: "@报告生成", hint: "技能" },
];

/** 浏览器 fetch 被网络层掐断时的错误文案（瞬时可恢复，值得自动重试一次） */
const NETWORK_ERROR_RE =
  /failed to fetch|fetch failed|networkerror|load failed|network request failed|err_network/i;

function toUiMessages(session: AgentSession | undefined): UIMessage[] {
  if (!session) return [];
  return session.messages.map(
    (m) => ({ id: m.id, role: m.role, parts: m.parts }) as unknown as UIMessage,
  );
}

function toAgentMessages(
  messages: UIMessage[],
  isError: boolean,
): AgentMessage[] {
  const now = Date.now();
  return messages.map((m) => ({
    id: m.id,
    role: m.role,
    parts: uiMessageToParts(m as unknown as LooseUIMessage),
    createdAt: now,
    status: isError ? "error" : "done",
  }));
}

/** 从 UIMessage 的 data-trace part 收集调度轨迹（同一 span 保留终态） */
function collectTraceSpans(messages: UIMessage[]): TraceSpan[] {
  const map = new Map<string, TraceSpan>();
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    for (const part of (message.parts ?? []) as Array<{
      type?: string;
      data?: unknown;
    }>) {
      if (part?.type !== "data-trace" || !part.data) continue;
      const span = part.data as TraceSpan;
      if (span?.span_id) map.set(span.span_id, span);
    }
  }
  return [...map.values()].sort(
    (a, b) => a.started_at - b.started_at || a.seq - b.seq,
  );
}

/** 从 UIMessage 的 data-task part 收集业务事件（编排侧显式推送） */
function collectTaskEvents(messages: UIMessage[]): TaskBoardEvent[] {
  const events: TaskBoardEvent[] = [];
  for (const message of messages) {
    if (message.role !== "assistant") continue;
    for (const part of (message.parts ?? []) as Array<{
      type?: string;
      data?: unknown;
    }>) {
      if (part?.type !== "data-task" || !part.data) continue;
      const event = part.data as TaskBoardEvent;
      if (event?.task_id && TASK_EVENT_TYPES.includes(event.type)) {
        events.push(event);
      }
    }
  }
  return events;
}

export interface AgentChatPanelProps {
  sessionId: string;
  /** 会话标题（用于头部展示） */
  title?: string;
  /** AI Agent 开关；关闭时服务端只走默认规则，不调用大模型 */
  agentEnabled?: boolean;
  /** 看板快照上报：工作台右侧实时栏消费 */
  onTaskBoardSnapshot?: (
    snapshot: TaskBoardSnapshot | null,
    traceId: string | null,
  ) => void;
  /** 流式状态上报：工作台据此冻结治理抽屉的自动弹出 */
  onStreamingChange?: (streaming: boolean) => void;
  /** 头部右侧附加操作（如「设为定时任务」） */
  headerAction?: React.ReactNode;
  /** 外部指定任务号；不传则由会话派生并持久化，保证 SPEC 门禁与右栏实时可见 */
  taskId?: string;
  /** 本轮开始（右栏可立即挂载并轮询） */
  onTaskStart?: (taskId: string) => void;
}

function AgentChatPanelInner({
  sessionId,
  title,
  agentEnabled = false,
  onTaskBoardSnapshot,
  onStreamingChange,
  headerAction,
  taskId: taskIdProp,
  onTaskStart,
}: AgentChatPanelProps) {
  const setMessages = useAgentSessionStore((s) => s.setMessages);
  const storedSession = useAgentSessionStore((s) =>
    s.sessions.find((item) => item.id === sessionId),
  );
  const initialMessages = useMemo(
    () => toUiMessages(storedSession),
    [sessionId],
  ); // eslint-disable-line react-hooks/exhaustive-deps
  // 任务号与会话绑定并持久化：随请求下发后，右栏可立即挂载轮询，
  // 不必等本轮流结束才拿到 trace_id。
  const taskId = useMemo(() => {
    if (taskIdProp) return taskIdProp;
    const key = `wb-task:${sessionId}`;
    try {
      const existing = window.sessionStorage.getItem(key);
      if (existing) return existing;
      const id =
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `wb-${Date.now()}-${Math.random().toString(16).slice(2)}`;
      window.sessionStorage.setItem(key, id);
      return id;
    } catch {
      return `wb-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    }
  }, [sessionId, taskIdProp]);
  const [input, setInput] = useState("");
  const [l2Reviewed, setL2Reviewed] = useState(false);
  // O0 调度轨迹：随消息流累积，新一轮发送时清空
  const [traceSpans, setTraceSpans] = useState<TraceSpan[]>([]);
  // 调度轨迹属于诊断视图：默认隐藏，仅 ?debug=1 时出现
  const [debug, setDebug] = useState(false);
  const [showTrace, setShowTrace] = useState(false);
  // 对话内确认（意图澄清 / 写操作）：409 拦截后立即弹窗，确认后继续
  const [pendingConfirm, setPendingConfirm] = useState<{
    taskId: string;
    gates: Array<{
      gate_id: string;
      kind: string;
      title: string;
      evidence_ref: string;
    }>;
  } | null>(null);
  const [confirmBusy, setConfirmBusy] = useState(false);
  const [confirmError, setConfirmError] = useState<string | null>(null);
  const [confirmRejecting, setConfirmRejecting] = useState(false);
  const [confirmComment, setConfirmComment] = useState("");
  // 意图澄清：不是审批，用户补充一句即可继续，不产生待办
  const [clarify, setClarify] = useState<{
    message: string;
    text: string;
  } | null>(null);
  // SPEC 硬门禁：生成后必须先确认，确认前大模型不推进
  const [specConfirm, setSpecConfirm] = useState<{
    taskId: string;
    fields: Array<{ key: string; label: string; value: string }>;
  } | null>(null);
  const [specConfirmBusy, setSpecConfirmBusy] = useState(false);

  /** 409 被拦截时用一段普通文本流收尾，避免 useChat 抛网络错误 */
  const confirmStreamResponse = (text: string) => {
    const stream = createUIMessageStream({
      execute: ({ writer }) => {
        const id = `confirm-${Date.now()}`;
        writer.write({ type: "text-start", id });
        writer.write({ type: "text-delta", id, delta: text });
        writer.write({ type: "text-end", id });
      },
    });
    return createUIMessageStreamResponse({ stream });
  };
  const endRef = useRef<HTMLDivElement>(null);
  // 服务端事件同步去重：同一轮事件集只上报一次
  const syncedRef = useRef<string>("");

  const transport = useMemo(
    () =>
      new DefaultChatTransport({
        api: "/api/agent/chat",
        // 读取服务端接管标记：本轮回答由 L2 复核/接管时在头部展示
        fetch: async (input: RequestInfo | URL, init?: RequestInit) => {
          const res = await fetch(input, init);
          // 意图澄清 / 写操作确认：服务端返回 409，直接转为对话内弹窗
          if (res.status === 409) {
            const payload = (await res.clone().json().catch(() => null)) as
              | {
                  task_id?: string;
                  error?: { code?: string; message?: string };
                  spec?: {
                    fields?: Array<{
                      key: string;
                      label: string;
                      value: string;
                    }>;
                  };
                  pending_gates?: Array<{
                    gate_id: string;
                    kind: string;
                    title: string;
                    evidence_ref: string;
                  }>;
                }
              | null;
            // SPEC 硬门禁：先确认再推进
            if (payload?.error?.code === "SPEC_CONFIRM_REQUIRED") {
              const nextTaskId = String(payload.task_id || taskId);
              setSpecConfirm({
                taskId: nextTaskId,
                fields: payload.spec?.fields ?? [],
              });
              onTaskStart?.(nextTaskId);
              return confirmStreamResponse("SPEC 已生成，确认后继续。");
            }
            // 意图澄清：弹一个补充框，用户写完继续，不生成审批
            if (payload?.error?.code === "INTENT_CLARIFICATION") {
              setClarify({
                message:
                  payload.error.message ??
                  "意图不明确：请补充要处理的对象或范围",
                text: "",
              });
              return confirmStreamResponse("需要你补充一点信息后继续。");
            }
            if (payload?.pending_gates?.length) {
              setPendingConfirm({
                taskId: String(payload.task_id ?? ""),
                gates: payload.pending_gates,
              });
              setConfirmError(null);
              setConfirmRejecting(false);
              setConfirmComment("");
              return confirmStreamResponse("这一步需要你确认后继续。");
            }
          }
          // 读取服务端接管标记：本轮回答由 L2 复核/接管时在头部展示
          setL2Reviewed(res.headers.get("x-l2-takeover") === "1");
          return res;
        },
      }),
    [],
  );
  const { messages, sendMessage, status, error, stop, regenerate } = useChat({
    id: sessionId,
    messages: initialMessages,
    transport,
    onFinish: ({ messages: finalMessages, isError }) => {
      setMessages(sessionId, toAgentMessages(finalMessages, isError));
    },
  });

  // 流式消息里的 data-trace part 会持续更新：合并进面板状态（保留终态）
  useEffect(() => {
    const next = collectTraceSpans(messages);
    if (next.length === 0) return;
    setTraceSpans((prev) => {
      const map = new Map(prev.map((span) => [span.span_id, span]));
      for (const span of next) map.set(span.span_id, span);
      return [...map.values()].sort(
        (a, b) => a.started_at - b.started_at || a.seq - b.seq,
      );
    });
  }, [messages]);

  // 诊断模式：只在 ?debug=1 时展开调度轨迹
  useEffect(() => {
    const on = new URLSearchParams(window.location.search).get("debug") === "1";
    setDebug(on);
    if (on) setShowTrace(true);
  }, []);

  // 任务看板：优先使用编排侧 data-task 事件；没有时用 O0 轨迹降级投影。
  // 流式过程中不落盘，结束后再写一次，避免每个 token 触发 localStorage 写入。
  useEffect(() => {
    if (status === "submitted" || status === "streaming") return;
    const traceId = traceSpans[0]?.trace_id;
    if (!traceId) return;
    const events = [
      ...projectTaskEvents({ taskId: traceId, traceId }, traceSpans),
      ...collectTaskEvents(messages),
    ];
    const snapshot = applyEventsToStorage(traceId, traceId, events);
    onTaskBoardSnapshot?.(snapshot, traceId);

    // 同步到服务端 L0：治理待办与门禁由服务端快照统一回放
    if (events.length === 0) return;
    const signature = `${traceId}:${events.length}`;
    if (syncedRef.current === signature) return;
    syncedRef.current = signature;
    void fetch(`/api/task/${encodeURIComponent(traceId)}`, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ events }),
    })
      .then(async (response) => {
        if (!response.ok) return;
        const data = (await response.json().catch(() => null)) as
          | { success?: boolean; snapshot?: TaskBoardSnapshot }
          | null;
        if (data?.snapshot) onTaskBoardSnapshot?.(data.snapshot, traceId);
      })
      .catch(() => {
        // 服务端不可达：本地快照仍然可用，不打断对话
      });
  }, [traceSpans, messages, status, onTaskBoardSnapshot]);

  const busy = status === "submitted" || status === "streaming";

  // 流式状态外抛：治理抽屉在推理期间不自动弹出
  useEffect(() => {
    onStreamingChange?.(busy);
  }, [busy, onStreamingChange]);

  const virtualize = shouldVirtualize(messages.length);
  // 本轮任务号沿用 trace_id：看板与轨迹共用同一标识
  const traceId = traceSpans[0]?.trace_id;
  // AI Agent 档位随每次发送/重生成带到服务端；关闭时服务端不调用大模型
  const requestOptions = useMemo(
    () => ({ body: { agent_enabled: agentEnabled, task_id: taskId } }),
    [agentEnabled, taskId],
  );

  // 断网续流：流被网络中断时记下「待恢复」，联网恢复后自动重试该轮一次
  const [online, setOnline] = useState(true);
  const interruptedRef = useRef(false);
  const retriedRef = useRef(false);
  // 网络级失败自动重试一次（每轮发送重置），避免瞬时抖动直接把 "Failed to fetch" 抛给用户
  const autoRetriedRef = useRef(false);

  useEffect(() => {
    if (status === "submitted" || status === "streaming") {
      // 新一轮请求已发出且仍在进行：清除中断标记，允许下次中断再续
      interruptedRef.current = false;
      retriedRef.current = false;
    } else if (status === "error") {
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
      if (
        messages.length > 0 &&
        interruptedRef.current &&
        !retriedRef.current
      ) {
        retriedRef.current = true;
        interruptedRef.current = false;
        void regenerate(requestOptions).catch(() => {
          // 续流失败保持原样，由用户手动「重生成」
        });
      }
    };
    window.addEventListener("offline", handleOffline);
    window.addEventListener("online", handleOnline);
    return () => {
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener("online", handleOnline);
    };
  }, [regenerate, messages.length, requestOptions]);

  // 网络级失败（浏览器侧 fetch 被掐断）→ 自动重试该轮一次，成功则错误自然清除
  useEffect(() => {
    if (status !== "error" || autoRetriedRef.current) return;
    const reason = error instanceof Error ? error.message : "";
    if (!NETWORK_ERROR_RE.test(reason) || messages.length === 0) return;
    autoRetriedRef.current = true;
    const timer = setTimeout(() => {
      void regenerate(requestOptions).catch(() => {
        // 重试仍失败：保留原始错误，由用户手动「重新生成」
      });
    }, 800);
    return () => clearTimeout(timer);
  }, [status, error, messages.length, regenerate, requestOptions]);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length, status]);

  const handleSend = (attachments?: string[]) => {
    const text = input.trim();
    if (!text || busy) return;
    const composed =
      attachments && attachments.length > 0
        ? `${text}\n\n[附件] ${attachments.join(", ")}`
        : text;
    setInput("");
    setL2Reviewed(false);
    setTraceSpans([]);
    interruptedRef.current = false;
    retriedRef.current = false;
    autoRetriedRef.current = false;
    // 先告诉工作台任务号：右栏立刻挂载，SPEC/意图事件一到就点亮
    onTaskStart?.(taskId);
    void sendMessage({ text: composed }, requestOptions);
  };

  const approveSpecAndContinue = async () => {
    if (!specConfirm || specConfirmBusy) return;
    setSpecConfirmBusy(true);
    try {
      const response = await fetch(
        `/api/task/${encodeURIComponent(specConfirm.taskId)}/spec/confirm`,
        { method: "POST" },
      );
      if (!response.ok) return;
      setSpecConfirm(null);
      // 确认已落盘，重发刚才被拦截的这一轮
      void regenerate(requestOptions);
    } finally {
      setSpecConfirmBusy(false);
    }
  };

  const handleConfirmDecision = async (status: "approved" | "rejected") => {
    if (!pendingConfirm || confirmBusy) return;
    if (status === "rejected" && !confirmComment.trim()) {
      setConfirmError("驳回请填写原因");
      return;
    }
    setConfirmBusy(true);
    setConfirmError(null);
    try {
      const response = await fetch(
        `/api/task/${encodeURIComponent(pendingConfirm.taskId)}/gate`,
        {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({
            gate_id: pendingConfirm.gates[0].gate_id,
            gate_ids:
              pendingConfirm.gates.length > 1
                ? pendingConfirm.gates.map((gate) => gate.gate_id)
                : undefined,
            status,
            comment: status === "rejected" ? confirmComment.trim() : undefined,
          }),
        },
      );
      const data = (await response.json().catch(() => null)) as
        | { success?: boolean; error?: string; snapshot?: TaskBoardSnapshot }
        | null;
      if (!response.ok || !data?.success) {
        setConfirmError(data?.error || `http_${response.status}`);
        return;
      }
      if (data.snapshot) {
        onTaskBoardSnapshot?.(data.snapshot, pendingConfirm.taskId);
      }
      setPendingConfirm(null);
      setConfirmRejecting(false);
      setConfirmComment("");
      // 通过后继续刚才被拦截的这一轮（跳过重复的澄清拦截）
      if (status === "approved") {
        void regenerate({
          body: { agent_enabled: agentEnabled, intent_confirmed: true },
        });
      }
    } catch {
      setConfirmError("network_error");
    } finally {
      setConfirmBusy(false);
    }
  };

  return (
    <div className="flex h-full min-h-0">
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="flex shrink-0 items-center gap-2 border-b border-slate-800 px-4 py-2 text-xs text-slate-400">
          <span className="truncate">{title || "新会话"}</span>
          <span className="shrink-0 text-[10px] text-slate-600">
            {agentEnabled ? "AI Agent · 按 token 计费" : "默认模式 · 不扣积分"}
          </span>
          {l2Reviewed && (
            <span
              data-testid="l2-reviewed-badge"
              className="shrink-0 rounded border border-indigo-700/50 bg-indigo-950/40 px-1.5 py-0.5 text-[10px] text-indigo-300"
            >
              已由 L2 复核
            </span>
          )}
          <div className="ml-auto flex shrink-0 items-center gap-1.5">
            {headerAction}
            {traceId && (
              <Link
                href={`/dashboard/task/${traceId}`}
                className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
              >
                任务看板 ↗
              </Link>
            )}
            {debug && (
              <button
                type="button"
                data-testid="agent-trace-toggle"
                onClick={() => setShowTrace((v) => !v)}
                className="rounded border border-slate-700 px-2 py-0.5 text-[10px] text-slate-400 hover:bg-slate-800 hover:text-slate-200"
                aria-pressed={showTrace}
              >
                {showTrace ? "隐藏轨迹" : "调度轨迹"}
              </button>
            )}
          </div>
        </header>

      <div className="flex-1 overflow-y-auto px-4 py-3 space-y-4">
        {messages.length === 0 && !busy && (
          <div className="flex h-full flex-col items-center justify-center text-slate-500">
            <p className="text-sm">Agent 工作台已就绪</p>
            <p className="mt-1 text-xs text-slate-600">
              输入问题，或输入 @ 选择技能
            </p>
          </div>
        )}

        {messages.map((message) => {
          const parts = uiMessageToParts(message as unknown as LooseUIMessage);
          return (
            <div
              key={message.id}
              data-testid="agent-message-row"
              style={virtualize ? VIRTUALIZED_ROW_STYLE : undefined}
              className={
                message.role === "user"
                  ? "flex justify-end"
                  : "flex justify-start"
              }
            >
              <div className="max-w-[85%]">
                {message.role === "user" ? (
                  <div className="rounded-xl border border-slate-700/40 bg-slate-800/60 px-4 py-2.5 text-sm text-slate-200 whitespace-pre-wrap break-words">
                    {parts
                      .filter((p) => p.type === "text")
                      .map((p) => (p.type === "text" ? p.text : ""))
                      .join("\n")}
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
            {status === "submitted" ? "正在提交…" : "正在生成…"}
          </div>
        )}

        {!online && (
          <div className="rounded-lg border border-amber-800/40 bg-amber-950/30 px-3 py-2 text-xs text-amber-300">
            网络已断开{busy ? "，正在等待重连…" : "，恢复联网后将自动重试"}
          </div>
        )}

        {error && (
          <div className="rounded-lg border border-red-800/40 bg-red-950/30 px-3 py-2 text-xs text-red-300">
            {NETWORK_ERROR_RE.test(error.message)
              ? "网络连接中断，已自动重试；仍失败请点击「重新生成」"
              : `请求失败：${error.message}`}
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
          onRegenerate={() => void regenerate(requestOptions)}
          placeholder="输入问题，Enter 发送，Shift+Enter 换行，@ 选择技能"
        />
      </div>
      </div>
      {specConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="flex max-h-[80vh] w-full max-w-lg flex-col rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <h3 className="text-sm font-semibold text-slate-100">
              确认 SPEC 后继续
            </h3>
            <p className="mt-1 text-[11px] text-slate-400">
              SPEC 未确认前不会推进执行。确认后会按这份 SPEC 的深度与工具预算执行。
            </p>
            <dl className="mt-3 min-h-0 flex-1 space-y-1.5 overflow-y-auto rounded-lg border border-slate-800 bg-slate-950/50 p-3">
              {specConfirm.fields.map((field) => (
                <div key={field.key}>
                  <dt className="text-[9px] uppercase tracking-wider text-slate-500">
                    {field.label}
                  </dt>
                  <dd className="mt-0.5 text-[10px] leading-relaxed text-slate-300 break-words">
                    {field.value}
                  </dd>
                </div>
              ))}
            </dl>
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                disabled={specConfirmBusy}
                onClick={() => setSpecConfirm(null)}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
              >
                先不执行
              </button>
              <button
                type="button"
                disabled={specConfirmBusy}
                onClick={() => void approveSpecAndContinue()}
                className="rounded-md bg-indigo-500 px-3 py-1.5 text-[11px] font-medium text-white disabled:opacity-50"
              >
                {specConfirmBusy ? "确认中…" : "确认并继续"}
              </button>
            </div>
          </div>
        </div>
      )}

      {clarify && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <h3 className="text-sm font-semibold text-slate-100">
              补充一下你的意图
            </h3>
            <p className="mt-1 text-[11px] text-slate-400">{clarify.message}</p>
            <textarea
              value={clarify.text}
              onChange={(event) =>
                setClarify((current) =>
                  current ? { ...current, text: event.target.value } : current,
                )
              }
              rows={3}
              autoFocus
              placeholder="例如：把 600519 的持仓报告整理一下"
              className="mt-3 w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 outline-none focus:border-indigo-700"
            />
            <div className="mt-4 flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setClarify(null)}
                className="rounded-md border border-slate-700 px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
              >
                取消
              </button>
              <button
                type="button"
                disabled={!clarify.text.trim()}
                onClick={() => {
                  const text = clarify.text.trim();
                  if (!text) return;
                  setClarify(null);
                  void sendMessage({ text }, requestOptions);
                }}
                className="rounded-md bg-indigo-500 px-3 py-1.5 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
              >
                继续
              </button>
            </div>
          </div>
        </div>
      )}

      {pendingConfirm && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4">
          <div className="w-full max-w-md rounded-2xl border border-slate-700 bg-slate-900 p-5 shadow-2xl">
            <h3 className="text-sm font-semibold text-slate-100">
              需要你确认后继续
            </h3>
            <p className="mt-1 text-[11px] text-slate-400">
              这一步涉及
              {pendingConfirm.gates.some((gate) => gate.kind === "intent")
                ? "意图澄清"
                : "写操作"}
              ，确认后才会继续执行。
            </p>
            <ul className="mt-3 space-y-1.5">
              {pendingConfirm.gates.map((gate) => (
                <li
                  key={gate.gate_id}
                  className="rounded-lg border border-slate-800 bg-slate-950/60 px-2.5 py-2"
                >
                  <p className="text-[11px] text-slate-200">{gate.title}</p>
                  <p className="mt-0.5 text-[10px] text-slate-500">
                    证据 {gate.evidence_ref}
                  </p>
                </li>
              ))}
            </ul>

            {confirmRejecting ? (
              <div className="mt-3 space-y-2">
                <textarea
                  value={confirmComment}
                  onChange={(event) => setConfirmComment(event.target.value)}
                  rows={2}
                  placeholder="填写驳回原因（必填）"
                  className="w-full rounded-md border border-slate-700 bg-slate-950/80 px-3 py-2 text-xs text-slate-200 outline-none focus:border-amber-700"
                />
                <div className="flex justify-end gap-2">
                  <button
                    type="button"
                    onClick={() => {
                      setConfirmRejecting(false);
                      setConfirmComment("");
                      setConfirmError(null);
                    }}
                    className="rounded-md border border-slate-700 px-3 py-1.5 text-[11px] text-slate-300"
                  >
                    返回
                  </button>
                  <button
                    type="button"
                    disabled={confirmBusy || !confirmComment.trim()}
                    onClick={() => void handleConfirmDecision("rejected")}
                    className="rounded-md border border-red-800 bg-red-950/40 px-3 py-1.5 text-[11px] font-medium text-red-300 disabled:cursor-not-allowed disabled:opacity-50"
                  >
                    {confirmBusy ? "提交中…" : "确认驳回"}
                  </button>
                </div>
              </div>
            ) : (
              <div className="mt-4 flex justify-end gap-2">
                <button
                  type="button"
                  disabled={confirmBusy}
                  onClick={() => {
                    setPendingConfirm(null);
                    setConfirmError(null);
                  }}
                  className="rounded-md border border-slate-700 px-3 py-1.5 text-[11px] text-slate-400 hover:text-slate-200"
                >
                  取消
                </button>
                <button
                  type="button"
                  disabled={confirmBusy}
                  onClick={() => setConfirmRejecting(true)}
                  className="rounded-md border border-red-800/70 px-3 py-1.5 text-[11px] text-red-300 hover:bg-red-950/30"
                >
                  驳回
                </button>
                <button
                  type="button"
                  disabled={confirmBusy}
                  onClick={() => void handleConfirmDecision("approved")}
                  className="rounded-md bg-indigo-500 px-3 py-1.5 text-[11px] font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
                >
                  {confirmBusy ? "处理中…" : "确认继续"}
                </button>
              </div>
            )}

            {confirmError && (
              <p className="mt-2 text-[11px] text-red-400">{confirmError}</p>
            )}
          </div>
        </div>
      )}

      {debug && showTrace && (
        <TracePanel spans={traceSpans} onClose={() => setShowTrace(false)} />
      )}
    </div>
  );
}

/** 外层按 sessionId 重挂载：useChat 的初始 messages 只在挂载时生效 */
export function AgentChatPanel({
  sessionId,
  title,
  agentEnabled,
  onTaskBoardSnapshot,
  onStreamingChange,
  headerAction,
  taskId,
  onTaskStart,
}: AgentChatPanelProps) {
  return (
    // agentEnabled 必须透传：丢弃会让服务端永远收到 false，开关打开也提示「未启用」
    <AgentChatPanelInner
      key={sessionId}
      sessionId={sessionId}
      title={title}
      agentEnabled={agentEnabled}
      onTaskBoardSnapshot={onTaskBoardSnapshot}
      onStreamingChange={onStreamingChange}
      headerAction={headerAction}
      taskId={taskId}
      onTaskStart={onTaskStart}
    />
  );
}

export default AgentChatPanel;
