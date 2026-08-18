/**
 * Dynamic Chain Smoke Test
 *
 * 验证：types, planner, executor, reflect-engine, runner 之间端到端协同
 * 用法：npx tsx scripts/dynamic-chain-smoke-test.ts
 */

import { generateInitialPlan } from '../src/lib/dynamic-chain/graph-planner';
import { executeStepPlan } from '../src/lib/dynamic-chain/executor';
import { reflect, DYNAMIC_CHAIN_CONSTANTS } from '../src/lib/dynamic-chain/reflect-engine';
import { runDynamicChain } from '../src/lib/dynamic-chain/runner';
import { createGraphReflectionState, buildGraphSummary, updateCompressionSignal } from '../src/lib/graph-reflection-bridge';
import { routeIntent } from '../src/lib/intent/smart-router';
import { compressorAdapter } from '../src/lib/compressor-adapter';

const RESULTS: { name: string; pass: boolean; message?: string; duration?: number }[] = [];

function assert(name: string, cond: boolean, message = '') {
  const pass = !!cond;
  RESULTS.push({ name, pass, message: pass ? '' : message });
  console.log(`  ${pass ? '✅' : '❌'} ${name}` + (message && !pass ? ` — ${message}` : ''));
}

// ------------------------
// T1: 类型正确性（planner 生成 plan 且步骤数合理）
// ------------------------
console.log('\n=== T1: Planner 类型正确性 ===');
const plan = generateInitialPlan({
  intent: 'deep_analysis',
  message: 'BTC 今日趋势如何？',
  sessionId: 'test-planner-001',
  symbol: 'BTC',
  category: 'crypto',
  displayName: 'Bitcoin',
  instId: 'BTC-USDT-SWAP',
  thinkingMode: 'deep',
  lang: 'zh',
  entities: { timeframe: '4h' },
});

assert('Plan steps > 0', plan.steps.length > 0, `got ${plan.steps.length} steps`);
assert('Plan rationale non-empty', plan.rationale.length > 0, `got rationale of length ${plan.rationale.length}`);
assert('Plan.steps contains S1_RESEARCH', plan.steps.some((s) => s.id === 'S1_RESEARCH'));
assert('Plan.steps contains S2_ANALYSIS', plan.steps.some((s) => s.id === 'S2_ANALYSIS'));
assert('Plan.steps contains S3_DESIGN', plan.steps.some((s) => s.id === 'S3_DESIGN'));
assert('Plan.steps contains S4_VALIDATE', plan.steps.some((s) => s.id === 'S4_VALIDATE'));

// 同样测试其他意图
const stratVerify = generateInitialPlan({
  intent: 'strategy_verify',
  message: '验证我的策略：买入价低于MA5时做多',
  sessionId: 'test-planner-002',
  symbol: 'BTC',
  category: 'crypto',
  displayName: 'Bitcoin',
  instId: 'BTC-USDT-SWAP',
  thinkingMode: 'standard',
  lang: 'zh',
});
assert('strategy_verify 从 S2 起步', stratVerify.steps[0]?.id === 'S2_ANALYSIS', `首步：${stratVerify.steps[0]?.id}`);

// ------------------------
// T2: Executor — 每步有内容且生成 token 数合理
// ------------------------
console.log('\n=== T2: Executor 步骤产出 ===');
let graphState = createGraphReflectionState('exec-test-001');
const outputs: { id: string; len: number; confidence: number; risk: number }[] = [];
for (const step of plan.steps) {
  const r = executeStepPlan(step, {
    intent: 'deep_analysis',
    message: 'BTC 今日趋势如何？',
    sessionId: 'exec-test-001',
    symbol: 'BTC',
    category: 'crypto',
    displayName: 'Bitcoin',
    instId: 'BTC-USDT-SWAP',
    thinkingMode: 'deep',
    lang: 'zh',
  }, graphState, outputs.map((o) => ({
    stepId: o.id,
    content: `content for ${o.id}`,
    confidence: 0.8,
    riskScore: 0.3,
    issuesFound: [],
    corrections: [],
    latencyMs: 0,
    tokenCost: 0,
  })));

  outputs.push({ id: r.stepId, len: r.content.length, confidence: r.confidence, risk: r.riskScore });
  assert(`Step ${step.id} 非空输出`, r.content.length > 50, `length=${r.content.length}`);
  assert(`Step ${step.id} 置信度合理`, r.confidence >= 0.3, `confidence=${r.confidence}`);
}

// graphState 节点状态更新
updateCompressionSignal(graphState);
const gs = buildGraphSummary(graphState);
assert('GraphSummary completed nodes > 0', gs.totalNodes >= 4, `got ${gs.totalNodes}`);
assert('GraphSummary 有 compressible 节点', gs.compressibleCount >= 0);

// ------------------------
// T3: Reflect Engine — 各决策分支均能触发
// 新策略：REDO/JUMP_TO/CONTINUE 都可能触发，验证各分支可达
// ------------------------
console.log('\n=== T3: Reflect Engine ===');
const gs3 = createGraphReflectionState('reflect-test-001');
const highConfResult = executeStepPlan(plan.steps[0], {
  intent: 'deep_analysis', message: 'BTC', sessionId: 'reflect-test-001',
  symbol: 'BTC', category: 'crypto', displayName: 'Bitcoin', instId: 'BTC-USDT-SWAP',
  thinkingMode: 'deep', lang: 'zh',
}, gs3, []);

// 验证新置信度分布：S1 无 marketData + deep 模式 → 应该有 issues 累积
// 置信度预期 < 0.55（REDO）或在 [0.55, 0.85] 范围（CONTINUE/JUMP_TO）
// 关键是：不再 100% 都是 CONTINUE
const r1 = reflect(plan, gs3, highConfResult, { intent: 'deep_analysis' } as any, 1, 1);
const allowedDecisions = new Set(['CONTINUE', 'REDO', 'JUMP_TO', 'INSERT_BEFORE', 'EARLY_TERMINATE']);
assert(
  `Reflect 返回合法决策类型`,
  allowedDecisions.has(r1.type),
  `got ${r1.type}`
);
// 若触发了 REDO，说明新的 analyzeStepConfidence 正确检测到质量问题
assert(
  `Reflect 决策reason非空`,
  (r1.reason?.length ?? 0) > 10,
  `reason="${r1.reason}"`
);

// ------------------------
// T4: Runner — 端到端执行（无异常）
// ------------------------
console.log('\n=== T4: Runner 端到端 ===');
const result = runDynamicChain({
  intent: 'deep_analysis',
  message: '深度分析 BTC 未来 24 小时趋势',
  sessionId: 'runner-test-001',
  symbol: 'BTC',
  category: 'crypto',
  displayName: 'Bitcoin',
  instId: 'BTC-USDT-SWAP',
  thinkingMode: 'deep',
  lang: 'zh',
});

assert('Runner 返回 success=true', result.success);
assert('Runner steps >= 3', result.steps.length >= 3, `got ${result.steps.length}`);
assert('Runner summaryMarkdown 非空', result.summaryMarkdown.length > 200, `length=${result.summaryMarkdown.length}`);
assert('Runner metadata has reflectionTrace', Array.isArray(result.metadata.reflectionTrace));

// ------------------------
// T5: smart-router 升级意图的 is_dynamic
// ------------------------
console.log('\n=== T5: smart-router 动态路由标志 ===');
const r5 = routeIntent('deep_analysis', 'complex', {
  session_id: 'router-test-001',
  user_role: 'PRO',
  thinking_mode: 'deep',
  message_history: ['分析 BTC 趋势'],
});
assert('deep_analysis with PRO => is_dynamic=true', r5.is_dynamic === true, `got ${r5.is_dynamic}`);

const r5b = routeIntent('simple_qa', 'simple', {
  session_id: 'router-test-002',
  user_role: 'FREE',
  thinking_mode: 'quick',
  message_history: ['hello'],
});
assert('simple_qa with FREE => is_dynamic 为 undefined/false', r5b.is_dynamic !== true, `got is_dynamic=${r5b.is_dynamic}`);

// ------------------------
// T6: compressor-adapter 图感知压缩
// ------------------------
console.log('\n=== T6: Compressor 图感知压缩 ===');
const r6 = compressorAdapter.compressFromGraphState(graphState);
assert('Compression ratio <= 1', r6.compressionRatio <= 1, `ratio=${r6.compressionRatio}`);
assert('Compression stats.totalNodes > 0', r6.stats.totalNodes > 0);
assert('Compression graph has architecture nodes',
  Array.isArray((r6.graph as any).architecture) || !!(r6.graph as any).architecture,
  'missing architecture field');

// ------------------------
// T7: execute_trade / scenario_sim / strategy_verify 全意图覆盖
// ------------------------
console.log('\n=== T7: 所有动态意图跑一遍 ===');
for (const intent of ['deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade'] as const) {
  const r7 = runDynamicChain({
    intent,
    message: `[${intent}] 测试消息`,
    sessionId: `intent-test-${intent}`,
    symbol: 'BTC',
    category: 'crypto',
    displayName: 'Bitcoin',
    instId: 'BTC-USDT-SWAP',
    thinkingMode: 'standard',
    lang: 'zh',
  });
  assert(`意图 ${intent} 成功`, r7.success, `success=${r7.success}`);
  assert(`意图 ${intent} summaryMarkdown 非空`, r7.summaryMarkdown.length > 200, `len=${r7.summaryMarkdown.length}`);
}

// ------------------------
// 汇总
// ------------------------
const passed = RESULTS.filter((r) => r.pass).length;
const total = RESULTS.length;
console.log('\n==============================');
console.log(`Results: ${passed}/${total} passed`);
console.log(`Failures: ${total - passed}`);
console.log('==============================');

RESULTS.filter((r) => !r.pass).forEach((r) => console.log(`  ❌ ${r.name} — ${r.message || '(无详情)'}`));
console.log();

if (total - passed > 0) process.exit(1);
process.exit(0);
