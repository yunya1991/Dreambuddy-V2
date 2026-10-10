/**
 * GET /api/cognitive/unified
 * 统一认知查询 — 一次性查认知记忆 + SKILL + 知识库 + 文档索引。
 *
 * Query:
 *   query (required) - 查询文本
 *   top_k (default 3) - 每个系统返回上限
 *   systems (default all) - 逗号分隔: cognitive,skill,knowledge,index
 *
 * FAIL-OPEN: 各子系统独立降级，不互相阻塞。
 */
import { NextRequest, NextResponse } from 'next/server';
import { callCognitive } from '@/lib/cognitive-client';
import { spawn } from 'child_process';
import path from 'path';

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const SKILL_ADAPTER = path.join(process.cwd(), 'scripts', 'skill_index_adapter.py');
const KNOWLEDGE_ADAPTER = path.join(process.cwd(), 'scripts', 'knowledge_search_adapter.py');
const PYTHON_BIN = process.env.COGNITIVE_PYTHON || '/opt/anaconda3/bin/python3';
const TIMEOUT_MS = 30000;

function spawnAdapter(
  adapterPath: string,
  command: string,
  args: Record<string, unknown>
): Promise<{ ok: boolean; data?: unknown; error?: string }> {
  return new Promise((resolve) => {
    let stdoutBuf = '';
    let settled = false;
    const child = spawn(PYTHON_BIN, [adapterPath, command, JSON.stringify(args)], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      try { child.kill('SIGKILL'); } catch { /* noop */ }
      resolve({ ok: false, error: `timeout_${TIMEOUT_MS}ms` });
    }, TIMEOUT_MS);
    child.stdout.on('data', (chunk: Buffer) => { stdoutBuf += chunk.toString(); });
    child.stderr.on('data', () => { /* discard */ });
    child.on('error', (err) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve({ ok: false, error: `spawn_failed: ${err.message}` });
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
        resolve({ ok: false, error: `parse_failed: ${e instanceof Error ? e.message : String(e)}` });
      }
    });
  });
}

export async function GET(req: NextRequest) {
  const query = req.nextUrl.searchParams.get('query') || '';
  const topKRaw = req.nextUrl.searchParams.get('top_k') || '3';
  const systemsRaw = req.nextUrl.searchParams.get('systems') || 'cognitive,skill,knowledge,index';

  if (!query) {
    return NextResponse.json(
      { degraded: true, error: 'missing query param' },
      { status: 400 }
    );
  }

  const topK = Math.max(1, Math.min(20, parseInt(topKRaw, 10) || 3));
  const systems = systemsRaw.split(',').map(s => s.trim()).filter(Boolean);

  const wantCognitive = systems.includes('cognitive');
  const wantSkill = systems.includes('skill');
  const wantKnowledge = systems.includes('knowledge');
  const wantIndex = systems.includes('index');

  // 并行查询所有子系统，各自独立 FAIL-OPEN
  const tasks: Promise<unknown>[] = [];

  if (wantCognitive) {
    tasks.push(
      callCognitive('recall', { context: query, top_k: topK, min_quality: 'C' })
        .then(r => ({ type: 'cognitive', r }))
    );
  }
  if (wantSkill) {
    tasks.push(
      spawnAdapter(SKILL_ADAPTER, 'query', { trigger: query, top_k: topK })
        .then(r => ({ type: 'skill', r }))
    );
  }
  if (wantKnowledge) {
    tasks.push(
      spawnAdapter(KNOWLEDGE_ADAPTER, 'search', { query, top_k: topK, method: 'hybrid' })
        .then(r => ({ type: 'knowledge', r }))
    );
  }
  if (wantIndex) {
    tasks.push(
      spawnAdapter(SKILL_ADAPTER, 'list', {})
        .then(r => ({ type: 'index', r }))
    );
  }

  const results = await Promise.all(tasks) as Array<{ type: string; r: any }>;

  const response: Record<string, unknown> = { degraded: false };

  for (const { type, r } of results) {
    if (type === 'cognitive') {
      if (r.ok && r.data) {
        const memories = (r.data as any)?.memories || [];
        response.cognitive = memories.slice(0, topK).map((m: any) => ({
          content: m.content,
          score: m.score ?? 0,
          id: m.id,
          tags: m.tags,
          quality_level: m.quality_level,
        }));
      } else {
        response.cognitive = [];
        response.degraded = true;
      }
    } else if (type === 'skill') {
      if (r.ok && r.data) {
        const skills = (r.data as any)?.skills || [];
        response.skills = skills.slice(0, topK).map((s: any) => ({
          id: s.name,
          name: s.name,
          description: s.description,
          score: s.confidence ?? 0.5,
          category: s.category,
          status: s.status,
        }));
      } else {
        response.skills = [];
        response.degraded = true;
      }
    } else if (type === 'knowledge') {
      if (r.ok && r.data) {
        response.knowledge = (r.data as any).results || [];
        if ((r.data as any).degraded) response.degraded = true;
      } else {
        response.knowledge = [];
        response.degraded = true;
      }
    } else if (type === 'index') {
      if (r.ok && r.data) {
        const skills = (r.data as any)?.skills || [];
        response.index = skills.slice(0, topK).map((s: any) => ({
          path: s.path,
          title: s.name,
          description: s.description,
          score: 0.5,
        }));
      } else {
        response.index = [];
        response.degraded = true;
      }
    }
  }

  return NextResponse.json(response);
}
