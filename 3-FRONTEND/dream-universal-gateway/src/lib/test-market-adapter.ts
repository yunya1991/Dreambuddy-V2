/**
 * 临时测试脚本：验证 market-data-adapter 是否能正确获取数据
 * 运行: `npx tsx src/lib/test-market-adapter.ts`
 */

import { fetchMarketData } from './market-data-adapter';

async function test() {
  console.log('======== 测试 1: BTC (OKX) ========');
  try {
    const result = await fetchMarketData('BTC', 'BTC-USDT-SWAP', 'crypto', 'BTC / USDT 永续合约', undefined, 'zh');
    console.log('✅ 成功:', {
      symbol: result.symbol,
      price: result.price,
      change24h: result.change24h,
      high24h: result.high24h,
      low24h: result.low24h,
      source: result.source,
      fundingRate: result.fundingRate,
    });
  } catch (e) {
    console.log('❌ 失败:', e);
  }

  console.log('\n======== 测试 2: 黄金 (Tavily) ========');
  try {
    const result = await fetchMarketData('XAU', '', 'macro', '黄金', 'gold price per ounce today in USD', 'zh');
    console.log('✅ 成功:', {
      symbol: result.symbol,
      price: result.price,
      change24h: result.change24h,
      source: result.source,
      extraInfo: (result.extraInfo || '').slice(0, 200),
    });
  } catch (e) {
    console.log('❌ 失败:', e);
  }

  console.log('\n======== 测试 3: ETH (OKX) ========');
  try {
    const result = await fetchMarketData('ETH', 'ETH-USDT-SWAP', 'crypto', 'ETH / USDT 永续合约', undefined, 'zh');
    console.log('✅ 成功:', {
      symbol: result.symbol,
      price: result.price,
      change24h: result.change24h,
      source: result.source,
    });
  } catch (e) {
    console.log('❌ 失败:', e);
  }
}

test();
