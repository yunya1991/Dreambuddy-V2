/**
 * 临时实测脚本：PROP-20260829-C P2 影子探针 live 验证（Z3 §2.2）
 * 3 条测试消息 → runShadowProbe（真实 FC 调用）→ 校验 shadow.jsonl
 */
import { runShadowProbe, shadowSampleCount, shadowBudgetExhausted, SHADOW_BUDGET } from '../../src/lib/intent/shadow-probe';

const CASES: Array<{ msg: string; legacyIntent: string }> = [
  { msg: 'BTC 现在多少钱', legacyIntent: 'price_query' },
  { msg: '帮我深度分析一下 ETH 的行情', legacyIntent: 'market_analysis' },
  { msg: '继续', legacyIntent: 'context_follow' },
];

async function main() {
  console.log(`预算: ${SHADOW_BUDGET}, 已用: ${shadowSampleCount(true)}, 耗尽: ${shadowBudgetExhausted()}`);
  for (const c of CASES) {
    await runShadowProbe(
      c.msg,
      { user_role: 'FREE', session_id: 'p2-live-test', message_history: [], thinking_mode: 'off' },
      { intent: c.legacyIntent, confidence: 0.9, method: 'llm', intent_method_actual: 'llm' }
    );
    console.log(`✓ 探针完成: ${c.msg}`);
  }
  console.log(`\n样本总数: ${shadowSampleCount(true)}`);
}

main().catch(e => { console.error('FATAL:', e); process.exit(1); });
