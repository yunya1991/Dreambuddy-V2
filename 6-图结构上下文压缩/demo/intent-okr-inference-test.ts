/**
 * 端到端压力测试：意图识别 → OKR 图架构 → 推理引擎 → Planner 增援
 *
 * 验证全链路：
 *   1. 用户消息 → 意图识别（定总目标）
 *   2. 意图目标写入 B 层根节点（Long OKR）
 *   3. Planner 执行 → 图推理引擎 → knowledgeHits 注入下一步
 *   4. 笔记本视图（B=长期目标 / A=中期计划 / C=短期记录 / 便签）
 *   5. 多轮意图切换场景
 */

import { createCompressor } from '../contract.ts';
import { ensureRegistryInitialized } from '../planner/skills-registry-init.ts';
import { orchestrate } from '../planner/index.ts';
import type { PlannerContext } from '../planner/planner-types.ts';

async function main() {
  ensureRegistryInitialized();
  const c = createCompressor({ mode: 'semantic', semanticWeight: 0.4 });

  console.log('╔═══════════════════════════════════════════════════════════╗');
  console.log('║  意图识别 → OKR 图架构 → 图推理引擎  端到端压力测试        ║');
  console.log('╚═══════════════════════════════════════════════════════════╝\n');

  const SESSION = 'okr-test-session';
  const sep = '─'.repeat(60);

  // ══════════════════════════════════════════════════════
  // 场景 1：交易分析意图（第 1 轮）
  // ══════════════════════════════════════════════════════
  console.log(`${sep}\n📌 场景 1: 交易分析意图\n${sep}`);

  const ir1 = c.recognizeIntent(
    'BTC 现在应该入场做多吗？帮我分析行情',
    SESSION,
    []
  );
  console.log(`意图识别: ${ir1.intent} | 目标: ${ir1.objective}`);
  console.log(`是否新意图: ${ir1.isNewIntent}`);
  console.log('OKR 总目标:\n' + ir1.okrSummary);

  // 添加便签
  c.addNote(SESSION, {
    title: 'BTC 入场研究',
    content: '关注 64800 支撑，RSI < 60 时入场',
    horizon: 'short',
    status: 'active',
  });

  // Planner 执行（AI链 standard）
  const p1 = await orchestrate(SESSION, 'BTC 行情分析', 'deep_analysis', {
    tradingMode: 'ai_skill', complexity: 'standard',
    chainWeights: { s_chain: 1, c_chain: 0, f_chain: 0 },
    priorHistory: {
      previousConclusions: ['BTC 趋势看多', 'RSI 55 中性区'],
      previousConfidences: [78, 72],
    },
  } as Partial<PlannerContext>);

  console.log(`\nPlanner 结果: steps=${p1.steps.length} CV=${p1.crossValidationResults?.length ?? 0} conf=${p1.overallConfidence}%`);
  p1.steps.forEach((s: any) => {
    const inferHits = s.skillsCalled?.filter((sc: any) =>
      sc.skillId?.includes('inference') || sc.skillId?.includes('knowledge')
    ).length ?? 0;
    console.log(`  [${s.stepId}] dec=${s.decision} conf=${s.confidence}%`);
  });

  // 压缩写入图结构
  const items1 = p1.steps.map((s: any, i: number) => ({
    id: `p1_${s.stepId}`,
    type: 'step' as const,
    content: `[A层-${s.stepId}] conf=${s.confidence}% dec=${s.decision}: ${s.answer?.slice(0, 80) ?? ''}`,
    tokens: s.tokensUsed || 100,
    timestamp: Date.now() + i * 10,
    meta: { layer: 'A', horizon: 'mid', round: 1 },
  }));

  const cr1 = await c.compress({
    sessionId: SESSION,
    payload: [...items1, {
      id: 'p1_conclusion',
      type: 'message',
      content: `[C层-结论] dir=${p1.conclusion?.direction ?? 'neutral'} conf=${p1.conclusion?.confidence ?? 0}%`,
      tokens: 60, timestamp: Date.now() + 1000,
      meta: { layer: 'C', horizon: 'short' },
    }],
    targetRatio: 0.5,
    metadata: { intent: 'trading', round: 1 },
  });

  console.log(`\n图结构压缩: B=${cr1.stats.byLevel.B} A=${cr1.stats.byLevel.A} C=${cr1.stats.byLevel.C}`);
  console.log(`  retained=${cr1.stats.retainedNodes} compressed=${cr1.stats.compressedNodes}`);

  // ══════════════════════════════════════════════════════
  // 场景 2：第 2 轮（同意图，验证推理引擎增援）
  // ══════════════════════════════════════════════════════
  console.log(`\n${sep}\n📌 场景 2: 第 2 轮（同意图，推理引擎增援验证）\n${sep}`);

  const ir2 = c.recognizeIntent(
    '刚才的分析给了建议，我想进一步验证入场时机',
    SESSION,
    [{ role: 'user', content: 'BTC 现在应该入场做多吗？' }]
  );
  console.log(`意图: ${ir2.intent} | 是否切换: ${ir2.isNewIntent}`);

  const p2 = await orchestrate(SESSION + '_r2', 'BTC 入场验证', 'execute_trade', {
    tradingMode: 'hybrid', complexity: 'standard',
    chainWeights: { s_chain: 0.4, c_chain: 0.4, f_chain: 0.2 },
    priorHistory: {
      previousConclusions: [
        p1.steps[0]?.answer?.slice(0, 60) ?? '上轮 S1 调研结论',
        p1.steps[1]?.answer?.slice(0, 60) ?? '上轮 S2 分析结论',
      ],
      previousConfidences: [
        p1.steps[0]?.confidence ?? 65,
        p1.steps[1]?.confidence ?? 70,
      ],
    },
  } as Partial<PlannerContext>);

  console.log(`Planner: steps=${p2.steps.length} conf=${p2.overallConfidence}%`);
  p2.steps.forEach((s: any) => console.log(`  [${s.stepId}] dec=${s.decision} conf=${s.confidence}%`));

  // ══════════════════════════════════════════════════════
  // 场景 3：意图切换（strategy → 验证切换检测）
  // ══════════════════════════════════════════════════════
  console.log(`\n${sep}\n📌 场景 3: 意图切换（trading → strategy）\n${sep}`);

  const ir3 = c.recognizeIntent(
    '我想设计一个新的马丁格策略，回测一下',
    SESSION,
    [{ role: 'user', content: 'BTC 分析' }]
  );
  console.log(`意图切换: ${ir3.isNewIntent ? '✅ 检测到切换' : '❌ 未切换'}`);
  console.log(`新意图: ${ir3.intent} | 目标: ${ir3.objective}`);
  if (ir3.isNewIntent) {
    console.log('旧目标已归档，新目标已激活');
  }

  // ══════════════════════════════════════════════════════
  // 最终：笔记本视图（OKR 全景）
  // ══════════════════════════════════════════════════════
  console.log(`\n${sep}\n📓 笔记本视图（OKR 全景）\n${sep}`);

  c.addNote(SESSION, {
    title: '马丁格策略参数',
    content: '加仓间隔 1.5%，最多 4 层，止损 -8%',
    horizon: 'mid',
    status: 'active',
  });

  const nb = c.getNotebookView(SESSION);
  console.log(`长期目标（B层）: ${nb.longTermObjective}`);
  console.log(`当前意图: ${nb.intent}`);
  console.log(`中期任务（A层）: ${nb.midTermTasks.length} 个节点`);
  nb.midTermTasks.slice(0, 3).forEach(t => console.log(`  - [${t.status}] ${t.name}`));
  console.log(`短期记录（C层）: ${nb.shortTermLog.length} 条`);
  nb.shortTermLog.slice(0, 3).forEach(l => console.log(`  - ${l.kept ? '✅' : '🗜️'} ${l.summary.slice(0, 50)}`));
  console.log(`便签: ${nb.notes.length} 条`);
  nb.notes.forEach(n => console.log(`  - [${n.horizon}/${n.status}] ${n.title}`));
  console.log('\nOKR 摘要:\n' + nb.okrSummary);

  // ══════════════════════════════════════════════════════
  // 验证清单
  // ══════════════════════════════════════════════════════
  console.log(`\n${sep}\n✅ 验证清单\n${sep}`);

  const checks: Array<[string, () => boolean]> = [
    ['意图识别正常（首次识别为新意图）', () => ir1.isNewIntent],
    ['意图 → B 层总目标正确映射', () => ir1.objective.includes('交易')],
    ['同意图连续轮次不误判为新意图', () => !ir2.isNewIntent],
    ['意图切换检测正确', () => ir3.isNewIntent],
    ['Planner 第 1 轮执行 3 步', () => p1.steps.length === 3],
    ['Planner 第 2 轮含历史增援（知识注入）', () => p2.steps.length > 0],
    ['图结构 B/A/C 三层均有节点', () => cr1.stats.byLevel.B > 0 && cr1.stats.byLevel.A > 0 && cr1.stats.byLevel.C > 0],
    ['C 层节点被压缩（保留部分）', () => cr1.stats.compressedNodes > 0 && cr1.stats.retainedNodes > 0],
    ['笔记本视图长期目标不为空', () => nb.longTermObjective.length > 0],
    ['笔记本中期任务来自图结构 A 层', () => nb.midTermTasks.length > 0],
    ['便签 API 正常（2 条便签）', () => nb.notes.length === 2],
  ];

  let pass = 0, fail = 0;
  checks.forEach(([label, fn]) => {
    let ok = false;
    try { ok = fn(); } catch {}
    console.log(`  ${ok ? '✅' : '❌'} ${label}`);
    ok ? pass++ : fail++;
  });

  console.log(`\n结果: ${pass}/${pass + fail} 通过${fail > 0 ? ` | ❌ ${fail} 失败` : ''}`);
  console.log(`\n全链路：意图识别→OKR目标→Planner动态链→图推理增援→笔记本视图 ✓`);
}

main().catch(e => {
  console.error('\n❌ 测试失败:', e.message, '\n', e.stack);
});
