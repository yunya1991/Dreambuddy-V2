/**
 * DreamBuddy 统计能力 Cordis plugin（TASKS-20261116 T1-1）
 *
 * 定位：L1 统计能力的 Worker 工具面。**只透传，不计算**（SPEC-53 HC-9）：
 *   - stats_list  → 读 manifest 目录（不执行任何能力）
 *   - stats_run   → 转发 `stats_capability`(op=run) → l1agg run_capability
 *
 * 硬边界：
 *   - 插件内不出现任何统计公式、不缓存结果；
 *   - 任何异常/超时 → 返回 `{ok:false, degraded:true, reason}`，不抛到 Worker（FAIL-OPEN）；
 *   - 能力是否可跑、怎么降级，一律由 L1 决定，插件只回传原信封。
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-stats";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  timeoutMs: z.number().default(20000),
});

const METHOD = "stats_capability";
const DEFAULT_LIMIT = 50;
const MAX_LIMIT = 200;

function degrade(reason) {
  return { ok: false, degraded: true, reason: String(reason) };
}

function withTimeout(promise, ms) {
  return new Promise((resolvePromise, rejectPromise) => {
    const timer = setTimeout(() => rejectPromise(new Error(`timeout:${ms}ms`)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolvePromise(value);
      },
      (error) => {
        clearTimeout(timer);
        rejectPromise(error);
      }
    );
  });
}

/**
 * 构造工具定义（不依赖 Cordis 运行时，便于单测注入假 IPC）。
 *
 * @param {{ callMethod: Function, ensureStarted?: Function, timeoutMs?: number }} deps
 * @returns {Array<object>} defineTool 结果数组
 */
export function createStatsTools({ callMethod, ensureStarted, timeoutMs = 20000 }) {
  const ensure = typeof ensureStarted === "function" ? ensureStarted : async () => {};

  async function request(op, params) {
    await ensure();
    const response = await withTimeout(callMethod(METHOD, { op, ...params }), timeoutMs);
    if (!response || response.ok !== true) {
      const detail = (response && (response.error || response.result)) || "empty_response";
      throw new Error(`stats ${op} failed: ${JSON.stringify(detail)}`);
    }
    return response.result;
  }

  const listTool = defineTool({
    name: "stats_list",
    description:
      "列出 L1 统计能力目录（93 个，含域/意图/最小样本/方法/数据域）。只读 capability_manifest，不执行能力。",
    parameters: {
      domain: {
        type: "string",
        description: "能力域过滤：A 指标 / B 趋势极值 / E 关系 / G 横截面 / J 科研方法 / K 只读出口",
      },
      q: {
        type: "string",
        description: "关键词：能力 ID（D-E17）、意图（correlation_query）或方法号（B14）",
      },
      min_n_max: {
        type: "number",
        description: "只保留 min_n ≤ 该值的能力（按当前数据量筛掉跑不动的）",
      },
      limit: {
        type: "number",
        description: `返回条数上限，默认 ${DEFAULT_LIMIT}，最大 ${MAX_LIMIT}`,
      },
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: true,
        properties: {
          manifest_version: { type: "number" },
          total: { type: "number" },
          returned: { type: "number" },
          items: { type: "array", items: { type: "object", additionalProperties: true } },
        },
      },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
    },
    async execute(args = {}) {
      const limit = Math.max(1, Math.min(Number(args.limit) || DEFAULT_LIMIT, MAX_LIMIT));
      try {
        return await request("list", {
          domain: args.domain || "",
          q: args.q || "",
          min_n_max: args.min_n_max == null ? null : Number(args.min_n_max),
          limit,
        });
      } catch (error) {
        return degrade(error && error.message ? error.message : error);
      }
    },
    presentCall: (args) => ({
      card: "generic",
      title: "统计能力目录",
      kind: "read",
      rawInput: JSON.stringify(args || {}),
      content: [{ type: "text", text: "列出 L1 可执行的统计能力" }],
    }),
    presentResult: (_args, result) => ({
      card: "generic",
      content: [
        {
          type: "text",
          text: result.ok === false
            ? `降级：${result.reason || "unknown"}`
            : `能力 ${result.returned}/${result.total}（manifest v${result.manifest_version}）`,
        },
      ],
    }),
  });

  const runTool = defineTool({
    name: "stats_run",
    description:
      "执行一个 L1 统计能力，返回标准 capability_result 信封（status/data/visual/meta）。插件只透传，不重算。",
    parameters: {
      capability_id: {
        type: "string",
        required: true,
        description: "能力 ID，如 D-A06 / D-E01 / D-K01（可先用 stats_list 查）",
      },
      payload: {
        type: "object",
        additionalProperties: true,
        description: "能力入参（如 {symbols:[...], days:400}）；按 manifest notes 与 stats_explain 给",
      },
    },
    output: {
      schema: {
        type: "object",
        additionalProperties: true,
        properties: {
          ok: { type: "boolean" },
          capability_id: { type: "string" },
          result: { type: "object", additionalProperties: true },
        },
      },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
    },
    async execute(args = {}) {
      const capabilityId = String(args.capability_id || "").trim();
      if (!capabilityId) return degrade("capability_id_required");
      const payload = args.payload && typeof args.payload === "object" ? args.payload : {};
      try {
        return await request("run", { capability_id: capabilityId, payload });
      } catch (error) {
        return degrade(error && error.message ? error.message : error);
      }
    },
    presentCall: (args) => ({
      card: "generic",
      title: `统计能力: ${args.capability_id || "?"}`,
      kind: "execute",
      rawInput: JSON.stringify(args.payload || {}),
      content: [{ type: "text", text: `执行 L1 能力 ${args.capability_id || "?"}` }],
    }),
    presentResult: (args, result) => {
      if (result && result.ok === false) {
        return { card: "generic", content: [{ type: "text", text: `降级：${result.reason || "unknown"}` }] };
      }
      const envelope = (result && result.result) || {};
      const status = envelope.status || "unknown";
      const degraded = envelope.degraded_reason ? ` · ${envelope.degraded_reason}` : "";
      return {
        card: "generic",
        content: [{ type: "text", text: `${args.capability_id}: ${status}${degraded}` }],
      };
    },
  });

  const validateTool = defineTool({
    name: "stats_validate",
    description:
      "预检能力能否用给定入参执行（不执行、不取数）：返回 missing_params / unknown_params / warnings。挂卡前先调它。",
    parameters: {
      capability_id: {
        type: "string",
        required: true,
        description: "能力 ID，如 D-A06",
      },
      payload: {
        type: "object",
        additionalProperties: true,
        description: "拟传入的入参；为空则只校验能力是否存在",
      },
    },
    output: {
      schema: { type: "object", additionalProperties: true },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
    },
    async execute(args = {}) {
      const capabilityId = String(args.capability_id || "").trim();
      if (!capabilityId) return degrade("capability_id_required");
      const payload = args.payload && typeof args.payload === "object" ? args.payload : {};
      try {
        return await request("validate", { capability_id: capabilityId, payload });
      } catch (error) {
        return degrade(error && error.message ? error.message : error);
      }
    },
    presentCall: (args) => ({
      card: "generic",
      title: `预检: ${args.capability_id || "?"}`,
      kind: "read",
      rawInput: JSON.stringify(args.payload || {}),
      content: [{ type: "text", text: "校验入参与能力前置条件" }],
    }),
    presentResult: (_args, result) => ({
      card: "generic",
      content: [
        {
          type: "text",
          text:
            result && result.ok
              ? "可执行"
              : `不可执行：missing=${(result.missing_params || []).join(",") || "-"} unknown=${(result.unknown_params || []).join(",") || "-"}`,
        },
      ],
    }),
  });

  const explainTool = defineTool({
    name: "stats_explain",
    description:
      "解释能力口径：方法号、最小样本、数据域、可接受参数、完整 notes（来自 manifest，不执行）。",
    parameters: {
      capability_id: {
        type: "string",
        required: true,
        description: "能力 ID，如 D-E17",
      },
    },
    output: {
      schema: { type: "object", additionalProperties: true },
      render: (_args, value) => [{ type: "text", text: JSON.stringify(value, null, 2) }],
    },
    async execute(args = {}) {
      const capabilityId = String(args.capability_id || "").trim();
      if (!capabilityId) return degrade("capability_id_required");
      try {
        return await request("explain", { capability_id: capabilityId });
      } catch (error) {
        return degrade(error && error.message ? error.message : error);
      }
    },
    presentCall: (args) => ({
      card: "generic",
      title: `能力口径: ${args.capability_id || "?"}`,
      kind: "read",
      rawInput: "",
      content: [{ type: "text", text: "读取 manifest 口径" }],
    }),
    presentResult: (_args, result) => ({
      card: "generic",
      content: [
        {
          type: "text",
          text: `${result.capability_id || "?"}: ${result.intent || "-"} · min_n=${result.min_n ?? "-"} · ${(result.methods || []).join("/") || "-"}`,
        },
      ],
    }),
  });

  return [listTool, runTool, validateTool, explainTool];
}

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath || resolve(__dirname, "../../python-server/server.py");
  const ipcClient = getSharedIPC({
    serverPath,
    executable: config.pythonExecutable || "python3",
  });

  let startPromise = null;
  const ensureStarted = () => {
    if (!startPromise) startPromise = ipcClient.start();
    return startPromise;
  };

  const tools = createStatsTools({
    callMethod: (method, params) => ipcClient.callMethod(method, params),
    ensureStarted,
    timeoutMs: Number(config.timeoutMs) || 20000,
  });

  for (const tool of tools) ctx.tools.register(tool);
}

export { Config, apply, inject, name };
