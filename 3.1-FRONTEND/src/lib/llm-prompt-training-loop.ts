/**
 * PromptOptimizationLoop — LLM Prompt 优化训练循环
 * ==========================================
 * SPEC-20261009 §4.2.5 P2-3
 * SPEC-20261011 v0.5 P0: 持续算法驱动训练 (ReplayBuffer + trainIncremental)
 *
 * 训练数据：session_memory 中 learned (经验数组) + outcome
 * 训练方法：① Prompt 模式聚类（频繁模板→最优模板）② 上下文注入优化（哪些信息最有效）③ Token 效率优化
 * 触发节奏：v0.5 三层触发（微批增量 + 漂移回调 + 优先级触发）
 * 复现目标：输出与 trae_learned 语义相似度 ≥ 0.7
 * 依赖：C层先训
 *
 * v0.5 变更:
 *   - bucket → ReplayBuffer（永不清空，循环覆盖）
 *   - 新增 trainIncremental()（增量训练，不清空 buffer）
 *   - KL 散度约束（防止 prompt 模式分布漂移过大）
 *   - 新增 checkpoint() / restore()（模型状态持久化）
 *   - 保留 train()（全量训练，向后兼容）
 *
 * 位置: 3.1-FRONTEND/src/lib/llm-prompt-training-loop.ts
 */

import { ReplayBuffer, type QualityLevel, LAYER_EWMA_LAMBDA, LAYER_MICRO_BATCH } from './replay-buffer';
import { DriftDetectorAdapter } from './drift-detector-adapter';
import { ModelCheckpoint, DEFAULT_PERSIST_DIR } from './model-checkpoint';

// ============================================================
// 1. 类型定义
// ============================================================

export interface PromptTrainingData {
  intent: string;
  learned: string[];
  outcome: 'success' | 'failure' | 'partial';
  prompt_pattern: string;
}

export interface PromptTemplate {
  template: string;
  count: number;
  success_count: number;
  success_rate: number;
}

export interface PromptTrainingResult {
  trained: boolean;
  bucket_count: number;
  bucket_threshold: number;
  prompt_templates: PromptTemplate[];
  context_keywords: Record<string, number>;
  avg_token_efficiency: number;
  semantic_similarity: number;
  timestamp: number;
  /** v0.5 新增: 增量训练步数 */
  incrementalStep?: number;
  /** v0.5 新增: buffer 统计 */
  bufferStats?: ReturnType<ReplayBuffer['getStats']>;
}

/** v0.5: 模型状态（用于 checkpoint/restore） */
export interface LLMModelState {
  templateStats: Record<string, { template: string; count: number; success_count: number; weight: number }>;
  contextKeywords: Record<string, number>;
  step: number;
  timestamp: number;
  version: string;
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 30; // SPEC v0.3 LLM
const CHECKPOINT_INTERVAL = 10; // 每 10 次增量训练后 checkpoint
const KL_DIVERGENCE_THRESHOLD = 0.5; // v0.5: KL 散度约束阈值

// ============================================================
// 3. 工具函数
// ============================================================

/**
 * 简易文本分词（中文 2-gram + 英文单词）
 */
function tokenize(text: string): string[] {
  if (!text) return [];
  const tokens: string[] = [];
  // 中文 2-gram
  const chinese = text.match(/[\u4e00-\u9fa5]+/g) || [];
  for (const seg of chinese) {
    for (let i = 0; i < seg.length - 1; i++) {
      tokens.push(seg.slice(i, i + 2));
    }
    if (seg.length === 1) tokens.push(seg);
  }
  // 英文词
  const englishWords = text.match(/[a-zA-Z]+/g) || [];
  tokens.push(...englishWords);
  return tokens;
}

/**
 * Jaccard 相似度（用于语义相似度近似）
 */
function jaccardSimilarity(a: Set<string>, b: Set<string>): number {
  if (a.size === 0 || b.size === 0) return 0;
  let intersection = 0;
  for (const v of a) {
    if (b.has(v)) intersection++;
  }
  const union = a.size + b.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

// ============================================================
// 4. PromptOptimizationLoop 主类
// ============================================================

export class PromptOptimizationLoop {
  readonly bucketThreshold: number;

  /** v0.5: ReplayBuffer 替代 bucket */
  private buffer: ReplayBuffer;

  /** v0.5: 模型状态（增量更新，不重置） */
  private _templateStats: Record<string, { template: string; count: number; success_count: number; weight: number }> = {};
  private _contextKeywords: Record<string, number> = {};
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
    // v0.5: 创建 LLM 层专用 ReplayBuffer
    this.buffer = ReplayBuffer.createForLayer('LLM');
    this._ewmaLambda = LAYER_EWMA_LAMBDA.LLM;
    // v0.5 P1: 漂移检测 + 检查点
    this.driftAdapter = new DriftDetectorAdapter('LLM');
    this.checkpoint = new ModelCheckpoint({ persistDir: DEFAULT_PERSIST_DIR });
    this._microBatchSize = LAYER_MICRO_BATCH.LLM;
    // v0.5.1: 从磁盘 checkpoint 恢复模型状态（热重载/服务重启后）
    // 测试环境跳过：避免测试间状态污染
    // FAIL-OPEN: checkpoint 损坏/格式不兼容时降级为全新状态，不阻塞启动
    if (process.env.NODE_ENV !== 'test') {
      try {
        const latestCkpt = this.checkpoint.restore('LLM');
        if (latestCkpt) {
          this.restoreModel(latestCkpt.state as unknown as LLMModelState);
        }
      } catch (e) {
        console.error('[PromptOptimizationLoop] checkpoint restore failed, fallback to fresh state:', e);
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
  addTrainingData(data: PromptTrainingData, quality?: QualityLevel): void {
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
    const batch = entries.map(e => e.data as PromptTrainingData);
    this.trainIncremental(batch);
    this._driftFlag = (reason === 'drift');

    // 定期检查点
    if (this._step % CHECKPOINT_INTERVAL === 0 && this._step > 0) {
      this.checkpoint.checkpoint('LLM', this.getModelSnapshot());
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
   * SPEC v0.5 §3.3.5: LLM 层新增 prompt 模式 + KL 散度约束 + 权重衰减
   *
   * 增量策略:
   *   1. EWMA 衰减旧模板权重 + 上下文关键词权重
   *   2. 增量添加 prompt 模式: templateStats[key] += λ
   *   3. KL 散度约束: 新旧模板分布 KL < 阈值则接受更新
   *   4. 增量更新上下文关键词（outcome 加权）
   *   5. buffer.decayAll() — 旧数据权重衰减
   *   6. 保留模型状态，不清空
   */
  trainIncremental(batch: PromptTrainingData[]): PromptTrainingResult {
    if (batch.length === 0) {
      return this._emptyResult();
    }

    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.2 };

    // Step 1: EWMA 衰减旧权重
    for (const key of Object.keys(this._templateStats)) {
      this._templateStats[key].weight *= (1 - this._ewmaLambda);
    }
    for (const kw of Object.keys(this._contextKeywords)) {
      this._contextKeywords[kw] *= (1 - this._ewmaLambda);
    }

    // Step 2: 计算旧分布（用于 KL 散度约束）
    const oldDist = this._getTemplateDistribution();

    // Step 3: 增量添加 prompt 模式
    for (const d of batch) {
      const key = d.prompt_pattern;
      if (!this._templateStats[key]) {
        this._templateStats[key] = { template: key, count: 0, success_count: 0, weight: 0 };
      }
      this._templateStats[key].count += 1;
      const ow = outcomeWeights[d.outcome] ?? 0.5;
      this._templateStats[key].weight += this._ewmaLambda * ow;
      if (d.outcome === 'success') {
        this._templateStats[key].success_count += 1;
      }
    }

    // Step 4: KL 散度约束 — 新旧分布差异过大则回退部分更新
    const newDist = this._getTemplateDistribution();
    const kl = this._klDivergence(oldDist, newDist);
    if (kl > KL_DIVERGENCE_THRESHOLD) {
      // 回退: 对新权重做衰减（缩放 0.5）
      for (const key of Object.keys(this._templateStats)) {
        this._templateStats[key].weight *= 0.5;
      }
    }

    // Step 5: 增量更新上下文关键词
    for (const d of batch) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      for (const learned of d.learned) {
        for (const kw of tokenize(learned)) {
          this._contextKeywords[kw] = (this._contextKeywords[kw] || 0) + this._ewmaLambda * w;
        }
      }
    }

    // Step 6: buffer 衰减（不清空）
    this.buffer.decayAll();

    // Step 7: 更新步数
    this._step++;

    return {
      trained: true,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      prompt_templates: this._buildTemplates(),
      context_keywords: { ...this._contextKeywords },
      avg_token_efficiency: 0, // 增量训练不重算
      semantic_similarity: 0,
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
   * ① Prompt 模式聚类：统计频繁模板
   * ② 上下文注入优化：success 案例的 learned 关键词权重↑
   * ③ Token 效率优化：模板长度 / 最长模板长度
   */
  train(): PromptTrainingResult {
    const allEntries = this.buffer.getAll();
    const count = allEntries.length;

    if (count < this.bucketThreshold) {
      return this._emptyResult();
    }

    // 从 buffer entries 提取 data
    const allData: PromptTrainingData[] = allEntries.map(e => e.data);

    // Step 1: Prompt 模式聚类
    const templateStats: Record<string, { template: string; count: number; success_count: number; weight: number }> = {};
    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.2 };
    for (const d of allData) {
      const key = d.prompt_pattern;
      if (!templateStats[key]) {
        templateStats[key] = { template: key, count: 0, success_count: 0, weight: 0 };
      }
      templateStats[key].count += 1;
      const ow = outcomeWeights[d.outcome] ?? 0.5;
      templateStats[key].weight += ow;
      if (d.outcome === 'success') templateStats[key].success_count += 1;
    }

    const promptTemplates: PromptTemplate[] = Object.values(templateStats)
      .map((s) => ({
        template: s.template,
        count: s.count,
        success_count: s.success_count,
        success_rate: s.count > 0 ? s.success_count / s.count : 0,
      }))
      .sort((a, b) => b.success_rate * b.count - a.success_rate * a.count);

    // Step 2: 上下文注入优化
    const contextKeywords: Record<string, number> = {};
    for (const d of allData) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      for (const learned of d.learned) {
        for (const kw of tokenize(learned)) {
          contextKeywords[kw] = (contextKeywords[kw] || 0) + w;
        }
      }
    }

    // Step 3: Token 效率优化
    let maxLen = 0;
    for (const t of promptTemplates) {
      maxLen = Math.max(maxLen, t.template.length);
    }
    const avgTokenEfficiency = maxLen > 0
      ? promptTemplates.reduce((s, t) => s + (1 - t.template.length / maxLen) * (t.count / count), 0)
      : 0;

    // Step 4: 语义相似度
    const successLearnedSets = allData
      .filter((d) => d.outcome === 'success')
      .map((d) => new Set(tokenize(d.learned.join(' '))));
    let semanticSimilarity = 0;
    if (successLearnedSets.length >= 2) {
      let totalSim = 0;
      let pairCount = 0;
      for (let i = 0; i < successLearnedSets.length - 1; i++) {
        for (let j = i + 1; j < successLearnedSets.length; j++) {
          totalSim += jaccardSimilarity(successLearnedSets[i], successLearnedSets[j]);
          pairCount++;
          if (pairCount >= 100) break;
        }
        if (pairCount >= 100) break;
      }
      semanticSimilarity = pairCount > 0 ? totalSim / pairCount : 0;
    }

    // v0.5: 更新模型状态（不清空 buffer）
    this._templateStats = templateStats;
    this._contextKeywords = contextKeywords;
    this._step++;

    // v0.5: 全量训练后也做 buffer 衰减（但不清空）
    this.buffer.decayAll();

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      prompt_templates: promptTemplates,
      context_keywords: contextKeywords,
      avg_token_efficiency: Math.min(1, Math.max(0, avgTokenEfficiency)),
      semantic_similarity: Math.min(1, Math.max(0, semanticSimilarity)),
      timestamp: Date.now(),
      incrementalStep: this._step,
      bufferStats: this.buffer.getStats(),
    };
  }

  /** v0.5: 只重置模型状态，不清空 buffer */
  clear(): void {
    this._templateStats = {};
    this._contextKeywords = {};
  }

  // ============================================================
  // v0.5 P1: checkpoint / restore
  // ============================================================

  /** v0.5: 获取模型状态快照 */
  getModelSnapshot(): LLMModelState {
    return {
      templateStats: JSON.parse(JSON.stringify(this._templateStats)),
      contextKeywords: { ...this._contextKeywords },
      step: this._step,
      timestamp: Date.now(),
      version: 'v0.5-20261011',
    };
  }

  /** v0.5: 恢复模型状态 */
  restoreModel(state: LLMModelState): void {
    this._templateStats = JSON.parse(JSON.stringify(state.templateStats));
    this._contextKeywords = { ...state.contextKeywords };
    this._step = state.step;
  }

  /** v0.5: 获取 buffer 统计 */
  getBufferStats() {
    return this.buffer.getStats();
  }

  // ============================================================
  // 内部方法
  // ============================================================

  private _emptyResult(): PromptTrainingResult {
    return {
      trained: false,
      bucket_count: this.buffer.size,
      bucket_threshold: this.bucketThreshold,
      prompt_templates: [],
      context_keywords: {},
      avg_token_efficiency: 0,
      semantic_similarity: 0,
      timestamp: Date.now(),
    };
  }

  private _buildTemplates(): PromptTemplate[] {
    return Object.values(this._templateStats)
      .map((s) => ({
        template: s.template,
        count: s.count,
        success_count: s.success_count,
        success_rate: s.count > 0 ? s.success_count / s.count : 0,
      }))
      .sort((a, b) => b.success_rate * b.count - a.success_rate * a.count);
  }

  /** v0.5: 获取模板权重分布（用于 KL 散度约束） */
  private _getTemplateDistribution(): Record<string, number> {
    const totalWeight = Object.values(this._templateStats).reduce((s, v) => s + v.weight, 0);
    const dist: Record<string, number> = {};
    for (const [key, v] of Object.entries(this._templateStats)) {
      dist[key] = totalWeight > 0 ? v.weight / totalWeight : 0;
    }
    return dist;
  }

  /** v0.5: KL 散度计算（简化版，用于约束 prompt 模式分布漂移） */
  private _klDivergence(p: Record<string, number>, q: Record<string, number>): number {
    const allKeys = new Set([...Object.keys(p), ...Object.keys(q)]);
    let kl = 0;
    for (const key of allKeys) {
      const pi = p[key] || 0;
      const qi = q[key] || 0;
      if (pi > 0 && qi > 0) {
        kl += pi * Math.log2(pi / qi);
      }
    }
    return Math.abs(kl);
  }
}

// ============================================================
// 5. 单例
// ============================================================

let _instance: PromptOptimizationLoop | null = null;

export function getPromptOptimizationLoop(): PromptOptimizationLoop {
  if (!_instance) _instance = new PromptOptimizationLoop();
  return _instance;
}
