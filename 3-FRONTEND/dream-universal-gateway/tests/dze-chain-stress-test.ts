/**
 * D/Z/E 思维链 + 步进确认机制 压力测试
 *
 * 测试场景:
 * 1. D/Z/E 链路定义验证
 * 2. 步进确认机制 - requiresStepConfirmation
 * 3. 用户确认解析 - parseUserConfirmation
 * 4. 多场景模拟 - 完整流程
 * 5. 并发压力测试
 *
 * 运行: npx tsx tests/dze-chain-stress-test.ts
 */

import {
  CHAIN_STEPS,
  requiresStepConfirmation,
  isExecutionChainStep,
  getConfirmationSteps,
  getNextConfirmationStep,
  generateStepConfirmationPrompt,
  parseUserConfirmation,
  routeIntent,
} from '../src/lib/intent';

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

function assertContains(a: unknown[], b: unknown, msg: string) {
  if (!a.includes(b)) {
    throw new Error(`${msg}: expected [${a.join(', ')}] to contain ${b}`);
  }
}

// ============================================================
// Test Suite 1: D/Z/E 链路定义验证
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 1: D/Z/E 链路定义验证');
console.log('='.repeat(60));

// D系列验证
test('D1_investigator 定义正确', () => {
  const d1 = CHAIN_STEPS['D1_investigator'];
  assert(!!d1, 'D1 should be defined');
  assertEqual(d1.label, 'D1深度调研', 'Wrong label');
  assertEqual(d1.icon, '🔍', 'Wrong icon');
  assertEqual(d1.credits, 50, 'Wrong credits');
  assertEqual(d1.chain, 'D', 'Should be D chain');
});

test('D2_analyst 定义正确', () => {
  const d2 = CHAIN_STEPS['D2_analyst'];
  assert(!!d2, 'D2 should be defined');
  assertEqual(d2.label, 'D2分析诊断', 'Wrong label');
  assertEqual(d2.credits, 80, 'Wrong credits');
  assertEqual(d2.chain, 'D', 'Should be D chain');
});

test('D3_deducer 定义正确', () => {
  const d3 = CHAIN_STEPS['D3_deducer'];
  assert(!!d3, 'D3 should be defined');
  assertEqual(d3.label, 'D3推演验证', 'Wrong label');
  assertEqual(d3.credits, 100, 'Wrong credits');
  assertEqual(d3.chain, 'D', 'Should be D chain');
});

test('D4_spec_author 定义正确', () => {
  const d4 = CHAIN_STEPS['D4_spec_author'];
  assert(!!d4, 'D4 should be defined');
  assertEqual(d4.label, 'D4-Spec合成', 'Wrong label');
  assertEqual(d4.credits, 120, 'Wrong credits');
  assertEqual(d4.chain, 'D', 'Should be D chain');
});

// Z系列验证
test('Z1_code_scanner 定义正确', () => {
  const z1 = CHAIN_STEPS['Z1_code_scanner'];
  assert(!!z1, 'Z1 should be defined');
  assertEqual(z1.label, 'Z1代码扫描', 'Wrong label');
  assertEqual(z1.credits, 60, 'Wrong credits');
  assertEqual(z1.chain, 'Z', 'Should be Z chain');
});

test('Z2_boundary_divider 定义正确', () => {
  const z2 = CHAIN_STEPS['Z2_boundary_divider'];
  assert(!!z2, 'Z2 should be defined');
  assertEqual(z2.label, 'Z2范围划分', 'Wrong label');
  assertEqual(z2.credits, 70, 'Wrong credits');
  assertEqual(z2.chain, 'Z', 'Should be Z chain');
});

test('Z3_path_planner 定义正确', () => {
  const z3 = CHAIN_STEPS['Z3_path_planner'];
  assert(!!z3, 'Z3 should be defined');
  assertEqual(z3.label, 'Z3路径设计', 'Wrong label');
  assertEqual(z3.credits, 80, 'Wrong credits');
  assertEqual(z3.chain, 'Z', 'Should be Z chain');
});

test('Z4_acceptance_designer 定义正确', () => {
  const z4 = CHAIN_STEPS['Z4_acceptance_designer'];
  assert(!!z4, 'Z4 should be defined');
  assertEqual(z4.label, 'Z4验收方案', 'Wrong label');
  assertEqual(z4.credits, 90, 'Wrong credits');
  assertEqual(z4.chain, 'Z', 'Should be Z chain');
});

// E系列验证
test('E1_task_executor 定义正确', () => {
  const e1 = CHAIN_STEPS['E1_task_executor'];
  assert(!!e1, 'E1 should be defined');
  assertEqual(e1.label, 'E1任务执行', 'Wrong label');
  assertEqual(e1.credits, 100, 'Wrong credits');
  assertEqual(e1.chain, 'E', 'Should be E chain');
});

test('E2_tester 定义正确', () => {
  const e2 = CHAIN_STEPS['E2_tester'];
  assert(!!e2, 'E2 should be defined');
  assertEqual(e2.label, 'E2测试验证', 'Wrong label');
  assertEqual(e2.credits, 80, 'Wrong credits');
  assertEqual(e2.chain, 'E', 'Should be E chain');
});

test('E3_deployer 定义正确', () => {
  const e3 = CHAIN_STEPS['E3_deployer'];
  assert(!!e3, 'E3 should be defined');
  assertEqual(e3.label, 'E3部署交付', 'Wrong label');
  assertEqual(e3.credits, 60, 'Wrong credits');
  assertEqual(e3.chain, 'E', 'Should be E chain');
});

// ============================================================
// Test Suite 2: 步进确认机制 - requiresStepConfirmation
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 2: 步进确认机制验证');
console.log('='.repeat(60));

test('D系列链路需要确认', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  assert(requiresStepConfirmation(chain) === true, 'D chain should require confirmation');
});

test('Z系列链路需要确认', () => {
  const chain = ['Z1_code_scanner', 'Z2_boundary_divider', 'Z3_path_planner', 'Z4_acceptance_designer'];
  assert(requiresStepConfirmation(chain) === true, 'Z chain should require confirmation');
});

test('E系列链路不需要确认', () => {
  const chain = ['E1_task_executor', 'E2_tester', 'E3_deployer'];
  assert(requiresStepConfirmation(chain) === false, 'E chain should not require confirmation');
});

test('D+Z+E混合链路需要确认', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'Z1_code_scanner', 'E1_task_executor'];
  assert(requiresStepConfirmation(chain) === true, 'Mixed chain should require confirmation');
});

test('纯A系列链路不需要确认', () => {
  const chain = ['A1_research', 'A2_analysis', 'A3_simulation'];
  assert(requiresStepConfirmation(chain) === false, 'A chain should not require confirmation');
});

test('market_data 链路不需要确认', () => {
  const chain = ['knowledge_base', 'market_data'];
  assert(requiresStepConfirmation(chain) === false, 'market_data chain should not require confirmation');
});

// ============================================================
// Test Suite 3: isExecutionChainStep
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 3: 执行链判别');
console.log('='.repeat(60));

test('E1_task_executor 是执行链', () => {
  assert(isExecutionChainStep('E1_task_executor') === true, 'E1 should be execution chain');
});

test('E2_tester 是执行链', () => {
  assert(isExecutionChainStep('E2_tester') === true, 'E2 should be execution chain');
});

test('E3_deployer 是执行链', () => {
  assert(isExecutionChainStep('E3_deployer') === true, 'E3 should be execution chain');
});

test('D1_investigator 不是执行链', () => {
  assert(isExecutionChainStep('D1_investigator') === false, 'D1 should not be execution chain');
});

test('Z1_code_scanner 不是执行链', () => {
  assert(isExecutionChainStep('Z1_code_scanner') === false, 'Z1 should not be execution chain');
});

test('market_data 不是执行链', () => {
  assert(isExecutionChainStep('market_data') === false, 'market_data should not be execution chain');
});

// ============================================================
// Test Suite 4: getConfirmationSteps
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 4: 获取需确认步骤');
console.log('='.repeat(60));

test('D链路返回所有D步骤', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const confirmSteps = getConfirmationSteps(chain);
  assertEqual(confirmSteps.length, 4, 'Should have 4 confirmation steps');
  assertEqual(confirmSteps[0], 'D1_investigator', 'First should be D1');
});

test('D+Z+E混合链路只返回D和Z步骤', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'Z1_code_scanner', 'E1_task_executor', 'E2_tester'];
  const confirmSteps = getConfirmationSteps(chain);
  assertEqual(confirmSteps.length, 3, 'Should have 3 confirmation steps (2 D + 1 Z)');
  assert(!confirmSteps.includes('E1_task_executor'), 'E1 should not be in confirmation steps');
  assert(!confirmSteps.includes('E2_tester'), 'E2 should not be in confirmation steps');
});

test('纯E链路返回空', () => {
  const chain = ['E1_task_executor', 'E2_tester', 'E3_deployer'];
  const confirmSteps = getConfirmationSteps(chain);
  assertEqual(confirmSteps.length, 0, 'E chain should return empty');
});

// ============================================================
// Test Suite 5: getNextConfirmationStep
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 5: 获取下一个确认步骤');
console.log('='.repeat(60));

test('D1后下一个确认步骤是D2', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const nextIdx = getNextConfirmationStep(chain, 0);
  assertEqual(nextIdx, 1, 'Next confirmation step should be index 1 (D2)');
});

test('D2后下一个确认步骤是D3', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const nextIdx = getNextConfirmationStep(chain, 1);
  assertEqual(nextIdx, 2, 'Next confirmation step should be index 2 (D3)');
});

test('D4后没有更多确认步骤', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const nextIdx = getNextConfirmationStep(chain, 3);
  assertEqual(nextIdx, -1, 'No more confirmation steps after D4');
});

test('D+Z+E混合链中Z步骤正确识别', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'Z1_code_scanner', 'E1_task_executor', 'Z2_boundary_divider'];
  const nextIdx = getNextConfirmationStep(chain, 2); // After Z1
  assertEqual(nextIdx, 4, 'Next confirmation step should be Z2 at index 4');
});

// ============================================================
// Test Suite 6: parseUserConfirmation
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 6: 用户确认解析');
console.log('='.repeat(60));

test('"1" → continue', () => {
  assertEqual(parseUserConfirmation('1'), 'continue', '1 should be continue');
});

test('"继续" → continue', () => {
  assertEqual(parseUserConfirmation('继续'), 'continue', '继续 should be continue');
});

test('"下一步" → continue', () => {
  assertEqual(parseUserConfirmation('下一步'), 'continue', '下一步 should be continue');
});

test('"2" → finalize', () => {
  assertEqual(parseUserConfirmation('2'), 'finalize', '2 should be finalize');
});

test('"落地" → finalize', () => {
  assertEqual(parseUserConfirmation('落地'), 'finalize', '落地 should be finalize');
});

test('"直接落地" → finalize', () => {
  assertEqual(parseUserConfirmation('直接落地'), 'finalize', '直接落地 should be finalize');
});

test('"3" → skip', () => {
  assertEqual(parseUserConfirmation('3'), 'skip', '3 should be skip');
});

test('"跳过" → skip', () => {
  assertEqual(parseUserConfirmation('跳过'), 'skip', '跳过 should be skip');
});

test('"跳过剩余步骤" → skip', () => {
  assertEqual(parseUserConfirmation('跳过剩余步骤'), 'skip', '跳过剩余步骤 should be skip');
});

test('未知输入 → unknown', () => {
  assertEqual(parseUserConfirmation('随便说'), 'unknown', 'Unknown input should return unknown');
});

test('空字符串 → unknown', () => {
  assertEqual(parseUserConfirmation(''), 'unknown', 'Empty should return unknown');
});

test('大小写不敏感', () => {
  assertEqual(parseUserConfirmation('CONTINUE'), 'continue', 'Uppercase should be handled');
});

// ============================================================
// Test Suite 7: generateStepConfirmationPrompt
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 7: 确认提示语生成');
console.log('='.repeat(60));

test('中文确认提示包含D1和D2标签', () => {
  const prompt = generateStepConfirmationPrompt('D1_investigator', 'D2_analyst', 'zh');
  assert(prompt.includes('D1深度调研'), 'Should include D1 label');
  assert(prompt.includes('D2分析诊断'), 'Should include D2 label');
  assert(prompt.includes('(1)'), 'Should include option 1');
  assert(prompt.includes('(2)'), 'Should include option 2');
});

test('英文确认提示包含步骤标签', () => {
  const prompt = generateStepConfirmationPrompt('D1_investigator', 'D2_analyst', 'en');
  assert(prompt.includes('Proceed'), 'Should include Proceed');
  assert(prompt.includes('Finalize'), 'Should include Finalize');
});

test('最后一步提示落地选项', () => {
  const prompt = generateStepConfirmationPrompt('D4_spec_author', null, 'zh');
  assert(prompt.includes('落地'), 'Should mention finalize');
  assert(!prompt.includes('(3)'), 'Should not include skip option');
});

// ============================================================
// Test Suite 8: triple_chain 路由
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 8: triple_chain 路由验证');
console.log('='.repeat(60));

test('triple_chain FREE模式路由到D1-D4', () => {
  const routing = routeIntent('triple_chain', 'moderate', {
    session_id: 'test',
    user_role: 'FREE',
    thinking_mode: 'quick',
    message_history: ['测试消息'],
  });
  assertContains(routing.chain, 'D1_investigator', 'Should include D1');
  assertContains(routing.chain, 'D2_analyst', 'Should include D2');
  assertContains(routing.chain, 'D3_deducer', 'Should include D3');
  assertContains(routing.chain, 'D4_spec_author', 'Should include D4');
});

test('triple_chain PRO deep模式路由到完整链路', () => {
  const routing = routeIntent('triple_chain', 'moderate', {
    session_id: 'test',
    user_role: 'PRO',
    thinking_mode: 'deep',
    message_history: ['测试消息'],
  });
  // 完整链路包含 D + Z + E
  assertContains(routing.chain, 'D1_investigator', 'Should include D1');
  assertContains(routing.chain, 'Z1_code_scanner', 'Should include Z1');
  assertContains(routing.chain, 'E1_task_executor', 'Should include E1');
  assertEqual(routing.chain.length, 11, 'Full chain should have 11 steps');
});

test('triple_chain 需要确认', () => {
  const routing = routeIntent('triple_chain', 'moderate', {
    session_id: 'test',
    user_role: 'FREE',
    thinking_mode: 'quick',
    message_history: ['测试消息'],
  });
  assertEqual(routing.requires_confirmation, true, 'triple_chain should require confirmation');
});

// ============================================================
// Test Suite 9: deep_analysis 路由到D链
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 9: deep_analysis 路由到 D 链验证');
console.log('='.repeat(60));

test('deep_analysis FREE路由到D1-D2', () => {
  const routing = routeIntent('deep_analysis', 'moderate', {
    session_id: 'test',
    user_role: 'FREE',
    thinking_mode: 'quick',
    message_history: ['分析BTC'],
  });
  assertContains(routing.chain, 'D1_investigator', 'Should include D1');
  assertContains(routing.chain, 'D2_analyst', 'Should include D2');
  assert(!routing.chain.includes('D3_deducer'), 'FREE mode should not include D3');
});

test('deep_analysis PRO deep路由到完整D链', () => {
  const routing = routeIntent('deep_analysis', 'moderate', {
    session_id: 'test',
    user_role: 'PRO',
    thinking_mode: 'deep',
    message_history: ['深度分析BTC'],
  });
  assertContains(routing.chain, 'D1_investigator', 'Should include D1');
  assertContains(routing.chain, 'D2_analyst', 'Should include D2');
  assertContains(routing.chain, 'D3_deducer', 'Should include D3');
  assertContains(routing.chain, 'D4_spec_author', 'Should include D4');
});

test('deep_analysis 需要确认', () => {
  const routing = routeIntent('deep_analysis', 'moderate', {
    session_id: 'test',
    user_role: 'FREE',
    thinking_mode: 'quick',
    message_history: ['分析ETH'],
  });
  assertEqual(routing.requires_confirmation, true, 'deep_analysis should require confirmation');
});

// ============================================================
// Test Suite 10: 场景模拟 - 完整D链流程
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 10: 场景模拟 - D链完整流程');
console.log('='.repeat(60));

test('场景1: 用户选择继续到下一步', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const confirmation = parseUserConfirmation('继续');

  assertEqual(confirmation, 'continue', 'Should be continue');
  if (confirmation === 'continue') {
    // 模拟步进
    const currentIdx = 0; // D1
    const nextIdx = getNextConfirmationStep(chain, currentIdx);
    assertEqual(nextIdx, 1, 'Next step should be D2');
  }
});

test('场景2: 用户选择直接落地D2后', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const confirmation = parseUserConfirmation('落地');

  assertEqual(confirmation, 'finalize', 'Should be finalize');
});

test('场景3: 用户选择跳过剩余步骤', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'];
  const confirmation = parseUserConfirmation('跳过');

  assertEqual(confirmation, 'skip', 'Should be skip');
});

test('场景4: D+Z+E混合链中E链不需确认', () => {
  const chain = ['D1_investigator', 'D2_analyst', 'Z1_code_scanner', 'E1_task_executor', 'E2_tester'];

  // 第一步D1需要确认
  const nextD = getNextConfirmationStep(chain, 0);
  assertEqual(nextD, 1, 'D1之后是D2');

  // D2之后是Z1
  const nextZ = getNextConfirmationStep(chain, 1);
  assertEqual(nextZ, 2, 'D2之后是Z1');

  // Z1之后是E1，但E1不需要确认
  const nextE = getNextConfirmationStep(chain, 2);
  assertEqual(nextE, -1, 'E链不需要确认步骤');

  // 但E链应该继续执行
  assert(isExecutionChainStep('E1_task_executor'), 'E1 is execution chain');
  assert(isExecutionChainStep('E2_tester'), 'E2 is execution chain');
});

// ============================================================
// Test Suite 11: 并发压力测试
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 11: 并发压力测试');
console.log('='.repeat(60));

const STRESS_COUNT = 1000;
const stressStart = performance.now();

for (let i = 0; i < STRESS_COUNT; i++) {
  // 测试各种链的确认判断
  const chains = [
    ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'],
    ['Z1_code_scanner', 'Z2_boundary_divider', 'Z3_path_planner', 'Z4_acceptance_designer'],
    ['E1_task_executor', 'E2_tester', 'E3_deployer'],
    ['D1_investigator', 'D2_analyst', 'Z1_code_scanner', 'E1_task_executor'],
    ['A1_research', 'A2_analysis', 'A3_simulation'],
  ];

  const chain = chains[i % chains.length];
  requiresStepConfirmation(chain);
  isExecutionChainStep(chain[0]);
  getConfirmationSteps(chain);
  parseUserConfirmation(['1', '2', '3', '继续', '落地', '跳过'][i % 6]);
  generateStepConfirmationPrompt(chain[0], chain[1] || null, 'zh');
}

const stressEnd = performance.now();
const stressDuration = stressEnd - stressStart;
const throughput = Math.round(STRESS_COUNT / (stressDuration / 1000));

console.log(`  输入数: ${STRESS_COUNT}`);
console.log(`  耗时: ${stressDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${throughput} ops/sec`);

test(`1000次操作 < 200ms`, () => {
  assert(stressDuration < 200, `Took ${stressDuration.toFixed(1)}ms, expected < 200ms`);
});

test(`吞吐量 > 5000 ops/sec`, () => {
  assert(throughput > 5000, `Throughput ${throughput} ops/sec, expected > 5000`);
});

// 极限压力
const EXTREME_COUNT = 10000;
const extremeStart = performance.now();

for (let i = 0; i < EXTREME_COUNT; i++) {
  const chains = [
    ['D1_investigator', 'D2_analyst', 'D3_deducer', 'D4_spec_author'],
    ['Z1_code_scanner', 'Z2_boundary_divider', 'Z3_path_planner', 'Z4_acceptance_designer'],
    ['E1_task_executor', 'E2_tester', 'E3_deployer'],
  ];
  const chain = chains[i % chains.length];
  requiresStepConfirmation(chain);
  getConfirmationSteps(chain);
}

const extremeEnd = performance.now();
const extremeDuration = extremeEnd - extremeStart;
const extremeThroughput = Math.round(EXTREME_COUNT / (extremeDuration / 1000));

console.log(`\n  极限压力: ${EXTREME_COUNT}次`);
console.log(`  耗时: ${extremeDuration.toFixed(1)}ms`);
console.log(`  吞吐量: ~${extremeThroughput} ops/sec`);

test(`10000次极限压力 < 500ms`, () => {
  assert(extremeDuration < 500, `Took ${extremeDuration.toFixed(1)}ms, expected < 500ms`);
});

// ============================================================
// Test Suite 12: 知识库内容验证
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('Test Suite 12: 知识库文件验证');
console.log('='.repeat(60));

test('知识库目录存在', () => {
  const fs = require('fs');
  const path = require('path');
  // 知识库在项目根目录
  const kbPath = path.resolve(__dirname, '..', '..', '..', '2-KNOWLEDGE');
  assert(fs.existsSync(kbPath), `Knowledge base should exist at ${kbPath}`);
});

test('三链开发目录存在', () => {
  const fs = require('fs');
  const path = require('path');
  // 三链开发在项目根目录
  const chainPath = path.resolve(__dirname, '..', '..', '..', '3-CHAIN-DEVELOPMENT');
  assert(fs.existsSync(chainPath), `Chain development should exist at ${chainPath}`);
});

// ============================================================
// 测试报告
// ============================================================

console.log('\n' + '='.repeat(60));
console.log('📊 D/Z/E 思维链测试报告');
console.log('='.repeat(60));
console.log(`  总测试数: ${totalTests}`);
console.log(`  通过: ${passedTests}`);
console.log(`  失败: ${failedTests}`);
console.log(`  1000次并发: ${stressDuration.toFixed(1)}ms (~${throughput} ops/sec)`);
console.log(`  10000次极限: ${extremeDuration.toFixed(1)}ms (~${extremeThroughput} ops/sec)`);

if (failedTests === 0) {
  console.log('\n  ✅ ALL DZE CHAIN TESTS PASSED');
} else {
  console.log(`\n  ❌ ${failedTests} DZE CHAIN TESTS FAILED`);
  process.exit(1);
}
