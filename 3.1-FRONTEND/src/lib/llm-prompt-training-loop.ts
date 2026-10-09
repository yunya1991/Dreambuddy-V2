/**
 * PromptOptimizationLoop — LLM Prompt 优化训练循环
 * ==========================================
 * SPEC-20261009 §4.2.5 P2-3
 *
 * 训练数据：session_memory 中 learned (经验数组) + outcome
 * 训练方法：① Prompt 模式聚类（频繁模板→最优模板）② 上下文注入优化（哪些信息最有效）③ Token 效率优化
 * 触发节奏：桶满 30 条触发
 * 复现目标：输出与 trae_learned 语义相似度 ≥ 0.7
 * 依赖：C层先训
 *
 * 位置: 3.1-FRONTEND/src/lib/llm-prompt-training-loop.ts
 */

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
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_BUCKET_THRESHOLD = 30; // SPEC v0.3 LLM

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
  private bucket: PromptTrainingData[] = [];

  constructor(opts?: { bucketThreshold?: number }) {
    this.bucketThreshold = opts?.bucketThreshold ?? DEFAULT_BUCKET_THRESHOLD;
  }

  get bucketCount(): number {
    return this.bucket.length;
  }

  addTrainingData(data: PromptTrainingData): void {
    this.bucket.push(data);
  }

  shouldTrain(): boolean {
    return this.bucket.length >= this.bucketThreshold;
  }

  /**
   * 执行训练
   * ① Prompt 模式聚类：统计频繁模板
   * ② 上下文注入优化：success 案例的 learned 关键词权重↑
   * ③ Token 效率优化：模板长度 / 最长模板长度
   */
  train(): PromptTrainingResult {
    const count = this.bucket.length;

    if (count < this.bucketThreshold) {
      return {
        trained: false,
        bucket_count: count,
        bucket_threshold: this.bucketThreshold,
        prompt_templates: [],
        context_keywords: {},
        avg_token_efficiency: 0,
        semantic_similarity: 0,
        timestamp: Date.now(),
      };
    }

    // Step 1: Prompt 模式聚类
    const templateStats: Record<string, { template: string; count: number; success_count: number }> = {};
    for (const d of this.bucket) {
      const key = d.prompt_pattern;
      if (!templateStats[key]) {
        templateStats[key] = { template: key, count: 0, success_count: 0 };
      }
      templateStats[key].count += 1;
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

    // Step 2: 上下文注入优化 — 统计 learned 关键词（outcome 加权）
    const contextKeywords: Record<string, number> = {};
    const outcomeWeights: Record<string, number> = { success: 1.0, partial: 0.5, failure: 0.2 };
    for (const d of this.bucket) {
      const w = outcomeWeights[d.outcome] ?? 0.5;
      for (const learned of d.learned) {
        for (const kw of tokenize(learned)) {
          contextKeywords[kw] = (contextKeywords[kw] || 0) + w;
        }
      }
    }

    // Step 3: Token 效率优化
    // 效率 = 1 - (当前模板长度 / 最长模板长度)，范围 [0, 1]
    let maxLen = 0;
    for (const t of promptTemplates) {
      maxLen = Math.max(maxLen, t.template.length);
    }
    const avgTokenEfficiency = maxLen > 0
      ? promptTemplates.reduce((s, t) => s + (1 - t.template.length / maxLen) * (t.count / count), 0)
      : 0;

    // Step 4: 语义相似度（近似：success 案例 learned 间的 Jaccard 平均）
    const successLearnedSets = this.bucket
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
          if (pairCount >= 100) break; // 限制计算量
        }
        if (pairCount >= 100) break;
      }
      semanticSimilarity = pairCount > 0 ? totalSim / pairCount : 0;
    }

    // 清空桶
    this.bucket = [];

    return {
      trained: true,
      bucket_count: count,
      bucket_threshold: this.bucketThreshold,
      prompt_templates: promptTemplates,
      context_keywords: contextKeywords,
      avg_token_efficiency: Math.min(1, Math.max(0, avgTokenEfficiency)),
      semantic_similarity: Math.min(1, Math.max(0, semanticSimilarity)),
      timestamp: Date.now(),
    };
  }

  clear(): void {
    this.bucket = [];
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
