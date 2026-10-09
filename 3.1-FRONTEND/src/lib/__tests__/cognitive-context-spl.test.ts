/**
 * SPEC-20261009 §11.8 P1-2: CognitiveContextBuilder 第5/6系统接入测试
 *
 * TDD RED→GREEN
 *
 * 覆盖：
 *   - CognitiveContext 新增 solution_cases + cvg_result 字段
 *   - build() 方法返回包含 solution_cases（FAIL-OPEN：TDR 不可用→空数组）
 *   - build() 方法返回包含 cvg_result（开关关闭→null）
 *   - isContextUsed 包含 solution_cases 判断
 */

// Mock 外部依赖
jest.mock('../cognitive-client', () => ({
  callCognitive: jest.fn().mockResolvedValue({ ok: true, data: { memories: [] } }),
}));

jest.mock('../knowledge-rag', () => ({
  retrieveRelevantChunks: jest.fn().mockResolvedValue([]),
}));

jest.mock('../skill-selector', () => ({
  getSkillSelector: jest.fn().mockReturnValue({
    select: jest.fn().mockReturnValue({ selections: [] }),
    getSkill: jest.fn(),
  }),
  IntentResult: {},
}));

// Mock child_process for index_query_adapter
jest.mock('child_process', () => ({
  spawn: jest.fn(() => ({
    stdout: { on: jest.fn() },
    stderr: { on: jest.fn() },
    on: jest.fn((event: string, cb: Function) => {
      if (event === 'close') cb();
    }),
    kill: jest.fn(),
  })),
}));

import { CognitiveContextBuilder, type CognitiveContext } from '../cognitive-context-builder';

describe('SPEC §11.8 P1-2: CognitiveContextBuilder 第5/6系统接入', () => {
  // ----------------------------------------------------------
  // 1. CognitiveContext 接口字段
  // ----------------------------------------------------------
  describe('CognitiveContext 接口字段', () => {
    it('应有 solution_cases 字段 (SolutionCase[])', () => {
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'test',
        solution_cases: [],
        cvg_result: null,
      };
      expect(ctx).toHaveProperty('solution_cases');
      expect(Array.isArray(ctx.solution_cases)).toBe(true);
    });

    it('应有 cvg_result 字段 (CrossValidationResult | null)', () => {
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'test',
        solution_cases: [],
        cvg_result: null,
      };
      expect(ctx).toHaveProperty('cvg_result');
      expect(ctx.cvg_result).toBeNull();
    });
  });

  // ----------------------------------------------------------
  // 2. build() 返回结构
  // ----------------------------------------------------------
  describe('build() 返回结构', () => {
    let builder: CognitiveContextBuilder;

    beforeEach(() => {
      builder = new CognitiveContextBuilder();
    });

    it('build() 返回应包含 solution_cases 字段', async () => {
      const ctx = await builder.build('intent_type', [], 'test query');
      expect(ctx).toHaveProperty('solution_cases');
    });

    it('build() 返回应包含 cvg_result 字段', async () => {
      const ctx = await builder.build('intent_type', [], 'test query');
      expect(ctx).toHaveProperty('cvg_result');
    });

    it('FAIL-OPEN: TDR 不可用时 solution_cases 应为空数组', async () => {
      const ctx = await builder.build('intent_type', [], 'test query');
      expect(ctx.solution_cases).toEqual([]);
    });

    it('FAIL-OPEN: CVG 开关关闭时 cvg_result 应为 null', async () => {
      const ctx = await builder.build('intent_type', [], 'test query');
      expect(ctx.cvg_result).toBeNull();
    });
  });

  // ----------------------------------------------------------
  // 3. isContextUsed
  // ----------------------------------------------------------
  describe('isContextUsed', () => {
    it('solution_cases 非空时应返回 true', () => {
      const builder = new CognitiveContextBuilder();
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'test',
        solution_cases: [{ id: 'case-1' } as any],
        cvg_result: null,
      };
      expect(builder.isContextUsed(ctx)).toBe(true);
    });

    it('所有字段为空（含 solution_cases）时应返回 false', () => {
      const builder = new CognitiveContextBuilder();
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'test',
        solution_cases: [],
        cvg_result: null,
      };
      expect(builder.isContextUsed(ctx)).toBe(false);
    });
  });
});
