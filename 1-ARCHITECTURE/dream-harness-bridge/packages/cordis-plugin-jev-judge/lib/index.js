/**
 * DreamBuddy Jev Judge Cordis plugin
 *
 * 将 TypeSafe Jev (System One Model) 作为 Harness 的决策判断层，
 * 挂载三个关键生命周期事件：
 *   1. agent/turn-stopping — 工作验收：任务是否完成？完成质量如何？
 *   2. agent/pre-step      — 方向裁决（可选）：意图路由辅助
 *   3. agent/step/end      — 反思增强：步骤产出是否合格？
 *
 * Phase 2 (confidence-gated 控制):
 *   - turn-stopping: 高置信度完成 → 放行停止；低置信度 → 可配置阻止停止
 *   - step/end: 低置信度不合格 → 设置 dreamosControl.redo 触发重执行
 *   - pre-step: 高置信度意图 → 记录到 session 供路由使用
 *
 * 边界守护（HC-9 硬约束）:
 * - 只调用 IPC（jev_judge），不做任何交易判断
 * - 不出现交易判断逻辑（direction/position/size/pnl 等）
 *
 * HC-7 FAIL-OPEN:
 * - Jev 调用失败/超时/degraded → 放行，不阻塞 agent loop
 * - 所有控制逻辑都有 FAIL-OPEN 兜底（降级时一律 next() 放行）
 *
 * 来源: Jev 引入调研（2026-09-22）
 */

import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";
import { readFileSync, existsSync } from "node:fs";
import z from "@deepseek-ai/schemastery";

const __dirname = dirname(fileURLToPath(import.meta.url));

/**
 * 从 .env 文件加载环境变量（简单解析，支持 KEY=VALUE 和 # 注释）
 * 不会覆盖已存在的 process.env 变量（shell 环境变量优先）
 */
function loadEnvFile(serverPath) {
  // .env 位于 dream-harness-bridge 根目录（server.py 的上两级）
  const bridgeRoot = resolve(dirname(serverPath), "..", "..");
  const envPath = resolve(bridgeRoot, ".env");
  if (!existsSync(envPath)) return {};

  const envVars = {};
  try {
    const content = readFileSync(envPath, "utf-8");
    for (const line of content.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed || trimmed.startsWith("#")) continue;
      const eqIdx = trimmed.indexOf("=");
      if (eqIdx === -1) continue;
      const key = trimmed.slice(0, eqIdx).trim();
      let value = trimmed.slice(eqIdx + 1).trim();
      // 去除引号
      if (
        (value.startsWith('"') && value.endsWith('"')) ||
        (value.startsWith("'") && value.endsWith("'"))
      ) {
        value = value.slice(1, -1);
      }
      envVars[key] = value;
    }
  } catch {
    // 读取失败，忽略
  }
  return envVars;
}

const name = "dreambuddy-jev-judge";
const inject = [];

const Config = z.object({
  pythonServerPath: z.string().default(""),
  pythonExecutable: z.string().default("python3"),
  enabled: z.boolean().default(true),
  // 各场景开关
  enableCompletionCheck: z.boolean().default(true), // turn-stopping 工作验收
  enableStepQuality: z.boolean().default(true), // step/end 步骤质量
  enableIntentRouting: z.boolean().default(false), // pre-step 意图路由（默认关闭）
  // Phase 2: confidence-gated 控制开关
  enableHardStopBlock: z.boolean().default(false), // 低置信度时是否强制阻止停止（默认关闭，安全第一）
  // 置信度门槛
  completionThreshold: z.number().default(0.85), // 任务完成置信度阈值（≥此值允许停止）
  completionLowThreshold: z.number().default(0.50), // 任务完成低阈值（<此值且 enableHardStopBlock 时阻止停止）
  stepQualityThreshold: z.number().default(0.7), // 步骤质量阈值（≥此值放行）
  stepQualityLowThreshold: z.number().default(0.4), // 步骤质量低阈值（<此值触发 REDO）
  intentRoutingThreshold: z.number().default(0.7), // 意图路由置信度阈值
  // 路径B: criteria override（领域特定 criteria 定制，空=用默认）
  // 来源: 路径B 实施（2026-09-22）
  completionCriteria: z.array(z.string()).default([]), // 完成度 score criteria override（空数组=用默认 4 项通用完成度）
  intentCriteria: z.any().default({}), // 意图 choice criteria override（空对象=用默认 6 类交易域意图）
});

const CURRENT_SCHEMA_VERSION = "1.0.0";

// ============================================================
// 默认 criteria 常量（override 空时 fallback 使用）
// 来源: 路径B 实施（2026-09-22）—— 从 checkCompletion/checkIntentRouting 提取
// ============================================================

const DEFAULT_COMPLETION_CRITERIA = [
  "未完成或严重偏离需求",
  "部分完成，有明显遗漏",
  "基本完成，小问题不影响使用",
  "高质量完成，完全满足需求",
];

const DEFAULT_INTENT_CRITERIA = {
  market_query: "查询行情、价格、数据",
  trend_analysis: "趋势分析、技术分析",
  trading_decision: "交易决策、开仓平仓",
  risk_analysis: "风险评估、仓位管理",
  strategy_recommendation: "策略建议、方案设计",
  other: "其他或无法分类",
};

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

      // 加载 .env 文件中的环境变量（shell 环境变量优先，不覆盖）
      const envFromFile = loadEnvFile(this.serverPath);
      const mergedEnv = { ...envFromFile, ...process.env };

      this.process = spawn(this.executable, [this.serverPath], {
        stdio: ["pipe", "pipe", "pipe"],
        env: mergedEnv,
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
            const parsed = JSON.parse(line);
            const hasVersion = typeof parsed.schema_version === "string";
            const isResponse = parsed.message_type === "response";
            if (hasVersion && isResponse) {
              const pending = this.pendingRequests.get(parsed.id);
              if (pending) {
                this.pendingRequests.delete(parsed.id);
                pending(parsed);
              }
            }
          } catch {
            // 非 JSON 行，忽略
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
        reject(new Error(`IPC 请求超时: ${request.method || request.message_type}`));
      }, 15000);

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

// ============================================================
// 工具函数
// ============================================================

/**
 * 从 session.messages 中提取文本内容
 */
function extractTextFromMessages(messages) {
  if (!Array.isArray(messages)) return "";
  return messages
    .map((m) => {
      if (typeof m === "string") return m;
      const content = m?.content;
      if (typeof content === "string") return content;
      if (Array.isArray(content)) {
        return content
          .filter((c) => typeof c === "string" || c?.type === "text")
          .map((c) => (typeof c === "string" ? c : c.text || ""))
          .join(" ");
      }
      return "";
    })
    .join("\n")
    .slice(0, 30000); // 限制 token 预算（~30k chars）
}

/**
 * 调用 jev_judge IPC，返回结构化结果
 * FAIL-OPEN: 任何异常返回 null
 */
async function callJevJudge(ipcClient, state, questions) {
  try {
    const response = await ipcClient.callMethod("jev_judge", { state, questions });
    if (response.ok && response.result && !response.result.degraded) {
      return response.result;
    }
    return null;
  } catch (e) {
    console.warn(`[JevJudge] IPC 调用失败: ${e.message}`);
    return null;
  }
}

// ============================================================
// 场景 1: 工作验收（agent/turn-stopping）
// ============================================================

/**
 * 工作验收：判断任务是否完成 + 完成质量
 * 复用 anasbekheit evaluate 契约：noul + score 并行
 */
async function checkCompletion(ipcClient, session, config = {}) {
  const messages = session?.messages || [];
  const state = {
    task: extractTextFromMessages(messages.slice(0, 3)), // 前 3 条 = 原始需求
    current_output: extractTextFromMessages(messages.slice(-3)), // 后 3 条 = 最新产出
    step: session?.step ?? 0,
  };

  // 路径B: criteria override 优先，空则 fallback 默认（HC-9 通用判断不变）
  const criteria =
    Array.isArray(config.completionCriteria) && config.completionCriteria.length > 0
      ? config.completionCriteria
      : DEFAULT_COMPLETION_CRITERIA;

  const questions = {
    task_complete: {
      type: "noul",
      instructions: "这个任务是否已经完成，满足了用户的原始需求？",
    },
    quality_score: {
      type: "score",
      instructions: "完成质量如何？",
      criteria,
    },
  };

  return callJevJudge(ipcClient, state, questions);
}

// ============================================================
// 场景 2: 步骤质量（agent/step/end）
// ============================================================

/**
 * 步骤质量判断：当前步骤产出是否合格
 */
async function checkStepQuality(ipcClient, session) {
  const messages = session?.messages || [];
  const state = {
    step: session?.step ?? 0,
    step_output: extractTextFromMessages(messages.slice(-2)), // 最近 2 条
  };

  const questions = {
    step_passed: {
      type: "noul",
      instructions: "这个步骤的产出是否达到了预期目标，没有明显错误？",
    },
  };

  return callJevJudge(ipcClient, state, questions);
}

// ============================================================
// 场景 3: 意图路由（agent/pre-step，默认关闭）
// ============================================================

/**
 * 意图路由辅助：从候选意图中选择
 */
async function checkIntentRouting(ipcClient, session, config = {}) {
  const messages = session?.messages || [];
  const lastMessage = messages[messages.length - 1];
  const userInput =
    typeof lastMessage === "string"
      ? lastMessage
      : typeof lastMessage?.content === "string"
        ? lastMessage.content
        : "";

  const state = { user_input: userInput, step: session?.step ?? 0 };

  // 路径B: criteria override 优先，空则 fallback 默认
  const criteria =
    config.intentCriteria && typeof config.intentCriteria === "object" &&
    Object.keys(config.intentCriteria).length > 0
      ? config.intentCriteria
      : DEFAULT_INTENT_CRITERIA;

  const questions = {
    intent: {
      type: "choice",
      instructions: "用户意图属于哪一类？",
      criteria,
    },
  };

  return callJevJudge(ipcClient, state, questions);
}

// ============================================================
// apply: 注册事件监听器
// ============================================================

function apply(ctx, config = {}) {
  const serverPath =
    config.pythonServerPath ||
    resolve(__dirname, "../../python-server/server.py");
  const executable = config.pythonExecutable || "python3";
  const enabled = config.enabled !== false;

  if (!enabled) return;

  const enableCompletionCheck = config.enableCompletionCheck !== false;
  const enableStepQuality = config.enableStepQuality !== false;
  const enableIntentRouting = config.enableIntentRouting === true;
  const enableHardStopBlock = config.enableHardStopBlock === true;
  const completionThreshold = config.completionThreshold ?? 0.85;
  const completionLowThreshold = config.completionLowThreshold ?? 0.50;
  const stepQualityThreshold = config.stepQualityThreshold ?? 0.7;
  const stepQualityLowThreshold = config.stepQualityLowThreshold ?? 0.4;
  const intentRoutingThreshold = config.intentRoutingThreshold ?? 0.7;

  const ipcClient = new PythonIPCClient(executable, serverPath);
  let startPromise = null;

  async function ensureStarted() {
    if (!startPromise) {
      startPromise = ipcClient.start();
    }
    return startPromise;
  }

  // ----------------------------------------------------------
  // 场景 1: agent/turn-stopping — 工作验收 (Phase 2: confidence-gated)
  // ----------------------------------------------------------
  if (enableCompletionCheck) {
    ctx.on("agent/turn-stopping", async (session, next) => {
      try {
        await ensureStarted();
        const result = await checkCompletion(ipcClient, session, config);

        if (result && result.answers) {
          const completeNoul = result.answers.task_complete?.noul ?? 0;
          const qualityScore = result.answers.quality_score?.score ?? 0;

          // 记录到 session 状态
          session.jevCompletion = {
            task_complete: completeNoul,
            quality_score: qualityScore,
            model: result.model,
          };
          if (completeNoul >= completionThreshold) {
            // 高置信度完成 → 放行停止
            console.log(
              `[JevJudge] 工作验收通过: complete=${completeNoul.toFixed(2)}, quality=${qualityScore.toFixed(2)} → 放行停止`
            );
            return await next();
          } else if (completeNoul < completionLowThreshold && enableHardStopBlock) {
            // 低置信度 + 启用强制阻止 → 阻止停止（不调用 next()）
            console.log(
              `[JevJudge] 工作验收未达低阈值: complete=${completeNoul.toFixed(2)} (low=${completionLowThreshold}) → 阻止停止，要求继续`
            );
            session.jevForceContinue = true;
            return; // 不调用 next()，阻止 turn 停止
          } else {
            // 中间区间 → 记录但放行
            console.log(
              `[JevJudge] 工作验收中间区间: complete=${completeNoul.toFixed(2)} (low=${completionLowThreshold}, high=${completionThreshold}) → 放行`
            );
            return await next();
          }
        } else {
          // Jev 不可用 → FAIL-OPEN 放行
          console.log("[JevJudge] 工作验收降级（Jev 不可用），FAIL-OPEN 放行");
          return await next();
        }
      } catch (e) {
        // 异常 → FAIL-OPEN 放行
        console.warn(`[JevJudge] 工作验收异常，FAIL-OPEN 放行: ${e.message}`);
        return await next();
      }
    });
  }

  // ----------------------------------------------------------
  // 场景 2: agent/step/end — 步骤质量 (Phase 2: confidence-gated REDO)
  // ----------------------------------------------------------
  if (enableStepQuality) {
    ctx.on("agent/step/end", async (session, next) => {
      try {
        await ensureStarted();
        const result = await checkStepQuality(ipcClient, session);

        if (result && result.answers) {
          const passedNoul = result.answers.step_passed?.noul ?? 0;

          session.jevStepQuality = {
            step_passed: passedNoul,
            model: result.model,
          };

          if (passedNoul >= stepQualityThreshold) {
            // 高置信度合格 → 放行
            console.log(
              `[JevJudge] 步骤质量合格: passed=${passedNoul.toFixed(2)} → 放行`
            );
          } else if (passedNoul < stepQualityLowThreshold) {
            // 低置信度不合格 → 设置 dreamosControl.redo，配合 reflector 重执行
            session.dreamosControl = {
              action: "redo",
              source: "jev_judge",
              reason: `step_quality_low: ${passedNoul.toFixed(2)} < ${stepQualityLowThreshold}`,
            };
            console.log(
              `[JevJudge] 步骤质量不合格: passed=${passedNoul.toFixed(2)} (low=${stepQualityLowThreshold}) → 触发 REDO`
            );
          } else {
            // 中间区间 → 放行
            console.log(
              `[JevJudge] 步骤质量中间区间: passed=${passedNoul.toFixed(2)} → 放行`
            );
          }
        }
      } catch (e) {
        console.warn(`[JevJudge] 步骤质量检查异常，FAIL-OPEN 放行: ${e.message}`);
      }

      // 放行（REDO 通过 dreamosControl 标记由 reflector pre-step 处理）
      return await next();
    });
  }

  // ----------------------------------------------------------
  // 场景 3: agent/pre-step — 意图路由 (Phase 2: confidence-gated)
  // ----------------------------------------------------------
  if (enableIntentRouting) {
    ctx.on("agent/pre-step", async (session, next) => {
      try {
        await ensureStarted();
        const result = await checkIntentRouting(ipcClient, session, config);

        if (result && result.answers) {
          const intent = result.answers.intent;
          const confidence = intent?.confidence ?? 0;

          session.jevIntent = {
            choice: intent?.choice,
            confidence: confidence,
            model: result.model,
          };

          if (confidence >= intentRoutingThreshold) {
            // 高置信度意图 → 记录到 session 供后续路由决策使用
            console.log(
              `[JevJudge] 意图路由命中: ${intent.choice} (confidence=${confidence.toFixed(2)} >= ${intentRoutingThreshold})`
            );
          } else {
            // 低置信度 → 清除意图，走原有逻辑
            session.jevIntent = null;
            console.log(
              `[JevJudge] 意图路由低置信度: confidence=${confidence.toFixed(2)} < ${intentRoutingThreshold} → 忽略`
            );
          }
        }
      } catch (e) {
        console.warn(`[JevJudge] 意图路由异常，FAIL-OPEN 放行: ${e.message}`);
      }

      return await next();
    });
  }

  ctx.on("dispose", () => {
    ipcClient.stop();
  });
}

export { Config, apply, inject, name };
