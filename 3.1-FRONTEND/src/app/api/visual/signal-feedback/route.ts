import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60;

// 信号反馈（TASKS-20261116 T9-4）：只读 signal_journal + 日线，脚本内做非重叠采样。
// 前端零统计：命中率 / base_rate / n_eff 全部由脚本给出。
async function runFeedback(horizons: string): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'signal_feedback.py');
  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  const { stdout } = await execFileAsync(
    pythonBin,
    [scriptPath, '--horizons', horizons],
    { maxBuffer: 20 * 1024 * 1024, timeout: 30000 },
  );
  const lines = stdout.trim().split('\n').filter((line: string) => line.trim().startsWith('{'));
  return JSON.parse(lines[lines.length - 1] || '{}');
}

const CACHE_TTL_MS = 60_000;
const cache = new Map<string, { at: number; data: any }>();

export async function GET(request: NextRequest) {
  const raw = request.nextUrl.searchParams.get('horizons') || '5,20';
  const horizons = raw
    .split(',')
    .map((item) => Number(item.trim()))
    .filter((item) => Number.isInteger(item) && item > 0 && item <= 120)
    .slice(0, 4)
    .join(',');

  const key = horizons || '5,20';
  const hit = cache.get(key);
  if (hit && Date.now() - hit.at < CACHE_TTL_MS) {
    return NextResponse.json(hit.data);
  }

  try {
    const data = await runFeedback(key);
    if (data?.ok) cache.set(key, { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (err: any) {
    // FAIL-OPEN：前端降级空态，不伪造命中率
    return NextResponse.json(
      { ok: false, horizons: [], degraded: true, error: err?.message || String(err) },
      { status: 503 },
    );
  }
}
