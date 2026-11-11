/**
 * @jest-environment node
 *
 * mcp-client 集成测试：真实 spawn cognition MCP stdio server。
 * 验证 initialize 握手 / tools:list 含 recall / callTool recall 命中 52-LobeHub 记忆 /
 * callTool record 被服务端拒绝（degraded / isError）。
 */
import { StdioMcpClient } from './mcp-client';

jest.setTimeout(60_000);

describe('StdioMcpClient（真实 stdio 集成）', () => {
  let client: StdioMcpClient;

  beforeAll(() => {
    client = new StdioMcpClient();
  });

  afterAll(() => {
    client.dispose();
  });

  it('initialize 握手成功 + tools/list 含 recall', async () => {
    const tools = await client.listTools();
    expect(Array.isArray(tools)).toBe(true);
    expect(tools.length).toBeGreaterThanOrEqual(7);
    const names = tools.map((t) => t.name);
    expect(names).toContain('recall');
    expect(names).toContain('unified_search');
    const recall = tools.find((t) => t.name === 'recall');
    expect(recall?.inputSchema).toMatchObject({ type: 'object' });
  });

  it('callTool unified_search 三后端统一检索命中数据（Phase 1 收尾挂载验收）', async () => {
    const result = await client.callTool('unified_search', {
      query: '52 LobeHub 协议集成',
      top_k: 3,
    });
    expect(result.isError).not.toBe(true);
    const text = result.content.map((c) => c.text ?? '').join('\n');
    expect(text.length).toBeGreaterThan(0);
    // 统一检索返回 ok:true 且 hits 非空（chroma/recall/41 任一路命中即算）
    expect(text).toMatch(/"ok":\s*true/);
    expect(text).toMatch(/hits/);
  });

  it('callTool recall 返回含 LobeHub 或 52 的记忆内容', async () => {
    const result = await client.callTool('recall', {
      context: 'LobeHub 52 协议集成',
      top_k: 2,
    });
    expect(result.isError).not.toBe(true);
    const text = result.content.map((c) => c.text ?? '').join('\n');
    expect(text.length).toBeGreaterThan(0);
    expect(/LobeHub|52/.test(text)).toBe(true);
  });

  it('callTool record 被拒（只读 profile：isError + degraded）', async () => {
    const result = await client.callTool('record', {
      content: 'mcp-client.test probe',
      quality_level: 'C',
      tags: 'probe',
    });
    expect(result.isError).toBe(true);
    const text = result.content.map((c) => c.text ?? '').join('\n');
    expect(/degraded|disabled|readonly|denied|拒绝/i.test(text)).toBe(true);
  });

  it('并发调用安全：并发 recall 各自拿到响应', async () => {
    const [a, b] = await Promise.all([
      client.callTool('recall', { context: 'LobeHub', top_k: 1 }),
      client.callTool('recall', { context: '52 协议', top_k: 1 }),
    ]);
    expect(a.content.length).toBeGreaterThan(0);
    expect(b.content.length).toBeGreaterThan(0);
  });

  it('进程不可 spawn 时 FAIL-OPEN 抛出 McpClientError', async () => {
    const bad = new StdioMcpClient('/nonexistent/python3', [], {});
    await expect(bad.listTools()).rejects.toMatchObject({
      name: 'McpClientError',
      degraded: true,
    });
    bad.dispose();
  });
});
