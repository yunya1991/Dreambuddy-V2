// ============================================
// sse-to-parts 适配器测试 — 交易域 SSE 事件 → AgentPart
// ============================================

import { sseEventToParts, sseEventsToParts } from '../sse-to-parts';

describe('sseEventToParts', () => {
  it('thinking → reasoning', () => {
    expect(sseEventToParts('thinking', { content: '正在分析' })).toEqual([
      { type: 'reasoning', text: '正在分析' },
    ]);
  });

  it('text_delta → text', () => {
    expect(sseEventToParts('text_delta', { delta: '结论' })).toEqual([{ type: 'text', text: '结论' }]);
  });

  it('progress 状态映射：running / done / failed', () => {
    const running = sseEventToParts('progress', { stepId: 's1', stepName: '取数', status: 'running' });
    expect(running[0]).toMatchObject({ type: 'tool', callId: 's1', toolName: '取数', state: 'running' });

    const done = sseEventToParts('progress', { stepId: 's1', stepName: '取数', status: 'done', durationMs: 1200 });
    expect(done[0]).toMatchObject({ type: 'tool', state: 'success', durationMs: 1200 });

    const failed = sseEventToParts('progress', { stepId: 's1', stepName: '取数', status: 'failed' });
    expect(failed[0]).toMatchObject({ type: 'tool', state: 'error' });
  });

  it('artifact_ref → artifact（report/chart/file 归类）', () => {
    expect(sseEventToParts('artifact_ref', { artifactId: 'art_1', title: '日报', artifactType: 'report' })).toEqual([
      { type: 'artifact', artifactId: 'art_1', title: '日报', kind: 'report' },
    ]);
    expect(sseEventToParts('artifact_ref', { artifactId: 'art_2', title: 'K线', artifactType: 'chart' })[0]).toMatchObject({
      kind: 'chart',
    });
    expect(sseEventToParts('artifact_ref', { artifactId: 'art_3', title: '附件' })[0]).toMatchObject({ kind: 'file' });
  });

  it('data_card → artifact', () => {
    expect(sseEventToParts('data_card', { cardId: 'c1', cardType: 'market', title: '行情' })).toEqual([
      { type: 'artifact', artifactId: 'c1', title: '行情', kind: 'chart' },
    ]);
  });

  it('cross_validation → verification（gatePassed=false 为 BLOCK）', () => {
    expect(
      sseEventToParts('cross_validation', { gatePassed: false, issuesFound: ['口径不一致'] }),
    ).toEqual([{ type: 'verification', verdict: 'BLOCK', evidenceRefs: ['口径不一致'] }]);

    expect(sseEventToParts('cross_validation', { gatePassed: true })[0]).toMatchObject({ verdict: 'PASS' });
  });

  it('action_required → tool(pending)', () => {
    const [part] = sseEventToParts('action_required', { action: 'approve_trade', message: '待确认' }, 2);
    expect(part).toMatchObject({ type: 'tool', callId: 'action_2', toolName: 'approve_trade', state: 'pending' });
  });

  it('done → text（无 content 时忽略）', () => {
    expect(sseEventToParts('done', { content: '已完成' })).toEqual([{ type: 'text', text: '已完成' }]);
    expect(sseEventToParts('done', {})).toEqual([]);
  });

  it('error → text；blocked 时追加 verification(BLOCK)', () => {
    expect(sseEventToParts('error', { error: '超时' })).toEqual([{ type: 'text', text: '错误：超时' }]);
    expect(sseEventToParts('error', { message: '越权', blocked: true })).toEqual([
      { type: 'text', text: '错误：越权' },
      { type: 'verification', verdict: 'BLOCK', evidenceRefs: ['越权'] },
    ]);
  });

  it('started 与未知事件忽略，不抛错', () => {
    expect(sseEventToParts('started', { message: '开始' })).toEqual([]);
    expect(sseEventToParts('mystery_event', { any: 1 })).toEqual([]);
  });
});

describe('sseEventsToParts', () => {
  it('按事件顺序扁平输出', () => {
    const parts = sseEventsToParts([
      { type: 'thinking', data: { content: '思考' } },
      { type: 'text_delta', data: { delta: '答案' } },
      { type: 'artifact_ref', data: { artifactId: 'a1', title: '报告', artifactType: 'report' } },
    ]);
    expect(parts.map((p) => p.type)).toEqual(['reasoning', 'text', 'artifact']);
  });
});
