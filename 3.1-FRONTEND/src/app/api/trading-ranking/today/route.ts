import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 0; // 实时拉 orchestrator, 不缓存

export async function GET(request: NextRequest) {
  const scriptPath = path.join(process.cwd(), 'scripts', 'trading_ranking.py');
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath], {
      maxBuffer: 10 * 1024 * 1024,
      timeout: 90000, // orchestrator 冷启动 30s+, 给足 90s
    });
    const data = JSON.parse(stdout.trim());
    // 前端 RankingPage.tsx 期望: { success, items: [], metrics }
    return NextResponse.json(data);
  } catch (err: any) {
    // FAIL-OPEN: 返回 success=false + 空 items, 前端自然降级到 mock
    return NextResponse.json(
      {
        success: false,
        items: [],
        metrics: null,
        source: 'error',
        degraded: true,
        error: err?.message || String(err),
      },
      { status: 503 },
    );
  }
}
