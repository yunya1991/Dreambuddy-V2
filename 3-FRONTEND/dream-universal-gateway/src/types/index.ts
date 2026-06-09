// ============================================
// Dream Universal Gateway — 核心类型定义
// 版本: v1.0 | 日期: 2026-05-14
// ============================================

// === 用户体系 ===

export type UserRole = "FREE" | "PRO" | "ADMIN";
export type TradeType = "SPOT" | "SWAP";
export type TradeMode = "SPOT_MODE" | "SWAP_MODE" | "FUTURES_MODE" | "OPTIONS_MODE" | "MARGIN_MODE";
export type MarginMode = "CROSS" | "ISOLATED";
export type PositionMode = "NET" | "HEDGE";
export type OptionsType = "CALL" | "PUT";
export type Direction = "BUY" | "SHORT" | "SKIP";
export type StrategyType = "RECOMMENDED" | "CUSTOM";
export type StrategyStatus = "DRAFT" | "APPROVED" | "APPLIED" | "PAUSED" | "EXPIRED";
export type TaskStatus = "ACTIVE" | "PAUSED" | "COMPLETED" | "FAILED";
export type Frequency = "ONE_H" | "FOUR_H" | "ONE_D";
export type RiskTolerance = "CONSERVATIVE" | "MODERATE" | "AGGRESSIVE";
export type ApiCategory = "EXCHANGE" | "LLM" | "DATA_SOURCE";
export type ChannelType = "TELEGRAM" | "WECHAT_SERVERCHAN" | "WECHAT_WORK" | "EMAIL_SMTP" | "DISCORD" | "SLACK";
export type CreditsType = "EARN" | "SPEND";
export type CreditsCategory =
  | "RECHARGE" | "SIGNIN" | "REFERRAL" | "BONUS" | "SIGNUP_BONUS"
  | "STRATEGY_EXECUTION" | "ANALYSIS_REPORT" | "INTEL_BRIEF";
export type TradingStatus = "ACTIVE" | "PAUSED" | "FROZEN" | "LOCKED";
export type OrderStatus = "PENDING" | "PAID" | "COMPLETED" | "CANCELLED" | "REFUNDED" | "FAILED";
export type PaymentMethod = "WECHAT_PAY" | "ALIPAY" | "APPLE_PAY";
export type PushFormat = "CONCISE" | "DETAILED";
export type PushMessageType =
  | "trade_signal" | "risk_alert" | "intel_update" | "daily_report"
  | "dream_insight" | "strategy_update" | "strategy_executed" | "system_notice" | "verification_code";

// === 意图识别 (v2) ===

export type IntentType =
  | "market_query" | "deep_analysis" | "scenario_sim" | "strategy_verify"
  | "execute_trade" | "simple_qa" | "command" | "system_config"
  | "credits_query" | "artifact_query" | "risk_alert_response";

export type ComplexityLevel = "simple" | "moderate" | "complex" | "urgent";
export type LoopType = "execution" | "intelligence" | "governance" | "general";

export interface IntentRecognitionResult {
  intent: IntentType;
  confidence: number;
  entities: Record<string, string>;
  complexity: ComplexityLevel;
  reasoning: string;
  method: "llm" | "rule" | "default";
  context_aware: boolean;
}

export interface RoutingDecision {
  loop_type: LoopType;
  chain: string[];
  estimated_time_ms: number;
  credits_cost: number;
  requires_confirmation: boolean;
  role_check: "pass" | "upgrade_required" | "denied";
  fallback_chain: string[];
  reasoning: string;
}

// === 意图识别路由响应 (API 返回格式) ===

export interface IntentRouteResponse {
  success: boolean;
  data: {
    content: string;
    intent: IntentType;
    confidence: number;
    routing: RoutingDecision;
    complexity: ComplexityLevel;
    method: "llm" | "rule" | "default";
    llm_status: "online" | "offline" | "degraded";
    llm_model: string;
    timestamp: string;
  };
}

// === 用户配置列表 (聚合视图) ===

export interface UserProfileView {
  uid: string;
  email: string;
  displayName?: string;
  avatarUrl?: string;
  role: UserRole;
  emailVerified: boolean;
  createdAt: string;

  tradingConfig: {
    availableCapital?: number;
    capitalPercentage: number;
    tradeType: TradeType;
    tradeMode: TradeMode;
    marginMode?: MarginMode;
    positionMode: PositionMode;
    leverageMax: number;
    dailyLossLimit: number;
    dailyLossPercent: number;
    accountLossLimit: number;
    accountLossPercent: number;
    allowedSymbols: string[];
    allowedTradeModes: TradeMode[];
    isTradingEnabled: boolean;
    optionsType?: OptionsType;
    expiryDate?: string;
    riskTolerance: RiskTolerance;
    preferredFrequency?: Frequency;
  };

  tradingLiveStatus: {
    todayLoss: number;
    todayTradeCount: number;
    totalLoss: number;
    totalTradeCount: number;
    status: TradingStatus;
    lastResetDate: string;
  };

  apiConfigStatus: {
    exchange: {
      provider: string;
      isConfigured: boolean;
      isVerified: boolean;
      environment: "demo" | "live";
      lastVerifiedAt?: string;
    } | null;
    llm: {
      provider: string;
      isConfigured: boolean;
    } | null;
    dataSource: {
      provider: string;
      isConfigured: boolean;
    } | null;
  };

  strategyConfig: {
    activeStrategyCount: number;
    totalStrategyCount: number;
    activeStrategies: {
      strategyId: string;
      strategyName: string;
      direction: Direction;
      executionFrequency: Frequency;
      nextExecutionAt: string;
    }[];
  };

  creditsInfo: {
    balance: number;
    totalEarned: number;
    totalSpent: number;
    expiringCredits: number;
  };

  channelConfig: {
    activeChannels: ChannelType[];
    channelCount: number;
  };
}

// === 意图识别 ===

export type IntentDomain = "crypto" | "traditional_finance" | "general";
export type IntentTask = "query" | "analysis" | "execution" | "configuration" | "credits";
export type IntentStrategy = "direct_return" | "incremental_update" | "partial_chain" | "full_chain";

export interface IntentResult {
  domain: IntentDomain;
  task: IntentTask;
  strategy: IntentStrategy;
  confidence: number;
  entities: Record<string, string>;
  relatedArtifactIds?: string[];
}

// === 对话 ===

export interface ChatMessage {
  id: string;
  role: "user" | "assistant" | "system";
  content: string;
  timestamp: number;
  metadata?: {
    intent?: IntentResult;
    artifactRefs?: string[];
    tokens?: number;
  };
}

export interface ChatSession {
  id: string;
  uid?: string;
  title: string;
  messages: ChatMessage[];
  createdAt: number;
  updatedAt: number;
}

// === TradingGate 门禁 ===

export interface TradingGateResult {
  passed: boolean;
  reason?: string;
  adjustedParams?: {
    leverage?: number;
    positionSize?: number;
  };
  checks: {
    capitalCheck: boolean;
    leverageCheck: boolean;
    dailyLossCheck: boolean;
    accountLossCheck: boolean;
    symbolCheck: boolean;
    tradingEnabledCheck: boolean;
    apiConfigCheck: boolean;
    creditsCheck: boolean;
  };
}

// === 术语映射 (A系列 → 用户可见) ===

export const TERM_MAP: Record<string, string> = {
  A0: "(内部)",
  A1: "市场侦察",
  A2: "深度分析",
  A3: "情景推演",
  A4: "方案验证",
  A5: "执行操作",
  A6: "情报更新",
  A7: "风控审查",
  A8: "(内部)",
  A9: "离场评估",
  RANGE_BOUND: "区间震荡",
  STRONG_BULL: "强势上涨",
  STRONG_BEAR: "强势下跌",
  MODERATE_BULL: "温和上涨",
  MODERATE_BEAR: "温和下跌",
  SKIP: "观望",
  WAIT: "等待",
  BUY: "做多",
  SHORT: "做空",
};

// === 配置完成度 ===

export interface CompletenessStep {
  key: string;
  label: string;
  completed: boolean;
  required: boolean;
}

export interface CompletenessResult {
  overall: number;
  steps: CompletenessStep[];
}

// === 交易参数视图 (GET /api/config/trading-params 响应) ===

export interface TradingParamsView {
  params: {
    availableCapital?: number;
    capitalPercentage: number;
    tradeType: TradeType;
    tradeMode: TradeMode;
    marginMode?: MarginMode;
    positionMode: PositionMode;
    leverageMax: number;
    dailyLossLimit: number;
    dailyLossPercent: number;
    accountLossLimit: number;
    accountLossPercent: number;
    allowedSymbols: string[];
    allowedTradeModes: TradeMode[];
    isTradingEnabled: boolean;
    optionsType?: OptionsType;
    expiryDate?: string;
    riskTolerance: RiskTolerance;
    preferredFrequency?: Frequency;
  };
  liveStatus: {
    todayLoss: number;
    todayTradeCount: number;
    totalLoss: number;
    totalTradeCount: number;
    status: TradingStatus;
    lastResetDate: string;
  };
  exchangeStatus: {
    provider: string;
    isConfigured: boolean;
    isVerified: boolean;
    environment: "demo" | "live";
    lastVerifiedAt?: string;
  } | null;
}

// === 交易模式标签映射 ===

export const TRADE_MODE_LABELS: Record<TradeMode, string> = {
  SPOT_MODE: "现货",
  SWAP_MODE: "永续合约",
  FUTURES_MODE: "交割期货",
  OPTIONS_MODE: "期权",
  MARGIN_MODE: "杠杆交易",
};

export const TRADE_MODE_ICONS: Record<TradeMode, string> = {
  SPOT_MODE: "💰",
  SWAP_MODE: "⚡",
  FUTURES_MODE: "📅",
  OPTIONS_MODE: "🎰",
  MARGIN_MODE: "📊",
};

export const MARGIN_MODE_LABELS: Record<MarginMode, string> = {
  CROSS: "全仓",
  ISOLATED: "逐仓",
};

export const POSITION_MODE_LABELS: Record<PositionMode, string> = {
  NET: "净仓",
  HEDGE: "逐仓(双向)",
};

export const OPTIONS_TYPE_LABELS: Record<OptionsType, string> = {
  CALL: "看涨",
  PUT: "看跌",
};

// === 通信渠道视图 ===

export interface ChannelConfigView {
  id: string;
  channelType: ChannelType;
  label: string;
  pushRules: {
    enabledTypes: PushMessageType[];
    format: PushFormat;
    silentStart?: string;
    silentEnd?: string;
  };
  isOnline: boolean;
  lastTestAt?: string;
  createdAt: string;
}

export const CHANNEL_TYPE_LABELS: Record<ChannelType, string> = {
  TELEGRAM: "Telegram",
  WECHAT_SERVERCHAN: "微信(Server酱)",
  WECHAT_WORK: "企业微信",
  EMAIL_SMTP: "Email",
  DISCORD: "Discord",
  SLACK: "Slack",
};

export const CHANNEL_TYPE_ICONS: Record<ChannelType, string> = {
  TELEGRAM: "📱",
  WECHAT_SERVERCHAN: "💬",
  WECHAT_WORK: "💼",
  EMAIL_SMTP: "📧",
  DISCORD: "🎮",
  SLACK: "📲",
};

// === 策略视图 ===

export interface StrategyView {
  id: string;
  type: StrategyType;
  name: string;
  description?: string;
  direction: Direction;
  symbol: string;
  tradeType: TradeType;
  leverage: number;
  positionSize: number;
  stopLoss?: number;
  takeProfit?: number;
  confidence?: number;
  edgeScore?: number;
  regime?: string;
  source?: string;
  isRead: boolean;
  rawInput?: string;
  status: StrategyStatus;
  tasks: StrategyTaskView[];
  createdAt: string;
}

export interface StrategyTaskView {
  id: string;
  executionFrequency: Frequency;
  status: TaskStatus;
  nextExecutionAt?: string;
  lastExecutionAt?: string;
  executionCount: number;
  skipCount: number;
  tradeCount: number;
}

// === 推送消息类型标签 ===

export const PUSH_TYPE_LABELS: Record<PushMessageType, string> = {
  trade_signal: "交易信号",
  risk_alert: "风险告警",
  intel_update: "情报更新",
  daily_report: "每日报告",
  dream_insight: "做梦洞察",
  strategy_update: "策略推荐",
  strategy_executed: "策略执行",
  system_notice: "系统通知",
  verification_code: "验证码",
};
