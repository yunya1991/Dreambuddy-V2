import { NextResponse } from 'next/server';

// BGeometrics (bitcoin-data.com) 公开 BTC 链上指标，免费无需鉴权
// 覆盖 MVRV / SOPR / NUPL / Puell Multiple / Realized Price / Active Addresses 等
const BASE = 'https://bitcoin-data.com/v1';

// 指标名 -> 端点路径 & 响应字段名
const METRICS: Record<string, { path: string; field: string }> = {
  mvrv: { path: '/mvrv', field: 'mvrv' },
  sopr: { path: '/sopr', field: 'sopr' },
  nupl: { path: '/nupl', field: 'nupl' },
  puell_multiple: { path: '/puell-multiple', field: 'puellMultiple' },
  active_addresses: { path: '/active-addresses', field: 'activeAddresses' },
  realized_price: { path: '/realized-price', field: 'realizedPrice' },
  aviv: { path: '/aviv', field: 'aviv' },
  nvt_ratio: { path: '/nvt-ratio', field: 'nvtRatio' },
};

async function fetchMetric(name: string): Promise<{ name: string; value: number; date: string } | null> {
  const cfg = METRICS[name];
  if (!cfg) return null;
  try {
    const res = await fetch(`${BASE}${cfg.path}`, { next: { revalidate: 3600 } });
    if (!res.ok) return null;
    const data = await res.json();
    if (!Array.isArray(data) || data.length === 0) return null;
    const latest = data[data.length - 1];
    const val = latest[cfg.field];
    if (val === undefined || val === null) return null;
    return { name, value: Number(val), date: latest.d || '' };
  } catch {
    return null;
  }
}

export async function GET(request: Request) {
  const { searchParams } = new URL(request.url);
  const requested = (searchParams.get('metrics') || 'mvrv,sopr,nupl,puell_multiple,realized_price,active_addresses')
    .split(',')
    .map(s => s.trim())
    .filter(s => s in METRICS);

  try {
    // free tier 限流严格(8次/小时)，串行请求并加延迟
    const map: Record<string, { value: number; date: string }> = {};
    for (const name of requested) {
      const r = await fetchMetric(name);
      if (r) map[r.name] = { value: r.value, date: r.date };
      await new Promise(resolve => setTimeout(resolve, 1200));
    }
    return NextResponse.json({ ok: true, metrics: map });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'bgeometrics_unavailable' },
      { status: 503 }
    );
  }
}
