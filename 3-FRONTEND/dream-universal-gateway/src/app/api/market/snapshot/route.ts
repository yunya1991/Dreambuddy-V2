/**
 * 行情快照 API
 * GET /api/market/snapshot?symbol=BTC-USDT-SWAP
 * 调用 OKX CLI 获取实时行情数据，60秒缓存
 */
import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';

// 缓存
interface MarketCache {
  data: Record<string, unknown>;
  timestamp: number;
}
let cache: MarketCache | null = null;
const CACHE_TTL = 60 * 1000; // 60秒

const DEFAULT_SYMBOL = 'BTC-USDT-SWAP';
const SYMBOL_MAP: Record<string, string> = {
  BTC: 'BTC-USDT-SWAP',
  ETH: 'ETH-USDT-SWAP',
  SOL: 'SOL-USDT-SWAP',
  XAU: 'XAU-USD',
  GOLD: 'XAU-USD',
};

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

function resolveSymbol(input: string): string {
  const upper = input.toUpperCase();
  if (SYMBOL_MAP[upper]) return SYMBOL_MAP[upper];
  if (upper.includes('-')) return upper;
  // XAU/GOLD 特殊处理（不追加 -USDT-SWAP）
  if (upper === 'XAU' || upper === 'GOLD' || upper.startsWith('XAU')) return 'XAU-USD';
  return `${upper}-USDT-SWAP`;
}

function isForexOrCommodity(symbol: string): boolean {
  return FOREX_MOCKS.hasOwnProperty(symbol) || symbol.includes('XAU') || symbol === 'XAU-USD';
}

function parseTickerOutput(output: string): Record<string, unknown> | null {
  try {
    // OKX CLI 输出格式:
    //   instId                BTC-USDT-SWAP
    //   last                  79408.1
    //   24h open              80881.1
    //   24h high              80882.5
    //   24h low               78721.5
    //   24h vol               9269879.12
    //   24h change %          -1.82%
    //   time                  5/14/2026, 6:42:34 PM

    // 尝试JSON解析（某些版本可能输出JSON）
    try {
      const json = JSON.parse(output);
      if (json.data) return json.data;
    } catch {}

    const result: Record<string, unknown> = {};
    const lines = output.split('\n').filter((l) => l.trim());

    for (const line of lines) {
      // 精确key匹配: key和value之间用2个以上空格分隔
      const kvMatch = line.match(/^([\w %]+?)\s{2,}(.+)$/);
      if (!kvMatch) continue;

      const key = kvMatch[1].trim().toLowerCase();
      const value = kvMatch[2].trim();

      if (key === 'last') {
        result.price = parseFloat(value);
      } else if (key === '24h open') {
        result.open24h = parseFloat(value);
      } else if (key === '24h high') {
        result.high24h = parseFloat(value);
      } else if (key === '24h low') {
        result.low24h = parseFloat(value);
      } else if (key === '24h vol') {
        result.volume24h = value;
      } else if (key === '24h change %') {
        // 值如 "-1.82%" 或 "2.15%"
        result.change24h = parseFloat(value.replace('%', ''));
      } else if (key === 'instid') {
        result.instId = value;
      } else if (key === 'time') {
        result.time = value;
      }
    }

    return Object.keys(result).length > 0 ? result : null;
  } catch {
    return null;
  }
}

function parseFundingRateOutput(output: string): string | null {
  try {
    // OKX CLI 输出格式:
    //   instId                BTC-USDT-SWAP
    //   fundingRate           0.0000431149958820
    //   nextFundingRate       
    //   fundingTime           5/15/2026, 12:00:00 AM
    //   nextFundingTime       5/15/2026, 8:00:00 AM

    const lines = output.split('\n').filter((l) => l.trim());
    for (const line of lines) {
      const kvMatch = line.match(/^([\w %]+?)\s{2,}(.+)$/);
      if (!kvMatch) continue;

      const key = kvMatch[1].trim().toLowerCase();
      const value = kvMatch[2].trim();

      // 精确匹配 fundingRate（不是 nextFundingRate）
      if (key === 'fundingrate' && value) {
        return value;
      }
    }
    return null;
  } catch {
    return null;
  }
}

function parsePositionsOutput(output: string): Array<Record<string, unknown>> {
  try {
    if (output.includes('No open positions') || output.includes('空仓')) {
      return [];
    }

    const positions: Array<Record<string, unknown>> = [];
    const lines = output.split('\n').filter((l) => l.trim());

    let currentPos: Record<string, unknown> = {};
    for (const line of lines) {
      const kvMatch = line.match(/^([\w %]+?)\s{2,}(.+)$/);
      const trimmed = line.trim();

      if (trimmed.match(/[A-Z]+-USDT-SWAP/)) {
        if (Object.keys(currentPos).length > 0) positions.push(currentPos);
        currentPos = { symbol: trimmed.match(/[A-Z]+-USDT-SWAP/)?.[0] || trimmed };
      }

      if (kvMatch) {
        const key = kvMatch[1].trim().toLowerCase();
        const value = kvMatch[2].trim();

        if (key === 'posside' || key === 'side') {
          currentPos.side = value.toLowerCase();
        } else if (key === 'lever') {
          currentPos.leverage = value;
        } else if (key === 'upl') {
          currentPos.upl = parseFloat(value);
        }
      } else {
        // fallback: 旧的模糊匹配
        if (trimmed.includes('long') || trimmed.includes('多头')) currentPos.side = 'long';
        if (trimmed.includes('short') || trimmed.includes('空头')) currentPos.side = 'short';
      }
    }
    if (Object.keys(currentPos).length > 0) positions.push(currentPos);

    return positions;
  } catch {
    return [];
  }
}

export async function GET(request: NextRequest) {
  const { searchParams } = new URL(request.url);
  const symbolInput = searchParams.get('symbol') || DEFAULT_SYMBOL;
  const symbol = resolveSymbol(symbolInput);

  // 检查缓存
  const cacheKey = symbol;
  if (cache && cache.data[cacheKey] && Date.now() - cache.timestamp < CACHE_TTL) {
    return NextResponse.json({
      success: true,
      data: cache.data[cacheKey],
      cached: true,
    });
  }

  // ====== 外汇/大宗商品（黄金等）优先处理 —— 不调用 OKX CLI ======
  if (isForexOrCommodity(symbol)) {
    let result: Record<string, unknown> = {};
    if (FOREX_MOCKS[symbol]) {
      result = FOREX_MOCKS[symbol]();
    } else {
      // 其他品种的默认 mock
      result = {
        instId: symbol,
        symbol: symbol,
        displayName: symbol,
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
        note: `${symbol} 参考行情（模拟数据）`,
        isMock: true,
      };
    }

    // 更新缓存
    if (!cache || Date.now() - cache.timestamp >= CACHE_TTL) {
      cache = { data: { [cacheKey]: result }, timestamp: Date.now() };
    } else {
      cache.data[cacheKey] = result;
    }

    return NextResponse.json({ success: true, data: result, cached: false, source: 'forex-mock' });
  }

  try {
    // 并行获取行情数据
    let tickerData: Record<string, unknown> = {};
    let fundingRate: string | null = null;
    let positions: Array<Record<string, unknown>> = [];

    // 1. 获取Ticker
    try {
      const tickerOutput = execSync(
        `okx market ticker ${symbol} --profile dreamdemo`,
        { timeout: 15000, encoding: 'utf-8' }
      );
      const parsed = parseTickerOutput(tickerOutput);
      if (parsed) tickerData = parsed;
    } catch (error) {
      console.error('获取ticker失败:', error);
    }

    // 2. 获取资金费率
    try {
      const fundingOutput = execSync(
        `okx market funding-rate ${symbol} --profile dreamdemo`,
        { timeout: 15000, encoding: 'utf-8' }
      );
      fundingRate = parseFundingRateOutput(fundingOutput);
    } catch (error) {
      console.error('获取费率失败:', error);
    }

    // 3. 获取持仓（仅BTC）
    if (symbol === 'BTC-USDT-SWAP') {
      try {
        const positionsOutput = execSync(
          `okx account positions --profile dreamdemo`,
          { timeout: 15000, encoding: 'utf-8' }
        );
        positions = parsePositionsOutput(positionsOutput);
      } catch (error) {
        console.error('获取持仓失败:', error);
      }
    }

    const result = {
      symbol,
      ...tickerData,
      fundingRate,
      positions,
      timestamp: new Date().toISOString(),
    };

    // 更新缓存
    if (!cache || Date.now() - cache.timestamp >= CACHE_TTL) {
      cache = {
        data: { [cacheKey]: result },
        timestamp: Date.now(),
      };
    } else {
      cache.data[cacheKey] = result;
    }

    return NextResponse.json({
      success: true,
      data: result,
      cached: false,
    });
  } catch (error) {
    console.error('获取行情快照失败:', error);
    return NextResponse.json(
      { success: false, error: '获取行情数据失败' },
      { status: 500 }
    );
  }
}
