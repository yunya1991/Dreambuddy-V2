/**
 * intent-golden-test.ts — P0 黄金集基线验证（Z3 §P0 / Z4 L1）
 *
 * 运行（离线基线，零 token）：
 *   cd /tmp/golden-run && npx --prefix <gateway> tsx <gateway>/scripts/intent-golden-test.ts
 *   或直接：npx tsx scripts/intent-golden-test.ts   （注意：会写 ./intent-memory/records.json）
 *
 * GOLDEN_LLM=1：启用真实 LLM 路径（消耗少量 token，仅验证期使用）
 *
 * 输出：控制台逐例结果 + 准确率；JSON 摘要写入 stdout 末尾（可重定向存档做 diff 基线）
 */

// 离线基线模式：清空 LLM 凭证，强制走规则/兜底路径（须在业务模块 import 前生效）
if (process.env.GOLDEN_LLM !== '1') {
  delete process.env.DASHSCOPE_API_KEY;
  delete process.env.DEEPSEEK_API_KEY;
  delete process.env.DASHSCOPE_BASE_URL;
}

import { recognizeIntent, SessionContext, IntentType } from '../src/lib/intent/fallback-engine';
import { isIntentCanon, IntentCanon, aliasToCanon } from '../src/lib/intent/intent-schema';

interface GoldenCase {
  id: string;
  utterance: string;
  expected: IntentCanon;      // 期望正典意图（黄金标准）
  tags: string[];
}

// ============ 黄金集（24 例，手工编写，覆盖 15 正典 + 场景意图 + 歧义）============
const GOLDEN: GoldenCase[] = [
  // 行情查询
  { id: 'g01', utterance: 'BTC现在什么价', expected: 'market_query', tags: ['行情'] },
  { id: 'g02', utterance: '查一下ETH的价格和24h涨跌', expected: 'market_query', tags: ['行情'] },
  // 深度分析
  { id: 'g03', utterance: '帮我深度分析一下SOL', expected: 'deep_analysis', tags: ['分析'] },
  { id: 'g04', utterance: '分析下比特币为什么跌了', expected: 'deep_analysis', tags: ['分析'] },
  // 情景模拟 / 策略验证
  { id: 'g05', utterance: '如果美联储突然加息，行情会怎么走', expected: 'scenario_sim', tags: ['模拟'] },
  { id: 'g06', utterance: '验证一下马丁策略在震荡市的表现', expected: 'strategy_verify', tags: ['策略'] },
  // 执行交易
  { id: 'g07', utterance: '买入0.1个BTC', expected: 'execute_trade', tags: ['交易', '高危'] },
  { id: 'g08', utterance: '开多ETH，100U，3倍杠杆', expected: 'execute_trade', tags: ['交易', '高危'] },
  // 简单问答
  { id: 'g09', utterance: 'MA200是什么意思', expected: 'simple_qa', tags: ['问答'] },
  { id: 'g10', utterance: '什么是马丁格尔策略', expected: 'simple_qa', tags: ['问答'] },
  // 命令（快路径必须 100%）
  { id: 'g11', utterance: '/status', expected: 'command', tags: ['命令'] },
  { id: 'g12', utterance: '/pause all', expected: 'command', tags: ['命令'] },
  // 积分 / 配置 / 产物
  { id: 'g13', utterance: '我还有多少积分', expected: 'credits_query', tags: ['查询'] },
  { id: 'g14', utterance: '把风险阈值改成5%', expected: 'system_config', tags: ['配置', '治理'] },
  { id: 'g15', utterance: '帮我找一下上次那份分析报告', expected: 'artifact_query', tags: ['查询'] },
  // 风险告警响应 / 三链
  { id: 'g16', utterance: '收到风险告警了，先减仓', expected: 'risk_alert_response', tags: ['风险'] },
  { id: 'g17', utterance: '跑一遍三链完整流程分析BTC', expected: 'triple_chain', tags: ['多步'] },
  // 多场景意图（fallback 规则路径能力边界）
  { id: 'g18', utterance: '帮我看看BTC的支撑位和阻力位', expected: 'support_resistance', tags: ['场景'] },
  { id: 'g19', utterance: '现在适合入场吗', expected: 'entry_timing', tags: ['场景'] },
  { id: 'g20', utterance: '该止盈离场了吗', expected: 'exit_timing', tags: ['场景'] },
  { id: 'g21', utterance: 'BTC和ETH哪个更强', expected: 'asset_comparison', tags: ['场景'] },
  { id: 'g22', utterance: '最近市场情绪怎么样', expected: 'market_sentiment', tags: ['场景'] },
  { id: 'g23', utterance: '给我推荐一个适合震荡市的策略', expected: 'strategy_recommendation', tags: ['场景'] },
  // 歧义用例（期望走澄清）
  { id: 'g24', utterance: '帮我处理一下', expected: 'need_clarification', tags: ['歧义'] },
];

async function main() {
  const mode = process.env.GOLDEN_LLM === '1' ? 'llm' : 'rule-baseline';
  console.log(`[黄金集] 模式=${mode} 用例=${GOLDEN.length}\n`);

  const ctxBase: SessionContext = {
    session_id: 'golden-test',
    user_role: 'ADMIN',
    message_history: [],
    thinking_mode: 'quick',
    trading_mode: 'ai_skill',
  };

  let correct = 0;
  const rows: Array<{ id: string; utterance: string; expected: string; got: string; ok: boolean; method: string; confidence: number }> = [];

  for (const c of GOLDEN) {
    try {
      const res = await recognizeIntent(c.utterance, { ...ctxBase });
      // 归一到正典（risk_alert 等别名）
      const gotCanon = aliasToCanon(res.intent as string) ?? (res.intent as IntentCanon);
      const ok = gotCanon === c.expected;
      if (ok) correct++;
      rows.push({ id: c.id, utterance: c.utterance, expected: c.expected, got: gotCanon, ok, method: res.method, confidence: res.confidence });
      console.log(`  ${ok ? '✓' : '✗'} ${c.id} [${res.method} ${res.confidence.toFixed(2)}] "${c.utterance}" → ${gotCanon}${ok ? '' : ` (期望 ${c.expected})`}`);
    } catch (e) {
      rows.push({ id: c.id, utterance: c.utterance, expected: c.expected, got: 'ERROR', ok: false, method: 'error', confidence: 0 });
      console.log(`  ✗ ${c.id} "${c.utterance}" → ERROR: ${(e as Error).message}`);
    }
  }

  const acc = correct / GOLDEN.length;
  const cmdCases = rows.filter(r => GOLDEN.find(g => g.id === r.id)?.tags.includes('命令'));
  const cmdAcc = cmdCases.length ? cmdCases.filter(r => r.ok).length / cmdCases.length : 1;

  console.log(`\n[结果] 总准确率=${(acc * 100).toFixed(1)}% (${correct}/${GOLDEN.length})  命令类=${(cmdAcc * 100).toFixed(0)}%`);
  console.log('\n[JSON摘要]');
  console.log(JSON.stringify({ mode, total: GOLDEN.length, correct, accuracy: +acc.toFixed(4), cmd_accuracy: +cmdAcc.toFixed(4), rows }, null, 1));

  // 基线模式不做硬门槛（记录现状）；fc 模式验收在 Phase 2 后执行
  process.exit(0);
}

main().catch(e => { console.error('FATAL', e); process.exit(2); });
