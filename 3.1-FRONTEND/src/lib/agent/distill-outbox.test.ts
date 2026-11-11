/**
 * @jest-environment node
 *
 * distill-outbox 测试：①no-op 模式（BRIDGE_OUTBOX_PATH 未配置）②字段补全
 * （bridge_ts + protocol-bridge tag）③异常 FAIL-OPEN ④session_summary 挂点条件。
 * 全部写临时目录，不触碰真实 outbox。
 */
import fs from 'fs';
import os from 'os';
import path from 'path';
import type { UIMessage } from 'ai';
import {
  appendDistillEntry,
  buildDistillEntry,
  maybeWriteSessionSummary,
} from './distill-outbox';

const ENV_KEY = 'BRIDGE_OUTBOX_PATH';

function userMsg(id: string, text: string): UIMessage {
  return { id, role: 'user', parts: [{ type: 'text', text }] } as UIMessage;
}

describe('distill-outbox', () => {
  let tmpDir: string;
  let outbox: string;
  const savedEnv = process.env[ENV_KEY];

  beforeEach(() => {
    tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'distill-outbox-'));
    outbox = path.join(tmpDir, 'outbox.jsonl');
  });

  afterEach(() => {
    if (savedEnv === undefined) delete process.env[ENV_KEY];
    else process.env[ENV_KEY] = savedEnv;
    fs.rmSync(tmpDir, { recursive: true, force: true });
  });

  it('no-op：BRIDGE_OUTBOX_PATH 未配置时不写入且返回 false', () => {
    delete process.env[ENV_KEY];
    const ok = appendDistillEntry({ type: 'session_summary', content: 'x', source_ref: 'm1' });
    expect(ok).toBe(false);
    expect(fs.existsSync(outbox)).toBe(false);
  });

  it('字段补全：自动补 bridge_ts 与 protocol-bridge tag，tags 去重', () => {
    const entry = buildDistillEntry({
      type: 'session_summary',
      content: '摘要',
      tags: ['protocol-bridge', '52-lobehub'],
      source_ref: 'msg-1',
    });
    expect(entry.bridge_ts).toMatch(/^\d{4}-\d{2}-\d{2}T/);
    expect(entry.tags).toContain('protocol-bridge');
    expect(entry.tags.filter((t) => t === 'protocol-bridge')).toHaveLength(1);
    expect(entry.source_ref).toBe('msg-1');

    process.env[ENV_KEY] = outbox;
    expect(appendDistillEntry(entry)).toBe(true);
    const lines = fs.readFileSync(outbox, 'utf-8').trim().split('\n');
    expect(lines).toHaveLength(1);
    expect(JSON.parse(lines[0])).toMatchObject({ type: 'session_summary', source_ref: 'msg-1' });
  });

  it('异常 FAIL-OPEN：append 抛错时 console.warn 且不抛出', () => {
    process.env[ENV_KEY] = tmpDir; // 指向目录 → appendFileSync 必抛 EISDIR
    const warn = jest.spyOn(console, 'warn').mockImplementation(() => undefined);
    expect(() =>
      appendDistillEntry({ type: 'session_summary', content: 'x', source_ref: 'm1' }),
    ).not.toThrow();
    expect(appendDistillEntry({ type: 'session_summary', content: 'x', source_ref: 'm1' })).toBe(false);
    expect(warn).toHaveBeenCalled();
    warn.mockRestore();
  });

  it('session_summary 挂点：轮数 <2 或无工具结果时不写', () => {
    process.env[ENV_KEY] = outbox;
    expect(
      maybeWriteSessionSummary({ messages: [userMsg('u1', '你好')], hasToolResults: true }),
    ).toBe(false);
    expect(
      maybeWriteSessionSummary({
        messages: [userMsg('u1', '你好'), userMsg('u2', '继续')],
        hasToolResults: false,
      }),
    ).toBe(false);
    expect(fs.existsSync(outbox)).toBe(false);
  });

  it('session_summary 挂点：轮数 ≥2 且有工具结果时写入（C 级类型/≤200 字/source_ref=首消息 id）', () => {
    process.env[ENV_KEY] = outbox;
    const longText = '查'.repeat(250);
    const ok = maybeWriteSessionSummary({
      messages: [userMsg('u-first', longText), userMsg('u2', '继续')],
      hasToolResults: true,
    });
    expect(ok).toBe(true);
    const entry = JSON.parse(fs.readFileSync(outbox, 'utf-8').trim());
    expect(entry.type).toBe('session_summary');
    expect(entry.content.length).toBeLessThanOrEqual(200);
    expect(entry.source_ref).toBe('u-first');
    expect(entry.tags).toContain('protocol-bridge');
    expect(entry.bridge_ts).toBeTruthy();
  });
});
