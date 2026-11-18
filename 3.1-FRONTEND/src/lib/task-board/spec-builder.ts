/**
 * 任务 SPEC 构造器（意图识别后统一出 SPEC）。
 *
 * 规则：任何任务都必须出 SPEC，形式字段固定齐全；
 * 简单任务只缩调研深度与工具预算，不删字段。
 *
 * 复杂度的核心差异在于「调研采用多少工具与 SKILL」：
 *   quick    → 1~2 个 SKILL，工具预算 2
 *   standard → 3~5 个 SKILL，工具预算 6
 *   deep     → 全部匹配 + 方法论类 SKILL，工具预算 15
 */

import type { ComplexityLevel, IntentType } from "@/lib/planner/planner-types";
import type { SpecField, TaskSpec } from "@/types/task-board";

export interface SelectedSkill {
  id: string;
  name: string;
  category: string;
}

export interface ComplexityAssessment {
  level: ComplexityLevel;
  score: number;
  reasons: string[];
}

const INTENT_RULES: Array<{ intent: IntentType; pattern: RegExp }> = [
  { intent: "execute_trade", pattern: /下单|买入|卖出|清仓|加仓|减仓|调仓|开仓/ },
  { intent: "strategy_verify", pattern: /回测|验证|复盘|胜率|夏普|最大回撤|参数/ },
  { intent: "risk_alert", pattern: /风险|预警|告警|止损|敞口|爆仓/ },
  { intent: "scenario_sim", pattern: /情景|推演|假设|如果.*会怎样|压力测试/ },
  { intent: "deep_analysis", pattern: /分析|研究|调研|对比|估值|基本面|产业链/ },
  { intent: "market_query", pattern: /行情|价格|股价|多少钱|涨跌|走势|K线|成交量|盘口/ },
  { intent: "artifact_query", pattern: /报告|文档|知识库|历史记录|纪要/ },
  { intent: "credits_query", pattern: /积分|余额|额度/ },
  { intent: "system_config", pattern: /配置|设置|开关|权限/ },
];

/** 轻量意图分类：L1 未命中时给 SPEC 一个可用分类，不冒充高置信结果 */
export function inferIntent(text: string): IntentType {
  const value = text.trim();
  for (const rule of INTENT_RULES) {
    if (rule.pattern.test(value)) return rule.intent;
  }
  return "simple_qa";
}

const DEEP_SIGNALS: Array<{ pattern: RegExp; reason: string }> = [
  { pattern: /回测|验证|策略|参数|夏普|回撤/, reason: "涉及策略验证与统计口径" },
  { pattern: /对比|比较|筛选|排序|多只|组合/, reason: "涉及多标的对比" },
  { pattern: /产业链|上下游|宏观|政策|基本面|估值/, reason: "需要多源基本面数据" },
  { pattern: /报告|研报|纪要|输出文档/, reason: "需要产出结构化交付物" },
  { pattern: /然后|接着|再|并且|同时|分步/, reason: "包含多步骤依赖" },
];

const STANDARD_SIGNALS: Array<{ pattern: RegExp; reason: string }> = [
  { pattern: /为什么|原因|逻辑|怎么看|判断/, reason: "需要解释性推理" },
  { pattern: /最新|今天|近期|本周|本月/, reason: "需要时效性数据" },
  { pattern: /持仓|账户|资金|仓位/, reason: "涉及账户上下文" },
];

const INTENT_BASELINE: Record<IntentType, ComplexityLevel> = {
  simple_qa: "quick",
  market_query: "quick",
  credits_query: "quick",
  artifact_query: "quick",
  system_config: "quick",
  deep_analysis: "deep",
  scenario_sim: "deep",
  strategy_verify: "deep",
  execute_trade: "standard",
  risk_alert: "standard",
  command: "quick",
};

/** 复杂度判定：规则可解释，结果直接决定调研深度与工具预算 */
export function assessComplexity(
  text: string,
  intent: IntentType,
): ComplexityAssessment {
  const value = text.trim();
  const reasons: string[] = [];
  let score = 0;

  if (value.length > 120) {
    score += 2;
    reasons.push("输入较长，包含多个约束");
  } else if (value.length > 40) {
    score += 1;
    reasons.push("输入包含较完整的需求描述");
  }

  for (const signal of DEEP_SIGNALS) {
    if (signal.pattern.test(value)) {
      score += 2;
      reasons.push(signal.reason);
    }
  }
  for (const signal of STANDARD_SIGNALS) {
    if (signal.pattern.test(value)) {
      score += 1;
      reasons.push(signal.reason);
    }
  }

  const baseline = INTENT_BASELINE[intent];
  if (baseline === "deep") {
    score += 2;
    reasons.push("意图本身需要深度调研");
  } else if (baseline === "standard") {
    score += 1;
  }

  const level: ComplexityLevel = score >= 4 ? "deep" : score >= 2 ? "standard" : "quick";
  return { level, score, reasons: [...new Set(reasons)] };
}

const TOOL_BUDGET: Record<ComplexityLevel, number> = {
  quick: 2,
  standard: 6,
  deep: 15,
};

const SKILL_LIMIT: Record<ComplexityLevel, number> = {
  quick: 2,
  standard: 5,
  deep: 12,
};

/** 需要多 Agent 择优的意图：深度分析 / 策略验证 / 情景推演 */
const BRAINSTORM_INTENTS: IntentType[] = [
  "deep_analysis",
  "strategy_verify",
  "scenario_sim",
];

/**
 * 是否启用多 Agent 择优脑暴。
 * 由复杂度与意图决定，并在 SPEC 中写明路数；轻量任务不跑（编排器成本高）。
 */
export function shouldBrainstorm(
  text: string,
  intent: IntentType,
  level: ComplexityLevel,
): { enabled: boolean; nPerSide: number } {
  if (level === "quick") return { enabled: false, nPerSide: 0 };
  const explicit = /方案|择优|脑暴|对比|哪个更好|选哪个/.test(text);
  if (level === "deep" && (BRAINSTORM_INTENTS.includes(intent) || explicit)) {
    return { enabled: true, nPerSide: 3 };
  }
  if (explicit) return { enabled: true, nPerSide: 2 };
  return { enabled: false, nPerSide: 0 };
}

const DEPTH_LABEL: Record<ComplexityLevel, string> = {  quick: "轻量（直接回答，必要时一次数据核查）",
  standard: "标准（多步核查，交叉验证关键结论）",
  deep: "深度（多源调研 + 方法论 SKILL，产出可复核证据）",
};

function stepsFor(level: ComplexityLevel): string[] {
  const base = ["确认目标与验收口径", "识别所需数据与工具"];
  if (level === "quick") {
    return [...base, "执行一次必要核查", "给出结论与依据"];
  }
  const standard = [...base, "调用匹配 SKILL 取证", "交叉验证关键结论", "输出结论与风险"];
  if (level === "standard") return standard;
  return [
    ...standard,
    "补充反向证据与失效边界",
    "形成可复核交付物",
  ];
}

function acceptanceFor(level: ComplexityLevel): string {
  if (level === "quick") return "结论有明确依据，不出现无来源数字";
  if (level === "standard") return "关键结论至少两个来源一致；不确定项显式标注";
  return "每个结论可追溯到证据；给出反例、失效条件与适用边界";
}

/**
 * 构造任务 SPEC。字段固定十项，任何深度都不缺项。
 */
export function buildTaskSpec({
  taskId,
  text,
  intent,
  skills,
  assessment,
}: {
  taskId: string;
  text: string;
  intent: IntentType;
  skills: SelectedSkill[];
  assessment?: ComplexityAssessment;
}): TaskSpec {
  const complexity = assessment ?? assessComplexity(text, intent);
  const budget = TOOL_BUDGET[complexity.level];
  const limit = SKILL_LIMIT[complexity.level];
  const picked = skills.slice(0, limit);
  const raw = text.trim().slice(0, 200);
  const brainstorm = shouldBrainstorm(text, intent, complexity.level);

  const fields: SpecField[] = [
    { key: "objective", label: "目标", value: raw || "未提供输入" },
    {
      key: "intent",
      label: "意图分类",
      value: `${intent}（${
        INTENT_BASELINE[intent] === "deep"
          ? "默认深度调研"
          : INTENT_BASELINE[intent] === "standard"
            ? "默认标准调研"
            : "默认轻量"
      }）`,
    },
    {
      key: "complexity",
      label: "复杂度与调研深度",
      value: `${complexity.level}（评分 ${complexity.score}）· ${DEPTH_LABEL[complexity.level]}${
        complexity.reasons.length ? `；依据：${complexity.reasons.join("；")}` : ""
      }`,
    },
    {
      key: "scope",
      label: "范围",
      value:
        complexity.level === "quick"
          ? `纳入：${raw || "当前问题"}；排除：与问题无关的历史背景与扩展分析`
          : `纳入：${raw || "当前任务"} 及其直接依赖；排除：未要求的交易执行与配置变更`,
    },
    {
      key: "tools",
      label: "调研工具与预算",
      value: `最多 ${budget} 次工具调用；${
        complexity.level === "quick"
          ? "仅允许只读行情/单点查询"
          : complexity.level === "standard"
            ? "允许行情 + 基本面 + 事件数据"
            : "允许行情、基本面、事件、逆向解析与外部检索"
      }`,
    },
    {
      key: "skills",
      label: "选用 SKILL",
      value:
        picked.length > 0
          ? picked.map((skill) => `${skill.name}（${skill.id}）`).join("；")
          : "注册表中暂无匹配 SKILL，按通用调研流程执行",
    },
    {
      key: "brainstorm",
      label: "多 Agent 择优脑暴",
      value: brainstorm.enabled
        ? `启用（${brainstorm.nPerSide} 路/侧），先分叉再评审收敛；结果计入证据`
        : "不启用（轻量任务直接取证，避免高成本编排）",
    },
    {
      key: "steps",
      label: "执行步骤",
      value: stepsFor(complexity.level).join(" → "),
    },
    {
      key: "acceptance",
      label: "验收标准",
      value: acceptanceFor(complexity.level),
    },
    {
      key: "deliverable",
      label: "交付物",
      value:
        complexity.level === "deep"
          ? "结论 + 证据清单 + 风险与失效边界"
          : "结论 + 关键依据",
    },
    {
      key: "risks",
      label: "风险与约束",
      value:
        complexity.level === "quick"
          ? "数据时效性未验证时需标注；不得虚构数值"
          : "数据缺口、口径差异、样本偏差需显式标注；不得以猜测替代证据",
    },
  ];

  return {
    spec_id: `${taskId}:v1`,
    version: 1,
    status: "draft",
    fields,
  };
}
