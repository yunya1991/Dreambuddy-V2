import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; data: any }>();

// 「数据研究」五子页只读聚合：注册表 / 预注册空间 / 算法分类 / 关联图案。
// 前端零重算，数值全部来自脚本投影；脚本 FAIL-OPEN，这里只做超时与缓存。
export async function GET(request: NextRequest) {
  const top = Math.max(1, Math.min(Number(request.nextUrl.searchParams.get('top')) || 12, 50));
  const target = (request.nextUrl.searchParams.get('target') || '')
    .trim()
    .replace(/[^A-Za-z0-9./-]/g, '')
    .slice(0, 24);
  const horizon = Math.max(
    1,
    Math.min(Number(request.nextUrl.searchParams.get('horizon')) || 1, 60),
  );
  const cacheKey = `${top}|${target.toUpperCase()}|${horizon}`;
  const hit = cache.get(cacheKey);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    return NextResponse.json(hit.data);
  }

  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  const scriptPath = path.join(process.cwd(), 'scripts', 'visual_research.py');

  try {
    const args = [scriptPath, '--top', String(top)];
    if (target) args.push('--target', target, '--horizon', String(horizon));
    const { stdout } = await execFileAsync(pythonBin, args, {
      maxBuffer: 20 * 1024 * 1024,
      timeout: 20000,
    });
    const lines = stdout
      .trim()
      .split('\n')
      .filter((line: string) => line.trim().startsWith('{'));
    const data = JSON.parse(lines[lines.length - 1] || '{"ok":false,"degraded":true}');
    if (data?.ok) cache.set(cacheKey, { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json(
      {
        ok: false,
        degraded: true,
        reason: err?.message || String(err),
        recommendations: [],
        candidates: [],
      },
      { status: 503 },
    );
  }
}
