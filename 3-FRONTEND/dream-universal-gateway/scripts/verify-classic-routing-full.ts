// 验证 developer 意图在 classic 模式下走 C 系列链
import { routeIntent } from '../src/lib/intent/smart-router';

console.log('\n========== [Developer 意图测试] ==========\n');

// Test 1: developer + classic
const r1 = routeIntent('developer' as any, 'moderate', {
  session_id: 'test_dev_classic',
  user_role: 'FREE',
  thinking_mode: 'deep',
  trading_mode: 'classic',
  message_history: [],
});

console.log(`【Test 1】developer + classic →`);
console.log(`  chain: ${r1.chain.join(' → ')}`);
console.log(`  is_classic_mode: ${(r1 as any).is_classic_mode}`);
console.log(`  loop_type: ${r1.loop_type}`);
console.log(`  ${r1.chain.some((s: string) => s.startsWith('C')) && (r1 as any).is_classic_mode === true ? '✅ PASS' : '❌ FAIL'}`);
console.log('');

// Test 2: developer + ai_skill（对比，应该是空链或走原路线）
const r2 = routeIntent('developer' as any, 'moderate', {
  session_id: 'test_dev_ai',
  user_role: 'FREE',
  thinking_mode: 'deep',
  trading_mode: 'ai_skill',
  message_history: [],
});

console.log(`【Test 2】developer + ai_skill →`);
console.log(`  chain: ${r2.chain.join(' → ') || '(empty - will fall to S5 engine in route.ts)'}`);
console.log(`  is_classic_mode: ${(r2 as any).is_classic_mode}`);
console.log(`  ${(r2 as any).is_classic_mode !== true ? '✅ PASS' : '❌ FAIL'}`);
console.log('');

// Test 3: execute_trade + classic
const r3 = routeIntent('execute_trade' as any, 'moderate', {
  session_id: 'test_exec_classic',
  user_role: 'FREE',
  thinking_mode: 'deep',
  trading_mode: 'classic',
  message_history: [],
});

console.log(`【Test 3】execute_trade + classic →`);
console.log(`  chain: ${r3.chain.join(' → ')}`);
console.log(`  is_classic_mode: ${(r3 as any).is_classic_mode}`);
console.log(`  ${r3.chain.length === 8 && (r3 as any).is_classic_mode === true ? '✅ PASS' : '❌ FAIL'}`);
console.log('');

// Test 4: 验证 smart-router 中的所有意图映射
const allIntents = [
  'deep_analysis', 'market_query', 'macro_analysis', 'strategy_recommendation',
  'entry_timing', 'exit_timing', 'risk_analysis', 'position_review',
  'portfolio_review', 'trend_analysis', 'volatility_analysis', 'arbitrage_opportunity',
  'market_sentiment', 'market_microstructure', 'portfolio_rebalance', 'sector_rotation',
  'developer', 'continue', 'execute_trade',
];

console.log(`【Test 4】所有 ${allIntents.length} 个意图在 classic 模式下的路由测试:`);
let pass = 0, fail = 0;
for (const intent of allIntents) {
  const result = routeIntent(intent as any, 'moderate', {
    session_id: `test_${intent}_classic`,
    user_role: 'FREE',
    thinking_mode: 'deep',
    trading_mode: 'classic',
    message_history: [],
  });
  const isClassic = (result as any).is_classic_mode === true;
  const hasChain = result.chain.length > 0;
  const allCSteps = result.chain.every((s: string) => s.startsWith('C'));
  if (isClassic && hasChain && allCSteps) {
    pass++;
    console.log(`  ✅ ${intent.padEnd(25)} → ${result.chain.join(' → ')}`);
  } else {
    fail++;
    console.log(`  ❌ ${intent.padEnd(25)} → ${result.chain.join(' → ') || '(empty)'}`);
  }
}

console.log(`\n  总计: ${pass}/${allIntents.length} 通过, ${fail}/${allIntents.length} 失败`);
console.log(`  结果: ${fail === 0 ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED'}\n`);
