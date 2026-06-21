"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { getCompressorAdapter } from "@/lib/compressor-adapter";
import type {
  CompressResult,
  DecisionNode,
  ConflictDetection,
  NextStepSuggestion,
  InferenceResult,
  SessionMeta,
  SessionData,
} from "@/lib/compressor-adapter";

// ==================== Props ====================

export interface CompressionMessage {
  role: string;
  content: string;
  chain?: string[];
  intent?: string;
  timestamp?: number;
  [key: string]: unknown;
}

export interface GraphContextCompressionPanelProps {
  messages: CompressionMessage[];
  sessionId?: string;
  onClose?: () => void;
  defaultOpen?: boolean;
  compactMode?: boolean;
  onSessionLoaded?: (messages: CompressionMessage[]) => void;
  onCompressionUpdate?: (stats: CompressResult["stats"] | null) => void;
}

// ==================== 主题色常量 ====================
// 腾讯云控制台深色主题：#0d0d0d bg / #1a1a1a panels / #e0e0e0 text

const COLORS = {
  bg: "#0d0d0d",
  panel: "#1a1a1a",
  border: "#2a2a2a",
  borderLight: "#333333",
  textPrimary: "#e0e0e0",
  textSecondary: "#8a8a8a",
  textTertiary: "#5a5a5a",
  accent: "#00a4ff",
  retained: "#10b981",
  compressed: "#6b7280",
  conflict: "#ef4444",
  suggestion: "#3b82f6",
  blueprint: "#8b5cf6",
  architecture: "#f59e0b",
  chronicle: "#0ea5e9",
  warning: "#f97316",
};

// ==================== 工具函数 ====================

function formatTime(ts?: number): string {
  if (!ts) return "--:--:--";
  const d = new Date(ts);
  const hh = String(d.getHours()).padStart(2, "0");
  const mm = String(d.getMinutes()).padStart(2, "0");
  const ss = String(d.getSeconds()).padStart(2, "0");
  return `${hh}:${mm}:${ss}`;
}

function formatDate(ts: number): string {
  const d = new Date(ts);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function truncate(s: string, maxLen: number): string {
  if (!s) return "";
  return s.length > maxLen ? s.slice(0, maxLen) + "…" : s;
}

function detectIntentFromMessages(
  messages: CompressionMessage[]
): string {
  const lastIntent = [...messages].reverse().find((m) => m.intent)?.intent;
  if (lastIntent) return lastIntent;
  if (messages.length === 0) return "idle";
  const txt = (messages[0].content || "").toLowerCase();
  if (txt.includes("调研") || txt.includes("research") || txt.includes("搜索"))
    return "research";
  if (txt.includes("分析") || txt.includes("analysis") || txt.includes("趋势"))
    return "analysis";
  if (txt.includes("交易") || txt.includes("执行") || txt.includes("execute") || txt.includes("trade"))
    return "execute";
  if (txt.includes("验证") || txt.includes("validate")) return "validate";
  if (txt.includes("设计") || txt.includes("strategy") || txt.includes("方案"))
    return "design";
  return "general";
}

function getRiskColor(score: number): string {
  if (score < 0.3) return COLORS.retained;
  if (score < 0.55) return COLORS.architecture;
  if (score < 0.8) return COLORS.warning;
  return COLORS.conflict;
}

// ==================== Mock 数据构建器（Adapter 不可用时回退）====================

function buildMockCompressResult(messages: CompressionMessage[]): CompressResult {
  const total = messages.length;
  const compressedNodes = Math.floor(total * 0.4);
  const retainedNodes = total - compressedNodes;
  const ratio = total === 0 ? 1 : retainedNodes / total;
  const originalTokens = messages.reduce(
    (sum, m) => sum + Math.max(10, Math.floor(String(m.content ?? "").length / 2)),
    0
  );
  return {
    graph: { edges: [] },
    originalTokens,
    compressedTokens: Math.floor(originalTokens * ratio),
    compressionRatio: ratio,
    stats: {
      totalNodes: total,
      totalEdges: 0,
      byLevel: { B: 2, A: 6, C: Math.min(total, 6) },
      retainedNodes,
      compressedNodes,
    },
  };
}

function buildMockInference(
  messages: CompressionMessage[],
  sessionId: string
): InferenceResult {
  const now = Date.now();
  const count = messages.length;
  const sampleContent = messages
    .map((m) => (typeof m.content === "string" ? m.content : ""))
    .join(" ");

  const nodes: DecisionNode[] = [];
  if (count > 0) {
    nodes.push({
      id: "d-goal",
      name: "业务目标",
      type: "goal",
      description: "从首条消息提取的核心目标",
      weight: 0.9,
      confidence: 0.8,
      sourceMessageIds: ["msg-0"],
      createdAt: now,
    });
  }
  if (count > 1) {
    nodes.push({
      id: "d-constraint",
      name: "资源约束",
      type: "constraint",
      description: "从上下文识别的约束条件",
      weight: 0.7,
      confidence: 0.65,
      sourceMessageIds: ["msg-1"],
      createdAt: now,
    });
  }
  nodes.push(
    {
      id: "d-action",
      name: "执行动作",
      type: "action",
      description: "建议执行的操作",
      weight: 0.6,
      confidence: 0.55,
      sourceMessageIds: [],
      createdAt: now,
    },
    {
      id: "d-choice",
      name: "方案选择",
      type: "choice",
      description: "可选方案权衡点",
      weight: 0.55,
      confidence: 0.5,
      sourceMessageIds: [],
      createdAt: now,
    },
    {
      id: "d-tradeoff",
      name: "权衡节点",
      type: "tradeoff",
      description: "成本/收益权衡",
      weight: 0.5,
      confidence: 0.45,
      sourceMessageIds: [],
      createdAt: now,
    }
  );

  const conflicts: ConflictDetection[] =
    count >= 3 && sampleContent.length > 100
      ? [
          {
            id: "c-1",
            type: "inconsistency",
            severity: "low",
            description: "前后消息存在轻微语义差异",
            involvedNodes: ["d-goal", "d-action"],
            suggestion: "建议核对目标与执行动作的一致性",
            detectedAt: now,
          },
        ]
      : [];

  const riskScore = Math.min(
    1,
    0.15 + conflicts.length * 0.2 + (count === 0 ? 0.25 : 0)
  );
  const riskLevel: "low" | "medium" | "high" | "critical" =
    riskScore < 0.3
      ? "low"
      : riskScore < 0.55
      ? "medium"
      : riskScore < 0.8
      ? "high"
      : "critical";

  return {
    sessionId,
    analyzedAt: now,
    keyDecisionNodes: nodes,
    keyReasoningPaths: [
      {
        id: "path-main",
        name: "主推理路径",
        nodeIds: nodes.map((n) => n.id),
        rationale: "基于目标→约束→动作的主推理链",
        confidence: 0.75,
        priority: "high",
      },
    ],
    conflicts,
    riskScore,
    riskLevel,
    nextSteps: [
      {
        id: "ns-1",
        title: "明确关键约束",
        description: "补充约束条件以降低不确定性，提升决策置信度",
        action: "ask-clarify",
        priority: riskScore > 0.5 ? "high" : "medium",
        estimatedTokens: 120,
      },
      {
        id: "ns-2",
        title: "验证执行路径",
        description: "对主推理路径做一次校验，确认可行性",
        action: "validate",
        priority: "medium",
        estimatedTokens: 80,
      },
      {
        id: "ns-3",
        title: "探索替代方案",
        description: "当风险较高时，识别并评估备选方案",
        action: "explore-alternative",
        priority: riskScore > 0.6 ? "high" : "low",
        estimatedTokens: 200,
      },
    ],
    summary:
      count === 0
        ? "当前无消息输入，建议提供初始请求以生成完整推理分析。"
        : `已分析 ${count} 条消息，识别 ${nodes.length} 个关键决策节点，检测到 ${conflicts.length} 个冲突，风险等级 ${riskLevel.toUpperCase()}。`,
    metadata: {
      messageCount: count,
      inferenceTokens: count * 60,
      analysisDurationMs: 50 + count * 5,
      mode: "fallback",
    },
  };
}

// ==================== 三层图节点构建 ====================

interface LayerNode {
  id: string;
  name: string;
  retained: boolean;
  summary?: string;
  meta?: Record<string, unknown>;
}

interface GraphLayers {
  blueprint: LayerNode[];
  architecture: LayerNode[];
  chronicle: LayerNode[];
}

function buildThreeLayerView(
  messages: CompressionMessage[],
  compressResult: CompressResult | null,
  intent: string
): GraphLayers {
  const blueprintNodes: LayerNode[] = [];
  blueprintNodes.push({
    id: "bp-intent",
    name: `意图: ${intent}`,
    retained: true,
    summary: "从消息内容识别的顶层业务意图",
  });
  if (messages.length > 0) {
    const first = messages[0];
    blueprintNodes.push({
      id: "bp-goal",
      name:
        "目标: " +
        truncate(
          typeof first.content === "string"
            ? first.content
            : JSON.stringify(first.content),
          32
        ),
      retained: true,
      summary: "用户最初提出的目标/请求",
    });
  }
  if (messages.length > 3) {
    blueprintNodes.push({
      id: "bp-constraint",
      name: "约束识别",
      retained: true,
      summary: "从上下文推断的约束条件",
    });
  }

  const S_STEPS = [
    "S0_DIRECT_ANSWER",
    "S1_RESEARCH",
    "S2_ANALYSIS",
    "S3_DESIGN",
    "S4_VALIDATE",
    "S5_EXECUTE",
  ];
  const chainSet = new Set<string>();
  for (const m of messages) {
    if (m.chain && Array.isArray(m.chain)) {
      for (const c of m.chain) chainSet.add(c);
    }
  }
  const architectureNodes: LayerNode[] = S_STEPS.map((step, i) => {
    const compressed = compressResult
      ? !!(
          compressResult.stats.compressedNodes > 0 &&
          i % 2 === 1 &&
          step !== "S1_RESEARCH" &&
          step !== "S5_EXECUTE"
        )
      : !chainSet.has(step);
    return {
      id: step,
      name: step,
      retained: !compressed,
      summary: compressed ? "已压缩（摘要保留）" : "关键执行节点",
      meta: { status: chainSet.has(step) ? "used" : "planned" },
    };
  });

  const chronicleNodes: LayerNode[] = messages
    .filter((_, i) => i === 0 || i === messages.length - 1 || i % 3 === 1)
    .map((m, idx) => ({
      id: `chronicle-${idx}`,
      name: truncate(
        typeof m.content === "string" ? m.content : JSON.stringify(m.content),
        28
      ),
      retained: idx % 2 === 0,
      summary: `时间戳 ${formatTime(m.timestamp)}`,
      meta: { timestamp: m.timestamp },
    }))
    .slice(0, 8);

  if (compressResult?.graph) {
    const g = compressResult.graph as unknown as {
      blueprint?: { id: string; name?: string; compressed?: boolean; summary?: string; meta?: Record<string, unknown> }[];
      architecture?: { id: string; name?: string; compressed?: boolean; summary?: string; meta?: Record<string, unknown> }[];
      chronicle?: { id: string; name?: string; compressed?: boolean; summary?: string; meta?: Record<string, unknown> }[];
    };
    if (Array.isArray(g.blueprint) && g.blueprint.length > 0) {
      for (const n of g.blueprint.slice(0, 4)) {
        blueprintNodes.push({
          id: n.id,
          name: n.name || n.id,
          retained: !n.compressed,
          summary: n.summary,
          meta: n.meta,
        });
      }
    }
    if (Array.isArray(g.architecture) && g.architecture.length > 0) {
      for (const n of g.architecture.slice(0, 6)) {
        architectureNodes.push({
          id: n.id,
          name: n.name || n.id,
          retained: !n.compressed,
          summary: n.summary,
          meta: n.meta,
        });
      }
    }
    if (Array.isArray(g.chronicle) && g.chronicle.length > 0) {
      for (const n of g.chronicle.slice(0, 6)) {
        chronicleNodes.push({
          id: n.id,
          name: n.name || n.id,
          retained: !n.compressed,
          summary: n.summary,
          meta: n.meta,
        });
      }
    }
  }

  return { blueprint: blueprintNodes, architecture: architectureNodes, chronicle: chronicleNodes };
}

// ==================== 时间线构建 ====================

interface TimelineRow {
  id: string;
  index: number;
  content: string;
  timestamp?: number;
  role: string;
  retained: boolean;
  meta?: string;
}

function buildTimeline(
  messages: CompressionMessage[],
  compressResult: CompressResult | null
): TimelineRow[] {
  const compressedSet = new Set<number>();
  if (compressResult?.stats?.compressedNodes && messages.length > 0) {
    for (let i = 1; i < messages.length - 1; i++) {
      if (i % 3 === 1) compressedSet.add(i);
    }
  }
  return messages.map((m, i) => ({
    id: `t-${i}`,
    index: i,
    content: typeof m.content === "string" ? m.content : JSON.stringify(m.content),
    timestamp: m.timestamp,
    role: m.role || "user",
    retained: !compressedSet.has(i),
    meta:
      m.chain && m.chain.length > 0
        ? `链: ${m.chain.slice(0, 2).join(", ")}`
        : m.intent
        ? `意图: ${m.intent}`
        : undefined,
  }));
}

// ==================== 主组件 ====================

export function GraphContextCompressionPanel(props: GraphContextCompressionPanelProps) {
  const {
    messages,
    sessionId: incomingSessionId,
    onClose,
    defaultOpen = true,
    compactMode = false,
    onSessionLoaded,
    onCompressionUpdate,
  } = props;

  // Adapter 懒引用
  const adapterRef = useRef<ReturnType<typeof getCompressorAdapter> | null>(null);
  if (!adapterRef.current) {
    try {
      adapterRef.current = getCompressorAdapter();
    } catch {
      adapterRef.current = null;
    }
  }

  const [derivedSessionId] = useState<string>(
    incomingSessionId || "session-" + Math.random().toString(36).slice(2, 8)
  );
  const [isOpen, setIsOpen] = useState<boolean>(defaultOpen);
  const [loading, setLoading] = useState<boolean>(false);
  const [autoRefresh, setAutoRefresh] = useState<boolean>(false);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<number>(Date.now());
  const [statusMessage, setStatusMessage] = useState<string>("初始化中…");

  const [compressResult, setCompressResult] = useState<CompressResult | null>(null);
  const [inferenceResult, setInferenceResult] = useState<InferenceResult | null>(null);
  const [sessionList, setSessionList] = useState<SessionMeta[]>([]);
  const [selectedSessionId, setSelectedSessionId] = useState<string>("");

  const [expandedSections, setExpandedSections] = useState<Record<string, boolean>>({
    graph: true,
    inference: true,
    session: false,
    timeline: !compactMode,
  });

  // --- 派生数据 ---
  const messageCount = messages.length;
  const intent = useMemo(() => detectIntentFromMessages(messages), [messages]);

  const stats = useMemo(() => {
    const compressedNodes =
      compressResult?.stats?.compressedNodes ?? Math.floor(messageCount * 0.4);
    const retainedNodes =
      compressResult?.stats?.retainedNodes ?? messageCount - compressedNodes;
    const total = Math.max(messageCount, compressedNodes + retainedNodes);
    const ratio = compressResult?.compressionRatio ?? (total === 0 ? 1 : retainedNodes / total);
    const riskScore = inferenceResult?.riskScore ?? 0.2;
    return {
      total,
      compressed: compressedNodes,
      retained: retainedNodes,
      ratio,
      riskScore,
      riskLevel: inferenceResult?.riskLevel ?? "low",
      originalTokens: compressResult?.originalTokens ?? 0,
      compressedTokens: compressResult?.compressedTokens ?? 0,
    };
  }, [compressResult, inferenceResult, messageCount]);

  const graphLayers = useMemo(
    () => buildThreeLayerView(messages, compressResult, intent),
    [messages, compressResult, intent]
  );

  const timelineItems = useMemo(
    () => buildTimeline(messages, compressResult),
    [messages, compressResult]
  );

  // --- 分析动作 ---
  const runAnalysis = useCallback(async () => {
    if (!adapterRef.current) {
      setInferenceResult(buildMockInference(messages, derivedSessionId));
      setCompressResult(buildMockCompressResult(messages));
      setLastUpdatedAt(Date.now());
      setStatusMessage("本地分析完成");
      return;
    }
    setLoading(true);
    setStatusMessage("分析中…");
    try {
      const [compressR, inferenceR] = await Promise.all([
        adapterRef.current.compress({
          sessionId: derivedSessionId,
          payload: messages.map((m, i) => ({
            id: `msg-${i}`,
            type: "message",
            content:
              typeof m.content === "string" ? m.content : JSON.stringify(m.content),
            timestamp: m.timestamp ?? Date.now() + i,
          })),
        }),
        adapterRef.current.analyzeFromMessages?.(messages) ??
          Promise.resolve(buildMockInference(messages, derivedSessionId)),
      ]);
      setCompressResult(compressR);
      setInferenceResult(inferenceR as InferenceResult);
      setLastUpdatedAt(Date.now());
      setStatusMessage("分析完成");
      if (onCompressionUpdate) onCompressionUpdate(compressR.stats);
    } catch (err) {
      console.warn("[GraphContextCompressionPanel] 分析失败，使用本地模式", err);
      setInferenceResult(buildMockInference(messages, derivedSessionId));
      setCompressResult(buildMockCompressResult(messages));
      setLastUpdatedAt(Date.now());
      setStatusMessage("本地分析模式");
    } finally {
      setLoading(false);
    }
  }, [messages, derivedSessionId, onCompressionUpdate]);

  // --- 会话列表 ---
  const refreshSessionList = useCallback(async () => {
    if (!adapterRef.current) {
      setSessionList([]);
      return;
    }
    try {
      if (typeof (adapterRef.current as unknown as { listSessionMetas?: () => Promise<SessionMeta[]> }).listSessionMetas === "function") {
        const metas = await (adapterRef.current as unknown as { listSessionMetas: () => Promise<SessionMeta[]> }).listSessionMetas();
        setSessionList(metas);
      } else {
        const ids = await adapterRef.current.listSessions();
        const metas: SessionMeta[] = [];
        for (const id of ids) {
          const data = (await adapterRef.current.loadSession(id)) as SessionData | null;
          if (!data) continue;
          metas.push({
            sessionId: data.sessionId,
            title: data.title ?? data.sessionId,
            createdAt: data.createdAt ?? Date.now(),
            updatedAt: data.updatedAt ?? Date.now(),
            messageCount: Array.isArray(data.messages) ? data.messages.length : 0,
            tokenEstimate: Array.isArray(data.messages)
              ? data.messages.reduce(
                  (sum: number, m: unknown) =>
                    sum +
                    Math.max(
                      10,
                      Math.floor(
                        String(
                          typeof (m as { content?: unknown }).content === "string"
                            ? (m as { content: string }).content
                            : JSON.stringify((m as { content?: unknown }).content ?? "")
                        ).length / 2
                      )
                    ),
                  0
                )
              : 0,
          });
        }
        setSessionList(metas);
      }
    } catch {
      setSessionList([]);
    }
  }, []);

  const saveCurrentSession = useCallback(async () => {
    if (!adapterRef.current) return;
    setStatusMessage("保存会话…");
    const ok = await adapterRef.current.saveSession(derivedSessionId, {
      title: `会话 · ${formatDate(Date.now())}`,
      messages,
      graphSnapshot: compressResult?.graph
        ? {
            blueprint:
              (compressResult.graph as unknown as { blueprint?: unknown[] }).blueprint ?? [],
            architecture:
              (compressResult.graph as unknown as { architecture?: unknown[] }).architecture ??
              [],
            chronicle:
              (compressResult.graph as unknown as { chronicle?: unknown[] }).chronicle ?? [],
          }
        : undefined,
      inferenceSnapshot: inferenceResult ?? undefined,
      createdAt: Date.now(),
      updatedAt: Date.now(),
      sessionId: derivedSessionId,
    });
    setStatusMessage(ok ? "已保存" : "保存失败");
    if (ok) refreshSessionList();
  }, [adapterRef, derivedSessionId, messages, compressResult, inferenceResult, refreshSessionList]);

  const loadSession = useCallback(
    async (sid: string) => {
      if (!adapterRef.current) return;
      setStatusMessage("加载会话…");
      const data = (await adapterRef.current.loadSession(sid)) as SessionData | null;
      if (data && Array.isArray(data.messages)) {
        setSelectedSessionId(sid);
        if (onSessionLoaded) {
          onSessionLoaded(
            data.messages.map((m: unknown) => ({
              role: String((m as { role?: string }).role ?? "user"),
              content:
                typeof (m as { content?: string }).content === "string"
                  ? ((m as { content: string }).content as string)
                  : JSON.stringify(m),
              timestamp: (m as { timestamp?: number }).timestamp,
              intent: (m as { intent?: string }).intent,
              chain: (m as { chain?: string[] }).chain,
            }))
          );
        }
        setStatusMessage("已加载：" + (data.title ?? sid));
      } else {
        setStatusMessage("加载失败");
      }
    },
    [adapterRef, onSessionLoaded]
  );

  const deleteSession = useCallback(
    async (sid: string) => {
      if (!adapterRef.current) return;
      const ok = await adapterRef.current.deleteSession(sid);
      setStatusMessage(ok ? "已删除" : "删除失败");
      if (ok) {
        refreshSessionList();
        if (selectedSessionId === sid) setSelectedSessionId("");
      }
    },
    [adapterRef, selectedSessionId, refreshSessionList]
  );

  // --- 初始化 + 消息变更自动分析 ---
  useEffect(() => {
    const init = async () => {
      await runAnalysis();
      await refreshSessionList();
    };
    init();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (autoRefresh) {
      const t = setTimeout(() => runAnalysis(), 500);
      return () => clearTimeout(t);
    }
    return;
  }, [messages, autoRefresh, runAnalysis]);

  // --- 折叠/展开 ---
  const toggleSection = (key: string) =>
    setExpandedSections((s) => ({ ...s, [key]: !s[key] }));

  // --- 渲染 ---
  if (!isOpen) {
    return (
      <div
        className="rounded-md border px-4 py-2 text-sm text-center flex items-center justify-between"
        style={{
          background: COLORS.panel,
          borderColor: COLORS.border,
          color: COLORS.textPrimary,
        }}
      >
        <span className="flex items-center gap-2">
          <span style={{ color: COLORS.accent }}>◈</span>
          <span>图结构上下文压缩面板</span>
          <span className="text-xs" style={{ color: COLORS.textSecondary }}>
            · {messageCount} 条消息 · 保留 {stats.retained} · 压缩 {stats.compressed}
          </span>
        </span>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setIsOpen(true)}
            className="text-xs hover:underline"
            style={{ color: COLORS.accent }}
          >
            展开 ▼
          </button>
          {onClose && (
            <button
              onClick={onClose}
              className="text-xs hover:underline"
              style={{ color: COLORS.textSecondary }}
            >
              关闭
            </button>
          )}
        </div>
      </div>
    );
  }

  return (
    <div
      className={compactMode ? "rounded-md" : "rounded-lg"}
      style={{
        background: COLORS.bg,
        color: COLORS.textPrimary,
        border: `1px solid ${COLORS.border}`,
        fontSize: compactMode ? 12 : 13,
        fontFamily:
          '-apple-system, BlinkMacSystemFont, "Segoe UI", "PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", sans-serif',
      }}
    >
      {/* ============ 顶部摘要栏 ============ */}
      <SummaryHeader
        sessionId={derivedSessionId}
        messageCount={messageCount}
        stats={stats}
        intent={intent}
        loading={loading}
        autoRefresh={autoRefresh}
        lastUpdatedAt={lastUpdatedAt}
        statusMessage={statusMessage}
        onToggleAutoRefresh={() => setAutoRefresh((v) => !v)}
        onManualRefresh={runAnalysis}
        onCollapse={() => setIsOpen(false)}
        onClose={onClose}
      />

      {/* ============ 主内容区 ============ */}
      <div style={{ padding: compactMode ? 10 : 14 }}>
        {/* 三层图架构 */}
        <Section
          title="全局图结构 · B / A / C 三层架构"
          subtitle={`Blueprint ${graphLayers.blueprint.length} · Architecture ${graphLayers.architecture.length} · Chronicle ${graphLayers.chronicle.length}`}
          color={COLORS.blueprint}
          expanded={expandedSections.graph}
          onToggle={() => toggleSection("graph")}
          compact={compactMode}
        >
          <ThreeLayerGraph layers={graphLayers} compact={compactMode} />
        </Section>

        {/* 推理引擎分析 */}
        <Section
          title="推理引擎分析"
          subtitle={
            inferenceResult
              ? `${inferenceResult.keyDecisionNodes?.length ?? 0} 决策节点 · ${inferenceResult.conflicts?.length ?? 0} 冲突 · 风险 ${(inferenceResult.riskScore * 100).toFixed(0)}`
              : "分析中…"
          }
          color={COLORS.suggestion}
          expanded={expandedSections.inference}
          onToggle={() => toggleSection("inference")}
          compact={compactMode}
        >
          <InferencePanel inference={inferenceResult} messagesCount={messageCount} />
        </Section>

        {/* 时间线 */}
        <Section
          title="消息时间线"
          subtitle={`${timelineItems.length} 条消息 · 保留 ${timelineItems.filter((i) => i.retained).length} · 压缩 ${timelineItems.filter((i) => !i.retained).length}`}
          color={COLORS.chronicle}
          expanded={expandedSections.timeline}
          onToggle={() => toggleSection("timeline")}
          compact={compactMode}
        >
          <TimelinePanel items={timelineItems} compact={compactMode} />
        </Section>

        {/* 会话持久化管理 */}
        <Section
          title="会话持久化管理"
          subtitle={`${sessionList.length} 个已保存会话`}
          color={COLORS.architecture}
          expanded={expandedSections.session}
          onToggle={() => {
            toggleSection("session");
            if (!expandedSections.session) refreshSessionList();
          }}
          compact={compactMode}
        >
          <SessionPanel
            sessionId={derivedSessionId}
            sessionList={sessionList}
            selectedSessionId={selectedSessionId}
            onSave={saveCurrentSession}
            onLoad={loadSession}
            onDelete={deleteSession}
            onRefresh={refreshSessionList}
          />
        </Section>
      </div>
    </div>
  );
}

// ==================== 顶部摘要栏 ====================

interface SummaryHeaderProps {
  sessionId: string;
  messageCount: number;
  stats: {
    total: number;
    compressed: number;
    retained: number;
    ratio: number;
    riskScore: number;
    riskLevel: string;
    originalTokens: number;
    compressedTokens: number;
  };
  intent: string;
  loading: boolean;
  autoRefresh: boolean;
  lastUpdatedAt: number;
  statusMessage: string;
  onToggleAutoRefresh: () => void;
  onManualRefresh: () => void;
  onCollapse: () => void;
  onClose?: () => void;
}

function SummaryHeader(p: SummaryHeaderProps) {
  const ratioPct = Math.round((1 - p.stats.ratio) * 100);
  const riskColor = getRiskColor(p.stats.riskScore);

  return (
    <div
      style={{
        padding: "10px 14px",
        borderBottom: `1px solid ${COLORS.border}`,
        background: COLORS.panel,
      }}
    >
      <div className="flex flex-wrap items-center gap-2 md:gap-3">
        <StatPill label="会话" value={truncate(p.sessionId, 10)} color={COLORS.blueprint} />
        <StatPill label="消息" value={String(p.messageCount)} color={COLORS.textPrimary} />
        <StatPill
          label="保留"
          value={String(p.stats.retained)}
          color={COLORS.retained}
        />
        <StatPill
          label="压缩"
          value={String(p.stats.compressed)}
          color={COLORS.compressed}
        />
        <StatPill
          label="压缩率"
          value={`${ratioPct}%`}
          color={COLORS.accent}
        />
        <StatPill
          label="风险"
          value={`${(p.stats.riskScore * 100).toFixed(0)} · ${p.stats.riskLevel.toUpperCase()}`}
          color={riskColor}
        />
        <StatPill label="意图" value={p.intent} color={COLORS.architecture} />

        <div className="flex-1 min-w-[40px]" />

        <button
          onClick={p.onToggleAutoRefresh}
          className="text-xs px-2.5 py-1 rounded transition-colors"
          style={{
            background: p.autoRefresh ? COLORS.retained + "20" : COLORS.bg,
            color: p.autoRefresh ? COLORS.retained : COLORS.textSecondary,
            border: `1px solid ${p.autoRefresh ? COLORS.retained : COLORS.border}`,
          }}
        >
          {p.autoRefresh ? "● 自动刷新" : "○ 自动刷新"}
        </button>
        <button
          onClick={p.onManualRefresh}
          disabled={p.loading}
          className="text-xs px-3 py-1 rounded transition-colors"
          style={{
            background: COLORS.bg,
            color: p.loading ? COLORS.compressed : COLORS.textPrimary,
            border: `1px solid ${COLORS.border}`,
            cursor: p.loading ? "not-allowed" : "pointer",
          }}
        >
          {p.loading ? "分析中…" : "⟳ 手动分析"}
        </button>
        <button
          onClick={p.onCollapse}
          className="text-xs px-2 py-1 rounded"
          style={{
            color: COLORS.textSecondary,
            border: `1px solid ${COLORS.border}`,
            background: COLORS.bg,
          }}
        >
          ▲
        </button>
        {p.onClose && (
          <button
            onClick={p.onClose}
            className="text-xs px-2 py-1 rounded"
            style={{
              color: COLORS.conflict,
              border: `1px solid ${COLORS.conflict + "60"}`,
              background: COLORS.conflict + "10",
            }}
          >
            关闭
          </button>
        )}
      </div>
      <div
        className="mt-1.5 flex items-center gap-2 text-[11px]"
        style={{ color: COLORS.textSecondary }}
      >
        <span>{p.statusMessage}</span>
        <span>·</span>
        <span>更新于 {formatTime(p.lastUpdatedAt)}</span>
        {p.stats.originalTokens > 0 && (
          <>
            <span>·</span>
            <span>
              tokens: {p.stats.originalTokens} → {p.stats.compressedTokens}
            </span>
          </>
        )}
      </div>
    </div>
  );
}

function StatPill({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div
      className="flex flex-col px-2.5 py-1 rounded"
      style={{
        background: COLORS.bg,
        border: `1px solid ${COLORS.border}`,
        minWidth: 60,
        lineHeight: 1.15,
      }}
    >
      <span className="text-[10px] uppercase tracking-wide" style={{ color: COLORS.textSecondary }}>
        {label}
      </span>
      <span className="text-xs font-semibold" style={{ color }}>
        {value}
      </span>
    </div>
  );
}

// ==================== 可折叠 Section ====================

interface SectionProps {
  title: string;
  subtitle?: string;
  color: string;
  expanded: boolean;
  onToggle: () => void;
  compact?: boolean;
  children: React.ReactNode;
}

function Section({ title, subtitle, color, expanded, onToggle, compact, children }: SectionProps) {
  return (
    <div
      className="mb-2.5"
      style={{
        border: `1px solid ${COLORS.border}`,
        borderRadius: 6,
        background: COLORS.panel,
        overflow: "hidden",
      }}
    >
      <div
        onClick={onToggle}
        className="flex items-center gap-2 cursor-pointer select-none hover:opacity-90 transition-opacity"
        style={{
          padding: compact ? "6px 10px" : "8px 12px",
          background: COLORS.bg,
          borderBottom: expanded ? `1px solid ${COLORS.border}` : "none",
        }}
      >
        <span style={{ color, fontSize: 10, letterSpacing: 1 }}>▍</span>
        <span className="text-xs font-semibold" style={{ color: COLORS.textPrimary }}>
          {title}
        </span>
        {subtitle && (
          <span className="text-[11px]" style={{ color: COLORS.textSecondary }}>
            — {subtitle}
          </span>
        )}
        <div className="flex-1" />
        <span className="text-[11px]" style={{ color: COLORS.textSecondary }}>
          {expanded ? "▼" : "▶"}
        </span>
      </div>
      {expanded && <div style={{ padding: compact ? 10 : 12 }}>{children}</div>}
    </div>
  );
}

// ==================== 三层图架构可视化 ====================

function ThreeLayerGraph({ layers, compact }: { layers: GraphLayers; compact?: boolean }) {
  return (
    <div className="flex flex-col gap-2.5">
      <LayerRow
        title="Blueprint · 顶层设计"
        description="意图 / 目标 / 约束"
        color={COLORS.blueprint}
        nodes={layers.blueprint}
        compact={compact}
      />
      <Connector color={COLORS.blueprint} />
      <LayerRow
        title="Architecture · 执行步骤"
        description="S0-S5 思维链"
        color={COLORS.architecture}
        nodes={layers.architecture}
        compact={compact}
      />
      <Connector color={COLORS.architecture} />
      <LayerRow
        title="Chronicle · 消息记录"
        description="关键消息节点"
        color={COLORS.chronicle}
        nodes={layers.chronicle}
        compact={compact}
      />
    </div>
  );
}

function Connector({ color }: { color: string }) {
  return (
    <div className="flex items-center gap-2 pl-1">
      <span style={{ color, fontSize: 9 }}>↓</span>
      <div
        className="flex-1"
        style={{ height: 1, background: `linear-gradient(to right, ${color}40, transparent)` }}
      />
    </div>
  );
}

function LayerRow({
  title,
  description,
  color,
  nodes,
  compact,
}: {
  title: string;
  description: string;
  color: string;
  nodes: LayerNode[];
  compact?: boolean;
}) {
  const retainedCount = nodes.filter((n) => n.retained).length;
  return (
    <div
      className="flex gap-3 items-start"
      style={{
        padding: compact ? 6 : 8,
        border: `1px solid ${color}30`,
        borderRadius: 4,
        background: color + "06",
      }}
    >
      <div
        className="flex-shrink-0"
        style={{
          width: compact ? 110 : 130,
          paddingRight: 10,
          borderRight: `1px solid ${color}30`,
        }}
      >
        <div className="text-xs font-semibold mb-0.5" style={{ color }}>
          {title}
        </div>
        <div className="text-[10px]" style={{ color: COLORS.textSecondary }}>
          {description}
        </div>
        <div className="text-[10px] mt-1" style={{ color: COLORS.textTertiary }}>
          {retainedCount}/{nodes.length} 保留
        </div>
      </div>
      <div className="flex flex-wrap gap-1.5 flex-1">
        {nodes.length === 0 ? (
          <div className="text-[11px] italic" style={{ color: COLORS.textSecondary }}>
            （无节点）
          </div>
        ) : (
          nodes.map((n) => <NodeCard key={n.id} node={n} color={color} compact={compact} />)
        )}
      </div>
    </div>
  );
}

function NodeCard({
  node,
  color,
  compact,
}: {
  node: LayerNode;
  color: string;
  compact?: boolean;
}) {
  return (
    <div
      title={node.summary || node.name}
      className="rounded transition-opacity"
      style={{
        padding: compact ? "2px 8px" : "3px 10px",
        border: `1px solid ${node.retained ? color + "60" : COLORS.border}`,
        background: node.retained ? color + "14" : COLORS.bg,
        color: node.retained ? COLORS.textPrimary : COLORS.compressed,
        fontSize: compact ? 11 : 11.5,
        whiteSpace: "nowrap",
        textDecoration: node.retained ? "none" : "line-through",
        opacity: node.retained ? 1 : 0.7,
      }}
    >
      <span style={{ marginRight: 4, fontSize: 9, color }}>{node.retained ? "●" : "○"}</span>
      {node.name}
    </div>
  );
}

// ==================== 推理引擎面板 ====================

function InferencePanel({
  inference,
  messagesCount,
}: {
  inference: InferenceResult | null;
  messagesCount: number;
}) {
  if (!inference) {
    return (
      <div className="text-[11px] italic" style={{ color: COLORS.textSecondary }}>
        分析中…
      </div>
    );
  }

  const topNodes: DecisionNode[] = [...(inference.keyDecisionNodes ?? [])]
    .sort((a, b) => (b.weight ?? 0) - (a.weight ?? 0))
    .slice(0, 5);
  const conflicts: ConflictDetection[] = inference.conflicts ?? [];
  const nextSteps: NextStepSuggestion[] = inference.nextSteps ?? [];
  const riskScore = inference.riskScore ?? 0;
  const riskPct = Math.round(riskScore * 100);
  const riskColor = getRiskColor(riskScore);

  return (
    <div className="flex flex-col gap-3">
      {/* 风险评分条 */}
      <div
        className="rounded"
        style={{
          padding: "8px 10px",
          border: `1px solid ${COLORS.border}`,
          background: COLORS.bg,
        }}
      >
        <div className="flex items-center gap-2 mb-1.5">
          <span className="text-[10px] uppercase tracking-wide" style={{ color: COLORS.textSecondary }}>
            风险评分
          </span>
          <span className="text-xs font-semibold" style={{ color: riskColor }}>
            {riskPct}/100 · {inference.riskLevel.toUpperCase()}
          </span>
          <div className="flex-1" />
          <span className="text-[10px]" style={{ color: COLORS.textSecondary }}>
            冲突 {conflicts.length} · 决策节点 {topNodes.length}
          </span>
        </div>
        <div
          className="w-full rounded overflow-hidden"
          style={{ height: 6, background: COLORS.panel, border: `1px solid ${COLORS.border}` }}
        >
          <div
            style={{
              width: `${riskPct}%`,
              height: "100%",
              background: `linear-gradient(to right, ${COLORS.retained}, ${COLORS.architecture}, ${COLORS.warning}, ${COLORS.conflict})`,
              transition: "width 0.3s",
            }}
          />
        </div>
      </div>

      {/* 关键决策节点 */}
      <SubPanel
        title={`关键决策节点 · Top ${topNodes.length}`}
        color={COLORS.retained}
      >
        {topNodes.length === 0 ? (
          <div className="text-[11px] italic" style={{ color: COLORS.textSecondary }}>
            无决策节点
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {topNodes.map((n) => (
              <div
                key={n.id}
                className="flex items-center gap-2 rounded"
                style={{
                  padding: "5px 8px",
                  border: `1px solid ${COLORS.border}`,
                  background: COLORS.bg,
                }}
              >
                <div
                  className="text-right flex-shrink-0"
                  style={{ width: 44, lineHeight: 1.1 }}
                >
                  <div className="text-xs font-semibold" style={{ color: COLORS.retained }}>
                    {Math.round((n.weight ?? 0) * 100)}
                  </div>
                  <div className="text-[9px]" style={{ color: COLORS.textTertiary }}>
                    权重
                  </div>
                </div>
                <div className="flex-1 min-w-0">
                  <div className="text-xs" style={{ color: COLORS.textPrimary }}>
                    <span className="font-semibold">{n.name || n.id}</span>
                    <span className="ml-1.5 text-[10px]" style={{ color: COLORS.textSecondary }}>
                      [{n.type}]
                    </span>
                  </div>
                  <div
                    className="text-[11px] truncate"
                    style={{ color: COLORS.textSecondary }}
                  >
                    {truncate(n.description || "", 90)}
                  </div>
                </div>
                <div
                  className="flex-shrink-0 rounded overflow-hidden"
                  style={{
                    width: 100,
                    height: 4,
                    background: COLORS.panel,
                    border: `1px solid ${COLORS.border}`,
                  }}
                >
                  <div
                    style={{
                      width: `${Math.round((n.weight ?? 0) * 100)}%`,
                      height: "100%",
                      background: COLORS.retained,
                    }}
                  />
                </div>
              </div>
            ))}
          </div>
        )}
      </SubPanel>

      {/* 冲突检测 */}
      <SubPanel
        title={`冲突检测 · ${conflicts.length}`}
        color={conflicts.length > 0 ? COLORS.conflict : COLORS.retained}
      >
        {conflicts.length === 0 ? (
          <div className="text-[11px]" style={{ color: COLORS.retained }}>
            ✓ 未检测到明显冲突
          </div>
        ) : (
          <div className="flex flex-col gap-1.5">
            {conflicts.map((c) => (
              <div
                key={c.id}
                className="rounded"
                style={{
                  padding: "6px 8px",
                  border: `1px solid ${COLORS.conflict}40`,
                  background: COLORS.conflict + "10",
                }}
              >
                <div className="text-xs font-semibold mb-0.5" style={{ color: COLORS.conflict }}>
                  ⚠ [{c.severity?.toUpperCase()}] {truncate(c.description || "", 70)}
                </div>
                {c.suggestion && (
                  <div className="text-[11px]" style={{ color: COLORS.textSecondary }}>
                    建议: {truncate(c.suggestion, 80)}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </SubPanel>

      {/* 下一步建议 */}
      <SubPanel title="下一步建议" color={COLORS.suggestion}>
        {nextSteps.length === 0 ? (
          <div className="text-[11px] italic" style={{ color: COLORS.textSecondary }}>
            暂无建议
          </div>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-2">
            {nextSteps.map((step, idx) => (
              <div
                key={step.id}
                className="rounded"
                style={{
                  padding: "8px 10px",
                  border: `1px solid ${COLORS.suggestion}40`,
                  background: COLORS.suggestion + "08",
                }}
              >
                <div className="text-xs font-semibold mb-1" style={{ color: COLORS.textPrimary }}>
                  {idx + 1}. {step.title || step.action}
                </div>
                <div className="text-[11px] mb-1.5 leading-snug" style={{ color: COLORS.textSecondary }}>
                  {truncate(step.description || "", 100)}
                </div>
                <div className="flex flex-wrap gap-2 text-[10px]" style={{ color: COLORS.textTertiary }}>
                  <span>类型: {step.action}</span>
                  {typeof step.estimatedTokens === "number" && (
                    <span>~{step.estimatedTokens} tokens</span>
                  )}
                  <span style={{ color: COLORS.suggestion }}>优先级: {step.priority}</span>
                </div>
              </div>
            ))}
          </div>
        )}
      </SubPanel>

      {/* 分析摘要 */}
      <SubPanel title="分析摘要" color={COLORS.textSecondary}>
        <div className="text-xs leading-relaxed" style={{ color: COLORS.textPrimary }}>
          {inference.summary || `已分析 ${messagesCount} 条消息。`}
        </div>
        {inference.metadata && (
          <div
            className="flex flex-wrap gap-3 mt-2 pt-2 text-[10px]"
            style={{
              color: COLORS.textSecondary,
              borderTop: `1px dashed ${COLORS.border}`,
            }}
          >
            <span>消息数: {inference.metadata.messageCount ?? messagesCount}</span>
            <span>tokens: {inference.metadata.inferenceTokens ?? "—"}</span>
            <span>耗时: {inference.metadata.analysisDurationMs ?? 0}ms</span>
            <span>模式: {inference.metadata.mode ?? "fallback"}</span>
          </div>
        )}
      </SubPanel>
    </div>
  );
}

function SubPanel({
  title,
  color,
  children,
}: {
  title: string;
  color: string;
  children: React.ReactNode;
}) {
  return (
    <div
      className="rounded"
      style={{
        border: `1px solid ${COLORS.border}`,
        background: COLORS.bg,
      }}
    >
      <div
        className="flex items-center gap-2"
        style={{
          padding: "5px 10px",
          borderBottom: `1px solid ${COLORS.border}`,
          fontSize: 11,
          fontWeight: 600,
          color,
        }}
      >
        <span style={{ fontSize: 9 }}>▍</span>
        {title}
      </div>
      <div style={{ padding: 8 }}>{children}</div>
    </div>
  );
}

// ==================== 会话持久化管理 ====================

interface SessionPanelProps {
  sessionId: string;
  sessionList: SessionMeta[];
  selectedSessionId: string;
  onSave: () => void;
  onLoad: (sid: string) => void;
  onDelete: (sid: string) => void;
  onRefresh: () => void;
}

function SessionPanel(p: SessionPanelProps) {
  return (
    <div className="flex flex-col gap-2.5">
      <div className="flex flex-wrap items-center gap-2">
        <ActionButton color={COLORS.retained} onClick={p.onSave}>
          💾 保存当前会话
        </ActionButton>
        <ActionButton color={COLORS.textSecondary} onClick={p.onRefresh}>
          ⟳ 刷新列表
        </ActionButton>
        <div className="flex-1" />
        <span className="text-[11px]" style={{ color: COLORS.textSecondary }}>
          当前: {truncate(p.sessionId, 16)}
        </span>
      </div>

      <div
        className="rounded overflow-hidden"
        style={{ border: `1px solid ${COLORS.border}`, background: COLORS.bg }}
      >
        {p.sessionList.length === 0 ? (
          <div
            className="text-center text-[11px] italic"
            style={{ padding: "16px 10px", color: COLORS.textSecondary }}
          >
            暂无已保存会话 · 点击「保存当前会话」创建第一条
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 11 }}>
              <thead>
                <tr style={{ background: COLORS.panel }}>
                  <Th>标题</Th>
                  <Th numeric>消息</Th>
                  <Th numeric>tokens</Th>
                  <Th numeric>更新时间</Th>
                  <Th numeric>操作</Th>
                </tr>
              </thead>
              <tbody>
                {p.sessionList.map((s) => (
                  <tr
                    key={s.sessionId}
                    style={{
                      borderTop: `1px solid ${COLORS.border}`,
                      background:
                        p.selectedSessionId === s.sessionId
                          ? COLORS.suggestion + "10"
                          : "transparent",
                    }}
                  >
                    <Td>
                      <div style={{ color: COLORS.textPrimary, fontWeight: 500 }}>
                        {truncate(s.title || s.sessionId, 40)}
                      </div>
                      <div className="text-[10px]" style={{ color: COLORS.textTertiary }}>
                        {truncate(s.sessionId, 24)}
                      </div>
                    </Td>
                    <Td numeric>{s.messageCount}</Td>
                    <Td numeric>{s.tokenEstimate}</Td>
                    <Td numeric>
                      <div>{formatDate(s.updatedAt)}</div>
                      <div className="text-[10px]" style={{ color: COLORS.textTertiary }}>
                        {formatTime(s.updatedAt)}
                      </div>
                    </Td>
                    <Td numeric>
                      <div className="flex gap-1 justify-end">
                        <MiniButton color={COLORS.suggestion} onClick={() => p.onLoad(s.sessionId)}>
                          加载
                        </MiniButton>
                        <MiniButton
                          color={COLORS.conflict}
                          onClick={() => {
                            if (
                              typeof window !== "undefined" &&
                              window.confirm(`确定删除会话 ${s.sessionId}？`)
                            ) {
                              p.onDelete(s.sessionId);
                            }
                          }}
                        >
                          删除
                        </MiniButton>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}

function Th({ children, numeric }: { children: React.ReactNode; numeric?: boolean }) {
  return (
    <th
      className="text-[10px] uppercase tracking-wide font-medium"
      style={{
        padding: "6px 10px",
        textAlign: numeric ? "right" : "left",
        color: COLORS.textSecondary,
      }}
    >
      {children}
    </th>
  );
}

function Td({ children, numeric }: { children: React.ReactNode; numeric?: boolean }) {
  return (
    <td
      style={{
        padding: "6px 10px",
        fontSize: 11,
        color: COLORS.textPrimary,
        textAlign: numeric ? "right" : "left",
        verticalAlign: "middle",
      }}
    >
      {children}
    </td>
  );
}

function ActionButton({
  color,
  onClick,
  children,
}: {
  color: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="text-xs px-3 py-1.5 rounded transition-colors hover:opacity-80"
      style={{
        background: color + "15",
        border: `1px solid ${color}40`,
        color,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

function MiniButton({
  color,
  onClick,
  children,
}: {
  color: string;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className="text-[10px] px-2 py-0.5 rounded transition-colors hover:opacity-80"
      style={{
        background: color + "12",
        border: `1px solid ${color}40`,
        color,
        cursor: "pointer",
      }}
    >
      {children}
    </button>
  );
}

// ==================== 时间线面板 ====================

function TimelinePanel({
  items,
  compact,
}: {
  items: TimelineRow[];
  compact?: boolean;
}) {
  if (items.length === 0) {
    return (
      <div className="text-[11px] italic" style={{ color: COLORS.textSecondary }}>
        暂无消息时间线
      </div>
    );
  }

  const maxDisplay = compact ? 15 : 50;
  const displayItems = items.slice(0, maxDisplay);
  const hiddenCount = items.length - maxDisplay;

  return (
    <div className="flex flex-col gap-1" style={{ maxHeight: compact ? 220 : 340, overflowY: "auto" }}>
      {displayItems.map((item) => (
        <div
          key={item.id}
          className="flex gap-2 items-start rounded"
          style={{
            padding: "5px 8px",
            border: `1px solid ${item.retained ? COLORS.chronicle + "30" : COLORS.border}`,
            background: item.retained ? COLORS.chronicle + "05" : COLORS.bg,
            opacity: item.retained ? 1 : 0.7,
          }}
        >
          <div
            className="flex-shrink-0 rounded-full flex items-center justify-center"
            style={{
              width: 22,
              height: 22,
              fontSize: 10,
              fontWeight: 600,
              color: item.retained ? COLORS.chronicle : COLORS.compressed,
              border: `1px solid ${item.retained ? COLORS.chronicle : COLORS.compressed}`,
            }}
          >
            {item.index}
          </div>
          <div className="flex-1 min-w-0">
            <div
              className="text-xs leading-snug"
              style={{
                color: item.retained ? COLORS.textPrimary : COLORS.compressed,
                textDecoration: item.retained ? "none" : "line-through",
                wordBreak: "break-word",
              }}
            >
              <span className="text-[10px] mr-1" style={{ color: COLORS.textSecondary }}>
                [{item.role}]
              </span>
              {truncate(item.content, 140)}
            </div>
            <div
              className="flex flex-wrap gap-2 mt-0.5 text-[10px]"
              style={{ color: COLORS.textTertiary }}
            >
              <span>{formatTime(item.timestamp)}</span>
              {item.meta && <span>{item.meta}</span>}
              <span style={{ color: item.retained ? COLORS.retained : COLORS.compressed }}>
                {item.retained ? "● 保留" : "○ 已压缩"}
              </span>
            </div>
          </div>
        </div>
      ))}
      {hiddenCount > 0 && (
        <div
          className="text-center text-[10px] italic pt-1"
          style={{ color: COLORS.textSecondary }}
        >
          …还有 {hiddenCount} 条消息未显示
        </div>
      )}
    </div>
  );
}

export default GraphContextCompressionPanel;
