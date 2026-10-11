/**
 * ExecutionPathTrainingLoop — DSH 执行路径训练循环
 * ==========================================
 * SPEC-20261009 §4.2.2 P2-1
 * SPEC-20261011 v0.5 P0: 持续算法驱动训练 (ReplayBuffer + trainIncremental)
 *
 * 训练数据：session_memory 中 actions 序列 + outcome
 * 训练方法：① 序列模式挖掘（频繁项集→路径模板）② 成功率加权（outcome=success 权重↑）③ 路径模板蒸馏为规则
 * 触发节奏：v0.5 三层触发（微批增量 + 漂移回调 + 优先级触发）
 * 复现目标：actions 编辑距离比 ≤ 0.3
 * 依赖：S层先训
 *
 * v0.5 变更:
 *   - bucket → ReplayBuffer（永不清空，循环覆盖）
 *   - 新增 trainIncremental()（增量训练，不清空 buffer）
 *   - 新增 checkpoint() / restore()（模型状态持久化）
 *   - 保留 train()（全量训练，向后兼容）
 *
 * 位置: 3.1-FRONTEND/src/lib/dsh-path-training-loop.ts
 */

import { ReplayBuffer, type QualityLevel, LAYER_EWMA_LAMBDA, LAYER_MICRO_BATCH } from './replay-buffer';
import { DriftDetectorAdapter } from './drift-detector-adapter';
import { ModelCheckpoint, DEFAULT_PERSIST_DIR } from './model-checkpoint';

// ============================================================
// 1. 类型定义
// ============================================================

export interface PathTrainingData {
  task: string;
  node_sequence: string[];
  outcome: 'success' | 'failure' | 'partial';
}

export interface PathTemplate {
  path: string[];
  count: number;
  success_count: number;
  success_rate: number;
  weight: number;
}

export interface PathTrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  path_templates: PathTemplate[];
  avg_path_length: number;
  success_rate: number;
  edit_distance_ratio: number;
  timestamp: number;
  /** v0.5 新增: 增量训练步数 */
  incrementalStep?: number;
  /** v0.5 新增: buffer 统计 */
  bufferStats?: ReturnType<ReplayBuffer['getStats']>;
}

/** v0.5: 模型状态（用于 checkpoint/restore） */
export interface DSHModelState {
  pathFreq: Record<string, number>;
  pathTemplates: PathTemplate[];
  step: number;
  timestamp: number;
  version: string;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // SPEC v0.3 DSH
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint
const OUTCOME_WEIGHTS: Record<string, number> = {
  success: 1.0,
  partial: 0.5,
  failure: 0.1,
};

// ============================================================
// 3. 工具函数
// ============================================================

/**
 * 编辑距离（Levenshtein）
 * 用于计算路径间相似度
 */
function editDistance(a: string[], b: string[]): number {
  const m = a.length;
  const n = b.length;
  if (m === 0) return n;
  if (n === 0) return m;

  const dp: number[][] = Array.from({ length: m + 1 }, () => new Array(n + 1).fill(0));
  for (let i = 0; i <= m; i++) dp[i][0] = i;
  for (let j = 0; j <= n; j++) dp[0][j] = j;

  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      const cost = a[i - 1] === b[j - 1] ? 0 : 1;
      dp[i][j] = Math.min(dp[i - 1][j] + 1, dp[i][j - 1] + 1, dp[i - 1][j - 1] + cost);
    }
  }
  return dp[m][n];
}

/**
 * 路径签名（用于去重和统计）
 * 注意: 参数名避免用 path（与 Node.js path 模块冲突的潜在风险）
 */
function pathSignature(nodes: string[]): string {
  if (!Array.isArray(nodes)) return String(nodes ?? '');
  return nodes.join('→');
}

// ============================================================
// 4. ExecutionPathTrainingLoop 主类
// ============================================================

export class ExecutionPathTrainingLoop {
  readonly bucketThreshold: number;

  /** v0.5: ReplayBuffer 替代 bucket */
  private buffer: ReplayBuffer;

  /** v0.5: 模型状态（增量更新，不重置） */
  private _pathStats: Record<string, { path: string[]; count: number; success_count: number; weight: number }> = {};
  private _step = 0;
  private _driftFlag = false;
  private _ewmaLambda: number;

  /** v0.5 P1: 三层触发 */
  private driftAdapter: DriftDetectorAdapter;
  private checkpoint: ModelCheckpoint;
  private _microBatchSize: number;
  private _baselineSet = false;

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
    // v0.5: 创建 DSH 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('DSH');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.DSH;
    // v0.5 P1: 漂移检测 + 检查点
    this.driftAdapter = new DriftDetectorAdapter('DSH');
    this.checkpoint = new ModelCheckpoint({ persistDir: DEFAULT_PERSIST_DIR });
    this._microBatchSize = LAYER_MICRO_BATCH.DSH;
    // v0.5.1: 从磁盘 checkpoint 恢复模型状态（热重载/服务重启后）
    // 测试环境跳过：避免测试间状态污染
    // FAIL-OPEN: checkpoint 损坏/格式不兼容时降级为全新状态，不阻塞启动
    if (process.env.NODE_ENV !== 'test') {
      try {
        const latestCkpt = this.checkpoint.restore('DSH');
        if (latestCkpt) {
          this.restoreModel(latestCkpt.state as unknown as DSHModelState);
        }
      } catch (e) {
        console.error('[ExecutionPathTrainingLoop] checkpoint restore failed, fallback to fresh state:', e);
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
  addTrainingData(data: PathTrainingData, quality?: QualityLevel): void {
    const q = quality || 'C';
    this.buffer.add(data, q);
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
    if (this.buffer.size % this._microBatchSize === 0) {
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
    const batch = entries.map(e => e.data as PathTrainingData);
    this.trainIncremental(batch);
    this._driftFlag = (reason === 'drift');

    // 定期检查点
    if (this._step % CHECKPOINT_INTERVAL === 0 && this._step > 0) {
      this.checkpoint.checkpoint('DSH', this.getModelSnapshot());
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
   * SPEC v0.5 §3.3.2: DSH 层路径频率统计增量 + 模板权重 EWMA 衰减
   *
   * 增量策略:
   *   1. EWMA 衰减旧模板权重: weight *= (1-λ)
   *   2. 增量更新路径频率: pathFreq[sig] += 1, weight += λ × outcomeWeight
   *   3. buffer.decayAll() — 旧数据权重衰减
   *   4. 保留模型状态，不清空
   */
  trainIncremental(batch: PathTrainingData[]): PathTrainingResult {
    if (batch.length === 0) {
      return this._emptyResult();
    }

    // Step 1: EWMA 衰减旧模板权重
    for (const sig of Object.keys(this._pathStats)) {
      this._pathStats[sig].weight *= (1 - this._ewmaLambda);
    }

    // Step 2: 增量更新路径频率统计
    for (const d of batch) {
      const sig = pathSignature(d.node_sequence);
      if (!this._pathStats[sig]) {
        this._pathStats[sig] = { path: d.node_sequence, count: 0, success_count: 0, weight: 0 };
      }
      this._pathStats[sig].count += 1;
      const outcomeWeight = OUTCOME_WEIGHTS[d.outcome] ?? 0.5;
      this._pathStats[sig].weight += this._ewmaLambda * outcomeWeight;
      if (d.outcome === 'success') {
        this._pathStats[sig].success_count += 1;
      }
    }

    // Step 3: buffer 衰减（不清空）
    this.buffer.decayAll();

    // Step 4: 更新步数
    this._step++;

    return {
      trained: true,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      path_templates: this._buildTemplates(),
      avg_path_length: 0, // 增量训练不重算
      success_rate: 0,
      edit_distance_ratio: 1,
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
   * ① 序列模式挖掘：统计频繁路径
   * ② 成功率加权：success 路径权重↑
   * ③ 计算平均路径长度和编辑距离比
   */
  train(): PathTrainingResult {
    const allEntries = this.buffer.getAll();
    const count = allEntries.length;

    if (count < this.bucketThreshold) {
      return this._emptyResult();
    }

    // 从 buffer entries 提取 data
    const allData: PathTrainingData[] = allEntries.map(e => e.data);

    // Step 1: 序列模式挖掘 — 统计路径频率
    const pathStats: Record<string, { path: string[]; count: number; success_count: number; weight: number }> = {};
    let totalPathLength = 0;
    let successCount = 0;

    for (const d of allData) {
      const sig = pathSignature(d.node_sequence);
      if (!pathStats[sig]) {
        pathStats[sig] = { path: d.node_sequence, count: 0, success_count: 0, weight: 0 };
      }
      pathStats[sig].count += 1;
      const outcomeWeight = OUTCOME_WEIGHTS[d.outcome] ?? 0.5;
      pathStats[sig].weight += outcomeWeight;
      if (d.outcome === 'success') {
        pathStats[sig].success_count += 1;
        successCount += 1;
      }
      totalPathLength += d.node_sequence.length;
    }

    // Step 2: 构建路径模板（按权重降序）
    const pathTemplates: PathTemplate[] = Object.values(pathStats)
      .map((s) => ({
        path: s.path,
        count: s.count,
        success_count: s.success_count,
        success_rate: s.count > 0 ? s.success_count / s.count : 0,
        weight: s.weight,
      }))
      .sort((a, b) => b.weight - a.weight);

    // Step 3: 计算指标
    const avgPathLength = count > 0 ? totalPathLength / count : 0;
    const successRate = count > 0 ? successCount / count : 0;

    // 编辑距离比：各路径与主模板（权重最高）的平均编辑距离 / 主模板长度
    let editDistanceRatio = 1;
    if (pathTemplates.length > 0) {
      const mainPath = pathTemplates[0].path;
      const mainLen = mainPath.length;
      if (mainLen > 0) {
        let totalEditDist = 0;
        for (const t of pathTemplates) {
          totalEditDist += editDistance(mainPath, t.path) * t.count;
        }
        editDistanceRatio = Math.min(1, totalEditDist / (count * mainLen));
      }
    }

    // v0.5: 更新模型状态（不清空 buffer）
    this._pathStats = pathStats;
    this._step++;

    // v0.5: 全量训练后也做 buffer 衰减（但不清空）
    this.buffer.decayAll();

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      path_templates: pathTemplates,
      avg_path_length: avgPathLength,
      success_rate: successRate,
      edit_distance_ratio: editDistanceRatio,
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  /** v0.5: 只重置模型状态，不清空 buffer */
  clear(): void {
    this._pathStats = {};
  }

  // ============================================================
  // v0.5 P1: checkpoint / restore
  // ============================================================

  /** v0.5: 获取模型状态快照 */
  getModelSnapshot(): DSHModelState {
    return {
      pathFreq: Object.fromEntries(
        Object.entries(this._pathStats).map(([k, v]) => [k, v.count]),
      ),
      pathTemplates: this._buildTemplates(),
      step: this._step,
      timestamp: Date.now(),
      version: 'v0.5-20261011',
    };
  }

  /** v0.5: 恢复模型状态 */
  restoreModel(state: DSHModelState): void {
    this._pathStats = {};
    for (const t of state.pathTemplates) {
      const sig = pathSignature(t.path);
      this._pathStats[sig] = {
        path: t.path,
        count: t.count,
        success_count: t.success_count,
        weight: t.weight,
      };
    }
    this._step = state.step;
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _emptyResult(): PathTrainingResult {
    return {
      trained: false,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      path_templates: [],
      avg_path_length: 0,
      success_rate: 0,
      edit_distance_ratio: 1,
      timestamp: Date.now(),
    };
  }

  private _buildTemplates(): PathTemplate[] {
    return Object.values(this._pathStats)
      .map((s) => ({
        path: s.path,
        count: s.count,
        success_count: s.success_count,
        success_rate: s.count > 0 ? s.success_count / s.count : 0,
        weight: s.weight,
      }))
      .sort((a, b) => b.weight - a.weight);
  }
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: ExecutionPathTrainingLoop | null = null;

export function getExecutionPathTrainingLoop(): ExecutionPathTrainingLoop {
  if (!_instance) _instance = new ExecutionPathTrainingLoop();
  return _instance;
}
