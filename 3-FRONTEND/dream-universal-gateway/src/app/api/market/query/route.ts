/**
 * 行情查询 API
 * POST /api/market/query
 * 支持自然语言查询，提取交易对并返回行情数据
 */
import { NextRequest, NextResponse } from 'next/server';
import { execSync } from 'child_process';

// 交易对别名映射
const SYMBOL_ALIASES: Record<string, string> = {
  BTC: 'BTC-USDT-SWAP',
  BITCOIN: 'BTC-USDT-SWAP',
  ETH: 'ETH-USDT-SWAP',
  ETHEREUM: 'ETH-USDT-SWAP',
  SOL: 'SOL-USDT-SWAP',
  SOLANA: 'SOL-USDT-SWAP',
  DOGE: 'DOGE-USDT-SWAP',
  XRP: 'XRP-USDT-SWAP',
  ADA: 'ADA-USDT-SWAP',
  AVAX: 'AVAX-USDT-SWAP',
  DOT: 'DOT-USDT-SWAP',
  LINK: 'LINK-USDT-SWAP',
  MATIC: 'MATIC-USDT-SWAP',
  UNI: 'UNI-USDT-SWAP',
};

function extractSymbol(query: string): string | null {
  const upper = query.toUpperCase();

  // 1. 尝试匹配完整交易对格式
  const fullMatch = upper.match(/([A-Z]+)-USDT-SWAP/);
  if (fullMatch) return fullMatch[1];

  // 2. 尝试匹配 XXX-USDT 格式
  const simpleMatch = upper.match(/([A-Z]+)-USDT/);
  if (simpleMatch) return simpleMatch[1];

  // 3. 尝试匹配别名
  for (const [alias, symbol] of Object.entries(SYMBOL_ALIASES)) {
    if (upper.includes(alias)) {
      return symbol;
    }
  }

  // 4. 尝试提取3-5个连续大写字母
  const coinMatch = upper.match(/\b([A-Z]{2,5})\b/);
  if (coinMatch && SYMBOL_ALIASES[coinMatch[1]]) {
    return SYMBOL_ALIASES[coinMatch[1]];
  }

  return null;
}

export async function POST(request: NextRequest) {
  try {
    const body = await request.json();
    const { query } = body;

    if (!query || typeof query !== 'string') {
      return NextResponse.json(
        { success: false, error: '请提供查询内容' },
        { status: 400 }
      );
    }

    // 提取交易对
    const symbol = extractSymbol(query);
    if (!symbol) {
      return NextResponse.json({
        success: false,
        error: '无法识别交易对，请使用格式如 "BTC"、"ETH-USDT" 或 "SOL-USDT-SWAP"',
        supported: Object.keys(SYMBOL_ALIASES),
      });
    }

    // 调用OKX CLI获取数据
    try {
      const output = execSync(
        `okx market ticker ${symbol} --profile dreamdemo`,
        { timeout: 15000, encoding: 'utf-8' }
      );

      // 尝试获取资金费率
      let fundingRate = null;
      try {
        const fundOutput = execSync(
          `okx market funding-rate ${symbol} --profile dreamdemo`,
          { timeout: 15000, encoding: 'utf-8' }
        );
        const rateMatch = fundOutput.match(/-?0\.\d{4,}/);
        if (rateMatch) fundingRate = rateMatch[0];
      } catch {}

      return NextResponse.json({
        success: true,
        data: {
          symbol,
          rawOutput: output,
          fundingRate,
          query,
          timestamp: new Date().toISOString(),
        },
      });
    } catch (cliError) {
      return NextResponse.json({
        success: false,
        error: `获取${symbol}行情数据失败: ${cliError instanceof Error ? cliError.message : 'CLI调用失败'}`,
        symbol,
      });
    }
  } catch (error) {
    console.error('行情查询失败:', error);
    return NextResponse.json(
      { success: false, error: '行情查询失败' },
      { status: 500 }
    );
  }
}
