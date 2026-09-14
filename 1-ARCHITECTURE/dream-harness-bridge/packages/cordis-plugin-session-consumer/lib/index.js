/**
 * DreamBuddy G 层 session log consumer Cordis plugin — Phase 1
 *
 * 监听 Harness session/event 事件，投影为 DreamBuddy G 层执行图格式，
 * 通过 IPC 写入 Python server 的 session_consumer 方法。
 *
 * 投影规则:
 *   tool/call → node_execution
 *   tool/result → node_result
 *   step/* → graph_node
 *   agent/pre-step → intent_gate
 *
 * HC-3: 不持有交易状态，仅消费事件流
 * V1-3: 从 session log 投影出的执行图与原快照等价
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-session-consumer";
const inject = [];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(true),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

/**
 * IPC client — 与 indicators/fundamental 相同的 stdio NDJSON 模式
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

/**
 * 投影规则：Harness session 事件 → DreamBuddy G 层格式
 *
 * Harness session/event 的 type 字段映射:
 *   tool/call   → node_execution  (工具调用开始)
 *   tool/result  → node_result     (工具调用结果)
 *   step/start   → graph_node      (agent step 开始)
 *   step/end     → graph_node      (agent step 结束)
 *   agent/pre-step → intent_gate   (意图识别/风险检查)
 *   其他         → graph_node      (默认)
 */
function projectEvent(sessionEvent) {
  const type = sessionEvent.type || sessionEvent.eventType || "unknown";
  const seq = sessionEvent.seq ?? sessionEvent.sequence ?? -1;
  const sessionId = sessionEvent.sessionId || sessionEvent.session_id || "unknown";

  let projectedType = "graph_node";
  if (type.startsWith("tool/call") || type === "tool_call") {
    projectedType = "node_execution";
  } else if (type.startsWith("tool/result") || type === "tool_result") {
    projectedType = "node_result";
  } else if (type.startsWith("agent/pre-step") || type === "agent_pre_step") {
    projectedType = "intent_gate";
  } else if (type.startsWith("step/")) {
    projectedType = "graph_node";
  }

  return {
    event_type: projectedType,
    event_data: {
      original_type: type,
      seq,
      payload: sessionEvent.payload || sessionEvent.data || {},
    },
    session_id: sessionId,
  };
}

function apply(ctx, config = {}) {
  if (!config.enabled) return;

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

  // 监听 session/event 事件
  // Harness 在 agent loop 中会触发各种 session 事件
  ctx.on("session/event", async (event) => {
    try {
      const projected = projectEvent(event);
      await ensureStarted();
      // 发送到 Python server 写入 G 层投影文件
      // 不 await — 非阻塞，事件流不阻塞 agent loop
      ipcClient.callMethod("session_consumer", projected).catch((e) => {
        // FAIL-OPEN: 写入失败不影响 agent loop
        ctx.logger?.warn?.(`session_consumer 写入失败: ${e.message}`) ;
      });
    } catch (e) {
      // FAIL-OPEN: 投影失败不阻塞 agent loop
      ctx.logger?.warn?.(`session/event 投影失败: ${e.message}`);
    }
  });

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name };
