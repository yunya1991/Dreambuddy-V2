/**
 * SPEC-20261009 §3.3 P1-1: Case Retriever (Soft Q-Learning 检索) 测试
 *
 * TDD RED→GREEN→REFACTOR
 *
 * 覆盖：
 *   - CaseRetriever 类存在性 + 可实例化
 *   - Soft Q-Learning score 计算（jaccard/cosine/quality/success_rate/age_penalty）
 *   - retrieval_mode 三种模式（exact/semantic/fallback）
 *   - FAIL-OPEN：CaseBankClient 不可用时返回 fallback 空结果
 *   - 参数默认值（α=0.3, β=0.3, γ=0.2, δ=0.15, λ=0.05）
 *   - top-K 截断
 */

import { CaseRetriever, type RetrievalResult } from '../case-retriever';
import type { CaseBankClient, CaseBankResult, SolutionCase, RetrieveResult as CBRetrieveResult } from '../case-bank-client';
import type { SolutionEncoder, EncodeResult } from '../solution-encoder';

// ============================================================
// Mock 工厂
// ============================================================

function makeMockCase(overrides: Partial<SolutionCase> = {}): SolutionCase {
  return {
    id: 'case-test-1',
    intent: '检查架构',
    actions: ['检查', '分析'],
    outcome_text: '完成',
    learned: ['架构自洽'],
    message_id: 'msg-1',
    message_summary_time: '2026-10-09 10:00:00',
    outcome: 'success',
    codebook_index: [0, 1, 2, 3],
    embedding: [0.5, 0.5, 0.5, 0.5],
    layer_tags: [],
    baseline_output: {
      trae_intent: '检查架构',
      trae_actions: ['检查'],
      trae_outcome: '完成',
      trae_learned: ['架构自洽'],
    },
    quality: 'B',
    confidence: 0.5,
    tags: ['架构'],
    source: 'test',
    created_at: Date.now(),
    last_retrieved_at: 0,
    replay_count: 0,
    verify_count: 0,
    ...overrides,
  };
}

function makeMockEncoder(encodeResult?: Partial<EncodeResult>): SolutionEncoder {
  return {
    encode: jest.fn().mockResolvedValue({
      codebook_index: [0, 1, 2, 3],
      embedding: [0.5, 0.5, 0.5, 0.5],
      retrieval_mode: 'vq-vae',
      ...encodeResult,
    }),
  } as unknown as SolutionEncoder;
}

function makeMockClient(retrieveData?: Partial<CBRetrieveResult>): CaseBankClient {
  return {
    retrieve: jest.fn().mockResolvedValue({
      ok: true,
      data: {
        cases: [makeMockCase()],
        scores: [0.8],
        retrieval_mode: 'semantic',
        ...retrieveData,
      },
    } as CaseBankResult<CBRetrieveResult>),
  } as unknown as CaseBankClient;
}

function makeMockClientDegraded(): CaseBankClient {
  return {
    retrieve: jest.fn().mockResolvedValue({
      ok: false,
      degraded: true,
      error: 'timeout',
    } as CaseBankResult<CBRetrieveResult>),
  } as unknown as CaseBankClient;
}

// ============================================================
// 测试
// ============================================================

describe('SPEC §3.3 P1-1: CaseRetriever (Soft Q-Learning 检索)', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('CaseRetriever 类应可导入且可实例化', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      expect(retriever).toBeInstanceOf(CaseRetriever);
    });

    it('retrieve 方法应存在', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      expect(typeof retriever.retrieve).toBe('function');
    });

    it('computeScore 方法应存在（用于单元测试 score 计算）', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      expect(typeof retriever.computeScore).toBe('function');
    });
  });

  // ----------------------------------------------------------
  // 2. Soft Q-Learning 参数默认值
  // ----------------------------------------------------------
  describe('Soft Q-Learning 参数默认值', () => {
    it('默认参数应为 α=0.3, β=0.3, γ=0.2, δ=0.15, λ=0.05', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      expect(retriever.params.alpha).toBe(0.3);
      expect(retriever.params.beta).toBe(0.3);
      expect(retriever.params.gamma).toBe(0.2);
      expect(retriever.params.delta).toBe(0.15);
      expect(retriever.params.lambda).toBe(0.05);
    });

    it('应支持自定义参数覆盖', () => {
      const retriever = new CaseRetriever(
        { caseBankClient: makeMockClient(), solutionEncoder: makeMockEncoder() },
        { alpha: 0.4, beta: 0.2 },
      );
      expect(retriever.params.alpha).toBe(0.4);
      expect(retriever.params.beta).toBe(0.2);
      expect(retriever.params.gamma).toBe(0.2); // 未覆盖保持默认
    });
  });

  // ----------------------------------------------------------
  // 3. Soft Q-Learning score 计算
  // ----------------------------------------------------------
  describe('Soft Q-Learning score 计算', () => {
    it('jaccard_similarity: codebook 完全一致应返回 1.0', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const score = retriever.computeScore(
        { codebook_index: [0, 1, 2, 3], embedding: [0.5, 0.5, 0.5, 0.5], retrieval_mode: 'vq-vae' },
        makeMockCase({ codebook_index: [0, 1, 2, 3] }),
      );
      // 完全匹配时 jaccard=1.0 → α*1.0=0.3 贡献
      expect(score).toBeGreaterThan(0);
    });

    it('jaccard_similarity: codebook 无交集应返回 0', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      // 完全不同的 codebook + 完全不同的 embedding → score 应很低
      const score = retriever.computeScore(
        { codebook_index: [10, 11, 12, 13], embedding: [1, 0, 0, 0], retrieval_mode: 'vq-vae' },
        makeMockCase({ codebook_index: [0, 1, 2, 3], embedding: [0, 1, 0, 0] }),
      );
      // jaccard=0, cosine=0 → score 仅靠 quality+success_rate-age_penalty
      expect(score).toBeLessThan(0.5);
    });

    it('cosine_similarity: 相同方向 embedding 应有高贡献', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const scoreSame = retriever.computeScore(
        { codebook_index: [99, 99, 99, 99], embedding: [1, 1, 1, 1], retrieval_mode: 'vq-vae' },
        makeMockCase({ codebook_index: [0, 1, 2, 3], embedding: [1, 1, 1, 1] }),
      );
      const scoreDiff = retriever.computeScore(
        { codebook_index: [99, 99, 99, 99], embedding: [1, 0, 0, 0], retrieval_mode: 'vq-vae' },
        makeMockCase({ codebook_index: [0, 1, 2, 3], embedding: [0, 1, 0, 0] }),
      );
      expect(scoreSame).toBeGreaterThan(scoreDiff);
    });

    it('quality_weight: S>A>B>C 质量权重应递减', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const enc = { codebook_index: [0, 1, 2, 3], embedding: [0.5, 0.5, 0.5, 0.5], retrieval_mode: 'vq-vae' as const };
      const scoreS = retriever.computeScore(enc, makeMockCase({ quality: 'S' as any }));
      const scoreA = retriever.computeScore(enc, makeMockCase({ quality: 'A' as any }));
      const scoreB = retriever.computeScore(enc, makeMockCase({ quality: 'B' as any }));
      const scoreC = retriever.computeScore(enc, makeMockCase({ quality: 'C' as any }));
      expect(scoreS).toBeGreaterThan(scoreA);
      expect(scoreA).toBeGreaterThan(scoreB);
      expect(scoreB).toBeGreaterThan(scoreC);
    });

    it('success_rate: success=1.0, partial=0.5, failure=0.0', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const enc = { codebook_index: [0, 1, 2, 3], embedding: [0.5, 0.5, 0.5, 0.5], retrieval_mode: 'vq-vae' as const };
      const scoreSuccess = retriever.computeScore(enc, makeMockCase({ outcome: 'success' }));
      const scorePartial = retriever.computeScore(enc, makeMockCase({ outcome: 'partial' }));
      const scoreFailure = retriever.computeScore(enc, makeMockCase({ outcome: 'failure' }));
      expect(scoreSuccess).toBeGreaterThan(scorePartial);
      expect(scorePartial).toBeGreaterThan(scoreFailure);
    });

    it('age_penalty: 越老的案例 score 越低', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const enc = { codebook_index: [0, 1, 2, 3], embedding: [0.5, 0.5, 0.5, 0.5], retrieval_mode: 'vq-vae' as const };
      const recentCase = makeMockCase({ created_at: Date.now() });
      const oldCase = makeMockCase({ created_at: Date.now() - 90 * 24 * 60 * 60 * 1000 }); // 90天前
      const scoreRecent = retriever.computeScore(enc, recentCase);
      const scoreOld = retriever.computeScore(enc, oldCase);
      expect(scoreRecent).toBeGreaterThan(scoreOld);
    });

    it('综合 score 公式: α*jaccard + β*cosine + γ*quality + δ*success - λ*age', () => {
      const retriever = new CaseRetriever({
        caseBankClient: makeMockClient(),
        solutionEncoder: makeMockEncoder(),
      });
      const enc = { codebook_index: [0, 1, 2, 3], embedding: [0.5, 0.5, 0.5, 0.5], retrieval_mode: 'vq-vae' as const };
      const candidate = makeMockCase({
        codebook_index: [0, 1, 2, 3], // jaccard=1.0
        embedding: [0.5, 0.5, 0.5, 0.5], // cosine=1.0
        quality: 'B' as any, // quality_weight=0.5
        outcome: 'success', // success_rate=1.0
        created_at: Date.now(), // age_penalty≈0
      });
      const score = retriever.computeScore(enc, candidate);
      // 期望: 0.3*1.0 + 0.3*1.0 + 0.2*0.5 + 0.15*1.0 - 0.05*0 = 0.85
      expect(score).toBeCloseTo(0.85, 1);
    });
  });

  // ----------------------------------------------------------
  // 4. retrieval_mode 三种模式
  // ----------------------------------------------------------
  describe('retrieval_mode 模式', () => {
    it('有候选且 codebook 完全匹配 → exact 模式', async () => {
      const encoder = makeMockEncoder({ codebook_index: [0, 1, 2, 3] });
      const client = makeMockClient({
        cases: [makeMockCase({ codebook_index: [0, 1, 2, 3] })],
        scores: [0.9],
        retrieval_mode: 'exact',
      });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('检查架构');
      expect(result.retrieval_mode).toBe('exact');
      expect(result.cases).toHaveLength(1);
    });

    it('有候选但 codebook 不完全匹配 → semantic 模式', async () => {
      const encoder = makeMockEncoder({ codebook_index: [0, 1, 2, 3] });
      const client = makeMockClient({
        cases: [makeMockCase({ codebook_index: [5, 6, 7, 8] })],
        scores: [0.6],
        retrieval_mode: 'semantic',
      });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('检查架构');
      expect(result.retrieval_mode).toBe('semantic');
      expect(result.cases).toHaveLength(1);
    });

    it('无候选案例 → fallback 模式', async () => {
      const encoder = makeMockEncoder();
      const client = makeMockClient({ cases: [], scores: [], retrieval_mode: 'fallback' });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('随机查询');
      expect(result.retrieval_mode).toBe('fallback');
      expect(result.cases).toHaveLength(0);
    });

    it('CaseBankClient degraded → fallback 模式（FAIL-OPEN）', async () => {
      const encoder = makeMockEncoder();
      const client = makeMockClientDegraded();
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('检查架构');
      expect(result.retrieval_mode).toBe('fallback');
      expect(result.cases).toHaveLength(0);
      expect(result.scores).toHaveLength(0);
    });
  });

  // ----------------------------------------------------------
  // 5. top-K 截断
  // ----------------------------------------------------------
  describe('top-K 截断', () => {
    it('应返回最多 topK 条案例', async () => {
      const encoder = makeMockEncoder();
      const cases = Array.from({ length: 10 }, (_, i) =>
        makeMockCase({ id: `case-${i}`, codebook_index: [i % 4, (i + 1) % 4, (i + 2) % 4, (i + 3) % 4] }),
      );
      const client = makeMockClient({ cases, scores: cases.map(() => 0.5), retrieval_mode: 'semantic' });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('test', 3);
      expect(result.cases).toHaveLength(3);
      expect(result.scores).toHaveLength(3);
    });

    it('默认 topK=5', async () => {
      const encoder = makeMockEncoder();
      const cases = Array.from({ length: 10 }, (_, i) => makeMockCase({ id: `case-${i}` }));
      const client = makeMockClient({ cases, scores: cases.map(() => 0.5), retrieval_mode: 'semantic' });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('test');
      expect(result.cases).toHaveLength(5);
    });

    it('结果按 score 降序排列', async () => {
      const encoder = makeMockEncoder();
      const cases = [
        makeMockCase({ id: 'low', quality: 'C' as any, codebook_index: [99, 99, 99, 99] }),
        makeMockCase({ id: 'high', quality: 'S' as any, codebook_index: [0, 1, 2, 3] }),
        makeMockCase({ id: 'mid', quality: 'B' as any, codebook_index: [0, 1, 99, 99] }),
      ];
      const client = makeMockClient({ cases, scores: [0.3, 0.9, 0.6], retrieval_mode: 'semantic' });
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('test', 3);
      expect(result.cases[0].id).toBe('high');
      expect(result.cases[1].id).toBe('mid');
      expect(result.cases[2].id).toBe('low');
      // scores 也应降序
      expect(result.scores[0]).toBeGreaterThanOrEqual(result.scores[1]);
      expect(result.scores[1]).toBeGreaterThanOrEqual(result.scores[2]);
    });
  });

  // ----------------------------------------------------------
  // 6. retrieve 完整流程
  // ----------------------------------------------------------
  describe('retrieve 完整流程', () => {
    it('应调用 encoder.encode 编码 query', async () => {
      const encoder = makeMockEncoder();
      const client = makeMockClient();
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      await retriever.retrieve('检查架构');
      expect(encoder.encode).toHaveBeenCalledWith(
        expect.objectContaining({ intent: '检查架构' }),
        false, // train=false（检索时不更新 codebook）
      );
    });

    it('应调用 caseBankClient.retrieve 获取候选', async () => {
      const encoder = makeMockEncoder();
      const client = makeMockClient();
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      await retriever.retrieve('检查架构', 5);
      expect(client.retrieve).toHaveBeenCalledWith('检查架构', 5);
    });

    it('RetrievalResult 应包含 cases + scores + retrieval_mode', async () => {
      const encoder = makeMockEncoder();
      const client = makeMockClient();
      const retriever = new CaseRetriever({ caseBankClient: client, solutionEncoder: encoder });
      const result = await retriever.retrieve('检查架构');
      expect(result).toHaveProperty('cases');
      expect(result).toHaveProperty('scores');
      expect(result).toHaveProperty('retrieval_mode');
    });
  });
});
