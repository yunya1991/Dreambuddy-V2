/**
 * Hermes-Planner 调度器压力测试脚本
 * 
 * 测试场景：
 *   1. 调度器模式（scheduler）：启用 Cost Keeper + Skip Gate
 *   2. 深度模式（deep）：完整链路执行
 * 
 * 核心指标：
 *   - Token 节省率
 *   - 步骤跳过率
 *   - 请求延迟
 *   - 并发处理能力
 * 
 * 运行方式：npx tsx scripts/stress-test.ts
 */

import * as scheduler from "../src/lib/scheduler";

const GREEN = "\x1b[32m";
const YELLOW = "\x1b[33m";
const RED = "\x1b[31m";
const BOLD = "\x1b[1m";
const BLUE = "\x1b[34m";
const CYAN = "\x1b[36m";
const RESET = "\x1b[0m";

function section(title: string, emoji: string = "📦") {
  console.log(`\n${BOLD}${emoji}  ${title}${RESET}`);
  console.log("─".repeat(70));
}

function ok(msg: string) { console.log(`  ${GREEN}✓${RESET} ${msg}`); }
function warn(msg: string) { console.log(`  ${YELLOW}⚠${RESET} ${msg}`); }
function fail(msg: string) { console.log(`  ${RED}✗${RESET} ${msg}`); }
function info(msg: string) { console.log(`    → ${msg}`); }

interface TestResult {
  sessionId: string;
  mode: string;
  totalTokens: number;
  promptTokens: number;
  completionTokens: number;
  skippedSteps: string[];
  executedSteps: number;
  latencyMs: number;
  budgetUsed: number;
}

const TEST_SCENARIOS = [
  {
    name: '概念解释（"什么是布林带？"）',
    userInput: '什么是布林带？',
    intent: 'concept_explain',
    complexity: 'simple' as const,
    expectedSkip: ['MARKET_DATA', 'STRATEGY_ENGINE', 'S4_VALIDATE'],
  },
  {
    name: '简单行情查询（"BTC 现在价格"）',
    userInput: 'BTC 现在价格',
    intent: 'market_query',
    complexity: 'simple' as const,
    expectedSkip: ['STRATEGY_ENGINE', 'S4_VALIDATE'],
  },
  {
    name: '深度分析（"分析 BTC 趋势和入场时机"）',
    userInput: '分析 BTC 的趋势和入场时机，并给出策略建议',
    intent: 'deep_analysis',
    complexity: 'complex' as const,
    expectedSkip: [],
  },
  {
    name: '策略验证（"回测这个策略"）',
    userInput: '回测一下这个策略在过去一年的表现',
    intent: 'strategy_verify',
    complexity: 'moderate' as const,
    expectedSkip: [],
  },
  {
    name: '日常问候（"你好"）',
    userInput: '你好',
    intent: 'simple_qa',
    complexity: 'simple' as const,
    expectedSkip: ['MARKET_DATA', 'STRATEGY_ENGINE', 'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'],
  },
];

async function simulateRequest(sessionId: string, mode: 'scheduler' | 'deep', scenario: typeof TEST_SCENARIOS[0]): Promise<TestResult> {
  const startTime = Date.now();
  
  const result: TestResult = {
    sessionId,
    mode,
    totalTokens: 0,
    promptTokens: 0,
    completionTokens: 0,
    skippedSteps: [],
    executedSteps: 0,
    latencyMs: 0,
    budgetUsed: 0,
  };

  if (mode === 'scheduler') {
    scheduler.initCostKeeper(sessionId, scenario.intent, scenario.complexity);
  }

  const allSteps = [
    { id: 'MARKET_DATA', name: '行情数据', baseTokens: 0, llmTokens: 300 },
    { id: 'RAG_KNOWLEDGE', name: '知识库检索', baseTokens: 100, llmTokens: 200 },
    { id: 'S1_RESEARCH', name: 'S1调研', baseTokens: 800, llmTokens: 600 },
    { id: 'S2_ANALYSIS', name: 'S2分析', baseTokens: 800, llmTokens: 600 },
    { id: 'S3_DESIGN', name: 'S3设计', baseTokens: 800, llmTokens: 600 },
    { id: 'S4_VALIDATE', name: 'S4验证', baseTokens: 1200, llmTokens: 800 },
    { id: 'STRATEGY_ENGINE', name: '策略引擎', baseTokens: 0, llmTokens: 0 },
  ];

  for (const step of allSteps) {
    let shouldSkip = false;
    let skipReason = '';

    if (mode === 'scheduler') {
      const gateResult = scheduler.shouldSkipStep(
        step.id as scheduler.StepName,
        scenario.userInput,
        scenario.intent,
        scenario.complexity
      );
      shouldSkip = gateResult.skip;
      skipReason = gateResult.reason;
    }

    if (shouldSkip) {
      result.skippedSteps.push(`${step.id}: ${skipReason}`);
      if (mode === 'scheduler') {
        scheduler.markStepSkipped(sessionId, step.id, step.name, skipReason);
      }
    } else {
      result.executedSteps++;
      result.promptTokens += step.baseTokens;
      result.completionTokens += step.llmTokens;

      if (mode === 'scheduler') {
        scheduler.markStepStart(sessionId, step.id, step.name);
        scheduler.markStepEnd(sessionId, step.id, step.name, {
          promptTokens: step.baseTokens,
          completionTokens: step.llmTokens,
        }, step.id.startsWith('S') ? 'llm' : 'other');
      }

      await new Promise(r => setTimeout(r, Math.random() * 50));
    }
  }

  result.totalTokens = result.promptTokens + result.completionTokens;

  if (mode === 'scheduler') {
    const report = scheduler.generateReport(sessionId);
    if (report) {
      result.totalTokens = report.totalTokens;
      result.promptTokens = report.totalPromptTokens;
      result.completionTokens = report.totalCompletionTokens;
      result.budgetUsed = report.totalTokens / report.budgetTokens * 100;
    }
    scheduler.cleanupSession(sessionId);
  }

  result.latencyMs = Date.now() - startTime;

  return result;
}

async function runSingleScenario(scenario: typeof TEST_SCENARIOS[0]) {
  section(`场景: ${scenario.name}`, "🎯");
  
  const schedulerResult = await simulateRequest(`stress_sched_${Date.now()}`, 'scheduler', scenario);
  const deepResult = await simulateRequest(`stress_deep_${Date.now()}`, 'deep', scenario);

  console.log(`\n${BOLD}${BLUE}🚀 调度器模式${RESET}`);
  console.log(`   Token: ${schedulerResult.totalTokens.toLocaleString()} (${schedulerResult.promptTokens} prompt + ${schedulerResult.completionTokens} completion)`);
  console.log(`   执行步骤: ${schedulerResult.executedSteps} / 7`);
  console.log(`   跳过步骤: ${schedulerResult.skippedSteps.length}`);
  if (schedulerResult.skippedSteps.length > 0) {
    schedulerResult.skippedSteps.forEach(s => console.log(`     - ${s}`));
  }
  console.log(`   延迟: ${schedulerResult.latencyMs}ms`);
  console.log(`   预算使用: ${schedulerResult.budgetUsed.toFixed(1)}%`);

  console.log(`\n${BOLD}${CYAN}🧠 深度模式${RESET}`);
  console.log(`   Token: ${deepResult.totalTokens.toLocaleString()} (${deepResult.promptTokens} prompt + ${deepResult.completionTokens} completion)`);
  console.log(`   执行步骤: ${deepResult.executedSteps} / 7`);
  console.log(`   延迟: ${deepResult.latencyMs}ms`);

  const tokenSavings = deepResult.totalTokens - schedulerResult.totalTokens;
  const tokenSavingsPercent = deepResult.totalTokens > 0 
    ? ((deepResult.totalTokens - schedulerResult.totalTokens) / deepResult.totalTokens * 100).toFixed(1)
    : '0';

  console.log(`\n${BOLD}📊 对比结果${RESET}`);
  if (tokenSavings > 0) {
    console.log(`   ${GREEN}✓ Token 节省: ${tokenSavings.toLocaleString()} (${tokenSavingsPercent}%)${RESET}`);
  } else {
    console.log(`   ${YELLOW}~ 无显著节省${RESET}`);
  }
  
  const expectedSkipCount = scenario.expectedSkip.length;
  const actualSkipCount = schedulerResult.skippedSteps.filter(s => 
    scenario.expectedSkip.some(expected => s.startsWith(expected))
  ).length;
  
  if (actualSkipCount === expectedSkipCount) {
    ok(`跳过策略符合预期`);
  } else {
    warn(`跳过策略偏差: 预期 ${expectedSkipCount} 个，实际跳过 ${actualSkipCount} 个`);
  }
}

async function runConcurrentTest(concurrentCount: number, rounds: number) {
  section(`并发压力测试: ${concurrentCount} 并发 × ${rounds} 轮`, "⚡");

  const allResults: TestResult[] = [];
  
  for (let round = 0; round < rounds; round++) {
    console.log(`\n  第 ${round + 1}/${rounds} 轮`);
    
    const promises = Array.from({ length: concurrentCount }, (_, i) => {
      const sessionId = `concurrent_${round}_${i}`;
      const scenario = TEST_SCENARIOS[Math.floor(Math.random() * TEST_SCENARIOS.length)];
      return simulateRequest(sessionId, 'scheduler', scenario);
    });

    const results = await Promise.all(promises);
    allResults.push(...results);

    const avgLatency = results.reduce((sum, r) => sum + r.latencyMs, 0) / results.length;
    const avgTokens = results.reduce((sum, r) => sum + r.totalTokens, 0) / results.length;
    const avgSkipped = results.reduce((sum, r) => sum + r.skippedSteps.length, 0) / results.length;
    
    console.log(`    平均延迟: ${avgLatency.toFixed(0)}ms | 平均Token: ${avgTokens.toFixed(0)} | 平均跳过: ${avgSkipped.toFixed(1)}步`);
  }

  const totalRequests = allResults.length;
  const totalTokens = allResults.reduce((sum, r) => sum + r.totalTokens, 0);
  const totalSkipped = allResults.reduce((sum, r) => sum + r.skippedSteps.length, 0);
  const totalLatency = allResults.reduce((sum, r) => sum + r.latencyMs, 0);
  
  console.log(`\n${BOLD}📈 总计结果${RESET}`);
  console.log(`   请求数: ${totalRequests}`);
  console.log(`   总Token: ${totalTokens.toLocaleString()}`);
  console.log(`   平均Token/请求: ${(totalTokens / totalRequests).toFixed(0)}`);
  console.log(`   总跳过步骤: ${totalSkipped}`);
  console.log(`   平均跳过/请求: ${(totalSkipped / totalRequests).toFixed(1)}`);
  console.log(`   平均延迟: ${(totalLatency / totalRequests).toFixed(0)}ms`);
  
  ok("并发测试完成");
}

async function runMemoryLeakTest(durationMs: number) {
  section(`内存泄漏测试: ${durationMs}ms 持续运行`, "🔍");
  
  const startTime = Date.now();
  let requestCount = 0;
  
  while (Date.now() - startTime < durationMs) {
    const sessionId = `memory_test_${requestCount}_${Date.now()}`;
    const scenario = TEST_SCENARIOS[requestCount % TEST_SCENARIOS.length];
    
    await simulateRequest(sessionId, 'scheduler', scenario);
    
    requestCount++;
    
    if (requestCount % 100 === 0) {
      console.log(`    已处理: ${requestCount} 请求 | 耗时: ${(Date.now() - startTime).toFixed(0)}ms`);
    }
  }
  
  const report = scheduler.getSessionCount();
  console.log(`\n   请求总数: ${requestCount}`);
  console.log(`   活跃会话数: ${report}`);
  
  if (report === 0) {
    ok("内存清理正常，无泄漏");
  } else {
    warn(`存在 ${report} 个未清理的会话，可能有泄漏`);
  }
}

async function main() {
  console.log(`\n${BOLD}════════════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  Hermes-Planner 调度器压力测试${RESET}`);
  console.log(`${BOLD}  版本: ${scheduler.PLANNER_VERSION}${RESET}`);
  console.log(`${BOLD}════════════════════════════════════════════════════════${RESET}`);

  console.log(`\n${YELLOW}⚠️ 注意：此测试模拟 LLM Token 用量，不实际调用 API${RESET}`);

  // 测试1: 单场景对比
  section("测试1: 场景对比测试", "📋");
  for (const scenario of TEST_SCENARIOS) {
    await runSingleScenario(scenario);
  }

  // 测试2: 并发压力测试
  await runConcurrentTest(10, 5);

  // 测试3: 内存泄漏测试
  await runMemoryLeakTest(5000);

  console.log(`\n${BOLD}════════════════════════════════════════════════════════${RESET}`);
  console.log(`${BOLD}  ${GREEN}所有测试完成！${RESET}`);
  console.log(`${BOLD}════════════════════════════════════════════════════════${RESET}`);
}

main().catch(err => {
  console.error(`${RED}测试失败: ${err.message}${RESET}`);
  process.exit(1);
});
