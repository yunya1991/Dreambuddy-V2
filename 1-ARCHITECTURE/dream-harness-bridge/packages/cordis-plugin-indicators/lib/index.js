/**
 * DreamBuddy 经典指标系统 Cordis plugin — Phase 1
 *
 * 通过 IPC 调用 Python server 的 technical_indicators 方法，
 * Python server 再通过 HTTP 调用 10-经典指标系统 (port 8092)。
 *
 * V1-1: 并行化验证 — 与 dreambuddy-fundamental 并行调用
 * V1-2: 降级链验证 — 8092 不可达时 FAIL-OPEN 返回中性默认值
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-indicators";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";

  const ipcClient = getSharedIPC({ serverPath, executable });

  let startPromise = null;

  async function ensureStarted() {
    if (!startPromise) {
      startPromise = ipcClient.start();
    }
    return startPromise;
  }

  // 注册经典指标系统 tool
  ctx.tools.register(
    defineTool({
      name: "get_technical_indicators",
      description:
        "获取经典技术指标信号（MA200、RSI、MACD、ATR、量能等）。数据来源：10-经典指标系统 (port 8092)。服务不可达时返回中性默认值。",
      parameters: {
        symbol: {
          type: "string",
          required: true,
          description: "交易对符号，如 BTC、ETH、SOL",
        },
        endpoint: {
          type: "string",
          description: "自定义 API endpoint 路径（默认 /signals/recent）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            node_id: { type: "string" },
            symbol: { type: "string" },
            status: { type: "string" },
            data: { type: "object", additionalProperties: true },
            neutral_default: { type: "object", additionalProperties: true },
          },
        },
        render: (_args, value) => [
          {
            type: "text",
            text: JSON.stringify(value, null, 2),
          },
        ],
      },
      async execute(args, _exec) {
        await ensureStarted();

        const response = await ipcClient.callMethod("technical_indicators", {
          symbol: args.symbol,
          endpoint: args.endpoint || "/signals/recent",
        });

        if (!response.ok) {
          throw new Error(
            `经典指标系统调用失败: ${JSON.stringify(response.error || response.result)}`
          );
        }

        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: `经典指标: ${args.symbol}`,
        kind: "execute",
        rawInput: `${args.symbol}`,
        content: [
          {
            type: "text",
            text: `查询 ${args.symbol} 技术指标信号`,
          },
        ],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text: `状态: ${result.status || "ok"} | 节点: ${result.node_id || "technical_indicators"}`,
          },
        ],
      }),
    })
  );

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
