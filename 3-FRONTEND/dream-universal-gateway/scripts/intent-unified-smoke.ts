/**
 * intent-unified-smoke.ts — P2 冒烟验证（零 token）
 * 验证统一管线 rule 模式：命令快路径 + 规则兜底 + 修复级联类型安全
 * 运行：cd <gateway> && npx tsx scripts/intent-unified-smoke.ts
 */
import { recognizeIntentUnified } from '../src/lib/intent/intent-unified';
import { matchCommandFastpath } from '../src/lib/intent/command-fastpath';
import { repairIntentArgs } from '../src/lib/intent/intent-args-repair';
import { readFileSync } from 'fs';
import { join } from 'path';
import type { SessionContext } from '../src/lib/intent/fallback-engine';

const SMOKE_CTX: SessionContext = {
  session_id: 'smoke',
  user_role: 'FREE',
  message_history: [],
  thinking_mode: 'quick',
  trading_mode: 'classic',
};

const GOLDEN = JSON.parse(readFileSync(join(__dirname, 'golden-baseline-rule.json'), 'utf8')) as {
  accuracy: number;
  rows: { id: string; utterance: string; expected: string; got: string; ok: boolean }[];
};

let pass = 0, fail = 0;
const fails: string[] = [];

function check(name: string, cond: boolean, detail = '') {
  if (cond) { pass++; }
  else { fail++; fails.push(`${name}${detail ? ' — ' + detail : ''}`); }
}

// ── 1. 命令快路径（P0 基线中 0% 的类别）──
const cmd1 = matchCommandFastpath('/status');
check('fastpath /status', cmd1?.intent === 'command' && cmd1.entities.command_name === 'status');
const cmd2 = matchCommandFastpath('/pause all');
check('fastpath /pause all', cmd2?.intent === 'command' && cmd2.entities.command_args === 'all');
check('fastpath 非命令返回 null', matchCommandFastpath('BTC什么价格') === null);

// ── 2. 修复级联 ──
const r1 = repairIntentArgs({ intent: 'RISK_ALERT', confidence: 1.5, entities: 'bad', complexity: 'weird' });
check('repair 别名归一', r1.intent === 'risk_alert_response');
check('repair confidence 钳制', r1.confidence === 1);
check('repair entities 容错', Object.keys(r1.entities).length === 0);
check('repair complexity 默认', r1.complexity === 'moderate');
check('repair 审计痕迹', r1.repairs.length >= 3, JSON.stringify(r1.repairs));
const r2 = repairIntentArgs('not-an-object');
check('repair 非对象输入', r2.intent === null && r2.repairs.includes('args_not_object'));
const r3 = repairIntentArgs({ intent: 'market_query', confidence: 0.9, entities: { symbol: 'btc' }, complexity: 'simple', reasoning: 'ok' });
check('repair symbol 大写', r3.intent === 'market_query' && r3.entities.symbol === 'BTC');
check('repair 无损不记痕', r3.repairs.length === 0, JSON.stringify(r3.repairs));

// ── 3. 统一管线 rule 模式（黄金集全量）──
async function main() {
  let ruleOk = 0;
  for (const c of GOLDEN.rows) {
    const res = await recognizeIntentUnified(c.utterance, SMOKE_CTX, { method: 'rule' });
    check(`unified-rule ${c.id} 结构完整`, !!res.intent && !!res.loop && !!res.gate, JSON.stringify(res));
    if (res.intent === c.expected) ruleOk++;
  }
  const unifiedAcc = ruleOk / GOLDEN.rows.length;
  console.log(`[unified-rule 准确率] ${ruleOk}/${GOLDEN.rows.length} = ${(unifiedAcc * 100).toFixed(1)}%（基线 ${(GOLDEN.accuracy * 100).toFixed(1)}%）`);
  check('unified-rule ≥ 基线', unifiedAcc >= GOLDEN.accuracy, `${unifiedAcc}`);
  // 命令类必须 100%（fastpath 生效）
  const cmdCases = GOLDEN.rows.filter(c => c.expected === 'command');
  for (const c of cmdCases) {
    const res = await recognizeIntentUnified(c.utterance, SMOKE_CTX, { method: 'rule' });
    check(`unified 命令 ${c.id}`, res.intent === 'command' && res.method === 'rule', res.intent);
  }

  console.log(`\n[P2 冒烟] pass=${pass} fail=${fail}`);
  if (fails.length) console.log('失败项:\n' + fails.map(f => '  - ' + f).join('\n'));
  process.exit(fail > 0 ? 1 : 0);
}

main().catch(e => { console.error('FATAL', e); process.exit(2); });
