/**
 * v1-protocol.test.ts — T-C3 SSE v1 契约（SPEC C §3.3 六条客户端规则）
 */

import {
  normalizeSSEEvent,
  SSEDeduper,
  SeqTracker,
  UnknownTypeCounter,
  OrderMonitor,
  SSEProtocolState,
} from '@/lib/sse/v1-protocol';

describe('normalizeSSEEvent: v1 与 legacy 归一化', () => {
  it('保留完整 v1 事件字段且 legacy=false', () => {
    const event = normalizeSSEEvent({
      event: 'progress',
      id: 'evt-1',
      data: {
        seq: 3,
        trace_id: 'trace-1',
        session_id: 'sess-1',
        ts: 1000,
        payload: { step: 'a' },
      },
    });

    expect(event).toMatchObject({
      id: 'evt-1',
      seq: 3,
      type: 'progress',
      trace_id: 'trace-1',
      session_id: 'sess-1',
      ts: 1000,
      payload: { step: 'a' },
      legacy: false,
    });
  });

  it('旧事件（无 seq）标记 legacy=true', () => {
    const event = normalizeSSEEvent({ event: 'text_delta', data: { delta: 'hi' } });
    expect(event.legacy).toBe(true);
    expect(event.seq).toBe(-1);
    expect(event.type).toBe('text_delta');
  });

  it('id 缺失时生成稳定去重键（同输入两次一致）', () => {
    const frame = { event: 'thinking', data: { content: 'abc', ts: 42 } };
    const a = normalizeSSEEvent(frame);
    const b = normalizeSSEEvent(frame);
    expect(a.id).toBe(b.id);
    expect(a.id).toContain('thinking:42:');
  });

  it('data.type 缺失时回退 unknown', () => {
    const event = normalizeSSEEvent({ data: {} });
    expect(event.type).toBe('unknown');
  });
});

describe('SSEDeduper: LRU 200 去重', () => {
  it('重复 id 第二次返回 seen=true 并计数', () => {
    const d = new SSEDeduper();
    expect(d.seen('a')).toBe(false);
    expect(d.seen('a')).toBe(true);
    expect(d.duplicates).toBe(1);
  });

  it('超过容量后最早 id 被淘汰，不再视为重复', () => {
    const d = new SSEDeduper(3);
    d.seen('a');
    d.seen('b');
    d.seen('c');
    d.seen('d'); // 淘汰 a
    expect(d.seen('a')).toBe(false);
    expect(d.size).toBe(3);
  });
});

describe('SeqTracker: 乱序丢弃', () => {
  it('同 session 的 seq 回退 → 乱序', () => {
    const t = new SeqTracker();
    expect(t.isOutOfOrder({ seq: 5, session_id: 's1', legacy: false })).toBe(false);
    expect(t.isOutOfOrder({ seq: 3, session_id: 's1', legacy: false })).toBe(true);
    expect(t.outOfOrder).toBe(1);
  });

  it('同 seq 重复同样视为乱序', () => {
    const t = new SeqTracker();
    t.isOutOfOrder({ seq: 5, session_id: 's1', legacy: false });
    expect(t.isOutOfOrder({ seq: 5, session_id: 's1', legacy: false })).toBe(true);
  });

  it('缺 session_id / legacy / 负 seq 不参与判定', () => {
    const t = new SeqTracker();
    expect(t.isOutOfOrder({ seq: 5, session_id: undefined, legacy: false })).toBe(false);
    expect(t.isOutOfOrder({ seq: 5, session_id: 's1', legacy: true })).toBe(false);
    expect(t.isOutOfOrder({ seq: -1, session_id: 's1', legacy: false })).toBe(false);
    expect(t.outOfOrder).toBe(0);
  });

  it('getLastSeq 可读取最后序号（monitor 重连用）', () => {
    const t = new SeqTracker();
    t.isOutOfOrder({ seq: 7, session_id: 's1', legacy: false });
    expect(t.getLastSeq('s1')).toBe(7);
  });
});

describe('UnknownTypeCounter: 未知类型忽略计数', () => {
  it('未知 type 计数 +1', () => {
    const c = new UnknownTypeCounter();
    expect(c.isUnknown('totally_unknown')).toBe(true);
    expect(c.unknownCount).toBe(1);
    expect(c.types).toEqual(['totally_unknown']);
  });

  it('v1 8 类与交易域扩展类型都不算未知', () => {
    const c = new UnknownTypeCounter();
    for (const type of [
      'started',
      'thinking',
      'progress',
      'step',
      'report',
      'done',
      'error',
      'heartbeat',
      'cross_validation',
      'text_delta',
      'data_card',
      'artifact_ref',
      'action_required',
    ]) {
      expect(c.isUnknown(type)).toBe(false);
    }
    expect(c.unknownCount).toBe(0);
  });
});

describe('OrderMonitor: 顺序告警不阻断', () => {
  it('done 出现在 started 之前只 warn 一次', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const m = new OrderMonitor();
    m.check('done', 'e1');
    m.check('done', 'e2');
    const messages = warn.mock.calls.map((c) => String(c[0]));
    expect(messages.filter((m2) => m2.includes('started 之前')).length).toBe(1);
    expect(m.isTerminated).toBe(true);
    warn.mockRestore();
  });

  it('heartbeat 不产生顺序告警', () => {
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => {});
    const m = new OrderMonitor();
    m.check('heartbeat', 'e1');
    expect(warn).not.toHaveBeenCalled();
    warn.mockRestore();
  });
});

describe('SSEProtocolState: 聚合丢弃策略', () => {
  it('重复 id 与乱序 seq 都被丢弃，正常事件通过且更新 lastEventId', () => {
    const state = new SSEProtocolState();

    const first = state.process({
      event: 'started',
      id: 'e1',
      data: { seq: 1, session_id: 's1', trace_id: 't1' },
    });
    expect(first).not.toBeNull();
    expect(state.lastEventId).toBe('e1');

    const duplicate = state.process({
      event: 'started',
      id: 'e1',
      data: { seq: 1, session_id: 's1', trace_id: 't1' },
    });
    expect(duplicate).toBeNull();

    const outOfOrder = state.process({
      event: 'progress',
      id: 'e0',
      data: { seq: 0, session_id: 's1', trace_id: 't1' },
    });
    expect(outOfOrder).toBeNull();

    const unknown = state.process({ event: 'weird_type', id: 'e9', data: { seq: 9, session_id: 's1' } });
    expect(unknown).toBeNull();

    const ok = state.process({
      event: 'done',
      id: 'e2',
      data: { seq: 2, session_id: 's1', trace_id: 't1' },
    });
    expect(ok).not.toBeNull();
    expect(state.stats).toMatchObject({
      duplicates: 1,
      outOfOrder: 1,
      unknownTypes: 1,
      lastEventId: 'e2',
    });
  });

  it('legacy 事件（无 seq）正常通过，不被乱序丢弃', () => {
    const state = new SSEProtocolState();
    const legacy = state.process({ event: 'text_delta', data: { delta: 'a' } });
    expect(legacy).not.toBeNull();
    expect(legacy?.legacy).toBe(true);
  });
});
