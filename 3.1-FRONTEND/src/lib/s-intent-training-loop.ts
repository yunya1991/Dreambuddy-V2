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
import { embedTexts, cosineSimilarity, ngramSimilarity } from './knowledge-rag';

// ============================================================
// 1. 类型定义
// ============================================================

export interface TrainingData {
  message: string;
  intent_type: string;
  entities?: string[];
  /** P2: 大认知系统正向意图识别 — quality 字段来自认知记忆/SKILL/文档采集器 */
  quality?: 'S' | 'A' | 'B' | 'C' | 'D';
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
  /** P2: 归档的低权重 intent 列表（参照 C 层 ruleArchive） */
  intentArchive: string[];
  /** v0.6: 语义原型向量（per intent_type） */
  semanticPrototypes?: Record<string, number[]>;
  /** v0.6: 语义层开关 */
  semanticEnabled?: boolean;
  /** v0.6: 语义训练步数 */
  semanticStep?: number;
  /** v0.6: 代表性文本（用于 n-gram fallback） */
  semanticSamples?: Record<string, string[]>;
}

/** P2: intent 归档阈值（归一化权重 < 此值 → 移入 archive）
 * S 层比 C 层 0.05 更严格（0.01），因 S 层权重本身较小。
 */
export const INTENT_ARCHIVE_THRESHOLD = 0.01;

/** P2: 大认知系统正向意图 boost 因子
 * quality=S → ×3 频率（最强 boost）
 * quality=A → ×2 频率（中等 boost）
 * 其他 → ×1（无 boost）
 */
const QUALITY_BOOST: Record<string, number> = {
  S: 3,
  A: 2,
  B: 1,
  C: 1,
  D: 1,
};

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // 向后兼容: 全量训练阈值
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint

/** v0.6: 混合打分权重 α（偏重 TF-IDF 主干，语义只做辅助修正） */
export const SEMANTIC_FUSION_ALPHA = 0.7;
/** v0.6: 语义原型 EWMA 更新系数（慢更新保证稳定性） */
export const SEMANTIC_EWMA_LAMBDA = 0.3;

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
  /** v0.5.2: 累计 add 次数，用于满 buffer 后的微批触发（buffer.size 满后恒定，不能用 size%micro） */
  private _addCount = 0;
  /** P2: 归档的低权重 intent 列表 */
  private _intentArchive: string[] = [];

  /** v0.6: 语义原型向量（per intent_type） */
  private _semanticPrototypes: Record<string, number[]> = {};
  /** v0.6: 代表性文本（用于 n-gram fallback） */
  private _semanticSamples: Record<string, string[]> = {};
  /** v0.6: 语义层开关 */
  private _semanticEnabled = true;
  /** v0.6: 语义训练步数 */
  private _semanticStep = 0;
  /** v0.6: 混合打分权重 α */
  private _semanticFusionAlpha: number;
  /** v0.6: 语义原型 EWMA 更新系数 */
  private _semanticEwmaLambda: number;
  /** v0.6: n-gram 降级开关 */
  private _ngramFallback: boolean;

  constructor(opts?: {
    bucketThreshold?: number;
    semanticEnabled?: boolean;
    semanticFusionAlpha?: number;
    semanticEwmaLambda?: number;
    ngramFallback?: boolean;
  }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
    // v0.5: 创建 S 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('S');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.S;
    // v0.6: 语义层配置
    this._semanticEnabled = opts?.semanticEnabled ?? true;
    this._semanticFusionAlpha = opts?.semanticFusionAlpha ?? SEMANTIC_FUSION_ALPHA;
    this._semanticEwmaLambda = opts?.semanticEwmaLambda ?? SEMANTIC_EWMA_LAMBDA;
    this._ngramFallback = opts?.ngramFallback ?? true;
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

  /** v0.6: 获取混合打分权重 α */
  get semanticFusionAlpha(): number {
    return this._semanticFusionAlpha;
  }

  /** v0.6: 获取语义原型 EWMA 更新系数 */
  get semanticEwmaLambda(): number {
    return this._semanticEwmaLambda;
  }

  /**
   * v0.5: 添加训练数据到 buffer（支持 quality 参数）
   * v0.5 P1: 三层触发检查（微批 + 漂移 + 优先级）
   * P3: intent_type 长度门控 — 超过 50 字符截断（数据质量保护）
   * 向后兼容: 不传 quality 时默认 'C'
   */
  addTrainingData(data: TrainingData, quality?: QualityLevel): void {
    const q = quality || 'C';
    // P3: intent_type 长度门控
    const sanitized: TrainingData = {
      ...data,
      intent_type: data.intent_type.length > 50
        ? data.intent_type.slice(0, 50)
        : data.intent_type,
    };
    this.buffer.add(sanitized, q);
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
      const { message, intent_type, quality } = data;

      // 词频
      for (let i = 0; i < message.length - 1; i++) {
        const gram = message.slice(i, i + 2);
        if (!this._typeKeywords[intent_type]) this._typeKeywords[intent_type] = {};
        this._typeKeywords[intent_type][gram] = (this._typeKeywords[intent_type][gram] || 0) + 1;
      }

      // 意图频率 — P2: 大认知系统正向意图 boost
      // quality=S → ×3 频率, quality=A → ×2 频率（来自 QUALITY_BOOST 表）
      const boost = quality ? (QUALITY_BOOST[quality] ?? 1) : 1;
      this._intentFreq[intent_type] = (this._intentFreq[intent_type] || 0) + boost;
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

    // Step 6: P2 ruleArchive — 归一化权重 < 阈值的 intent 移入 archive
    this._archiveLowWeightIntents();

    // Step 7: 更新步数
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

  /**
   * P2: 归档低权重 intent（参照 C 层 ruleArchive）。
   * 归一化权重 = weights[intent] / sum(all weights)
   * 归一化权重 < INTENT_ARCHIVE_THRESHOLD → 移入 _intentArchive，从 _weights 删除
   */
  private _archiveLowWeightIntents(): void {
    const totalWeight = Object.values(this._weights).reduce((s, w) => s + w, 0);
    if (totalWeight <= 0) return;

    const toArchive: string[] = [];
    for (const [intent, weight] of Object.entries(this._weights)) {
      const normalized = weight / totalWeight;
      if (normalized < INTENT_ARCHIVE_THRESHOLD
          && !this._intentArchive.includes(intent)) {
        toArchive.push(intent);
      }
    }

    for (const intent of toArchive) {
      this._intentArchive.push(intent);
      delete this._weights[intent];
      // 同时清理频率表和关键词表（避免后续误用）
      delete this._intentFreq[intent];
      delete this._typeKeywords[intent];
    }
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
    // P2: 清空归档
    this._intentArchive = [];
    // v0.6: 清空语义层
    this._semanticPrototypes = {};
    this._semanticSamples = {};
    this._semanticStep = 0;
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
      version: 'v0.6-20261012',
      // P2: 包含归档列表
      intentArchive: [...this._intentArchive],
      // v0.6: 语义层状态
      semanticPrototypes: JSON.parse(JSON.stringify(this._semanticPrototypes)),
      semanticEnabled: this._semanticEnabled,
      semanticStep: this._semanticStep,
      semanticSamples: JSON.parse(JSON.stringify(this._semanticSamples)),
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
    // P2: 恢复归档列表（兼容旧 snapshot 无此字段）
    this._intentArchive = state.intentArchive ? [...state.intentArchive] : [];
    // v0.6: 恢复语义层状态（兼容旧 snapshot 无语义字段）
    this._semanticPrototypes = state.semanticPrototypes
      ? JSON.parse(JSON.stringify(state.semanticPrototypes)) : {};
    this._semanticEnabled = state.semanticEnabled !== undefined ? state.semanticEnabled : true;
    this._semanticStep = state.semanticStep || 0;
    this._semanticSamples = state.semanticSamples
      ? JSON.parse(JSON.stringify(state.semanticSamples)) : {};
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // v0.6: 语义嵌入混合架构
  // ============================================================

  /**
   * v0.6: 更新语义原型向量（S/A/B 级样本做锚点）
   *
   * 策略:
   *   1. 过滤 batch，保留 quality=S/A/B 的样本
   *   2. 调 DeepSeek API 批量向量化
   *   3. 冷启动: 首条样本直接初始化原型
   *   4. 后续: EWMA β×new + (1-β)×old
   *   5. 保存代表性文本用于 n-gram fallback
   *   FAIL-OPEN: API 失败不阻塞训练，只 warn
   */
  async updateSemanticPrototypes(batch: TrainingData[]): Promise<void> {
    // P2: 放宽到 S/A/B 级（C/D 级仍跳过）
    const saSamples = batch.filter(d => d.quality === 'S' || d.quality === 'A' || d.quality === 'B');
    if (saSamples.length === 0) return;

    // 保存代表性文本（总是执行，用于 n-gram fallback — API 不可达时的降级方案）
    for (const sample of saSamples) {
      const { intent_type, message } = sample;
      if (!this._semanticSamples[intent_type]) this._semanticSamples[intent_type] = [];
      this._semanticSamples[intent_type].push(message);
      if (this._semanticSamples[intent_type].length > 5) {
        this._semanticSamples[intent_type].shift();
      }
    }

    try {
      const texts = saSamples.map(d => d.message);
      const vectors = await embedTexts(texts);
      if (vectors.length !== saSamples.length) return;

      for (let i = 0; i < saSamples.length; i++) {
        const { intent_type } = saSamples[i];
        const vec = vectors[i];
        const old = this._semanticPrototypes[intent_type];
        if (!old || old.length === 0) {
          // 冷启动：直接初始化
          this._semanticPrototypes[intent_type] = vec;
        } else {
          // EWMA: β × new + (1-β) × old
          this._semanticPrototypes[intent_type] = old.map((v, j) =>
            this._semanticEwmaLambda * (vec[j] || 0) + (1 - this._semanticEwmaLambda) * v
          );
        }
      }
      this._semanticStep++;
    } catch (e) {
      // FAIL-OPEN: embedding API 不可达，降级到 n-gram 相似度
      // _semanticSamples 已保存，predictIntent 可用 n-gram 做语义匹配
      this._semanticStep++;
      console.warn('[IntentTrainingLoop] embedding API 不可用，降级到 n-gram 相似度:', e instanceof Error ? e.message : e);
    }
  }

  /**
   * v0.6: 混合打分预测意图
   *
   * 三级 FAIL-OPEN:
   *   Level 1: DeepSeek API 可用 → 语义 embedding + TF-IDF 混合
   *   Level 2: API 不可用 → n-gram 相似度 + TF-IDF 混合
   *   Level 3: 无原型 / 语义关闭 → 纯 TF-IDF
   *
   * 公式: final_score = α × tfidf_score + (1-α) × semantic_sim
   */
  async predictIntent(message: string): Promise<string> {
    // Level 3: 无训练数据 → 返回空
    if (this._step === 0 || Object.keys(this._weights).length === 0) return '';

    // 语义未启用 or (无原型且无样本) → 纯 TF-IDF
    if (!this._semanticEnabled
        || (Object.keys(this._semanticPrototypes).length === 0
            && Object.keys(this._semanticSamples).length === 0)) {
      return this._predictIntent(message, this._typeKeywords);
    }

    // 获取候选 intents（有原型 or 有样本，且有 weights 的交集）
    const protoKeys = Object.keys(this._semanticPrototypes);
    const sampleKeys = Object.keys(this._semanticSamples);
    const allKeys = new Set([...protoKeys, ...sampleKeys]);
    const candidates = [...allKeys].filter(k => this._weights[k] !== undefined);
    if (candidates.length === 0) return this._predictIntent(message, this._typeKeywords);

    // Level 1: 尝试 DeepSeek API embedding
    let queryVec: number[] | null = null;
    try {
      const vectors = await embedTexts([message]);
      if (vectors.length > 0) queryVec = vectors[0];
    } catch {
      // API 失败 → 降级
      queryVec = null;
    }

    let bestType = '';
    let bestScore = -1;

    for (const intent of candidates) {
      // TF-IDF 分数
      const tfidfScore = this._tfidfScore(message, intent);

      if (queryVec) {
        // Level 1: 语义 embedding 混合
        const semSim = cosineSimilarity(queryVec, this._semanticPrototypes[intent]);
        const finalScore = this._semanticFusionAlpha * tfidfScore
          + (1 - this._semanticFusionAlpha) * semSim;
        if (finalScore > bestScore) {
          bestScore = finalScore;
          bestType = intent;
        }
      } else if (this._ngramFallback) {
        // Level 2: n-gram fallback 混合
        let ngSim = 0;
        const samples = this._semanticSamples[intent] || [];
        for (const s of samples) {
          ngSim = Math.max(ngSim, ngramSimilarity(message, s));
        }
        const finalScore = this._semanticFusionAlpha * tfidfScore
          + (1 - this._semanticFusionAlpha) * ngSim;
        if (finalScore > bestScore) {
          bestScore = finalScore;
          bestType = intent;
        }
      } else {
        // n-gram 关闭 → 纯 TF-IDF（α=1 等效）
        if (tfidfScore > bestScore) {
          bestScore = tfidfScore;
          bestType = intent;
        }
      }
    }

    // 如果语义打分没找到候选，回退到纯 TF-IDF
    if (!bestType) return this._predictIntent(message, this._typeKeywords);
    return bestType;
  }

  /**
   * v0.6: TF-IDF 单意图打分（2-gram 匹配分数）
   */
  private _tfidfScore(message: string, intentType: string): number {
    const keywords = this._typeKeywords[intentType];
    if (!keywords) return 0;
    let score = 0;
    for (let i = 0; i < message.length - 1; i++) {
      const gram = message.slice(i, i + 2);
      score += keywords[gram] || 0;
    }
    return score;
  }

  /**
   * v0.6: 运行时切换语义层配置
   */
  setSemanticConfig(opts: {
    enabled?: boolean;
    fusionAlpha?: number;
    ewmaLambda?: number;
    ngramFallback?: boolean;
  }): void {
    if (opts.enabled !== undefined) this._semanticEnabled = opts.enabled;
    if (opts.fusionAlpha !== undefined) this._semanticFusionAlpha = opts.fusionAlpha;
    if (opts.ewmaLambda !== undefined) this._semanticEwmaLambda = opts.ewmaLambda;
    if (opts.ngramFallback !== undefined) this._ngramFallback = opts.ngramFallback;
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
