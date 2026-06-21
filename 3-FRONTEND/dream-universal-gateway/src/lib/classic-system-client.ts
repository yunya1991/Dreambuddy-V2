/**
 * Classic Indicators ML System - API Client
 *
 * 与 classic-indicators-ml-system（量化金融核心治理系统）的集成
 *
 * 基础架构：
 * - Dreambuddy-v2 (策略研究/思维链) → classic-system (治理/回测/信号)
 * - 所有调用通过统一的 API 端点：http://127.0.0.1:8092
 *
 * 核心流程：
 * 1. 策略注入 Draft → 回测验证 → Gate 评估 → 审批 → Apply → 审计
 * 2. 策略库查询：提供知识库给 Dreambuddy
 * 3. 系统监控：审批状态、回滚点、运行健康
 */

const CLASSIC_SYSTEM_BASE_URL =
  process.env.NEXT_PUBLIC_CLASSIC_SYSTEM_URL || "http://127.0.0.1:8092";

export interface ClassicResponse<T = any> {
  ok: boolean;
  ts?: number;
  error?: string;
  data?: T;
  [key: string]: any;
}

/**
 * 通用 HTTP 请求函数
 */
async function classicRequest<T = any>(
  endpoint: string,
  options: RequestInit = {}
): Promise<ClassicResponse<T>> {
  try {
    const response = await fetch(`${CLASSIC_SYSTEM_BASE_URL}${endpoint}`, {
      headers: {
        "Content-Type": "application/json",
        ...options.headers,
      },
      ...options,
    });

    const data = await response.json();
    return data as ClassicResponse<T>;
  } catch (error) {
    console.error(`Classic System API Error [${endpoint}]:`, error);
    return {
      ok: false,
      error: error instanceof Error ? error.message : "Network error",
    } as ClassicResponse<T>;
  }
}

// ============================================================
// 1. 健康检查
// ============================================================

export const HealthAPI = {
  /**
   * 获取系统健康状态
   */
  async getHealth() {
    return classicRequest("/health", { method: "GET" });
  },

  /**
   * 系统自检
   */
  async selfcheck() {
    return classicRequest("/selfcheck", { method: "GET" });
  },
};

// ============================================================
// 2. 策略库与知识库 API
// ============================================================

export interface StrategyRegistryEntry {
  strategy_id: string;
  strategy_name?: string;
  description?: string;
  stage?: string;
  family?: string;
  tier?: string;
  source?: {
    kind?: string;
    asset_mirror_path?: string;
    asset_links?: string[];
    repo_url?: string;
    branch?: string;
    file_path?: string;
  };
  updated_at?: number;
  created_at?: number;
  status?: string;
  can_trigger?: boolean;
  direction_capability?: "long_short" | "long_only";
}

export interface StrategyParamsResponse {
  ok: boolean;
  strategies: Record<
    string,
    {
      group_id: string;
      feature_set_id: string;
      params: Record<string, any>;
    }
  >;
}

export const StrategyLibraryAPI = {
  /**
   * 获取策略注册表（作为知识库）
   */
  async getRegistry(): Promise<ClassicResponse<{ entries: StrategyRegistryEntry[] }>> {
    return classicRequest("/strategy/registry", { method: "GET" });
  },

  /**
   * 获取策略参数配置
   */
  async getParams(): Promise<ClassicResponse<StrategyParamsResponse>> {
    return classicRequest("/strategy/params", { method: "GET" });
  },

  /**
   * 获取feeder支持的策略列表及能力
   */
  async getFeederCapabilities() {
    return classicRequest("/strategy/feeder/capabilities", { method: "GET" });
  },

  /**
   * 获取策略库快照
   */
  async getLibrarySnapshot() {
    return classicRequest("/strategy/library/snapshot", { method: "GET" });
  },

  /**
   * 搜索策略（支持多维度过滤）
   */
  async searchStrategies(params: {
    q?: string;
    family?: string;
    stage?: string;
    tier?: string;
    limit?: number;
    offset?: number;
  }) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) query.append(k, String(v));
    });
    return classicRequest(`/search?${query.toString()}`, { method: "GET" });
  },

  /**
   * 获取策略包列表
   */
  async getBundles() {
    return classicRequest("/strategy/bundles", { method: "GET" });
  },

  /**
   * 构建策略包
   */
  async buildBundle(payload: { strategy_ids?: string[]; label?: string }) {
    return classicRequest("/strategy/bundle/build", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};

// ============================================================
// 3. 策略注入与治理 API（核心流程）
// ============================================================

export interface StrategyInjectDraftPayload {
  strategy_name: string;
  strategy_file?: {
    name: string;
    content_b64: string;
    sha256?: string;
  };
  candidate?: Record<string, any>;
  changeset?: {
    reason?: string;
    description?: string;
    version?: string;
    param_overrides?: Record<string, any>;
  };
  doc_refs?: Array<{
    doc_path?: string;
    section?: string;
    rule?: string;
  }>;
  evidence?: Array<{
    type?: string;
    source?: string;
    excerpt?: string;
    [k: string]: any;
  }>;
  gate_result?: Record<string, any>;
  trace_id?: string;
}

export interface StrategyInjectDraftResponse {
  ok: boolean;
  ts?: number;
  draft_id?: string;
  draft?: Record<string, any>;
  error?: string;
}

export interface StrategyApplyResponse {
  ok: boolean;
  ts?: number;
  trace_id?: string;
  draft_id?: string;
  status?: string;
  error?: string;
  before?: Record<string, any>;
  after?: Record<string, any>;
  rollback_point?: string;
}

export const StrategyInjectAPI = {
  /**
   * 创建策略变更草案（Draft 阶段）
   *
   * 这是策略注入的第一步：将策略定义提交到系统，
   * 生成 draft_id，后续的审批、应用都基于此 ID
   */
  async createDraft(
    payload: StrategyInjectDraftPayload
  ): Promise<ClassicResponse<StrategyInjectDraftResponse>> {
    return classicRequest("/strategy/inject/draft", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 请求策略审批（Approval 阶段）
   *
   * 调用此接口后，系统将创建一个待审批的提案，
   * 需获得审批后才能进入 apply 阶段
   */
  async requestApproval(payload: {
    draft_id: string;
    trace_id?: string;
    reason?: string;
    urgent?: boolean;
    category?: string;
  }): Promise<ClassicResponse<{ approval_id?: string; mip_id?: string }>> {
    return classicRequest("/strategy/inject/approval/request", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 应用策略变更（Apply 阶段）
   *
   * 需要先获得审批。此操作会创建回滚点，
   * 然后将策略代码注入到运行系统中
   */
  async apply(payload: {
    draft_id: string;
    trace_id?: string;
    confirm_live?: boolean;
    approval_id?: string;
  }): Promise<ClassicResponse<StrategyApplyResponse>> {
    return classicRequest("/strategy/inject/apply", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 创建变更审查（高级治理流程）
   */
  async reviewChangeset(payload: {
    draft_id?: string;
    changeset?: Record<string, any>;
    reason?: string;
  }) {
    return classicRequest("/governance/changeset/review", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 直接应用变更集
   */
  async applyChangeset(payload: {
    changeset?: Record<string, any>;
    reason?: string;
    confirm_live?: boolean;
  }) {
    return classicRequest("/governance/changeset/apply", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};

// ============================================================
// 4. 回测 API
// ============================================================

export interface BacktestRunPayload {
  config?: string; // config path, default: "user_data/config_local_backtest.json"
  timerange?: string; // e.g. "20240101-20241231"
  strategy?: string; // strategy class name
  strategy_name?: string;
  sandbox_path?: string;
  timeout_sec?: number;
  trace_id?: string;
  env?: Record<string, string>;
}

export interface BacktestResult {
  ok: boolean;
  result_zip?: string;
  metrics_summary?: {
    total_trades?: number;
    win_rate?: number;
    profit_factor?: number;
    sharpe_ratio?: number;
    max_drawdown?: number;
    total_pnl?: number;
  };
  report?: {
    trades?: Array<Record<string, any>>;
    signals?: Array<Record<string, any>>;
    summary?: Record<string, any>;
  };
}

export const BacktestAPI = {
  /**
   * 运行回测
   */
  async runBacktest(
    payload: BacktestRunPayload
  ): Promise<ClassicResponse<BacktestResult>> {
    return classicRequest("/automation/backtest/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 获取自动回测状态
   */
  async getAutoBacktestStatus() {
    return classicRequest("/automation/backtest/state", { method: "GET" });
  },

  /**
   * 获取最近一次回测报告
   */
  async getRecentReport() {
    return classicRequest("/automation/backtest/report", { method: "GET" });
  },
};

// ============================================================
// 5. 评估与 Gate 检查 API
// ============================================================

export interface GateCheckResponse {
  ok: boolean;
  pass: boolean;
  gate_id?: string;
  gate_result?: Record<string, any>;
  thresholds?: Record<string, any>;
  violations?: string[];
  warnings?: string[];
}

export const EvaluationAPI = {
  /**
   * 执行 Gate 检查（策略变更前的门禁评估）
   */
  async checkGate(payload: {
    gate_id?: string;
    strategy_id?: string;
    changeset?: Record<string, any>;
  }): Promise<ClassicResponse<GateCheckResponse>> {
    return classicRequest("/evaluation/gate/check", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 获取 Gate 阈值配置
   */
  async getGateThresholds() {
    return classicRequest("/gate/thresholds", { method: "GET" });
  },

  /**
   * 获取回滚点列表
   */
  async getRollbackList() {
    return classicRequest("/evaluation/rollback/list", { method: "GET" });
  },

  /**
   * 创建回滚快照
   */
  async createRollbackSnapshot(payload: { label?: string; reason?: string }) {
    return classicRequest("/evaluation/rollback/snapshot", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 恢复到某个回滚点
   */
  async restoreRollback(payload: { snapshot_id?: string; reason?: string }) {
    return classicRequest("/evaluation/rollback/restore", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 触发量化系统回滚
   */
  async triggerQuantRollback(payload: { reason?: string }) {
    return classicRequest("/quant/rollback", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};

// ============================================================
// 6. 审批流程 API
// ============================================================

export interface ApprovalBrief {
  approval_id: string;
  draft_id?: string;
  status: "pending" | "approved" | "rejected";
  reason?: string;
  created_at?: number;
  approver?: string;
  action?: string;
  changeset?: Record<string, any>;
}

export const ApprovalAPI = {
  /**
   * 获取审批摘要
   */
  async getApprovalSummary() {
    return classicRequest("/approvals/summary", { method: "GET" });
  },

  /**
   * 获取单个审批详情
   */
  async getApproval(approval_id: string) {
    return classicRequest(`/approvals/${approval_id}`, { method: "GET" });
  },

  /**
   * 生成审批摘要（由 Agent 生成）
   */
  async generateBrief(payload: {
    draft_id?: string;
    changeset?: Record<string, any>;
    gate_result?: Record<string, any>;
  }) {
    return classicRequest("/agent/approvals/brief/generate", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 获取审批摘要内容
   */
  async getBrief(payload: { draft_id?: string; approval_id?: string }) {
    return classicRequest("/agent/approvals/brief/get", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 审批健康状态
   */
  async getBriefHealth() {
    return classicRequest("/agent/approvals/brief/health", {
      method: "GET",
    });
  },

  /**
   * 获取审批历史
   */
  async getApprovalHistory() {
    return classicRequest("/approvals/history", { method: "GET" });
  },

  /**
   * 发送审批提醒
   */
  async sendApprovalReminder() {
    return classicRequest("/agent/approvals/reminder/run", {
      method: "POST",
    });
  },
};

// ============================================================
// 7. 可观测性与审计 API
// ============================================================

export const ObservabilityAPI = {
  /**
   * 获取每日观测摘要
   */
  async getDailyObservability() {
    return classicRequest("/agent/observability/daily", { method: "GET" });
  },

  /**
   * 获取近期参数优化结果
   */
  async getRecentParamOpt() {
    return classicRequest("/agent/observability/paramopt/recent", {
      method: "GET",
    });
  },

  /**
   * 获取系统总体概述
   */
  async getOverviewSummary() {
    return classicRequest("/agent/overview/summary", { method: "GET" });
  },

  /**
   * 提交审计动作记录
   */
  async submitAuditAction(payload: {
    action: string;
    scope: string;
    trace_id?: string;
    extra?: Record<string, any>;
  }) {
    return classicRequest("/agent/audit/actions", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 审计回放
   */
  async getAuditReplay(params: { trace_id?: string; limit?: number }) {
    const query = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
      if (v !== undefined && v !== null) query.append(k, String(v));
    });
    return classicRequest(`/agent/audit/replay?${query.toString()}`, {
      method: "GET",
    });
  },
};

// ============================================================
// 8. 沙箱与安全测试 API
// ============================================================

export const SandboxAPI = {
  /**
   * 获取沙箱策略
   */
  async getPolicy() {
    return classicRequest("/agent/sandbox/policy", { method: "GET" });
  },

  /**
   * 更新沙箱策略
   */
  async updatePolicy(payload: { policies?: Record<string, any> }) {
    return classicRequest("/agent/sandbox/policy", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 提交任务到沙箱队列
   */
  async submitTask(payload: {
    task_type: string;
    payload: Record<string, any>;
    priority?: number;
  }) {
    return classicRequest("/agent/sandbox/queue/submit", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * Prompt 注入检测
   */
  async checkPromptInjection(payload: { text: string; mode?: string }) {
    return classicRequest("/agent/redteam/prompt_injection", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 压力测试执行
   */
  async runPressureTest(payload: {
    n?: number;
    path?: string;
    http_status?: number;
  }) {
    return classicRequest("/agent/pressure/exec_failure", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },
};

// ============================================================
// 9. 信号系统 API
// ============================================================

export const SignalAPI = {
  /**
   * 发送 v1 信号
   */
  async sendV1Signal(payload: {
    strategy_id?: string;
    symbol?: string;
    signal: "long" | "short" | "exit";
    confidence?: number;
    reason?: string;
  }) {
    return classicRequest("/signals/v1", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 发送 Strategy005 信号
   */
  async sendStrategy005Signal(payload: {
    symbol?: string;
    direction?: string;
    entry_price?: number;
    confidence?: number;
  }) {
    return classicRequest("/signals/hyperliquid/strategy005", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 获取日线信号
   */
  async getDailySignal() {
    return classicRequest("/three_screen/daily/signal", { method: "GET" });
  },

  /**
   * 获取5分钟信号
   */
  async get5mSignal() {
    return classicRequest("/three_screen/5m/signal", { method: "GET" });
  },
};

// ============================================================
// 10. 自动化与运维 API
// ============================================================

export const AutomationAPI = {
  /**
   * 获取自动化状态
   */
  async getState() {
    return classicRequest("/automation/state", { method: "GET" });
  },

  /**
   * 重置自动化状态
   */
  async resetState() {
    return classicRequest("/automation/state/reset", { method: "POST" });
  },

  /**
   * 获取自动化管理状态
   */
  async getManagementState() {
    return classicRequest("/automation/management/state", { method: "GET" });
  },

  /**
   * 触发参数优化
   */
  async triggerParamOpt(payload: {
    strategy_id?: string;
    scope?: string;
  }) {
    return classicRequest("/automation/paramopt/trigger", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 运行影子循环
   */
  async runShadowLoop(payload: {
    mode?: "detect" | "record" | "compare";
    duration_sec?: number;
  }) {
    return classicRequest("/automation/shadow_loop/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 运行系统监控
   */
  async runSystemMonitor(payload: {
    checks?: string[];
    alert_threshold?: number;
  }) {
    return classicRequest("/automation/system_monitor/run", {
      method: "POST",
      body: JSON.stringify(payload),
    });
  },

  /**
   * 运行供应链路检查
   */
  async runSupplyChain() {
    return classicRequest("/automation/supply_chain/run", { method: "POST" });
  },
};

// ============================================================
// 导出统一 API 对象
// ============================================================

export const ClassicSystem = {
  health: HealthAPI,
  strategy: StrategyLibraryAPI,
  inject: StrategyInjectAPI,
  backtest: BacktestAPI,
  evaluation: EvaluationAPI,
  approval: ApprovalAPI,
  observability: ObservabilityAPI,
  sandbox: SandboxAPI,
  signals: SignalAPI,
  automation: AutomationAPI,
  baseUrl: CLASSIC_SYSTEM_BASE_URL,
};

export default ClassicSystem;
