/**
 * SPEC-20261009 §4.2.5 P2-3: LLM PromptOptimizationLoop 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - PromptOptimizationLoop 类存在性 + 可实例化
 *   - 桶满阈值=30（SPEC v0.3 LLM差异化）
 *   - Prompt 模式聚类（频繁模板→最优模板）
 *   - 上下文注入优化（哪些信息最有效）
 *   - Token 效率优化（精简 prompt）
 *   - 训练结果包含 prompt_templates + avg_token_efficiency + semantic_similarity
 */

import { PromptOptimizationLoop, type PromptTrainingData, type PromptTrainingResult } from '../llm-prompt-training-loop';

describe('SPEC §4.2.5 P2-3: LLM PromptOptimizationLoop', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('PromptOptimizationLoop 类应可导入且可实例化', () => {
      const loop = new PromptOptimizationLoop();
      expect(loop).toBeInstanceOf(PromptOptimizationLoop);
    });

    it('桶满阈值应为 30（SPEC v0.3 LLM差异化）', () => {
      const loop = new PromptOptimizationLoop();
      expect(loop.bucketThreshold).toBe(30);
    });
  });

  // ----------------------------------------------------------
  // 2. 训练数据管理
  // ----------------------------------------------------------
  describe('训练数据管理', () => {
    it('addTrainingData 应添加数据到桶', () => {
      const loop = new PromptOptimizationLoop();
      loop.addTrainingData({
        intent: '检查代码',
        learned: ['代码风格统一'],
        outcome: 'success',
        prompt_pattern: '请检查以下代码的风格问题：{code}',
      });
      expect(loop.bucketCount).toBe(1);
    });

    it('shouldTrain: 桶未满应返回 false', () => {
      const loop = new PromptOptimizationLoop();
      loop.addTrainingData({
        intent: 'test',
        learned: ['test'],
        outcome: 'success',
        prompt_pattern: 'test pattern',
      });
      expect(loop.shouldTrain()).toBe(false);
    });

    it('shouldTrain: 桶满30应返回 true', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `intent-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: `pattern-${i}`,
        });
      }
      expect(loop.shouldTrain()).toBe(true);
    });

    it('clear 应清空桶', () => {
      const loop = new PromptOptimizationLoop();
      loop.addTrainingData({
        intent: 'test',
        learned: ['test'],
        outcome: 'success',
        prompt_pattern: 'test',
      });
      loop.clear();
      expect(loop.bucketCount).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 3. 训练执行
  // ----------------------------------------------------------
  describe('训练执行', () => {
    it('空桶 train 应返回 trained=false', () => {
      const loop = new PromptOptimizationLoop();
      const result = loop.train();
      expect(result.trained).toBe(false);
    });

    it('桶满 train 应返回 trained=true + prompt_templates', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `检查代码${i}`,
          learned: ['代码风格统一', '变量命名规范'],
          outcome: 'success',
          prompt_pattern: '请检查代码：{code}，输出问题列表',
        });
      }
      const result = loop.train();
      expect(result.trained).toBe(true);
      expect(result.prompt_templates).toBeDefined();
      expect(result.prompt_templates.length).toBeGreaterThan(0);
    });

    it('train 后桶应清空', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['l'],
          outcome: 'success',
          prompt_pattern: 'p',
        });
      }
      loop.train();
      expect(loop.bucketCount).toBe(0);
    });

    it('Prompt 模式聚类: 频繁模板应成为最优模板', () => {
      const loop = new PromptOptimizationLoop();
      // 20 次相同模板，10 次不同模板
      for (let i = 0; i < 20; i++) {
        loop.addTrainingData({
          intent: `intent-a-${i}`,
          learned: ['经验A'],
          outcome: 'success',
          prompt_pattern: '请分析：{input}',
        });
      }
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({
          intent: `intent-b-${i}`,
          learned: ['经验B'],
          outcome: 'failure',
          prompt_pattern: '请总结：{input}',
        });
      }
      const result = loop.train();
      const topTemplate = result.prompt_templates[0];
      expect(topTemplate.template).toBe('请分析：{input}');
      expect(topTemplate.count).toBeGreaterThanOrEqual(20);
    });

    it('上下文注入优化: success 案例的 learned 应有更高权重', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 15; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['代码审查', '依赖分析'],
          outcome: 'success',
          prompt_pattern: 'p1',
        });
      }
      for (let i = 0; i < 15; i++) {
        loop.addTrainingData({
          intent: `i2-${i}`,
          learned: ['调试'],
          outcome: 'failure',
          prompt_pattern: 'p2',
        });
      }
      const result = loop.train();
      // success 案例的 learned 关键词权重应更高（2-gram: "审查" vs "调试"）
      expect(result.context_keywords['审查']).toBeGreaterThan(result.context_keywords['调试']);
    });

    it('Token 效率优化: 应计算 avg_token_efficiency', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: `prompt-${i % 2}`,
        });
      }
      const result = loop.train();
      expect(result.avg_token_efficiency).toBeGreaterThanOrEqual(0);
      expect(result.avg_token_efficiency).toBeLessThanOrEqual(1);
    });

    it('训练结果应包含 semantic_similarity 字段', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'p',
        });
      }
      const result = loop.train();
      expect(result.semantic_similarity).toBeGreaterThanOrEqual(0);
      expect(result.semantic_similarity).toBeLessThanOrEqual(1);
    });

    it('训练结果应包含 bucket_threshold + timestamp', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 30; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['l'],
          outcome: 'success',
          prompt_pattern: 'p',
        });
      }
      const result = loop.train();
      expect(result.bucket_threshold).toBe(30);
      expect(result.timestamp).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 4. 自定义桶满阈值
  // ----------------------------------------------------------
  describe('自定义桶满阈值', () => {
    it('应支持自定义桶满阈值', () => {
      const loop = new PromptOptimizationLoop({ bucketThreshold: 10 });
      expect(loop.bucketThreshold).toBe(10);
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['l'],
          outcome: 'success',
          prompt_pattern: 'p',
        });
      }
      expect(loop.shouldTrain()).toBe(true);
    });
  });
});
