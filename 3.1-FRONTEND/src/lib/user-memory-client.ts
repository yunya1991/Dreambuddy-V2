/**
 * 用户层记忆 TS 客户端 — 通过子进程调用 user_memory_adapter.py
 *
 * 复刻 P0 cognitive-client.ts 模式 (VM-1789618914215):
 *  - child_process.spawn + 行过滤 stdout
 *  - 10s 超时 + SIGKILL 兜底
 *  - FAIL-OPEN: 失败返回 {degraded: true}, 不抛异常
 *
 * 物理隔离硬约束 (VM-1786242777697):
 *  - 用户层数据存 user_memory.db，禁止写 cognitive_memory.db
 *  - 用户笔记不可自动升级为 VM（必须 P3 人工审批）
 */

import { spawn } from 'child_process';
import path from 'path';

export interface UserMemoryResult<T = unknown> {
  ok: boolean;
  data?: T;
  error?: string;
  degraded?: boolean;
  traceback?: string;
}

export interface UserPreference {
  user_id: string;
  pref_key: string;
  pref_value: string | null;
  updated_at: number;
}

export interface UserNote {
  id: string;            // user:note:xxx
  user_id: string;
  title: string | null;
  content: string | null;
  tags: string | null;
  promoted_to: string | null;  // 沉淀后的 VM-id
  created_at: number;
  updated_at: number;
}

export interface UserMemoryHealth {
  status: string;
  db_path: string;
  physical_isolation: boolean;
  preferences_count: number;
  notes_count: number;
  vm_leak_count: number;
}

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'user_memory_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 10000;

/**
 * 调用用户层记忆命令（单次请求模式）。
 *
 * @param command - get_prefs | set_pref | list_notes | create_note | delete_note | mark_promoted | health
 * @param args - 命令入参对象
 * @returns UserMemoryResult，失败时 degraded=true（FAIL-OPEN）
 */
export function callUserMemory<T = unknown>(
  command: string,
  args: Record<string, unknown> = {}
): Promise<UserMemoryResult<T>> {
  return new Promise<UserMemoryResult<T>>((resolve) => {
    let stdoutBuf = '';
    let stderrBuf = '';
    let settled = false;

    const child = spawn(PYTHON_BIN, [ADAPTER_PATH, command, JSON.stringify(args)], {
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
        const parsed = JSON.parse(lastLine) as UserMemoryResult<T>;
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
