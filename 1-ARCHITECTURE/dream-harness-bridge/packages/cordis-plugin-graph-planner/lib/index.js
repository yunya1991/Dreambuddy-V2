/**
 * DreamBuddy A 层 GraphPlanner Cordis plugin
 *
 * 注册 agent/pre-step listener，在 S 层意图识别后执行图编排。
 * 接收 S 层 intent_gateway 输出（或自行推导），通过 IPC 调用 Python server
 * 的 graph_planner 方法，生成 ExecutionPlan 并存储到 session context。
 *
 * 映射: A层(GraphPlanner) → agent/pre-step listener → graph_planner IPC
 * 对应文档: RESEARCH_SACG_HARNESS_MAPPING.md §A层
 *
 * Phase 1: 通过 IPC 调用真实 DreamOS GraphPlanner
 * HC-7: 失败时降级为空计划 (FAIL-OPEN)，不阻塞交易流程
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-graph-planner";
const inject = [];

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
          this._handshake().then(() => resolve()).catch(reject);
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
            const pending = this.pendingRequests.get(response.id);
            if (pending) {
              this.pendingRequests.delete(response.id);
              pending(response);
            }
          } catch {}
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
        reject(new Error(`IPC 请求超时: ${request.method || request.message_type}`));
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

/**
 * 从用户输入推导 graph_planner 参数
 * Phase 1: 简单关键词映射；Phase 2 由 S 层 intent_gateway 直接传入
 */
function deriveGraphPlannerParams(userInput) {
  const text = (userInput || "").toLowerCase();

  // 意图类型 → 推荐链路映射
  let intentType = "MARKET_ANALYSIS";
  let recommendedChain = "C"; // 默认 C 链（分析链）

  if (/(开仓|买入|卖出|trade|下单)/.test(text)) {
    intentType = "TRADE_EXECUTION";
    recommendedChain = "A"; // 交易执行走 A 链
  } else if (/(趋势|trend|均线|突破)/.test(text)) {
    intentType = "TREND_FOLLOWING";
    recommendedChain = "A";
  } else if (/(反转|reversal|抄底|摸顶)/.test(text)) {
    intentType = "REVERSAL";
    recommendedChain = "F";
  } else if (/(查询|持仓|balance|状态)/.test(text)) {
    intentType = "POSITION_QUERY";
    recommendedChain = "C";
  } else if (/(扫描|scan|选股|筛选)/.test(text)) {
    intentType = "SCANNING";
    recommendedChain = "C";
  }

  // 置信度: 有明确关键词则较高
  const confidence = /(开仓|买入|卖出|趋势|反转|扫描)/.test(text) ? 0.72 : 0.5;

  return {
    intent_type: intentType,
    recommended_chain: recommendedChain,
    confidence,
  };
}

/**
 * 默认空计划（FAIL-OPEN 降级用）
 */
function emptyPlan(reason) {
  return {
    planned_chain: "C",
    selected_nodes: [],
    budget: { total: 0, per_node: {} },
    rationale: `[degraded] ${reason}`,
    estimated_total_tokens: 0,
    estimated_total_latency_ms: 0,
    _source: "plugin_fail_open",
  };
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

  // A 层: 在 agent/pre-step 执行图编排
  // 时序: S层(intent-gateway) → A层(graph-planner) → C层(节点执行)
  ctx.on("agent/pre-step", async (session, next) => {
    try {
      await ensureStarted();

      // 从 session 中提取最后一条用户消息
      const messages = session?.messages || [];
      const lastMessage = messages[messages.length - 1];
      let userInput = "";
      if (typeof lastMessage === "string") {
        userInput = lastMessage;
      } else if (lastMessage) {
        const content = lastMessage.content;
        if (typeof content === "string") {
          userInput = content;
        } else if (Array.isArray(content)) {
          userInput = content
            .filter((c) => typeof c === "string" || c?.type === "text")
            .map((c) => (typeof c === "string" ? c : c.text || ""))
            .join(" ");
        } else if (content) {
          userInput = JSON.stringify(content);
        }
      }

      // 推导 graph_planner 参数
      const params = deriveGraphPlannerParams(userInput);

      // 通过 IPC 调用 Python server 的 graph_planner 方法
      const response = await ipcClient.callMethod("graph_planner", params);

      if (response.ok && response.result) {
        const plan = response.result;
        // 存储 ExecutionPlan 到 session context，供 C 层节点读取
        session.dreamosPlan = plan;
        session.dreamosPlannedChain = plan.planned_chain;
        session.dreamosSelectedNodeIds = (plan.selected_nodes || []).map(
          (n) => n.node_id || n
        );

        console.log(
          `[GraphPlanner] chain=${plan.planned_chain} ` +
            `nodes=${(plan.selected_nodes || []).length} ` +
            `source=${plan._source || "unknown"}`
        );
      } else {
        // IPC 调用失败 → FAIL-OPEN: 使用空计划
        console.warn(
          `[GraphPlanner] IPC 调用失败，FAIL-OPEN: ${response.error?.message || "unknown"}`
        );
        session.dreamosPlan = emptyPlan("IPC 调用失败");
      }

      return await next();
    } catch (e) {
      // 异常 → FAIL-OPEN: 使用空计划，不阻塞 agent step
      console.warn(`[GraphPlanner] 异常，FAIL-OPEN: ${e.message}`);
      session.dreamosPlan = emptyPlan(e.message);
      return await next();
    }
  });

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name, deriveGraphPlannerParams, emptyPlan };
