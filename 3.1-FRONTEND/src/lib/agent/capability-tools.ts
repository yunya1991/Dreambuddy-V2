/**
 * 系统能力工具（只读）——对话模型与能力注册表之间的唯一接口。
 *
 * 只有两个工具：
 * - system_capabilities：按层/关键词查询能力清单（模型自发现）；
 * - run_capability：按能力 ID 统一执行，分发到 L1 / DSH / 6-TRADING。
 *
 * 能力清单来自 capability-registry.json；新增能力只改注册表，不改本文件。
 * 全部 FAIL-OPEN：失败返回 { ok:false, error }，由模型如实说明，不阻断对话。
 */
import { tool } from "ai";
import { z } from "zod";
import {
  CAPABILITY_PROMPT,
  listCapabilities,
  runCapability,
  type CapabilityLayer,
} from "./capability-registry";

export { CAPABILITY_PROMPT };

export function createCapabilityTools() {
  return {
    system_capabilities: tool({
      description:
        "查询当前系统可调用的只读能力清单（ID、层级、适用场景、耗时）。不确定该调什么时先查这里。",
      inputSchema: z.object({
        layer: z
          .enum(["L0", "L1", "L2"])
          .optional()
          .describe("按架构层过滤"),
        keyword: z
          .string()
          .optional()
          .describe("关键词过滤，如 趋势 / 估值 / 矛盾 / 回测"),
      }),
      execute: async ({
        layer,
        keyword,
      }: {
        layer?: CapabilityLayer;
        keyword?: string;
      }) => ({
        ok: true,
        capabilities: listCapabilities({ layer, keyword }).map((c) => ({
          id: c.id,
          name: c.name,
          layer: c.layer,
          when: c.when,
          params: c.params,
          latency_ms: c.latency_ms,
        })),
      }),
    }),

    run_capability: tool({
      description:
        "执行一个只读能力。id 取自 system_capabilities；params 按能力定义传入（常见：question、symbol、context）。",
      inputSchema: z.object({
        id: z.string().describe("能力 ID，如 market.price / dsh.technical / dsh.c_drive"),
        params: z
          .record(z.string(), z.unknown())
          .optional()
          .describe("能力参数，如 { question, symbol, context }"),
      }),
      execute: async ({
        id,
        params,
      }: {
        id: string;
        params?: Record<string, unknown>;
      }) => runCapability(id, params ?? {}),
    }),
  };
}

export type CapabilityTools = ReturnType<typeof createCapabilityTools>;
