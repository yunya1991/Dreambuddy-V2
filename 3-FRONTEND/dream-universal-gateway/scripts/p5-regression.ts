/**
 * PROP-20260828B P5 回归验证
 * 1. intent-schema 往返无损  2. 统一管线 rule 模式各分支
 * 3. 命令快路径 8/8          4. symbol 保留  5. 记忆双写  6. 黄金集
 */
import { recognizeIntentUnified } from '../src/lib/intent/intent-unified';
import { INTENT_CANON, canonToLegacy, LEGACY_VIEW } from '../src/lib/intent/intent-schema';
import { matchCommandFastpath } from '../src/lib/intent/command-fastpath';

let pass = 0, fail = 0;
const failures: string[] = [];
function check(name: string, cond: boolean, detail = '') {
  if (cond) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; failures.push(`${name} ${detail}`); console.log(`  ❌ ${name} ${detail}`); }
}

// P5修复: 以 intent-schema 导出的 LEGACY_VIEW 为权威清单（含 developer，无 follow_up——
// follow_up 是 method 不是 intent 型）
function mkCtx(over: Record<string, unknown> = {}) {
  return {
    session_id: 'p5-test',
    user_role: 'FREE',
    message_history: [] as string[],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
    ...over,
  } as any;
}

(async () => {
  console.log('═══ 1. intent-schema 往返无损 ═══');
  let rtOk = 0;
  for (const legacy of LEGACY_VIEW) {
    // legacy 15 型 ⊆ 正典 35 型，恒等映射后降级应还原
    if (canonToLegacy(legacy as any) === legacy) rtOk++;
  }
  check(`legacy 恒等往返 ${rtOk}/${LEGACY_VIEW.length}`, rtOk === LEGACY_VIEW.length);
  check('正典总数=35', INTENT_CANON.length === 35, `实际=${INTENT_CANON.length}`);
  const image = new Set(INTENT_CANON.map(c => canonToLegacy(c)));
  const surjective = LEGACY_VIEW.every(l => image.has(l as any));
  check('canon→legacy 满射（15 型全覆盖）', surjective, `像集大小=${image.size}`);

  console.log('═══ 2. 命令快路径 8/8 ═══');
  const commands: [string, string][] = [
    ['/status', 'command'], ['/help', 'command'], ['查看状态', 'command'],
    ['帮助', 'command'], ['/pause', 'command'], ['/resume', 'command'],
    ['暂停交易', 'command'], ['恢复交易', 'command'],
  ];
  let cmdOk = 0;
  for (const [msg, expected] of commands) {
    const fp = matchCommandFastpath(msg);
    if (fp && fp.intent === expected) cmdOk++;
    else console.log(`    ↳ miss: "${msg}" → ${fp ? fp.intent : 'null'}`);
  }
  check(`命令快路径 ${cmdOk}/8`, cmdOk === 8);

  console.log('═══ 3. 统一管线 rule 模式 ═══');
  const r1 = await recognizeIntentUnified('BTC 现在什么价格', mkCtx(), { method: 'rule' });
  check('行情查询→market_query', r1.intent === 'market_query', `实际=${r1.intent}`);
  check('symbol=BTC 大写保留', r1.entities.symbol === 'BTC', `实际=${r1.entities.symbol}`);

  const r2 = await recognizeIntentUnified('帮我深度分析一下 ETH 的走势', mkCtx(), { method: 'rule' });
  check('深度分析→deep_analysis', r2.intent === 'deep_analysis', `实际=${r2.intent}`);

  // P5修复: need_clarification 是 FC(LLM) 路径特性；rule 模式下裸动词句确定命中
  // eq_004，无意义输入落 ④ 默认兜底——这两条才是 rule 模式的保证面。
  const r3 = await recognizeIntentUnified('帮我分析一下', mkCtx(), { method: 'rule' });
  check('裸动词分析句→deep_analysis', r3.intent === 'deep_analysis', `实际=${r3.intent}`);
  const r3b = await recognizeIntentUnified('啊啊啊', mkCtx(), { method: 'rule' });
  check('无意义输入→default兜底', r3b.intent === 'simple_qa' && r3b.method === 'default', `实际=${r3b.intent}/${r3b.method}`);

  const r4 = await recognizeIntentUnified('/status', mkCtx(), { method: 'rule' });
  check('统一管线命令→command', r4.intent === 'command', `实际=${r4.intent}`);
  check('命令置信度=1', r4.confidence === 1);

  const r5 = await recognizeIntentUnified('怎么样', mkCtx({ last_intent: 'market_query', last_symbol: 'BTC' }), { method: 'rule' });
  check('follow_up 识别', r5.method === 'follow_up', `实际=${r5.intent}/${r5.method}`);
  check('follow_up 继承 last_symbol', r5.entities.symbol === 'BTC', `实际=${r5.entities.symbol}`);

  console.log('═══ 4. 角色门禁审计 ═══');
  const r6 = await recognizeIntentUnified('修改系统配置', mkCtx(), { method: 'rule' });
  check('gate 字段存在', !!r6.gate && typeof r6.gate.allowed === 'boolean');

  console.log('═══ 5. 黄金集 ═══');
  const golden: { msg: string; expect: string }[] = [
    { msg: '/status', expect: 'command' },
    { msg: '查看状态', expect: 'command' },
    { msg: '/help', expect: 'command' },
    { msg: '暂停交易', expect: 'command' },
    { msg: 'BTC 现在什么价格', expect: 'market_query' },
    { msg: 'ETH 4小时线怎么样', expect: 'market_query' },
    { msg: 'SOL 最近走势如何', expect: 'market_query' },
    { msg: '帮我深度分析 BTC 趋势', expect: 'deep_analysis' },
  ];
  let gOk = 0;
  for (const g of golden) {
    const r = await recognizeIntentUnified(g.msg, mkCtx(), { method: 'rule' });
    if (r.intent === g.expect) gOk++;
    else console.log(`    ↳ miss: "${g.msg}" 期望=${g.expect} 实际=${r.intent}`);
  }
  check(`黄金集 ${gOk}/${golden.length} (${(gOk / golden.length * 100).toFixed(1)}%)`, gOk === golden.length);

  console.log('═══ 6. 记忆双写 ═══');
  const before = (await import('../src/lib/intent/intent-memory')).getMemoryStats();
  await recognizeIntentUnified('HYPE 现在多少钱', mkCtx(), { method: 'rule' });
  await recognizeIntentUnified('/status', mkCtx(), { method: 'rule' }); // 命令不入库
  const after = (await import('../src/lib/intent/intent-memory')).getMemoryStats();
  check('金融消息入库(+1)', after.total_records === before.total_records + 1,
    `before=${before.total_records} after=${after.total_records}`);

  console.log('\n════════════════════════');
  console.log(`总计: ${pass} 通过, ${fail} 失败`);
  if (failures.length) console.log('失败项:', failures.join(' | '));
  process.exit(fail > 0 ? 1 : 0);
})().catch(e => { console.error('FATAL:', e); process.exit(2); });
