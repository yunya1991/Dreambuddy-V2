/**
 * CaseRetriever — Soft Q-Learning 案例检索器
 * ==========================================
 * SPEC-20261009 §3.3 P1-1
 *
 * 基于 Memento 架构（arXiv:2508.16153），使用 Soft Q-Learning 策略
 * 对 TDR 检索结果进行二次排序。
 *
 * Soft Q-Learning score:
 *   case_score = α * jaccard_similarity    // codebook 匹配度
 *              + β * cosine_similarity      // 语义相似度
 *              + γ * quality_weight         // 质量权重（S>A>B>C）
 *              + δ * success_rate           // 历史成功率
 *              - λ * age_penalty;            // 时间衰减
 *
 * 参数初始值：α=0.3, β=0.3, γ=0.2, δ=0.15, λ=0.05
 *
 * 检索流程：
 *   1. SolutionEncoder.encode(query) → codebook_index + embedding
 *   2. CaseBankClient.retrieve(query, topK) → 候选案例列表
 *   3. 对每个候选计算 Soft Q score
 *   4. 按分数降序排列，截断 topK
 *   5. 无候选 → retrieval_mode='fallback'
 *
 * 设计原则：
 *   - FAIL-OPEN：CaseBankClient 不可用 → fallback 空结果
 *   - 依赖注入：CaseBankClient + SolutionEncoder 可替换（测试友好）
 *   - 检索时不更新 codebook（train=false）
 *
 * 位置: 3.1-FRONTEND/src/lib/case-retriever.ts
 */

import type { CaseBankClient, CaseBankResult, SolutionCase } from './case-bank-client';
import type { SolutionEncoder, EncodeInput, EncodeResult } from './solution-encoder';
import type { DriftDetector, DriftAction } from './drift-detector';

// ============================================================
// 1. 类型定义
// ============================================================

export interface RetrievalResult {
  cases: SolutionCase[];
  scores: number[]; // Soft Q 值，与 cases 一一对应
  retrieval_mode: 'exact' | 'semantic' | 'fallback';
  drift_actions?: DriftAction[]; // SPEC §3.5: 漂移触发的增量训练动作（可选）
}

export interface SoftQParams {
  alpha: number; // jaccard weight (0.3)
  beta: number; // cosine weight (0.3)
  gamma: number; // quality weight (0.2)
  delta: number; // success_rate weight (0.15)
  lambda: number; // age_penalty weight (0.05)
}

export interface CaseRetrieverDependencies {
  caseBankClient: CaseBankClient;
  solutionEncoder: SolutionEncoder;
  driftDetector?: DriftDetector; // SPEC §3.5: 可选的分布漂移检测器
}

// ============================================================
// 2. 常量
// ============================================================

const DEFAULT_PARAMS: SoftQParams = {
  alpha: 0.3,
  beta: 0.3,
  gamma: 0.2,
  delta: 0.15,
  lambda: 0.05,
};

const QUALITY_WEIGHTS: Record<string, number> = {
  S: 1.0,
  A: 0.8,
  B: 0.5,
  C: 0.3,
};

const SUCCESS_RATES: Record<string, number> = {
  success: 1.0,
  partial: 0.5,
  failure: 0.0,
  unknown: 0.5,
};

const AGE_PENALTY_MAX_DAYS = 90; // 90天后 age_penalty 达到最大值 1.0
const JACCARD_THRESHOLD = 0.3; // SPEC §3.3: Jaccard > 0.3 才作为候选

// ============================================================
// 3. 相似度计算工具函数
// ============================================================

/**
 * Jaccard 相似度（codebook_index 数组）
 * J(A, B) = |A ∩ B| / |A ∪ B|
 */
function jaccardSimilarity(a: number[], b: number[]): number {
  if (!a || !b || a.length === 0 || b.length === 0) return 0;
  const setA = new Set(a);
  const setB = new Set(b);
  let intersection = 0;
  for (const v of setA) {
    if (setB.has(v)) intersection++;
  }
  const union = setA.size + setB.size - intersection;
  return union === 0 ? 0 : intersection / union;
}

/**
 * 余弦相似度（embedding 向量）
 * cos(A, B) = (A·B) / (|A| * |B|)
 */
function cosineSimilarity(a: number[], b: number[]): number {
  if (!a || !b || a.length === 0 || b.length === 0) return 0;
  const len = Math.min(a.length, b.length);
  let dot = 0;
  let normA = 0;
  let normB = 0;
  for (let i = 0; i < len; i++) {
    dot += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  const denom = Math.sqrt(normA) * Math.sqrt(normB);
  return denom === 0 ? 0 : dot / denom;
}

/**
 * 时间衰减惩罚
 * age_days / 90 线性增长，上限 1.0
 */
function agePenalty(createdAt: number): number {
  if (!createdAt) return 0;
  const ageDays = (Date.now() - createdAt) / (1000 * 60 * 60 * 24);
  return Math.min(1.0, Math.max(0, ageDays / AGE_PENALTY_MAX_DAYS));
}

// ============================================================
// 4. CaseRetriever 主类
// ============================================================

export class CaseRetriever {
  readonly params: SoftQParams;
  private deps: CaseRetrieverDependencies;
  private driftDetector?: DriftDetector;

  constructor(deps: CaseRetrieverDependencies, params?: Partial<SoftQParams>) {
    this.deps = deps;
    this.params = { ...DEFAULT_PARAMS, ...params };
    this.driftDetector = deps.driftDetector;
  }

  /**
   * 获取漂移检测器（如果已配置）
   */
  getDriftDetector(): DriftDetector | undefined {
    return this.driftDetector;
  }

  /**
   * 检索相似案例
   * @param query 查询文本（意图）
   * @param topK 返回 top-K 案例数（默认 5）
   * @returns RetrievalResult { cases, scores, retrieval_mode }
   */
  async retrieve(query: string, topK: number = 5): Promise<RetrievalResult> {
    // Step 1: 编码 query
    const encodeInput: EncodeInput = {
      intent: query,
      actions: [],
      outcome_text: '',
      learned: [],
    };
    const encodeResult = await this.deps.solutionEncoder.encode(encodeInput, false);

    // Step 2: 从 TDR 检索候选
    const bankResult = await this.deps.caseBankClient.retrieve(query, topK);

    // FAIL-OPEN: degraded 或无数据 → fallback
    if (!bankResult.ok || !bankResult.data || !bankResult.data.cases || bankResult.data.cases.length === 0) {
      return { cases: [], scores: [], retrieval_mode: 'fallback' };
    }

    // Step 3: 对每个候选计算 Soft Q score
    const candidates = bankResult.data.cases;
    const scored = candidates.map((c) => ({
      case: c,
      score: this.computeScore(encodeResult, c),
    }));

    // Step 4: 按 score 降序排列
    scored.sort((a, b) => b.score - a.score);

    // Step 5: 截断 topK
    const top = scored.slice(0, topK);

    // Step 6: 判定 retrieval_mode
    // exact: top-1 的 jaccard=1.0（codebook 完全匹配）
    // semantic: 有候选但不完全匹配
    const topJaccard = jaccardSimilarity(encodeResult.codebook_index, top[0].case.codebook_index);
    const retrievalMode: 'exact' | 'semantic' = topJaccard === 1.0 ? 'exact' : 'semantic';

    // Step 7: SPEC §3.5 漂移检测 — 收集 codebook 索引并检测分布漂移
    let driftActions: DriftAction[] | undefined;
    if (this.driftDetector) {
      this.driftDetector.addSample(encodeResult.codebook_index);
      driftActions = this.driftDetector.getDriftActions();
    }

    return {
      cases: top.map((s) => s.case),
      scores: top.map((s) => s.score),
      retrieval_mode: retrievalMode,
      drift_actions: driftActions,
    };
  }

  /**
   * 计算 Soft Q-Learning score
   * case_score = α * jaccard + β * cosine + γ * quality + δ * success_rate - λ * age_penalty
   *
   * @param queryEncoding query 的 VQ-VAE 编码结果
   * @param candidate TDR 中的候选案例
   * @returns Soft Q score（0~1 范围，可能因 age_penalty 略低）
   */
  computeScore(queryEncoding: EncodeResult, candidate: SolutionCase): number {
    const jac = jaccardSimilarity(queryEncoding.codebook_index, candidate.codebook_index);
    const cos = cosineSimilarity(queryEncoding.embedding, candidate.embedding);
    const qw = QUALITY_WEIGHTS[candidate.quality] ?? 0.3;
    const sr = SUCCESS_RATES[candidate.outcome] ?? 0.5;
    const ap = agePenalty(candidate.created_at);

    return (
      this.params.alpha * jac +
      this.params.beta * cos +
      this.params.gamma * qw +
      this.params.delta * sr -
      this.params.lambda * ap
    );
  }
}

// ============================================================
// 5. 单例（延迟初始化，依赖注入时用构造函数）
// ============================================================

let _instance: CaseRetriever | null = null;

export function getCaseRetriever(deps?: CaseRetrieverDependencies): CaseRetriever {
  if (!_instance) {
    if (!deps) {
      throw new Error('CaseRetriever 首次初始化需要提供 dependencies');
    }
    _instance = new CaseRetriever(deps);
  }
  return _instance;
}
