/**
 * 双维度编排架构 - 多场景压力测试
 *
 * 测试场景:
 * 1. 意图类型: market_query, deep_analysis, execute_trade, strategy_verify, risk_alert
 * 2. 复杂度: quick, standard, deep
 * 3. 交易模式: ai_skill, classic, hybrid
 * 4. 特殊场景: 并发请求, 超时处理, 空输入
 * 5. 性能指标: 耗时, 成功率, 置信度分布
 */

import {
  initializeSkillsRegistry,
  getSkillsSummary,
  ExecutionPlanner,
} from '../../../6-图结构上下文压缩/planner/index.ts';

// ============================================================
// 测试场景定义
// ============================================================

interface TestScenario {
  name: string;
  intent: 'market_query' | 'deep_analysis' | 'execute_trade' | 'strategy_verify' | 'risk_alert';
  complexity: 'quick' | 'standard' | 'deep';
  tradingMode: 'ai_skill' | 'classic' | 'hybrid';
  userRequest: string;
  symbol?: string;
}

const SCENARIOS: TestScenario[] = [
  // ===== 意图类型测试 =====
  {
    name: '场景1: 市场行情查询',
    intent: 'market_query',
    complexity: 'quick',
    tradingMode: 'hybrid',
    userRequest: 'BTC 现在价格多少？',
    symbol: 'BTC',
  },
  {
    name: '场景2: 深度分析',
    intent: 'deep_analysis',
    complexity: 'deep',
    tradingMode: 'hybrid',
    userRequest: '请深度分析 BTC 当前走势，从技术面、资金面、情绪面多维度分析是否适合买入',
    symbol: 'BTC',
  },
  {
    name: '场景3: 执行交易',
    intent: 'execute_trade',
    complexity: 'standard',
    tradingMode: 'ai_skill',
    userRequest: '现在买入 BTC，仓位 20%，止损设置 5%',
    symbol: 'BTC',
  },
  {
    name: '场景4: 策略验证',
    intent: 'strategy_verify',
    complexity: 'standard',
    tradingMode: 'hybrid',
    userRequest: '验证双均线交叉策略在当前市场是否有效',
    symbol: 'BTC',
  },
  {
    name: '场景5: 风险预警',
    intent: 'risk_alert',
    complexity: 'quick',
    tradingMode: 'classic',
    userRequest: '检测当前持仓风险，显示风险预警',
    symbol: 'BTC',
  },

  // ===== 复杂度测试 =====
  {
    name: '场景6: 快速查询 (quick)',
    intent: 'market_query',
    complexity: 'quick',
    tradingMode: 'ai_skill',
    userRequest: 'ETH 涨了吗？',
    symbol: 'ETH',
  },
  {
    name: '场景7: 标准分析 (standard)',
    intent: 'deep_analysis',
    complexity: 'standard',
    tradingMode: 'hybrid',
    userRequest: '分析 ETH 的技术指标和趋势',
    symbol: 'ETH',
  },
  {
    name: '场景8: 深度研究 (deep)',
    intent: 'deep_analysis',
    complexity: 'deep',
    tradingMode: 'hybrid',
    userRequest: '对 ETH 进行全面深度分析，包括技术指标、资金流向、市场情绪、链上数据、宏观经济因素',
    symbol: 'ETH',
  },

  // ===== 交易模式测试 =====
  {
    name: '场景9: AI技能模式',
    intent: 'deep_analysis',
    complexity: 'standard',
    tradingMode: 'ai_skill',
    userRequest: '用 AI 交易系统分析 SOL',
    symbol: 'SOL',
  },
  {
    name: '场景10: 经典指标模式',
    intent: 'market_query',
    complexity: 'standard',
    tradingMode: 'classic',
    userRequest: '用经典指标系统分析 SOL',
    symbol: 'SOL',
  },
  {
    name: '场景11: 混合模式',
    intent: 'deep_analysis',
    complexity: 'standard',
    tradingMode: 'hybrid',
    userRequest: '综合分析 SOL 市场状态',
    symbol: 'SOL',
  },

  // ===== 多币种测试 =====
  {
    name: '场景12: 多币种轮询',
    intent: 'market_query',
    complexity: 'quick',
    tradingMode: 'hybrid',
    userRequest: '扫描主流币种 BTC, ETH, SOL, AVAX 的市场状态',
  },
  {
    name: '场景13: 山寨币分析',
    intent: 'deep_analysis',
    complexity: 'standard',
    tradingMode: 'hybrid',
    userRequest: '分析 PEPE 的交易机会',
    symbol: 'PEPE',
  },

  // ===== 边界场景 =====
  {
    name: '场景14: 超长请求',
    intent: 'deep_analysis',
    complexity: 'deep',
    tradingMode: 'hybrid',
    userRequest: '请分析 BTC、ETH、SOL 三个币种的 1H、4H、日线、周线多周期技术指标，包括 RSI、MACD、均线、成交量、布林带等多个指标，同时考虑资金流向、链上数据、市场情绪、宏观因素等，并给出具体的买入/卖出点位建议、止损止盈设置、仓位管理方案。',
    symbol: 'BTC',
  },
  {
    name: '场景15: 空符号处理',
    intent: 'market_query',
    complexity: 'quick',
    tradingMode: 'hybrid',
    userRequest: '现在的市场情况怎么样？',
  },

  // ===== 错误处理场景 =====
  {
    name: '场景16: 异常输入',
    intent: 'deep_analysis',
    complexity: 'standard',
    tradingMode: 'hybrid',
    userRequest: '!!!@@@###$$$',
  },
];

// ============================================================
// 测试执行
// ============================================================

interface TestResult {
  scenario: string;
  intent: string;
  complexity: string;
  tradingMode: string;
  success: boolean;
  duration: number;
  overallConfidence: number;
  stepCount: number;
  cvNodeCount: number;
  direction: string;
  error?: string;
}

async function runScenario(
  scenario: TestScenario,
  planner: ExecutionPlanner
): Promise<TestResult> {
  const startTime = Date.now();

  try {
    const result = await planner.execute({
      sessionId: `stress_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`,
      userRequest: scenario.userRequest,
      intent: scenario.intent,
      symbol: scenario.symbol,
      complexity: scenario.complexity,
      tradingMode: scenario.tradingMode,
      chainWeights: {
        s_chain: scenario.tradingMode === 'ai_skill' ? 0.7 : scenario.tradingMode === 'classic' ? 0.1 : 0.45,
        c_chain: scenario.tradingMode === 'ai_skill' ? 0.2 : scenario.tradingMode === 'classic' ? 0.8 : 0.35,
        f_chain: scenario.tradingMode === 'ai_skill' ? 0.1 : scenario.tradingMode === 'classic' ? 0.1 : 0.2,
      },
      maxLatencyMs: 30000,
      budgetTokens: 5000,
      userRole: 'USER',
      priorHistory: [],
    });

    return {
      scenario: scenario.name,
      intent: scenario.intent,
      complexity: scenario.complexity,
      tradingMode: scenario.tradingMode,
      success: result.success,
      duration: Date.now() - startTime,
      overallConfidence: result.overallConfidence,
      stepCount: result.steps?.length || 0,
      cvNodeCount: result.crossValidationResults?.length || 0,
      direction: result.conclusion?.direction || 'unknown',
    };
  } catch (error) {
    return {
      scenario: scenario.name,
      intent: scenario.intent,
      complexity: scenario.complexity,
      tradingMode: scenario.tradingMode,
      success: false,
      duration: Date.now() - startTime,
      overallConfidence: 0,
      stepCount: 0,
      cvNodeCount: 0,
      direction: 'error',
      error: error instanceof Error ? error.message : 'Unknown error',
    };
  }
}

async function runStressTest() {
  console.log('='.repeat(100));
  console.log('  双维度编排架构 - 多场景压力测试');
  console.log('='.repeat(100));
  console.log('');

  // -------------------- 初始化 --------------------
  console.log('[初始化] 初始化技能注册表...');
  initializeSkillsRegistry();
  const skills = getSkillsSummary();
  console.log(`  ✓ 总技能数: ${skills.length}`);
  console.log(`  ├─ A 链: ${skills.filter(s => s.chain === 'A').length} 个`);
  console.log(`  ├─ C 链: ${skills.filter(s => s.chain === 'C').length} 个`);
  console.log(`  └─ F 链: ${skills.filter(s => s.chain === 'F').length} 个`);
  console.log('');

  // -------------------- 顺序执行测试 --------------------
  console.log('[测试1/3] 顺序执行所有场景...');
  console.log('-'.repeat(100));

  const sequentialResults: TestResult[] = [];
  const planner = new ExecutionPlanner();

  for (const scenario of SCENARIOS) {
    process.stdout.write(`  ${scenario.name.slice(0, 20).padEnd(20)}`);
    const result = await runScenario(scenario, planner);
    sequentialResults.push(result);
    process.stdout.write(` ${result.success ? '✓' : '✗'} ${result.duration}ms conf=${result.overallConfidence}%\n`);
  }

  console.log('-'.repeat(100));
  console.log('');

  // -------------------- 并发测试 --------------------
  console.log('[测试2/3] 高并发测试 (10 并发)...');
  console.log('-'.repeat(100));

  const concurrentPlanner = new ExecutionPlanner();
  const concurrentPromises = SCENARIOS.slice(0, 10).map(scenario =>
    runScenario({ ...scenario, name: `[并发] ${scenario.name}` }, concurrentPlanner)
  );

  const concurrentResults = await Promise.all(concurrentPromises);

  for (const result of concurrentResults) {
    console.log(`  ${result.scenario.slice(0, 30).padEnd(30)} ${result.success ? '✓' : '✗'} ${result.duration}ms`);
  }

  console.log('-'.repeat(100));
  console.log('');

  // -------------------- 统计汇总 --------------------
  console.log('[测试3/3] 统计汇总...');
  console.log('');

  // 合并所有结果
  const allResults = [...sequentialResults, ...concurrentResults];
  const totalScenarios = allResults.length;
  const successCount = allResults.filter(r => r.success).length;
  const failCount = totalScenarios - successCount;
  const avgDuration = allResults.reduce((sum, r) => sum + r.duration, 0) / totalScenarios;
  const maxDuration = Math.max(...allResults.map(r => r.duration));
  const minDuration = Math.min(...allResults.map(r => r.duration));
  const avgConfidence = allResults.reduce((sum, r) => sum + r.overallConfidence, 0) / totalScenarios;

  // 按意图分组统计
  const byIntent: Record<string, { total: number; success: number; avgConf: number }> = {};
  for (const result of allResults) {
    if (!byIntent[result.intent]) {
      byIntent[result.intent] = { total: 0, success: 0, avgConf: 0 };
    }
    byIntent[result.intent].total++;
    if (result.success) byIntent[result.intent].success++;
    byIntent[result.intent].avgConf += result.overallConfidence;
  }

  // 按复杂度分组统计
  const byComplexity: Record<string, { total: number; success: number; avgConf: number }> = {};
  for (const result of allResults) {
    if (!byComplexity[result.complexity]) {
      byComplexity[result.complexity] = { total: 0, success: 0, avgConf: 0 };
    }
    byComplexity[result.complexity].total++;
    if (result.success) byComplexity[result.complexity].success++;
    byComplexity[result.complexity].avgConf += result.overallConfidence;
  }

  // 按交易模式分组统计
  const byTradingMode: Record<string, { total: number; success: number; avgConf: number }> = {};
  for (const result of allResults) {
    if (!byTradingMode[result.tradingMode]) {
      byTradingMode[result.tradingMode] = { total: 0, success: 0, avgConf: 0 };
    }
    byTradingMode[result.tradingMode].total++;
    if (result.success) byTradingMode[result.tradingMode].success++;
    byTradingMode[result.tradingMode].avgConf += result.overallConfidence;
  }

  // 打印统计结果
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              总体统计                                       │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  console.log(`│  总场景数: ${totalScenarios.toString().padEnd(60)}│`);
  console.log(`│  成功率:   ${(successCount / totalScenarios * 100).toFixed(1)}% (${successCount}/${totalScenarios})${' '.repeat(40)}│`);
  console.log(`│  失败数:   ${failCount}${'. '.repeat(55 - failCount.toString().length)}│`);
  console.log(`│  平均耗时: ${avgDuration.toFixed(0)}ms${' '.repeat(52)}│`);
  console.log(`│  最快耗时: ${minDuration}ms${' '.repeat(52)}│`);
  console.log(`│  最慢耗时: ${maxDuration}ms${' '.repeat(52)}│`);
  console.log(`│  平均置信度: ${avgConfidence.toFixed(1)}%${' '.repeat(47)}│`);
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 意图分布
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              意图类型分布                                    │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  for (const [intent, stats] of Object.entries(byIntent)) {
    const conf = stats.avgConf / stats.total;
    const bar = '█'.repeat(Math.round(stats.success / stats.total * 20)).padEnd(20);
    console.log(`│  ${intent.padEnd(15)} [${bar}] ${(stats.success / stats.total * 100).toFixed(0).padStart(3)}% conf=${conf.toFixed(0)}%${' '.repeat(20)}│`);
  }
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 复杂度分布
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              复杂度分布                                      │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  for (const [complexity, stats] of Object.entries(byComplexity)) {
    const conf = stats.avgConf / stats.total;
    const bar = '█'.repeat(Math.round(stats.success / stats.total * 20)).padEnd(20);
    console.log(`│  ${complexity.padEnd(15)} [${bar}] ${(stats.success / stats.total * 100).toFixed(0).padStart(3)}% conf=${conf.toFixed(0)}%${' '.repeat(20)}│`);
  }
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 交易模式分布
  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              交易模式分布                                    │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  for (const [mode, stats] of Object.entries(byTradingMode)) {
    const conf = stats.avgConf / stats.total;
    const bar = '█'.repeat(Math.round(stats.success / stats.total * 20)).padEnd(20);
    console.log(`│  ${mode.padEnd(15)} [${bar}] ${(stats.success / stats.total * 100).toFixed(0).padStart(3)}% conf=${conf.toFixed(0)}%${' '.repeat(20)}│`);
  }
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 方向分布
  const directions = allResults.reduce((acc, r) => {
    acc[r.direction] = (acc[r.direction] || 0) + 1;
    return acc;
  }, {} as Record<string, number>);

  console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
  console.log('│                              结论方向分布                                    │');
  console.log('├─────────────────────────────────────────────────────────────────────────────┤');
  const totalBars = Object.values(directions).reduce((a, b) => a + b, 0);
  for (const [dir, count] of Object.entries(directions).sort((a, b) => b[1] - a[1])) {
    const bar = '█'.repeat(Math.round(count / totalBars * 40)).padEnd(40);
    console.log(`│  ${dir.padEnd(10)} [${bar}] ${count} (${(count / totalBars * 100).toFixed(1)}%)${' '.repeat(Math.max(0, 35 - bar.length - count.toString().length - (count / totalBars * 100).toFixed(1).length))}│`);
  }
  console.log('└─────────────────────────────────────────────────────────────────────────────┘');
  console.log('');

  // 失败案例详情
  const failedResults = allResults.filter(r => !r.success);
  if (failedResults.length > 0) {
    console.log('┌─────────────────────────────────────────────────────────────────────────────┐');
    console.log('│                              失败案例详情                                    │');
    console.log('├─────────────────────────────────────────────────────────────────────────────┤');
    for (const result of failedResults) {
      console.log(`│  ❌ ${result.scenario.padEnd(40)} ${result.error?.slice(0, 30) || 'Unknown'}`);
    }
    console.log('└─────────────────────────────────────────────────────────────────────────────┘');
    console.log('');
  }

  // 最终结论
  console.log('='.repeat(100));
  const successRate = successCount / totalScenarios * 100;
  if (successRate >= 95) {
    console.log('  ✅ 测试通过: 成功率 >= 95%');
  } else if (successRate >= 80) {
    console.log('  ⚠️  测试警告: 成功率 80-95%');
  } else {
    console.log('  ❌ 测试失败: 成功率 < 80%');
  }
  console.log(`  总耗时: ${allResults.reduce((sum, r) => sum + r.duration, 0)}ms`);
  console.log('='.repeat(100));
}

// 执行
runStressTest().catch(error => {
  console.error('压力测试失败:', error);
  process.exit(1);
});
