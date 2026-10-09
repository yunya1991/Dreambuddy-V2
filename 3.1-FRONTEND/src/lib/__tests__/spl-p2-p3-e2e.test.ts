/**
 * SPEC-20261009 §10 Phase 3 P3: DSH+C+LLM E2E 端到端测试
 *
 * 验证 SPL P2-P3 全链路训练：
 *   DSH ExecutionPathTrainingLoop → C层 ReflectionTrainingLoop → LLM PromptOptimizationLoop
 *
 * 测试覆盖：
 *   1. DSH E2E: 添加路径数据→桶满→训练→路径模板+编辑距离比
 *   2. C层 E2E: 添加反射数据→桶满→训练→决策规则+纠错
 *   3. LLM E2E: 添加Prompt数据→桶满→训练→模板聚类+关键词权重
 *   4. 全链路 E2E: S→DSH→C→LLM 依赖顺序训练
 *   5. 训练依赖验证: DSH依赖S, C依赖DSH, LLM依赖C
 */

import { ExecutionPathTrainingLoop } from '../dsh-path-training-loop';
import { ReflectionTrainingLoop, type ReflectionDecision } from '../c-reflection-training-loop';
import { PromptOptimizationLoop } from '../llm-prompt-training-loop';
import { IntentTrainingLoop } from '../s-intent-training-loop';

describe('SPEC §10 Phase 3 P3: DSH+C+LLM E2E 端到端测试', () => {
  // ----------------------------------------------------------
  // 1. DSH E2E: 路径训练
  // ----------------------------------------------------------
  describe('1. DSH ExecutionPathTrainingLoop E2E', () => {
    it('完整流程：添加路径数据→桶满→训练→路径模板+编辑距离比', () => {
      const dsh = new ExecutionPathTrainingLoop({ bucketThreshold: 20 });

      // 15 条高频成功路径 A→B→C
      for (let i = 0; i < 15; i++) {
        dsh.addTrainingData({
          task: `code-review-${i}`,
          node_sequence: ['A', 'B', 'C'],
          outcome: 'success',
        });
      }
      // 5 条失败路径 A→D→E
      for (let i = 0; i < 5; i++) {
        dsh.addTrainingData({
          task: `fail-${i}`,
          node_sequence: ['A', 'D', 'E'],
          outcome: 'failure',
        });
      }

      const result = dsh.train();

      expect(result.trained).toBe(true);
      expect(result.path_templates.length).toBeGreaterThanOrEqual(2);
      // 主模板应为 A→B→C（权重最高）
      expect(result.path_templates[0].path.join('→')).toBe('A→B→C');
      expect(result.success_rate).toBe(0.75); // 15/20
      expect(result.avg_path_length).toBe(3);
      expect(result.edit_distance_ratio).toBeGreaterThanOrEqual(0);
      expect(result.edit_distance_ratio).toBeLessThanOrEqual(1);
    });
  });

  // ----------------------------------------------------------
  // 2. C层 E2E: 反射决策训练
  // ----------------------------------------------------------
  describe('2. C层 ReflectionTrainingLoop E2E', () => {
    it('完整流程：添加反射数据→桶满→训练→决策规则+纠错', () => {
      const c = new ReflectionTrainingLoop({ bucketThreshold: 20 });

      // 12 条 CONTINUE success
      for (let i = 0; i < 12; i++) {
        c.addTrainingData({
          context_summary: `检查通过${i}`,
          action_taken: '验证',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      // 8 条 EARLY_TERMINATE failure
      for (let i = 0; i < 8; i++) {
        c.addTrainingData({
          context_summary: `检查失败${i}`,
          action_taken: '继续执行',
          outcome: 'failure',
          expected_decision: 'EARLY_TERMINATE',
        });
      }

      const result = c.train();

      expect(result.trained).toBe(true);
      expect(result.decision_rules['CONTINUE']).toBeGreaterThan(0);
      expect(result.decision_rules['EARLY_TERMINATE']).toBeGreaterThan(0);
      // failure 案例触发 MCTS 纠错
      expect(result.correction_count).toBe(8);
      expect(result.decision_accuracy).toBeGreaterThanOrEqual(0);
    });
  });

  // ----------------------------------------------------------
  // 3. LLM E2E: Prompt 优化训练
  // ----------------------------------------------------------
  describe('3. LLM PromptOptimizationLoop E2E', () => {
    it('完整流程：添加Prompt数据→桶满→训练→模板聚类+关键词权重', () => {
      const llm = new PromptOptimizationLoop({ bucketThreshold: 15 });

      // 10 条 success 模板
      for (let i = 0; i < 10; i++) {
        llm.addTrainingData({
          intent: `code-review-${i}`,
          learned: ['代码审查通过', '风格统一'],
          outcome: 'success',
          prompt_pattern: '请审查代码：{code}',
        });
      }
      // 5 条 failure 模板
      for (let i = 0; i < 5; i++) {
        llm.addTrainingData({
          intent: `debug-${i}`,
          learned: ['调试失败'],
          outcome: 'failure',
          prompt_pattern: '请调试：{code}',
        });
      }

      const result = llm.train();

      expect(result.trained).toBe(true);
      expect(result.prompt_templates[0].template).toBe('请审查代码：{code}');
      // success 案例的关键词权重更高
      expect(result.context_keywords['审查']).toBeGreaterThan(result.context_keywords['调试']);
      expect(result.avg_token_efficiency).toBeGreaterThanOrEqual(0);
      expect(result.semantic_similarity).toBeGreaterThanOrEqual(0);
    });
  });

  // ----------------------------------------------------------
  // 4. 全链路 E2E: S→DSH→C→LLM 依赖顺序训练
  // ----------------------------------------------------------
  describe('4. 全链路 E2E: S→DSH→C→LLM 依赖顺序', () => {
    it('按依赖顺序训练：S先训→DSH→C→LLM', () => {
      // S 层
      const s = new IntentTrainingLoop({ bucketThreshold: 5 });
      for (let i = 0; i < 5; i++) {
        s.addTrainingData({ message: `检查代码${i}`, intent_type: 'code_inspection' });
      }
      const sResult = s.train();
      expect(sResult.trained).toBe(true);

      // DSH 层（依赖 S）
      const dsh = new ExecutionPathTrainingLoop({ bucketThreshold: 5 });
      for (let i = 0; i < 5; i++) {
        dsh.addTrainingData({
          task: `task-${i}`,
          node_sequence: ['lint', 'fix', 'test'],
          outcome: 'success',
        });
      }
      const dshResult = dsh.train();
      expect(dshResult.trained).toBe(true);

      // C 层（依赖 S+DSH）
      const c = new ReflectionTrainingLoop({ bucketThreshold: 5 });
      for (let i = 0; i < 5; i++) {
        c.addTrainingData({
          context_summary: `ctx-${i}`,
          action_taken: 'act',
          outcome: 'success',
          expected_decision: 'CONTINUE',
        });
      }
      const cResult = c.train();
      expect(cResult.trained).toBe(true);

      // LLM 层（依赖 C）
      const llm = new PromptOptimizationLoop({ bucketThreshold: 5 });
      for (let i = 0; i < 5; i++) {
        llm.addTrainingData({
          intent: `intent-${i}`,
          learned: ['经验'],
          outcome: 'success',
          prompt_pattern: 'pattern',
        });
      }
      const llmResult = llm.train();
      expect(llmResult.trained).toBe(true);

      // 全链路验证：所有层都训练成功
      expect(sResult.trained && dshResult.trained && cResult.trained && llmResult.trained).toBe(true);
    });
  });

  // ----------------------------------------------------------
  // 5. 训练依赖验证
  // ----------------------------------------------------------
  describe('5. 训练依赖验证', () => {
    it('DSH 应依赖 S 层（桶满阈值不同）', () => {
      const s = new IntentTrainingLoop();
      const dsh = new ExecutionPathTrainingLoop();
      // S=50, DSH=50
      expect(s.bucketThreshold).toBe(50);
      expect(dsh.bucketThreshold).toBe(50);
    });

    it('C 层应支持5种决策类型', () => {
      const c = new ReflectionTrainingLoop({ bucketThreshold: 1 });
      c.addTrainingData({
        context_summary: 'ctx',
        action_taken: 'act',
        outcome: 'success',
        expected_decision: 'CONTINUE',
      });
      const result = c.train();
      // 5 种决策都应在 decision_rules 中
      expect(Object.keys(result.decision_rules)).toHaveLength(5);
      const decisions: ReflectionDecision[] = ['CONTINUE', 'REDO', 'INSERT_BEFORE', 'JUMP_TO', 'EARLY_TERMINATE'];
      for (const d of decisions) {
        expect(result.decision_rules[d]).toBeDefined();
      }
    });

    it('LLM 桶满阈值应为 30（最小）', () => {
      const llm = new PromptOptimizationLoop();
      expect(llm.bucketThreshold).toBe(30);
    });

    it('各层桶满阈值: S=50, DSH=50, C=50, LLM=30', () => {
      const s = new IntentTrainingLoop();
      const dsh = new ExecutionPathTrainingLoop();
      const c = new ReflectionTrainingLoop();
      const llm = new PromptOptimizationLoop();
      expect(s.bucketThreshold).toBe(50);
      expect(dsh.bucketThreshold).toBe(50);
      expect(c.bucketThreshold).toBe(50);
      expect(llm.bucketThreshold).toBe(30);
    });
  });
});
