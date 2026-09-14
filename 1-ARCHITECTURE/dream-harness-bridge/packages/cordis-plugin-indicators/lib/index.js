/**
 * DreamBuddy 经典指标系统 Cordis plugin — Phase 1
 *
 * 通过 IPC 调用 Python server 的 technical_indicators 方法，
 * Python server 再通过 HTTP 调用 10-经典指标系统 (port 8092)。
 *
 * V1-1: 并行化验证 — 与 dreambuddy-fundamental 并行调用
 * V1-2: 降级链验证 — 8092 不可达时 FAIL-OPEN 返回中性默认值
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
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
    return new Promise((resolveP, rejectP) => {
      const timeout = setTimeout(() => {
        rejectP(new Error("Python server 启动超时 (10s)"));
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
            .then(() => resolveP())
            .catch((e) => rejectP(e));
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
          } catch (_e) {
            // 忽略解析错误
          }
        }
      });

      this.process.on("exit", () => {
        this.started = false;
        this.process = null;
      });

      this.process.on("error", (err) => {
        clearTimeout(timeout);
        rejectP(new Error(`Python server 启动失败: ${err.message}`));
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
    return new Promise((resolveP, rejectP) => {
      const timeout = setTimeout(() => {
        this.pendingRequests.delete(request.id);
        rejectP(new Error(`IPC 请求超时 (30s): ${request.method || request.message_type}`));
      }, 30000);

      this.pendingRequests.set(request.id, (response) => {
        clearTimeout(timeout);
        resolveP(response);
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

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name };
