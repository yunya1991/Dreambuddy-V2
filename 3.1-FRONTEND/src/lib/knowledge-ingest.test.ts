/**
 * KnowledgeIngester 单元测试
 * 验证: 分类逻辑 + 交易决策检测 + 存储逻辑 + 向量化调用 + 认知记录 + FAIL-OPEN + 开关
 */

import { EventEmitter } from 'events';

// Mock child_process.spawn (must be before import)
let _spawnResponses: { stdout?: string; exitCode?: number; delay?: number }[] = [];
let _spawnCallCount = 0;

jest.mock('child_process', () => ({
  spawn: jest.fn((_cmd: string, _args: string[]) => {
    const idx = Math.min(_spawnCallCount, _spawnResponses.length - 1);
    const mock = _spawnResponses[idx] || { exitCode: 0 };
    _spawnCallCount++;

    const child = new EventEmitter();
    child.stdout = new EventEmitter();
    child.stderr = new EventEmitter();
    child.kill = jest.fn();

    setTimeout(() => {
      if (mock.stdout) {
        child.stdout.emit('data', Buffer.from(mock.stdout));
      }
      child.emit('close', mock.exitCode ?? 0);
    }, mock.delay || 0);

    return child;
  }),
}));

// Mock fs
jest.mock('fs', () => ({
  existsSync: jest.fn(() => true),
  mkdirSync: jest.fn(),
  writeFileSync: jest.fn(),
  readFileSync: jest.fn(() => '# Index\n\n| 标题 | 领域 | 标签 | 日期 |\n|------|------|------|------|\n'),
  appendFileSync: jest.fn(),
}));

// Mock cognitive-client
jest.mock('./cognitive-client', () => ({
  callCognitive: jest.fn(),
}));

import { spawn } from 'child_process';
import * as fs from 'fs';
import { callCognitive } from './cognitive-client';
import {
  KnowledgeIngester,
  classifyContent,
  isTradeDecision,
  getKnowledgeIngester,
  type KnowledgeMetadata,
} from './knowledge-ingest';

function resetMocks() {
  _spawnResponses = [];
  _spawnCallCount = 0;
  (spawn as any).mockClear();
  (fs.writeFileSync as any).mockClear();
  (fs.mkdirSync as any).mockClear();
  (callCognitive as any).mockReset();
}

function setSpawnResponse(exitCode: number = 0, stdout?: string) {
  _spawnResponses.push({ exitCode, stdout });
}

function setCognitiveRecordResponse(ok: boolean, id?: string) {
  (callCognitive as any).mockResolvedValue(
    ok ? { ok: true, data: { id: id || 'VM-test-123' } } : { ok: false, degraded: true, error: 'record_failed' }
  );
}

function makeMetadata(overrides: Partial<KnowledgeMetadata> = {}): KnowledgeMetadata {
  return {
    title: 'Test Knowledge',
    domain: 'test',
    tags: ['test'],
    source: 'test-suite',
    category: 'methodology',
    ...overrides,
  };
}

// ============================================================
// 1. 分类逻辑测试
// ============================================================

describe('classifyContent', () => {
  it('should classify trading content', () => {
    const content = '本策略使用马丁格尔加仓，设置止盈止损点位';
    expect(classifyContent(content)).toBe('trading');
  });

  it('should classify external research content', () => {
    const content = '市场调研报告：行业竞品分析';
    expect(classifyContent(content)).toBe('external_research');
  });

  it('should classify AI cognition content', () => {
    const content = '认知记忆系统的进化机制与贝叶斯蒸馏';
    expect(classifyContent(content)).toBe('ai_cognition');
  });

  it('should classify technical analysis content', () => {
    const content = 'K线技术指标MACD与RSI趋势分析';
    expect(classifyContent(content)).toBe('technical');
  });

  it('should classify theory content', () => {
    const content = '博弈论与概率统计的数学模型理论';
    expect(classifyContent(content)).toBe('theory');
  });

  it('should use metadata category if provided', () => {
    const content = '通用内容';
    expect(classifyContent(content, { category: 'trading' })).toBe('trading');
  });

  it('should default to methodology when no keywords match', () => {
    const content = 'generic content about nothing specific';
    expect(classifyContent(content)).toBe('methodology');
  });
});

// ============================================================
// 2. 交易决策检测测试
// ============================================================

describe('isTradeDecision', () => {
  it('should detect trade decision content with direction', () => {
    expect(isTradeDecision('direction: LONG\nentry_price: 50000')).toBe(true);
  });

  it('should detect trade decision with stop_loss', () => {
    expect(isTradeDecision('stop_loss: 45000\ntake_profit: 55000')).toBe(true);
  });

  it('should not detect non-trade content', () => {
    expect(isTradeDecision('这是一份关于市场调研的报告')).toBe(false);
  });

  it('should detect SHORT direction', () => {
    expect(isTradeDecision('direction: SHORT')).toBe(true);
  });
});

// ============================================================
// 3. ingest 主流程测试
// ============================================================

describe('KnowledgeIngester.ingest', () => {
  let ingester: KnowledgeIngester;

  beforeEach(() => {
    resetMocks();
    ingester = new KnowledgeIngester();
    process.env.KNOWLEDGE_INGEST_ENABLED = 'true';
  });

  it('should skip when disabled', async () => {
    process.env.KNOWLEDGE_INGEST_ENABLED = 'false';
    const result = await ingester.ingest('content', makeMetadata());
    expect(result.skipped).toBe(true);
    expect(result.success).toBe(false);
    expect(result.errors).toContain('ingest_disabled');
  });

  it('should skip trade decision content (requires human review)', async () => {
    const result = await ingester.ingest(
      'direction: LONG\nentry_price: 50000',
      makeMetadata()
    );
    expect(result.skipped).toBe(true);
    expect(result.errors).toContain('requires_human_review');
  });

  it('should successfully ingest knowledge with all steps passing', async () => {
    setSpawnResponse(0); // build_index.py succeeds
    setSpawnResponse(0); // index_query_adapter.py reload succeeds
    setCognitiveRecordResponse(true, 'VM-test-456');

    const result = await ingester.ingest(
      '认知记忆系统的贝叶斯蒸馏机制研究',
      makeMetadata({ title: '贝叶斯蒸馏', domain: 'ai_cognition', tags: ['蒸馏'] })
    );

    expect(result.success).toBe(true);
    expect(result.skipped).toBe(false);
    expect(result.stored_path).toBeDefined();
    expect(result.memory_id).toBe('VM-test-456');
    expect(result.vectorized).toBe(true);
    expect(result.index_reloaded).toBe(true);
    expect(result.errors).toHaveLength(0);
    expect(fs.writeFileSync).toHaveBeenCalled();
  });

  it('should FAIL-OPEN on vectorization failure', async () => {
    setSpawnResponse(1); // build_index.py fails
    setSpawnResponse(0); // reload still works
    setCognitiveRecordResponse(true);

    const result = await ingester.ingest(
      '交易策略回测方法论',
      makeMetadata({ title: '回测方法论' })
    );

    expect(result.success).toBe(true); // storage success = overall success
    expect(result.vectorized).toBe(false);
    expect(result.errors.length).toBeGreaterThan(0);
    expect(result.errors.some(e => e.includes('build_index_exit'))).toBe(true);
  });

  it('should FAIL-OPEN on cognitive record failure', async () => {
    setSpawnResponse(0);
    setSpawnResponse(0);
    setCognitiveRecordResponse(false);

    const result = await ingester.ingest(
      '市场调研行业报告',
      makeMetadata({ title: '行业调研', domain: 'external_research' })
    );

    expect(result.success).toBe(true);
    expect(result.memory_id).toBeUndefined();
    expect(result.errors.some(e => e.includes('record'))).toBe(true);
  });

  it('should FAIL-OPEN on index reload failure', async () => {
    setSpawnResponse(0); // build_index
    setSpawnResponse(1); // reload fails
    setCognitiveRecordResponse(true);

    const result = await ingester.ingest(
      '理论模型概率统计',
      makeMetadata({ title: '统计理论' })
    );

    expect(result.success).toBe(true);
    expect(result.index_reloaded).toBe(false);
    expect(result.errors.some(e => e.includes('reload'))).toBe(true);
  });

  it('should store file with correct frontmatter', async () => {
    setSpawnResponse(0);
    setSpawnResponse(0);
    setCognitiveRecordResponse(true);

    await ingester.ingest(
      '认知记忆进化',
      makeMetadata({ title: '进化机制', domain: 'cognition', tags: ['进化', '记忆'] })
    );

    const writeCall = (fs.writeFileSync as any).mock.calls[0];
    expect(writeCall).toBeDefined();
    const content = writeCall[1] as string;
    expect(content).toContain('---');
    expect(content).toContain('title: "进化机制"');
    expect(content).toContain('domain: cognition');
    expect(content).toContain('source: "test-suite"');
    expect(content).toContain('requires_human_review: false');
    expect(content).toContain('认知记忆进化');
  });
});

// ============================================================
// 4. 单例测试
// ============================================================

describe('getKnowledgeIngester', () => {
  it('should return singleton instance', () => {
    const a = getKnowledgeIngester();
    const b = getKnowledgeIngester();
    expect(a).toBe(b);
  });
});
