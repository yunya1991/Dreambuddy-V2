/**
 * 认知系统 TS 客户端 — 通过子进程调用 cognitive_adapter.py
 *
 * 复刻 dream-harness-bridge P0-5 IPC 模式 (VM-1789618914215):
 *  - child_process.spawn + 行过滤 stdout
 *  - 10s 超时
 *  - FAIL-OPEN: 失败返回 {degraded: true}, 不抛异常
 *
 * 不改 4-MEMORY 后端, 仅在 3.1-FRONTEND 接入层新增。
 */

import { spawn } from 'child_process';
import path from 'path';

export interface CognitiveResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  degraded?: boolean;
  traceback?: string;
}

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'cognitive_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 10000;

/**
 * 调用认知系统 MCP 工具（单次请求模式）。
 *
 * @param toolName - recall | record | verify | stats | health
 * @param args - 工具入参对象
 * @returns CognitiveResult，失败时 degraded=true（FAIL-OPEN）
 */
export async function callCognitive<T = unknown>(
  toolName: string,
  args: Record<string, unknown> = {}
): Promise<CognitiveResult<T>> {
  return new Promise<CognitiveResult<T>>((resolve) => {
    let stdoutBuf = '';
    let stderrBuf = '';
    let settled = false;

    const child = spawn(PYTHON_BIN, [ADAPTER_PATH, toolName, JSON.stringify(args)], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({
        ok: false,
        degraded: true,
        error: `timeout_${TIMEOUT_MS}ms`,
      });
    }, TIMEOUT_MS);

    child.stdout.on('data', (chunk: Buffer) => {
      stdoutBuf += chunk.toString();
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderrBuf += chunk.toString();
    });

    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({
        ok: false,
        degraded: true,
        error: `spawn_failed: ${err.message}`,
      });
    });

    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);

      // adapter 保证 stdout 最后一行是单行 JSON
      const lines = stdoutBuf.split('\n').filter((l) => l.trim().startsWith('{'));
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        const parsed = JSON.parse(lastLine) as CognitiveResult<T>;
        resolve(parsed);
      } catch (e) {
        resolve({
          ok: false,
          degraded: true,
          error: `parse_failed: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  });
}
