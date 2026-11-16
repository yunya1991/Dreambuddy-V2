import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const dynamic = 'force-dynamic';

// SPEC-54 R6：resolve 观测报表（按日聚合 / 分档 P95 / 失败 code 分布 / 5 分钟告警）
// 观测失败不影响取数：这里只读 SQLite，异常一律 503 + degraded。
const REPORT_TTL_MS = 30_000;
const reportCache = new Map<string, { at: number; data: any }>();

export async function GET(request: NextRequest) {
  const days = Math.min(Math.max(Number(request.nextUrl.searchParams.get('days')) || 7, 1), 90);
  const hit = reportCache.get(String(days));
  if (hit && Date.now() - hit.at < REPORT_TTL_MS) {
    return NextResponse.json(hit.data);
  }

  const pythonBin = process.env.COGNITIVE_PYTHON || process.env.PYTHON || 'python3';
  const scriptPath = path.join(process.cwd(), 'scripts', 'resolve_metrics.py');
  try {
    const { stdout } = await execFileAsync(pythonBin, [scriptPath, '--report', '--days', String(days)], {
      maxBuffer: 8 * 1024 * 1024,
      timeout: 15_000,
    });
    const lines = stdout
      .trim()
      .split('\n')
      .filter((line) => line.trim().startsWith('{'));
    const data = JSON.parse(lines[lines.length - 1] || '{}');
    if (data?.ok) reportCache.set(String(days), { at: Date.now(), data });
    return NextResponse.json(data);
  } catch (err: any) {
    return NextResponse.json(
      { ok: false, degraded: true, reason: err?.message || String(err) },
      { status: 503 },
    );
  }
}
