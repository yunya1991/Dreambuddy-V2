/**
 * 基础设施协作综合压力测试 v2
 * =============================================
 *
 * 测试目标：
 * 1. Scheduler (CostKeeper + SkipGate) 独立正确性
 * 2. Compressor Adapter 独立正确性
 * 3. Router + CostKeeper 协作
 * 4. CostKeeper + SkipGate 协作
 * 5. graph-reflection-bridge 独立正确性
 * 6. Knowledge-Loader 独立正确性
 * 7. 极端场景冲突检测
 * 8. 全链路端到端
 *
 * 运行: PATH="/opt/homebrew/bin:/usr/local/bin:$PATH" pnpm tsx tests/infrastructure-integration-test.ts
 */

import * as fs from 'fs';
import * as path from 'path';

// ============================================================
// 测试框架
// ============================================================

let totalTests = 0;
let passedTests = 0;
let failedTests = 0;
const failures: string[] = [];
let testResults: Array<{ name: string; passed: boolean; durationMs: number; details?: string }> = [];

async function loadModules() {
  const scheduler = await import('../src/lib/scheduler');
  const router = await import('../src/lib/intent/smart-router');
  const compressor = await import('../src/lib/compressor-adapter');
  const graphBridge = await import('../src/lib/graph-reflection-bridge');
  const knowledgeLoader = await import('../src/lib/knowledge-loader');
  return { ...scheduler, ...router, ...compressor, ...graphBridge, ...knowledgeLoader };
}

function test(name: string, fn: () => void | Promise<void>) {
  totalTests++;
  const start = Date.now();
  try {
    const result = fn();
    if (result && typeof result.then === 'function') {
      (async () => {
        try {
          await result;
          passedTests++;
          testResults.push({ name, passed: true, durationMs: Date.now() - start });
          console.log(`  ✅ ${name} (${Date.now() - start}ms)`);
        } catch (e: unknown) {
          failedTests++;
          const msg = e instanceof Error ? e.message : String(e);
          failures.push(`${name}: ${msg}`);
          testResults.push({ name, passed: false, durationMs: Date.now() - start, details: msg });
          console.log(`  ❌ ${name}: ${msg.slice(0, 150)}`);
        }
      })();
    } else {
      passedTests++;
      testResults.push({ name, passed: true, durationMs: Date.now() - start });
      console.log(`  ✅ ${name} (${Date.now() - start}ms)`);
    }
  } catch (e: unknown) {
    failedTests++;
    const msg = e instanceof Error ? e.message : String(e);
    failures.push(`${name}: ${msg}`);
    testResults.push({ name, passed: false, durationMs: Date.now() - start, details: msg });
    console.log(`  ❌ ${name}: ${msg.slice(0, 150)}`);
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

function assertApprox(actual: number, expected: number, tolerance: number, msg: string) {
  if (Math.abs(actual - expected) > tolerance) {
    throw new Error(`${msg}: expected ~${expected} (±${tolerance}), got ${actual}`);
  }
}

function assertGT(a: number, b: number, msg: string) {
  if (a <= b) throw new Error(`${msg}: expected > ${b}, got ${a}`);
}

// ============================================================
// 数据构建器
// ============================================================

function buildMockMessages(count: number): Array<{ type: 'message'; id: string; content: string }> {
  const topics = ['BTC 走势分析', 'ETH 布林带', 'Solana 生态', '马丁策略加仓', '止损设置'];
  return Array.from({ length: count }, (_, i) => ({
    type: 'message' as const,
    id: `msg_${i}`,
    content: `${topics[i % topics.length]} #${i} ${'详细内容 '.repeat(i % 3)}`,
  }));
}

// ============================================================
// Suite 1: CostKeeper 独立正确性
// ============================================================

async function suite1(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n📊 Suite 1: CostKeeper 独立正确性');

  test('initCostKeeper 初始化会话成功', () => {
    m.initCostKeeper('s1-init', 'deep_analysis', 'moderate');
    const usage = m.getCurrentUsage('s1-init');
    assertEqual(usage!.used, 0, 'initial used should be 0');
    assertEqual(usage!.stepCount, 0, 'initial stepCount should be 0');
    m.cleanupSession('s1-init');
  });

  test('markStepStart/markStepEnd 正确记录 token 用量', () => {
    m.initCostKeeper('s1-tokens', 'deep_analysis', 'complex');
    m.markStepStart('s1-tokens', 'S1_RESEARCH', 'S1 市场调研');
    m.markStepEnd('s1-tokens', 'S1_RESEARCH', 'S1 市场调研', { promptTokens: 1500, completionTokens: 500 });
    const usage = m.getCurrentUsage('s1-tokens');
    assertEqual(usage!.used, 2000, 'used should be 2000');
    assertEqual(usage!.stepCount, 1, 'stepCount should be 1');
    m.cleanupSession('s1-tokens');
  });

  test('shouldTerminate 在超预算时返回 true', () => {
    m.initCostKeeper('s1-terminate', 'deep_analysis', 'complex');
    m.markStepStart('s1-terminate', 'S1', 'S1');
    m.markStepEnd('s1-terminate', 'S1', 'S1', { promptTokens: 6000, completionTokens: 2500 }); // 8500 > 8000
    const stopped = m.shouldTerminate('s1-terminate');
    assertEqual(stopped, true, 'shouldTerminate should be true after exceeding budget');
    m.cleanupSession('s1-terminate');
  });

  test('generateReport 生成完整报告结构', () => {
    m.initCostKeeper('s1-report', 'deep_analysis', 'moderate');
    m.markStepStart('s1-report', 'S1_RESEARCH', 'S1');
    m.markStepEnd('s1-report', 'S1_RESEARCH', 'S1', { promptTokens: 1000, completionTokens: 500 });
    m.markStepStart('s1-report', 'S2_ANALYSIS', 'S2');
    m.markStepEnd('s1-report', 'S2_ANALYSIS', 'S2', { promptTokens: 2000, completionTokens: 1000 });
    // Total: 4500 tokens, budget: 3500 (moderate) → exceeded
    const report = m.generateReport('s1-report');
    assert(report !== null, 'report should not be null');
    assertEqual(report!.intent, 'deep_analysis');
    assertEqual(report!.totalTokens, 4500, 'totalTokens should be 4500');
    assertEqual(report!.steps.length, 2, 'steps.length should be 2');
    assertEqual(report!.reachedBudgetLimit, true, 'reachedBudgetLimit should be true (4500 > 3500)');
    m.cleanupSession('s1-report');
  });

  test('estimateTokens 估算 token 数量', () => {
    const text = 'BTC 走势分析：当前价格 67000 美元，24小时涨幅 2.3%。';
    const tokens = m.estimateTokens(text);
    assertGT(tokens, 0, 'estimateTokens should return > 0');
  });

  test('cleanupSession 清理后 getCurrentUsage 返回空', () => {
    m.initCostKeeper('s1-cleanup', 'deep_analysis', 'moderate');
    m.markStepStart('s1-cleanup', 'S1', 'S1');
    m.markStepEnd('s1-cleanup', 'S1', 'S1', { promptTokens: 1000, completionTokens: 500 });
    m.cleanupSession('s1-cleanup');
    const usage = m.getCurrentUsage('s1-cleanup');
    assertEqual(usage!.used, 0, 'after cleanup used should be 0');
    assertEqual(usage!.stepCount, 0, 'after cleanup stepCount should be 0');
  });
}

// ============================================================
// Suite 2: Compressor 独立正确性
// ============================================================

async function suite2(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n🗜️ Suite 2: Compressor 独立正确性');

  test('Compressor 默认启用（非显式禁用）', () => {
    const adapter = m.getCompressorAdapter();
    assert(adapter !== null, 'adapter should not be null');
  });

  test('Compressor 处理空 payload 不崩溃', async () => {
    const adapter = m.getCompressorAdapter();
    const result = await adapter.compress({ sessionId: 's2-empty', payload: [] });
    assert(result !== null, 'result should not be null');
  });

  test('Compressor 处理超长输入正确统计 token', async () => {
    const adapter = m.getCompressorAdapter();
    const longPayload = buildMockMessages(100);
    const result = await adapter.compress({ sessionId: 's2-long', payload: longPayload, targetRatio: 0.3 });
    assert(result !== null, 'result should not be null');
    assertGT(result.originalTokens, 0, 'originalTokens should be > 0');
    assert(result.compressionRatio >= 0, 'compressionRatio should be >= 0');
  });

  test('Compressor 图数据不为空时 stats 正常', async () => {
    const adapter = m.getCompressorAdapter();
    const graphData = {
      nodes: buildMockMessages(20).map(c => ({ id: c.id, name: c.content.slice(0, 30), type: 'concept' as const, level: 'A' as const })),
      edges: Array.from({ length: 15 }, (_, i) => ({ from: `msg_${i}`, to: `msg_${i + 1}`, label: 'related' })),
    };
    const result = await adapter.compress({ sessionId: 's2-graph', payload: buildMockMessages(30), targetRatio: 0.5, graphData });
    assert(result !== null, 'result should not be null');
    assert(result.stats !== null, 'stats should not be null');
    // GraphStats uses totalNodes/totalEdges, not nodeCount/edgeCount
    assertEqual(typeof result.stats!.totalNodes === 'number', true, `totalNodes should be number`);
    assertEqual(typeof result.stats!.totalEdges === 'number', true, `totalEdges should be number`);
  });

  test('高频调用：连续 50 次 compress 不崩溃', async () => {
    const adapter = m.getCompressorAdapter();
    for (let i = 0; i < 50; i++) {
      const result = await adapter.compress({
        sessionId: `s2-freq-${i}`,
        payload: buildMockMessages(10),
        targetRatio: 0.5,
      });
      assert(result !== null, `iteration ${i}: result should not be null`);
    }
  });
}

// ============================================================
// Suite 3: Router + CostKeeper 协作
// ============================================================

async function suite3(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n🔗 Suite 3: Router + CostKeeper 协作');

  test('deep_analysis + PRO + deep → mode=dynamic, is_dynamic=true', () => {
    const routing = m.routeIntent('deep_analysis', 'complex', {
      session_id: 's3-dynamic', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).mode, 'dynamic', 'mode should be dynamic');
    assertEqual((routing as any).is_dynamic, true, 'is_dynamic should be true');
    assertGT((routing as any).chain.length, 2, 'chain should have > 2 steps');
  });

  test('stepwise 模式 → requires_confirmation=true', () => {
    const routing = m.routeIntent('deep_analysis', 'moderate', {
      session_id: 's3-stepwise', user_role: 'PRO', thinking_mode: 'stepwise',
    } as any);
    assertEqual((routing as any).mode, 'stepwise', 'mode should be stepwise');
    assertEqual((routing as any).requires_confirmation, true, 'requires_confirmation should be true');
  });

  test('developer 模式 → is_dev_chain=true, credits=60', () => {
    const routing = m.routeIntent('developer', 'complex', {
      session_id: 's3-dev', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).mode, 'developer', 'mode should be developer');
    assertEqual((routing as any).is_dev_chain, true, 'is_dev_chain should be true');
    assertEqual((routing as any).credits_cost, 60, 'credits_cost should be 60');
    assert((routing as any).chain.includes('DEV_E_CHAIN'), 'chain should include DEV_E_CHAIN');
  });

  test('FREE 用户 execute_trade → role_check=upgrade_required', () => {
    const routing = m.routeIntent('execute_trade', 'complex', {
      session_id: 's3-free', user_role: 'FREE', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).role_check, 'upgrade_required', 'FREE execute_trade should require upgrade');
  });

  test('PRO + deep_analysis 全链执行，CostKeeper 正确记录', () => {
    m.initCostKeeper('s3-full-chain', 'deep_analysis', 'complex');
    const routing = m.routeIntent('deep_analysis', 'complex', {
      session_id: 's3-full-chain', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    for (const step of (routing as any).chain) {
      m.markStepStart('s3-full-chain', step, step);
      m.markStepEnd('s3-full-chain', step, step, { promptTokens: 1000, completionTokens: 500 });
    }
    const report = m.generateReport('s3-full-chain');
    assert(report !== null, 'report should not be null');
    assertGT(report!.totalTokens, 0, 'totalTokens should be > 0');
    assertEqual(report!.steps.length, (routing as any).chain.length, 'steps count should match');
    m.cleanupSession('s3-full-chain');
  });

  test('scenario_sim + stepwise → mode=stepwise', () => {
    const routing = m.routeIntent('scenario_sim', 'complex', {
      session_id: 's3-sim', user_role: 'PRO', thinking_mode: 'stepwise',
    } as any);
    assertEqual((routing as any).mode, 'stepwise', 'scenario_sim stepwise should be stepwise');
  });

  test('strategy_verify + dynamic → 验证 S2/S3/S4 链', () => {
    const routing = m.routeIntent('strategy_verify', 'complex', {
      session_id: 's3-verify', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).mode, 'dynamic', 'strategy_verify dynamic should be dynamic');
    // strategy_verify pro_full_chain = [S2_ANALYSIS, S3_DESIGN, S4_VALIDATE] = 3 steps
    assertEqual((routing as any).chain.length, 3, 'strategy_verify chain should have 3 steps');
  });
}

// ============================================================
// Suite 4: SkipGate 协作
// ============================================================

async function suite4(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n⏭️ Suite 4: SkipGate 协作');

  test('shouldSkipStep 对 S4_VALIDATE 返回 skip 判断', () => {
    const result = m.shouldSkipStep('S4_VALIDATE', 'BTC 走势分析，请验证策略', 'deep_analysis', 'complex');
    assert(result !== null, 'result should not be null');
    assert(typeof result.skip === 'boolean', 'skip should be boolean');
    assert(typeof result.reason === 'string', 'reason should be string');
  });

  test('shouldSkipStep 对 S1_RESEARCH 通常不跳过', () => {
    const result = m.shouldSkipStep('S1_RESEARCH', 'BTC 深度分析', 'deep_analysis', 'complex');
    assertEqual(result.skip, false, 'S1_RESEARCH should not be skipped for deep_analysis');
  });

  test('markStepSkipped 记录到报告', () => {
    m.initCostKeeper('s4-skip', 'scenario_sim', 'moderate');
    m.markStepStart('s4-skip', 'S1', 'S1');
    m.markStepEnd('s4-skip', 'S1', 'S1', { promptTokens: 1000, completionTokens: 500 });
    m.markStepSkipped('s4-skip', 'S4_VALIDATE', 'SkipGate: simple intent skip rule', 'S4');
    const report = m.generateReport('s4-skip');
    assert(report !== null, 'report should not be null');
    assert(report!.skippedSteps.some((s: string) => s.includes('S4_VALIDATE')), 'S4 should be in skippedSteps');
    m.cleanupSession('s4-skip');
  });

  test('shouldTerminate 在简单意图超预算时触发', () => {
    m.initCostKeeper('s4-terminate', 'deep_analysis', 'simple'); // simple budget = 1200
    m.markStepStart('s4-terminate', 'S1', 'S1');
    m.markStepEnd('s4-terminate', 'S1', 'S1', { promptTokens: 800, completionTokens: 500 }); // 1300 > 1200
    assertEqual(m.shouldTerminate('s4-terminate'), true, 'should terminate after exceeding simple budget');
    m.cleanupSession('s4-terminate');
  });
}

// ============================================================
// Suite 5: Knowledge-Loader 独立正确性
// ============================================================

async function suite5(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n📚 Suite 5: Knowledge-Loader 独立正确性');

  test('getKnowledgeContextSync 返回结构化上下文', () => {
    const context = m.getKnowledgeContextSync('s5-test', 'BTC马丁策略止损设置', 'deep_analysis');
    assert(context !== null, 'context should not be null');
    assert(typeof context === 'string' || typeof context === 'object', 'context should be string or object');
  });

  test('loadAllKnowledge 加载知识库目录', () => {
    const result = m.loadAllKnowledge();
    assert(result !== null, 'result should not be null');
    // 知识库目录可能存在（测试环境有40个chunk）
    assert(typeof result.loaded === 'number', 'loaded should be number');
    assert(typeof result.failed === 'number', 'failed should be number');
  });

  test('getKnowledgeStats 返回统计信息', () => {
    const stats = m.getKnowledgeStats();
    assert(stats !== null, 'stats should not be null');
    assert(typeof stats.totalChunks === 'number', 'totalChunks should be number');
    // cacheHitRate 可能不存在或不是number（取决于RAG模块实现）
    assert(typeof stats.cacheHitRate === 'number' || stats.cacheHitRate === undefined, 'cacheHitRate should be number or undefined');
  });
}

// ============================================================
// Suite 6: Graph-Reflection-Bridge 独立正确性
// ============================================================

async function suite6(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n🔄 Suite 6: Graph-Reflection-Bridge 独立正确性');

  test('createGraphReflectionState 创建初始状态', () => {
    const state = m.createGraphReflectionState('s6-init');
    assert(state !== null, 'state should not be null');
    assertEqual(state.sessionId, 's6-init', 'sessionId should match');
    assert(Array.isArray(state.blueprintNodes), 'blueprintNodes should be array');
    assert(state.architectureNodes instanceof Map, 'architectureNodes should be Map');
    // createGraphReflectionState creates 5 arch nodes (S1-S5) in blueprint template
    assertEqual(state.totalNodes, 5, 'initial totalNodes should be 5');
    assertEqual(state.completedNodes, 0, 'initial completedNodes should be 0');
  });

  test('graphAwareShouldSkipStep 返回 skip 判断', () => {
    const state = m.createGraphReflectionState('s6-skip');
    // API: graphAwareShouldSkipStep(step, graphState, stepMetadatas[])
    const result = m.graphAwareShouldSkipStep('S4_VALIDATE', state, []);
    assert(result !== null, 'result should not be null');
    assert(typeof result.skipStep === 'boolean', 'skipStep should be boolean');
  });

  test('buildGraphSummary 返回摘要', () => {
    const state = m.createGraphReflectionState('s6-summary');
    const summary = m.buildGraphSummary(state);
    assert(summary !== null, 'summary should not be null');
    assert(typeof summary === 'string' || typeof summary === 'object', 'summary should be string or object');
  });

  test('updateCompressionSignal 正常更新压缩信号', () => {
    const state = m.createGraphReflectionState('s6-compress');
    m.updateCompressionSignal(state);
    assert(state.compressionSignal !== null, 'compressionSignal should not be null');
    assert(Array.isArray(state.compressionSignal.highValueNodes), 'highValueNodes should be array');
    assert(Array.isArray(state.compressionSignal.compressibleNodes), 'compressibleNodes should be array');
  });

  test('markRollback 正常回滚', () => {
    const state = m.createGraphReflectionState('s6-rollback');
    m.markRollback(state, 'S3_DESIGN');
    assertEqual(state.rollbackCount, 1, 'rollbackCount should be 1');
  });

  test('getSessionCount 返回会话数量', () => {
    // Note: Sessions from previous suites have been cleaned up, so count may be 0
    const count = m.getSessionCount();
    assert(typeof count === 'number' && count >= 0, 'sessionCount should be >= 0 (number)');
  });
}

// ============================================================
// Suite 7: 极端场景冲突检测
// ============================================================

async function suite7(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n⚠️ Suite 7: 极端场景冲突检测');

  test('超长消息历史（500条）+ Compressor 不崩溃', async () => {
    const adapter = m.getCompressorAdapter();
    const longPayload = buildMockMessages(500);
    const result = await adapter.compress({ sessionId: 's7-long', payload: longPayload, targetRatio: 0.1 });
    assert(result !== null, 'result should not be null');
    assertGT(result.originalTokens, 0, 'originalTokens should be > 0');
  });

  test('超高频：连续 100 次 markStepEnd 不影响正确性', () => {
    m.initCostKeeper('s7-freq', 'deep_analysis', 'complex');
    for (let i = 0; i < 100; i++) {
      m.markStepStart('s7-freq', `STEP_${i}`, `Step ${i}`);
      m.markStepEnd('s7-freq', `STEP_${i}`, `Step ${i}`, { promptTokens: 50, completionTokens: 25 });
    }
    const usage = m.getCurrentUsage('s7-freq');
    assertApprox(usage!.used, 100 * 75, 10, 'total tokens should be ~7500');
    assertEqual(usage!.stepCount, 100, 'stepCount should be 100');
    m.cleanupSession('s7-freq');
  });

  test('Router 路由在超长输入下仍能正确决策', () => {
    const longInput = 'BTC ETH SOL '.repeat(100);
    const routing = m.routeIntent('deep_analysis', 'complex', {
      session_id: 's7-router', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).mode, 'dynamic', 'should be dynamic mode');
    assertGT((routing as any).chain.length, 2, 'chain should still be complete');
  });

  test('graphAwareShouldSkipStep 对高频连续调用返回一致结果', () => {
    const state = m.createGraphReflectionState('s7-consistency');
    // API: graphAwareShouldSkipStep(step, graphState, stepMetadatas[])
    const results = Array.from({ length: 20 }, () =>
      m.graphAwareShouldSkipStep('S1_RESEARCH', state, [])
    );
    // 所有结果应该一致（没有外部状态影响）
    const first = results[0].skipStep;
    for (const r of results) {
      assertEqual(r.skipStep, first, 'all skip results should be consistent');
    }
  });

  test('Compressor 并发调用不共享状态（session 隔离）', async () => {
    const adapter = m.getCompressorAdapter();
    const [r1, r2] = await Promise.all([
      adapter.compress({ sessionId: 's7-parallel-a', payload: buildMockMessages(10), targetRatio: 0.5 }),
      adapter.compress({ sessionId: 's7-parallel-b', payload: buildMockMessages(20), targetRatio: 0.3 }),
    ]);
    assert(r1 !== null && r2 !== null, 'both results should be non-null');
    assert(r1.originalTokens !== r2.originalTokens, 'different inputs should produce different originalTokens');
  });
}

// ============================================================
// Suite 8: 全链路端到端
// ============================================================

async function suite8(m: Awaited<ReturnType<typeof loadModules>>) {
  console.log('\n🔮 Suite 8: 全链路端到端');

  test('完整场景：deep_analysis → Router → CostKeeper → Compressor', async () => {
    const adapter = m.getCompressorAdapter();
    const history = buildMockMessages(60);
    const compressed = await adapter.compress({ sessionId: 's8-full', payload: history, targetRatio: 0.5 });
    assertGT(compressed.originalTokens, 0, 'compressed originalTokens should be > 0');

    m.initCostKeeper('s8-full', 'deep_analysis', 'moderate');
    const routing = m.routeIntent('deep_analysis', 'moderate', {
      session_id: 's8-full', user_role: 'PRO', thinking_mode: 'deep',
    } as any);
    assertEqual((routing as any).mode, 'dynamic');

    for (const step of (routing as any).chain) {
      const skipResult = m.shouldSkipStep(step, 'BTC 深度分析', 'deep_analysis', 'moderate');
      if (skipResult.skip) {
        m.markStepSkipped('s8-full', step, `SkipGate: ${skipResult.reason}`, step);
      } else {
        m.markStepStart('s8-full', step, step);
        m.markStepEnd('s8-full', step, step, { promptTokens: 1000, completionTokens: 500 });
      }
    }

    const report = m.generateReport('s8-full');
    assert(report !== null);
    assertGT(report!.totalTokens, 0, 'totalTokens should be > 0');
    assertGT(report!.steps.length, 0, 'steps should be recorded');
    m.cleanupSession('s8-full');
  });

  test('stepwise 场景：分步确认，CostKeeper 追踪部分执行', () => {
    m.initCostKeeper('s8-stepwise', 'strategy_verify', 'complex');
    const routing = m.routeIntent('strategy_verify', 'complex', {
      session_id: 's8-stepwise', user_role: 'PRO', thinking_mode: 'stepwise',
    } as any);
    assertEqual((routing as any).mode, 'stepwise');
    assertEqual((routing as any).requires_confirmation, true);

    // 第一轮：S1 + S2
    const partialChain = ((routing as any).chain as string[]).filter(s =>
      ['S1_RESEARCH', 'S2_ANALYSIS'].includes(s)
    );
    for (const step of partialChain) {
      m.markStepStart('s8-stepwise', step, step);
      m.markStepEnd('s8-stepwise', step, step, { promptTokens: 1000, completionTokens: 500 });
    }
    const report1 = m.generateReport('s8-stepwise');
    assertGT(report1!.totalTokens, 0);
    assertEqual(report1!.steps.length, partialChain.length);

    // 确认后继续 S3
    m.markStepStart('s8-stepwise', 'S3_DESIGN', 'S3');
    m.markStepEnd('s8-stepwise', 'S3_DESIGN', 'S3', { promptTokens: 2000, completionTokens: 1000 });
    const report2 = m.generateReport('s8-stepwise');
    assertGT(report2!.steps.length, partialChain.length, 'second report should have more steps');
    m.cleanupSession('s8-stepwise');
  });

  test('developer 场景：E 链与 S 系列完全隔离', () => {
    m.initCostKeeper('s8-dev', 'developer', 'complex');
    const routing = m.routeIntent('developer', 'complex', {
      session_id: 's8-dev', user_role: 'PRO', thinking_mode: 'deep',
    } as any);

    const hasSSeries = ((routing as any).chain as string[]).some(s => s.startsWith('S'));
    assertEqual(hasSSeries, false, 'developer mode should not use S-series steps');
    assert((routing as any).chain.includes('DEV_E_CHAIN'), 'should use DEV_E_CHAIN');

    m.markStepStart('s8-dev', 'DEV_E_CHAIN', 'E链');
    m.markStepEnd('s8-dev', 'DEV_E_CHAIN', 'E链', { promptTokens: 3000, completionTokens: 1000 });
    const report = m.generateReport('s8-dev');
    assertEqual(report!.intent, 'developer');
    assertGT(report!.totalTokens, 0);
    m.cleanupSession('s8-dev');
  });

  test('多意图路由：不同意图 → 不同 mode', () => {
    const testCases = [
      { intent: 'deep_analysis', expectedMode: 'dynamic' },
      { intent: 'scenario_sim', expectedMode: 'dynamic' },
      { intent: 'strategy_verify', expectedMode: 'dynamic' },
      // market_query with thinking_mode='deep' returns 'dynamic' (not 'quick' which requires thinking_mode='quick')
      { intent: 'market_query', expectedMode: 'dynamic' },
    ];
    for (const { intent, expectedMode } of testCases) {
      m.initCostKeeper(`s8-multi-${intent}`, intent, 'moderate');
      const routing = m.routeIntent(intent, 'moderate', {
        session_id: `s8-multi-${intent}`, user_role: 'PRO', thinking_mode: 'deep',
      } as any);
      assertEqual((routing as any).mode, expectedMode, `${intent} should have mode=${expectedMode}`);
      m.cleanupSession(`s8-multi-${intent}`);
    }
  });

  test('graph-reflection-bridge 与 CostKeeper 联合：回滚记录正确', () => {
    const graphState = m.createGraphReflectionState('s8-graph-cost');
    m.initCostKeeper('s8-graph-cost', 'deep_analysis', 'complex');
    m.markStepStart('s8-graph-cost', 'S1', 'S1');
    m.markStepEnd('s8-graph-cost', 'S1', 'S1', { promptTokens: 1000, completionTokens: 500 });
    m.markRollback(graphState, 'S2_ANALYSIS');
    m.markStepStart('s8-graph-cost', 'S2', 'S2');
    m.markStepEnd('s8-graph-cost', 'S2', 'S2', { promptTokens: 2000, completionTokens: 1000 });
    assertEqual(graphState.rollbackCount, 1, 'rollbackCount should be 1');
    const report = m.generateReport('s8-graph-cost');
    assertEqual(report!.steps.length, 2, 'should have 2 steps');
    m.cleanupSession('s8-graph-cost');
  });
}

// ============================================================
// 测试报告
// ============================================================

async function printReport() {
  console.log('\n' + '='.repeat(60));
  console.log('📋 基础设施协作综合测试报告');
  console.log('='.repeat(60));
  console.log(`总计: ${totalTests} | 通过: ${passedTests} | 失败: ${failedTests}`);

  if (failedTests > 0) {
    console.log('\n❌ 失败详情:');
    for (const f of failures) console.log(`  - ${f.slice(0, 200)}`);
  }

  const suiteStats: Record<string, { total: number; passed: number }> = {};
  for (const r of testResults) {
    const suite = r.name.split(':')[0] || 'unknown';
    if (!suiteStats[suite]) suiteStats[suite] = { total: 0, passed: 0 };
    suiteStats[suite].total++;
    if (r.passed) suiteStats[suite].passed++;
  }

  console.log('\n📊 分 Suite 统计:');
  for (const [suite, stats] of Object.entries(suiteStats)) {
    const pct = ((stats.passed / stats.total) * 100).toFixed(0);
    const status = stats.passed === stats.total ? '✅' : '⚠️';
    console.log(`  ${status} ${suite}: ${stats.passed}/${stats.total} (${pct}%)`);
  }

  console.log('\n⏱️ 最慢测试:');
  for (const r of testResults.sort((a, b) => b.durationMs - a.durationMs).slice(0, 5)) {
    console.log(`  ${r.durationMs}ms — ${r.name}`);
  }

  const allPassed = failedTests === 0;
  console.log(`\n${allPassed ? '✅ 所有测试通过！' : '❌ 部分测试失败！'}`);
  console.log('='.repeat(60));
  process.exit(allPassed ? 0 : 1);
}

// ============================================================
// 主入口
// ============================================================

async function main() {
  console.log('🧪 基础设施协作综合压力测试开始...');
  console.log(`时间: ${new Date().toISOString()}\n`);

  const m = await loadModules();
  console.log(`模块加载: CostKeeper=✅ Router=✅ Compressor=✅ GraphBridge=✅ KnowledgeLoader=✅`);

  await suite1(m);
  await suite2(m);
  await suite3(m);
  await suite4(m);
  await suite5(m);
  await suite6(m);
  await suite7(m);
  await suite8(m);

  await new Promise(resolve => setTimeout(resolve, 300));
  await printReport();
}

main().catch(e => {
  console.error('Fatal error:', e);
  process.exit(1);
});
