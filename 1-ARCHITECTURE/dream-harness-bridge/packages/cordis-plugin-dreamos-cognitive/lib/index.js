/**
 * DreamBuddy 认知能力 Cordis 插件 (P1-1)
 *
 * 把 4-MEMORY 认知系统封装为 Worker 原生工具面:
 *   dreamos_recall / dreamos_search        —— 只读
 *   dreamos_record / dreamos_verify        —— 写(需 enableWrites + 宿主写 scope)
 *
 * 架构: 复用 D3-b 共享 IPC(python-server/server.py 单进程),
 * Python 侧 cognitive_bridge.py 直接调用 CognitiveLoopEntry,不启动第二个 MCP 进程。
 *
 * 硬约束:
 *   HC-1 FAIL-OPEN: IPC 异常 → degraded,不 crash Worker
 *   HC-2 默认关: enabled=false 时不注册任何工具;enableWrites=false 时不注册写工具
 *   写门禁: Python 端仍校验 COGNITIVE_MCP_MODE / WRITE_ENABLED / principal(纵深防御)
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-dreamos-cognitive";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(false),          // HC-2 默认关
  enableWrites: z.boolean().default(false),     // record/verify 默认不注册
  defaultTopK: z.number().default(5),
  defaultMinQuality: z.string().default("C"),
  role: z.string().default("dreamos-cognitive"),
});

// 只读工具(始终注册,受 enabled 控制)
const READ_TOOL_DEFS = [
  {
    name: "dreamos_recall",
    method: "cognitive_recall",
    description:
      "从 DreamOS 认知记忆库检索相关经验(recall)。开工前调用可避免重复踩坑。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        context: { type: "string", description: "检索上下文/问题关键词" },
        top_k: { type: "number", description: "返回条数(默认 5)" },
        min_quality: {
          type: "string",
          enum: ["S", "A", "B", "C", "D"],
          description: "最低质量等级(默认 C,返回最多结果)",
        },
      },
      required: ["context"],
    },
  },
  {
    name: "dreamos_search",
    method: "cognitive_search",
    description: "对 DreamOS 认知记忆做语义搜索(向量检索),返回相关记忆片段。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        query: { type: "string", description: "搜索语句" },
        top_k: { type: "number", description: "返回条数(默认 5)" },
        tags: {
          type: "array",
          items: { type: "string" },
          description: "标签过滤(可选)",
        },
      },
      required: ["query"],
    },
  },
];

// 写工具(仅 enableWrites=true 时注册)
const WRITE_TOOL_DEFS = [
  {
    name: "dreamos_record",
    method: "cognitive_record",
    description:
      "把新经验写入 DreamOS 认知记忆库(record)。需宿主写 scope;写入后建议再调用 dreamos_verify。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        content: { type: "string", description: "经验内容(精炼,≤3000 字)" },
        quality_level: {
          type: "string",
          enum: ["S", "A", "B", "C", "D"],
          description: "质量等级(默认 C)",
        },
        tags: {
          type: "array",
          items: { type: "string" },
          description: "标签列表",
        },
        level: {
          type: "string",
          enum: ["observation", "derivation", "inference", "unknown"],
          description: "Evidence 事实分级(默认 observation)",
        },
        external_id: {
          type: "string",
          description: "幂等键(同 key 只写 1 条)",
        },
      },
      required: ["content"],
    },
  },
  {
    name: "dreamos_verify",
    method: "cognitive_verify",
    description:
      "验证记忆并触发贝叶斯置信度更新(verify)。需宿主写 scope;默认要求带 outcome 后果回传。",
    parameters: {
      type: "object",
      additionalProperties: false,
      properties: {
        memory_id: { type: "string", description: "记忆 ID(如 VM-xxx)" },
        success: { type: "boolean", description: "验证是否成功(默认 true)" },
        known_gaps_update: {
          type: "array",
          items: { type: "string" },
          description: "验证后更新的已知局限",
        },
        outcome: {
          type: "object",
          additionalProperties: true,
          description:
            "SPEC-33-G T-G1 后果回传: {accepted, tests_pass, reverted, change_id?, run_id?, outcome_seq?}",
        },
      },
      required: ["memory_id"],
    },
  },
];

function apply(ctx, config = {}) {
  if (!config.enabled) {
    return; // HC-2 默认关
  }

  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";

  const ipc = getSharedIPC({ serverPath, executable });

  let startPromise = null;
  async function ensureStarted() {
    if (!startPromise) startPromise = ipc.start();
    return startPromise;
  }

  const defs = config.enableWrites
    ? [...READ_TOOL_DEFS, ...WRITE_TOOL_DEFS]
    : [...READ_TOOL_DEFS];

  for (const def of defs) {
    try {
      ctx.tools.register({
        name: def.name,
        description: def.description,
        parameters: def.parameters,
        output: {
          schema: { type: "object", additionalProperties: true },
          render: (_args, value) => [
            { type: "text", text: JSON.stringify(value ?? null) },
          ],
        },
        async execute(args) {
          const params = { ...(args || {}) };
          // 只读工具的默认值在此补齐(写工具不注入默认,避免误写)
          if (def.method === "cognitive_recall") {
            if (params.top_k == null) params.top_k = config.defaultTopK;
            if (params.min_quality == null) params.min_quality = config.defaultMinQuality;
          }
          if (def.method === "cognitive_search") {
            if (params.top_k == null) params.top_k = config.defaultTopK;
          }
          try {
            await ensureStarted();
            const resp = await ipc.callMethod(def.method, params);
            if (resp?.ok) {
              return resp.result ?? { ok: true };
            }
            return {
              ok: false,
              degraded: true,
              reason: resp?.error?.message || "ipc_response_not_ok",
            };
          } catch (e) {
            // HC-1 FAIL-OPEN
            return { ok: false, degraded: true, reason: `ipc_error: ${e.message}` };
          }
        },
      });
      console.log(`[DreamOSCognitive] tool registered: ${def.name} → ${def.method}`);
    } catch (e) {
      console.warn(
        `[DreamOSCognitive] register ${def.name} failed (FAIL-OPEN): ${e.message}`
      );
    }
  }

  // 共享 IPC 进程由 shared-ipc.mjs 统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
