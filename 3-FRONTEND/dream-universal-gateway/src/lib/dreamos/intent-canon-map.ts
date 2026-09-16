/**
 * intent-canon-map.ts — 意图正典 → DreamOS 编排指令映射表（S4）
 * P0 正典对齐 · 20260829-bridge
 *
 * 职责：以 intent-schema.ts 的 35 型正典（PROP-20260828B SSoT）为唯一键源，
 *   声明哪些网关意图可进入 DreamOS 物理编排，以及映射到哪个 DreamOS IntentType。
 *
 * 对齐原则（保守可审计）：
 *   1. 仅 intelligence 环分析型意图过桥；execution 环（execute_trade/dca_strategy）
 *      与 governance 环意图一律不过桥（执行链人工审批门禁不变）。
 *   2. DreamOS IntentType 是策略型枚举（6 型），与网关分析型正典不同体系：
 *      有明确策略语义的做显式映射（如 trend_analysis→TREND_FOLLOWING），
 *      其余落 UNCERTAIN —— user_input 仍传入规划器，行为等价于现状但省去
 *      S 层 LLM 识别耗时（54s 痛点主因）。
 *   3. 网关正典原名始终随 canon_intent 字段透传，供下游观测与映射迭代。
 *
 * 纪律：新增键必须先在 intent-schema.ts 登记（IntentCanon 类型约束编译期强制）。
 */
import type { IntentCanon } from "@/lib/intent/intent-schema";

/** DreamOS IntentType 枚举值（与 1-ARCHITECTURE/dreamos/core/sense/types.py 对齐） */
export type DreamOSIntentType =
  | "TREND_FOLLOWING"
  | "MEAN_REVERSION"
  | "FUNDAMENTAL_PLAY"
  | "BREAKOUT"
  | "KNOWLEDGE_MATCH"
  | "UNCERTAIN";

interface CanonSpec {
  /** 映射到 DreamOS 策略意图；缺省 = UNCERTAIN */
  dreamos_intent?: DreamOSIntentType;
  /** 建议主链（A/C/F），缺省由 DreamOS 规划器自决 */
  chain?: string;
  note: string;
}

/** intelligence 环 · 可过桥意图映射表 */
const ELIGIBLE: Partial<Record<IntentCanon, CanonSpec>> = {
  // 显式策略映射
  trend_analysis: { dreamos_intent: "TREND_FOLLOWING", chain: "A", note: "趋势分析→趋势跟随链" },

  // 分析型（落 UNCERTAIN，user_input 驱动规划）
  market_query: { note: "行情查询" },
  deep_analysis: { chain: "A", note: "深度分析→A 链编排" },
  scenario_sim: { chain: "A", note: "情景模拟" },
  strategy_verify: { chain: "A", note: "策略验证" },
  technical_signal: { note: "技术信号分析" },
  support_resistance: { note: "支撑/阻力位" },
  volatility_analysis: { note: "波动率分析" },
  market_sentiment: { note: "市场情绪" },
  macro_analysis: { note: "宏观分析" },
  entry_timing: { chain: "A", note: "入场时机" },
  exit_timing: { chain: "A", note: "离场时机" },
  risk_analysis: { note: "风险分析" },
  position_sizing: { note: "仓位 sizing" },
  portfolio_allocation: { note: "组合配置" },
  portfolio_rebalance: { note: "组合再平衡" },
  strategy_recommendation: { note: "策略推荐" },
  backtest_help: { note: "回测辅助" },
  event_analysis: { note: "事件分析" },
  sector_rotation: { note: "板块轮动" },
  arbitrage_opportunity: { note: "套利机会" },
  asset_comparison: { note: "资产对比" },
};

export interface DreamOSDirective {
  intent_type: DreamOSIntentType;
  confidence: number;
  chain?: string;
  canon_intent: IntentCanon;
  note: string;
}

/**
 * 查询正典意图的 DreamOS 指令。
 * @returns 不可过桥（未登记/执行环/治理环）返回 null
 */
export function lookupDreamOSDirective(
  intent: string,
  confidence = 0.85,
): DreamOSDirective | null {
  const spec = ELIGIBLE[intent as IntentCanon];
  if (!spec) return null;
  return {
    intent_type: spec.dreamos_intent ?? "UNCERTAIN",
    confidence,
    chain: spec.chain,
    canon_intent: intent as IntentCanon,
    note: spec.note,
  };
}

/** 全部可过桥正典意图（供运维面板/文档生成） */
export function listDreamOSEligibleIntents(): IntentCanon[] {
  return Object.keys(ELIGIBLE) as IntentCanon[];
}
