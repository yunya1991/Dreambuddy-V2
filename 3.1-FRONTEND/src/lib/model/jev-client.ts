/**
 * JEV（TypeSafe System One）门禁客户端。
 *
 * 用途：验收类门禁的机器预审与异构第二票。
 * 边界：
 * - 只判断「是否完成 / 质量分级 / 证据是否齐全」，不判断市场方向（HC-9）；
 * - noul / score 都是概率型输出，置信度不足时一律 needs_human；
 * - 只发送结构化摘要，不发送原始行情与持仓明细。
 */

import type {
  GateModelCaller,
  GateModelVerdict,
  GatePrecheckInput,
} from "@/lib/task-board/gate-model";
import { runGatePrecheck } from "@/lib/task-board/gate-model";

export interface JevClientConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  timeoutMs: number;
}

export const COMPLETION_THRESHOLD = 0.85;
export const COMPLETION_LOW_THRESHOLD = 0.5;

export function loadJevClientConfig(
  env: Record<string, string | undefined> = process.env,
): JevClientConfig | null {
  const apiKey = env.TYPESAFE_API_KEY?.trim();
  if (!apiKey) return null;

  const baseUrl = (env.TYPESAFE_BASE_URL || "https://api.typesafe.ai")
    .trim()
    .replace(/\/+$/, "");
  const model =
    env.MODEL_GATE_SECONDARY?.trim() ||
    env.TYPESAFE_DEFAULT_MODEL?.trim() ||
    "jev-latest";
  const timeoutSeconds = Number(env.TYPESAFE_TIMEOUT_S);

  return {
    baseUrl,
    apiKey,
    model,
    timeoutMs:
      Number.isFinite(timeoutSeconds) && timeoutSeconds > 0
        ? timeoutSeconds * 1000
        : 10000,
  };
}

export function buildJevQuestions(): Record<string, unknown> {
  return {
    task_complete: {
      type: "noul",
      instructions:
        "任务是否已完成：所有必需产物已生成、证据齐全、无未关闭缺口。只判断过程与证据，不判断市场方向。",
    },
    quality_score: {
      type: "score",
      instructions: "交付质量分级",
      criteria: ["不合格", "基本合格", "合格", "优秀"],
    },
  };
}

function readRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === "object"
    ? (value as Record<string, unknown>)
    : {};
}

function readNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

/** 把 JEV 的 noul + score 映射成门禁结论 */
export function mapJevResponse(
  raw: unknown,
  modelId: string | null = null,
): GateModelVerdict {
  const root = readRecord(raw);
  if (root.degraded === true) {
    return {
      verdict: "needs_human",
      reasons: ["jev_degraded", String(root.reason ?? "unknown")],
      evidence_refs: [],
      missing: [],
      confidence: null,
      model_id: modelId,
      degraded: true,
    };
  }

  const answers = readRecord(root.answers);
  const complete = readRecord(answers.task_complete);
  const quality = readRecord(answers.quality_score);
  const noul = readNumber(complete.noul);
  const rawScore = readNumber(quality.score);
  const levels = Array.isArray(quality.legend)
    ? quality.legend.length
    : Array.isArray(quality.probabilities)
      ? quality.probabilities.length
      : 4;
  const qualityRatio =
    rawScore === null
      ? null
      : levels > 1
        ? Math.min(1, Math.max(0, rawScore / (levels - 1)))
        : 0;

  if (noul === null) {
    return {
      verdict: "needs_human",
      reasons: ["jev_missing_noul"],
      evidence_refs: [],
      missing: [],
      confidence: null,
      model_id: modelId,
      degraded: true,
    };
  }

  const reasons: string[] = [
    `complete=${noul.toFixed(2)}`,
    qualityRatio === null
      ? "quality=unknown"
      : `quality=${(qualityRatio * 100).toFixed(0)}%`,
  ];

  if (noul >= COMPLETION_THRESHOLD && (qualityRatio ?? 1) >= 0.5) {
    return {
      verdict: "pass",
      reasons,
      evidence_refs: [],
      missing: [],
      confidence: noul,
      model_id: modelId,
      degraded: false,
    };
  }

  if (noul < COMPLETION_LOW_THRESHOLD) {
    return {
      verdict: "fail",
      reasons: ["completion_below_low_threshold", ...reasons],
      evidence_refs: [],
      missing: [],
      confidence: noul,
      model_id: modelId,
      degraded: false,
    };
  }

  return {
    verdict: "needs_human",
    reasons: ["completion_in_middle_band", ...reasons],
    evidence_refs: [],
    missing: [],
    confidence: noul,
    model_id: modelId,
    degraded: true,
  };
}

export function createJevCaller(config: JevClientConfig): GateModelCaller {
  return async (input: GatePrecheckInput) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.timeoutMs);

    try {
      const response = await fetch(`${config.baseUrl}/v1/systemone`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify({
          state: input.evidence,
          model: config.model,
          questions: buildJevQuestions(),
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`jev_http_${response.status}`);
      }

      const data = (await response.json()) as Record<string, unknown>;
      return mapJevResponse(data, config.model);
    } finally {
      clearTimeout(timer);
    }
  };
}

export interface JevProbe {
  configured: boolean;
  ok: boolean;
  model: string | null;
  verdict?: string;
  confidence?: number | null;
  latency_ms?: number;
  reason?: string;
}

/** 连通性探针：只验证凭据与契约，不代表业务判定 */
export async function probeJevModel(
  env: Record<string, string | undefined> = process.env,
): Promise<JevProbe> {
  const config = loadJevClientConfig(env);
  if (!config) {
    return {
      configured: false,
      ok: false,
      model: null,
      reason: "jev_unconfigured",
    };
  }

  const started = Date.now();
  const verdict = await runGatePrecheck(
    {
      gate_kind: "acceptance",
      evidence_ref: "health:1",
      evidence: { ping: true, objective: "health check", krs: [] },
    },
    { caller: createJevCaller(config), modelId: config.model },
  );

  const connectivityError =
    verdict.reasons.includes("gate_model_error") ||
    verdict.reasons.includes("gate_model_unavailable");

  return {
    configured: true,
    ok: !connectivityError,
    model: config.model,
    verdict: verdict.verdict,
    confidence: verdict.confidence,
    latency_ms: Date.now() - started,
    reason: connectivityError ? verdict.reasons[0] : undefined,
  };
}
