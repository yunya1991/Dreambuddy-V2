/**
 * 模型分层注册表（DESIGN §十二）。
 *
 * 三类模型按职责分工，而不是按价格分工：
 * - judge  判定：意图识别、OKR 验收（小、快、结构化、低温度）
 * - worker 生产：派工、聚合、辩论、简报研报（强推理、可调工具）
 * - gate   门禁：五道门的机器预审（独立供应商、只读、无工具、temperature=0）
 *
 * 硬约束：gate 必须与所有 worker / judge 异构；gate 不得拥有任何能力授权。
 * 校验失败时：生产环境拒绝启动；开发环境降级为「门禁只有人工确认」。
 */

export type ModelClass = "judge" | "worker" | "gate";

export interface ModelSpec {
  /** `${provider}:${model}`，用于会签去重 */
  id: string;
  class: ModelClass;
  provider: string;
  family: string;
  model: string;
  temperature: number;
  allowedCapabilities: string[];
  enabled: boolean;
}

export interface ModelRegistry {
  worker: ModelSpec | null;
  judge: ModelSpec | null;
  /** 主门禁模型（如 Qwen） */
  gate: ModelSpec | null;
  /** 第二门禁模型（如 JEV），用于异构会签 */
  gate_secondary: ModelSpec | null;
}

export interface RegistryIssue {
  level: "error" | "warning";
  code: string;
  message: string;
}

type EnvLike = Record<string, string | undefined>;

const FAMILY_PATTERNS: Array<[RegExp, string]> = [
  [/jev|typesafe/i, "typesafe"],
  [/qwen|tongyi|dashscope/i, "alibaba"],
  [/deepseek/i, "deepseek"],
  [/kimi|moonshot/i, "moonshot"],
  [/claude|anthropic/i, "anthropic"],
  [/gemini|google/i, "google"],
  [/glm|zhipu|chatglm/i, "zhipu"],
  [/llama|meta/i, "meta"],
  [/mistral|mixtral/i, "mistral"],
  [/gpt|openai|^o[1-9]/i, "openai"],
];

/** 从模型名推断家族；用于异构判定，宁可保守也不把同族判成异族。 */
export function detectModelFamily(model: string): string {
  const name = (model || "").trim();
  for (const [pattern, family] of FAMILY_PATTERNS) {
    if (pattern.test(name)) return family;
  }
  return name.split(/[-_.:/]/)[0]?.toLowerCase() || "unknown";
}

function readSpec(
  cls: ModelClass,
  provider: string | undefined,
  model: string | undefined,
  temperature: number,
  allowedCapabilities: string[],
): ModelSpec | null {
  const safeModel = (model || "").trim();
  const safeProvider = (provider || "").trim();
  if (!safeModel || !safeProvider) return null;
  const family = detectModelFamily(safeModel);
  return {
    id: `${safeProvider}:${safeModel}`,
    class: cls,
    provider: safeProvider,
    family,
    model: safeModel,
    temperature,
    allowedCapabilities,
    enabled: true,
  };
}

/**
 * 从环境变量构建注册表。
 *
 * worker 复用现有 AGENT_* 变量，避免破坏既有对话链路；
 * judge / gate 必须显式配置，未配置即视为缺失（生产拒绝启动）。
 */
export function buildModelRegistry(env: EnvLike = process.env): ModelRegistry {
  const workerProvider = env.MODEL_WORKER_PROVIDER ?? env.AGENT_PROVIDER ?? "openai-compatible";
  const workerModel = env.MODEL_WORKER ?? env.AGENT_MODEL ?? "qwen-plus";

  return {
    worker: readSpec("worker", workerProvider, workerModel, 0.7, [
      "tools",
      "write_artifacts",
    ]),
    judge: readSpec(
      "judge",
      env.MODEL_JUDGE_PROVIDER ?? workerProvider,
      env.MODEL_JUDGE,
      0.1,
      [],
    ),
    gate: readSpec(
      "gate",
      env.MODEL_GATE_PROVIDER ?? "openai-compatible",
      env.MODEL_GATE,
      0,
      [],
    ),
    gate_secondary: readSpec(
      "gate",
      env.MODEL_GATE_SECONDARY_PROVIDER ?? "typesafe",
      env.MODEL_GATE_SECONDARY ?? env.TYPESAFE_DEFAULT_MODEL,
      0,
      [],
    ),
  };
}

/** 是否要求严格校验：生产默认严格，也可用 GATE_STRICT_STARTUP=1 强制。 */
export function isStrictEnvironment(env: EnvLike = process.env): boolean {
  return env.NODE_ENV === "production" || env.GATE_STRICT_STARTUP === "1";
}

export function validateModelRegistry(
  registry: ModelRegistry,
  opts: { strict?: boolean } = {},
): RegistryIssue[] {
  const strict = opts.strict ?? isStrictEnvironment();
  const issues: RegistryIssue[] = [];
  const missing = (level: "error" | "warning", cls: ModelClass) =>
    issues.push({
      level,
      code: `missing_${cls}_model`,
      message: `未配置 ${cls} 类模型（对应 MODEL_${cls.toUpperCase()} 环境变量）`,
    });

  if (!registry.worker) missing(strict ? "error" : "warning", "worker");
  if (!registry.judge) missing(strict ? "error" : "warning", "judge");
  if (!registry.gate) missing(strict ? "error" : "warning", "gate");

  const gates = [registry.gate, registry.gate_secondary].filter(
    (spec): spec is ModelSpec => Boolean(spec),
  );

  for (const gate of gates) {
    if (gate.class !== "gate") {
      issues.push({
        level: "error",
        code: "gate_class_invalid",
        message: `门禁模型的 class 必须为 gate（${gate.id}）`,
      });
    }
    if (gate.temperature !== 0) {
      issues.push({
        level: "error",
        code: "gate_temperature_nonzero",
        message: `门禁模型 temperature 必须为 0（${gate.id}）`,
      });
    }
    if (gate.allowedCapabilities.length > 0) {
      issues.push({
        level: "error",
        code: "gate_has_capabilities",
        message: `门禁模型只读，allowedCapabilities 必须为空（${gate.id}）`,
      });
    }
    if (!gate.enabled) {
      issues.push({
        level: strict ? "error" : "warning",
        code: "gate_disabled",
        message: `门禁模型未启用（${gate.id}），该票将不可用`,
      });
    }

    for (const other of [registry.worker, registry.judge]) {
      if (!other) continue;
      if (other.id === gate.id) {
        issues.push({
          level: "error",
          code: "gate_not_isolated",
          message: `门禁模型与 ${other.class} 模型相同（${gate.id}），违反模型级 SoD`,
        });
        continue;
      }
      if (other.provider === gate.provider && other.family === gate.family) {
        issues.push({
          level: "error",
          code: "gate_not_heterogeneous",
          message: `门禁模型与 ${other.class} 模型同源（${gate.provider}/${gate.family}），会签将失去独立性`,
        });
      }
    }
  }

  if (!registry.gate_secondary) {
    issues.push({
      level: "warning",
      code: "missing_gate_secondary",
      message: "未配置第二门禁模型，高风险门将退化为「单模型预审 + 人工确认」",
    });
  }

  const primary = registry.gate;
  const secondary = registry.gate_secondary;
  if (primary && secondary) {
    if (primary.id === secondary.id) {
      issues.push({
        level: "error",
        code: "gate_secondary_not_isolated",
        message: `主副门禁模型相同（${primary.id}），会签失去意义`,
      });
    } else if (
      primary.provider === secondary.provider &&
      primary.family === secondary.family
    ) {
      issues.push({
        level: "error",
        code: "gate_secondary_not_heterogeneous",
        message: `主副门禁模型同源（${primary.provider}/${primary.family}），会签失去独立性`,
      });
    }
  }

  return issues;
}

export function assertModelRegistry(
  registry: ModelRegistry,
  opts: { strict?: boolean } = {},
): void {
  const strict = opts.strict ?? isStrictEnvironment();
  const issues = validateModelRegistry(registry, { strict });
  const errors = issues.filter((issue) => issue.level === "error");
  if (strict && errors.length > 0) {
    throw new Error(
      `模型注册表校验失败：\n${errors.map((e) => `- [${e.code}] ${e.message}`).join("\n")}`,
    );
  }
}

let cached: ModelRegistry | null = null;

export function getModelRegistry(): ModelRegistry {
  cached ??= buildModelRegistry();
  return cached;
}

/** 仅测试使用：清空进程缓存 */
export function resetModelRegistryForTest(): void {
  cached = null;
}
