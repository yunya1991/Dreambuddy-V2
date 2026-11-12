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

async function handleFundamental(segments: string[]): Promise<NextResponse> {
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
        timeseries: [],
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
  return handleFundamental(path);
}

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ path: string[] }> },
) {
  const { path } = await params;
  return handleFundamental(path);
}
