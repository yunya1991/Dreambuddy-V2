/**
 * 执行链 trace 基础件测试（PLAN Phase 2 T2-1~T2-4）
 * 契约来源：1-ARCHITECTURE/registry/scripts/bcl_gate_check.py G-BCL-3
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import { newTraceId, isValidTraceId } from '@/lib/trace-id';
import { traceStage, getTraceLedgerPath, type TraceStage } from '@/lib/execution-trace';

describe('trace-id', () => {
  it('生成合法 trace 且不使用 task_id 格式', () => {
    const traceId = newTraceId();
    expect(isValidTraceId(traceId)).toBe(true);
    expect(traceId.startsWith('task_')).toBe(false);
  });

  it('1000 次生成全局唯一', () => {
    const ids = new Set(Array.from({ length: 1000 }, () => newTraceId()));
    expect(ids.size).toBe(1000);
  });
});

describe('execution-trace 台账', () => {
  const ledger = path.join(os.tmpdir(), `bcl_trace_test_${process.pid}_${Date.now()}.jsonl`);
  const prev = process.env.BCL_TRACE_RECORDS_PATH;

  beforeEach(() => {
    process.env.BCL_TRACE_RECORDS_PATH = ledger;
  });

  afterEach(() => {
    fs.rmSync(ledger, { force: true });
  });

  afterAll(() => {
    if (prev === undefined) delete process.env.BCL_TRACE_RECORDS_PATH;
    else process.env.BCL_TRACE_RECORDS_PATH = prev;
  });

  it('路径可由环境变量覆盖', () => {
    expect(getTraceLedgerPath()).toBe(ledger);
  });

  it('五阶段行均可写入且含 G-BCL-3 所需字段', () => {
    const stages: TraceStage[] = ['created', 'route', 'execute', 'accept', 'settle'];
    for (const stage of stages) {
      traceStage({ task_id: 'task_1', trace_id: '20261113-120000-FE-abc12345', stage, intent: 'data_query' });
    }
    const rows = fs
      .readFileSync(ledger, 'utf-8')
      .split('\n')
      .filter(Boolean)
      .map((line) => JSON.parse(line));
    expect(rows.map((r) => r.stage)).toEqual(stages);
    expect(rows.every((r) => r.task_id === 'task_1' && r.trace_id === '20261113-120000-FE-abc12345')).toBe(true);
    expect(rows.every((r) => typeof r.ts === 'string' && r.source === 'execution_chain')).toBe(true);
  });

  it('降级行必须携带 degraded_reason（门禁要求非空）', () => {
    traceStage({
      task_id: 'task_2',
      trace_id: '20261113-120000-FE-def65432',
      stage: 'settle',
      degraded_reason: 'cognitive_unavailable',
    });
    const row = JSON.parse(fs.readFileSync(ledger, 'utf-8').trim());
    expect(row.degraded_reason).toBe('cognitive_unavailable');
  });

  it('写入失败不抛出（FAIL-OPEN）', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    process.env.BCL_TRACE_RECORDS_PATH = path.join('/dev/null', 'cannot_write.jsonl');
    expect(() => traceStage({ task_id: 'task_3', trace_id: '20261113-120000-FE-ghi00000', stage: 'created' })).not.toThrow();
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });
});
