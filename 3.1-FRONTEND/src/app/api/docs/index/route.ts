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

// --- A2（SPEC §13.1）：优先 41 索引查询（毫秒级），FAIL-OPEN 降级 adapter 实时扫描 ---
const FIS_CLI = '/home/ubuntu/fis-p0/.venv/bin/python';
const FIS_SCRIPT = '/home/ubuntu/fis-p0/scripts/search_cli.py';

async function fisListDocs(root?: string | null): Promise<DocIndexData | null> {
  return new Promise((resolve) => {
    let out = '';
    let settled = false;
    const req = JSON.stringify({ cmd: 'list_files', root: root || undefined, type: 'doc', limit: 2000 });
    const child = spawn(FIS_CLI, [FIS_SCRIPT], {
      env: { ...process.env, FIS_PG_PASSWORD: process.env.FIS_PG_PASSWORD || 'xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE' },
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve(null);
    }, 8000);
    child.stdout.on('data', (c: Buffer) => { out += c.toString(); });
    child.on('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(null);
    });
    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        const res = JSON.parse(out) as { success: boolean; files?: Array<{ path: string; root: string; category: string; last_synced: string; size_bytes: number }> };
        if (!res.success || !Array.isArray(res.files)) { resolve(null); return; }
        const docs: DocItem[] = res.files.map((f) => ({
          path: f.path,
          root: f.root,
          category: f.category,
          last_synced: f.last_synced,
          cognitive_linked: false, // 认知沉淀标记属 /api/docs/sync 链路，41 仅替代扫描环节（SPEC §7.9-3）
          size_bytes: f.size_bytes,
        }));
        resolve({
          schema_version: 'fis-l1',
          count: docs.length,
          docs,
          roots_scanned: root ? [root] : ['0-系统文档管理', '2-KNOWLEDGE'],
        });
      } catch {
        resolve(null);
      }
    });
    child.stdin.write(req);
    child.stdin.end();
  });
}

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// A5（SPEC §13.1）：41 status 的 reconcile_diff 新鲜度信息（FAIL-OPEN，失败不阻塞主结果）
async function fisStatus(): Promise<{ changed: number; last_indexed_at: string | null } | null> {
  return new Promise((resolve) => {
    let out = '';
    let settled = false;
    const child = spawn(FIS_CLI, [FIS_SCRIPT], {
      env: { ...process.env, FIS_PG_PASSWORD: process.env.FIS_PG_PASSWORD || 'xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE' },
      stdio: ['pipe', 'pipe', 'ignore'],
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve(null);
    }, 8000);
    child.stdout.on('data', (c: Buffer) => { out += c.toString(); });
    child.on('error', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(null);
    });
    child.on('close', () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      try {
        const res = JSON.parse(out) as { success: boolean; reconcile_diff?: { changed: number }; index_freshness?: { last_indexed_at: string | null } };
        if (!res.success) { resolve(null); return; }
        resolve({ changed: res.reconcile_diff?.changed ?? 0, last_indexed_at: res.index_freshness?.last_indexed_at ?? null });
      } catch {
        resolve(null);
      }
    });
    child.stdin.write(JSON.stringify({ cmd: 'status' }));
    child.stdin.end();
  });
}
export async function GET(req: Request) {
  const url = new URL(req.url);
  const root = url.searchParams.get('root');

  const args: Record<string, unknown> = {};
  if (root) args.roots = [root];

  // 优先 41 索引查询（A2）；失败降级 adapter 实时扫描（FAIL-OPEN）
  const [fisData, fisStat] = await Promise.all([fisListDocs(root), fisStatus()]);
  if (fisData) {
    return NextResponse.json({ ...fisData, source: 'fis', reconcile: fisStat ?? undefined });
  }
  const result = await callDocIndex<DocIndexData>('list', args);

  if (!result.ok || !result.data) {
    return NextResponse.json(
      { degraded: true, error: result.error },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
