/**
 * market-data-adapter.ts
 * ======================
 * 统一数据源适配器：加密货币 → OKX，宏观金融 → Tavily
 * 路径 A (chat) 和路径 B (task) 共用同一套适配器
 */

import { execSync } from 'child_process';

// ============================================================
// 统一数据结构
// ============================================================

export type MarketCategory = 'crypto' | 'macro';

export interface MarketData {
  category: MarketCategory;
  symbol: string;           // 原始符号：BTC / GOLD / STOCK_US
  displayName: string;       // 显示名：BTC / 黄金 / 美股
  instId: string;           // OKX 合约代码（仅 crypto）
  price: number | null;
  change24h: number | null; // 百分比
  open24h: number | null;
  high24h: number | null;
  low24h: number | null;
  fundingRate: string | null;
  extraInfo?: string;       // Tavily 原始摘要
  timestamp: string;
  source: 'okx' | 'tavily' | 'error';
  error?: string;
}

// ============================================================
// OKX 数据源（加密货币）
// ============================================================

async function fetchOKXData(instId: string): Promise<Omit<MarketData, 'category' | 'symbol' | 'displayName' | 'instId'>> {
  const result = {
    price: null as number | null,
    open24h: null as number | null,
    high24h: null as number | null,
    low24h: null as number | null,
    change24h: null as number | null,
    fundingRate: null as string | null,
    timestamp: new Date().toISOString(),
    source: 'okx' as const,
  };

  try {
    const output = execSync(`okx market ticker ${instId} --profile dreamdemo`, {
      timeout: 10000,
      encoding: 'utf-8',
    });

    for (const line of output.split('\n')) {
      const kvMatch = line.match(/^([\w\s%]+?)\s{2,}(.+)$/);
      if (!kvMatch) continue;
      const key = kvMatch[1].trim().toLowerCase();
      const value = kvMatch[2].trim();
      if (key === 'last') result.price = parseFloat(value);
      else if (key === '24h open') result.open24h = parseFloat(value);
      else if (key === '24h high') result.high24h = parseFloat(value);
      else if (key === '24h low') result.low24h = parseFloat(value);
      else if (key === '24h change %') result.change24h = parseFloat(value.replace('%', ''));
    }
  } catch (error) {
    return { ...result, source: 'error', error: error instanceof Error ? error.message : String(error) };
  }

  // 资金费率
  try {
    const fundingOutput = execSync(`okx market funding-rate ${instId} --profile dreamdemo`, {
      timeout: 10000,
      encoding: 'utf-8',
    });
    for (const line of fundingOutput.split('\n')) {
      const kvMatch = line.match(/^([\w\s%]+?)\s{2,}(.+)$/);
      if (!kvMatch) continue;
      const key = kvMatch[1].trim().toLowerCase();
      const value = kvMatch[2].trim();
      if (key === 'fundingrate' && value) {
        result.fundingRate = value;
        break;
      }
    }
  } catch {
    // 忽略资金费率错误
  }

  return result;
}

// ============================================================
// Tavily 数据源（宏观金融）
// ============================================================

interface TavilyResult {
  success: boolean;
  answer: string;
  rawContent: string;
  error?: string;
}

async function fetchTavilyData(query: string, lang: 'zh' | 'en' = 'zh'): Promise<{ answer: string; rawContent: string; error?: string }> {
  const apiKey = process.env.TAVILY_API_KEY;
  if (!apiKey) {
    return { answer: '', rawContent: '', error: 'TAVILY_API_KEY not configured' };
  }

  // 中文查询使用中文数据源，提高返回中文内容的概率
  const requestBody: Record<string, unknown> = {
    api_key: apiKey,
    query,
    search_depth: 'basic',
    max_results: 5,
    include_images: false,
    include_answer: true,
    include_raw_content: false,
  };

  // Tavily 不直接支持 lang 参数，但可以限定数据源域名
  if (lang === 'zh') {
    requestBody.include_domains = [
      'zh.tradingeconomics.com',
      'xueqiu.com',
      'finance.sina.com.cn',
      'money.163.com',
      'eastmoney.com',
    ];
  }

  try {
    const response = await fetch('https://api.tavily.com/search', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      return { answer: '', rawContent: '', error: `Tavily API ${response.status}` };
    }

    const data = await response.json();
    return {
      answer: data.answer || '',
      rawContent: (data.results || []).map((r: any) => r.content).join('\n\n'),
    };
  } catch (error) {
    return { answer: '', rawContent: '', error: error instanceof Error ? error.message : String(error) };
  }
}

// ============================================================
// 品种符号定义（中心化，避免重复定义）
// ============================================================

export interface SymbolDefinition {
  patterns: string[];        // 匹配关键词
  symbol: string;            // 内部符号
  instId: string;            // OKX 合约代码（crypto only）
  category: MarketCategory;
  display: string;           // 显示名
  tavilyQuery: string;       // Tavily 搜索 query
}

// 所有品种定义（与 route.ts extractEntities 保持同步）
export const SYMBOL_DEFINITIONS: SymbolDefinition[] = [
  // 加密货币
  { patterns: ['btc', '比特币', 'bitcoin'], symbol: 'BTC', instId: 'BTC-USDT-SWAP', category: 'crypto', display: 'BTC', tavilyQuery: 'Bitcoin BTC price latest 2026' },
  { patterns: ['eth', '以太坊', 'ethereum'], symbol: 'ETH', instId: 'ETH-USDT-SWAP', category: 'crypto', display: 'ETH', tavilyQuery: 'Ethereum ETH price latest 2026' },
  { patterns: ['sol', 'solana'], symbol: 'SOL', instId: 'SOL-USDT-SWAP', category: 'crypto', display: 'SOL', tavilyQuery: 'Solana SOL price latest 2026' },
  { patterns: ['bnb'], symbol: 'BNB', instId: 'BNB-USDT-SWAP', category: 'crypto', display: 'BNB', tavilyQuery: 'BNB Binance coin price latest 2026' },
  { patterns: ['xrp', '瑞波'], symbol: 'XRP', instId: 'XRP-USDT-SWAP', category: 'crypto', display: 'XRP', tavilyQuery: 'XRP Ripple price latest 2026' },
  { patterns: ['doge', '狗狗币', 'dogecoin'], symbol: 'DOGE', instId: 'DOGE-USDT-SWAP', category: 'crypto', display: 'DOGE', tavilyQuery: 'Dogecoin DOGE price latest 2026' },
  { patterns: ['ordi'], symbol: 'ORDI', instId: 'ORDI-USDT-SWAP', category: 'crypto', display: 'ORDI', tavilyQuery: 'ORDI ordinals price latest 2026' },
  { patterns: ['sui'], symbol: 'SUI', instId: 'SUI-USDT-SWAP', category: 'crypto', display: 'SUI', tavilyQuery: 'Sui SUI price latest 2026' },
  // 宏观金融
  { patterns: ['美股', 's&p 500', 's&p500', 'sp500', 'sp 500', '标普', '道指', 'dow jones', 'nasdaq', '纳斯达克', 'spx', 'spy'], symbol: 'STOCK_US', instId: '', category: 'macro', display: '美股', tavilyQuery: 'S&P 500 Dow Jones Nasdaq stock market today latest price 2026' },
  { patterns: ['黄金', 'gold price', 'gold', 'xau', '金价'], symbol: 'GOLD', instId: '', category: 'macro', display: '黄金', tavilyQuery: 'gold price per ounce today XAU USD spot price latest 2026' },
  { patterns: ['白银', 'silver', 'xag'], symbol: 'SILVER', instId: '', category: 'macro', display: '白银', tavilyQuery: 'silver price per ounce today XAG USD 2026' },
  { patterns: ['原油', 'oil price', 'brent', 'wti', '油价', 'crude oil'], symbol: 'OIL', instId: '', category: 'macro', display: '原油', tavilyQuery: 'crude oil price WTI brent today latest 2026' },
  { patterns: ['人民币兑美元', 'rmb exchange', 'cny usd', 'usd cny', '美元人民币', '美金兑人民币'], symbol: 'CNY', instId: '', category: 'macro', display: '人民币汇率', tavilyQuery: 'USD to CNY Chinese yuan exchange rate today 2026' },
  { patterns: ['汇率', 'exchange rate', '外汇'], symbol: 'CNY', instId: '', category: 'macro', display: '人民币汇率', tavilyQuery: 'USD CNY exchange rate today 2026' },
  { patterns: ['人民币', 'cny', 'rmb', '离岸人民币', 'cnh'], symbol: 'CNY', instId: '', category: 'macro', display: '人民币汇率', tavilyQuery: 'USD to CNY Chinese yuan exchange rate today 2026' },
  { patterns: ['欧元', 'eur', 'euro'], symbol: 'EUR', instId: '', category: 'macro', display: '欧元', tavilyQuery: 'EUR USD euro exchange rate today 2026' },
  { patterns: ['日元', 'jpy', 'yen'], symbol: 'JPY', instId: '', category: 'macro', display: '日元', tavilyQuery: 'USD JPY Japanese yen exchange rate today 2026' },
  { patterns: ['美元指数', 'dxy', 'dollar index'], symbol: 'USD', instId: '', category: 'macro', display: '美元指数', tavilyQuery: 'US Dollar Index DXY today 2026' },
  { patterns: ['美元', 'usd', 'dollar'], symbol: 'USD', instId: '', category: 'macro', display: '美元', tavilyQuery: 'US Dollar Index DXY today 2026' },
  { patterns: ['当前美联储利率', '美联储利率', '联邦基金利率', 'federal funds rate', 'fed rate', 'fomc'], symbol: 'INTEREST_RATE', instId: '', category: 'macro', display: '美联储利率', tavilyQuery: 'US Federal Reserve interest rate FOMC current rate 2026' },
  { patterns: ['当前利率是多少', '当前利率', '利率是多少', '利率查询', 'interest rate', '央行利率', '加息', '降息', '当前加息'], symbol: 'INTEREST_RATE', instId: '', category: 'macro', display: '利率', tavilyQuery: 'US Federal Reserve interest rate FOMC policy 2026' },
  { patterns: ['通胀', 'inflation', 'cpi', '通货膨胀', '物价指数', '消费者价格'], symbol: 'INFLATION', instId: '', category: 'macro', display: '通胀数据', tavilyQuery: 'US CPI inflation rate latest data 2026' },
  { patterns: ['gdp', '经济增长', '经济数据', 'economy growth'], symbol: 'GDP', instId: '', category: 'macro', display: 'GDP', tavilyQuery: 'US GDP latest economic growth data 2026' },
  { patterns: ['宏观经济', '宏观', 'macro economy', 'macroeconomic'], symbol: 'MACRO', instId: '', category: 'macro', display: '宏观经济', tavilyQuery: 'global macroeconomic outlook financial market overview 2026' },
];

/**
 * 从消息中提取品种信息（与 route.ts extractEntities 共用同一套规则）
 */
export function extractSymbolFromMessage(msg: string): SymbolDefinition | null {
  const lower = msg.toLowerCase();

  let bestMatch: { def: SymbolDefinition; position: number } | null = null;

  for (const def of SYMBOL_DEFINITIONS) {
    for (const pattern of def.patterns) {
      const pos = lower.indexOf(pattern);
      if (pos !== -1) {
        if (!bestMatch || pos < bestMatch.position) {
          bestMatch = { def, position: pos };
        }
        break;
      }
    }
  }

  return bestMatch ? bestMatch.def : null;
}

// ============================================================
// 统一数据源适配器
// ============================================================

/**
 * 获取市场数据（自动选择 OKX 或 Tavily）
 * lang 参数决定搜索查询语言和输出格式
 */
export async function fetchMarketData(
  symbol: string,
  instId: string,
  category: MarketCategory,
  displayName: string,
  tavilyQuery?: string,
  lang: 'zh' | 'en' = 'zh',
): Promise<MarketData> {
  const base = { symbol, displayName, instId };

  if (category === 'crypto') {
    const okxData = await fetchOKXData(instId);
    return {
      ...base,
      category: 'crypto',
      ...okxData,
    };
  }

  // macro → Tavily，使用对应语言的搜索查询
  const isZh = lang === 'zh';
  const year = new Date().getFullYear();
  const zhQueries: Record<string, string> = {
    'STOCK_US': `美股 标普500 道琼斯 纳斯达克 今日最新行情 ${year}年`,
    'GOLD': `黄金价格 今日 XAU USD 现货黄金 每盎司 ${year}年`,
    'SILVER': `白银价格 XAG 今日最新 ${year}年`,
    'OIL': `原油价格 WTI 布伦特 今日最新 ${year}年`,
    'CNY': `人民币汇率 美元兑人民币 USD CNY 今日 ${year}年`,
    'EUR': `欧元汇率 EUR USD 今日 ${year}年`,
    'JPY': `日元汇率 USD JPY 今日 ${year}年`,
    'USD': `美元指数 DXY 今日 ${year}年`,
    'INTEREST_RATE': `美联储利率 联邦基金利率 FOMC 最新 ${year}年`,
    'INFLATION': `美国 CPI 通货膨胀率 最新数据 ${year}年`,
    'GDP': `美国 GDP 经济增长 最新数据 ${year}年`,
    'MACRO': `全球宏观经济 金融市场展望 ${year}年`,
  };

  const query = isZh
    ? (zhQueries[symbol] || `${displayName} 最新价格 ${year}年`)
    : (tavilyQuery || `${displayName} market price latest ${year}`);

  const tavilyData = await fetchTavilyData(query, lang);

  if (!tavilyData.answer && !tavilyData.rawContent) {
    return {
      ...base,
      category: 'macro',
      price: null,
      change24h: null,
      open24h: null,
      high24h: null,
      low24h: null,
      fundingRate: null,
      timestamp: new Date().toISOString(),
      source: 'error',
      error: tavilyData.error || 'No data from Tavily',
    };
  }

  return {
    ...base,
    category: 'macro',
    price: null,
    change24h: null,
    open24h: null,
    high24h: null,
    low24h: null,
    fundingRate: null,
    extraInfo: tavilyData.answer + (tavilyData.rawContent ? '\n\n' + tavilyData.rawContent.slice(0, 300) : ''),
    timestamp: new Date().toISOString(),
    source: 'tavily',
  };
}

/**
 * 格式化市场数据为统一响应字符串
 */
export function formatMarketData(data: MarketData, chain: string[], lang: 'zh' | 'en' = 'zh'): string {
  const chainLine = chain.join(' → ');
  const isZh = lang === 'zh';

  if (data.source === 'error' || (!data.price && !data.extraInfo)) {
    return isZh
      ? `📊 **${data.displayName} 行情数据**

> ⚠️ 暂无法获取 ${data.displayName} 行情数据
> 错误: ${data.error || 'Unknown error'}

请稍后重试，或尝试其他品种。`
      : `📊 **${data.displayName} Market Data**

> ⚠️ Unable to retrieve ${data.displayName} market data
> Error: ${data.error || 'Unknown error'}

Please try again later or try another symbol.`;
  }

  if (data.category === 'crypto' && data.price !== null) {
    const changeStr = data.change24h !== null
      ? `${data.change24h > 0 ? '+' : ''}${data.change24h.toFixed(2)}%`
      : 'N/A';
    const emoji = data.change24h === null ? '' : (data.change24h >= 0 ? '🟢' : '🔴');

    const header = isZh
      ? `📊 **${data.displayName} (${data.instId}) 实时行情**

> 由 Dream Gateway 中台即时生成 | 链路: ${chainLine}`
      : `📊 **${data.displayName} (${data.instId}) Real-time Market Data**

> Generated by Dream Gateway | Chain: ${chainLine}`;

    let result = `${header}

**${isZh ? '当前状态' : 'Current Status'}**
- ${isZh ? '当前价格' : 'Price'}: **$${data.price.toLocaleString()}** ${emoji}${changeStr} (24h)\n`;

    if (data.open24h !== null) result += `- ${isZh ? '24h开盘' : '24h Open'}: $${data.open24h.toLocaleString()}\n`;
    if (data.high24h !== null) result += `- ${isZh ? '24h最高' : '24h High'}: $${data.high24h.toLocaleString()}\n`;
    if (data.low24h !== null) result += `- ${isZh ? '24h最低' : '24h Low'}: $${data.low24h.toLocaleString()}\n`;
    if (data.fundingRate) {
      const frNum = parseFloat(data.fundingRate);
      if (!isNaN(frNum)) {
        const direction = isZh ? (frNum > 0 ? ' (偏多)' : ' (偏空)') : (frNum > 0 ? ' (Bullish)' : ' (Bearish)');
        result += `- ${isZh ? '资金费率' : 'Funding Rate'}: ${(frNum * 100).toFixed(4)}%${direction}\n`;
      }
    }
    result += `- ${isZh ? '更新时间' : 'Updated'}: ${new Date(data.timestamp).toLocaleString(isZh ? 'zh-CN' : 'en-US')}\n\n`;
    return result;
  }

  // macro → Tavily
  const header = isZh
    ? `📊 **${data.displayName} 实时行情**

> 由 Dream Gateway 中台即时生成 | 数据来源: Tavily 联网搜索 | 链路: ${chainLine}`
    : `📊 **${data.displayName} Real-time Market Data**

> Generated by Dream Gateway | Source: Tavily Web Search | Chain: ${chainLine}`;

  let result = `${header}\n\n`;

  if (data.extraInfo) {
    result += data.extraInfo.slice(0, 600) + (data.extraInfo.length > 600 ? '...' : '') + '\n\n';
  }
  result += `- ${isZh ? '更新时间' : 'Updated'}: ${new Date(data.timestamp).toLocaleString(isZh ? 'zh-CN' : 'en-US')}\n\n`;
  return result;
}
