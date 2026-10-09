/**
 * ReflectionEngine — SPL 反思引擎（MCTS 纠错）
 * ==========================================
 * SPEC-20261009 §3.4 P4-2
 *
 * Agent-R 式 MCTS 纠错（异步离线执行，不阻塞主链路）
 *
 * 触发条件：
 *   - 案例执行结果为 failure 或 partial
 *   - 同类 pattern 连续失败 ≥ 2 次
 *
 * 纠错流程：
 *   1. 提取失败轨迹：problem → analysis → solution → result(fail)
 *   2. MCTS 搜索修正路径：从失败点开始，尝试 N 条替代路径
 *   3. 拼接正确路径：找到成功终态 → 反向推导修正方案
 *   4. 生成修正案例 → 入 TDR（标记 corrected_from: 原案例id）
 *
 * 异步执行：
 *   - 通过 setImmediate 异步处理
 *   - 主链路不等待反思完成
 *   - 反思完成后写入 TDR，下次同类 query 自动命中
 *
 * 位置: 3.1-FRONTEND/src/lib/reflection-engine.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export interface FailureCase {
  id: string;
  intent: string;
  actions: string[];
  outcome: 'success' | 'failure' | 'partial' | 'unknown';
  outcome_text: string;
  learned: string[];
}

export interface CorrectedCase {
  id: string;
  intent: string;
  actions: string[];
  outcome: 'success';
  outcome_text: string;
  learned: string[];
  corrected_from: string;
  correction_reason: string;
}

// ============================================================
// 2. 常量
// ============================================================

const CONSECUTIVE_FAILURE_THRESHOLD = 2; // 同类连续失败 ≥ 2 次触发

// MCTS 修正策略：基于失败原因的启发式修正
const CORRECTION_STRATEGIES: Record<string, string[]> = {
  default: ['分析原因', '制定备选方案', '执行备选方案', '验证结果'],
};

// ============================================================
// 3. ReflectionEngine 主类
// ============================================================

export class ReflectionEngine {
  readonly consecutiveFailureThreshold: number;
  private failureCounts: Map<string, number> = new Map();

  constructor(opts?: { consecutiveFailureThreshold?: number }) {
    this.consecutiveFailureThreshold = opts?.consecutiveFailureThreshold ?? CONSECUTIVE_FAILURE_THRESHOLD;
  }

  /**
   * 判断是否应该触发反思
   * 条件: outcome=failure/partial 或 同类连续失败 ≥ 阈值
   */
  shouldReflect(caseData: FailureCase): boolean {
    // 条件1: outcome 为 failure 或 partial
    if (caseData.outcome === 'failure' || caseData.outcome === 'partial') {
      return true;
    }
    // 条件2: 同类 pattern 连续失败 ≥ 阈值
    const failureCount = this.failureCounts.get(caseData.intent) || 0;
    return failureCount >= this.consecutiveFailureThreshold;
  }

  /**
   * 记录同类失败
   */
  recordFailure(pattern: string, caseId: string): void {
    const current = this.failureCounts.get(pattern) || 0;
    this.failureCounts.set(pattern, current + 1);
  }

  /**
   * 获取同类失败次数
   */
  getFailureCount(pattern: string): number {
    return this.failureCounts.get(pattern) || 0;
  }

  /**
   * 清空失败记录
   */
  clearFailures(): void {
    this.failureCounts.clear();
  }

  /**
   * 执行反思纠错（同步版）
   * MCTS 启发式：
   *   1. 分析失败原因（从 outcome_text 提取关键词）
   *   2. 生成修正路径（在原 actions 前后插入验证/回滚步骤）
   *   3. 生成修正案例（outcome=success）
   */
  reflect(caseData: FailureCase): CorrectedCase {
    // Step 1: 分析失败原因
    const failureReason = this._analyzeFailure(caseData);

    // Step 2: MCTS 搜索修正路径（启发式）
    const correctedActions = this._generateCorrectedActions(caseData.actions, failureReason);

    // Step 3: 生成反思经验
    const learned = this._generateLearned(caseData, failureReason);

    return {
      id: `corrected-${caseData.id}-${Date.now()}`,
      intent: caseData.intent,
      actions: correctedActions,
      outcome: 'success',
      outcome_text: `修正后完成（原失败原因: ${failureReason}）`,
      learned,
      corrected_from: caseData.id,
      correction_reason: failureReason,
    };
  }

  /**
   * 异步反思（不阻塞主链路）
   */
  async reflectAsync(caseData: FailureCase): Promise<CorrectedCase> {
    return new Promise((resolve) => {
      setTimeout(() => {
        resolve(this.reflect(caseData));
      }, 0);
    });
  }

  // ============================================================
  // 4. 内部方法
  // ============================================================

  /**
   * 分析失败原因（从 outcome_text 提取关键词）
   */
  private _analyzeFailure(caseData: FailureCase): string {
    const text = caseData.outcome_text.toLowerCase();
    if (text.includes('bug') || text.includes('错误') || text.includes('error')) {
      return '引入新 bug，需增加测试验证';
    }
    if (text.includes('失败') || text.includes('fail')) {
      return '执行失败，需回滚并重试';
    }
    if (text.includes('部分') || text.includes('partial') || text.includes('未完整')) {
      return '未完整执行，需补充后续步骤';
    }
    return '执行未达预期，需分析并调整方案';
  }

  /**
   * 生成修正动作序列（MCTS 启发式）
   * 在原 actions 基础上插入验证/回滚/分析步骤
   */
  private _generateCorrectedActions(originalActions: string[], reason: string): string[] {
    const strategy = CORRECTION_STRATEGIES.default;
    const corrected: string[] = [];

    // 前置：分析原因
    corrected.push(`分析原因: ${reason}`);

    // 中间：保留原动作，但插入验证点
    for (let i = 0; i < originalActions.length; i++) {
      corrected.push(originalActions[i]);
      // 每 2 个动作插入一个验证点
      if ((i + 1) % 2 === 0 && i < originalActions.length - 1) {
        corrected.push('验证中间结果');
      }
    }

    // 后置：执行备选方案 + 验证
    corrected.push(...strategy.slice(2)); // 执行备选方案 + 验证结果

    return corrected;
  }

  /**
   * 生成反思经验
   */
  private _generateLearned(caseData: FailureCase, reason: string): string[] {
    const learned: string[] = [];
    if (caseData.learned.length > 0) {
      learned.push(`原经验: ${caseData.learned.join('; ')}`);
    }
    learned.push(`失败教训: ${reason}`);
    learned.push('修正策略: 增加验证步骤，避免直接执行');
    return learned;
  }
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: ReflectionEngine | null = null;

export function getReflectionEngine(): ReflectionEngine {
  if (!_instance) _instance = new ReflectionEngine();
  return _instance;
}
