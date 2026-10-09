/**
 * SPEC-20261009 §4.2.1 P1-5: S层 IntentTrainingLoop 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - IntentTrainingLoop 类存在性 + 可实例化
 *   - 桶满阈值=50（SPEC v0.3 S层差异化）
 *   - addTrainingData / shouldTrain / train / clear
 *   - 训练结果包含 accuracy + weights
 *   - FAIL-OPEN：空桶训练返回 not trained
 */

import { IntentTrainingLoop, type TrainingData, type TrainingResult } from '../s-intent-training-loop';

describe('SPEC §4.2.1 P1-5: S层 IntentTrainingLoop', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('IntentTrainingLoop 类应可导入且可实例化', () => {
      const loop = new IntentTrainingLoop();
      expect(loop).toBeInstanceOf(IntentTrainingLoop);
    });

    it('桶满阈值应为 50（SPEC v0.3 S层差异化）', () => {
      const loop = new IntentTrainingLoop();
      expect(loop.bucketThreshold).toBe(50);
    });
  });

  // ----------------------------------------------------------
  // 2. 训练数据管理
  // ----------------------------------------------------------
  describe('训练数据管理', () => {
    it('addTrainingData 应添加数据到桶', () => {
      const loop = new IntentTrainingLoop();
      loop.addTrainingData({ message: '检查架构', intent_type: 'code_inspection' });
      expect(loop.bucketCount).toBe(1);
    });

    it('shouldTrain: 桶未满应返回 false', () => {
      const loop = new IntentTrainingLoop();
      loop.addTrainingData({ message: 'test', intent_type: 'test' });
      expect(loop.shouldTrain()).toBe(false);
    });

    it('shouldTrain: 桶满50应返回 true', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: `type-${i % 5}` });
      }
      expect(loop.shouldTrain()).toBe(true);
    });

    it('clear 应清空桶', () => {
      const loop = new IntentTrainingLoop();
      loop.addTrainingData({ message: 'test', intent_type: 'test' });
      loop.clear();
      expect(loop.bucketCount).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 3. 训练执行
  // ----------------------------------------------------------
  describe('训练执行', () => {
    it('空桶 train 应返回 trained=false', () => {
      const loop = new IntentTrainingLoop();
      const result = loop.train();
      expect(result.trained).toBe(false);
    });

    it('桶满 train 应返回 trained=true + accuracy + weights', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `检查架构问题${i}`, intent_type: 'code_inspection' });
      }
      const result = loop.train();
      expect(result.trained).toBe(true);
      expect(result.accuracy).toBeGreaterThanOrEqual(0);
      expect(result.accuracy).toBeLessThanOrEqual(1);
      expect(result.weights).toBeDefined();
      expect(Object.keys(result.weights).length).toBeGreaterThan(0);
    });

    it('train 后桶应清空', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: `type-${i % 3}` });
      }
      loop.train();
      expect(loop.bucketCount).toBe(0);
    });

    it('训练权重应反映 intent_type 频率分布', () => {
      const loop = new IntentTrainingLoop();
      // 40 条 code_inspection + 10 条 research
      for (let i = 0; i < 40; i++) {
        loop.addTrainingData({ message: `检查代码${i}`, intent_type: 'code_inspection' });
      }
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({ message: `调研方案${i}`, intent_type: 'research' });
      }
      const result = loop.train();
      // code_inspection 权重应高于 research
      expect(result.weights['code_inspection']).toBeGreaterThan(result.weights['research']);
    });

    it('训练结果应包含 bucket_threshold 字段', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' });
      }
      const result = loop.train();
      expect(result.bucket_threshold).toBe(50);
    });

    it('训练结果应包含 timestamp 字段', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' });
      }
      const before = Date.now();
      const result = loop.train();
      expect(result.timestamp).toBeGreaterThanOrEqual(before);
    });
  });

  // ----------------------------------------------------------
  // 4. 自定义桶满阈值
  // ----------------------------------------------------------
  describe('自定义桶满阈值', () => {
    it('应支持自定义桶满阈值', () => {
      const loop = new IntentTrainingLoop({ bucketThreshold: 10 });
      expect(loop.bucketThreshold).toBe(10);
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' });
      }
      expect(loop.shouldTrain()).toBe(true);
    });
  });
});
