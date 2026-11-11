/**
 * @jest-environment node
 *
 * Phase 4.5 side-A variant 透传测试：focus/seed 解析与提示词约束。
 */
import {
  FOCUS_DIRECTIVES,
  buildVariantPromptSection,
  normalizeVariant,
} from './plan-variant';

describe('normalizeVariant', () => {
  it('合法 variant 原样透传（focus + seed）', () => {
    expect(normalizeVariant({ focus: 'risk-first', seed: 1 })).toEqual({
      focus: 'risk-first',
      seed: 1,
    });
  });

  it('未知 focus / 非对象 → null（向后兼容）', () => {
    expect(normalizeVariant({ focus: 'unknown-focus', seed: 0 })).toBeNull();
    expect(normalizeVariant(undefined)).toBeNull();
    expect(normalizeVariant('risk-first')).toBeNull();
  });

  it('seed 非法 → 归零，focus 仍生效', () => {
    expect(normalizeVariant({ focus: 'cost-first', seed: -3 })).toEqual({
      focus: 'cost-first',
      seed: 0,
    });
  });
});

describe('buildVariantPromptSection', () => {
  it('三个 focus 分别注入对应约束，且缺省为空', () => {
    const risk = buildVariantPromptSection({ focus: 'risk-first', seed: 0 }).join('\n');
    const cost = buildVariantPromptSection({ focus: 'cost-first', seed: 1 }).join('\n');
    const speed = buildVariantPromptSection({ focus: 'speed-first', seed: 2 }).join('\n');

    expect(risk).toContain('风险控制');
    expect(cost).toContain('最少步骤');
    expect(speed).toContain('最短路径');
    expect(risk).toContain(FOCUS_DIRECTIVES['risk-first']);
    expect(buildVariantPromptSection(null)).toEqual([]);
  });
});
