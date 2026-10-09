/**
 * SPEC-20261009 §4.2.4 P1-6: G层 GraphStructureTrainingLoop 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - GraphStructureTrainingLoop 类存在性 + 可实例化
 *   - 桶满阈值=60（SPEC v0.3 G层差异化）
 *   - addTrainingData / shouldTrain / train / clear
 *   - 训练结果包含 graph_coverage + node_count + edge_count + compression_ratio
 *   - FAIL-OPEN：空桶训练返回 not trained
 */

import { GraphStructureTrainingLoop, type GraphTrainingData, type GraphTrainingResult } from '../g-graph-training-loop';

describe('SPEC §4.2.4 P1-6: G层 GraphStructureTrainingLoop', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('GraphStructureTrainingLoop 类应可导入且可实例化', () => {
      const loop = new GraphStructureTrainingLoop();
      expect(loop).toBeInstanceOf(GraphStructureTrainingLoop);
    });

    it('桶满阈值应为 60（SPEC v0.3 G层差异化）', () => {
      const loop = new GraphStructureTrainingLoop();
      expect(loop.bucketThreshold).toBe(60);
    });
  });

  // ----------------------------------------------------------
  // 2. 训练数据管理
  // ----------------------------------------------------------
  describe('训练数据管理', () => {
    it('addTrainingData 应添加数据到桶', () => {
      const loop = new GraphStructureTrainingLoop();
      loop.addTrainingData({
        decisions: ['采用TDD开发'],
        rules: ['测试先行'],
      });
      expect(loop.bucketCount).toBe(1);
    });

    it('shouldTrain: 桶未满应返回 false', () => {
      const loop = new GraphStructureTrainingLoop();
      loop.addTrainingData({ decisions: ['test'], rules: [] });
      expect(loop.shouldTrain()).toBe(false);
    });

    it('shouldTrain: 桶满60应返回 true', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({ decisions: [`决策-${i}`], rules: [`规则-${i}`] });
      }
      expect(loop.shouldTrain()).toBe(true);
    });

    it('clear 应清空桶', () => {
      const loop = new GraphStructureTrainingLoop();
      loop.addTrainingData({ decisions: ['test'], rules: [] });
      loop.clear();
      expect(loop.bucketCount).toBe(0);
    });
  });

  // ----------------------------------------------------------
  // 3. 训练执行
  // ----------------------------------------------------------
  describe('训练执行', () => {
    it('空桶 train 应返回 trained=false', () => {
      const loop = new GraphStructureTrainingLoop();
      const result = loop.train();
      expect(result.trained).toBe(false);
    });

    it('桶满 train 应返回 trained=true + graph_coverage + node_count + edge_count', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({
          decisions: [`采用TDD开发模式${i}`],
          rules: [`测试先行规则${i}`],
        });
      }
      const result = loop.train();
      expect(result.trained).toBe(true);
      expect(result.graph_coverage).toBeGreaterThanOrEqual(0);
      expect(result.graph_coverage).toBeLessThanOrEqual(1);
      expect(result.node_count).toBeGreaterThan(0);
      expect(result.edge_count).toBeGreaterThanOrEqual(0);
    });

    it('train 后桶应清空', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({ decisions: [`决策-${i}`], rules: [`规则-${i}`] });
      }
      loop.train();
      expect(loop.bucketCount).toBe(0);
    });

    it('训练结果应包含 compression_ratio 字段', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({ decisions: [`决策-${i}`], rules: [`规则-${i}`] });
      }
      const result = loop.train();
      expect(result.compression_ratio).toBeGreaterThanOrEqual(0);
      expect(result.compression_ratio).toBeLessThanOrEqual(1);
    });

    it('训练结果应包含 bucket_threshold 字段', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({ decisions: [`d-${i}`], rules: [`r-${i}`] });
      }
      const result = loop.train();
      expect(result.bucket_threshold).toBe(60);
    });

    it('训练结果应包含 timestamp 字段', () => {
      const loop = new GraphStructureTrainingLoop();
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({ decisions: [`d-${i}`], rules: [`r-${i}`] });
      }
      const before = Date.now();
      const result = loop.train();
      expect(result.timestamp).toBeGreaterThanOrEqual(before);
    });

    it('节点数应反映决策数量', () => {
      const loop = new GraphStructureTrainingLoop();
      const decisions = ['TDD', 'CI/CD', '代码审查'];
      for (let i = 0; i < 60; i++) {
        loop.addTrainingData({
          decisions: [decisions[i % 3]],
          rules: [`规则-${i % 3}`],
        });
      }
      const result = loop.train();
      // 3 个唯一决策 → 至少 3 个节点
      expect(result.node_count).toBeGreaterThanOrEqual(3);
    });
  });

  // ----------------------------------------------------------
  // 4. 自定义桶满阈值
  // ----------------------------------------------------------
  describe('自定义桶满阈值', () => {
    it('应支持自定义桶满阈值', () => {
      const loop = new GraphStructureTrainingLoop({ bucketThreshold: 10 });
      expect(loop.bucketThreshold).toBe(10);
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({ decisions: [`d-${i}`], rules: [`r-${i}`] });
      }
      expect(loop.shouldTrain()).toBe(true);
    });
  });
});
