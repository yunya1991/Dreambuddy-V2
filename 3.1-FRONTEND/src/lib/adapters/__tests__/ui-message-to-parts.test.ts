// ============================================
// ui-message-to-parts 适配器测试 — AI SDK UIMessage.parts → AgentPart
// ============================================

import { uiMessageToParts } from '../ui-message-to-parts';

describe('uiMessageToParts', () => {
  it('映射 text / reasoning', () => {
    const parts = uiMessageToParts({
      parts: [
        { type: 'text', text: '你好' },
        { type: 'reasoning', text: '先查数据' },
      ],
    });
    expect(parts).toEqual([
      { type: 'text', text: '你好' },
      { type: 'reasoning', text: '先查数据' },
    ]);
  });

  it('映射 tool-* 四态', () => {
    const parts = uiMessageToParts({
      parts: [
        { type: 'tool-recall', toolCallId: 't1', state: 'input-streaming', input: { context: 'x' } },
        { type: 'tool-recall', toolCallId: 't2', state: 'input-available', input: { context: 'y' } },
        { type: 'tool-recall', toolCallId: 't3', state: 'output-available', output: { ok: true } },
        { type: 'tool-recall', toolCallId: 't4', state: 'output-error', errorText: 'boom' },
      ],
    });

    expect(parts).toHaveLength(4);
    expect(parts[0]).toMatchObject({ type: 'tool', toolName: 'recall', state: 'running', args: { context: 'x' } });
    expect(parts[1]).toMatchObject({ state: 'running' });
    expect(parts[2]).toMatchObject({ state: 'success', result: { ok: true } });
    expect(parts[3]).toMatchObject({ state: 'error', error: 'boom' });
  });

  it('忽略 step-start 等未知 part 与空消息', () => {
    expect(
      uiMessageToParts({ parts: [{ type: 'step-start' }, { type: 'source-url' }, { type: 'text', text: '只留文本' }] }),
    ).toEqual([{ type: 'text', text: '只留文本' }]);
    expect(uiMessageToParts(null)).toEqual([]);
    expect(uiMessageToParts({})).toEqual([]);
  });

  it('未知 state 降级为 pending', () => {
    const [part] = uiMessageToParts({ parts: [{ type: 'tool-x', state: 'weird' }] });
    expect(part).toMatchObject({ state: 'pending', callId: 'tool_0' });
  });
});
