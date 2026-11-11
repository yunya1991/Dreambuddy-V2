/**
 * POST /api/agent/brainstorm
 * 52-LobeHub 协议集成 Phase 4.6 — 3.1 用户入口（择优脑暴）。
 *
 * Body: { intent: string, nPerSide?: number, force?: boolean }
 *
 * 流程：校验 intent（非空且 ≤2000 字）→ spawn 编排器 CLI
 * （`52-lobehub协议集成/orchestrator/brainstorm_orchestrator.py --json-out`）
 * → 解析 stdout 最后一行 JSON 摘要返回 `{ ok:true, ...summary }`。
 *
 * 边界（硬约束）：UI 不直连编排器，统一经本路由；解析失败/非零退出/超时
 * 一律 200 degraded 信封（沿用 /api/agent/plan 的 FAIL-OPEN 风格），绝不 500。
 * python 可执行路径可用 env `ORCHESTRATOR_PY` 覆盖（默认 python3），超时 180s。
 * 只读：GET 返回 405。
 */
import path from 'path';
import { spawn } from 'child_process';
import { NextRequest, NextResponse } from 'next/server';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const MAX_INTENT_LENGTH = 2000;
const ORCHESTRATOR_TIMEOUT_MS = 180_000;
const STDIO_CAP_BYTES = 1024 * 1024;

function degraded(reason: string, extra: Record<string, unknown> = {}) {
  return NextResponse.json({ ok: false, data: null, degraded: true, error: reason, ...extra });
}

/** 默认编排器脚本路径（3.1-FRONTEND/../52-lobehub协议集成/orchestrator）。 */
function resolveOrchestratorScript(): string {
  return path.join(
    process.cwd(),
    '..',
    '52-lobehub协议集成',
    'orchestrator',
    'brainstorm_orchestrator.py',
  );
}

interface OrchestratorResult {
  stdout: string;
  stderr: string;
  code: number | null;
  timedOut: boolean;
  spawnError?: string;
}

/** 执行编排器 CLI（超时 kill）；任何异常收敛为结果对象，不抛出。 */
function runOrchestrator(args: string[]): Promise<OrchestratorResult> {
  return new Promise((resolve) => {
    const script = resolveOrchestratorScript();
    const python = process.env.ORCHESTRATOR_PY || 'python3';
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    let settled = false;

    const child = spawn(python, [script, ...args], {
      cwd: path.dirname(script),
      env: process.env,
      stdio: ['ignore', 'pipe', 'pipe'],
    });

    const finish = (result: OrchestratorResult) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(result);
    };

    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
      // kill 后不保证立刻收到 close，超时直接收敛结果
      finish({ stdout, stderr, code: null, timedOut: true });
    }, ORCHESTRATOR_TIMEOUT_MS);

    child.stdout?.on('data', (chunk: Buffer | string) => {
      if (stdout.length < STDIO_CAP_BYTES) stdout += chunk.toString();
    });
    child.stderr?.on('data', (chunk: Buffer | string) => {
      if (stderr.length < STDIO_CAP_BYTES) stderr += chunk.toString();
    });
    child.on('error', (error: Error) => {
      finish({ stdout, stderr, code: null, timedOut, spawnError: error.message });
    });
    child.on('close', (code: number | null) => {
      finish({ stdout, stderr, code, timedOut });
    });
  });
}

function lastJsonLine(stdout: string): Record<string, unknown> | null {
  const lines = stdout
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean);
  if (lines.length === 0) return null;
  try {
    const parsed = JSON.parse(lines[lines.length - 1]);
    return parsed && typeof parsed === 'object' ? (parsed as Record<string, unknown>) : null;
  } catch {
    return null;
  }
}

export async function POST(request: NextRequest) {
  let body: { intent?: string; nPerSide?: number; force?: boolean };
  try {
    body = await request.json();
  } catch {
    return degraded('invalid_json_body');
  }

  const intent = typeof body?.intent === 'string' ? body.intent.trim() : '';
  if (!intent) {
    return degraded('intent_required');
  }
  if (intent.length > MAX_INTENT_LENGTH) {
    return degraded('intent_too_long', { max_length: MAX_INTENT_LENGTH });
  }

  const args = ['--intent', intent, '--json-out'];
  const nPerSide = body?.nPerSide;
  if (typeof nPerSide === 'number' && Number.isInteger(nPerSide) && nPerSide >= 1 && nPerSide <= 3) {
    args.push('--n-per-side', String(nPerSide));
  }
  if (body?.force === true) {
    args.push('--force');
  }

  const result = await runOrchestrator(args);

  if (result.spawnError) {
    return degraded(`orchestrator_spawn_failed: ${result.spawnError}`);
  }
  if (result.timedOut) {
    return degraded('orchestrator_timeout');
  }
  if (result.code !== 0) {
    return degraded('orchestrator_exit_nonzero', {
      exit_code: result.code,
      stderr: result.stderr.slice(-500),
    });
  }

  const summary = lastJsonLine(result.stdout);
  if (!summary) {
    return degraded('orchestrator_output_invalid', {
      stderr: result.stderr.slice(-500),
    });
  }
  if (summary.ok === false) {
    return degraded(String(summary.error ?? 'orchestrator_failed'));
  }

  return NextResponse.json({ ...summary, ok: true });
}

export async function GET() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/agent/brainstorm accepts POST only' },
    { status: 405 },
  );
}
