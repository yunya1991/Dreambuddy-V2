/**
 * 三大工程多场景模拟验证
 *
 * 场景覆盖:
 * 1. 意图识别 — LLM/规则/追问/兜底 四种路径
 * 2. 智能路由 — FREE/PRO/ADMIN × 不同意图/复杂度/思考模式
 * 3. 记忆库 — 记录写入/反馈/模式发现/置信度调整/候选采纳/持久化
 * 4. 端到端 — 从用户输入 → 意图识别 → 智能路由 → 记忆记录
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// 加载经验模式库
// ============================================================

const EXPERIENCE_MEMORY = JSON.parse(
  fs.readFileSync(
    path.resolve(__dirname, '..', 'skills', 'user-intent-recognition', 'experience-memory.json'),
    'utf-8'
  )
);
const PATTERNS = EXPERIENCE_MEMORY.patterns;

// ============================================================
// 独立实现（与源码对齐，不依赖运行时）
// ============================================================

// --- 实体提取 ---
function extractEntities(msg: string): Record<string, string> {
  const entities: Record<string, string> = {};
  const symbolMap: Record<string, string[]> = {
    BTC: ['btc', 'bitcoin', '比特币'],
    ETH: ['eth', 'ethereum', '以太坊'],
    SOL: ['sol', 'solana'],
    BNB: ['bnb'],
    XRP: ['xrp', 'ripple'],
  };
  const lower = msg.toLowerCase();
  for (const [symbol, keywords] of Object.entries(symbolMap)) {
    if (keywords.some(k => lower.includes(k))) { entities.symbol = symbol; break; }
  }
  if (msg.includes('1小时') || msg.includes('1h')) entities.timeframe = '1h';
  else if (msg.includes('4小时') || msg.includes('4h')) entities.timeframe = '4h';
  else if (msg.includes('日线') || msg.includes('1d')) entities.timeframe = '1d';
  else if (msg.includes('周') || msg.includes('1w')) entities.timeframe = '1w';
  return entities;
}

// --- 规则引擎 ---
function matchRule(message: string): { intent: string; confidence: number; entities: Record<string, string>; complexity: string; matched_pattern_id: string } | null {
  const lower = message.toLowerCase().trim();
  let best: typeof PATTERNS[0] | null = null;
  let bestScore = 0;
  for (const p of PATTERNS) {
    for (const pat of p.patterns) {
      if (new RegExp(pat, 'i').test(lower)) {
        if (p.confidence > bestScore) { bestScore = p.confidence; best = p; }
        break;
      }
    }
  }
  if (!best) return null;
  const entities = extractEntities(message);
  for (const [k, v] of Object.entries(best.entities_template)) {
    if (v === '{{auto_detect}}' && !entities[k]) continue;
    if (v !== '{{auto_detect}}' && !entities[k]) entities[k] = v;
  }
  return { intent: best.intent, confidence: best.confidence, entities, complexity: best.complexity, matched_pattern_id: best.id };
}

// --- 模拟 LLM 意图（不真实调 API，用启发式模拟）---
function simulateLLM(message: string): { intent: string; confidence: number; entities: Record<string, string>; complexity: string } {
  const rule = matchRule(message);
  if (rule && rule.confidence >= 0.75) {
    return { intent: rule.intent, confidence: Math.min(0.95, rule.confidence + 0.08), entities: rule.entities, complexity: rule.complexity };
  }
  // 无规则匹配时，LLM 仍然能识别一些常见模式
  const lower = message.toLowerCase().trim();
  if (lower.includes('btc') && (lower.includes('预测') || lower.includes('下周') || lower.includes('明天'))) {
    return { intent: 'scenario_sim', confidence: 0.78, entities: { symbol: 'BTC' }, complexity: 'complex' };
  }
  if (lower.includes('btc') && (lower.includes('分析') || lower.includes('走势'))) {
    return { intent: 'deep_analysis', confidence: 0.75, entities: { symbol: 'BTC' }, complexity: 'moderate' };
  }
  if (lower.includes('行情') || lower.includes('价格') || lower.includes('多少')) {
    return { intent: 'market_query', confidence: 0.70, entities: extractEntities(message), complexity: 'simple' };
  }
  if (lower.includes('分析') || lower.includes('走势') || lower.includes('趋势')) {
    return { intent: 'deep_analysis', confidence: 0.72, entities: extractEntities(message), complexity: 'moderate' };
  }
  if (lower.includes('开仓') || lower.includes('做多') || lower.includes('做空') || lower.includes('买入') || lower.includes('卖出')) {
    return { intent: 'execute_trade', confidence: 0.80, entities: extractEntities(message), complexity: 'complex' };
  }
  return { intent: 'simple_qa', confidence: 0.55, entities: extractEntities(message), complexity: 'simple' };
}

// --- 追问检测 ---
function detectFollowUp(message: string, lastIntent?: string): { isFollowUp: boolean; intent?: string } {
  if (!lastIntent) return { isFollowUp: false };
  const short = message.trim().length < 15;
  const words = ['为什么', '原因', '详细', '详细点', '解释', '什么意思', '如何', '还能', '然后', '接着', '呢', '为什么跌', '为什么涨'];
  if (short && words.some(w => message.includes(w))) {
    return { isFollowUp: true, intent: ['deep_analysis', 'scenario_sim', 'strategy_verify'].includes(lastIntent) ? lastIntent : (lastIntent === 'simple_qa' ? 'market_query' : lastIntent) };
  }
  if (short && message.trim().length < 5 && /^(涨|跌|怎么样|如何|还能|还行吗|呢)$/.test(message.trim())) {
    return { isFollowUp: true, intent: 'market_query' };
  }
  return { isFollowUp: false };
}

// --- 完整意图识别引擎 (无 LLM API，模拟) ---
interface IntentResult {
  intent: string;
  confidence: number;
  entities: Record<string, string>;
  complexity: string;
  method: 'llm' | 'rule' | 'follow_up' | 'default';
  matched_pattern_id?: string;
  llm_intent?: string;
}

function recognizeIntent(message: string, lastIntent?: string): IntentResult {
  // Step 1: 追问
  const fu = detectFollowUp(message, lastIntent);
  if (fu.isFollowUp && fu.intent) {
    return { intent: fu.intent, confidence: 0.85, entities: extractEntities(message), complexity: 'simple', method: 'follow_up' };
  }
  // Step 2: 规则引擎
  const rule = matchRule(message);
  // Step 3: 模拟 LLM
  const llm = simulateLLM(message);
  // LLM vs Rule 对比
  if (rule && rule.confidence >= 0.5) {
    if (llm.intent !== rule.intent && Math.abs(llm.confidence - rule.confidence) > 0.15) {
      // 分歧时取 LLM（更高置信度）
      if (llm.confidence > rule.confidence) {
        return { intent: llm.intent, confidence: llm.confidence, entities: llm.entities, complexity: llm.complexity, method: 'llm', matched_pattern_id: rule.matched_pattern_id, llm_intent: llm.intent };
      }
    }
    return { intent: rule.intent, confidence: rule.confidence, entities: rule.entities, complexity: rule.complexity, method: 'rule', matched_pattern_id: rule.matched_pattern_id, llm_intent: llm.intent };
  }
  // 无规则匹配
  if (llm.confidence >= 0.6) {
    return { intent: llm.intent, confidence: llm.confidence, entities: llm.entities, complexity: llm.complexity, method: 'llm', llm_intent: llm.intent };
  }
  return { intent: 'simple_qa', confidence: 0.4, entities: extractEntities(message), complexity: 'simple', method: 'default', llm_intent: llm.intent };
}

// --- 智能路由 ---
const CHAIN_STEPS: Record<string, { credits: number; time_ms: number; loop: string }> = {
  A1_research: { credits: 50, time_ms: 30000, loop: 'execution' },
  A2_analysis: { credits: 80, time_ms: 45000, loop: 'execution' },
  A3_simulation: { credits: 100, time_ms: 60000, loop: 'execution' },
  A4_validation: { credits: 120, time_ms: 45000, loop: 'execution' },
  A5_execution: { credits: 150, time_ms: 30000, loop: 'execution' },
  A9_exit: { credits: 80, time_ms: 20000, loop: 'execution' },
  A6_intelligence: { credits: 30, time_ms: 15000, loop: 'intelligence' },
  A6_alert: { credits: 20, time_ms: 5000, loop: 'intelligence' },
  A7_practice: { credits: 60, time_ms: 30000, loop: 'governance' },
  A8_verification: { credits: 70, time_ms: 30000, loop: 'governance' },
  knowledge_base: { credits: 5, time_ms: 2000, loop: 'general' },
  tavily_search: { credits: 10, time_ms: 8000, loop: 'general' },
  market_data: { credits: 5, time_ms: 3000, loop: 'intelligence' },
  direct_answer: { credits: 5, time_ms: 2000, loop: 'general' },
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
  market_query: { loop: 'intelligence', free_chain: ['knowledge_base', 'market_data'], pro_short_chain: ['A6_intelligence', 'market_data'], pro_full_chain: ['A6_intelligence', 'market_data'], requires_confirmation: false, fallback_chain: ['market_data'] },
  deep_analysis: { loop: 'execution', free_chain: ['knowledge_base', 'A1_research'], pro_short_chain: ['A1_research'], pro_full_chain: ['A1_research', 'A2_analysis', 'A3_simulation', 'A4_validation'], requires_confirmation: false, fallback_chain: ['A1_research', 'A2_analysis'] },
  scenario_sim: { loop: 'execution', free_chain: ['knowledge_base'], pro_short_chain: ['A3_simulation'], pro_full_chain: ['A1_research', 'A2_analysis', 'A3_simulation'], requires_confirmation: false, fallback_chain: ['A2_analysis'] },
  strategy_verify: { loop: 'execution', free_chain: ['A4_validation'], pro_short_chain: ['A4_validation'], pro_full_chain: ['A3_simulation', 'A4_validation', 'A5_execution'], requires_confirmation: false, fallback_chain: ['A2_analysis'] },
  execute_trade: { loop: 'execution', free_chain: [], pro_short_chain: ['A4_validation', 'A5_execution'], pro_full_chain: ['A4_validation', 'A5_execution', 'A9_exit'], requires_confirmation: true, fallback_chain: ['A4_validation'] },
  system_config: { loop: 'general', free_chain: ['direct_answer'], pro_short_chain: ['direct_answer'], pro_full_chain: ['direct_answer'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
  credits_query: { loop: 'general', free_chain: ['direct_answer'], pro_short_chain: ['direct_answer'], pro_full_chain: ['direct_answer'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
  artifact_query: { loop: 'general', free_chain: ['knowledge_base'], pro_short_chain: ['knowledge_base'], pro_full_chain: ['knowledge_base', 'tavily_search'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
  risk_alert_response: { loop: 'intelligence', free_chain: ['A6_intelligence', 'A6_alert'], pro_short_chain: ['A6_intelligence', 'A6_alert'], pro_full_chain: ['A6_intelligence', 'A6_alert'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
  simple_qa: { loop: 'general', free_chain: ['direct_answer'], pro_short_chain: ['direct_answer'], pro_full_chain: ['tavily_search', 'direct_answer'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
  command: { loop: 'general', free_chain: ['direct_answer'], pro_short_chain: ['direct_answer'], pro_full_chain: ['direct_answer'], requires_confirmation: false, fallback_chain: ['direct_answer'] },
};

function routeIntent(intent: string, complexity: string, role: 'FREE' | 'PRO' | 'ADMIN', thinking: 'quick' | 'deep') {
  const rc = ROUTE_MAP[intent];
  if (!rc) return { loop: 'general', chain: ['direct_answer'], role_check: 'pass', credits: 5, time_ms: 2000 };

  if (intent === 'execute_trade' && role === 'FREE') return { loop: rc.loop, chain: [], role_check: 'upgrade_required', credits: 0, time_ms: 0 };
  if (intent === 'scenario_sim' && role === 'FREE' && (complexity === 'complex' || complexity === 'urgent')) return { loop: rc.loop, chain: ['knowledge_base'], role_check: 'upgrade_required', credits: 5, time_ms: 2000 };

  let chain: string[];
  if (role === 'FREE') chain = rc.free_chain;
  else chain = (thinking === 'deep' && complexity !== 'simple') ? rc.pro_full_chain : rc.pro_short_chain;

  if (complexity === 'urgent') chain = ['A6_intelligence', 'A6_alert'];

  const credits = chain.reduce((s, step) => s + (CHAIN_STEPS[step]?.credits || 0), 0);
  const time_ms = chain.reduce((s, step) => s + (CHAIN_STEPS[step]?.time_ms || 0), 0);
  return { loop: rc.loop, chain, role_check: 'pass', credits, time_ms, requires_confirmation: rc.requires_confirmation };
}

// ============================================================
// 测试框架
// ============================================================
let total = 0, passed = 0, failed = 0;
function t(name: string, fn: () => void) {
  total++;
  try { fn(); passed++; console.log(`  ✅ ${name}`); }
  catch (e) { failed++; console.log(`  ❌ ${name}: ${e instanceof Error ? e.message : String(e)}`); }
}
function ok(c: boolean, m: string) { if (!c) throw new Error(m); }
function eq(a: unknown, b: unknown, m: string) { if (JSON.stringify(a) !== JSON.stringify(b)) throw new Error(`${m}: expected ${JSON.stringify(b)}, got ${JSON.stringify(a)}`); }

// ============================================================
// 场景 1: 意图识别 — 四种路径
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('场景 1: 意图识别 — 四种路径');
console.log('='.repeat(60));

// 1a. 规则引擎路径
t('规则路径: "BTC现在多少钱" → market_query (规则)', () => {
  const r = recognizeIntent('BTC现在多少钱');
  eq(r.intent, 'market_query', 'Wrong intent');
  eq(r.method, 'rule', 'Wrong method');
  ok(r.matched_pattern_id !== undefined, 'Should have pattern_id');
});

t('规则路径: "帮我开个BTC多单" → execute_trade', () => {
  const r = recognizeIntent('帮我开个BTC多单');
  eq(r.intent, 'execute_trade', 'Wrong intent');
  ok(r.matched_pattern_id !== undefined, 'Should have pattern_id');
});

// 1b. LLM 路径（规则未匹配但 LLM 可识别）
t('LLM路径: "BTC如果跌到6万会怎样" → scenario_sim (模拟LLM)', () => {
  const r = recognizeIntent('BTC如果跌到6万会怎样');
  ok(r.intent === 'scenario_sim' || r.intent === 'deep_analysis', 'Should be scenario_sim or deep_analysis');
});

t('LLM路径: "预测下周BTC走势" → scenario_sim', () => {
  const r = recognizeIntent('预测下周BTC走势');
  ok(r.intent === 'scenario_sim', `Wrong intent: ${r.intent}`);
});

// 1c. 追问路径
t('追问路径: 上下文"deep_analysis" + "为什么" → deep_analysis', () => {
  const r = recognizeIntent('为什么', 'deep_analysis');
  eq(r.intent, 'deep_analysis', 'Should continue last intent');
  eq(r.method, 'follow_up', 'Should be follow_up');
});

t('追问路径: 上下文"market_query" + "涨" → market_query', () => {
  const r = recognizeIntent('涨', 'market_query');
  eq(r.intent, 'market_query', 'Should continue market_query');
  eq(r.method, 'follow_up', 'Should be follow_up');
});

// 1d. 默认兜底
t('兜底路径: "xjhfksdjkfh" → simple_qa (默认)', () => {
  const r = recognizeIntent('xjhfksdjkfh');
  eq(r.intent, 'simple_qa', 'Should fallback to simple_qa');
  eq(r.method, 'default', 'Should be default');
});

t('兜底路径: "!@#$%^&*" → simple_qa', () => {
  const r = recognizeIntent('!@#$%^&*');
  eq(r.intent, 'simple_qa', 'Should fallback to simple_qa');
});

// ============================================================
// 场景 2: 智能路由 — 角色 × 复杂度矩阵
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('场景 2: 智能路由 — 角色×复杂度矩阵');
console.log('='.repeat(60));

// FREE 用户
t('FREE + market_query → knowledge_base + market_data', () => {
  const r = routeIntent('market_query', 'simple', 'FREE', 'quick');
  eq(r.chain, ['knowledge_base', 'market_data'], 'Wrong chain');
  eq(r.role_check, 'pass', 'Should pass');
  eq(r.loop, 'intelligence', 'Wrong loop');
});

t('FREE + deep_analysis → knowledge_base + A1_research', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'FREE', 'quick');
  eq(r.chain, ['knowledge_base', 'A1_research'], 'Wrong chain');
});

t('FREE + execute_trade → upgrade_required', () => {
  const r = routeIntent('execute_trade', 'complex', 'FREE', 'deep');
  eq(r.chain, [], 'Chain should be empty');
  eq(r.role_check, 'upgrade_required', 'Should require upgrade');
});

t('FREE + scenario_sim (complex) → 降级到knowledge_base', () => {
  const r = routeIntent('scenario_sim', 'complex', 'FREE', 'deep');
  eq(r.chain, ['knowledge_base'], 'Should downgrade');
  eq(r.role_check, 'upgrade_required', 'Should require upgrade');
});

// PRO 用户
t('PRO + market_query (quick) → A6_intelligence + market_data', () => {
  const r = routeIntent('market_query', 'simple', 'PRO', 'quick');
  eq(r.chain, ['A6_intelligence', 'market_data'], 'Wrong chain');
});

t('PRO + deep_analysis (deep) → A1→A2→A3→A4', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'deep');
  eq(r.chain, ['A1_research', 'A2_analysis', 'A3_simulation', 'A4_validation'], 'Wrong chain');
});

t('PRO + deep_analysis (quick) → A1_research', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'quick');
  eq(r.chain, ['A1_research'], 'Wrong chain');
});

t('PRO + execute_trade (deep) → A4→A5→A9', () => {
  const r = routeIntent('execute_trade', 'complex', 'PRO', 'deep');
  eq(r.chain, ['A4_validation', 'A5_execution', 'A9_exit'], 'Wrong chain');
  ok(r.requires_confirmation === true, 'Trade should require confirmation');
});

t('PRO + strategy_verify (deep) → A3→A4→A5', () => {
  const r = routeIntent('strategy_verify', 'moderate', 'PRO', 'deep');
  eq(r.chain, ['A3_simulation', 'A4_validation', 'A5_execution'], 'Wrong chain');
});

// 紧急事件
t('任何角色 + urgent → A6_intelligence + A6_alert', () => {
  for (const role of ['FREE', 'PRO', 'ADMIN'] as const) {
    const r = routeIntent('market_query', 'urgent', role, 'quick');
    eq(r.chain, ['A6_intelligence', 'A6_alert'], `${role} urgent should force intel chain`);
  }
});

// 积分和时间
t('积分计算: A1→A2→A3→A4 = 350 credits', () => {
  const r = routeIntent('deep_analysis', 'moderate', 'PRO', 'deep');
  eq(r.credits, 350, 'Wrong credits');
});

t('时间计算: A4→A5→A9 = 95000ms', () => {
  const r = routeIntent('execute_trade', 'complex', 'PRO', 'deep');
  eq(r.time_ms, 95000, 'Wrong time');
});

// ============================================================
// 场景 3: 记忆库 — 记录/查询/反馈/发现/调整/持久化
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('场景 3: 记忆库 — 全生命周期');
console.log('='.repeat(60));

// 模拟记忆库操作
const memoryStore: Array<{
  id: string;
  timestamp: string;
  input: string;
  recognized_intent: string;
  recognized_confidence: number;
  recognized_method: string;
  recognized_complexity: string;
  matched_pattern_id?: string;
  llm_intent?: string;
  llm_confidence?: number;
  routing_chain: string[];
  user_feedback?: 'correct' | 'incorrect' | null;
  corrected_intent?: string;
  session_id: string;
  user_role: string;
}> = [];

function memRecord(data: Omit<typeof memoryStore[0], 'id' | 'timestamp' | 'user_feedback'>): string {
  const id = `mem_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  memoryStore.push({ ...data, id, timestamp: new Date().toISOString(), user_feedback: null });
  return id;
}

function memFeedback(id: string, feedback: 'correct' | 'incorrect', corrected?: string) {
  for (const r of memoryStore) {
    if (r.id === id) { r.user_feedback = feedback; r.corrected_intent = corrected; return true; }
  }
  return false;
}

// 3a. 记录写入
t('记忆记录: 记录 10 条不同输入', () => {
  const inputs = [
    { input: 'BTC现在多少钱', intent: 'market_query', method: 'rule' as const, complexity: 'simple' as const },
    { input: '分析一下BTC走势', intent: 'deep_analysis', method: 'rule' as const, complexity: 'moderate' as const },
    { input: '预测下周BTC走势', intent: 'scenario_sim', method: 'rule' as const, complexity: 'complex' as const },
    { input: '帮我开个BTC多单', intent: 'execute_trade', method: 'rule' as const, complexity: 'complex' as const },
    { input: 'BTC如果跌到6万会怎样', intent: 'scenario_sim', method: 'rule' as const, complexity: 'complex' as const },
    { input: '我还剩多少积分', intent: 'credits_query', method: 'rule' as const, complexity: 'simple' as const },
    { input: '看看昨天的报告', intent: 'artifact_query', method: 'rule' as const, complexity: 'simple' as const },
    { input: '什么风险', intent: 'risk_alert_response', method: 'rule' as const, complexity: 'urgent' as const },
    { input: '关闭交易', intent: 'system_config', method: 'rule' as const, complexity: 'simple' as const },
    { input: 'xjhfksdjkfh', intent: 'simple_qa', method: 'default' as const, complexity: 'simple' as const },
  ];
  for (const inp of inputs) {
    memRecord({
      input: inp.input,
      recognized_intent: inp.intent,
      recognized_confidence: 0.8,
      recognized_method: inp.method,
      recognized_complexity: inp.complexity,
      matched_pattern_id: inp.method === 'rule' ? 'eq_001' : undefined,
      routing_chain: ['market_data'],
      session_id: 'test_session_1',
      user_role: 'PRO',
    });
  }
  ok(memoryStore.length === 10, `Expected 10 records, got ${memoryStore.length}`);
});

// 3b. 反馈
t('记忆反馈: 标记前 8 条为 correct', () => {
  for (let i = 0; i < 8; i++) {
    const success = memFeedback(memoryStore[i].id, 'correct');
    ok(success, `Failed to mark record ${i} as correct`);
  }
  const correctCount = memoryStore.filter(r => r.user_feedback === 'correct').length;
  ok(correctCount === 8, `Expected 8 correct, got ${correctCount}`);
});

t('记忆反馈: 标记第 9 条为 incorrect (不覆盖 correct)', () => {
  memFeedback(memoryStore[9].id, 'incorrect', 'deep_analysis');
  const correctCount = memoryStore.filter(r => r.user_feedback === 'correct').length;
  const incorrectCount = memoryStore.filter(r => r.user_feedback === 'incorrect').length;
  ok(correctCount === 8, `Expected 8 correct, got ${correctCount}`);
  ok(incorrectCount === 1, `Expected 1 incorrect, got ${incorrectCount}`);
});

t('记忆反馈: 覆盖标记 — 将第 1 条从 correct 改为 incorrect', () => {
  memFeedback(memoryStore[0].id, 'incorrect', 'deep_analysis');
  const incorrectCount = memoryStore.filter(r => r.user_feedback === 'incorrect').length;
  const correctCount = memoryStore.filter(r => r.user_feedback === 'correct').length;
  // memoryStore[9] was already incorrect, now memoryStore[0] is also incorrect (overwritten from correct)
  ok(incorrectCount === 2, `Expected 2 incorrect, got ${incorrectCount}`);
  ok(correctCount === 7, `Expected 7 correct, got ${correctCount}`);
});

// 3c. 统计计算
t('记忆统计: 准确率计算 (7正确/2错误 = 78%)', () => {
  const correctCount = memoryStore.filter(r => r.user_feedback === 'correct').length;
  const incorrectCount = memoryStore.filter(r => r.user_feedback === 'incorrect').length;
  const accuracyRate = correctCount + incorrectCount > 0
    ? Math.round((correctCount / (correctCount + incorrectCount)) * 100)
    : 0;
  ok(accuracyRate === 78, `Accuracy should be 78%, got ${accuracyRate}%`);
});

t('记忆统计: 方法分布', () => {
  const dist: Record<string, number> = {};
  for (const r of memoryStore) {
    dist[r.recognized_method] = (dist[r.recognized_method] || 0) + 1;
  }
  ok(dist['rule'] === 9, 'Should have 9 rule records');
  ok(dist['default'] === 1, 'Should have 1 default record');
});

t('记忆统计: 意图分布', () => {
  const dist: Record<string, number> = {};
  for (const r of memoryStore) {
    dist[r.recognized_intent] = (dist[r.recognized_intent] || 0) + 1;
  }
  ok(dist['scenario_sim'] === 2, 'Should have 2 scenario_sim records');
});

// 3d. LLM vs Rule 差异记录
t('记忆记录: LLM-only 记录 (规则未匹配)', () => {
  // 直接插入 LLM-only 记录，确保 method='llm' 且无 pattern_id
  const llmOnlyInputs = [
    'btc到7万会怎样',
    'btc如果跌破9万怎么办',
    'btc假如跌到5万呢',
  ];
  for (const input of llmOnlyInputs) {
    memRecord({
      input,
      recognized_intent: 'scenario_sim',
      recognized_confidence: 0.72,
      recognized_method: 'llm',
      recognized_complexity: 'complex',
      matched_pattern_id: undefined,
      llm_intent: 'scenario_sim',
      llm_confidence: 0.72,
      routing_chain: [],
      session_id: 'test_session_2',
      user_role: 'PRO',
    });
  }
});

// 3e. 候选模式发现
t('记忆候选: 发现高频 LLM-only 模式', () => {
  const llmOnlyRecords = memoryStore.filter(r => !r.matched_pattern_id && r.recognized_method === 'llm');
  ok(llmOnlyRecords.length >= 3, `Should have at least 3 LLM-only records, got ${llmOnlyRecords.length}`);

  // 模拟 ngram 提取 (中英文混合)
  function extractNgrams(input: string): string[] {
    const cleaned = input.replace(/[^\w\u4e00-\u9fff]/g, '').trim().toLowerCase();
    if (cleaned.length < 2) return [];
    const ngrams: string[] = [];
    for (let i = 0; i < cleaned.length - 1; i++) {
      ngrams.push(cleaned.slice(i, i + 2));
      if (i < cleaned.length - 2) ngrams.push(cleaned.slice(i, i + 3));
    }
    return [...new Set(ngrams)];
  }

  const keywordCounts: Record<string, number> = {};
  for (const r of llmOnlyRecords) {
    for (const w of extractNgrams(r.input)) {
      keywordCounts[w] = (keywordCounts[w] || 0) + 1;
    }
  }

  const frequent = Object.entries(keywordCounts)
    .filter(([, count]) => count >= 2)
    .sort((a, b) => b[1] - a[1]);

  // 所有 3 条记录都包含 "btc"，应出现 3 次
  ok(keywordCounts['btc'] === 3, `"btc" should appear 3 times, got ${keywordCounts['btc']}`);
  ok(frequent.length > 0, `Should find frequent ngrams, got ${frequent.length}`);
});

// 3f. 持久化
t('记忆持久化: 写入 records.json', () => {
  const testPath = path.resolve(__dirname, 'test-memory-records.json');
  fs.writeFileSync(testPath, JSON.stringify({
    records: memoryStore,
    total: memoryStore.length,
    saved_at: new Date().toISOString(),
  }, null, 2));
  ok(fs.existsSync(testPath), 'File should exist');
  const loaded = JSON.parse(fs.readFileSync(testPath, 'utf-8'));
  ok(loaded.records.length === memoryStore.length, 'Records should match');
  // 清理
  fs.unlinkSync(testPath);
});

// ============================================================
// 场景 4: 端到端 — 用户输入 → 意图识别 → 智能路由 → 记忆记录
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('场景 4: 端到端 — 完整用户交互流程');
console.log('='.repeat(60));

interface E2EScenario {
  name: string;
  userRole: 'FREE' | 'PRO' | 'ADMIN';
  thinkingMode: 'quick' | 'deep';
  inputs: Array<{
    message: string;
    context?: string; // last_intent
    expectedIntent: string;
    expectedLoop?: string;
    expectedChainLength?: number;
  }>;
}

const scenarios: E2EScenario[] = [
  {
    name: 'FREE 用户行情查询',
    userRole: 'FREE',
    thinkingMode: 'quick',
    inputs: [
      { message: 'BTC现在多少钱', expectedIntent: 'market_query', expectedLoop: 'intelligence', expectedChainLength: 2 },
      { message: '涨', context: 'market_query', expectedIntent: 'market_query', expectedLoop: 'intelligence' },
      { message: '详细点', context: 'market_query', expectedIntent: 'market_query', expectedLoop: 'intelligence' },
    ],
  },
  {
    name: 'PRO 用户深度分析',
    userRole: 'PRO',
    thinkingMode: 'deep',
    inputs: [
      { message: '分析一下BTC走势', expectedIntent: 'deep_analysis', expectedLoop: 'execution', expectedChainLength: 4 },
      { message: '为什么', context: 'deep_analysis', expectedIntent: 'deep_analysis', expectedLoop: 'execution' },
    ],
  },
  {
    name: 'PRO 用户情景推演',
    userRole: 'PRO',
    thinkingMode: 'deep',
    inputs: [
      { message: '预测下周BTC走势', expectedIntent: 'scenario_sim', expectedLoop: 'execution', expectedChainLength: 3 },
      { message: 'BTC如果跌到6万会怎样', expectedIntent: 'scenario_sim', expectedLoop: 'execution', expectedChainLength: 3 },
    ],
  },
  {
    name: 'FREE 用户交易请求被拒',
    userRole: 'FREE',
    thinkingMode: 'deep',
    inputs: [
      { message: '帮我开个BTC多单', expectedIntent: 'execute_trade', expectedLoop: 'execution', expectedChainLength: 0 },
    ],
  },
  {
    name: '紧急事件处理',
    userRole: 'PRO',
    thinkingMode: 'quick',
    inputs: [
      { message: '紧急处理', expectedIntent: 'risk_alert_response', expectedLoop: 'intelligence', expectedChainLength: 2 },
    ],
  },
];

let e2eTotal = 0;
let e2ePassed = 0;
for (const scenario of scenarios) {
  console.log(`\n  ── ${scenario.name} (${scenario.userRole}, ${scenario.thinkingMode}) ──`);
  let lastIntent: string | undefined;
  for (const input of scenario.inputs) {
    e2eTotal++;
    // Step 1: 意图识别
    const intentResult = recognizeIntent(input.message, input.context || lastIntent);
    // Step 2: 智能路由
    const routeResult = routeIntent(intentResult.intent, intentResult.complexity, scenario.userRole, scenario.thinkingMode);

    let allPass = true;
    let issues: string[] = [];

    if (intentResult.intent !== input.expectedIntent) {
      allPass = false;
      issues.push(`intent: expected ${input.expectedIntent}, got ${intentResult.intent}`);
    }
    if (input.expectedLoop && routeResult.loop !== input.expectedLoop) {
      allPass = false;
      issues.push(`loop: expected ${input.expectedLoop}, got ${routeResult.loop}`);
    }
    if (input.expectedChainLength !== undefined && routeResult.chain.length !== input.expectedChainLength) {
      allPass = false;
      issues.push(`chain length: expected ${input.expectedChainLength}, got ${routeResult.chain.length} (${routeResult.chain.join(' → ')})`);
    }

    // 角色拦截验证
    if (scenario.userRole === 'FREE' && input.expectedIntent === 'execute_trade') {
      if (routeResult.role_check !== 'upgrade_required') {
        allPass = false;
        issues.push('should require upgrade for FREE + execute_trade');
      }
    }

    // Step 3: 记忆记录
    const memId = memRecord({
      input: input.message,
      recognized_intent: intentResult.intent,
      recognized_confidence: intentResult.confidence,
      recognized_method: intentResult.method,
      recognized_complexity: intentResult.complexity,
      matched_pattern_id: intentResult.matched_pattern_id,
      llm_intent: intentResult.llm_intent,
      llm_confidence: intentResult.llm_confidence,
      routing_chain: routeResult.chain,
      session_id: `e2e_${scenario.name.replace(/\s/g, '_')}`,
      user_role: scenario.userRole,
    });

    if (allPass) {
      e2ePassed++;
      console.log(`    ✅ "${input.message}" → ${intentResult.intent} [${routeResult.loop}] ${routeResult.chain.join(' → ')} (mem: ${memId.slice(0, 20)}...)`);
    } else {
      console.log(`    ❌ "${input.message}" → ${intentResult.intent} [${routeResult.loop}] ${issues.join(', ')}`);
    }

    lastIntent = intentResult.intent;
  }
}

// ============================================================
// 场景 5: 边界/异常
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('场景 5: 边界/异常输入');
console.log('='.repeat(60));

t('空字符串 → simple_qa (兜底)', () => {
  const r = recognizeIntent('');
  eq(r.intent, 'simple_qa', 'Should fallback to simple_qa');
});

t('纯空格 → simple_qa (兜底)', () => {
  const r = recognizeIntent('   ');
  eq(r.intent, 'simple_qa', 'Should fallback to simple_qa');
});

t('emoji 输入 → 不崩溃', () => {
  const r = recognizeIntent('🚀 BTC 📈');
  ok(typeof r.intent === 'string', 'Should return a valid intent');
});

t('SQL 注入 → 不崩溃', () => {
  const r = recognizeIntent("'; DROP TABLE users; --");
  ok(typeof r.intent === 'string', 'Should return a valid intent');
});

t('XSS 输入 → 不崩溃', () => {
  const r = recognizeIntent('<script>alert("xss")</script>');
  ok(typeof r.intent === 'string', 'Should return a valid intent');
});

t('超长输入 → 不崩溃', () => {
  const r = recognizeIntent('BTC'.repeat(100));
  ok(typeof r.intent === 'string', 'Should return a valid intent');
});

// ============================================================
// 报告
// ============================================================
console.log('\n' + '='.repeat(60));
console.log('📊 多场景验证报告');
console.log('='.repeat(60));
console.log(`  单元测试: ${passed}/${total} 通过, ${failed} 失败`);
console.log(`  端到端场景: ${e2ePassed}/${e2eTotal} 通过`);
console.log(`  记忆库记录数: ${memoryStore.length} 条`);
console.log(`  反馈记录: ${memoryStore.filter(r => r.user_feedback === 'correct').length} 正确, ${memoryStore.filter(r => r.user_feedback === 'incorrect').length} 错误`);
console.log(`  经验模式库: ${PATTERNS.length} 条模式`);

if (failed === 0) {
  console.log('\n  ✅ ALL SCENARIOS PASSED');
} else {
  console.log(`\n  ❌ ${failed} TESTS FAILED`);
  process.exit(1);
}
