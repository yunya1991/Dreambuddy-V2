/**
 * SPEC-20261009 §3.2 P0-2: VQ-VAE 编码器 (SolutionEncoder) 测试
 *
 * TDD RED 阶段 — 验证 SolutionEncoder 接口 + codebook 逻辑
 *
 * 覆盖：
 *   - SolutionEncoder 类存在性 + encode 方法
 *   - codebook 初始化（k-means++ 首批数据）
 *   - EMA 更新（α=0.99）
 *   - codebook 塌缩防护（使用率 < 1/256 → 重置）
 *   - 降级模式（hit rate < 30% → bge+LSH）
 *   - 相似输入产生相似 codebook 索引
 */

import { SolutionEncoder, type EncodeResult } from '../solution-encoder';

describe('SPEC §3.2 P0-2: VQ-VAE SolutionEncoder', () => {
  // ============================================================
  // §3.2: 类存在性
  // ============================================================
  describe('SolutionEncoder 类', () => {
    it('应导出 SolutionEncoder 类', () => {
      expect(SolutionEncoder).toBeDefined();
      expect(typeof SolutionEncoder).toBe('function');
    });

    it('应提供 getSolutionEncoder 单例', () => {
      const { getSolutionEncoder } = require('../solution-encoder');
      expect(typeof getSolutionEncoder).toBe('function');
      const enc = getSolutionEncoder();
      expect(enc).toBeInstanceOf(SolutionEncoder);
    });

    it('encode 方法存在', () => {
      const enc = new SolutionEncoder();
      expect(typeof enc.encode).toBe('function');
    });
  });

  // ============================================================
  // §3.2: encode — 四元组 → codebook 索引
  // ============================================================
  describe('encode 方法', () => {
    it('应返回 4 个 codebook 索引（intent/actions/outcome/learned）', () => {
      const enc = new SolutionEncoder();
      const result = enc.encode({
        intent: '检查架构',
        actions: ['检查', '修复'],
        outcome_text: '完成',
        learned: ['架构自洽'],
      });
      expect(result.codebook_index).toHaveLength(4);
      expect(result.codebook_index.every((i) => i >= 0 && i < 256)).toBe(true);
    });

    it('应返回 embedding 向量', () => {
      const enc = new SolutionEncoder();
      const result = enc.encode({
        intent: 'test',
        actions: ['a'],
        outcome_text: 'ok',
        learned: ['l'],
      });
      expect(result.embedding).toBeDefined();
      expect(result.embedding.length).toBeGreaterThan(0);
    });

    it('应返回 retrieval_mode 标记', () => {
      const enc = new SolutionEncoder();
      const result = enc.encode({
        intent: 'test',
        actions: ['a'],
        outcome_text: 'ok',
        learned: ['l'],
      });
      expect(result.retrieval_mode).toBeDefined();
      expect(['vq-vae', 'lsh', 'fallback']).toContain(result.retrieval_mode);
    });
  });

  // ============================================================
  // §3.2: codebook 初始化（k-means++ 首批数据）
  // ============================================================
  describe('codebook 初始化', () => {
    it('冷启动期（< 100 条数据）应返回 fallback 模式', () => {
      const enc = new SolutionEncoder();
      const result = enc.encode({
        intent: 'cold-start',
        actions: ['init'],
        outcome_text: 'starting',
        learned: ['init'],
      });
      // 冷启动期 codebook 未初始化，应降级
      expect(result.retrieval_mode).toBe('fallback');
    });

    it('积累 100 条数据后应触发 k-means++ 初始化', () => {
      const enc = new SolutionEncoder();
      // 灌入 100 条数据
      for (let i = 0; i < 100; i++) {
        enc.encode({
          intent: `intent-${i}`,
          actions: [`action-${i}`],
          outcome_text: `outcome-${i}`,
          learned: [`learned-${i}`],
        });
      }
      // 第 101 条应该使用初始化后的 codebook
      const result = enc.encode({
        intent: 'post-init',
        actions: ['action'],
        outcome_text: 'done',
        learned: ['something'],
      });
      expect(result.retrieval_mode).not.toBe('fallback');
    });
  });

  // ============================================================
  // §3.2: EMA 更新（α=0.99）
  // ============================================================
  describe('EMA 更新', () => {
    it('应暴露 getDecayRate 方法返回 α=0.99', () => {
      const enc = new SolutionEncoder();
      expect(enc.getDecayRate()).toBeCloseTo(0.99, 2);
    });

    it('应暴露 getStats 方法返回 codebook 状态', () => {
      const enc = new SolutionEncoder();
      const stats = enc.getStats();
      expect(stats).toHaveProperty('codebook_size');
      expect(stats).toHaveProperty('initialized');
      expect(stats).toHaveProperty('total_encoded');
      expect(stats).toHaveProperty('hit_rate');
    });
  });

  // ============================================================
  // §3.2: codebook 塌缩防护
  // ============================================================
  describe('codebook 塌缩防护', () => {
    it('应暴露 collapseThreshold 常量 = 1/256', () => {
      const enc = new SolutionEncoder();
      expect(enc.collapseThreshold).toBeCloseTo(1 / 256, 4);
    });

    it('getStats 应返回 usage 分布', () => {
      const enc = new SolutionEncoder();
      const stats = enc.getStats();
      expect(stats).toHaveProperty('usage_distribution');
    });
  });

  // ============================================================
  // §3.2: 降级模式 — hit rate < 30% → bge+LSH
  // ============================================================
  describe('降级模式', () => {
    it('应暴露 degradationHitRateThreshold = 0.3', () => {
      const enc = new SolutionEncoder();
      expect(enc.degradationHitRateThreshold).toBeCloseTo(0.3, 2);
    });

    it('hit rate < 30% 时 retrieval_mode 应为 lsh', () => {
      const enc = new SolutionEncoder({ forceHitRate: 0.15 });
      // 模拟低 hit rate
      const result = enc.encode({
        intent: 'degradation-test',
        actions: ['a'],
        outcome_text: 'ok',
        learned: ['l'],
      });
      expect(['lsh', 'fallback']).toContain(result.retrieval_mode);
    });
  });

  // ============================================================
  // §3.2: 相似输入产生相似 codebook 索引
  // ============================================================
  describe('相似性保持', () => {
    it('相似 intent 应映射到相同或相近的 codebook 索引', () => {
      const enc = new SolutionEncoder();
      // 先灌入足量数据触发初始化
      for (let i = 0; i < 100; i++) {
        enc.encode({
          intent: `seed-${i}`,
          actions: [`act-${i}`],
          outcome_text: `out-${i}`,
          learned: [`l-${i}`],
        });
      }
      // inference-only 模式：相同输入应产生相同索引（不做 EMA 更新）
      const r1 = enc.encode({
        intent: '检查项目架构逻辑',
        actions: ['检查架构', '修复问题'],
        outcome_text: '架构检查完成',
        learned: ['架构自洽'],
      }, false);  // train=false: inference-only
      const r2 = enc.encode({
        intent: '检查项目架构逻辑',
        actions: ['检查架构', '修复问题'],
        outcome_text: '架构检查完成',
        learned: ['架构自洽'],
      }, false);
      // 完全相同输入应产生相同 codebook 索引
      expect(r1.codebook_index).toEqual(r2.codebook_index);
    });
  });
});
