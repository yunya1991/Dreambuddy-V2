/**
 * 端到端简化测试：验证 classic 模式从 routeIntent → executeClassicChain 的完整流程
 * 
 * 注意：此测试不启动 Next.js 服务器，也不调用真实的后端 API
 * 它只验证：
 * 1. smart-router 的 routeIntent 在 trading_mode=classic 时返回 C 系列链
 * 2. executeClassicChain 能够正确执行这些 C 系列步骤（即使 API 失败）
 * 3. AI 技能模式 (trading_mode=ai_skill) 不受影响
 */

import { routeIntent } from '../src/lib/intent/smart-router';
import { executeClassicChain, type TaskFile } from '../src/lib/task-manager';

async function main() {
  console.log('\n========== [E2E Test] Classic 模式完整流程验证 ==========\n');

  // ====== 测试用例 ======
  const testCases = [
    { message: '分析 BTC 的走势', intent: 'deep_analysis' as any, mode: 'classic' as const },
    { message: '现在开仓 ETH 是否合适？', intent: 'execute_trade' as any, mode: 'classic' as const },
    { message: 'BTC 现在的宏观情况', intent: 'macro_analysis' as any, mode: 'classic' as const },
    { message: '有什么好的入场信号', intent: 'entry_timing' as any, mode: 'classic' as const },
    { message: '分析 BTC 的走势', intent: 'deep_analysis' as any, mode: 'ai_skill' as const },
    { message: '现在开仓 ETH 是否合适？', intent: 'execute_trade' as any, mode: 'ai_skill' as const },
  ];

  let passed = 0;
  let failed = 0;

  for (let i = 0; i < testCases.length; i++) {
    const tc = testCases[i];
    const testName = `[${i + 1}/${testCases.length}] ${tc.intent} (${tc.mode})`;

    try {
      // --- Stage 1: routeIntent ---
      const routing = routeIntent(tc.intent, 'moderate', {
        session_id: `e2e_test_${i}`,
        user_role: 'FREE',
        message_history: [tc.message],
        thinking_mode: tc.mode === 'classic' ? 'deep' : 'quick',
        trading_mode: tc.mode,
      });

      const hasChain = routing.chain.length > 0;
      const isClassicChain = routing.chain.some((s: string) => s.startsWith('C'));
      const isClassicMode = (routing as any).is_classic_mode === true;

      let stage1Pass = true;
      if (tc.mode === 'classic') {
        stage1Pass = hasChain && isClassicChain && isClassicMode;
      } else {
        stage1Pass = hasChain && !isClassicChain;
      }

      console.log(`${stage1Pass ? '✅' : '❌'} ${testName}`);
      console.log(`    Stage 1 - routeIntent: chain=[${routing.chain.join(' → ')}], is_classic_mode=${isClassicMode}`);

      if (!stage1Pass) {
        console.log(`    ❌ FAIL - routeIntent stage failed`);
        failed++;
        continue;
      }

      // --- Stage 2: executeClassicChain (仅 classic 模式) ---
      if (tc.mode === 'classic') {
        const task: TaskFile = {
          task_id: `e2e_${Date.now()}_${i}`,
          status: 'completed',
          created_at: new Date().toISOString(),
          updated_at: new Date().toISOString(),
          source: 'test',
          message: tc.message,
          intent: { type: tc.intent, confidence: 0.8, entities: {} },
          thinking_mode: 'deep',
          trading_mode: 'classic',
          session_id: `e2e_test_${i}`,
          priority: 'high',
          metadata: {},
        };

        try {
          const result = await executeClassicChain(task, 'zh');
          const hasContent = typeof result.content === 'string' && result.content.length > 50;
          const stage2Pass = hasContent;
          console.log(`    Stage 2 - executeClassicChain: ${stage2Pass ? '✅' : '❌'} content_length=${result.content.length}`);
          console.log(`    Preview: ${result.content.slice(0, 200).replace(/\n/g, ' ')}...`);
          stage2Pass ? passed++ : failed++;
        } catch (err: any) {
          console.log(`    Stage 2 - executeClassicChain: ❌ ERROR - ${err.message}`);
          failed++;
        }
      } else {
        console.log(`    (ai_skill 模式跳过 executeClassicChain 测试)`);
        passed++;
      }
      console.log('');
    } catch (err: any) {
      console.log(`❌ ${testName} - 异常: ${err.message}`);
      failed++;
    }
  }

  console.log('\n========== [Test Summary] ==========');
  console.log(`  Total:  ${testCases.length} tests`);
  console.log(`  Passed: ${passed}`);
  console.log(`  Failed: ${failed}`);
  console.log(`  Result: ${failed === 0 ? '✅ ALL TESTS PASSED' : '❌ SOME TESTS FAILED'}\n`);
}

main().catch(console.error);
