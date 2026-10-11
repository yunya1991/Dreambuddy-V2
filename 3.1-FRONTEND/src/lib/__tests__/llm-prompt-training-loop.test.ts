/**
 * SPEC-20261009 §4.2.5 P2-3: LLM PromptOptimizationLoop 测试
 * SPEC-20261011 v0.5: ReplayBuffer + trainIncremental
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
 *   - v0.5: trainIncremental + getModelSnapshot / restoreModel
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

    it('clear 只重置模型状态，不清空 buffer（v0.5）', () => {
      const loop = new PromptOptimizationLoop();
      loop.addTrainingData({
        intent: 'test',
        learned: ['test'],
        outcome: 'success',
        prompt_pattern: 'test',
      });
      loop.clear();
      // v0.5: clear 只重置模型状态，不清空 buffer
      expect(loop.bucketCount).toBe(1);
      expect(loop.step).toBe(0);
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

    it('train 后 buffer 不清空（v0.5: 持续训练，不清空）', () => {
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
      // v0.5: buffer 永不清空，只做衰减
      expect(loop.bucketCount).toBe(30);
    });

    it('train 后应返回 incrementalStep + bufferStats（v0.5）', () => {
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
      expect(result.incrementalStep).toBeGreaterThan(0);
      expect(result.bufferStats).toBeDefined();
      expect(result.bufferStats?.size).toBe(30);
      expect(result.bufferStats?.capacity).toBe(100);
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
  // 3.5 v0.5: trainIncremental 增量训练
  // ----------------------------------------------------------
  describe('v0.5: trainIncremental 增量训练', () => {
    it('trainIncremental 应增量更新模型，不清空 buffer', () => {
      const loop = new PromptOptimizationLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'p',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      const result = loop.trainIncremental(batch);
      expect(result.trained).toBe(true);
      expect(result.incrementalStep).toBe(1);
      expect(loop.bucketCount).toBe(3);
      expect(loop.step).toBe(1);
    });

    it('trainIncremental 多次训练应递增 step', () => {
      const loop = new PromptOptimizationLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'p',
        }, 'B');
      }
      for (let i = 0; i < 3; i++) {
        const batch = loop.replayBuffer.sample(3).map(e => e.data);
        loop.trainIncremental(batch);
      }
      expect(loop.step).toBe(3);
    });

    it('trainIncremental 后模型状态应保留', () => {
      const loop = new PromptOptimizationLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['代码审查'],
          outcome: 'success',
          prompt_pattern: '请分析：{input}',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      expect(snapshot.step).toBe(1);
      expect(Object.keys(snapshot.templateStats).length).toBeGreaterThan(0);
      expect(snapshot.templateStats['请分析：{input}']).toBeDefined();
      expect(snapshot.contextKeywords['审查']).toBeGreaterThan(0);
    });

    it('getModelSnapshot / restoreModel 应可保存恢复', () => {
      const loop = new PromptOptimizationLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'p',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);

      const snapshot = loop.getModelSnapshot();
      const loop2 = new PromptOptimizationLoop();
      loop2.restoreModel(snapshot);

      expect(loop2.step).toBe(1);
      expect(loop2.getModelSnapshot().templateStats).toEqual(snapshot.templateStats);
    });

    it('addTrainingData 支持 quality 参数', () => {
      const loop = new PromptOptimizationLoop();
      loop.addTrainingData({
        intent: 'S级',
        learned: ['l'],
        outcome: 'success',
        prompt_pattern: 'p',
      }, 'S');
      loop.addTrainingData({
        intent: 'C级',
        learned: ['l'],
        outcome: 'success',
        prompt_pattern: 'p',
      }, 'C');
      const stats = loop.getBufferStats();
      expect(stats.qualityDistribution.S).toBe(1);
      expect(stats.qualityDistribution.C).toBe(1);
    });
  });

  // ----------------------------------------------------------
  // 3.6 SPEC v0.5 P3.3: LLM 层 KL 散度约束
  // ----------------------------------------------------------
  describe('SPEC v0.5 P3.3: KL 散度约束', () => {
    it('P3.3: trainIncremental 在分布漂移时应触发 KL 约束（不崩溃）', () => {
      const loop = new PromptOptimizationLoop();
      // 阶段1: 喂入 template-A 数据
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验A'],
          outcome: 'success',
          prompt_pattern: 'template-A',
        }, 'B');
      }
      const batchA = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batchA);
      // 阶段2: 喂入完全不同的 template-B 数据 → 分布剧变
      const batchB: PromptTrainingData[] = [];
      for (let i = 0; i < 3; i++) {
        batchB.push({
          intent: `i-b${i}`,
          learned: ['经验B'],
          outcome: 'success',
          prompt_pattern: 'template-B',
        });
      }
      // KL 约束应触发但不崩溃
      const result = loop.trainIncremental(batchB);
      expect(result.trained).toBe(true);
      expect(result.incrementalStep).toBe(2);
    });

    it('P3.3: KL 约束触发后模板权重应被回退（缩放 0.5）', () => {
      const loop = new PromptOptimizationLoop();
      // 阶段1: 建立 template-A 主导分布
      for (let i = 0; i < 5; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验A'],
          outcome: 'success',
          prompt_pattern: 'template-A',
        }, 'B');
      }
      const batchA = loop.replayBuffer.sample(5).map(e => e.data);
      loop.trainIncremental(batchA);
      const wBefore = loop.getModelSnapshot().templateStats['template-A']?.weight ?? 0;

      // 阶段2: 完全不同的 template-B → KL > 0.5 → 回退
      const batchB: PromptTrainingData[] = [];
      for (let i = 0; i < 5; i++) {
        batchB.push({
          intent: `i-b${i}`,
          learned: ['经验B'],
          outcome: 'success',
          prompt_pattern: 'template-B',
        });
      }
      loop.trainIncremental(batchB);
      const wAfter = loop.getModelSnapshot().templateStats['template-A']?.weight ?? 0;
      // KL 回退后 A 的权重应明显小于回退前（×0.5 衰减）
      expect(wAfter).toBeLessThan(wBefore);
    });

    it('P3.3: 相同模板增量训练不触发 KL 回退（分布稳定）', () => {
      const loop = new PromptOptimizationLoop();
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          intent: `i-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'same-template',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const w1 = loop.getModelSnapshot().templateStats['same-template']?.weight ?? 0;
      // 再次喂入相同模板 → 分布不变 → KL≈0 → 不回退
      loop.trainIncremental(batch);
      const w2 = loop.getModelSnapshot().templateStats['same-template']?.weight ?? 0;
      // 相同模板叠加，权重应增长（不回退）
      expect(w2).toBeGreaterThanOrEqual(w1);
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
