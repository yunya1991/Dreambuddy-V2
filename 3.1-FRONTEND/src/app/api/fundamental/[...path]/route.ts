import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60; // 60秒缓存

// 所有 /api/fundamental/** 子路径统一走本地 aggregator (替代原 9094 反代)
async function handleFundamental(segments: string[]): Promise<NextResponse> {
  const subPath = segments.join('/');

  if (subPath === 'snapshot') {
    const scriptPath = path.join(process.cwd(), 'scripts', 'fundamental_snapshot.py');
    try {
      const { stdout } = await execFileAsync('python3', [scriptPath], {
        maxBuffer: 10 * 1024 * 1024,
        timeout: 15000,
      });
      const data = JSON.parse(stdout.trim());
      return NextResponse.json(data);
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

  return NextResponse.json(
    { error: `未实现的基本面子路径: ${subPath}`, available: ['snapshot'] },
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
