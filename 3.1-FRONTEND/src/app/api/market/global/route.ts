import { NextResponse } from 'next/server';

// Coingecko 公开全局市场数据，含 BTC 主导率、总市值等，无需鉴权
export async function GET() {
  try {
    const res = await fetch('https://api.coingecko.com/api/v3/global', {
      headers: { Accept: 'application/json' },
      next: { revalidate: 60 },
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    const body = await res.json();
    const data = body?.data;
    if (!data) throw new Error('no_data');
    return NextResponse.json({
      ok: true,
      btc_dominance: Number(data.market_cap_percentage?.btc ?? 0),
      eth_dominance: Number(data.market_cap_percentage?.eth ?? 0),
      total_market_cap: Number(data.total_market_cap?.usd ?? 0),
      total_volume_24h: Number(data.total_volume?.usd ?? 0),
      market_cap_change_24h: Number(data.market_cap_change_percentage_24h_usd ?? 0),
      active_cryptocurrencies: Number(data.active_cryptocurrencies ?? 0),
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'coingecko_unavailable' },
      { status: 503 }
    );
  }
}
