/**
 * DreamBuddy C1 技术扫描节点 Cordis plugin
 *
 * Phase 0 POC: 通过 IPC 调用 Python server 的 c1_scan 方法
 * Phase 1: 接入真实 DreamBuddy NodeRegistry
 *
 * V0-1 验证: tool 调用结果记录在 Harness session log 中
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
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

      // 监听 stderr 作为启动标志
      let stderrBuffer = "";
      this.process.stderr.on("data", (data) => {
        stderrBuffer += data.toString();
        // Python server 启动日志包含 "启动" 关键字
        if (stderrBuffer.includes("启动") && !this.started) {
          this.started = true;
          clearTimeout(timeout);
          // 版本握手
          this._handshake()
            .then(() => resolve())
            .catch((e) => reject(e));
        }
      });

      // 监听 stdout 的 NDJSON 响应
      let stdoutBuffer = "";
      this.process.stdout.on("data", (data) => {
        stdoutBuffer += data.toString();
        const lines = stdoutBuffer.split("\n");
        stdoutBuffer = lines.pop(); // 保留最后一行不完整的
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
            // 忽略解析错误
          }
        }
      });

      this.process.on("exit", (code) => {
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
        reject(new Error(`IPC 请求超时 (30s): ${request.method || request.message_type}`));
      }, 30000);

      this.pendingRequests.set(request.id, (response) => {
        clearTimeout(timeout);
        resolve(response);
      });

      const line = JSON.stringify(request);
      this.process.stdin.write(line + "\n");
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

  const ipcClient = new PythonIPCClient(executable, serverPath);

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

  // Cordis dispose：停止 Python server
  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name };
