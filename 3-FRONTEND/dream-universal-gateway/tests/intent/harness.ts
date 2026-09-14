/**
 * harness.ts — 意图层黄金集回归 harness（双模）
 * PROP-20260829-C · P1（Z3 §0.3 实现，替代 Z4 0.2 中 vitest 方案——
 * GW 环境未安装 vitest，改用 tsx+node:assert，零新依赖）
 *
 * 模式：
 *   offline（默认）— 纯函数断言：零 LLM、零网络、零记忆写入副作用
 *   live           — 完整管线识别对比（INTENT_HARNESS_MODE=live，需 LLM 端点，影子期用）
 *
 * 运行：npx tsx tests/intent/harness.ts
 *       INTENT_HARNESS_MODE=live npx tsx tests/intent/harness.ts
 *
 * 纪律：offline 模式只调用纯函数（intent-schema / command-fastpath /
 * fallback-engine.detectFollowUp），绝不走 recognizeIntentUnified→finalize，
 * 避免向生产 intent-memory 写入测试数据。
 */
import assert from 'node:assert';
import { readFileSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  INTENT_CANON,
  LEGACY_VIEW,
  IntentCanon,
  IntentLoop,
  intentLoop,
  gateAllows,
  aliasToCanon,
  canonToLegacy,
  canonToPlanner,
} from '../../src/lib/intent/intent-schema';
import { matchCommandFastpath } from '../../src/lib/intent/command-fastpath';
import { detectFollowUp, SessionContext } from '../../src/lib/intent/fallback-engine';

const __dirname = dirname(fileURLToPath(import.meta.url));

interface GoldenCase {
  id: string;
  input: string;
  user_role: 'FREE' | 'PRO' | 'ADMIN';
  expected_canon: IntentCanon;
  expected_legacy: string;
  expected_loop: IntentLoop;
  gate_allowed: boolean;
  tags: string[];
  expected_command_name?: string;
  skip_offline?: boolean;
  context?: SessionContext;
  note?: string;
}

const golden = JSON.parse(readFileSync(join(__dirname, 'golden-set.json'), 'utf8'));
const cases: GoldenCase[] = golden.cases;

let pass = 0;
let fail = 0;
const failures: string[] = [];

function check(label: string, fn: () => void) {
  try {
    fn();
    pass++;
  } catch (e) {
    fail++;
    failures.push(`[${label}] ${(e as Error).message}`);
  }
}

// ============ A. 映射不变式（全 35 正典系统性验证） ============
const LOOPS: IntentLoop[] = ['execution', 'intelligence', 'governance', 'general'];
for (const c of INTENT_CANON) {
  check(`A.legacy:${c}`, () => {
    assert.ok((LEGACY_VIEW as readonly string[]).includes(canonToLegacy(c)),
      `canonToLegacy(${c})=${canonToLegacy(c)} 不在 15 legacy 视图内`);
  });
  check(`A.loop:${c}`, () => {
    assert.ok(LOOPS.includes(intentLoop(c)), `intentLoop(${c})=${intentLoop(c)} 非法`);
  });
  check(`A.alias-identity:${c}`, () => {
    assert.strictEqual(aliasToCanon(c), c, `aliasToCanon(${c}) 应恒等`);
  });
}
check('A.alias:risk_alert→risk_alert_response', () => {
  assert.strictEqual(aliasToCanon('risk_alert'), 'risk_alert_response', 'planner 别名映射断裂');
});
check('A.planner-reverse:risk_alert_response→risk_alert', () => {
  assert.strictEqual(canonToPlanner('risk_alert_response'), 'risk_alert', '反向映射断裂');
});
check('A.alias:unknown→null', () => {
  assert.strictEqual(aliasToCanon('nonexistent_intent_xyz'), null, '未知别名应返回 null');
});

// ============ B. 黄金集自洽性（防黄金集自身写错） ============
for (const gc of cases) {
  check(`B.selfconsist:${gc.id}`, () => {
    assert.strictEqual(canonToLegacy(gc.expected_canon), gc.expected_legacy,
      `${gc.id}: legacy 预期 ${gc.expected_legacy} ≠ 引擎 ${canonToLegacy(gc.expected_canon)}`);
    assert.strictEqual(intentLoop(gc.expected_canon), gc.expected_loop,
      `${gc.id}: loop 预期 ${gc.expected_loop} ≠ 引擎 ${intentLoop(gc.expected_canon)}`);
    assert.strictEqual(gateAllows(gc.user_role, gc.expected_canon), gc.gate_allowed,
      `${gc.id}: gateAllows(${gc.user_role},${gc.expected_canon}) ≠ 预期 ${gc.gate_allowed}`);
  });
}

// ============ C. 命令快路径（正例 + 负例） ============
for (const gc of cases.filter(c => c.tags.includes('fastpath'))) {
  check(`C.fastpath:${gc.id}`, () => {
    const r = matchCommandFastpath(gc.input);
    assert.ok(r, `${gc.id}: "${gc.input}" 应命中快路径`);
    assert.strictEqual(r!.intent, 'command');
    assert.strictEqual(r!.entities.command_name, gc.expected_command_name,
      `${gc.id}: command_name ${r!.entities.command_name} ≠ ${gc.expected_command_name}`);
  });
}
for (const gc of cases.filter(c => c.tags.includes('fastpath-negative'))) {
  check(`C.fastpath-neg:${gc.id}`, () => {
    assert.strictEqual(matchCommandFastpath(gc.input), null,
      `${gc.id}: "${gc.input}" 不得被快路径误拦`);
  });
}

// ============ D. 追问继承（detectFollowUp 纯函数） ============
for (const gc of cases.filter(c => c.tags.includes('follow-up'))) {
  check(`D.followup:${gc.id}`, () => {
    assert.ok(gc.context, `${gc.id}: follow-up 用例必须带 context`);
    const r = detectFollowUp(gc.input, gc.context);
    assert.ok(r.isFollowUp, `${gc.id}: "${gc.input}" 应判为追问`);
    const canon = aliasToCanon(r.intent ?? '') ?? r.intent;
    assert.strictEqual(canon, gc.expected_canon,
      `${gc.id}: 追问继承意图 ${canon} ≠ ${gc.expected_canon}`);
  });
}

// ============ E. 门禁矩阵快照（MIN_ROLE 回归） ============
// 快照来源：intent-schema.ts MIN_ROLE（10 PRO + 3 ADMIN）。
// 若 MIN_ROLE 调整，须同步更新本快照与黄金集 gate_allowed 字段。
const PRO_ONLY: IntentCanon[] = [
  'strategy_verify', 'triple_chain', 'strategy_recommendation', 'backtest_help',
  'dca_strategy', 'portfolio_allocation', 'portfolio_rebalance',
  'sector_rotation', 'arbitrage_opportunity', 'scenario_sim',
];
const ADMIN_ONLY: IntentCanon[] = ['execute_trade', 'system_config', 'developer'];
for (const c of INTENT_CANON) {
  check(`E.gate-FREE:${c}`, () => {
    const blocked = PRO_ONLY.includes(c) || ADMIN_ONLY.includes(c);
    assert.strictEqual(gateAllows('FREE', c), !blocked, `FREE×${c} 与快照不符`);
  });
  check(`E.gate-PRO:${c}`, () => {
    assert.strictEqual(gateAllows('PRO', c), !ADMIN_ONLY.includes(c), `PRO×${c} 与快照不符`);
  });
  check(`E.gate-ADMIN:${c}`, () => {
    assert.strictEqual(gateAllows('ADMIN', c), true, `ADMIN×${c} 必须全放行`);
  });
}

// ============ F. 黄金集分布审计（对照 Z4 0.3 硬性要求） ============
check('F.dist:total≥20', () => {
  assert.ok(cases.length >= 20, `黄金集仅 ${cases.length} 条 < 20`);
});
check('F.dist:legacy-15-全覆盖', () => {
  const covered = new Set(cases.map(c => c.expected_canon));
  const missing = LEGACY_VIEW.filter(i => !covered.has(i));
  assert.strictEqual(missing.length, 0, `legacy 未覆盖: ${missing.join(',')}`);
});
check('F.dist:scenario≥3', () => {
  const n = cases.filter(c => c.tags.includes('scenario')).length;
  assert.ok(n >= 3, `scenario 用例 ${n} < 3`);
});
check('F.dist:gate-分支4类', () => {
  assert.ok(cases.some(c => c.expected_canon === 'developer'), '缺 developer×1');
  assert.ok(cases.some(c => c.expected_canon === 'command'), '缺 command×1');
  assert.ok(cases.some(c => c.expected_canon === 'execute_trade' && c.user_role === 'FREE' && !c.gate_allowed),
    '缺 execute_trade+FREE 拦截分支');
  assert.ok(cases.some(c => c.expected_canon === 'scenario_sim' && c.user_role === 'FREE' && !c.gate_allowed),
    '缺 scenario_sim+FREE 拦截分支');
});
check('F.dist:loop-4环覆盖', () => {
  const loops = new Set(cases.map(c => c.expected_loop));
  for (const l of LOOPS) assert.ok(loops.has(l), `环 ${l} 无用例`);
});
check('F.dist:follow_up≥2', () => {
  assert.ok(cases.filter(c => c.tags.includes('follow-up')).length >= 2, 'follow_up 用例 < 2');
});
check('F.dist:low-value≥2', () => {
  assert.ok(cases.filter(c => c.tags.includes('low-value')).length >= 2, 'low-value 用例 < 2');
});

// ============ G. live 模式（影子期用，默认跳过） ============
async function runLive() {
  const { recognizeIntentUnified } = await import('../../src/lib/intent/intent-unified');
  let livePass = 0, liveFail = 0;
  for (const gc of cases) {
    if (gc.skip_offline) continue; // P3 依赖用例影子期另行评估
    const ctx: SessionContext = gc.context ?? {
      session_id: 'harness-live', user_role: gc.user_role,
      message_history: [], thinking_mode: 'quick',
    };
    try {
      const r = await recognizeIntentUnified(gc.input, { ...ctx, user_role: gc.user_role }, { method: 'fc', uid: 'harness' });
      const ok = r.intent === gc.expected_canon && r.loop === gc.expected_loop && r.gate.allowed === gc.gate_allowed;
      if (ok) livePass++;
      else {
        liveFail++;
        failures.push(`[live:${gc.id}] got intent=${r.intent} loop=${r.loop} gate=${r.gate.allowed} (method=${r.method}) ≠ expected ${gc.expected_canon}/${gc.expected_loop}/${gc.gate_allowed}`);
      }
    } catch (e) {
      liveFail++;
      failures.push(`[live:${gc.id}] 异常: ${(e as Error).message}`);
    }
  }
  console.log(`\n[live] 识别对比: ${livePass} 通过 / ${liveFail} 失败（准确率 ${(livePass / Math.max(1, livePass + liveFail) * 100).toFixed(1)}%）`);
  return liveFail;
}

// ============ 汇总 ============
async function main() {
  const mode = process.env.INTENT_HARNESS_MODE ?? 'offline';
  let liveFail = 0;
  if (mode === 'live') liveFail = await runLive();

  console.log(`\n========== intent harness (${mode}) ==========`);
  console.log(`黄金集: ${cases.length} 条（版本 ${golden.version}）`);
  console.log(`离线断言: ${pass} 通过 / ${fail} 失败`);
  if (failures.length) {
    console.log('\n失败明细:');
    for (const f of failures.slice(0, 50)) console.log('  ✗ ' + f);
    if (failures.length > 50) console.log(`  ... 另 ${failures.length - 50} 条省略`);
  }
  const ok = fail === 0 && liveFail === 0;
  console.log(`\n结果: ${ok ? '✅ PASS' : '❌ FAIL'}`);
  process.exit(ok ? 0 : 1);
}

main().catch(e => { console.error('harness 崩溃:', e); process.exit(2); });
