/**
 * 多数据源适配器
 *
 * 位置: 3-FRONTEND/dream-universal-gateway/src/lib/market-data-sources.ts
 *
 * 职责:
 *   封装多个免费公开 API，为编排系统提供多维度市场数据：
 *   - 情绪面：恐惧贪婪指数（alternative.me）
 *   - 技术面：K线数据/蜡烛图（HyperLiquid）
 *   - 流动性：订单簿深度（HyperLiquid）
 *   - 资金面：已有 HyperLiquid 行情数据（价格、资金费率）
 *
 * 所有数据源均免费，无需 API Key（Tavily 新闻搜索除外）
 */

// ============================================================
// 类型定义
// ============================================================

export interface FearGreedData {
  value: number;          // 0-100
  classification: string;  // Extreme Fear / Fear / Neutral / Greed / Extreme Greed
  timestamp: string;
  history: Array<{ value: number; classification: string; timestamp: string }>;
}

export interface CandleData {
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  timestamp: number;
}

export interface OrderBookLevel {
  price: number;
  size: number;
}

export interface OrderBookData {
  bids: OrderBookLevel[];  // 买单（从高到低）
  asks: OrderBookLevel[];  // 卖单（从低到高）
  spread: number;          // 价差
  midPrice: number;        // 中间价
  bidDepth: number;        // 买盘总深度
  askDepth: number;        // 卖盘总深度
}

export interface TechnicalIndicators {
  sma5: number | null;     // 5根K线均线
  sma10: number | null;    // 10根K线均线
  sma20: number | null;    // 20根K线均线
  rsi: number | null;      // RSI 指标
  volatility: number | null; // 波动率
  volumeAvg: number | null;  // 平均成交量
  supportLevel: number | null;  // 支撑位
  resistanceLevel: number | null; // 阻力位
}

export interface MultiDimensionMarketData {
  // 资金面（来自 HyperLiquid 行情）
  price: number | null;
  open24h: number | null;
  change24h: number | null;
  fundingRate: string | null;

  // 情绪面（来自 alternative.me）
  fearGreed: FearGreedData | null;

  // 技术面（来自 HyperLiquid K线）
  candles: CandleData[];
  indicators: TechnicalIndicators;

  // 流动性（来自 HyperLiquid 订单簿）
  orderBook: OrderBookData | null;

  // 元信息
  timestamp: string;
  sources: string[];
}

// ============================================================
// 配置
// ============================================================

const HYPERLIQUID_API_URL = 'https://api.hyperliquid.xyz';
const FEAR_GREED_API_URL = 'https://api.alternative.me/fng';

// 缓存
const CACHE_TTL = 30000; // 30秒
const fearGreedCache = { data: null as FearGreedData | null, timestamp: 0 };
const candleCache = new Map<string, { data: CandleData[], timestamp: number }>();
const orderBookCache = new Map<string, { data: OrderBookData, timestamp: number }>();

// ============================================================
// 恐惧贪婪指数
// ============================================================

/**
 * 获取恐惧贪婪指数（情绪面数据）
 * 免费 API: https://api.alternative.me/fng/?limit=7
 */
export async function fetchFearGreedIndex(): Promise<FearGreedData | null> {
  // 检查缓存
  if (fearGreedCache.data && Date.now() - fearGreedCache.timestamp < CACHE_TTL) {
    return fearGreedCache.data;
  }

  try {
    const response = await fetch(`${FEAR_GREED_API_URL}/?limit=7`, {
      signal: AbortSignal.timeout(8000),
    });

    if (!response.ok) {
      throw new Error(`恐惧贪婪指数 API 返回 ${response.status}`);
    }

    const data = await response.json();
    const items = data.data || [];
    if (items.length === 0) return null;

    const latest = items[0];
    const result: FearGreedData = {
      value: parseInt(latest.value),
      classification: latest.value_classification,
      timestamp: new Date(parseInt(latest.timestamp) * 1000).toISOString(),
      history: items.slice(1, 7).map((item: { value: string; value_classification: string; timestamp: string }) => ({
        value: parseInt(item.value),
        classification: item.value_classification,
        timestamp: new Date(parseInt(item.timestamp) * 1000).toISOString(),
      })),
    };

    fearGreedCache.data = result;
    fearGreedCache.timestamp = Date.now();
    return result;
  } catch (error) {
    console.warn('[MarketDataSources] 恐惧贪婪指数获取失败:', error);
    return null;
  }
}

// ============================================================
// HyperLiquid K线数据
// ============================================================

/**
 * 获取 HyperLiquid K线数据（技术面数据）
 * API: POST /info  body: { type: 'candles', coin: 'BTC', interval: '1h', startTime: ... }
 */
export async function fetchCandles(coin: string, interval: string = '1h', count: number = 24): Promise<CandleData[]> {
  const cacheKey = `${coin}_${interval}_${count}`;
  const cached = candleCache.get(cacheKey);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL) {
    return cached.data;
  }

  try {
    const now = Date.now();
    const intervalMs = interval === '1h' ? 3600000 : interval === '15m' ? 900000 : interval === '4h' ? 14400000 : 3600000;
    const startTime = now - intervalMs * count;

    const response = await fetch(`${HYPERLIQUID_API_URL}/info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        type: 'candleSnapshot',
        req: { coin, interval, startTime },
      }),
      signal: AbortSignal.timeout(10000),
    });

    if (!response.ok) {
      throw new Error(`HyperLiquid K线 API 返回 ${response.status}`);
    }

    const data = await response.json();
    const rawCandles = Array.isArray(data) ? data : (data.candles || []);

    const candles: CandleData[] = rawCandles.slice(-count).map((c: { t: number; o: string; h: string; l: string; c: string; v: string }) => ({
      open: parseFloat(c.o),
      high: parseFloat(c.h),
      low: parseFloat(c.l),
      close: parseFloat(c.c),
      volume: parseFloat(c.v),
      timestamp: c.t,
    })).filter((c: CandleData) => !isNaN(c.close));

    candleCache.set(cacheKey, { data: candles, timestamp: Date.now() });
    return candles;
  } catch (error) {
    console.warn(`[MarketDataSources] K线数据获取失败 ${coin}:`, error);
    return [];
  }
}

/**
 * 计算技术指标
 */
export function calculateIndicators(candles: CandleData[]): TechnicalIndicators {
  if (candles.length === 0) {
    return {
      sma5: null, sma10: null, sma20: null,
      rsi: null, volatility: null, volumeAvg: null,
      supportLevel: null, resistanceLevel: null,
    };
  }

  const closes = candles.map(c => c.close);
  const volumes = candles.map(c => c.volume);
  const highs = candles.map(c => c.high);
  const lows = candles.map(c => c.low);

  // SMA
  const sma = (period: number): number | null => {
    if (closes.length < period) return null;
    const slice = closes.slice(-period);
    return slice.reduce((a, b) => a + b, 0) / period;
  };

  // RSI (14)
  const rsi = (): number | null => {
    if (closes.length < 15) return null;
    let gains = 0, losses = 0;
    for (let i = closes.length - 14; i < closes.length; i++) {
      const diff = closes[i] - closes[i - 1];
      if (diff > 0) gains += diff;
      else losses -= diff;
    }
    const avgGain = gains / 14;
    const avgLoss = losses / 14;
    if (avgLoss === 0) return 100;
    return 100 - (100 / (1 + avgGain / avgLoss));
  };

  // 波动率（标准差）
  const volatility = (): number | null => {
    if (closes.length < 2) return null;
    const returns = [];
    for (let i = 1; i < closes.length; i++) {
      returns.push((closes[i] - closes[i - 1]) / closes[i - 1]);
    }
    const mean = returns.reduce((a, b) => a + b, 0) / returns.length;
    const variance = returns.reduce((a, b) => a + (b - mean) ** 2, 0) / returns.length;
    return Math.sqrt(variance) * 100;
  };

  // 支撑位和阻力位
  const recentLows = lows.slice(-20).sort((a, b) => a - b);
  const recentHighs = highs.slice(-20).sort((a, b) => b - a);

  return {
    sma5: sma(5),
    sma10: sma(10),
    sma20: sma(20),
    rsi: rsi(),
    volatility: volatility(),
    volumeAvg: volumes.length > 0 ? volumes.reduce((a, b) => a + b, 0) / volumes.length : null,
    supportLevel: recentLows.length > 0 ? recentLows[0] : null,
    resistanceLevel: recentHighs.length > 0 ? recentHighs[0] : null,
  };
}

// ============================================================
// HyperLiquid 订单簿
// ============================================================

/**
 * 获取 HyperLiquid 订单簿（流动性数据）
 * API: POST /info  body: { type: 'l2Book', coin: 'BTC' }
 */
export async function fetchOrderBook(coin: string): Promise<OrderBookData | null> {
  const cached = orderBookCache.get(coin);
  if (cached && Date.now() - cached.timestamp < 10000) { // 订单簿缓存10秒
    return cached.data;
  }

  try {
    const response = await fetch(`${HYPERLIQUID_API_URL}/info`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ type: 'l2Book', coin }),
      signal: AbortSignal.timeout(8000),
    });

    if (!response.ok) {
      throw new Error(`HyperLiquid 订单簿 API 返回 ${response.status}`);
    }

    const data = await response.json();
    const levels = data.levels || {};
    const bids = (levels.bids || []).slice(0, 10).map((l: { px: string; sz: string }) => ({
      price: parseFloat(l.px),
      size: parseFloat(l.sz),
    }));
    const asks = (levels.asks || []).slice(0, 10).map((l: { px: string; sz: string }) => ({
      price: parseFloat(l.px),
      size: parseFloat(l.sz),
    }));

    if (bids.length === 0 || asks.length === 0) return null;

    const midPrice = (bids[0].price + asks[0].price) / 2;
    const spread = asks[0].price - bids[0].price;
    const bidDepth = bids.reduce((sum, b) => sum + b.size, 0);
    const askDepth = asks.reduce((sum, a) => sum + a.size, 0);

    const result: OrderBookData = { bids, asks, spread, midPrice, bidDepth, askDepth };
    orderBookCache.set(coin, { data: result, timestamp: Date.now() });
    return result;
  } catch (error) {
    console.warn(`[MarketDataSources] 订单簿获取失败 ${coin}:`, error);
    return null;
  }
}

// ============================================================
// 统一多维度数据获取
// ============================================================

/**
 * 获取多维度市场数据（资金面 + 情绪面 + 技术面 + 流动性）
 * 这是主入口函数，编排系统调用此函数获取所有维度的市场数据
 */
export async function fetchMultiDimensionMarketData(
  symbol: string,
  existingTicker?: { price: number | null; open24h: number | null; change24h: number | null; fundingRate: string | null }
): Promise<MultiDimensionMarketData> {
  const coin = symbol.split('-')[0].toUpperCase();
  const sources: string[] = [];

  // 并行获取所有数据源
  const [fearGreed, candles, orderBook] = await Promise.all([
    fetchFearGreedIndex(),
    fetchCandles(coin, '1h', 24),
    fetchOrderBook(coin),
  ]);

  if (fearGreed) sources.push('alternative.me');
  if (candles.length > 0) sources.push('hyperliquid-candles');
  if (orderBook) sources.push('hyperliquid-orderbook');

  const indicators = calculateIndicators(candles);

  return {
    price: existingTicker?.price ?? null,
    open24h: existingTicker?.open24h ?? null,
    change24h: existingTicker?.change24h ?? null,
    fundingRate: existingTicker?.fundingRate ?? null,
    fearGreed,
    candles: candles.slice(-6), // 最近6根K线
    indicators,
    orderBook,
    timestamp: new Date().toISOString(),
    sources,
  };
}

/**
 * 将多维度数据格式化为 prompt 注入文本
 */
export function formatMultiDimensionData(data: MultiDimensionMarketData): string {
  const parts: string[] = [];

  // 资金面
  if (data.price !== null) {
    parts.push(`\n实时行情（HyperLiquid）:`);
    parts.push(`  当前价格: ${data.price}`);
    if (data.open24h) parts.push(`  24h开盘价: ${data.open24h}`);
    if (data.change24h !== null) parts.push(`  24h涨跌幅: ${data.change24h.toFixed(2)}%`);
    if (data.fundingRate) parts.push(`  资金费率: ${data.fundingRate}`);
  }

  // 情绪面
  if (data.fearGreed) {
    parts.push(`\n情绪面数据（alternative.me）:`);
    parts.push(`  恐惧贪婪指数: ${data.fearGreed.value} (${data.fearGreed.classification})`);
    if (data.fearGreed.history.length > 0) {
      const trend = data.fearGreed.history.slice(-3).map(h => h.value).join(' → ');
      parts.push(`  近期趋势: ${trend} → ${data.fearGreed.value}`);
    }
  }

  // 技术面
  if (data.candles.length > 0) {
    const ind = data.indicators;
    parts.push(`\n技术面数据（HyperLiquid K线）:`);
    if (ind.sma5) parts.push(`  SMA5: ${ind.sma5.toFixed(2)}`);
    if (ind.sma10) parts.push(`  SMA10: ${ind.sma10.toFixed(2)}`);
    if (ind.sma20) parts.push(`  SMA20: ${ind.sma20.toFixed(2)}`);
    if (ind.rsi !== null) parts.push(`  RSI(14): ${ind.rsi.toFixed(1)}`);
    if (ind.volatility !== null) parts.push(`  波动率: ${ind.volatility.toFixed(2)}%`);
    if (ind.volumeAvg !== null) parts.push(`  平均成交量: ${ind.volumeAvg.toFixed(0)}`);
    if (ind.supportLevel) parts.push(`  近期支撑位: ${ind.supportLevel.toFixed(2)}`);
    if (ind.resistanceLevel) parts.push(`  近期阻力位: ${ind.resistanceLevel.toFixed(2)}`);

    // K线摘要
    const recentCandles = data.candles.slice(-3);
    const candleSummary = recentCandles.map(c =>
      `O:${c.open.toFixed(0)} H:${c.high.toFixed(0)} L:${c.low.toFixed(0)} C:${c.close.toFixed(0)} V:${c.volume.toFixed(0)}`
    ).join(' | ');
    parts.push(`  最近K线: ${candleSummary}`);
  }

  // 流动性
  if (data.orderBook) {
    const ob = data.orderBook;
    parts.push(`\n流动性数据（HyperLiquid 订单簿）:`);
    parts.push(`  价差: ${ob.spread.toFixed(2)}`);
    parts.push(`  买盘深度: ${ob.bidDepth.toFixed(2)}`);
    parts.push(`  卖盘深度: ${ob.askDepth.toFixed(2)}`);
    parts.push(`  买卖比: ${(ob.bidDepth / ob.askDepth).toFixed(2)}`);
  }

  parts.push(`\n数据来源: ${data.sources.join(', ') || '无'}`);
  parts.push(`数据时间: ${data.timestamp}`);

  return parts.join('\n');
}
