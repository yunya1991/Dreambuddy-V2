/**
 * Agent 对话的提示词与循环参数（单一来源）。
 *
 * 路由与离线评测共用本模块，避免「评测跑一套 prompt、线上跑另一套」的漂移。
 */
import { CAPABILITY_PROMPT } from "./capability-tools";
import { profileSystemPrompt, type ToolProfileSpec } from "./tool-profiles";

export const CHAT_BASE_PROMPT = [
  "你是 DreamBuddy 内置协议层的对话助手。",
  "你只可使用已注册的工具回答；工具结果须如实引用，不得编造数字或行情。",
  "你具备只读分析能力（取数、多维度分析、矛盾裁决、历史回测），但没有下单、写库、改配置权限。",
  CAPABILITY_PROMPT,
].join("\n");

function readNumber(value: string | undefined, fallback: number, min: number, max: number): number {
  const parsed = Number(value);
  if (!Number.isFinite(parsed)) return fallback;
  return Math.min(max, Math.max(min, parsed));
}

/** 工具选择/参数填充需要低随机性；可用 AGENT_TEMPERATURE 覆盖。 */
export const AGENT_TEMPERATURE = readNumber(
  process.env.AGENT_TEMPERATURE,
  0.15,
  0,
  1,
);

/** 多跳任务需要比 5 步更多的预算；可用 AGENT_MAX_STEPS 覆盖（上限 12）。 */
export const AGENT_MAX_STEPS = Math.round(
  readNumber(process.env.AGENT_MAX_STEPS, 8, 1, 12),
);

/**
 * 单步最大输出 token。不显式下发时用上游默认值（DeepSeek 为 4096），
 * 长回答会被静默截断表现为「输出到一半就停了」；可用 AGENT_MAX_OUTPUT_TOKENS 覆盖。
 * 注意推理模型的 reasoning tokens 也占用该额度。
 */
export const AGENT_MAX_OUTPUT_TOKENS = Math.round(
  readNumber(process.env.AGENT_MAX_OUTPUT_TOKENS, 16384, 512, 32768),
);

export function buildChatSystem(
  profile: ToolProfileSpec,
  extra: Array<string | null | undefined> = [],
): string {
  return [CHAT_BASE_PROMPT, profileSystemPrompt(profile), ...extra]
    .filter(Boolean)
    .join("\n");
}

export type StepVerdict = "pass" | "fail" | "unknown";

/**
 * 步评审判定解析：只认「PASS/FAIL 开头」或结构化 JSON，
 * 不再用宽松正则扫全文（旧实现会把「PASS：无 FAIL 项」误判为 fail）。
 * 无法解析 → unknown，由调用方按 FAIL-OPEN 放行。
 */
export function parseStepVerdict(raw: string): StepVerdict {
  const text = (raw ?? "").trim();
  if (!text) return "unknown";

  const jsonText = text.match(/\{[\s\S]*\}/)?.[0];
  if (jsonText) {
    try {
      const verdict = String(
        (JSON.parse(jsonText) as { verdict?: unknown }).verdict ?? "",
      ).toLowerCase();
      if (verdict === "pass" || verdict === "通过") return "pass";
      if (verdict === "fail" || verdict === "不通过") return "fail";
    } catch {
      // 非 JSON，继续按前缀判断
    }
  }

  if (/^PASS\b/i.test(text) || /^通过[：:\s]/.test(text)) return "pass";
  if (/^FAIL\b/i.test(text) || /^不通过[：:\s]/.test(text)) return "fail";
  return "unknown";
}
