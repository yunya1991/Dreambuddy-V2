/**
 * SPEC v0.5 P1: DriftDetectorAdapter 适配层测试
 *
 * TDD RED→GREEN
 *
 * 覆盖:
 *   - DriftDetectorAdapter 类存在性 + 可实例化
 *   - S层: intent_freq 分布 → 概率向量 → drift 检测
 *   - C层: rule outcome 分布 → 概率向量
 *   - G层: node degree 直方图
 *   - LLM层: template usage 频率
 *   - 各层 KL 阈值差异化
 *   - reset 方法
 */

import { DriftDetectorAdapter } from '../drift-detector-adapter';

describe('SPEC v0.5 P1: DriftDetectorAdapter 适配层', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('DriftDetectorAdapter 应可导入且可实例化', () => {
      const adapter = new DriftDetectorAdapter('S');
      expect(adapter).toBeInstanceOf(DriftDetectorAdapter);
    });

    it('应支持 5 层创建', () => {
      for (const layer of ['S', 'DSH', 'C', 'G', 'LLM']) {
        const adapter = new DriftDetectorAdapter(layer);
        expect(adapter).toBeInstanceOf(DriftDetectorAdapter);
      }
    });
  });

  // ----------------------------------------------------------
  // 2. S 层: intent 频率分布 → drift 检测
  // ----------------------------------------------------------
  describe('S 层: intent 频率分布', () => {
    it('应将 intentFreq 转换为分布向量', () => {
      const adapter = new DriftDetectorAdapter('S');
      const snapshot = {
        weights: {},
        typeKeywords: {},
        intentFreq: { code_inspection: 30, research: 15, bugfix: 5 },
        docCount: 50,
        step: 0,
        drift_flag: false,
        timestamp: 0,
        version: 'v0.5',
      };
      const dist = adapter.toDistribution(snapshot);
      expect(dist.length).toBeGreaterThan(0);
      // 3 个 intent types
      expect(dist.length).toBe(3);
      // 归一化: sum = 1
      const sum = dist.reduce((a, b) => a + b, 0);
      expect(sum).toBeCloseTo(1.0, 5);
    });

    it('S 层 KL 阈值应为 0.15', () => {
      const adapter = new DriftDetectorAdapter('S');
      expect(adapter.klThreshold).toBe(0.15);
    });

    it('分布稳定时不应检测到漂移', () => {
      const adapter = new DriftDetectorAdapter('S');
      const snapshot = {
        intentFreq: { a: 10, b: 10 },
        docCount: 20,
      };
      // 设置基线 + 添加相同分布的样本
      adapter.setBaseline(snapshot);
      adapter.addSample(snapshot);
      const result = adapter.detectDrift(snapshot);
      expect(result.drift_detected).toBe(false);
    });

    it('分布剧变时应检测到漂移', () => {
      const adapter = new DriftDetectorAdapter('S');
      const baseline = { intentFreq: { a: 50, b: 0 }, docCount: 50 };
      const drifted = { intentFreq: { a: 0, b: 50 }, docCount: 50 };
      adapter.setBaseline(baseline);
      // 添加多个漂移样本
      for (let i = 0; i < 10; i++) {
        adapter.addSample(drifted);
      }
      const result = adapter.detectDrift(drifted);
      expect(result.drift_detected).toBe(true);
      expect(result.kl_score).toBeGreaterThan(0.15);
    });
  });

  // ----------------------------------------------------------
  // 3. C 层: rule outcome 分布
  // ----------------------------------------------------------
  describe('C 层: rule outcome 分布', () => {
    it('应将 rules 的 outcome 分布转换为概率向量', () => {
      const adapter = new DriftDetectorAdapter('C');
      const snapshot = {
        rules: [
          { outcome: 'success' },
          { outcome: 'success' },
          { outcome: 'partial' },
          { outcome: 'failure' },
        ],
      };
      const dist = adapter.toDistribution(snapshot);
      // 3 个 outcome 类别
      expect(dist.length).toBe(3);
      const sum = dist.reduce((a, b) => a + b, 0);
      expect(sum).toBeCloseTo(1.0, 5);
    });

    it('C 层 KL 阈值应为 0.20', () => {
      const adapter = new DriftDetectorAdapter('C');
      expect(adapter.klThreshold).toBe(0.20);
    });
  });

  // ----------------------------------------------------------
  // 4. G 层: node degree 直方图
  // ----------------------------------------------------------
  describe('G 层: node degree 直方图', () => {
    it('应将 graph nodes 的 degree 转换为直方图', () => {
      const adapter = new DriftDetectorAdapter('G');
      const snapshot = {
        graph: {
          nodes: {
            A: { edges: ['e1', 'e2'], weight: 1 },
            B: { edges: ['e1'], weight: 1 },
            C: { edges: [], weight: 1 },
          },
          edges: {},
        },
      };
      const dist = adapter.toDistribution(snapshot);
      expect(dist.length).toBeGreaterThan(0);
      const sum = dist.reduce((a, b) => a + b, 0);
      expect(sum).toBeCloseTo(1.0, 5);
    });

    it('G 层 KL 阈值应为 0.25', () => {
      const adapter = new DriftDetectorAdapter('G');
      expect(adapter.klThreshold).toBe(0.25);
    });
  });

  // ----------------------------------------------------------
  // 5. LLM 层: template usage 频率
  // ----------------------------------------------------------
  describe('LLM 层: template usage 频率', () => {
    it('应将 promptTemplates 的 usage_count 转换为概率向量', () => {
      const adapter = new DriftDetectorAdapter('LLM');
      const snapshot = {
        promptTemplates: [
          { usage_count: 10 },
          { usage_count: 5 },
          { usage_count: 20 },
        ],
      };
      const dist = adapter.toDistribution(snapshot);
      expect(dist.length).toBe(3);
      const sum = dist.reduce((a, b) => a + b, 0);
      expect(sum).toBeCloseTo(1.0, 5);
    });

    it('LLM 层 KL 阈值应为 0.15', () => {
      const adapter = new DriftDetectorAdapter('LLM');
      expect(adapter.klThreshold).toBe(0.15);
    });
  });

  // ----------------------------------------------------------
  // 6. DSH 层
  // ----------------------------------------------------------
  describe('DSH 层', () => {
    it('DSH 层 KL 阈值应为 0.15', () => {
      const adapter = new DriftDetectorAdapter('DSH');
      expect(adapter.klThreshold).toBe(0.15);
    });

    it('应将 pathFreq 转换为 Top-K 分布', () => {
      const adapter = new DriftDetectorAdapter('DSH');
      const snapshot = {
        pathFreq: { 'A→B→C': 10, 'X→Y→Z': 5, 'P→Q': 3 },
      };
      const dist = adapter.toDistribution(snapshot);
      expect(dist.length).toBeGreaterThan(0);
      const sum = dist.reduce((a, b) => a + b, 0);
      expect(sum).toBeCloseTo(1.0, 5);
    });
  });

  // ----------------------------------------------------------
  // 7. reset
  // ----------------------------------------------------------
  describe('reset', () => {
    it('reset 后应可重新设置基线', () => {
      const adapter = new DriftDetectorAdapter('S');
      const snapshot = { intentFreq: { a: 10 }, docCount: 10 };
      adapter.setBaseline(snapshot);
      adapter.addSample(snapshot);
      adapter.reset();
      // reset 后 window 应为空
      const result = adapter.detectDrift(snapshot);
      expect(result.kl_score).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 8. 空快照处理
  // ----------------------------------------------------------
  describe('空快照处理', () => {
    it('空快照应返回空分布', () => {
      const adapter = new DriftDetectorAdapter('S');
      const dist = adapter.toDistribution({});
      expect(dist.length).toBe(0);
    });

    it('空快照 detectDrift 不应崩溃', () => {
      const adapter = new DriftDetectorAdapter('S');
      const result = adapter.detectDrift({});
      expect(result.drift_detected).toBe(false);
      expect(result.kl_score).toBe(0);
    });
  });
});
