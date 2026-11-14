import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60; // 60秒缓存

// 所有 /api/fundamental/** 子路径统一走本地 aggregator (替代原 9094 反代)
async function runAggregator(): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'fundamental_snapshot.py');
  const { stdout } = await execFileAsync('python3', [scriptPath], {
    maxBuffer: 10 * 1024 * 1024,
    timeout: 15000,
  });
  return JSON.parse(stdout.trim());
}

function clampDays(raw: string | null): number {
  const n = Number(raw || 0);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(Math.max(Math.trunc(n), 1), 1825);
}

async function handleFundamental(segments: string[], daysParam?: string | null): Promise<NextResponse> {
  const subPath = segments.join('/');

  if (subPath === 'snapshot') {
    try {
      return NextResponse.json(await runAggregator());
    } catch (err: any) {
      return NextResponse.json(
        {
          modules: {},
          timestamp: null,
          source: 'error',
          degraded: true,
          error: err?.message || String(err),
        },
        { status: 503 },
      );
    }
  }

  // <module>/snapshot：把聚合结果中单个模块适配为 ModuleDetail 需要的 ModuleSnapshot
  if (segments.length === 2 && segments[1] === 'snapshot') {
    const moduleKey = segments[0];
    try {
      const data = await runAggregator();
      const mod = data?.modules?.[moduleKey];
      if (!mod) {
        return NextResponse.json(
          { error: `未知模块: ${moduleKey}`, available: Object.keys(data?.modules || {}) },
          { status: 404 },
        );
      }
      const quality = mod?.meta?.data_quality || 'unknown';
      // S1: 支持 ?days=30|90|365 窗口切片（序列已在快照中一次性取回，避免重复查库）
      const windowDays = clampDays(daysParam ?? null);
      const rawTimeseries: Array<{ ts?: number; value?: number; direction_score?: number }> =
        mod?.timeseries || [];
      const cutoff = windowDays ? Math.floor(Date.now() / 1000) - windowDays * 86400 : 0;
      const timeseries = cutoff
        ? rawTimeseries.filter((p) => (p.ts || 0) >= cutoff)
        : rawTimeseries;
      const baseMeta = mod?.timeseries_meta || null;
      const timeseries_meta = baseMeta
        ? {
            ...baseMeta,
            days: windowDays || baseMeta.days,
            sample_n: timeseries.length,
            quality:
              timeseries.length === 0
                ? 'empty'
                : timeseries.length < 30
                  ? 'partial'
                  : baseMeta.quality,
          }
        : null;
      return NextResponse.json({
        module: moduleKey,
        ts: mod?.meta?.last_update || data?.timestamp || null,
        resistance_3d: {
          direction: '',
          direction_score: 0,
          confidence: quality === 'good' ? 1 : quality === 'partial' ? 0.5 : 0,
          data_points: Object.keys(mod?.metrics?.core || {}).length,
          trend_summary: `指标快照 · 数据质量 ${quality}`,
        },
        signals: mod?.signals || [],
        metrics: {
          core: mod?.metrics?.core || {},
          breakdown: mod?.metrics?.breakdown || {},
        },
        // S1: 真实历史序列（54 指标字典 → L0 datacenter.series），不再硬编码 []
        timeseries,
        timeseries_meta,
      });
    } catch (err: any) {
      return NextResponse.json(
        { error: err?.message || String(err), resistance_3d: null },
        { status: 503 },
      );
    }
  }

  return NextResponse.json(
    { error: `未实现的基本面子路径: ${subPath}`, available: ['snapshot', '<module>/snapshot'] },
    { status: 404 },
  );
}

export async function GET(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return handleFundamental(path, request.nextUrl.searchParams.get('days'));
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return handleFundamental(path, request.nextUrl.searchParams.get('days'));
}
