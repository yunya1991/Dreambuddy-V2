/**
 * SummaryAgent 单元测试
 * 验证: summarize 汇总 + aggregated 构造 + sources 来源标注 + 置信度计算 + 人工复核阈值 + FAIL-OPEN
 */

import { EventEmitter } from 'events';
import { SummaryAgent, FinalOutput, SourceRef } from './summary-agent';
import type { SkillResult } from './dsh-execution-engine';
import type { CDriveDecision } from './c-drive';

// ============================================================
// Mock child_process.spawn
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

function makeMockCards(): any[] {
  return [
    {
      card_type: 'insight',
      title: '多头共识信号',
      content: '多源 SubAgent 共识偏多',
      signals_ref: [],
      charts_ref: [],
      confidence: 0.75,
      source_modules: ['DSH_TECHNICAL', 'DSH_SENTIMENT'],
    },
    {
      card_type: 'recommendation',
      title: '关注做多机会',
      content: '多源共识偏多，可关注顺势做多',
      signals_ref: [],
      charts_ref: [],
      confidence: 0.7,
      source_modules: ['DSH_TECHNICAL'],
    },
  ];
}

function makeMockCDrive(overrides: Partial<CDriveDecision> = {}): CDriveDecision {
  return {
    action: 'continue',
    reason: '正常继续',
    confidence: 0.8,
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
      summary: 'BTC RSI=65, EMA排列多头',
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

describe('SummaryAgent', () => {
  let agent: SummaryAgent;

  beforeEach(() => {
    resetMock();
    agent = new SummaryAgent();
  });

  // ── summarize 基础测试 ──────────────────────────────

  describe('summarize', () => {
    it('should call synthesizer IPC with aggregated dict', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const results = [makeSkillResult(), makeSkillResult({ skill_id: 'DSH_SENTIMENT' })];

      const output = await agent.summarize('market_query', results);

      expect(_spawnCallCount).toBe(1);
      expect(_lastSpawnArgs?.module).toBe('synthesizer');
      expect(_lastSpawnArgs?.params.aggregated).toBeDefined();
      expect(_lastSpawnArgs?.params.aggregated.summaries).toHaveLength(2);
      expect(_lastSpawnArgs?.params.aggregated.modules).toContain('DSH_TECHNICAL');
      expect(_lastSpawnArgs?.params.aggregated.modules).toContain('DSH_SENTIMENT');
    });

    it('should return FinalOutput with SynthesizedCards as content', async () => {
      const cards = makeMockCards();
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards },
      }));

      const output = await agent.summarize('market_query', [makeSkillResult()]);

      expect(output.intent_type).toBe('market_query');
      expect(Array.isArray(output.content)).toBe(true);
      expect(output.content).toHaveLength(2);
      expect(output.content[0].card_type).toBe('insight');
      expect(output.content[1].card_type).toBe('recommendation');
    });

    it('should compute confidence from C-Drive decision when available', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const cdrive = makeMockCDrive({ confidence: 0.85 });
      const output = await agent.summarize('market_query', [makeSkillResult()], cdrive);

      expect(output.confidence).toBe(0.85);
      expect(output.human_review_required).toBe(false);
    });

    it('should compute confidence from cards average when no C-Drive', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const output = await agent.summarize('market_query', [makeSkillResult()]);

      // cards confidence: 0.75, 0.7 → avg = 0.725
      expect(output.confidence).toBeCloseTo(0.725, 2);
    });
  });

  // ── human_review_required 阈值测试 ──────────────────

  describe('human_review_required', () => {
    it('should be true when confidence <= 0.4', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: [{ ...makeMockCards()[0], confidence: 0.3 }] },
      }));

      // 无 C-Drive，confidence 从 cards 取 = 0.3
      const output = await agent.summarize('market_query', [makeSkillResult()]);

      expect(output.confidence).toBe(0.3);
      expect(output.human_review_required).toBe(true);
    });

    it('should be false when confidence > 0.4', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const output = await agent.summarize('market_query', [makeSkillResult()]);

      expect(output.confidence).toBeGreaterThan(0.4);
      expect(output.human_review_required).toBe(false);
    });
  });

  // ── sources 来源标注测试 ─────────────────────────────

  describe('sources', () => {
    it('should build SourceRef from SkillResults', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const results = [
        makeSkillResult({ skill_id: 'DSH_TECHNICAL', source: 'node' }),
        makeSkillResult({ skill_id: 'DSH_SENTIMENT', source: 'llm' }),
      ];

      const output = await agent.summarize('market_query', results);

      expect(output.sources).toHaveLength(2);
      expect(output.sources[0].subagent_id).toBe('DSH_TECHNICAL');
      expect(output.sources[0].source_type).toBe('node');
      expect(output.sources[1].subagent_id).toBe('DSH_SENTIMENT');
      expect(output.sources[1].source_type).toBe('llm');
    });
  });

  // ── aggregated dict 构造测试 ────────────────────────

  describe('aggregated dict construction', () => {
    it('should compute consensus_direction from signal voting', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const results = [
        makeSkillResult({ content: { direction: 'LONG', signals: [{ name: 's1', direction: 'LONG', confidence: 0.8 }] } }),
        makeSkillResult({ skill_id: 'DSH_SENTIMENT', content: { direction: 'LONG', signals: [{ name: 's2', direction: 'LONG', confidence: 0.7 }] } }),
      ];

      await agent.summarize('market_query', results);

      // long_count=2, short_count=0 → consensus='long'
      expect(_lastSpawnArgs?.params.aggregated.consensus_direction).toBe('long');
      expect(_lastSpawnArgs?.params.aggregated.long_count).toBe(2);
      expect(_lastSpawnArgs?.params.aggregated.short_count).toBe(0);
    });

    it('should sort top_signals by confidence descending', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const results = [
        makeSkillResult({ content: { signals: [
          { name: 'low', direction: 'LONG', confidence: 0.3 },
          { name: 'high', direction: 'LONG', confidence: 0.9 },
          { name: 'mid', direction: 'SHORT', confidence: 0.6 },
        ] } }),
      ];

      await agent.summarize('market_query', results);

      const top = _lastSpawnArgs?.params.aggregated.top_signals;
      expect(top).toHaveLength(3);
      expect(top[0].confidence).toBe(0.9);
      expect(top[1].confidence).toBe(0.6);
      expect(top[2].confidence).toBe(0.3);
    });

    it('should include C-Drive charts in all_charts', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const cdrive = makeMockCDrive({
        charts: [{ title: 'RSI heatmap', type: 'heatmap' }],
      });
      const results = [makeSkillResult({ content: { charts: [{ title: 'EMA line', type: 'line' }] } })];

      await agent.summarize('market_query', results, cdrive);

      const allCharts = _lastSpawnArgs?.params.aggregated.all_charts;
      expect(allCharts).toHaveLength(2);
      expect(allCharts[0].title).toBe('EMA line');
      expect(allCharts[1].title).toBe('RSI heatmap');
    });
  });

  // ── FAIL-OPEN 降级测试 ──────────────────────────────

  describe('FAIL-OPEN fallback', () => {
    it('should return degraded content when SynthesizerAgent IPC fails', async () => {
      setMockResponse(JSON.stringify({
        ok: false,
        error: 'import_failed: ModuleNotFoundError',
      }));

      const results = [makeSkillResult()];
      const output = await agent.summarize('market_query', results);

      expect(output.content.degraded).toBe(true);
      expect(output.content.reason).toContain('IPC 失败');
      expect(output.content.summaries).toHaveLength(1);
    });

    it('should compute confidence from SkillResults when no cards and no C-Drive', async () => {
      setMockResponse(JSON.stringify({
        ok: false,
        error: 'failed',
      }));

      const results = [makeSkillResult({ confidence: 0.35 })];
      const output = await agent.summarize('market_query', results);

      expect(output.confidence).toBe(0.35);
      expect(output.human_review_required).toBe(true);
    });

    it('should handle empty results gracefully', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: [] },
      }));

      const output = await agent.summarize('market_query', []);

      expect(output.confidence).toBe(0.3);
      expect(output.human_review_required).toBe(true);
      expect(output.sources).toEqual([]);
    });
  });

  // ── FinalOutput 结构验证 ────────────────────────────

  describe('FinalOutput structure', () => {
    it('should return valid FinalOutput with all required fields', async () => {
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards: makeMockCards() },
      }));

      const output = await agent.summarize(
        'market_query',
        [makeSkillResult()],
        makeMockCDrive(),
      );

      expect(output).toHaveProperty('intent_type');
      expect(output).toHaveProperty('content');
      expect(output).toHaveProperty('confidence');
      expect(output).toHaveProperty('sources');
      expect(output).toHaveProperty('execution_time_ms');
      expect(output).toHaveProperty('human_review_required');
      expect(typeof output.execution_time_ms).toBe('number');
      expect(output.execution_time_ms).toBeGreaterThanOrEqual(0);
    });
  });

  // ── 真实 handler 返回格式兼容性 (修复 cards 字段读取 bug) ─────

  describe('real handler format compatibility (top-level cards)', () => {
    it('should read top-level cards (not output.cards) — matches synthesizer handler E2E', async () => {
      // 真实 handle_synthesizer_agent 返回 {ok:true, cards:[...]}
      // 不是 {ok:true, output:{cards:[...]}}
      const cards = makeMockCards();
      setMockResponse(JSON.stringify({
        ok: true,
        cards,  // 顶层 cards（真实格式）
      }));

      const output = await agent.summarize('market_query', [makeSkillResult()]);

      expect(Array.isArray(output.content)).toBe(true);
      expect(output.content).toHaveLength(2);
      expect(output.content[0].card_type).toBe('insight');
    });

    it('should still work with output.cards wrapped format (defensive compat)', async () => {
      const cards = makeMockCards();
      setMockResponse(JSON.stringify({
        ok: true,
        output: { cards },  // 包装格式（理论兼容）
      }));

      const output = await agent.summarize('market_query', [makeSkillResult()]);

      expect(Array.isArray(output.content)).toBe(true);
      expect(output.content).toHaveLength(2);
    });
  });
});
