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

    it('clear 应重置模型状态（v0.5: 不清空 buffer）', () => {
      const loop = new IntentTrainingLoop();
      loop.addTrainingData({ message: 'test', intent_type: 'test' });
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

    it('train 后 buffer 不清空（v0.5: 持续训练，不清空）', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: `type-${i % 3}` });
      }
      loop.train();
      // v0.5: buffer 永不清空，只做衰减
      expect(loop.bucketCount).toBe(50);
    });

    it('train 后应返回 incrementalStep + bufferStats（v0.5）', () => {
      const loop = new IntentTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' });
      }
      const result = loop.train();
      expect(result.incrementalStep).toBeGreaterThan(0);
      expect(result.bufferStats).toBeDefined();
      expect(result.bufferStats?.size).toBe(50);
      expect(result.bufferStats?.capacity).toBe(200);
    });
  });

  // ----------------------------------------------------------
  // 3.5 v0.5: trainIncremental 增量训练
  // ----------------------------------------------------------
  describe('v0.5: trainIncremental 增量训练', () => {
    it('trainIncremental 应增量更新模型，不清空 buffer', () => {
      const loop = new IntentTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: `type-${i % 2}` }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      const result = loop.trainIncremental(batch);
      expect(result.trained).toBe(true);
      expect(result.incrementalStep).toBe(1);
      expect(loop.bucketCount).toBe(3);
      expect(loop.step).toBe(1);
    });

    it('trainIncremental 多次训练应递增 step', () => {
      const loop = new IntentTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' }, 'B');
      }
      for (let i = 0; i < 3; i++) {
        const batch = loop.replayBuffer.sample(3).map(e => e.data);
        loop.trainIncremental(batch);
      }
      expect(loop.step).toBe(3);
    });

    it('trainIncremental 后模型状态应保留', () => {
      const loop = new IntentTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ message: `检查代码${i}`, intent_type: 'code_inspection' }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      expect(snapshot.step).toBe(1);
      expect(snapshot.intentFreq['code_inspection']).toBeGreaterThan(0);
      expect(snapshot.weights['code_inspection']).toBeGreaterThan(0);
    });

    it('getModelSnapshot / restoreModel 应可保存恢复', () => {
      const loop = new IntentTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ message: `msg-${i}`, intent_type: 'test' }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);

      const snapshot = loop.getModelSnapshot();
      const loop2 = new IntentTrainingLoop();
      loop2.restoreModel(snapshot);

      expect(loop2.step).toBe(1);
      expect(loop2.getModelSnapshot().intentFreq).toEqual(snapshot.intentFreq);
    });

    it('addTrainingData 支持 quality 参数', () => {
      const loop = new IntentTrainingLoop();
      loop.addTrainingData({ message: 'S级', intent_type: 'test' }, 'S');
      loop.addTrainingData({ message: 'C级', intent_type: 'test' }, 'C');
      const stats = loop.getBufferStats();
      expect(stats.qualityDistribution.S).toBe(1);
      expect(stats.qualityDistribution.C).toBe(1);
    });
  });

  // ----------------------------------------------------------
  // 4. 训练质量验证
  // ----------------------------------------------------------
  describe('训练质量验证', () => {
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
