/**
 * 52-LobeHub 协议集成 Phase 1 — stdio JSON-RPC MCP 客户端（只读 cognition 壳）。
 *
 * 职责边界（硬约束）：
 *  - 仅消费 47 registry 注册的 cognition MCP server（写工具由服务端拒绝）；
 *  - 本层不做任何交易/策略/风控/记忆写能力；
 *  - 所有错误以 FAIL-OPEN 语义抛出（McpClientError.degraded=true），由上层降级处理。
 *
 * 协议：MCP over stdio，换行分隔 JSON-RPC 2.0。
 * 生命周期：懒启动（首次调用 spawn）→ initialize/initialized 握手 → 复用进程；
 * 空闲 IDLE_TIMEOUT_MS 后自动回收（kill），下次调用重新 spawn。
 * 并发安全：请求 id 单调递增，响应按 id 匹配到 pending 回调。
 */
import path from 'path';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import { jsonSchema, tool } from 'ai';
import type { Tool } from 'ai';

/** 47 registry 只读 profile（/tmp/lobehub_frontend_profile.json 对齐，唯一事实源）。 */
const DEFAULT_COMMAND = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
// 脚本与 PYTHONPATH 按仓库根推导（前端 cwd 为 3.1-FRONTEND），云端可用 DREAMBUDDY_ROOT 覆盖
const REPO_ROOT = process.env.DREAMBUDDY_ROOT || path.resolve(process.cwd(), '..');
const DEFAULT_ARGS = [
  process.env.COGNITIVE_MCP_SERVER
    || path.join(REPO_ROOT, '4-MEMORY', '9-工具与接口', 'cognitive_mcp_server.py'),
];
const DEFAULT_ENV = {
  PYTHONPATH: REPO_ROOT,
  PYTHONIOENCODING: 'utf-8',
  COGNITIVE_MCP_MODE: 'local',
  COGNITIVE_MCP_WRITE_ENABLED: 'false',
};

const REQUEST_TIMEOUT_MS = 30_000;
const IDLE_TIMEOUT_MS = 60_000;
const PROTOCOL_VERSION = '2024-11-05';

export interface McpToolDef {
  name: string;
  description?: string;
  inputSchema: Record<string, unknown>;
}

export interface McpCallResult {
  content: Array<{ type: string; text?: string }>;
  isError?: boolean;
}

/** FAIL-OPEN 错误：degraded 恒为 true，路由层捕获后走降级信封。 */
export class McpClientError extends Error {
  readonly degraded = true;
  constructor(message: string) {
    super(message);
    this.name = 'McpClientError';
  }
}

interface PendingRequest {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
  timer: NodeJS.Timeout;
}

export class StdioMcpClient {
  private proc: ChildProcessWithoutNullStreams | null = null;
  private nextId = 1;
  private pending = new Map<number, PendingRequest>();
  private buffer = '';
  private readyPromise: Promise<void> | null = null;
  private idleTimer: NodeJS.Timeout | null = null;

  constructor(
    private readonly command: string = DEFAULT_COMMAND,
    private readonly args: string[] = DEFAULT_ARGS,
    private readonly env: Record<string, string> = DEFAULT_ENV,
  ) {}

  /** 确保进程已启动并完成 initialize/initialized 握手。 */
  private async ensureReady(): Promise<void> {
    if (!this.readyPromise) {
      this.readyPromise = this.spawnAndHandshake().catch((e) => {
        this.readyPromise = null;
        throw e;
      });
    }
    return this.readyPromise;
  }

  private async spawnAndHandshake(): Promise<void> {
    let proc: ChildProcessWithoutNullStreams;
    try {
      proc = spawn(this.command, this.args, {
        env: { ...process.env, ...this.env },
        stdio: ['pipe', 'pipe', 'pipe'],
      });
    } catch (e) {
      throw new McpClientError(`mcp_spawn_failed: ${(e as Error).message}`);
    }
    this.proc = proc;
    this.buffer = '';

    proc.stdout.on('data', (chunk: Buffer) => this.onData(chunk.toString('utf-8')));
    proc.on('error', (e) => this.onProcessGone(new McpClientError(`mcp_process_error: ${e.message}`)));
    proc.on('exit', (code) => this.onProcessGone(new McpClientError(`mcp_process_exit: ${code}`)));
    // stderr 仅记录，不参与协议（Python 侧可能打警告行）
    proc.stderr.on('data', () => { /* swallow */ });

    const result = (await this.request('initialize', {
      protocolVersion: PROTOCOL_VERSION,
      capabilities: {},
      clientInfo: { name: 'dreambuddy-agent-protocol-layer', version: '0.1.0' },
    })) as { serverInfo?: { name?: string } } | undefined;
    if (!result?.serverInfo?.name) {
      throw new McpClientError('mcp_initialize_invalid_response');
    }
    this.notify('notifications/initialized');
  }

  private onData(data: string): void {
    this.buffer += data;
    for (;;) {
      const idx = this.buffer.indexOf('\n');
      if (idx < 0) break;
      const line = this.buffer.slice(0, idx).trim();
      this.buffer = this.buffer.slice(idx + 1);
      if (!line || !line.startsWith('{')) continue; // 忽略非 JSON 警告行
      let msg: { id?: number; result?: unknown; error?: { message?: string } };
      try {
        msg = JSON.parse(line);
      } catch {
        continue;
      }
      // 只处理带 id 的响应；服务端 notification 直接忽略
      if (typeof msg.id !== 'number') continue;
      const entry = this.pending.get(msg.id);
      if (!entry) continue;
      this.pending.delete(msg.id);
      clearTimeout(entry.timer);
      if (msg.error) {
        entry.reject(new McpClientError(`mcp_rpc_error: ${msg.error.message ?? 'unknown'}`));
      } else {
        entry.resolve(msg.result);
      }
    }
  }

  private onProcessGone(err: McpClientError): void {
    // 进程死亡：拒绝所有 pending，重置状态使下次调用重新 spawn
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(err);
    }
    this.pending.clear();
    this.readyPromise = null;
    this.proc = null;
  }

  private send(payload: Record<string, unknown>): void {
    if (!this.proc) throw new McpClientError('mcp_not_started');
    this.proc.stdin.write(JSON.stringify(payload) + '\n');
  }

  private notify(method: string, params?: Record<string, unknown>): void {
    try {
      this.send({ jsonrpc: '2.0', method, ...(params ? { params } : {}) });
    } catch {
      /* notification 失败不影响主链路 */
    }
  }

  private touchIdle(): void {
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = setTimeout(() => {
      // 空闲回收：无 pending 请求时 kill 进程
      if (this.pending.size === 0) this.dispose();
    }, IDLE_TIMEOUT_MS);
    // 不阻止 Node 进程退出
    this.idleTimer.unref?.();
  }

  /** 发 JSON-RPC 请求并等待响应（id 匹配 + 超时保护）。 */
  async request(method: string, params?: Record<string, unknown>): Promise<unknown> {
    // 握手期间的 initialize 请求允许在 ensureReady 内直接调用
    const ready = method === 'initialize' ? Promise.resolve() : this.ensureReady();
    await ready;

    const id = this.nextId++;
    if (this.idleTimer) clearTimeout(this.idleTimer);

    return new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        this.pending.delete(id);
        reject(new McpClientError(`mcp_request_timeout: ${method}`));
      }, REQUEST_TIMEOUT_MS);
      this.pending.set(id, { resolve, reject, timer });
      try {
        this.send({ jsonrpc: '2.0', id, method, ...(params ? { params } : {}) });
      } catch (e) {
        clearTimeout(timer);
        this.pending.delete(id);
        reject(e);
        return;
      }
      // 包装 resolve/reject 以在完成后重置空闲计时
      const entry = this.pending.get(id);
      if (entry) {
        const origResolve = entry.resolve;
        const origReject = entry.reject;
        entry.resolve = (v) => { origResolve(v); this.touchIdle(); };
        entry.reject = (e) => { origReject(e); this.touchIdle(); };
      }
    });
  }

  /** tools/list → MCP 工具定义数组。 */
  async listTools(): Promise<McpToolDef[]> {
    const result = (await this.request('tools/list')) as { tools?: McpToolDef[] } | undefined;
    if (!result || !Array.isArray(result.tools)) {
      throw new McpClientError('mcp_tools_list_invalid');
    }
    return result.tools;
  }

  /** tools/call → { content, isError }。isError 不抛异常，交由上层判断降级语义。 */
  async callTool(name: string, args: Record<string, unknown> = {}): Promise<McpCallResult> {
    const result = (await this.request('tools/call', { name, arguments: args })) as
      | McpCallResult
      | undefined;
    if (!result || !Array.isArray(result.content)) {
      throw new McpClientError('mcp_tool_call_invalid');
    }
    return result;
  }

  /** 把 MCP tools 转成 Vercel AI SDK tools（inputSchema 透传，execute 走 callTool）。 */
  async toAiSdkTools(): Promise<Record<string, Tool>> {
    const defs = await this.listTools();
    const client = this;
    const tools: Record<string, Tool> = {};
    for (const def of defs) {
      tools[def.name] = tool({
        description: def.description ?? '',
        inputSchema: jsonSchema(def.inputSchema as never),
        execute: async (args) => {
          const r = await client.callTool(def.name, args as Record<string, unknown>);
          // MCP text content 拼成字符串返回给模型
          return r.content
            .map((c) => (c.type === 'text' ? c.text ?? '' : JSON.stringify(c)))
            .join('\n');
        },
      });
    }
    return tools;
  }

  /** 回收进程与计时器（测试/关闭时调用）。 */
  dispose(): void {
    if (this.idleTimer) {
      clearTimeout(this.idleTimer);
      this.idleTimer = null;
    }
    const proc = this.proc;
    this.proc = null;
    this.readyPromise = null;
    for (const entry of this.pending.values()) {
      clearTimeout(entry.timer);
      entry.reject(new McpClientError('mcp_disposed'));
    }
    this.pending.clear();
    if (proc) {
      try {
        proc.kill('SIGTERM');
      } catch {
        /* already dead */
      }
    }
  }
}

/** 进程级单例：Next.js 路由在 module 作用域复用，避免每请求 spawn Python。 */
let sharedClient: StdioMcpClient | null = null;

export function getCognitionMcpClient(): StdioMcpClient {
  if (!sharedClient) sharedClient = new StdioMcpClient();
  return sharedClient;
}

/** 测试辅助：重置单例。 */
export function resetCognitionMcpClient(): void {
  sharedClient?.dispose();
  sharedClient = null;
}
