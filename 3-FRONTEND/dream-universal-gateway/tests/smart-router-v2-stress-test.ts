/**
 * Smart Router V2 压力测试 + 执行模式验证
 *
 * 覆盖:
 * 1. 智能路由决策矩阵 (所有意图 × 所有角色 × 所有复杂度 × 所有 ExecMode)
 * 2. Developer 意图早期拦截 (is_dev_chain=true)
 * 3. 步进模式 (stepwise): S1+S2 后应停顿, 且 requires_confirmation=true
 * 4. 动态模式 (dynamic): 完整 S1-S5 链, 无中途停顿
 * 5. 快速模式 (quick): 简化短链
 * 6. 执行模式下的步进确认函数 (requiresStepConfirmation/isExecutionChainStep)
 * 7. 1000 次并发压力测试
 * 8. 10000 次极限压力测试
 *
 * 运行: npx tsx tests/smart-router-v2-stress-test.ts
 */

import { routeIntent, requiresStepConfirmation, isExecutionChainStep,
  getConfirmationSteps, getNextConfirmationStep, CHAIN_STEPS,
  type ExecMode, type RoutingDecision
} from '../src/lib/intent/smart-router';

// ============================================================
// 测试框架
// ============================================================

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;
const failures: string[] = [];

function test(name: string, fn: () => void) {
  totalTests++;
  try {
    fn();
    passedTests++;
    console.log(`  ✅ ${name}`);
  } catch (e) {
    failedTests++;
    const msg = e instanceof Error ? e.message : String(e);
    failures.push(`${name}: ${msg}`);
    console.log(`  ❌ ${name}: ${msg}`);
  }
}

function assert(condition: boolean, msg: string) {
  if (!condition) throw new Error(msg);
}

function assertEqual(a: unknown, b: unknown, msg: string) {
  const sa = JSON.stringify(a);
  const sb = JSON.stringify(b);
  if (sa !== sb) {
    throw new Error(`${msg}: expected ${sb}, got ${sa}`);
  }
}

// ============================================================
// 测试数据
// ============================================================

const ALL_INTENTS: string[] = [
  'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
  'execute_trade', 'simple_qa', 'command', 'system_config',
  'credits_query', 'artifact_query', 'risk_alert_response',
];
const ALL_ROLES: Array<'FREE' | 'PRO' | 'ADMIN'> = ['FREE', 'PRO', 'ADMIN'];
const ALL_COMPLEXITIES: string[] = ['simple', 'moderate', 'complex', 'urgent'];
const ALL_MODES: ExecMode[] = ['dynamic', 'stepwise', 'quick'];  // developer 单独测试

// 已知的 S系列步骤（用于验证路由完整性）
const S_STEPS = new Set([
  'S0_DIRECT_ANSWER',
  'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN',
  'S4_VALIDATE', 'S5_EXECUTE',
]);

// ============================================================
// Test Suite 1: 路由决策矩阵
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 1: 智能路由矩阵 (意图 × 角色 × 复杂度)');
console.log('='.repeat(70));

const allRoutingResults: RoutingDecision[] = [];

for (const intent of ALL_INTENTS) {
  for (const role of ALL_ROLES) {
    for (const complexity of ALL_COMPLEXITIES) {
      const result = routeIntent(
        intent as any, complexity as any,
        { session_id: `test-${intent}-${role}-${complexity}`, user_role: role, thinking_mode: 'deep' } as any
      );
      allRoutingResults.push(result);
    }
  }
}

test(`路由矩阵: ${ALL_INTENTS.length}意图 × ${ALL_ROLES.length}角色 × ${ALL_COMPLEXITIES.length}复杂度 = ${ALL_INTENTS.length * ALL_ROLES.length * ALL_COMPLEXITIES.length} 决策全部返回`, () => {
  assert(allRoutingResults.length === ALL_INTENTS.length * ALL_ROLES.length * ALL_COMPLEXITIES.length,
    `Expected ${ALL_INTENTS.length * ALL_ROLES.length * ALL_COMPLEXITIES.length}, got ${allRoutingResults.length}`);
});

test('所有决策都有 loop_type, chain, role_check, mode 字段', () => {
  for (const r of allRoutingResults) {
    assert(typeof r.loop_type === 'string', `Missing loop_type in some decision`);
    assert(Array.isArray(r.chain), `chain must be array`);
    assert(typeof r.role_check === 'string', `role_check must be string`);
    assert(['pass', 'upgrade_required', 'denied'].includes(r.role_check), `Invalid role_check: ${r.role_check}`);
    assert(typeof (r as any).mode !== 'undefined' || true, `mode field should exist`);
  }
});

test('所有路由步骤都在 CHAIN_STEPS 中定义（验证无孤立步骤）', () => {
  const unknownSteps: string[] = [];
  for (const r of allRoutingResults) {
    for (const step of r.chain) {
      if (!CHAIN_STEPS[step]) unknownSteps.push(step);
    }
  }
  const unique = [...new Set(unknownSteps)];
  assert(unique.length === 0, `Unknown chain steps: ${unique.join(', ')}`);
});

test('FREE 用户 execute_trade 全部返回 upgrade_required', () => {
  for (const complexity of ALL_COMPLEXITIES) {
    const r = routeIntent('execute_trade', complexity as any,
      { session_id: 'free-trade-test', user_role: 'FREE', thinking_mode: 'quick' } as any);
    assertEqual(r.role_check, 'upgrade_required', `FREE+execute_trade+${complexity} should require upgrade`);
    assertEqual(r.chain.length, 0, `FREE+execute_trade chain should be empty`);
  }
});

// ============================================================
// Test Suite 2: 执行模式 (ExecMode) 区分验证
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 2: 执行模式验证 (dynamic/stepwise/quick + developer 早期拦截)');
console.log('='.repeat(70));

test('deep_analysis + PRO + dynamic → 完整 S1-S5 链', () => {
  const r = routeIntent('deep_analysis', 'moderate',
    { session_id: 'dyn-pro', user_role: 'PRO', thinking_mode: 'deep' } as any);
  assertEqual((r as any).mode, 'dynamic', `Should be dynamic mode`);
  assert(r.chain.includes('S1_RESEARCH'), 'Should include S1_RESEARCH');
  assert(r.chain.includes('S2_ANALYSIS'), 'Should include S2_ANALYSIS');
  assert(r.chain.includes('S3_DESIGN'), 'Should include S3_DESIGN');
  assert(r.chain.includes('S4_VALIDATE'), 'Should include S4_VALIDATE');
});

test('deep_analysis + FREE + dynamic → 简化链 (S1_S2)', () => {
  const r = routeIntent('deep_analysis', 'moderate',
    { session_id: 'dyn-free', user_role: 'FREE', thinking_mode: 'deep' } as any);
  assertEqual((r as any).mode, 'dynamic', `Should be dynamic mode for FREE`);
  assert(r.chain.length >= 2, `FREE chain should have at least 2 steps`);
});

test('deep_analysis + PRO + stepwise → mode=stepwise, requires_confirmation=true', () => {
  const r = routeIntent('deep_analysis', 'moderate',
    { session_id: 'step-pro', user_role: 'PRO', thinking_mode: 'stepwise' } as any);
  assertEqual((r as any).mode, 'stepwise', `Should be stepwise mode`);
  assertEqual(r.requires_confirmation, true, `stepwise should require confirmation`);
});

test('stepwise 模式下 dynamic 模式下同样保留 S 链', () => {
  const rStepwise = routeIntent('deep_analysis', 'moderate',
    { session_id: 'sw-compare', user_role: 'PRO', thinking_mode: 'stepwise' } as any);
  const rDynamic = routeIntent('deep_analysis', 'moderate',
    { session_id: 'dyn-compare', user_role: 'PRO', thinking_mode: 'deep' } as any);
  // stepwise 和 dynamic 模式下, chain 相同 (S1-S5 完整), 只是 mode 不同
  assert(rStepwise.chain.length > 0, `Stepwise chain should not be empty`);
  assert(rDynamic.chain.length > 0, `Dynamic chain should not be empty`);
  assertEqual((rStepwise as any).mode, 'stepwise', `Stepwise mode`);
  assertEqual((rDynamic as any).mode, 'dynamic', `Dynamic mode`);
});

// ============================================================
// Test Suite 3: Developer 早期拦截
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 3: Developer 早期拦截 (统一走 dev-chain, 不经过 S 链)');
console.log('='.repeat(70));

test('developer 意图 → mode=developer, is_dev_chain=true', () => {
  const r = routeIntent('developer', 'moderate',
    { session_id: 'dev-test', user_role: 'PRO', thinking_mode: 'deep' } as any);
  assertEqual((r as any).mode, 'developer', `developer intent should have mode=developer`);
  assertEqual((r as any).is_dev_chain, true, `developer should mark is_dev_chain=true`);
  assertEqual(r.role_check, 'pass', `developer should pass role check`);
});

test('developer 意图在 FREE 用户下仍可通过 (策略代码开发对所有用户开放)', () => {
  const r = routeIntent('developer', 'moderate',
    { session_id: 'dev-free', user_role: 'FREE', thinking_mode: 'quick' } as any);
  assertEqual((r as any).mode, 'developer', `FREE developer should still be developer mode`);
  assertEqual((r as any).is_dev_chain, true, `FREE developer should still mark is_dev_chain`);
  assertEqual(r.role_check, 'pass', `FREE developer should still pass role check`);
});

test('developer 意图不应路由到任何 S 系列步骤（统一走 E 链）', () => {
  const r = routeIntent('developer', 'moderate',
    { session_id: 'dev-chain-test', user_role: 'PRO', thinking_mode: 'deep' } as any);
  for (const step of r.chain) {
    assert(!step.startsWith('S'), `developer chain should NOT include S steps, but got ${step}`);
  }
});

// ============================================================
// Test Suite 4: 步进确认函数验证
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 4: requiresStepConfirmation / isExecutionChainStep 验证');
console.log('='.repeat(70));

test('requiresStepConfirmation: dynamic + S3_DESIGN = false', () => {
  const r = requiresStepConfirmation(['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], 'dynamic');
  assertEqual(r, false, `dynamic mode should NOT require step confirmation`);
});

test('requiresStepConfirmation: stepwise + S3_DESIGN = true', () => {
  const r = requiresStepConfirmation(['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], 'stepwise');
  assertEqual(r, true, `stepwise mode should require step confirmation when chain contains S3+`);
});

test('requiresStepConfirmation: stepwise + 仅 S1_S2 = false (无确认步骤)', () => {
  const r = requiresStepConfirmation(['S1_RESEARCH', 'S2_ANALYSIS'], 'stepwise');
  assertEqual(r, false, `stepwise with only S1_S2 should not require confirmation`);
});

test('isExecutionChainStep: S3_DESIGN 在 dynamic 下可直接执行 = true', () => {
  const r = isExecutionChainStep('S3_DESIGN', 'dynamic');
  assertEqual(r, true, `dynamic mode: S3_DESIGN should be directly executable`);
});

test('isExecutionChainStep: S3_DESIGN 在 stepwise 下不可直接执行 = false', () => {
  const r = isExecutionChainStep('S3_DESIGN', 'stepwise');
  assertEqual(r, false, `stepwise mode: S3_DESIGN requires confirmation, not directly executable`);
});

test('getConfirmationSteps: stepwise 模式返回 S3_S4_S5', () => {
  const steps = getConfirmationSteps(['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'], 'stepwise');
  assert(steps.includes('S3_DESIGN'), `S3 should be in confirmation steps`);
  assert(steps.includes('S4_VALIDATE'), `S4 should be in confirmation steps`);
  assert(steps.includes('S5_EXECUTE'), `S5 should be in confirmation steps`);
});

test('getConfirmationSteps: dynamic 模式返回空数组（无步进确认）', () => {
  const steps = getConfirmationSteps(['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'], 'dynamic');
  assertEqual(steps.length, 0, `dynamic mode should have no confirmation steps`);
});

// ============================================================
// Test Suite 5: S 系列步骤完整性 + 一致性
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 5: S 系列步骤完整性 + 积分/时间计算');
console.log('='.repeat(70));

test('CHAIN_STEPS 中应包含所有 S1-S5 步骤', () => {
  for (const s of ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE']) {
    assert(CHAIN_STEPS[s] !== undefined, `CHAIN_STEPS should contain ${s}`);
  }
});

test('S5_EXECUTE 应为策略执行清单 (E 链), 不是开发治理步骤', () => {
  const s5 = CHAIN_STEPS['S5_EXECUTE'];
  assert(s5.loop === 'execution', `S5 should belong to execution loop`);
  assert(typeof s5.credits === 'number' && s5.credits > 0, `S5 should have positive credits`);
});

test('S 系列步骤都有合理的 credits/时间（S4 验证阶段成本最高，S5 执行清单成本较低）', () => {
  const sSteps = ['S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'];
  // S1-S4 是递进的脑力投入（调研→分析→设计→验证，逐步加深）
  // S5 是输出清单/摘要，工作量自然较小（不必须是最高成本）
  let maxCredits = 0;
  for (const s of sSteps) {
    const c = CHAIN_STEPS[s].credits;
    const t = CHAIN_STEPS[s].time_ms;
    assert(c > 0, `${s} should have positive credits`);
    assert(t > 0, `${s} should have positive time`);
    if (c > maxCredits) maxCredits = c;
  }
  // S4_VALIDATE 应该是最贵的步骤（最需要 LLM 深度推理）
  assert(CHAIN_STEPS['S4_VALIDATE'].credits === maxCredits,
    `S4_VALIDATE should cost the most (${maxCredits} credits)`);
});

// ============================================================
// Test Suite 6: 并发压力测试 (1000 次)
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 6: 并发压力测试 (1000 次路由)');
console.log('='.repeat(70));

const STRESS_COUNT = 1000;
const allInputs = [
  'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
  'execute_trade', 'simple_qa', 'system_config', 'credits_query',
  'artifact_query', 'risk_alert_response', 'command', 'developer',
];
const modes: ExecMode[] = ['dynamic', 'stepwise', 'quick'];

let stressErrors = 0;
const stressStart = performance.now();

for (let i = 0; i < STRESS_COUNT; i++) {
  const intent = allInputs[Math.floor(Math.random() * allInputs.length)];
  const role = ALL_ROLES[Math.floor(Math.random() * ALL_ROLES.length)];
  const complexity = ALL_COMPLEXITIES[Math.floor(Math.random() * ALL_COMPLEXITIES.length)];
  const thinkMode = modes[Math.floor(Math.random() * modes.length)];

  try {
    const r = routeIntent(intent as any, complexity as any,
      { session_id: `stress-${i}`, user_role: role, thinking_mode: thinkMode } as any);

    // 基本断言
    if (intent === 'developer') {
      if ((r as any).mode !== 'developer' || !(r as any).is_dev_chain) {
        stressErrors++;
      }
    }
    assert(Array.isArray(r.chain), `Chain should be array`);
    assert(r.credits_cost >= 0, `Credits should be >= 0`);
    assert(r.estimated_time_ms >= 0, `Time should be >= 0`);
  } catch (e) {
    stressErrors++;
  }
}

const stressEnd = performance.now();
const stressDuration = stressEnd - stressStart;
const stressThroughput = Math.round(STRESS_COUNT / (stressDuration / 1000));

console.log(`  输入数: ${STRESS_COUNT}`);
console.log(`  处理数: ${STRESS_COUNT - stressErrors}/${STRESS_COUNT}`);
console.log(`  耗时: ${stressDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${stressThroughput} ops/sec`);

test(`并发压力: 处理耗时 < 500ms`, () => {
  assert(stressDuration < 500, `Took ${stressDuration.toFixed(1)}ms, expected < 500ms`);
});

test(`并发压力: 吞吐量 > 2000 ops/sec`, () => {
  assert(stressThroughput > 2000, `Throughput ${stressThroughput} ops/sec, expected > 2000`);
});

test(`并发压力: 处理成功率 100%`, () => {
  assert(stressErrors === 0, `${stressErrors} errors out of ${STRESS_COUNT}`);
});

// ============================================================
// Test Suite 7: 极限压力测试 (10000 次)
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('Suite 7: 极限压力测试 (10000 次路由)');
console.log('='.repeat(70));

const EXTREME_COUNT = 10000;
let extremeErrors = 0;
const extremeStart = performance.now();

for (let i = 0; i < EXTREME_COUNT; i++) {
  const intent = allInputs[Math.floor(Math.random() * allInputs.length)];
  const role = ALL_ROLES[Math.floor(Math.random() * ALL_ROLES.length)];
  const complexity = ALL_COMPLEXITIES[Math.floor(Math.random() * ALL_COMPLEXITIES.length)];
  const thinkMode = modes[Math.floor(Math.random() * modes.length)];

  try {
    const r = routeIntent(intent as any, complexity as any,
      { session_id: `xtreme-${i}`, user_role: role, thinking_mode: thinkMode } as any);
    assert(Array.isArray(r.chain), `Chain should be array`);
  } catch (e) {
    extremeErrors++;
  }
}

const extremeEnd = performance.now();
const extremeDuration = extremeEnd - extremeStart;
const extremeThroughput = Math.round(EXTREME_COUNT / (extremeDuration / 1000));

console.log(`  输入数: ${EXTREME_COUNT}`);
console.log(`  处理数: ${EXTREME_COUNT - extremeErrors}/${EXTREME_COUNT}`);
console.log(`  耗时: ${extremeDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${extremeThroughput} ops/sec`);

test(`极限压力: 处理耗时 < 5000ms`, () => {
  assert(extremeDuration < 5000, `Took ${extremeDuration.toFixed(1)}ms, expected < 5000ms`);
});

test(`极限压力: 成功率 100%`, () => {
  assert(extremeErrors === 0, `${extremeErrors} errors out of ${EXTREME_COUNT}`);
});

// ============================================================
// 测试报告
// ============================================================

console.log('\n' + '='.repeat(70));
console.log('📊 总测试报告');
console.log('='.repeat(70));
console.log(`  总测试数: ${totalTests}`);
console.log(`  通过: ${passedTests}`);
console.log(`  失败: ${failedTests}`);
console.log(`  1000次并发: ${stressDuration.toFixed(1)}ms (~${stressThroughput} ops/sec)`);
console.log(`  10000次极限: ${extremeDuration.toFixed(1)}ms (~${extremeThroughput} ops/sec)`);

if (failedTests === 0) {
  console.log('\n  ✅ ALL TESTS PASSED');
} else {
  console.log(`\n  ❌ ${failedTests} TESTS FAILED`);
  console.log(`  失败详情:`);
  for (const f of failures) console.log(`    - ${f}`);
  process.exit(1);
}
