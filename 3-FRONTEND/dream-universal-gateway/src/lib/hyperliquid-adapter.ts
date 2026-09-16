/**
 * HyperLiquid 市场数据适配器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/hyperliquid-adapter.ts
 *
 * 职责:
 *   替代 OKX CLI，通过 HyperLiquid REST API 获取加密货币行情数据
 *   - 公开行情：价格、24h涨跌幅、24h开高低
 *   - 持仓查询：通过钱包地址查询用户持仓（需要 API 密钥）
 *
 * HyperLiquid API 文档: https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api
 */

// ============================================================
// 类型定义
// ============================================================

export interface HyperLiquidTicker {
  price: number | null;
  change24h: number | null;
  open24h: number | null;
  high24h: number | null;
  low24h: number | null;
  fundingRate: string | null;
  timestamp: string;
  source: 'hyperliquid';
}

export interface HyperLiquidPosition {
  coin: string;
  szi: string;
  entryPx: string;
  unrealizedPnl: string;
  leverage: string;
  side: 'long' | 'short';
}

// ============================================================
// 配置
// ============================================================

const HYPERLIQUID_API_URL = 'https://api.hyperliquid.xyz';
const HYPERLIQUID_WALLET = process.env.HYPERLIQUID_WALLET || '0x81cA2cf32b57a5790338c2b0d7Ca847abC18838a';

// 行情数据缓存（30 秒 TTL，避免重复调用 API）
const TICKER_CACHE_TTL = 30000;
const tickerCache = new Map<string, { data: HyperLiquidTicker; timestamp: number }>();

// 符号映射：将常见交易对映射为 HyperLiquid 的 coin 名称
const SYMBOL_MAP: Record<string, string> = {
  'BTC': 'BTC',
  'BTC-USDT-SWAP': 'BTC',
  'ETH': 'ETH',
  'ETH-USDT-SWAP': 'ETH',
  'SOL': 'SOL',
  'SOL-USDT-SWAP': 'SOL',
  'BNB': 'BNB',
  'DOGE': 'DOGE',
  'XRP': 'XRP',
  'ADA': 'ADA',
  'AVAX': 'AVAX',
  'LINK': 'LINK',
  'MATIC': 'MATIC',
  'DOT': 'DOT',
  'TRX': 'TRX',
  'LTC': 'LTC',
  'BCH': 'BCH',
  'ATOM': 'ATOM',
  'UNI': 'UNI',
  'NEAR': 'NEAR',
  'APT': 'APT',
  'OP': 'OP',
  'ARB': 'ARB',
  'SUI': 'SUI',
  'TIA': 'TIA',
  'SEI': 'SEI',
  'INJ': 'INJ',
  'FIL': 'FIL',
  'RUNE': 'RUNE',
};

/**
 * 将 OKX 合约代码或通用符号转换为 HyperLiquid coin 名称
 */
function toHyperLiquidCoin(instId: string): string {
  // 直接映射
  if (SYMBOL_MAP[instId]) return SYMBOL_MAP[instId];
  // 尝试提取基础符号（如 BTC-USDT-SWAP → BTC）
  const base = instId.split('-')[0].toUpperCase();
  if (SYMBOL_MAP[base]) return SYMBOL_MAP[base];
  return base;
}

// ============================================================
// 公开行情数据
// ============================================================

/**
 * 获取 HyperLiquid 行情数据（公开接口，无需 API 密钥）
 *
 * API: POST /info
 * Body: { type: 'l2Book', coin: 'BTC' } 或 { type: 'metaAndAssetCtxs' }
 */
export async function fetchHyperLiquidTicker(instId: string): Promise<HyperLiquidTicker> {
  const coin = toHyperLiquidCoin(instId);

  // 检查缓存：如果缓存存在且未过期，直接返回缓存数据
  const cached = tickerCache.get(coin);
  if (cached && Date.now() - cached.timestamp < TICKER_CACHE_TTL) {
    return cached.data;
  }

  const result: HyperLiquidTicker = {
    price: null,
    change24h: null,
    open24h: null,
    high24h: null,
    low24h: null,
    fundingRate: null,
    timestamp: new Date().toISOString(),
    source: 'hyperliquid',
  };

  try {
    // 获取所有资产的元数据和上下文数据
    const response = await fetch(`${HYPERLIQUID_API_URL}/info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'metaAndAssetCtxs' }),
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) {
      throw new Error(`HyperLiquid API 返回 ${response.status}`);
    }

    const data = await response.json();
    // data 格式: [meta, assetCtxs]
    // meta: { universe: [{ name: 'BTC', maxLeverage: 20, onlyIsolated: false }, ...] }
    // assetCtxs: [{ funding: 0.0001, openInterest: 1000, prevDayPx: 50000, dayNtlVlm: 5000000, premium: 0, oraclePx: 50100, markPx: 50050, midPx: 50050, ... }, ...]

    const meta = data[0];
    const assetCtxs = data[1];

    if (!meta?.universe || !Array.isArray(assetCtxs)) {
      throw new Error('HyperLiquid API 返回数据格式异常');
    }

    // 查找目标 coin
    const coinIndex = meta.universe.findIndex((u: { name: string }) => u.name === coin);
    if (coinIndex === -1) {
      throw new Error(`HyperLiquid 未找到 ${coin} 市场`);
    }

    const ctx = assetCtxs[coinIndex];
    if (!ctx) {
      throw new Error(`HyperLiquid ${coin} 上下文数据缺失`);
    }

    // 解析数据
    const markPx = parseFloat(ctx.markPx);
    const prevDayPx = parseFloat(ctx.prevDayPx);

    result.price = isNaN(markPx) ? null : markPx;
    result.open24h = isNaN(prevDayPx) ? null : prevDayPx;

    // 计算 24h 涨跌幅
    if (markPx && prevDayPx && prevDayPx > 0) {
      result.change24h = ((markPx - prevDayPx) / prevDayPx) * 100;
    }

    // 资金费率
    if (ctx.funding !== undefined && ctx.funding !== null) {
      result.fundingRate = (parseFloat(ctx.funding) * 100).toFixed(6) + '%';
    }

    // 获取 24h 最高最低价（通过 allMids 接口）
    try {
      const midsResponse = await fetch(`${HYPERLIQUID_API_URL}/info`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ type: 'allMids' }),
        signal: AbortSignal.timeout(5000),
      });

      if (midsResponse.ok) {
        const midsData = await midsResponse.json();
        // allMids 返回 { mids: { BTC: '50000', ETH: '3000', ... } }
        // 这里只有当前中间价，没有 24h 高低
        // 24h 高低暂时设为 null，后续可通过 trades 接口获取
      }
    } catch {
      // 忽略 allMids 错误
    }

  } catch (error) {
    console.error(`[HyperLiquid] 获取 ${coin} 行情失败:`, error);
    return {
      ...result,
      source: 'hyperliquid',
      timestamp: new Date().toISOString(),
    };
  }

  // 更新缓存
  if (result.price !== null) {
    tickerCache.set(coin, { data: result, timestamp: Date.now() });
  }

  return result;
}

// ============================================================
// 持仓查询（需要钱包地址）
// ============================================================

/**
 * 查询 HyperLiquid 用户持仓
 *
 * API: POST /info
 * Body: { type: 'clearinghouseState', user: '0x...' }
 */
export async function fetchHyperLiquidPositions(walletAddress?: string): Promise<HyperLiquidPosition[]> {
  const user = walletAddress || HYPERLIQUID_WALLET;

  try {
    const response = await fetch(`${HYPERLIQUID_API_URL}/info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'clearinghouseState',
        user: user,
      }),
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) {
      throw new Error(`HyperLiquid API 返回 ${response.status}`);
    }

    const data = await response.json();

    if (!data?.assetPositions || !Array.isArray(data.assetPositions)) {
      return [];
    }

    return data.assetPositions.map((ap: { position: { coin: string; szi: string; entryPx: string; unrealizedPnl: string; leverage: string; side: string } }) => ({
      coin: ap.position.coin,
      szi: ap.position.szi,
      entryPx: ap.position.entryPx,
      unrealizedPnl: ap.position.unrealizedPnl,
      leverage: ap.position.leverage,
      side: ap.position.side === 'B' ? 'long' : 'short',
    }));
  } catch (error) {
    console.error('[HyperLiquid] 查询持仓失败:', error);
    return [];
  }
}

// ============================================================
// 测试入口
// ============================================================

/**
 * 测试 HyperLiquid API 连通性
 */
export async function testHyperLiquidConnection(): Promise<boolean> {
  try {
    const ticker = await fetchHyperLiquidTicker('BTC');
    return ticker.price !== null;
  } catch {
    return false;
  }
}
