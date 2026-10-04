import { NextResponse } from 'next/server';

// Blockchain.com 公开链上数据（BTC），无需鉴权
// 活跃地址、哈希率、交易笔数等
const BC_BASE = 'https://api.blockchain.info/charts';

async function fetchChart(name: string, timespan = '7days') {
  const res = await fetch(`${BC_BASE}/${name}?timespan=${timespan}&format=json`, {
    headers: { Accept: 'application/json' },
    next: { revalidate: 300 },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status} for ${name}`);
  const body = await res.json();
  const values = body?.values ?? [];
  if (values.length === 0) throw new Error(`no_values for ${name}`);
  const latest = values[values.length - 1].y;
  const avg = values.reduce((s: number, v: any) => s + v.y, 0) / values.length;
  return { latest, avg };
}

export async function GET() {
  try {
    const [addresses, hashRate, txCount] = await Promise.all([
      fetchChart('n-unique-addresses', '3days'),
      fetchChart('hash-rate', '3days'),
      fetchChart('n-transactions', '3days'),
    ]);
    return NextResponse.json({
      ok: true,
      active_addresses: Math.round(addresses.latest),
      active_addresses_7d_avg: Math.round(addresses.avg),
      hash_rate_ehs: Number((hashRate.latest / 1e6).toFixed(2)), // blockchain.info 单位 TH/s -> EH/s
      tx_24h: Math.round(txCount.latest),
      tx_7d_avg: Math.round(txCount.avg),
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'blockchain_unavailable' },
      { status: 503 }
    );
  }
}
