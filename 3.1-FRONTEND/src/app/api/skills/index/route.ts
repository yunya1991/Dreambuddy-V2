/**
 * GET /api/skills/index
 * 返回 Skill 索引列表（含生命周期状态 + 认知链接数）。
 *
 * 查询参数:
 *  - trigger: 按触发词过滤
 *  - category: 按分类过滤
 *  - status: 按状态过滤 (active/shadow/deprecated)
 *
 * 复刻 P0 cognitive/stats route 模式:
 *  - runtime='nodejs' + force-dynamic
 *  - FAIL-OPEN: 后端不可达返回 503 + {degraded: true}
 */
import { NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';

// Skill adapter 走单独 spawn，但与 cognitive-client 同模式
// 为避免新增 lib 文件，这里直接内联 spawn 逻辑（与 cognitive-client 一致）
import { spawn } from 'child_process';
import path from 'path';

export interface SkillItem {
  name: string;
  description: string;
  version: string;
  status: 'shadow' | 'active' | 'deprecated' | 'proposed' | 'archived';
  category: string;
  triggers: string[];
  cognitive_links: string[];
  confidence: number;
  apply_count: number;
  last_verified: string | null;
  path: string;
}

interface SkillIndexData {
  schema_version: string;
  count: number;
  skills: SkillItem[];
}

const ADAPTER_PATH = path.join(process.cwd(), 'scripts', 'skill_index_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 15000;  // skill 扫描稍慢，给 15s

async function callSkillIndex<T>(
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
  const trigger = url.searchParams.get('trigger');
  const category = url.searchParams.get('category');
  const status = url.searchParams.get('status');

  // 任一过滤条件存在 → query；否则 list 全量
  const hasFilter = trigger || category || status;
  const command = hasFilter ? 'query' : 'list';
  const args: Record<string, unknown> = {};
  if (trigger) args.trigger = trigger;
  if (category) args.category = category;
  if (status) args.status = status;

  const result = await callSkillIndex<SkillIndexData>(command, args);

  if (!result.ok || !result.data) {
    return NextResponse.json(
      { degraded: true, error: result.error },
      { status: 503 }
    );
  }
  return NextResponse.json(result.data);
}
