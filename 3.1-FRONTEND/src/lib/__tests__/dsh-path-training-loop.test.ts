/**
 * SPEC-20261009 §4.2.2 P2-1: DSH ExecutionPathTrainingLoop 测试
 * SPEC-20261011 v0.5: ReplayBuffer + trainIncremental
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - ExecutionPathTrainingLoop 类存在性 + 可实例化
 *   - 桶满阈值=50（SPEC v0.3 DSH差异化）
 *   - addTrainingData / shouldTrain / train / clear
 *   - 训练结果包含 path_templates + avg_path_length + success_rate + edit_distance_ratio
 *   - 序列模式挖掘：频繁项集→路径模板
 *   - 成功率加权：success 路径权重↑
 *   - v0.5: trainIncremental + getModelSnapshot / restoreModel
 */

import { ExecutionPathTrainingLoop, type PathTrainingData, type PathTrainingResult } from '../dsh-path-training-loop';

describe('SPEC §4.2.2 P2-1: DSH ExecutionPathTrainingLoop', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('ExecutionPathTrainingLoop 类应可导入且可实例化', () => {
      const loop = new ExecutionPathTrainingLoop();
      expect(loop).toBeInstanceOf(ExecutionPathTrainingLoop);
    });

    it('桶满阈值应为 50（SPEC v0.3 DSH差异化）', () => {
      const loop = new ExecutionPathTrainingLoop();
      expect(loop.bucketThreshold).toBe(50);
    });
  });

  // ----------------------------------------------------------
  // 2. 训练数据管理
  // ----------------------------------------------------------
  describe('训练数据管理', () => {
    it('addTrainingData 应添加数据到桶', () => {
      const loop = new ExecutionPathTrainingLoop();
      loop.addTrainingData({ task: '检查架构', node_sequence: ['n1', 'n2'], outcome: 'success' });
      expect(loop.bucketCount).toBe(1);
    });

    it('shouldTrain: 桶未满应返回 false', () => {
      const loop = new ExecutionPathTrainingLoop();
      loop.addTrainingData({ task: 'test', node_sequence: ['n1'], outcome: 'success' });
      expect(loop.shouldTrain()).toBe(false);
    });

    it('shouldTrain: 桶满50应返回 true', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ task: `task-${i}`, node_sequence: ['n1', 'n2'], outcome: 'success' });
      }
      expect(loop.shouldTrain()).toBe(true);
    });

    it('clear 只重置模型状态，不清空 buffer（v0.5）', () => {
      const loop = new ExecutionPathTrainingLoop();
      loop.addTrainingData({ task: 'test', node_sequence: ['n1'], outcome: 'success' });
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
      const loop = new ExecutionPathTrainingLoop();
      const result = loop.train();
      expect(result.trained).toBe(false);
    });

    it('桶满 train 应返回 trained=true + path_templates', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          task: `检查代码${i}`,
          node_sequence: ['code_inspection', 'lint', 'fix'],
          outcome: 'success',
        });
      }
      const result = loop.train();
      expect(result.trained).toBe(true);
      expect(result.path_templates).toBeDefined();
      expect(result.path_templates.length).toBeGreaterThan(0);
    });

    it('train 后 buffer 不清空（v0.5: 持续训练，不清空）', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' });
      }
      loop.train();
      // v0.5: buffer 永不清空，只做衰减
      expect(loop.bucketCount).toBe(50);
    });

    it('train 后应返回 incrementalStep + bufferStats（v0.5）', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' });
      }
      const result = loop.train();
      expect(result.incrementalStep).toBeGreaterThan(0);
      expect(result.bufferStats).toBeDefined();
      expect(result.bufferStats?.size).toBe(50);
      expect(result.bufferStats?.capacity).toBe(300);
    });

    it('成功率加权: success 路径权重应高于 failure', () => {
      const loop = new ExecutionPathTrainingLoop();
      // 25 success + 25 failure，相同路径
      for (let i = 0; i < 25; i++) {
        loop.addTrainingData({
          task: `task-s-${i}`,
          node_sequence: ['n1', 'n2', 'n3'],
          outcome: 'success',
        });
      }
      for (let i = 0; i < 25; i++) {
        loop.addTrainingData({
          task: `task-f-${i}`,
          node_sequence: ['n1', 'n2', 'n3'],
          outcome: 'failure',
        });
      }
      const result = loop.train();
      expect(result.success_rate).toBeGreaterThan(0.4); // 25/50=0.5
      expect(result.success_rate).toBeLessThanOrEqual(1.0);
    });

    it('序列模式挖掘: 频繁出现的路径应成为模板', () => {
      const loop = new ExecutionPathTrainingLoop();
      // 频繁路径 A→B→C 出现 40 次
      for (let i = 0; i < 40; i++) {
        loop.addTrainingData({
          task: `task-a-${i}`,
          node_sequence: ['A', 'B', 'C'],
          outcome: 'success',
        });
      }
      // 其他路径 10 次
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({
          task: `task-b-${i}`,
          node_sequence: ['X', 'Y'],
          outcome: 'failure',
        });
      }
      const result = loop.train();
      // A→B→C 应成为高频模板
      const abcTemplate = result.path_templates.find(t => t.path.join('→') === 'A→B→C');
      expect(abcTemplate).toBeDefined();
      expect(abcTemplate!.count).toBeGreaterThanOrEqual(40);
    });

    it('训练结果应包含 avg_path_length 字段', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          task: `t-${i}`,
          node_sequence: ['n1', 'n2', 'n3'],
          outcome: 'success',
        });
      }
      const result = loop.train();
      expect(result.avg_path_length).toBeCloseTo(3, 0);
    });

    it('训练结果应包含 edit_distance_ratio 字段', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          task: `t-${i}`,
          node_sequence: ['n1', 'n2', 'n3'],
          outcome: 'success',
        });
      }
      const result = loop.train();
      expect(result.edit_distance_ratio).toBeGreaterThanOrEqual(0);
      expect(result.edit_distance_ratio).toBeLessThanOrEqual(1);
    });

    it('训练结果应包含 bucket_threshold + timestamp', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' });
      }
      const result = loop.train();
      expect(result.bucket_threshold).toBe(50);
      expect(result.timestamp).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 3.5 v0.5: trainIncremental 增量训练
  // ----------------------------------------------------------
  describe('v0.5: trainIncremental 增量训练', () => {
    it('trainIncremental 应增量更新模型，不清空 buffer', () => {
      const loop = new ExecutionPathTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1', 'n2'], outcome: 'success' }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      const result = loop.trainIncremental(batch);
      expect(result.trained).toBe(true);
      expect(result.incrementalStep).toBe(1);
      expect(loop.bucketCount).toBe(3);
      expect(loop.step).toBe(1);
    });

    it('trainIncremental 多次训练应递增 step', () => {
      const loop = new ExecutionPathTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' }, 'B');
      }
      for (let i = 0; i < 3; i++) {
        const batch = loop.replayBuffer.sample(3).map(e => e.data);
        loop.trainIncremental(batch);
      }
      expect(loop.step).toBe(3);
    });

    it('trainIncremental 后模型状态应保留', () => {
      const loop = new ExecutionPathTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          task: `t-${i}`,
          node_sequence: ['A', 'B', 'C'],
          outcome: 'success',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      expect(snapshot.step).toBe(1);
      expect(snapshot.pathTemplates.length).toBeGreaterThan(0);
      expect(snapshot.pathFreq['A→B→C']).toBeGreaterThan(0);
    });

    it('getModelSnapshot / restoreModel 应可保存恢复', () => {
      const loop = new ExecutionPathTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          task: `t-${i}`,
          node_sequence: ['n1', 'n2'],
          outcome: 'success',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);

      const snapshot = loop.getModelSnapshot();
      const loop2 = new ExecutionPathTrainingLoop();
      loop2.restoreModel(snapshot);

      expect(loop2.step).toBe(1);
      expect(loop2.getModelSnapshot().pathTemplates).toEqual(snapshot.pathTemplates);
    });

    it('addTrainingData 支持 quality 参数', () => {
      const loop = new ExecutionPathTrainingLoop();
      loop.addTrainingData({ task: 'S级', node_sequence: ['n1'], outcome: 'success' }, 'S');
      loop.addTrainingData({ task: 'C级', node_sequence: ['n1'], outcome: 'success' }, 'C');
      const stats = loop.getBufferStats();
      expect(stats.qualityDistribution.S).toBe(1);
      expect(stats.qualityDistribution.C).toBe(1);
    });
  });

  // ----------------------------------------------------------
  // 4. 自定义桶满阈值
  // ----------------------------------------------------------
  describe('自定义桶满阈值', () => {
    it('应支持自定义桶满阈值', () => {
      const loop = new ExecutionPathTrainingLoop({ bucketThreshold: 10 });
      expect(loop.bucketThreshold).toBe(10);
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' });
      }
      expect(loop.shouldTrain()).toBe(true);
    });
  });
});
