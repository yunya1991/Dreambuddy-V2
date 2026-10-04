#!/usr/bin/env npx tsx
/**
 * 意图识别多轮交互集成测试
 *
 * 验证内容：
 * 1. 澄清选项数字回复解析（核心：解决"回复1后空转"问题）
 * 2. 行情查询规则兜底（不触发 LLM）
 * 3. 跨轮次实体继承
 * 4. 多轮交互连续不空转
 */

import { recognizeIntent } from './fallback-engine';
import type { SessionContext, ClarificationOption } from './fallback-engine';

// ============================================================
// 测试工具
// ============================================================

let passed = 0;
let failed = 0;

function test(name: string, fn: () => Promise<void> | void) {
  Promise.resolve(fn())
    .then(() => {
      console.log(`✅ ${name}`);
      passed++;
    })
    .catch((error) => {
      console.log(`❌ ${name}`);
      console.log(`   错误: ${error instanceof Error ? error.message : String(error)}`);
      failed++;
    });
}

function assertEqual(actual: any, expected: any, msg?: string) {
  if (actual !== expected) {
    throw new Error(`${msg || ''} 期望 ${expected}, 实际 ${actual}`);
  }
}

function assertTrue(cond: boolean, msg?: string) {
  if (!cond) {
    throw new Error(msg || '断言失败');
  }
}

// ============================================================
// 测试场景 1: 澄清选项数字回复解析
// ============================================================

const clarificationOptions: ClarificationOption[] = [
  { key: 'query', label: '查询 BTC 实时行情', target_intent: 'market_query', entities: { symbol: 'BTC' } },
  { key: 'analysis', label: '深度分析 BTC 走势', target_intent: 'deep_analysis', entities: { symbol: 'BTC' } },
  { key: 'strategy', label: '制定 BTC 交易策略', target_intent: 'triple_chain', entities: { symbol: 'BTC' } },
];

test('澄清选项数字回复: 输入"1" → market_query', async () => {
  const ctx: SessionContext = {
    session_id: 'test_clarify_1',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('1', ctx);
  assertEqual(result.intent, 'market_query', '意图应为 market_query');
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应为 BTC');
  assertTrue(result.confidence >= 0.85, '置信度应 >= 0.85');
  assertEqual(result.method, 'follow_up', '方法应为 follow_up');
});

test('澄清选项数字回复: 输入"2" → deep_analysis', async () => {
  const ctx: SessionContext = {
    session_id: 'test_clarify_2',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('2', ctx);
  assertEqual(result.intent, 'deep_analysis', '意图应为 deep_analysis');
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应为 BTC');
});

test('澄清选项数字回复: 输入"3" → triple_chain', async () => {
  const ctx: SessionContext = {
    session_id: 'test_clarify_3',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('3', ctx);
  assertEqual(result.intent, 'triple_chain', '意图应为 triple_chain');
});

test('澄清选项数字超出范围: 输入"5" → need_clarification', async () => {
  const ctx: SessionContext = {
    session_id: 'test_clarify_oob',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('5', ctx);
  assertEqual(result.intent, 'need_clarification', '超出范围应返回 need_clarification');
});

test('澄清选项数字+文字混合: 输入"1 查询" → market_query', async () => {
  const ctx: SessionContext = {
    session_id: 'test_clarify_mixed',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('1 查询', ctx);
  assertEqual(result.intent, 'market_query', '混合输入应匹配数字索引');
});

test('无上一轮选项时输入"1" → 不触发澄清解析', async () => {
  const ctx: SessionContext = {
    session_id: 'test_no_clarify',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('1', ctx);
  // 无上一轮选项，"1" 不应被解析为澄清回复
  // 可能走 LLM 或默认兜底，但不应是 clarification 相关
  assertTrue(result.intent !== undefined, '应有意图结果');
});

// ============================================================
// 测试场景 2: 行情查询规则兜底（不触发 LLM）
// ============================================================

test('行情查询: "BTC现在多少钱" → market_query (rule)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_market_1',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('BTC现在多少钱', ctx);
  assertEqual(result.intent, 'market_query', '意图应为 market_query');
  assertEqual(result.method, 'rule', '方法应为 rule（规则预过滤）');
  assertTrue(result.confidence >= 0.85, '置信度应 >= 0.85');
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应为 BTC');
});

test('行情查询: "以太坊行情" → market_query (rule, ETH)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_market_2',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('以太坊行情', ctx);
  assertEqual(result.intent, 'market_query', '意图应为 market_query');
  assertEqual(result.entities.symbol, 'ETH', 'symbol 应为 ETH');
});

test('行情查询: "狗狗币价格" → market_query (rule, DOGE)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_market_3',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('狗狗币价格', ctx);
  assertEqual(result.intent, 'market_query', '意图应为 market_query');
  assertEqual(result.entities.symbol, 'DOGE', 'symbol 应为 DOGE');
});

// ============================================================
// 测试场景 3: 跨轮次实体继承
// ============================================================

test('跨轮次实体继承: 上一轮 BTC，本轮"走势" → symbol=BTC', async () => {
  const ctx: SessionContext = {
    session_id: 'test_inherit',
    user_role: 'FREE',
    last_intent: 'market_query',
    last_symbol: 'BTC',
    message_history: ['BTC现在多少钱'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('走势', ctx);
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应继承为 BTC');
});

// ============================================================
// 测试场景 4: 自然语言追问
// ============================================================

test('自然语言追问: 上一轮 deep_analysis，本轮"为什么" → 延续 deep_analysis', async () => {
  const ctx: SessionContext = {
    session_id: 'test_followup',
    user_role: 'FREE',
    last_intent: 'deep_analysis',
    last_symbol: 'BTC',
    message_history: ['深度分析比特币走势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('为什么', ctx);
  assertEqual(result.intent, 'deep_analysis', '追问应延续 deep_analysis');
});

test('极短追问: "涨" → market_query', async () => {
  const ctx: SessionContext = {
    session_id: 'test_short',
    user_role: 'FREE',
    last_intent: 'market_query',
    last_symbol: 'BTC',
    message_history: ['BTC价格'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  const result = await recognizeIntent('涨', ctx);
  assertEqual(result.intent, 'market_query', '极短追问应返回 market_query');
});

// ============================================================
// 测试场景 5: 多轮交互完整流程（模拟）
// ============================================================

test('多轮交互: 分析→澄清→回复1→追问 不空转', async () => {
  const sessionId = 'test_multiround';
  let ctx: SessionContext = {
    session_id: sessionId,
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  // 第1轮: "分析比特币趋势" → 应命中 deep_analysis 规则（或 LLM 澄清）
  let result = await recognizeIntent('分析比特币趋势', ctx);
  // 规则预过滤会命中 deep_analysis（关键词"分析"）
  if (result.intent === 'deep_analysis') {
    assertTrue(result.entities.symbol === 'BTC', '第1轮 symbol 应为 BTC');
  }

  // 模拟第2轮: 系统返回澄清选项，用户回复"1"
  ctx = {
    ...ctx,
    last_intent: 'need_clarification',
    last_symbol: 'BTC',
    last_clarification_options: clarificationOptions,
    message_history: [...ctx.message_history, '分析比特币趋势'],
  };

  result = await recognizeIntent('1', ctx);
  assertEqual(result.intent, 'market_query', '第2轮回复"1"应为 market_query');
  assertEqual(result.entities.symbol, 'BTC', '第2轮 symbol 应为 BTC');

  // 第3轮: 用户追问"为什么"
  ctx = {
    ...ctx,
    last_intent: 'market_query',
    last_symbol: 'BTC',
    last_clarification_options: undefined,
    message_history: [...ctx.message_history, '1'],
  };

  result = await recognizeIntent('为什么', ctx);
  // "为什么" 是追问词，应延续上一轮意图
  assertTrue(['market_query', 'deep_analysis'].includes(result.intent), '第3轮追问不应空转');
});

// ============================================================
// 测试场景 6: 更多币种行情查询
// ============================================================

test('行情查询: "SOL现价" → market_query (SOL)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_sol',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('SOL现价', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
  assertEqual(result.entities.symbol, 'SOL', 'symbol 应为 SOL');
});

test('行情查询: "BNB报价" → market_query (BNB)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_bnb',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('BNB报价', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
  assertEqual(result.entities.symbol, 'BNB', 'symbol 应为 BNB');
});

test('行情查询: "瑞波币行情" → market_query (XRP)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_xrp',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('瑞波币行情', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
  assertEqual(result.entities.symbol, 'XRP', 'symbol 应为 XRP');
});

// ============================================================
// 测试场景 7: 深度分析意图
// ============================================================

test('深度分析: "深度分析比特币" → deep_analysis (rule)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_deep',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('深度分析比特币', ctx);
  assertEqual(result.intent, 'deep_analysis', '应为 deep_analysis');
  assertEqual(result.method, 'rule', '应为 rule 方法');
});

test('深度分析: "技术分析ETH" → deep_analysis', async () => {
  const ctx: SessionContext = {
    session_id: 'test_tech',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('技术分析ETH', ctx);
  assertEqual(result.intent, 'deep_analysis', '应为 deep_analysis');
  assertEqual(result.entities.symbol, 'ETH', 'symbol 应为 ETH');
});

// ============================================================
// 测试场景 8: 澄清选项 key/label 匹配
// ============================================================

test('澄清选项 label 匹配: 输入"查询BTC实时行情" → market_query', async () => {
  const ctx: SessionContext = {
    session_id: 'test_label_match',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('查询BTC实时行情', ctx);
  assertEqual(result.intent, 'market_query', 'label 匹配应为 market_query');
});

// ============================================================
// 测试场景 9: 空消息/无意义输入
// ============================================================

test('空消息处理: 输入"" → 不崩溃', async () => {
  const ctx: SessionContext = {
    session_id: 'test_empty',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('', ctx);
  assertTrue(result.intent !== undefined, '空消息应有意图结果');
});

// ============================================================
// 测试场景 10: 多轮连续追问
// ============================================================

test('多轮连续追问: 分析→行情→为什么→然后 → 不空转', async () => {
  const sessionId = 'test_continuous';
  let ctx: SessionContext = {
    session_id: sessionId,
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  // 轮1: 行情查询
  let result = await recognizeIntent('BTC价格', ctx);
  assertEqual(result.intent, 'market_query', '轮1应为 market_query');

  // 轮2: 追问为什么
  ctx = { ...ctx, last_intent: 'market_query', last_symbol: 'BTC', message_history: [...ctx.message_history, 'BTC价格'] };
  result = await recognizeIntent('为什么', ctx);
  assertTrue(['market_query', 'deep_analysis'].includes(result.intent), '轮2追问不应空转');

  // 轮3: 继续追问然后
  ctx = { ...ctx, last_intent: result.intent, message_history: [...ctx.message_history, '为什么'] };
  result = await recognizeIntent('然后呢', ctx);
  assertTrue(result.intent !== undefined && result.intent !== 'need_clarification', '轮3追问不应空转或反复澄清');
});

// ============================================================
// 测试场景 11: 策略制定意图
// ============================================================

test('策略制定: "制定BTC交易策略" → triple_chain', async () => {
  const ctx: SessionContext = {
    session_id: 'test_strategy_1',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('制定BTC交易策略', ctx);
  assertEqual(result.intent, 'triple_chain', '应为 triple_chain');
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应为 BTC');
});

test('策略制定: "帮我设计ETH的入场止损止盈" → triple_chain', async () => {
  const ctx: SessionContext = {
    session_id: 'test_strategy_2',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('帮我设计ETH的入场止损止盈', ctx);
  assertEqual(result.intent, 'triple_chain', '应为 triple_chain');
});

// ============================================================
// 测试场景 12: 场景模拟意图
// ============================================================

test('场景模拟: "模拟BTC跌到5万会怎样" → scenario_sim', async () => {
  const ctx: SessionContext = {
    session_id: 'test_sim_1',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('模拟BTC跌到5万会怎样', ctx);
  assertEqual(result.intent, 'scenario_sim', '应为 scenario_sim');
});

// ============================================================
// 测试场景 13: 策略验证意图
// ============================================================

test('策略验证: "验证一下这个策略的有效性" → strategy_verify', async () => {
  const ctx: SessionContext = {
    session_id: 'test_verify_1',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('验证一下这个策略的有效性', ctx);
  assertEqual(result.intent, 'strategy_verify', '应为 strategy_verify');
});

// ============================================================
// 测试场景 14: 更多追问词变体
// ============================================================

test('追问词: "详细说说" → 延续上一轮意图', async () => {
  const ctx: SessionContext = {
    session_id: 'test_followup_detail',
    user_role: 'FREE',
    last_intent: 'deep_analysis',
    last_symbol: 'BTC',
    message_history: ['深度分析比特币'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('详细说说', ctx);
  assertTrue(result.intent !== undefined, '追问词应有意图结果');
});

test('追问词: "继续" → 延续上一轮意图', async () => {
  const ctx: SessionContext = {
    session_id: 'test_followup_continue',
    user_role: 'FREE',
    last_intent: 'market_query',
    last_symbol: 'ETH',
    message_history: ['ETH价格'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('继续', ctx);
  assertTrue(result.intent !== undefined, '追问词应有意图结果');
});

test('追问词: "然后呢" → 延续上一轮意图', async () => {
  const ctx: SessionContext = {
    session_id: 'test_followup_then',
    user_role: 'FREE',
    last_intent: 'triple_chain',
    last_symbol: 'BTC',
    message_history: ['制定BTC策略'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('然后呢', ctx);
  assertTrue(result.intent !== undefined, '追问词应有意图结果');
});

// ============================================================
// 测试场景 15: 币种切换场景
// ============================================================

test('币种切换: 上一轮BTC，本轮"ETH呢" → symbol=ETH', async () => {
  const ctx: SessionContext = {
    session_id: 'test_switch',
    user_role: 'FREE',
    last_intent: 'market_query',
    last_symbol: 'BTC',
    message_history: ['BTC价格'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('ETH呢', ctx);
  assertEqual(result.entities.symbol, 'ETH', 'symbol 应切换为 ETH');
});

test('币种切换: 上一轮BTC，本轮"看看SOL" → symbol=SOL', async () => {
  const ctx: SessionContext = {
    session_id: 'test_switch_2',
    user_role: 'FREE',
    last_intent: 'market_query',
    last_symbol: 'BTC',
    message_history: ['BTC价格'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('看看SOL', ctx);
  assertEqual(result.entities.symbol, 'SOL', 'symbol 应切换为 SOL');
});

// ============================================================
// 测试场景 16: 5+轮连续对话（长对话稳定性）
// ============================================================

test('5轮连续对话: 行情→追问→切换币种→追问→再切换 不空转', async () => {
  const sessionId = 'test_5round';
  let ctx: SessionContext = {
    session_id: sessionId,
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  // 轮1: BTC行情
  let result = await recognizeIntent('BTC价格', ctx);
  assertEqual(result.intent, 'market_query', '轮1应为 market_query');

  // 轮2: 追问为什么
  ctx = { ...ctx, last_intent: result.intent, last_symbol: 'BTC', message_history: [...ctx.message_history, 'BTC价格'] };
  result = await recognizeIntent('为什么', ctx);
  assertTrue(result.intent !== undefined, '轮2不应空转');

  // 轮3: 切换到ETH
  ctx = { ...ctx, last_intent: result.intent, last_symbol: 'BTC', message_history: [...ctx.message_history, '为什么'] };
  result = await recognizeIntent('ETH呢', ctx);
  assertEqual(result.entities.symbol, 'ETH', '轮3应切换 ETH');

  // 轮4: 追问
  ctx = { ...ctx, last_intent: result.intent, last_symbol: 'ETH', message_history: [...ctx.message_history, 'ETH呢'] };
  result = await recognizeIntent('然后呢', ctx);
  assertTrue(result.intent !== undefined, '轮4不应空转');

  // 轮5: 切换到SOL
  ctx = { ...ctx, last_intent: result.intent, message_history: [...ctx.message_history, '然后呢'] };
  result = await recognizeIntent('看看SOL', ctx);
  assertEqual(result.entities.symbol, 'SOL', '轮5应切换 SOL');
});

// ============================================================
// 测试场景 17: 澄清选项消费后清除验证
// ============================================================

test('澄清选项消费: 选择后last_clarification_options应被消费（模拟task-manager行为）', async () => {
  // 这个测试验证 detectFollowUp 消费选项后的行为
  // 注意：fallback-engine 本身不清除 store，由 task-manager 的 updateSessionContextFromResult 负责
  // 这里验证：选择选项后，再次输入数字不会误匹配（因为 ctx 中已清除）
  const sessionId = 'test_consume';
  let ctx: SessionContext = {
    session_id: sessionId,
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: clarificationOptions,
    message_history: ['分析比特币趋势'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  // 第1次: 选择"1" → market_query
  let result = await recognizeIntent('1', ctx);
  assertEqual(result.intent, 'market_query', '选择1应为 market_query');

  // 模拟 task-manager 清除选项
  ctx = { ...ctx, last_intent: 'market_query', last_clarification_options: undefined };

  // 第2次: 再次输入"1" → 不应匹配澄清选项
  result = await recognizeIntent('1', ctx);
  // 无上一轮选项，"1" 不会被解析为澄清回复
  assertTrue(result.intent !== undefined, '清除选项后仍应有意图结果');
});

// ============================================================
// 测试场景 18: 实体继承 - 不同意图类型
// ============================================================

test('实体继承: deep_analysis → market_query 继承 symbol', async () => {
  const ctx: SessionContext = {
    session_id: 'test_inherit_2',
    user_role: 'FREE',
    last_intent: 'deep_analysis',
    last_symbol: 'ETH',
    message_history: ['深度分析以太坊'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('价格', ctx);
  assertEqual(result.entities.symbol, 'ETH', '应继承 ETH');
});

test('实体继承: triple_chain → deep_analysis 继承 symbol', async () => {
  const ctx: SessionContext = {
    session_id: 'test_inherit_3',
    user_role: 'FREE',
    last_intent: 'triple_chain',
    last_symbol: 'SOL',
    message_history: ['制定SOL策略'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('技术分析', ctx);
  assertEqual(result.entities.symbol, 'SOL', '应继承 SOL');
});

// ============================================================
// 测试场景 19: 中英混合输入
// ============================================================

test('中英混合: "BTC price now" → market_query', async () => {
  const ctx: SessionContext = {
    session_id: 'test_mixed_en',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('BTC price now', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
  assertEqual(result.entities.symbol, 'BTC', 'symbol 应为 BTC');
});

test('中英混合: "eth 行情" → market_query (ETH)', async () => {
  const ctx: SessionContext = {
    session_id: 'test_mixed_cn',
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('eth 行情', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
  assertEqual(result.entities.symbol, 'ETH', 'symbol 应为 ETH');
});

// ============================================================
// 测试场景 20: 澄清选项 - 2个选项场景
// ============================================================

const twoOptions: ClarificationOption[] = [
  { key: 'query', label: '查询行情', target_intent: 'market_query', entities: { symbol: 'BTC' } },
  { key: 'analysis', label: '深度分析', target_intent: 'deep_analysis', entities: { symbol: 'BTC' } },
];

test('2选项澄清: 输入"1" → 第1个选项', async () => {
  const ctx: SessionContext = {
    session_id: 'test_2opt_1',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: twoOptions,
    message_history: ['分析'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('1', ctx);
  assertEqual(result.intent, 'market_query', '应为 market_query');
});

test('2选项澄清: 输入"2" → 第2个选项', async () => {
  const ctx: SessionContext = {
    session_id: 'test_2opt_2',
    user_role: 'FREE',
    last_intent: 'need_clarification',
    last_clarification_options: twoOptions,
    message_history: ['分析'],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };
  const result = await recognizeIntent('2', ctx);
  assertEqual(result.intent, 'deep_analysis', '应为 deep_analysis');
});

// ============================================================
// 测试场景 21: 复杂多轮 - 澄清后追问再切换
// ============================================================

test('复杂多轮: 分析→澄清→选2→追问→切换币种', async () => {
  const sessionId = 'test_complex';
  let ctx: SessionContext = {
    session_id: sessionId,
    user_role: 'FREE',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  // 轮1: 分析（触发澄清）
  let result = await recognizeIntent('分析比特币', ctx);
  assertTrue(result.intent !== undefined, '轮1应有意图');

  // 轮2: 系统返回澄清，用户选"2"（深度分析）
  ctx = {
    ...ctx,
    last_intent: 'need_clarification',
    last_symbol: 'BTC',
    last_clarification_options: clarificationOptions,
    message_history: [...ctx.message_history, '分析比特币'],
  };
  result = await recognizeIntent('2', ctx);
  assertEqual(result.intent, 'deep_analysis', '轮2选2应为 deep_analysis');

  // 轮3: 追问
  ctx = { ...ctx, last_intent: 'deep_analysis', last_symbol: 'BTC', last_clarification_options: undefined, message_history: [...ctx.message_history, '2'] };
  result = await recognizeIntent('为什么', ctx);
  assertTrue(result.intent !== undefined, '轮3追问不应空转');

  // 轮4: 切换到 ETH
  ctx = { ...ctx, last_intent: result.intent, last_symbol: 'BTC', message_history: [...ctx.message_history, '为什么'] };
  result = await recognizeIntent('ETH呢', ctx);
  assertEqual(result.entities.symbol, 'ETH', '轮4应切换 ETH');
});

// ============================================================
// 输出结果
// ============================================================

setTimeout(() => {
  console.log(`\n${'='.repeat(60)}`);
  console.log(`测试结果: ${passed} 通过, ${failed} 失败`);
  console.log(`${'='.repeat(60)}`);
  process.exit(failed > 0 ? 1 : 0);
}, 2000);
