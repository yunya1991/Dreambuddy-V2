import { NextRequest, NextResponse } from 'next/server';

// Yahoo Finance 公开行情，无需鉴权。服务端代理规避 CORS。
// 支持多 symbol 批量查询，减少请求数: /api/market/yahoo?symbols=GC=F,^GSPC,^IXIC
const YAHOO_BASE = 'https://query1.finance.yahoo.com';

function normalizeSymbol(s: string): string {
  // 前端可用 _ 代替 = 、__ 代替 ^ ，避免 URL 特殊字符问题
  // 顺序：先处理双下划线 ^ ，再处理单下划线 =
  return s.replace(/__/g, '^').replace(/_/g, '=');
}

async function fetchYahoo(symbol: string) {
  const url = `${YAHOO_BASE}/v8/finance/chart/${encodeURIComponent(symbol)}?interval=1d&range=1d`;
  const res = await fetch(url, {
    headers: { 'User-Agent': 'Mozilla/5.0', Accept: 'application/json' },
    next: { revalidate: 30 },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const body = await res.json();
  const result = body?.chart?.result?.[0];
  if (!result) throw new Error('no_result');
  const meta = result.meta;
  const price = meta.regularMarketPrice ?? meta.previousClose ?? 0;
  const prev = meta.chartPreviousClose ?? meta.previousClose ?? price;
  const change = prev ? ((price - prev) / prev) * 100 : 0;
  return {
    symbol,
    price: Number(price),
    previousClose: Number(prev),
    change24h: change,
    currency: meta.currency || 'USD',
    ts: meta.regularMarketTime ?? Math.floor(Date.now() / 1000),
  };
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const raw = searchParams.get('symbols') || 'GC=F,^GSPC,^IXIC,^VIX,CL=F,DX-Y.NYB';
  const symbols = raw.split(',').map(s => s.trim()).filter(Boolean).map(normalizeSymbol);

  try {
    const results = await Promise.all(
      symbols.map(async sym => {
        try {
          return { ok: true, ...(await fetchYahoo(sym)) };
        } catch (err) {
          return { ok: false, symbol: sym, error: err instanceof Error ? err.message : 'fetch_error' };
        }
      })
    );
    return NextResponse.json({ ok: true, data: results });
  } catch (err) {
    return NextResponse.json({ ok: false, error: err instanceof Error ? err.message : 'yahoo_unavailable' }, { status: 503 });
  }
}
