import { NextRequest, NextResponse } from 'next/server';

// OKX 公开行情接口，无需鉴权
const OKX_BASE = 'https://www.okx.com';
const OKX_BACKUP = 'https://aws.okx.com';

export async function GET(request: NextRequest, { params }: { params: Promise<{ symbol: string }> }) {
  const { symbol } = await params;
  const sym = (symbol || 'BTC').toUpperCase().replace(/[^A-Z0-9]/g, '');
  const instId = `${sym}-USDT`;

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

    if (body?.code !== '0' || !Array.isArray(body.data) || body.data.length === 0) {
      return NextResponse.json({ ok: false, error: body?.msg || 'no_data', instId }, { status: 404 });
    }

    const d = body.data[0];
    const last = Number(d.last);
    const open24h = Number(d.open24h);
    const change24h = open24h ? ((last - open24h) / open24h) * 100 : 0;

    return NextResponse.json({
      ok: true,
      symbol: sym,
      instId,
      price: last,
      open24h,
      high24h: Number(d.high24h),
      low24h: Number(d.low24h),
      change24h,
      volume24h: Number(d.vol24h),
      ts: Number(d.ts),
    });
  } catch (err) {
    return NextResponse.json(
      { ok: false, error: err instanceof Error ? err.message : 'okx_unavailable', instId },
      { status: 503 }
    );
  }
}
