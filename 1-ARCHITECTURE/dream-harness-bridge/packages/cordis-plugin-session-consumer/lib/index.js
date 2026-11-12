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

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
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

  const ipcClient = getSharedIPC({ serverPath, executable });

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

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
