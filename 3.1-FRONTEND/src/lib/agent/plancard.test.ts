/**
 * @jest-environment node
 *
 * PlanCard 手写校验测试（与 52/schemas/plancard.schema.json 同规则）。
 */
import {
  PLAN_CARD_ID_PREFIX,
  newPlanCardId,
  validatePlanCard,
  type PlanCard,
} from './plancard';

function makeCard(overrides: Partial<PlanCard> = {}): PlanCard {
  return {
    id: 'pc-01hzzzzzzz',
    intent: '评估是否给离场模块增加波动率自适应阈值',
    context_refs: ['unified_search:vol-adaptive-threshold'],
    plan_steps: [
      { step: 1, action: '检索历史阈值经验', tool: 'l0.cognition.mcp.recall' },
      { step: 2, action: '评估候选方案', tool: 'l0.eval.mcp.eval_analyze' },
    ],
    evidence_refs: ['recall:VM-001', 'unified_search:doc-7'],
    risk_flags: [],
    cost_estimate: { tokens: 3200, tool_calls: 2 },
    expected_outcome: '给出阈值候选与回测验证计划',
    validation: {
      evaluator_refs: ['45.heuristic@1.0.0'],
      acceptance_checks: ['回测最大回撤不劣于基线'],
    },
    ...overrides,
  };
}

describe('validatePlanCard', () => {
  it('合法卡 → ok', () => {
    const result = validatePlanCard(makeCard());
    expect(result.ok).toBe(true);
    expect(result.errors).toEqual([]);
  });

  it('缺 validation → 错误', () => {
    const card = makeCard();
    delete (card as Partial<PlanCard>).validation;
    const result = validatePlanCard(card);
    expect(result.ok).toBe(false);
    expect(result.errors).toContain('validation_required');
  });

  it('id 前缀错 → 错误', () => {
    const result = validatePlanCard(makeCard({ id: 'plan-001' }));
    expect(result.ok).toBe(false);
    expect(result.errors.some((e) => e.startsWith('id_invalid_prefix'))).toBe(true);
  });

  it('plan_steps 空 → 错误', () => {
    const result = validatePlanCard(makeCard({ plan_steps: [] }));
    expect(result.ok).toBe(false);
    expect(result.errors).toContain('plan_steps_empty');
  });

  it('plan_steps 工具名不合规 → 错误', () => {
    const result = validatePlanCard(
      makeCard({ plan_steps: [{ step: 1, action: 'x', tool: 'cognition.recall' }] }),
    );
    expect(result.ok).toBe(false);
    expect(result.errors.some((e) => e.includes('tool_invalid'))).toBe(true);
  });

  it('evaluator_refs 不合规 → 错误', () => {
    const result = validatePlanCard(
      makeCard({ validation: { evaluator_refs: ['heuristic@1.0.0'] } }),
    );
    expect(result.ok).toBe(false);
    expect(result.errors.some((e) => e.includes('evaluator_refs'))).toBe(true);
  });

  it('unknown 字段容错（不因多余字段失败）', () => {
    const card = { ...makeCard(), extra_unknown_field: { any: 'value' } };
    const result = validatePlanCard(card);
    expect(result.ok).toBe(true);
  });

  it('非对象 → root_not_object', () => {
    expect(validatePlanCard(null)).toEqual({ ok: false, errors: ['root_not_object'] });
    expect(validatePlanCard('pc-x')).toEqual({ ok: false, errors: ['root_not_object'] });
  });
});

describe('newPlanCardId', () => {
  it('pc- 前缀且两次生成不重复', () => {
    const a = newPlanCardId();
    const b = newPlanCardId();
    expect(a.startsWith(PLAN_CARD_ID_PREFIX)).toBe(true);
    expect(a).not.toBe(b);
  });
});
