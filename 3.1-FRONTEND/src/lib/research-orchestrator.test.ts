/**
 * ResearchOrchestrator 单元测试
 * 验证: 状态机流转 + 确认门 + 回退 + 子 SKILL 调度 + 认知闭环
 */

// Mock cognitive-client
jest.mock('./cognitive-client', () => ({
  callCognitive: jest.fn(),
}));

import { callCognitive } from './cognitive-client';
import { ResearchOrchestrator, getResearchOrchestrator } from './research-orchestrator';

function resetMocks() {
  (callCognitive as any).mockReset();
  (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
}

// ============================================================
// 1. 启动测试
// ============================================================

describe('ResearchOrchestrator.start', () => {
  beforeEach(() => resetMocks());

  it('should start with PROBLEM stage', async () => {
    const orch = new ResearchOrchestrator();
    const result = await orch.start('如何设计新的交易系统架构？');

    expect(result.stage).toBe('PROBLEM');
    expect(result.skill_called).toBe('dream-contradiction-theory');
    expect(result.needs_confirmation).toBe(true);
    expect(result.recommended_next).toContain('confirm');
    expect(orch.getCurrentStage()).toBe('PROBLEM');
  });

  it('should record experience on start', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('测试问题');

    expect(callCognitive).toHaveBeenCalledWith('record', expect.objectContaining({
      tags: expect.stringContaining('research-orchestrator'),
    }));
  });

  it('should detect complex problem and use qwen-eval for research', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('这是一个跨系统多模块的架构重构迁移问题，需要全量修改核心底层逻辑');

    // Confirm PROBLEM → RESEARCH
    const result = await orch.confirm();

    expect(result.stage).toBe('RESEARCH');
    expect(result.skill_called).toBe('dream-qwen-eval-collab');
  });

  it('should detect simple problem and use research-workflow', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('简单问题');

    const result = await orch.confirm();

    expect(result.stage).toBe('RESEARCH');
    expect(result.skill_called).toBe('dream-research-workflow');
  });
});

// ============================================================
// 2. 状态机流转测试
// ============================================================

describe('ResearchOrchestrator state machine', () => {
  beforeEach(() => resetMocks());

  it('should flow through all 5 stages', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('测试问题');

    // PROBLEM → RESEARCH
    let result = await orch.confirm();
    expect(result.stage).toBe('RESEARCH');
    expect(result.skill_called).toBe('dream-research-workflow');

    // RESEARCH → SPEC
    result = await orch.confirm();
    expect(result.stage).toBe('SPEC');
    expect(result.skill_called).toBe('dream-qwen-eval-collab');

    // SPEC → REVIEW
    result = await orch.confirm();
    expect(result.stage).toBe('REVIEW');
    expect(result.skill_called).toBe('dream-science-peer-review');

    // REVIEW → PLAN
    result = await orch.confirm();
    expect(result.stage).toBe('PLAN');
    expect(result.skill_called).toBe('dream-eng-mgmt-workflow');

    // PLAN → DONE
    result = await orch.confirm();
    expect(result.stage).toBe('DONE');
    expect(result.needs_confirmation).toBe(false);
    expect(orch.getCurrentStage()).toBe('DONE');
  });

  it('should return error when confirm called before start', async () => {
    const orch = new ResearchOrchestrator();
    const result = await orch.confirm();

    expect(result.error).toContain('未启动');
  });

  it('should return done when confirming at DONE stage', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('问题');
    for (let i = 0; i < 5; i++) await orch.confirm(); // through all stages

    const result = await orch.confirm();
    expect(result.stage).toBe('DONE');
    expect(result.needs_confirmation).toBe(false);
  });
});

// ============================================================
// 3. 回退测试
// ============================================================

describe('ResearchOrchestrator rollback', () => {
  beforeEach(() => resetMocks());

  it('should rollback from REVIEW to SPEC', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('问题');
    await orch.confirm(); // PROBLEM → RESEARCH
    await orch.confirm(); // RESEARCH → SPEC
    await orch.confirm(); // SPEC → REVIEW

    const result = await orch.rollback('SPEC');

    expect(result.stage).toBe('SPEC');
    expect(result.skill_called).toBe('dream-qwen-eval-collab');
    expect(orch.getCurrentStage()).toBe('SPEC');
  });

  it('should not allow rollback from PROBLEM', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('问题');

    const result = await orch.rollback('RESEARCH');

    expect(result.error).toContain('不允许');
  });

  it('should not allow skipping stages via rollback', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('问题');
    await orch.confirm(); // RESEARCH

    // Cannot rollback to PLAN from RESEARCH (forward direction not allowed)
    const result = await orch.rollback('PLAN');
    expect(result.error).toBeDefined();
  });

  it('should record rollback experience', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('问题');
    await orch.confirm(); // RESEARCH
    await orch.confirm(); // SPEC
    await orch.confirm(); // REVIEW

    (callCognitive as any).mockClear();
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });

    await orch.rollback('SPEC');

    expect(callCognitive).toHaveBeenCalledWith('record', expect.objectContaining({
      content: expect.stringContaining('rollback'),
    }));
  });
});

// ============================================================
// 4. 状态查询测试
// ============================================================

describe('ResearchOrchestrator getStatus', () => {
  beforeEach(() => resetMocks());

  it('should return current status', async () => {
    const orch = new ResearchOrchestrator();
    await orch.start('测试问题');
    await orch.confirm(); // RESEARCH

    const status = orch.getStatus();

    expect(status.current_stage).toBe('RESEARCH');
    expect(status.problem).toBe('测试问题');
    expect(status.completed_stages).toContain('PROBLEM');
    expect(status.started_at).toBeGreaterThan(0);
  });
});

// ============================================================
// 5. 认知闭环测试
// ============================================================

describe('ResearchOrchestrator cognitive loop', () => {
  beforeEach(() => resetMocks());

  it('should call verify when reaching DONE', async () => {
    (callCognitive as any).mockClear();
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });

    const orch = new ResearchOrchestrator();
    await orch.start('问题');
    for (let i = 0; i < 5; i++) await orch.confirm(); // all stages → DONE

    // Should have called verify
    const verifyCalls = (callCognitive as any).mock.calls.filter(
      (c: any[]) => c[0] === 'verify'
    );
    expect(verifyCalls.length).toBeGreaterThan(0);
  });
});

// ============================================================
// 6. 单例测试
// ============================================================

describe('getResearchOrchestrator', () => {
  it('should return singleton', () => {
    const a = getResearchOrchestrator();
    const b = getResearchOrchestrator();
    expect(a).toBe(b);
  });
});
