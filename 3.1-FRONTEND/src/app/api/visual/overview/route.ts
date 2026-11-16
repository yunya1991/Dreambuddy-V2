import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60;

// 资产池由前端按「回测排行 Top 标的」传入；符号白名单只做格式约束，不代替后端注册表校验
function normalizeSymbols(raw: string | null): string[] {
  if (!raw) return [];
  return raw
    .split(',')
    .map(s => s.trim().toUpperCase())
    .filter(s => /^[A-Z0-9^]{1,12}$/.test(s))
    .slice(0, 16);
}

async function runOverview(symbols: string[], history: number): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'visual_overview.py');
  const args = [scriptPath];
  if (symbols.length > 0) args.push('--symbols', symbols.join(','));
  if (history > 0) args.push('--history', String(history));
  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  // 影带回放需要逐期重跑 D-E19（约 +1.6s/期），仅显式请求时放宽超时；默认仍 25s
  const { stdout } = await execFileAsync(pythonBin, args, {
    maxBuffer: 20 * 1024 * 1024,
    timeout: history > 0 ? 60000 : 25000,
  });
  const lines = stdout.trim().split('\n').filter((l: string) => l.trim().startsWith('{'));
  return JSON.parse(lines[lines.length - 1] || '{}');
}

// 进程内 60s 缓存（按资产池分键）；失败结果不缓存，避免粘住故障
const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; data: any }>();

export async function GET(request: NextRequest) {
  const symbols = normalizeSymbols(request.nextUrl.searchParams.get('symbols'));
  // 点亮影带期数（T9-2）：0 = 不回溯（保持旧 payload）；上限 45 期，避免超时
  const history = Math.min(45, Math.max(0, Number(request.nextUrl.searchParams.get('history')) || 0));
  const cacheKey = `${symbols.join(',')}|h${history}`;
  const hit = cache.get(cacheKey);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    return NextResponse.json(hit.data);
  }

  try {
    const data = await runOverview(symbols, history);
    if (data?.ok) cache.set(cacheKey, { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (err: any) {
    // FAIL-OPEN：前端降级为空态，不伪造图
    return NextResponse.json(
      {
        ok: false,
        visuals: [],
        recommended: [],
        degraded: true,
        error: err?.message || String(err),
      },
      { status: 503 },
    );
  }
}
