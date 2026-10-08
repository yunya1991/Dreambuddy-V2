/**
 * SkillOrchestrationExecutor 集成测试
 * ====================================
 * 验证 M2 集成层编排逻辑:
 *   1. 双轨开关 isSkillOrchestrationEnabled
 *   2. executeSkillOrchestration 完整调用链（mock M2 组件）
 *   3. FAIL-OPEN 降级（组件失败返回 null）
 *   4. 进度事件透传
 *   5. C-Drive 禁用开关
 */

// 共享 mock 单例（方便运行时覆写）
const mockCtxBuilder = {
  build: jest.fn().mockResolvedValue({
    experiences: [{ memory_id: 'm1', content: 'exp1', quality_level: 'B', confidence: 0.5, relevance_score: 0.8 }],
    knowledge: [{ chunk_id: 'k1', content: 'know1', source_type: 'strategy_doc', domain: 'trading', score: 0.9 }],
    references: [],
    skill_candidates: [],
    built_at: Date.now(),
    intent_type: 'market_query',
  }),
  isContextUsed: jest.fn().mockReturnValue(true),
};

const mockSelector = {
  select: jest.fn().mockReturnValue({
    skill_ids: ['dream-backtest'],
    order: ['dream-backtest'],
    params: { symbol: 'BTC-USDT' },
    match_reasons: ['rule_match: 1 SKILLs matched triggers'],
    context: { experiences: [], knowledge: [], references: [], skill_candidates: [], built_at: 0, intent_type: 'market_query' },
    selections: [{ skill_id: 'dream-backtest', match_score: 0.9, match_reasons: ['trigger:backtest'], confidence: 0.9 }],
  }),
};

const mockEngine = {
  execute_plan: jest.fn().mockResolvedValue([
    {
      skill_id: 'dream-backtest',
      content: { signals: [{ name: 'EMA', value: '多头', direction: 'LONG', confidence: 0.8 }], direction: 'LONG', confidence: 0.8 },
      confidence: 0.8,
      source: 'node',
      node_outputs: { technical: { confidence: 0.8 } },
      llm_output: null,
      context_used: true,
      latency_ms: 1200,
    },
  ]),
  execute_skill: jest.fn().mockResolvedValue({
    skill_id: 'technical',
    content: { confidence: 0.7 },
    confidence: 0.7,
    source: 'node',
    node_outputs: {},
    llm_output: null,
    context_used: true,
    latency_ms: 800,
  }),
};

const mockCDrive = {
  decideFromResults: jest.fn().mockResolvedValue({
    action: 'continue',
    reason: 'all good',
    confidence: 0.8,
    suggestions: [],
    bull_argument: null,
    bear_argument: null,
    bull_confidence: null,
    bear_confidence: null,
    jump_to: null,
    supplement_module: null,
    jeval_noul: null,
    steps_executed: [],
    effort_level: 'standard',
    debate_rounds: 0,
    synthesized_cards: [],
    enhancement_hints: [],
    charts: [],
  }),
  shouldSupplement: jest.fn().mockReturnValue(false),
  shouldContinue: jest.fn().mockReturnValue(true),
};

const mockSummary = {
  summarize: jest.fn().mockResolvedValue({
    intent_type: 'market_query',
    content: '## SKILL 编排结果\n\n市场分析完成，方向偏多',
    confidence: 0.75,
    sources: [{ subagent_id: 'technical', source_type: 'node', description: '技术面分析' }],
    execution_time_ms: 2000,
    human_review_required: false,
  }),
};

jest.mock('./cognitive-context-builder', () => ({
  getCognitiveContextBuilder: () => mockCtxBuilder,
}));
jest.mock('./skill-selector', () => ({
  getSkillSelector: () => mockSelector,
}));
jest.mock('./dsh-execution-engine', () => ({
  getDSHExecutionEngine: () => mockEngine,
}));
jest.mock('./c-drive', () => ({
  CDriveCoordinator: jest.fn().mockImplementation(() => mockCDrive),
}));
jest.mock('./summary-agent', () => ({
  SummaryAgent: jest.fn().mockImplementation(() => mockSummary),
}));

import { isSkillOrchestrationEnabled, executeSkillOrchestration } from './skill-orchestration-executor';
import type { TaskFile } from './task-manager';
import type { PlannerProgressEvent } from './planner/planner-types';

describe('SkillOrchestrationExecutor', () => {
  const mockTask: TaskFile = {
    task_id: 'test_task_001',
    session_id: 'sess_001',
    message: '分析BTC行情',
    intent: { type: 'market_query', confidence: 0.85, entities: { symbol: 'BTC' } },
    thinking_mode: 'quick',
    status: 'pending',
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  } as any;

  beforeEach(() => {
    jest.clearAllMocks();
    // 重置默认 mock 实现
    mockCtxBuilder.build.mockResolvedValue({
      experiences: [{ memory_id: 'm1', content: 'exp1', quality_level: 'B', confidence: 0.5, relevance_score: 0.8 }],
      knowledge: [{ chunk_id: 'k1', content: 'know1', source_type: 'strategy_doc', domain: 'trading', score: 0.9 }],
      references: [],
      skill_candidates: [],
      built_at: Date.now(),
      intent_type: 'market_query',
    });
    mockEngine.execute_plan.mockResolvedValue([
      {
        skill_id: 'dream-backtest',
        content: { signals: [{ name: 'EMA', value: '多头', direction: 'LONG', confidence: 0.8 }], direction: 'LONG', confidence: 0.8 },
        confidence: 0.8,
        source: 'node',
        node_outputs: { technical: { confidence: 0.8 } },
        llm_output: null,
        context_used: true,
        latency_ms: 1200,
      },
    ]);
    mockSummary.summarize.mockResolvedValue({
      intent_type: 'market_query',
      content: '## SKILL 编排结果\n\n市场分析完成，方向偏多',
      confidence: 0.75,
      sources: [{ subagent_id: 'technical', source_type: 'node', description: '技术面分析' }],
      execution_time_ms: 2000,
      human_review_required: false,
    });
    process.env.USE_SKILL_ORCHESTRATION = 'true';
  });

  afterEach(() => {
    delete process.env.USE_SKILL_ORCHESTRATION;
    delete process.env.SKILL_ORCH_CDRIVE;
  });

  describe('isSkillOrchestrationEnabled', () => {
    it('应根据 USE_SKILL_ORCHESTRATION 环境变量返回开关状态', () => {
      process.env.USE_SKILL_ORCHESTRATION = 'true';
      expect(isSkillOrchestrationEnabled()).toBe(true);
      process.env.USE_SKILL_ORCHESTRATION = 'false';
      expect(isSkillOrchestrationEnabled()).toBe(false);
      delete process.env.USE_SKILL_ORCHESTRATION;
      expect(isSkillOrchestrationEnabled()).toBe(false);
    });
  });

  describe('executeSkillOrchestration', () => {
    it('应完成完整编排调用链并返回 SkillOrchestrationResult', async () => {
      const events: PlannerProgressEvent[] = [];
      const result = await executeSkillOrchestration(
        mockTask,
        '分析BTC行情',
        'zh',
        (e) => events.push(e),
      );

      expect(result).not.toBeNull();
      expect(result!.content).toContain('SKILL 编排结果');
      expect(result!.confidence).toBe(0.75);
      expect(result!.human_review_required).toBe(false);
      expect(result!.execution_time_ms).toBeGreaterThanOrEqual(0);

      expect(result!.execution_summary.chain_executed).toEqual(
        ['CTX_BUILD', 'SKILL_SELECT', 'DSH_EXEC', 'CDRIVE', 'SUMMARY'],
      );
      expect(result!.execution_summary.total_steps).toBe(5);
      expect(result!.execution_summary.orchestration_mode).toBe('skill_orchestration');
      expect(result!.execution_summary.cdrive_action).toBe('continue');
      expect(result!.execution_summary.source_stats).toEqual({ node: 1, llm: 0, mixed: 0 });

      expect(result!.metadata.executor).toBe('skill_orchestration');
      expect(result!.metadata.skill_ids).toEqual(['dream-backtest']);
      expect(result!.metadata.match_reasons.length).toBeGreaterThan(0);

      expect(events.length).toBeGreaterThanOrEqual(8);
      expect(events.some((e) => e.type === 'plan_created')).toBe(true);
      expect(events.some((e) => e.type === 'step_start' && e.stepId === 'CTX_BUILD')).toBe(true);
      expect(events.some((e) => e.type === 'step_end' && e.stepId === 'DSH_EXEC')).toBe(true);
      expect(events.some((e) => e.type === 'completed')).toBe(true);
    });

    it('C-Drive 禁用时应跳过 CDRIVE 步骤', async () => {
      process.env.SKILL_ORCH_CDRIVE = 'false';

      const result = await executeSkillOrchestration(mockTask, '分析BTC行情', 'zh');

      expect(result).not.toBeNull();
      expect(result!.execution_summary.skipped_steps).toContain('CDRIVE');
      expect(result!.execution_summary.cdrive_action).toBeNull();
      // CDriveCoordinator 不应被调用
      expect(mockCDrive.decideFromResults).not.toHaveBeenCalled();
    });

    it('FAIL-OPEN: 组件异常时应返回 null 降级', async () => {
      // mock CognitiveContextBuilder 抛异常
      mockCtxBuilder.build.mockRejectedValue(new Error('recall timeout'));

      const result = await executeSkillOrchestration(mockTask, '分析BTC行情', 'zh');

      expect(result).toBeNull();
    });

    it('进度事件应包含正确的 stepId 和 timestamp', async () => {
      const events: PlannerProgressEvent[] = [];
      await executeSkillOrchestration(mockTask, '分析BTC行情', 'zh', (e) => events.push(e));

      for (const e of events) {
        expect(typeof e.timestamp).toBe('number');
        expect(e.timestamp).toBeGreaterThan(0);
      }
      const stepEvents = events.filter((e) => e.type === 'step_start' || e.type === 'step_end');
      for (const e of stepEvents) {
        expect(e.stepId).toBeTruthy();
      }
    });
  });
});
