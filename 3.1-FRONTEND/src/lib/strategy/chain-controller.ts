/**
 * 策略思维链 - 链状态机控制器
 *
 * 版本: v1.0
 * 日期: 2026-06-15
 * 职责: 管理策略链的状态转换和步骤执行
 */

import {
  StrategyStepId,
  StrategyStepStatus,
  StrategyChainState,
  StrategyComplexity,
  StrategyStep,
  createDefaultChainState,
  getNextStepId,
} from "./types";
import { getNextStep, canSkipStep } from "./route";
import { executeStrategyStep } from "./steps";

// ============================================================
// 状态机事件
// ============================================================

export type ChainEvent =
  | { type: "INIT"; scope: string; complexity: StrategyComplexity }
  | { type: "START" }
  | { type: "COMPLETE"; stepId: StrategyStepId; output: string }
  | { type: "SKIP"; stepId: StrategyStepId; reason?: string }
  | { type: "PAUSE" }
  | { type: "RESUME" }
  | { type: "RESET" };

// ============================================================
// 状态机结果
// ============================================================

export interface ChainTransitionResult {
  success: boolean;
  reason?: string;
  state?: StrategyChainState;
  nextStepId?: StrategyStepId | null;
  requiresConfirmation?: boolean;
}

// ============================================================
// 链状态机控制器
// ============================================================

export class StrategyChainController {
  private state: StrategyChainState | null = null;
  private allowedSteps: StrategyStepId[] = [];

  /**
   * 初始化策略链
   */
  init(scope: string, complexity: StrategyComplexity, steps: StrategyStepId[]): StrategyChainState {
    this.state = createDefaultChainState(scope, complexity);
    this.allowedSteps = steps;

    // 根据允许的步骤设置状态
    this.state.steps = this.state.steps.map((step, idx) => {
      if (this.allowedSteps.includes(step.id)) {
        // 允许的步骤保持pending或active
        return step;
      } else {
        // 不允许的步骤标记为skipped
        return {
          ...step,
          status: "skipped" as StrategyStepStatus,
          skippedReason: "超出复杂度范围",
        };
      }
    });

    return this.state;
  }

  /**
   * 获取当前状态
   */
  getState(): StrategyChainState | null {
    return this.state;
  }

  /**
   * 获取当前步骤
   */
  getCurrentStep(): StrategyStep | null {
    if (!this.state) return null;
    const currentStepId = this.state.currentStep;
    if (!currentStepId) return null;
    return this.state.steps.find(s => s.id === currentStepId) ?? null;
  }

  /**
   * 获取允许的步骤列表
   */
  getAllowedSteps(): StrategyStepId[] {
    return this.allowedSteps;
  }

  /**
   * 检查是否可以继续
   */
  canContinue(): boolean {
    if (!this.state) return false;
    const current = this.getCurrentStep();
    if (!current) return false;
    return current.status === "done" || current.status === "active";
  }

  /**
   * 检查是否可以跳过当前步骤
   */
  canSkipCurrent(): boolean {
    if (!this.state) return false;
    const current = this.getCurrentStep();
    if (!current) return false;
    return canSkipStep(current.id, this.allowedSteps, this.state.complexity !== "quick");
  }

  /**
   * 执行步骤
   */
  async executeCurrentStep(input: any): Promise<string | null> {
    if (!this.state) return null;
    const current = this.getCurrentStep();
    if (!current || current.status !== "active") return null;

    try {
      const output = await executeStrategyStep(current.id, input);
      return output;
    } catch (error) {
      console.error(`执行步骤 ${current.id} 失败:`, error);
      return null;
    }
  }

  /**
   * 确认步骤完成
   */
  confirmStep(stepId: StrategyStepId, output: string): ChainTransitionResult {
    if (!this.state) {
      return { success: false, reason: "链未初始化" };
    }

    const stepIndex = this.state.steps.findIndex(s => s.id === stepId);
    if (stepIndex === -1) {
      return { success: false, reason: `步骤 ${stepId} 不存在` };
    }

    const step = this.state.steps[stepIndex];
    if (step.status !== "active") {
      return { success: false, reason: `步骤 ${stepId} 当前状态为 ${step.status}，无法确认` };
    }

    // 更新步骤状态
    const now = new Date().toISOString();
    this.state.steps[stepIndex] = {
      ...step,
      status: "done",
      output,
      completedAt: now,
    };
    this.state.modifiedAt = now;

    // 获取下一步
    const nextStepId = getNextStep(stepId, this.allowedSteps);
    if (nextStepId) {
      // 激活下一步
      const nextIndex = this.state.steps.findIndex(s => s.id === nextStepId);
      if (nextIndex !== -1) {
        this.state.steps[nextIndex] = {
          ...this.state.steps[nextIndex],
          status: "active",
          startedAt: now,
        };
        this.state.currentStep = nextStepId;
      }
    } else {
      // 没有下一步了
      this.state.currentStep = null;
    }

    return {
      success: true,
      state: this.state,
      nextStepId,
      requiresConfirmation: this.state.complexity !== "quick" && nextStepId !== null,
    };
  }

  /**
   * 跳过当前步骤
   */
  skipStep(stepId: StrategyStepId, reason?: string): ChainTransitionResult {
    if (!this.canSkipCurrent()) {
      return { success: false, reason: "当前步骤不允许跳过" };
    }

    if (!this.state) {
      return { success: false, reason: "链未初始化" };
    }

    const stepIndex = this.state.steps.findIndex(s => s.id === stepId);
    if (stepIndex === -1) {
      return { success: false, reason: `步骤 ${stepId} 不存在` };
    }

    const step = this.state.steps[stepIndex];
    if (step.status === "done" || step.status === "skipped") {
      return { success: false, reason: `步骤 ${stepId} 已完成或已跳过` };
    }

    // 更新步骤状态
    const now = new Date().toISOString();
    this.state.steps[stepIndex] = {
      ...step,
      status: "skipped",
      skippedReason: reason ?? "用户跳过",
      completedAt: now,
    };
    this.state.modifiedAt = now;

    // 获取下下一步
    const nextStepId = getNextStep(stepId, this.allowedSteps);
    if (nextStepId) {
      const nextIndex = this.state.steps.findIndex(s => s.id === nextStepId);
      if (nextIndex !== -1 && this.state.steps[nextIndex].status === "pending") {
        this.state.steps[nextIndex] = {
          ...this.state.steps[nextIndex],
          status: "active",
          startedAt: now,
        };
        this.state.currentStep = nextStepId;
      }
    } else {
      this.state.currentStep = null;
    }

    return {
      success: true,
      state: this.state,
      nextStepId,
    };
  }

  /**
   * 暂停链
   */
  pause(): ChainTransitionResult {
    if (!this.state) {
      return { success: false, reason: "链未初始化" };
    }

    return {
      success: true,
      state: this.state,
    };
  }

  /**
   * 恢复链
   */
  resume(): ChainTransitionResult {
    if (!this.state) {
      return { success: false, reason: "链未初始化" };
    }

    const current = this.getCurrentStep();
    if (!current) {
      return { success: false, reason: "没有可执行的步骤" };
    }

    return {
      success: true,
      state: this.state,
      nextStepId: current.id,
    };
  }

  /**
   * 重置链
   */
  reset(): ChainTransitionResult {
    if (!this.state) {
      return { success: false, reason: "链未初始化" };
    }

    const now = new Date().toISOString();
    this.state.steps = this.state.steps.map((step, idx) => {
      if (this.allowedSteps.includes(step.id)) {
        return {
          ...step,
          status: idx === 0 ? ("active" as StrategyStepStatus) : ("pending" as StrategyStepStatus),
          output: "",
          notes: "",
          startedAt: idx === 0 ? now : undefined,
          completedAt: undefined,
        };
      } else {
        return {
          ...step,
          status: "skipped" as StrategyStepStatus,
        };
      }
    });
    this.state.currentStep = this.allowedSteps[0] ?? null;
    this.state.modifiedAt = now;

    return {
      success: true,
      state: this.state,
      nextStepId: this.state.currentStep,
    };
  }

  /**
   * 获取链进度
   */
  getProgress(): { current: number; total: number; percentage: number } {
    if (!this.state) {
      return { current: 0, total: 0, percentage: 0 };
    }

    const total = this.allowedSteps.length;
    const completed = this.state.steps.filter(
      s => this.allowedSteps.includes(s.id) && s.status === "done"
    ).length;

    return {
      current: completed,
      total,
      percentage: total > 0 ? Math.round((completed / total) * 100) : 0,
    };
  }
}

// ============================================================
// 工厂函数
// ============================================================

let globalController: StrategyChainController | null = null;

/**
 * 获取全局链控制器
 */
export function getChainController(): StrategyChainController {
  if (!globalController) {
    globalController = new StrategyChainController();
  }
  return globalController;
}

/**
 * 创建新的链控制器
 */
export function createChainController(): StrategyChainController {
  return new StrategyChainController();
}
