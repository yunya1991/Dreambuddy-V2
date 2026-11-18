/**
 * Agent 工具调用全量埋点（P0）。
 *
 * 目标：回答「这次任务模型调了哪些工具、参数是什么、结果成功还是失败、错在哪一类」，
 * 为后续工具面改造与模型选型提供可复核的基线，不在生产链路里做任何决策。
 *
 * 约束：
 *  - FAIL-OPEN：任何写入异常都吞掉，绝不影响对话；
 *  - 只落本地 JSONL，不落完整 prompt / API key；
 *  - 参数与结果按字段脱敏并截断，避免日志膨胀。
 *
 * 目录：`AGENT_TELEMETRY_DIR`，默认 `<cwd>/.data/agent-telemetry`
 * 文件：`tool_calls.jsonl` / `steps.jsonl` / `runs.jsonl`
 */
import { promises as fs } from "fs";
import * as path from "path";
import type { Tool } from "ai";

const TELEMETRY_DIR =
  process.env.AGENT_TELEMETRY_DIR?.trim() ||
  path.join(process.cwd(), ".data", "agent-telemetry");
const MAX_FIELD_CHARS = 2000;
const SECRET_KEY_RE = /(api[_-]?key|token|secret|password|authorization|cookie)/i;

export interface ToolTelemetryContext {
  traceId: string;
  taskId?: string;
  surface?: string;
  profile?: string;
  model?: string;
  /** 当前模型步序号（工具执行时读，onStepFinish 后自增） */
  getStep?: () => number;
}

export interface ToolCallEvent {
  ts: string;
  trace_id: string;
  task_id?: string;
  surface?: string;
  profile?: string;
  model?: string;
  step: number;
  call_seq: number;
  tool: string;
  tool_call_id?: string;
  ok: boolean;
  degraded: boolean;
  error_code: string;
  error?: string;
  latency_ms: number;
  args?: unknown;
  args_chars?: number;
  result_preview?: string;
  result_chars?: number;
}

export interface ToolResultVerdict {
  ok: boolean;
  degraded: boolean;
  errorCode: string;
  error?: string;
}

/** 单条记录串行写入，避免并发 append 交错。 */
let writeChain: Promise<unknown> = Promise.resolve();

function appendJsonl(file: string, record: Record<string, unknown>): Promise<void> {
  writeChain = writeChain.then(async () => {
    try {
      await fs.mkdir(TELEMETRY_DIR, { recursive: true });
      await fs.appendFile(
        path.join(TELEMETRY_DIR, file),
        `${JSON.stringify(record)}\n`,
        "utf-8",
      );
    } catch {
      // FAIL-OPEN：埋点失败不影响主链路
    }
  });
  return writeChain as Promise<void>;
}

function truncate(text: string, max = MAX_FIELD_CHARS): string {
  return text.length > max ? `${text.slice(0, max)}…(truncated)` : text;
}

function sanitize(value: unknown, depth = 0): unknown {
  if (depth > 4) return "[depth]";
  if (typeof value === "string") return truncate(value);
  if (typeof value === "number" || typeof value === "boolean" || value === null) {
    return value;
  }
  if (Array.isArray(value)) {
    return value.slice(0, 20).map((item) => sanitize(item, depth + 1));
  }
  if (value && typeof value === "object") {
    const out: Record<string, unknown> = {};
    for (const [key, item] of Object.entries(value as Record<string, unknown>)) {
      out[key] = SECRET_KEY_RE.test(key) ? "[redacted]" : sanitize(item, depth + 1);
    }
    return out;
  }
  return String(value);
}

function previewResult(result: unknown): string {
  try {
    if (typeof result === "string") return truncate(result);
    if (result && typeof result === "object") {
      const record = result as Record<string, unknown>;
      const content = record.content;
      if (Array.isArray(content)) {
        const text = content
          .map((part) =>
            part && typeof part === "object" && typeof (part as { text?: unknown }).text === "string"
              ? (part as { text: string }).text
              : "",
          )
          .filter(Boolean)
          .join("\n");
        if (text) return truncate(text);
      }
    }
    return truncate(JSON.stringify(result) ?? String(result));
  } catch {
    return "[unserializable]";
  }
}

export function classifyToolError(message: string): string {
  const text = (message || "").toLowerCase();
  if (/未知能力|未启用|不对 l2 开放|非只读|invalid/.test(text)) return "invalid";
  if (/超时|timeout|timed out/.test(text)) return "timeout";
  if (/未直接命中|not_found|not found|不存在/.test(text)) return "not_found";
  if (/不可达|unavailable|connection|econn|失败/.test(text)) return "unavailable";
  if (/conflict|冲突/.test(text)) return "conflict";
  return "upstream_error";
}

/** 统一判定工具结果是否失败；兼容能力工具 `{ok:false,error}` 与 MCP `isError`。 */
export function inspectToolResult(result: unknown): ToolResultVerdict {
  if (!result || typeof result !== "object") {
    return { ok: true, degraded: false, errorCode: "" };
  }
  const record = result as Record<string, unknown>;
  const degraded = record.degraded === true;
  if (record.isError === true) {
    return { ok: false, degraded, errorCode: "mcp_error", error: "isError=true" };
  }
  if (record.ok === false) {
    const message =
      typeof record.error === "string" ? record.error : JSON.stringify(record.error ?? "");
    return {
      ok: false,
      degraded,
      errorCode: classifyToolError(message),
      error: truncate(message, 300),
    };
  }
  return { ok: true, degraded, errorCode: degraded ? "degraded" : "" };
}

type ExecutableTool = Tool & {
  execute?: (input: unknown, options?: { toolCallId?: string }) => unknown;
};

/** 包装工具执行：记录每次调用的入参、结果、错误分类与耗时。 */
export function withToolTelemetry<T extends Tool>(
  tools: Record<string, T> | undefined,
  ctx: ToolTelemetryContext,
): Record<string, T> | undefined {
  if (!tools) return tools;
  const wrapped: Record<string, T> = {};
  let callSeq = 0;

  for (const [name, def] of Object.entries(tools)) {
    const raw = def as unknown as ExecutableTool;
    if (typeof raw.execute !== "function") {
      wrapped[name] = def;
      continue;
    }
    const original = raw.execute.bind(raw);
    wrapped[name] = {
      ...(def as object),
      execute: async (input: unknown, options?: { toolCallId?: string }) => {
        const startedAt = Date.now();
        const seq = ++callSeq;
        const argsText = previewResult(input);
        try {
          const result = await original(input, options);
          const verdict = inspectToolResult(result);
          const resultText = previewResult(result);
          await appendJsonl("tool_calls.jsonl", {
            ts: new Date().toISOString(),
            trace_id: ctx.traceId,
            task_id: ctx.taskId,
            surface: ctx.surface,
            profile: ctx.profile,
            model: ctx.model,
            step: ctx.getStep?.() ?? -1,
            call_seq: seq,
            tool: name,
            tool_call_id: options?.toolCallId,
            ok: verdict.ok,
            degraded: verdict.degraded,
            error_code: verdict.errorCode,
            error: verdict.error,
            latency_ms: Date.now() - startedAt,
            args: sanitize(input),
            args_chars: argsText.length,
            result_preview: resultText,
            result_chars: resultText.length,
          } satisfies ToolCallEvent);
          return result;
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          await appendJsonl("tool_calls.jsonl", {
            ts: new Date().toISOString(),
            trace_id: ctx.traceId,
            task_id: ctx.taskId,
            surface: ctx.surface,
            profile: ctx.profile,
            model: ctx.model,
            step: ctx.getStep?.() ?? -1,
            call_seq: seq,
            tool: name,
            tool_call_id: options?.toolCallId,
            ok: false,
            degraded: false,
            error_code: "thrown",
            error: truncate(message, 300),
            latency_ms: Date.now() - startedAt,
            args: sanitize(input),
            args_chars: argsText.length,
          } satisfies ToolCallEvent);
          throw error;
        }
      },
    } as unknown as T;
  }
  return wrapped;
}

/** 步级记录：把 tool_call_id 与模型步序号绑定，便于和 tool_calls 关联。 */
export async function recordStep(
  ctx: ToolTelemetryContext,
  index: number,
  calls: Array<{ toolCallId?: string; toolName: string }>,
  verdict: string,
  text?: string,
): Promise<void> {
  await appendJsonl("steps.jsonl", {
    ts: new Date().toISOString(),
    trace_id: ctx.traceId,
    task_id: ctx.taskId,
    model: ctx.model,
    step: index,
    verdict,
    tool_call_ids: calls.map((call) => call.toolCallId).filter(Boolean),
    tools: calls.map((call) => call.toolName),
    text_preview: truncate(text ?? "", 500),
  });
}

/** 轮次汇总：成本、步数、失败工具数，供基线报告直接消费。 */
export async function recordRunSummary(
  ctx: ToolTelemetryContext,
  summary: {
    steps: number;
    toolCalls: number;
    toolErrors: number;
    inputTokens: number;
    outputTokens: number;
    finishReason?: string;
    latencyMs: number;
  },
): Promise<void> {
  await appendJsonl("runs.jsonl", {
    ts: new Date().toISOString(),
    trace_id: ctx.traceId,
    task_id: ctx.taskId,
    surface: ctx.surface,
    profile: ctx.profile,
    model: ctx.model,
    ...summary,
  });
}
