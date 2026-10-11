/**
 * SPEC-20261009 §4.2.3 P2-2: C层 ReflectionTrainingLoop 测试
 * SPEC-20261011 v0.5: ReplayBuffer + trainIncremental
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - ReflectionTrainingLoop 类存在性 + 可实例化
 *   - 桶满阈值=50（SPEC v0.3 C层差异化）
 *   - 5种反射决策: CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE
 *   - CBR 案例检索 + 决策规则蒸馏 + MCTS 纠错
 *   - 训练结果包含 decision_rules + decision_accuracy + correction_count
 *   - v0.5: trainIncremental + getModelSnapshot / restoreModel
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

    it('clear 只重置模型状态，不清空 buffer（v0.5）', () => {
      const loop = new ReflectionTrainingLoop();
      loop.addTrainingData({
        context_summary: 'test',
        action_taken: 'test',
        outcome: 'success',
        expected_decision: 'CONTINUE',
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

    it('train 后 buffer 不清空（v0.5: 持续训练，不清空）', () => {
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
      // v0.5: buffer 永不清空，只做衰减
      expect(loop.bucketCount).toBe(50);
    });

    it('train 后应返回 incrementalStep + bufferStats（v0.5）', () => {
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
      expect(result.incrementalStep).toBeGreaterThan(0);
      expect(result.bufferStats).toBeDefined();
      expect(result.bufferStats?.size).toBe(50);
      expect(result.bufferStats?.capacity).toBe(200);
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
  // 3.5 v0.5: trainIncremental 增量训练
  // ----------------------------------------------------------
  describe('v0.5: trainIncremental 增量训练', () => {
    it('trainIncremental 应增量更新模型，不清空 buffer', () => {
      const loop = new ReflectionTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
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
      const loop = new ReflectionTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      for (let i = 0; i < 3; i++) {
        const batch = loop.replayBuffer.sample(3).map(e => e.data);
        loop.trainIncremental(batch);
      }
      expect(loop.step).toBe(3);
    });

    it('trainIncremental 后模型状态应保留', () => {
      const loop = new ReflectionTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      expect(snapshot.step).toBe(1);
      expect(snapshot.decisionCounts['CONTINUE']).toBeGreaterThan(0);
      expect(snapshot.decisionRules['CONTINUE']).toBeGreaterThan(0);
    });

    it('getModelSnapshot / restoreModel 应可保存恢复', () => {
      const loop = new ReflectionTrainingLoop();
      // v0.5 P1: 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);

      const snapshot = loop.getModelSnapshot();
      const loop2 = new ReflectionTrainingLoop();
      loop2.restoreModel(snapshot);

      expect(loop2.step).toBe(1);
      expect(loop2.getModelSnapshot().decisionCounts).toEqual(snapshot.decisionCounts);
    });

    it('addTrainingData 支持 quality 参数', () => {
      const loop = new ReflectionTrainingLoop();
      loop.addTrainingData({
        context_summary: 'S级',
        action_taken: 'act',
        outcome: 'success',
        expected_decision: 'CONTINUE',
      }, 'S');
      loop.addTrainingData({
        context_summary: 'C级',
        action_taken: 'act',
        outcome: 'success',
        expected_decision: 'CONTINUE',
      }, 'C');
      const stats = loop.getBufferStats();
      expect(stats.qualityDistribution.S).toBe(1);
      expect(stats.qualityDistribution.C).toBe(1);
    });
  });

  // ----------------------------------------------------------
  // 3.6 SPEC v0.5 P3.2: C 层规则权重衰减 + ruleArchive 保留阈值
  // ----------------------------------------------------------
  describe('SPEC v0.5 P3.2: 规则权重衰减 + ruleArchive', () => {
    it('P3.2: weight<0.05 的规则应移入 ruleArchive（不从系统删除）', () => {
      const loop = new ReflectionTrainingLoop();
      // 用 'B' 质量避免自动触发
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      // 只喂 CONTINUE 数据 → REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE 权重=0 < 0.05
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      // 4 个非 CONTINUE 决策应被归档
      expect(snapshot.ruleArchive.length).toBeGreaterThan(0);
      // CONTINUE 应有非零权重，未被归档
      expect(snapshot.decisionCounts['CONTINUE']).toBeGreaterThan(0);
      expect(snapshot.ruleArchive).not.toContain('CONTINUE');
    });

    it('P3.2: ruleArchive 在 getModelSnapshot / restoreModel 中应可保存恢复', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const snapshot = loop.getModelSnapshot();
      expect(snapshot.ruleArchive.length).toBeGreaterThan(0);

      const loop2 = new ReflectionTrainingLoop();
      loop2.restoreModel(snapshot);
      const restored = loop2.getModelSnapshot();
      expect(restored.ruleArchive).toEqual(snapshot.ruleArchive);
    });

    it('P3.2: 多次 trainIncremental 后旧规则权重应持续衰减', () => {
      const loop = new ReflectionTrainingLoop();
      for (let i = 0; i < 3; i++) {
        loop.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        }, 'B');
      }
      const batch = loop.replayBuffer.sample(3).map(e => e.data);
      loop.trainIncremental(batch);
      const weightsAfter1 = loop.getModelSnapshot().decisionCounts['CONTINUE'];
      for (let i = 0; i < 5; i++) {
        loop.trainIncremental(batch);
      }
      const weightsAfter6 = loop.getModelSnapshot().decisionCounts['CONTINUE'];
      // 5 次额外训练后 CONTINUE 权重应继续变化（EWMA 衰减 + 叠加）
      expect(weightsAfter6).not.toBe(weightsAfter1);
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
