/**
 * 36-通信系统层（Signal Bus）类型定义
 * 依据 SPEC.md v1.0 第 4 章
 */

/** 信号类型（topic 维度） */
export type SignalType =
  | 'trade_signal.open'
  | 'trade_signal.close'
  | 'trade_signal.skip'
  | 'risk_alert'
  | 'strategy_update'
  | 'strategy_executed'
  | 'intel_update'
  | 'daily_report'
  | 'system_notice';

/** 严重级别（沿用 15 号模块定义） */
export type Severity = 'critical' | 'error' | 'warning' | 'info';

/** 分发通道 */
export type DispatchChannel = 'API' | 'HERMES';

/** 信号信封（消息头） */
export interface SignalEnvelope {
  /** 唯一 ID（ULID），支持追溯与重放 */
  id: string;
  /** 信号类型（topic） */
  type: SignalType;
  /** 严重级别 */
  severity: Severity;
  /** 来源模块（如 m28-freqtrade、m15-monitor） */
  source: string;
  /** 发出时间戳（ms） */
  ts: number;
  /** 类型化负载 */
  payload: Record<string, unknown>;
  /** 幂等键，防重复投递（可选） */
  dedupKey?: string;
}

/** 交易信号负载：trade_signal.open / close / skip */
export interface TradeSignalPayload {
  symbol: string;
  direction: 'LONG' | 'SHORT';
  entryPrice?: number;
  exitPrice?: number;
  confidence?: number;
  reason?: string;
  strategyName?: string;
  orderId?: string;
}

/** 风险告警负载 */
export interface RiskAlertPayload {
  metric: string;
  value: number;
  threshold: number;
  positionId?: string;
}

/** 信号订阅记录（对应 Prisma SignalSubscription） */
export interface SignalSubscription {
  id: string;
  uid: string;
  signalType: SignalType;
  channel: DispatchChannel;
  /** API 通道时为渠道配置ID；HERMES 时为群 chat_id */
  target?: string | null;
  createdAt: string;
  updatedAt: string;
}

/** emit 接口响应 */
export interface EmitResult {
  id: string;
  /** 已分发到的通道描述 */
  dispatched: string[];
  /** 降级挂起时进入的队列 */
  queued?: string[];
}

/** 通知类信号类型集合（默认走 API 直推） */
export const NOTIFY_TYPES: ReadonlySet<SignalType> = new Set([
  'trade_signal.open',
  'trade_signal.close',
  'trade_signal.skip',
  'risk_alert',
  'strategy_update',
  'strategy_executed',
  'daily_report',
  'system_notice',
]);

/** 交互类信号类型集合（默认走 Hermes 智能通道） */
export const INTERACTIVE_TYPES: ReadonlySet<SignalType> = new Set([
  'intel_update',
]);

/** 信号类型中文标签 */
export const SIGNAL_TYPE_LABELS: Record<SignalType, string> = {
  'trade_signal.open': '开仓信号',
  'trade_signal.close': '平仓信号',
  'trade_signal.skip': '跳过信号',
  'risk_alert': '风险告警',
  'strategy_update': '策略更新',
  'strategy_executed': '策略执行',
  'intel_update': '情报更新',
  'daily_report': '每日报告',
  'system_notice': '系统通知',
};

/** 严重级别颜色映射（沿用 15 号模块） */
export const SEVERITY_COLORS: Record<Severity, string> = {
  critical: '#ff4d4f',
  error: '#ff7875',
  warning: '#faad14',
  info: '#1890ff',
};

/** 严重级别 Emoji */
export const SEVERITY_EMOJI: Record<Severity, string> = {
  critical: '🔴',
  error: '🟠',
  warning: '🟡',
  info: '🔵',
};
