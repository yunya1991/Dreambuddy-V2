/**
 * 认知系统 TS 客户端
 *
 * 传输顺序（SPEC-20261111-C §3.5 / T-C5）：
 *  1. 若配置 `COGNITIVE_API_BASE`，优先 HTTP 代理（前端 route.ts 不新增 spawn）
 *  2. HTTP 不可用/未配置时回退既有 IPC：child_process.spawn + 行过滤 stdout
 *
 * IPC 模式复刻 dream-harness-bridge P0-5 (VM-1789618914215):
 *  - 分工具超时；FAIL-OPEN: 失败返回 {degraded: true}, 不抛异常
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
// 不写死本机解释器路径：云端用 COGNITIVE_PYTHON / PYTHON 覆盖，缺省回落 python3
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';

// 超时按工具分级：
//  - health 用于页面轮询，必须快速失败，避免认知服务异常时页面长时间空白；
//  - recall/record/verify 是业务调用，云端 30 万+ 记忆的 recall 实测约 14s
//    （向量检索 + Python 进程冷启动），原 10s 固定超时会把正常慢调用误判为降级。
function resolveTimeoutMs(toolName: string): number {
  const isHealth = toolName === 'health';
  const envValue = Number(
    isHealth ? process.env.COGNITIVE_HEALTH_TIMEOUT_MS : process.env.COGNITIVE_TIMEOUT_MS,
  );
  if (Number.isFinite(envValue) && envValue > 0) return envValue;
  return isHealth ? 10000 : 35000;
}

/**
 * HTTP 代理调用（T-C5）。
 * 返回 null 表示「不可用/不可解析」——调用方回退 IPC，保证 FAIL-OPEN。
 */
async function callCognitiveHttp<T>(
  base: string,
  toolName: string,
  args: Record<string, unknown>,
  timeoutMs: number,
): Promise<CognitiveResult<T> | null> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${base.replace(/\/+$/, '')}/cognitive/${encodeURIComponent(toolName)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(args),
      signal: controller.signal,
    });
    if (!res.ok) return null;
    const body = (await res.json()) as unknown;
    if (body && typeof body === 'object' && 'ok' in (body as Record<string, unknown>)) {
      return body as CognitiveResult<T>;
    }
    return { ok: true, data: body as T };
  } catch {
    return null;
  } finally {
    clearTimeout(timer);
  }
}

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
  const timeoutMs = resolveTimeoutMs(toolName);
  const httpBase = process.env.COGNITIVE_API_BASE?.trim();
  if (httpBase) {
    const viaHttp = await callCognitiveHttp<T>(httpBase, toolName, args, timeoutMs);
    if (viaHttp) return viaHttp;
  }
  return callCognitiveIpc<T>(toolName, args, timeoutMs);
}

/** IPC 回退路径（既有实现，未改动语义） */
function callCognitiveIpc<T>(
  toolName: string,
  args: Record<string, unknown>,
  timeoutMs: number,
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
        error: `timeout_${timeoutMs}ms`,
      });
    }, timeoutMs);

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
