/**
 * 行情快照 API
 * GET /api/market/snapshot?symbol=BTC
 *
 * PROP-20260828A P5（2026-08-28，用户批准）:
 *   OKX CLI 在当前服务器网络环境不可达（www.okx.com 被墙），原实现恒 500。
 *   加密行情主源切换为 Hyperliquid 官方 REST API（api.hyperliquid.xyz，可达），
 *   备用源 alternative.me（仅 BTC）。外汇/大宗商品仍走本地 mock。60秒缓存保留。
 *
 * 数据源说明:
 *   - metaAndAssetCtxs: 最新价/前日价(≈24h open)/24h名义成交量/资金费率
 *   - candleSnapshot(1d): 当日 UTC 高/低
 *   - 持仓字段: OKX CLI 不可用, 恒返回空数组 + 说明
 */
import { NextRequest, NextResponse } from 'next/server';

// 缓存
interface MarketCache {
  data: Record<string, unknown>;
  timestamp: number;
}
let cache: MarketCache | null = null;
const CACHE_TTL = 60 * 1000; // 60秒

const DEFAULT_SYMBOL = 'BTC';
const HL_API = 'https://api.hyperliquid.xyz/info';
const FETCH_TIMEOUT_MS = 10000;

// 黄金/外汇 mock 数据（基于市场最近值 + 轻微随机波动，模拟实时行情）
const FOREX_MOCKS: Record<string, () => Record<string, unknown>> = {
  'XAU-USD': () => {
    const basePrice = 3085.0; // 黄金最近区间参考价
    const jitter = (Math.random() - 0.5) * 15; // ±7.5 美元随机
    const price = basePrice + jitter;
    const open = basePrice + (Math.random() - 0.5) * 8;
    const high = Math.max(price, open) + Math.random() * 6;
    const low = Math.min(price, open) - Math.random() * 6;
    const changePct = ((price - open) / open) * 100;
    return {
      instId: 'XAU-USD',
      symbol: 'XAU/USD',
      displayName: '黄金/美元 (现货)',
      category: 'commodity',
      price: parseFloat(price.toFixed(2)),
      open24h: parseFloat(open.toFixed(2)),
      high24h: parseFloat(high.toFixed(2)),
      low24h: parseFloat(low.toFixed(2)),
      change24h: parseFloat(changePct.toFixed(2)),
      volume24h: 'Spot Market',
      time: new Date().toLocaleString('zh-CN', { hour12: false }),
      unit: 'USD/oz',
      currency: 'USD',
      support_levels: [3070, 3050, 3020],
      resistance_levels: [3100, 3120, 3150],
      note: '黄金实时参考价 · 基于国际现货黄金市场最近成交价 + 轻微波动模拟',
      isMock: true,
    };
  },
};

/** 归一化币种代码: 兼容 OKX 风格（BTC-USDT-SWAP）与裸代码（BTC） */
function resolveCoin(input: string): string {
  const upper = input.toUpperCase().trim();
  if (upper === 'GOLD' || upper === 'XAU' || upper.startsWith('XAU')) return 'XAU-USD';
  // OKX instId 风格: 取首段
  if (upper.includes('-')) return upper.split('-')[0];
  return upper;
}

function isForexOrCommodity(symbol: string): boolean {
  return FOREX_MOCKS.hasOwnProperty(symbol) || symbol.includes('XAU') || symbol === 'XAU-USD';
}

async function hlPost(body: Record<string, unknown>): Promise<unknown> {
  const res = await fetch(HL_API, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`Hyperliquid HTTP ${res.status}`);
  return res.json();
}

interface HlAssetCtx {
  funding?: string;
  prevDayPx?: string;
  dayNtlVlm?: string;
  markPx?: string;
  midPx?: string;
  openInterest?: string;
}

/** 主源: Hyperliquid metaAndAssetCtxs + candleSnapshot(1d) */
async function fetchFromHyperliquid(coin: string): Promise<Record<string, unknown>> {
  const [metaAndCtxs, candles] = await Promise.all([
    hlPost({ type: 'metaAndAssetCtxs' }),
    hlPost({
      type: 'candleSnapshot',
      req: {
        coin,
        interval: '1d',
        startTime: Date.now() - 2 * 86400 * 1000,
        endTime: Date.now(),
      },
    }).catch(() => [] as unknown[]), // K线失败不阻断主流程
  ]);

  const [meta, assetCtxs] = metaAndCtxs as [
    { universe: Array<{ name: string }> },
    HlAssetCtx[],
  ];
  const idx = meta.universe.findIndex((u) => u.name === coin);
  if (idx < 0) throw new Error(`Hyperliquid 无此币种: ${coin}`);
  const ctx = assetCtxs[idx];

  const price = parseFloat(ctx.markPx || ctx.midPx || '0');
  const open24h = parseFloat(ctx.prevDayPx || '0');
  if (!price) throw new Error(`Hyperliquid 无 ${coin} 价格`);

  let high24h = price;
  let low24h = price;
  const candleArr = candles as Array<{ h?: string; l?: string }>;
  if (Array.isArray(candleArr) && candleArr.length > 0) {
    const last = candleArr[candleArr.length - 1];
    high24h = parseFloat(last.h || String(price));
    low24h = parseFloat(last.l || String(price));
  }

  const change24h = open24h ? ((price - open24h) / open24h) * 100 : 0;

  return {
    symbol: `${coin}-USDT-SWAP`,
    instId: `${coin}-USDT-SWAP`,
    price,
    open24h,
    high24h,
    low24h,
    change24h: parseFloat(change24h.toFixed(2)),
    volume24h: ctx.dayNtlVlm || '0',
    fundingRate: ctx.funding || null,
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    source: 'hyperliquid',
  };
}

/** 备用源: alternative.me（仅 BTC） */
async function fetchFromAlternativeMe(): Promise<Record<string, unknown>> {
  const res = await fetch('https://api.alternative.me/v2/ticker/BTC/', {
    signal: AbortSignal.timeout(FETCH_TIMEOUT_MS),
  });
  if (!res.ok) throw new Error(`alternative.me HTTP ${res.status}`);
  const json = await res.json();
  const btc = json?.data?.BTC;
  if (!btc) throw new Error('alternative.me 无 BTC 数据');
  const price = parseFloat(btc.price_usd);
  const change24h = parseFloat(btc.percent_change_24h || '0');
  return {
    symbol: 'BTC-USDT-SWAP',
    instId: 'BTC-USDT-SWAP',
    price,
    open24h: change24h ? price / (1 + change24h / 100) : price,
    high24h: null,
    low24h: null,
    change24h,
    volume24h: btc.volume_24h || '0',
    fundingRate: null,
    time: new Date().toLocaleString('zh-CN', { hour12: false }),
    source: 'alternative.me',
    note: '备用源数据: 无24h高低/资金费率',
  };
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbolInput = searchParams.get('symbol') || DEFAULT_SYMBOL;
  const coin = resolveCoin(symbolInput);

  // 检查缓存
  const cacheKey = coin;
  if (cache && cache.data[cacheKey] && Date.now() - cache.timestamp < CACHE_TTL) {
    return NextResponse.json({
      success: true,
      data: cache.data[cacheKey],
      cached: true,
    });
  }

  // ====== 外汇/大宗商品（黄金等）优先处理 —— 本地 mock ======
  if (isForexOrCommodity(coin)) {
    let result: Record<string, unknown> = {};
    if (FOREX_MOCKS[coin]) {
      result = FOREX_MOCKS[coin]();
    } else {
      result = {
        instId: coin,
        symbol: coin,
        displayName: coin,
        category: 'commodity',
        price: 100,
        open24h: 99.5,
        high24h: 101,
        low24h: 98.5,
        change24h: 0.5,
        volume24h: 'Spot Market',
        time: new Date().toLocaleString('zh-CN', { hour12: false }),
        unit: 'USD',
        currency: 'USD',
        note: `${coin} 参考行情（模拟数据）`,
        isMock: true,
      };
    }

    if (!cache || Date.now() - cache.timestamp >= CACHE_TTL) {
      cache = { data: { [cacheKey]: result }, timestamp: Date.now() };
    } else {
      cache.data[cacheKey] = result;
    }

    return NextResponse.json({ success: true, data: result, cached: false, source: 'forex-mock' });
  }

  // ====== 加密货币: Hyperliquid 主源 → alternative.me 备源（仅BTC） ======
  try {
    let tickerData: Record<string, unknown>;
    try {
      tickerData = await fetchFromHyperliquid(coin);
    } catch (hlError) {
      if (coin === 'BTC') {
        tickerData = await fetchFromAlternativeMe();
        console.warn(`Hyperliquid 失败, 已降级 alternative.me: ${hlError}`);
      } else {
        throw hlError;
      }
    }

    const result = {
      ...tickerData,
      positions: [] as Array<Record<string, unknown>>,
      positionsNote: 'OKX CLI 在当前环境不可用, 持仓数据暂缺',
      timestamp: new Date().toISOString(),
    };

    if (!cache || Date.now() - cache.timestamp >= CACHE_TTL) {
      cache = { data: { [cacheKey]: result }, timestamp: Date.now() };
    } else {
      cache.data[cacheKey] = result;
    }

    return NextResponse.json({
      success: true,
      data: result,
      cached: false,
      source: result.source,
    });
  } catch (error) {
    console.error('获取行情快照失败:', error);
    return NextResponse.json(
      {
        success: false,
        error: `获取行情数据失败: ${coin}`,
        detail: error instanceof Error ? error.message : String(error),
        sources_tried: coin === 'BTC' ? ['hyperliquid', 'alternative.me'] : ['hyperliquid'],
      },
      { status: 502 }
    );
  }
}
