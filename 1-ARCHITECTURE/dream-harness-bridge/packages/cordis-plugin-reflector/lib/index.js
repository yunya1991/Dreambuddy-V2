/**
 * DreamBuddy C 层 Reflector Cordis plugin
 *
 * 注册 agent/step/end listener，在每个 agent step 结束后执行反射决策。
 * 5 种决策 (CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE) 经 IPC
 * 调用 Python server 的 reflection 方法校验后，映射到 Harness 步骤控制。
 *
 * 映射: C层(Reflector) → agent/step/end listener → reflection IPC
 * 对应文档: RESEARCH_SACG_HARNESS_MAPPING.md §C层
 *
 * Phase 1: 校验 + 记录决策，映射为日志 + session 状态
 * HC-7: 失败时降级为 CONTINUE (FAIL-OPEN)，不阻塞 agent loop
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

const name = "dreambuddy-reflector";
const inject = [];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(true),
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

/** 合法的反思维决策 */
const VALID_DECISIONS = [
  "CONTINUE",
  "REDO",
  "INSERT_BEFORE",
  "JUMP_TO",
  "EARLY_TERMINATE",
];

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
 * 从 session/step 结果推导反射决策
 * Phase 1 回退方案：当 decide 模式不可用时使用关键词启发式
 */
function deriveReflectionDecision(session) {
  const step = session?.step ?? 0;
  const messages = session?.messages || [];
  const lastMsg = messages[messages.length - 1];
  let text = "";
  if (typeof lastMsg === "string") {
    text = lastMsg.toLowerCase();
  } else if (lastMsg?.content) {
    text = (typeof lastMsg.content === "string"
      ? lastMsg.content
      : JSON.stringify(lastMsg.content)
    ).toLowerCase();
  }

  if (/(重做|重新|retry|redo|再来一次)/.test(text)) {
    return { decision: "REDO", reason: "agent 请求重做当前步骤" };
  }
  if (/(终止|结束|完成|terminate|stop|enough)/.test(text) && step >= 2) {
    return { decision: "EARLY_TERMINATE", reason: "agent 表示已有足够信息" };
  }
  return { decision: "CONTINUE", reason: "正常继续下一步" };
}

/**
 * Phase 2: 从 session 构建 Reflector.decide() 所需的上下文参数
 *
 * 收集:
 *  - current_node_id: 当前节点 ID
 *  - confidence/direction: 从最近 tool 结果提取
 *  - executed_count: 当前 step 数
 *  - max_nodes: 从 graph_planner 的 ExecutionPlan 获取
 *  - budget_remaining_ratio: 从 ExecutionPlan.budget 计算
 *  - prev_results: 前序节点结果（从 session 历史提取）
 */
function buildDecideParams(session) {
  const step = session?.step ?? 0;
  const plan = session?.dreamosPlan;
  const messages = session?.messages || [];

  // 从最近消息中提取置信度和方向（Phase 2 简化：从文本关键词推断方向）
  let direction = null;
  let confidence = 0.5;
  for (let i = messages.length - 1; i >= 0; i--) {
    const msg = messages[i];
    const content = typeof msg === "string" ? msg : (msg?.content || "");
    const text = (typeof content === "string" ? content : JSON.stringify(content)).toLowerCase();
    if (/long|做多|买入|看涨|bullish/.test(text)) {
      direction = "LONG";
      confidence = 0.7;
      break;
    }
    if (/short|做空|卖出|看跌|bearish/.test(text)) {
      direction = "SHORT";
      confidence = 0.7;
      break;
    }
    if (/hold|观望|中性|neutral/.test(text)) {
      direction = "HOLD";
      confidence = 0.5;
      break;
    }
  }

  // 从 graph_planner 的 plan 中获取预算和节点数
  const selectedNodes = plan?.selected_nodes || [];
  const maxNodes = selectedNodes.length > 0 ? selectedNodes.length : 5;

  // 计算预算剩余比例
  let budgetRemainingRatio = null;
  const budget = plan?.budget;
  if (budget) {
    const total = budget.total_budget || budget.total || 0;
    const remaining = budget.remaining ?? (total - (budget.used || 0));
    if (total > 0) {
      budgetRemainingRatio = Math.max(0, Math.min(1, remaining / total));
    }
  }

  // 前序节点结果（从 session 历史简化提取）
  const prevResults = [];
  if (session?.dreamosNodeResults) {
    for (const [nid, r] of Object.entries(session.dreamosNodeResults)) {
      prevResults.push({
        node_id: nid,
        direction: r.direction || null,
        confidence: r.confidence ?? 0.5,
      });
    }
  }

  return {
    mode: "decide",
    current_node_id: session?.currentNodeId || `step-${step}`,
    confidence,
    direction,
    status: "SUCCESS",
    executed_count: step,
    max_nodes: maxNodes,
    budget_remaining_ratio: budgetRemainingRatio,
    prev_results: prevResults,
  };
}

/**
 * 将反射决策映射为 Harness 步骤控制动作
 * Phase 1: 记录到 session 并返回日志
 * Phase 2: 实际控制 agent loop（REDO→重跑, JUMP_TO→跳转, EARLY_TERMINATE→终止）
 */
function mapDecisionToAction(decision, params) {
  const action = {
    CONTINUE: { type: "continue", label: "继续下一步" },
    REDO: { type: "redo", label: "重做当前步骤" },
    INSERT_BEFORE: { type: "insert_before", label: `在步骤 ${params?.target_step} 前插入` },
    JUMP_TO: { type: "jump_to", label: `跳转到步骤 ${params?.target_step}` },
    EARLY_TERMINATE: { type: "early_terminate", label: "提前终止" },
  };
  return action[decision] || action.CONTINUE;
}

/**
 * 默认降级决策（FAIL-OPEN 用）
 */
function degradedDecision(reason) {
  return {
    decision: "CONTINUE",
    reason: `[degraded] ${reason}`,
    _source: "plugin_fail_open",
  };
}

/**
 * Phase 3: 根据反射决策实际控制 agent loop
 *
 * 控制策略:
 * - CONTINUE: 清除控制标记，next() 继续
 * - REDO: 设置 dreamosControl={action:"redo"}，pre-step 时重新执行
 * - INSERT_BEFORE: 设置 dreamosControl={action:"insert_before", insert_node_id}
 * - JUMP_TO: 设置 dreamosControl={action:"jump_to", target_node_id}
 * - EARLY_TERMINATE: ctx.emit("agent/turn-stopping") 终止 turn，不调用 next()
 *
 * @param ctx Cordis context（用于 emit turn-stopping）
 * @param session Harness session
 * @param decision 反射决策
 * @param params IPC 回传参数（含 target_step / insert_node_id / jump_to）
 * @param next 中间件 next 函数
 */
async function applyReflectionControl(ctx, session, decision, params, next) {
  const step = session?.step ?? 0;
  const reason = params?.reason || "";

  switch (decision) {
    case "CONTINUE":
      // 清除任何遗留的控制标记
      session.dreamosControl = null;
      return await next();

    case "REDO":
      session.dreamosControl = {
        action: "redo",
        step,
        reason: reason || "低置信度/节点失败，重新执行",
      };
      console.log(`[Reflector] → 设置 REDO 标记 step=${step}`);
      return await next();

    case "INSERT_BEFORE": {
      const insertNodeId = params?.insert_node_id || params?.target_step;
      session.dreamosControl = {
        action: "insert_before",
        insert_node_id: insertNodeId,
        step,
        reason: reason || "方向矛盾，插入补充节点",
      };
      console.log(`[Reflector] → 设置 INSERT_BEFORE 标记 node=${insertNodeId}`);
      return await next();
    }

    case "JUMP_TO": {
      const targetNodeId = params?.jump_to || params?.target_step;
      session.dreamosControl = {
        action: "jump_to",
        target_node_id: targetNodeId,
        step,
        reason: reason || "预算不足/高置信度，跳转至收尾节点",
      };
      console.log(`[Reflector] → 设置 JUMP_TO 标记 node=${targetNodeId}`);
      return await next();
    }

    case "EARLY_TERMINATE":
      // 直接终止 turn，不调用 next()
      console.log(`[Reflector] → EARLY_TERMINATE: ${reason}`);
      session.dreamosControl = {
        action: "terminate",
        step,
        reason,
      };
      try {
        ctx.emit("agent/turn-stopping", {
          reason: reason || "Reflector 决策提前终止",
          source: "dreamos_reflector",
          step,
        });
      } catch (e) {
        console.warn(`[Reflector] emit turn-stopping 失败: ${e.message}`);
      }
      // 不调用 next()，终止执行链
      return undefined;

    default:
      // 未知决策 → FAIL-OPEN: 继续
      session.dreamosControl = null;
      return await next();
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

  // C 层: 在 agent/step/end 执行反射决策
  ctx.on("agent/step/end", async (session, next) => {
    try {
      await ensureStarted();

      let decision;
      let reason;
      let echoParams = {};
      let reflectionSource = "keyword_heuristic";

      // Phase 2: 优先使用真实 Reflector.decide()（基于置信度/预算/矛盾）
      const decideParams = buildDecideParams(session);
      try {
        const decideResponse = await ipcClient.callMethod("reflection", decideParams);
        const decideResult = decideResponse.result || {};
        const decideEcho = decideResult.echo?.params || {};
        if (decideEcho.decision) {
          decision = decideEcho.decision;
          reason = decideEcho.reason;
          echoParams = decideEcho;
          reflectionSource = decideResult.reflection_source || "dreamos_reflector_decide";
        }
      } catch (decideErr) {
        // decide 模式失败 → 回退到关键词启发式 + validate 模式
        console.warn(`[Reflector] decide 模式失败，回退启发式: ${decideErr.message}`);
      }

      // 回退方案：关键词启发式 + validate 校验
      if (!decision) {
        const heuristic = deriveReflectionDecision(session);
        decision = heuristic.decision;
        reason = heuristic.reason;
        const validateResponse = await ipcClient.callMethod("reflection", {
          decision,
          reason,
        });
        const validateResult = validateResponse.result || {};
        echoParams = validateResult.echo?.params || {};
        decision = echoParams.decision || decision;
        reflectionSource = "keyword_heuristic";
      }

      // 映射决策到动作
      const action = mapDecisionToAction(decision, echoParams);

      // 存储反射决策到 session context
      session.dreamosReflection = {
        decision,
        action,
        step: session?.step ?? 0,
        reason: echoParams.reason || reason,
        executed: true,
        source: reflectionSource,
        confidence: echoParams.confidence,
      };

      console.log(
        `[Reflector] step=${session?.step ?? 0} decision=${decision} ` +
          `action=${action.type} source=${reflectionSource}`
      );

      // ── Phase 3: 根据决策实际控制 agent loop ──────────────────
      return applyReflectionControl(ctx, session, decision, echoParams, next);
    } catch (e) {
      // 异常 → FAIL-OPEN: 降级为 CONTINUE，不阻塞 agent loop
      console.warn(`[Reflector] 异常，FAIL-OPEN: ${e.message}`);
      const degraded = degradedDecision(e.message);
      session.dreamosReflection = degraded;
      // FAIL-OPEN: 清除控制标记，继续执行
      session.dreamosControl = null;
      return await next();
    }
  });

  // Phase 3: agent/pre-step 检测 dreamosControl 标记，执行 REDO/JUMP_TO/INSERT_BEFORE
  ctx.on("agent/pre-step", async (session, next) => {
    const control = session?.dreamosControl;
    if (!control || !control.action) {
      return await next();
    }

    const { action, target_node_id, insert_node_id, reason, step } = control;

    try {
      switch (action) {
        case "redo":
          // REDO: 标记当前 step 需重新执行
          // agent loop 会重新调用当前 step 的 tool
          console.log(`[Reflector] REDO step=${step}: ${reason}`);
          // 清除标记，避免无限循环
          session.dreamosControl = null;
          session._dreamosRedoStep = step;
          break;

        case "jump_to":
          // JUMP_TO: 跳过中间 steps，直接执行目标节点
          console.log(`[Reflector] JUMP_TO node=${target_node_id}: ${reason}`);
          session.dreamosControl = null;
          session._dreamosJumpTo = target_node_id;
          break;

        case "insert_before":
          // INSERT_BEFORE: 动态注册补充节点 tool
          console.log(`[Reflector] INSERT_BEFORE node=${insert_node_id}: ${reason}`);
          session.dreamosControl = null;
          session._dreamosInsertBefore = insert_node_id;
          break;

        default:
          session.dreamosControl = null;
          break;
      }
    } catch (e) {
      console.warn(`[Reflector] pre-step 控制异常，FAIL-OPEN: ${e.message}`);
      session.dreamosControl = null;
    }

    return await next();
  });

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export {
  Config,
  apply,
  inject,
  name,
  deriveReflectionDecision,
  buildDecideParams,
  mapDecisionToAction,
  applyReflectionControl,
  degradedDecision,
  VALID_DECISIONS,
};
