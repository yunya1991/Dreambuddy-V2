/**
 * DreamBuddy C1 技术扫描节点 Cordis plugin
 *
 * Phase 0 POC: 通过 IPC 调用 Python server 的 c1_scan 方法
 * Phase 1: 接入真实 DreamBuddy NodeRegistry
 *
 * V0-1 验证: tool 调用结果记录在 Harness session log 中
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-c1";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

/**
 * 简易 IPC client：通过 stdio NDJSON 与 Python server 通信
 */

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";

  const ipcClient = getSharedIPC({ serverPath, executable });

  // 延迟启动：第一次 tool 调用时启动
  let startPromise = null;

  async function ensureStarted() {
    if (!startPromise) {
      startPromise = ipcClient.start();
    }
    return startPromise;
  }

  // 注册 C1 技术扫描 tool
  ctx.tools.register(
    defineTool({
      name: "c1_technical_scan",
      description:
        "DreamBuddy C1 技术扫描节点：扫描指定交易对的技术指标（MA200、RSI、MACD、成交量、ATR），返回整体信号和置信度。",
      parameters: {
        symbol: {
          type: "string",
          required: true,
          description: "交易对符号，如 BTC、ETH、SOL",
        },
        timeframe: {
          type: "string",
          description: "K线周期，如 4H、1H、1D（默认 4H）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            node_id: { type: "string" },
            symbol: { type: "string" },
            overall_signal: { type: "string" },
            confidence: { type: "number" },
            indicators: { type: "object", additionalProperties: true },
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

        const response = await ipcClient.callMethod("c1_scan", {
          symbol: args.symbol,
          timeframe: args.timeframe || "4H",
        });

        if (!response.ok) {
          throw new Error(
            `C1 技术扫描失败: ${JSON.stringify(response.error || response.result)}`
          );
        }

        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: `C1 技术扫描: ${args.symbol}`,
        kind: "execute",
        rawInput: `${args.symbol} ${args.timeframe || "4H"}`,
        content: [
          {
            type: "text",
            text: `扫描 ${args.symbol} ${args.timeframe || "4H"} 技术指标`,
          },
        ],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text: `信号: ${result.overall_signal} | 置信度: ${(result.confidence * 100).toFixed(0)}% | MA200: ${result.indicators?.ma200?.signal || "N/A"}`,
          },
        ],
      }),
    })
  );

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
