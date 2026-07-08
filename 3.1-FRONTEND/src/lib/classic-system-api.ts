/**
 * Classic System API Client
 * 
 * 调用 10-经典指标系统 (ml_trade_service.py, 端口 8092) 的 API
 * 模块化设计：策略库、信号触发、离场管理等
 */

const CLASSIC_BASE = process.env.NEXT_PUBLIC_CLASSIC_SYSTEM_URL || "http://127.0.0.1:8092";

// ============================================================
// 通用请求封装
// ============================================================

async function classicRequest<T = any>(endpoint: string, options: RequestInit = {}): Promise<T> {
  const url = `${CLASSIC_BASE}${endpoint}`;
  const response = await fetch(url, {
    headers: {
      "Content-Type": "application/json",
      ...options.headers,
    },
    ...options,
  });
  
  if (!response.ok) {
    throw new Error(`Classic API Error: ${response.status} ${response.statusText}`);
  }
  
  return response.json();
}

// ============================================================
// 策略库 (Strategy Registry)
// ============================================================

export interface StrategyInfo {
  strategy: string;
  book_id?: string;
  ab_owner?: string;
  status?: string;
  last_update?: number;
  metrics?: {
    win_rate?: number;
    sharpe_ratio?: number;
    max_drawdown?: number;
  };
}

export interface StrategyRegistryResponse {
  ok: boolean;
  strategies?: StrategyInfo[];
  error?: string;
}

export const StrategyLibraryAPI = {
  /** 获取所有注册策略 —— 合并 feeder/capabilities 与 strategy/params 的活跃策略信息 */
  async listStrategies(): Promise<StrategyRegistryResponse> {
    try {
      const [capabilities, params] = await Promise.all([
        classicRequest<any>("/strategy/feeder/capabilities"),
        classicRequest<any>("/strategy/params"),
      ]);

      const strategyMap = new Map<string, StrategyInfo>();

      // 从 feeder/capabilities 收集策略基本信息
      if (capabilities && capabilities.strategies && Array.isArray(capabilities.strategies)) {
        capabilities.strategies.forEach((s: any) => {
          strategyMap.set(s.strategy_id, {
            strategy: s.strategy_id,
            status: s.can_trigger ? "active" : "inactive",
            book_id: s.direction_capability,
          });
        });
      }

      // 从 strategy/params 补充活跃策略详情（覆盖重复的）
      if (params && params.strategies && typeof params.strategies === "object") {
        Object.entries(params.strategies).forEach(([id, info]: [string, any]) => {
          const existing = strategyMap.get(id) || { strategy: id, status: "active" };
          strategyMap.set(id, {
            ...existing,
            strategy: id,
            status: "active",
            book_id: (info as any).group_id || existing.book_id,
            ab_owner: (info as any).feature_set_id || existing.ab_owner,
          });
        });
      }

      const strategies: StrategyInfo[] = Array.from(strategyMap.values());
      return { ok: true, strategies };
    } catch (error) {
      console.error("[ClassicAPI] List strategies failed:", error);
      return { ok: false, error: String(error) };
    }
  },

  /** 获取策略详情 */
  async getStrategy(strategyName: string): Promise<any> {
    try {
      return await classicRequest(`/strategy/inject/state?strategy=${encodeURIComponent(strategyName)}`);
    } catch (error) {
      console.error("[ClassicAPI] Get strategy failed:", error);
      return { ok: false, error: String(error) };
    }
  },

  /** 获取策略配置 */
  async getStrategyConfig(strategyName: string): Promise<any> {
    try {
      return await classicRequest(`/strategy/params?strategy=${encodeURIComponent(strategyName)}`);
    } catch (error) {
      console.error("[ClassicAPI] Get strategy config failed:", error);
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Pipeline 策略上线通道 (已移至文件末尾)
// ============================================================

export interface PipelineDraft {
  strategy_name: string;
  changeset?: {
    reason?: string;
    description?: string;
    param_overrides?: Record<string, any>;
  };
}

export interface PipelinePhaseResult {
  phase: string;
  success: boolean;
  message: string;
  data?: any;
  timestamp: number;
}

export interface PipelineResult {
  success: boolean;
  strategyName: string;
  traceId: string;
  changesetId?: string;
  approvalId?: string;
  steps: PipelinePhaseResult[];
  error?: string;
}

// ============================================================
// 沙箱测试 (Backtest) - 已移至文件末尾
// ============================================================

export interface BacktestConfig {
  strategy: string;
  config?: string;
  timeout_sec?: number;
}

export interface BacktestResult {
  ok: boolean;
  task_id?: string;
  status?: string;
  result?: any;
  error?: string;
}

// ============================================================
// 信号系统 (Signals)
// ============================================================

export interface SignalInfo {
  id?: string;
  strategy?: string;
  signal?: string;
  direction?: "long" | "short" | "neutral";
  entry_price?: number;
  stop_loss?: number;
  take_profit?: number;
  confidence?: number;
  timestamp?: number;
  status?: string;
}

export interface SignalsResponse {
  ok: boolean;
  signals?: SignalInfo[];
  total?: number;
  error?: string;
}

export const SignalsAPI = {
  /** 获取最近信号 —— /signals/recent 返回 [{action,pair,side,strategy_id,ts,...}] */
  async getRecentSignals(limit: number = 20): Promise<SignalsResponse> {
    try {
      const data = await classicRequest<any>(`/signals/recent?limit=${limit}`);
      let rawSignals: any[] = [];
      if (Array.isArray(data)) {
        rawSignals = data;
      } else if (data && data.ok && Array.isArray(data.signals)) {
        rawSignals = data.signals;
      }
      // 将后端字段映射到前端 SignalInfo
      const signals: SignalInfo[] = rawSignals.map((sig: any) => ({
        id: sig.id,
        strategy: sig.strategy_id || sig.strategy,
        signal: sig.action || sig.signal,
        direction: (sig.side === "long" || sig.direction === "long") ? "long" :
                   (sig.side === "short" || sig.direction === "short") ? "short" : "neutral",
        confidence: typeof sig.confidence === "number" ? sig.confidence :
                   typeof sig.pc === "number" ? sig.pc : undefined,
        timestamp: sig.ts || sig.timestamp,
        status: sig.status,
      }));
      return { ok: true, signals, total: signals.length };
    } catch (error) {
      return { ok: false, signals: [], error: String(error) };
    }
  },
};

// ============================================================
// 执行管理 (Execution)
// ============================================================

export interface OrderInfo {
  order_id?: string;
  symbol?: string;
  side?: "buy" | "sell";
  type?: string;
  status?: string;
  filled?: number;
  price?: number;
  timestamp?: number;
}

export interface PositionInfo {
  symbol?: string;
  side?: "long" | "short";
  size?: number;
  entry_price?: number;
  unrealized_pnl?: number;
  timestamp?: number;
}

export const ExecutionAPI = {
  /** 获取当前持仓 */
  async getPositions(): Promise<{ ok: boolean; positions?: PositionInfo[]; error?: string }> {
    try {
      return await classicRequest("/execution/positions");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取最近订单 */
  async getRecentOrders(limit: number = 20): Promise<{ ok: boolean; orders?: OrderInfo[]; error?: string }> {
    try {
      return await classicRequest(`/execution/orders/recent?limit=${limit}`);
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// 离场管理 (Exit System)
// ============================================================

export interface ExitSignal {
  id?: string;
  symbol?: string;
  position_id?: string;
  exit_type?: string;
  reason?: string;
  timestamp?: number;
  status?: string;
}

export interface ExitResponse {
  ok: boolean;
  signals?: ExitSignal[];
  error?: string;
}

export interface ExitSignal {
  id?: string;
  symbol?: string;
  position_id?: string;
  exit_type?: string;
  reason?: string;
  timestamp?: number;
  status?: string;
}

export interface ExitResponse {
  ok: boolean;
  signals?: ExitSignal[];
  error?: string;
}

// 后端 /tracker/stats?view=exit 返回结构
export interface TrackerExitPosition {
  pair: string;
  side: string;
  mode: string;
  system_id: string;
  strategy_id: string;
  entry_ts: number;
  hold_value: number;
  hold_risk: number;
  notional_usdc: number;
  leverage: number;
  exit_owner: string;
  exit_l1_last_decision: {
    action: string;
    reason: string;
    hold_risk: number;
    hold_value: number;
  };
}

export interface TrackerExitStats {
  ok: boolean;
  open_positions: Record<string, TrackerExitPosition>;
  exit_inflight: Record<string, unknown>;
  exit_owner_state: {
    weights: Record<string, number>;
    history: unknown[];
  };
}

export const ExitAPI = {
  /** 获取离场状态 —— 从 /tracker/stats?view=exit */
  async getExitStatus(): Promise<TrackerExitStats> {
    try {
      return await classicRequest("/tracker/stats?view=exit");
    } catch (error) {
      console.error("[ClassicAPI] Exit status failed:", error);
      return { ok: false, open_positions: {}, exit_inflight: {}, exit_owner_state: { weights: {}, history: [] } };
    }
  },

  /** 获取离场追踪状态 */
  async getExitTrackerStatus(): Promise<any> {
    try {
      return await classicRequest("/exit/tracker/status");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// 系统健康检查
// ============================================================

export const SystemHealthAPI = {
  /** 健康检查 */
  async healthCheck(): Promise<{ ok: boolean; error?: string }> {
    try {
      return await classicRequest("/health");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取系统指标 */
  async getMetrics(): Promise<any> {
    try {
      return await classicRequest("/metrics");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// 审批管理 (Approvals)
// ============================================================

export interface ApprovalInfo {
  id?: string;
  strategy_name?: string;
  status?: "pending" | "approved" | "rejected";
  request_type?: string;
  created_at?: number;
  updated_at?: number;
  reason?: string;
}

export const ApprovalsAPI = {
  /** 获取待审批列表 —— /approvals/summary 返回 pending 字段 */
  async getPendingApprovals(): Promise<{ ok: boolean; approvals?: ApprovalInfo[]; error?: string }> {
    try {
      const data = await classicRequest<any>("/approvals/summary");
      if (data && data.ok) {
        const raw: any[] = data.pending || [];
        const approvals: ApprovalInfo[] = raw.map((item: any) => ({
          id: item.id || item.change_id,
          strategy_name: item.strategy_name || item.strategy_id,
          status: item.status || "pending",
          request_type: item.request_type || item.type,
          created_at: item.created_at || item.ts,
        }));
        return { ok: true, approvals };
      }
      return { ok: false, approvals: [], error: "load failed" };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取审批详情 */
  async getApprovalDetail(approvalId: string): Promise<any> {
    try {
      return await classicRequest(`/approvals/get?id=${encodeURIComponent(approvalId)}`);
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 执行审批操作 */
  async actionApproval(approvalId: string, action: "approve" | "reject", comment?: string): Promise<any> {
    try {
      return await classicRequest("/approvals/action", {
        method: "POST",
        body: JSON.stringify({ id: approvalId, action, comment }),
      });
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// 自动化状态 (Automation)
// ============================================================

export interface AutomationCard {
  card_id: string;
  status: string;
  progress?: { pct: number };
  trace_id?: string;
  updated_at_ms?: number;
  stuck?: { stuck_since_ms?: number; reason_code?: string };
}

export interface AutomationCardsResponse {
  ok: boolean;
  cards?: AutomationCard[];
  error?: string;
}

export const AutomationAPI = {
  /** 获取自动化卡片状态 */
  async getAutomationStatus(): Promise<AutomationCardsResponse> {
    try {
      return await classicRequest("/automation/cards/state");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Arena 多模型投票
// ============================================================

export const ArenaAPI = {
  async getState(): Promise<{ ok: boolean; enabled?: boolean; pool_u?: number; models?: Record<string, any>; error?: string }> {
    try {
      return await classicRequest("/arena/state");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Universe 代币筛选
// ============================================================

export const UniverseAPI = {
  async getStatus(): Promise<{ ok: boolean; core?: string[]; watchlist?: string[]; shadow?: string[]; counts?: { core: number; watchlist: number; shadow: number }; last_update?: number; error?: string }> {
    try {
      const data = await classicRequest<any>("/universe/status");
      // 后端没有 ok 字段，手动添加
      return { ok: true, ...data };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Macro 宏观门控
// ============================================================

export const MacroAPI = {
  async getOverview(): Promise<{ ok: boolean; gate_std1h?: Record<string, any>; btc?: { energy?: string; trend?: string }; eth?: { energy?: string; trend?: string }; macro_btceth_shape?: Record<string, any>; macro_tri_layer?: Record<string, any>; error?: string }> {
    try {
      return await classicRequest("/macro/btceth/overview");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Evaluation 模型评估与在线学习
// ============================================================

export const EvaluationAPI = {
  async getAcceptanceStatus(): Promise<{ ok: boolean; orders?: { total: number; window: number }; acceptance?: Record<string, any>; online?: Record<string, any>; profit_window?: Record<string, any>; error?: string }> {
    try {
      return await classicRequest("/evaluation/acceptance/status");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取 Gate Check 结果
   * @description 当后端回测数据不可用时返回降级响应（ok=true, available=false）
   *              不抛出异常，让调用方可以正常处理"暂无数据"的展示
   */
  async getGateCheck(): Promise<{ ok: boolean; available: boolean; passed?: boolean; checks?: Record<string, boolean>; thresholds?: Record<string, number>; metrics?: Record<string, number>; ts?: number; error?: string }> {
    try {
      const data = await classicRequest<any>("/evaluation/gate/check");
      // 后端返回 {ok: false, error: "backtest_unavailable"} 表示回测数据不可用
      // 这是预期行为，返回降级响应而不是错误
      if (data && data.ok === false) {
        return {
          ok: true, // 业务层面成功（API 调用成功，只是数据不可用）
          available: false,
          error: data.error || "backtest_unavailable",
        };
      }
      return { ok: true, available: true, ...data };
    } catch (error: any) {
      // HTTP 错误（404 等）也降级处理
      if (error?.message?.includes("404") || error?.message?.includes("Classic API Error: 404")) {
        return {
          ok: true,
          available: false,
          error: "backtest_unavailable",
        };
      }
      return { ok: false, available: false, error: String(error) };
    }
  },
};

// ============================================================
// Tracker 执行记录
// ============================================================

export interface SettlementRecord {
  event_id: string;
  order_id: string;
  pair: string;
  strategy_id: string;
  system_id: string;
  owner: string;
  group_id: string;
  ts: number;
  duration_ms: number;
  pnl_usdc: number;
  ret_ratio: number;
  notional_usdc: number;
  reason: string;
  fee_abs: number | null;
  funding_abs: number | null;
  slippage_abs: number | null;
}

export const TrackerAPI = {
  async getStats(): Promise<{ ok: boolean; ab_settlements?: SettlementRecord[]; error?: string }> {
    try {
      const data = await classicRequest<any>("/tracker/stats");
      return { ok: true, ab_settlements: data.ab_settlements || [] };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Sandbox 沙箱测试
// ============================================================

export interface BacktestResultItem {
  zip?: string;
  strategy?: string;
  ts?: number;
  ok?: boolean;
  metrics_summary?: {
    pf?: number;
    maxdd?: number;
    trades?: number;
    winrate?: number;
    sharpe?: number;
  };
}

export interface SandboxState {
  running?: number;
  queued?: number;
  max_slots?: number;
}

export const SandboxAPI = {
  /** 获取回测结果列表 */
  async getBacktestResults(limit: number = 30): Promise<{ ok: boolean; results?: BacktestResultItem[]; latest?: string; ts?: number; error?: string }> {
    try {
      return await classicRequest(`/backtest/results?limit=${limit}`);
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取沙箱状态
   * @description 优先尝试 /automation/sandbox/state，失败则降级到 /sandbox/policy
   */
  async getSandboxState(): Promise<{ ok: boolean; state?: SandboxState; available: boolean; error?: string }> {
    // 优先尝试主端点
    try {
      const data = await classicRequest<any>("/automation/sandbox/state");
      if (data && data.ok) {
        const st = data.state || data.sandbox_state || {};
        return {
          ok: true,
          available: true,
          state: {
            running: st.running || 0,
            queued: st.queued || 0,
            max_slots: st.max_slots || 3,
          },
        };
      }
      throw new Error("automation/sandbox/state returned ok=false");
    } catch (primaryError: any) {
      // 如果主端点 404，降级尝试 /sandbox/policy
      if (primaryError?.message?.includes("404") || primaryError?.message?.includes("Classic API Error: 404")) {
        try {
          const policyData = await classicRequest<any>("/sandbox/policy");
          return {
            ok: true,
            available: true,
            state: { running: 0, queued: 0, max_slots: 3 }, // policy 端点不返回队列信息
          };
        } catch {
          // 两个端点都失败，返回降级响应
          return {
            ok: true,
            available: false,
            state: { running: 0, queued: 0, max_slots: 3 },
            error: "sandbox_unavailable",
          };
        }
      }
      // 非 404 错误
      return {
        ok: true,
        available: false,
        state: { running: 0, queued: 0, max_slots: 3 },
        error: String(primaryError),
      };
    }
  },

  /** 启动回测 */
  async runBacktest(config: BacktestConfig): Promise<BacktestResult> {
    try {
      return await classicRequest("/automation/backtest/run", {
        method: "POST",
        body: JSON.stringify({
          strategy: config.strategy,
          config: config.config || "user_data/config_local_backtest.json",
          timeout_sec: config.timeout_sec || 1800,
        }),
      });
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 查询回测状态 */
  async getBacktestStatus(taskId: string): Promise<BacktestResult> {
    try {
      return await classicRequest(`/automation/backtest/status?task_id=${encodeURIComponent(taskId)}`);
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取回测结果 */
  async getBacktestResult(taskId: string): Promise<BacktestResult> {
    try {
      return await classicRequest(`/automation/backtest/result?task_id=${encodeURIComponent(taskId)}`);
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};

// ============================================================
// Pipeline 策略上线通道
// ============================================================

export interface PipelinePhaseInfo {
  phase?: string;
  status?: string;
  trace_id?: string;
  ts?: number;
}

export interface ServingPipelineState {
  phase?: string;
  current?: string;
  candidate?: string;
  gate_result?: { passed?: boolean; checks?: Record<string, boolean> };
  approval_id?: string;
  ts?: number;
}

export const PipelineAPI = {
  /** 获取 Serving Pipeline 状态 */
  async getServingPipelineState(): Promise<{ ok: boolean; serving_pipeline?: ServingPipelineState; error?: string }> {
    try {
      return await classicRequest("/automation/serving/pipeline/state");
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },

  /** 获取 Gate Check 结果
   * @description 当后端回测数据不可用时返回降级响应（ok=true, available=false）
   */
  async getGateCheck(): Promise<{ ok: boolean; available: boolean; passed?: boolean; checks?: Record<string, boolean>; thresholds?: Record<string, number>; metrics?: Record<string, number>; ts?: number; error?: string }> {
    try {
      const data = await classicRequest<any>("/evaluation/gate/check");
      if (data && data.ok === false) {
        return { ok: true, available: false, error: data.error || "backtest_unavailable" };
      }
      return { ok: true, available: true, ...data };
    } catch (error: any) {
      if (error?.message?.includes("404") || error?.message?.includes("Classic API Error: 404")) {
        return { ok: true, available: false, error: "backtest_unavailable" };
      }
      return { ok: false, available: false, error: String(error) };
    }
  },

  /** Stage 1: 创建 Draft */
  async createDraft(payload: PipelineDraft): Promise<PipelinePhaseResult> {
    try {
      const result = await classicRequest("/agent/changeset/draft", {
        method: "POST",
        body: JSON.stringify({
          strategy_name: payload.strategy_name,
          changeset: payload.changeset || {},
        }),
      });
      return {
        phase: "draft",
        success: result?.ok ?? false,
        message: result?.ok ? `Draft已创建: ${payload.strategy_name}` : "Draft创建失败",
        data: result,
        timestamp: Date.now(),
      };
    } catch (error) {
      return {
        phase: "draft",
        success: false,
        message: String(error),
        timestamp: Date.now(),
      };
    }
  },

  /** Stage 2: Gate 评估 */
  async runGateCheck(changesetId?: string): Promise<PipelinePhaseResult> {
    try {
      const result = await classicRequest("/evaluation/gate/check", {
        method: "GET",
      });
      return {
        phase: "gate",
        success: result?.ok ?? result?.pass ?? false,
        message: result?.ok ? "Gate评估通过" : "Gate评估未通过",
        data: result,
        timestamp: Date.now(),
      };
    } catch (error) {
      return {
        phase: "gate",
        success: false,
        message: String(error),
        timestamp: Date.now(),
      };
    }
  },

  /** Stage 3: 申请审批 */
  async requestApproval(strategyName: string, changesetId?: string): Promise<PipelinePhaseResult> {
    try {
      const result = await classicRequest("/agent/approvals/brief/generate", {
        method: "POST",
        body: JSON.stringify({
          strategy_name: strategyName,
          changeset_id: changesetId,
          request_type: "strategy_deployment",
        }),
      });
      return {
        phase: "approval",
        success: result?.ok ?? false,
        message: result?.ok ? "审批请求已提交" : "审批请求提交失败",
        data: result,
        timestamp: Date.now(),
      };
    } catch (error) {
      return {
        phase: "approval",
        success: false,
        message: String(error),
        timestamp: Date.now(),
      };
    }
  },

  /** Stage 4: Apply 变更 */
  async applyChangeset(strategyName: string, changesetId?: string): Promise<PipelinePhaseResult> {
    try {
      const result = await classicRequest("/governance/changeset/apply", {
        method: "POST",
        body: JSON.stringify({
          strategy_name: strategyName,
          changeset_id: changesetId,
          mode: "apply",
        }),
      });
      return {
        phase: "apply",
        success: result?.ok ?? false,
        message: result?.ok ? "策略已应用" : "策略应用失败",
        data: result,
        timestamp: Date.now(),
      };
    } catch (error) {
      return {
        phase: "apply",
        success: false,
        message: String(error),
        timestamp: Date.now(),
      };
    }
  },

  /** 完整流水线执行 */
  async runPipeline(payload: PipelineDraft, onProgress?: (state: PipelinePhaseResult) => void): Promise<PipelineResult> {
    const steps: PipelinePhaseResult[] = [];

    // Draft
    const draftResult = await this.createDraft(payload);
    steps.push(draftResult);
    onProgress?.(draftResult);
    if (!draftResult.success) {
      return { success: false, strategyName: payload.strategy_name, traceId: "", steps, error: "Draft创建失败" };
    }

    // Gate
    const gateResult = await this.runGateCheck(draftResult.data?.changeset_id);
    steps.push(gateResult);
    onProgress?.(gateResult);

    // Approval
    const approvalResult = await this.requestApproval(payload.strategy_name, draftResult.data?.changeset_id);
    steps.push(approvalResult);
    onProgress?.(approvalResult);

    // Apply
    const applyResult = await this.applyChangeset(payload.strategy_name, draftResult.data?.changeset_id);
    steps.push(applyResult);
    onProgress?.(applyResult);

    return {
      success: steps.every(s => s.success),
      strategyName: payload.strategy_name,
      traceId: draftResult.data?.changeset_id || "",
      changesetId: draftResult.data?.changeset_id,
      approvalId: approvalResult.data?.approval_id,
      steps,
    };
  },
};

// ============================================================
// Gate Thresholds 信号过滤阈值
// ============================================================

export const GateThresholdsAPI = {
  /** 获取 Gate Thresholds */
  async getThresholds(): Promise<{ ok: boolean; thresholds?: Record<string, number>; error?: string }> {
    try {
      const data = await classicRequest<any>("/evaluation/gate/check");
      if (data && data.ok) {
        return { ok: true, thresholds: data.thresholds || {} };
      }
      return { ok: false, error: "load failed" };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  },
};
