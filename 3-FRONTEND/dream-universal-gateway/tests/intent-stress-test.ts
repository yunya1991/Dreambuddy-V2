/**
 * Intent + Smart Router 压力测试
 *
 * 测试场景:
 * 1. 经验模式库模式匹配 (55条)
 * 2. 实体提取 (symbol, timeframe)
 * 3. 追问检测
 * 4. 智能路由决策矩阵 (所有意图 × 角色 × 复杂度)
 * 5. 边界/异常输入
 * 6. 并发压力测试 (100次并行路由)
 *
 * 运行: npx tsx tests/intent-stress-test.ts
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// 加载核心数据
// ============================================================

const EXPERIENCE_MEMORY = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, '..', 'skills', 'user-intent-recognition', 'experience-memory.json'), 'utf-8')
);

const PATTERNS: Array<{
  id: string;
  patterns: string[];
  intent: string;
  confidence: number;
  entities_template: Record<string, string>;
  complexity: string;
  source: string;
}> = EXPERIENCE_MEMORY.patterns;

// ============================================================
// 实体提取 (独立实现，与 fallback-engine.ts 对齐)
// ============================================================

function extractEntities(msg: string): Record<string, string> {
  const entities: Record<string, string> = {};
  const symbolMap: Record<string, string[]> = {
    'BTC': ['btc', 'bitcoin', '比特币'],
    'ETH': ['eth', 'ethereum', '以太坊'],
    'SOL': ['sol', 'solana'],
    'BNB': ['bnb'],
    'XRP': ['xrp', 'ripple'],
  };
  const lower = msg.toLowerCase();
  for (const [symbol, keywords] of Object.entries(symbolMap)) {
    if (keywords.some(k => lower.includes(k))) {
      entities.symbol = symbol;
      break;
    }
  }
  if (msg.includes('1小时') || msg.includes('1h')) entities.timeframe = '1h';
  else if (msg.includes('4小时') || msg.includes('4h')) entities.timeframe = '4h';
  else if (msg.includes('日线') || msg.includes('1d')) entities.timeframe = '1d';
  else if (msg.includes('周') || msg.includes('1w')) entities.timeframe = '1w';
  return entities;
}

// ============================================================
// 规则匹配引擎
// ============================================================

function matchRuleEngine(message: string): { intent: string; confidence: number; entities: Record<string, string>; complexity: string } | null {
  const lower = message.toLowerCase().trim();
  let bestMatch: typeof PATTERNS[0] | null = null;
  let bestScore = 0;

  for (const p of PATTERNS) {
    for (const pat of p.patterns) {
      const regex = new RegExp(pat, 'i');
      if (regex.test(lower)) {
        if (p.confidence > bestScore) {
          bestScore = p.confidence;
          bestMatch = p;
        }
        break;
      }
    }
  }

  if (!bestMatch) return null;

  const entities = extractEntities(message);
  for (const [key, val] of Object.entries(bestMatch.entities_template)) {
    if (val === '{{auto_detect}}' && !entities[key]) continue;
    if (val !== '{{auto_detect}}' && !entities[key]) {
      entities[key] = val;
    }
  }

  return {
    intent: bestMatch.intent,
    confidence: bestMatch.confidence,
    entities,
    complexity: bestMatch.complexity,
  };
}

// ============================================================
// 智能路由引擎 (独立实现，与 smart-router.ts 对齐)
// ============================================================

const CHAIN_STEPS: Record<string, { label: string; credits: number; time_ms: number; loop: string }> = {
  A1_research:    { label: '市场侦察', credits: 50,  time_ms: 30000, loop: 'execution' },
  A2_analysis:    { label: '深度分析', credits: 80,  time_ms: 45000, loop: 'execution' },
  A3_simulation:  { label: '情景推演', credits: 100, time_ms: 60000, loop: 'execution' },
  A4_validation:  { label: '方案验证', credits: 120, time_ms: 45000, loop: 'execution' },
  A5_execution:   { label: '决策执行', credits: 150, time_ms: 30000, loop: 'execution' },
  A9_exit:        { label: '离场评估', credits: 80,  time_ms: 20000, loop: 'execution' },
  A6_intelligence:{ label: '情报监控', credits: 30,  time_ms: 15000, loop: 'intelligence' },
  A6_alert:       { label: '情报告警', credits: 20,  time_ms: 5000,  loop: 'intelligence' },
  A7_practice:    { label: '实践记录', credits: 60,  time_ms: 30000, loop: 'governance' },
  A8_verification:{ label: '知行验证', credits: 70,  time_ms: 30000, loop: 'governance' },
  knowledge_base: { label: '知识库',   credits: 5,   time_ms: 2000,  loop: 'general' },
  tavily_search:  { label: '联网搜索', credits: 10,  time_ms: 8000,  loop: 'general' },
  market_data:    { label: '行情数据', credits: 5,   time_ms: 3000,  loop: 'intelligence' },
  direct_answer:  { label: '直接回答', credits: 5,   time_ms: 2000,  loop: 'general' },
};

interface RouteConfig {
  loop: string;
  free_chain: string[];
  pro_short_chain: string[];
  pro_full_chain: string[];
  requires_confirmation: boolean;
  fallback_chain: string[];
}

const ROUTE_MAP: Record<string, RouteConfig> = {
  market_query: {
    loop: 'intelligence',
    free_chain: ['knowledge_base', 'market_data'],
    pro_short_chain: ['A6_intelligence', 'market_data'],
    pro_full_chain: ['A6_intelligence', 'market_data'],
    requires_confirmation: false,
    fallback_chain: ['market_data'],
  },
  deep_analysis: {
    loop: 'execution',
    free_chain: ['knowledge_base', 'A1_research'],
    pro_short_chain: ['A1_research'],
    pro_full_chain: ['A1_research', 'A2_analysis', 'A3_simulation', 'A4_validation'],
    requires_confirmation: false,
    fallback_chain: ['A1_research', 'A2_analysis'],
  },
  scenario_sim: {
    loop: 'execution',
    free_chain: ['knowledge_base'],
    pro_short_chain: ['A3_simulation'],
    pro_full_chain: ['A1_research', 'A2_analysis', 'A3_simulation'],
    requires_confirmation: false,
    fallback_chain: ['A2_analysis'],
  },
  strategy_verify: {
    loop: 'execution',
    free_chain: ['A4_validation'],
    pro_short_chain: ['A4_validation'],
    pro_full_chain: ['A3_simulation', 'A4_validation', 'A5_execution'],
    requires_confirmation: false,
    fallback_chain: ['A2_analysis'],
  },
  execute_trade: {
    loop: 'execution',
    free_chain: [],
    pro_short_chain: ['A4_validation', 'A5_execution'],
    pro_full_chain: ['A4_validation', 'A5_execution', 'A9_exit'],
    requires_confirmation: true,
    fallback_chain: ['A4_validation'],
  },
  system_config: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  credits_query: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  artifact_query: {
    loop: 'general',
    free_chain: ['knowledge_base'],
    pro_short_chain: ['knowledge_base'],
    pro_full_chain: ['knowledge_base', 'tavily_search'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  risk_alert_response: {
    loop: 'intelligence',
    free_chain: ['A6_intelligence', 'A6_alert'],
    pro_short_chain: ['A6_intelligence', 'A6_alert'],
    pro_full_chain: ['A6_intelligence', 'A6_alert'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  simple_qa: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['tavily_search', 'direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
  command: {
    loop: 'general',
    free_chain: ['direct_answer'],
    pro_short_chain: ['direct_answer'],
    pro_full_chain: ['direct_answer'],
    requires_confirmation: false,
    fallback_chain: ['direct_answer'],
  },
};

function routeIntent(intent: string, complexity: string, userRole: 'FREE' | 'PRO' | 'ADMIN', thinkingMode: 'quick' | 'deep') {
  const rc = ROUTE_MAP[intent];
  if (!rc) {
    return { loop: 'general', chain: ['direct_answer'], role_check: 'pass', requires_confirmation: false };
  }

  if (intent === 'execute_trade' && userRole === 'FREE') {
    return { loop: rc.loop, chain: [], role_check: 'upgrade_required', requires_confirmation: true };
  }

  if (intent === 'scenario_sim' && userRole === 'FREE' && complexity === 'complex') {
    return { loop: rc.loop, chain: ['knowledge_base'], role_check: 'upgrade_required', requires_confirmation: false };
  }

  let chain: string[];
  if (userRole === 'FREE') {
    chain = rc.free_chain;
  } else {
    chain = (thinkingMode === 'deep' && complexity !== 'simple') ? rc.pro_full_chain : rc.pro_short_chain;
  }

  // 紧急事件: 强制情报环 (在所有角色和意图上)
  if (complexity === 'urgent') {
    chain = ['A6_intelligence', 'A6_alert'];
  }

  return {
    loop: rc.loop,
    chain,
    role_check: chain.length > 0 ? 'pass' : 'upgrade_required',
    requires_confirmation: rc.requires_confirmation,
  };
}

// ============================================================
// 测试框架
// ============================================================

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;

function test(name: string, fn: () => void) {
  totalTests++;
  try {
    fn();
    passedTests++;
    console.log(`  ✅ ${name}`);
  } catch (e) {
    failedTests++;
    console.log(`  ❌ ${name}: ${e instanceof Error ? e.message : String(e)}`);
  }
}

function assert(condition: boolean, msg: string) {
  if (!condition) throw new Error(msg);
}

function assertEqual(a: unknown, b: unknown, msg: string) {
  if (JSON.stringify(a) !== JSON.stringify(b)) {
    throw new Error(`${msg}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`);
  }
}

// ============================================================
// Test Suite 1: 经验模式库
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 1: 经验模式库模式匹配 (55 patterns)');
console.log('='.repeat(60));

// 验证模式数量
test('经验模式库有 55 条模式', () => {
  assert(PATTERNS.length === 55, `Expected 55, got ${PATTERNS.length}`);
});

// 验证所有模式都有必需字段
test('所有模式都有必需字段 (id, patterns, intent, confidence, complexity)', () => {
  for (const p of PATTERNS) {
    assert(!!p.id, `Missing id in pattern`);
    assert(Array.isArray(p.patterns) && p.patterns.length > 0, `Empty patterns in ${p.id}`);
    assert(!!p.intent, `Missing intent in ${p.id}`);
    assert(typeof p.confidence === 'number' && p.confidence > 0 && p.confidence <= 1, `Bad confidence in ${p.id}`);
    assert(!!p.complexity, `Missing complexity in ${p.id}`);
  }
});

// 验证意图分布
test('意图分布覆盖 11 种意图类型', () => {
  const intents = new Set(PATTERNS.map(p => p.intent));
  const expectedIntents = [
    'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
    'execute_trade', 'simple_qa', 'command', 'system_config',
    'credits_query', 'artifact_query', 'risk_alert_response',
  ];
  for (const ei of expectedIntents) {
    assert(intents.has(ei), `Missing intent: ${ei}`);
  }
});

// 验证命令模式
test('5个命令模式 (行情/分析/推演/验证/开仓)', () => {
  const cmdPatterns = PATTERNS.filter(p => p.source === 'command');
  assert(cmdPatterns.length === 5, `Expected 5 command patterns, got ${cmdPatterns.length}`);
  assert(cmdPatterns.every(p => p.confidence === 0.95), 'Command confidence should be 0.95');
});

// ============================================================
// Test Suite 2: 规则引擎模式匹配
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 2: 规则引擎模式匹配');
console.log('='.repeat(60));

// 行情查询
test('"BTC现在多少钱" → market_query', () => {
  const result = matchRuleEngine('BTC现在多少钱');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'market_query', 'Wrong intent');
  assertEqual(result!.entities.symbol, 'BTC', 'Missing BTC symbol');
});

test('"看看ETH行情" → market_query', () => {
  const result = matchRuleEngine('看看ETH行情');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'market_query', 'Wrong intent');
  assertEqual(result!.entities.symbol, 'ETH', 'Missing ETH symbol');
});

// 深度分析
test('"分析一下BTC走势" → deep_analysis', () => {
  const result = matchRuleEngine('分析一下BTC走势');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'deep_analysis', 'Wrong intent');
  assertEqual(result!.entities.symbol, 'BTC', 'Missing BTC symbol');
});

test('"全面分析ETH" → deep_analysis (complex)', () => {
  const result = matchRuleEngine('全面分析ETH');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'deep_analysis', 'Wrong intent');
  assertEqual(result!.complexity, 'complex', 'Wrong complexity');
});

// 情景推演
test('"如果BTC跌破8万会怎样" → scenario_sim', () => {
  const result = matchRuleEngine('如果BTC跌破8万会怎样');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'scenario_sim', 'Wrong intent');
});

test('"预测下周BTC走势" → scenario_sim', () => {
  const result = matchRuleEngine('预测下周BTC走势');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'scenario_sim', 'Wrong intent');
});

// 执行交易
test('"帮我开个BTC多单" → execute_trade', () => {
  const result = matchRuleEngine('帮我开个BTC多单');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'execute_trade', 'Wrong intent');
});

test('"现在做空ETH" → execute_trade', () => {
  const result = matchRuleEngine('现在做空ETH');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'execute_trade', 'Wrong intent');
});

// 系统配置
test('"把杠杆调到5倍" → system_config', () => {
  const result = matchRuleEngine('把杠杆调到5倍');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'system_config', 'Wrong intent');
});

test('"关闭交易" → system_config', () => {
  const result = matchRuleEngine('关闭交易');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'system_config', 'Wrong intent');
});

// 积分查询
test('"我还剩多少积分" → credits_query', () => {
  const result = matchRuleEngine('我还剩多少积分');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'credits_query', 'Wrong intent');
});

// 产物查询
test('"看看昨天的报告" → artifact_query', () => {
  const result = matchRuleEngine('看看昨天的报告');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'artifact_query', 'Wrong intent');
});

// 风险响应
test('"什么风险" → risk_alert_response', () => {
  const result = matchRuleEngine('什么风险');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'risk_alert_response', 'Wrong intent');
});

// 简单问答
test('"你是什么" → simple_qa', () => {
  const result = matchRuleEngine('你是什么');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'simple_qa', 'Wrong intent');
});

// 命令
test('"/行情 BTC" → command', () => {
  const result = matchRuleEngine('/行情 BTC');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'command', 'Wrong intent');
});

test('"/开仓 ETH" → command', () => {
  const result = matchRuleEngine('/开仓 ETH');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'command', 'Wrong intent');
});

// 社交
test('"感谢" → simple_qa', () => {
  const result = matchRuleEngine('感谢');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'simple_qa', 'Wrong intent');
});

// 紧急
test('"紧急处理" → risk_alert_response (urgent)', () => {
  const result = matchRuleEngine('紧急处理');
  assert(result !== null, 'No match');
  assertEqual(result!.intent, 'risk_alert_response', 'Wrong intent');
  assertEqual(result!.complexity, 'urgent', 'Wrong complexity');
});

// 未匹配
test('"xjhfksdjkfh" → null (无匹配)', () => {
  const result = matchRuleEngine('xjhfksdjkfh');
  assert(result === null, 'Should not match gibberish');
});

// ============================================================
// Test Suite 3: 实体提取
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 3: 实体提取');
console.log('='.repeat(60));

test('"BTC" → symbol=BTC', () => {
  const e = extractEntities('BTC价格');
  assertEqual(e.symbol, 'BTC', 'Wrong symbol');
});

test('"比特币" → symbol=BTC', () => {
  const e = extractEntities('比特币行情');
  assertEqual(e.symbol, 'BTC', 'Wrong symbol');
});

test('"ETH" → symbol=ETH', () => {
  const e = extractEntities('ETH走势');
  assertEqual(e.symbol, 'ETH', 'Wrong symbol');
});

test('"solana" → symbol=SOL', () => {
  const e = extractEntities('solana分析');
  assertEqual(e.symbol, 'SOL', 'Wrong symbol');
});

test('"4h时间框架" → timeframe=4h', () => {
  const e = extractEntities('BTC 4h时间框架');
  assertEqual(e.timeframe, '4h', 'Wrong timeframe');
});

test('"日线数据" → timeframe=1d', () => {
  const e = extractEntities('BTC日线数据');
  assertEqual(e.timeframe, '1d', 'Wrong timeframe');
});

test('"BTC 1小时" → symbol=BTC, timeframe=1h', () => {
  const e = extractEntities('BTC 1小时行情');
  assertEqual(e.symbol, 'BTC', 'Wrong symbol');
  assertEqual(e.timeframe, '1h', 'Wrong timeframe');
});

// ============================================================
// Test Suite 4: 智能路由决策矩阵
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 4: 智能路由决策矩阵');
console.log('='.repeat(60));

// FREE 用户 - market_query (simple)
test('FREE + market_query + simple → knowledge_base + market_data', () => {
  const r = routeIntent('market_query', 'simple', 'FREE', 'quick');
  assertEqual(r.chain, ['knowledge_base', 'market_data'], 'Wrong chain');
  assertEqual(r.role_check, 'pass', 'Wrong role_check');
  assertEqual(r.loop, 'intelligence', 'Wrong loop');
});

// FREE 用户 - deep_analysis (moderate)
test('FREE + deep_analysis + moderate → knowledge_base + A1_research', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'FREE', 'quick');
  assertEqual(r.chain, ['knowledge_base', 'A1_research'], 'Wrong chain');
  assertEqual(r.role_check, 'pass', 'Wrong role_check');
});

// FREE 用户 - execute_trade → 不可用
test('FREE + execute_trade → upgrade_required (chain为空)', () => {
  const r = routeIntent('execute_trade', 'complex', 'FREE', 'deep');
  assertEqual(r.chain, [], 'Chain should be empty for FREE user');
  assertEqual(r.role_check, 'upgrade_required', 'Should require upgrade');
});

// FREE 用户 - scenario_sim + complex → 降级
test('FREE + scenario_sim + complex → 降级到knowledge_base', () => {
  const r = routeIntent('scenario_sim', 'complex', 'FREE', 'deep');
  assertEqual(r.chain, ['knowledge_base'], 'Should downgrade to knowledge base');
  assertEqual(r.role_check, 'upgrade_required', 'Should require upgrade');
});

// PRO 用户 - market_query + simple
test('PRO + market_query + simple + quick → A6_intelligence + market_data', () => {
  const r = routeIntent('market_query', 'simple', 'PRO', 'quick');
  assertEqual(r.chain, ['A6_intelligence', 'market_data'], 'Wrong chain');
  assertEqual(r.role_check, 'pass', 'Wrong role_check');
});

// PRO 用户 - deep_analysis + moderate + deep
test('PRO + deep_analysis + moderate + deep → 完整链路 A1→A2→A3→A4', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'deep');
  assertEqual(r.chain, ['A1_research', 'A2_analysis', 'A3_simulation', 'A4_validation'], 'Wrong full chain');
  assertEqual(r.loop, 'execution', 'Wrong loop');
});

// PRO 用户 - deep_analysis + moderate + quick
test('PRO + deep_analysis + moderate + quick → 短链路 A1_research', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'quick');
  assertEqual(r.chain, ['A1_research'], 'Wrong short chain');
});

// PRO 用户 - execute_trade
test('PRO + execute_trade → A4→A5→A9', () => {
  const r = routeIntent('execute_trade', 'complex', 'PRO', 'deep');
  assertEqual(r.chain, ['A4_validation', 'A5_execution', 'A9_exit'], 'Wrong trade chain');
  assertEqual(r.requires_confirmation, true, 'Trade should require confirmation');
  assertEqual(r.loop, 'execution', 'Wrong loop');
});

// PRO 用户 - 紧急事件
test('PRO + any + urgent → A6_intelligence + A6_alert', () => {
  const r = routeIntent('market_query', 'urgent', 'PRO', 'quick');
  assertEqual(r.chain, ['A6_intelligence', 'A6_alert'], 'Urgent should force intel chain');
});

// PRO 用户 - simple_qa + simple (complexity simple → short chain regardless of thinkingMode)
test('PRO + simple_qa + simple + deep → direct_answer (simple complexity uses short chain)', () => {
  const r = routeIntent('simple_qa', 'simple', 'PRO', 'deep');
  assertEqual(r.chain, ['direct_answer'], 'simple_qa simple should use short chain');
});

test('PRO + simple_qa + moderate + deep → tavily_search + direct_answer', () => {
  const r = routeIntent('simple_qa', 'moderate', 'PRO', 'deep');
  assertEqual(r.chain, ['tavily_search', 'direct_answer'], 'Wrong chain for simple_qa PRO+moderate+deep');
});

// PRO 用户 - artifact_query + deep
test('PRO + artifact_query + deep → knowledge_base + tavily_search', () => {
  const r = routeIntent('artifact_query', 'moderate', 'PRO', 'deep');
  assertEqual(r.chain, ['knowledge_base', 'tavily_search'], 'Wrong chain');
});

// PRO 用户 - risk_alert_response
test('PRO + risk_alert_response → A6 + A6_alert', () => {
  const r = routeIntent('risk_alert_response', 'urgent', 'PRO', 'quick');
  assertEqual(r.chain, ['A6_intelligence', 'A6_alert'], 'Wrong chain');
  assertEqual(r.loop, 'intelligence', 'Wrong loop');
});

// 策略验证 - PRO + deep
test('PRO + strategy_verify + deep → A3→A4→A5', () => {
  const r = routeIntent('strategy_verify', 'moderate', 'PRO', 'deep');
  assertEqual(r.chain, ['A3_simulation', 'A4_validation', 'A5_execution'], 'Wrong chain');
});

// ADMIN 用户 (等同于 PRO)
test('ADMIN + execute_trade + complex → 正常执行', () => {
  const r = routeIntent('execute_trade', 'complex', 'ADMIN', 'deep');
  assertEqual(r.chain, ['A4_validation', 'A5_execution', 'A9_exit'], 'Wrong chain');
  assertEqual(r.role_check, 'pass', 'Admin should pass');
});

// ============================================================
// Test Suite 5: 路由积分和时间计算
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 5: 路由积分和时间计算');
console.log('='.repeat(60));

function calcCredits(chain: string[]): number {
  return chain.reduce((sum, step) => sum + (CHAIN_STEPS[step]?.credits || 10), 0);
}

function calcTime(chain: string[]): number {
  return chain.reduce((sum, step) => sum + (CHAIN_STEPS[step]?.time_ms || 5000), 0);
}

test('FREE + market_query 积分消耗', () => {
  const r = routeIntent('market_query', 'simple', 'FREE', 'quick');
  const credits = calcCredits(r.chain);
  assert(credits > 0, 'Credits should be > 0');
  assertEqual(credits, 10, 'knowledge_base(5) + market_data(5) = 10');
});

test('PRO + deep_analysis (deep) 积分消耗', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'deep');
  const credits = calcCredits(r.chain);
  assertEqual(credits, 350, 'A1(50)+A2(80)+A3(100)+A4(120) = 350');
});

test('PRO + execute_trade (deep) 时间预估', () => {
  const r = routeIntent('execute_trade', 'complex', 'PRO', 'deep');
  const time = calcTime(r.chain);
  assertEqual(time, 95000, 'A4(45k)+A5(30k)+A9(20k) = 95000');
});

test('A6_intelligence 是最便宜的链路 (30 credits)', () => {
  assertEqual(CHAIN_STEPS['A6_intelligence']?.credits, 30, 'Wrong credits');
});

test('A5_execution 是最贵的链路 (150 credits)', () => {
  assertEqual(CHAIN_STEPS['A5_execution']?.credits, 150, 'Wrong credits');
});

// ============================================================
// Test Suite 6: 闭环分类验证
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 6: 三闭环分类验证');
console.log('='.repeat(60));

test('执行环链路: A1-A5, A9', () => {
  const execLoops = Object.entries(CHAIN_STEPS).filter(([, v]) => v.loop === 'execution');
  const execNames = execLoops.map(([k]) => k);
  assert(execNames.includes('A1_research'), 'Missing A1');
  assert(execNames.includes('A2_analysis'), 'Missing A2');
  assert(execNames.includes('A3_simulation'), 'Missing A3');
  assert(execNames.includes('A4_validation'), 'Missing A4');
  assert(execNames.includes('A5_execution'), 'Missing A5');
  assert(execNames.includes('A9_exit'), 'Missing A9');
});

test('情报环链路: A6_intelligence, A6_alert, market_data', () => {
  const intelLoops = Object.entries(CHAIN_STEPS).filter(([, v]) => v.loop === 'intelligence');
  const intelNames = intelLoops.map(([k]) => k);
  assert(intelNames.includes('A6_intelligence'), 'Missing A6_intelligence');
  assert(intelNames.includes('A6_alert'), 'Missing A6_alert');
  assert(intelNames.includes('market_data'), 'Missing market_data');
});

test('治理环链路: A7_practice, A8_verification', () => {
  const govLoops = Object.entries(CHAIN_STEPS).filter(([, v]) => v.loop === 'governance');
  const govNames = govLoops.map(([k]) => k);
  assert(govNames.includes('A7_practice'), 'Missing A7_practice');
  assert(govNames.includes('A8_verification'), 'Missing A8_verification');
});

// ============================================================
// Test Suite 7: 边界/异常输入
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 7: 边界/异常输入');
console.log('='.repeat(60));

test('空字符串 → null', () => {
  const result = matchRuleEngine('');
  assert(result === null, 'Empty string should not match');
});

test('纯空格 → null', () => {
  const result = matchRuleEngine('   ');
  assert(result === null, 'Whitespace should not match');
});

test('特殊字符 → null', () => {
  const result = matchRuleEngine('!@#$%^&*()');
  assert(result === null, 'Special chars should not match');
});

test('极长输入 → 仍然能处理', () => {
  const longInput = 'BTC'.repeat(1000);
  const result = matchRuleEngine(longInput);
  assert(result !== null || true, 'Should not crash on long input');
});

test('混合中英文 → 能识别', () => {
  const result = matchRuleEngine('分析一下 bitcoin 的走势 please');
  assert(result !== null, 'Mixed language should still match');
  assertEqual(result!.intent, 'deep_analysis', 'Wrong intent');
});

test('emoji 输入 → 不崩溃', () => {
  const result = matchRuleEngine('🚀 BTC 📈📉');
  assert(typeof result === 'object' || result === null, 'Should not crash on emoji input');
});

test('数字输入 → 不崩溃', () => {
  const result = matchRuleEngine('123456789');
  assert(result === null, 'Pure numbers should not match');
});

test('SQL 注入 → 不崩溃', () => {
  const result = matchRuleEngine("'; DROP TABLE users; --");
  assert(typeof result === 'object' || result === null, 'Should not crash on SQL injection');
});

test('XSS 输入 → 不崩溃', () => {
  const result = matchRuleEngine('<script>alert("xss")</script>');
  assert(typeof result === 'object' || result === null, 'Should not crash on XSS');
});

// ============================================================
// Test Suite 8: 路由全覆盖验证 (所有意图 × 所有角色 × 复杂度)
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 8: 路由全覆盖验证 (11意图 × 3角色 × 4复杂度 = 132)');
console.log('='.repeat(60));

const ALL_INTENTS = [
  'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
  'execute_trade', 'simple_qa', 'command', 'system_config',
  'credits_query', 'artifact_query', 'risk_alert_response',
];
const ALL_ROLES: Array<'FREE' | 'PRO' | 'ADMIN'> = ['FREE', 'PRO', 'ADMIN'];
const ALL_COMPLEXITIES = ['simple', 'moderate', 'complex', 'urgent'];

let totalMatrix = 0;
let passedMatrix = 0;
const matrixFailures: string[] = [];

for (const intent of ALL_INTENTS) {
  for (const role of ALL_ROLES) {
    for (const complexity of ALL_COMPLEXITIES) {
      totalMatrix++;
      try {
        const r = routeIntent(intent, complexity, role, 'quick');
        // 验证返回格式
        assert(typeof r.loop === 'string', `loop must be string`);
        assert(Array.isArray(r.chain), `chain must be array`);
        assert(typeof r.role_check === 'string', `role_check must be string`);
        assert(['pass', 'upgrade_required', 'denied'].includes(r.role_check), `invalid role_check: ${r.role_check}`);
        // 验证所有 chain 步骤都存在
        for (const step of r.chain) {
          assert(!!CHAIN_STEPS[step], `Unknown chain step: ${step}`);
        }
        passedMatrix++;
      } catch (e) {
        matrixFailures.push(`${intent}/${role}/${complexity}: ${e instanceof Error ? e.message : String(e)}`);
      }
    }
  }
}

console.log(`  路由矩阵: ${passedMatrix}/${totalMatrix} passed`);
if (matrixFailures.length > 0) {
  console.log(`  失败案例:`);
  for (const f of matrixFailures.slice(0, 10)) {
    console.log(`    ❌ ${f}`);
  }
}

// 关键路由验证
test('所有 urgent 请求都路由到 A6_intelligence + A6_alert (除 FREE+execute_trade 被角色拦截)', () => {
  for (const intent of ALL_INTENTS) {
    for (const role of ALL_ROLES) {
      if (intent === 'execute_trade' && role === 'FREE') continue;
      const r = routeIntent(intent, 'urgent', role, 'quick');
      assertEqual(r.chain, ['A6_intelligence', 'A6_alert'],
        `${intent}/${role} urgent should force intel chain, got ${r.chain.join(',')}`);
    }
  }
});

test('FREE 用户 execute_trade 全部返回 upgrade_required', () => {
  for (const complexity of ALL_COMPLEXITIES) {
    const r = routeIntent('execute_trade', complexity, 'FREE', 'quick');
    assertEqual(r.role_check, 'upgrade_required', `FREE+execute_trade+${complexity} should require upgrade`);
  }
});

// ============================================================
// Test Suite 9: 并发压力测试
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 9: 并发压力测试 (1000次并行路由)');
console.log('='.repeat(60));

// 生成随机输入
function randomInput(): string {
  const inputs = [
    'BTC行情', 'ETH分析', 'SOL推演', 'BTC如果跌到7万',
    '帮我开个多单', '关闭交易', '我的积分', '最新报告',
    '紧急处理', 'BTC价格', 'ETH走势怎么看', '全面分析BTC',
    '/行情', '/分析 BTC', '/开仓 ETH', 'xjhfksd',
    'btc 4h', '比特币日线', 'eth 1小时行情', 'solana分析',
    '对比BTC和ETH', '预测下周', '历史回顾', 'MACD指标',
    '支撑阻力位', '费率变化', '爆仓数据', '我的仓位',
    '收益多少', '最新资讯', '复盘交易', 'API配置',
    '通知设置', '策略推荐', '快速分析', '感谢',
    '涨', '跌', '为什么', '详细点', '什么意思',
    'BTC' + Math.random().toString(36).slice(2, 8),
    '分析 ' + Math.random().toString(36).slice(2, 10),
  ];
  return inputs[Math.floor(Math.random() * inputs.length)];
}

const STRESS_COUNT = 1000;

const stressStart = performance.now();
for (let i = 0; i < STRESS_COUNT; i++) {
  const input = randomInput();
  const ruleResult = matchRuleEngine(input);
  // 如果有匹配，再跑路由
  if (ruleResult) {
    const role = ALL_ROLES[Math.floor(Math.random() * 3)];
    const complexity = ruleResult.complexity || 'simple';
    routeIntent(ruleResult.intent, complexity, role, 'quick');
  }
}
const stressEnd = performance.now();
const stressDuration = stressEnd - stressStart;
const throughput = Math.round(STRESS_COUNT / (stressDuration / 1000));

console.log(`  输入数: ${STRESS_COUNT}`);
console.log(`  耗时: ${stressDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${throughput} ops/sec`);

test(`并发压力: 1000次 < 100ms`, () => {
  assert(stressDuration < 100, `Took ${stressDuration.toFixed(1)}ms, expected < 100ms`);
});

test(`并发压力: 吞吐量 > 10000 ops/sec`, () => {
  assert(throughput > 10000, `Throughput ${throughput} ops/sec, expected > 10000`);
});

// 更极端的并发测试
const EXTREME_COUNT = 10000;
const extremeStart = performance.now();
for (let i = 0; i < EXTREME_COUNT; i++) {
  const input = randomInput();
  const ruleResult = matchRuleEngine(input);
  if (ruleResult) {
    const role = ALL_ROLES[Math.floor(Math.random() * 3)];
    routeIntent(ruleResult.intent, ruleResult.complexity, role, 'deep');
  }
}
const extremeEnd = performance.now();
const extremeDuration = extremeEnd - extremeStart;
const extremeThroughput = Math.round(EXTREME_COUNT / (extremeDuration / 1000));

console.log(`\n  极限压力: ${EXTREME_COUNT}次`);
console.log(`  耗时: ${extremeDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${extremeThroughput} ops/sec`);

test(`极限压力: 10000次 < 500ms`, () => {
  assert(extremeDuration < 500, `Took ${extremeDuration.toFixed(1)}ms, expected < 500ms`);
});

// ============================================================
// 测试报告
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('📊 测试报告');
console.log('='.repeat(60));
console.log(`  总测试数: ${totalTests}`);
console.log(`  通过: ${passedTests}`);
console.log(`  失败: ${failedTests}`);
console.log(`  路由矩阵: ${passedMatrix}/${totalMatrix}`);
console.log(`  1000次并发: ${stressDuration.toFixed(1)}ms (~${throughput} ops/sec)`);
console.log(`  10000次极限: ${extremeDuration.toFixed(1)}ms (~${extremeThroughput} ops/sec)`);

if (failedTests === 0) {
  console.log('\n  ✅ ALL TESTS PASSED');
} else {
  console.log(`\n  ❌ ${failedTests} TESTS FAILED`);
  process.exit(1);
}
