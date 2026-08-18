"use client";

import { useState, useEffect, useCallback, useMemo, useRef } from "react";
// import { useSession } from "next-auth/react";
// 临时 mock —— Next.js 15.5 与 next-auth 5.0-beta webpack 不兼容
function useSession(): { data: { user?: { name?: string; email?: string } } | null; status: "authenticated" | "loading" | "unauthenticated" } {
  return { data: { user: { name: "Analyst", email: "analyst@dreambuddy.io" } }, status: "authenticated" };
}
import { useRouter } from "next/navigation";
import dynamic from 'next/dynamic';
const FundamentalPanel = dynamic(() => import("./FundamentalPanel"), { ssr: false });
import { useAutoConfigStore } from "@/stores/auto-config-store";
import type { ChainTrace } from "@/types";
import AutoConfigBubble from "@/components/chat/AutoConfigBubble";
import AutoConfigSummary from "@/components/chat/AutoConfigSummary";
import { useAuthStore } from "@/stores";
import { navigateToRecharge } from "./navigation";
import {
  normalizeTradingPanelData,
  type TradingPanelData,
} from "./trading-panel-data";
import { buildStrategyPanelViewModel } from "./strategy-view-model";
import {
  StrategyLibraryAPI,
  PipelineAPI,
  SandboxAPI,
  SignalsAPI,
  ApprovalsAPI,
  ExecutionAPI,
  ExitAPI,
  SystemHealthAPI,
  AutomationAPI,
  ArenaAPI,
  UniverseAPI,
  MacroAPI,
  EvaluationAPI,
  TrackerAPI,
  GateThresholdsAPI,
  type StrategyInfo,
  type SignalInfo,
  type ApprovalInfo,
  type AutomationCard,
  type SettlementRecord,
  type BacktestResultItem,
  type SandboxState,
  type ServingPipelineState,
} from "@/lib/classic-system-api";
import "./dashboard.css";
// Notebook 组件
const NotebookPanel = dynamic(() => import("@/components/notebook/NotebookPanel"), { ssr: false });

// 图结构上下文压缩面板
const GraphCompressionPanel = dynamic(() => import("@/components/graph-compression-viz/GraphContextCompressionPanel"), { ssr: false });

// 编排追踪面板 (三层架构可视化)
const OrchestrationPanel = dynamic(() => import("@/components/orchestration/OrchestrationPanel"), { ssr: false });

// 对话内嵌思考卡
const ThinkingCard = dynamic(() => import("@/components/chat/ThinkingCard"), { ssr: false });

function NotebookPanelWrapper() {
  return <NotebookPanel />;
}

// 动态导入 react-markdown (客户端only)
const ReactMarkdown = dynamic(() => import('react-markdown'), { ssr: false });

// Color system - 腾讯云控制台风格
const colors = {
  bgPrimary: "#0d0d0d",
  bgSecondary: "#1a1a1a",
  bgChat: "#141414",
  textPrimary: "#ffffff",
  textSecondary: "#8a8a8a",
  accentBlue: "#0066ff",
  accentGreen: "#00c853",
  accentRed: "#ff3b30",
};

// 模型列表
const QWEN_MODELS = [
  { id: 'deepseek-v4-pro', name: 'DeepSeek V4 Pro', desc: '最强推理·金融分析', provider: 'deepseek' },
];

type RightPanelType = 'analysis' | 'market' | 'signal' | 'position' | 'api' | 'trading' | 'strategy' | 'communication' | 'llm' | 'report' | 'monitor' | 'memory' | 'notebook' | 'graph-compression' | 'orchestration';

// 链路步骤定义 (v2 三闭环架构)
// Phase 0: 统一使用 S 系列，A 系列已迁移到后端
const CHAIN_STEP_MAP: Record<string, { label: string; icon: string; loop?: string }> = {
  // S 系列策略思维链（前端主链）
  'S0_DIRECT_ANSWER': { label: 'S0 快速回答', icon: '💬', loop: 'general' },
  'S1_RESEARCH':       { label: 'S1 调研', icon: '🔍', loop: 'execution' },
  'S2_ANALYSIS':       { label: 'S2 分析', icon: '🧠', loop: 'execution' },
  'S3_DESIGN':         { label: 'S3 设计', icon: '📐', loop: 'execution' },
  'S4_VALIDATE':       { label: 'S4 验证', icon: '✅', loop: 'execution' },
  'S5_EXECUTE':        { label: 'S5 执行', icon: '⚡', loop: 'execution' },

  // A 系列兼容映射（向后兼容，后端技能链）
  'A1_research':    { label: 'S1 调研（后端）', icon: '🔍', loop: 'execution' },
  'A2_analysis':    { label: 'S2 分析（后端）', icon: '🧠', loop: 'execution' },
  'A3_simulation':  { label: 'S3 设计（后端）', icon: '🎲', loop: 'execution' },
  'A4_validation':  { label: 'S4 验证（后端）', icon: '✅', loop: 'execution' },
  'A5_execution':   { label: 'S5 执行（后端）', icon: '⚡', loop: 'execution' },
  'A9_exit':        { label: 'S5 执行（离场）', icon: '🚪', loop: 'execution' },
  'A6_intelligence':{ label: 'S2 分析（情报）', icon: '📡', loop: 'intelligence' },
  'A6_alert':       { label: 'S2 分析（告警）', icon: '⚠️', loop: 'intelligence' },
  'A6_intel':       { label: 'S2 分析（情报）', icon: '📡', loop: 'intelligence' },
  'A7_practice':    { label: 'S5 执行（实践）', icon: '📝', loop: 'governance' },
  'A7_gate':        { label: 'S5 执行（风控）', icon: '🛡️', loop: 'governance' },
  'A8_verification':{ label: 'S4 验证（知行）', icon: '🔮', loop: 'governance' },

  // 旧 utility 步骤兼容映射
  'market_data':    { label: 'S1 调研（行情）', icon: '📊', loop: 'intelligence' },
  'knowledge_base': { label: 'S1 调研（知识库）', icon: '📚', loop: 'general' },
  'tavily_search': { label: 'S1 调研（联网）', icon: '🌐', loop: 'general' },
  'direct_answer': { label: 'S0 快速回答', icon: '💬', loop: 'general' },
};

// 意图→默认链路映射 (v2 对齐智能路由 + S系列策略思维链)
// Phase 0: 统一使用 S 系列
const INTENT_CHAIN_MAP: Record<string, string[]> = {
  'market_query':    ['S1_RESEARCH'],
  'deep_analysis':   ['S1_RESEARCH', 'S2_ANALYSIS'],
  'scenario_sim':    ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'],
  'strategy_verify': ['S4_VALIDATE'],
  'execute_trade':   ['S4_VALIDATE', 'S5_EXECUTE'],
  'triple_chain':    ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'],
  'deep_full':       ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
  'simple_qa':       ['S0_DIRECT_ANSWER'],
  'command':         ['S1_RESEARCH'],
  'system_config':   ['S0_DIRECT_ANSWER'],
  'credits_query':   ['S0_DIRECT_ANSWER'],
  'artifact_query':  ['S1_RESEARCH'],
  'risk_alert_response': ['S2_ANALYSIS'],
};

// API配置类型
interface ApiConfigItem {
  id: string;
  category: string;
  provider: string;
  label: string;
  keyHint: string;
  environment?: string;
  baseUrl?: string | null;
  isVerified: boolean;
  lastVerifiedAt?: string;
  createdAt?: string;
  updatedAt?: string;
}

// 行情数据类型
interface MarketData {
  symbol: string;
  price?: number;
  change24h?: number;
  open24h?: number;
  high24h?: number;
  low24h?: number;
  fundingRate?: string | null;
  volume24h?: string;
  positions?: Array<Record<string, unknown>>;
  timestamp: string;
}

// 研报元数据类型
interface ReportMeta {
  file: string;
  title: string;
  date: string;
  chain_phase: string;
  tags: string;
  status: string;
  confidence?: number;
  phaseColor: string;
  regime?: string;
  direction?: string;
  isToday?: boolean;
  relativeTime?: string;
  freshness?: 'today' | 'stale';
}

export default function ChatPage() {
  const router = useRouter();
  const { data: session, status } = useSession();
  const [mounted, setMounted] = useState(false);
  const [leftCollapsed, setLeftCollapsed] = useState(false);
  const [rightCollapsed, setRightCollapsed] = useState(false);
  const [activeTab, setActiveTab] = useState<'trade' | 'classic' | 'fundamental'>('trade');
  const [classicSubTab, setClassicSubTab] = useState<'strategies' | 'sandbox' | 'approvals' | 'signals' | 'filter' | 'execution' | 'exit' | 'library' | 'arena' | 'universe' | 'macro' | 'evaluation'>('library');

  // ========== 经典交易体系 API 数据 ==========
  const [classicHealth, setClassicHealth] = useState<{ ok: boolean; error?: string }>({ ok: false });
  const [strategyList, setStrategyList] = useState<StrategyInfo[]>([]);
  const [signalList, setSignalList] = useState<SignalInfo[]>([]);
  const [approvalList, setApprovalList] = useState<ApprovalInfo[]>([]);
  const [automationCards, setAutomationCards] = useState<AutomationCard[]>([]);
  const [exitStats, setExitStats] = useState<{ ok: boolean; open_positions: Record<string, any>; exit_owner_state: { weights: Record<string, number> } }>({ ok: false, open_positions: {}, exit_owner_state: { weights: {} } });
  const [arenaState, setArenaState] = useState<{ ok: boolean; enabled?: boolean; pool_u?: number; models?: Record<string, any> }>({ ok: false });
  const [universeState, setUniverseState] = useState<{ ok: boolean; core?: string[]; watchlist?: string[]; shadow?: string[]; last_update?: number }>({ ok: false });
  const [macroState, setMacroState] = useState<{ ok: boolean; gate_std1h?: Record<string, any>; btc?: Record<string, any>; eth?: Record<string, any>; macro_btceth_shape?: Record<string, any>; macro_tri_layer?: Record<string, any> }>({ ok: false });
  const [evaluationState, setEvaluationState] = useState<{ ok: boolean; orders?: { total: number; window: number }; acceptance?: Record<string, any>; online?: Record<string, any>; profit_window?: Record<string, any> }>({ ok: false });
  const [settlements, setSettlements] = useState<SettlementRecord[]>([]);
  const [backtestResults, setBacktestResults] = useState<BacktestResultItem[]>([]);
  const [sandboxState, setSandboxState] = useState<SandboxState>({ running: 0, queued: 0, max_slots: 3 });
  const [pipelineState, setPipelineState] = useState<ServingPipelineState>({});
  const [gateCheck, setGateCheck] = useState<{ ok: boolean; passed?: boolean; checks?: Record<string, boolean>; thresholds?: Record<string, number>; metrics?: Record<string, number> }>({ ok: false });
  const [isLoadingClassicData, setIsLoadingClassicData] = useState(false);

  // 加载经典系统数据
  const loadClassicSystemData = useCallback(async () => {
    setIsLoadingClassicData(true);
    try {
      // 健康检查
      const health = await SystemHealthAPI.healthCheck();
      setClassicHealth(health);

      // 并行加载策略库、信号、审批、自动化状态、离场状态、Arena、Universe、Macro、Evaluation、Tracker、Sandbox、Pipeline、GateCheck
      const [strategies, signals, approvals, autoCards, exitData, arena, universe, macro, evaluation, tracker, backtestRes, sandboxRes, pipelineRes, gateCheckRes] = await Promise.all([
        StrategyLibraryAPI.listStrategies(),
        SignalsAPI.getRecentSignals(20),
        ApprovalsAPI.getPendingApprovals(),
        AutomationAPI.getAutomationStatus(),
        ExitAPI.getExitStatus(),
        ArenaAPI.getState(),
        UniverseAPI.getStatus(),
        MacroAPI.getOverview(),
        EvaluationAPI.getAcceptanceStatus(),
        TrackerAPI.getStats(),
        SandboxAPI.getBacktestResults(20),
        SandboxAPI.getSandboxState(),
        PipelineAPI.getServingPipelineState(),
        PipelineAPI.getGateCheck(),
      ]);

      if (strategies.ok && strategies.strategies) {
        setStrategyList(strategies.strategies);
      }
      if (signals.ok && signals.signals) {
        setSignalList(signals.signals);
      }
      if (approvals.ok && approvals.approvals) {
        setApprovalList(approvals.approvals);
      }
      if (autoCards.ok && autoCards.cards) {
        setAutomationCards(autoCards.cards);
      }
      if (exitData.ok) {
        setExitStats(exitData);
      }
      if (arena.ok) {
        setArenaState(arena);
      }
      if (universe.ok) {
        setUniverseState(universe);
      }
      if (macro.ok) {
        setMacroState(macro);
      }
      if (evaluation.ok) {
        setEvaluationState(evaluation);
      }
      if (tracker.ok && tracker.ab_settlements) {
        setSettlements(tracker.ab_settlements);
      }
      if (backtestRes.ok && backtestRes.results) {
        setBacktestResults(backtestRes.results);
      }
      if (sandboxRes.ok && sandboxRes.state) {
        setSandboxState(sandboxRes.state);
      }
      if (pipelineRes.ok && pipelineRes.serving_pipeline) {
        setPipelineState(pipelineRes.serving_pipeline);
      }
      if (gateCheckRes.ok) {
        setGateCheck(gateCheckRes);
      }
    } catch (error) {
      console.error("[Classic System] Load data failed:", error);
    } finally {
      setIsLoadingClassicData(false);
    }
  }, []);

  // 当切换到经典交易体系 Tab 时加载数据
  useEffect(() => {
    if (activeTab === 'classic') {
      loadClassicSystemData();
    }
  }, [activeTab, loadClassicSystemData]);

  // 定时刷新数据（每 30 秒）
  useEffect(() => {
    if (activeTab !== 'classic') return;
    const interval = setInterval(loadClassicSystemData, 30000);
    return () => clearInterval(interval);
  }, [activeTab, loadClassicSystemData]);

  const [dataCardExpanded, setDataCardExpanded] = useState(false);
  const [settingsExpanded, setSettingsExpanded] = useState(false);
  const [rightPanelContent, setRightPanelContent] = useState<RightPanelType>('analysis');
  const [orchestrationTrace, setOrchestrationTrace] = useState<ChainTrace | null>(null);
  
  // 流式进度状态（实时更新思考卡）
  const [streamProgress, setStreamProgress] = useState<{
    isStreaming: boolean;
    currentStep: string | null;
    currentSkill: string | null;
    planSteps: Array<{ stepId: string; stage: string; chain: string; label?: string; status: 'pending' | 'active' | 'done' | 'skipped' }>;
    skillStatuses: Record<string, { status: 'pending' | 'active' | 'done'; confidence?: number; latencyMs?: number }>;
    contentAccumulated: string;
  } | null>(null);
  
  const [input, setInput] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [thinkingMode, setThinkingMode] = useState<'quick' | 'deep'>('quick');
  const [lang, setLang] = useState<'zh' | 'en'>('zh'); // 语言设置，默认中文

  const [sessionId, setSessionId] = useState<string>(() => {
    if (typeof window !== 'undefined') {
      const saved = localStorage.getItem('dream_gateway_session_id');
      if (saved) return saved;
    }
    const newId = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    if (typeof window !== 'undefined') {
      localStorage.setItem('dream_gateway_session_id', newId);
    }
    return newId;
  });

  const handleNewChat = () => {
    if (isLoading) return;
    const newId = `sess_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
    setSessionId(newId);
    if (typeof window !== 'undefined') {
      localStorage.setItem('dream_gateway_session_id', newId);
    }
    setMessages([
      {
        role: "assistant",
        content: "你好！我是 Dream Gateway 智能交易助手。\n\n可以帮你分析市场、制定策略、管理交易。下方可切换思考深度与响应模式，交易任务执行前会要求确认。\n\n试试输入「分析BTC」或「/行情」",
      },
    ]);
    setAnalysisChain(null);
    setStreamProgress(null);
  };

  const loadChatHistory = useCallback(async (sessId: string) => {
    try {
      const res = await fetch(`/api/chat/history?session_id=${encodeURIComponent(sessId)}`);
      const data = await res.json();
      if (data.success && data.data && data.data.messages && data.data.messages.length > 0) {
        const formatted = data.data.messages.map((m: any) => ({
          role: m.role,
          content: m.content,
          intent: m.intent_type,
          task_id: m.task_id,
        }));
        setMessages(formatted);
        return true;
      }
    } catch (err) {
      console.warn('[loadChatHistory] 加载会话历史失败:', err);
    }
    return false;
  }, []);

  // P2-双交易模式
  //   ai_skill: AI SKILL 模式 (自然语言 → OKX Agent CLI → 交易所)，灵活但消耗 Token
  //   classic:  经典交易体系 (策略代码 → Freqtrade → 沙箱测试 → 治理上线)，结构化可回测
  const [tradingMode, setTradingMode] = useState<'ai_skill' | 'classic'>('ai_skill');

  // ========== 动态分析链路追踪 ==========
  const [analysisChain, setAnalysisChain] = useState<{
    id: string;
    label: string;
    icon: string;
    status: 'idle' | 'running' | 'completed' | 'error';
    summary?: string;
    timestamp?: string;
  }[]>([]);
  const [analysisStartTime, setAnalysisStartTime] = useState<number | null>(null);
  const [analysisEndTime, setAnalysisEndTime] = useState<number | null>(null);
  const [analysisIntent, setAnalysisIntent] = useState<string>('');
  const [analysisConfidence, setAnalysisConfidence] = useState<number | null>(null);

  // ========== 监控面板状态 ==========
  const [monitorEvents, setMonitorEvents] = useState<Array<{
    id: string; trace_id: string; uid: string; timestamp: string;
    layer: string; phase: string; status: string;
    intent?: string; thinking_mode?: string; chain?: string[];
    duration_ms?: number; error?: string; artifact_file?: string; message_preview?: string;
  }>>([]);
  const [monitorPaused, setMonitorPaused] = useState(false);
  const [monitorPipeline, setMonitorPipeline] = useState<{
    frontend: { total: number; completed: number; rate: string };
    gateway: { total: number; completed: number; rate: string };
    workbuddy: { total: number; completed: number; rate: string };
    artifact_hub: { total: number; completed: number; rate: string };
  } | null>(null);
  const [monitorStats, setMonitorStats] = useState<{
    total_requests: number; total_completed: number; total_failed: number; total_timeout: number;
    success_rate: number; avg_duration_ms: number; active_traces: number;
    intent_distribution: Record<string, number>;
  } | null>(null);
  const [monitorSelectedTrace, setMonitorSelectedTrace] = useState<string | null>(null);
  const monitorSSERef = useRef<EventSource | null>(null);

  // Memory Bank 状态
  const [memoryRecords, setMemoryRecords] = useState<any[]>([]);
  const [memoryStats, setMemoryStats] = useState<any>(null);
  const [memoryCandidates, setMemoryCandidates] = useState<any[]>([]);
  const [memoryAdjustments, setMemoryAdjustments] = useState<any[]>([]);
  
  // LLM 状态
  const [llmStatus, setLlmStatus] = useState<'online' | 'offline' | 'degraded'>('offline');
  const [llmModel, setLlmModel] = useState('qwen3-30b-a3b');
  const [intentMethod, setIntentMethod] = useState<'rule' | 'llm'>('llm');
  
  const [messages, setMessages] = useState<Array<{
    role: string;
    content: string;
    intent?: string;
    confidence?: number;
    context_aware?: boolean;
    chain?: string[];
    thinking_mode?: string;
    trade_task_id?: string;
    trade_confirmed?: boolean;
    task_id?: string;       // 📌 任务 ID，用于结果去重
    in_flight?: boolean;    // 📌 标识是否进行中（thinking 消息）
    artifacts?: Array<{ file: string; type: string; chain_phase: string }>; // 📌 生成的策略产物
    step_confirmation?: {
      current_step: string;
      next_step: string | null;
      options: Array<{ key: string; label: string; action: string }>;
      prompt: string;
    };
    step_task_id?: string;
    awaiting_step?: string;
    next_step?: string;
    clarification_state?: {
      options: Array<{ key: string; label: string; target_intent?: string; action?: string }>;
      prompt?: string;
      current_intent?: string;
    };
  }>>([
    {
      role: "assistant",
      content: "你好！我是 Dream Gateway 智能交易助手。\n\n可以帮你分析市场、制定策略、管理交易。下方可切换思考深度与响应模式，交易任务执行前会要求确认。\n\n试试输入「分析BTC」或「/行情」",
    },
  ]);

  // ========== 新增状态 ==========

  // API配置状态
  const [apiConfigs, setApiConfigs] = useState<ApiConfigItem[]>([]);
  const [showAddApiForm, setShowAddApiForm] = useState(false);
  const [addApiForm, setAddApiForm] = useState({
    category: 'EXCHANGE',
    provider: 'okx',
    label: '',
    apiKey: '',
    secretKey: '',
    passphrase: '',
    environment: 'demo',
  });
  const [apiTesting, setApiTesting] = useState<string | null>(null);
  const [apiTestResult, setApiTestResult] = useState<Record<string, { success: boolean; message: string; latency?: number }> | null>(null);

  // LLM配置状态
  const [showAddLlmForm, setShowAddLlmForm] = useState(false);
  const [addLlmForm, setAddLlmForm] = useState({
    provider: 'openai',
    label: '',
    apiKey: '',
    baseUrl: '',
  });

  // 交易参数状态
  const [tradingParams, setTradingParams] = useState<TradingPanelData | null>(null);
  const [tradingLoading, setTradingLoading] = useState(false);
  const [tradingError, setTradingError] = useState<string | null>(null);
  const [tradingEditing, setTradingEditing] = useState(false);
  const [tradingSaving, setTradingSaving] = useState(false);
  const [tradingEditForm, setTradingEditForm] = useState<Record<string, unknown>>({});

  // === 关联交易所选择状态（四选择器）===
  const [exchangeSelect, setExchangeSelect] = useState<{
    exchange: string;      // 交易所: okx
    configId: string;     // 配置ID: 用于数据库凭证查询
    accountLabel: string;  // 账户名: 主账户
    environment: 'live' | 'demo';  // 环境: live/demo
    symbol: string;       // 币种: USDT
  }>({ exchange: 'okx', configId: '', accountLabel: '', environment: 'demo', symbol: 'USDT' });
  const [balanceLoading, setBalanceLoading] = useState(false);
  const [realtimeBalance, setRealtimeBalance] = useState<{
    available: number;
    totalEquity: number;
    marginUsed: number;
    unrealizedPnl: number;
  } | null>(null);

  // 策略状态
  const [strategies, setStrategies] = useState<{
    strategies: unknown[];
    recommended: unknown[];
    custom: unknown[];
    applied: unknown[];
  }>({ strategies: [], recommended: [], custom: [], applied: [] });
  const [strategiesLoading, setStrategiesLoading] = useState(false);
  const [customStrategyInput, setCustomStrategyInput] = useState('');
  const [customStrategyLoading, setCustomStrategyLoading] = useState(false);
  const strategyViewModel = useMemo(
    () => buildStrategyPanelViewModel({ strategies: strategies.strategies }),
    [strategies.strategies],
  );

  // === 策略向导状态 (Wizard) ===
  type StrategyWizardStep = 'input' | 'preview' | 'confirm';
  const [wizardStep, setWizardStep] = useState<StrategyWizardStep>('input');
  const [wizardParsing, setWizardParsing] = useState(false);
  const [parsedStrategy, setParsedStrategy] = useState<{
    intent: { direction: string; symbol: string; tradeType: string; indicators: string[] };
    suggestedParams: { direction: string; symbol: string; tradeType: string; leverage: number; positionSize: number; stopLoss: number | null; takeProfit: number | null };
    confidence: number;
    explanation: string;
    warnings: string[];
  } | null>(null);
  const [wizardForm, setWizardForm] = useState({
    direction: 'BUY' as string,
    symbol: 'BTC-USDT-SWAP',
    tradeType: 'SPOT' as string,
    leverage: 2,
    positionSize: 0.3,
    stopLoss: '' as string,
    takeProfit: '' as string,
    frequency: 'FOUR_H' as string,
  });
  const [strategyError, setStrategyError] = useState<string | null>(null);
  const [showDrafts, setShowDrafts] = useState(false);
  const [toast, setToast] = useState<{ id: number; type: 'success' | 'error'; msg: string } | null>(null);
  let toastIdCounter = 0;
  // Toast helper
  const showToast = (type: 'success' | 'error', msg: string) => {
    const id = ++toastIdCounter;
    setToast({ id, type, msg });
    setTimeout(() => setToast(prev => (prev?.id === id ? null : prev)), 3000);
  };

  // 通信渠道状态
  const [channels, setChannels] = useState<unknown[]>([]);
  const [channelsLoading, setChannelsLoading] = useState(false);
  const [showAddChannelForm, setShowAddChannelForm] = useState(false);
  const [addChannelForm, setAddChannelForm] = useState({
    channelType: 'TELEGRAM',
    label: '',
    botToken: '',
    chatId: '',
    sendKey: '',
    enabledTypes: ['trade_signal', 'risk_alert', 'intel_update'],
    format: 'CONCISE',
    silentStart: '',
    silentEnd: '',
  });
  const [channelTesting, setChannelTesting] = useState<string | null>(null);
  const [channelTestResult, setChannelTestResult] = useState<Record<string, { success: boolean; message: string }> | null>(null);

  // 积分状态
  const [creditsBalance, setCreditsBalance] = useState(0);
  const [signedInToday, setSignedInToday] = useState(false);
  const [checkinLoading, setCheckinLoading] = useState(false);

  // 获取积分状态
  const fetchCreditsStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/user/checkin');
      const data = await res.json();
      if (data.success) {
        setCreditsBalance(data.data.balance || 0);
        setSignedInToday(data.data.signedInToday || false);
      }
    } catch {}
  }, []);

  // 签到
  const handleCheckin = async () => {
    if (signedInToday) {
      showToast('error', '今日已签到，明日再来吧！');
      return;
    }
    setCheckinLoading(true);
    try {
      const res = await fetch('/api/user/checkin', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        setCreditsBalance(data.data.newBalance);
        setSignedInToday(true);
        showToast('success', `签到成功！获得 ${data.data.bonus} 积分`);
      } else {
        showToast('error', data.error || '签到失败');
      }
    } catch {
      showToast('error', '签到失败，请稍后重试');
    } finally {
      setCheckinLoading(false);
    }
  };

  // 退出登录
  const handleLogout = async () => {
    if (!confirm('确定要退出登录吗？')) return;
    try {
      await fetch('/api/auth/signout', { method: 'POST' });
    } catch {}
    router.push('/login');
  };

  // 行情数据状态
  const [marketData, setMarketData] = useState<MarketData | null>(null);
  const [marketLoading, setMarketLoading] = useState(false);
  const [selectedSymbol, setSelectedSymbol] = useState('BTC-USDT-SWAP');
  const [marketError, setMarketError] = useState<string | null>(null);
  const marketIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const reportIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  // 🔒 同步任务锁：防止快速双击/重入导致重复提交 (state setIsLoading 是异步的，仅靠它无法防重入)
  const submittingRef = useRef<boolean>(false);
  // 📌 最近一次提交的 user message 指纹 + 任务 ID，用于去重 (同样的消息短时间内只触发一次)
  const lastSubmitRef = useRef<{ message: string; ts: number; taskId?: string } | null>(null);

  // 研报状态
  const [reportList, setReportList] = useState<ReportMeta[]>([]);
  const [reportLoading, setReportLoading] = useState(false);
  const [selectedReport, setSelectedReport] = useState<{ filename: string; content: string; metadata: ReportMeta | null } | null>(null);
  const [reportContentLoading, setReportContentLoading] = useState(false);

  // 获取 LLM 状态
  const fetchLLMStatus = useCallback(async () => {
    try {
      const res = await fetch('/api/chat?action=status');
      const data = await res.json();
      if (data.success) {
        setLlmStatus(data.data.llm_status);
        setLlmModel(data.data.llm_model);
        setIntentMethod(data.data.intent_method);
      }
    } catch {}
  }, []);

  // === 获取实时余额（四选择器支持，使用configId从数据库读取凭证）===
  const fetchRealtimeBalance = useCallback(async (
    exchange: string, 
    configId: string,
    accountLabel: string,
    environment: 'live' | 'demo', 
    symbol: string
  ) => {
    setBalanceLoading(true);
    try {
      // 构建查询参数，优先使用configId
      const params = new URLSearchParams({ symbol });
      
      if (configId) {
        // 使用configId从数据库获取凭证
        params.set('configId', configId);
      } else {
        // 兼容旧参数
        params.set('exchange', exchange);
        params.set('environment', environment);
        params.set('accountLabel', accountLabel);
      }
      
      const res = await fetch(`/api/trade/balance?${params.toString()}`);
      const data = await res.json();
      if (data.success && data.data) {
        setRealtimeBalance({
          available: data.data.available,
          totalEquity: data.data.totalEquity,
          marginUsed: data.data.marginUsed,
          unrealizedPnl: data.data.unrealizedPnl,
        });
        return data.data;
      } else {
        // 处理特定错误
        if (data.errorCode === 'DECRYPT_FAILED') {
          console.warn('API凭证需要重新配置:', data.error);
          showToast('error', 'API凭证已过期，请重新添加交易所配置');
        } else {
          console.warn('余额获取失败:', data.error || '未知错误');
        }
        setRealtimeBalance(null);
        return null;
      }
    } catch (error) {
      console.error('获取余额失败:', error);
      setRealtimeBalance(null);
      return null;
    } finally {
      setBalanceLoading(false);
    }
  }, []);

  // 获取API配置列表
  const fetchApiConfigs = useCallback(async () => {
    try {
      const res = await fetch('/api/config/api-keys');
      const data = await res.json();
      if (data.success) {
        setApiConfigs(data.data);
        
        // 自动选择第一个模拟盘配置并获取余额（优先模拟盘，避免默认显示0）
        // 仅从交易所配置中选择，排除 LLM / 数据源配置
        const exchangeOnly = (data.data as ApiConfigItem[]).filter((c: ApiConfigItem) => c.category === 'EXCHANGE');
        if (exchangeOnly.length > 0) {
          // 优先选择模拟盘配置
          const demoConfig = exchangeOnly.find((c: ApiConfigItem) => c.environment === 'demo');
          const firstConfig = demoConfig || exchangeOnly[0];
          setExchangeSelect({
            exchange: firstConfig.provider,
            configId: firstConfig.id,  // 保存配置ID用于数据库查询
            accountLabel: firstConfig.label || '默认账户',
            environment: (firstConfig.environment as 'live' | 'demo') || 'demo',
            symbol: 'USDT',
          });
          // 获取该配置的余额（使用configId从数据库读取凭证）
          fetchRealtimeBalance(firstConfig.provider, firstConfig.id, firstConfig.label || '默认账户', firstConfig.environment as 'live' | 'demo' || 'demo', 'USDT');
        }
      }
    } catch {}
  }, [fetchRealtimeBalance]);

  // 获取交易参数
  const fetchTradingParams = useCallback(async () => {
    setTradingLoading(true);
    setTradingError(null);
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), 5000);

    try {
      const res = await fetch('/api/config/trading-params', {
        signal: controller.signal,
      });
      const data = await res.json();
      if (data.success) {
        const normalized = normalizeTradingPanelData(data.data);
        setTradingParams(normalized);
        setTradingEditForm({
          availableCapital: normalized.params.availableCapital ?? '',
          capitalPercentage: Math.round(normalized.params.capitalPercentage * 100),
          tradeMode: normalized.params.tradeMode,
          marginMode: normalized.params.marginMode ?? 'CROSS',
          positionMode: normalized.params.positionMode,
          leverageMax: normalized.params.leverageMax,
          dailyLossLimit: normalized.params.dailyLossLimit,
          dailyLossPercent: Math.round(normalized.params.dailyLossPercent * 100),
          accountLossLimit: normalized.params.accountLossLimit,
          accountLossPercent: Math.round(normalized.params.accountLossPercent * 100),
          riskTolerance: normalized.params.riskTolerance,
        });
      } else {
        setTradingError(data.error || '交易设置加载失败');
      }
    } catch (error) {
      setTradingError(
        error instanceof Error && error.name === 'AbortError'
          ? '交易设置加载超时，请重试'
          : '交易设置加载失败，请重试'
      );
    } finally {
      clearTimeout(timeoutId);
      setTradingLoading(false);
    }
  }, []);

  // 选择交易所/账户后自动更新可用资金（传递configId）
  const handleExchangeChange = useCallback(async (
    exchange: string, 
    configId: string,
    accountLabel: string,
    environment: 'live' | 'demo', 
    symbol: string
  ) => {
    setExchangeSelect({ exchange, configId, accountLabel, environment, symbol });
    const balance = await fetchRealtimeBalance(exchange, configId, accountLabel, environment, symbol);
    if (balance && balance.available > 0) {
      // 自动更新可用资金
      setTradingEditForm(prev => ({
        ...prev,
        availableCapital: balance.available,
      }));
    }
  }, [fetchRealtimeBalance]);

  // 获取策略列表
  const fetchStrategies = useCallback(async () => {
    setStrategiesLoading(true);
    try {
      const res = await fetch('/api/config/strategies');
      const data = await res.json();
      if (data.success) {
        setStrategies({
          strategies: data.data.strategies || [],
          recommended: data.data.recommended || [],
          custom: data.data.custom || [],
          applied: data.data.applied || [],
        });
      }
    } catch {} finally {
      setStrategiesLoading(false);
    }
  }, []);

  // 获取通信渠道列表
  const fetchChannels = useCallback(async () => {
    setChannelsLoading(true);
    try {
      const res = await fetch('/api/config/channels');
      const data = await res.json();
      if (data.success) {
        setChannels(data.data || []);
      }
    } catch {} finally {
      setChannelsLoading(false);
    }
  }, []);

  // 获取行情数据
  const fetchMarketData = useCallback(async (symbol?: string) => {
    setMarketLoading(true);
    setMarketError(null);
    try {
      const sym = symbol || selectedSymbol;
      const res = await fetch(`/api/market/snapshot?symbol=${encodeURIComponent(sym)}`);
      const data = await res.json();
      if (data.success) {
        setMarketData(data.data);
      } else {
        setMarketError(data.error || '获取行情失败');
      }
    } catch (error) {
      setMarketError('网络错误，无法获取行情');
    } finally {
      setMarketLoading(false);
    }
  }, [selectedSymbol]);

  // 获取研报列表 - 默认只取A1/A2/A3/A6最新3份
  const fetchReportList = useCallback(async () => {
    setReportLoading(true);
    try {
      const res = await fetch('/api/reports?phases=A1,A2,A3,A6&latest=3');
      const data = await res.json();
      if (data.success) {
        setReportList(data.data);
      }
    } catch {} finally {
      setReportLoading(false);
    }
  }, []);

  // 获取研报内容
  const fetchReportContent = useCallback(async (filename: string) => {
    setReportContentLoading(true);
    try {
      const res = await fetch(`/api/reports?file=${encodeURIComponent(filename)}`);
      const data = await res.json();
      if (data.success) {
        setSelectedReport(data.data);
        setRightPanelContent('report');
      }
    } catch {} finally {
      setReportContentLoading(false);
    }
  }, []);

  useEffect(() => {
    setMounted(true);
    fetchLLMStatus();
    fetchApiConfigs();
    fetchTradingParams();
    fetchStrategies();
    fetchChannels();
    fetchMarketData();
    fetchReportList();
    fetchCreditsStatus();
    // 每30秒刷新一次状态
    const interval = setInterval(fetchLLMStatus, 30000);
    // 每60秒刷新行情
    marketIntervalRef.current = setInterval(() => fetchMarketData(), 60000);
    // 每1小时刷新研报列表
    reportIntervalRef.current = setInterval(() => fetchReportList(), 3600000);
    return () => {
      clearInterval(interval);
      if (marketIntervalRef.current) clearInterval(marketIntervalRef.current);
      if (reportIntervalRef.current) clearInterval(reportIntervalRef.current);
    };
  }, [fetchLLMStatus, fetchApiConfigs, fetchTradingParams, fetchStrategies, fetchChannels, fetchMarketData, fetchReportList, fetchCreditsStatus]);

  useEffect(() => {
    if (!mounted) return;
    loadChatHistory(sessionId);
  }, [mounted, sessionId, loadChatHistory]);

  // ========== 监控面板 SSE 连接 ==========
  useEffect(() => {
    // 只在右面板切到 monitor 时连接
    if (rightPanelContent !== 'monitor') {
      if (monitorSSERef.current) {
        monitorSSERef.current.close();
        monitorSSERef.current = null;
      }
      return;
    }

    // 加载历史事件和统计
    const fetchMonitorData = async () => {
      try {
        const [eventsRes, statsRes] = await Promise.all([
          fetch('/api/monitor/events?limit=30'),
          fetch('/api/monitor/stats'),
        ]);
        const eventsData = await eventsRes.json();
        const statsData = await statsRes.json();
        if (eventsData.success) setMonitorEvents(eventsData.data);
        if (statsData.success) {
          setMonitorStats(statsData.data.stats);
          setMonitorPipeline(statsData.data.pipeline);
        }
      } catch {}
    };

    fetchMonitorData();

    // 建立 SSE 连接
    if (!monitorSSERef.current && !monitorPaused) {
      try {
        const es = new EventSource('/api/monitor/stream');
        es.onmessage = (e) => {
          try {
            const event = JSON.parse(e.data);
            if (event.type === 'connected') return; // 忽略连接确认
            setMonitorEvents(prev => [event, ...prev].slice(0, 100));
            // 更新 pipeline 和 stats（从事件推断）
            if (event.layer && event.phase) {
              fetch('/api/monitor/stats').then(r => r.json()).then(d => {
                if (d.success) {
                  setMonitorStats(d.data.stats);
                  setMonitorPipeline(d.data.pipeline);
                }
              }).catch(() => {});
            }
          } catch {}
        };
        es.onerror = () => {
          // SSE 断开，5s后重试
          es.close();
          monitorSSERef.current = null;
        };
        monitorSSERef.current = es;
      } catch {}
    }

    // 定期刷新统计
    const statsInterval = setInterval(fetchMonitorData, 10000);

    return () => {
      clearInterval(statsInterval);
      if (monitorSSERef.current) {
        monitorSSERef.current.close();
        monitorSSERef.current = null;
      }
    };
  }, [rightPanelContent, monitorPaused]);

  // 记忆库数据获取
  const fetchMemoryData = useCallback(async () => {
    try {
      const [recordsRes, statsRes, candidatesRes, adjustmentsRes] = await Promise.all([
        fetch('/api/intent/memory?limit=20'),
        fetch('/api/intent/memory?action=stats'),
        fetch('/api/intent/memory?action=candidates'),
        fetch('/api/intent/memory?action=adjustments'),
      ]);
      const recordsData = await recordsRes.json();
      const statsData = await statsRes.json();
      const candidatesData = await candidatesRes.json();
      const adjustmentsData = await adjustmentsRes.json();
      if (recordsData.records) setMemoryRecords(recordsData.records);
      if (statsData.total_records !== undefined) setMemoryStats(statsData);
      if (candidatesData.candidates) setMemoryCandidates(candidatesData.candidates);
      if (adjustmentsData.adjustments) setMemoryAdjustments(adjustmentsData.adjustments);
    } catch {}
  }, []);

  // 当切换到记忆库面板时加载数据
  useEffect(() => {
    if (rightPanelContent === 'memory') {
      fetchMemoryData();
    }
  }, [rightPanelContent, fetchMemoryData]);

  // 提交反馈
  const submitMemoryFeedback = async (recordId: string, feedback: 'correct' | 'incorrect') => {
    try {
      await fetch('/api/intent/memory?action=feedback', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ record_id: recordId, feedback }),
      });
      // 刷新数据
      fetchMemoryData();
    } catch {}
  };

  // 触发进化
  const triggerEvolve = async () => {
    try {
      const res = await fetch('/api/intent/memory?action=evolve', { method: 'POST' });
      const data = await res.json();
      if (data.success) {
        fetchMemoryData();
      }
    } catch {}
  };

  // 采纳候选模式
  const adoptCandidate = async (c: any) => {
    try {
      await fetch('/api/intent/memory?action=adopt', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(c),
      });
      fetchMemoryData();
    } catch {}
  };

  // 切换模型
  const switchModel = async (modelId: string) => {
    try {
      const res = await fetch(`/api/chat?action=set_model&model=${modelId}`);
      const data = await res.json();
      if (data.success) {
        setLlmModel(modelId);
        setLlmStatus('offline'); // 重置状态
        fetchLLMStatus(); // 立即检查新模型
      }
    } catch {}
  };

  // 切换识别方法
  const switchMethod = async (method: 'rule' | 'llm') => {
    try {
      const res = await fetch(`/api/chat?action=set_method&method=${method}`);
      const data = await res.json();
      if (data.success) {
        setIntentMethod(method);
      }
    } catch {}
  };

  // ========== 分析链路辅助函数 ==========
  
  /** 根据意图+思考模式初始化分析链路 */
  const initAnalysisChain = (intent: string, mode: 'quick' | 'deep') => {
    let steps: string[];
    if (mode === 'deep' && (intent === 'deep_analysis' || intent === 'scenario_sim' || intent === 'triple_chain')) {
      // 深度模式：完整 S 系列链
      if (intent === 'triple_chain') {
        steps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
      } else if (intent === 'scenario_sim') {
        steps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'];
      } else {
        steps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'];
      }
    } else {
      steps = INTENT_CHAIN_MAP[intent] || ['S1_RESEARCH'];
    }
    
    const chain = steps.map((id, idx) => ({
      id,
      label: CHAIN_STEP_MAP[id]?.label || id,
      icon: CHAIN_STEP_MAP[id]?.icon || '📋',
      status: idx === 0 ? 'running' as const : 'idle' as const,
    }));
    
    setAnalysisChain(chain);
    setAnalysisStartTime(Date.now());
    setAnalysisIntent(intent);
    setAnalysisConfidence(null);
  };

  /** 标记某个步骤完成 */
  const markChainStep = (stepId: string, status: 'completed' | 'error', summary?: string) => {
    setAnalysisChain(prev => prev.map((step, idx) => {
      if (step.id === stepId) {
        return {
          ...step,
          status,
          summary: summary || step.summary,
          timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        };
      }
      return step;
    }));
    if (status === 'completed') {
      setAnalysisChain(prev => {
        const completedIdx = prev.findIndex(s => s.id === stepId);
        const next = prev[completedIdx + 1];
        if (next && next.status === 'idle') {
          return prev.map((s, i) => i === completedIdx + 1 ? { ...s, status: 'running' as const } : s);
        }
        return prev;
      });
    }
  };

  /** 模拟深度分析的分步进度（用于中台即时模式，在等待结果时展示动画） */
  const simulateDeepProgress = (steps: string[]) => {
    let currentStep = 0;
    const stepDurations = [2000, 3000, 2500, 2000]; // 每步模拟时长(ms)
    
    const advance = () => {
      if (currentStep >= steps.length) return;
      
      const stepId = steps[currentStep];
      setAnalysisChain(prev => prev.map((s, i) => {
        if (s.id === stepId && s.status === 'running') {
          return { ...s, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) };
        }
        // 下一步开始
        if (s.status === 'idle' && i === currentStep + 1) {
          return { ...s, status: 'running' as const };
        }
        return s;
      }));
      
      currentStep++;
      if (currentStep < steps.length) {
        setTimeout(advance, stepDurations[currentStep] || 2000);
      } else {
        // 全部完成
        setAnalysisEndTime(Date.now());
      }
    };
    
    // 第一步延迟后标记完成
    setTimeout(advance, stepDurations[0] || 2000);
  };

  /** 清空分析链路 */
  const resetAnalysisChain = () => {
    setAnalysisChain([]);
    setAnalysisStartTime(null);
    setAnalysisEndTime(null);
    setAnalysisIntent('');
    setAnalysisConfidence(null);
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;

    // 🔒 同步锁：防止快速重复点击/重入 (setIsLoading 异步更新不足以防重入)
    if (submittingRef.current) return;
    submittingRef.current = true;

    const userMessage = input;

    // 📌 短时间窗口 (1500ms) 内相同消息视为重复提交，直接忽略
    const now = Date.now();
    if (
      lastSubmitRef.current &&
      lastSubmitRef.current.message === userMessage &&
      now - lastSubmitRef.current.ts < 1500
    ) {
      submittingRef.current = false;
      return;
    }
    lastSubmitRef.current = { message: userMessage, ts: now };

    // 🔍 检测用户是否在回复步进确认（D/Z/E 思维链选择）
    const lastAssistantMsg = messages[messages.length - 1];
    if (lastAssistantMsg?.step_confirmation && lastAssistantMsg?.step_task_id) {
      // 识别用户的步进确认选择
      const normalizedInput = userMessage.trim().toLowerCase();
      let choice: 'continue' | 'finalize' | 'skip' | 'unknown' = 'unknown';

      if (normalizedInput === '1' || normalizedInput.includes('继续') || normalizedInput.includes('下一步')) {
        choice = 'continue';
      } else if (normalizedInput === '2' || normalizedInput.includes('落地') || normalizedInput.includes('finalize')) {
        choice = 'finalize';
      } else if (normalizedInput === '3' || normalizedInput.includes('跳过') || normalizedInput.includes('skip')) {
        choice = 'skip';
      }

      if (choice !== 'unknown') {
        await handleStepConfirmation(userMessage, lastAssistantMsg, choice);
        return;
      }
    }

    // 🔍 检测用户是否在回复意图澄清（数字选择澄清选项）
    if (lastAssistantMsg?.clarification_state?.options && lastAssistantMsg.clarification_state.options.length > 0) {
      const options = lastAssistantMsg.clarification_state.options;
      const trimmed = userMessage.trim();
      const numMatch = trimmed.match(/^(\d+)$/);
      let selectedOpt: any = null;

      if (numMatch) {
        const idx = parseInt(numMatch[1], 10) - 1;
        if (idx >= 0 && idx < options.length) {
          selectedOpt = options[idx];
        }
      } else {
        selectedOpt = options.find((opt: any) =>
          trimmed === opt.label || trimmed === opt.key || trimmed.includes(opt.label)
        );
      }

      if (selectedOpt) {
        setInput("");
        await handleClarificationChoice(lastAssistantMsg, selectedOpt, options.indexOf(selectedOpt));
        submittingRef.current = false;
        return;
      }
    }

    // 🛡️ 二次防御：若 messages 末尾已有相同内容的 user 消息 (state更新延迟场景)，跳过添加
    if (messages.length > 0) {
      const tail = messages[messages.length - 1];
      if (tail.role === 'user' && tail.content === userMessage) {
        submittingRef.current = false;
        return;
      }
    }

    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setIsLoading(true);
    resetAnalysisChain(); // 清除上一轮分析链路

    try {
      await handleWorkbuddyTask(userMessage);
    } finally {
      // 🔓 释放同步锁，isLoading 也会在子流程的 finally 中重置
      submittingRef.current = false;
    }
  };

  /**
   * 处理 D/Z/E 思维链步进确认
   * 用户选择 (1)继续/(2)落地/(3)跳过 后调用此函数
   */
  const handleStepConfirmation = async (
    userMessage: string,
    lastMsg: typeof messages[number],
    choice: 'continue' | 'finalize' | 'skip'
  ) => {
    const stepTaskId = lastMsg.step_task_id;
    const currentStep = lastMsg.awaiting_step;
    const nextStep = lastMsg.next_step;

    // 将用户选择作为新消息发送，继续执行思维链
    const continueMessage = choice === 'continue'
      ? `用户选择: 继续到下一步 (${nextStep})`
      : choice === 'finalize'
      ? '用户选择: 直接落地'
      : '用户选择: 跳过剩余步骤落地';

    setMessages((prev) => [...prev, { role: "user", content: userMessage }]);
    setInput("");
    setIsLoading(true);
    resetAnalysisChain();

    try {
      const res = await fetch("/api/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: continueMessage,
          session_id: sessionId,
          thinking_mode: lastMsg.thinking_mode || 'deep',
          llm_model: llmModel,
          intent_method: intentMethod,
          lang: lang,
          // 传递前序步骤信息用于链 continuation
          chain_context: {
            previous_task_id: stepTaskId,
            previous_step: currentStep,
            user_choice: choice,
            next_step: nextStep,
          },
        }),
      });

      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      const taskStatus = data.data.status;
      const content = data.data.content || '';

      if (taskStatus === 'completed') {
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "step_confirmation");
          return [
            ...filtered,
            { role: "assistant", content, intent: 'step_continued' },
          ];
        });
      } else if (taskStatus === 'awaiting_confirmation') {
        // 再次等待确认
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "step_confirmation");
          return [
            ...filtered,
            {
              role: "assistant",
              content,
              intent: 'step_confirmation' as any,
              step_confirmation: data.data.step_confirmation,
              step_task_id: data.data.task_id,
              awaiting_step: data.data.execution_summary?.current_step,
              next_step: data.data.step_confirmation?.next_step,
              thinking_mode: lastMsg.thinking_mode,
            },
          ];
        });
      }
    } catch (error) {
      console.error('Step confirmation error:', error);
      setMessages((prev) => {
        const filtered = prev.filter((m) => m.intent !== "step_confirmation");
        return [
          ...filtered,
          { role: "assistant", content: `❌ 步进确认失败: ${error instanceof Error ? error.message : '未知错误'}`, intent: 'error' },
        ];
      });
    } finally {
      setIsLoading(false);
    }
  };

  /**
   * 处理用户点击澄清选项（意图识别不确定时）
   * 用户点击后，构造更明确的消息发送到后端（结合原始问题和选择）
   * 后端会重新走意图识别→执行链路
   */
  const handleClarificationChoice = async (msg: any, opt: any, _idx: number) => {
    const choiceLabel = opt.label || opt.key || '';
    let newUserMessage = choiceLabel;
    const userMessages = messages.filter((m: any) => m.role === 'user');
    const lastUserMsg = userMessages[userMessages.length - 1]?.content || '';
    if (lastUserMsg && lastUserMsg !== choiceLabel) {
      newUserMessage = `${lastUserMsg} - ${choiceLabel}`;
    }
    setMessages((prev) => {
      const filtered = prev.filter((m: any) => !(m.clarification_state && m.clarification_state.options));
      return [...filtered, { role: "user", content: choiceLabel }];
    });
    setIsLoading(true);
    await handleWorkbuddyTask(newUserMessage);
  };

  /**
   * 处理 D/Z/E 思维链的步进确认
   */
  const handleStepChoice = async (msg: any, _opt: any) => {
    // 简单地让用户重新输入选择
    const choiceMessage = _opt.key === 'continue' || _opt.label?.includes('继续')
      ? '进入下一步'
      : _opt.key === 'finalize' || _opt.label?.includes('落地')
      ? '直接落地'
      : '跳过';
    setMessages((prev) => {
      const filtered = prev.filter((m: any) => !(m.step_confirmation));
      return [...filtered, { role: "user", content: choiceMessage }];
    });
    setIsLoading(true);
    await handleWorkbuddyTask(choiceMessage);
  };

  /**
   * WorkBuddy即时任务模式 v2.0
   * 中台即时触发：POST创建任务后直接返回结果（秒级），无需轮询
   * 回退：如果返回processing状态，仍然走轮询逻辑
   */
  const handleWorkbuddyTask = async (userMessage: string) => {
    // 📌 幂等保护：若 messages 末尾已经是 thinking 或同样的任务结果，短路返回
    const tail = messages[messages.length - 1];
    if (tail && tail.role === 'assistant' && (tail.intent === 'thinking' || (tail as any).in_flight)) {
      console.warn('[handleWorkbuddyTask] 检测到正在进行的任务消息，忽略重复调用');
      return;
    }

    const thinkingText = thinkingMode === 'quick'
      ? "⏳ ⚡ 任务已发送，中台即时执行中..."
      : "⏳ 🧠 深度任务已发送，中台即时执行中...";

    // 🛡️ 防御性添加 thinking 消息：用 setMessages 回调式更新，避免闭包旧值问题
    setMessages((prev) => {
      const last = prev[prev.length - 1];
      if (last && last.role === 'assistant' && last.intent === 'thinking') {
        return prev;
      }
      return [...prev, { role: "assistant", content: thinkingText, intent: "thinking", in_flight: true } as any];
    });

    // 🔗 初始化分析链路追踪
    initAnalysisChain('deep_analysis', thinkingMode);

    // 重置流式进度状态
    setStreamProgress({
      isStreaming: true,
      currentStep: null,
      currentSkill: null,
      planSteps: [],
      skillStatuses: {},
      contentAccumulated: '',
    });

    try {
      // ========== SSE 流式执行（优先） ==========
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 180000); // 3分钟超时

      const response = await fetch("/api/task/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          session_id: sessionId,
          thinking_mode: thinkingMode,
          llm_model: llmModel,
          intent_method: intentMethod,
          lang: lang,
          trading_mode: tradingMode,
        }),
        signal: controller.signal,
      });

      clearTimeout(timeoutId);

      if (!response.ok) {
        // 如果流式接口不可用，降级到原有模式
        console.warn('[SSE] 流式接口不可用，降级到同步模式');
        await handleWorkbuddyTaskLegacy(userMessage);
        return;
      }

      const reader = response.body?.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      let finalData: any = null;
      let accumulatedContent = '';

      if (!reader) {
        throw new Error('无法读取响应流');
      }

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });

        // 解析 SSE 事件
        const eventLines = buffer.split('\n\n');
        buffer = eventLines.pop() || '';

        for (const eventBlock of eventLines) {
          if (!eventBlock.trim()) continue;

          const lines = eventBlock.split('\n');
          let eventType = 'message';
          let eventData = '';

          for (const line of lines) {
            if (line.startsWith('event: ')) {
              eventType = line.slice(7).trim();
            } else if (line.startsWith('data: ')) {
              eventData += line.slice(6);
            }
          }

          if (!eventData) continue;

          try {
            const data = JSON.parse(eventData);
            
            switch (eventType) {
              case 'started':
                console.log('[SSE] 任务开始');
                break;

              case 'progress':
                // 处理进度事件
                handleProgressEvent(data);
                break;

              case 'done':
                finalData = data;
                break;

              case 'error':
                throw new Error(data.error || '执行错误');
            }
          } catch (e) {
            console.warn('[SSE] 解析事件失败:', e, eventData.slice(0, 100));
          }
        }
      }

      // 流式读取完成
      if (finalData && finalData.status === 'completed' && finalData.content) {
        handleStreamSuccess(finalData);
      } else if (finalData && finalData.status === 'processing') {
        // 需要异步执行，走轮询降级
        const taskId = finalData.task_id;
        await pollTaskResult(taskId);
      } else {
        // 没有得到有效结果，降级到同步模式
        console.warn('[SSE] 未获取到有效结果，降级到同步模式');
        await handleWorkbuddyTaskLegacy(userMessage);
      }

    } catch (error) {
      console.error("WorkBuddy task error:", error);
      
      // 网络错误或超时，尝试降级到同步模式
      if (error instanceof Error && (error.name === 'AbortError' || error.message === 'Failed to fetch')) {
        console.warn('[SSE] 流式请求失败，尝试降级模式');
        try {
          await handleWorkbuddyTaskLegacy(userMessage);
          return;
        } catch {
          // 降级也失败，继续下面的错误处理
        }
      }

      // 友好错误提示
      let errorMsg = "未知错误";
      if (error instanceof Error) {
        if (error.name === 'AbortError') {
          errorMsg = '请求超时（3分钟），任务可能仍在后台执行';
        } else if (error.message === 'Failed to fetch') {
          errorMsg = '网络连接失败，服务器可能正在重启或响应过长，请稍后重试';
        } else {
          errorMsg = error.message;
        }
      }
      setMessages((prev) => {
        const filtered = prev.filter((m) => m.intent !== "thinking");
        return [
          ...filtered,
          {
            role: "assistant",
            content: `❌ 任务请求失败：${errorMsg}\n\n请稍后重试。`,
            intent: "error",
          },
        ];
      });
      setIsLoading(false);
      setStreamProgress(null);
    }
  };

  // ========== 处理进度事件 ==========
  const handleProgressEvent = (event: any) => {
    setStreamProgress((prev) => {
      if (!prev) return prev;
      let updated = { ...prev };

      switch (event.type) {
        case 'plan_created':
          updated.planSteps = event.plan.steps.map((s: any) => ({
            stepId: s.stepId,
            stage: s.stage,
            chain: s.chain,
            label: s.label,
            status: 'pending' as const,
          }));
          break;

        case 'step_start':
          updated.currentStep = event.stepId;
          updated.planSteps = updated.planSteps.map(s =>
            s.stepId === event.stepId ? { ...s, status: 'active' as const } : s
          );
          break;

        case 'step_skill_start':
          updated.currentSkill = event.skillName;
          const skillKeyStart = `${event.stepId}_${event.skillId}`;
          updated.skillStatuses = {
            ...updated.skillStatuses,
            [skillKeyStart]: { status: 'active' as const },
          };
          break;

        case 'step_skill_end':
          const skillKeyEnd = `${event.stepId}_${event.skillId}`;
          updated.skillStatuses = {
            ...updated.skillStatuses,
            [skillKeyEnd]: {
              status: 'done' as const,
              confidence: event.confidence,
              latencyMs: event.latencyMs,
            },
          };
          break;

        case 'step_end':
          updated.planSteps = updated.planSteps.map(s =>
            s.stepId === event.stepId
              ? { ...s, status: event.status === 'completed' ? 'done' as const : event.status === 'skipped' ? 'skipped' as const : 'done' as const }
              : s
          );
          if (event.status === 'completed' || event.status === 'skipped') {
            updated.currentStep = null;
            updated.currentSkill = null;
          }
          break;

        case 'content_delta':
          updated.contentAccumulated += event.delta;
          break;

        case 'done':
          updated.isStreaming = false;
          break;
      }

      return updated;
    });

    // 同步更新 thinking 消息的内容（打字机效果）
    if (event.type === 'content_delta' && event.delta) {
      setMessages((prev) => {
        const lastIdx = prev.length - 1;
        if (lastIdx < 0) return prev;
        const last = prev[lastIdx];
        if (last.role !== 'assistant' || last.intent !== 'thinking') return prev;

        const currentContent = (last as any).streaming_content || '';
        const updated = [...prev];
        updated[lastIdx] = {
          ...last,
          content: currentContent + event.delta,
          streaming_content: currentContent + event.delta,
        };
        return updated;
      });
    }
  };

  // ========== 流式成功处理 ==========
  const handleStreamSuccess = (data: any) => {
    const content = data.chat_content || data.content;
    const artifacts = data.artifacts_produced || [];
    const summary = data.execution_summary;
    const isTrade = data.trade_requires_confirmation;
    const taskId = data.task_id;
    const intentType = data.intent?.type || data.intent;

    if (data.chain_trace) {
      setOrchestrationTrace(data.chain_trace);
    }

    // 🔗 更新分析链路
    if (summary?.chain_executed) {
      const executedChain = summary.chain_executed as string[];
      setAnalysisChain(prev => prev.map(step => {
        if (executedChain.includes(step.id)) {
          return {
            ...step,
            status: 'completed' as const,
            timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
          };
        }
        if (step.status === 'running') {
          return { ...step, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) };
        }
        return step;
      }));
      setAnalysisEndTime(Date.now());
    }
    if (data.intent?.confidence) {
      setAnalysisConfidence(data.intent.confidence);
    }
    
    let resultContent = content;
    if (artifacts.length > 0) {
      resultContent += `\n\n📎 生成产物: ${artifacts.map((a: any) => `${a.chain_phase}: ${a.file}`).join(' | ')}`;
    }
    if (summary) {
      resultContent += `\n🔗 执行链路: ${summary.chain_executed?.join(' → ') || 'N/A'}`;
    }

    const isSChain = summary?.chain_executed && summary.chain_executed.some((s: string) => s.startsWith('S'));
    
    setMessages((prev) => {
      const filtered = prev.filter((m) => m.intent !== "thinking");
      const existingIdx = filtered.findIndex((m: any) => m.task_id === taskId);
      const newMsg = {
        role: "assistant",
        content: resultContent,
        intent: isTrade ? 'execute_trade' : intentType,
        confidence: data.intent?.confidence,
        thinking_mode: thinkingMode,
        chain: summary?.chain_executed || [],
        task_id: taskId,
        artifacts: artifacts.length > 0 ? artifacts : undefined,
        chain_trace: data.chain_trace,
        trade_task_id: isTrade ? taskId : undefined,
        trade_confirmed: false,
        strategyChain: isSChain ? {
          scope: `${data.intent?.entities?.symbol || 'BTC'} 策略分析`,
          currentStep: summary?.chain_executed?.[summary.chain_executed.length - 1] || null,
          steps: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'].map((stepId, idx) => {
            const isExecuted = summary?.chain_executed?.includes(stepId);
            const isCurrent = stepId === summary?.chain_executed?.[summary.chain_executed.length - 1];
            let status = 'pending';
            if (isExecuted && !isCurrent) status = 'done';
            else if (isCurrent) status = 'active';
            const nameMap: Record<string, string> = {
              'S1_RESEARCH': 'S1 调研',
              'S2_ANALYSIS': 'S2 分析',
              'S3_DESIGN': 'S3 设计',
              'S4_VALIDATE': 'S4 验证',
              'S5_EXECUTE': 'S5 执行',
            };
            return {
              id: stepId,
              number: idx + 1,
              name: nameMap[stepId] || stepId,
              status,
            };
          }),
          complexity: (summary?.chain_executed?.length || 0) <= 2 ? 'quick' : (summary?.chain_executed?.length || 0) <= 3 ? 'standard' : 'deep',
        } : undefined,
      };
      if (existingIdx >= 0) {
        const next = [...filtered];
        next[existingIdx] = { ...next[existingIdx], ...newMsg };
        return next;
      }
      return [...filtered, newMsg];
    });
    setIsLoading(false);
    setStreamProgress(null);
  };

  // ========== 轮询任务结果（降级路径） ==========
  const pollTaskResult = async (taskId: string) => {
    const pollInterval = 3000;
    const maxPollTime = 5 * 60 * 1000;
    const startTime = Date.now();

    while (Date.now() - startTime < maxPollTime) {
      await new Promise(r => setTimeout(r, pollInterval));

      const pollRes = await fetch(`/api/task?id=${taskId}`);
      if (!pollRes.ok) continue;

      const pollData = await pollRes.json();
      const pollStatus = pollData.data.status;

      if (pollStatus === 'completed') {
        const content = pollData.data.chat_content || pollData.data.content || '执行完成，但未返回内容';
        const artifacts = pollData.data.artifacts_produced || [];
        const summary = pollData.data.execution_summary;
        const intentType = pollData.data.intent?.type || pollData.data.intent;
        
        if (pollData.data.chain_trace) {
          setOrchestrationTrace(pollData.data.chain_trace);
        }
        
        if (summary?.chain_executed) {
          const executedChain = summary.chain_executed as string[];
          setAnalysisChain(prev => prev.map(step => {
            if (executedChain.includes(step.id)) {
              return { ...step, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) };
            }
            if (step.status === 'running') {
              return { ...step, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) };
            }
            return step;
          }));
        }
        if (pollData.data.intent?.confidence) setAnalysisConfidence(pollData.data.intent.confidence);
        
        let resultContent = content;
        if (artifacts.length > 0) {
          resultContent += `\n\n📎 生成产物: ${artifacts.map((a: any) => `${a.chain_phase}: ${a.file}`).join(' | ')}`;
        }
        if (summary) {
          resultContent += `\n🔗 执行链路: ${summary.chain_executed?.join(' → ') || 'N/A'}`;
        }

        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "thinking");
          const existingIdx = filtered.findIndex((m: any) => m.task_id === taskId);
          const newMsg = {
            role: "assistant",
            content: resultContent,
            intent: intentType,
            confidence: pollData.data.intent?.confidence,
            thinking_mode: thinkingMode,
            chain: summary?.chain_executed || [],
            task_id: taskId,
          };
          if (existingIdx >= 0) {
            const next = [...filtered];
            next[existingIdx] = { ...next[existingIdx], ...newMsg };
            return next;
          }
          return [...filtered, newMsg];
        });
        setIsLoading(false);
        setStreamProgress(null);
        return;
      }

      if (pollStatus === 'failed') {
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "thinking");
          const existingIdx = filtered.findIndex((m: any) => m.task_id === taskId);
          const newMsg = {
            role: "assistant",
            content: `❌ 任务执行失败\n\n📋 任务ID: ${taskId}\n💥 错误: ${pollData.data.error || '未知错误'}`,
            intent: "error",
            task_id: taskId,
          };
          if (existingIdx >= 0) {
            const next = [...filtered];
            next[existingIdx] = { ...next[existingIdx], ...newMsg };
            return next;
          }
          return [...filtered, newMsg];
        });
        setIsLoading(false);
        setStreamProgress(null);
        return;
      }
    }

    // 轮询超时
    setMessages((prev) => {
      const filtered = prev.filter((m) => m.intent !== "thinking");
      return [
        ...filtered,
        {
          role: "assistant",
          content: `⏰ 等待超时（5分钟）\n\n任务仍在后台执行，你可以稍后查看结果。`,
          intent: "timeout",
        },
      ];
    });
    setIsLoading(false);
    setStreamProgress(null);
  };

  // ========== 旧版同步模式（降级路径） ==========
  const handleWorkbuddyTaskLegacy = async (userMessage: string) => {
    try {
      const controller = new AbortController();
      const timeoutId = setTimeout(() => controller.abort(), 180000);
      const createRes = await fetch("/api/task", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: userMessage,
          session_id: sessionId,
          thinking_mode: thinkingMode,
          llm_model: llmModel,
          intent_method: intentMethod,
          lang: lang,
          trading_mode: tradingMode,
        }),
        signal: controller.signal,
      });
      clearTimeout(timeoutId);

      if (!createRes.ok) {
        if (createRes.status === 429) {
          throw new Error('任务队列已满，请等待当前任务完成');
        }
        throw new Error(`任务创建失败: ${createRes.status}`);
      }

      const createData = await createRes.json();
      const taskStatus = createData.data.status;
      const intentType = createData.data.intent?.type || createData.data.intent;
      const taskId = createData.data.task_id;

      if (taskStatus === 'completed' && createData.data.content) {
        const content = createData.data.content;
        const artifacts = createData.data.artifacts_produced || [];
        const summary = createData.data.execution_summary;
        const isTrade = createData.data.trade_requires_confirmation;

        if ((createData.data as any).chain_trace) {
          setOrchestrationTrace((createData.data as any).chain_trace);
        }
        
        if (summary?.chain_executed) {
          const executedChain = summary.chain_executed as string[];
          setAnalysisChain(prev => prev.map(step => {
            if (executedChain.includes(step.id)) {
              const stepIdLower = step.id.toLowerCase();
              const stepIdNormalized = step.id.replace(/^S\d+_/, '').toLowerCase();
              const artifact = artifacts?.find((a: any) => {
                const phase = String(a.chain_phase || '').toLowerCase();
                return phase === stepIdLower || phase === stepIdNormalized;
              });
              return {
                ...step,
                status: 'completed' as const,
                summary: artifact ? `${artifact.chain_phase}: ${artifact.file?.split('/').pop()}` : undefined,
                timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
              };
            }
            if (step.status === 'running') {
              return { ...step, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) };
            }
            return step;
          }));
          setAnalysisChain(prev => prev.map(s => s.status === 'running' ? { ...s, status: 'completed' as const, timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }) } : s));
          setAnalysisEndTime(Date.now());
        }
        if (createData.data.intent?.confidence) {
          setAnalysisConfidence(createData.data.intent.confidence);
        }
        
        let resultContent = content;
        if (artifacts.length > 0) {
          resultContent += `\n\n📎 生成产物: ${artifacts.map((a: any) => `${a.chain_phase}: ${a.file}`).join(' | ')}`;
        }
        if (summary) {
          resultContent += `\n🔗 执行链路: ${summary.chain_executed?.join(' → ') || 'N/A'}`;
        }

        const isSChain = summary?.chain_executed && summary.chain_executed.some((s: string) => s.startsWith('S'));
        
        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "thinking");
          const existingIdx = filtered.findIndex((m: any) => m.task_id === taskId);
          const newMsg = {
            role: "assistant",
            content: resultContent,
            intent: isTrade ? 'execute_trade' : intentType,
            confidence: createData.data.intent?.confidence,
            thinking_mode: thinkingMode,
            chain: summary?.chain_executed || [],
            task_id: taskId,
            artifacts: artifacts.length > 0 ? artifacts : undefined,
            chain_trace: (createData.data as any).chain_trace,
            trade_task_id: isTrade ? taskId : undefined,
            trade_confirmed: false,
            strategyChain: isSChain ? {
              scope: `${createData.data.intent?.entities?.symbol || 'BTC'} 策略分析`,
              currentStep: summary?.chain_executed?.[summary.chain_executed.length - 1] || null,
              steps: ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'].map((stepId, idx) => {
                const isExecuted = summary?.chain_executed?.includes(stepId);
                const isCurrent = stepId === summary?.chain_executed?.[summary.chain_executed.length - 1];
                let status = 'pending';
                if (isExecuted && !isCurrent) status = 'done';
                else if (isCurrent) status = 'active';
                const nameMap: Record<string, string> = {
                  'S1_RESEARCH': 'S1 调研',
                  'S2_ANALYSIS': 'S2 分析',
                  'S3_DESIGN': 'S3 设计',
                  'S4_VALIDATE': 'S4 验证',
                  'S5_EXECUTE': 'S5 执行',
                };
                return {
                  id: stepId,
                  number: idx + 1,
                  name: nameMap[stepId] || stepId,
                  status,
                };
              }),
              complexity: (summary?.chain_executed?.length || 0) <= 2 ? 'quick' : (summary?.chain_executed?.length || 0) <= 3 ? 'standard' : 'deep',
            } : undefined,
          };
          if (existingIdx >= 0) {
            const next = [...filtered];
            next[existingIdx] = { ...next[existingIdx], ...newMsg };
            return next;
          }
          return [...filtered, newMsg];
        });
        setIsLoading(false);
        return;
      }

      if (taskStatus === 'awaiting_clarification') {
        const content = createData.data.content || '';
        const clarificationState = createData.data.clarification_state;
        const summary = createData.data.execution_summary;

        if (summary?.chain_executed) {
          const executedChain = summary.chain_executed as string[];
          setAnalysisChain(prev => prev.map(step => {
            if (executedChain.includes(step.id)) {
              return {
                ...step,
                status: 'completed' as const,
                timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
              };
            }
            return step;
          }));
        }
        if (createData.data.intent?.confidence) {
          setAnalysisConfidence(createData.data.intent.confidence);
        }

        setMessages((prev) => {
          const filtered = prev.filter((m: any) => m.intent !== "thinking");
          return [
            ...filtered,
            {
              role: "assistant",
              content,
              intent: 'need_clarification',
              confidence: createData.data.intent?.confidence,
              thinking_mode: thinkingMode,
              chain: summary?.chain_executed || [],
              clarification_state: clarificationState,
            },
          ];
        });
        setIsLoading(false);
        return;
      }

      if (taskStatus === 'awaiting_confirmation') {
        const content = createData.data.content || '';
        const summary = createData.data.execution_summary;
        const stepConfirmation = createData.data.step_confirmation;

        if (summary?.chain_executed) {
          const executedChain = summary.chain_executed as string[];
          setAnalysisChain(prev => prev.map((step, idx) => {
            if (executedChain.includes(step.id)) {
              return {
                ...step,
                status: 'completed' as const,
                timestamp: new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
              };
            }
            const executedSet = new Set(executedChain);
            const nextIdx = prev.findIndex((s, i) => i > idx && !executedSet.has(s.id));
            if (idx === nextIdx - 1 && step.status === 'idle') {
              return { ...step, status: 'running' as const };
            }
            return step;
          }));
          setAnalysisEndTime(Date.now());
        }

        setMessages((prev) => {
          const filtered = prev.filter((m) => m.intent !== "thinking");
          return [
            ...filtered,
            {
              role: "assistant",
              content: content,
              intent: 'step_confirmation' as any,
              confidence: createData.data.intent?.confidence,
              thinking_mode: thinkingMode,
              chain: summary?.chain_executed || [],
              step_confirmation: stepConfirmation,
              step_task_id: taskId,
              awaiting_step: summary?.current_step,
              next_step: stepConfirmation?.next_step,
            },
          ];
        });
        setIsLoading(false);
        return;
      }

      if (taskStatus === 'processing') {
        await pollTaskResult(taskId);
        return;
      }
    } catch (error) {
      throw error;
    }
  };

  // ========== 交易确认交互 ==========
  const [scheduleTime, setScheduleTime] = useState('');

  /**
   * 交易确认/定时/取消
   */
  const handleTradeConfirm = async (taskId: string, action: 'confirm' | 'schedule' | 'cancel') => {
    try {
      const body: Record<string, unknown> = { task_id: taskId, action };
      if (action === 'schedule') {
        if (!scheduleTime) {
          alert('请输入定时时间（格式：HH:MM，如 14:30）');
          return;
        }
        // 将今天的日期与输入的时间组合为ISO8601
        const today = new Date().toISOString().slice(0, 10);
        body.scheduled_time = `${today}T${scheduleTime}:00`;
      }

      const res = await fetch('/api/task/confirm', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || `请求失败: ${res.status}`);
      }

      const data = await res.json();

      // 更新消息状态
      setMessages((prev) => prev.map((m) => {
        if (m.trade_task_id === taskId) {
          return {
            ...m,
            trade_confirmed: true,
            content: action === 'confirm'
              ? `✅ **交易已确认执行**\n\n${data.data.chain ? '🔗 链路: ' + data.data.chain.join(' → ') : ''}\n\n${data.data.message || ''}`
              : action === 'schedule'
              ? `🕐 **交易已定时**\n\n⏰ 执行时间: ${data.data.scheduled_time || scheduleTime}\n\n${data.data.message || ''}`
              : `🚫 **交易已取消**\n\n${data.data.message || ''}`,
          };
        }
        return m;
      }));

      setScheduleTime('');
    } catch (error) {
      console.error('Trade confirm error:', error);
      alert(`操作失败: ${error instanceof Error ? error.message : '未知错误'}`);
    }
  };

  const handleShowRightPanel = (type: RightPanelType) => {
    setRightPanelContent(type);
    setRightCollapsed(false);
  };

  // LLM 状态指示灯
  const renderStatusDot = (status: 'online' | 'offline' | 'degraded') => {
    const config = {
      online: { color: 'bg-green-500', text: '在线', textColor: 'text-green-500' },
      offline: { color: 'bg-red-500', text: '离线', textColor: 'text-red-500' },
      degraded: { color: 'bg-yellow-500', text: '降级', textColor: 'text-yellow-500' },
    };
    const c = config[status];
    return (
      <span className={`flex items-center gap-1 ${c.textColor}`}>
        <span className={`w-2 h-2 ${c.color} rounded-full animate-pulse`} />
        <span className="text-xs">{c.text}</span>
      </span>
    );
  };

  // LLM 提供商图标和名称映射
  const getProviderIcon = (provider: string) => {
    const map: Record<string, string> = {
      openai: '🤖',
      deepseek: '🔍',
      dashscope: '☁️',
      aliyun: '☁️',
      qwen: '☁️',
      anthropic: '🧠',
      claude: '🧠',
      custom: '⚙️',
      'openai-compatible': '⚙️',
    };
    return map[provider?.toLowerCase()] || '🤖';
  };

  const getProviderLabel = (provider: string) => {
    const map: Record<string, string> = {
      openai: 'OpenAI',
      deepseek: 'DeepSeek',
      dashscope: '阿里云百炼',
      aliyun: '阿里云百炼',
      qwen: '通义千问',
      anthropic: 'Anthropic',
      claude: 'Claude',
      custom: '自定义',
      'openai-compatible': 'OpenAI兼容',
    };
    return map[provider?.toLowerCase()] || provider;
  };

  const renderRightPanel = () => {
    switch (rightPanelContent) {
      case 'orchestration':
        return (
          <div>
            <div className="panel-title" style={{ marginBottom: 12 }}>
              🔀 编排追踪 · 三层架构
            </div>
            <OrchestrationPanel trace={orchestrationTrace} />
          </div>
        );
      case 'graph-compression':
        return (
          <div>
            <div className="panel-title" style={{ marginBottom: 0 }}>
              🗜️ 图结构上下文压缩 & 推理引擎
            </div>
            <GraphCompressionPanel
              messages={messages.map((m, idx) => ({
                id: `msg-${idx}`,
                role: m.role,
                content: m.content || '',
                timestamp: Date.now() - (messages.length - idx) * 60000,
                intent: m.intent,
                chain: m.chain,
              }))}
              sessionId="current-chat"
              defaultOpen={true}
            />
          </div>
        );
      case 'notebook':
        return (
          <div style={{ padding: 0 }}>
            <NotebookPanelWrapper />
          </div>
        );
      case 'llm':
        const llmConfigs = apiConfigs.filter(c => c.category === 'LLM');
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>🤖 大模型配置</div>
              <button
                onClick={() => setShowAddLlmForm(!showAddLlmForm)}
                className="px-3 py-1.5 text-xs bg-green-500 text-white rounded hover:bg-green-600 transition font-medium"
              >
                ➕ 添加
              </button>
            </div>

            {/* 服务状态总览 */}
            <div className="config-section">
              <div className="font-semibold mb-2">📊 服务状态</div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-[#8a8a8a]">LLM 连接</span>
                {renderStatusDot(llmStatus)}
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-[#8a8a8a]">当前模型</span>
                <span className="text-xs text-[#3b82f6] font-semibold">{llmModel}</span>
              </div>
              <div className="flex items-center justify-between mb-2">
                <span className="text-xs text-[#8a8a8a]">识别方法</span>
                <span className={`text-xs font-semibold ${intentMethod === 'llm' ? 'text-green-500' : 'text-yellow-500'}`}>
                  {intentMethod === 'llm' ? '🧠 LLM' : '📋 规则'}
                </span>
              </div>
              {llmStatus === 'degraded' && (
                <div className="mt-2 p-2 bg-yellow-500/10 border border-yellow-500/30 rounded text-xs text-yellow-500">
                  ⚠️ 免费额度已用完，已降级为规则识别。请配置您的 API Key。
                </div>
              )}
              {llmStatus === 'offline' && llmConfigs.length === 0 && (
                <div className="mt-2 p-2 bg-red-500/10 border border-red-500/30 rounded text-xs text-red-500">
                  ❌ 未配置大模型 API，请添加配置后使用。
                </div>
              )}
            </div>

            {/* 识别方法切换 */}
            <div className="config-section">
              <div className="font-semibold mb-2">🧠 识别方法</div>
              <div className="flex gap-2">
                <button
                  onClick={() => switchMethod('llm')}
                  className={`flex-1 px-3 py-2 text-xs rounded-md transition ${
                    intentMethod === 'llm'
                      ? 'bg-[#0066ff] text-white'
                      : 'bg-[#141414] text-[#8a8a8a] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🧠 LLM识别
                </button>
                <button
                  onClick={() => switchMethod('rule')}
                  className={`flex-1 px-3 py-2 text-xs rounded-md transition ${
                    intentMethod === 'rule'
                      ? 'bg-[#ffb74d] text-black'
                      : 'bg-[#141414] text-[#8a8a8a] hover:bg-[#1f1f1f]'
                  }`}
                >
                  📋 规则识别
                </button>
              </div>
              <div className="text-xs text-[#8a8a8a] mt-2">
                {intentMethod === 'llm'
                  ? '使用大模型进行意图识别，更精准但消耗API额度'
                  : '基于关键词规则匹配，不消耗API额度'}
              </div>
            </div>

            {/* 添加LLM配置表单 */}
            {showAddLlmForm && (
              <div className="config-section" style={{ borderLeft: '3px solid #8b5cf6' }}>
                <div className="font-semibold mb-2">➕ 新增大模型配置</div>
                <div className="space-y-2">
                  <div>
                    <label className="text-xs text-[#8a8a8a]">提供商</label>
                    <select
                      value={addLlmForm.provider}
                      onChange={(e) => setAddLlmForm({ ...addLlmForm, provider: e.target.value })}
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#8b5cf6]"
                    >
                      <option value="openai">OpenAI (GPT)</option>
                      <option value="deepseek">DeepSeek</option>
                      <option value="dashscope">阿里云百炼 (Qwen)</option>
                      <option value="anthropic">Anthropic (Claude)</option>
                      <option value="custom">自定义 (OpenAI兼容)</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">
                      配置名称 <span className="text-red-400">*</span>
                    </label>
                    <input
                      value={addLlmForm.label}
                      onChange={(e) => setAddLlmForm({ ...addLlmForm, label: e.target.value })}
                      placeholder="如: 默认模型 / GPT-4o / 工作号"
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#8b5cf6]"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">
                      API Key <span className="text-red-400">*</span>
                    </label>
                    <input
                      value={addLlmForm.apiKey}
                      onChange={(e) => setAddLlmForm({ ...addLlmForm, apiKey: e.target.value })}
                      placeholder="输入 API Key"
                      type="password"
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#8b5cf6]"
                    />
                  </div>
                  {addLlmForm.provider === 'custom' && (
                    <div>
                      <label className="text-xs text-[#8a8a8a]">
                        API Base URL <span className="text-red-400">*</span>
                      </label>
                      <input
                        value={addLlmForm.baseUrl}
                        onChange={(e) => setAddLlmForm({ ...addLlmForm, baseUrl: e.target.value })}
                        placeholder="如: https://api.example.com/v1"
                        className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#8b5cf6]"
                      />
                      <div className="text-xs text-[#666] mt-1">
                        支持所有 OpenAI 兼容的 API 中转服务
                      </div>
                    </div>
                  )}
                  {addLlmForm.provider !== 'custom' && addLlmForm.provider !== 'openai' && (
                    <div>
                      <label className="text-xs text-[#8a8a8a]">自定义 Base URL（可选）</label>
                      <input
                        value={addLlmForm.baseUrl}
                        onChange={(e) => setAddLlmForm({ ...addLlmForm, baseUrl: e.target.value })}
                        placeholder="留空使用官方地址"
                        className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#8b5cf6]"
                      />
                    </div>
                  )}
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={async () => {
                        if (!addLlmForm.label.trim()) {
                          alert('请输入配置名称');
                          return;
                        }
                        if (!addLlmForm.apiKey.trim()) {
                          alert('请输入 API Key');
                          return;
                        }
                        if (addLlmForm.provider === 'custom' && !addLlmForm.baseUrl.trim()) {
                          alert('自定义 API 需要填写 Base URL');
                          return;
                        }
                        try {
                          const res = await fetch('/api/config/api-keys', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              category: 'LLM',
                              provider: addLlmForm.provider,
                              label: addLlmForm.label,
                              apiKey: addLlmForm.apiKey,
                              secretKey: addLlmForm.apiKey,
                              baseUrl: addLlmForm.baseUrl || null,
                            }),
                          });
                          const data = await res.json();
                          if (data.success) {
                            setShowAddLlmForm(false);
                            setAddLlmForm({ provider: 'openai', label: '', apiKey: '', baseUrl: '' });
                            fetchApiConfigs();
                            showToast('success', '大模型配置添加成功');
                          } else {
                            alert(data.error || '添加失败');
                          }
                        } catch (error) {
                          alert('添加失败: ' + (error instanceof Error ? error.message : '未知错误'));
                        }
                      }}
                      className="flex-1 px-3 py-2 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-purple-700 transition font-medium"
                    >
                      💾 保存
                    </button>
                    <button
                      onClick={() => setShowAddLlmForm(false)}
                      className="px-3 py-2 text-xs bg-[#2a2a2a] text-[#8a8a8a] rounded-md hover:bg-[#1a1a1a] transition"
                    >
                      取消
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* LLM配置列表 */}
            {llmConfigs.length === 0 ? (
              <div className="config-section text-center">
                <div className="text-xs text-[#8a8a8a] mb-2">暂无大模型配置</div>
                <div className="text-xs text-[#8a8a8a] mb-3">点击上方"➕ 添加"按钮配置您的大模型 API</div>
                <div className="text-xs text-[#666]">
                  支持 OpenAI / DeepSeek / 百炼 / Claude 及所有 OpenAI 兼容接口
                </div>
              </div>
            ) : (
              llmConfigs.map((config) => (
                <div key={config.id} className="config-section">
                  <div className="flex justify-between items-center mb-2">
                    <div className="font-semibold">
                      {getProviderIcon(config.provider)} {getProviderLabel(config.provider)}
                    </div>
                    <div className="flex gap-1.5 items-center">
                      {config.isVerified ? (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-green-500/20 text-green-400">
                          ✅ 已验证
                        </span>
                      ) : (
                        <span className="px-2 py-0.5 rounded text-xs font-semibold bg-yellow-500/20 text-yellow-400">
                          ⚠️ 未验证
                        </span>
                      )}
                    </div>
                  </div>
                  <div className="text-xs text-[#8a8a8a] mb-1">
                    <span className="text-[#8b5cf6]">名称: {config.label}</span>
                  </div>
                  <div className="text-xs mb-1">
                    API Key: {config.keyHint || '•••••••'}
                  </div>
                  {config.baseUrl && (
                    <div className="text-xs text-[#666] mb-2">
                      Endpoint: {config.baseUrl}
                    </div>
                  )}
                  {config.lastVerifiedAt && (
                    <div className="text-xs text-[#666] mb-2">
                      最后验证: {new Date(config.lastVerifiedAt).toLocaleString('zh-CN')}
                    </div>
                  )}
                  {/* 测试结果显示 */}
                  {apiTestResult && apiTestResult[config.id] && (
                    <div className={`text-xs mb-2 p-2 rounded ${
                      apiTestResult[config.id].success
                        ? 'bg-green-500/10 text-green-400'
                        : 'bg-red-500/10 text-red-400'
                    }`}>
                      {apiTestResult[config.id].success ? '✅' : '❌'}{' '}
                      {apiTestResult[config.id].message}
                      {apiTestResult[config.id].latency !== undefined && (
                        <span className="ml-2 opacity-70">({apiTestResult[config.id].latency}ms)</span>
                      )}
                    </div>
                  )}
                  <div className="flex gap-2 flex-wrap">
                    <button
                      onClick={async () => {
                        setApiTesting(config.id);
                        try {
                          const res = await fetch('/api/config/api-keys/test', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              configId: config.id,
                              provider: config.provider,
                              category: 'LLM',
                            }),
                          });
                          const data = await res.json();
                          setApiTestResult(prev => ({
                            ...prev,
                            [config.id]: data.data || { success: false, message: data.error || '测试失败' }
                          }));
                          if (data.success && data.data?.success) {
                            fetchApiConfigs();
                            showToast('success', '连接测试成功');
                          }
                        } catch {} finally {
                          setApiTesting(null);
                        }
                      }}
                      disabled={apiTesting === config.id}
                      className="px-3 py-1.5 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition disabled:opacity-50"
                    >
                      {apiTesting === config.id ? '⏳ 测试中...' : '🔄 测试连接'}
                    </button>
                    <button
                      onClick={() => {
                        switchModel(config.id);
                        showToast('success', `已切换到 ${config.label}`);
                      }}
                      className="px-3 py-1.5 text-xs bg-[#8b5cf6] text-white rounded hover:bg-purple-700 transition"
                    >
                      ⭐ 设为默认
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('确定删除此大模型配置？')) return;
                        try {
                          await fetch(`/api/config/api-keys?id=${config.id}`, { method: 'DELETE' });
                          fetchApiConfigs();
                          showToast('success', '配置已删除');
                        } catch {}
                      }}
                      className="px-3 py-1.5 text-xs bg-red-500/80 text-white rounded hover:bg-red-600 transition"
                    >
                      🗑 删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        );
      case 'market':
        return (
          <div>
            <div className="panel-title">📈 行情卡片</div>

            {/* 交易对选择器 */}
            <div className="flex gap-1.5 mb-3">
              {['BTC', 'ETH', 'SOL'].map((sym) => (
                <button
                  key={sym}
                  onClick={() => {
                    const swapSymbol = `${sym}-USDT-SWAP`;
                    setSelectedSymbol(swapSymbol);
                    fetchMarketData(swapSymbol);
                  }}
                  className={`px-3 py-1.5 text-xs rounded-md transition ${
                    selectedSymbol === `${sym}-USDT-SWAP`
                      ? 'bg-[#0066ff] text-white'
                      : 'bg-[#141414] text-[#8a8a8a] hover:bg-[#1f1f1f]'
                  }`}
                >
                  {sym}
                </button>
              ))}
              <button
                onClick={() => fetchMarketData()}
                className="px-2 py-1.5 text-xs bg-[#141414] text-[#3b82f6] rounded-md hover:bg-[#1f1f1f] transition"
                title="刷新数据"
              >
                🔄
              </button>
            </div>

            {/* 行情数据 */}
            {marketLoading && !marketData ? (
              <div className="data-card">
                <div className="data-card-title">📊 {selectedSymbol}</div>
                <div className="data-card-content">
                  <span className="text-[#8a8a8a]">⏳ 加载中...</span>
                </div>
              </div>
            ) : marketError ? (
              <div className="data-card">
                <div className="data-card-title">📊 {selectedSymbol}</div>
                <div className="data-card-content">
                  <span className="text-red-500">❌ {marketError}</span>
                </div>
              </div>
            ) : marketData ? (
              <div className="data-card">
                <div className="data-card-title">📊 {marketData.symbol}</div>
                <div className="data-card-content">
                  {marketData.price ? (
                    <>
                      <div className="text-xl font-bold mb-1">
                        ${typeof marketData.price === 'number' ? marketData.price.toLocaleString() : marketData.price}
                        {marketData.change24h !== undefined && marketData.change24h !== null && (
                          <span className={`text-sm ml-2 ${marketData.change24h >= 0 ? 'text-red-500' : 'text-green-500'}`}>
                            {marketData.change24h >= 0 ? '▲' : '▼'} {Math.abs(marketData.change24h).toFixed(2)}%
                          </span>
                        )}
                      </div>
                      <div className="grid grid-cols-2 gap-x-4 gap-y-0.5 text-xs text-[#8a8a8a]">
                        {marketData.open24h && <div>开盘: ${typeof marketData.open24h === 'number' ? marketData.open24h.toLocaleString() : marketData.open24h}</div>}
                        {marketData.high24h && <div>24h高: <span className="text-red-400">${typeof marketData.high24h === 'number' ? marketData.high24h.toLocaleString() : marketData.high24h}</span></div>}
                        {marketData.low24h && <div>24h低: <span className="text-green-400">${typeof marketData.low24h === 'number' ? marketData.low24h.toLocaleString() : marketData.low24h}</span></div>}
                        {marketData.volume24h && (
                          <div>24h量: {(() => {
                            const v = parseFloat(String(marketData.volume24h).replace(/,/g, ''));
                            if (isNaN(v)) return marketData.volume24h;
                            if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
                            if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
                            if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
                            return v.toFixed(0);
                          })()}</div>
                        )}
                      </div>
                    </>
                  ) : (
                    <div className="text-[#8a8a8a]">数据解析中，请刷新重试</div>
                  )}
                  {marketData.fundingRate && (
                    <div className="mt-1 text-xs">
                      资金费率: <span className={parseFloat(marketData.fundingRate) >= 0 ? 'text-red-500' : 'text-green-500'}>
                        {parseFloat(marketData.fundingRate) >= 0 ? '+' : ''}
                        {(parseFloat(marketData.fundingRate) * 100).toFixed(4)}%
                      </span>
                    </div>
                  )}
                  {marketData.positions && marketData.positions.length > 0 ? (
                    <div className="mt-2">
                      <div className="text-[#3b82f6] font-semibold">持仓信息:</div>
                      {marketData.positions.map((pos, idx) => (
                        <div key={idx} className="mt-1">
                          {Boolean(pos.symbol) && <span>{String(pos.symbol)}</span>}
                          {Boolean(pos.side) && <span> | {String(pos.side)}</span>}
                          {Boolean(pos.leverage) && <span> | {String(pos.leverage)}x</span>}
                          {pos.upl !== undefined && <span className={Number(pos.upl) >= 0 ? 'text-red-500' : 'text-green-500'}> | UPL: {String(pos.upl)}</span>}
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-1">持仓: <span className="text-[#8a8a8a]">空仓</span></div>
                  )}
                  <div className="text-[10px] text-[#555] mt-2">
                    更新: {marketData.timestamp ? new Date(marketData.timestamp).toLocaleTimeString('zh-CN') : 'N/A'}
                  </div>
                </div>
              </div>
            ) : (
              <div className="data-card">
                <div className="data-card-title">📊 {selectedSymbol}</div>
                <div className="data-card-content text-[#8a8a8a]">暂无数据</div>
              </div>
            )}

            {/* 行情查询 */}
            <div className="config-section mt-3">
              <div className="font-semibold mb-2">🔍 自定义查询</div>
              <div className="flex gap-2">
                <input
                  type="text"
                  placeholder="如: DOGE, XRP-USDT"
                  className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff] transition"
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') {
                      const val = (e.target as HTMLInputElement).value.trim();
                      if (val) {
                        const symbol = val.includes('-') ? val.toUpperCase() : `${val.toUpperCase()}-USDT-SWAP`;
                        setSelectedSymbol(symbol);
                        fetchMarketData(symbol);
                      }
                    }
                  }}
                />
                <button
                  onClick={() => fetchMarketData()}
                  className="px-3 py-1.5 text-xs bg-[#0066ff] text-white rounded-md hover:bg-blue-700 transition"
                >
                  查询
                </button>
              </div>
            </div>
          </div>
        );
      case 'signal':
        return (
          <div>
            <div className="panel-title">🎯 评分卡片</div>
            <div className="data-card">
              <div className="data-card-title">🎯 交易评分</div>
              <div className="data-card-content">
                总分: <span className="text-red-500 font-semibold">12/80</span> → 偏空<br />
                优势评分: -35 (强空方优势)<br />
                宏观: 3/10 (CPI超预期)<br />
                技术: 5/10 (关键均线下方)<br />
                情绪: 4/10 (恐惧持续)<br />
                <span className="text-yellow-500">建议: 观望为主，谨慎做空</span>
              </div>
            </div>
          </div>
        );
      case 'position':
        return (
          <div>
            <div className="panel-title">💼 持仓卡片</div>
            <div className="data-card">
              <div className="data-card-title">💼 当前持仓</div>
              <div className="data-card-content">
                状态: <span className="text-[#8a8a8a]">空仓</span><br />
                <span className="text-green-500">OR</span><br />
                方向: 做多 | 杠杆: 2x<br />
                未实现盈亏: <span className="text-green-500">+$140.5</span>
              </div>
            </div>
          </div>
        );
      case 'api':
        const exchangeConfigs = apiConfigs.filter(c => c.category === 'EXCHANGE');
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>⚙️ 交易所API</div>
              <button
                onClick={() => setShowAddApiForm(!showAddApiForm)}
                className="px-3 py-1.5 text-xs bg-green-500 text-white rounded hover:bg-green-600 transition font-medium"
              >
                ➕ 添加
              </button>
            </div>

            {/* 添加API表单 */}
            {showAddApiForm && (
              <div className="config-section" style={{ borderLeft: '3px solid #22c55e' }}>
                <div className="font-semibold mb-2">➕ 新增交易所API</div>
                <div className="space-y-2">
                  <div>
                    <label className="text-xs text-[#8a8a8a]">交易所</label>
                    <select
                      value={addApiForm.provider}
                      onChange={(e) => setAddApiForm({ ...addApiForm, provider: e.target.value, category: 'EXCHANGE' })}
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    >
                      <option value="okx">OKX</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">
                      账户名 <span className="text-red-400">*</span>
                    </label>
                    <input
                      value={addApiForm.label}
                      onChange={(e) => setAddApiForm({ ...addApiForm, label: e.target.value })}
                      placeholder="如: 模拟盘1 / 实盘主账户"
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">API Key</label>
                    <input
                      value={addApiForm.apiKey}
                      onChange={(e) => setAddApiForm({ ...addApiForm, apiKey: e.target.value })}
                      placeholder="输入API Key"
                      type="password"
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    />
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">Secret Key</label>
                    <input
                      value={addApiForm.secretKey}
                      onChange={(e) => setAddApiForm({ ...addApiForm, secretKey: e.target.value })}
                      placeholder="输入Secret Key"
                      type="password"
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    />
                  </div>
                  {addApiForm.provider === 'okx' && (
                    <div>
                      <label className="text-xs text-[#8a8a8a]">Passphrase</label>
                      <input
                        value={addApiForm.passphrase}
                        onChange={(e) => setAddApiForm({ ...addApiForm, passphrase: e.target.value })}
                        placeholder="输入Passphrase"
                        type="password"
                        className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                      />
                    </div>
                  )}
                  <div>
                    <label className="text-xs text-[#8a8a8a]">环境</label>
                    <select
                      value={addApiForm.environment}
                      onChange={(e) => setAddApiForm({ ...addApiForm, environment: e.target.value })}
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    >
                      <option value="demo">Demo模拟盘</option>
                      <option value="live">Live实盘</option>
                    </select>
                  </div>
                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={async () => {
                        // 前端验证
                        if (!addApiForm.label.trim()) {
                          alert('请输入账户名，用于区分不同的API配置');
                          return;
                        }
                        if (!addApiForm.apiKey.trim()) {
                          alert('请输入API Key');
                          return;
                        }
                        if (!addApiForm.secretKey.trim()) {
                          alert('请输入Secret Key');
                          return;
                        }
                        try {
                          const res = await fetch('/api/config/api-keys', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify(addApiForm),
                          });
                          const data = await res.json();
                          if (data.success) {
                            setShowAddApiForm(false);
                            setAddApiForm({ category: 'EXCHANGE', provider: 'okx', label: '', apiKey: '', secretKey: '', passphrase: '', environment: 'demo' });
                            fetchApiConfigs();
                          } else {
                            alert(data.error || '添加失败');
                          }
                        } catch (error) {
                          alert('添加失败: ' + (error instanceof Error ? error.message : '未知错误'));
                        }
                      }}
                      className="flex-1 px-3 py-2 text-xs bg-[#0066ff] text-white rounded-md hover:bg-blue-700 transition font-medium"
                    >
                      💾 保存
                    </button>
                    <button
                      onClick={() => setShowAddApiForm(false)}
                      className="px-3 py-2 text-xs bg-[#2a2a2a] text-[#8a8a8a] rounded-md hover:bg-[#1a1a1a] transition"
                    >
                      取消
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 交易所API配置列表 */}
            {exchangeConfigs.length === 0 ? (
              <div className="config-section text-center">
                <div className="text-xs text-[#8a8a8a] mb-2">暂无交易所API配置</div>
                <div className="text-xs text-[#8a8a8a]">点击上方"➕ 添加"按钮配置交易所 API（大模型配置请切换到 🤖 LLM 面板）</div>
              </div>
            ) : (
              exchangeConfigs.map((config) => (
                <div key={config.id} className="config-section">
                  <div className="flex justify-between items-center mb-2">
                    <div className="font-semibold">{config.provider.toUpperCase()}</div>
                    <div className="flex gap-1.5 items-center">
                      <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                        config.environment === 'live' ? 'bg-red-500/20 text-red-400' : 'bg-green-500 text-black'
                      }`}>
                        {config.environment === 'live' ? '● Live' : '● Demo'}
                      </span>
                    </div>
                  </div>
                  <div className="text-xs text-[#8a8a8a] mb-1">
                    <span className="text-[#3b82f6]">账户: {config.label}</span>
                  </div>
                  <div className="text-xs mb-2">
                    <div>API Key: {config.keyHint || '•••••••'} <span className="text-[#3b82f6] cursor-pointer">[👁]</span></div>
                  </div>
                  {config.isVerified ? (
                    <div className="text-green-500 text-xs mb-2">
                      ✅ 已验证 {config.lastVerifiedAt ? `(${new Date(config.lastVerifiedAt).toLocaleDateString('zh-CN')})` : ''}
                    </div>
                  ) : (
                    <div className="text-yellow-500 text-xs mb-2">⚠️ 未验证</div>
                  )}
                  {/* 测试结果显示 */}
                  {apiTestResult && apiTestResult[config.id] && (
                    <div className={`text-xs mb-2 p-2 rounded ${
                      apiTestResult[config.id].success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'
                    }`}>
                      {apiTestResult[config.id].success ? '✅' : '❌'} {apiTestResult[config.id].message}
                    </div>
                  )}
                  <div className="flex gap-2">
                    <button
                      onClick={async () => {
                        setApiTesting(config.id);
                        try {
                          const res = await fetch('/api/config/api-keys/test', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ configId: config.id, provider: config.provider, environment: config.environment }),
                          });
                          const data = await res.json();
                          setApiTestResult(prev => ({
                            ...prev,
                            [config.id]: data.data || { success: false, message: data.error || '测试失败' }
                          }));
                          if (data.success && data.data?.success) {
                            fetchApiConfigs(); // 刷新验证状态
                          }
                        } catch {} finally {
                          setApiTesting(null);
                        }
                      }}
                      disabled={apiTesting === config.id}
                      className="px-3 py-1.5 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition disabled:opacity-50"
                    >
                      {apiTesting === config.id ? '⏳ 测试中...' : '测试连接'}
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('确定删除此API配置？')) return;
                        try {
                          await fetch(`/api/config/api-keys?id=${config.id}`, { method: 'DELETE' });
                          fetchApiConfigs();
                        } catch {}
                      }}
                      className="px-3 py-1.5 text-xs bg-red-500 text-white rounded hover:bg-red-600 transition"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        );
      case 'trading':
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>💰 交易设置</div>
              <button
                onClick={() => setTradingEditing(!tradingEditing)}
                className={`px-3 py-1.5 text-xs rounded transition font-medium ${
                  tradingEditing ? 'bg-[#0066ff] text-white' : 'bg-[#2a2a2a] text-[#e0e0e0] border border-[#0066ff]'
                }`}
              >
                {tradingEditing ? '✕ 取消' : '✏️ 编辑'}
              </button>
            </div>

            {tradingLoading && !tradingParams ? (
              <div className="config-section text-center text-xs text-[#8a8a8a]">⏳ 加载中...</div>
            ) : tradingError ? (
              <div className="config-section text-center">
                <div className="text-xs text-red-400 mb-2">⚠️ {tradingError}</div>
                <button
                  onClick={() => fetchTradingParams()}
                  className="px-3 py-1.5 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition"
                >
                  重新加载
                </button>
              </div>
            ) : tradingParams ? (
              <>
                {/* 关联交易所 - 四选择器 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">🔗 关联交易所</div>
                  {apiConfigs.length > 0 ? (
                    <div className="space-y-2">
                      {/* 交易所选择 */}
                      <div>
                        <label className="text-xs text-[#8a8a8a] mb-1 block">交易所</label>
                        <select
                          value={exchangeSelect.exchange}
                          onChange={(e) => {
                            const newExchange = e.target.value;
                            // 筛选该交易所的所有配置
                            const exchangeConfigs = apiConfigs.filter(c => c.provider === newExchange);
                            // 获取该交易所下的所有账户名
                            const labels = [...new Set(exchangeConfigs.map(c => c.label || '默认账户'))];
                            // 自动选择第一个账户名
                            const firstLabel = labels[0] || '默认账户';
                            // 获取该账户名+当前环境的configId
                            const firstConfig = apiConfigs.find(c => 
                              c.provider === newExchange && 
                              (c.label || '默认账户') === firstLabel &&
                              c.environment === exchangeSelect.environment
                            );
                            const firstConfigId = firstConfig?.id || apiConfigs.find(c => c.provider === newExchange && (c.label || '默认账户') === firstLabel)?.id || '';
                            // 检查该账户是否有实盘/模拟盘配置
                            const hasLive = exchangeConfigs.some(c => (c.label || '默认账户') === firstLabel && c.environment === 'live');
                            const hasDemo = exchangeConfigs.some(c => (c.label || '默认账户') === firstLabel && c.environment === 'demo');
                            const newEnv = hasLive ? 'live' : (hasDemo ? 'demo' : 'demo');
                            handleExchangeChange(newExchange, firstConfigId, firstLabel, newEnv, exchangeSelect.symbol);
                          }}
                          className="w-full bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        >
                          {Array.from(new Set(apiConfigs.map(c => c.provider))).map(provider => (
                            <option key={provider} value={provider}>
                              {provider.toUpperCase()}
                            </option>
                          ))}
                        </select>
                      </div>

                      {/* 账户名选择 */}
                      <div>
                        <label className="text-xs text-[#8a8a8a] mb-1 block">账户名</label>
                        <select
                          value={exchangeSelect.accountLabel}
                          onChange={(e) => {
                            const newLabel = e.target.value;
                            // 获取该账户名+当前环境的configId
                            const config = apiConfigs.find(c => 
                              c.provider === exchangeSelect.exchange && 
                              (c.label || '默认账户') === newLabel &&
                              c.environment === exchangeSelect.environment
                            );
                            const configId = config?.id || apiConfigs.find(c => c.provider === exchangeSelect.exchange && (c.label || '默认账户') === newLabel)?.id || '';
                            const newEnv = (config?.environment as 'live' | 'demo') || 'demo';
                            handleExchangeChange(exchangeSelect.exchange, configId, newLabel, newEnv, exchangeSelect.symbol);
                          }}
                          className="w-full bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        >
                          {[...new Set(apiConfigs.filter(c => c.provider === exchangeSelect.exchange).map(c => c.label || '默认账户'))].map(label => (
                            <option key={label} value={label}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </div>

                      {/* 账户类型选择 */}
                      <div>
                        <label className="text-xs text-[#8a8a8a] mb-1 block">账户</label>
                        <div className="flex gap-1.5">
                          <button
                            onClick={async () => {
                              // 获取该账户名+实盘环境的configId
                              const liveConfig = apiConfigs.find(c => 
                                c.provider === exchangeSelect.exchange && 
                                (c.label || '默认账户') === exchangeSelect.accountLabel && 
                                c.environment === 'live'
                              );
                              const liveConfigId = liveConfig?.id || '';
                              if (!liveConfigId) {
                                showToast('error', '该账户未配置实盘');
                                return;
                              }
                              await handleExchangeChange(exchangeSelect.exchange, liveConfigId, exchangeSelect.accountLabel, 'live', exchangeSelect.symbol);
                            }}
                            className={`flex-1 px-3 py-1.5 text-xs rounded transition font-medium ${
                              exchangeSelect.environment === 'live'
                                ? 'bg-red-500/20 text-red-400 border border-red-500'
                                : 'bg-[#141414] text-[#8a8a8a] border border-[#2a2a2a] hover:border-red-500'
                            }`}
                          >
                            🔴 实盘
                          </button>
                          <button
                            onClick={async () => {
                              // 获取该账户名+模拟盘环境的configId
                              const demoConfig = apiConfigs.find(c => 
                                c.provider === exchangeSelect.exchange && 
                                (c.label || '默认账户') === exchangeSelect.accountLabel && 
                                c.environment === 'demo'
                              );
                              const demoConfigId = demoConfig?.id || '';
                              if (!demoConfigId) {
                                showToast('error', '该账户未配置模拟盘');
                                return;
                              }
                              await handleExchangeChange(exchangeSelect.exchange, demoConfigId, exchangeSelect.accountLabel, 'demo', exchangeSelect.symbol);
                            }}
                            className={`flex-1 px-3 py-1.5 text-xs rounded transition font-medium ${
                              exchangeSelect.environment === 'demo'
                                ? 'bg-green-500/20 text-green-400 border border-green-500'
                                : 'bg-[#141414] text-[#8a8a8a] border border-[#2a2a2a] hover:border-green-500'
                            }`}
                          >
                            🟢 模拟
                          </button>
                        </div>
                      </div>

                      {/* 交易币种选择 */}
                      <div>
                        <label className="text-xs text-[#8a8a8a] mb-1 block">币种</label>
                        <select
                          value={exchangeSelect.symbol}
                          onChange={(e) => handleExchangeChange(exchangeSelect.exchange, exchangeSelect.configId, exchangeSelect.accountLabel, exchangeSelect.environment, e.target.value)}
                          className="w-full bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        >
                          <option value="USDT">USDT (计息/保证金)</option>
                          <option value="BTC">BTC</option>
                          <option value="ETH">ETH</option>
                        </select>
                      </div>

                      {/* 实时余额显示 */}
                      {balanceLoading ? (
                        <div className="text-xs text-[#8a8a8a] text-center py-2">⏳ 获取余额中...</div>
                      ) : realtimeBalance ? (
                        <div className="bg-[#0a0a0a] rounded-md p-2 mt-2">
                          <div className="grid grid-cols-2 gap-2 text-xs">
                            <div>
                              <div className="text-[#8a8a8a]">可用</div>
                              <div className="text-green-400 font-semibold">{realtimeBalance.available.toLocaleString()} {exchangeSelect.symbol}</div>
                            </div>
                            <div>
                              <div className="text-[#8a8a8a]">总权益</div>
                              <div className="text-[#3b82f6] font-semibold">{realtimeBalance.totalEquity.toLocaleString()} {exchangeSelect.symbol}</div>
                            </div>
                            {realtimeBalance.marginUsed > 0 && (
                              <div>
                                <div className="text-[#8a8a8a]">保证金</div>
                                <div className="text-yellow-400 font-semibold">{realtimeBalance.marginUsed.toLocaleString()}</div>
                              </div>
                            )}
                            {realtimeBalance.unrealizedPnl !== 0 && (
                              <div>
                                <div className="text-[#8a8a8a]">未实现</div>
                                <div className={`font-semibold ${realtimeBalance.unrealizedPnl >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                  {realtimeBalance.unrealizedPnl >= 0 ? '+' : ''}{realtimeBalance.unrealizedPnl.toLocaleString()}
                                </div>
                              </div>
                            )}
                          </div>
                        </div>
                      ) : (
                        <div className="text-xs text-yellow-500 text-center py-2">⚠️ 无法获取余额</div>
                      )}
                    </div>
                  ) : (
                    <>
                      <div className="text-xs text-yellow-500 mb-1">○ 未配置交易所API</div>
                      <button
                        onClick={() => setRightPanelContent('api')}
                        className="text-xs text-[#3b82f6] hover:underline mt-1"
                      >
                        → 前往交易所API配置
                      </button>
                    </>
                  )}
                </div>

                {/* 交易可用资金 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">💵 交易可用资金</div>
                  {tradingEditing ? (
                    <div className="space-y-2">
                      <div>
                        <label className="text-xs text-[#8a8a8a] flex justify-between">
                          <span>可用余额 (USDT)</span>
                          {realtimeBalance && realtimeBalance.available > 0 && (
                            <button
                              onClick={() => {
                                setTradingEditForm(prev => ({ ...prev, availableCapital: realtimeBalance.available }));
                                showToast('success', `已同步: ${realtimeBalance.available.toLocaleString()} USDT`);
                              }}
                              className="text-[#3b82f6] hover:underline"
                            >
                              [同步余额]
                            </button>
                          )}
                        </label>
                        <input
                          type="number"
                          value={tradingEditForm.availableCapital as string || ''}
                          onChange={(e) => setTradingEditForm({ ...tradingEditForm, availableCapital: e.target.value ? parseFloat(e.target.value) : '' })}
                          className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          placeholder="输入可用余额"
                        />
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="text-lg font-semibold text-[#3b82f6]">
                        {tradingParams.params.availableCapital != null ? `${tradingParams.params.availableCapital.toLocaleString()} USDT` : '未设置'}
                      </div>
                      <div className="text-xs text-[#8a8a8a] mt-1">
                        每次交易: {Math.round(tradingParams.params.capitalPercentage * 100)}% 账户余额
                      </div>
                    </>
                  )}
                  <div className="text-xs text-[#8a8a8a] mt-2">ℹ️ 百分比由系统统一设定，确保策略一致性</div>
                </div>

                {/* 交易模式 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">🔄 交易模式</div>
                  {tradingEditing ? (
                    <>
                      {/* 交易模式选择 - 标签式 */}
                      <div className="flex flex-wrap gap-1.5 mb-3">
                        {(['SPOT_MODE', 'SWAP_MODE'] as const).map((mode) => (
                          <button
                            key={mode}
                            onClick={() => setTradingEditForm({ ...tradingEditForm, tradeMode: mode })}
                            className={`px-3 py-1.5 text-xs rounded transition font-medium ${
                              tradingEditForm.tradeMode === mode
                                ? 'bg-[#0066ff] text-white'
                                : 'bg-[#141414] text-[#8a8a8a] border border-[#2a2a2a] hover:border-[#0066ff]'
                            }`}
                          >
                            {mode === 'SPOT_MODE' ? '💰 现货' : '⚡ 合约'}
                          </button>
                        ))}
                      </div>
                      {/* 合约模式特有设置 */}
                      {tradingEditForm.tradeMode !== 'SPOT_MODE' && (
                        <div className="space-y-2 pl-2 border-l-2 border-[#0066ff]/30">
                          <div>
                            <label className="text-xs text-[#8a8a8a]">保证金模式</label>
                            <select
                              value={tradingEditForm.marginMode as string || 'CROSS'}
                              onChange={(e) => setTradingEditForm({ ...tradingEditForm, marginMode: e.target.value })}
                              className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                            >
                              <option value="CROSS">全仓 (Cross)</option>
                              <option value="ISOLATED">逐仓 (Isolated)</option>
                            </select>
                          </div>
                          <div>
                            <label className="text-xs text-[#8a8a8a]">持仓模式</label>
                            <select
                              value={tradingEditForm.positionMode as string || 'NET'}
                              onChange={(e) => setTradingEditForm({ ...tradingEditForm, positionMode: e.target.value })}
                              className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                            >
                              <option value="NET">净仓 (One-way)</option>
                              <option value="HEDGE">逐仓双向 (Hedge)</option>
                            </select>
                          </div>
                        </div>
                      )}
                    </>
                  ) : (
                    <>
                      <div className="flex items-center gap-2 mb-2">
                        <span className={`px-2.5 py-1 text-xs rounded font-medium ${
                          tradingParams.params.tradeMode === 'SPOT_MODE'
                            ? 'bg-[#0066ff] text-white'
                            : 'bg-[#eab308]/20 text-[#eab308]'
                        }`}>
                          {tradingParams.params.tradeMode === 'SPOT_MODE' ? '💰 现货' : '⚡ 合约'}
                        </span>
                        <span className="text-xs text-[#8a8a8a]">
                          {tradingParams.params.tradeType}
                        </span>
                      </div>
                      {tradingParams.params.tradeMode !== 'SPOT_MODE' && (
                        <div className="text-xs text-[#8a8a8a] space-y-0.5 pl-2">
                          <div>保证金: {tradingParams.params.marginMode === 'ISOLATED' ? '逐仓' : '全仓'}</div>
                          <div>持仓模式: {tradingParams.params.positionMode === 'HEDGE' ? '逐仓双向' : '净仓'}</div>
                        </div>
                      )}
                    </>
                  )}
                </div>

                {/* 杠杆设置 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">⚡ 杠杆设置</div>
                  {tradingEditing ? (
                    <div>
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs text-[#8a8a8a]">1x</span>
                        <span className="text-sm font-semibold text-[#3b82f6]">{String(tradingEditForm.leverageMax)}x</span>
                        <span className="text-xs text-[#8a8a8a]">5x</span>
                      </div>
                      <input
                        type="range"
                        min={1}
                        max={5}
                        step={1}
                        value={tradingEditForm.leverageMax as number}
                        onChange={(e) => setTradingEditForm({ ...tradingEditForm, leverageMax: parseInt(e.target.value) })}
                        className="w-full h-1.5 bg-[#2a2a2a] rounded-lg appearance-none cursor-pointer accent-[#3b82f6]"
                      />
                      {(tradingEditForm.leverageMax as number) >= 3 && (
                        <div className={`mt-2 p-2 rounded text-xs ${
                          (tradingEditForm.leverageMax as number) >= 5 ? 'bg-red-500/10 text-red-400 border border-red-500/30' : 'bg-yellow-500/10 text-yellow-500 border border-yellow-500/30'
                        }`}>
                          ⚠️ {(tradingEditForm.leverageMax as number) >= 5 ? '5x杠杆风险极高！' : `${tradingEditForm.leverageMax}x杠杆风险较高`}
                        </div>
                      )}
                    </div>
                  ) : (
                    <div className="flex items-center gap-2">
                      <div className="flex-1 h-2 bg-[#2a2a2a] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${((tradingParams.params.leverageMax - 1) / 4) * 100}%`,
                            backgroundColor: tradingParams.params.leverageMax >= 5 ? '#ef4444' : tradingParams.params.leverageMax >= 3 ? '#eab308' : '#3b82f6',
                          }}
                        />
                      </div>
                      <span className="text-sm font-semibold text-[#3b82f6] min-w-[36px] text-right">{tradingParams.params.leverageMax}x</span>
                    </div>
                  )}
                </div>

                {/* 亏损限制 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">🛡️ 亏损限制</div>
                  {tradingEditing ? (
                    <div className="space-y-3">
                      <div>
                        <label className="text-xs text-[#8a8a8a]">日亏损限制</label>
                        <div className="flex gap-2 mt-1">
                          <input
                            type="number"
                            value={tradingEditForm.dailyLossLimit as number}
                            onChange={(e) => {
                              const val = parseFloat(e.target.value) || 0;
                              setTradingEditForm({
                                ...tradingEditForm,
                                dailyLossLimit: val,
                                dailyLossPercent: tradingParams?.params?.availableCapital ? Math.round((val / tradingParams.params.availableCapital) * 10000) / 100 : tradingEditForm.dailyLossPercent,
                              });
                            }}
                            className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          />
                          <span className="text-xs text-[#8a8a8a] self-center">USDT /</span>
                          <input
                            type="number"
                            value={tradingEditForm.dailyLossPercent as number}
                            onChange={(e) => {
                              const val = parseFloat(e.target.value) || 0;
                              setTradingEditForm({
                                ...tradingEditForm,
                                dailyLossPercent: val,
                                dailyLossLimit: tradingParams?.params?.availableCapital ? Math.round(tradingParams.params.availableCapital * val / 100 * 100) / 100 : tradingEditForm.dailyLossLimit,
                              });
                            }}
                            className="w-16 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          />
                          <span className="text-xs text-[#8a8a8a] self-center">%</span>
                        </div>
                      </div>
                      <div>
                        <label className="text-xs text-[#8a8a8a]">账户亏损限制</label>
                        <div className="flex gap-2 mt-1">
                          <input
                            type="number"
                            value={tradingEditForm.accountLossLimit as number}
                            onChange={(e) => {
                              const val = parseFloat(e.target.value) || 0;
                              setTradingEditForm({
                                ...tradingEditForm,
                                accountLossLimit: val,
                                accountLossPercent: tradingParams?.params?.availableCapital ? Math.round((val / tradingParams.params.availableCapital) * 10000) / 100 : tradingEditForm.accountLossPercent,
                              });
                            }}
                            className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          />
                          <span className="text-xs text-[#8a8a8a] self-center">USDT /</span>
                          <input
                            type="number"
                            value={tradingEditForm.accountLossPercent as number}
                            onChange={(e) => {
                              const val = parseFloat(e.target.value) || 0;
                              setTradingEditForm({
                                ...tradingEditForm,
                                accountLossPercent: val,
                                accountLossLimit: tradingParams?.params?.availableCapital ? Math.round(tradingParams.params.availableCapital * val / 100 * 100) / 100 : tradingEditForm.accountLossLimit,
                              });
                            }}
                            className="w-16 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          />
                          <span className="text-xs text-[#8a8a8a] self-center">%</span>
                        </div>
                      </div>
                      <div className="text-xs text-[#8a8a8a]">ℹ️ 绝对金额与百分比两个维度取更严格值</div>
                    </div>
                  ) : (
                    <div className="space-y-2">
                      <div className="flex justify-between items-center">
                        <span className="text-xs text-[#8a8a8a]">日亏损限制</span>
                        <span className="text-xs text-[#e0e0e0] font-medium">{tradingParams.params.dailyLossLimit} USDT / {Math.round(tradingParams.params.dailyLossPercent * 100)}%</span>
                      </div>
                      <div className="flex justify-between items-center">
                        <span className="text-xs text-[#8a8a8a]">账户亏损限制</span>
                        <span className="text-xs text-[#e0e0e0] font-medium">{tradingParams.params.accountLossLimit} USDT / {Math.round(tradingParams.params.accountLossPercent * 100)}%</span>
                      </div>
                    </div>
                  )}
                </div>

                {/* 风险偏好 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">🎯 风险偏好</div>
                  {tradingEditing ? (
                    <div className="flex gap-1.5">
                      {(['CONSERVATIVE', 'MODERATE', 'AGGRESSIVE'] as const).map((tol) => (
                        <button
                          key={tol}
                          onClick={() => setTradingEditForm({ ...tradingEditForm, riskTolerance: tol })}
                          className={`flex-1 px-2 py-1.5 text-xs rounded transition font-medium ${
                            tradingEditForm.riskTolerance === tol
                              ? tol === 'CONSERVATIVE' ? 'bg-green-500 text-white'
                                : tol === 'AGGRESSIVE' ? 'bg-red-500 text-white'
                                : 'bg-[#0066ff] text-white'
                              : 'bg-[#141414] text-[#8a8a8a] border border-[#2a2a2a]'
                          }`}
                        >
                          {tol === 'CONSERVATIVE' ? '🛡️ 保守' : tol === 'MODERATE' ? '⚖️ 适中' : '🔥 激进'}
                        </button>
                      ))}
                    </div>
                  ) : (
                    <div className="text-xs">
                      <span className={`px-2 py-0.5 rounded font-medium ${
                        tradingParams.params.riskTolerance === 'CONSERVATIVE' ? 'bg-green-500/20 text-green-400'
                          : tradingParams.params.riskTolerance === 'AGGRESSIVE' ? 'bg-red-500/20 text-red-400'
                          : 'bg-[#0066ff]/20 text-[#3b82f6]'
                      }`}>
                        {tradingParams.params.riskTolerance === 'CONSERVATIVE' ? '🛡️ 保守' : tradingParams.params.riskTolerance === 'AGGRESSIVE' ? '🔥 激进' : '⚖️ 适中'}
                      </span>
                    </div>
                  )}
                </div>

                {/* 今日状态 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">📊 今日状态</div>
                  <div className="space-y-2">
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[#8a8a8a]">日亏损</span>
                        <span className={tradingParams.liveStatus.todayLoss > 0 ? 'text-red-400' : 'text-[#8a8a8a]'}>
                          {tradingParams.liveStatus.todayLoss.toFixed(1)} / {tradingParams.params.dailyLossLimit} USDT
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-[#2a2a2a] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.min((tradingParams.liveStatus.todayLoss / tradingParams.params.dailyLossLimit) * 100, 100)}%`,
                            backgroundColor: tradingParams.liveStatus.todayLoss / tradingParams.params.dailyLossLimit > 0.8 ? '#ef4444' : '#3b82f6',
                          }}
                        />
                      </div>
                    </div>
                    <div>
                      <div className="flex justify-between text-xs mb-1">
                        <span className="text-[#8a8a8a]">账户亏损</span>
                        <span className={tradingParams.liveStatus.totalLoss > 0 ? 'text-red-400' : 'text-[#8a8a8a]'}>
                          {tradingParams.liveStatus.totalLoss.toFixed(1)} / {tradingParams.params.accountLossLimit} USDT
                        </span>
                      </div>
                      <div className="w-full h-1.5 bg-[#2a2a2a] rounded-full overflow-hidden">
                        <div
                          className="h-full rounded-full transition-all"
                          style={{
                            width: `${Math.min((tradingParams.liveStatus.totalLoss / tradingParams.params.accountLossLimit) * 100, 100)}%`,
                            backgroundColor: tradingParams.liveStatus.totalLoss / tradingParams.params.accountLossLimit > 0.8 ? '#ef4444' : '#eab308',
                          }}
                        />
                      </div>
                    </div>
                    <div className="flex justify-between text-xs">
                      <span className="text-[#8a8a8a]">今日交易</span>
                      <span className="text-[#e0e0e0]">{tradingParams.liveStatus.todayTradeCount} 次</span>
                    </div>
                  </div>
                </div>

                {/* 交易开关 */}
                <div className="config-section">
                  <div className="font-semibold mb-2">🔧 交易开关</div>
                  <div className="flex items-center justify-between mb-3">
                    <div className="flex items-center gap-2">
                      <div className={`w-3 h-3 rounded-full ${tradingParams.liveStatus.status === 'ACTIVE' ? 'bg-green-500' : tradingParams.liveStatus.status === 'PAUSED' ? 'bg-yellow-500' : 'bg-red-500'}`} />
                      <span className="text-xs">
                        {tradingParams.liveStatus.status === 'ACTIVE' ? '运行中' : tradingParams.liveStatus.status === 'PAUSED' ? '已暂停' : tradingParams.liveStatus.status === 'FROZEN' ? '已冻结' : '已锁定'}
                      </span>
                    </div>
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${
                      tradingParams.liveStatus.status === 'ACTIVE' ? 'bg-green-500/20 text-green-400' :
                      tradingParams.liveStatus.status === 'PAUSED' ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {tradingParams.liveStatus.status}
                    </span>
                  </div>
                  <div className="flex gap-2">
                    {tradingParams.liveStatus.status === 'ACTIVE' ? (
                      <button
                        onClick={async () => {
                          if (!confirm('确定要暂停交易？')) return;
                          try {
                            const res = await fetch('/api/config/trading-params/pause', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ reason: '用户主动暂停' }) });
                            if ((await res.json()).success) fetchTradingParams();
                          } catch {}
                        }}
                        className="flex-1 px-3 py-2 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/30 transition"
                      >
                        ⏸ 暂停交易
                      </button>
                    ) : (
                      <button
                        onClick={async () => {
                          try {
                            const res = await fetch('/api/config/trading-params/resume', { method: 'POST' });
                            if ((await res.json()).success) fetchTradingParams();
                          } catch {}
                        }}
                        className="flex-1 px-3 py-2 text-xs bg-green-500/20 text-green-400 border border-green-500/30 rounded hover:bg-green-500/30 transition"
                      >
                        ▶ 恢复交易
                      </button>
                    )}
                    <button
                      onClick={async () => {
                        if (!confirm('确定要重置日亏损计数？')) return;
                        try {
                          const res = await fetch('/api/config/trading-params/reset-daily', { method: 'POST' });
                          if ((await res.json()).success) fetchTradingParams();
                        } catch {}
                      }}
                      className="px-3 py-2 text-xs bg-[#2a2a2a] text-[#8a8a8a] rounded hover:bg-[#1a1a1a] transition"
                    >
                      🔄 重置日亏损
                    </button>
                  </div>
                </div>

                {/* 保存按钮 (仅编辑模式) */}
                {tradingEditing && (
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={async () => {
                        setTradingSaving(true);
                        try {
                          const res = await fetch('/api/config/trading-params', {
                            method: 'PATCH',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              availableCapital: tradingEditForm.availableCapital || null,
                              capitalPercentage: (tradingEditForm.dailyLossPercent as number) / 100 || 0.10,
                              tradeMode: tradingEditForm.tradeMode,
                              marginMode: tradingEditForm.marginMode || null,
                              positionMode: tradingEditForm.positionMode,
                              leverageMax: tradingEditForm.leverageMax,
                              dailyLossLimit: tradingEditForm.dailyLossLimit,
                              dailyLossPercent: (tradingEditForm.dailyLossPercent as number) / 100,
                              accountLossLimit: tradingEditForm.accountLossLimit,
                              accountLossPercent: (tradingEditForm.accountLossPercent as number) / 100,
                              riskTolerance: tradingEditForm.riskTolerance,
                            }),
                          });
                          const data = await res.json();
                          if (data.success) {
                            setTradingEditing(false);
                            fetchTradingParams();
                            if (data.warnings?.length) alert('⚠️ ' + data.warnings.join('\n'));
                          } else {
                            alert(data.error || '保存失败');
                          }
                        } catch { alert('保存失败'); }
                        finally { setTradingSaving(false); }
                      }}
                      disabled={tradingSaving}
                      className="flex-1 px-3 py-2 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition disabled:opacity-50 font-medium"
                    >
                      {tradingSaving ? '⏳ 保存中...' : '💾 保存设置'}
                    </button>
                    <button
                      onClick={() => setTradingEditing(false)}
                      className="px-3 py-2 text-xs bg-[#2a2a2a] text-[#8a8a8a] rounded hover:bg-[#1a1a1a] transition"
                    >
                      取消
                    </button>
                  </div>
                )}
              </>
            ) : (
              <div className="config-section text-center text-xs text-[#8a8a8a]">暂无交易配置</div>
            )}
          </div>
        );
      case 'strategy':
        return (
          <div className="relative">
            {/* Toast 容器 */}
            {toast && (
              <div className="toast-container" style={{ position: 'fixed', top: 12, right: 12, zIndex: 9999 }}>
                <div key={toast.id} className={`toast-item ${toast.type}`}>{toast.msg}</div>
              </div>
            )}

            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>🎯 策略设置</div>
              <div className="flex gap-2">
                {(() => {
                  const draftCount = strategyViewModel.drafts.length;
                  return draftCount > 0 ? (
                    <button
                      onClick={() => setShowDrafts(!showDrafts)}
                      className={`px-3 py-1.5 text-xs rounded transition flex items-center gap-1 ${
                        showDrafts
                          ? 'bg-[#0066ff] text-white border border-[#0066ff]'
                          : 'bg-[#2a2a2a] text-[#e0e0e0] border border-[#f59e0b] hover:bg-[#1a1a1a]'
                      }`}
                    >
                      📝 查看草稿
                      <span className="inline-flex items-center justify-center min-w-[18px] h-[18px] px-1 text-[10px] font-bold rounded-full bg-[#f59e0b] text-black">
                        {draftCount}
                      </span>
                    </button>
                  ) : null;
                })()}
                <button
                  onClick={() => { fetchStrategies(); setWizardStep('input'); setParsedStrategy(null); setStrategyError(null); }}
                  className="px-3 py-1.5 text-xs bg-[#2a2a2a] text-[#e0e0e0] border border-[#0066ff] rounded hover:bg-[#1a1a1a] transition"
                >
                  🔄 刷新
                </button>
              </div>
            </div>

            {strategiesLoading ? (
              <div className="config-section text-center text-xs text-[#8a8a8a]">⏳ 加载中...</div>
            ) : (
              <>
                {/* ===== 草稿箱展开面板 ===== */}
                {showDrafts && (() => {
                  const drafts = strategyViewModel.drafts;
                  return (
                    <div className="mb-4 border border-[#f59e0b]/30 rounded-lg overflow-hidden" style={{ background: 'linear-gradient(135deg, rgba(245,158,11,0.08) 0%, rgba(30,30,50,0.6) 100%)' }}>
                      <div className="flex items-center justify-between px-3 py-2 bg-[#f59e0b]/10 border-b border-[#f59e0b]/20">
                        <div className="text-xs font-semibold text-[#f59e0b] flex items-center gap-1.5">
                          📝 草稿箱
                          <span className="bg-[#f59e0b] text-black px-1.5 py-0.5 rounded-full text-[10px] font-bold">{drafts.length}</span>
                        </div>
                        <button
                          onClick={() => setShowDrafts(false)}
                          className="text-xs text-[#8a8a8a] hover:text-white transition"
                        >
                          ✕ 收起
                        </button>
                      </div>
                      {drafts.length === 0 ? (
                        <div className="px-3 py-4 text-center text-xs text-[#8a8a8a]">暂无草稿策略</div>
                      ) : (
                        <div className="p-2 space-y-2 max-h-[400px] overflow-y-auto">
                          {drafts.map((s) => (
                            <div key={s.strategyId} className="rounded-lg p-3 bg-[#0f172a]/80 border border-[#2a2a2a]" style={{ borderLeft: '3px solid #f59e0b' }}>
                              {/* 策略名 + 状态标签 */}
                              <div className="flex justify-between items-center mb-2">
                                <div className="font-semibold text-sm text-[#e0e0e0] flex items-center gap-1.5">
                                  📝 {s.name}
                                  <span className="px-1.5 py-0.5 rounded text-[10px] font-medium bg-[#f59e0b]/20 text-[#f59e0b] border border-[#f59e0b]/30">
                                    草稿
                                  </span>
                                </div>
                                <div className="flex gap-1.5">
                                  <button
                                    onClick={async () => {
                                      try {
                                        const res = await fetch(`/api/config/strategies/${s.strategyId}/apply`, { method: 'POST' });
                                        const data = await res.json();
                                        if (data.success) {
                                          showToast('success', `策略"${s.name}"已应用`);
                                          fetchStrategies();
                                        } else {
                                          showToast('error', data.error || '应用失败');
                                        }
                                      } catch { showToast('error', '网络错误'); }
                                    }}
                                    className="px-2.5 py-1 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition flex items-center gap-1"
                                  >
                                    🚀 应用
                                  </button>
                                  <button
                                    onClick={async () => {
                                      if (!confirm('确定删除此草稿？')) return;
                                      try {
                                        await fetch(`/api/config/strategies?id=${s.strategyId}`, { method: 'DELETE' });
                                        showToast('success', '草稿已删除');
                                        fetchStrategies();
                                      } catch { showToast('error', '删除失败'); }
                                    }}
                                    className="px-2 py-1 text-xs bg-red-500/20 text-red-400 border border-red-500/30 rounded hover:bg-red-500/30 transition"
                                  >
                                    🗑️
                                  </button>
                                </div>
                              </div>
                              {/* 策略参数详情 */}
                              <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                                <div className="text-[#8a8a8a]">
                                  方向: <span className={s.direction === 'BUY' ? 'text-[#22c55e]' : s.direction === 'SHORT' ? 'text-[#ef4444]' : 'text-[#eab308]'}>
                                    {s.direction === 'BUY' ? '📈 做多' : s.direction === 'SHORT' ? '📉 做空' : '👀 观望'}
                                  </span>
                                </div>
                                <div className="text-[#8a8a8a]">
                                  杠杆: <span className="text-[#e0e0e0] font-medium">{s.leverage ?? '-'}{s.leverage !== null ? 'x' : ''}</span>
                                </div>
                                <div className="text-[#8a8a8a]">
                                  仓位: <span className="text-[#e0e0e0] font-medium">{s.positionSize ?? '-'}{s.positionSize !== null ? 'x' : ''}</span>
                                </div>
                                <div className="text-[#8a8a8a]">
                                  类型: <span className="text-[#e0e0e0] font-medium">{s.tradeType || 'N/A'}</span>
                                </div>
                                {s.stopLoss !== null && (
                                  <div className="text-[#8a8a8a]">
                                    止损: <span className="text-[#ef4444] font-medium">{s.stopLoss}</span>
                                  </div>
                                )}
                                {s.takeProfit !== null && (
                                  <div className="text-[#8a8a8a]">
                                    止盈: <span className="text-[#22c55e] font-medium">{s.takeProfit}</span>
                                  </div>
                                )}
                              </div>
                              {/* 原始输入 */}
                              {s.rawInput && (
                                <div className="mt-2 p-2 rounded bg-[#0a0f1e] border border-[#1e293b]">
                                  <div className="text-[10px] text-[#71717a] mb-0.5">💬 原始输入</div>
                                  <div className="text-xs text-[#94a3b8] break-all">{s.rawInput}</div>
                                </div>
                              )}
                              {/* 时间信息 */}
                              <div className="flex justify-between items-center mt-2 text-[10px] text-[#71717a]">
                                <span>创建: {s.createdAt ? new Date(s.createdAt).toLocaleString('zh-CN') : '-'}</span>
                                {s.updatedAt && s.updatedAt !== s.createdAt && (
                                  <span>更新: {new Date(s.updatedAt).toLocaleString('zh-CN')}</span>
                                )}
                              </div>
                            </div>
                          ))}
                        </div>
                      )}
                    </div>
                  );
                })()}

                {/* ===== 推荐策略 (保持原有逻辑，修复应用按钮) ===== */}
                <div className="text-xs text-[#8a8a8a] mb-2">📋 推荐策略 ({strategyViewModel.recommended.length})</div>
                {strategyViewModel.recommended.length === 0 ? (
                  <div className="config-section text-center text-xs text-[#8a8a8a]">
                    暂无推荐策略，等待A4验证推送
                  </div>
                ) : (
                  strategyViewModel.recommended.map((s) => (
                    <div key={s.strategyId} className="config-section" style={{ borderLeft: `3px solid ${s.direction === 'BUY' ? '#22c55e' : s.direction === 'SHORT' ? '#ef4444' : '#eab308'}` }}>
                      <div className="flex justify-between items-center mb-2">
                        <div className="font-semibold">{s.direction === 'SKIP' ? '🟡' : s.direction === 'BUY' ? '🟢' : '🔴'} {s.name}</div>
                        <div>
                          {!s.isRead && <span className="bg-green-500 text-black px-1.5 py-0.5 rounded text-xs mr-1">新</span>}
                          <span className="text-xs text-[#8a8a8a]">{s.regime || ''}</span>
                        </div>
                      </div>
                      <div className="text-xs text-[#8a8a8a]">
                        {s.regime && `${s.regime} | `}置信度{s.confidence || '?'}% | Edge {s.edgeScore || '?'}
                      </div>
                      <div className="text-xs mt-1">方向: {s.direction === 'BUY' ? '做多' : s.direction === 'SHORT' ? '做空' : '观望'} | 杠杆: {s.leverage}x | 仓位: {s.positionSize}x</div>
                      {s.source && <div className="text-xs text-[#06b6d4] mt-1">来源: {s.source}</div>}
                      <div className="flex gap-2 mt-2">
                        <button
                          onClick={async () => {
                            try {
                              const res = await fetch(`/api/config/strategies/${s.strategyId}/apply`, { method: 'POST' });
                              const data = await res.json();
                              if (data.success) {
                                showToast('success', `策略"${s.name}"已应用`);
                                fetchStrategies();
                              } else {
                                showToast('error', data.error || '应用失败');
                              }
                            } catch { showToast('error', '网络错误'); }
                          }}
                          className="px-2.5 py-1 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition"
                        >
                          应用
                        </button>
                      </div>
                    </div>
                  ))
                )}

                {/* ===== 已有自定义策略列表 ===== */}
                {strategyViewModel.custom.length > 0 && (
                  <>
                    <div className="text-xs text-[#8a8a8a] mt-4 mb-2">📝 已有自定义策略 ({strategyViewModel.custom.length})</div>
                    {strategyViewModel.custom.map((s) => (
                      <div key={s.strategyId} className="config-section" style={{ borderLeft: `3px solid ${s.status === 'APPLIED' ? '#22c55e' : s.status === 'PAUSED' ? '#eab308' : '#6b7280'}` }}>
                        <div className="flex justify-between items-center mb-1">
                          <div className="font-semibold text-xs">
                            {s.status === 'APPLIED' ? '🟢' : s.status === 'PAUSED' ? '⏸️' : '📝'} {s.name}
                          </div>
                          <div className="flex gap-1.5">
                            {s.status === 'DRAFT' && (
                              <button
                                onClick={async () => {
                                  try {
                                    const res = await fetch(`/api/config/strategies/${s.strategyId}/apply`, { method: 'POST' });
                                    const data = await res.json();
                                    if (data.success) {
                                      showToast('success', `策略"${s.name}"已应用`);
                                      fetchStrategies();
                                    } else {
                                      showToast('error', data.error || '应用失败');
                                    }
                                  } catch { showToast('error', '网络错误'); }
                                }}
                                className="px-2 py-0.5 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition"
                              >
                                应用
                              </button>
                            )}
                            {s.status === 'APPLIED' && (
                              <button
                                onClick={async () => {
                                  try {
                                    await fetch(`/api/config/strategies/${s.strategyId}/pause`, { method: 'POST' });
                                    showToast('success', '策略已暂停');
                                    fetchStrategies();
                                  } catch {}
                                }}
                                className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/30 transition"
                              >
                                ⏸ 暂停
                              </button>
                            )}
                            <button
                              onClick={async () => {
                                  if (!confirm('确定删除此策略？')) return;
                                try {
                                  await fetch(`/api/config/strategies?id=${s.strategyId}`, { method: 'DELETE' });
                                  showToast('success', '策略已删除');
                                  fetchStrategies();
                                } catch {}
                              }}
                              className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 border border-red-500/30 rounded hover:bg-red-500/30 transition"
                            >
                              🗑️
                            </button>
                          </div>
                        </div>
                        <div className="text-xs text-[#8a8a8a]">
                          方向: {s.direction === 'BUY' ? '做多' : s.direction === 'SHORT' ? '做空' : '观望'} | 杠杆: {s.leverage}x | 仓位: {s.positionSize}x
                        </div>
                        {s.stopLoss !== null && <div className="text-xs text-[#ef4444]">止损: {s.stopLoss}</div>}
                        {s.takeProfit !== null && <div className="text-xs text-[#22c55e]">止盈: {s.takeProfit}</div>}
                        {s.rawInput && <div className="text-xs text-[#71717a] mt-1 truncate">原始输入: {s.rawInput}</div>}
                        <div className="text-xs text-[#71717a] mt-1">状态: {s.status} | 创建: {s.createdAt ? new Date(s.createdAt).toLocaleString('zh-CN') : '-'}</div>
                      </div>
                    ))}
                  </>
                )}

                {/* ===== 自定义策略 — 三步向导 ===== */}
                <div className="text-xs text-[#8a8a8a] mt-4 mb-2">✏️ 自定义策略</div>
                <div className="config-section">

                  {/* 步骤指示器 */}
                  <div className="wizard-steps">
                    {(() => {
                      const step = wizardStep as string;
                      return (
                        <>
                          <div className={`wizard-step-dot ${step === 'input' ? 'active' : step !== 'input' ? 'done' : ''}`}>
                            <div className="step-num">{step !== 'input' ? '✓' : '1'}</div>
                            <div className="step-label">输入</div>
                          </div>
                          <div className={`wizard-step-connector ${step !== 'input' ? 'done' : ''}`} />
                          <div className={`wizard-step-dot ${step === 'preview' ? 'active' : step === 'confirm' ? 'done' : ''}`}>
                            <div className="step-num">{step === 'confirm' ? '✓' : '2'}</div>
                            <div className="step-label">预览</div>
                          </div>
                          <div className={`wizard-step-connector ${step === 'confirm' ? 'done' : ''}`} />
                          <div className={`wizard-step-dot ${step === 'confirm' ? 'active' : ''}`}>
                            <div className="step-num">3</div>
                            <div className="step-label">确认</div>
                          </div>
                        </>
                      );
                    })()}
                  </div>

                  {/* ── Step 1: 意图输入 ── */}
                  {wizardStep === 'input' && (
                    <>
                      <div className="text-xs text-[#8a8a8a] mb-3">描述你的策略意图，系统将自动解析并生成可调参数</div>

                      <textarea
                        value={customStrategyInput}
                        onChange={(e) => setCustomStrategyInput(e.target.value)}
                        placeholder="例如：RSI低于30并且MACD金叉的时候做多BTC，2x杠杆..."
                        className="w-full bg-[#141414] border border-[#2a2a2a] rounded-md p-2.5 text-[#e0e0e0] text-sm min-h-[64px] resize-y focus:outline-none focus:border-[#0066ff] transition"
                      />

                      {/* 模板卡片 */}
                      <div className="text-xs text-[#71717a] mt-3 mb-1.5">快捷模板（点击填充）</div>
                      <div className="template-grid">
                        {[
                          { id: 'trend', icon: '📊', label: '趋势跟随', desc: '均线多头排列时顺势入场', input: '当MA20上穿MA60且成交量放大时，以2x杠杆做多BTC永续合约', dir: 'BUY', lever: 2, type: 'SWAP' },
                          { id: 'rsi', icon: '📈', label: '超卖反弹', desc: 'RSI极端区域逆向抄底', input: '当RSI(14)低于30且出现背离时，做多BTC现货', dir: 'BUY', lever: 1, type: 'SPOT' },
                          { id: 'boll', icon: '📉', label: '均值回归', desc: '布林带触及下轨后回归中线', input: '价格触及布林带下轨且MACD柱缩短时，做多BTC现货', dir: 'BUY', lever: 1, type: 'SPOT' },
                          { id: 'breakout', icon: '⚡', label: '放量突破', desc: '突破关键阻力位追入', input: '价格放量突破前高且站稳上方时，3x杠杆做多BTC永续合约', dir: 'BUY', lever: 3, type: 'SWAP' },
                        ].map(t => (
                          <div
                            key={t.id}
                            className="template-card"
                            onClick={() => {
                              setCustomStrategyInput(t.input);
                              setWizardForm(prev => ({ ...prev, direction: t.dir, leverage: t.lever, tradeType: t.type }));
                            }}
                          >
                            <div><span className="template-card-icon">{t.icon}</span><span className="template-card-title">{t.label}</span></div>
                            <div className="template-card-desc">{t.desc}</div>
                          </div>
                        ))}
                      </div>

                      {strategyError && (
                        <div className="inline-error">{strategyError}</div>
                      )}

                      <button
                        onClick={async () => {
                          if (!customStrategyInput.trim()) { setStrategyError('请输入策略描述'); return; }
                          setStrategyError(null);
                          setWizardParsing(true);
                          try {
                            const res = await fetch('/api/config/strategies/parse', {
                              method: 'POST',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ rawInput: customStrategyInput }),
                            });
                            const data = await res.json();
                            if (data.success) {
                              setParsedStrategy(data.data);
                              // 预填充表单为解析结果
                              const p = data.data.suggestedParams;
                              setWizardForm({
                                direction: p.direction,
                                symbol: p.symbol,
                                tradeType: p.tradeType,
                                leverage: p.leverage,
                                positionSize: p.positionSize,
                                stopLoss: p.stopLoss?.toString() || '',
                                takeProfit: p.takeProfit?.toString() || '',
                                frequency: 'FOUR_H',
                              });
                              setWizardStep('preview');
                            } else {
                              setStrategyError(data.error || '解析失败');
                            }
                          } catch { setStrategyError('网络错误，请重试'); }
                          finally { setWizardParsing(false); }
                        }}
                        disabled={wizardParsing || !customStrategyInput.trim()}
                        className="w-full mt-3 px-4 py-2.5 text-sm bg-[#0066ff] text-white rounded-md hover:bg-blue-700 transition disabled:opacity-50 font-medium"
                      >
                        {wizardParsing ? (
                          <span>⏳ 正在解析...</span>
                        ) : (
                          <span>🔍 解析策略 →</span>
                        )}
                      </button>
                    </>
                  )}

                  {/* ── Step 2: 解析预览 + 参数调整 ── */}
                  {wizardStep === 'preview' && parsedStrategy && (
                    <>
                      {/* 系统理解卡片 */}
                      <div className="parse-preview-card">
                        <div className="parse-preview-header">
                          <span className="parse-preview-icon">🤖</span>
                          <span className="parse-preview-title">系统理解</span>
                        </div>
                        <div className="parse-preview-text">{parsedStrategy.explanation}</div>
                        {parsedStrategy.intent.indicators.length > 0 && (
                          <div className="indicator-tags">
                            {parsedStrategy.intent.indicators.map((ind: string) => (
                              <span key={ind} className="indicator-tag">{ind}</span>
                            ))}
                          </div>
                        )}
                      </div>

                      {/* 置信度 */}
                      <div className="confidence-bar-container">
                        <span className="text-xs text-[#8a8a8a]">置信度</span>
                        <div className="confidence-bar-track">
                          <div className="confidence-bar-fill" style={{ width: `${parsedStrategy.confidence}%` }} />
                        </div>
                        <span className="confidence-bar-text">{parsedStrategy.confidence}%</span>
                      </div>

                      {/* 参数调整表单 */}
                      <div className="param-form">
                        {/* 方向 */}
                        <div className="param-field">
                          <div className="param-label">交易方向</div>
                          <div className="param-radio-group">
                            {['BUY', 'SHORT', 'SKIP'].map(d => (
                              <div
                                key={d}
                                className={`param-radio-btn ${wizardForm.direction === d ? (d === 'BUY' ? 'active-buy' : d === 'SHORT' ? 'param-radio-btn-active-short' : 'param-radio-btn-active-skip') : ''}`}
                                onClick={() => setWizardForm(f => ({ ...f, direction: d }))}
                              >
                                {d === 'BUY' ? '🟢 做多' : d === 'SHORT' ? '🔴 做空' : '🟡 观望'}
                              </div>
                            ))}
                          </div>
                        </div>

                        {/* 品种 */}
                        <div className="param-field">
                          <div className="param-label">交易品种</div>
                          <select
                            value={wizardForm.symbol}
                            onChange={(e) => setWizardForm(f => ({ ...f, symbol: e.target.value }))}
                            className="param-select"
                          >
                            <option value="BTC-USDT-SWAP">BTC-USDT-SWAP</option>
                            <option value="ETH-USDT-SWAP">ETH-USDT-SWAP</option>
                            <option value="SOL-USDT-SWAP">SOL-USDT-SWAP</option>
                          </select>
                        </div>

                        {/* 类型 Toggle */}
                        <div className="param-field">
                          <div className="param-label">交易类型</div>
                          <div className="param-toggle-group">
                            <div
                              className={`param-toggle-btn ${wizardForm.tradeType === 'SPOT' ? 'active' : ''}`}
                              onClick={() => setWizardForm(f => ({ ...f, tradeType: 'SPOT', leverage: 1 }))}
                            >💰 现货</div>
                            <div
                              className={`param-toggle-btn ${wizardForm.tradeType === 'SWAP' ? 'active' : ''}`}
                              onClick={() => setWizardForm(f => ({ ...f, tradeType: 'SWAP', leverage: f.leverage <= 1 ? 2 : f.leverage }))}
                            >⚡ 合约</div>
                          </div>
                        </div>

                        {/* 杠杆 Slider */}
                        {wizardForm.tradeType === 'SWAP' && (
                          <div className="param-field">
                            <div className="param-label">
                              <span>杠杆倍数</span>
                              <span className="param-label-value">{wizardForm.leverage}x</span>
                            </div>
                            <div className="param-slider-row">
                              <input
                                type="range" min="1" max="5" step="1"
                                value={wizardForm.leverage}
                                onChange={(e) => setWizardForm(f => ({ ...f, leverage: parseInt(e.target.value) }))}
                                className="param-slider-input flex-1"
                              />
                            </div>
                          </div>
                        )}

                        {/* 仓位 Slider */}
                        <div className="param-field">
                          <div className="param-label">
                            <span>仓位比例</span>
                            <span className="param-label-value">{(wizardForm.positionSize * 100).toFixed(0)}%</span>
                          </div>
                          <div className="param-slider-row">
                            <input
                              type="range" min="10" max="100" step="10"
                              value={Math.round(wizardForm.positionSize * 100)}
                              onChange={(e) => setWizardForm(f => ({ ...f, positionSize: parseInt(e.target.value) / 100 }))}
                              className="param-slider-input flex-1"
                            />
                          </div>
                        </div>

                        {/* 止损/止盈 并排 */}
                        <div className="flex gap-2">
                          <div className="param-field flex-1">
                            <div className="param-label"><span>止损价</span></div>
                            <input
                              type="number" placeholder="可选"
                              value={wizardForm.stopLoss}
                              onChange={(e) => setWizardForm(f => ({ ...f, stopLoss: e.target.value }))}
                              className="param-number-input"
                            />
                          </div>
                          <div className="param-field flex-1">
                            <div className="param-label"><span>止盈价</span></div>
                            <input
                              type="number" placeholder="可选"
                              value={wizardForm.takeProfit}
                              onChange={(e) => setWizardForm(f => ({ ...f, takeProfit: e.target.value }))}
                              className="param-number-input"
                            />
                          </div>
                        </div>

                        {/* 执行频率 */}
                        <div className="param-field">
                          <div className="param-label">执行频率</div>
                          <div className="param-radio-group">
                            {[
                              { v: 'ONE_H', l: '1小时' },
                              { v: 'FOUR_H', l: '4小时' },
                              { v: 'ONE_D', l: '1天' },
                            ].map(freq => (
                              <div
                                key={freq.v}
                                className={`param-radio-btn ${wizardForm.frequency === freq.v ? 'active-buy' : ''}`}
                                onClick={() => setWizardForm(f => ({ ...f, frequency: freq.v }))}
                              >
                                {freq.l}
                              </div>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* 警告 */}
                      {parsedStrategy.warnings.length > 0 && (
                        <div className="warnings-list">
                          {parsedStrategy.warnings.map((w: string, i: number) => (
                            <div key={i} className="warning-item">
                              <span className="warning-icon">⚠️</span>
                              <span>{w}</span>
                            </div>
                          ))}
                        </div>
                      )}

                      {/* 操作按钮 */}
                      <div className="wizard-actions">
                        <button
                          className="wizard-btn wizard-btn-secondary"
                          onClick={() => setWizardStep('input')}
                        >
                          ← 返回修改
                        </button>
                        <button
                          className="wizard-btn wizard-btn-primary"
                          onClick={() => setWizardStep('confirm')}
                        >
                          ✅ 确认创建 →
                        </button>
                      </div>
                    </>
                  )}

                  {/* ── Step 3: 确认 + 应用 ── */}
                  {wizardStep === 'confirm' && (
                    <>
                      <div className="confirm-success-card">
                        <div className="confirm-success-icon">📋</div>
                        <div className="confirm-success-title">确认策略参数</div>
                        <div className="confirm-success-detail">
                          <div>{wizardForm.direction === 'BUY' ? '🟢' : wizardForm.direction === 'SHORT' ? '🔴' : '🟡'}{' '}
                            {customStrategyInput.slice(0, 40)}{customStrategyInput.length > 40 ? '...' : ''}</div>
                          <div style={{ marginTop: 4 }}>
                            {wizardForm.symbol} · {wizardForm.tradeType === 'SWAP' ? `${wizardForm.leverage}x合约` : '现货'}
                            {' '}· 仓位{(wizardForm.positionSize * 100).toFixed(0)}%
                            {wizardForm.stopLoss ? ` · SL=${wizardForm.stopLoss}` : ''}
                            {wizardForm.takeProfit ? ` · TP=${wizardForm.takeProfit}` : ''}
                          </div>
                        </div>
                      </div>

                      <div className="wizard-actions">
                        <button
                          className="wizard-btn wizard-btn-secondary"
                          onClick={() => setWizardStep('preview')}
                        >
                          ← 返回调整
                        </button>
                        <button
                          className="wizard-btn wizard-btn-success"
                          onClick={async () => {
                            setCustomStrategyLoading(true);
                            try {
                              const res = await fetch('/api/config/strategies', {
                                method: 'POST',
                                headers: { 'Content-Type': 'application/json' },
                                body: JSON.stringify({
                                  type: 'CUSTOM',
                                  name: customStrategyInput.slice(0, 40),
                                  description: parsedStrategy?.explanation || '',
                                  direction: wizardForm.direction,
                                  symbol: wizardForm.symbol,
                                  tradeType: wizardForm.tradeType,
                                  leverage: wizardForm.leverage,
                                  positionSize: wizardForm.positionSize,
                                  stopLoss: wizardForm.stopLoss ? parseFloat(wizardForm.stopLoss) : null,
                                  takeProfit: wizardForm.takeProfit ? parseFloat(wizardForm.takeProfit) : null,
                                  confidence: parsedStrategy?.confidence || null,
                                  rawInput: customStrategyInput,
                                }),
                              });
                              const data = await res.json();
                              if (data.success) {
                                // 尝试自动 apply
                                try {
                                  await fetch(`/api/config/strategies/${data.data.id}/apply`, {
                                    method: 'POST',
                                    headers: { 'Content-Type': 'application/json' },
                                    body: JSON.stringify({ frequency: wizardForm.frequency }),
                                  });
                                } catch {} // apply 失败不阻断

                                showToast('success', `策略"${data.data.name}"创建成功`);
                                setCustomStrategyInput('');
                                setParsedStrategy(null);
                                setWizardStep('input');
                                fetchStrategies();
                              } else {
                                showToast('error', data.error || '创建失败');
                              }
                            } catch { showToast('error', '创建失败'); }
                            finally { setCustomStrategyLoading(false); }
                          }}
                          disabled={customStrategyLoading}
                        >
                          {customStrategyLoading ? '⏳ 创建中...' : '🚀 创建并应用策略'}
                        </button>
                      </div>
                    </>
                  )}
                </div>

                {/* ===== 运行中的策略：统一读取 task order 视图模型 ===== */}
                <div className="text-xs text-[#8a8a8a] mt-4 mb-2">⚡ 运行中的策略 ({strategyViewModel.active.length})</div>
                {strategyViewModel.active.length === 0 ? (
                  <div className="config-section text-center text-xs text-[#8a8a8a]">
                    暂无运行中的策略，应用策略后将显示在此
                  </div>
                ) : (
                  <>
                    {strategyViewModel.active.map((s) => (
                      <div key={s.taskOrderId} className="config-section" style={{ borderLeft: '3px solid #22c55e' }}>
                        <div className="flex justify-between items-center mb-1">
                          <div className="font-semibold text-xs">🟢 {s.title}</div>
                          <div className="text-[10px] text-[#8a8a8a]">
                            {s.runStatus === 'running' ? '● 运行中' : s.runStatus === 'queued' ? '● 待执行' : '● 已应用'}
                          </div>
                        </div>
                        <div className="text-xs text-[#8a8a8a]">
                          频率: {s.frequencyLabel} | 下次执行: {s.nextExecutionAt ? new Date(s.nextExecutionAt).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' }) : '未设置'}
                        </div>
                        <div className="text-xs text-[#8a8a8a] mt-1">
                          已执行{s.executionCount}次 | 交易{s.tradeCount}次 | 跳过{s.skipCount}次
                        </div>
                        <div className="flex justify-between items-center mt-2">
                          <div className="text-xs text-[#71717a]">
                            {s.leverage ?? '-'}{s.leverage !== null ? 'x' : ''} | {s.direction === 'BUY' ? '做多' : s.direction === 'SHORT' ? '做空' : '观望'}
                          </div>
                          <div className="flex gap-1.5">
                            <button
                              onClick={async () => {
                                try {
                                  await fetch(`/api/config/strategies/${s.strategyId}/pause`, { method: 'POST' });
                                  showToast('success', '策略已暂停');
                                  fetchStrategies();
                                } catch {}
                              }}
                              className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/30 transition"
                            >
                              ⏸ 暂停
                            </button>
                            <button
                              onClick={async () => {
                                if (!confirm('确定删除此策略？')) return;
                                try {
                                  await fetch(`/api/config/strategies?id=${s.strategyId}`, { method: 'DELETE' });
                                  showToast('success', '策略已删除');
                                  fetchStrategies();
                                } catch {}
                              }}
                              className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 border border-red-500/30 rounded hover:bg-red-500/30 transition"
                            >
                              🗑️
                            </button>
                          </div>
                        </div>
                      </div>
                    ))}
                  </>
                )}

                {/* ===== 已应用策略：统一读取 task order 视图模型 ===== */}
                <div className="text-xs text-[#8a8a8a] mt-4 mb-2">📊 已应用策略 ({strategyViewModel.applied.length})</div>
                {strategyViewModel.applied.length === 0 ? (
                  <div className="config-section text-center text-xs text-[#8a8a8a]">
                    暂无已应用策略
                  </div>
                ) : (
                  strategyViewModel.applied.map((s) => (
                    <div key={s.taskOrderId} className="config-section" style={{ borderLeft: '3px solid #22c55e' }}>
                      <div className="flex justify-between items-center mb-1">
                        <div className="font-semibold text-xs">🟢 {s.title}</div>
                        <div className="flex gap-1.5">
                          <button
                            onClick={async () => {
                              try {
                                await fetch(`/api/config/strategies/${s.strategyId}/pause`, { method: 'POST' });
                                showToast('success', '策略已暂停');
                                fetchStrategies();
                              } catch {}
                            }}
                            className="px-2 py-0.5 text-xs bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/30 transition"
                          >
                            ⏸ 暂停
                          </button>
                          <button
                            onClick={async () => {
                              if (!confirm('确定删除此策略？')) return;
                              try {
                                await fetch(`/api/config/strategies?id=${s.strategyId}`, { method: 'DELETE' });
                                showToast('success', '策略已删除');
                                fetchStrategies();
                              } catch {}
                            }}
                            className="px-2 py-0.5 text-xs bg-red-500/20 text-red-400 border border-red-500/30 rounded hover:bg-red-500/30 transition"
                          >
                            🗑️
                          </button>
                        </div>
                      </div>
                      <div className="text-xs text-[#8a8a8a]">
                        {s.leverage ?? '-'}{s.leverage !== null ? 'x' : ''} | {s.direction === 'BUY' ? '做多' : s.direction === 'SHORT' ? '做空' : '观望'} | {s.frequencyLabel}
                      </div>
                      {s.summary && <div className="text-xs text-[#71717a] mt-1 truncate">{s.summary}</div>}
                    </div>
                  ))
                )}
              </>
            )}
          </div>
        );
      case 'communication':
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>📡 通信渠道</div>
              <button
                onClick={() => setShowAddChannelForm(!showAddChannelForm)}
                className="px-3 py-1.5 text-xs bg-green-500 text-white rounded hover:bg-green-600 transition font-medium"
              >
                ➕ 添加
              </button>
            </div>

            {/* 添加渠道表单 */}
            {showAddChannelForm && (
              <div className="config-section" style={{ borderLeft: '3px solid #22c55e' }}>
                <div className="font-semibold mb-3 text-sm">添加新渠道</div>
                <div className="space-y-2">
                  <div>
                    <label className="text-xs text-[#8a8a8a]">渠道类型</label>
                    <select
                      value={addChannelForm.channelType}
                      onChange={(e) => setAddChannelForm({ ...addChannelForm, channelType: e.target.value })}
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                    >
                      <option value="TELEGRAM">📱 Telegram</option>
                      <option value="WECHAT_SERVERCHAN">💬 微信 (Server酱)</option>
                      <option value="EMAIL_SMTP">📧 Email</option>
                      <option value="DISCORD">🎮 Discord</option>
                      <option value="SLACK">📲 Slack</option>
                    </select>
                  </div>
                  <div>
                    <label className="text-xs text-[#8a8a8a]">标签</label>
                    <input
                      value={addChannelForm.label}
                      onChange={(e) => setAddChannelForm({ ...addChannelForm, label: e.target.value })}
                      className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                      placeholder="我的信号群"
                    />
                  </div>

                  {/* Telegram 配置 */}
                  {addChannelForm.channelType === 'TELEGRAM' && (
                    <>
                      <div>
                        <label className="text-xs text-[#8a8a8a]">Bot Token</label>
                        <input
                          type="password"
                          value={addChannelForm.botToken}
                          onChange={(e) => setAddChannelForm({ ...addChannelForm, botToken: e.target.value })}
                          className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          placeholder="123456:ABC-DEF..."
                        />
                      </div>
                      <div>
                        <label className="text-xs text-[#8a8a8a]">Chat ID</label>
                        <input
                          value={addChannelForm.chatId}
                          onChange={(e) => setAddChannelForm({ ...addChannelForm, chatId: e.target.value })}
                          className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          placeholder="-1001234567890"
                        />
                      </div>
                    </>
                  )}

                  {/* Server酱 配置 */}
                  {addChannelForm.channelType === 'WECHAT_SERVERCHAN' && (
                    <div>
                      <label className="text-xs text-[#8a8a8a]">SendKey</label>
                      <input
                        type="password"
                        value={addChannelForm.sendKey}
                        onChange={(e) => setAddChannelForm({ ...addChannelForm, sendKey: e.target.value })}
                        className="w-full mt-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        placeholder="SCTxxxx..."
                      />
                    </div>
                  )}

                  {/* 推送类型 */}
                  <div>
                    <label className="text-xs text-[#8a8a8a]">推送类型</label>
                    <div className="flex flex-wrap gap-1.5 mt-1">
                      {[
                        { key: 'trade_signal', label: '交易信号' },
                        { key: 'risk_alert', label: '风险告警' },
                        { key: 'intel_update', label: '情报更新' },
                        { key: 'daily_report', label: '每日报告' },
                        { key: 'strategy_update', label: '策略推荐' },
                      ].map(({ key, label }) => (
                        <button
                          key={key}
                          onClick={() => {
                            const types = addChannelForm.enabledTypes.includes(key)
                              ? addChannelForm.enabledTypes.filter((t: string) => t !== key)
                              : [...addChannelForm.enabledTypes, key];
                            setAddChannelForm({ ...addChannelForm, enabledTypes: types });
                          }}
                          className={`px-2 py-0.5 text-xs rounded transition ${
                            addChannelForm.enabledTypes.includes(key)
                              ? 'bg-[#0066ff] text-white'
                              : 'bg-[#141414] text-[#8a8a8a] border border-[#2a2a2a]'
                          }`}
                        >
                          {label}
                        </button>
                      ))}
                    </div>
                  </div>

                  {/* 静默时段 */}
                  <div>
                    <label className="text-xs text-[#8a8a8a]">静默时段 (可选)</label>
                    <div className="flex gap-2 mt-1">
                      <input
                        value={addChannelForm.silentStart}
                        onChange={(e) => setAddChannelForm({ ...addChannelForm, silentStart: e.target.value })}
                        className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        placeholder="23:00"
                      />
                      <span className="text-xs text-[#8a8a8a] self-center">-</span>
                      <input
                        value={addChannelForm.silentEnd}
                        onChange={(e) => setAddChannelForm({ ...addChannelForm, silentEnd: e.target.value })}
                        className="flex-1 bg-[#141414] border border-[#2a2a2a] rounded-md px-2.5 py-1.5 text-xs text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                        placeholder="07:00"
                      />
                    </div>
                  </div>

                  <div className="flex gap-2 pt-1">
                    <button
                      onClick={async () => {
                        const credentials: Record<string, string> = {};
                        if (addChannelForm.channelType === 'TELEGRAM') {
                          credentials.botToken = addChannelForm.botToken;
                          credentials.chatId = addChannelForm.chatId;
                        } else if (addChannelForm.channelType === 'WECHAT_SERVERCHAN') {
                          credentials.sendKey = addChannelForm.sendKey;
                        }
                        try {
                          const res = await fetch('/api/config/channels', {
                            method: 'POST',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({
                              channelType: addChannelForm.channelType,
                              label: addChannelForm.label,
                              credentials,
                              pushRules: { enabledTypes: addChannelForm.enabledTypes },
                              silentStart: addChannelForm.silentStart || null,
                              silentEnd: addChannelForm.silentEnd || null,
                              format: addChannelForm.format,
                            }),
                          });
                          const data = await res.json();
                          if (data.success) {
                            setShowAddChannelForm(false);
                            setAddChannelForm({
                              channelType: 'TELEGRAM', label: '', botToken: '', chatId: '', sendKey: '',
                              enabledTypes: ['trade_signal', 'risk_alert', 'intel_update'],
                              format: 'CONCISE', silentStart: '', silentEnd: '',
                            });
                            fetchChannels();
                          } else { alert(data.error || '添加失败'); }
                        } catch { alert('添加失败'); }
                      }}
                      className="flex-1 px-3 py-2 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition font-medium"
                    >
                      💾 保存
                    </button>
                    <button
                      onClick={() => setShowAddChannelForm(false)}
                      className="px-3 py-2 text-xs bg-[#2a2a2a] text-[#8a8a8a] rounded hover:bg-[#1a1a1a] transition"
                    >
                      取消
                    </button>
                  </div>
                </div>
              </div>
            )}

            {/* 渠道列表 */}
            {channelsLoading ? (
              <div className="config-section text-center text-xs text-[#8a8a8a]">⏳ 加载中...</div>
            ) : (channels as any[]).length === 0 ? (
              <div className="config-section text-center text-xs text-[#8a8a8a]">
                暂无通信渠道配置<br />
                <span className="text-xs">点击上方"➕ 添加"按钮配置</span>
              </div>
            ) : (
              (channels as any[]).map((ch: any) => (
                <div key={ch.id} className="config-section">
                  <div className="flex justify-between items-center mb-2">
                    <div className="font-semibold">
                      {ch.channelType === 'TELEGRAM' ? '📱' : ch.channelType === 'WECHAT_SERVERCHAN' ? '💬' : '📧'} {ch.label || ch.channelType}
                    </div>
                    <span className={`px-2 py-0.5 rounded text-xs font-semibold ${ch.isOnline ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                      {ch.isOnline ? '● 在线' : '○ 离线'}
                    </span>
                  </div>
                  {ch.pushRules?.enabledTypes && (
                    <div className="text-xs text-[#8a8a8a] mb-1">
                      推送: {ch.pushRules.enabledTypes.map((t: string) => {
                        const labels: Record<string, string> = { trade_signal: '交易信号', risk_alert: '风险告警', intel_update: '情报更新', daily_report: '每日报告', strategy_update: '策略推荐' };
                        return labels[t] || t;
                      }).join('/')}
                    </div>
                  )}
                  {(ch.silentStart && ch.silentEnd) && (
                    <div className="text-xs text-[#8a8a8a]">静默: {ch.silentStart} - {ch.silentEnd}</div>
                  )}
                  {/* 测试结果 */}
                  {channelTestResult && channelTestResult[ch.id] && (
                    <div className={`text-xs mb-2 p-2 rounded ${channelTestResult[ch.id].success ? 'bg-green-500/10 text-green-400' : 'bg-red-500/10 text-red-400'}`}>
                      {channelTestResult[ch.id].success ? '✅' : '❌'} {channelTestResult[ch.id].message}
                    </div>
                  )}
                  <div className="flex gap-2 mt-2">
                    <button
                      onClick={async () => {
                        setChannelTesting(ch.id);
                        setChannelTestResult(null);
                        try {
                          const res = await fetch(`/api/config/channels/${ch.id}/test`, { method: 'POST' });
                          const data = await res.json();
                          if (data.success) {
                            setChannelTestResult({ [ch.id]: data.data });
                            if (data.data?.success) fetchChannels();
                          }
                        } catch {} finally { setChannelTesting(null); }
                      }}
                      disabled={channelTesting === ch.id}
                      className="px-2.5 py-1 text-xs bg-[#0066ff] text-white rounded hover:bg-blue-700 transition disabled:opacity-50"
                    >
                      {channelTesting === ch.id ? '⏳ 测试中...' : '测试'}
                    </button>
                    <button
                      onClick={async () => {
                        if (!confirm('确定删除此渠道？')) return;
                        try {
                          await fetch(`/api/config/channels?id=${ch.id}`, { method: 'DELETE' });
                          fetchChannels();
                        } catch {}
                      }}
                      className="px-2.5 py-1 text-xs bg-red-500 text-white rounded hover:bg-red-600 transition"
                    >
                      删除
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        );
      case 'monitor':
        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>📡 信息传递监控</div>
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setMonitorPaused(!monitorPaused)}
                  className="text-[10px] px-2 py-1 rounded transition"
                  style={{ background: monitorPaused ? '#3b82f6' : '#0f3460', color: monitorPaused ? '#fff' : '#a1a1aa' }}
                >
                  {monitorPaused ? '▶ 恢复' : '⏸ 暂停'}
                </button>
                <button
                  onClick={() => setMonitorEvents([])}
                  className="text-[10px] px-2 py-1 rounded bg-[#0f3460] text-[#8a8a8a] hover:text-[#e0e0e0] transition"
                >
                  🗑 清除
                </button>
              </div>
            </div>

            {/* ===== 全链路状态概览 ===== */}
            <div className="config-section mb-3">
              <div className="text-[10px] text-[#8a8a8a] mb-2 font-semibold">全链路状态</div>
              <div className="flex items-center gap-1 text-[10px]">
                {monitorPipeline ? (
                  <>
                    {(['frontend', 'gateway', 'workbuddy', 'artifact_hub'] as const).map((layer, idx) => {
                      const info = monitorPipeline[layer];
                      const labels: Record<string, string> = {
                        frontend: '前端', gateway: '中台', workbuddy: 'WB', artifact_hub: '产物',
                      };
                      const icons: Record<string, string> = {
                        frontend: '🖥️', gateway: '🔀', workbuddy: '⚙️', artifact_hub: '📦',
                      };
                      const isHealthy = info.rate !== '--' && parseInt(info.rate) >= 90;
                      const isWarning = info.rate !== '--' && parseInt(info.rate) >= 70 && parseInt(info.rate) < 90;
                      return (
                        <div key={layer} className="flex items-center gap-0.5">
                          {idx > 0 && <span className="text-[#8a8a8a]">→</span>}
                          <div className={`px-1.5 py-1 rounded text-center min-w-[52px] ${
                            isHealthy ? 'bg-green-500/15 border border-green-500/20' :
                            isWarning ? 'bg-yellow-500/15 border border-yellow-500/20' :
                            'bg-[#0f3460] border border-[#1a1a2e]'
                          }`}>
                            <div className="text-[9px]">{icons[layer]} {labels[layer]}</div>
                            <div className={`font-bold ${
                              isHealthy ? 'text-green-400' : isWarning ? 'text-yellow-400' : 'text-[#8a8a8a]'
                            }`}>
                              {info.rate === '--' ? '--' : info.rate}
                            </div>
                            <div className="text-[8px] text-[#8a8a8a]">{info.completed}/{info.total}</div>
                          </div>
                        </div>
                      );
                    })}
                  </>
                ) : (
                  <span className="text-[#8a8a8a]">等待数据...</span>
                )}
              </div>
            </div>

            {/* ===== 实时事件流 ===== */}
            <div className="config-section mb-3" style={{ maxHeight: '240px', overflowY: 'auto' }}>
              <div className="text-[10px] text-[#8a8a8a] mb-2 font-semibold">
                实时事件流 {monitorPaused && <span className="text-yellow-400">（已暂停）</span>}
              </div>
              {monitorEvents.length === 0 ? (
                <div className="text-[10px] text-[#8a8a8a] text-center py-3">
                  暂无事件 — 提交请求后自动显示
                </div>
              ) : (
                <div className="space-y-1">
                  {monitorEvents.slice(0, 20).map((event) => {
                    const time = new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false });
                    const statusIcon: Record<string, string> = {
                      received: '📥', processing: '🔄', completed: '✅', failed: '❌', timeout: '⏱️',
                    };
                    const layerColors: Record<string, string> = {
                      frontend: '#3b82f6', gateway: '#8b5cf6', workbuddy: '#f59e0b', artifact_hub: '#22c55e',
                    };
                    const phaseLabels: Record<string, string> = {
                      user_input: '用户请求', intent_recognized: '意图识别', task_created: '任务创建',
                      inline_exec_start: '内联执行→', inline_exec_done: '内联完成✓',
                      async_spawned: '异步触发', trade_pending: '交易待确认',
                      wb_received: 'WB接收', wb_completed: 'WB完成', wb_failed: 'WB失败',
                      artifact_synced: '产物同步', feed_ready: 'Feed就绪', result_displayed: '结果展示',
                      chain_started: '链路启动', index_updated: '索引更新', wb_processing: 'WB处理中',
                    };
                    const isSelected = monitorSelectedTrace === event.trace_id;
                    return (
                      <div
                        key={event.id}
                        onClick={() => setMonitorSelectedTrace(isSelected ? null : event.trace_id)}
                        className={`flex items-center gap-1.5 py-1 px-1.5 rounded cursor-pointer transition text-[10px] ${
                          event.status === 'failed' || event.status === 'timeout'
                            ? 'bg-red-500/10 border border-red-500/20'
                            : isSelected
                            ? 'bg-[#0066ff]/15 border border-[#0066ff]/30'
                            : 'hover:bg-[#1f1f1f]/40'
                        }`}
                      >
                        <span className="text-[9px] text-[#8a8a8a] flex-shrink-0">{time}</span>
                        <span>{statusIcon[event.status] || '❓'}</span>
                        <span
                          className="px-1 rounded text-[8px] font-bold text-white flex-shrink-0"
                          style={{ backgroundColor: layerColors[event.layer] || '#666' }}
                        >
                          {event.layer.slice(0, 3).toUpperCase()}
                        </span>
                        <span className="text-[#e0e0e0] flex-1 truncate">
                          {phaseLabels[event.phase] || event.phase}
                        </span>
                        {event.duration_ms != null && (
                          <span className="text-[8px] text-[#8a8a8a] flex-shrink-0">{event.duration_ms}ms</span>
                        )}
                        {event.intent && (
                          <span className="text-[8px] text-[#3b82f6] flex-shrink-0 truncate max-w-[50px]">{event.intent}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>

            {/* ===== 链路追踪详情 ===== */}
            {monitorSelectedTrace && (
              <div className="config-section mb-3 border border-[#0066ff]/20 rounded-lg p-2">
                <div className="text-[10px] text-[#3b82f6] font-semibold mb-2">
                  🔗 链路追踪: {monitorSelectedTrace.slice(0, 30)}...
                </div>
                {(() => {
                  const traceEvents = monitorEvents
                    .filter(e => e.trace_id === monitorSelectedTrace)
                    .sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime());
                  return (
                    <div className="space-y-1">
                      {traceEvents.map((event, idx) => {
                        const time = new Date(event.timestamp).toLocaleTimeString('zh-CN', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
                        const statusColors: Record<string, string> = {
                          received: '#3b82f6', processing: '#f59e0b', completed: '#22c55e', failed: '#ef4444', timeout: '#f59e0b',
                        };
                        return (
                          <div key={event.id} className="flex items-center gap-1.5 text-[9px]">
                            <span className="text-[#8a8a8a] w-16 flex-shrink-0">{time}</span>
                            <div className="w-2 h-2 rounded-full flex-shrink-0" style={{ backgroundColor: statusColors[event.status] || '#666' }} />
                            <span className="text-[#e0e0e0]">{event.phase}</span>
                            {event.intent && <span className="text-[#3b82f6]">[{event.intent}]</span>}
                            {event.duration_ms != null && <span className="text-[#8a8a8a]">{event.duration_ms}ms</span>}
                            {event.error && <span className="text-red-400 truncate max-w-[80px]">{event.error}</span>}
                          </div>
                        );
                      })}
                      {traceEvents.length === 0 && (
                        <span className="text-[#8a8a8a] text-[9px]">暂无此 trace 的事件</span>
                      )}
                    </div>
                  );
                })()}
              </div>
            )}

            {/* ===== 统计面板 ===== */}
            <div className="config-section">
              <div className="text-[10px] text-[#8a8a8a] mb-2 font-semibold">统计</div>
              {monitorStats ? (
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[#8a8a8a] text-[8px]">今日请求</div>
                    <div className="font-bold text-[#e0e0e0]">{monitorStats.total_requests}</div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[#8a8a8a] text-[8px]">成功率</div>
                    <div className={`font-bold ${monitorStats.success_rate >= 90 ? 'text-green-400' : monitorStats.success_rate >= 70 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {monitorStats.success_rate}%
                    </div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[#8a8a8a] text-[8px]">均耗时</div>
                    <div className="font-bold text-[#e0e0e0]">{monitorStats.avg_duration_ms}ms</div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[#8a8a8a] text-[8px]">活跃Trace</div>
                    <div className="font-bold text-[#3b82f6]">{monitorStats.active_traces}</div>
                  </div>
                </div>
              ) : (
                <span className="text-[10px] text-[#8a8a8a]">等待数据...</span>
              )}
              {/* 意图分布 */}
              {monitorStats?.intent_distribution && Object.keys(monitorStats.intent_distribution).length > 0 && (
                <div className="mt-2">
                  <div className="text-[8px] text-[#8a8a8a] mb-1">意图分布</div>
                  <div className="flex flex-wrap gap-1">
                    {Object.entries(monitorStats.intent_distribution).map(([intent, count]) => {
                      const intentColors: Record<string, string> = {
                        market_query: '#3b82f6', deep_analysis: '#8b5cf6', scenario_sim: '#f59e0b',
                        strategy_verify: '#06b6d4', execute_trade: '#22c55e', simple_qa: '#a1a1aa',
                      };
                      const intentLabels: Record<string, string> = {
                        market_query: '行情', deep_analysis: '分析', scenario_sim: '推演',
                        strategy_verify: '验证', execute_trade: '交易', simple_qa: '问答',
                      };
                      return (
                        <span key={intent} className="text-[8px] px-1.5 py-0.5 rounded text-white"
                          style={{ backgroundColor: intentColors[intent] || '#666' }}>
                          {intentLabels[intent] || intent}: {count}
                        </span>
                      );
                    })}
                  </div>
                </div>
              )}
              {/* 异常统计 */}
              {monitorStats && (monitorStats.total_failed > 0 || monitorStats.total_timeout > 0) && (
                <div className="mt-2 flex items-center gap-2 text-[9px]">
                  <span className="text-red-400">❌ 失败: {monitorStats.total_failed}</span>
                  <span className="text-yellow-400">⏱️ 超时: {monitorStats.total_timeout}</span>
                </div>
              )}
            </div>
          </div>
        );

      case 'report':
        return (
          <div>
            <div className="flex items-center gap-2 mb-3">
              <button
                onClick={() => { setSelectedReport(null); setRightPanelContent('analysis'); }}
                className="text-[#8a8a8a] hover:text-[#e0e0e0] transition"
              >
                ←
              </button>
              <div className="panel-title" style={{ marginBottom: 0 }}>📄 研报详情</div>
            </div>
            {reportContentLoading ? (
              <div className="config-section text-center">
                <span className="text-[#8a8a8a]">⏳ 加载中...</span>
              </div>
            ) : selectedReport ? (
              <div className="report-content">
                {/* 元数据标签 */}
                {selectedReport.metadata && (
                  <div className="config-section mb-3">
                    <div className="flex items-center gap-2 mb-2">
                      <span
                        className="px-2 py-0.5 rounded text-xs font-semibold text-white"
                        style={{ backgroundColor: selectedReport.metadata.phaseColor || '#3b82f6' }}
                      >
                        {selectedReport.metadata.chain_phase}
                      </span>
                      <span className="text-xs text-[#8a8a8a]">{selectedReport.metadata.title}</span>
                    </div>
                    <div className="text-xs text-[#8a8a8a]">
                      {selectedReport.metadata.regime && <span>Regime: {selectedReport.metadata.regime} | </span>}
                      {selectedReport.metadata.confidence !== undefined && <span>置信度: {selectedReport.metadata.confidence}% | </span>}
                      {selectedReport.metadata.direction && <span>方向: {selectedReport.metadata.direction}</span>}
                    </div>
                  </div>
                )}
                {/* Markdown内容 */}
                <div className="report-markdown">
                  <ReactMarkdown>{selectedReport.content}</ReactMarkdown>
                </div>
              </div>
            ) : (
              <div className="config-section text-center text-[#8a8a8a] text-xs">
                未选择研报
              </div>
            )}
          </div>
        );

      case 'memory':
        const intentLabel: Record<string, string> = {
          market_query: '行情', deep_analysis: '分析', scenario_sim: '推演',
          strategy_verify: '验证', execute_trade: '交易', simple_qa: '问答',
          command: '命令', system_config: '配置', credits_query: '积分',
          artifact_query: '产物', risk_alert_response: '风险',
        };
        const methodColor: Record<string, string> = {
          llm: '#3b82f6', rule: '#f59e0b', follow_up: '#22c55e', default: '#6b7280',
        };
        const methodLabel: Record<string, string> = {
          llm: 'LLM', rule: '规则', follow_up: '追问', default: '兜底',
        };

        return (
          <div>
            <div className="flex items-center justify-between mb-3">
              <div className="panel-title" style={{ marginBottom: 0 }}>🧠 意图记忆库</div>
              <button
                onClick={triggerEvolve}
                className="text-[10px] px-2 py-1 rounded bg-[#8b5cf6]/20 text-[#8b5cf6] hover:bg-[#8b5cf6]/30 transition"
              >
                🔄 进化
              </button>
            </div>

            {/* 统计概览 */}
            <div className="config-section mb-3">
              <div className="text-[10px] text-[#a1a1aa] mb-2 font-semibold">学习统计</div>
              {memoryStats ? (
                <div className="grid grid-cols-2 gap-2 text-[10px]">
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[8px] text-[#a1a1aa]">总记录</div>
                    <div className="font-bold text-[#e4e4e7]">{memoryStats.total_records}</div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[8px] text-[#a1a1aa]">准确率</div>
                    <div className={`font-bold ${memoryStats.accuracy_rate >= 80 ? 'text-green-400' : memoryStats.accuracy_rate >= 60 ? 'text-yellow-400' : 'text-red-400'}`}>
                      {memoryStats.accuracy_rate}%
                    </div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[8px] text-[#a1a1aa]">平均置信度</div>
                    <div className="font-bold text-[#3b82f6]">{memoryStats.avg_confidence}</div>
                  </div>
                  <div className="bg-[#0f3460] rounded p-1.5 text-center">
                    <div className="text-[8px] text-[#a1a1aa]">反馈</div>
                    <div className="font-bold">
                      <span className="text-green-400">{memoryStats.feedback_counts.correct}</span>
                      /<span className="text-red-400">{memoryStats.feedback_counts.incorrect}</span>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="text-[10px] text-[#a1a1aa] text-center py-2">等待数据...</div>
              )}
            </div>

            {/* 方法分布 */}
            {memoryStats?.method_distribution && Object.keys(memoryStats.method_distribution).length > 0 && (
              <div className="config-section mb-3">
                <div className="text-[8px] text-[#a1a1aa] mb-1">识别方法分布</div>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(memoryStats.method_distribution).map(([method, count]) => (
                    <span key={method} className="text-[8px] px-1.5 py-0.5 rounded text-white"
                      style={{ backgroundColor: methodColor[method] || '#666' }}>
                      {methodLabel[method] || method}: {String(count)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 意图分布 */}
            {memoryStats?.intent_distribution && Object.keys(memoryStats.intent_distribution).length > 0 && (
              <div className="config-section mb-3">
                <div className="text-[8px] text-[#a1a1aa] mb-1">意图分布</div>
                <div className="flex flex-wrap gap-1">
                  {Object.entries(memoryStats.intent_distribution).map(([intent, count]) => (
                    <span key={intent} className="text-[8px] px-1.5 py-0.5 rounded text-white"
                      style={{ backgroundColor: '#3b82f6' }}>
                      {intentLabel[intent] || intent}: {String(count)}
                    </span>
                  ))}
                </div>
              </div>
            )}

            {/* 置信度调整推荐 */}
            {memoryAdjustments.length > 0 && (
              <div className="config-section mb-3">
                <div className="text-[10px] text-[#8b5cf6] mb-1 font-semibold">⚙️ 置信度调整推荐</div>
                {memoryAdjustments.slice(0, 5).map((adj) => (
                  <div key={adj.pattern_id} className="flex items-center justify-between py-0.5 text-[9px]">
                    <span className="text-[#e4e4e7]">{adj.pattern_id}</span>
                    <span className={adj.delta > 0 ? 'text-green-400' : 'text-red-400'}>
                      {adj.current_confidence} → {adj.suggested_confidence} ({adj.delta > 0 ? '+' : ''}{adj.delta})
                    </span>
                  </div>
                ))}
              </div>
            )}

            {/* 候选新模式 */}
            {memoryCandidates.length > 0 && (
              <div className="config-section mb-3">
                <div className="text-[10px] text-[#22c55e] mb-1 font-semibold">💡 候选新模式</div>
                {memoryCandidates.slice(0, 3).map((c, idx) => (
                  <div key={idx} className="bg-[#0f3460] rounded p-1.5 mb-1">
                    <div className="flex items-center justify-between text-[9px]">
                      <span className="text-[#3b82f6]">{intentLabel[c.intent] || c.intent}</span>
                      <span className="text-[#a1a1aa]">{c.occurrences}次</span>
                    </div>
                    <div className="text-[8px] text-[#e4e4e7] mt-0.5">关键词: {c.keywords.join(', ')}</div>
                    <button
                      onClick={() => adoptCandidate(c)}
                      className="text-[8px] mt-1 px-1.5 py-0.5 rounded bg-[#22c55e]/20 text-[#22c55e] hover:bg-[#22c55e]/30 transition"
                    >
                      采纳
                    </button>
                  </div>
                ))}
              </div>
            )}

            {/* 识别记录列表 */}
            <div className="config-section" style={{ maxHeight: '300px', overflowY: 'auto' }}>
              <div className="text-[10px] text-[#a1a1aa] mb-2 font-semibold">识别记录</div>
              {memoryRecords.length === 0 ? (
                <div className="text-[10px] text-[#a1a1aa] text-center py-3">暂无记录</div>
              ) : (
                <div className="space-y-1">
                  {memoryRecords.map((r) => (
                    <div key={r.id} className="py-1 px-1.5 rounded text-[9px] bg-[#0f3460]/50 hover:bg-[#0f3460] transition">
                      <div className="flex items-center justify-between mb-0.5">
                        <span className="text-[#e4e4e7] font-medium truncate">{r.input}</span>
                        <span className="text-[#a1a1aa] flex-shrink-0 ml-1">{r.recognized_confidence.toFixed(2)}</span>
                      </div>
                      <div className="flex items-center gap-1">
                        <span className="px-1 rounded text-[8px] text-white"
                          style={{ backgroundColor: '#3b82f6' }}>
                          {intentLabel[r.recognized_intent] || r.recognized_intent}
                        </span>
                        <span className="px-1 rounded text-[8px] text-white"
                          style={{ backgroundColor: methodColor[r.recognized_method] || '#666' }}>
                          {methodLabel[r.recognized_method] || r.recognized_method}
                        </span>
                        {r.user_feedback === 'correct' && <span className="text-green-400">✓</span>}
                        {r.user_feedback === 'incorrect' && <span className="text-red-400">✗</span>}
                        {r.user_feedback === null && (
                          <div className="flex gap-1 ml-auto">
                            <button
                              onClick={() => submitMemoryFeedback(r.id, 'correct')}
                              className="text-green-400 hover:text-green-300"
                            >✓</button>
                            <button
                              onClick={() => submitMemoryFeedback(r.id, 'incorrect')}
                              className="text-red-400 hover:text-red-300"
                            >✗</button>
                          </div>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        );

      default:
        return (
          <div>
            <div className="panel-title">📌 分析面板</div>
            
            {/* ===== 动态分析链路进度 ===== */}
            {analysisChain.length > 0 ? (
              <div>
                <div className="panel-subtitle">
                  📊 分析进度 
                  {analysisStartTime && (
                    <span className="text-[10px] text-[#8a8a8a] ml-2">
                      {(() => {
                        const endTime = analysisEndTime || Date.now();
                        const elapsed = Math.floor((endTime - analysisStartTime) / 1000);
                        return elapsed < 60 ? `${elapsed}s` : `${Math.floor(elapsed/60)}m${elapsed%60}s`;
                      })()}
                    </span>
                  )}
                  {analysisConfidence !== null && (
                    <span className={`ml-2 text-[10px] px-1 py-0.5 rounded ${
                      analysisConfidence >= 60 ? 'bg-green-500/20 text-green-400' :
                      analysisConfidence >= 40 ? 'bg-yellow-500/20 text-yellow-400' :
                      'bg-red-500/20 text-red-400'
                    }`}>
                      {analysisConfidence}% 置信度
                    </span>
                  )}
                </div>
                
                {/* 总体进度条 */}
                <div className="config-section mb-3">
                  <div className="flex items-center justify-between mb-1.5">
                    <span className="text-[10px] text-[#8a8a8a]">
                      {analysisChain.filter(s => s.status === 'completed').length}/{analysisChain.length} 步骤完成
                    </span>
                    <span className="text-[10px] text-[#8a8a8a]">
                      {analysisChain.some(s => s.status === 'running') ? '执行中...' : 
                       analysisChain.every(s => s.status === 'completed') ? '✅ 全部完成' :
                       analysisChain.some(s => s.status === 'error') ? '❌ 执行异常' : '等待中'}
                    </span>
                  </div>
                  <div className="w-full bg-[#0f3460] rounded-full h-2 overflow-hidden">
                    <div 
                      className="h-full rounded-full transition-all duration-700 ease-out"
                      style={{ 
                        width: `${(analysisChain.filter(s => s.status === 'completed').length / analysisChain.length) * 100}%`,
                        background: analysisChain.some(s => s.status === 'error') 
                          ? 'linear-gradient(90deg, #22c55e, #ef4444)' 
                          : 'linear-gradient(90deg, #3b82f6, #22c55e)',
                      }}
                    />
                  </div>
                </div>

                {/* 链路步骤列表 */}
                <div className="config-section space-y-1">
                  {analysisChain.map((step, idx) => (
                    <div 
                      key={step.id}
                      className={`flex items-center gap-2 py-1.5 px-2 rounded transition-all duration-300 ${
                        step.status === 'running' ? 'bg-[#0f3460]/60 border border-[#0066ff]/30' : 
                        step.status === 'error' ? 'bg-red-500/10 border border-red-500/20' :
                        step.status === 'completed' ? '' : 'opacity-50'
                      }`}
                    >
                      {/* 步骤序号 + 状态图标 */}
                      <div className={`w-6 h-6 rounded-full flex items-center justify-center text-[11px] font-bold flex-shrink-0 ${
                        step.status === 'completed' ? 'bg-green-500/20 text-green-400' :
                        step.status === 'running' ? 'bg-[#0066ff]/20 text-[#3b82f6]' :
                        step.status === 'error' ? 'bg-red-500/20 text-red-400' :
                        'bg-[#0f3460] text-[#8a8a8a]'
                      }`}>
                        {step.status === 'completed' ? '✓' : 
                         step.status === 'running' ? (idx + 1) :
                         step.status === 'error' ? '✗' :
                         (idx + 1)}
                      </div>
                      
                      {/* 步骤图标+名称 */}
                      <span className={`text-xs flex-1 ${
                        step.status === 'completed' ? 'text-green-400' :
                        step.status === 'running' ? 'text-[#e0e0e0]' :
                        step.status === 'error' ? 'text-red-400' :
                        'text-[#8a8a8a]'
                      }`}>
                        {step.icon} {step.label}
                      </span>

                      {/* 状态标签 */}
                      {step.status === 'completed' && (
                        <span className="text-[10px] text-green-400">✅ 完成</span>
                      )}
                      {step.status === 'running' && (
                        <span className="text-[10px] text-[#3b82f6] animate-pulse">🔄 执行中</span>
                      )}
                      {step.status === 'error' && (
                        <span className="text-[10px] text-red-400">❌ 失败</span>
                      )}
                      {step.status === 'idle' && (
                        <span className="text-[10px] text-[#8a8a8a]">⏳ 等待</span>
                      )}

                      {/* 完成时间 */}
                      {step.timestamp && (
                        <span className="text-[9px] text-[#71717a]">{step.timestamp}</span>
                      )}
                    </div>
                  ))}
                </div>

                {/* 连接线 — 步骤间的视觉连接 */}
                <div className="flex items-center justify-center gap-1 mt-2 mb-1">
                  {analysisChain.map((step, idx) => (
                    <div key={step.id} className="flex items-center gap-1">
                      <div className={`w-2 h-2 rounded-full ${
                        step.status === 'completed' ? 'bg-green-500' :
                        step.status === 'running' ? 'bg-[#0066ff] animate-pulse' :
                        step.status === 'error' ? 'bg-red-500' :
                        'bg-[#0f3460]'
                      }`} />
                      {idx < analysisChain.length - 1 && (
                        <div className={`w-4 h-0.5 ${
                          step.status === 'completed' ? 'bg-green-500/50' : 'bg-[#0f3460]'
                        }`} />
                      )}
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              /* 空闲状态 — 显示提示 */
              <div className="config-section text-center py-6">
                <div className="text-2xl mb-2">🧠</div>
                <div className="text-xs text-[#8a8a8a] mb-1">暂无进行中的分析</div>
                <div className="text-[10px] text-[#71717a]">发送消息后，分析进度将在此实时显示</div>
                <div className="text-[10px] text-[#71717a] mt-1">
                  ⚡快速: S1→S2 | 🧠深度: S1→S2→S3→S4 | 🎯完整: S1→S2→S3→S4→S5
                </div>
              </div>
            )}

            <div className="panel-subtitle">📋 市场概况</div>
            <div className="config-section">
              <div className="config-row"><span>品种</span><span>BTC-USDT-SWAP</span></div>
              <div className="config-row"><span>状态</span><span className="text-yellow-500">区间震荡</span></div>
              <div className="config-row"><span>持仓</span><span>空仓</span></div>
              <div className="config-row"><span>恐惧指数</span><span>42 (恐惧)</span></div>
              <div className="config-row"><span>资金费率</span><span>+0.003%</span></div>
            </div>
            <div className="panel-subtitle">📄 最新研报 ({reportList.length})</div>
            {/* 非当日产物警告 */}
            {reportList.length > 0 && !reportList.some(r => r.isToday) && (
              <div className="config-section" style={{ borderLeft: '3px solid #eab308', padding: '8px 12px' }}>
                <div className="text-xs text-yellow-500">⚠️ 当前无当日产物，展示最近可用研报</div>
              </div>
            )}
            {reportLoading ? (
              <div className="config-section text-xs text-[#8a8a8a]">⏳ 加载中...</div>
            ) : reportList.length === 0 ? (
              <div className="config-section text-xs text-[#8a8a8a]">暂无研报</div>
            ) : (
              <div className="space-y-2">
                {reportList.map((report, idx) => (
                  <div
                    key={idx}
                    className="report-card"
                    onClick={() => fetchReportContent(report.file)}
                    style={{ borderLeftColor: report.phaseColor || '#3b82f6' }}
                  >
                    <div className="flex items-center gap-2 mb-1">
                      <span
                        className="px-1.5 py-0.5 rounded text-[10px] font-semibold text-white"
                        style={{ backgroundColor: report.phaseColor || '#3b82f6' }}
                      >
                        {report.chain_phase}
                      </span>
                      <span className="text-xs text-[#e0e0e0] truncate flex-1">{report.title}</span>
                      {/* 新鲜度标签 */}
                      {report.isToday ? (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-green-500/20 text-green-400">🟢 当日</span>
                      ) : (
                        <span className="px-1.5 py-0.5 rounded text-[10px] font-semibold bg-yellow-500/20 text-yellow-400">🟡 非当日</span>
                      )}
                    </div>
                    <div className="flex items-center gap-2 text-[10px] text-[#8a8a8a]">
                      <span>{report.relativeTime || (report.date ? new Date(report.date).toLocaleDateString('zh-CN') : '')}</span>
                      {report.confidence !== undefined && report.confidence !== null && (
                        <span className={`px-1 py-0.5 rounded ${
                          report.confidence >= 60 ? 'bg-green-500/20 text-green-400' :
                          report.confidence >= 40 ? 'bg-yellow-500/20 text-yellow-400' :
                          'bg-red-500/20 text-red-400'
                        }`}>
                          {report.confidence}%
                        </span>
                      )}
                      {report.direction && (
                        <span className={`${
                          report.direction === 'LONG' || report.direction === 'BUY' ? 'text-red-500' :
                          report.direction === 'SHORT' || report.direction === 'BEARISH' ? 'text-green-500' :
                          'text-[#8a8a8a]'
                        }`}>
                          {report.direction}
                        </span>
                      )}
                    </div>
                  </div>
                ))}
                {/* 查看全部按钮 */}
                <button
                  onClick={async () => {
                    setReportLoading(true);
                    try {
                      const res = await fetch('/api/reports?phases=A1,A2,A3,A6&limit=20');
                      const data = await res.json();
                      if (data.success) {
                        setReportList(data.data);
                      }
                    } catch {} finally {
                      setReportLoading(false);
                    }
                  }}
                  className="w-full text-center text-xs text-[#3b82f6] hover:text-[#60a5fa] transition py-2"
                >
                  📋 查看全部研报 →
                </button>
              </div>
            )}
          </div>
        );
    }
  };

  if (!mounted) {
    return (
      <div className="flex h-screen items-center justify-center bg-[#0d0d0d]">
        <div className="text-[#8a8a8a]">加载中...</div>
      </div>
    );
  }

  return (
    <main className="h-screen w-screen flex flex-col bg-[#0d0d0d] text-[#e0e0e0] overflow-hidden">
      <div className="h-11 flex-shrink-0 bg-[#1a1a1a] border-b border-[#1a1a1a] flex items-center px-2 gap-1">
        <button
          onClick={() => setActiveTab('trade')}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
            activeTab === 'trade'
              ? 'bg-[#0066ff] text-white'
              : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
          }`}
        >
          🔗 对话交易
        </button>
        <button
          onClick={() => setActiveTab('classic')}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
            activeTab === 'classic'
              ? 'bg-[#8b5cf6] text-white'
              : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
          }`}
        >
          📊 经典交易体系
        </button>
        <button
          onClick={() => router.push('/dashboard/fundamental/overview')}
          className={`px-4 py-1.5 rounded-md text-sm font-medium transition ${
            activeTab === 'fundamental'
              ? 'bg-[#f59e0b] text-white'
              : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
          }`}
        >
          🧭 基本面分析
        </button>
      </div>

      {activeTab === 'trade' && (
        <section className="flex-1 min-h-0 flex overflow-hidden">
          <div className="flex-1 flex min-h-0">
            {/* Left Sidebar */}
      <div
        className={`${leftCollapsed ? "w-0" : "w-64"} flex-shrink-0 flex flex-col bg-[#1a1a1a] border-r border-[#1a1a1a] transition-all duration-300 overflow-hidden`}
      >
        <div className="p-4 border-b border-[#1a1a1a] flex items-center justify-between">
          <h1 className="text-lg font-bold text-[#e0e0e0]">🧠 Dream</h1>
          {renderStatusDot(llmStatus)}
        </div>
        
        <div className="p-3">
          <button
            onClick={() => setLeftCollapsed(true)}
            className="w-full text-left px-3 py-2 text-sm text-[#8a8a8a] hover:bg-[#1f1f1f] rounded-md transition"
          >
            ← 收起
          </button>
        </div>
        
        <div className="flex-1 overflow-y-auto p-3 space-y-2">
          <div className="text-xs text-[#8a8a8a] px-3 py-1">今天</div>
          <div className="px-3 py-2 text-sm bg-[#0f3460] rounded-md text-[#3b82f6] cursor-pointer">
            🔴 BTC 行情分析
          </div>
          <div className="px-3 py-2 text-sm hover:bg-[#1f1f1f] rounded-md text-[#e0e0e0] cursor-pointer">
            📈 ETH 走势查看
          </div>
        </div>
        
        {/* Collapsible Modules */}
        <div className="p-3 space-y-2 border-t border-[#1a1a1a]">
          <div className="collapsible-module">
            <div 
              className="collapsible-header"
              onClick={() => setDataCardExpanded(!dataCardExpanded)}
            >
              <span className="flex items-center gap-2">📊 数据卡片</span>
              <span className={`arrow ${dataCardExpanded ? 'expanded' : ''}`}>▶</span>
            </div>
            <div className={`collapsible-content ${dataCardExpanded ? 'expanded' : ''}`}>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('market')}>📈 行情卡片</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('signal')}>📊 评分卡片</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('position')}>💼 持仓卡片</div>
            </div>
          </div>
          
          <div className="collapsible-module">
            <div
              className="collapsible-header"
              style={{ backgroundColor: '#0f3460', borderRadius: '6px' }}
              onClick={() => useAutoConfigStore.getState().start()}
            >
              <span className="flex items-center gap-2">🚀 开始自动化配置</span>
              <span className="text-[10px] text-[#8a8a8a]">4步快速配置</span>
            </div>
          </div>

          <div className="collapsible-module">
            <div
              className="collapsible-header"
              onClick={() => setSettingsExpanded(!settingsExpanded)}
            >
              <span className="flex items-center gap-2">⚙️ 设置</span>
              <span className={`arrow ${settingsExpanded ? 'expanded' : ''}`}>▶</span>
            </div>
            <div className={`collapsible-content ${settingsExpanded ? 'expanded' : ''}`}>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('llm')}>🤖 大模型配置</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('api')}>⚙️ 交易所API</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('trading')}>💰 交易设置</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('strategy')}>🎯 策略设置</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('communication')}>📡 通信渠道</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('monitor')}>📡 传递监控</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('memory')}>🧠 意图记忆库</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('notebook')}>📒 笔记本 (Notebook)</div>
              <div className="collapsible-item" onClick={() => handleShowRightPanel('graph-compression')}>🗜️ 图压缩</div>
            </div>
          </div>
        </div>
        
        {/* User Info */}
        <div className="p-3 border-t border-[#1a1a1a] bg-[#141414]">
          {mounted && session ? (
            <div className="flex items-center space-x-3 mb-2">
              <div className="w-8 h-8 bg-[#0066ff] rounded-full flex items-center justify-center text-sm">
                {(session.user?.name?.[0] || 'U').toUpperCase()}
              </div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold truncate">{session.user?.name || '用户'}</div>
                <div className="text-xs text-[#8a8a8a]">{session.user?.email || ''}</div>
              </div>
            </div>
          ) : (
            <div className="flex items-center space-x-3 mb-2">
              <div className="w-8 h-8 bg-gradient-to-br from-[#0066ff] to-[#0052cc] rounded-full flex items-center justify-center text-sm font-medium">U</div>
              <div className="flex-1 min-w-0">
                <div className="text-xs font-semibold truncate">测试用户</div>
                <div className="text-xs text-[#8a8a8a]">U3kR***xQ</div>
              </div>
            </div>
          )}
          <div className="flex items-center gap-2 mb-2 p-2 bg-[#1a1a1a] rounded-lg">
            <span className="text-sm">💎</span>
            <span className="text-xs text-[#8a8a8a]">积分</span>
            <span className="text-sm font-semibold text-[#ffffff] flex-1">{creditsBalance.toLocaleString()}</span>
            <button 
              onClick={() => navigateToRecharge(router)}
              className="px-2 py-1 text-xs bg-[#0066ff] text-white rounded hover:bg-[#0052cc] transition font-medium"
            >
              充值
            </button>
          </div>
          <div className="flex gap-2">
            <button 
              onClick={handleCheckin}
              disabled={checkinLoading || signedInToday}
              className={`flex-1 px-2.5 py-1.5 text-xs rounded transition ${
                signedInToday 
                  ? 'bg-[#333333] text-[#666666] cursor-not-allowed' 
                  : 'bg-[#0066ff] text-white hover:bg-[#0052cc]'
              }`}
            >
              {checkinLoading ? '签到中...' : signedInToday ? '已签到' : '签到+10'}
            </button>
            <button 
              onClick={handleLogout}
              className="flex-1 px-2.5 py-1.5 text-xs bg-[#1a1a1a] text-[#ff6b6b] border border-[#2a2a2a] rounded hover:bg-[#222222]"
            >
              退出登录
            </button>
          </div>
        </div>
      </div>

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-[600px] bg-[#0d0d0d]">
        {/* Header */}
        <div className="h-14 border-b border-[#1a1a1a] flex items-center justify-between px-4">
          <div className="flex items-center space-x-2">
            {leftCollapsed && (
              <button onClick={() => setLeftCollapsed(false)} className="p-1 hover:bg-[#1a1a1a] rounded transition">
                <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                </svg>
              </button>
            )}
            <span className="text-sm font-medium">BTC 行情分析</span>
            <button
              onClick={handleNewChat}
              disabled={isLoading}
              className="ml-2 px-3 py-1 text-xs bg-[#1a1a1a] hover:bg-[#2a2a2a] rounded-md text-[#e0e0e0] hover:text-white transition flex items-center gap-1 disabled:opacity-50 disabled:cursor-not-allowed"
              title="开启新对话，清空历史记录"
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
              </svg>
              新对话
            </button>
          </div>
          
          {/* 思考模式切换 */}
          <div className="flex items-center space-x-1 bg-[#1a1a1a] rounded-lg p-0.5">
            <button
              onClick={() => setThinkingMode('quick')}
              className={`px-3 py-1.5 text-xs rounded-md transition ${
                thinkingMode === 'quick'
                  ? 'bg-[#0066ff] text-white shadow-lg shadow-blue-500/20'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="智能思考：轻量级，直接调用SKILL"
            >
              ⚡ 智能思考
            </button>
            <button
              onClick={() => setThinkingMode('deep')}
              className={`px-3 py-1.5 text-xs rounded-md transition ${
                thinkingMode === 'deep'
                  ? 'bg-[#8b5cf6] text-white shadow-lg shadow-purple-500/20'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="深度思考：完整S1-S5闭环"
            >
              🧠 深度思考
            </button>
          </div>

          {/* 交易模式切换：AI SKILL / Classic */}
          <div className="flex items-center space-x-1 bg-[#1a1a1a] rounded-lg p-0.5">
            <button
              onClick={() => setTradingMode('ai_skill')}
              className={`px-3 py-1.5 text-xs rounded-md transition ${
                tradingMode === 'ai_skill'
                  ? 'bg-[#f59e0b] text-black shadow-lg shadow-amber-500/20 font-medium'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="AI SKILL 模式：自然语言通过 OKX Agent CLI 下单，灵活但消耗 Token"
            >
              🤖 AI SKILL
            </button>
            <button
              onClick={() => setTradingMode('classic')}
              className={`px-3 py-1.5 text-xs rounded-md transition ${
                tradingMode === 'classic'
                  ? 'bg-[#22c55e] text-white shadow-lg shadow-green-500/20 font-medium'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="经典交易体系：通过 Freqtrade 策略代码驱动，可回测可审计，低 Token 成本"
            >
              📊 经典交易
            </button>
          </div>

          {/* 语言切换 */}
          <div className="flex items-center space-x-1 bg-[#1a1a1a] rounded-lg p-0.5">
            <button
              onClick={() => setLang('zh')}
              className={`px-2 py-1.5 text-xs rounded-md transition ${
                lang === 'zh'
                  ? 'bg-[#f59e0b] text-black shadow-lg shadow-amber-500/20 font-medium'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="中文"
            >
              🀄 中文
            </button>
            <button
              onClick={() => setLang('en')}
              className={`px-2 py-1.5 text-xs rounded-md transition ${
                lang === 'en'
                  ? 'bg-[#f59e0b] text-black shadow-lg shadow-amber-500/20 font-medium'
                  : 'text-[#8a8a8a] hover:text-[#e0e0e0]'
              }`}
              title="English"
            >
              🇺🇸 EN
            </button>
          </div>
          
          <button
            onClick={() => setRightCollapsed(!rightCollapsed)}
            className="p-1 hover:bg-[#1a1a1a] rounded text-[#8a8a8a] transition"
          >
            <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
            </svg>
          </button>
        </div>
        
        {/* Messages */}
        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          <AutoConfigBubble />
          <AutoConfigSummary />
          {/* 🛡️ 渲染层去重：1) 同 taskId 保留最新；2) 连续重复 user 消息去重；3) 永远只保留最后一个 thinking */}
          {(() => {
            const dedupByTaskId = (() => {
              const map = new Map<string, number>();
              messages.forEach((m: any, idx) => {
                if (m?.task_id) {
                  map.set(m.task_id, idx);
                }
              });
              return messages.filter((m: any, idx: number) => !m?.task_id || map.get(m.task_id) === idx);
            })();
            // 连续 user 消息去重 (相同 content)
            const dedupUser = dedupByTaskId.filter((m, idx, arr) => {
              if (idx === 0) return true;
              const prev = arr[idx - 1];
              if (m.role === 'user' && prev?.role === 'user' && m.content === prev.content) return false;
              return true;
            });
            // thinking 消息只保留最后一个
            const lastThinkingIdx = dedupUser.map((m: any) => m.intent).lastIndexOf('thinking');
            const finalMessages = dedupUser.filter((m: any, idx) => m.intent !== 'thinking' || idx === lastThinkingIdx);
            return finalMessages.map((msg, i) => (
            <div key={i} className={`flex ${msg.role === "user" ? "justify-end" : "justify-start"}`}>
              <div
                className={`max-w-[80%] px-4 py-3 rounded-lg ${
                  msg.role === "user"
                    ? "bg-[#0066ff] text-white"
                    : "bg-[#1a1a1a] text-[#e0e0e0]"
                }`}
              >
                {msg.role === "assistant" && (
                  <div className="text-[#06b6d4] text-xs mb-1.5 flex items-center gap-2 flex-wrap">
                    <span>🤖 AI助手 · {i === 0 ? "2秒前" : "刚刚"}</span>
                    {msg.intent && msg.intent !== "unknown" && msg.intent !== "thinking" && msg.intent !== "error" && (
                      <span className="bg-[#0f3460] px-1.5 py-0.5 rounded text-[10px]">
                        {msg.intent}
                      </span>
                    )}
                    {msg.confidence !== undefined && (
                      <span className={`px-1.5 py-0.5 rounded text-[10px] ${
                        msg.confidence >= 0.8 ? 'bg-green-500/20 text-green-400' : 
                        msg.confidence >= 0.6 ? 'bg-yellow-500/20 text-yellow-400' : 
                        'bg-red-500/20 text-red-400'
                      }`}>
                        置信度 {(msg.confidence * 100).toFixed(0)}%
                      </span>
                    )}
                    {msg.context_aware && (
                      <span className="bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded text-[10px]">
                        💡 上下文
                      </span>
                    )}
                    {msg.thinking_mode && msg.thinking_mode !== 'quick' && (
                      <span className="bg-purple-500/20 text-purple-400 px-1.5 py-0.5 rounded text-[10px]">
                        🧠 深度
                      </span>
                    )}
                  </div>
                )}
                {/* 🧠 思考卡 */}
                {msg.role === "assistant" && ((msg as any).chain_trace || msg.intent === 'thinking') && msg.intent !== 'error' && (
                  <ThinkingCard
                    trace={(msg as any).chain_trace}
                    isLoading={msg.intent === 'thinking'}
                    streamProgress={msg.intent === 'thinking' && i === finalMessages.length - 1 ? streamProgress : undefined}
                  />
                )}
                {msg.role === "user" && (
                  <div className="text-right text-xs mb-1.5 opacity-70">👤 你</div>
                )}
                <div className="text-sm prose prose-invert prose-sm max-w-none chat-markdown">
                  <ReactMarkdown
                    components={{
                      a: ({ node, ...props }) => {
                        const isReportLink = props.href?.startsWith('/reports/');
                        const isInternal = props.href?.startsWith('/');
                        return (
                          <a
                            {...props}
                            target={isReportLink ? '_blank' : (isInternal ? undefined : '_blank')}
                            rel={isInternal && !isReportLink ? undefined : 'noopener noreferrer'}
                            className="text-blue-400 hover:text-blue-300 underline"
                          />
                        );
                      },
                      details: ({ node, children, ...props }) => (
                        <details className="my-2 text-xs" {...props}>
                          {children}
                        </details>
                      ),
                      summary: ({ node, children, ...props }) => (
                        <summary className="cursor-pointer text-gray-400 hover:text-gray-300" {...props}>
                          {children}
                        </summary>
                      ),
                    }}
                  >
                    {msg.content}
                  </ReactMarkdown>
                </div>
                {/* 🏆 笔记本 7 步进度条 */}
                {msg.role === "assistant" && ((msg as any).stepProgress || (msg as any).step_progress) && (() => {
                  const sp = (msg as any).stepProgress || (msg as any).step_progress;
                  return (
                    <div className="mt-4 pt-3 border-t border-[#2a2a2a]">
                      <div className="text-[11px] text-[#8a8a8a] mb-2">📖 笔记本 · 7步进度</div>
                      <div className="flex items-center gap-1">
                        {sp.steps.map((s: any, idx: number) => {
                          const isActive = s.status === 'active';
                          const isDone = s.status === 'completed';
                          const isSkipped = s.status === 'skipped';
                          return (
                            <div key={s.id} className="flex items-center flex-shrink-0" style={{ minWidth: 0 }}>
                              <div
                                className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                                  isActive ? 'bg-[#0066ff] text-white animate-pulse' :
                                  isDone ? 'bg-green-500/30 text-green-400' :
                                  isSkipped ? 'bg-gray-500/20 text-gray-400' :
                                  'bg-[#1a1a1a] text-[#666]'
                                }`}
                              >
                                {isDone ? '✓' : idx + 1}
                              </div>
                              {idx < sp.steps.length - 1 && (
                                <div
                                  className={`h-0.5 w-3 flex-shrink-0 ${
                                    isDone ? 'bg-green-500/50' : 'bg-[#2a2a2a]'
                                  }`}
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex items-center gap-2 mt-2 text-[9px] text-[#71717a]">
                        {sp.steps.map((s: any, idx: number) => (
                          <span key={s.id} style={{ width: `${100 / sp.steps.length}%`, textAlign: 'center', minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                            {s.name}
                          </span>
                        ))}
                      </div>
                    </div>
                  );
                })()}
                {/* 📎 生成的策略产物卡片 (S系列核心产出) */}
                {msg.role === "assistant" && (msg as any).artifacts && (msg as any).artifacts.length > 0 && (() => {
                  const artifacts: Array<{ file: string; type: string; chain_phase: string }> = (msg as any).artifacts;
                  const phaseNameMap: Record<string, { name: string; icon: string; desc: string }> = {
                    S1_RESEARCH: { name: 'S1 调研报告', icon: '🔍', desc: '市场数据 & 宏观环境' },
                    S2_ANALYSIS: { name: 'S2 分析报告', icon: '🧠', desc: '多维度技术分析' },
                    S3_DESIGN: { name: 'S3 策略方案', icon: '📐', desc: '入场出场点位' },
                    S4_VALIDATE: { name: 'S4 验证报告', icon: '✅', desc: '回测 & 风险评估' },
                    S5_EXECUTE: { name: 'S5 执行计划', icon: '⚡', desc: '下单 & 跟踪计划' },
                    A2: { name: '分析报告', icon: '🧠', desc: '深度分析' },
                    A6: { name: '情报简报', icon: '🔍', desc: '市场情报' },
                  };
                  return (
                    <div className="mt-3 pt-3 border-t border-[#2a2a2a]">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-[#06b6d4] font-semibold flex items-center gap-1.5">
                          📎 生成的策略产物 <span className="text-[#71717a] font-normal">({artifacts.length})</span>
                        </div>
                        <button
                          onClick={() => {
                            // 打开全部产物列表弹窗
                            const event = new CustomEvent('show-artifacts', { detail: { artifacts, taskId: (msg as any).task_id } });
                            window.dispatchEvent(event);
                          }}
                          className="text-[10px] text-[#06b6d4] hover:underline"
                        >
                          全部查看 →
                        </button>
                      </div>
                      <div className="grid grid-cols-1 gap-2">
                        {artifacts.map((art, idx) => {
                          const info = phaseNameMap[art.chain_phase] || { name: art.chain_phase, icon: '📄', desc: art.type };
                          return (
                            <div
                              key={idx}
                              className="flex items-center gap-2 px-2.5 py-2 bg-gradient-to-r from-cyan-500/10 to-purple-500/5 border border-cyan-500/30 rounded-lg hover:border-cyan-500/60 transition group cursor-pointer"
                              onClick={async () => {
                                try {
                                  const res = await fetch(`/api/artifact?file=${encodeURIComponent(art.file)}`);
                                  const data = await res.json();
                                  if (data.success && data.content) {
                                    alert(`📄 ${art.file}\n\n${data.content.slice(0, 2000)}${data.content.length > 2000 ? '\n\n...(更多内容)' : ''}`);
                                  } else {
                                    alert(`⚠️ 产物文件暂未生成\n\n文件名: ${art.file}\n类型: ${art.type}\n阶段: ${art.chain_phase}\n\n请稍后再试或查看消息内容。`);
                                  }
                                } catch (e) {
                                  alert(`❌ 读取失败: ${e instanceof Error ? e.message : '未知错误'}`);
                                }
                              }}
                            >
                              <div className="text-lg flex-shrink-0">{info.icon}</div>
                              <div className="flex-1 min-w-0">
                                <div className="text-xs font-semibold text-[#06b6d4] truncate">{info.name}</div>
                                <div className="text-[10px] text-[#71717a] truncate">{info.desc} · {art.file}</div>
                              </div>
                              <div className="text-[10px] text-[#71717a] group-hover:text-[#06b6d4] flex-shrink-0">
                                点击查看 →
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
                {msg.role === "assistant" && ((msg as any).strategyChain || (msg as any).strategy_chain) && ((msg as any).strategyChain?.steps || (msg as any).strategy_chain?.steps) && (() => {
                  const sc = (msg as any).strategyChain || (msg as any).strategy_chain;
                  const stepInfo: Record<string, { name: string; desc: string }> = {
                    S1_RESEARCH: { name: "调研", desc: "市场数据收集" },
                    S2_ANALYSIS: { name: "分析", desc: "多维度分析" },
                    S3_DESIGN: { name: "设计", desc: "策略方案制定" },
                    S4_VALIDATE: { name: "验证", desc: "回测风险评估" },
                    S5_EXECUTE: { name: "执行", desc: "执行计划跟踪" },
                  };
                  const totalDone = sc.steps.filter((s: any) => s.status === 'done' || s.status === 'skipped').length;
                  const total = sc.steps.length;
                  
                  return (
                    <div className="mt-3 pt-3 border-t border-[#2a2a2a]">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-[#a855f7]">🎯 S系列策略思维链</div>
                        <div className="text-[9px] text-[#71717a]">
                          {totalDone}/{total} · {sc.complexity === 'quick' ? '快速' : sc.complexity === 'standard' ? '标准' : '深度'}
                        </div>
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        {sc.steps.map((step: any, idx: number) => {
                          const info = stepInfo[step.id] || { name: step.id, desc: '' };
                          const isLast = idx === sc.steps.length - 1;
                          const isCurrent = sc.currentStep === step.id;
                          const isDone = step.status === 'done' || step.status === 'skipped';
                          const isPending = step.status === 'pending';
                          return (
                            <div key={step.id} className="flex items-center" style={{ flex: isLast ? 0 : 1 }}>
                              <div 
                                className={`w-10 h-10 rounded-full flex flex-col items-center justify-center text-xs flex-shrink-0 transition-all ${
                                  isCurrent ? 'bg-purple-500/30 border-2 border-purple-500 text-white' :
                                  isDone ? 'bg-green-500/20 border-2 border-green-500/50 text-green-400' :
                                  isPending ? 'bg-[#1a1a1a] border-2 border-[#2a2a2a] text-[#666]' :
                                  'bg-[#1a1a1a] border-2 border-[#2a2a2a] text-[#999]'
                                }`}
                              >
                                <span>{isCurrent ? '▶' : isDone ? '✓' : isPending ? '⬜' : '⏭'}</span>
                                <span className="text-[9px] mt-0.5">{step.number}</span>
                              </div>
                              {!isLast && (
                                <div 
                                  className="flex-1 h-0.5 mx-[-4px]" 
                                  style={{ 
                                    backgroundColor: sc.steps[idx + 1]?.status !== 'pending' ? '#a855f7' : '#2a2a2a',
                                    minWidth: 8
                                  }} 
                                />
                              )}
                            </div>
                          );
                        })}
                      </div>
                      <div className="flex justify-between gap-2 mt-2">
                        {sc.steps.map((step: any) => {
                          const info = stepInfo[step.id] || { name: step.id, desc: '' };
                          const isCurrent = sc.currentStep === step.id;
                          const isDone = step.status === 'done' || step.status === 'skipped';
                          return (
                            <div 
                              key={step.id} 
                              className="flex-1 text-center text-[10px] px-1"
                              style={{ 
                                color: isCurrent ? '#a855f7' : isDone ? '#22c55e' : '#666',
                                fontWeight: isCurrent ? 700 : 400
                              }}
                            >
                              <div className="font-semibold">{info.name}</div>
                              <div className="text-[8px] opacity-60 mt-0.5">
                                {step.status === 'active' ? '进行中' : step.status === 'done' ? '已完成' : step.status === 'skipped' ? '已跳过' : '待开始'}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                      <div className="mt-2 h-1 bg-[#2a2a2a] rounded-full overflow-hidden">
                        <div 
                          className="h-full bg-[#a855f7] transition-all duration-300" 
                          style={{ width: `${Math.round((totalDone / total) * 100)}%` }}
                        />
                      </div>
                      <div className="text-center text-[9px] text-[#666] mt-1">
                        进度 {totalDone}/{total} · {Math.round((totalDone / total) * 100)}%
                      </div>

                      {/* 🎯 数字选项 + 系统推荐 - 基于当前进度智能推荐 */}
                      {(() => {
                        const currentStepIdx = sc.steps.findIndex((s: any) => s.status === 'active');
                        const allDone = totalDone === total;
                        const nextStepIdx = currentStepIdx >= 0 ? currentStepIdx + 1 : (allDone ? -1 : sc.steps.findIndex((s: any) => s.status === 'pending'));
                        const completion = total > 0 ? totalDone / total : 0;
                        const options: Array<{ key: string; label: string; desc: string; recommended: boolean }> = [];

                        if (nextStepIdx >= 0 && nextStepIdx < sc.steps.length) {
                          const nextStep = sc.steps[nextStepIdx];
                          const nextInfo = stepInfo[nextStep.id] || { name: nextStep.id, desc: '' };
                          // 选项1: 继续下一步
                          let rec1 = true;
                          let desc1 = `进入 ${nextStep.id} ${nextInfo.name} 阶段，${nextInfo.desc}。`;
                          if (completion >= 0.8) {
                            desc1 = `${nextInfo.name} 是策略收官环节，建议完成以解锁执行计划。`;
                          } else if (completion >= 0.4) {
                            desc1 = `核心步骤已完成大半，继续 ${nextInfo.name} 可获得闭环结论。`;
                          } else {
                            desc1 = `当前已完成 ${totalDone}/${total} 步，建议继续走完 S 系列以获得完整策略。`;
                          }
                          options.push({ key: '1', label: `继续 ${nextInfo.name}`, desc: desc1, recommended: rec1 });
                          // 选项2: 跳过
                          options.push({ key: '2', label: `跳过 ${nextInfo.name}`, desc: `如果不需要 ${nextInfo.desc}，可跳到后续步骤。`, recommended: false });
                          // 选项3: 落地保存
                          options.push({ key: '3', label: '落地保存', desc: `已完成的 ${totalDone} 步可作为研报保存，结束本轮 S 系列。`, recommended: false });
                        } else if (allDone) {
                          // S系列全部完成后，询问是否形成策略驱动交易
                          const symbol = sc.scope?.replace(/[\s策略分析]/g, '') || 'BTC';
                          options.push({ key: '1', label: `📊 策略驱动交易 ${symbol}`, desc: '基于 S1-S5 完整策略，立即生成交易计划并执行。', recommended: true });
                          options.push({ key: '2', label: '📄 查看完整报告', desc: '汇总 S 系列各阶段结论，生成完整策略文档。', recommended: false });
                          options.push({ key: '3', label: '💾 保存研报', desc: '将策略结论存入研报库，稍后参考。', recommended: false });
                          options.push({ key: '4', label: '🔄 开始新分析', desc: '结束当前会话，切换到其他标的继续分析。', recommended: false });
                        } else if (totalDone >= 1 && nextStepIdx < 0) {
                          // 有步骤已完成但不是全部完成，且无下一步可选 → 询问是否形成策略驱动交易
                          const symbol = sc.scope?.replace(/[\s策略分析]/g, '') || '';
                          const stepNames = sc.steps.filter((s: any) => s.status === 'done' || s.status === 'skipped').map((s: any) => (stepInfo[s.id] || { name: s.id }).name).join(' → ');
                          options.push({ key: '1', label: `📊 形成策略驱动交易${symbol ? ` ${symbol}` : ''}`, desc: `基于已完成 ${stepNames} 环节，生成交易计划。`, recommended: true });
                          options.push({ key: '2', label: '📄 查看分析报告', desc: '汇总已完成的分析环节，生成研报文档。', recommended: false });
                          options.push({ key: '3', label: '💾 保存研报', desc: '将分析结论存入研报库，稍后参考。', recommended: false });
                          options.push({ key: '4', label: '🔄 继续分析', desc: '继续执行剩余 S 系列环节，获得更完整结论。', recommended: false });
                        }

                        if (options.length === 0) return null;
                        return (
                          <div className="mt-3 pt-2 border-t border-[#2a2a2a]">
                            <div className="text-[10px] text-[#a1a1aa] mb-1.5 font-medium">🔗 下一步操作（点击或输入数字）：</div>
                            <div className="flex flex-col gap-1.5">
                              {options.map((opt) => {
                                const bgClass = opt.recommended
                                  ? 'bg-gradient-to-r from-purple-500/20 to-cyan-500/10 border-purple-500/60 hover:from-purple-500/30'
                                  : 'bg-[#1a1a1a] border-[#2a2a2a] hover:bg-[#222] hover:border-[#3a3a3a]';
                                return (
                                  <button
                                    key={opt.key}
                                    onClick={() => {
                                      let choiceText = '';
                                      if (nextStepIdx >= 0) {
                                        // 执行中选项
                                        choiceText = opt.key === '1'
                                          ? `继续${(stepInfo[sc.steps[nextStepIdx].id] || {name: ''}).name}`
                                          : opt.key === '2'
                                          ? `跳过${(stepInfo[sc.steps[nextStepIdx].id] || {name: ''}).name}`
                                          : '落地保存当前研报';
                                      } else if (allDone) {
                                        // S系列全部完成选项
                                        const sym = sc.scope?.replace(/[\s策略分析]/g, '') || 'BTC';
                                        choiceText = opt.key === '1'
                                          ? `基于策略执行交易 ${sym}`
                                          : opt.key === '2'
                                          ? '查看S系列完整报告'
                                          : opt.key === '3'
                                          ? '保存研报'
                                          : '开始新一轮分析';
                                      } else {
                                        // 有步骤完成但非全部完成选项
                                        choiceText = opt.key === '1'
                                          ? '形成策略驱动交易'
                                          : opt.key === '2'
                                          ? '查看分析报告'
                                          : opt.key === '3'
                                          ? '保存研报'
                                          : '继续完成S系列';
                                      }
                                      // 找到输入框元素并触发提交
                                      const input = document.querySelector('input[placeholder*="输入消息"]') as HTMLInputElement;
                                      if (input) {
                                        const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                                        nativeInputValueSetter?.call(input, choiceText);
                                        input.dispatchEvent(new Event('input', { bubbles: true }));
                                        setTimeout(() => {
                                          const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                                          input.dispatchEvent(enterEvent);
                                        }, 100);
                                      }
                                    }}
                                    className={`group flex items-start gap-2 px-2.5 py-1.5 text-left text-[10px] rounded-lg transition border ${bgClass}`}
                                  >
                                    <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center font-bold text-[10px] ${
                                      opt.recommended ? 'bg-purple-500 text-white shadow' : 'bg-[#2a2a2a] text-[#a1a1aa] group-hover:bg-[#3a3a3a]'
                                    }`}>
                                      {opt.key}
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className={`font-semibold ${opt.recommended ? 'text-purple-200' : 'text-[#e0e0e0]'}`}>
                                        {opt.label}
                                        {opt.recommended && (
                                          <span className="ml-1.5 inline-flex items-center gap-0.5 px-1 py-0.5 bg-cyan-500/20 text-cyan-300 rounded text-[8px] font-bold">
                                            💡 系统推荐
                                          </span>
                                        )}
                                      </div>
                                      <div className={`text-[9px] mt-0.5 ${opt.recommended ? 'text-[#a1a1aa]' : 'text-[#71717a]'} leading-tight`}>
                                        {opt.desc}
                                      </div>
                                    </div>
                                  </button>
                                );
                              })}
                            </div>
                            <div className="mt-1.5 text-[9px] text-[#71717a]">
                              💬 或输入 <span className="font-mono text-[#a1a1aa]">{options.map(o => o.key).join(' / ')}</span> 选择
                            </div>
                          </div>
                        );
                      })()}

                      {/* 📊 策略驱动交易引导卡片 - S系列分析完成后询问 */}
                      {(() => {
                        const sc = (msg as any).strategyChain || (msg as any).strategy_chain;
                        if (!sc || !sc.steps) return null;
                        const totalDone = sc.steps.filter((s: any) => s.status === 'done' || s.status === 'skipped').length;
                        const allDone = totalDone === sc.steps.length;
                        const currentActive = sc.steps.find((s: any) => s.status === 'active');
                        const symbol = (msg as any).chain?.length > 0
                          ? (msg as any).chain.join('').includes('BTC') ? 'BTC' : (msg as any).chain.join('').includes('ETH') ? 'ETH' : ''
                          : sc.scope?.replace(/[\s策略分析]/g, '') || '';
                        // 有步骤完成，且不在等待确认状态 → 显示策略驱动交易引导
                        if (totalDone === 0) return null;
                        const isAllDone = totalDone === sc.steps.length;
                        return (
                          <div className="mt-3 pt-2 border-t border-[#2a2a2a]">
                            <div className="text-[10px] text-[#e0c060] font-semibold mb-2 flex items-center gap-1.5">
                              <span>💡</span>
                              <span>{isAllDone ? 'S系列策略分析已完成！' : '策略分析已有结论'}</span>
                            </div>
                            <div className="bg-gradient-to-r from-yellow-500/10 to-green-500/5 border border-yellow-500/30 rounded-lg px-3 py-2.5">
                              <div className="text-[11px] text-[#e0e0e0] font-medium mb-2">
                                {isAllDone
                                  ? `📊 基于完整 ${symbol || '标的'} S系列策略，是否现在形成策略驱动交易？`
                                  : `📊 基于已完成分析，是否形成策略驱动交易${symbol ? ` ${symbol}` : ''}？`}
                              </div>
                              <div className="flex gap-2">
                                <button
                                  onClick={() => {
                                    const input = document.querySelector('input[placeholder*="输入消息"]') as HTMLInputElement;
                                    if (input) {
                                      const text = symbol ? `基于策略执行交易 ${symbol}` : '基于策略执行交易';
                                      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                                      nativeInputValueSetter?.call(input, text);
                                      input.dispatchEvent(new Event('input', { bubbles: true }));
                                      setTimeout(() => {
                                        const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                                        input.dispatchEvent(enterEvent);
                                      }, 100);
                                    }
                                  }}
                                  className="flex-1 px-3 py-2 text-[11px] font-semibold bg-gradient-to-r from-green-500/80 to-emerald-500/80 hover:from-green-500 hover:to-emerald-500 text-white rounded-lg transition shadow"
                                >
                                  ⚡ 是，立即生成交易计划
                                </button>
                                <button
                                  onClick={() => {
                                    const input = document.querySelector('input[placeholder*="输入消息"]') as HTMLInputElement;
                                    if (input) {
                                      const nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')?.set;
                                      nativeInputValueSetter?.call(input, '先看看分析报告');
                                      input.dispatchEvent(new Event('input', { bubbles: true }));
                                      setTimeout(() => {
                                        const enterEvent = new KeyboardEvent('keydown', { key: 'Enter', code: 'Enter', keyCode: 13, bubbles: true });
                                        input.dispatchEvent(enterEvent);
                                      }, 100);
                                    }
                                  }}
                                  className="px-3 py-2 text-[11px] bg-[#2a2a2a] hover:bg-[#333] text-[#a1a1aa] border border-[#3a3a3a] rounded-lg transition"
                                >
                                  📋 查看报告
                                </button>
                              </div>
                            </div>
                          </div>
                        );
                      })()}
                    </div>
                  );
                })()}
                
                {/* 🔗 D-Z-E 思维链可视化（保留用于开发治理场景） */}
                {msg.role === "assistant" && ((msg as any).chainState || (msg as any).chain_state) && ((msg as any).chainState?.phases || (msg as any).chain_state?.phases) && !(msg as any).strategyChain && !(msg as any).strategy_chain && (() => {
                  const cs = (msg as any).chainState || (msg as any).chain_state;
                  const groups = [
                    { key: 'D', name: '调研链', color: '#0088aa', items: cs.phases.filter((p: any) => p.id.startsWith('D')) },
                    { key: 'Z', name: '规划链', color: '#aa6600', items: cs.phases.filter((p: any) => p.id.startsWith('Z')) },
                    { key: 'E', name: '执行链', color: '#008855', items: cs.phases.filter((p: any) => p.id.startsWith('E')) },
                  ].filter(g => g.items.length > 0);
                  
                  if (groups.length === 0) return null;
                  
                  return (
                    <div className="mt-3 pt-3 border-t border-[#2a2a2a]">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-[#0088aa]">🔗 D-Z-E 思维链 (开发治理)</div>
                        <div className="text-[9px] text-[#71717a]">{cs.scope || ''}</div>
                      </div>
                      <div className="space-y-2">
                        {groups.map((g: any) => {
                          const groupDone = g.items.filter((p: any) => p.status === 'completed' || p.status === 'skipped').length;
                          return (
                            <div key={g.key} className="p-2 rounded bg-[#0d0d0d]">
                              <div className="flex items-center gap-2 mb-1">
                                <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: g.color }} />
                                <span className="text-[10px] text-[#999]">{g.name}</span>
                                <span className="text-[9px] text-[#666] ml-auto">{groupDone}/{g.items.length}</span>
                              </div>
                              <div className="flex gap-1 flex-wrap">
                                {g.items.map((p: any) => {
                                  const isCurrent = cs.currentPhase === p.id;
                                  const isDone = p.status === 'completed' || p.status === 'skipped';
                                  return (
                                    <div
                                      key={p.id}
                                      className={`px-2 py-1 rounded text-[10px] text-center min-w-[48px] flex-shrink-0 ${
                                        isCurrent ? 'bg-[#0066ff]/20 text-[#3b82f6] border border-[#0066ff]/50' :
                                        isDone ? 'bg-green-500/10 text-green-400 border border-green-500/30' :
                                        'bg-[#141414] text-[#666] border border-[#2a2a2a]'
                                      }`}
                                      style={isCurrent ? { animation: 'pulse 1.5s ease-in-out infinite' } : {}}
                                    >
                                      <div className="font-bold">{p.id}</div>
                                      <div className="text-[8px] opacity-70 mt-0.5 truncate max-w-[60px]">{p.name}</div>
                                    </div>
                                  );
                                })}
                              </div>
                            </div>
                          );
                        })}
                      </div>
                    </div>
                  );
                })()}
                {/* 📊 市场价格卡片 */}
                {msg.role === "assistant" && (msg as any).market && (msg as any).market.price != null && (() => {
                  const m = (msg as any).market;
                  const change = typeof m.change24h === 'number' ? m.change24h : 0;
                  return (
                    <div className="mt-3 pt-3 border-t border-[#2a2a2a]">
                      <div className="flex items-center justify-between mb-2">
                        <div className="text-[11px] text-[#06b6d4]">📊 实时行情</div>
                        <div className="text-[9px] text-[#71717a]">{m.displayName || m.symbol}</div>
                      </div>
                      <div className="p-3 rounded-lg bg-gradient-to-br from-[#0f3460]/30 to-[#0d0d0d] border border-[#2a2a2a]">
                        <div className="flex items-baseline justify-between">
                          <div className="text-2xl font-bold text-[#e0e0e0]">
                            {typeof m.price === 'number' ? `$${m.price.toLocaleString('en-US', { maximumFractionDigits: 2 })}` : m.price}
                          </div>
                          <div className={`text-xs font-semibold ${change >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                            {change >= 0 ? '▲' : '▼'} {Math.abs(change).toFixed(2)}%
                          </div>
                        </div>
                        <div className="grid grid-cols-2 gap-2 mt-2 text-[10px]">
                          <div>
                            <span className="text-[#71717a]">支撑: </span>
                            <span className="text-[#666]">
                              {Array.isArray(m.support) ? m.support.slice(0, 2).map((v: number) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`).join(' / ') : m.support}
                            </span>
                          </div>
                          <div>
                            <span className="text-[#71717a]">阻力: </span>
                            <span className="text-[#666]">
                              {Array.isArray(m.resistance) ? m.resistance.slice(0, 2).map((v: number) => `$${v.toLocaleString('en-US', { maximumFractionDigits: 2 })}`).join(' / ') : m.resistance}
                            </span>
                          </div>
                          <div>
                            <span className="text-[#71717a]">24h 高: </span>
                            <span className="text-[#666]">${typeof m.high24h === 'number' ? m.high24h.toLocaleString('en-US', { maximumFractionDigits: 2 }) : m.high24h}</span>
                          </div>
                          <div>
                            <span className="text-[#71717a]">24h 低: </span>
                            <span className="text-[#666]">${typeof m.low24h === 'number' ? m.low24h.toLocaleString('en-US', { maximumFractionDigits: 2 }) : m.low24h}</span>
                          </div>
                        </div>
                        {m.note && (
                          <div className="text-[9px] text-[#555] mt-2 italic">{m.note}</div>
                        )}
                      </div>
                    </div>
                  );
                })()}
                {/* 交易确认按钮 */}
                {msg.trade_task_id && !msg.trade_confirmed && (
                  <div className="mt-3 pt-3 border-t border-[#1a1a1a]">
                    <div className="text-xs text-[#8a8a8a] mb-2">🔒 请确认交易操作：</div>
                    <div className="flex flex-wrap gap-2">
                      <button
                        onClick={() => handleTradeConfirm(msg.trade_task_id!, 'confirm')}
                        className="px-3 py-1.5 text-xs bg-green-500 text-white rounded-md hover:bg-green-600 transition font-medium"
                      >
                        ✅ 确认执行
                      </button>
                      <div className="flex items-center gap-1">
                        <input
                          type="time"
                          value={scheduleTime}
                          onChange={(e) => setScheduleTime(e.target.value)}
                          className="px-2 py-1 text-xs bg-[#141414] border border-[#2a2a2a] rounded text-[#e0e0e0] focus:outline-none focus:border-[#0066ff]"
                          style={{ width: '90px' }}
                        />
                        <button
                          onClick={() => handleTradeConfirm(msg.trade_task_id!, 'schedule')}
                          className="px-3 py-1.5 text-xs bg-yellow-500 text-black rounded-md hover:bg-yellow-600 transition font-medium"
                        >
                          🕐 定时执行
                        </button>
                      </div>
                      <button
                        onClick={() => handleTradeConfirm(msg.trade_task_id!, 'cancel')}
                        className="px-3 py-1.5 text-xs bg-red-500/80 text-white rounded-md hover:bg-red-600 transition font-medium"
                      >
                        🚫 取消
                      </button>
                    </div>
                  </div>
                )}
                {/* 澄清选项按钮 */}
                {msg.clarification_state && msg.clarification_state.options && msg.clarification_state.options.length > 0 && (
                  <div className="mt-3 pt-3 border-t border-[#1a1a1a]">
                    <div className="text-xs text-[#8a8a8a] mb-2">💡 请选择你要的操作：</div>
                    <div className="flex flex-wrap gap-2">
                      {msg.clarification_state.options.map((opt: any, idx: number) => (
                        <button
                          key={opt.key || idx}
                          onClick={() => handleClarificationChoice(
                            msg,
                            opt,
                            idx
                          )}
                          className="px-3 py-1.5 text-xs bg-[#0066ff]/20 text-[#5ca8ff] rounded-md hover:bg-[#0066ff]/30 border border-[#0066ff]/30 transition font-medium"
                        >
                          {idx + 1}. {opt.label || opt.key}
                        </button>
                      ))}
                    </div>
                  </div>
                )}
                {/* 🎯 S系列步进确认 - 数字选项 + 系统推荐 */}
                {msg.step_confirmation && msg.step_confirmation.options && msg.step_confirmation.options.length > 0 && (() => {
                  const sc = msg.step_confirmation;
                  const currentStep = sc.current_step;
                  const nextStep = sc.next_step;
                  const stepNameMap: Record<string, string> = {
                    'S1_RESEARCH': 'S1 调研', 'S2_ANALYSIS': 'S2 分析', 'S3_DESIGN': 'S3 设计',
                    'S4_VALIDATE': 'S4 验证', 'S5_EXECUTE': 'S5 执行',
                  };
                  const currentName = stepNameMap[currentStep] || currentStep;
                  const nextName = nextStep ? stepNameMap[nextStep] || nextStep : null;
                  // 🔮 智能推荐逻辑：基于已执行步骤数 & 复杂度给出推荐
                  const totalSteps = (msg as any).strategyChain?.steps?.length || 0;
                  const doneSteps = (msg as any).strategyChain?.steps?.filter((s: any) => s.status === 'done' || s.status === 'skipped').length || 0;
                  const completion = totalSteps > 0 ? doneSteps / totalSteps : 0;
                  let recommendedKey = '1';
                  let recommendReason = '';
                  if (nextStep) {
                    if (completion < 0.5) {
                      recommendedKey = '1';
                      recommendReason = `当前已完成 ${doneSteps}/${totalSteps} 步，建议继续走完 S 系列以获得完整策略。`;
                    } else if (completion < 0.8) {
                      recommendedKey = '1';
                      recommendReason = `核心步骤已完成大半，继续执行 ${nextName} 可获得闭环结论。`;
                    } else {
                      recommendedKey = '1';
                      recommendReason = `${nextName} 是策略的收官环节，建议完成以解锁执行计划。`;
                    }
                  } else {
                    recommendedKey = '2';
                    recommendReason = '已是最后一步，建议直接落地保存当前结果。';
                  }
                  return (
                    <div className="mt-3 pt-3 border-t border-[#2a2a2a]">
                      {/* 当前步骤信息 */}
                      <div className="flex items-center gap-2 mb-2 text-[11px]">
                        <span className="px-1.5 py-0.5 bg-purple-500/20 text-purple-300 rounded font-mono">{currentName}</span>
                        <span className="text-[#71717a]">已完成 ·</span>
                        {nextName && (
                          <>
                            <span className="text-[#71717a]">下一步:</span>
                            <span className="px-1.5 py-0.5 bg-cyan-500/20 text-cyan-300 rounded font-mono">{nextName}</span>
                          </>
                        )}
                      </div>
                      <div className="text-xs text-[#a1a1aa] mb-2 font-medium">🔗 请选择下一步操作：</div>
                      <div className="flex flex-col gap-2">
                        {sc.options.map((opt: any, idx: number) => {
                          const isRecommended = opt.key === recommendedKey;
                          return (
                            <button
                              key={opt.key || idx}
                              onClick={() => handleStepChoice(msg, opt)}
                              className={`group flex items-start gap-3 px-3 py-2.5 text-left text-xs rounded-lg transition border ${
                                isRecommended
                                  ? 'bg-gradient-to-r from-purple-500/20 to-cyan-500/10 border-purple-500/60 hover:from-purple-500/30 hover:to-cyan-500/20 shadow-[0_0_12px_rgba(168,85,247,0.15)]'
                                  : 'bg-[#1a1a1a] border-[#2a2a2a] hover:bg-[#222] hover:border-[#3a3a3a]'
                              }`}
                            >
                              <div className={`flex-shrink-0 w-7 h-7 rounded-full flex items-center justify-center font-bold text-sm ${
                                isRecommended
                                  ? 'bg-purple-500 text-white shadow-[0_0_8px_rgba(168,85,247,0.5)]'
                                  : 'bg-[#2a2a2a] text-[#a1a1aa] group-hover:bg-[#333]'
                              }`}>
                                {opt.key || idx + 1}
                              </div>
                              <div className="flex-1 min-w-0">
                                <div className={`font-semibold ${isRecommended ? 'text-purple-200' : 'text-[#e0e0e0]'}`}>
                                  {opt.label || opt.key}
                                  {isRecommended && (
                                    <span className="ml-2 inline-flex items-center gap-1 px-1.5 py-0.5 bg-cyan-500/20 text-cyan-300 rounded text-[9px] font-bold">
                                      💡 系统推荐
                                    </span>
                                  )}
                                </div>
                                {isRecommended && recommendReason && (
                                  <div className="text-[10px] text-[#a1a1aa] mt-1 leading-relaxed">
                                    {recommendReason}
                                  </div>
                                )}
                              </div>
                            </button>
                          );
                        })}
                      </div>
                      <div className="mt-2 text-[10px] text-[#71717a]">
                        💬 也可直接输入数字 <span className="font-mono text-[#a1a1aa]">1</span> / <span className="font-mono text-[#a1a1aa]">2</span> / <span className="font-mono text-[#a1a1aa]">3</span> 回复
                      </div>
                    </div>
                  );
                })()}
              </div>
            </div>
          ));
          })()}
        </div>

        {/* Quick Commands */}
        <div className="px-4 py-2 border-t border-[#1a1a1a]">
          <div className="flex flex-wrap gap-2 mb-2">
            {["/行情", "/分析", "/推演", "/验证", "/开仓"].map((cmd) => (
              <button
                key={cmd}
                onClick={() => setInput(cmd)}
                disabled={isLoading}
                className={`px-3 py-1 text-xs rounded-full transition ${
                  isLoading
                    ? 'bg-[#1a1a1a] text-[#52525b] cursor-not-allowed'
                    : 'bg-[#1a1a1a] text-[#8a8a8a] hover:bg-[#1f1f1f] cursor-pointer'
                }`}
              >
                {cmd}
              </button>
            ))}
          </div>
        </div>
        
        {/* Input */}
        <form onSubmit={handleSubmit} className={`p-4 border-t border-[#1a1a1a] transition-opacity ${isLoading ? 'opacity-70' : ''}`}>
          <div className={`flex items-center space-x-2 bg-[#1a1a1a] rounded-lg px-4 py-3 transition ${isLoading ? 'ring-1 ring-[#0066ff]/50' : ''}`}>
            <input
              value={input}
              onChange={(e) => setInput(e.target.value)}
              disabled={isLoading}
              placeholder={isLoading ? '⏳ 处理中，请稍候...' : `输入消息... (${
                thinkingMode === 'quick' ? '⚡智能' : '🧠深度'
              } | 支持 /命令)`}
              className="flex-1 bg-transparent text-sm text-[#e0e0e0] placeholder-[#a1a1aa] focus:outline-none disabled:cursor-not-allowed"
            />
            <button
              type="submit"
              disabled={isLoading || !input.trim()}
              className={`p-2 rounded-md transition ${
                isLoading
                  ? 'bg-[#0066ff]/70 cursor-wait'
                  : input.trim()
                  ? 'bg-[#0066ff] hover:bg-blue-700 cursor-pointer'
                  : 'bg-[#2a2a2a] cursor-not-allowed'
              }`}
            >
              {isLoading ? (
                <svg className="w-4 h-4 text-white animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z" />
                </svg>
              ) : (
                <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                </svg>
              )}
            </button>
          </div>
          <div className="flex items-center justify-between mt-2 text-xs text-[#8a8a8a]">
            <span className="flex items-center gap-2">
              模型: {llmModel}
              {renderStatusDot(llmStatus)}
              | 方法: {intentMethod === 'llm' ? '🧠 LLM' : '📋 规则'}
              | <span className="text-green-500 font-semibold">🔗 中台即时</span>
            </span>
            <span>
              模式: {thinkingMode === 'quick' ? '⚡ 智能思考' : '🧠 深度思考'}
            </span>
          </div>
        </form>
      </div>

      {/* Right Panel */}
      <div
        className={`${rightCollapsed ? "w-0" : "w-80"} flex-shrink-0 flex flex-col bg-[#1a1a1a] border-l border-[#1a1a1a] transition-all duration-300 overflow-hidden`}
      >
        <div className="p-4 border-b border-[#1a1a1a] flex items-center justify-between">
          <h2 className="text-sm font-semibold text-[#3b82f6]">
            {rightPanelContent === 'analysis' ? '📌 分析面板' :
             rightPanelContent === 'market' ? '📈 行情卡片' :
             rightPanelContent === 'signal' ? '🎯 评分卡片' :
             rightPanelContent === 'position' ? '💼 持仓卡片' :
             rightPanelContent === 'api' ? '⚙️ 交易所API' :
             rightPanelContent === 'trading' ? '💰 交易设置' :
             rightPanelContent === 'strategy' ? '🎯 策略设置' :
             rightPanelContent === 'communication' ? '📡 通信渠道' :
             rightPanelContent === 'llm' ? '🤖 大模型配置' :
             rightPanelContent === 'monitor' ? '📡 传递监控' :
             rightPanelContent === 'memory' ? '🧠 意图记忆库' :
             rightPanelContent === 'orchestration' ? '🔀 编排追踪' :
             rightPanelContent === 'report' ? '📄 研报详情' :
             rightPanelContent === 'graph-compression' ? '🗜️ 图压缩面板' : '面板'}
          </h2>
          <button
            onClick={() => {
              if (rightPanelContent !== 'analysis') {
                setRightPanelContent('analysis');
              } else {
                setRightCollapsed(true);
              }
            }}
            className="p-1 hover:bg-[#1f1f1f] rounded transition text-[#8a8a8a]"
            title={rightPanelContent !== 'analysis' ? '返回分析面板' : '关闭面板'}
          >
            {rightPanelContent !== 'analysis' ? '←' : '✕'}
          </button>
        </div>

        <div className="flex gap-1 flex-wrap border-b border-[#1a1a1a] px-4 py-2">
          <button
            onClick={() => setRightPanelContent('analysis')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'analysis'
                ? 'bg-[#3b82f6] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            📊 分析
          </button>
          <button
            onClick={() => setRightPanelContent('memory')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'memory'
                ? 'bg-[#3b82f6] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            🧠 记忆
          </button>
          <button
            onClick={() => setRightPanelContent('notebook')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'notebook'
                ? 'bg-[#3b82f6] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            📒 笔记
          </button>
          <button
            onClick={() => setRightPanelContent('graph-compression')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'graph-compression'
                ? 'bg-[#10b981] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            🗜️ 图压缩
          </button>
          <button
            onClick={() => setRightPanelContent('monitor')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'monitor'
                ? 'bg-[#3b82f6] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            📡 监控
          </button>
          <button
            onClick={() => setRightPanelContent('orchestration')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'orchestration'
                ? 'bg-[#6366f1] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            🔀 编排
          </button>
          <button
            onClick={() => setRightPanelContent('llm')}
            className={`px-2 py-1 rounded text-[11px] transition ${
              rightPanelContent === 'llm'
                ? 'bg-[#3b82f6] text-white'
                : 'bg-[#1a1a1a] text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#2a2a2a]'
            }`}
          >
            🤖 LLM
          </button>
        </div>

        <div className="flex-1 overflow-y-auto p-4 space-y-4">
          {renderRightPanel()}
        </div>
      </div>
        </div>
      </section>
      )}

      {activeTab === 'classic' && (
        <section className="flex-1 min-h-0 flex flex-col overflow-hidden bg-[#0d0d0d] text-[#e0e0e0]">
            <div className="bg-[#1a1a1a] border-b border-[#1a1a1a] px-4 py-3">
              <div className="flex gap-1 flex-wrap">
                <button
                  onClick={() => setClassicSubTab('library')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'library' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  📚 策略库
                </button>
                <button
                  onClick={() => setClassicSubTab('strategies')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'strategies' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🛠 策略上线通道
                </button>
                <button
                  onClick={() => setClassicSubTab('sandbox')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'sandbox' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🧪 沙箱测试
                </button>
                <button
                  onClick={() => setClassicSubTab('approvals')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'approvals' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  ✅ 审计与审批
                </button>
                <button
                  onClick={() => setClassicSubTab('signals')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'signals' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🎯 信号触发 (Freqtrade)
                </button>
                <button
                  onClick={() => setClassicSubTab('filter')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'filter' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🔍 信号过滤
                </button>
                <button
                  onClick={() => setClassicSubTab('execution')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'execution' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  ⚡ 信号执行
                </button>
                <button
                  onClick={() => setClassicSubTab('exit')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'exit' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🏁 信号离场
                </button>
                <button
                  onClick={() => setClassicSubTab('arena')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'arena' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🎲 多模型投票
                </button>
                <button
                  onClick={() => setClassicSubTab('universe')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'universe' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  🌐 代币筛选
                </button>
                <button
                  onClick={() => setClassicSubTab('macro')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'macro' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  📊 宏观门控
                </button>
                <button
                  onClick={() => setClassicSubTab('evaluation')}
                  className={`px-3 py-1.5 rounded-md text-sm font-medium transition ${
                    classicSubTab === 'evaluation' ? 'bg-[#8b5cf6] text-white' : 'text-[#8a8a8a] hover:text-[#e0e0e0] hover:bg-[#1f1f1f]'
                  }`}
                >
                  📈 模型评估
                </button>
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4">
              {classicSubTab === 'library' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-semibold text-white mb-2">📚 策略库 (Strategy Registry)</h2>
                    <div className="flex items-center gap-2">
                      {isLoadingClassicData && (
                        <span className="text-xs text-[#8b5cf6] animate-pulse">加载中...</span>
                      )}
                      <button
                        onClick={loadClassicSystemData}
                        className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
                      >
                        🔄 刷新
                      </button>
                    </div>
                  </div>
                  <p className="text-[#8a8a8a] text-sm">已验证并可复用的经典策略集合。来源于 10-经典指标系统 策略注册表。</p>

                  {/* 系统状态指示 */}
                  <div className="flex items-center gap-2 text-sm">
                    <span className={`w-2 h-2 rounded-full ${classicHealth.ok ? 'bg-green-500' : 'bg-red-500'}`}></span>
                    <span className="text-[#8a8a8a]">
                      经典交易系统: {classicHealth.ok ? '在线' : '离线'}
                      {!classicHealth.ok && classicHealth.error && (
                        <span className="text-xs ml-2">({classicHealth.error})</span>
                      )}
                    </span>
                  </div>

                  {strategyList.length > 0 ? (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mt-4">
                      {strategyList.map((s, idx) => (
                        <div key={idx} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] hover:border-[#8b5cf6] transition cursor-pointer">
                          <div className="flex items-center justify-between mb-2">
                            <h3 className="text-white font-medium">{s.strategy || 'Unknown Strategy'}</h3>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              s.status === 'active' ? 'bg-green-500/20 text-green-400' :
                              s.status === 'inactive' ? 'bg-gray-500/20 text-gray-400' :
                              'bg-yellow-500/20 text-yellow-400'}`}
                            >
                              {s.status || 'unknown'}
                            </span>
                          </div>
                          <div className="text-xs text-[#8a8a8a] space-y-1">
                            {s.book_id && <p>📖 Book: {s.book_id}</p>}
                            {s.ab_owner && <p>👤 Owner: {s.ab_owner}</p>}
                            {s.metrics && (
                              <>
                                {s.metrics.win_rate !== undefined && <p>🎯 胜率: {(s.metrics.win_rate * 100).toFixed(1)}%</p>}
                                {s.metrics.sharpe_ratio !== undefined && <p>📊 夏普率: {s.metrics.sharpe_ratio.toFixed(2)}</p>}
                                {s.metrics.max_drawdown !== undefined && <p>⚠️ 最大回撤: {(s.metrics.max_drawdown * 100).toFixed(1)}%</p>}
                              </>
                            )}
                            {s.last_update && <p>🕐 更新: {new Date(s.last_update * 1000).toLocaleString('zh-CN')}</p>}
                          </div>
                          <button
                            onClick={() => {
                              setActiveTab('trade');
                              setInput(`帮我用「${s.strategy}」策略分析当前 BTC 走势`);
                            }}
                            className="mt-3 text-xs text-[#8b5cf6] hover:text-white transition"
                          >
                            💬 在对话中引用 →
                          </button>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="mt-4 text-center text-[#8a8a8a] py-8">
                      {classicHealth.ok ? '暂无注册策略' : '系统离线，请检查 10-经典指标系统 服务'}
                    </div>
                  )}
                </div>
              )}

              {classicSubTab === 'strategies' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🛠 策略上线通道</h2>
                  <p className="text-[#8a8a8a] text-sm">完整治理流程：Draft → Gate 评估 → 审批 → Apply 应用 → Audit 记录。只有通过全部流程的策略才会真正上线到 Freqtrade。</p>

                  {/* Pipeline 状态总览 */}
                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">📝 策略治理管线</h3>
                    <div className="space-y-2">
                      {[
                        { step: '① Draft（起草）', status: pipelineState.phase === 'draft' ? '进行中' : pipelineState.current ? '已完成' : '待处理', detail: '用户在对话中生成策略代码', phase: 'draft' },
                        { step: '② Gate（门槛）', status: gateCheck.passed ? '已通过' : gateCheck.ok ? '未通过' : '待处理', detail: '自动化合规/风险检查', phase: 'gate' },
                        { step: '③ Approval（审批）', status: pipelineState.approval_id ? '已提交' : '待处理', detail: '风控/运营人工确认', phase: 'approval' },
                        { step: '④ Apply（应用）', status: pipelineState.phase === 'apply' ? '进行中' : pipelineState.phase === 'live' ? '已上线' : '待处理', detail: '部署到 Freqtrade 执行引擎', phase: 'apply' },
                        { step: '⑤ Audit（审计）', status: '自动记录', detail: '运行数据记录与回测归档', phase: 'audit' },
                      ].map((item, idx) => {
                        const isActive = item.status === '进行中' || item.status === '已通过' || item.status === '已提交' || item.status === '已上线';
                        const isPending = item.status === '待处理' || item.status === '未通过';
                        return (
                          <div key={idx} className="flex items-center gap-3 text-sm p-2 bg-[#0d0d0d] rounded">
                            <span className="text-white font-medium w-56">{item.step}</span>
                            <span className="text-[#8a8a8a] flex-1">{item.detail}</span>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              isActive ? 'bg-green-500/20 text-green-400' :
                              isPending ? 'bg-gray-500/20 text-[#8a8a8a]' :
                              'bg-yellow-500/20 text-yellow-400'}`}
                            >
                              {item.status}
                            </span>
                          </div>
                        );
                      })}
                    </div>
                  </div>

                  {/* Gate Check 详情 */}
                  {gateCheck.ok && gateCheck.checks && (
                    <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">🚪 Gate Check 详情</h3>
                      <div className="grid grid-cols-4 gap-3 text-sm">
                        {Object.entries(gateCheck.checks).map(([key, passed]) => (
                          <div key={key} className="flex items-center gap-2">
                            <span className="text-[#8a8a8a]">{key}:</span>
                            <span className={passed ? 'text-green-400' : 'text-red-400'}>
                              {passed ? '✓' : '✗'}
                            </span>
                          </div>
                        ))}
                      </div>
                      {gateCheck.metrics && (
                        <div className="mt-3 text-xs text-[#8a8a8a]">
                          Metrics: PF={gateCheck.metrics.pf?.toFixed(2) || '-'}, WinRate={((gateCheck.metrics.winrate || 0) * 100).toFixed(1)}%, MaxDD={((gateCheck.metrics.maxdd || 0) * 100).toFixed(1)}%
                        </div>
                      )}
                    </div>
                  )}

                  {/* 当前 Pipeline Candidate */}
                  {pipelineState.candidate && (
                    <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
                      <h3 className="text-white font-medium mb-2">🎯 当前候选策略</h3>
                      <div className="text-sm">
                        <span className="text-white font-medium">{pipelineState.candidate}</span>
                        {pipelineState.gate_result && (
                          <span className={`ml-2 text-xs px-2 py-0.5 rounded-full ${pipelineState.gate_result.passed ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                            {pipelineState.gate_result.passed ? 'Gate通过' : 'Gate未通过'}
                          </span>
                        )}
                      </div>
                    </div>
                  )}
                </div>
              )}

              {classicSubTab === 'sandbox' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🧪 沙箱测试 (Sandbox Testing)</h2>
                  <p className="text-[#8a8a8a] text-sm">策略上线前的模拟运行环境。使用历史数据 + 实时行情进行回测与模拟交易，不会产生任何真实下单。</p>

                  {/* 沙箱状态总览 */}
                  <div className="mt-4 grid grid-cols-3 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <p className="text-[#8a8a8a] text-xs mb-1">📊 运行中任务</p>
                      <p className="text-2xl font-bold text-white">{sandboxState.running || 0}</p>
                      <p className="text-xs text-[#6a6a6a] mt-1">正在实时模拟</p>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <p className="text-[#8a8a8a] text-xs mb-1">⏳ 队列等待</p>
                      <p className="text-2xl font-bold text-yellow-400">{sandboxState.queued || 0}</p>
                      <p className="text-xs text-[#6a6a6a] mt-1">待执行任务</p>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <p className="text-[#8a8a8a] text-xs mb-1">🎯 最大并发</p>
                      <p className="text-2xl font-bold text-[#8b5cf6]">{sandboxState.max_slots || 3}</p>
                      <p className="text-xs text-[#6a6a6a] mt-1">并发槽位</p>
                    </div>
                  </div>

                  {/* 回测结果列表 */}
                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-white font-medium">🔬 最新回测结果</h3>
                      <span className="text-xs text-[#8a8a8a]">共 {backtestResults.length} 条记录</span>
                    </div>
                    {backtestResults.length > 0 ? (
                      <div className="space-y-2 text-sm max-h-64 overflow-y-auto">
                        {backtestResults.slice(0, 10).map((bt, idx) => (
                          <div key={idx} className="flex items-center gap-3 p-2 bg-[#0d0d0d] rounded border-l-2 border-[#8b5cf6]">
                            <span className="text-white font-medium w-40 truncate">{bt.strategy || bt.zip?.replace('.zip', '') || 'Unknown'}</span>
                            <span className="text-[#8a8a8a] flex-1 text-xs">
                              {bt.ts ? new Date(bt.ts).toLocaleDateString('zh-CN') : '-'}
                            </span>
                            {bt.metrics_summary && (
                              <>
                                <span className={`text-xs ${bt.metrics_summary.pf !== undefined && bt.metrics_summary.pf >= 1 ? 'text-green-400' : 'text-red-400'}`}>
                                  PF: {bt.metrics_summary.pf?.toFixed(2) || '-'}
                                </span>
                                <span className="text-xs text-[#8a8a8a]">
                                  WR: {((bt.metrics_summary.winrate || 0) * 100).toFixed(0)}%
                                </span>
                              </>
                            )}
                            <span className={`text-xs px-2 py-0.5 rounded-full ${bt.ok ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                              {bt.ok ? '成功' : '失败'}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center text-[#8a8a8a] py-8">
                        {isLoadingClassicData ? '加载中...' : '暂无回测记录'}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {classicSubTab === 'approvals' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-semibold text-white mb-2">✅ 审计与审批</h2>
                    <button
                      onClick={loadClassicSystemData}
                      className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
                    >
                      🔄 刷新
                    </button>
                  </div>
                  <p className="text-[#8a8a8a] text-sm">经过沙箱测试后，策略需要经过审计（代码安全、参数合规、风险披露）。审计通过后，再提交审批流程。</p>

                  {/* 自动化状态轻量卡片 */}
                  <div className="mt-3 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
                    <h3 className="text-white font-medium text-sm mb-2">🤖 自动化状态</h3>
                    <div className="flex gap-4 text-xs">
                      <div className="flex items-center gap-1">
                        <span className="text-[#8a8a8a]">审批待办:</span>
                        <span className={`font-medium ${approvalList.filter(a => a.status === 'pending').length > 0 ? 'text-yellow-400' : 'text-green-400'}`}>
                          {approvalList.filter(a => a.status === 'pending').length}
                        </span>
                      </div>
                      {(() => {
                        const pc = automationCards.find(c => c.card_id === 'paramopt_automation');
                        if (!pc) return null;
                        const status = String(pc.status || '').toUpperCase();
                        const isRunning = status === 'RUNNING';
                        const isError = status === 'ERROR' || status === 'STUCK' || pc.stuck;
                        return (
                          <div className="flex items-center gap-1">
                            <span className="text-[#8a8a8a]">参数优化:</span>
                            <span className={`font-medium ${isRunning ? 'text-green-400' : isError ? 'text-red-400' : 'text-[#8a8a8a]'}`}>
                              {isRunning ? '运行中' : isError ? '异常' : pc.status || '空闲'}
                            </span>
                          </div>
                        );
                      })()}
                    </div>
                  </div>

                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">📋 待审批策略</h3>
                    {approvalList.length > 0 ? (
                      <div className="space-y-2 text-sm">
                        {approvalList.map((a, idx) => (
                          <div key={idx} className="flex items-center justify-between p-2 bg-[#0d0d0d] rounded">
                            <div>
                              <p className="text-white">{a.strategy_name || 'Unknown Strategy'}</p>
                              <p className="text-xs text-[#8a8a8a]">
                                类型: {a.request_type || 'strategy_deployment'}
                                {a.created_at && <span> · {new Date(a.created_at * 1000).toLocaleString('zh-CN')}</span>}
                              </p>
                            </div>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              a.status === 'approved' ? 'bg-green-500/20 text-green-400' :
                              a.status === 'rejected' ? 'bg-red-500/20 text-red-400' :
                              'bg-yellow-500/20 text-yellow-400'}`}
                            >
                              {a.status || 'pending'}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center text-[#8a8a8a] py-4">
                        {isLoadingClassicData ? '加载中...' : '暂无待审批项'}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {classicSubTab === 'signals' && (
                <div className="space-y-3">
                  <div className="flex items-center justify-between">
                    <h2 className="text-xl font-semibold text-white mb-2">🎯 信号触发 (Freqtrade)</h2>
                    <div className="flex items-center gap-2">
                      <span className={`w-2 h-2 rounded-full ${classicHealth.ok ? 'bg-green-500 animate-pulse' : 'bg-red-500'}`}></span>
                      <span className="text-xs text-[#8a8a8a]">{classicHealth.ok ? 'LIVE' : 'OFFLINE'}</span>
                      <button
                        onClick={loadClassicSystemData}
                        className="px-3 py-1 text-xs bg-[#8b5cf6] text-white rounded-md hover:bg-[#7c3aed] transition"
                      >
                        🔄 刷新
                      </button>
                    </div>
                  </div>
                  <p className="text-[#8a8a8a] text-sm">经典策略通过 Freqtrade 执行引擎产生入场/离场信号。此处显示所有已上线策略的实时信号。</p>

                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <div className="flex items-center justify-between mb-3">
                      <h3 className="text-white font-medium">📡 实时信号流</h3>
                      <span className="text-xs text-[#8a8a8a]">共 {signalList.length} 条信号</span>
                    </div>
                    {signalList.length > 0 ? (
                      <div className="space-y-2 text-sm max-h-96 overflow-y-auto">
                        {signalList.map((s, idx) => (
                          <div key={idx} className="flex items-center gap-3 p-2 bg-[#0d0d0d] rounded border-l-2 border-[#8b5cf6]">
                            <span className="text-[#6a6a6a] text-xs w-20">
                              {s.timestamp ? new Date(s.timestamp * 1000).toLocaleTimeString('zh-CN') : '-'}
                            </span>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${
                              s.signal === 'enter' || s.signal === 'entry' ? 'bg-green-500/20 text-green-400' :
                              s.signal === 'exit' || s.signal === 'close' ? 'bg-blue-500/20 text-blue-400' :
                              'bg-gray-500/20 text-gray-400'}`}
                            >
                              {s.signal || 'unknown'}
                            </span>
                            <span className="text-white font-medium w-28">{s.strategy || '-'}</span>
                            <span className="text-[#8a8a8a] flex-1 text-xs">
                              {s.direction === 'long' ? '📈 LONG' : s.direction === 'short' ? '📉 SHORT' : '➡️ NEUTRAL'}
                            </span>
                            {s.confidence !== undefined && (
                              <span className={`text-xs px-2 py-0.5 rounded-full ${
                                s.confidence >= 0.7 ? 'bg-green-500/20 text-green-400' :
                                s.confidence >= 0.4 ? 'bg-yellow-500/20 text-yellow-400' :
                                'bg-gray-500/20 text-gray-400'}`}
                              >
                                {(s.confidence * 100).toFixed(0)}%
                              </span>
                            )}
                            {s.entry_price && <span className="text-white text-sm">${s.entry_price}</span>}
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="text-center text-[#8a8a8a] py-8">
                        {isLoadingClassicData ? '加载中...' : (classicHealth.ok ? '暂无信号' : '系统离线')}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {classicSubTab === 'filter' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🔍 信号过滤</h2>
                  <p className="text-[#8a8a8a] text-sm">全局过滤器避免在不利市场条件下执行信号。包括：波动率阈值、资金费率阈值、趋势方向确认、黑窗口时段屏蔽等。</p>

                  {/* Gate Thresholds */}
                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">🚪 Gate Thresholds（门槛阈值）</h3>
                    {gateCheck.ok && gateCheck.thresholds ? (
                      <div className="space-y-2">
                        {[
                          { key: 'pf', name: '📊 Profit Factor', desc: '盈亏比阈值', defaultVal: '≥ 1.05' },
                          { key: 'dd', name: '⚠️ Max Drawdown', desc: '最大回撤限制', defaultVal: '≤ 95%' },
                          { key: 'trades', name: '🎯 交易次数', desc: '最小交易次数比例', defaultVal: '≥ 70%' },
                          { key: 'winrate', name: '🏆 胜率', desc: '胜率阈值', defaultVal: '≥ 95%' },
                        ].map((item, idx) => {
                          const val = gateCheck.thresholds?.[item.key];
                          const checkPassed = gateCheck.checks?.[item.key];
                          return (
                            <div key={idx} className="flex items-center justify-between p-3 bg-[#0d0d0d] rounded">
                              <div className="flex-1">
                                <p className="text-white text-sm font-medium">{item.name}</p>
                                <p className="text-xs text-[#8a8a8a] mt-1">{item.desc}: {val !== undefined ? (item.key === 'dd' ? `≤ ${(val * 100).toFixed(0)}%` : item.key === 'winrate' ? `≥ ${(val * 100).toFixed(0)}%` : item.key === 'pf' ? `≥ ${val.toFixed(2)}` : `≥ ${(val * 100).toFixed(0)}%`) : item.defaultVal}</p>
                              </div>
                              <span className={`text-xs px-2 py-1 rounded-full ${
                                checkPassed ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}
                              >
                                {checkPassed ? '✓ 通过' : '✗ 未通过'}
                              </span>
                            </div>
                          );
                        })}
                      </div>
                    ) : (
                      <div className="text-center text-[#8a8a8a] py-4">
                        {isLoadingClassicData ? '加载中...' : '暂无阈值配置'}
                      </div>
                    )}
                  </div>

                  {/* Gate Check 结果 */}
                  {gateCheck.ok && (
                    <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#8b5cf6]/30">
                      <div className="flex items-center justify-between">
                        <h3 className="text-white font-medium">🚪 Gate Check 状态</h3>
                        <span className={`text-xs px-3 py-1 rounded-full ${gateCheck.passed ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                          {gateCheck.passed ? '✓ 全部通过' : '✗ 存在未通过项'}
                        </span>
                      </div>
                      {gateCheck.metrics && (
                        <div className="mt-3 grid grid-cols-4 gap-3 text-xs">
                          <div className="text-center">
                            <div className="text-[#8a8a8a]">Profit Factor</div>
                            <div className={`text-lg font-bold ${gateCheck.metrics.pf >= 1 ? 'text-green-400' : 'text-red-400'}`}>
                              {gateCheck.metrics.pf?.toFixed(2) || '-'}
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-[#8a8a8a]">Win Rate</div>
                            <div className="text-lg font-bold text-white">
                              {((gateCheck.metrics.winrate || 0) * 100).toFixed(1)}%
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-[#8a8a8a]">Max DD</div>
                            <div className={`text-lg font-bold ${gateCheck.metrics.maxdd <= 0.1 ? 'text-green-400' : 'text-red-400'}`}>
                              {((gateCheck.metrics.maxdd || 0) * 100).toFixed(1)}%
                            </div>
                          </div>
                          <div className="text-center">
                            <div className="text-[#8a8a8a]">Trades</div>
                            <div className="text-lg font-bold text-white">
                              {gateCheck.metrics.trades || '-'}
                            </div>
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              )}

              {classicSubTab === 'execution' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">⚡ 信号执行</h2>
                  <p className="text-[#8a8a8a] text-sm">已通过过滤的信号触发交易所下单。显示最近的结算记录（ab_settlements）。</p>

                  {/* 统计总览 */}
                  <div className="grid grid-cols-4 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-white">{settlements.length}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">总结算数</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-green-400">
                        {settlements.filter(s => s.pnl_usdc > 0).length}
                      </div>
                      <div className="text-xs text-[#8a8a8a] mt-1">盈利次数</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-red-400">
                        {settlements.filter(s => s.pnl_usdc < 0).length}
                      </div>
                      <div className="text-xs text-[#8a8a8a] mt-1">亏损次数</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-yellow-400">
                        {settlements.length > 0 ? (settlements.reduce((sum, s) => sum + s.pnl_usdc, 0)).toFixed(2) : '-'}
                      </div>
                      <div className="text-xs text-[#8a8a8a] mt-1">总盈亏 USDC</div>
                    </div>
                  </div>

                  {/* 执行记录表 */}
                  <div className="mt-4 bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">💼 最近执行记录</h3>
                    <div className="overflow-x-auto">
                      <table className="w-full text-sm">
                        <thead>
                          <tr className="text-[#8a8a8a] text-xs border-b border-[#1f1f1f]">
                            <th className="py-2 px-3 text-left">时间</th>
                            <th className="py-2 px-3 text-left">策略</th>
                            <th className="py-2 px-3 text-left">交易对</th>
                            <th className="py-2 px-3 text-left">原因</th>
                            <th className="py-2 px-3 text-right">名义金额</th>
                            <th className="py-2 px-3 text-right">盈亏</th>
                            <th className="py-2 px-3 text-right">收益率</th>
                          </tr>
                        </thead>
                        <tbody>
                          {settlements.slice(0, 20).map((s, idx) => (
                            <tr key={s.event_id || idx} className="border-b border-[#1f1f1f] hover:bg-[#161616]">
                              <td className="py-2 px-3 text-[#6a6a6a]">
                                {s.ts ? new Date(s.ts).toLocaleString('zh-CN', { hour12: false, month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}
                              </td>
                              <td className="py-2 px-3 text-white">{s.strategy_id || '-'}</td>
                              <td className="py-2 px-3 text-white">{s.pair || '-'}</td>
                              <td className="py-2 px-3 text-[#8a8a8a]">{s.reason || '-'}</td>
                              <td className="py-2 px-3 text-right text-white">{s.notional_usdc?.toFixed(0) || '-'}</td>
                              <td className={`py-2 px-3 text-right ${s.pnl_usdc >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {s.pnl_usdc != null ? (s.pnl_usdc >= 0 ? '+' : '') + s.pnl_usdc.toFixed(2) : '-'}
                              </td>
                              <td className={`py-2 px-3 text-right ${s.ret_ratio >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                                {s.ret_ratio != null ? (s.ret_ratio >= 0 ? '+' : '') + (s.ret_ratio * 100).toFixed(2) + '%' : '-'}
                              </td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {settlements.length === 0 && (
                      <div className="text-center text-[#8a8a8a] py-8">
                        {isLoadingClassicData ? '加载中...' : '暂无执行记录'}
                      </div>
                    )}
                  </div>
                </div>
              )}

              {classicSubTab === 'exit' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🏁 离场管理</h2>
                  <p className="text-[#8a8a8a] text-sm">策略离场管理。支持：固定止盈止损、移动止损（Trailing Stop）、时间止损、波动率自适应离场等。</p>

                  {/* 离场状态总览 */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-white">{Object.keys(exitStats.open_positions).length}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">当前持仓</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-green-400">{exitStats.exit_owner_state?.weights?.exit_feeder != null ? `${Math.round((exitStats.exit_owner_state.weights.exit_feeder || 0) * 100)}%` : '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">Exit Feeder 权重</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-yellow-400">{exitStats.exit_owner_state?.weights?.strategy != null ? `${Math.round((exitStats.exit_owner_state.weights.strategy || 0) * 100)}%` : '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">策略退出权重</div>
                    </div>
                  </div>

                  {/* 持仓列表 */}
                  {Object.keys(exitStats.open_positions).length > 0 ? (
                    <div className="space-y-2">
                      {Object.entries(exitStats.open_positions).map(([pair, pos]: [string, any]) => (
                        <div key={pair} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                          <div className="flex items-center justify-between mb-2">
                            <div className="flex items-center gap-3">
                              <span className="text-white font-medium">{pair}</span>
                              <span className={`text-xs px-2 py-0.5 rounded-full ${pos.side === 'long' ? 'bg-green-500/20 text-green-400' : 'bg-red-500/20 text-red-400'}`}>
                                {pos.side?.toUpperCase()}
                              </span>
                              <span className={`text-xs px-2 py-0.5 rounded-full ${pos.mode === 'live' ? 'bg-red-500/20 text-red-400' : 'bg-yellow-500/20 text-yellow-400'}`}>
                                {pos.mode}
                              </span>
                            </div>
                            <span className="text-xs text-[#8a8a8a]">
                              {pos.strategy_id || pos.system_id}
                            </span>
                          </div>
                          <div className="grid grid-cols-4 gap-2 text-xs">
                            <div>
                              <span className="text-[#8a8a8a]">入场时间: </span>
                              <span className="text-white">{pos.entry_ts ? new Date(pos.entry_ts).toLocaleString('zh-CN', { hour12: false }) : '-'}</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">持仓金额: </span>
                              <span className="text-white">{pos.notional_usdc?.toFixed(1)} USDC</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">杠杆: </span>
                              <span className="text-white">{pos.leverage}x</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">离场决策: </span>
                              <span className={pos.exit_l1_last_decision?.action === 'hold' ? 'text-green-400' : 'text-yellow-400'}>
                                {pos.exit_l1_last_decision?.action || '-'}
                              </span>
                            </div>
                          </div>
                          <div className="mt-2 flex gap-4 text-xs">
                            <div>
                              <span className="text-[#8a8a8a]">持有价值: </span>
                              <span className={pos.hold_value >= 0.9 ? 'text-green-400' : pos.hold_value >= 0.7 ? 'text-yellow-400' : 'text-red-400'}>
                                {(pos.hold_value * 100).toFixed(1)}%
                              </span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">持有风险: </span>
                              <span className="text-red-400">{(pos.hold_risk * 100).toFixed(1)}%</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">退出方: </span>
                              <span className="text-white">{pos.exit_owner || '-'}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center text-[#8a8a8a] py-8 bg-[#1a1a1a] rounded-lg border border-[#1f1f1f]">
                      {isLoadingClassicData ? '加载中...' : '暂无持仓'}
                    </div>
                  )}
                </div>
              )}

              {/* Arena 多模型投票 */}
              {classicSubTab === 'arena' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🎲 多模型投票 (Arena)</h2>
                  <p className="text-[#8a8a8a] text-sm">多模型竞争与投票机制，决定哪个模型负责执行交易。</p>

                  {/* 状态总览 */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-white">{arenaState.enabled ? '运行中' : '未启用'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">Arena 状态</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-green-400">{arenaState.models ? Object.keys(arenaState.models).length : 0}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">参与模型数</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-yellow-400">{arenaState.pool_u != null ? arenaState.pool_u.toFixed(2) : '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">Pool U</div>
                    </div>
                  </div>

                  {/* 模型列表 */}
                  {arenaState.models && Object.keys(arenaState.models).length > 0 ? (
                    <div className="space-y-2">
                      {Object.entries(arenaState.models).map(([modelId, model]: [string, any]) => (
                        <div key={modelId} className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                          <div className="flex items-center justify-between mb-2">
                            <span className="text-white font-medium">{model.name || modelId}</span>
                            <span className={`text-xs px-2 py-0.5 rounded-full ${model.eligible ? 'bg-green-500/20 text-green-400' : 'bg-[#2a2a2a] text-[#8a8a8a]'}`}>
                              {model.eligible ? '合格' : '待观察'}
                            </span>
                          </div>
                          <div className="grid grid-cols-4 gap-2 text-xs">
                            <div>
                              <span className="text-[#8a8a8a]">Capital U: </span>
                              <span className="text-white">{model.capital_u?.toFixed(2) || '-'}</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">Sharpe: </span>
                              <span className="text-white">{model.sharpe?.toFixed(2) || '-'}</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">Win Rate: </span>
                              <span className="text-white">{model.win_rate?.toFixed(2) || '-'}</span>
                            </div>
                            <div>
                              <span className="text-[#8a8a8a]">LogLoss: </span>
                              <span className="text-white">{model.avg_logloss?.toFixed(4) || '-'}</span>
                            </div>
                          </div>
                        </div>
                      ))}
                    </div>
                  ) : (
                    <div className="text-center text-[#8a8a8a] py-8 bg-[#1a1a1a] rounded-lg border border-[#1f1f1f]">
                      {isLoadingClassicData ? '加载中...' : '暂无模型数据'}
                    </div>
                  )}
                </div>
              )}

              {/* Universe 代币筛选 */}
              {classicSubTab === 'universe' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">🌐 代币筛选 (Universe)</h2>
                  <p className="text-[#8a8a8a] text-sm">核心代币池 + 观察池 + 影子池。策略只在这些代币对中生成信号。</p>

                  {/* 状态总览 */}
                  <div className="grid grid-cols-3 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-green-400">{universeState.core?.length || 0}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">核心币 (Core)</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-yellow-400">{universeState.watchlist?.length || 0}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">观察列表 (Watchlist)</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-blue-400">{universeState.shadow?.length || 0}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">影子池 (Shadow)</div>
                    </div>
                  </div>

                  {/* 核心币列表 */}
                  <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">核心代币 (Core) - {universeState.core?.length || 0} 个</h3>
                    <div className="flex flex-wrap gap-2">
                      {universeState.core?.slice(0, 30).map((coin: string) => (
                        <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-green-400">
                          {coin}
                        </span>
                      ))}
                    </div>
                    {universeState.core && universeState.core.length > 30 && (
                      <div className="text-xs text-[#8a8a8a] mt-2">还有 {universeState.core.length - 30} 个...</div>
                    )}
                  </div>

                  {/* 观察列表 */}
                  {universeState.watchlist && universeState.watchlist.length > 0 && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">观察列表 (Watchlist) - {universeState.watchlist.length} 个</h3>
                      <div className="flex flex-wrap gap-2">
                        {universeState.watchlist.map((coin: string) => (
                          <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-yellow-400">
                            {coin}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 影子池 */}
                  {universeState.shadow && universeState.shadow.length > 0 && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">影子池 (Shadow) - {universeState.shadow.length} 个</h3>
                      <div className="flex flex-wrap gap-2">
                        {universeState.shadow.slice(0, 20).map((coin: string) => (
                          <span key={coin} className="px-2 py-1 bg-[#2a2a2a] rounded-md text-xs text-blue-400">
                            {coin}
                          </span>
                        ))}
                      </div>
                    </div>
                  )}

                  {/* 更新时间 */}
                  <div className="text-xs text-[#8a8a8a]">
                    最后更新: {universeState.last_update ? new Date(universeState.last_update).toLocaleString('zh-CN', { hour12: false }) : '-'}
                  </div>
                </div>
              )}

              {/* Macro 宏观门控 */}
              {classicSubTab === 'macro' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">📊 宏观门控 (Macro)</h2>
                  <p className="text-[#8a8a8a] text-sm">BTC/ETH 市场整体状态。门控决定在特定市场环境下是否允许开仓。</p>

                  {/* 门控状态 */}
                  <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                    <h3 className="text-white font-medium mb-3">Gate 状态</h3>
                    <div className="grid grid-cols-2 gap-3">
                      <div className="text-center">
                        <div className={`text-2xl font-bold ${macroState.gate_std1h?.effective_long_ok ? 'text-green-400' : 'text-red-400'}`}>
                          {macroState.gate_std1h?.effective_long_ok ? '允许做多' : '禁止做多'}
                        </div>
                        <div className="text-xs text-[#8a8a8a] mt-1">Long Direction</div>
                      </div>
                      <div className="text-center">
                        <div className={`text-2xl font-bold ${macroState.gate_std1h?.effective_short_ok ? 'text-green-400' : 'text-red-400'}`}>
                          {macroState.gate_std1h?.effective_short_ok ? '允许做空' : '禁止做空'}
                        </div>
                        <div className="text-xs text-[#8a8a8a] mt-1">Short Direction</div>
                      </div>
                    </div>
                    <div className="mt-3 text-center text-xs text-[#8a8a8a]">
                      当前推荐: <span className="text-white">{macroState.gate_std1h?.effective_recommend || '-'}</span>
                    </div>
                  </div>

                  {/* BTC/ETH 趋势 */}
                  <div className="grid grid-cols-2 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">BTC</h3>
                      <div className="space-y-1 text-xs">
                        {(() => {
                          const energyRows = (macroState.btc?.energy as any)?.rows || [];
                          const trendRows = (macroState.btc?.trend as any)?.rows || [];
                          const latestEnergy = energyRows[energyRows.length - 1] || {};
                          const latestTrend = trendRows[trendRows.length - 1] || {};
                          return (
                            <>
                              <div>
                                <span className="text-[#8a8a8a]">Close: </span>
                                <span className="text-white">{latestEnergy.close?.toFixed(2) || '-'}</span>
                              </div>
                              <div>
                                <span className="text-[#8a8a8a]">Regime: </span>
                                <span className="text-white">{latestTrend.time_regime || '-'}</span>
                              </div>
                              <div>
                                <span className="text-[#8a8a8a]">Shape: </span>
                                <span className="text-white">{latestTrend.trend_shape_5 || '-'}</span>
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">ETH</h3>
                      <div className="space-y-1 text-xs">
                        {(() => {
                          const energyRows = (macroState.eth?.energy as any)?.rows || [];
                          const trendRows = (macroState.eth?.trend as any)?.rows || [];
                          const latestEnergy = energyRows[energyRows.length - 1] || {};
                          const latestTrend = trendRows[trendRows.length - 1] || {};
                          return (
                            <>
                              <div>
                                <span className="text-[#8a8a8a]">Close: </span>
                                <span className="text-white">{latestEnergy.close?.toFixed(2) || '-'}</span>
                              </div>
                              <div>
                                <span className="text-[#8a8a8a]">Regime: </span>
                                <span className="text-white">{latestTrend.time_regime || '-'}</span>
                              </div>
                              <div>
                                <span className="text-[#8a8a8a]">Shape: </span>
                                <span className="text-white">{latestTrend.trend_shape_5 || '-'}</span>
                              </div>
                            </>
                          );
                        })()}
                      </div>
                    </div>
                  </div>

                  {/* Shape 状态 */}
                  {macroState.macro_btceth_shape && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">Shape 状态</h3>
                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">方向判断:</span>
                          <span className={`${macroState.macro_btceth_shape.dir_12h === 'long' ? 'text-green-400' : macroState.macro_btceth_shape.dir_12h === 'short' ? 'text-red-400' : 'text-white'}`}>
                            {macroState.macro_btceth_shape.dir_12h || '-'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">允许做多:</span>
                          <span className={macroState.macro_btceth_shape.dir_long_any ? 'text-green-400' : 'text-red-400'}>
                            {macroState.macro_btceth_shape.dir_long_any ? '是' : '否'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">允许做空:</span>
                          <span className={macroState.macro_btceth_shape.dir_short_any ? 'text-red-400' : 'text-green-400'}>
                            {macroState.macro_btceth_shape.dir_short_any ? '是' : '否'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">OK:</span>
                          <span className={macroState.macro_btceth_shape.ok ? 'text-green-400' : 'text-yellow-400'}>
                            {macroState.macro_btceth_shape.ok ? '正常' : '警告'}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Tri-layer 状态 */}
                  {macroState.macro_tri_layer && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">Tri-Layer 控制</h3>
                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">允许开仓:</span>
                          <span className={macroState.macro_tri_layer.allow_open ? 'text-green-400' : 'text-red-400'}>
                            {macroState.macro_tri_layer.allow_open ? '是' : '否'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">允许附加:</span>
                          <span className={macroState.macro_tri_layer.allow_addon ? 'text-green-400' : 'text-red-400'}>
                            {macroState.macro_tri_layer.allow_addon ? '是' : '否'}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}

              {/* Evaluation 模型评估 */}
              {classicSubTab === 'evaluation' && (
                <div className="space-y-3">
                  <h2 className="text-xl font-semibold text-white mb-2">📈 模型评估 (Evaluation)</h2>
                  <p className="text-[#8a8a8a] text-sm">模型接受度、在线学习、版本控制与晋升机制。</p>

                  {/* 状态总览 */}
                  <div className="grid grid-cols-4 gap-3">
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-white">{evaluationState.orders?.total ?? '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">总订单数</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-green-400">{evaluationState.orders?.window ?? '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">窗口期订单</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-yellow-400">{evaluationState.profit_window?.profit_factor?.toFixed(2) || '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">Profit Factor</div>
                    </div>
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f] text-center">
                      <div className="text-2xl font-bold text-blue-400">v{evaluationState.online?.version || '-'}</div>
                      <div className="text-xs text-[#8a8a8a] mt-1">模型版本</div>
                    </div>
                  </div>

                  {/* Acceptance 状态 */}
                  {evaluationState.acceptance && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">接受度控制</h3>
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="space-y-1">
                          <div className="flex justify-between">
                            <span className="text-[#8a8a8a]">采样阶段:</span>
                            <span className="text-white">{String(evaluationState.acceptance.sampling_phase)}</span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-[#8a8a8a]">利润阶段:</span>
                            <span className="text-white">{String(evaluationState.acceptance.profit_phase)}</span>
                          </div>
                        </div>
                        <div className="space-y-1">
                          <div className="flex justify-between">
                            <span className="text-[#8a8a8a]">主释放门:</span>
                            <span className={evaluationState.acceptance.main_release_gate ? 'text-green-400' : 'text-yellow-400'}>
                              {String(evaluationState.acceptance.main_release_gate)}
                            </span>
                          </div>
                          <div className="flex justify-between">
                            <span className="text-[#8a8a8a]">回滚状态:</span>
                            <span className="text-white">{String(evaluationState.acceptance.rollback)}</span>
                          </div>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Online 学习 */}
                  {evaluationState.online && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">在线学习状态</h3>
                      <div className="space-y-2 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">上次训练:</span>
                          <span className="text-white">
                            {evaluationState.online.last_train_ms ? new Date(evaluationState.online.last_train_ms).toLocaleString('zh-CN', { hour12: false }) : '-'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">上次晋升:</span>
                          <span className="text-white">
                            {evaluationState.online.last_promote_ms ? new Date(evaluationState.online.last_promote_ms).toLocaleString('zh-CN', { hour12: false }) : '-'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">训练样本:</span>
                          <span className="text-white">{evaluationState.online.train_sample_count ?? '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">ART 训练:</span>
                          <span className={evaluationState.online.artifact_trained ? 'text-green-400' : 'text-yellow-400'}>
                            {String(evaluationState.online.artifact_trained)}
                          </span>
                        </div>
                      </div>
                    </div>
                  )}

                  {/* Profit Window */}
                  {evaluationState.profit_window && (
                    <div className="bg-[#1a1a1a] rounded-lg p-4 border border-[#1f1f1f]">
                      <h3 className="text-white font-medium mb-3">利润窗口 ({evaluationState.profit_window.days || '-'} 天)</h3>
                      <div className="grid grid-cols-2 gap-3 text-xs">
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">样本数:</span>
                          <span className="text-white">{evaluationState.profit_window.n || '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">最大回撤 U:</span>
                          <span className="text-red-400">{evaluationState.profit_window.max_drawdown_u?.toFixed(2) || '-'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">Profit Factor:</span>
                          <span className={evaluationState.profit_window.profit_factor >= 2 ? 'text-green-400' : 'text-yellow-400'}>
                            {evaluationState.profit_window.profit_factor?.toFixed(2) || '-'}
                          </span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-[#8a8a8a]">最大恢复耗时:</span>
                          <span className="text-white">{evaluationState.profit_window.max_recovery_ms || '-'}</span>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
        </section>
      )}

      {activeTab === 'fundamental' && (
        <div />
      )}
    </main>
  );
}
