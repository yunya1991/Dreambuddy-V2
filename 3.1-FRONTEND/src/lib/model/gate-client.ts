/**
 * 千问门禁模型客户端（OpenAI 兼容协议）。
 *
 * 只读预审：固定 temperature=0，输出严格 JSON，不提供任何工具。
 * 凭据只从环境变量读取，不写入代码或日志。
 */

import type { GateModelCaller } from "@/lib/task-board/gate-model";
import { runGatePrecheck } from "@/lib/task-board/gate-model";

export interface GateClientConfig {
  baseUrl: string;
  apiKey: string;
  model: string;
  timeoutMs: number;
  maxTokens: number;
  disableThinking: boolean;
}

const SYSTEM_PROMPT = [
  "你是独立门禁审查模型，只做证据审查，不参与生产。",
  "你只能依据用户提供的结构化证据判断，禁止猜测、补全或使用常识替代缺失证据。",
  "输出必须是单个 JSON 对象，且严格符合：",
  '{"verdict":"pass|fail|needs_human","reasons":["..."],"evidence_refs":["..."],"missing":["..."],"confidence":0}',
  "规则：",
  "1. 证据不足或存在未关闭缺口时，verdict 必须为 needs_human；",
  "2. 证据与判据矛盾时，verdict 为 fail，并写明原因；",
  "3. 只有判据全部满足时才允许 pass；",
  "4. 不得输出 JSON 之外的任何文字。",
].join("\n");

export function loadGateClientConfig(
  env: Record<string, string | undefined> = process.env,
): GateClientConfig | null {
  const baseUrl = env.MODEL_GATE_BASE_URL?.trim().replace(/\/+$/, "");
  const apiKey = env.MODEL_GATE_API_KEY?.trim();
  const model = env.MODEL_GATE?.trim();
  if (!baseUrl || !apiKey || !model) return null;

  const timeout = Number(env.MODEL_GATE_TIMEOUT_MS);
  const maxTokens = Number(env.MODEL_GATE_MAX_TOKENS);

  return {
    baseUrl,
    apiKey,
    model,
    timeoutMs: Number.isFinite(timeout) && timeout > 0 ? timeout : 20000,
    maxTokens: Number.isFinite(maxTokens) && maxTokens > 0 ? maxTokens : 600,
    disableThinking: env.MODEL_GATE_DISABLE_THINKING === "1",
  };
}

/** 去掉模型偶发的 markdown 代码围栏，再解析 JSON */
export function extractJsonObject(raw: string): unknown {
  const text = raw.trim();
  if (!text) throw new Error("gate_model_empty_content");
  const fenced = text.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const candidate = fenced ? fenced[1].trim() : text;
  const start = candidate.indexOf("{");
  const end = candidate.lastIndexOf("}");
  if (start < 0 || end <= start) throw new Error("gate_model_not_json");
  return JSON.parse(candidate.slice(start, end + 1));
}

export function createGateCaller(config: GateClientConfig): GateModelCaller {
  return async (input) => {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), config.timeoutMs);

    try {
      const response = await fetch(`${config.baseUrl}/chat/completions`, {
        method: "POST",
        headers: {
          "content-type": "application/json",
          authorization: `Bearer ${config.apiKey}`,
        },
        body: JSON.stringify({
          model: config.model,
          temperature: 0,
          max_tokens: config.maxTokens,
          response_format: { type: "json_object" },
          ...(config.disableThinking ? { enable_thinking: false } : {}),
          messages: [
            { role: "system", content: SYSTEM_PROMPT },
            { role: "user", content: JSON.stringify(input) },
          ],
        }),
        signal: controller.signal,
      });

      if (!response.ok) {
        throw new Error(`gate_model_http_${response.status}`);
      }

      const data = (await response.json()) as {
        choices?: Array<{ message?: { content?: string } }>;
      };
      const content = data?.choices?.[0]?.message?.content;
      if (typeof content !== "string") {
        throw new Error("gate_model_empty_content");
      }
      return extractJsonObject(content);
    } finally {
      clearTimeout(timer);
    }
  };
}

export interface GateProbe {
  configured: boolean;
  ok: boolean;
  model: string | null;
  verdict?: string;
  reason?: string;
  latency_ms?: number;
}

/** 连通性探针：只验证凭据与输出契约，不代表业务判定 */
export async function probeGateModel(
  env: Record<string, string | undefined> = process.env,
): Promise<GateProbe> {
  const config = loadGateClientConfig(env);
  if (!config) {
    return {
      configured: false,
      ok: false,
      model: null,
      reason: "gate_model_unconfigured",
    };
  }

  const started = Date.now();
  const verdict = await runGatePrecheck(
    {
      gate_kind: "intent",
      evidence_ref: "health:1",
      evidence: { ping: true },
    },
    { caller: createGateCaller(config), modelId: config.model },
  );

  const connectivityError =
    verdict.reasons.includes("gate_model_error") ||
    verdict.reasons.includes("gate_model_unavailable") ||
    verdict.reasons.includes("gate_output_not_object");

  return {
    configured: true,
    ok: !connectivityError,
    model: config.model,
    verdict: verdict.verdict,
    reason: connectivityError ? verdict.reasons[0] : undefined,
    latency_ms: Date.now() - started,
  };
}
