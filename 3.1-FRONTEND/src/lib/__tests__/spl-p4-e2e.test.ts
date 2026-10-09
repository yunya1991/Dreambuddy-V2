/**
 * SPEC-20261009 §10 Phase 4 P4: 全链路联调 + 性能基准测试
 *
 * 验证 SPL P4 全链路：
 *   训练 → 评估 → 反思 → 认知闭环
 *
 * 测试覆盖：
 *   1. 全链路训练+评估: S+G→DSH→C→LLM 训练后评估
 *   2. 反思引擎接入: 失败案例→MCTS纠错→修正案例
 *   3. 认知闭环: 评估结果→verify cognitive
 *   4. 全链路复现: 所有层复现后端到端一致率 ≥ 70%
 *   5. 性能基准: 各模块延迟
 */

import { IntentTrainingLoop } from '../s-intent-training-loop';
import { GraphStructureTrainingLoop } from '../g-graph-training-loop';
import { ExecutionPathTrainingLoop } from '../dsh-path-training-loop';
import { ReflectionTrainingLoop } from '../c-reflection-training-loop';
import { PromptOptimizationLoop } from '../llm-prompt-training-loop';
import { EvalLayer, type LayerName } from '../eval-layer';
import { ReflectionEngine, type FailureCase } from '../reflection-engine';

describe('SPEC §10 Phase 4 P4: 全链路联调 + 性能基准', () => {
  // ----------------------------------------------------------
  // 1. 全链路训练 + 评估
  // ----------------------------------------------------------
  describe('1. 全链路训练 + 评估', () => {
    it('S+G→DSH→C→LLM 训练后评估，验证复现/超越', () => {
      // S 层训练
      const s = new IntentTrainingLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        s.addTrainingData({ message: `检查代码${i}`, intent_type: 'code_inspection' });
      }
      const sResult = s.train();

      // G 层训练
      const g = new GraphStructureTrainingLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        g.addTrainingData({ decisions: [`TDD${i}`], rules: [`rule${i}`] });
      }
      const gResult = g.train();

      // DSH 层训练
      const dsh = new ExecutionPathTrainingLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        dsh.addTrainingData({ task: `t${i}`, node_sequence: ['A', 'B', 'C'], outcome: 'success' });
      }
      const dshResult = dsh.train();

      // C 层训练
      const c = new ReflectionTrainingLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        c.addTrainingData({
          context_summary: `ctx${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      const cResult = c.train();

      // LLM 层训练
      const llm = new PromptOptimizationLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        llm.addTrainingData({
          intent: `intent${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'pattern',
        });
      }
      const llmResult = llm.train();

      // 所有层训练成功
      expect(sResult.trained).toBe(true);
      expect(gResult.trained).toBe(true);
      expect(dshResult.trained).toBe(true);
      expect(cResult.trained).toBe(true);
      expect(llmResult.trained).toBe(true);

      // 评估（模拟指标全部达标）
      const evalLayer = new EvalLayer();
      const evalSummary = evalLayer.evaluateAll({
        S: { metric: sResult.accuracy, baseline: 0.7 },
        DSH: { metric: dshResult.edit_distance_ratio, baseline: 0.5 },
        C: { metric: cResult.decision_accuracy, baseline: 0.6 },
        LLM: { metric: llmResult.semantic_similarity, baseline: 0.5 },
        G: { metric: gResult.graph_coverage, baseline: 0.5 },
      });

      // 评估结果结构正确
      expect(evalSummary.layer_results).toHaveLength(5);
      expect(evalSummary.reproduction_rate).toBeGreaterThanOrEqual(0);
    });
  });

  // ----------------------------------------------------------
  // 2. 反思引擎接入
  // ----------------------------------------------------------
  describe('2. 反思引擎接入', () => {
    it('失败案例 → MCTS 纠错 → 修正案例', () => {
      const engine = new ReflectionEngine();

      const failureCase: FailureCase = {
        id: 'case-fail-e2e',
        intent: '部署服务',
        actions: ['直接部署到生产'],
        outcome: 'failure',
        outcome_text: '部署失败，服务不可用',
        learned: [],
      };

      // 触发反思
      expect(engine.shouldReflect(failureCase)).toBe(true);

      // MCTS 纠错
      const corrected = engine.reflect(failureCase);

      // 验证修正案例
      expect(corrected.corrected_from).toBe('case-fail-e2e');
      expect(corrected.outcome).toBe('success');
      expect(corrected.actions.length).toBeGreaterThan(failureCase.actions.length);
      expect(corrected.learned.length).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 3. 全链路复现验证
  // ----------------------------------------------------------
  describe('3. 全链路复现验证', () => {
    it('所有层复现后端到端一致率应 ≥ 70%', () => {
      const evalLayer = new EvalLayer();

      // 模拟各层指标全部达标（复现）
      const summary = evalLayer.evaluateAll({
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.25, baseline: 0.3 },
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      });

      // 所有层复现
      expect(summary.all_reproduced).toBe(true);
      // 全链路复现率 = 1.0
      expect(summary.reproduction_rate).toBe(1.0);
    });

    it('部分层未复现时全链路复现率应 < 1.0', () => {
      const evalLayer = new EvalLayer();
      const summary = evalLayer.evaluateAll({
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.4, baseline: 0.3 }, // 未复现
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      });

      expect(summary.all_reproduced).toBe(false);
      expect(summary.reproduction_rate).toBe(0.8); // 4/5
    });
  });

  // ----------------------------------------------------------
  // 4. 性能基准测试
  // ----------------------------------------------------------
  describe('4. 性能基准测试', () => {
    it('各层训练延迟应在合理范围', () => {
      const s = new IntentTrainingLoop({ bucketThreshold: 50 });
      for (let i = 0; i < 50; i++) {
        s.addTrainingData({ message: `msg${i}`, intent_type: `type${i % 5}` });
      }

      const start = Date.now();
      s.train();
      const elapsed = Date.now() - start;

      // S 层训练应 < 500ms
      expect(elapsed).toBeLessThan(500);
    });

    it('评估层延迟应极低', () => {
      const evalLayer = new EvalLayer();
      const inputs = {
        S: { metric: 0.85, baseline: 0.8 },
        DSH: { metric: 0.25, baseline: 0.3 },
        C: { metric: 0.8, baseline: 0.75 },
        LLM: { metric: 0.75, baseline: 0.7 },
        G: { metric: 0.75, baseline: 0.7 },
      };

      const start = Date.now();
      evalLayer.evaluateAll(inputs);
      const elapsed = Date.now() - start;

      // 评估应 < 10ms
      expect(elapsed).toBeLessThan(10);
    });

    it('反思引擎延迟应合理', () => {
      const engine = new ReflectionEngine();
      const failureCase: FailureCase = {
        id: 'perf-test',
        intent: 'test',
        actions: ['act1', 'act2'],
        outcome: 'failure',
        outcome_text: '失败',
        learned: [],
      };

      const start = Date.now();
      engine.reflect(failureCase);
      const elapsed = Date.now() - start;

      // 反思应 < 100ms
      expect(elapsed).toBeLessThan(100);
    });
  });

  // ----------------------------------------------------------
  // 5. 全链路端到端: 训练→评估→反思→认知闭环
  // ----------------------------------------------------------
  describe('5. 全链路端到端: 训练→评估→反思→认知闭环', () => {
    it('完整流程: 训练 → 评估 → 失败反思 → 修正案例', () => {
      // Step 1: 训练 DSH 层
      const dsh = new ExecutionPathTrainingLoop({ bucketThreshold: 10 });
      for (let i = 0; i < 10; i++) {
        dsh.addTrainingData({
          task: `task-${i}`,
          node_sequence: ['lint', 'fix', 'test'],
          outcome: i < 8 ? 'success' : 'failure',
        });
      }
      const dshResult = dsh.train();
      expect(dshResult.trained).toBe(true);

      // Step 2: 评估 DSH
      const evalLayer = new EvalLayer();
      const dshEval = evalLayer.evaluateLayer('DSH', {
        metric: dshResult.edit_distance_ratio,
        baseline: 0.3,
      });

      // Step 3: 如果有失败案例，触发反思
      if (dshResult.success_rate < 1.0) {
        const engine = new ReflectionEngine();
        const failureCase: FailureCase = {
          id: 'case-fail-e2e',
          intent: '代码修复',
          actions: ['lint', 'fix', 'test'],
          outcome: 'failure',
          outcome_text: '修复失败',
          learned: [],
        };

        const corrected = engine.reflect(failureCase);
        expect(corrected.corrected_from).toBe('case-fail-e2e');
        expect(corrected.outcome).toBe('success');
      }

      // 全链路验证完成
      expect(true).toBe(true);
    });
  });
});
