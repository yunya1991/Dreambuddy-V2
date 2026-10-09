/**
 * IntentTrainingLoop — S层意图训练循环
 * ==========================================
 * SPEC-20261009 §4.2.1 P1-5
 *
 * 训练数据：session_memory 中 (message, intent) pairs
 * 训练方法：① 规则权重增量（TF-IDF + 频率统计）② DynamicRecognizer 权重更新
 * 触发节奏：桶满 50 条触发（v0.3 S层差异化）
 * 复现目标：intent 一致率 ≥ 80%
 * 依赖：独立可训练（与 G层并行）
 *
 * 位置: 3.1-FRONTEND/src/lib/s-intent-training-loop.ts
 */

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
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 50; // SPEC v0.3: S层需覆盖35型，30条不足

// ============================================================
// 3. IntentTrainingLoop 主类
// ============================================================

export class IntentTrainingLoop {
  readonly bucketThreshold: number;
  private bucket: TrainingData[] = [];

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
  }

  /** 获取当前桶中数据量 */
  get bucketCount(): number {
    return this.bucket.length;
  }

  /** 添加训练数据到桶 */
  addTrainingData(data: TrainingData): void {
    this.bucket.push(data);
  }

  /** 检查桶是否满，是否应该训练 */
  shouldTrain(): boolean {
    return this.bucket.length >= this.bucketThreshold;
  }

  /**
   * 执行训练
   * ① 统计 intent_type 频率 → 规则权重
   * ② TF-IDF 关键词提取 → 规则增量
   * ③ 计算一致率（训练数据自预测准确率）
   */
  train(): TrainingResult {
    const count = this.bucket.length;

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

    // Step 1: 统计 intent_type 频率
    const typeCounts: Record<string, number> = {};
    const typeMessages: Record<string, string[]> = {};
    for (const d of this.bucket) {
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
    // 为每个 intent_type 提取 top 关键词
    const typeKeywords: Record<string, Record<string, number>> = {};
    for (const [type, msgs] of Object.entries(typeMessages)) {
      const kw: Record<string, number> = {};
      for (const msg of msgs) {
        // 简化分词：按字符 2-gram
        for (let i = 0; i < msg.length - 1; i++) {
          const gram = msg.slice(i, i + 2);
          kw[gram] = (kw[gram] || 0) + 1;
        }
      }
      typeKeywords[type] = kw;
    }

    // Step 4: 计算一致率（用关键词频率预测 intent_type）
    let correct = 0;
    for (const d of this.bucket) {
      const predicted = this._predictIntent(d.message, typeKeywords);
      if (predicted === d.intent_type) correct++;
    }
    const accuracy = correct / count;

    // 清空桶
    this.bucket = [];

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      accuracy,
      weights,
      timestamp: Date.now(),
    };
  }

  /** 清空桶 */
  clear(): void {
    this.bucket = [];
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
