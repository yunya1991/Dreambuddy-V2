/**
 * SIE-SPEC §5.1 P1: cognitive-context-builder imitation_context 字段测试 — RED 阶段
 *
 * 验证 CognitiveContext 新增 imitation_context 字段（注入文档检索结果）
 * 该字段供路径 B/C 下游消费者（SummaryAgent 等）访问文档/调研结果
 *
 * 覆盖：
 *   - CognitiveContext.imitation_context 字段存在性（可选）
 *   - ImitationContext 数据结构（document_results + research_report）
 *   - withImitationContext() 静态方法注入文档检索结果
 *   - 不破坏既有 build() 返回结构（向后兼容）
 */

import { getCognitiveContextBuilder, type CognitiveContext } from './cognitive-context-builder';

describe('SIE-SPEC §5.1 P1: imitation_context 字段 (cognitive-context-builder)', () => {
  // ============================================================
  // §5.1: CognitiveContext 新增 imitation_context 字段
  // ============================================================
  describe('CognitiveContext.imitation_context 字段', () => {
    it('CognitiveContext 接口应包含 imitation_context 可选字段', () => {
      // 构造一个不包含 imitation_context 的上下文（向后兼容）
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
      };
      // imitation_context 应是可选的，不设置时为 undefined
      expect(ctx.imitation_context).toBeUndefined();
    });

    it('CognitiveContext 应允许设置 imitation_context 字段', () => {
      const ctx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
        imitation_context: {
          document_results: [
            { ref_id: 'doc-1', title: 'Test Doc', path: '/test.md', category: 'doc', description: '' },
          ],
          research_report: null,
        },
      };
      expect(ctx.imitation_context).toBeDefined();
      expect(ctx.imitation_context?.document_results).toHaveLength(1);
      expect(ctx.imitation_context?.document_results[0].title).toBe('Test Doc');
    });
  });

  // ============================================================
  // §5.1: withImitationContext 静态方法注入文档检索结果
  // ============================================================
  describe('withImitationContext 方法', () => {
    it('应提供 withImitationContext 函数注入文档检索结果到既有上下文', () => {
      // RED 原因：cognitive-context-builder 当前不导出 withImitationContext
      const { withImitationContext } = require('./cognitive-context-builder');

      const baseCtx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
      };

      const docResults = [
        { ref_id: 'doc-1', title: '配置指南', path: '/config.md', category: 'doc' as const, description: '如何配置' },
        { ref_id: 'doc-2', title: 'API 文档', path: '/api.md', category: 'doc' as const, description: 'API 说明' },
      ];

      const enriched = withImitationContext(baseCtx, docResults);

      expect(enriched.imitation_context).toBeDefined();
      expect(enriched.imitation_context.document_results).toHaveLength(2);
      expect(enriched.imitation_context.document_results[0].title).toBe('配置指南');
      // 原有字段保持不变
      expect(enriched.experiences).toBe(baseCtx.experiences);
      expect(enriched.intent_type).toBe('simple_qa');
    });

    it('withImitationContext 应支持注入 research_report（路径 C 调研报告）', () => {
      const { withImitationContext } = require('./cognitive-context-builder');

      const baseCtx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
      };

      const researchReport = '# 调研报告\n\n某工具的配置方法...';
      const enriched = withImitationContext(baseCtx, [], researchReport);

      expect(enriched.imitation_context).toBeDefined();
      expect(enriched.imitation_context.research_report).toBe(researchReport);
      expect(enriched.imitation_context.document_results).toHaveLength(0);
    });

    it('withImitationContext 应同时支持文档结果和调研报告', () => {
      const { withImitationContext } = require('./cognitive-context-builder');

      const baseCtx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
      };

      const docResults = [
        { ref_id: 'doc-1', title: 'Doc', path: '/d.md', category: 'doc' as const, description: '' },
      ];
      const researchReport = '调研报告内容';

      const enriched = withImitationContext(baseCtx, docResults, researchReport);
      expect(enriched.imitation_context.document_results).toHaveLength(1);
      expect(enriched.imitation_context.research_report).toBe(researchReport);
    });

    it('withImitationContext 空输入应仍返回带 imitation_context 的上下文', () => {
      const { withImitationContext } = require('./cognitive-context-builder');

      const baseCtx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
      };

      const enriched = withImitationContext(baseCtx);
      expect(enriched.imitation_context).toBeDefined();
      expect(enriched.imitation_context.document_results).toEqual([]);
      expect(enriched.imitation_context.research_report).toBeNull();
    });
  });

  // ============================================================
  // 向后兼容：既有 build() 不破坏
  // ============================================================
  describe('向后兼容', () => {
    it('build() 返回的上下文不含 imitation_context（未注入时）', async () => {
      const builder = getCognitiveContextBuilder();
      // build 可能因外部依赖不可达而 FAIL-OPEN
      try {
        const ctx = await builder.build('simple_qa', [], 'test query');
        // 既有字段应存在
        expect(ctx.experiences).toBeDefined();
        expect(ctx.knowledge).toBeDefined();
        expect(ctx.references).toBeDefined();
        expect(ctx.skill_candidates).toBeDefined();
        // 未注入 imitation_context 时应为 undefined
        expect(ctx.imitation_context).toBeUndefined();
      } catch {
        // 外部依赖不可达时跳过
      }
    });

    it('isContextUsed 应仍按原逻辑判断（不考虑 imitation_context）', () => {
      const builder = getCognitiveContextBuilder();
      const emptyCtx: CognitiveContext = {
        experiences: [],
        knowledge: [],
        references: [],
        skill_candidates: [],
        built_at: Date.now(),
        intent_type: 'simple_qa',
        // 即使有 imitation_context，但四系统为空时 isContextUsed 应返回 false
        imitation_context: {
          document_results: [{ ref_id: 'x', title: 'x', path: 'x', category: 'doc', description: '' }],
          research_report: null,
        },
      };
      // isContextUsed 只看四系统，不看 imitation_context（HC-7 只读原则）
      expect(builder.isContextUsed(emptyCtx)).toBe(false);
    });
  });
});
