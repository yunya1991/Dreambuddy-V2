// 验证 execute_trade + classic 模式走哪个分支
import { isConversationIntent, isTradeIntent } from '../src/lib/task-manager';

console.log('========== 意图分类验证 ==========\n');

// TEST 1: execute_trade 的分类
console.log('【Test 1】execute_trade 意图分类:');
console.log(`  isConversationIntent('execute_trade') = ${isConversationIntent('execute_trade' as any)}`);
console.log(`  isTradeIntent('execute_trade') = ${isTradeIntent('execute_trade' as any)}`);
console.log('');

// TEST 2: 模拟 createAndExecuteTask 的决策逻辑
console.log('【Test 2】模拟 createAndExecuteTask 分支决策:');

const testCases = [
  { intent: 'execute_trade', mode: 'classic' },
  { intent: 'execute_trade', mode: 'ai_skill' },
  { intent: 'deep_analysis', mode: 'classic' },
  { intent: 'market_query', mode: 'classic' },
];

for (const tc of testCases) {
  const isClassic = tc.mode === 'classic';
  const isConv = isConversationIntent(tc.intent as any);
  const isTrade = isTradeIntent(tc.intent as any);

  let branch = '⚠️ unknown';
  if (isClassic && isConv) branch = '✅ executeClassicChain()';
  else if (isClassic && isTrade) branch = '❌ generateTradePendingResult() - WRONG BRANCH!';
  else if (isConv) branch = 'executeConversationTaskInline()';
  else if (isTrade) branch = 'generateTradePendingResult()';

  console.log(`  意图=${tc.intent}, trading_mode=${tc.mode}`);
  console.log(`    → 条件1(classic + 对话): ${isClassic && isConv}`);
  console.log(`    → 条件2(对话): ${isConv}`);
  console.log(`    → 条件3(交易): ${isTrade}`);
  console.log(`    → 实际走分支: ${branch}\n`);
}

console.log('========== 结论 ==========');
console.log('当 trading_mode=classic 且 intent=execute_trade 时:');
console.log('  不会走 executeClassicChain 分支!');
console.log('  而是走 generateTradePendingResult - 返回交易待确认提示');
console.log('  这意味着 classic 模式下的 execute_trade 意图根本拿不到 C 系列分析!\n');
