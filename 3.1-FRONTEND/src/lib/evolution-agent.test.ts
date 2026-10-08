/**
 * EvolutionAgent 单元测试
 * 验证: 三大维度进化 + 异步触发 + FAIL-OPEN + 开关 + 非阻塞
 */

import { EventEmitter } from 'events';

// Mock child_process.spawn
let _spawnExitCode = 0;
let _spawnStdout = '';
let _spawnDelay = 0;
let _spawnCalls: string[] = [];

jest.mock('child_process', () => ({
  spawn: jest.fn((_cmd: string, args: string[]) => {
    _spawnCalls.push(args.join(' '));
    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = jest.fn();

    setTimeout(() => {
      if (_spawnStdout) {
        child.stdout.emit('data', Buffer.from(_spawnStdout));
      }
      child.emit('close', _spawnExitCode);
    }, _spawnDelay);

    return child;
  }),
}));

// Mock fs
jest.mock('fs', () => ({
  existsSync: jest.fn(() => true),
  mkdirSync: jest.fn(),
  writeFileSync: jest.fn(),
}));

// Mock cognitive-client
jest.mock('./cognitive-client', () => ({
  callCognitive: jest.fn(),
}));

// Mock knowledge-ingest
jest.mock('./knowledge-ingest', () => ({
  getKnowledgeIngester: jest.fn(() => ({
    ingest: jest.fn(),
  })),
}));

import { spawn } from 'child_process';
import { callCognitive } from './cognitive-client';
import { getKnowledgeIngester } from './knowledge-ingest';
import { EvolutionAgent, getEvolutionAgent, type TaskResult } from './evolution-agent';

function resetMocks() {
  _spawnExitCode = 0;
  _spawnStdout = '';
  _spawnDelay = 0;
  _spawnCalls = [];
  (spawn as any).mockClear();
  (callCognitive as any).mockReset();
  (getKnowledgeIngester as any).mockClear();
}

function setSpawnResponse(exitCode: number, stdout: string = '', delay: number = 0) {
  _spawnExitCode = exitCode;
  _spawnStdout = stdout;
  _spawnDelay = delay;
}

function makeTaskResult(overrides: Partial<TaskResult> = {}): TaskResult {
  return {
    intent_type: 'deep_analysis',
    skill_ids: ['dream-research-workflow'],
    final_output: '调研报告内容',
    is_research_type: true,
    success: true,
    ...overrides,
  };
}

// ============================================================
// 1. 开关测试
// ============================================================

describe('EvolutionAgent disabled', () => {
  beforeEach(() => {
    resetMocks();
    process.env.EVOLUTION_ENABLED = 'false';
  });

  it('should skip when disabled', async () => {
    const agent = new EvolutionAgent();
    const report = await agent.trigger(makeTaskResult());
    expect(report.triggered).toBe(false);
    expect(report.cognitive_evolution.triggered).toBe(false);
    expect(report.skill_evolution.triggered).toBe(false);
    expect(report.knowledge_evolution.triggered).toBe(false);
    expect(spawn).not.toHaveBeenCalled();
  });

  it('triggerAsync should be noop when disabled', () => {
    const agent = new EvolutionAgent();
    agent.triggerAsync(makeTaskResult());
    expect(spawn).not.toHaveBeenCalled();
  });
});

// ============================================================
// 2. 正常触发测试
// ============================================================

describe('EvolutionAgent trigger', () => {
  beforeEach(() => {
    resetMocks();
    process.env.EVOLUTION_ENABLED = 'true';
    process.env.EVOLUTION_NO_LLM = 'true';
  });

  it('should trigger all three dimensions', async () => {
    setSpawnResponse(0, JSON.stringify({ role: 'evolution', dry_run: true, no_llm: true, per_role: {} }));
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: true, stored_path: '/test/path.md', errors: [] }),
    });

    const agent = new EvolutionAgent();
    const report = await agent.trigger(makeTaskResult());

    expect(report.triggered).toBe(true);
    expect(report.cognitive_evolution.triggered).toBe(true);
    expect(report.cognitive_evolution.success).toBe(true);
    expect(report.cognitive_evolution.role).toBe('evolution');

    expect(report.skill_evolution.triggered).toBe(true);
    expect(report.skill_evolution.verified_count).toBe(1); // 1 skill in task

    expect(report.knowledge_evolution.triggered).toBe(true);
    expect(report.knowledge_evolution.ingested).toBe(true);
    expect(report.knowledge_evolution.stored_path).toBe('/test/path.md');
  });

  it('should call cognitive_evolution_scheduler with --dry-run --no-llm', async () => {
    setSpawnResponse(0, JSON.stringify({ role: 'verifier' }));
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: false, errors: [] }),
    });

    const agent = new EvolutionAgent();
    await agent.trigger(makeTaskResult({ is_research_type: false }));

    expect(_spawnCalls.length).toBeGreaterThan(0);
    expect(_spawnCalls[0]).toContain('--dry-run');
    expect(_spawnCalls[0]).toContain('--no-llm');
    expect(_spawnCalls[0]).toContain('--role');
    expect(_spawnCalls[0]).toContain('auto');
  });
});

// ============================================================
// 3. FAIL-OPEN 测试
// ============================================================

describe('EvolutionAgent FAIL-OPEN', () => {
  beforeEach(() => {
    resetMocks();
    process.env.EVOLUTION_ENABLED = 'true';
    process.env.EVOLUTION_NO_LLM = 'true';
  });

  it('should FAIL-OPEN when cognitive evolution spawn fails', async () => {
    setSpawnResponse(1); // scheduler exits with error
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: true, stored_path: '/p.md', errors: [] }),
    });

    const agent = new EvolutionAgent();
    const report = await agent.trigger(makeTaskResult());

    expect(report.cognitive_evolution.success).toBe(false);
    expect(report.cognitive_evolution.error).toContain('exit_1');
    // Other dimensions should still execute
    expect(report.skill_evolution.verified_count).toBe(1);
    expect(report.knowledge_evolution.ingested).toBe(true);
  });

  it('should FAIL-OPEN when verify fails', async () => {
    setSpawnResponse(0, JSON.stringify({ role: 'evolution' }));
    (callCognitive as any).mockResolvedValue({ ok: false, degraded: true, error: 'verify_failed' });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: true, stored_path: '/p.md', errors: [] }),
    });

    const agent = new EvolutionAgent();
    const report = await agent.trigger(makeTaskResult());

    expect(report.skill_evolution.verified_count).toBe(0);
    expect(report.skill_evolution.errors.length).toBeGreaterThan(0);
    // Other dimensions should still execute
    expect(report.cognitive_evolution.success).toBe(true);
    expect(report.knowledge_evolution.ingested).toBe(true);
  });

  it('should not trigger knowledge evolution for non-research tasks', async () => {
    setSpawnResponse(0, JSON.stringify({ role: 'evolution' }));
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: true, stored_path: '/p.md', errors: [] }),
    });

    const agent = new EvolutionAgent();
    const report = await agent.trigger(makeTaskResult({ is_research_type: false }));

    expect(report.knowledge_evolution.ingested).toBe(false);
    // KnowledgeIngester should NOT be called for non-research tasks
    expect(getKnowledgeIngester).not.toHaveBeenCalled();
  });
});

// ============================================================
// 4. 异步触发测试
// ============================================================

describe('EvolutionAgent triggerAsync', () => {
  beforeEach(() => {
    resetMocks();
    process.env.EVOLUTION_ENABLED = 'true';
    process.env.EVOLUTION_NO_LLM = 'true';
  });

  it('should fire-and-forget (not block)', async () => {
    setSpawnResponse(0, JSON.stringify({ role: 'evolution' }), 50); // 50ms delay
    (callCognitive as any).mockResolvedValue({ ok: true, data: {} });
    (getKnowledgeIngester as any).mockReturnValue({
      ingest: jest.fn().mockResolvedValue({ success: false, errors: [] }),
    });

    const agent = new EvolutionAgent();
    const start = Date.now();
    agent.triggerAsync(makeTaskResult());
    const elapsed = Date.now() - start;

    // Should return almost immediately (not wait for evolution)
    expect(elapsed).toBeLessThan(50);
  });
});

// ============================================================
// 5. 单例测试
// ============================================================

describe('getEvolutionAgent', () => {
  it('should return singleton', () => {
    const a = getEvolutionAgent();
    const b = getEvolutionAgent();
    expect(a).toBe(b);
  });
});
