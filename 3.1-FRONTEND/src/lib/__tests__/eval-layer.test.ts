/**
 * SPEC-20261009 §4.5 P4-1: 评估层 EvalLayer 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - EvalLayer 类存在性 + 可实例化
 *   - 各层复现阈值: S=0.8, DSH=0.3, C=0.75, LLM=0.7, G=0.7
 *   - evaluateLayer: 复现/超越判定
 *   - evaluateAll: 全链路评估
 *   - LayerEvalResult 结构: {layer, reproduced, surpassed, metric, baseline, threshold}
 */

import { EvalLayer, type LayerName, type LayerEvalResult, type EvalSummary } from '../eval-layer';

describe('SPEC §4.5 P4-1: 评估层 EvalLayer', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('EvalLayer 类应可导入且可实例化', () => {
      const evalLayer = new EvalLayer();
      expect(evalLayer).toBeInstanceOf(EvalLayer);
    });

    it('各层复现阈值应为 S=0.8, DSH=0.3, C=0.75, LLM=0.7, G=0.7', () => {
      const evalLayer = new EvalLayer();
      expect(evalLayer.thresholds.S).toBe(0.8);
      expect(evalLayer.thresholds.DSH).toBe(0.3);
      expect(evalLayer.thresholds.C).toBe(0.75);
      expect(evalLayer.thresholds.LLM).toBe(0.7);
      expect(evalLayer.thresholds.G).toBe(0.7);
    });
  });

  // ----------------------------------------------------------
  // 2. evaluateLayer 复现判定
  // ----------------------------------------------------------
  describe('evaluateLayer 复现判定', () => {
    it('S层: intent 一致率 ≥ 0.8 → reproduced=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', {
        metric: 0.85, // 一致率 85%
        baseline: 0.8, // Trae Code 80%
      });
      expect(result.reproduced).toBe(true);
      expect(result.layer).toBe('S');
      expect(result.metric).toBe(0.85);
    });

    it('S层: intent 一致率 < 0.8 → reproduced=false', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', {
        metric: 0.75,
        baseline: 0.8,
      });
      expect(result.reproduced).toBe(false);
    });

    it('DSH层: 编辑距离比 ≤ 0.3 → reproduced=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('DSH', {
        metric: 0.25, // 编辑距离比 25%
        baseline: 0.3,
      });
      expect(result.reproduced).toBe(true);
    });

    it('DSH层: 编辑距离比 > 0.3 → reproduced=false', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('DSH', {
        metric: 0.4,
        baseline: 0.3,
      });
      expect(result.reproduced).toBe(false);
    });

    it('C层: 决策一致率 ≥ 0.75 → reproduced=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('C', {
        metric: 0.8,
        baseline: 0.75,
      });
      expect(result.reproduced).toBe(true);
    });

    it('LLM层: 语义相似度 ≥ 0.7 → reproduced=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('LLM', {
        metric: 0.75,
        baseline: 0.7,
      });
      expect(result.reproduced).toBe(true);
    });

    it('G层: 图覆盖率 ≥ 0.7 → reproduced=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('G', {
        metric: 0.75,
        baseline: 0.7,
      });
      expect(result.reproduced).toBe(true);
    });
  });

  // ----------------------------------------------------------
  // 3. evaluateLayer 超越判定
  // ----------------------------------------------------------
  describe('evaluateLayer 超越判定', () => {
    it('超越: 输出质量 > baseline 且指标更优 → surpassed=true', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', {
        metric: 0.9, // 一致率 90%
        baseline: 0.8, // Trae 80%
      });
      expect(result.surpassed).toBe(true); // 90% > 80% baseline
    });

    it('未超越: 输出质量 == baseline → surpassed=false', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', {
        metric: 0.8,
        baseline: 0.8,
      });
      expect(result.surpassed).toBe(false);
    });

    it('未超越: 输出质量 < baseline → surpassed=false', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', {
        metric: 0.82,
        baseline: 0.9,
      });
      expect(result.surpassed).toBe(false);
    });
  });

  // ----------------------------------------------------------
  // 4. LayerEvalResult 结构
  // ----------------------------------------------------------
  describe('LayerEvalResult 结构', () => {
    it('应包含 layer, reproduced, surpassed, metric, baseline, threshold 字段', () => {
      const evalLayer = new EvalLayer();
      const result = evalLayer.evaluateLayer('S', { metric: 0.85, baseline: 0.8 });
      expect(result).toHaveProperty('layer');
      expect(result).toHaveProperty('reproduced');
      expect(result).toHaveProperty('surpassed');
      expect(result).toHaveProperty('metric');
      expect(result).toHaveProperty('baseline');
      expect(result).toHaveProperty('threshold');
      expect(result.threshold).toBe(0.8);
    });
  });

  // ----------------------------------------------------------
  // 5. evaluateAll 全链路评估
  // ----------------------------------------------------------
  describe('evaluateAll 全链路评估', () => {
    it('应评估所有层并返回汇总', () => {
      const evalLayer = new EvalLayer();
      const results = evalLayer.evaluateAll({
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.25, baseline: 0.3 },
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      });

      expect(results.layer_results).toHaveLength(5);
      // 所有层都复现
      expect(results.all_reproduced).toBe(true);
      // 所有层都超越（metric > baseline）
      expect(results.all_surpassed).toBe(true);
    });

    it('部分层未复现 → all_reproduced=false', () => {
      const evalLayer = new EvalLayer();
      const results = evalLayer.evaluateAll({
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.4, baseline: 0.3 }, // 未复现
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      });

      expect(results.all_reproduced).toBe(false);
      expect(results.layer_results.find(r => r.layer === 'DSH')?.reproduced).toBe(false);
    });

    it('全链路复现率应计算正确', () => {
      const evalLayer = new EvalLayer();
      const results = evalLayer.evaluateAll({
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.4, baseline: 0.3 },
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      });
      // 4/5 复现 = 0.8
      expect(results.reproduction_rate).toBeCloseTo(0.8, 1);
    });
  });

  // ----------------------------------------------------------
  // 6. 自定义阈值
  // ----------------------------------------------------------
  describe('自定义阈值', () => {
    it('应支持自定义复现阈值', () => {
      const evalLayer = new EvalLayer({ thresholds: { S: 0.9 } });
      expect(evalLayer.thresholds.S).toBe(0.9);
      const result = evalLayer.evaluateLayer('S', { metric: 0.85, baseline: 0.8 });
      expect(result.reproduced).toBe(false); // 0.85 < 0.9
    });
  });
});
