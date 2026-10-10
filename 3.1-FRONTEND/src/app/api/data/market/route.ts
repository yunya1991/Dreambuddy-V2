import { NextRequest, NextResponse } from 'next/server';
import { execFile } from 'child_process';
import { promisify } from 'util';
import path from 'path';
import { fetchMetricViaTavily } from '@/lib/tavily-service';

const execFileAsync = promisify(execFile);

// OKX 公开行情接口，无需鉴权
const OKX_BASE = 'https://www.okx.com';
const OKX_BACKUP = 'https://aws.okx.com';

export const runtime = 'nodejs';
export const revalidate = 10; // 10秒缓存

interface OkxTicker {
  last: string;
  open24h: string;
  high24h: string;
  low24h: string;
  vol24h: string;
  ts: string;
}

async function fetchOkxPrice(symbol: string): Promise<OkxTicker | null> {
  const instId = `${symbol.toUpperCase()}-USDT`;
  const tryFetch = async (base: string) => {
    const res = await fetch(`${base}/api/v5/market/ticker?instId=${instId}`, {
      headers: { Accept: 'application/json' },
      next: { revalidate: 10 },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  };
  try {
    let body: any;
    try {
      body = await tryFetch(OKX_BASE);
    } catch {
      body = await tryFetch(OKX_BACKUP);
    }
    if (body?.code === '0' && Array.isArray(body.data) && body.data.length > 0) {
      return body.data[0] as OkxTicker;
    }
    return null;
  } catch {
    return null;
  }
}

async function queryMarketMetrics(): Promise<any> {
  const scriptPath = path.join(process.cwd(), 'scripts', 'market_data_query.py');
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

  // 并行获取 OKX 价格 + 本地指标
  const [okxData, metrics] = await Promise.all([
    fetchOkxPrice(symbol),
    queryMarketMetrics(),
  ]);

  const response: any = {
    symbol,
    source: 'okx+dal',
    timestamp: new Date().toISOString(),
    degraded: metrics.degraded === true && !okxData,
  };

  // OKX 实时价格
  if (okxData) {
    const price = parseFloat(okxData.last);
    const open = parseFloat(okxData.open24h);
    const change = open > 0 ? ((price - open) / open) * 100 : 0;
    response.price = price;
    response.change24h = change;
    response.high24h = parseFloat(okxData.high24h);
    response.low24h = parseFloat(okxData.low24h);
    response.volume24h = parseFloat(okxData.vol24h);
  }

  // 资金费率
  if (metrics.funding_rate && metrics.funding_rate.rate_pct !== undefined) {
    response.funding_rate = metrics.funding_rate.rate_pct;
    response.funding_rate_annualized = metrics.funding_rate.annualized_pct;
  }

  // 恐惧贪婪
  if (metrics.fear_greed && metrics.fear_greed.value !== undefined) {
    response.fear_greed = metrics.fear_greed.value;
    response.fear_greed_classification = metrics.fear_greed.classification;
  }

  // 多空比
  if (metrics.long_short_ratio && metrics.long_short_ratio.ratio !== undefined) {
    response.long_short_ratio = metrics.long_short_ratio.ratio;
    response.long_account_pct = metrics.long_short_ratio.long_pct;
    response.short_account_pct = metrics.long_short_ratio.short_pct;
  }

  // 持仓量（本地无，Tavily 补齐）
  if (metrics.open_interest === undefined || metrics.open_interest === null) {
    const oi = await fetchMetricViaTavily(
      `${symbol} open interest current 2026`,
      /[\$]?([\d,]+\.?\d*)\s*(?:billion|B|bn)/i,
      3
    );
    if (oi.value !== null) {
      response.open_interest = oi.value;
      response.open_interest_source = 'tavily';
    }
  } else {
    response.open_interest = metrics.open_interest;
    response.open_interest_source = 'dal';
  }

  // 爆仓数据（本地无，Tavily 补齐）
  if (metrics.liquidation === undefined || metrics.liquidation === null) {
    const liq = await fetchMetricViaTavily(
      `${symbol} liquidation 24h long short 2026`,
      /([\d,]+\.?\d*)\s*(?:million|M|mn)/i,
      3
    );
    if (liq.value !== null) {
      response.liquidation_24h = liq.value;
      response.liquidation_source = 'tavily';
    }
  } else {
    response.liquidation_24h = metrics.liquidation;
    response.liquidation_source = 'dal';
  }

  return NextResponse.json(response);
}

// 只读强制：POST 等写操作返回 405
export async function POST() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/market is read-only, use GET' },
    { status: 405 }
  );
}

export async function PUT() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/market is read-only, use GET' },
    { status: 405 }
  );
}

export async function DELETE() {
  return NextResponse.json(
    { error: 'Method Not Allowed', message: '/api/data/market is read-only, use GET' },
    { status: 405 }
  );
}
