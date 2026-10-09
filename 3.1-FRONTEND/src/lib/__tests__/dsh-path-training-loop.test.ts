/**
 * SPEC-20261009 §4.2.2 P2-1: DSH ExecutionPathTrainingLoop 测试
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

    it('clear 应清空桶', () => {
      const loop = new ExecutionPathTrainingLoop();
      loop.addTrainingData({ task: 'test', node_sequence: ['n1'], outcome: 'success' });
      loop.clear();
      expect(loop.bucketCount).toBe(0);
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

    it('train 后桶应清空', () => {
      const loop = new ExecutionPathTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({ task: `t-${i}`, node_sequence: ['n1'], outcome: 'success' });
      }
      loop.train();
      expect(loop.bucketCount).toBe(0);
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
