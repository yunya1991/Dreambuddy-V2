/**
 * POST /api/config/strategies/parse
 *
 * 意图解析端点（不入库）— 将用户自然语言解析为结构化策略参数
 * 使用规则引擎（关键词匹配），后续可替换为 LLM 调用
 */
import { NextRequest, NextResponse } from 'next/server';

// === 关键词规则库 ===

interface ParseResult {
  intent: {
    direction: 'BUY' | 'SHORT' | 'SKIP';
    symbol: string;
    tradeType: 'SPOT' | 'SWAP';
    indicators: string[];
  };
  suggestedParams: {
    direction: 'BUY' | 'SHORT' | 'SKIP';
    symbol: string;
    tradeType: 'SPOT' | 'SWAP';
    leverage: number;
    positionSize: number;
    stopLoss: number | null;
    takeProfit: number | null;
  };
  confidence: number;       // 0-100
  explanation: string;       // 自然语言解释
  warnings: string[];        // 风险提示
}

// 做多关键词
const BUY_KEYWORDS = [
  { words: ['做多', '买入', '买', '看涨', 'bull', 'long', '抄底', '反弹', '入场'], weight: 3 },
  { words: ['超卖', 'oversold', '金叉', '底部', '支撑', '突破', 'breakout', '放量上涨'], weight: 2 },
];

// 做空关键词
const SHORT_KEYWORDS = [
  { words: ['做空', '卖出', '卖空', '看跌', 'bear', 'short', '逃顶', '做空'], weight: 3 },
  { words: ['超买', 'overbought', '死叉', '顶部', '阻力', '跌破', '放量下跌'], weight: 2 },
];

// 合约关键词
const SWAP_KEYWORDS = ['合约', '永续', 'swap', '杠杆', 'leverage', '期货', 'futures'];

// 品种识别
const SYMBOL_PATTERNS: [RegExp, string][] = [
  [/ETH|以太坊|ethereum/i, 'ETH-USDT-SWAP'],
  [/SOL|solana/i, 'SOL-USDT-SWAP'],
  [/BTC|比特币|bitcoin/i, 'BTC-USDT-SWAP'],
];

// 杠杆识别
const LEVERAGE_PATTERN = /(\d+)\s*[xX倍]?杠杆|杠杆\s*(\d+)[xX倍]?|(\d+)x/;

// 止损止盈识别
const STOP_LOSS_PATTERN = /止损\s*[\$¥]?\s*([\d,]+(?:\.\d+)?)/;
const TAKE_PROFIT_PATTERN = /止盈\s*[\$¥]?\s*([\d,]+(?:\.\d+)?)/;

function extractDirection(input: string): { direction: 'BUY' | 'SHORT' | 'SKIP'; score: number } {
  const lower = input.toLowerCase();
  let buyScore = 0;
  let shortScore = 0;

  for (const group of BUY_KEYWORDS) {
    for (const word of group.words) {
      if (lower.includes(word.toLowerCase())) buyScore += group.weight;
    }
  }

  for (const group of SHORT_KEYWORDS) {
    for (const word of group.words) {
      if (lower.includes(word.toLowerCase())) shortScore += group.weight;
    }
  }

  if (buyScore > shortScore) return { direction: 'BUY', score: Math.min(buyScore, 10) };
  if (shortScore > buyScore) return { direction: 'SHORT', score: Math.min(shortScore, 10) };
  return { direction: 'BUY', score: 1 }; // 默认做多
}

function extractSymbol(input: string): string {
  for (const [pattern, symbol] of SYMBOL_PATTERNS) {
    if (pattern.test(input)) return symbol;
  }
  return 'BTC-USDT-SWAP'; // 默认
}

function extractTradeType(input: string): 'SPOT' | 'SWAP' {
  const lower = input.toLowerCase();
  for (const kw of SWAP_KEYWORDS) {
    if (lower.includes(kw.toLowerCase())) return 'SWAP';
  }
  // 如果有杠杆关键词但无明确"现货"，默认合约
  if (/\d\s*[xX倍]|杠杆/.test(input)) return 'SWAP';
  return 'SPOT';
}

function extractLeverage(input: string): number {
  const match = input.match(LEVERAGE_PATTERN);
  if (match) {
    const val = parseInt(match[1] || match[2] || match[3]);
    if (val >= 1 && val <= 5) return val;
    if (val > 5) return 5; // 上限
  }
  // 有合约关键词但没指定数字，给个保守默认
  if (extractTradeType(input) === 'SWAP') return 2;
  return 1;
}

function extractStopLoss(input: string): number | null {
  const match = input.match(STOP_LOSS_PATTERN);
  return match ? parseFloat(match[1].replace(',', '')) : null;
}

function extractTakeProfit(input: string): number | null {
  const match = input.match(TAKE_PROFIT_PATTERN);
  return match ? parseFloat(match[1].replace(',', '')) : null;
}

function extractIndicators(input: string): string[] {
  const indicators: string[] = [];
  const patterns: [RegExp, string][] = [
    [/RSI|rsi/, 'RSI'],
    [/MACD|macd/, 'MACD'],
    [/MA\d+|均线|moving.*average/i, 'MA(均线)'],
    [/布林带|bollinger|BOLL/, '布林带'],
    [/成交量|volume|VOL/, '成交量'],
    [/KDJ|kdj/, 'KDJ'],
    [/EMA|ema/, 'EMA'],
    [/斐波那契|fibonacci|回调/, '斐波那契回调'],
    [/支撑位|阻力位|support|resistance/, '支撑/阻力'],
  ];
  for (const [pattern, name] of patterns) {
    if (pattern.test(input)) indicators.push(name);
  }
  return indicators;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { rawInput } = body;

    if (!rawInput || typeof rawInput !== 'string' || rawInput.trim().length < 4) {
      return NextResponse.json(
        { success: false, error: '请输入至少4个字符的策略描述' },
        { status: 400 }
      );
    }

    const input = rawInput.trim();

    // === 规则引擎解析 ===
    const dirResult = extractDirection(input);
    const symbol = extractSymbol(input);
    const tradeType = extractTradeType(input);
    const leverage = extractLeverage(input);
    const stopLoss = extractStopLoss(input);
    const takeProfit = extractTakeProfit(input);
    const indicators = extractIndicators(input);

    // 计算置信度 (基于信息完整度)
    let confidence = 40 + dirResult.score * 5;
    if (indicators.length > 0) confidence += 10;
    if (stopLoss !== null) confidence += 10;
    if (takeProfit !== null) confidence += 10;
    if (leverage > 1) confidence += 5;
    confidence = Math.min(confidence, 95);

    // 仓位建议 (基于杠杆和置信度)
    const positionSize = leverage > 1 ? Math.max(0.2, 0.6 - leverage * 0.1) : 0.5;

    // 风险提示
    const warnings: string[] = [];
    if (stopLoss === null) warnings.push('未设置止损，强烈建议添加止损价');
    if (leverage >= 3) warnings.push(`杠杆${leverage}x较高，注意爆仓风险`);
    if (indicators.length === 0) warnings.push('未检测到明确的技术指标，策略可能较模糊');
    if (confidence < 50) warnings.push('置信度较低，建议补充更多条件');

    // 生成自然语言解释
    const dirLabel = dirResult.direction === 'BUY' ? '做多' : dirResult.direction === 'SHORT' ? '做空' : '观望';
    const typeLabel = tradeType === 'SWAP' ? `永续合约 (${leverage}x杠杆)` : '现货';
    const indicatorStr = indicators.length > 0 ? indicators.join('、') : '综合分析';

    const explanation = `检测到您想要${dirLabel}${symbol.split('-')[0]}，使用${typeLabel}模式。基于${indicatorStr}信号触发，建议仓位 ${((positionSize) * 100).toFixed(0)}%。`;

    const result: ParseResult = {
      intent: {
        direction: dirResult.direction,
        symbol,
        tradeType,
        indicators,
      },
      suggestedParams: {
        direction: dirResult.direction,
        symbol,
        tradeType,
        leverage,
        positionSize: Math.round(positionSize * 100) / 100,
        stopLoss,
        takeProfit,
      },
      confidence,
      explanation,
      warnings,
    };

    return NextResponse.json({ success: true, data: result });
  } catch (error) {
    console.error('策略解析失败:', error);
    return NextResponse.json(
      { success: false, error: '策略解析失败，请检查输入' },
      { status: 500 }
    );
  }
}
