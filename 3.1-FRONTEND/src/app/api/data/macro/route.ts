/**
 * GET /api/data/macro
 * 宏观经济数据只读 API — 查询 DXY/US10Y/VIX/Gold/SP500 等指标。
 *
 * 无参数（返回全部可用宏观指标）
 *
 * FAIL-OPEN: 后端不可达返回 degraded:true, 不阻塞。
 * 只读: POST/PUT/DELETE 返回 405。
 */
import { NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 300; // 300秒缓存（宏观数据更新慢）

async function queryMacroData(): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'macro_data_query.py');
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath], { timeout: 5000 });
    return JSON.parse(stdout.trim());
  } catch (e: any) {
    return { degraded: true, error: e?.message || 'query_failed' };
  }
}

export async function GET() {
  const data = await queryMacroData();

  const response: any = {
    source: data.source || 'dal',
    timestamp: data.timestamp || new Date().toISOString(),
    degraded: data.degraded === true,
  };

  // 映射宏观指标
  const metrics = [
    'dxy', 'us10y_yield', 'vix', 'gold', 'sp500',
    'fed_funds_rate', 'nasdaq', 'm2_supply',
  ];

  for (const key of metrics) {
    if (data[key] !== undefined) {
      response[key] = data[key];
    }
  }

  if (data.error) {
    response.error = data.error;
  }

  return NextResponse.json(response);
}

export async function POST() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/macro is read-only, use GET' },
    { status: 405 }
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/macro is read-only, use GET' },
    { status: 405 }
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/macro is read-only, use GET' },
    { status: 405 }
  );
}
