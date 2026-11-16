/**
 * A1-2 多壳消费 — MCP 多壳聚合（FAIL-OPEN）
 *
 * 背景：3.1 原先只连 cognition 单壳（mcp-client.ts），工具面由各壳各自推导。
 * 本层把「多壳」收敛为一个聚合入口：壳级失败只降级该壳，不阻塞其他壳；
 * 同名工具冲突保留先注册者并留痕（禁止静默覆盖）。
 *
 * 壳来源：
 *  1. 内置 l0.cognition 单例（复用 mcp-client.ts 的懒启动/空闲回收）；
 *  2. 环境变量 DREAMBUDDY_MCP_SHELLS（JSON 数组：[{key, command, args?, env?}]，可选）。
 */
import type { Tool } from 'ai';
import {
  McpClientError,
  StdioMcpClient,
  getCognitionMcpClient,
  resetCognitionMcpClient,
} from './mcp-client';

export interface McpShell {
  key: string;
  toAiSdkTools(): Promise<Record<string, Tool>>;
  dispose?(): void;
}

export interface AggregatedToolSet {
  tools: Record<string, Tool>;
  degradedShells: Array<{ shell: string; error: string }>;
  conflicts: string[];
}

export class MultiShellMcpRegistry {
  private readonly shells = new Map<string, McpShell>();

  registerShell(shell: McpShell): void {
    if (this.shells.has(shell.key)) {
      throw new McpClientError(`mcp_shell_duplicate: ${shell.key}`);
    }
    this.shells.set(shell.key, shell);
  }

  listShells(): string[] {
    return [...this.shells.keys()];
  }

  /** 聚合所有壳工具：壳级 FAIL-OPEN，同名冲突保留先注册者。 */
  async toAiSdkTools(): Promise<AggregatedToolSet> {
    const tools: Record<string, Tool> = {};
    const degradedShells: AggregatedToolSet['degradedShells'] = [];
    const conflicts: string[] = [];

    for (const [key, shell] of this.shells) {
      try {
        const shellTools = await shell.toAiSdkTools();
        for (const [name, toolDef] of Object.entries(shellTools)) {
          if (tools[name]) {
            conflicts.push(name);
            continue;
          }
          tools[name] = toolDef;
        }
      } catch (e) {
        degradedShells.push({
          shell: key,
          error: e instanceof Error ? e.message : String(e),
        });
      }
    }

    return { tools, degradedShells, conflicts };
  }

  dispose(): void {
    for (const shell of this.shells.values()) {
      try {
        shell.dispose?.();
      } catch {
        /* 已关闭 */
      }
    }
    this.shells.clear();
  }
}

interface ShellSpec {
  key: string;
  command: string;
  args?: string[];
  env?: Record<string, string>;
}

/** 解析 DREAMBUDDY_MCP_SHELLS；非法 JSON/条目不阻塞主链路，仅告警。 */
function shellsFromEnv(): ShellSpec[] {
  const raw = process.env.DREAMBUDDY_MCP_SHELLS;
  if (!raw) return [];
  try {
    const parsed = JSON.parse(raw);
    if (!Array.isArray(parsed)) throw new Error('not an array');
    return parsed.filter(
      (s: Partial<ShellSpec>) => typeof s?.key === 'string' && typeof s?.command === 'string',
    ) as ShellSpec[];
  } catch (e) {
    console.warn('[MCP] DREAMBUDDY_MCP_SHELLS 解析失败（忽略）:', (e as Error).message);
    return [];
  }
}

let sharedRegistry: MultiShellMcpRegistry | null = null;

/** 进程级单例：内置 cognition + 环境声明的额外壳。 */
export function getAgentMcpShells(): MultiShellMcpRegistry {
  if (sharedRegistry) return sharedRegistry;

  const registry = new MultiShellMcpRegistry();
  registry.registerShell({
    key: 'l0.cognition',
    toAiSdkTools: () => getCognitionMcpClient().toAiSdkTools(),
    dispose: () => resetCognitionMcpClient(),
  });

  for (const spec of shellsFromEnv()) {
    const client = new StdioMcpClient(spec.command, spec.args, spec.env);
    registry.registerShell({
      key: spec.key,
      toAiSdkTools: () => client.toAiSdkTools(),
      dispose: () => client.dispose(),
    });
  }

  sharedRegistry = registry;
  return registry;
}

/**
 * 聚合工具入口（3.1 chat/plan 使用）。
 * 全部壳降级时抛 McpClientError，调用方按原单壳语义降级为无工具对话。
 */
export async function getAgentMcpTools(
  registry: MultiShellMcpRegistry = getAgentMcpShells(),
): Promise<Record<string, Tool>> {
  const { tools, degradedShells, conflicts } = await registry.toAiSdkTools();

  if (degradedShells.length) {
    console.warn(
      '[MCP] 壳降级（FAIL-OPEN）:',
      degradedShells.map((d) => `${d.shell}: ${d.error}`).join('; '),
    );
  }
  if (conflicts.length) {
    console.warn('[MCP] 工具名冲突（保留先注册者）:', conflicts.join(', '));
  }

  if (Object.keys(tools).length === 0 && registry.listShells().length === degradedShells.length) {
    throw new McpClientError('mcp_all_shells_degraded');
  }
  return tools;
}

/** 测试辅助：重置单例。 */
export function resetAgentMcpShells(): void {
  sharedRegistry?.dispose();
  sharedRegistry = null;
}
