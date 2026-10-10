/**
 * GET /api/data/chain
 * 链上数据只读 API — 查询指定标的的链上指标。
 *
 * Query:
 *   symbol (required) - 标的，如 BTC
 *   metrics (optional) - 逗号分隔指标列表
 *
 * FAIL-OPEN: 后端不可达返回 degraded:true, 不阻塞。
 * 只读: POST/PUT/DELETE 返回 405。
 */
import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';

const execFileAsync = promisify(execFile);

export const runtime = 'nodejs';
export const revalidate = 60; // 60秒缓存

async function queryChainData(): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'chain_data_query.py');
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath], { timeout: 5000 });
    return JSON.parse(stdout.trim());
  } catch (e: any) {
    return { degraded: true, error: e?.message || 'query_failed' };
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbol = (searchParams.get('symbol') || 'BTC').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const metricsFilter = searchParams.get('metrics');

  const data = await queryChainData();

  const response: any = {
    symbol,
    source: data.source || 'dal',
    timestamp: data.timestamp || new Date().toISOString(),
    degraded: data.degraded === true,
  };

  // 映射链上指标到响应
  const allMetrics: Record<string, string> = {
    active_addresses_24h: 'active_addresses_24h',
    hash_rate: 'hash_rate',
    difficulty_change_pct: 'difficulty_change_pct',
    mempool_count: 'mempool_count',
    exchange_inflow_24h: 'exchange_inflow_24h',
    exchange_balance_btc: 'exchange_balance_btc',
    large_transfers_24h: 'large_transfers_24h',
    whale_netflow_24h: 'whale_netflow_24h',
  };

  for (const [key, dbKey] of Object.entries(allMetrics)) {
    if (data[dbKey] !== undefined) {
      if (!metricsFilter || metricsFilter.split(',').includes(key)) {
        response[key] = data[dbKey];
      }
    }
  }

  return NextResponse.json(response);
}

export async function POST() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/chain is read-only, use GET' },
    { status: 405 }
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/chain is read-only, use GET' },
    { status: 405 }
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/chain is read-only, use GET' },
    { status: 405 }
  );
}
