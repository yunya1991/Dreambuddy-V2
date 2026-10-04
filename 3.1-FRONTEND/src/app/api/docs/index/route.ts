/**
 * GET /api/docs/index
 * 返回文档索引列表（0-系统文档管理 + 2-KNOWLEDGE 的 .md 文件）。
 *
 * 查询参数:
 *  - root: 指定根目录（默认扫描 0-系统文档管理 + 2-KNOWLEDGE）
 *
 * 复刻 P1 /api/skills/index route 模式:
 *  - runtime='nodejs' + force-dynamic
 *  - FAIL-OPEN: 后端不可达返回 503 + {degraded: true}
 *  - 单次 spawn + stdout 行过滤取最后一行 JSON
 */
import { NextResponse } from 'next/server';
import { spawn } from 'child_process';
import path from 'path';

export interface DocItem {
  path: string;
  root: string;
  category: string;
  last_synced: string;
  cognitive_linked: boolean;
  size_bytes: number;
}

interface DocIndexData {
  schema_version: string;
  count: number;
  docs: DocItem[];
  roots_scanned: string[];
}

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'doc_index_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 15000;  // 文档扫描稍慢，给 15s

async function callDocIndex<T>(
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

export async function GET(req: Request) {
  const url = new URL(req.url);
  const root = url.searchParams.get('root');

  const args: Record<string, unknown> = {};
  if (root) args.roots = [root];

  const result = await callDocIndex<DocIndexData>('list', args);

  if (!result.ok || !result.data) {
    return NextResponse.json(
      { degraded: true, error: result.error },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
