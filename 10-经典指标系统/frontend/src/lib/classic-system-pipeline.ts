/**
 * Classic System Strategy Pipeline
 *
 * 将 Dreambuddy-v2 策略输出自动推送到 classic-indicators-ml-system
 * 完整治理流程：
 *
 * [Dreambuddy S思维链]
 *         ↓
 *   Draft 策略注入 → Gate 评估 → 审批流程 → Apply 应用 → 审计追踪
 *         ↓                       ↓
 *   (可选回测验证)           Signal 信号系统
 *
 * 同时提供：
 * - 策略库查询：将 classic-system 策略库作为知识库供 Dreambuddy 使用
 * - 系统监控：审批状态、回滚点、运行健康查询
 */

import { transformToClassicDraft, generateBacktestConfig, type CompleteStrategyChain } from "./classic-system-bridge";

const CLASSIC_BASE = "http://127.0.0.1:8092";

/**
 * 流程阶段枚举
 */
export const PipelinePhase = {
  DRAFT: "draft",
  GATE: "gate",
  APPROVAL: "approval",
  APPLY: "apply",
  AUDIT: "audit",
} as const;

export type PipelinePhaseType = typeof PipelinePhase[keyof typeof PipelinePhase];

/**
 * 流程状态
 */
export interface PipelineState {
  phase: PipelinePhaseType;
  success: boolean;
  message: string;
  data?: any;
  timestamp: number;
}

/**
 * pipeline 运行时选项
 */
export interface PipelineOptions {
  runBacktest?: boolean;
  autoApproval?: boolean;
  maxWaitMs?: number;
  onProgress?: (state: PipelineState) => void;
}

/**
 * pipeline 完整运行结果
 */
export interface PipelineResult {
  success: boolean;
  strategyName: string;
  traceId: string;
  changesetId?: string;
  approvalId?: string;
  steps: PipelineState[];
  error?: string;
}

/**
 * 管道辅助：统一请求
 */
async function classicRequest(endpoint: string, options: RequestInit = {}): Promise<any> {
  try {
    const response = await fetch(`${CLASSIC_BASE}${endpoint}`, {
      headers: { "Content-Type": "application/json", ...options.headers },
      ...options,
    });
    return await response.json();
  } catch (error: any) {
    console.error(`[ClassicPipeline] Request failed: ${endpoint}`, error);
    return { ok: false, error: error?.message || "request_failed" };
  }
}

/**
 * Stage 1: 创建策略 Draft
 * 将 S思维链输出转换为 classic-system 可理解的变更草案
 */
export async function pushStrategyDraft(
  chain: CompleteStrategyChain
): Promise<PipelineState> {
  const payload = transformToClassicDraft(chain);

  try {
    const result = await classicRequest("/agent/changeset/draft", {
      method: "POST",
      body: JSON.stringify(payload),
    });

    return {
      phase: PipelinePhase.DRAFT,
      success: result?.ok ?? false,
      message: result?.ok ? `Draft已创建: ${payload.strategy_name}` : "Draft创建失败",
      data: result,
      timestamp: Date.now(),
    };
  } catch (error: any) {
    return {
      phase: PipelinePhase.DRAFT,
      success: false,
      message: error?.message || "Draft推送异常",
      timestamp: Date.now(),
    };
  }
}

/**
 * Stage 2: Gate评估 - 验证策略是否符合上线标准
 */
export async function runGateEval(
  payload: any,
  draftResult?: PipelineState
): Promise<PipelineState> {
  const changeset = draftResult?.data?.changeset_id || payload?.trace_id || `cs-${Date.now()}`;

  try {
    const result = await classicRequest("/evaluation/gate/check", {
      method: "POST",
      body: JSON.stringify({
        changeset_id: changeset,
        strategy_name: payload?.strategy_name || "unknown",
        gate_checks: payload?.gate_result?.checks || {},
        metrics: payload?.gate_result?.metrics || {},
        risks: payload?.gate_result?.risks || [],
      }),
    });

    return {
      phase: PipelinePhase.GATE,
      success: result?.ok ?? result?.pass ?? false,
      message: result?.ok
        ? `Gate评估通过 (风险项: ${payload?.gate_result?.risks?.length || 0})`
        : `Gate评估未通过: ${result?.reasons?.[0] || "未满足所有检查"}`,
      data: result,
      timestamp: Date.now(),
    };
  } catch (error: any) {
    return {
      phase: PipelinePhase.GATE,
      success: false,
      message: error?.message || "Gate评估异常",
      timestamp: Date.now(),
    };
  }
}

/**
 * Stage 3: 申请审批
 */
export async function requestApproval(
  payload: any,
  gateResult?: PipelineState
): Promise<PipelineState> {
  try {
    const result = await classicRequest("/agent/approvals/request", {
      method: "POST",
      body: JSON.stringify({
        strategy_name: payload?.strategy_name || "unknown",
        changeset_id: gateResult?.data?.changeset_id || payload?.trace_id || "",
        request_type: "strategy_deployment",
        reason: payload?.changeset?.reason || "策略变更申请",
        priority: gateResult?.success ? "normal" : "high",
        gate_pass: gateResult?.success ?? true,
        risks: payload?.gate_result?.risks || [],
      }),
    });

    return {
      phase: PipelinePhase.APPROVAL,
      success: result?.ok ?? false,
      message: result?.ok
        ? `审批请求已提交 (ID: ${result?.approval_id || result?.data?.approval_id || "N/A"})`
        : `审批请求提交失败`,
      data: result,
      timestamp: Date.now(),
    };
  } catch (error: any) {
    return {
      phase: PipelinePhase.APPROVAL,
      success: false,
      message: error?.message || "审批请求异常",
      timestamp: Date.now(),
    };
  }
}

/**
 * Stage 4: Apply 变更（策略部署到交易系统）
 */
export async function applyChangeset(
  payload: any,
  approvalResult?: PipelineState
): Promise<PipelineState> {
  try {
    const result = await classicRequest("/governance/changeset/apply", {
      method: "POST",
      body: JSON.stringify({
        strategy_name: payload?.strategy_name || "unknown",
        changeset_id: approvalResult?.data?.changeset_id || payload?.trace_id || "",
        mode: approvalResult?.success ? "apply" : "dry_run",
        param_overrides: payload?.changeset?.param_overrides || {},
      }),
    });

    return {
      phase: PipelinePhase.APPLY,
      success: result?.ok ?? false,
      message: result?.ok
        ? `策略已应用到交易系统`
        : `策略应用失败: ${result?.error || "unknown"}`,
      data: result,
      timestamp: Date.now(),
    };
  } catch (error: any) {
    return {
      phase: PipelinePhase.APPLY,
      success: false,
      message: error?.message || "Apply异常",
      timestamp: Date.now(),
    };
  }
}

/**
 * Stage 5: 审计记录
 */
export async function recordAudit(
  payload: any,
  steps: PipelineState[]
): Promise<PipelineState> {
  try {
    const result = await classicRequest("/agent/audit/record", {
      method: "POST",
      body: JSON.stringify({
        strategy_name: payload?.strategy_name || "unknown",
        trace_id: payload?.trace_id || "",
        action: "strategy_deployment",
        status: steps.every(s => s.success) ? "success" : "partial",
        evidence: payload?.evidence || [],
        doc_refs: payload?.doc_refs || [],
        summary: `完整治理流程: ${steps.map(s => s.phase).join("→")}`,
      }),
    });

    return {
      phase: PipelinePhase.AUDIT,
      success: result?.ok ?? false,
      message: result?.ok ? "审计记录完成" : "审计记录未写入",
      data: result,
      timestamp: Date.now(),
    };
  } catch (error: any) {
    return {
      phase: PipelinePhase.AUDIT,
      success: false,
      message: error?.message || "审计异常",
      timestamp: Date.now(),
    };
  }
}

/**
 * 完整策略推送流程编排
 * 接收 Dreambuddy-v2 S思维链输出，自动执行完整治理流程
 */
export async function runStrategyPipeline(
  chain: CompleteStrategyChain,
  options: PipelineOptions = {}
): Promise<PipelineResult> {
  const { runBacktest = false, autoApproval = true, onProgress } = options;
  const payload = transformToClassicDraft(chain);
  const steps: PipelineState[] = [];

  const notify = (state: PipelineState) => {
    steps.push(state);
    onProgress?.(state);
  };

  try {
    // 阶段1: Draft创建
    const draftResult = await pushStrategyDraft(chain);
    notify(draftResult);
    if (!draftResult.success) {
      return buildFailure(steps, payload, "Draft创建失败");
    }

    // 阶段1.5: 可选回测验证
    if (runBacktest && chain.s3?.strategyName) {
      const backtestTask = await BacktestAPI.runBacktest(chain);
      notify({
        phase: "draft",
        success: backtestTask?.ok ?? false,
        message: backtestTask?.ok
          ? `回测任务已启动 (ID: ${backtestTask?.task_id || "N/A"})`
          : "回测启动失败，跳过回测",
        data: backtestTask,
        timestamp: Date.now(),
      });
    }

    // 阶段2: Gate评估
    const gateResult = await runGateEval(payload, draftResult);
    notify(gateResult);
    if (!gateResult.success && !autoApproval) {
      return buildFailure(steps, payload, "Gate评估未通过");
    }

    // 阶段3: 审批请求
    const approvalResult = await requestApproval(payload, gateResult);
    notify(approvalResult);

    // 阶段4: Apply变更
    const applyResult = await applyChangeset(payload, approvalResult);
    notify(applyResult);

    // 阶段5: 审计记录
    const auditResult = await recordAudit(payload, steps);
    notify(auditResult);

    return {
      success: steps.filter(s => s.phase !== PipelinePhase.AUDIT).every(s => s.success),
      strategyName: payload.strategy_name,
      traceId: payload.trace_id,
      changesetId: draftResult?.data?.changeset_id,
      approvalId: approvalResult?.data?.approval_id,
      steps,
    };
  } catch (error: any) {
    return buildFailure(steps, payload, error?.message || "未知错误");
  }
}

function buildFailure(
  steps: PipelineState[],
  payload: any,
  reason: string
): PipelineResult {
  return {
    success: false,
    strategyName: payload?.strategy_name || "unknown",
    traceId: payload?.trace_id || "",
    steps,
    error: reason,
  };
}

// ============================================================
// 策略库集成（知识库）
// ============================================================

/**
 * 查询策略库（供 Dreambuddy 作为知识库使用）
 */
export const StrategyLibraryAPI = {
  /** 查询所有策略 */
  async listStrategies(options: { scope?: string; status?: string; search?: string } = {}) {
    const params = new URLSearchParams();
    if (options.scope) params.set("scope", options.scope);
    if (options.status) params.set("status", options.status);
    if (options.search) params.set("search", options.search);

    return classicRequest(
      `/strategy/inject/list${params.toString() ? `?${params.toString()}` : ""}`,
      { method: "GET" }
    );
  },

  /** 获取单个策略详情 */
  async getStrategy(strategyName: string) {
    return classicRequest(`/strategy/inject/state?strategy=${encodeURIComponent(strategyName)}`, {
      method: "GET",
    });
  },

  /** 获取策略配置详情 */
  async getStrategyConfig(strategyName: string) {
    return classicRequest(
      `/strategy/inject/config?strategy=${encodeURIComponent(strategyName)}`,
      { method: "GET" }
    );
  },

  /** 策略参数预览 */
  async previewStrategyParams(strategyName: string, overrides: Record<string, any> = {}) {
    return classicRequest("/strategy/inject/preview-params", {
      method: "POST",
      body: JSON.stringify({ strategy: strategyName, param_overrides: overrides }),
    });
  },
};

// ============================================================
// 回测集成
// ============================================================

/**
 * 回测相关接口
 */
export const BacktestAPI = {
  /** 启动回测 */
  async runBacktest(chain: CompleteStrategyChain) {
    const config = generateBacktestConfig(chain);
    return classicRequest("/automation/backtest/run", {
      method: "POST",
      body: JSON.stringify(config),
    });
  },

  /** 查询回测状态 */
  async getStatus(taskId: string) {
    return classicRequest(`/automation/backtest/status?task_id=${encodeURIComponent(taskId)}`, {
      method: "GET",
    });
  },

  /** 获取回测结果 */
  async getResult(taskId: string) {
    return classicRequest(`/automation/backtest/result?task_id=${encodeURIComponent(taskId)}`, {
      method: "GET",
    });
  },
};

// ============================================================
// 系统监控接口（审批、回滚、审计查询）
// ============================================================

export const SystemMonitorAPI = {
  /** 获取所有审批 */
  async listApprovals(status?: string) {
    const q = status ? `?status=${encodeURIComponent(status)}` : "";
    return classicRequest(`/agent/approvals/list${q}`, { method: "GET" });
  },

  /** 获取单个审批详情 */
  async getApproval(approvalId: string) {
    return classicRequest(`/agent/approvals/detail?id=${encodeURIComponent(approvalId)}`, {
      method: "GET",
    });
  },

  /** 审批操作（approve/reject） */
  async actionApproval(approvalId: string, action: "approve" | "reject", comment?: string) {
    return classicRequest("/agent/approvals/action", {
      method: "POST",
      body: JSON.stringify({ id: approvalId, action, comment }),
    });
  },

  /** 获取回滚点 */
  async listRollbackPoints(strategyName?: string) {
    const q = strategyName ? `?strategy=${encodeURIComponent(strategyName)}` : "";
    return classicRequest(`/evaluation/rollback/list${q}`, { method: "GET" });
  },

  /** 执行回滚 */
  async rollback(rollbackId: string, reason?: string) {
    return classicRequest("/evaluation/rollback/restore", {
      method: "POST",
      body: JSON.stringify({ id: rollbackId, reason }),
    });
  },

  /** 查询审计记录 */
  async listAudit(options: { strategy?: string; action?: string; limit?: number } = {}) {
    const params = new URLSearchParams();
    if (options.strategy) params.set("strategy", options.strategy);
    if (options.action) params.set("action", options.action);
    if (options.limit) params.set("limit", String(options.limit));

    return classicRequest(
      `/agent/audit/list${params.toString() ? `?${params.toString()}` : ""}`,
      { method: "GET" }
    );
  },

  /** 系统健康检查 */
  async healthCheck() {
    return classicRequest("/agent/api/health", { method: "GET" });
  },
};
