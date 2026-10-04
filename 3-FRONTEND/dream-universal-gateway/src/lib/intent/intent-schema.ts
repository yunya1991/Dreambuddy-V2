/**
 * intent-schema.ts — 统一意图正典（Single Source of Truth）
 * PROP-20260828B · Phase 1（Z3 路径设计 §1）
 *
 * 职责：
 *   1. 定义全系统意图正典（35 型 = fallback 15 + 多场景 20）
 *   2. 三链别名映射（fallback/planner/chat 视图 ↔ 正典）双向无损
 *   3. 环归属（execution/intelligence/governance/general）
 *   4. 角色门禁矩阵（草案，Phase 3 评审签字后启用强制）
 *
 * 纪律：本文件零运行时依赖（不 import 任何业务模块），可被所有链安全引用。
 * 新增意图必须且只能在此文件登记，禁止各链私自定义。
 */

// ============ 1. 意图正典（35 型）============

/** 基础 15 型（源自 fallback-engine，系统级意图） */
const BASE_INTENTS = [
  'market_query',        // 行情查询
  'deep_analysis',       // 深度分析
  'scenario_sim',        // 情景模拟
  'strategy_verify',     // 策略验证
  'execute_trade',       // 执行交易
  'simple_qa',           // 简单问答
  'command',             // 命令（/开头快路径）
  'system_config',       // 系统配置
  'credits_query',       // 积分查询
  'artifact_query',      // 知识/产物查询
  'risk_alert_response', // 风险告警响应
  'triple_chain',        // 三链任务
  'need_clarification',  // 需要澄清（歧义出口）
  'clarification_result',// 澄清结果回传
  'developer',           // D-Z-E 开发链
] as const;

/** 多场景分析 20 型（源自 chat route P2-1，深度分析子类） */
const SCENARIO_INTENTS = [
  'asset_comparison', 'entry_timing', 'exit_timing', 'risk_analysis',
  'position_sizing', 'market_sentiment', 'trend_analysis', 'technical_signal',
  'support_resistance', 'portfolio_allocation', 'portfolio_rebalance',
  'event_analysis', 'concept_explain', 'strategy_recommendation',
  'backtest_help', 'volatility_analysis', 'macro_analysis', 'dca_strategy',
  'arbitrage_opportunity', 'sector_rotation',
] as const;

export const INTENT_CANON = [...BASE_INTENTS, ...SCENARIO_INTENTS] as const;
export type IntentCanon = typeof INTENT_CANON[number];

export function isIntentCanon(v: string): v is IntentCanon {
  return (INTENT_CANON as readonly string[]).includes(v);
}

// ============ 2. 环归属（与 smart-router LoopType 对齐）============

export type IntentLoop = 'execution' | 'intelligence' | 'governance' | 'general';

const LOOP_MAP: Record<IntentCanon, IntentLoop> = {
  // execution 执行环：直接改变仓位/资金/系统状态
  execute_trade: 'execution',
  dca_strategy: 'execution',
  portfolio_rebalance: 'execution',
  arbitrage_opportunity: 'execution',
  sector_rotation: 'execution',
  // governance 治理环：改变系统自身配置/代码
  system_config: 'governance',
  developer: 'governance',
  // general 通用：问答/命令/澄清等无环归属
  simple_qa: 'general',
  command: 'general',
  credits_query: 'general',
  artifact_query: 'general',
  concept_explain: 'general',
  backtest_help: 'general',
  need_clarification: 'general',
  clarification_result: 'general',
  // intelligence 情报环：其余全部为分析/研究类
  market_query: 'intelligence',
  deep_analysis: 'intelligence',
  scenario_sim: 'intelligence',
  strategy_verify: 'intelligence',
  risk_alert_response: 'intelligence',
  triple_chain: 'intelligence',
  asset_comparison: 'intelligence',
  entry_timing: 'intelligence',
  exit_timing: 'intelligence',
  risk_analysis: 'intelligence',
  position_sizing: 'intelligence',
  market_sentiment: 'intelligence',
  trend_analysis: 'intelligence',
  technical_signal: 'intelligence',
  support_resistance: 'intelligence',
  portfolio_allocation: 'intelligence',
  event_analysis: 'intelligence',
  strategy_recommendation: 'intelligence',
  volatility_analysis: 'intelligence',
  macro_analysis: 'intelligence',
};

export function intentLoop(intent: IntentCanon): IntentLoop {
  return LOOP_MAP[intent];
}

// ============ 3. 角色门禁矩阵（草案，Phase 3 评审后启用）============

export type UserRole = 'FREE' | 'PRO' | 'ADMIN';

/**
 * 每意图的最低角色要求。
 * ⚠️ 草案状态：由 Z4 验收方案产出，Phase 3 必须评审签字后才可接入强制校验。
 * 当前仅提供查询能力，不改变任何现有行为。
 */
const MIN_ROLE: Record<IntentCanon, UserRole> = {
  // ADMIN only
  execute_trade: 'ADMIN',
  system_config: 'ADMIN',
  developer: 'ADMIN',
  // PRO 及以上（策略/组合/进阶研究）
  strategy_verify: 'PRO',
  triple_chain: 'PRO',
  strategy_recommendation: 'PRO',
  backtest_help: 'PRO',
  dca_strategy: 'PRO',
  portfolio_allocation: 'PRO',
  portfolio_rebalance: 'PRO',
  sector_rotation: 'PRO',
  arbitrage_opportunity: 'PRO',
  scenario_sim: 'PRO',
  // 其余全部 FREE 可用（查询/分析/问答/澄清）
  market_query: 'FREE', deep_analysis: 'FREE', simple_qa: 'FREE',
  command: 'FREE', credits_query: 'FREE', artifact_query: 'FREE',
  risk_alert_response: 'FREE', need_clarification: 'FREE',
  clarification_result: 'FREE', concept_explain: 'FREE',
  asset_comparison: 'FREE', entry_timing: 'FREE', exit_timing: 'FREE',
  risk_analysis: 'FREE', position_sizing: 'FREE', market_sentiment: 'FREE',
  trend_analysis: 'FREE', technical_signal: 'FREE', support_resistance: 'FREE',
  event_analysis: 'FREE', volatility_analysis: 'FREE', macro_analysis: 'FREE',
};

const ROLE_RANK: Record<UserRole, number> = { FREE: 0, PRO: 1, ADMIN: 2 };

/** 查询：该角色是否允许该意图（草案，未接入强制） */
export function gateAllows(role: UserRole, intent: IntentCanon): boolean {
  return ROLE_RANK[role] >= ROLE_RANK[MIN_ROLE[intent]];
}

// ============ 4. 三链别名映射（双向无损）============

/**
 * planner 视图（24-图结构上下文压缩/planner/planner-types.ts，11 型）
 * 关键分歧：planner 用 'risk_alert'，fallback/chat 用 'risk_alert_response'
 */
const PLANNER_ALIASES: Record<string, IntentCanon> = {
  market_query: 'market_query',
  deep_analysis: 'deep_analysis',
  scenario_sim: 'scenario_sim',
  strategy_verify: 'strategy_verify',
  execute_trade: 'execute_trade',
  risk_alert: 'risk_alert_response', // ← 命名分歧修复点
  simple_qa: 'simple_qa',
  system_config: 'system_config',
  credits_query: 'credits_query',
  artifact_query: 'artifact_query',
  command: 'command',
};

/** planner 域内的正典 → planner 视图（正典子集） */
const CANON_TO_PLANNER: Partial<Record<IntentCanon, string>> = {
  market_query: 'market_query',
  deep_analysis: 'deep_analysis',
  scenario_sim: 'scenario_sim',
  strategy_verify: 'strategy_verify',
  execute_trade: 'execute_trade',
  risk_alert_response: 'risk_alert', // ← 反向映射
  simple_qa: 'simple_qa',
  system_config: 'system_config',
  credits_query: 'credits_query',
  artifact_query: 'artifact_query',
  command: 'command',
};

/** 别名 → 正典（未知返回 null，调用方决定兜底策略） */
export function aliasToCanon(alias: string): IntentCanon | null {
  if (isIntentCanon(alias)) return alias;
  return PLANNER_ALIASES[alias] ?? null;
}

/** 正典 → planner 视图（不在 planner 域内返回 null） */
export function canonToPlanner(intent: IntentCanon): string | null {
  return CANON_TO_PLANNER[intent] ?? null;
}

// ============ Legacy 视图（fallback-engine 15 型） ============

/**
 * fallback-engine 旧视图的 15 个意图。
 * 用于把正典结果无损降级回旧链（task-manager convertIntentToTaskFile 等）。
 */
export const LEGACY_VIEW = [
  'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade',
  'simple_qa', 'command', 'system_config', 'credits_query', 'artifact_query',
  'risk_alert_response', 'triple_chain', 'need_clarification', 'clarification_result', 'developer',
] as const;

export type LegacyIntent = typeof LEGACY_VIEW[number];

/**
 * 正典 → legacy 视图：15 个原生意图恒等映射，
 * 20 个多场景分析意图归并到其自然父类 deep_analysis（task 链按父类路由）。
 */
const CANON_TO_LEGACY: Record<IntentCanon, LegacyIntent> = {
  ...Object.fromEntries(LEGACY_VIEW.map(i => [i, i])) as Record<LegacyIntent, LegacyIntent>,
  asset_comparison: 'deep_analysis',
  entry_timing: 'deep_analysis',
  exit_timing: 'deep_analysis',
  risk_analysis: 'deep_analysis',
  position_sizing: 'deep_analysis',
  market_sentiment: 'deep_analysis',
  trend_analysis: 'deep_analysis',
  technical_signal: 'deep_analysis',
  support_resistance: 'deep_analysis',
  portfolio_allocation: 'deep_analysis',
  portfolio_rebalance: 'deep_analysis',
  event_analysis: 'deep_analysis',
  concept_explain: 'simple_qa',
  strategy_recommendation: 'deep_analysis',
  backtest_help: 'strategy_verify',
  volatility_analysis: 'deep_analysis',
  macro_analysis: 'deep_analysis',
  dca_strategy: 'deep_analysis',
  arbitrage_opportunity: 'deep_analysis',
  sector_rotation: 'deep_analysis',
};

export function canonToLegacy(c: IntentCanon): LegacyIntent {
  return CANON_TO_LEGACY[c] ?? 'deep_analysis';
}

// ============ 5. 前后端意图映射（前端 35 型 → 内核 6×30 对话意图）============
// DreamOS 内核 S 层使用 6 大类 × 25 二级意图的对话意图体系
// 本映射表将前端 35 型正典意图映射到内核的一级 + 二级意图

export type KernelPrimaryIntent = 'query' | 'analysis' | 'trade' | 'strategy' | 'risk' | 'dialog';
export type KernelRiskLevel = 'low' | 'medium' | 'high';

export interface KernelIntentMapping {
  primary: KernelPrimaryIntent;
  secondary: string;
  risk_level: KernelRiskLevel;
  capability_route: string;
}

/**
 * 前端 35 型正典 → 内核 6×30 对话意图映射
 * 用于前端识别后将结果传递给内核能力路由
 */
export const CANON_TO_KERNEL: Record<IntentCanon, KernelIntentMapping> = {
  // ===== query 类（低风险） =====
  market_query: { primary: 'query', secondary: 'market_query', risk_level: 'low', capability_route: 'database' },
  simple_qa: { primary: 'query', secondary: 'market_query', risk_level: 'low', capability_route: 'direct_response' },
  credits_query: { primary: 'query', secondary: 'account_query', risk_level: 'low', capability_route: 'database' },
  artifact_query: { primary: 'query', secondary: 'order_query', risk_level: 'low', capability_route: 'index_system' },
  concept_explain: { primary: 'query', secondary: 'market_query', risk_level: 'low', capability_route: 'knowledge_base' },

  // ===== analysis 类（中风险） =====
  deep_analysis: { primary: 'analysis', secondary: 'deep_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  scenario_sim: { primary: 'analysis', secondary: 'deep_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  triple_chain: { primary: 'analysis', secondary: 'three_screen_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  asset_comparison: { primary: 'analysis', secondary: 'sector_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  entry_timing: { primary: 'analysis', secondary: 'technical_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  exit_timing: { primary: 'analysis', secondary: 'holding_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  market_sentiment: { primary: 'analysis', secondary: 'sector_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  trend_analysis: { primary: 'analysis', secondary: 'technical_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  technical_signal: { primary: 'analysis', secondary: 'technical_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  support_resistance: { primary: 'analysis', secondary: 'technical_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  event_analysis: { primary: 'analysis', secondary: 'deep_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  volatility_analysis: { primary: 'analysis', secondary: 'technical_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  macro_analysis: { primary: 'analysis', secondary: 'sector_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },
  backtest_help: { primary: 'analysis', secondary: 'deep_analysis', risk_level: 'medium', capability_route: 'trading_nodes' },

  // ===== trade 类（高风险） =====
  execute_trade: { primary: 'trade', secondary: 'buy', risk_level: 'high', capability_route: 'trading_nodes' },
  dca_strategy: { primary: 'trade', secondary: 'conditional_order', risk_level: 'high', capability_route: 'trading_nodes' },
  portfolio_rebalance: { primary: 'trade', secondary: 'close_position', risk_level: 'high', capability_route: 'trading_nodes' },
  arbitrage_opportunity: { primary: 'trade', secondary: 'buy', risk_level: 'high', capability_route: 'trading_nodes' },
  sector_rotation: { primary: 'trade', secondary: 'buy', risk_level: 'high', capability_route: 'trading_nodes' },

  // ===== strategy 类（中风险） =====
  strategy_verify: { primary: 'strategy', secondary: 'strategy_optimization', risk_level: 'medium', capability_route: 'trading_nodes' },
  strategy_recommendation: { primary: 'strategy', secondary: 'stock_recommendation', risk_level: 'medium', capability_route: 'trading_nodes' },
  portfolio_allocation: { primary: 'strategy', secondary: 'stock_recommendation', risk_level: 'medium', capability_route: 'trading_nodes' },
  position_sizing: { primary: 'strategy', secondary: 'stock_recommendation', risk_level: 'medium', capability_route: 'trading_nodes' },

  // ===== risk 类（中风险） =====
  risk_alert_response: { primary: 'risk', secondary: 'risk_advice', risk_level: 'medium', capability_route: 'trading_nodes' },
  risk_analysis: { primary: 'risk', secondary: 'risk_assessment', risk_level: 'medium', capability_route: 'trading_nodes' },

  // ===== dialog 类（低风险） =====
  command: { primary: 'dialog', secondary: 'chitchat', risk_level: 'low', capability_route: 'direct_response' },
  system_config: { primary: 'dialog', secondary: 'modify', risk_level: 'low', capability_route: 'direct_response' },
  need_clarification: { primary: 'dialog', secondary: 'clarify', risk_level: 'low', capability_route: 'direct_response' },
  clarification_result: { primary: 'dialog', secondary: 'confirm', risk_level: 'low', capability_route: 'direct_response' },
  developer: { primary: 'dialog', secondary: 'clarify', risk_level: 'low', capability_route: 'harness' },
};

/** 前端正典意图 → 内核对话意图映射 */
export function canonToKernel(intent: IntentCanon): KernelIntentMapping {
  return CANON_TO_KERNEL[intent] ?? { primary: 'query', secondary: 'market_query', risk_level: 'low', capability_route: 'direct_response' };
}

// ============ 统一意图识别结果 ============

/**
 * 识别路径可观测标记：
 *   rule      — 命令快路径/正则规则（零 LLM）
 *   fc        — LLM Function Calling 结构化识别
 *   llm       — 传统 LLM JSON 识别
 *   follow_up — 追问继承
 *   default   — 兜底默认
 */
export type IntentMethod = 'rule' | 'fc' | 'llm' | 'follow_up' | 'default';

/**
 * 统一意图识别结果（扩展兼容 fallback-engine IntentRecognitionResult 形状）。
 * Phase 2/3 各链适配器返回此类型，调用方按需降级为各自视图。
 */
export interface UnifiedIntentResult {
  intent: IntentCanon;
  confidence: number;
  entities: Record<string, string>;
  complexity: 'simple' | 'moderate' | 'complex' | 'urgent';
  reasoning: string;
  method: IntentMethod;
  context_aware: boolean;
  loop: IntentLoop;
  /** 角色门禁查询结果（草案期仅记录，不拦截） */
  gate: { role: UserRole; allowed: boolean };
  /** 修复级联审计：记录 FC 解析修复动作（Phase 2） */
  repair_applied?: string[];
  matchedPatternId?: string;
  clarification_options?: Array<{
    key: string;
    label: string;
    target_intent: IntentCanon;
    entities?: Record<string, string>;
  }>;
  clarification_question?: string;
}

// ============ 6. DreamOS 双向映射（35型↔7型 + 6×30→35型）============
// PROP-20260917 · 解决意图识别前后端一致性问题
// 后端 Python 镜像: 1-ARCHITECTURE/dream-harness-bridge/integration/canon_intent_bridge.py
// 测试同步: 1-ARCHITECTURE/dream-harness-bridge/integration/test_canon_intent_bridge.py

/**
 * DreamOS 交易能力域 7 型策略意图
 * 来源: 1-ARCHITECTURE/dreamos/capabilities/trading/strategy_types.py (StrategyIntent)
 */
export const DREAMOS_STRATEGY_TYPES = [
  'TREND_FOLLOWING',
  'MEAN_REVERSION',
  'FUNDAMENTAL_PLAY',
  'BREAKOUT',
  'KNOWLEDGE_MATCH',
  'DEEP_ANALYSIS',
  'UNCERTAIN',
] as const;
export type DreamOSStrategy = typeof DREAMOS_STRATEGY_TYPES[number];

/**
 * 35 型正典 → 7 型策略意图（取最常见代表）
 * 多对一映射：多个 35 型可映射到同一 7 型
 * 反向映射会丢失信息，DREAMOS_TO_CANON 取代表 35 型
 */
export const CANON_TO_DREAMOS: Record<IntentCanon, DreamOSStrategy> = {
  // TREND_FOLLOWING: 趋势入场
  trend_analysis: 'TREND_FOLLOWING',
  entry_timing: 'TREND_FOLLOWING',
  // MEAN_REVERSION: 均值回归
  volatility_analysis: 'MEAN_REVERSION',
  // FUNDAMENTAL_PLAY: 基本面/事件驱动
  event_analysis: 'FUNDAMENTAL_PLAY',
  macro_analysis: 'FUNDAMENTAL_PLAY',
  sector_rotation: 'FUNDAMENTAL_PLAY',
  // BREAKOUT: 突破
  technical_signal: 'BREAKOUT',
  support_resistance: 'BREAKOUT',
  // KNOWLEDGE_MATCH: 知识问答
  simple_qa: 'KNOWLEDGE_MATCH',
  concept_explain: 'KNOWLEDGE_MATCH',
  // DEEP_ANALYSIS: 深度分析类
  deep_analysis: 'DEEP_ANALYSIS',
  triple_chain: 'DEEP_ANALYSIS',
  asset_comparison: 'DEEP_ANALYSIS',
  strategy_recommendation: 'DEEP_ANALYSIS',
  // UNCERTAIN: 无对应（系统级/对话类）
  market_query: 'UNCERTAIN',
  scenario_sim: 'UNCERTAIN',
  strategy_verify: 'UNCERTAIN',
  execute_trade: 'UNCERTAIN',
  command: 'UNCERTAIN',
  system_config: 'UNCERTAIN',
  credits_query: 'UNCERTAIN',
  artifact_query: 'UNCERTAIN',
  risk_alert_response: 'UNCERTAIN',
  need_clarification: 'UNCERTAIN',
  clarification_result: 'UNCERTAIN',
  developer: 'UNCERTAIN',
  exit_timing: 'UNCERTAIN',
  risk_analysis: 'UNCERTAIN',
  position_sizing: 'UNCERTAIN',
  market_sentiment: 'UNCERTAIN',
  portfolio_allocation: 'UNCERTAIN',
  portfolio_rebalance: 'UNCERTAIN',
  backtest_help: 'UNCERTAIN',
  dca_strategy: 'UNCERTAIN',
  arbitrage_opportunity: 'UNCERTAIN',
};

/**
 * 7 型策略意图 → 35 型正典（取代表，反向映射）
 * 一对一映射：每个 7 型选一个最贴近的 35 型代表
 */
export const DREAMOS_TO_CANON: Record<DreamOSStrategy, IntentCanon> = {
  TREND_FOLLOWING: 'trend_analysis',
  MEAN_REVERSION: 'volatility_analysis',
  FUNDAMENTAL_PLAY: 'event_analysis',
  BREAKOUT: 'technical_signal',
  KNOWLEDGE_MATCH: 'concept_explain',
  DEEP_ANALYSIS: 'deep_analysis',
  UNCERTAIN: 'simple_qa',
};

/**
 * 6×30 二级意图 → 35 型正典（取代表，反向映射）
 * 来源: 1-ARCHITECTURE/dreamos/core/sense/dialogue_intent/taxonomy.py
 * 实际 6 大类共 30 个二级意图（5+5+6+4+4+6=30）
 */
export const KERNEL_TO_CANON: Record<string, IntentCanon> = {
  // query 查询类（5）
  market_query: 'market_query',
  holding_query: 'position_sizing',
  order_query: 'artifact_query',
  account_query: 'credits_query',
  market_overview: 'market_query',
  // analysis 分析类（5）
  technical_analysis: 'technical_signal',
  holding_analysis: 'exit_timing',
  deep_analysis: 'deep_analysis',
  three_screen_analysis: 'triple_chain',
  sector_analysis: 'asset_comparison',
  // trade 交易类（6）
  buy: 'execute_trade',
  add_position: 'execute_trade',
  sell: 'execute_trade',
  close_position: 'execute_trade',
  conditional_order: 'dca_strategy',
  order_manage: 'execute_trade',
  // strategy 策略类（4）
  stock_recommendation: 'strategy_recommendation',
  factor_screen: 'asset_comparison',
  strategy_design: 'strategy_recommendation',
  strategy_optimization: 'strategy_verify',
  // risk 风控类（4）
  risk_assessment: 'risk_analysis',
  risk_advice: 'risk_analysis',
  alert_setup: 'risk_alert_response',
  portfolio_risk: 'risk_analysis',
  // dialog 对话类（6）
  confirm: 'clarification_result',
  cancel: 'clarification_result',
  modify: 'system_config',
  repeat: 'simple_qa',
  clarify: 'need_clarification',
  chitchat: 'simple_qa',
};

/** 35 型正典 → 7 型策略意图（FAIL-OPEN：未知返回 UNCERTAIN） */
export function canonToDreamOS(intent: IntentCanon): DreamOSStrategy {
  return CANON_TO_DREAMOS[intent] ?? 'UNCERTAIN';
}

/** 7 型策略意图 → 35 型正典（FAIL-OPEN：未知返回 simple_qa） */
export function dreamOSToCanon(strategy: string): IntentCanon {
  return (DREAMOS_TO_CANON as Record<string, IntentCanon>)[strategy] ?? 'simple_qa';
}

/** 6×30 二级意图 → 35 型正典（FAIL-OPEN：未知返回 simple_qa） */
export function kernelToCanon(secondary: string): IntentCanon {
  return KERNEL_TO_CANON[secondary] ?? 'simple_qa';
}

/** 检查是否为合法的 7 型策略意图 */
export function isDreamOSStrategy(v: string): v is DreamOSStrategy {
  return (DREAMOS_STRATEGY_TYPES as readonly string[]).includes(v);
}
