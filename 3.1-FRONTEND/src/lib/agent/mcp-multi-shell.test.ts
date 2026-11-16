/**
 * @jest-environment node
 *
 * A1-2 多壳聚合单测：壳级 FAIL-OPEN / 同名冲突留痕 / 全降级抛错。
 * 使用假壳，不 spawn 真实进程。
 */
import type { Tool } from 'ai';
import { McpClientError } from './mcp-client';
import {
  MultiShellMcpRegistry,
  getAgentMcpTools,
  type McpShell,
} from './mcp-multi-shell';

const fakeTool = (name: string): Tool => ({ description: name }) as unknown as Tool;

function shell(key: string, tools: Record<string, Tool> | Error): McpShell {
  return {
    key,
    async toAiSdkTools() {
      if (tools instanceof Error) throw tools;
      return tools;
    },
  };
}

describe('MultiShellMcpRegistry', () => {
  it('聚合多壳工具', async () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', { recall: fakeTool('recall') }));
    registry.registerShell(shell('l2.dreamos', { route: fakeTool('route') }));

    const result = await registry.toAiSdkTools();
    expect(Object.keys(result.tools).sort()).toEqual(['recall', 'route']);
    expect(result.degradedShells).toEqual([]);
    expect(result.conflicts).toEqual([]);
  });

  it('单壳失败不阻塞其他壳（FAIL-OPEN）', async () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', { recall: fakeTool('recall') }));
    registry.registerShell(shell('l2.dreamos', new Error('mcp_process_exit: 1')));

    const result = await registry.toAiSdkTools();
    expect(Object.keys(result.tools)).toEqual(['recall']);
    expect(result.degradedShells).toEqual([
      { shell: 'l2.dreamos', error: 'mcp_process_exit: 1' },
    ]);
  });

  it('同名工具冲突保留先注册者并留痕', async () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', { recall: fakeTool('first') }));
    registry.registerShell(shell('l2.dreamos', { recall: fakeTool('second') }));

    const result = await registry.toAiSdkTools();
    expect((result.tools.recall as { description?: string }).description).toBe('first');
    expect(result.conflicts).toEqual(['recall']);
  });

  it('重复注册同一壳 key 直接报错', () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', {}));
    expect(() => registry.registerShell(shell('l0.cognition', {}))).toThrow(McpClientError);
  });
});

describe('getAgentMcpTools', () => {
  it('全部壳降级时抛错（调用方退化为无工具对话）', async () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', new Error('boom')));
    await expect(getAgentMcpTools(registry)).rejects.toThrow('mcp_all_shells_degraded');
  });

  it('部分壳可用时返回可用工具', async () => {
    const registry = new MultiShellMcpRegistry();
    registry.registerShell(shell('l0.cognition', { recall: fakeTool('recall') }));
    registry.registerShell(shell('l2.dreamos', new Error('boom')));
    await expect(getAgentMcpTools(registry)).resolves.toHaveProperty('recall');
  });
});
