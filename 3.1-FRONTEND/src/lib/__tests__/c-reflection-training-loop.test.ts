/**
 * SPEC-20261009 §4.2.3 P2-2: C层 ReflectionTrainingLoop 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - ReflectionTrainingLoop 类存在性 + 可实例化
 *   - 桶满阈值=50（SPEC v0.3 C层差异化）
 *   - 5种反射决策: CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE
 *   - CBR 案例检索 + 决策规则蒸馏 + MCTS 纠错
 *   - 训练结果包含 decision_rules + decision_accuracy + correction_count
 */

import { ReflectionTrainingLoop, type ReflectionTrainingData, type ReflectionDecision, type ReflectionTrainingResult } from '../c-reflection-training-loop';

describe('SPEC §4.2.3 P2-2: C层 ReflectionTrainingLoop', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('ReflectionTrainingLoop 类应可导入且可实例化', () => {
      const loop = new ReflectionTrainingLoop();
      expect(loop).toBeInstanceOf(ReflectionTrainingLoop);
    });

    it('桶满阈值应为 50（SPEC v0.3 C层差异化）', () => {
      const loop = new ReflectionTrainingLoop();
      expect(loop.bucketThreshold).toBe(50);
    });

    it('应支持5种反射决策类型', () => {
      const decisions: ReflectionDecision[] = ['CONTINUE', 'REDO', 'INSERT_BEFORE', 'JUMP_TO', 'EARLY_TERMINATE'];
      expect(decisions).toHaveLength(5);
    });
  });

  // ----------------------------------------------------------
  // 2. 训练数据管理
  // ----------------------------------------------------------
  describe('训练数据管理', () => {
    it('addTrainingData 应添加数据到桶', () => {
      const loop = new ReflectionTrainingLoop();
      loop.addTrainingData({
        context_summary: '代码审查中发现问题',
        action_taken: '修复',
        outcome: 'success',
        expected_decision: 'CONTINUE',
      });
      expect(loop.bucketCount).toBe(1);
    });

    it('shouldTrain: 桶未满应返回 false', () => {
      const loop = new ReflectionTrainingLoop();
      loop.addTrainingData({
        context_summary: 'test',
        action_taken: 'test',
        outcome: 'success',
        expected_decision: 'CONTINUE',
      });
      expect(loop.shouldTrain()).toBe(false);
    });

    it('shouldTrain: 桶满50应返回 true', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      expect(loop.shouldTrain()).toBe(true);
    });

    it('clear 应清空桶', () => {
      const loop = new ReflectionTrainingLoop();
      loop.addTrainingData({
        context_summary: 'test',
        action_taken: 'test',
        outcome: 'success',
        expected_decision: 'CONTINUE',
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
      const loop = new ReflectionTrainingLoop();
      const result = loop.train();
      expect(result.trained).toBe(false);
    });

    it('桶满 train 应返回 trained=true + decision_rules', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `检查发现问题${i}`,
          action_taken: '修复',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      const result = loop.train();
      expect(result.trained).toBe(true);
      expect(result.decision_rules).toBeDefined();
      expect(Object.keys(result.decision_rules).length).toBeGreaterThan(0);
    });

    it('train 后桶应清空', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      loop.train();
      expect(loop.bucketCount).toBe(0);
    });

    it('决策规则蒸馏: 频繁模式应生成规则', () => {
      const loop = new ReflectionTrainingLoop();
      // 40 条 CONTINUE（success），10 条 REDO（failure）
      for (let i = 0; i < 40; i++) {
        loop.addTrainingData({
          context_summary: `检查通过${i}`,
          action_taken: '验证',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({
          context_summary: `检查失败${i}`,
          action_taken: '回滚',
          outcome: 'failure',
          expected_decision: 'REDO',
        });
      }
      const result = loop.train();
      // CONTINUE 规则应有更高权重
      expect(result.decision_rules['CONTINUE']).toBeGreaterThan(result.decision_rules['REDO']);
    });

    it('MCTS 纠错: 失败案例应触发纠正决策', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `失败场景${i}`,
          action_taken: '错误操作',
          outcome: 'failure',
          expected_decision: 'EARLY_TERMINATE',
        });
      }
      const result = loop.train();
      expect(result.correction_count).toBeGreaterThan(0);
      expect(result.decision_rules['EARLY_TERMINATE']).toBeGreaterThan(0);
    });

    it('训练结果应包含 decision_accuracy 字段', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      const result = loop.train();
      expect(result.decision_accuracy).toBeGreaterThanOrEqual(0);
      expect(result.decision_accuracy).toBeLessThanOrEqual(1);
    });

    it('训练结果应包含 correction_count 字段', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      const result = loop.train();
      expect(result.correction_count).toBeGreaterThanOrEqual(0);
    });

    it('训练结果应包含 bucket_threshold + timestamp', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 50; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
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
      const loop = new ReflectionTrainingLoop({ bucketThreshold: 10 });
      expect(loop.bucketThreshold).toBe(10);
      for (let i = 0; i < 10; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      expect(loop.shouldTrain()).toBe(true);
    });
  });
});
