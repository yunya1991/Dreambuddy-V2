/**
 * S 层拆解器（S2）：SPEC → TaskObjective + OkrNode[]。
 *
 * 双策略（DECOMPOSE_STRATEGY=A/B 对比后定默认，保留开关）：
 * - deterministic：基于意图模板 + 复杂度确定 KR 数量，零 token、可复现；
 * - llm：调用 /api/agent/plan 产出的 PlanCard，按能力域归并为 KR。
 *
 * 硬约束：
 * - deep 2–5 个 KR / standard 2–3 个 / quick 1 个且不进入 A 派发；
 * - 每个 KR 必须带 criteria / verify / owner_domain / capability_ids；
 * - 拆解失败一律 FAIL-OPEN 降级为确定性模板，并标记 degraded；
 * - 拆解的 model 与执行、验收模型三元互异，写入结果供审计。
 */

import type { ComplexityLevel, IntentType } from "@/lib/planner/planner-types";
import type { OkrNode, TaskObjective, VerifyKind } from "@/types/task-board";
import type { PlanCard } from "@/lib/agent/plancard";
import { DOMAINS, getDomain, resolveDomainForIntent } from "./capability-domain";

export type DecomposeStrategy = "deterministic" | "llm";

/** 验收置信度阈值默认值；全局配置 AGENT_VERIFY_CONFIDENCE_THRESHOLD 可覆盖 */
export const DEFAULT_VERIFY_CONFIDENCE_THRESHOLD = 0.7;

export interface DecomposeInput {
  taskId: string;
  text: string;
  intent: IntentType;
  level: ComplexityLevel;
  /** 复杂度评分（门禁边界判定用，不参与 KR 数量模板） */
  score?: number;
  skills?: Array<{ id: string; name: string }>;
}

export interface DecomposeDeps {
  /** LLM 策略：注入 PlanCard 生成器（测试可替换，生产走 /api/agent/plan） */
  planCard?: (input: {
    intent: IntentType;
    text: string;
  }) => Promise<PlanCard | null>;
}

export interface DecomposeResult {
  objective: TaskObjective;
  krs: OkrNode[];
  strategy: DecomposeStrategy;
  /** 拆解模型标识（与执行/验收模型三元互异） */
  model: string;
  degraded: boolean;
  /** quick 任务不进入 A 派发，直接回答 */
  skip_dispatch: boolean;
}

const KR_CAPS: Record<ComplexityLevel, { min: number; max: number }> = {
  quick: { min: 1, max: 1 },
  standard: { min: 2, max: 3 },
  deep: { min: 2, max: 5 },
};

const KR_TEMPLATES: Record<IntentType, string[]> = {
  market_query: ["获取行情与必要指标", "核对数据时效与口径"],
  deep_analysis: ["收集数据与证据", "交叉验证关键结论", "形成结论与失效边界"],
  scenario_sim: ["设定情景假设", "推演路径与影响", "输出情景结论"],
  strategy_verify: [
    "明确策略与统计口径",
    "执行回测或沙箱取证",
    "检查统计显著性与稳健性",
  ],
  execute_trade: ["核对账户与持仓", "确认交易约束与风控", "生成执行建议（不落单）"],
  risk_alert: ["识别风险敞口", "核对风控阈值", "输出预警与处置建议"],
  artifact_query: ["定位所需文档与记录", "提取关键依据"],
  simple_qa: ["直接回答并给出依据"],
  credits_query: ["查询积分与额度"],
  system_config: ["核对当前配置", "给出变更建议"],
  command: ["解析命令意图", "执行只读检查"],
};

/** 模板不足下限时补齐用（不引入新语义，只扩步骤） */
const GENERIC_TITLES = ["补充证据与数据校验", "输出结论与风险提示"];

const ACCEPTANCE_BY_INTENT: Record<IntentType, string> = {
  market_query: "行情数值可回溯到工具返回，且标注数据时效",
  deep_analysis: "每个结论都有证据引用；冲突点单列而非抹平",
  scenario_sim: "情景假设、参数与结论一一对应，失效条件明确",
  strategy_verify: "给出统计口径、样本区间与显著性结论",
  execute_trade: "交易约束与风控校验齐全，且不产生真实下单",
  risk_alert: "风险敞口与阈值可复核，处置建议可执行",
  artifact_query: "引用的文档与片段可定位",
  simple_qa: "回答覆盖问题要点，无法验证处标注 pending",
  credits_query: "积分与额度来自真实查询结果",
  system_config: "配置项与影响范围一致",
  command: "命令解析与只读检查结果一致",
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

/** 读取拆解策略；非法值回落到确定性策略（不因配置错误阻断链路） */
export function readDecomposeStrategy(
  env: Record<string, string | undefined> = process.env,
): DecomposeStrategy {
  const raw = (env.DECOMPOSE_STRATEGY || "").trim().toLowerCase();
  return raw === "llm" ? "llm" : "deterministic";
}

/** 验收置信度阈值：全局配置，非法/越界回落默认值 */
export function readVerifyThreshold(
  env: Record<string, string | undefined> = process.env,
): number {
  const raw = (env.AGENT_VERIFY_CONFIDENCE_THRESHOLD || "").trim();
  if (!raw) return DEFAULT_VERIFY_CONFIDENCE_THRESHOLD;
  const parsed = Number(raw);
  if (!Number.isFinite(parsed)) return DEFAULT_VERIFY_CONFIDENCE_THRESHOLD;
  return clamp(parsed, 0, 1);
}

function verdictLevelFor(intent: IntentType, level: ComplexityLevel): "U0" | "U1" | "U2" | "U3" {
  if (intent === "strategy_verify" || intent === "execute_trade" || intent === "risk_alert") {
    return "U2";
  }
  if (level === "deep") return "U1";
  return "U0";
}

function verifyFor(level: ComplexityLevel): VerifyKind {
  return level === "quick" ? "c_action" : "evidence_backed";
}

/** 按复杂度上下限裁剪/补齐 KR 标题；补齐只扩步骤，不改判据 */
function fitKrTitles(titles: string[], level: ComplexityLevel): string[] {
  const cap = KR_CAPS[level];
  const picked = titles.slice(0, cap.max);
  const used = new Set(picked);
  for (const extra of GENERIC_TITLES) {
    if (picked.length >= cap.min) break;
    if (used.has(extra)) continue;
    used.add(extra);
    picked.push(extra);
  }
  return picked;
}

function buildKrs(
  input: DecomposeInput,
  titles: string[],
): OkrNode[] {
  const domainId = resolveDomainForIntent(input.intent);
  const domain = getDomain(domainId);
  const capabilityIds = domain ? domain.capabilities.slice(0, 3) : [];
  const verify = verifyFor(input.level);
  return titles.map((title, index) => {
    const nodeId = `kr-${index + 1}`;
    const kr: OkrNode = {
      node_id: nodeId,
      objective: title,
      criteria: `${ACCEPTANCE_BY_INTENT[input.intent]}；验收对象：${title}`,
      verify,
      owner: "a_layer:okr_owner",
      evidence_count: 0,
      verdict: "pending",
      owner_domain: domainId,
      owner_agent: domain ? `agent:${domain.name}` : undefined,
      capability_ids: capabilityIds,
    };
    // evidence_backed 必须有证据锚点，否则视为 OKR 不明确（T5 门禁会拦截）
    if (verify === "evidence_backed") {
      kr.evidence_id = `kr-evidence:${input.taskId}:${nodeId}`;
    }
    return kr;
  });
}

function buildObjective(input: DecomposeInput, krs: OkrNode[], env?: Record<string, string | undefined>): TaskObjective {
  return {
    title: input.text.trim().slice(0, 120) || "未命名任务",
    owner: "a_layer:okr_owner",
    mode: input.level === "deep" ? "supervise" : "judge",
    confidence_threshold: readVerifyThreshold(env),
    progress: 0,
    claims: krs.map((kr) => kr.objective),
    required_verdict_level: verdictLevelFor(input.intent, input.level),
    waiting_verdict: false,
  };
}

function deterministicDecompose(
  input: DecomposeInput,
  env?: Record<string, string | undefined>,
): DecomposeResult {
  const titles = fitKrTitles(KR_TEMPLATES[input.intent] ?? KR_TEMPLATES.simple_qa, input.level);
  const krs = buildKrs(input, titles);
  return {
    objective: buildObjective(input, krs, env),
    krs,
    strategy: "deterministic",
    model: "decomposer:deterministic",
    degraded: false,
    skip_dispatch: input.level === "quick",
  };
}

/** PlanCard 步骤 → 能力域：tool 后缀命中域内能力即归属该域，否则返回 null */
function inferDomainForTool(tool: string): string | null {
  const parts = tool.split(".");
  const tail = parts[parts.length - 1] ?? "";
  for (const [domainId, domain] of Object.entries(DOMAINS)) {
    if (domain.capabilities.some((cap) => cap.endsWith(`.${tail}`))) {
      return domainId;
    }
  }
  return null;
}

/** 把 PlanCard 的步骤按能力域归并为 KR 标题（连续同域合并，保留顺序） */
function mergePlanStepsByDomain(card: PlanCard): string[] {
  const titles: string[] = [];
  let lastDomain: string | null = null;
  for (const step of card.plan_steps) {
    const domainId = inferDomainForTool(step.tool);
    if (domainId && domainId === lastDomain && titles.length > 0) {
      // 同域连续步骤合并为一条 KR，避免拆得过碎
      continue;
    }
    lastDomain = domainId;
    const action = step.action.trim();
    if (action) titles.push(action);
  }
  return titles;
}

async function llmDecompose(
  input: DecomposeInput,
  deps: DecomposeDeps,
  env?: Record<string, string | undefined>,
): Promise<DecomposeResult | null> {
  if (!deps.planCard) return null;
  const card = await deps.planCard({ intent: input.intent, text: input.text });
  if (!card || card.plan_steps.length === 0) return null;
  const merged = mergePlanStepsByDomain(card);
  if (merged.length === 0) return null;
  const titles = fitKrTitles(merged, input.level);
  const krs = buildKrs(input, titles);
  return {
    objective: buildObjective(input, krs, env),
    krs,
    strategy: "llm",
    model: "decomposer:llm",
    degraded: false,
    skip_dispatch: input.level === "quick",
  };
}

/**
 * 拆解入口：按策略选择 P1/P2，失败一律降级为确定性模板。
 * quick 不调用 LLM（省成本且最终不派发）。
 */
export async function decomposeTask(
  input: DecomposeInput,
  deps: DecomposeDeps = {},
  env: Record<string, string | undefined> = process.env,
): Promise<DecomposeResult> {
  const strategy = readDecomposeStrategy(env);
  if (strategy === "llm" && input.level !== "quick") {
    try {
      const result = await llmDecompose(input, deps, env);
      if (result) return result;
    } catch (error) {
      console.warn(
        "[Decompose] LLM 拆解失败，降级为确定性模板:",
        error instanceof Error ? error.message : error,
      );
    }
    return { ...deterministicDecompose(input, env), degraded: true };
  }
  return deterministicDecompose(input, env);
}
