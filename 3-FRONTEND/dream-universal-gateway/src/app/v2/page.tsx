"use client";

import React, { useState, useEffect, useRef, useCallback } from "react";
import Sidebar from "./components/Sidebar";
import TopBar from "./components/TopBar";

// ── Inline SVG icon components (no external dependencies) ──

function IconBarChart({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="12" y1="20" x2="12" y2="10" /><line x1="18" y1="20" x2="18" y2="4" /><line x1="6" y1="20" x2="6" y2="16" />
    </svg>
  );
}
function IconWallet({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M19 7V4a1 1 0 0 0-1-1H5a2 2 0 0 0 0 4h15a1 1 0 0 1 1 1v4h-3a2 2 0 0 0 0 4h3a1 1 0 0 0 1-1v-2a1 1 0 0 0-1-1" />
      <path d="M3 5v14a2 2 0 0 0 2 2h15a1 1 0 0 0 1-1v-4" />
    </svg>
  );
}
function IconSend({ className }: { className?: string }) {
  return (
    <svg className={className} width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <line x1="22" y1="2" x2="11" y2="13" /><polygon points="22 2 15 22 11 13 2 9 22 2" />
    </svg>
  );
}
function IconStop({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2" />
    </svg>
  );
}
function IconSpinner({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M21 12a9 9 0 1 1-6.219-8.56" />
    </svg>
  );
}
function IconAlertTriangle({ className }: { className?: string }) {
  return (
    <svg className={className} width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z" />
      <line x1="12" y1="9" x2="12" y2="13" /><line x1="12" y1="17" x2="12.01" y2="17" />
    </svg>
  );
}

// ── Types ──

interface Message {
  role: "user" | "assistant";
  content: string;
  intent?: string;
  in_flight?: boolean;
  streaming_content?: string;
  confidence?: number;
  chain?: string[];
  task_id?: string;
  strategyChain?: AnalysisChainStep[];
  error?: boolean;
}

interface AnalysisChainStep {
  id: string;
  label: string;
  icon: string;
  status: "idle" | "running" | "completed" | "error";
  summary?: string;
  timestamp?: string;
}

interface StreamProgress {
  isStreaming: boolean;
  currentStep: string | null;
  currentSkill: string | null;
  planSteps: any[];
  skillStatuses: Record<string, any>;
  contentAccumulated: string;
}

interface MarketData {
  price?: number;
  change24h?: number;
  volume24h?: number;
  high24h?: number;
  low24h?: number;
  [key: string]: any;
}

// ── Constants ──

const CHAIN_STEP_MAP: Record<string, { label: string; icon: string }> = {
  S1_RESEARCH: { label: "S1 调研", icon: "\uD83D\uDD0D" },
  S2_ANALYSIS: { label: "S2 分析", icon: "\uD83E\uDDE0" },
  S3_DESIGN: { label: "S3 设计", icon: "\uD83C\uDFAF" },
  S4_VALIDATE: { label: "S4 验证", icon: "\u2705" },
  S5_EXECUTE: { label: "S5 执行", icon: "\u26A1" },
};

const SLASH_COMMANDS: Record<string, { intent: string; message: string }> = {
  "/行情": { intent: "market_query", message: "查询当前市场行情" },
  "/分析": { intent: "deep_analysis", message: "深度分析当前市场" },
  "/推演": { intent: "scenario_sim", message: "推演市场情景" },
  "/验证": { intent: "validate", message: "验证交易策略" },
  "/开仓": { intent: "execute_trade", message: "执行交易开仓" },
};

const COMMAND_CHIPS = Object.keys(SLASH_COMMANDS);

const RIGHT_TABS = [
  { key: "analysis", label: "\uD83D\uDCCA 分析" },
  { key: "memory", label: "\uD83E\uDDE0 记忆" },
  { key: "notes", label: "\uD83D\uDCD2 笔记" },
  { key: "monitor", label: "\uD83D\uDCE1 监控" },
  { key: "pipeline", label: "\uD83D\uDD00 编排" },
  { key: "llm", label: "\uD83E\uDD16 LLM" },
];

// ── Helper ──

function formatPrice(p: number | undefined): string {
  if (p === undefined || p === null) return "--";
  return "$" + p.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function formatChange(c: number | undefined): string {
  if (c === undefined || c === null) return "--";
  const sign = c >= 0 ? "+" : "";
  return sign + c.toFixed(2) + "%";
}

function formatVolume(v: number | undefined): string {
  if (v === undefined || v === null) return "--";
  if (v >= 1e9) return "$" + (v / 1e9).toFixed(1) + "B";
  if (v >= 1e6) return "$" + (v / 1e6).toFixed(1) + "M";
  return "$" + v.toLocaleString();
}

// ── Main Component ──

export default function V2Dashboard() {
  // ── State ──
  const [messages, setMessages] = useState<Message[]>([]);
  const [input, setInput] = useState<string>("");
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [activeTab, setActiveTab] = useState<string>("chat");
  const [thinkingMode, setThinkingMode] = useState<"quick" | "deep">("quick");
  const [lang, setLang] = useState<"zh" | "en">("zh");
  const [rightTab, setRightTab] = useState<string>("analysis");
  const [credits] = useState<number>(1200);

  const [llmStatus, setLlmStatus] = useState<string>("");
  const [llmModel, setLlmModel] = useState<string>("");
  const [intentMethod, setIntentMethod] = useState<string>("");
  const [marketData, setMarketData] = useState<MarketData>({});
  const [analysisChain, setAnalysisChain] = useState<AnalysisChainStep[]>([]);
  const [streamProgress, setStreamProgress] = useState<StreamProgress | null>(null);

  const messagesEndRef = useRef<HTMLDivElement>(null);
  const submitLockRef = useRef<boolean>(false);
  const abortControllerRef = useRef<AbortController | null>(null);
  const marketIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // ── Auto-scroll ──
  const scrollToBottom = useCallback(() => {
    requestAnimationFrame(() => {
      messagesEndRef.current?.scrollIntoView({ behavior: "smooth" });
    });
  }, []);

  useEffect(() => {
    scrollToBottom();
  }, [messages, streamProgress, scrollToBottom]);

  // ── Fetch LLM Status ──
  const fetchLLMStatus = useCallback(async () => {
    try {
      const res = await fetch("/api/chat?action=status");
      const json = await res.json();
      if (json.success && json.data) {
        setLlmStatus(json.data.llm_status || "");
        setLlmModel(json.data.llm_model || "");
        setIntentMethod(json.data.intent_method || "");
      }
    } catch {
      // Silently fail — will show "unknown" in UI
    }
  }, []);

  // ── Fetch Market Data ──
  const fetchMarketData = useCallback(async () => {
    try {
      const res = await fetch("/api/market/snapshot?symbol=BTC-USDT-SWAP");
      const json = await res.json();
      if (json.success && json.data) {
        setMarketData(json.data);
      }
    } catch {
      // Silently fail — keeps last known data
    }
  }, []);

  // ── Init Analysis Chain ──
  const initAnalysisChain = useCallback((intent: string | undefined, mode: "quick" | "deep"): AnalysisChainStep[] => {
    let steps: string[] = [];

    if (!intent || intent === "market_query" || mode === "quick") {
      steps = ["S1_RESEARCH"];
    } else if (intent === "deep_analysis") {
      steps = ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE"];
    } else if (intent === "scenario_sim") {
      steps = ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN"];
    } else if (intent === "execute_trade" || intent === "triple_chain") {
      steps = ["S1_RESEARCH", "S2_ANALYSIS", "S3_DESIGN", "S4_VALIDATE", "S5_EXECUTE"];
    } else if (intent === "validate") {
      steps = ["S1_RESEARCH", "S2_ANALYSIS", "S4_VALIDATE"];
    } else {
      steps = ["S1_RESEARCH"];
    }

    return steps.map((stepId) => ({
      id: stepId,
      label: CHAIN_STEP_MAP[stepId]?.label || stepId,
      icon: CHAIN_STEP_MAP[stepId]?.icon || "",
      status: "idle" as const,
    }));
  }, []);

  // ── Handle SSE Progress Event ──
  const handleProgressEvent = useCallback(
    (event: any, assistantMsgIdx: number) => {
      const eventType = event.event || event.type;

      if (eventType === "progress") {
        const subType = event.sub_type || event.subType;
        const data = event.data || {};

        setStreamProgress((prev) => {
          const updated = {
            ...(prev || { isStreaming: true, currentStep: null, currentSkill: null, planSteps: [], skillStatuses: {}, contentAccumulated: prev?.contentAccumulated || "" }),
            isStreaming: true,
          };

          if (subType === "plan_created" && data.steps) {
            updated.planSteps = data.steps;
          }
          if (subType === "step_start") {
            updated.currentStep = data.step;
          }
          if (subType === "step_skill_start") {
            updated.currentSkill = data.skill;
            updated.skillStatuses = {
              ...updated.skillStatuses,
              [data.skill]: { status: "running" },
            };
          }
          if (subType === "step_skill_end") {
            updated.currentSkill = null;
            updated.skillStatuses = {
              ...updated.skillStatuses,
              [data.skill]: { status: "completed", result: data.result },
            };
          }
          if (subType === "step_end") {
            const completedStep = data.step || prev?.currentStep;
            if (completedStep) {
              setAnalysisChain((chain) =>
                chain.map((s) =>
                  s.id === completedStep
                    ? { ...s, status: "completed", timestamp: new Date().toLocaleTimeString() }
                    : s.id === prev?.currentStep && s.status === "running"
                      ? s
                      : s
                )
              );
            }
            updated.currentStep = null;
          }
          if (subType === "content_delta") {
            const delta = data.delta || data.content || "";
            updated.contentAccumulated = (updated.contentAccumulated || "") + delta;

            // Update message with typing effect
            setMessages((prev) =>
              prev.map((m, i) =>
                i === assistantMsgIdx
                  ? { ...m, streaming_content: updated.contentAccumulated }
                  : m
              )
            );
          }

          return updated;
        });
      }

      if (eventType === "done") {
        const finalContent = event.data?.content || streamProgress?.contentAccumulated || "";
        setStreamProgress(null);
        setAnalysisChain((chain) =>
          chain.map((s) => (s.status === "running" ? { ...s, status: "completed" as const } : s))
        );
        setMessages((prev) =>
          prev.map((m, i) =>
            i === assistantMsgIdx
              ? {
                  ...m,
                  content: finalContent || m.streaming_content || m.content,
                  streaming_content: undefined,
                  in_flight: false,
                  confidence: event.data?.confidence || m.confidence,
                  chain: event.data?.chain || m.chain,
                }
              : m
          )
        );
        setIsLoading(false);
        submitLockRef.current = false;
      }

      if (eventType === "error") {
        const errMsg = event.data?.error || event.data?.message || "Unknown error";
        setStreamProgress(null);
        setAnalysisChain((chain) =>
          chain.map((s) => (s.status === "running" ? { ...s, status: "error" as const } : s))
        );
        setMessages((prev) =>
          prev.map((m, i) =>
            i === assistantMsgIdx
              ? {
                  ...m,
                  content: m.streaming_content || m.content || `Error: ${errMsg}`,
                  streaming_content: undefined,
                  in_flight: false,
                  error: true,
                }
              : m
          )
        );
        setIsLoading(false);
        submitLockRef.current = false;
      }
    },
    [streamProgress]
  );

  // ── Sync fallback: POST /api/task ──
  const submitSyncTask = useCallback(
    async (
      message: string,
      intent: string | undefined,
      assistantMsgIdx: number,
      chain: AnalysisChainStep[]
    ) => {
      try {
        const res = await fetch("/api/task", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message,
            session_id: "v2-session",
            thinking_mode: thinkingMode,
            llm_model: llmModel || undefined,
            intent_method: intentMethod || undefined,
            lang,
            trading_mode: "ai_skill",
          }),
        });
        const json = await res.json();

        if (json.success && json.data) {
          const data = json.data;
          // If task is async, poll for result
          if (data.status === "pending" && data.task_id) {
            setMessages((prev) =>
              prev.map((m, i) =>
                i === assistantMsgIdx ? { ...m, task_id: data.task_id } : m
              )
            );

            // Poll for async result
            const startTime = Date.now();
            const maxPollMs = 5 * 60 * 1000;

            const poll = async () => {
              while (Date.now() - startTime < maxPollMs) {
                try {
                  const pollRes = await fetch(`/api/task?id=${data.task_id}`);
                  const pollJson = await pollRes.json();
                  if (pollJson.success && pollJson.data) {
                    if (pollJson.data.status === "completed") {
                      const completedChain = chain.map((s) => ({
                        ...s,
                        status: "completed" as const,
                        timestamp: new Date().toLocaleTimeString(),
                      }));
                      setMessages((prev) =>
                        prev.map((m, i) =>
                          i === assistantMsgIdx
                            ? {
                                ...m,
                                content: pollJson.data.content || m.content,
                                in_flight: false,
                                confidence: pollJson.data.confidence || m.confidence,
                                chain: pollJson.data.chain || m.chain,
                                strategyChain: completedChain,
                              }
                            : m
                        )
                      );
                      setAnalysisChain(completedChain);
                      setIsLoading(false);
                      submitLockRef.current = false;
                      return;
                    }
                    if (pollJson.data.status === "failed") {
                      setMessages((prev) =>
                        prev.map((m, i) =>
                          i === assistantMsgIdx
                            ? { ...m, content: `Error: ${pollJson.data.error || "Task failed"}`, in_flight: false, error: true }
                            : m
                        )
                      );
                      setIsLoading(false);
                      submitLockRef.current = false;
                      return;
                    }
                  }
                } catch {
                  // Continue polling on error
                }
                await new Promise((r) => setTimeout(r, 3000));
              }
              // Timeout
              setMessages((prev) =>
                prev.map((m, i) =>
                  i === assistantMsgIdx
                    ? { ...m, content: m.content || "Task timed out after 5 minutes", in_flight: false, error: true }
                    : m
                )
              );
              setIsLoading(false);
              submitLockRef.current = false;
            };
            poll();
          } else {
            // Sync result
            const completedChain = chain.map((s) => ({
              ...s,
              status: "completed" as const,
              timestamp: new Date().toLocaleTimeString(),
            }));
            setMessages((prev) =>
              prev.map((m, i) =>
                i === assistantMsgIdx
                  ? {
                      ...m,
                      content: data.content || m.content,
                      in_flight: false,
                      confidence: data.confidence || m.confidence,
                      intent: data.intent || m.intent,
                      chain: data.chain || m.chain,
                      strategyChain: completedChain,
                    }
                  : m
              )
            );
            setAnalysisChain(completedChain);
            setIsLoading(false);
            submitLockRef.current = false;
          }
        } else {
          throw new Error(json.error || "Request failed");
        }
      } catch (err: any) {
        setStreamProgress(null);
        setMessages((prev) =>
          prev.map((m, i) =>
            i === assistantMsgIdx
              ? { ...m, content: `Error: ${err.message || "Network error"}`, in_flight: false, error: true }
              : m
          )
        );
        setIsLoading(false);
        submitLockRef.current = false;
      }
    },
    [thinkingMode, llmModel, intentMethod, lang]
  );

  // ── Handle Submit ──
  const handleSubmit = useCallback(
    async (submitInput?: string) => {
      const messageText = (submitInput || input).trim();
      if (!messageText || submitLockRef.current) return;

      submitLockRef.current = true;
      setIsLoading(true);
      setInput("");

      // Detect slash command
      let intent: string | undefined;
      let processedMessage = messageText;
      const cmdMatch = SLASH_COMMANDS[messageText];
      if (cmdMatch) {
        intent = cmdMatch.intent;
        processedMessage = cmdMatch.message;
      }

      // Add user message
      const userMsg: Message = { role: "user", content: processedMessage };
      // Add assistant placeholder
      const assistantMsg: Message = {
        role: "assistant",
        content: "",
        intent,
        in_flight: true,
        streaming_content: "",
        strategyChain: [],
      };

      setMessages((prev) => [...prev, userMsg, assistantMsg]);
      const assistantMsgIdx = messages.length + 1; // index after adding user + assistant

      // Init analysis chain
      const chain = initAnalysisChain(intent, thinkingMode);
      setAnalysisChain([...chain]);

      // Mark first step as running
      const chainWithRunning = chain.map((s, i) =>
        i === 0 ? { ...s, status: "running" as const } : s
      );
      setAnalysisChain(chainWithRunning);

      // Update assistant message with initial chain
      setMessages((prev) =>
        prev.map((m, i) =>
          i === assistantMsgIdx ? { ...m, strategyChain: [...chainWithRunning] } : m
        )
      );

      setStreamProgress({
        isStreaming: true,
        currentStep: chain[0]?.id || null,
        currentSkill: null,
        planSteps: [],
        skillStatuses: {},
        contentAccumulated: "",
      });

      // Try SSE stream first
      try {
        const controller = new AbortController();
        abortControllerRef.current = controller;

        const res = await fetch("/api/task/stream", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            message: processedMessage,
            session_id: "v2-session",
            thinking_mode: thinkingMode,
            llm_model: llmModel || undefined,
            intent_method: intentMethod || undefined,
            lang,
            trading_mode: "ai_skill",
          }),
          signal: controller.signal,
        });

        if (!res.ok || !res.body) {
          throw new Error(`HTTP ${res.status}`);
        }

        const reader = res.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
          const { done, value } = await reader.read();
          if (done) break;

          buffer += decoder.decode(value, { stream: true });

          // Parse SSE lines
          const lines = buffer.split("\n");
          buffer = lines.pop() || "";

          let eventData = "";
          let eventType = "";

          for (const line of lines) {
            if (line.startsWith("event: ")) {
              eventType = line.slice(7).trim();
            }
            if (line.startsWith("data: ")) {
              eventData = line.slice(6).trim();
            }
            if (line === "" && eventData) {
              try {
                const parsed = JSON.parse(eventData);
                const eventWithMeta = { ...parsed, event: eventType, type: eventType };
                handleProgressEvent(eventWithMeta, assistantMsgIdx);
              } catch {
                // Non-JSON data, try to use as content delta
                if (eventType === "progress") {
                  handleProgressEvent({ event: "progress", sub_type: "content_delta", data: { delta: eventData } }, assistantMsgIdx);
                }
              }
              eventData = "";
              eventType = "";
            }
          }
        }

        // If stream ended without a "done" event
        if (submitLockRef.current) {
          // Stream ended — finalize
          setStreamProgress((prev) => {
            if (prev && prev.contentAccumulated) {
              setMessages((msgs) =>
                msgs.map((m, i) =>
                  i === assistantMsgIdx
                    ? { ...m, content: prev.contentAccumulated, streaming_content: undefined, in_flight: false, strategyChain: chainWithRunning.map((s) => ({ ...s, status: "completed" as const })) }
                    : m
                )
              );
              setAnalysisChain(chainWithRunning.map((s) => ({ ...s, status: "completed" as const })));
            }
            return null;
          });
          setIsLoading(false);
          submitLockRef.current = false;
        }
      } catch (err: any) {
        if (err.name === "AbortError") {
          // User cancelled — do nothing special, cleanup handled elsewhere
          return;
        }
        // Fallback to sync
        console.warn("SSE stream failed, falling back to sync:", err.message);
        setStreamProgress(null);
        await submitSyncTask(processedMessage, intent, assistantMsgIdx, chainWithRunning);
      }
    },
    [input, messages.length, thinkingMode, llmModel, intentMethod, lang, initAnalysisChain, handleProgressEvent, submitSyncTask]
  );

  // ── Handle stop ──
  const handleStop = useCallback(() => {
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
      abortControllerRef.current = null;
    }
    setStreamProgress(null);
    setIsLoading(false);
    submitLockRef.current = false;
    setAnalysisChain((chain) =>
      chain.map((s) => (s.status === "running" ? { ...s, status: "idle" as const } : s))
    );
    setMessages((prev) =>
      prev.map((m) =>
        m.in_flight
          ? { ...m, in_flight: false, content: m.streaming_content || m.content || "(cancelled)", streaming_content: undefined }
          : m
      )
    );
  }, []);

  // ── Mount effects ──
  useEffect(() => {
    fetchLLMStatus();
    fetchMarketData();

    marketIntervalRef.current = setInterval(fetchMarketData, 10000);

    return () => {
      if (marketIntervalRef.current) {
        clearInterval(marketIntervalRef.current);
      }
      if (abortControllerRef.current) {
        abortControllerRef.current.abort();
      }
    };
  }, [fetchLLMStatus, fetchMarketData]);

  // ── Render: Chain Progress ──
  const renderChainProgress = (chain: AnalysisChainStep[]) => {
    if (!chain || chain.length === 0) return null;
    return (
      <div className="px-4 py-3 flex items-center gap-2">
        {chain.map((step, i) => (
          <React.Fragment key={step.id}>
            <div
              className={`w-5 h-5 rounded-full flex items-center justify-center text-[9px] font-bold ${
                step.status === "completed"
                  ? "bg-[rgba(34,197,94,0.2)] text-[#22c55e]"
                  : step.status === "running"
                    ? "bg-[#3b82f6] text-white animate-pulse"
                    : step.status === "error"
                      ? "bg-[rgba(239,68,68,0.2)] text-[#ef4444]"
                      : "bg-[#1e293b] text-[#64748b]"
              }`}
            >
              {step.status === "completed" ? "\u2713" : step.status === "error" ? "!" : step.status === "running" ? "\u25B6" : i + 1}
            </div>
            <span className={`text-[10px] ${step.status === "running" ? "text-[#3b82f6]" : step.status === "completed" ? "text-[#22c55e]" : "text-[#64748b]"}`}>
              {step.label}
            </span>
            {i < chain.length - 1 && (
              <div className={`w-4 h-px ${step.status === "completed" ? "bg-[#22c55e]/50" : "bg-[#1e293b]"}`} />
            )}
          </React.Fragment>
        ))}
      </div>
    );
  };

  // ── Render: Message ──
  const renderMessage = (msg: Message, idx: number) => {
    if (msg.role === "user") {
      return (
        <div key={idx} className="flex justify-end">
          <div className="max-w-[75%] bg-[rgba(59,130,246,0.1)] border border-[rgba(59,130,246,0.2)] rounded-lg px-4 py-3">
            <div className="text-[11px] text-[#64748b] mb-1 text-right">{"\uD83D\uDC64"} 你</div>
            <p className="text-[13px] text-[#f1f5f9]">{msg.content}</p>
          </div>
        </div>
      );
    }

    // Assistant message
    const displayContent = msg.streaming_content || msg.content;
    const isFlying = msg.in_flight;
    const hasChain = msg.strategyChain && msg.strategyChain.length > 0;

    return (
      <div key={idx} className="flex justify-start">
        <div className={`max-w-[80%] ${msg.error ? "border-[#ef4444]/30" : "border-[#1e293b]"} border rounded-lg overflow-hidden bg-[#111827]`}>
          {/* Header */}
          <div className="px-4 py-2 border-b border-[#1e293b] flex items-center gap-2">
            <span className="text-[11px] text-[#06b6d4]">{"\uD83E\uDD16"} AI助手{"\u00B7"} 刚刚</span>
            {msg.intent && (
              <span className="text-[10px] px-1.5 py-0.5 rounded bg-[rgba(6,182,212,0.1)] text-[#06b6d4]">
                {msg.intent}
              </span>
            )}
            {isFlying && !displayContent && (
              <span className="inline-flex items-center gap-1 text-[10px] text-[#3b82f6]">
                <IconSpinner className="w-3 h-3 animate-spin" /> 思考中...
              </span>
            )}
          </div>

          {/* Chain progress */}
          {hasChain && renderChainProgress(msg.strategyChain)}

          {/* Content */}
          <div className="px-4 py-3 text-[13px] text-[#94a3b8] leading-relaxed">
            {displayContent ? (
              displayContent.split("\n").map((line, li) => (
                <p key={li} className={li > 0 ? "mt-2" : ""}>
                  {line || "\u00A0"}
                </p>
              ))
            ) : isFlying ? (
              <div className="flex items-center gap-1">
                <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6] animate-bounce" style={{ animationDelay: "0ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6] animate-bounce" style={{ animationDelay: "150ms" }} />
                <span className="w-1.5 h-1.5 rounded-full bg-[#3b82f6] animate-bounce" style={{ animationDelay: "300ms" }} />
              </div>
            ) : null}
          </div>

          {/* Confidence bar */}
          {msg.confidence !== undefined && msg.confidence !== null && displayContent && (
            <div className="px-4 pb-2">
              <div className="flex items-center justify-between mb-1">
                <span className="text-[10px] text-[#64748b]">分析置信度</span>
                <span className="text-[11px] font-semibold text-[#f1f5f9] font-mono">{Math.round(msg.confidence)}%</span>
              </div>
              <div className="h-1.5 bg-[#1e293b] rounded-full overflow-hidden">
                <div
                  className="h-full rounded-full bg-gradient-to-r from-[#ef4444] via-[#f59e0b] to-[#22c55e]"
                  style={{ width: `${Math.min(100, Math.max(0, msg.confidence))}%` }}
                />
              </div>
            </div>
          )}

          {/* Chain tags */}
          {msg.chain && msg.chain.length > 0 && (
            <div className="px-4 pb-3 flex gap-2 flex-wrap">
              {msg.chain.map((tag, ti) => (
                <span key={ti} className="text-[10px] px-2 py-0.5 rounded-full bg-[rgba(59,130,246,0.1)] text-[#3b82f6] border border-[rgba(59,130,246,0.2)]">
                  {tag}
                </span>
              ))}
            </div>
          )}

          {/* Error indicator */}
          {msg.error && (
            <div className="px-4 pb-3 flex items-center gap-1 text-[#ef4444] text-[10px]">
              <IconAlertTriangle className="w-3 h-3" />
              <span>请求出错，请重试</span>
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── Render: Right panel content ──
  const renderRightContent = () => {
    if (rightTab === "analysis") {
      return (
        <div className="flex-1 overflow-y-auto p-4">
          {/* 市场概览 */}
          <div className="mb-4">
            <div className="text-[12px] font-semibold text-[#f1f5f9] mb-3">市场概览</div>
            <div className="grid grid-cols-2 gap-2">
              <div className="bg-[#1e293b] rounded-lg p-3">
                <div className="text-[10px] text-[#64748b]">BTC/USDT</div>
                <div className="text-[14px] text-[#f1f5f9] font-mono mt-1">
                  {formatPrice(marketData.price)}
                </div>
                <div className={`text-[11px] font-mono ${(marketData.change24h || 0) >= 0 ? "text-[#22c55e]" : "text-[#ef4444]"}`}>
                  {formatChange(marketData.change24h)}
                </div>
              </div>
              <div className="bg-[#1e293b] rounded-lg p-3">
                <div className="text-[10px] text-[#64748b]">24h High</div>
                <div className="text-[14px] text-[#f1f5f9] font-mono mt-1">
                  {formatPrice(marketData.high24h)}
                </div>
                <div className="text-[10px] text-[#64748b] mt-1">
                  Low: {formatPrice(marketData.low24h)}
                </div>
              </div>
              <div className="bg-[#1e293b] rounded-lg p-3 col-span-2">
                <div className="text-[10px] text-[#64748b]">24h Volume</div>
                <div className="text-[14px] text-[#f1f5f9] font-mono mt-1">
                  {formatVolume(marketData.volume24h)}
                </div>
              </div>
            </div>
          </div>

          {/* LLM Status */}
          <div className="mb-4">
            <div className="text-[12px] font-semibold text-[#f1f5f9] mb-3">模型状态</div>
            <div className="bg-[#1e293b] rounded-lg p-3">
              <div className="flex items-center gap-2 mb-2">
                <div className={`w-2 h-2 rounded-full ${llmStatus ? "bg-[#22c55e]" : "bg-[#64748b]"}`} />
                <span className="text-[11px] text-[#94a3b8]">
                  {llmStatus ? `LLM 在线` : "LLM 状态未知"}
                </span>
              </div>
              {llmModel && (
                <div className="text-[11px] text-[#64748b] font-mono">LLM: {llmModel}</div>
              )}
              {intentMethod && (
                <div className="text-[11px] text-[#64748b] font-mono mt-1">Intent: {intentMethod}</div>
              )}
            </div>
          </div>

          {/* Connection status */}
          <div>
            <div className="text-[12px] font-semibold text-[#f1f5f9] mb-3">连接状态</div>
            <div className="bg-[#1e293b] rounded-lg p-3">
              <div className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-full bg-[#22c55e]" />
                <span className="text-[11px] text-[#94a3b8]">API 已连接</span>
              </div>
              <div className="text-[10px] text-[#64748b] mt-1 font-mono">
                Market refresh: 10s interval
              </div>
            </div>
          </div>
        </div>
      );
    }

    // Other tabs: placeholder
    return (
      <div className="flex-1 overflow-y-auto p-4">
        <div className="text-[12px] text-[#64748b] text-center mt-8">
          {rightTab === "memory" && "记忆库功能开发中..."}
          {rightTab === "notes" && "笔记功能开发中..."}
          {rightTab === "monitor" && "系统监控功能开发中..."}
          {rightTab === "pipeline" && "编排功能开发中..."}
          {rightTab === "llm" && (
            <div>
              <div className="text-[12px] font-semibold text-[#f1f5f9] mb-3">LLM 配置</div>
              <div className="bg-[#1e293b] rounded-lg p-3 text-left">
                <div className="text-[11px] text-[#94a3b8] mb-2">当前模型</div>
                <div className="text-[13px] text-[#f1f5f9] font-mono">{llmModel || "未加载"}</div>
                <div className="text-[11px] text-[#94a3b8] mt-3 mb-2">意图识别</div>
                <div className="text-[13px] text-[#f1f5f9] font-mono">{intentMethod || "未加载"}</div>
                <div className="text-[11px] text-[#94a3b8] mt-3 mb-2">思考模式</div>
                <div className="text-[13px] text-[#f1f5f9]">{thinkingMode === "quick" ? "智能思考" : "深度思考"}</div>
              </div>
            </div>
          )}
        </div>
      </div>
    );
  };

  // ── Main Render ──
  return (
    <div className="h-screen w-screen flex overflow-hidden bg-[#0a0e17] v2-theme">
      {/* Sidebar */}
      <Sidebar activeTab={activeTab} onTabChange={setActiveTab} />

      {/* Main area */}
      <div className="flex-1 flex flex-col overflow-hidden">
        {/* TopBar */}
        <TopBar
          pageTitle="对话交易"
          thinkingMode={thinkingMode}
          onThinkingModeChange={setThinkingMode}
          lang={lang}
          onLangChange={setLang}
          credits={credits}
        />

        {/* Content area */}
        <div className="flex-1 flex overflow-hidden">
          {/* Chat Area */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Welcome Section — only shown when no messages */}
            {messages.length === 0 && (
              <div className="p-6">
                <div className="text-[20px] font-semibold text-[#f1f5f9]">
                  你好，Analyst
                </div>
                <div className="text-[13px] text-[#94a3b8] mt-1">
                  Dream Gateway 智能交易助手
                </div>
                <div className="flex items-center gap-2 mt-3">
                  <div className={`w-2 h-2 rounded-full ${llmStatus ? "bg-[#22c55e]" : "bg-[#64748b]"}`} />
                  <span className="text-[11px] text-[#64748b]">
                    {llmStatus ? `LLM 在线 \u00B7 ${llmModel}` : "正在连接 LLM..."}
                  </span>
                </div>
                <div className="flex gap-3 mt-5">
                  <div
                    className="bg-[#1e293b] border border-[#2d3a52] rounded-lg p-3 cursor-pointer hover:border-[#3b82f6]/50"
                    onClick={() => handleSubmit("/行情")}
                  >
                    <IconBarChart className="w-4 h-4 text-[#3b82f6]" />
                    <div className="text-[12px] font-medium text-[#f1f5f9] mt-1">
                      分析 BTC
                    </div>
                  </div>
                  <div
                    className="bg-[#1e293b] border border-[#2d3a52] rounded-lg p-3 cursor-pointer hover:border-[#3b82f6]/50"
                    onClick={() => handleSubmit("/推演")}
                  >
                    <IconWallet className="w-4 h-4 text-[#3b82f6]" />
                    <div className="text-[12px] font-medium text-[#f1f5f9] mt-1">
                      场景推演
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* Messages Area */}
            {messages.length > 0 && (
              <div className="flex-1 overflow-y-auto px-6 space-y-4">
                {messages.map((msg, idx) => renderMessage(msg, idx))}
                <div ref={messagesEndRef} />
              </div>
            )}

            {/* Input Area */}
            <div className="p-4 border-t border-[#1e293b]">
              {/* Command chips */}
              <div className="flex gap-2 mb-3">
                {COMMAND_CHIPS.map((chip) => (
                  <span
                    key={chip}
                    className="text-[11px] text-[#94a3b8] bg-[#1e293b] px-2.5 py-1 rounded-md hover:text-[#3b82f6] hover:bg-[rgba(59,130,246,0.08)] cursor-pointer select-none"
                    onClick={() => handleSubmit(chip)}
                  >
                    {chip}
                  </span>
                ))}
              </div>
              {/* Input row */}
              <div className="flex gap-3">
                <input
                  type="text"
                  value={input}
                  onChange={(e) => setInput(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter" && !e.shiftKey) {
                      e.preventDefault();
                      handleSubmit();
                    }
                  }}
                  placeholder={"输入消息... (\u26A1智能 | 支持 /命令)"}
                  className="flex-1 bg-[#111827] border border-[#1e293b] rounded-lg px-4 py-2.5 text-[13px] text-[#f1f5f9] placeholder:text-[#475569] outline-none focus:border-[#3b82f6]/50"
                  disabled={isLoading}
                />
                {isLoading ? (
                  <button
                    onClick={handleStop}
                    className="w-10 h-10 rounded-lg bg-[#ef4444] flex items-center justify-center cursor-pointer"
                    title="停止生成"
                  >
                    <IconStop className="w-3.5 h-3.5 text-white" />
                  </button>
                ) : (
                  <button
                    onClick={() => handleSubmit()}
                    className="w-10 h-10 rounded-lg bg-[#3b82f6] flex items-center justify-center cursor-pointer"
                    title="发送"
                  >
                    <IconSend className="w-4 h-4 text-white" />
                  </button>
                )}
              </div>
            </div>
          </div>

          {/* Right Analysis Panel */}
          <div className="w-[340px] border-l border-[#1e293b] bg-[#111827] flex flex-col">
            {/* Tab bar */}
            <div className="border-b border-[#1e293b] flex px-1">
              {RIGHT_TABS.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setRightTab(tab.key)}
                  className={`text-[11px] py-3 px-2 cursor-pointer ${
                    rightTab === tab.key
                      ? "text-[#3b82f6] border-b-2 border-[#3b82f6]"
                      : "text-[#64748b] hover:text-[#94a3b8]"
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </div>

            {/* Tab content */}
            {renderRightContent()}
          </div>
        </div>
      </div>
    </div>
  );
}
