/**
 * intent-schema-test.ts — P1 验收：意图正典与别名映射无损性
 * 运行：npx tsx scripts/intent-schema-test.ts
 * Z4 验收 L0 项：别名→正典→别名双向无损（3 套映射表全量）
 */
import {
  INTENT_CANON,
  IntentCanon,
  isIntentCanon,
  intentLoop,
  gateAllows,
  aliasToCanon,
  canonToPlanner,
} from '../src/lib/intent/intent-schema';

let pass = 0;
let fail = 0;
function check(name: string, ok: boolean, detail = '') {
  if (ok) { pass++; }
  else { fail++; console.error(`  ✗ ${name} ${detail}`); }
}

// ── 1. 正典完整性 ──
check('正典数量 = 35', INTENT_CANON.length === 35, `实际 ${INTENT_CANON.length}`);
check('正典无重复', new Set(INTENT_CANON).size === INTENT_CANON.length);
check('每个正典有环归属', INTENT_CANON.every(i => typeof intentLoop(i) === 'string'));

// ── 2. planner 视图双向无损（11 型）──
const PLANNER_VIEW = [
  'market_query', 'deep_analysis', 'scenario_sim', 'strategy_verify',
  'execute_trade', 'risk_alert', 'simple_qa', 'system_config',
  'credits_query', 'artifact_query', 'command',
];
check('planner 视图 = 11 型', PLANNER_VIEW.length === 11);
for (const alias of PLANNER_VIEW) {
  const canon = aliasToCanon(alias);
  check(`planner→canon: ${alias}`, canon !== null, `映射缺失`);
  if (canon) {
    const back = canonToPlanner(canon);
    check(`canon→planner 回转: ${alias}`, back === alias, `回转得 ${back}`);
  }
}

// ── 3. 关键分歧修复点 ──
check('risk_alert → risk_alert_response', aliasToCanon('risk_alert') === 'risk_alert_response');
check('risk_alert_response → risk_alert (planner)', canonToPlanner('risk_alert_response') === 'risk_alert');

// ── 4. 正典直通（chat/fallback 视图恒等）──
for (const c of INTENT_CANON) {
  check(`恒等映射: ${c}`, aliasToCanon(c) === c);
}

// ── 5. 未知别名兜底 ──
check('未知别名 → null', aliasToCanon('totally_unknown_intent_xyz') === null);
check('planner 域外正典 → null', canonToPlanner('trend_analysis' as IntentCanon) === null);
check('isIntentCanon 判定', isIntentCanon('deep_analysis') && !isIntentCanon('risk_alert'));

// ── 6. 门禁矩阵合理性 ──
check('ADMIN 全放行', INTENT_CANON.every(i => gateAllows('ADMIN', i)));
check('FREE 禁 execute_trade', !gateAllows('FREE', 'execute_trade'));
check('FREE 禁 system_config', !gateAllows('FREE', 'system_config'));
check('FREE 禁 developer', !gateAllows('FREE', 'developer'));
check('PRO 放行 execute_trade? 否', !gateAllows('PRO', 'execute_trade'));
check('FREE 放行 market_query', gateAllows('FREE', 'market_query'));
check('FREE 禁 triple_chain', !gateAllows('FREE', 'triple_chain'));

// ── 结果 ──
console.log(`\n[P1 schema 测试] pass=${pass} fail=${fail}`);
process.exit(fail > 0 ? 1 : 0);
