/**
 * SPEC-20261009 §3.4 P4-2: Reflection Engine (MCTS 纠错) 测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - ReflectionEngine 类存在性 + 可实例化
 *   - 触发条件: failure/partial 或同类连续失败 ≥ 2 次
 *   - MCTS 纠错流程: 提取失败轨迹 → 搜索修正路径 → 生成修正案例
 *   - 异步执行: 不阻塞主链路
 *   - 修正案例标记 corrected_from 原案例 id
 */

import { ReflectionEngine, type FailureCase, type CorrectedCase } from '../reflection-engine';

describe('SPEC §3.4 P4-2: ReflectionEngine (MCTS 纠错)', () => {
  // ----------------------------------------------------------
  // 1. 模块存在性
  // ----------------------------------------------------------
  describe('模块存在性', () => {
    it('ReflectionEngine 类应可导入且可实例化', () => {
      const engine = new ReflectionEngine();
      expect(engine).toBeInstanceOf(ReflectionEngine);
    });

    it('连续失败阈值应为 2（SPEC §3.4）', () => {
      const engine = new ReflectionEngine();
      expect(engine.consecutiveFailureThreshold).toBe(2);
    });
  });

  // ----------------------------------------------------------
  // 2. 触发条件判定
  // ----------------------------------------------------------
  describe('触发条件判定', () => {
    it('outcome=failure → shouldReflect=true', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-1',
        intent: '检查架构',
        actions: ['检查', '修复'],
        outcome: 'failure',
        outcome_text: '修复失败',
        learned: ['错误方法'],
      };
      expect(engine.shouldReflect(caseData)).toBe(true);
    });

    it('outcome=partial → shouldReflect=true', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-2',
        intent: '检查架构',
        actions: ['检查'],
        outcome: 'partial',
        outcome_text: '部分完成',
        learned: ['未完整'],
      };
      expect(engine.shouldReflect(caseData)).toBe(true);
    });

    it('outcome=success → shouldReflect=false', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-3',
        intent: '检查架构',
        actions: ['检查', '修复'],
        outcome: 'success',
        outcome_text: '完成',
        learned: ['正确方法'],
      };
      expect(engine.shouldReflect(caseData)).toBe(false);
    });

    it('同类 pattern 连续失败 ≥ 2 次 → shouldReflect=true', () => {
      const engine = new ReflectionEngine();
      // 第一次失败
      engine.recordFailure('检查架构', 'case-1');
      // 第二次同类失败
      const caseData: FailureCase = {
        id: 'case-2',
        intent: '检查架构',
        actions: ['检查'],
        outcome: 'failure',
        outcome_text: '失败',
        learned: [],
      };
      expect(engine.shouldReflect(caseData)).toBe(true);
    });
  });

  // ----------------------------------------------------------
  // 3. MCTS 纠错
  // ----------------------------------------------------------
  describe('MCTS 纠错', () => {
    it('应生成修正案例，标记 corrected_from', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-fail-1',
        intent: '修复 Bug',
        actions: ['直接修改代码'],
        outcome: 'failure',
        outcome_text: '修改引入新 bug',
        learned: ['直接修改有风险'],
      };

      const corrected = engine.reflect(caseData);

      expect(corrected).toBeDefined();
      expect(corrected.corrected_from).toBe('case-fail-1');
      expect(corrected.actions.length).toBeGreaterThan(0);
      // 修正案例应包含原案例没有的步骤（如测试、回滚等）
      expect(corrected.actions).not.toEqual(caseData.actions);
    });

    it('修正案例的 outcome 应为 success（模拟 MCTS 找到成功路径）', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-fail-2',
        intent: '部署服务',
        actions: ['直接部署'],
        outcome: 'failure',
        outcome_text: '部署失败',
        learned: [],
      };

      const corrected = engine.reflect(caseData);
      expect(corrected.outcome).toBe('success');
    });

    it('修正案例应保留原 intent', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-fail-3',
        intent: '数据库迁移',
        actions: ['直接迁移'],
        outcome: 'failure',
        outcome_text: '数据丢失',
        learned: [],
      };

      const corrected = engine.reflect(caseData);
      expect(corrected.intent).toBe('数据库迁移');
    });

    it('修正案例的 learned 应包含反思经验', () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-fail-4',
        intent: '代码审查',
        actions: ['跳过审查'],
        outcome: 'failure',
        outcome_text: '线上 bug',
        learned: [],
      };

      const corrected = engine.reflect(caseData);
      expect(corrected.learned.length).toBeGreaterThan(0);
    });
  });

  // ----------------------------------------------------------
  // 4. 异步执行
  // ----------------------------------------------------------
  describe('异步执行', () => {
    it('reflectAsync 应异步执行不阻塞', async () => {
      const engine = new ReflectionEngine();
      const caseData: FailureCase = {
        id: 'case-async',
        intent: 'test',
        actions: ['act'],
        outcome: 'failure',
        outcome_text: 'fail',
        learned: [],
      };

      const promise = engine.reflectAsync(caseData);
      // 不等待，验证返回 Promise
      expect(promise).toBeInstanceOf(Promise);
      const result = await promise;
      expect(result.corrected_from).toBe('case-async');
    });
  });

  // ----------------------------------------------------------
  // 5. 失败记录管理
  // ----------------------------------------------------------
  describe('失败记录管理', () => {
    it('recordFailure 应记录同类失败次数', () => {
      const engine = new ReflectionEngine();
      engine.recordFailure('检查架构', 'case-1');
      engine.recordFailure('检查架构', 'case-2');
      expect(engine.getFailureCount('检查架构')).toBe(2);
    });

    it('不同 pattern 的失败应独立计数', () => {
      const engine = new ReflectionEngine();
      engine.recordFailure('检查架构', 'case-1');
      engine.recordFailure('部署服务', 'case-2');
      expect(engine.getFailureCount('检查架构')).toBe(1);
      expect(engine.getFailureCount('部署服务')).toBe(1);
    });

    it('clearFailures 应清空失败记录', () => {
      const engine = new ReflectionEngine();
      engine.recordFailure('检查架构', 'case-1');
      engine.clearFailures();
      expect(engine.getFailureCount('检查架构')).toBe(0);
    });
  });
});
