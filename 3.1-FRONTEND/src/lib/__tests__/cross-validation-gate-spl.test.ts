/**
 * SPEC-20261009 §11 P0-4: CrossValidationGate for SPL 测试
 *
 * TDD RED 阶段 — 验证 3 个组件 + 五步算法
 *
 * 覆盖（§11.9 TDD 步骤 1-4）：
 *   Step 1: PatternAggregator — VQ-VAE 编码 → A_dim_spl
 *   Step 2: SolutionPatternValidator — TDR 检索 → G_dim_spl
 *   Step 3: CrossValidationGate 主体 — 五步算法
 *   Step 4: 层权重接入 — layer_weight_adjustment
 *
 * 维度（§11.3）: code-driven / ai-driven / hybrid / lookup / research
 */

import {
  CrossValidationGateSPL,
  PatternAggregator,
  SolutionPatternValidator,
  type CrossValidationResult,
  type SPLDimension,
} from '../cross-validation-gate-spl';

describe('SPEC §11 P0-4: CrossValidationGate for SPL', () => {
  // ============================================================
  // §11.9 Step 1: PatternAggregator
  // ============================================================
  describe('Step 1: PatternAggregator', () => {
    it('应导出 PatternAggregator 类', () => {
      expect(PatternAggregator).toBeDefined();
      expect(typeof PatternAggregator).toBe('function');
    });

    it('应从 actions 数组判定主范式维度', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate(['修改文件', '创建组件', '编辑代码']);
      expect(result.dim).toBe('code-driven');
      expect(result.strength).toBeGreaterThan(0);
    });

    it('AI 驱动 actions → ai-driven', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate(['分析需求', '生成方案', '评估结果']);
      expect(result.dim).toBe('ai-driven');
    });

    it('代码+AI 混合 → hybrid', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate(['修改文件', '分析需求', '创建组件']);
      expect(result.dim).toBe('hybrid');
    });

    it('查询类 → lookup', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate(['查询文档', '检索知识', '搜索案例']);
      expect(result.dim).toBe('lookup');
    });

    it('调研类 → research', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate(['调研方案', '研究论文', '对比工具']);
      expect(result.dim).toBe('research');
    });

    it('空 actions → null dim', () => {
      const agg = new PatternAggregator();
      const result = agg.aggregate([]);
      expect(result.dim).toBeNull();
    });
  });

  // ============================================================
  // §11.9 Step 2: SolutionPatternValidator
  // ============================================================
  describe('Step 2: SolutionPatternValidator', () => {
    it('应导出 SolutionPatternValidator 类', () => {
      expect(SolutionPatternValidator).toBeDefined();
      expect(typeof SolutionPatternValidator).toBe('function');
    });

    it('应从 TDR 检索结果推断过去主范式', () => {
      const validator = new SolutionPatternValidator();
      // 模拟 TDR 检索结果（多数 code-driven）
      const tdrResults = [
        { actions: ['修改文件', '创建组件'], outcome: 'success', quality: 'B' as const },
        { actions: ['修改文件', '编辑代码'], outcome: 'success', quality: 'B' as const },
        { actions: ['分析需求'], outcome: 'success', quality: 'C' as const },
      ];
      const result = validator.validate(tdrResults);
      expect(result.dim).toBe('code-driven');
      expect(result.confidence).toBeGreaterThan(0);
    });

    it('TDR 空结果 → dim=null + confidence=0', () => {
      const validator = new SolutionPatternValidator();
      const result = validator.validate([]);
      expect(result.dim).toBeNull();
      expect(result.confidence).toBe(0);
    });
  });

  // ============================================================
  // §11.9 Step 3: CrossValidationGate 主体（五步算法）
  // ============================================================
  describe('Step 3: CrossValidationGate 五步算法', () => {
    it('应导出 CrossValidationGateSPL 类', () => {
      expect(CrossValidationGateSPL).toBeDefined();
      expect(typeof CrossValidationGateSPL).toBe('function');
    });

    it('G_dim == A_dim → confidence_boost(1.15), no shift', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare('code-driven', 0.8, 'code-driven', 0.9, false);
      expect(result.confidence_mult).toBeCloseTo(1.15, 2);
      expect(result.shift_signal).toBe(false);
      expect(result.divergence_count).toBe(0);
    });

    it('G_dim != A_dim → confidence_penalty(0.9), shift_signal=true', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, false);
      expect(result.confidence_mult).toBeCloseTo(0.9, 2);
      expect(result.shift_signal).toBe(true);
      expect(result.divergence_count).toBe(1);
    });

    it('G_dim 或 A_dim 为 null → 中性结果(FAIL-OPEN)', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare(null, 0, 'code-driven', 0.9, false);
      expect(result.confidence_mult).toBe(1.0);
      expect(result.shift_signal).toBe(false);
    });

    it('持续分歧 >= persistence_threshold(5) + drift → 质变', () => {
      const cvg = new CrossValidationGateSPL({ persistence_threshold: 5 });
      // 连续 5 次分歧
      let result: CrossValidationResult;
      for (let i = 0; i < 4; i++) {
        result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, false);
        expect(result.quality_change).toBe(false);
      }
      // 第 5 次 + drift → 质变
      result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, true);
      expect(result.quality_change).toBe(true);
      expect(result.retrain_trigger).toBe(true);
      expect(result.new_main_dim).toBe('ai-driven');
    });

    it('持续分歧 >= threshold 但无 drift → 不质变', () => {
      const cvg = new CrossValidationGateSPL({ persistence_threshold: 5 });
      for (let i = 0; i < 5; i++) {
        const result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, false);
        expect(result.quality_change).toBe(false);
      }
    });

    it('质变后 divergence_count 应重置为 0', () => {
      const cvg = new CrossValidationGateSPL({ persistence_threshold: 3 });
      for (let i = 0; i < 2; i++) {
        cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, false);
      }
      const result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, true);
      expect(result.quality_change).toBe(true);
      expect(result.divergence_count).toBe(0);
    });
  });

  // ============================================================
  // §11.9 Step 4: 层权重动态调整
  // ============================================================
  describe('Step 4: 层权重调整', () => {
    it('分歧期间应生成 layer_weight_adjustment', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare('code-driven', 0.8, 'ai-driven', 0.9, false);
      expect(result.shift_signal).toBe(true);
      expect(Object.keys(result.layer_weight_adjustment).length).toBeGreaterThan(0);
    });

    it('一致时 layer_weight_adjustment 应为空', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare('code-driven', 0.8, 'code-driven', 0.9, false);
      expect(Object.keys(result.layer_weight_adjustment).length).toBe(0);
    });

    it('code-driven → [S, DSH] 层', () => {
      const cvg = new CrossValidationGateSPL();
      const result = cvg.compare('ai-driven', 0.8, 'code-driven', 0.9, false);
      expect(result.layer_weight_adjustment).toHaveProperty('S');
      expect(result.layer_weight_adjustment).toHaveProperty('DSH');
    });

    it('层权重应在 [0.5, 2.0] 范围内（floor/ceiling）', () => {
      const cvg = new CrossValidationGateSPL({ persistence_threshold: 3, layer_boost_rate: 0.5 });
      for (let i = 0; i < 2; i++) {
        cvg.compare('lookup', 0.8, 'code-driven', 0.9, false);
      }
      const result = cvg.compare('lookup', 0.8, 'code-driven', 0.9, false);
      for (const [layer, weight] of Object.entries(result.layer_weight_adjustment)) {
        expect(weight).toBeGreaterThanOrEqual(0.5);
        expect(weight).toBeLessThanOrEqual(2.0);
      }
    });
  });

  // ============================================================
  // §11.7: 配置开关
  // ============================================================
  describe('配置开关', () => {
    it('默认参数: persistence=5, boost=1.15, penalty=0.9', () => {
      const cvg = new CrossValidationGateSPL();
      expect(cvg.persistence_threshold).toBe(5);
      expect(cvg.confidence_boost).toBeCloseTo(1.15, 2);
      expect(cvg.confidence_penalty).toBeCloseTo(0.9, 2);
    });

    it('layer_boost_rate 默认 0.3, layer_decay_rate 默认 0.2', () => {
      const cvg = new CrossValidationGateSPL();
      expect(cvg.layer_boost_rate).toBeCloseTo(0.3, 2);
      expect(cvg.layer_decay_rate).toBeCloseTo(0.2, 2);
    });
  });
});
