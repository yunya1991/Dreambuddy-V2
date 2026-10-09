/**
 * ReflectionTrainingLoop — C层反射决策训练循环
 * ==========================================
 * SPEC-20261009 §4.2.3 P2-2
 *
 * 训练数据：(context, action, outcome) 三元组 → 5种反射决策
 * 训练方法：① CBR 案例检索 ② 决策规则蒸馏（频繁模式→规则）③ MCTS 纠错（失败→修正决策）
 * 触发节奏：桶满 50 条触发
 * 复现目标：决策一致率 ≥ 75%
 * 依赖：S层 + DSH 先训
 *
 * 5种反射决策：
 *   CONTINUE — 继续执行
 *   REDO — 重做当前步骤
 *   INSERT_BEFORE — 在当前步骤前插入
 *   JUMP_TO — 跳转到其他步骤
 *   EARLY_TERMINATE — 提前终止
 *
 * 位置: 3.1-FRONTEND/src/lib/c-reflection-training-loop.ts
 */

// ============================================================
// 1. 类型定义
// ============================================================

export type ReflectionDecision = 'CONTINUE' | 'REDO' | 'INSERT_BEFORE' | 'JUMP_TO' | 'EARLY_TERMINATE';

export interface ReflectionTrainingData {
  context_summary: string;
  action_taken: string;
  outcome: 'success' | 'failure' | 'partial';
  expected_decision: ReflectionDecision;
}

export interface ReflectionTrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  decision_rules: Record<ReflectionDecision, number>;
  decision_accuracy: number;
  correction_count: number;
  timestamp: number;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // SPEC v0.3 C层

// 失败→纠正决策映射（MCTS 纠错启发式）
const FAILURE_CORRECTION: Record<ReflectionDecision, ReflectionDecision> = {
  CONTINUE: 'EARLY_TERMINATE',
  REDO: 'INSERT_BEFORE',
  INSERT_BEFORE: 'REDO',
  JUMP_TO: 'REDO',
  EARLY_TERMINATE: 'CONTINUE',
};

// ============================================================
// 3. ReflectionTrainingLoop 主类
// ============================================================

export class ReflectionTrainingLoop {
  readonly bucketThreshold: number;
  private bucket: ReflectionTrainingData[] = [];

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
  }

  get bucketCount(): number {
    return this.bucket.length;
  }

  addTrainingData(data: ReflectionTrainingData): void {
    this.bucket.push(data);
  }

  shouldTrain(): boolean {
    return this.bucket.length >= this.bucketThreshold;
  }

  /**
   * 执行训练
   * ① 决策规则蒸馏：统计各决策频率 + outcome 加权
   * ② MCTS 纠错：失败案例映射到纠正决策
   * ③ 计算决策一致率（训练数据自预测准确率）
   */
  train(): ReflectionTrainingResult {
    const count = this.bucket.length;

    if (count < this.bucketThreshold) {
      return {
        trained: false,
        bucket_count: count,
        bucket_threshold: this.bucketThreshold,
        decision_rules: { CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0 },
        decision_accuracy: 0,
        correction_count: 0,
        timestamp: Date.now(),
      };
    }

    // Step 1: 决策规则蒸馏 — 统计各决策频率（outcome 加权）
    const decisionCounts: Record<ReflectionDecision, number> = {
      CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0,
    };
    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.3 };

    for (const d of this.bucket) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      decisionCounts[d.expected_decision] += w;
    }

    // Step 2: MCTS 纠错 — 失败案例的纠正决策也纳入规则
    let correctionCount = 0;
    for (const d of this.bucket) {
      if (d.outcome === 'failure') {
        const correctedDecision = FAILURE_CORRECTION[d.expected_decision];
        decisionCounts[correctedDecision] += 0.5; // 纠正决策权重
        correctionCount += 1;
      }
    }

    // 归一化决策规则为权重
    const totalWeight = Object.values(decisionCounts).reduce((s, v) => s + v, 0);
    const decisionRules: Record<ReflectionDecision, number> = {
      CONTINUE: totalWeight > 0 ? decisionCounts.CONTINUE / totalWeight : 0,
      REDO: totalWeight > 0 ? decisionCounts.REDO / totalWeight : 0,
      INSERT_BEFORE: totalWeight > 0 ? decisionCounts.INSERT_BEFORE / totalWeight : 0,
      JUMP_TO: totalWeight > 0 ? decisionCounts.JUMP_TO / totalWeight : 0,
      EARLY_TERMINATE: totalWeight > 0 ? decisionCounts.EARLY_TERMINATE / totalWeight : 0,
    };

    // Step 3: 决策一致率（用最高权重决策预测）
    const topDecision = (Object.entries(decisionRules) as [ReflectionDecision, number][])
      .sort((a, b) => b[1] - a[1])[0][0];
    let correct = 0;
    for (const d of this.bucket) {
      if (d.expected_decision === topDecision) correct++;
    }
    const decisionAccuracy = correct / count;

    // 清空桶
    this.bucket = [];

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      decision_rules: decisionRules,
      decision_accuracy: decisionAccuracy,
      correction_count: correctionCount,
      timestamp: Date.now(),
    };
  }

  clear(): void {
    this.bucket = [];
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: ReflectionTrainingLoop | null = null;

export function getReflectionTrainingLoop(): ReflectionTrainingLoop {
  if (!_instance) _instance = new ReflectionTrainingLoop();
  return _instance;
}
