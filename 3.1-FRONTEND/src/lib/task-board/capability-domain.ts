/**
 * 能力域注册表（A 层 KR 归属的最小实现）。
 *
 * 字段集直接对齐 superpowers skill manifest：
 *   name / description / capabilities / acceptance / evidence_types / version
 * 不另造一套元数据，后续注册（T4）只需往 DOMAINS 里加条目或从 skill 目录导入。
 *
 * 原则：域内的 capabilities 必须是 capability-registry 中真实存在的只读能力；
 * 匹配不到 = 能力缺口，宁可不派发，也不临时猜。
 */

import type { IntentType } from "@/lib/planner/planner-types";

export interface CapabilityDomain {
  /** manifest name（唯一显示名） */
  name: string;
  description: string;
  /** 能力清单（capability-registry 的 id） */
  capabilities: string[];
  /** 验收口径 */
  acceptance: string;
  /** 可接受的证据类型 */
  evidence_types: string[];
  version: string;
}

export const DOMAINS: Record<string, CapabilityDomain> = {
  "domain:market_data": {
    name: "market-data",
    description: "行情、K 线与技术指标的只读取证",
    capabilities: [
      "market.price",
      "market.series",
      "market.technical_indicator",
      "news.listing",
    ],
    acceptance: "每个数值都能回溯到工具返回，且标注数据时效",
    evidence_types: ["tool_result", "quote_snapshot"],
    version: "1.0.0",
  },
  "domain:fundamental": {
    name: "fundamental-data",
    description: "宏观、基本面与链上数据的只读取证",
    capabilities: [
      "data.macro_snapshot",
      "data.fundamental_snapshot",
      "data.onchain_cycle",
    ],
    acceptance: "口径与统计区间明确，缺数据显式标注而非补零",
    evidence_types: ["tool_result", "dataset_snapshot"],
    version: "1.0.0",
  },
  "domain:analysis": {
    name: "evidence-analysis",
    description: "多源证据交叉验证与解释性分析",
    capabilities: [
      "analysis.data_insight",
      "analysis.contradiction",
      "dsh.technical",
      "dsh.macro",
      "dsh.sentiment",
      "dsh.valuation",
      "chart.visual_capabilities",
    ],
    acceptance: "结论必须引用证据；冲突点单列，不得以单一口径掩盖分歧",
    evidence_types: ["tool_result", "cross_validation", "chart"],
    version: "1.0.0",
  },
  "domain:strategy": {
    name: "strategy-verification",
    description: "策略回测、筛选与风险口径验证",
    capabilities: [
      "trading.backtest",
      "trading.screen_first",
      "trading.exit_review",
      "trading.analysis_pipeline",
      "dsh.risk",
    ],
    acceptance: "必须给出统计口径与样本区间；策略类结论需 U2 及以上证据",
    evidence_types: ["backtest_report", "tool_result", "risk_report"],
    version: "1.0.0",
  },
  "domain:general": {
    name: "general-delivery",
    description: "文档、配置与轻量问答的通用交付",
    capabilities: ["analysis.data_insight"],
    acceptance: "结论与关键依据成对出现，无法验证的部分标注 pending",
    evidence_types: ["document", "tool_result"],
    version: "1.0.0",
  },
};

/** 能力域 ID 列表（用于完整性校验） */
export function domainIds(): string[] {
  return Object.keys(DOMAINS);
}

export function getDomain(domainId: string): CapabilityDomain | undefined {
  return DOMAINS[domainId];
}

/** 按能力 ID 反查所属能力域；未注册返回 null */
export function matchDomainForCapability(capabilityId: string): string | null {
  for (const [id, domain] of Object.entries(DOMAINS)) {
    if (domain.capabilities.includes(capabilityId)) return id;
  }
  return null;
}

const INTENT_DOMAIN: Record<IntentType, string> = {
  market_query: "domain:market_data",
  deep_analysis: "domain:analysis",
  scenario_sim: "domain:analysis",
  strategy_verify: "domain:strategy",
  execute_trade: "domain:strategy",
  risk_alert: "domain:strategy",
  artifact_query: "domain:general",
  simple_qa: "domain:general",
  credits_query: "domain:general",
  system_config: "domain:general",
  command: "domain:general",
};

/** 意图 → 默认能力域；未知意图落入通用域（仍然可校验） */
export function resolveDomainForIntent(intent: IntentType): string {
  return INTENT_DOMAIN[intent] ?? "domain:general";
}
