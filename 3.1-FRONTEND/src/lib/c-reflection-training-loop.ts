/**
 * ReflectionTrainingLoop — C层反射决策训练循环
 * ==========================================
 * SPEC-20261009 §4.2.3 P2-2
 * SPEC-20261011 v0.5 P0: 持续算法驱动训练 (ReplayBuffer + trainIncremental)
 *
 * 训练数据：(context, action, outcome) 三元组 → 5种反射决策
 * 训练方法：① CBR 案例检索 ② 决策规则蒸馏（频繁模式→规则）③ MCTS 纠错（失败→修正决策）
 * 触发节奏：v0.5 三层触发（微批增量 + 漂移回调 + 优先级触发）
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
 * v0.5 变更:
 *   - bucket → ReplayBuffer（永不清空，循环覆盖）
 *   - 新增 trainIncremental()（增量训练，不清空 buffer）
 *   - 规则权重低于 0.05 移入 ruleArchive（不从系统删除）
 *   - 新增 checkpoint() / restore()（模型状态持久化）
 *   - 保留 train()（全量训练，向后兼容）
 *
 * 位置: 3.1-FRONTEND/src/lib/c-reflection-training-loop.ts
 */

import { ReplayBuffer, type QualityLevel, LAYER_EWMA_LAMBDA, LAYER_MICRO_BATCH } from './replay-buffer';
import { DriftDetectorAdapter } from './drift-detector-adapter';
import { ModelCheckpoint, DEFAULT_PERSIST_DIR } from './model-checkpoint';

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
  /** v0.5 新增: 增量训练步数 */
  incrementalStep?: number;
  /** v0.5 新增: buffer 统计 */
  bufferStats?: ReturnType<ReplayBuffer['getStats']>;
}

/** v0.5: 模型状态（用于 checkpoint/restore） */
export interface CModelState {
  decisionCounts: Record<ReflectionDecision, number>;
  decisionRules: Record<ReflectionDecision, number>;
  ruleArchive: ReflectionDecision[];
  correctionCount: number;
  step: number;
  timestamp: number;
  version: string;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // SPEC v0.3 C层
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint
const RULE_ARCHIVE_THRESHOLD = 0.05; // v0.5: 权重低于此值移入 ruleArchive

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

  /** v0.5: ReplayBuffer 替代 bucket */
  private buffer: ReplayBuffer;

  /** v0.5: 模型状态（增量更新，不重置） */
  private _decisionCounts: Record<ReflectionDecision, number> = {
    CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0,
  };
  private _ruleArchive: ReflectionDecision[] = [];
  private _correctionCount = 0;
  private _step = 0;
  private _driftFlag = false;
  private _ewmaLambda: number;

  /** v0.5 P1: 三层触发 */
  private driftAdapter: DriftDetectorAdapter;
  private checkpoint: ModelCheckpoint;
  private _microBatchSize: number;
  private _baselineSet = false;
  /** v0.5.2: 累计 add 次数，用于满 buffer 后的微批触发（buffer.size 满后恒定，不能用 size%micro） */
  private _addCount = 0;

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
    // v0.5: 创建 C 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('C');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.C;
    // v0.5 P1: 漂移检测 + 检查点
    this.driftAdapter = new DriftDetectorAdapter('C');
    this.checkpoint = new ModelCheckpoint({ persistDir: DEFAULT_PERSIST_DIR });
    this._microBatchSize = LAYER_MICRO_BATCH.C;
    // v0.5.1: 从磁盘 checkpoint 恢复模型状态（热重载/服务重启后）
    // 测试环境跳过：避免测试间状态污染
    // FAIL-OPEN: checkpoint 损坏/格式不兼容时降级为全新状态，不阻塞启动
    if (process.env.NODE_ENV !== 'test') {
      try {
        const latestCkpt = this.checkpoint.restore('C');
        if (latestCkpt) {
          this.restoreModel(latestCkpt.state as unknown as CModelState);
        }
      } catch (e) {
        console.error('[ReflectionTrainingLoop] checkpoint restore failed, fallback to fresh state:', e);
      }
    }
  }

  /** 获取当前 buffer 中数据量（向后兼容 bucketCount） */
  get bucketCount(): number {
    return this.buffer.size;
  }

  /** v0.5: 获取 buffer 引用 */
  get replayBuffer(): ReplayBuffer {
    return this.buffer;
  }

  /** v0.5: 获取增量训练步数 */
  get step(): number {
    return this._step;
  }

  /**
   * v0.5: 添加训练数据到 buffer（支持 quality 参数）
   * 向后兼容: 不传 quality 时默认 'C'
   */
  addTrainingData(data: ReflectionTrainingData, quality?: QualityLevel): void {
    const q = quality || 'C';
    this.buffer.add(data, q);
    this._addCount++;
    this._checkTriggers(q);
  }

  /**
   * v0.5 P1: 三层触发检查
   * ① 优先级触发: quality='S' → 立即训练
   * ② 微批触发: buffer.size % microBatchSize === 0 → 训练
   * ③ 漂移触发: KL > 阈值 → 训练
   * 冷启动守卫: buffer.size < microBatchSize → 不触发（优先级除外）
   */
  private _checkTriggers(quality: QualityLevel): void {
    // 优先级触发: quality='S' 绕过冷启动守卫
    if (quality === 'S') {
      this._triggerTrain('priority');
      return;
    }

    // 冷启动守卫
    if (this.buffer.size < this._microBatchSize) return;

    // 首次 warmup 时设置基线
    if (!this._baselineSet) {
      this.driftAdapter.setBaseline(this.getModelSnapshot());
      this._baselineSet = true;
    }

    // 微批触发: 每 N 条数据触发
    if (this._addCount % this._microBatchSize === 0) {
      this._triggerTrain('micro-batch');
      return;
    }

    // 漂移触发: KL > 阈值
    const driftResult = this.driftAdapter.detectDrift(this.getModelSnapshot());
    if (driftResult.drift_detected) {
      this._triggerTrain('drift');
    }
  }

  /**
   * v0.5 P1: 执行触发训练 + 检查点
   */
  private _triggerTrain(reason: 'priority' | 'micro-batch' | 'drift'): void {
    const entries = this.buffer.sample(this._microBatchSize);
    const batch = entries.map(e => e.data as ReflectionTrainingData);
    this.trainIncremental(batch);
    this._driftFlag = (reason === 'drift');

    // 定期检查点
    if (this._step % CHECKPOINT_INTERVAL === 0 && this._step > 0) {
      this.checkpoint.checkpoint('C', this.getModelSnapshot());
    }
  }

  /** 检查桶是否满（向后兼容） */
  shouldTrain(): boolean {
    return this.buffer.size >= this.bucketThreshold;
  }

  // ============================================================
  // v0.5 P0: trainIncremental — 增量训练（不清空 buffer）
  // ============================================================

  /**
   * SPEC v0.5 §3.3.3: C 层新增规则 + 规则权重衰减
   *
   * 增量策略:
   *   1. EWMA 衰减旧规则权重: decisionCounts[d] *= (1-λ)
   *   2. 增量更新决策频率: outcome 加权
   *   3. MCTS 纠错: 失败案例映射到纠正决策
   *   4. 权重低于 0.05 的规则移入 ruleArchive（不从系统删除）
   *   5. buffer.decayAll() — 旧数据权重衰减
   *   6. 保留模型状态，不清空
   */
  trainIncremental(batch: ReflectionTrainingData[]): ReflectionTrainingResult {
    if (batch.length === 0) {
      return this._emptyResult();
    }

    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.3 };

    // Step 1: EWMA 衰减旧规则权重
    for (const d of Object.keys(this._decisionCounts) as ReflectionDecision[]) {
      this._decisionCounts[d] *= (1 - this._ewmaLambda);
    }

    // Step 2: 增量更新决策频率（outcome 加权）
    for (const d of batch) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      this._decisionCounts[d.expected_decision] += this._ewmaLambda * w;
    }

    // Step 3: MCTS 纠错 — 失败案例的纠正决策
    for (const d of batch) {
      if (d.outcome === 'failure') {
        const correctedDecision = FAILURE_CORRECTION[d.expected_decision];
        this._decisionCounts[correctedDecision] += this._ewmaLambda * 0.5;
        this._correctionCount += 1;
      }
    }

    // Step 4: 规则权重低于 0.05 移入 ruleArchive（不从系统删除）
    const totalWeight = Object.values(this._decisionCounts).reduce((s, v) => s + v, 0);
    if (totalWeight > 0) {
      for (const d of Object.keys(this._decisionCounts) as ReflectionDecision[]) {
        const normalized = this._decisionCounts[d] / totalWeight;
        if (normalized < RULE_ARCHIVE_THRESHOLD && !this._ruleArchive.includes(d)) {
          this._ruleArchive.push(d);
        }
      }
    }

    // Step 5: buffer 衰减（不清空）
    this.buffer.decayAll();

    // Step 6: 更新步数
    this._step++;

    return {
      trained: true,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      decision_rules: this._buildRules(),
      decision_accuracy: 0, // 增量训练不重算
      correction_count: this._correctionCount,
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  // ============================================================
  // v0.2 向后兼容: train — 全量训练（不清空 buffer）
  // ============================================================

  /**
   * 执行全量训练
   * v0.5 变更: 使用 buffer.getAll() 代替 bucket，训练后不清空
   * ① 决策规则蒸馏：统计各决策频率 + outcome 加权
   * ② MCTS 纠错：失败案例映射到纠正决策
   * ③ 计算决策一致率（训练数据自预测准确率）
   */
  train(): ReflectionTrainingResult {
    const allEntries = this.buffer.getAll();
    const count = allEntries.length;

    if (count < this.bucketThreshold) {
      return this._emptyResult();
    }

    // 从 buffer entries 提取 data
    const allData: ReflectionTrainingData[] = allEntries.map(e => e.data);

    // Step 1: 决策规则蒸馏 — 统计各决策频率（outcome 加权）
    const decisionCounts: Record<ReflectionDecision, number> = {
      CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0,
    };
    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.3 };

    for (const d of allData) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      decisionCounts[d.expected_decision] += w;
    }

    // Step 2: MCTS 纠错 — 失败案例的纠正决策也纳入规则
    let correctionCount = 0;
    for (const d of allData) {
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
    for (const d of allData) {
      if (d.expected_decision === topDecision) correct++;
    }
    const decisionAccuracy = correct / count;

    // v0.5: 更新模型状态（不清空 buffer）
    this._decisionCounts = decisionCounts;
    this._correctionCount = correctionCount;
    this._step++;

    // v0.5: 全量训练后也做 buffer 衰减（但不清空）
    this.buffer.decayAll();

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      decision_rules: decisionRules,
      decision_accuracy: decisionAccuracy,
      correction_count: correctionCount,
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  /** v0.5: 只重置模型状态，不清空 buffer */
  clear(): void {
    this._decisionCounts = { CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0 };
    this._ruleArchive = [];
    this._correctionCount = 0;
  }

  // ============================================================
  // v0.5 P1: checkpoint / restore
  // ============================================================

  /** v0.5: 获取模型状态快照 */
  getModelSnapshot(): CModelState {
    return {
      decisionCounts: { ...this._decisionCounts },
      decisionRules: this._buildRules(),
      ruleArchive: [...this._ruleArchive],
      correctionCount: this._correctionCount,
      step: this._step,
      timestamp: Date.now(),
      version: 'v0.5-20261011',
    };
  }

  /** v0.5: 恢复模型状态 */
  restoreModel(state: CModelState): void {
    this._decisionCounts = { ...state.decisionCounts };
    this._ruleArchive = [...state.ruleArchive];
    this._correctionCount = state.correctionCount;
    this._step = state.step;
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _emptyResult(): ReflectionTrainingResult {
    return {
      trained: false,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      decision_rules: { CONTINUE: 0, REDO: 0, INSERT_BEFORE: 0, JUMP_TO: 0, EARLY_TERMINATE: 0 },
      decision_accuracy: 0,
      correction_count: 0,
      timestamp: Date.now(),
    };
  }

  private _buildRules(): Record<ReflectionDecision, number> {
    const totalWeight = Object.values(this._decisionCounts).reduce((s, v) => s + v, 0);
    return {
      CONTINUE: totalWeight > 0 ? this._decisionCounts.CONTINUE / totalWeight : 0,
      REDO: totalWeight > 0 ? this._decisionCounts.REDO / totalWeight : 0,
      INSERT_BEFORE: totalWeight > 0 ? this._decisionCounts.INSERT_BEFORE / totalWeight : 0,
      JUMP_TO: totalWeight > 0 ? this._decisionCounts.JUMP_TO / totalWeight : 0,
      EARLY_TERMINATE: totalWeight > 0 ? this._decisionCounts.EARLY_TERMINATE / totalWeight : 0,
    };
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
