/**
 * 统一检索 API（阶段二 P1）
 * GET /api/search?query=xxx&module=all&limit=20
 *
 * 聚合四大模块数据源（报告/策略/记忆/文档），服务端模糊检索。
 * 权限：复用 NextAuth 会话，未登录返回 401；结果按会话可见范围过滤（当前单用户部署，全量返回）。
 * 相似案例：query 非空时附带 case-retriever 的 Soft Q 检索结果（FAIL-OPEN，失败不影响主结果）。
 */
import { NextRequest, NextResponse } from 'next/server';
import { spawn } from 'child_process';
import { auth } from '@/lib/auth';
import { getCaseRetriever } from '@/lib/case-retriever';
import type { SearchModule } from '@/lib/search/search-core';

interface ApiSearchItem {
  id: string;
  module: SearchModule;
  title: string;
  subtitle?: string;
  href: string;
  score: number;
}

/** spawn 执行 CLI 并经 stdin/stdout 交换 JSON */
function runCli(cli: string, args: string[], input: string, timeoutMs: number): Promise<string> {
  return new Promise((resolve, reject) => {
    const child = spawn(cli, args, {
      env: { ...process.env, FIS_PG_PASSWORD: process.env.FIS_PG_PASSWORD || 'xWazSBSwFwXqZkNdZzKVpz7L9pJxCiE' },
    });
    let out = '';
    let timer: ReturnType<typeof setTimeout> | undefined;
    child.stdout.on('data', (d) => { out += d; });
    child.stderr.on('data', () => {}); // 静默 stderr
    child.on('error', reject);
    child.on('close', (code) => {
      if (timer) clearTimeout(timer);
      if (code === 0) resolve(out);
      else reject(new Error(`cli exit ${code}`));
    });
    timer = setTimeout(() => {
      child.kill();
      reject(new Error('cli timeout'));
    }, timeoutMs);
    child.stdin.write(input);
    child.stdin.end();
  });
}
const FIS_CLI = '/home/ubuntu/fis-p0/.venv/bin/python';
const FIS_SCRIPT = '/home/ubuntu/fis-p0/scripts/search_cli.py';

/** 41 type → 前端 module 映射 */
function typeToModule(t: string): SearchModule {
  if (t === 'report') return 'report';
  if (t === 'strategy') return 'strategy';
  if (t === 'memory' || t === 'case') return 'memory';
  return 'doc'; // doc / code / 其他
}

/** 41 type → 前端跳转 href 推导 */
function typeToHref(t: string): string {
  if (t === 'report') return '/dashboard/reports';
  if (t === 'strategy') return '/dashboard/settings';
  if (t === 'memory' || t === 'case') return '/dashboard/memory';
  return '/dashboard';
}

/** spawn 桥接 41 search_api（BM25 倒排检索，E1 修正项） */
async function fisSearch(query: string, limit: number, moduleFilter: string): Promise<ApiSearchItem[] | null> {
  try {
    const filters = moduleFilter !== 'all' ? { module: [moduleFilter] } : undefined;
    const stdout = await runCli(
      FIS_CLI,
      [FIS_SCRIPT],
      JSON.stringify({ query, limit, filters }),
      10000,
    );
    const res = JSON.parse(stdout) as { success: boolean; hits?: Array<{ source: { path: string; line?: number }; score: number; snippet: string; type: string }> };
    if (!res.success || !Array.isArray(res.hits)) return null;
    return res.hits.map((h) => ({
      id: h.source.path,
      module: typeToModule(h.type),
      title: h.source.path.split('/').pop() || h.source.path,
      subtitle: h.snippet.slice(0, 80),
      href: typeToHref(h.type),
      score: h.score,
    }));
  } catch {
    return null; // FAIL-OPEN：桥接失败由调用方降级
  }
}

/** A4/E2（SPEC §7.6/§13.1）：41 recall() 补充候选（case 类型文档命中），注入相似案例池 */
async function fisRecallCases(query: string): Promise<Array<{ id: string; title: string; score: number }>> {
  try {
    const stdout = await runCli(FIS_CLI, [FIS_SCRIPT], JSON.stringify({ cmd: 'recall', query, limit: 20 }), 10000);
    const res = JSON.parse(stdout) as { success: boolean; hits?: Array<{ path: string; score: number; type: string }> };
    if (!res.success || !Array.isArray(res.hits)) return [];
    return res.hits
      .filter((h) => h.type === 'case')
      .map((h) => ({ id: h.path, title: h.path.split('/').pop() || h.path, score: h.score }));
  } catch {
    return []; // FAIL-OPEN
  }
}

/** 两路合并去重（按案例 id / 文档路径）：Soft Q 主链路 + 41 recall 补充候选（A4/E2，SPEC §7.6） */
async function getSimilarCases(query: string): Promise<Array<{ id: string; title: string; score: number }>> {
  let softQ: Array<{ id: string; title: string; score: number }> = [];
  try {
    const retriever = getCaseRetriever();
    const retrieval = await retriever.retrieve(query, 5);
    softQ = retrieval.cases.map((c, i) => ({
      id: String((c as unknown as Record<string, unknown>).id ?? i),
      title: String((c as unknown as Record<string, unknown>).title ?? (c as unknown as Record<string, unknown>).name ?? `案例 ${i + 1}`),
      score: retrieval.scores[i] ?? 0,
    }));
  } catch {
    // FAIL-OPEN：案例检索失败不影响主结果
  }
  const fis = await fisRecallCases(query);
  const seen = new Set<string>();
  const merged: Array<{ id: string; title: string; score: number }> = [];
  for (const item of [...softQ, ...fis]) {
    if (seen.has(item.id)) continue;
    seen.add(item.id);
    merged.push(item);
  }
  return merged.slice(0, 5);
}

/** 简易模糊匹配打分：包含命中 + 前缀命中加权（服务端无 minisearch 依赖） */
function fuzzyScore(text: string, q: string): number {
  const lower = text.toLowerCase();
  const idx = lower.indexOf(q);
  if (idx < 0) return 0;
  // 前缀命中权重更高
  return idx === 0 ? 3 : 2;
}

export async function GET(request: NextRequest) {
  // 会话过滤：未登录拒绝
  const session = await auth();
  if (!session?.user) {
    return NextResponse.json({ success: false, error: 'Unauthorized' }, { status: 401 });
  }

  const { searchParams } = new URL(request.url);
  const query = (searchParams.get('query') || '').trim().toLowerCase();
  const moduleFilter = searchParams.get('module') || 'all';
  const limit = Math.min(parseInt(searchParams.get('limit') || '20', 10) || 20, 50);

  if (!query) {
    return NextResponse.json({ success: true, results: [], similarCases: [], count: 0 });
  }

  // --- 主检索：优先 41 BM25 倒排（E1），FAIL-OPEN 降级前端聚合 ---
  const fisResults = await fisSearch(query, limit, moduleFilter);
  if (fisResults !== null) {
    // 相似案例：两路合并（Soft Q 主链路 + 41 recall 补充，A4/E2）
    const fisSimilar = await getSimilarCases(query);
    return NextResponse.json({ success: true, results: fisResults, similarCases: fisSimilar, count: fisResults.length, source: 'fis' });
  }

  // --- 聚合四大模块数据源（内部请求转发会话 cookie，FAIL-OPEN） ---
  const origin = new URL(request.url).origin;
  const cookie = request.headers.get('cookie') || '';
  const fetchJson = async (path: string): Promise<Record<string, unknown> | null> => {
    try {
      const res = await fetch(`${origin}${path}`, { headers: { cookie }, cache: 'no-store' });
      if (!res.ok) return null;
      return (await res.json()) as Record<string, unknown>;
    } catch {
      return null;
    }
  };

  const [reportsRes, briefingsRes, strategiesRes, channelsRes, apiKeysRes, proposalsRes, tasksRes] =
    await Promise.all([
      fetchJson('/api/reports'),
      fetchJson('/api/briefings'),
      fetchJson('/api/config/strategies'),
      fetchJson('/api/config/channels'),
      fetchJson('/api/config/api-keys'),
      fetchJson('/api/board/proposals'),
      fetchJson('/api/notebook/tasks'),
    ]);

  // --- 归一化为候选条目 ---
  interface Candidate {
    id: string;
    module: SearchModule;
    title: string;
    subtitle?: string;
    href: string;
  }
  const candidates: Candidate[] = [];
  const pushList = (
    data: Record<string, unknown> | null,
    key: string,
    module: SearchModule,
    href: string,
  ) => {
    if (!data) return;
    const list = data[key];
    if (!Array.isArray(list)) return;
    for (const raw of list) {
      const item = raw as Record<string, unknown>;
      const id = String(item.id ?? '');
      if (!id) continue;
      const title = String(item.title ?? item.name ?? id);
      candidates.push({
        id,
        module,
        title,
        subtitle: item.subtitle !== undefined ? String(item.subtitle) : undefined,
        href,
      });
    }
  };
  pushList(reportsRes, 'reports', 'report', '/dashboard/reports');
  pushList(briefingsRes, 'briefings', 'report', '/dashboard/reports');
  pushList(strategiesRes, 'strategies', 'strategy', '/dashboard/settings');
  pushList(channelsRes, 'channels', 'strategy', '/dashboard/settings');
  pushList(apiKeysRes, 'apiKeys', 'strategy', '/dashboard/settings');
  pushList(proposalsRes, 'proposals', 'strategy', '/dashboard/governance');
  pushList(tasksRes, 'tasks', 'memory', '/dashboard/notebook');

  // --- 模糊打分 + 模块过滤 + 排序截断 ---
  const results: ApiSearchItem[] = [];
  for (const c of candidates) {
    if (moduleFilter !== 'all' && c.module !== moduleFilter) continue;
    const score = fuzzyScore(c.title, query) || fuzzyScore(c.id, query) || (c.subtitle ? fuzzyScore(c.subtitle, query) : 0);
    if (score <= 0) continue;
    results.push({ id: c.id, module: c.module, title: c.title, subtitle: c.subtitle, href: c.href, score });
  }
  results.sort((a, b) => b.score - a.score);
  results.splice(limit);

  // --- 相似案例：两路合并（Soft Q 主链路 + 41 recall 补充，A4/E2） ---
  const similarCases = await getSimilarCases(query);

  return NextResponse.json({
    success: true,
    results,
    similarCases,
    count: results.length,
  });
}
