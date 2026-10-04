/**
 * Intent Pipeline Harness — 统一意图识别管线离线黄金集测试
 * PROP-20260828B · Phase 2 验收
 *
 * 运行: npx tsx tests/intent/harness.ts
 *
 * 覆盖范围（零 LLM 路径）：
 *   ① 意图正典不变量（intent-schema.ts）：35 型 SSoT、环归属、别名映射、角色门禁
 *   ② 命令快路径（command-fastpath.ts）：/斜杠 + 中文命令词典
 *   ③ 规则引擎兜底（fallback-engine.ts matchRuleEngine）：硬编码规则 + 组合词
 *   ④ 默认兜底（fallback-engine.ts defaultFallback）
 *   ⑤ FC 参数修复级联（intent-args-repair.ts）：异常 LLM 输出修复
 *   ⑥ 影子探针常量（shadow-probe.ts）：预算/上限不变量
 *
 * 注意：L2 FC 结构化识别依赖 LLM，离线时跳过（method='rule'）。
 *      记忆双写关闭（recordMemory: false）避免污染 intent-memory。
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

import {
  INTENT_CANON,
  LEGACY_VIEW,
  isIntentCanon,
  intentLoop,
  aliasToCanon,
  canonToPlanner,
  canonToLegacy,
  gateAllows,
} from '../../src/lib/intent/intent-schema';
import { matchCommandFastpath } from '../../src/lib/intent/command-fastpath';
import { repairIntentArgs } from '../../src/lib/intent/intent-args-repair';
import { recognizeIntentUnified } from '../../src/lib/intent/intent-unified';
import { SHADOW_BUDGET, SHADOW_MAX_TOKENS } from '../../src/lib/intent/shadow-probe';

// ============================================================
// 测试框架
// ============================================================

interface TestResult {
  name: string;
  pass: boolean;
  detail?: string;
}

const results: TestResult[] = [];

function assertEq<T>(name: string, actual: T, expected: T, detail = ''): void {
  const pass = actual === expected;
  results.push({
    name,
    pass,
    detail: pass ? undefined : `expected=${JSON.stringify(expected)} actual=${JSON.stringify(actual)} ${detail}`,
  });
}

function assertTrue(name: string, cond: boolean, detail = ''): void {
  results.push({ name, pass: cond, detail: cond ? undefined : detail });
}

function assertIncludes(name: string, arr: readonly string[], item: string, detail = ''): void {
  const pass = (arr as readonly string[]).includes(item);
  results.push({ name, pass, detail: pass ? undefined : `${item} not in array ${detail}` });
}

// ============================================================
// ① 意图正典不变量（intent-schema.ts）
// ============================================================

function testSchemaInvariants(): void {
  // 35 型正典
  assertEq('schema: INTENT_CANON 35 型', INTENT_CANON.length, 35);
  // 15 型 legacy 视图
  assertEq('schema: LEGACY_VIEW 15 型', LEGACY_VIEW.length, 15);

  // isIntentCanon
  assertTrue('schema: isIntentCanon(market_query)=true', isIntentCanon('market_query'));
  assertTrue('schema: isIntentCanon(execute_trade)=true', isIntentCanon('execute_trade'));
  assertEq('schema: isIntentCanon(unknown)=false', isIntentCanon('unknown' as never) as unknown as string, false);

  // 环归属
  assertEq('schema: intentLoop(execute_trade)=execution', intentLoop('execute_trade'), 'execution');
  assertEq('schema: intentLoop(system_config)=governance', intentLoop('system_config'), 'governance');
  assertEq('schema: intentLoop(market_query)=intelligence', intentLoop('market_query'), 'intelligence');
  assertEq('schema: intentLoop(simple_qa)=general', intentLoop('simple_qa'), 'general');
  assertEq('schema: intentLoop(developer)=governance', intentLoop('developer'), 'governance');

  // 别名映射（planner 视图分歧点 risk_alert → risk_alert_response）
  assertEq('schema: aliasToCanon(risk_alert)=risk_alert_response', aliasToCanon('risk_alert'), 'risk_alert_response');
  assertEq('schema: aliasToCanon(market_query)=market_query', aliasToCanon('market_query'), 'market_query');
  assertEq('schema: aliasToCanon(unknown)=null', aliasToCanon('unknown'), null);

  // 正典 → planner 视图
  assertEq('schema: canonToPlanner(risk_alert_response)=risk_alert', canonToPlanner('risk_alert_response'), 'risk_alert');
  assertEq('schema: canonToPlanner(market_query)=market_query', canonToPlanner('market_query'), 'market_query');
  // 多场景意图不在 planner 域内
  assertEq('schema: canonToPlanner(asset_comparison)=null', canonToPlanner('asset_comparison'), null);

  // 正典 → legacy 视图（多场景归并到 deep_analysis）
  assertEq('schema: canonToLegacy(market_query)=market_query', canonToLegacy('market_query'), 'market_query');
  assertEq('schema: canonToLegacy(asset_comparison)=deep_analysis', canonToLegacy('asset_comparison'), 'deep_analysis');
  assertEq('schema: canonToLegacy(concept_explain)=simple_qa', canonToLegacy('concept_explain'), 'simple_qa');
  assertEq('schema: canonToLegacy(backtest_help)=strategy_verify', canonToLegacy('backtest_help'), 'strategy_verify');

  // 角色门禁（草案：FREE 可查询，不可执行交易/配置/开发）
  assertTrue('schema: gateAllows(FREE, market_query)=true', gateAllows('FREE', 'market_query'));
  assertEq('schema: gateAllows(FREE, execute_trade)=false', gateAllows('FREE', 'execute_trade') as unknown as string, false);
  assertEq('schema: gateAllows(FREE, system_config)=false', gateAllows('FREE', 'system_config') as unknown as string, false);
  assertTrue('schema: gateAllows(ADMIN, execute_trade)=true', gateAllows('ADMIN', 'execute_trade'));
  assertTrue('schema: gateAllows(PRO, strategy_verify)=true', gateAllows('PRO', 'strategy_verify'));
}

// ============================================================
// ⑤ FC 参数修复级联（intent-args-repair.ts）
// ============================================================

function testRepairIntentArgs(): void {
  // 正常输入：透传 + symbol 大写规范化（complexity 必须给定，否则触发 complexity_default 修复）
  const r1 = repairIntentArgs({ intent: 'market_query', confidence: 0.9, complexity: 'moderate', entities: { symbol: 'btc' } });
  assertEq('repair: 正常输入 intent', r1.intent, 'market_query');
  assertEq('repair: 正常输入 confidence', r1.confidence, 0.9);
  assertEq('repair: symbol 大写', r1.entities.symbol, 'BTC');
  assertEq('repair: 正常输入无修复动作', r1.repairs.length, 0);

  // 别名修复：risk_alert → risk_alert_response
  const r2 = repairIntentArgs({ intent: 'risk_alert', confidence: 1.5 });
  assertEq('repair: 别名 intent=risk_alert_response', r2.intent, 'risk_alert_response');
  assertEq('repair: confidence 钳制 1.5→1.0', r2.confidence, 1.0);
  assertTrue('repair: 记录 intent_alias', r2.repairs.includes('intent_alias:risk_alert->risk_alert_response'));
  assertTrue('repair: 记录 confidence_clamped', r2.repairs.includes('confidence_clamped'));

  // 空对象：intent 缺失 + confidence 默认
  const r3 = repairIntentArgs({});
  assertEq('repair: 空对象 intent=null', r3.intent, null);
  assertEq('repair: confidence 默认 0.6', r3.confidence, 0.6);
  assertTrue('repair: 记录 intent_missing', r3.repairs.includes('intent_missing'));
  assertTrue('repair: 记录 confidence_missing_default_0.6', r3.repairs.includes('confidence_missing_default_0.6'));

  // 未知意图
  const r4 = repairIntentArgs({ intent: 'unknown_xyz' });
  assertEq('repair: 未知意图 intent=null', r4.intent, null);
  assertTrue('repair: 记录 intent_unknown:unknown_xyz', r4.repairs.includes('intent_unknown:unknown_xyz'));

  // 非对象输入
  const r5 = repairIntentArgs('not_an_object');
  assertEq('repair: 非对象 intent=null', r5.intent, null);
  assertTrue('repair: 记录 args_not_object', r5.repairs.includes('args_not_object'));
}

// ============================================================
// ⑥ 影子探针常量（shadow-probe.ts）
// ============================================================

function testShadowConstants(): void {
  assertEq('shadow: SHADOW_BUDGET=200', SHADOW_BUDGET, 200);
  assertEq('shadow: SHADOW_MAX_TOKENS=150', SHADOW_MAX_TOKENS, 150);
}

// ============================================================
// ②③④ 黄金集：消息 → 意图（recognizeIntentUnified, method='rule'）
// ============================================================

interface GoldenCase {
  id: number;
  q: string;
  expected: string;
  level: string;
  note: string;
}

async function runGoldenSet(): Promise<void> {
  const goldenPath = path.resolve(__dirname, 'golden-set.json');
  const golden = JSON.parse(fs.readFileSync(goldenPath, 'utf-8')) as { cases: GoldenCase[] };

  for (const c of golden.cases) {
    const res = await recognizeIntentUnified(c.q, undefined, {
      method: 'rule',      // 离线：跳过 LLM FC 路径
      recordMemory: false, // 测试不污染 intent-memory
    });
    const pass = res.intent === c.expected;
    results.push({
      name: `golden #${c.id} [${c.level}] "${c.q}" → ${c.expected}`,
      pass,
      detail: pass
        ? undefined
        : `expected=${c.expected} actual=${res.intent} method=${res.method} reason=${res.reasoning} ${c.note}`,
    });
  }
}

// ============================================================
// ② 命令快路径单元（matchCommandFastpath 直接调用）
// ============================================================

function testCommandFastpathUnit(): void {
  const slash = matchCommandFastpath('/help');
  assertTrue('cmd: /help 命中', slash !== null);
  assertEq('cmd: /help intent=command', slash?.intent ?? '', 'command');
  assertEq('cmd: /help command_name=help', slash?.entities.command_name ?? '', 'help');

  const slashArgs = matchCommandFastpath('/start trading');
  assertTrue('cmd: /start trading 命中', slashArgs !== null);
  assertEq('cmd: /start trading command_name=start', slashArgs?.entities.command_name ?? '', 'start');
  assertEq('cmd: /start trading command_args=trading', slashArgs?.entities.command_args ?? '', 'trading');

  const cn = matchCommandFastpath('查看状态');
  assertTrue('cmd: 查看状态 命中', cn !== null);
  assertEq('cmd: 查看状态 command_name=status', cn?.entities.command_name ?? '', 'status');

  const notCmd = matchCommandFastpath('BTC 现在多少钱');
  assertEq('cmd: 非命令返回 null', notCmd === null ? 'null' : 'not-null', 'null');
}

// ============================================================
// 主入口
// ============================================================

async function main(): Promise<void> {
  console.log('=== Intent Pipeline Harness (offline, method=rule) ===\n');

  // 静态测试（无异步）
  console.log('[1/5] Schema invariants (intent-schema.ts)');
  testSchemaInvariants();

  console.log('[2/5] Command fastpath unit (command-fastpath.ts)');
  testCommandFastpathUnit();

  console.log('[3/5] FC args repair cascade (intent-args-repair.ts)');
  testRepairIntentArgs();

  console.log('[4/5] Shadow probe constants (shadow-probe.ts)');
  testShadowConstants();

  console.log('[5/5] Golden set: message → intent (recognizeIntentUnified, method=rule)');
  await runGoldenSet();

  // 汇总
  const total = results.length;
  const passed = results.filter(r => r.pass).length;
  const failed = total - passed;
  const passRate = total > 0 ? ((passed / total) * 100).toFixed(1) : '0.0';

  console.log('\n=== 失败详情 ===');
  const failures = results.filter(r => !r.pass);
  if (failures.length === 0) {
    console.log('  (无失败)');
  } else {
    for (const f of failures) {
      console.log(`  ✗ ${f.name}`);
      if (f.detail) console.log(`      ${f.detail}`);
    }
  }

  console.log('\n=== 汇总 ===');
  console.log(`  TOTAL: ${total}  PASS: ${passed}  FAIL: ${failed}  通过率: ${passRate}%`);
  const acceptance = parseFloat(passRate) >= 90;
  console.log(`  验收门槛 (>=90%): ${acceptance ? 'PASS ✓' : 'FAIL ✗'}`);

  process.exit(acceptance ? 0 : 1);
}

main().catch(e => {
  console.error('Harness 异常退出:', e);
  process.exit(2);
});
