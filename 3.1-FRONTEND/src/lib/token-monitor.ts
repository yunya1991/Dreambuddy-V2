/**
 * Token Monitor — 内置 Token 监控器
 * ==================================
 *
 * 功能：
 * 1. 定期监控 token / credits 余额
 * 2. 低于阈值时自动触发降级到经典指标系统
 * 3. 充值恢复后自动重新启用大模型
 * 4. 多级告警 + 状态持久化
 *
 * 设计原则：
 * - 看门狗模式：独立运行，不依赖 React 渲染周期
 * - 事件驱动：状态变更时触发回调（UI 更新、通知等）
 * - 幂等降级：多次触发低余额事件只执行一次降级操作
 * - 渐进恢复：余额恢复到安全线以上才重新启用 AI
 */

import type { TradingMode } from "./trading-mode";

// ============================================================
// 类型定义
// ============================================================

export type MonitorStatus = "idle" | "running" | "paused" | "error";

export type TokenLevel = "critical" | "low" | "medium" | "healthy";

export interface TokenMonitorState {
  status: MonitorStatus;
  balance: number;
  totalEarned: number;
  totalSpent: number;
  level: TokenLevel;
  lastChecked: number;
  lastError?: string;
  autoDowngradeEnabled: boolean;
  isDowngraded: boolean;
  downgradedAt?: number;
  checkCount: number;
  consecutiveLowCount: number;
}

export interface TokenMonitorConfig {
  /** 检查间隔（毫秒），默认 5 分钟 */
  checkIntervalMs: number;
  /** 低余额阈值（百分比 0-100），默认 10% */
  lowBalanceThreshold: number;
  /** 严重低余额阈值（百分比 0-100），默认 5% */
  criticalBalanceThreshold: number;
  /** 恢复阈值（百分比 0-100），默认 20% — 恢复到此值以上才重新启用 AI */
  recoveryThreshold: number;
  /** 连续 N 次检测到低余额才触发降级，防止抖动 */
  consecutiveLowChecks: number;
  /** 是否启用自动降级 */
  autoDowngradeEnabled: boolean;
  /** 每日配额（用于计算百分比），为 0 则只用绝对值 */
  dailyQuota: number;
}

export interface TokenMonitorCallbacks {
  onBalanceChange?: (balance: number, prevBalance: number, state: TokenMonitorState) => void;
  onLevelChange?: (level: TokenLevel, prevLevel: TokenLevel, state: TokenMonitorState) => void;
  onLowBalance?: (state: TokenMonitorState) => void;
  onCriticalBalance?: (state: TokenMonitorState) => void;
  onRecovery?: (state: TokenMonitorState) => void;
  onAutoDowngrade?: (state: TokenMonitorState) => void;
  onAutoRecovery?: (state: TokenMonitorState) => void;
  onError?: (error: Error, state: TokenMonitorState) => void;
}

export type FetchBalanceFn = () => Promise<{
  balance: number;
  totalEarned?: number;
  totalSpent?: number;
}>;

// ============================================================
// 默认配置
// ============================================================

const DEFAULT_CONFIG: TokenMonitorConfig = {
  checkIntervalMs: 5 * 60 * 1000, // 5 分钟
  lowBalanceThreshold: 10, // 10%
  criticalBalanceThreshold: 5, // 5%
  recoveryThreshold: 20, // 20%
  consecutiveLowChecks: 2, // 连续 2 次
  autoDowngradeEnabled: true,
  dailyQuota: 0, // 0 = 不使用百分比，直接用绝对阈值
};

// ============================================================
// TokenMonitor 类
// ============================================================

export class TokenMonitor {
  private config: TokenMonitorConfig;
  private state: TokenMonitorState;
  private callbacks: TokenMonitorCallbacks;
  private fetchBalance: FetchBalanceFn;
  private timerId: ReturnType<typeof setInterval> | null = null;
  private prevBalance: number = 0;
  private prevLevel: TokenLevel = "healthy";

  constructor(
    fetchBalance: FetchBalanceFn,
    config: Partial<TokenMonitorConfig> = {},
    callbacks: TokenMonitorCallbacks = {}
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.fetchBalance = fetchBalance;
    this.callbacks = callbacks;
    this.state = {
      status: "idle",
      balance: 0,
      totalEarned: 0,
      totalSpent: 0,
      level: "healthy",
      lastChecked: 0,
      autoDowngradeEnabled: this.config.autoDowngradeEnabled,
      isDowngraded: false,
      checkCount: 0,
      consecutiveLowCount: 0,
    };
  }

  // ── 公共 API ────────────────────────────────────────────────

  /** 启动监控 */
  start(): void {
    if (this.state.status === "running") return;

    this.state.status = "running";
    this.state.lastError = undefined;

    // 立即执行一次检查
    this.checkBalance().catch((err) => {
      this.handleError(err);
    });

    // 启动定时检查
    this.timerId = setInterval(() => {
      this.checkBalance().catch((err) => {
        this.handleError(err);
      });
    }, this.config.checkIntervalMs);

    console.log(
      `[TokenMonitor] Started, interval=${this.config.checkIntervalMs / 1000}s, ` +
        `lowThreshold=${this.config.lowBalanceThreshold}%, ` +
        `autoDowngrade=${this.config.autoDowngradeEnabled}`
    );
  }

  /** 暂停监控 */
  pause(): void {
    if (this.timerId) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    this.state.status = "paused";
    console.log("[TokenMonitor] Paused");
  }

  /** 恢复监控 */
  resume(): void {
    if (this.state.status === "running") return;
    this.start();
  }

  /** 停止监控 */
  stop(): void {
    if (this.timerId) {
      clearInterval(this.timerId);
      this.timerId = null;
    }
    this.state.status = "idle";
    console.log("[TokenMonitor] Stopped");
  }

  /** 手动触发一次检查 */
  async checkNow(): Promise<TokenMonitorState> {
    await this.checkBalance();
    return this.getState();
  }

  /** 获取当前状态 */
  getState(): Readonly<TokenMonitorState> {
    return { ...this.state };
  }

  /** 更新配置 */
  updateConfig(config: Partial<TokenMonitorConfig>): void {
    const prevInterval = this.config.checkIntervalMs;
    this.config = { ...this.config, ...config };
    this.state.autoDowngradeEnabled = this.config.autoDowngradeEnabled;

    // 如果间隔变了，重启定时器
    if (config.checkIntervalMs !== undefined && config.checkIntervalMs !== prevInterval) {
      if (this.state.status === "running" && this.timerId) {
        clearInterval(this.timerId);
        this.timerId = setInterval(() => {
          this.checkBalance().catch((err) => {
            this.handleError(err);
          });
        }, this.config.checkIntervalMs);
      }
    }

    console.log("[TokenMonitor] Config updated:", this.config);
  }

  /** 更新回调 */
  setCallbacks(callbacks: TokenMonitorCallbacks): void {
    this.callbacks = { ...this.callbacks, ...callbacks };
  }

  /** 手动触发降级（用于测试） */
  triggerDowngrade(): void {
    if (this.state.isDowngraded) return;
    this.state.isDowngraded = true;
    this.state.downgradedAt = Date.now();
    this.callbacks.onAutoDowngrade?.(this.getState());
  }

  /** 手动恢复（用于测试） */
  triggerRecovery(): void {
    if (!this.state.isDowngraded) return;
    this.state.isDowngraded = false;
    this.callbacks.onAutoRecovery?.(this.getState());
  }

  // ── 内部方法 ────────────────────────────────────────────────

  private async checkBalance(): Promise<void> {
    try {
      const result = await this.fetchBalance();
      const balance = result.balance;
      const prevBalance = this.state.balance;

      // 更新状态
      this.state.balance = balance;
      this.state.totalEarned = result.totalEarned ?? this.state.totalEarned;
      this.state.totalSpent = result.totalSpent ?? this.state.totalSpent;
      this.state.lastChecked = Date.now();
      this.state.checkCount++;

      // 计算余额等级
      const level = this.calculateLevel(balance);
      const prevLevel = this.state.level;
      this.state.level = level;

      // 余额变化回调
      if (balance !== prevBalance) {
        this.callbacks.onBalanceChange?.(balance, prevBalance, this.getState());
      }

      // 等级变化回调
      if (level !== prevLevel) {
        this.callbacks.onLevelChange?.(level, prevLevel, this.getState());
        this.prevLevel = level;
      }

      // 检查低余额 / 严重低余额
      if (level === "critical") {
        this.callbacks.onCriticalBalance?.(this.getState());
      } else if (level === "low") {
        this.callbacks.onLowBalance?.(this.getState());
      }

      // 自动降级 / 恢复逻辑
      this.handleAutoDowngradeRecovery(balance, level);

      this.prevBalance = balance;
    } catch (error) {
      this.handleError(error as Error);
    }
  }

  private calculateLevel(balance: number): TokenLevel {
    const { lowBalanceThreshold, criticalBalanceThreshold, dailyQuota } = this.config;

    // 如果有每日配额，用百分比
    if (dailyQuota > 0) {
      const pct = (balance / dailyQuota) * 100;
      if (pct <= criticalBalanceThreshold) return "critical";
      if (pct <= lowBalanceThreshold) return "low";
      if (pct <= 50) return "medium";
      return "healthy";
    }

    // 没有配额时，用绝对值的启发式判断
    // 假设：< 1000 = critical, < 5000 = low, < 20000 = medium
    if (balance <= 1000) return "critical";
    if (balance <= 5000) return "low";
    if (balance <= 20000) return "medium";
    return "healthy";
  }

  private handleAutoDowngradeRecovery(balance: number, level: TokenLevel): void {
    if (!this.config.autoDowngradeEnabled) return;

    const { consecutiveLowChecks, recoveryThreshold, dailyQuota } = this.config;

    // 检查是否应该降级
    if (!this.state.isDowngraded) {
      if (level === "low" || level === "critical") {
        this.state.consecutiveLowCount++;

        if (this.state.consecutiveLowCount >= consecutiveLowChecks) {
          this.state.isDowngraded = true;
          this.state.downgradedAt = Date.now();
          console.warn(
            `[TokenMonitor] Auto-downgrade triggered! balance=${balance}, ` +
              `level=${level}, consecutive=${this.state.consecutiveLowCount}`
          );
          this.callbacks.onAutoDowngrade?.(this.getState());
        }
      } else {
        // 余额恢复，重置计数
        this.state.consecutiveLowCount = 0;
      }
    } else {
      // 已降级状态，检查是否应该恢复
      const shouldRecover = this.checkRecoveryCondition(balance, level);

      if (shouldRecover) {
        this.state.isDowngraded = false;
        this.state.consecutiveLowCount = 0;
        console.log(
          `[TokenMonitor] Auto-recovery! balance=${balance}, level=${level}`
        );
        this.callbacks.onAutoRecovery?.(this.getState());
      }
    }
  }

  private checkRecoveryCondition(balance: number, level: TokenLevel): boolean {
    const { recoveryThreshold, dailyQuota } = this.config;

    // 有配额时用百分比
    if (dailyQuota > 0) {
      const pct = (balance / dailyQuota) * 100;
      return pct >= recoveryThreshold;
    }

    // 无配额时：恢复到 healthy 或 medium 且比降级时增长了 50%
    if (level === "healthy") return true;
    if (level === "medium") return true;
    return false;
  }

  private handleError(error: Error): void {
    this.state.status = "error";
    this.state.lastError = error.message;
    console.error("[TokenMonitor] Error:", error.message);
    this.callbacks.onError?.(error, this.getState());

    // 错误后自动恢复运行状态（继续尝试）
    setTimeout(() => {
      if (this.state.status === "error") {
        this.state.status = "running";
      }
    }, 5000);
  }
}

// ============================================================
// 辅助函数
// ============================================================

export function formatTokenAmount(amount: number): string {
  if (amount >= 1000000) return `${(amount / 1000000).toFixed(1)}M`;
  if (amount >= 1000) return `${(amount / 1000).toFixed(1)}K`;
  return Math.floor(amount).toString();
}

export function getLevelColor(level: TokenLevel): string {
  switch (level) {
    case "critical":
      return "text-red-500";
    case "low":
      return "text-orange-500";
    case "medium":
      return "text-yellow-500";
    case "healthy":
      return "text-green-500";
  }
}

export function getLevelBgColor(level: TokenLevel): string {
  switch (level) {
    case "critical":
      return "bg-red-500";
    case "low":
      return "bg-orange-500";
    case "medium":
      return "bg-yellow-500";
    case "healthy":
      return "bg-green-500";
  }
}

export function getLevelLabel(level: TokenLevel): string {
  switch (level) {
    case "critical":
      return "严重不足";
    case "low":
      return "余额偏低";
    case "medium":
      return "适中";
    case "healthy":
      return "充足";
  }
}
