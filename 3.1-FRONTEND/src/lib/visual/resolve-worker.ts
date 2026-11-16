// 能力装配的常驻 Python worker（SPEC-54 R6）
// 背景：一次性 CLI 每次请求都要付 ~11s 的 Python import（sklearn/scipy），
// 13 张卡并发必然撞 25s 超时。这里把 import 摊到进程启动一次，请求串行复用。
// FAIL-OPEN：worker 异常时退回一次性 CLI，功能不受影响，只退化延迟。

import { execFile, spawn, type ChildProcessWithoutNullStreams } from 'child_process';
import { promises as fs } from 'fs';
import os from 'os';
import path from 'path';
import { promisify } from 'util';

const execFileAsync = promisify(execFile);

const REQUEST_TIMEOUT_MS = 30_000;
const MAX_STDERR = 4096;

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
  timer: NodeJS.Timeout;
}

interface WorkerState {
  proc: ChildProcessWithoutNullStreams;
  pending: Map<string, Pending>;
  buffer: string;
  stderr: string;
  queue: Promise<unknown>;
  seq: number;
}

const globalStore = globalThis as typeof globalThis & {
  __visualResolveWorker?: WorkerState;
};

function pythonBin(): string {
  return process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
}

function startWorker(): WorkerState {
  const scriptPath = path.join(process.cwd(), 'scripts', 'capability_resolve_server.py');
  const proc = spawn(pythonBin(), [scriptPath], {
    stdio: ['pipe', 'pipe', 'pipe'],
  }) as ChildProcessWithoutNullStreams;

  const state: WorkerState = {
    proc,
    pending: new Map(),
    buffer: '',
    stderr: '',
    queue: Promise.resolve(),
    seq: 0,
  };

  const failAll = (error: Error) => {
    for (const [id, item] of state.pending) {
      clearTimeout(item.timer);
      item.reject(error);
      state.pending.delete(id);
    }
  };

  proc.stdout.setEncoding('utf8');
  proc.stdout.on('data', (chunk: string) => {
    state.buffer += chunk;
    let index = state.buffer.indexOf('\n');
    while (index >= 0) {
      const line = state.buffer.slice(0, index).trim();
      state.buffer = state.buffer.slice(index + 1);
      if (line.startsWith('{')) {
        try {
          const payload = JSON.parse(line) as { id?: string };
          const id = String(payload.id ?? '');
          const item = state.pending.get(id);
          if (item) {
            clearTimeout(item.timer);
            state.pending.delete(id);
            item.resolve(payload);
          }
        } catch {
          // 非 JSON 行忽略（Python 侧日志已走 stderr）
        }
      }
      index = state.buffer.indexOf('\n');
    }
  });

  proc.stderr.setEncoding('utf8');
  proc.stderr.on('data', (chunk: string) => {
    state.stderr = (state.stderr + chunk).slice(-MAX_STDERR);
  });

  proc.on('exit', (code) => {
    if (globalStore.__visualResolveWorker === state) {
      globalStore.__visualResolveWorker = undefined;
    }
    failAll(new Error(`resolve worker exited (code ${code}) ${state.stderr.slice(-400)}`));
  });
  proc.on('error', (error) => {
    if (globalStore.__visualResolveWorker === state) {
      globalStore.__visualResolveWorker = undefined;
    }
    failAll(error instanceof Error ? error : new Error(String(error)));
  });

  return state;
}

function worker(): WorkerState {
  if (!globalStore.__visualResolveWorker) {
    globalStore.__visualResolveWorker = startWorker();
  }
  return globalStore.__visualResolveWorker;
}

async function callWorker(capabilityId: string, payload: Record<string, unknown>) {
  const state = worker();
  const id = String(++state.seq);
  return new Promise<unknown>((resolve, reject) => {
    const timer = setTimeout(() => {
      state.pending.delete(id);
      reject(new Error('resolve worker timeout'));
    }, REQUEST_TIMEOUT_MS);
    state.pending.set(id, { resolve, reject, timer });
    try {
      state.proc.stdin.write(`${JSON.stringify({ id, capability: capabilityId, payload })}\n`);
    } catch (error) {
      clearTimeout(timer);
      state.pending.delete(id);
      reject(error instanceof Error ? error : new Error(String(error)));
    }
  });
}

/** 一次性 CLI 兜底（worker 不可用时保持功能可用，只是慢） */
async function resolveOnce(capabilityId: string, payload: Record<string, unknown>) {
  const scriptPath = path.join(process.cwd(), 'scripts', 'capability_resolve.py');
  const args = [scriptPath, '--capability', capabilityId];
  let tmpDir: string | null = null;
  try {
    if (Object.keys(payload).length > 0) {
      // custom_series 可能较大，走临时文件避开命令行长度限制
      tmpDir = await fs.mkdtemp(path.join(os.tmpdir(), 'cap-resolve-'));
      const file = path.join(tmpDir, 'payload.json');
      await fs.writeFile(file, JSON.stringify(payload), 'utf8');
      args.push('--payload-file', file);
    }
    const { stdout } = await execFileAsync(pythonBin(), args, {
      maxBuffer: 20 * 1024 * 1024,
      timeout: 60_000,
    });
    const lines = stdout
      .trim()
      .split('\n')
      .filter((line: string) => line.trim().startsWith('{'));
    return JSON.parse(lines[lines.length - 1] || '{}');
  } finally {
    if (tmpDir) await fs.rm(tmpDir, { recursive: true, force: true }).catch(() => undefined);
  }
}

/**
 * 串行复用常驻 worker；worker 失败自动回落一次性 CLI。
 * 返回体与 `capability_resolve.py` 单行输出一致（`{ok, code, capability_id, ...}`）。
 */
export async function resolveCapabilityViaWorker(
  capabilityId: string,
  payload: Record<string, unknown>,
): Promise<unknown> {
  const state = worker();
  const task = state.queue.then(
    () => callWorker(capabilityId, payload),
    () => callWorker(capabilityId, payload),
  );
  // 队列自身永不 reject，避免一次失败卡死后续请求
  state.queue = task.then(
    () => undefined,
    () => undefined,
  );
  try {
    return await task;
  } catch {
    return resolveOnce(capabilityId, payload);
  }
}
