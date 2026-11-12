/**
 * DreamBuddy C 层能力域 Cordis plugin
 *
 * 设计边界:
 *   - 暴露**能力域级别**的接口（execute_c_chain），不直接暴露 C1/C2/C3 内部节点
 *   - C1/C2/C3 是交易能力域的内部执行单元，需要 market_data，agent 无法直接提供
 *   - 内部自动获取数据 → 构造 State → 依次执行 C 链节点 → 综合 direction/confidence
 *
 * 对应 Dream OS:
 *   dreamos.capabilities.trading (交易能力域)
 *   → 内部节点 C1_tech_scan / C2_momentum / C3_volatility
 *   → 由 GraphExecutor 调度执行（此处简化为顺序执行）
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";
import { defineTool } from "@deepseek-ai/dsh-tools";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-c-chain";
const inject = ["tools"];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(true),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";
  const enabled = config.enabled !== false;

  if (!enabled) return;

  const ipcClient = getSharedIPC({ serverPath, executable });
  let startPromise = null;

  async function ensureStarted() {
    if (!startPromise) {
      startPromise = ipcClient.start();
    }
    return startPromise;
  }

  // C 层能力域 tool：执行完整 C 链
  ctx.tools.register(
    defineTool({
      name: "execute_c_chain",
      description:
        "DreamBuddy C 层交易分析能力：执行完整 C 链分析（C1技术扫描→C2动量分析→C3波动率分析），返回综合方向(LONG/SHORT/HOLD)和置信度。内部自动获取市场数据，无需手动传入指标。",
      parameters: {
        symbol: {
          type: "string",
          required: true,
          description: "交易对符号，如 BTC、ETH、SOL",
        },
        timeframe: {
          type: "string",
          description: "时间周期，如 1H、4H、1D（默认 4H）",
        },
      },
      output: {
        schema: {
          type: "object",
          additionalProperties: true,
          properties: {
            capability: { type: "string" },
            direction: { type: "string" },
            confidence: { type: "number" },
            details: {
              type: "object",
              additionalProperties: true,
              properties: {
                C1: { type: "object", additionalProperties: true },
                C2: { type: "object", additionalProperties: true },
                C3: { type: "object", additionalProperties: true },
              },
            },
          },
        },
        render: (_args, value) => [
          { type: "text", text: JSON.stringify(value, null, 2) },
        ],
      },
      async execute(args, _exec) {
        await ensureStarted();

        const response = await ipcClient.callMethod("execute_c_chain", {
          symbol: args.symbol,
          timeframe: args.timeframe || "4H",
        });

        if (!response.ok) {
          throw new Error(
            `C 链执行失败: ${JSON.stringify(response.error || response.result)}`
          );
        }

        return response.result;
      },
      presentCall: (args) => ({
        card: "generic",
        title: `C 链分析: ${args.symbol} (${args.timeframe || "4H"})`,
        kind: "execute",
        content: [
          {
            type: "text",
            text: "执行 C1技术扫描 → C2动量分析 → C3波动率分析",
          },
        ],
      }),
      presentResult: (_args, result) => ({
        card: "generic",
        content: [
          {
            type: "text",
            text: `综合方向: ${result.direction} | 置信度: ${(result.confidence * 100).toFixed(0)}%\n` +
              `C1: ${result.details?.C1?.direction}(${result.details?.C1?.confidence?.toFixed(2)}) | ` +
              `C2: ${result.details?.C2?.direction}(${result.details?.C2?.confidence?.toFixed(2)}) | ` +
              `C3: ${result.details?.C3?.direction}(${result.details?.C3?.confidence?.toFixed(2)})`,
          },
        ],
      }),
    })
  );

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
