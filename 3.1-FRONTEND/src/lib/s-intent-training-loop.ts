/**
 * IntentTrainingLoop — S层意图训练循环
 * ==========================================
 * SPEC-20261009 §4.2.1 P1-5 (v0.2)
 * SPEC-20261011 v0.5 P0: 持续算法驱动训练 (ReplayBuffer + trainIncremental)
 *
 * 训练数据：session_memory 中 (message, intent) pairs
 * 训练方法：① 规则权重增量（TF-IDF + 频率统计）② DynamicRecognizer 权重更新
 * 触发节奏：v0.5 三层触发（微批增量 + 漂移回调 + 优先级触发）
 * 复现目标：intent 一致率 ≥ 80%
 * 依赖：独立可训练（与 G层并行）
 *
 * v0.5 变更:
 *   - bucket → ReplayBuffer（永不清空，循环覆盖）
 *   - 新增 trainIncremental()（增量训练，不清空 buffer）
 *   - 新增 checkpoint() / restore()（模型状态持久化）
 *   - 保留 train()（全量训练，向后兼容）
 *
 * 位置: 3.1-FRONTEND/src/lib/s-intent-training-loop.ts
 */

import { ReplayBuffer, type QualityLevel, LAYER_CAPACITY, LAYER_MICRO_BATCH, LAYER_EWMA_LAMBDA } from './replay-buffer';
import { DriftDetectorAdapter } from './drift-detector-adapter';
import { ModelCheckpoint, DEFAULT_PERSIST_DIR } from './model-checkpoint';

// ============================================================
// 1. 类型定义
// ============================================================

export interface TrainingData {
  message: string;
  intent_type: string;
  entities?: string[];
}

export interface TrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  accuracy: number;
  weights: Record<string, number>;
  timestamp: number;
  /** v0.5 新增: 增量训练步数 */
  incrementalStep?: number;
  /** v0.5 新增: buffer 统计 */
  bufferStats?: ReturnType<ReplayBuffer['getStats']>;
}

/** v0.5: 模型状态（用于 checkpoint/restore） */
export interface SModelState {
  weights: Record<string, number>;
  typeKeywords: Record<string, Record<string, number>>;
  intentFreq: Record<string, number>;
  docCount: number;
  step: number;
  drift_flag: boolean;
  timestamp: number;
  version: string;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // 向后兼容: 全量训练阈值
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint

// ============================================================
// 3. IntentTrainingLoop 主类
// ============================================================

export class IntentTrainingLoop {
  readonly bucketThreshold: number;

  /** v0.5: ReplayBuffer 替代 bucket */
  private buffer: ReplayBuffer;

  /** v0.5: 模型状态（增量更新，不重置） */
  private _weights: Record<string, number> = {};
  private _typeKeywords: Record<string, Record<string, number>> = {};
  private _intentFreq: Record<string, number> = {};
  private _docCount = 0;
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
    // v0.5: 创建 S 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('S');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.S;
    // v0.5 P1: 漂移检测 + 检查点
    this.driftAdapter = new DriftDetectorAdapter('S');
    this.checkpoint = new ModelCheckpoint({ persistDir: DEFAULT_PERSIST_DIR });
    this._microBatchSize = LAYER_MICRO_BATCH.S;
    // v0.5.1: 从磁盘 checkpoint 恢复模型状态（热重载/服务重启后）
    // 测试环境跳过：避免测试间状态污染
    // FAIL-OPEN: checkpoint 损坏/格式不兼容时降级为全新状态，不阻塞启动
    if (process.env.NODE_ENV !== 'test') {
      try {
        const latestCkpt = this.checkpoint.restore('S');
        if (latestCkpt) {
          this.restoreModel(latestCkpt.state as unknown as SModelState);
        }
      } catch (e) {
        console.error('[IntentTrainingLoop] checkpoint restore failed, fallback to fresh state:', e);
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
   * v0.5 P1: 三层触发检查（微批 + 漂移 + 优先级）
   * 向后兼容: 不传 quality 时默认 'C'
   */
  addTrainingData(data: TrainingData, quality?: QualityLevel): void {
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
    const batch = entries.map(e => e.data as TrainingData);
    this.trainIncremental(batch);
    this._driftFlag = (reason === 'drift');

    // 定期检查点
    if (this._step % CHECKPOINT_INTERVAL === 0 && this._step > 0) {
      this.checkpoint.checkpoint('S', this.getModelSnapshot());
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
   * SPEC v0.5 §3.3.1: S 层 TF-IDF 增量更新
   *
   * 增量策略:
   *   1. 增量更新词频表: term_freq[term] += 1
   *   2. 增量更新文档频率: doc_freq[term] += 1（新文档到达）
   *   3. 增量更新意图频率: intent_freq[intent_type] += 1
   *   4. EWMA 衰减旧权重: weights[intent] = λ × new + (1-λ) × old
   *   5. buffer.decayAll() — 旧数据权重衰减
   *   6. 保留模型状态，不清空
   */
  trainIncremental(batch: TrainingData[]): TrainingResult {
    if (batch.length === 0) {
      return this._emptyResult();
    }

    // Step 1-3: 增量更新频率表
    for (const data of batch) {
      const { message, intent_type } = data;

      // 词频
      for (let i = 0; i < message.length - 1; i++) {
        const gram = message.slice(i, i + 2);
        if (!this._typeKeywords[intent_type]) this._typeKeywords[intent_type] = {};
        this._typeKeywords[intent_type][gram] = (this._typeKeywords[intent_type][gram] || 0) + 1;
      }

      // 意图频率
      this._intentFreq[intent_type] = (this._intentFreq[intent_type] || 0) + 1;
      this._docCount++;
    }

    // Step 4: EWMA 衰减旧权重 + 叠加新证据
    for (const intent of Object.keys(this._intentFreq)) {
      const newEvidence = this._intentFreq[intent] / this._docCount;
      this._weights[intent] = this._ewmaLambda * newEvidence
        + (1 - this._ewmaLambda) * (this._weights[intent] || 0);
    }

    // Step 5: buffer 衰减（不清空）
    this.buffer.decayAll();

    // Step 6: 更新步数
    this._step++;

    return {
      trained: true,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      accuracy: 0, // 增量训练不重算 accuracy
      weights: { ...this._weights },
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
   * ① 统计 intent_type 频率 → 规则权重
   * ② TF-IDF 关键词提取 → 规则增量
   * ③ 计算一致率（训练数据自预测准确率）
   */
  train(): TrainingResult {
    const allEntries = this.buffer.getAll();
    const count = allEntries.length;

    if (count < this.bucketThreshold) {
      return {
        trained: false,
        bucket_count: count,
        bucket_threshold: this.bucketThreshold,
        accuracy: 0,
        weights: {},
        timestamp: Date.now(),
      };
    }

    // 从 buffer entries 提取 data
    const allData: TrainingData[] = allEntries.map(e => e.data);

    // Step 1: 统计 intent_type 频率
    const typeCounts: Record<string, number> = {};
    const typeMessages: Record<string, string[]> = {};
    for (const d of allData) {
      typeCounts[d.intent_type] = (typeCounts[d.intent_type] || 0) + 1;
      if (!typeMessages[d.intent_type]) typeMessages[d.intent_type] = [];
      typeMessages[d.intent_type].push(d.message);
    }

    // Step 2: 计算权重（频率归一化）
    const weights: Record<string, number> = {};
    for (const [type, cnt] of Object.entries(typeCounts)) {
      weights[type] = cnt / count;
    }

    // Step 3: TF-IDF 关键词提取（简化：词频统计）
    const typeKeywords: Record<string, Record<string, number>> = {};
    for (const [type, msgs] of Object.entries(typeMessages)) {
      const kw: Record<string, number> = {};
      for (const msg of msgs) {
        for (let i = 0; i < msg.length - 1; i++) {
          const gram = msg.slice(i, i + 2);
          kw[gram] = (kw[gram] || 0) + 1;
        }
      }
      typeKeywords[type] = kw;
    }

    // Step 4: 计算一致率
    let correct = 0;
    for (const d of allData) {
      const predicted = this._predictIntent(d.message, typeKeywords);
      if (predicted === d.intent_type) correct++;
    }
    const accuracy = correct / count;

    // v0.5: 更新模型状态（不清空 buffer）
    this._weights = weights;
    this._typeKeywords = typeKeywords;
    this._intentFreq = typeCounts;
    this._docCount = count;
    this._step++;

    // v0.5: 全量训练后也做 buffer 衰减（但不清空）
    this.buffer.decayAll();

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      accuracy,
      weights,
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  /** 清空 buffer（v0.5: 向后兼容，但实际不推荐使用） */
  clear(): void {
    // v0.5: 不再清空 buffer，只重置模型状态
    this._weights = {};
    this._typeKeywords = {};
    this._intentFreq = {};
    this._docCount = 0;
  }

  // ============================================================
  // v0.5 P1: checkpoint / restore
  // ============================================================

  /** v0.5: 获取模型状态快照 */
  getModelSnapshot(): SModelState {
    return {
      weights: { ...this._weights },
      typeKeywords: JSON.parse(JSON.stringify(this._typeKeywords)),
      intentFreq: { ...this._intentFreq },
      docCount: this._docCount,
      step: this._step,
      drift_flag: this._driftFlag,
      timestamp: Date.now(),
      version: 'v0.5-20261011',
    };
  }

  /** v0.5: 恢复模型状态 */
  restoreModel(state: SModelState): void {
    this._weights = { ...state.weights };
    this._typeKeywords = JSON.parse(JSON.stringify(state.typeKeywords));
    this._intentFreq = { ...state.intentFreq };
    this._docCount = state.docCount;
    this._step = state.step;
    this._driftFlag = state.drift_flag;
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _emptyResult(): TrainingResult {
    return {
      trained: false,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      accuracy: 0,
      weights: {},
      timestamp: Date.now(),
    };
  }

  /**
   * 简化预测：用关键词频率匹配 intent_type
   */
  private _predictIntent(
    message: string,
    typeKeywords: Record<string, Record<string, number>>,
  ): string {
    let bestType = '';
    let bestScore = -1;

    for (const [type, keywords] of Object.entries(typeKeywords)) {
      let score = 0;
      for (let i = 0; i < message.length - 1; i++) {
        const gram = message.slice(i, i + 2);
        score += keywords[gram] || 0;
      }
      if (score > bestScore) {
        bestScore = score;
        bestType = type;
      }
    }

    return bestType;
  }
}

// ============================================================
// 4. 单例
// ============================================================

let _instance: IntentTrainingLoop | null = null;

export function getIntentTrainingLoop(): IntentTrainingLoop {
  if (!_instance) _instance = new IntentTrainingLoop();
  return _instance;
}
