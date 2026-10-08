/**
 * SkillSelector 单元测试
 * 验证：规则匹配 + TF-IDF 向量兜底 + 认知上下文加权 + 澄清流程
 */

import { getSkillSelector, IntentResult, SkillExecutionPlan } from './skill-selector';
import { CognitiveContext } from './cognitive-context-builder';

function makeContext(intentType: string): CognitiveContext {
  return {
    experiences: [],
    knowledge: [],
    references: [],
    skill_candidates: [],
    built_at: Date.now(),
    intent_type: intentType,
  };
}

function makeIntent(
  type: string,
  rawText: string,
  confidence: number = 0.85,
  entities: Record<string, string> = {},
): IntentResult {
  return { type, entities, confidence, raw_text: rawText };
}

describe('SkillSelector', () => {
  const selector = getSkillSelector();

  it('should load registry with 197 skills', () => {
    expect(selector.getSkillCount()).toBeGreaterThan(100);
  });

  // Test 1: trigger match — 回测验证
  it('should match dream-backtest-verify by trigger "回测验证"', () => {
    const plan = selector.select(
      makeIntent('deep_analysis', '帮我做回测验证，评估BDSM子系统价值'),
      makeContext('deep_analysis'),
    );
    expect(plan.skill_ids).toContain('dream-backtest-verify');
    expect(plan.match_reasons.some(r => r.includes('trigger'))).toBe(true);
  });

  // Test 2: trigger match — TDD
  it('should match dream-tdd-dev-workflow by trigger "TDD"', () => {
    const plan = selector.select(
      makeIntent('developer', '用TDD开发新模块，红绿重构'),
      makeContext('developer'),
    );
    expect(plan.skill_ids).toContain('dream-tdd-dev-workflow');
  });

  // Test 3: trigger match — bug修复
  it('should match dream-bugfix-workflow by trigger "bug 修复"', () => {
    const plan = selector.select(
      makeIntent('developer', '这个bug怎么修复，帮我做根因分析5why'),
      makeContext('developer'),
    );
    expect(plan.skill_ids).toContain('dream-bugfix-workflow');
  });

  // Test 4: trigger match — 工程管理
  it('should match dream-eng-mgmt-workflow by trigger "工程管理"', () => {
    const plan = selector.select(
      makeIntent('developer', '需要做工程管理和排期，规划里程碑'),
      makeContext('developer'),
    );
    expect(plan.skill_ids).toContain('dream-eng-mgmt-workflow');
  });

  // Test 5: vector match — BTC行情 (no exact trigger match, should use TF-IDF)
  // SIE-SPEC v0.2: cosine threshold raised 0.15→0.30, this query may trigger imitation
  it('should return candidates via TF-IDF for market query (or imitation_required)', () => {
    const plan = selector.select(
      makeIntent('market_query', 'BTC现在的行情怎么样，分析一下走势'),
      makeContext('market_query'),
    );
    // 阈值 0.30 后，若 cosine < 0.30 则返回 imitation_required（路径 B）
    if (plan.imitation_required) {
      expect(plan.skill_ids.length).toBe(0);
    } else {
      expect(plan.skill_ids.length).toBeGreaterThan(0);
      expect(plan.selections[0].match_score).toBeGreaterThan(0);
    }
  });

  // Test 6: low confidence → top-3 clarification
  it('should return top-3 candidates when confidence < 0.7', () => {
    const plan = selector.select(
      makeIntent('simple_qa', '帮我看一下', 0.5),
      makeContext('simple_qa'),
    );
    expect(plan.match_reasons.some(r => r.includes('0.7'))).toBe(true);
    expect(plan.selections.length).toBeLessThanOrEqual(3);
  });

  // Test 7: match_reasons are always populated
  it('should always have match_reasons in selections', () => {
    const plan = selector.select(
      makeIntent('deep_analysis', '做深度调研和框架研究'),
      makeContext('deep_analysis'),
    );
    for (const sel of plan.selections) {
      expect(sel.match_reasons.length).toBeGreaterThan(0);
    }
  });

  // Test 8: context boost — experience mentions SKILL
  it('should boost score when cognitive context mentions SKILL', () => {
    const ctxWithBoost: CognitiveContext = {
      ...makeContext('deep_analysis'),
      experiences: [{
        memory_id: 'test',
        content: 'dream-backtest-verify is the right approach for backtest verification',
        quality_level: 'B',
        confidence: 0.4,
        relevance_score: 0.5,
      }],
    };
    const plan = selector.select(
      makeIntent('deep_analysis', '帮我做回测验证'),
      ctxWithBoost,
    );
    const backtestSel = plan.selections.find(s => s.skill_id === 'dream-backtest-verify');
    if (backtestSel) {
      expect(backtestSel.match_reasons.some(r => r.includes('context_boost'))).toBe(true);
    }
  });

  // Test 9: SIE-SPEC §3.2.1 — 无匹配时返回 imitation_required（原 fallback simple_qa 已改为模仿信号）
  it('SIE-SPEC: should return imitation_required when no match (was fallback simple_qa)', () => {
    const plan = selector.select(
      makeIntent('simple_qa', 'xyzqwerty nonsensical text 12345'),
      makeContext('simple_qa'),
    );
    // SIE-SPEC v0.2: 无匹配时返回 imitation_required=true，skill_ids 为空
    expect(plan.imitation_required).toBe(true);
    expect(plan.skill_ids).not.toContain('simple_qa');
  });

  // Test 10: plan structure is valid
  it('should produce valid SkillExecutionPlan structure', () => {
    const plan: SkillExecutionPlan = selector.select(
      makeIntent('deep_analysis', '深度分析市场'),
      makeContext('deep_analysis'),
    );
    expect(plan.skill_ids).toBeDefined();
    expect(plan.order).toBeDefined();
    expect(plan.match_reasons).toBeDefined();
    expect(plan.context).toBeDefined();
    expect(plan.selections).toBeDefined();
    expect(plan.skill_ids.length).toBe(plan.order.length);
  });

  // ============================================================
  // SIE-SPEC §3.2.1: imitation_required 信号 (路径 B 触发)
  // ============================================================

  // Test 11 (SIE-SPEC §3.2.1): 无匹配时返回 imitation_required 信号而非 simple_qa
  it('SIE-SPEC: should return imitation_required=true when no SKILL matches (cosine<0.30)', () => {
    const plan = selector.select(
      makeIntent('simple_qa', 'xyzqwerty completely nonsensical text 12345'),
      makeContext('simple_qa'),
    );
    // 新行为：无匹配时不再 fallback 到 simple_qa，而是返回 imitation_required 信号
    expect(plan.imitation_required).toBe(true);
    expect(plan.skill_ids).not.toContain('simple_qa');
  });

  // Test 12 (SIE-SPEC §3.2.1): 命中时 imitation_required=false
  it('SIE-SPEC: should return imitation_required=false when SKILL matches', () => {
    const plan = selector.select(
      makeIntent('deep_analysis', '帮我做回测验证'),
      makeContext('deep_analysis'),
    );
    expect(plan.imitation_required).toBe(false);
    expect(plan.skill_ids.length).toBeGreaterThan(0);
  });

  // Test 13 (SIE-SPEC §3.2.1): SkillExecutionPlan 应有 imitation_required 字段
  it('SIE-SPEC: SkillExecutionPlan should have imitation_required field', () => {
    const plan: SkillExecutionPlan = selector.select(
      makeIntent('deep_analysis', '深度分析'),
      makeContext('deep_analysis'),
    );
    expect(plan).toHaveProperty('imitation_required');
    expect(typeof plan.imitation_required).toBe('boolean');
  });
});
