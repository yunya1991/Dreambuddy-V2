/**
 * 门禁模型适配器（DESIGN §11.8.4 / §十二）。
 *
 * 约束：
 * - 只读：输入只有证据摘要，不提供任何工具；
 * - temperature=0、固定 prompt 版本由注册表保证；
 * - 未配置模型、调用失败、输出不合 schema、结论为 pass 但仍有缺口
 *   → 一律降级为 needs_human，绝不默认放行。
 */

import type { GateKind } from "@/types/task-board";

export type GateVerdict = "pass" | "fail" | "needs_human";

export interface GateModelVerdict {
  verdict: GateVerdict;
  reasons: string[];
  evidence_refs: string[];
  missing: string[];
  /** 模型自报置信度；缺失为 null，不填 0 冒充 */
  confidence: number | null;
  model_id: string | null;
  degraded: boolean;
}

export interface GatePrecheckInput {
  gate_kind: GateKind;
  evidence_ref: string;
  /** 只放结构化摘要，不放原始长文本，降低提示注入面 */
  evidence: unknown;
}

export type GateModelCaller = (
  input: GatePrecheckInput,
) => Promise<unknown>;

export function needsHuman(
  reason: string,
  modelId: string | null = null,
): GateModelVerdict {
  return {
    verdict: "needs_human",
    reasons: [reason],
    evidence_refs: [],
    missing: [],
    confidence: null,
    model_id: modelId,
    degraded: true,
  };
}

function asStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .filter((item): item is string => typeof item === "string")
    .map((item) => item.trim())
    .filter(Boolean);
}

/** 严格归一化：任何越界输出都视为 needs_human */
export function normalizeGateVerdict(
  raw: unknown,
  modelId: string | null = null,
): GateModelVerdict {
  if (!raw || typeof raw !== "object") {
    return needsHuman("gate_output_not_object", modelId);
  }
  const value = raw as Record<string, unknown>;
  const verdict = value.verdict;
  if (verdict !== "pass" && verdict !== "fail" && verdict !== "needs_human") {
    return needsHuman("gate_output_invalid_verdict", modelId);
  }

  const reasons = asStringArray(value.reasons);
  const evidenceRefs = asStringArray(value.evidence_refs ?? value.evidenceRefs);
  const missing = asStringArray(value.missing);
  const confidence =
    typeof value.confidence === "number" &&
    Number.isFinite(value.confidence) &&
    value.confidence >= 0 &&
    value.confidence <= 1
      ? value.confidence
      : null;

  if (verdict === "pass" && missing.length > 0) {
    return {
      verdict: "needs_human",
      reasons: ["evidence_gap_unresolved", ...reasons],
      evidence_refs: evidenceRefs,
      missing,
      confidence,
      model_id: modelId,
      degraded: true,
    };
  }

  if (verdict === "fail" && reasons.length === 0) {
    reasons.push("unspecified_failure");
  }

  return {
    verdict,
    reasons,
    evidence_refs: evidenceRefs,
    missing,
    confidence,
    model_id: modelId,
    degraded: verdict === "needs_human",
  };
}

export async function runGatePrecheck(
  input: GatePrecheckInput,
  deps: { caller?: GateModelCaller | null; modelId?: string | null } = {},
): Promise<GateModelVerdict> {
  const modelId = deps.modelId ?? null;
  if (!deps.caller) {
    return needsHuman("gate_model_unavailable", modelId);
  }

  try {
    const raw = await deps.caller(input);
    return normalizeGateVerdict(raw, modelId);
  } catch {
    return needsHuman("gate_model_error", modelId);
  }
}
