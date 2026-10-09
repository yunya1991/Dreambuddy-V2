/**
 * SPEC-20261009 §3.1 + §10 P0-1: TDR (Training Data Repository) 客户端测试
 *
 * TDD RED 阶段 — 验证 CaseBankClient 接口存在性 + FAIL-OPEN 行为
 *
 * 覆盖：
 *   - SolutionCase 数据结构（四元组 + layer_tags + baseline + 元数据）
 *   - CaseBankClient 类方法（store/retrieve/stats）
 *   - FAIL-OPEN：Python 不可用时返回 degraded 结果
 *   - 物理隔离：独立 DB solution_case_bank.db
 */

import { CaseBankClient, type SolutionCase, type CaseBankResult } from '../case-bank-client';

describe('SPEC §3.1 P0-1: TDR CaseBankClient', () => {
  // ============================================================
  // §3.1: SolutionCase 数据结构
  // ============================================================
  describe('SolutionCase 数据结构', () => {
    it('应包含四元组字段 (intent/actions/outcome_text/learned)', () => {
      const c: SolutionCase = {
        id: 'case-123',
        intent: '检查项目架构',
        actions: ['检查架构', '修复问题'],
        outcome_text: '架构检查完成',
        learned: ['架构自洽'],
        message_id: 'msg-1',
        message_summary_time: '2026-10-09 10:00:00',
        outcome: 'success',
        codebook_index: [0, 1, 2, 3],
        embedding: [0.1, 0.2],
        layer_tags: [],
        baseline_output: {
          trae_intent: '检查项目架构',
          trae_actions: ['检查架构'],
          trae_outcome: '完成',
          trae_learned: ['架构自洽'],
        },
        quality: 'B',
        confidence: 0.5,
        tags: ['架构'],
        source: 'session-1',
        created_at: Date.now(),
        last_retrieved_at: 0,
        replay_count: 0,
        verify_count: 0,
      };
      expect(c.intent).toBe('检查项目架构');
      expect(c.actions).toHaveLength(2);
      expect(c.learned).toHaveLength(1);
      expect(c.outcome).toBe('success');
    });

    it('应支持 LayerTag 分层标注', () => {
      const c: SolutionCase = {
        id: 'case-456',
        intent: 'test',
        actions: [],
        outcome_text: '',
        learned: [],
        message_id: '',
        message_summary_time: '',
        outcome: 'unknown',
        codebook_index: [],
        embedding: [],
        layer_tags: [
          { layer: 'S', training_data: null, bucket_count: 1, bucket_threshold: 50 },
          { layer: 'DSH', training_data: null, bucket_count: 1, bucket_threshold: 100 },
        ],
        baseline_output: {
          trae_intent: '', trae_actions: [], trae_outcome: '', trae_learned: [],
        },
        quality: 'C',
        confidence: 0.3,
        tags: [],
        source: 'test',
        created_at: 0,
        last_retrieved_at: 0,
        replay_count: 0,
        verify_count: 0,
      };
      expect(c.layer_tags).toHaveLength(2);
      expect(c.layer_tags[0].layer).toBe('S');
      expect(c.layer_tags[1].bucket_threshold).toBe(100);
    });
  });

  // ============================================================
  // §10 P0-1: CaseBankClient 类存在性
  // ============================================================
  describe('CaseBankClient 类', () => {
    it('应导出 CaseBankClient 类', () => {
      expect(CaseBankClient).toBeDefined();
      expect(typeof CaseBankClient).toBe('function');
    });

    it('应提供 getCaseBankClient 单例获取方法', () => {
      const { getCaseBankClient } = require('../case-bank-client');
      expect(typeof getCaseBankClient).toBe('function');
      const client = getCaseBankClient();
      expect(client).toBeInstanceOf(CaseBankClient);
    });

    it('CaseBankClient 应有 store 方法', () => {
      const client = new CaseBankClient();
      expect(typeof client.store).toBe('function');
    });

    it('CaseBankClient 应有 retrieve 方法', () => {
      const client = new CaseBankClient();
      expect(typeof client.retrieve).toBe('function');
    });

    it('CaseBankClient 应有 stats 方法', () => {
      const client = new CaseBankClient();
      expect(typeof client.stats).toBe('function');
    });
  });

  // ============================================================
  // §11.7: FAIL-OPEN — Python 不可用时降级
  // ============================================================
  describe('FAIL-OPEN 行为', () => {
    it('store 在 Python 不可用时应返回 degraded 结果', async () => {
      const client = new CaseBankClient({ pythonBin: '/nonexistent/python3' });
      const result = await client.store({
        intent: 'test',
        actions: ['a'],
        outcome_text: 'ok',
        learned: ['l'],
        message_id: 'm1',
        message_summary_time: '2026-01-01 00:00:00',
      });
      expect(result.ok).toBe(false);
      expect(result.degraded).toBe(true);
    });

    it('retrieve 在 Python 不可用时应返回空数组 + degraded', async () => {
      const client = new CaseBankClient({ pythonBin: '/nonexistent/python3' });
      const result = await client.retrieve('test query', 5);
      expect(result.ok).toBe(false);
      expect(result.degraded).toBe(true);
      if (!result.data) {
        // degraded 情况 data 可能为空
        return;
      }
      expect(result.data.cases).toEqual([]);
    });

    it('stats 在 Python 不可用时应返回 degraded', async () => {
      const client = new CaseBankClient({ pythonBin: '/nonexistent/python3' });
      const result = await client.stats();
      expect(result.ok).toBe(false);
      expect(result.degraded).toBe(true);
    });
  });

  // ============================================================
  // §3.1: 质量闸门 — 有 learned 即入库
  // ============================================================
  describe('质量闸门', () => {
    it('store 应拒绝 learned 为空的四元组（质量闸门：有 learned 才入库）', async () => {
      const client = new CaseBankClient();
      const result = await client.store({
        intent: 'test',
        actions: ['a'],
        outcome_text: 'ok',
        learned: [],  // 空 learned → 应被质量闸门拒绝
        message_id: 'm1',
        message_summary_time: '2026-01-01 00:00:00',
      });
      // 质量闸门在 TS 层拦截，不调 Python
      expect(result.ok).toBe(false);
      expect(result.error).toContain('learned');
    });
  });

  // ============================================================
  // §3.1: outcome 分类推断
  // ============================================================
  describe('outcome 分类推断', () => {
    it('outcome 包含"完成/成功" → success', () => {
      const client = new CaseBankClient();
      const outcome = client.inferOutcome('架构检查完成，核心架构已修复');
      expect(outcome).toBe('success');
    });

    it('outcome 包含"失败/错误" → failure', () => {
      const client = new CaseBankClient();
      const outcome = client.inferOutcome('执行失败，报错 TypeError');
      expect(outcome).toBe('failure');
    });

    it('outcome 包含"部分/修改" → partial', () => {
      const client = new CaseBankClient();
      const outcome = client.inferOutcome('部分修改，还有遗留问题');
      expect(outcome).toBe('partial');
    });

    it('outcome 无法判断 → unknown', () => {
      const client = new CaseBankClient();
      const outcome = client.inferOutcome('一些无关文本');
      expect(outcome).toBe('unknown');
    });
  });
});
