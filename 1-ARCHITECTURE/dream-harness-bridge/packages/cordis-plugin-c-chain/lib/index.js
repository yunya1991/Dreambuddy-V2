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

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
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

class PythonIPCClient {
  constructor(executable, serverPath) {
    this.executable = executable;
    this.serverPath = serverPath;
    this.process = null;
    this.pendingRequests = new Map();
    this.started = false;
    this.startPromise = null;
  }

  async start() {
    if (this.started) return;
    if (this.startPromise) return this.startPromise;
    this.startPromise = this._doStart();
    return this.startPromise;
  }

  async _doStart() {
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        reject(new Error("Python server 启动超时 (10s)"));
      }, 10000);

      this.process = spawn(this.executable, [this.serverPath], {
        stdio: ["pipe", "pipe", "pipe"],
      });

      let stderrBuffer = "";
      this.process.stderr.on("data", (data) => {
        stderrBuffer += data.toString();
        if (stderrBuffer.includes("启动") && !this.started) {
          this.started = true;
          clearTimeout(timeout);
          this._handshake()
            .then(() => resolve())
            .catch((e) => reject(e));
        }
      });

      let stdoutBuffer = "";
      this.process.stdout.on("data", (data) => {
        stdoutBuffer += data.toString();
        const lines = stdoutBuffer.split("\n");
        stdoutBuffer = lines.pop();
        for (const line of lines) {
          if (!line.trim()) continue;
          try {
            const response = JSON.parse(line);
            const id = response.id;
            const pending = this.pendingRequests.get(id);
            if (pending) {
              this.pendingRequests.delete(id);
              pending(response);
            }
          } catch (e) {
            // ignore
          }
        }
      });

      this.process.on("exit", () => {
        this.started = false;
        this.process = null;
      });

      this.process.on("error", (err) => {
        clearTimeout(timeout);
        reject(new Error(`Python server 启动失败: ${err.message}`));
      });
    });
  }

  async _handshake() {
    const request = {
      schema_version: CURRENT_SCHEMA_VERSION,
      message_type: "handshake_request",
      client_version: CURRENT_SCHEMA_VERSION,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    };
    const response = await this.send(request);
    if (!response.ok) {
      throw new Error(`版本握手失败: ${JSON.stringify(response.error)}`);
    }
  }

  async send(request) {
    if (!this.started || !this.process) {
      throw new Error("Python server 未启动");
    }
    return new Promise((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(request.id);
        reject(new Error(`IPC 请求超时 (30s): ${request.method}`));
      }, 30000);

      this.pendingRequests.set(request.id, (response) => {
        clearTimeout(timeout);
        resolve(response);
      });

      this.process.stdin.write(JSON.stringify(request) + "\n");
    });
  }

  async callMethod(method, params) {
    const request = {
      schema_version: CURRENT_SCHEMA_VERSION,
      message_type: "request",
      method,
      params,
      id: randomUUID(),
      timestamp: new Date().toISOString(),
    };
    return this.send(request);
  }

  stop() {
    if (this.process) {
      this.process.kill("SIGTERM");
      this.process = null;
      this.started = false;
    }
  }
}

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";
  const enabled = config.enabled !== false;

  if (!enabled) return;

  const ipcClient = new PythonIPCClient(executable, serverPath);
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
          properties: {
            capability: { type: "string" },
            direction: { type: "string" },
            confidence: { type: "number" },
            details: {
              type: "object",
              properties: {
                C1: { type: "object" },
                C2: { type: "object" },
                C3: { type: "object" },
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

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name };
