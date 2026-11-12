/**
 * DreamBuddy S 层 IntentGateway Cordis plugin
 *
 * 注册 agent/pre-step listener，在 agent step 之前执行意图识别和风险评估。
 * V0-5: 验证 IntentGateway pre-step listener 接入
 *
 * Phase 0 POC: 简化版，通过 IPC 调用 Python server 的 intent_gateway 方法
 * Phase 1: 接入真实 DreamBuddy S 层 IntentGateway
 */

import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { getSharedIPC } from "../../python-server/shared-ipc.mjs";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-intent-gateway";
const inject = [];

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

  // V0-5: 注册 agent/pre-step listener
  // IntentGateway 在 agent step 之前执行意图识别和风险评估
  ctx.on(
    "agent/pre-step",
    async (session, next) => {
      try {
        await ensureStarted();

        // 从 session 中提取参数
        const messages = session?.messages || [];
        const step = session?.step ?? 0;
        const agentId = session?.agent?.id || "unknown";

        // 提取最后一条用户消息作为意图识别输入
        const lastMessage = messages[messages.length - 1];
        let userInput = "";
        if (typeof lastMessage === "string") {
          userInput = lastMessage;
        } else if (lastMessage) {
          const content = lastMessage.content;
          if (typeof content === "string") {
            userInput = content;
          } else if (Array.isArray(content)) {
            // content 可能是数组，提取文本部分
            userInput = content
              .filter((c) => typeof c === "string" || c?.type === "text")
              .map((c) => (typeof c === "string" ? c : c.text || ""))
              .join(" ");
          } else if (content) {
            userInput = JSON.stringify(content);
          }
        }

        // 通过 IPC 调用 Python server 的 intent_gateway 方法
        const response = await ipcClient.callMethod("intent_gateway", {
          user_input: userInput,
          step,
          agent_id: agentId,
        });

        if (response.ok && response.result) {
          const result = response.result;

          // 如果 IntentGateway 判定为高风险，记录日志
          if (result.risk_level === "high" && result.advisory) {
            console.log(
              `[IntentGateway] 风险提示: ${result.advisory} (risk=${result.risk_level})`
            );
          } else {
            console.log(
              `[IntentGateway] 意图: ${result.intent}, 风险: ${result.risk_level}`
            );
          }

          // IntentGateway 通过后继续 agent step
          return await next();
        } else {
          // IPC 调用失败 → FAIL-OPEN：继续 agent step
          console.warn(
            `[IntentGateway] IPC 调用失败，FAIL-OPEN 放行: ${response.error?.message || "unknown"}`
          );
          return await next();
        }
      } catch (e) {
        // 异常 → FAIL-OPEN：不阻塞 agent step
        console.warn(`[IntentGateway] 异常，FAIL-OPEN 放行: ${e.message}`);
        return await next();
      }
    }
  );

  // 共享 IPC 进程由 shared-ipc.mjs 在 Node 退出时统一回收,单插件 dispose 不 stop
}

export { Config, apply, inject, name };
