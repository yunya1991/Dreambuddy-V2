/**
 * POST /api/docs/sync
 * 手动触发 doc-sync（调用 DocSyncTrigger.sync → 认知库 record）。
 *
 * 返回 SyncReport（含 memory_id）。
 *
 * 复刻 P1 /api/skills/index route 模式:
 *  - runtime='nodejs' + force-dynamic
 *  - FAIL-OPEN: 后端不可达返回 503 + {degraded: true}
 *  - 单次 spawn + stdout 行过滤取最后一行 JSON
 *  - 超时 20s（sync 涉及认知库 record，给更长）
 */
import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';

interface SyncReport {
  action: string;
  index_updated: boolean;
  knowledge_updated: boolean;
  lint_passed: boolean;
  recorded: boolean;
  memory_id: string | null;
  reason: string;
  synced_at: string;
  files_scanned: number;
  changes_count?: number;
}

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'doc_index_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 20000;  // sync 涉及认知库 record，给 20s

async function callDocSync<T>(
  command: string,
  args: Record<string, unknown> = {}
): Promise<{ ok: boolean; data?: T; error?: string; degraded?: boolean }> {
  return new Promise((resolve) => {
    let stdoutBuf = '';
    let settled = false;
    const child = spawn(PYTHON_BIN, [ADAPTER_PATH, command, JSON.stringify(args)], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ ok: false, degraded: true, error: `timeout_${TIMEOUT_MS}ms` });
    }, TIMEOUT_MS);
    child.stdout.on('data', (chunk: Buffer) => { stdoutBuf += chunk.toString(); });
    child.stderr.on('data', () => { /* discard */ });
    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, degraded: true, error: `spawn_failed: ${err.message}` });
    });
    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      const lines = stdoutBuf.split('\n').filter((l) => l.trim().startsWith('{'));
      const lastLine = lines[lines.length - 1] || '{}';
      try {
        resolve(JSON.parse(lastLine));
      } catch (e) {
        resolve({
          ok: false, degraded: true,
          error: `parse_failed: ${e instanceof Error ? e.message : String(e)}`,
        });
      }
    });
  });
}

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

export async function POST() {
  const result = await callDocSync<SyncReport>('sync', {});

  if (!result.ok || !result.data) {
    return NextResponse.json(
      { degraded: true, error: result.error },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
