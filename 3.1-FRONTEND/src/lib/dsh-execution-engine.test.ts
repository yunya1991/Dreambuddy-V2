/**
 * DSHExecutionEngine 单元测试
 * 验证: 节点优先 + LLM 兜底 + 认知上下文注入 + execute_plan 顺序执行
 *
 * Mock 策略: mock child_process.spawn，不依赖真实 Python 环境
 */

import { EventEmitter } from 'events';
import { DSHExecutionEngine, SkillResult } from './dsh-execution-engine';
import type { CognitiveContext } from './cognitive-context-builder';

// ============================================================
// Mock child_process.spawn
// ============================================================

let _mockResponse: { stdout?: string; delay?: number } = {};
let _spawnCallCount = 0;
let _lastSpawnArgs: { adapter: string; module: string; params: any } | null = null;

jest.mock('child_process', () => ({
  spawn: jest.fn((cmd: string, args: string[]) => {
    _spawnCallCount++;
    // 解析 adapter 调用参数
    const module = args[1] || '';
    let params: any = {};
    try { params = JSON.parse(args[2] || '{}'); } catch { /* noop */ }
    _lastSpawnArgs = { adapter: args[0], module, params };

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

// helper
function setMockResponse(stdout: string, delay: number = 0) {
  _mockResponse = { stdout, delay };
}

function resetMock() {
  _mockResponse = {};
  _spawnCallCount = 0;
  _lastSpawnArgs = null;
}

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

function makeContextWithExperiences(intentType: string): CognitiveContext {
  return {
    experiences: [{
      memory_id: 'VM-test',
      content: '历史经验: BTC 趋势跟踪策略在牛市表现优异',
      quality_level: 'B' as const,
      confidence: 0.7,
      relevance_score: 0.8,
    }],
    knowledge: [],
    references: [],
    skill_candidates: [],
    built_at: Date.now(),
    intent_type: intentType,
  };
}

// ============================================================
// 测试
// ============================================================

describe('DSHExecutionEngine', () => {
  let engine: DSHExecutionEngine;

  beforeEach(() => {
    resetMock();
    engine = new DSHExecutionEngine();
  });

  // ── resolveModule 测试 ──────────────────────────────

  describe('resolveModule', () => {
    it('should map DSH_ node_id to module directly', () => {
      expect(engine.resolveModule('DSH_TECHNICAL')).toBe('technical');
      expect(engine.resolveModule('DSH_SENTIMENT')).toBe('sentiment');
      expect(engine.resolveModule('DSH_RISK')).toBe('risk');
      expect(engine.resolveModule('DSH_PORTFOLIO')).toBe('portfolio');
    });

    it('should map by keyword heuristics', () => {
      expect(engine.resolveModule('technical-analysis-skill')).toBe('technical');
      expect(engine.resolveModule('情绪面分析')).toBe('sentiment');
      expect(engine.resolveModule('macro-view')).toBe('macro');
    });

    it('should return null when no mapping exists', () => {
      expect(engine.resolveModule('dream-backtest-verify')).toBeNull();
      expect(engine.resolveModule('simple-qa')).toBeNull();
    });
  });

  // ── execute_skill: 节点优先 ──────────────────────────

  describe('execute_skill - node priority', () => {
    it('should call SubAgent via IPC when skill_id maps to node', async () => {
      // 模拟 SubAgent 成功返回
      setMockResponse(JSON.stringify({
        ok: true,
        output: {
          summary: 'BTC RSI=65, EMA排列多头',
          direction: 'LONG',
          confidence: 0.8,
          signals: [{ name: 'EMA排列', value: '多头', direction: 'LONG', confidence: 0.85 }],
        },
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        { symbol: 'BTC-USDT' },
        makeContext('market_query'),
      );

      expect(result.source).toBe('node');
      expect(result.confidence).toBe(0.8);
      expect(result.skill_id).toBe('DSH_TECHNICAL');
      expect(result.node_outputs.technical).toBeDefined();
      expect(result.llm_output).toBeNull();
      expect(_spawnCallCount).toBe(1);
      expect(_lastSpawnArgs?.module).toBe('technical');
    });

    it('should return source=mixed when confidence is low', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.2, direction: 'NEUTRAL' },
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContext('market_query'),
      );

      expect(result.source).toBe('mixed');
      expect(result.confidence).toBe(0.2);
    });
  });

  // ── execute_skill: LLM 兜底 ──────────────────────────

  describe('execute_skill - LLM fallback', () => {
    it('should fallback to LLM when no SubAgent mapping', async () => {
      const result = await engine.execute_skill(
        'dream-backtest-verify',
        {},
        makeContext('deep_analysis'),
      );

      expect(result.source).toBe('llm');
      expect(result.confidence).toBe(0.3);
      expect(result.content.degraded).toBe(true);
      expect(_spawnCallCount).toBe(0); // 无 IPC 调用
    });

    it('should fallback to LLM when SubAgent IPC fails', async () => {
      setMockResponse(JSON.stringify({
        ok: false,
        error: 'import_failed: ModuleNotFoundError',
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContext('market_query'),
      );

      expect(result.source).toBe('llm');
      expect(result.confidence).toBe(0.3);
      expect(result.content.degraded).toBe(true);
    });

    it('should fallback to LLM on timeout', async () => {
      // 不设置 mock response → child 不会 emit close → 超时
      // 但 mock 中 setTimeout 不会触发，需要手动模拟超时
      // 用极长的 delay 模拟超时
      setMockResponse('{}', 99999); // 永不返回 → 触发超时

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContext('market_query'),
      );

      // 超时后走 LLM 兜底
      expect(result.source).toBe('llm');
      expect(result.confidence).toBe(0.3);
    }, 20000); // 测试超时 20s
  });

  // ── execute_skill: 认知上下文注入 ─────────────────────

  describe('execute_skill - cognitive context injection', () => {
    it('should inject cognitive context into node_output', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7, direction: 'LONG' },
      }));

      await engine.execute_skill(
        'DSH_TECHNICAL',
        { symbol: 'BTC-USDT' },
        makeContextWithExperiences('market_query'),
      );

      expect(_lastSpawnArgs?.params.node_output.cognitive_context).toBeDefined();
      expect(_lastSpawnArgs?.params.node_output.cognitive_context.intent_type).toBe('market_query');
      expect(_lastSpawnArgs?.params.node_output.cognitive_context.experiences).toHaveLength(1);
    });

    it('should set context_used=true when context has experiences', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7 },
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContextWithExperiences('market_query'),
      );

      expect(result.context_used).toBe(true);
    });

    it('should set context_used=false when context is empty', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7 },
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContext('market_query'),
      );

      expect(result.context_used).toBe(false);
    });
  });

  // ── execute_plan: 顺序执行 ──────────────────────────

  describe('execute_plan', () => {
    it('should execute skills in order', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7, direction: 'LONG' },
      }));

      const plan = {
        skill_ids: ['DSH_TECHNICAL', 'DSH_SENTIMENT'],
        order: ['DSH_TECHNICAL', 'DSH_SENTIMENT'],
        params: { symbol: 'BTC-USDT' },
        match_reasons: [],
        context: makeContext('market_query'),
        selections: [],
      };

      const results = await engine.execute_plan(plan);

      expect(results).toHaveLength(2);
      expect(results[0].skill_id).toBe('DSH_TECHNICAL');
      expect(results[1].skill_id).toBe('DSH_SENTIMENT');
      expect(_spawnCallCount).toBe(2);
    });

    it('should use skill_ids when order is empty', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7 },
      }));

      const plan = {
        skill_ids: ['DSH_RISK', 'DSH_ONCHAIN'],
        order: [],
        params: {},
        match_reasons: [],
        context: makeContext('market_query'),
        selections: [],
      };

      const results = await engine.execute_plan(plan);

      expect(results).toHaveLength(2);
      expect(results[0].skill_id).toBe('DSH_RISK');
      expect(results[1].skill_id).toBe('DSH_ONCHAIN');
    });

    it('should handle mixed node + LLM fallback in plan', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.7 },
      }));

      const plan = {
        skill_ids: ['DSH_TECHNICAL', 'dream-backtest-verify'],
        order: ['DSH_TECHNICAL', 'dream-backtest-verify'],
        params: {},
        match_reasons: [],
        context: makeContext('deep_analysis'),
        selections: [],
      };

      const results = await engine.execute_plan(plan);

      expect(results).toHaveLength(2);
      expect(results[0].source).toBe('node');
      expect(results[1].source).toBe('llm');
    });
  });

  // ── SkillResult 结构验证 ─────────────────────────────

  describe('SkillResult structure', () => {
    it('should return valid SkillResult with all required fields', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { confidence: 0.75, direction: 'LONG', summary: 'test' },
      }));

      const result = await engine.execute_skill(
        'DSH_TECHNICAL',
        {},
        makeContext('market_query'),
      );

      expect(result).toHaveProperty('skill_id');
      expect(result).toHaveProperty('content');
      expect(result).toHaveProperty('confidence');
      expect(result).toHaveProperty('source');
      expect(result).toHaveProperty('node_outputs');
      expect(result).toHaveProperty('llm_output');
      expect(result).toHaveProperty('context_used');
      expect(result).toHaveProperty('latency_ms');
      expect(typeof result.latency_ms).toBe('number');
      expect(result.latency_ms).toBeGreaterThanOrEqual(0);
    });
  });
});
