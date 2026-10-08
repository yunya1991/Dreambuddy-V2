/**
 * CDriveCoordinator 单元测试
 * 验证: reflect 反射决策 + decideFromResult + decideFromResults 聚合 + should* 判断 + FAIL-OPEN
 *
 * Mock 策略: mock child_process.spawn（与 dsh-execution-engine.test.ts 一致）
 */

import { EventEmitter } from 'events';
import { CDriveCoordinator, CDriveDecision, CDriveRequest } from './c-drive';
import type { SkillResult } from './dsh-execution-engine';
import type { CognitiveContext } from './cognitive-context-builder';

// ============================================================
// Mock child_process.spawn（复用 dsh-execution-engine.test.ts 的模式）
// ============================================================

let _mockResponse: { stdout?: string; delay?: number } = {};
let _spawnCallCount = 0;
let _lastSpawnArgs: { module: string; params: any } | null = null;

jest.mock('child_process', () => ({
  spawn: jest.fn((_cmd: string, args: string[]) => {
    _spawnCallCount++;
    const module = args[1] || '';
    let params: any = {};
    try { params = JSON.parse(args[2] || '{}'); } catch { /* noop */ }
    _lastSpawnArgs = { module, params };

    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = jest.fn();

    const delay = _mockResponse.delay || 0;
    const stdout = _mockResponse.stdout || '{"ok":false,"error":"no_mock_set"}';

    setTimeout(() => {
      child.stdout.emit('data', Buffer.from(stdout));
      child.emit('close');
    }, delay);

    return child;
  }),
}));

function setMockResponse(stdout: string, delay: number = 0) {
  _mockResponse = { stdout, delay };
}

function resetMock() {
  _mockResponse = {};
  _spawnCallCount = 0;
  _lastSpawnArgs = null;
}

function makeMockDecision(overrides: Partial<CDriveDecision> = {}): CDriveDecision {
  return {
    action: 'continue',
    reason: '正常继续',
    confidence: 0.75,
    suggestions: [],
    bull_argument: null,
    bear_argument: null,
    bull_confidence: null,
    bear_confidence: null,
    jump_to: null,
    supplement_module: null,
    jeval_noul: null,
    steps_executed: ['DSH_TECHNICAL'],
    effort_level: 'light',
    debate_rounds: 0,
    synthesized_cards: [],
    enhancement_hints: [],
    charts: [],
    ...overrides,
  };
}

function makeSkillResult(overrides: Partial<SkillResult> = {}): SkillResult {
  return {
    skill_id: 'DSH_TECHNICAL',
    content: {
      direction: 'LONG',
      confidence: 0.8,
      signals: [{ name: 'EMA排列', value: '多头', direction: 'LONG', confidence: 0.85 }],
    },
    confidence: 0.8,
    source: 'node',
    node_outputs: {},
    llm_output: null,
    context_used: true,
    latency_ms: 100,
    ...overrides,
  };
}

// ============================================================
// 测试
// ============================================================

describe('CDriveCoordinator', () => {
  let coordinator: CDriveCoordinator;

  beforeEach(() => {
    resetMock();
    coordinator = new CDriveCoordinator();
  });

  // ── reflect 基础测试 ────────────────────────────────

  describe('reflect', () => {
    it('should call c_drive IPC handler with correct params', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision() },
      }));

      const request: CDriveRequest = {
        node_id: 'DSH_TECHNICAL',
        confidence: 0.8,
        direction: 'LONG',
        signals: [{ name: 'EMA', value: '多头', direction: 'LONG', confidence: 0.85 }],
        intent_type: 'market_query',
      };

      const decision = await coordinator.reflect(request);

      expect(_spawnCallCount).toBe(1);
      expect(_lastSpawnArgs?.module).toBe('c_drive');
      expect(_lastSpawnArgs?.params.node_id).toBe('DSH_TECHNICAL');
      expect(_lastSpawnArgs?.params.confidence).toBe(0.8);
      expect(_lastSpawnArgs?.params.direction).toBe('LONG');
      expect(_lastSpawnArgs?.params.intent_type).toBe('market_query');
      expect(decision.action).toBe('continue');
    });

    it('should return REDO decision when Python returns redo', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision({ action: 'redo', reason: '置信度过低' }) },
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_RISK',
        confidence: 0.2,
        direction: 'NEUTRAL',
        signals: [],
      });

      expect(decision.action).toBe('redo');
      expect(decision.reason).toContain('置信度');
    });

    it('should return SUPPLEMENT decision with module target', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision({
          action: 'supplement',
          supplement_module: 'sentiment',
          reason: '技术面与情绪面矛盾，需补充情绪面',
        }) },
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.6,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('supplement');
      expect(decision.supplement_module).toBe('sentiment');
    });

    it('should return DEBATE decision with bull/bear arguments', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision({
          action: 'debate',
          bull_argument: 'EMA多头排列',
          bear_argument: 'RSI超买',
          bull_confidence: 0.7,
          bear_confidence: 0.65,
          debate_rounds: 2,
        }) },
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.55,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('debate');
      expect(decision.bull_argument).toContain('EMA');
      expect(decision.bear_argument).toContain('RSI');
      expect(decision.debate_rounds).toBe(2);
    });

    it('should return JUMP decision with target', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision({
          action: 'jump',
          jump_to: 'DSH_RISK',
          reason: '预算不足，跳转风控收尾',
        }) },
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.5,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('jump');
      expect(decision.jump_to).toBe('DSH_RISK');
    });
  });

  // ── FAIL-OPEN 降级测试 ──────────────────────────────

  describe('FAIL-OPEN fallback', () => {
    it('should return CONTINUE fallback when IPC fails', async () => {
      setMockResponse(JSON.stringify({
        ok: false,
        error: 'import_failed: ModuleNotFoundError',
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.8,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('continue');
      expect(decision.reason).toContain('IPC 降级');
      expect(decision.confidence).toBe(0.5);
    });

    it('should return CONTINUE fallback when response is malformed', async () => {
      setMockResponse('not a json');

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.8,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('continue');
      expect(decision.reason).toContain('IPC 降级');
    });
  });

  // ── decideFromResult 测试 ──────────────────────────

  describe('decideFromResult', () => {
    it('should extract params from SkillResult and reflect', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision() },
      }));

      const result = makeSkillResult();
      const decision = await coordinator.decideFromResult(result, 'market_query');

      expect(_lastSpawnArgs?.params.node_id).toBe('DSH_TECHNICAL');
      expect(_lastSpawnArgs?.params.confidence).toBe(0.8);
      expect(_lastSpawnArgs?.params.direction).toBe('LONG');
      expect(_lastSpawnArgs?.params.signals).toHaveLength(1);
      expect(_lastSpawnArgs?.params.intent_type).toBe('market_query');
      expect(decision.action).toBe('continue');
    });

    it('should handle SkillResult with no signals', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision() },
      }));

      const result = makeSkillResult({ content: { direction: 'NEUTRAL', confidence: 0.3 } });
      const decision = await coordinator.decideFromResult(result);

      expect(_lastSpawnArgs?.params.signals).toEqual([]);
      expect(_lastSpawnArgs?.params.direction).toBe('NEUTRAL');
      expect(decision.action).toBe('continue');
    });
  });

  // ── decideFromResults 聚合测试 ─────────────────────

  describe('decideFromResults', () => {
    it('should aggregate multiple SkillResults with weighted confidence', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision() },
      }));

      const results: SkillResult[] = [
        makeSkillResult({ skill_id: 'DSH_TECHNICAL', confidence: 0.8, content: { direction: 'LONG', signals: [] } }),
        makeSkillResult({ skill_id: 'DSH_SENTIMENT', confidence: 0.6, content: { direction: 'LONG', signals: [] } }),
        makeSkillResult({ skill_id: 'DSH_RISK', confidence: 0.4, content: { direction: 'SHORT', signals: [] } }),
      ];

      const decision = await coordinator.decideFromResults(results, 'market_query');

      // 加权平均置信度: (0.8² + 0.6² + 0.4²) / (0.8+0.6+0.4) = 1.16 / 1.8 ≈ 0.644
      expect(_lastSpawnArgs?.params.confidence).toBeCloseTo(0.644, 1);
      // 方向投票: LONG 权重 0.8+0.6=1.4 > SHORT 0.4
      expect(_lastSpawnArgs?.params.direction).toBe('LONG');
      expect(decision.action).toBe('continue');
    });

    it('should merge all signals from multiple results', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision() },
      }));

      const results: SkillResult[] = [
        makeSkillResult({ content: { direction: 'LONG', signals: [{ name: 'EMA', value: '多', direction: 'LONG', confidence: 0.8 }] } }),
        makeSkillResult({ skill_id: 'DSH_SENTIMENT', content: { direction: 'LONG', signals: [{ name: 'FGI', value: '贪婪', direction: 'LONG', confidence: 0.7 }] } }),
      ];

      await coordinator.decideFromResults(results);

      expect(_lastSpawnArgs?.params.signals).toHaveLength(2);
      expect(_lastSpawnArgs?.params.signals[0].name).toBe('EMA');
      expect(_lastSpawnArgs?.params.signals[1].name).toBe('FGI');
    });

    it('should return fallback for empty results', async () => {
      const decision = await coordinator.decideFromResults([]);

      expect(decision.action).toBe('continue');
      expect(decision.reason).toContain('empty_results');
      expect(_spawnCallCount).toBe(0);
    });
  });

  // ── should* 判断方法测试 ────────────────────────────

  describe('should* methods', () => {
    it('shouldContinue returns true for continue action', () => {
      expect(coordinator.shouldContinue(makeMockDecision({ action: 'continue' }))).toBe(true);
      expect(coordinator.shouldContinue(makeMockDecision({ action: 'redo' }))).toBe(false);
    });

    it('shouldRedo returns true for redo action', () => {
      expect(coordinator.shouldRedo(makeMockDecision({ action: 'redo' }))).toBe(true);
      expect(coordinator.shouldRedo(makeMockDecision({ action: 'continue' }))).toBe(false);
    });

    it('shouldJump returns true only when jump_to is set', () => {
      expect(coordinator.shouldJump(makeMockDecision({ action: 'jump', jump_to: 'DSH_RISK' }))).toBe(true);
      expect(coordinator.shouldJump(makeMockDecision({ action: 'jump', jump_to: null }))).toBe(false);
      expect(coordinator.shouldJump(makeMockDecision({ action: 'continue' }))).toBe(false);
    });

    it('shouldSupplement returns true only when supplement_module is set', () => {
      expect(coordinator.shouldSupplement(makeMockDecision({ action: 'supplement', supplement_module: 'sentiment' }))).toBe(true);
      expect(coordinator.shouldSupplement(makeMockDecision({ action: 'supplement', supplement_module: null }))).toBe(false);
      expect(coordinator.shouldSupplement(makeMockDecision({ action: 'continue' }))).toBe(false);
    });

    it('shouldDebate returns true for debate action', () => {
      expect(coordinator.shouldDebate(makeMockDecision({ action: 'debate' }))).toBe(true);
      expect(coordinator.shouldDebate(makeMockDecision({ action: 'continue' }))).toBe(false);
    });
  });

  // ── 真实 handler 返回格式兼容性 (修复 decision 字段读取 bug) ─────

  describe('real handler format compatibility (top-level decision)', () => {
    it('should read top-level decision (not output.decision) — matches c_drive handler E2E', async () => {
      // 真实 handle_c_drive_agent 返回 {ok:true, decision:{...}}
      // 不是 {ok:true, output:{decision:{...}}}
      setMockResponse(JSON.stringify({
        ok: true,
        decision: makeMockDecision({  // 顶层 decision（真实格式）
          action: 'supplement',
          reason: '矛盾需补充',
          supplement_module: 'sentiment',
        }),
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.5,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('supplement');
      expect(decision.supplement_module).toBe('sentiment');
      expect(coordinator.shouldSupplement(decision)).toBe(true);
    });

    it('should still work with output.decision wrapped format (defensive compat)', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { decision: makeMockDecision({ action: 'jump', jump_to: 'DSH_RISK' }) },
      }));

      const decision = await coordinator.reflect({
        node_id: 'DSH_TECHNICAL',
        confidence: 0.5,
        direction: 'LONG',
        signals: [],
      });

      expect(decision.action).toBe('jump');
      expect(decision.jump_to).toBe('DSH_RISK');
    });
  });
});
