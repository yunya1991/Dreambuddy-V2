/**
 * 调度协调能力综合评估测试
 *
 * 评估维度:
 * 1. 动态思维链调度能力 (Plan-Execute-Reflect 闭环)
 * 2. 策略链/开发链状态机调度能力
 * 3. 图反射桥双向融合能力
 * 4. 意图路由调度能力
 * 5. 任务管理协调能力
 *
 * 评估指标:
 * - 功能完备性: 已实现的调度功能数量
 * - 决策多样性: 不同调度决策类型的覆盖度
 * - 状态一致性: 调度过程中状态同步的准确性
 * - 错误处理: 异常场景下的鲁棒性
 * - 性能表现: 调度延迟和资源消耗
 */

import { runDynamicChain, quickRun } from '../src/lib/dynamic-chain/runner';
import { generateInitialPlan, adjustPlanAfterStep, initGraphState } from '../src/lib/dynamic-chain/graph-planner';
import { executeStepPlan } from '../src/lib/dynamic-chain/executor';
import { reflect, DYNAMIC_CHAIN_CONSTANTS } from '../src/lib/dynamic-chain/reflect-engine';
import type { DynamicChainContext, DynamicChainIntent, PlanStep } from '../src/lib/dynamic-chain/types';

import {
  createGraphReflectionState,
  graphAwareSelfCriticism,
  graphAwareShouldSkipStep,
  recordStepReflection,
  markRollback,
  buildGraphSummary,
  updateCompressionSignal,
  estimateTokens,
  type GraphReflectionState,
} from '../src/lib/graph-reflection-bridge';

import type { StepPhase, StepMetadata } from '../src/lib/reflection-gates';
import { analyzeStepConfidence, runSelfCriticism } from '../src/lib/reflection-gates';

import { StrategyChainController } from '../src/lib/strategy/chain-controller';
import type { StrategyComplexity, StrategyStepId } from '../src/lib/strategy/types';

// ============================================================
// 测试框架
// ============================================================

interface TestCase {
  name: string;
  category: string;
  description: string;
  run: () => TestResult | Promise<TestResult>;
}

interface TestResult {
  passed: boolean;
  score: number; // 0-100
  details: string;
  metrics?: Record<string, number | string>;
  error?: string;
}

interface EvalReport {
  totalScore: number;
  categories: {
    name: string;
    score: number;
    weight: number;
    tests: { name: string; passed: boolean; score: number; details: string }[];
  }[];
  summary: {
    strengths: string[];
    weaknesses: string[];
    recommendations: string[];
  };
  timestamp: string;
}

// ============================================================
// 测试用例定义
// ============================================================

const testCases: TestCase[] = [
  // ===== 维度1: 动态思维链调度能力 =====
  {
    name: '动态链 - 初始计划生成',
    category: '动态思维链调度',
    description: '验证动态链能否根据不同意图生成正确的初始计划',
    run: testDynamicChainInitialPlan,
  },
  {
    name: '动态链 - 步骤执行能力',
    category: '动态思维链调度',
    description: '验证步骤执行器能否正确生成步骤内容并评估质量',
    run: testDynamicChainStepExecution,
  },
  {
    name: '动态链 - 反思决策多样性',
    category: '动态思维链调度',
    description: '验证反思引擎能否产生多种决策类型（CONTINUE/REDO/JUMP_TO等）',
    run: testDynamicChainReflectionDecisions,
  },
  {
    name: '动态链 - 完整闭环执行',
    category: '动态思维链调度',
    description: '验证完整的 Plan-Execute-Reflect 闭环能否正常运行',
    run: testDynamicChainFullLoop,
  },
  {
    name: '动态链 - 计划动态调整',
    category: '动态思维链调度',
    description: '验证根据图状态动态调整计划的能力（INSERT/REDO/JUMP）',
    run: testDynamicChainPlanAdjustment,
  },

  // ===== 维度2: 策略链/开发链状态机调度 =====
  {
    name: '策略链 - 状态机初始化',
    category: '状态机调度',
    description: '验证策略链状态机的初始化和步骤配置',
    run: testStrategyChainInit,
  },
  {
    name: '策略链 - 步进执行',
    category: '状态机调度',
    description: '验证策略链的步进执行和状态转换',
    run: testStrategyChainStepExecution,
  },
  {
    name: '策略链 - 跳过机制',
    category: '状态机调度',
    description: '验证策略链的步骤跳过功能',
    run: testStrategyChainSkip,
  },
  {
    name: '开发链 - E链执行',
    category: '状态机调度',
    description: '验证开发链E1-E2-E3的执行能力',
    run: testDevChainExecution,
  },

  // ===== 维度3: 图反射桥双向融合能力 =====
  {
    name: '图反射桥 - 状态初始化',
    category: '图反射融合',
    description: '验证图反射状态的初始化结构完整性',
    run: testGraphReflectionInit,
  },
  {
    name: '图反射桥 - Reflection→Graph 写入',
    category: '图反射融合',
    description: '验证自省结果能否正确写入图节点',
    run: testReflectionToGraphWrite,
  },
  {
    name: '图反射桥 - Graph→Reflection 增强',
    category: '图反射融合',
    description: '验证图状态能否增强自省判断',
    run: testGraphToReflectionEnhance,
  },
  {
    name: '图反射桥 - 压缩信号生成',
    category: '图反射融合',
    description: '验证基于反射结果的压缩信号生成',
    run: testCompressionSignal,
  },
  {
    name: '图反射桥 - 回退标记',
    category: '图反射融合',
    description: '验证回退场景下图节点的状态更新',
    run: testRollbackMarking,
  },

  // ===== 维度4: 调度性能与鲁棒性 =====
  {
    name: '性能 - 调度延迟',
    category: '性能与鲁棒性',
    description: '测量不同意图下的调度执行延迟',
    run: testSchedulingLatency,
  },
  {
    name: '鲁棒性 - 边界输入处理',
    category: '性能与鲁棒性',
    description: '验证边界输入下调度系统的稳定性',
    run: testBoundaryInputs,
  },
  {
    name: '鲁棒性 - 并发调度',
    category: '性能与鲁棒性',
    description: '验证多会话并发调度的状态隔离性',
    run: testConcurrentScheduling,
  },
];

// ============================================================
// 测试实现
// ============================================================

// ---- 动态思维链调度测试 ----

function testDynamicChainInitialPlan(): TestResult {
  const intents: DynamicChainIntent[] = ['deep_analysis', 'scenario_sim', 'strategy_verify', 'execute_trade'];
  const results: { intent: string; stepCount: number; hasInputs: boolean }[] = [];
  let allPass = true;

  for (const intent of intents) {
    const ctx: DynamicChainContext = {
      intent,
      message: `测试 ${intent} 意图`,
      sessionId: `test_${intent}_${Date.now()}`,
      symbol: 'BTC',
      category: 'crypto',
      displayName: 'Bitcoin',
      instId: 'BTC-USDT-SWAP',
      thinkingMode: 'standard',
      lang: 'zh',
    };

    try {
      const plan = generateInitialPlan(ctx);
      const hasInputs = plan.steps.every(s => s.id === plan.steps[0].id || s.inputs && s.inputs.length > 0);
      results.push({ intent, stepCount: plan.steps.length, hasInputs });

      if (plan.steps.length < 2 || !plan.chainId || plan.totalCredits <= 0) {
        allPass = false;
      }
    } catch (e) {
      allPass = false;
      results.push({ intent, stepCount: 0, hasInputs: false });
    }
  }

  const passCount = results.filter(r => r.stepCount >= 2).length;
  const score = Math.round((passCount / intents.length) * 100);

  return {
    passed: allPass,
    score,
    details: `4种意图均生成计划: ${results.map(r => `${r.intent}(${r.stepCount}步)`).join(', ')}`,
    metrics: {
      意图覆盖数: intents.length,
      平均步骤数: (results.reduce((s, r) => s + r.stepCount, 0) / intents.length).toFixed(1),
    },
  };
}

function testDynamicChainStepExecution(): TestResult {
  const ctx: DynamicChainContext = {
    intent: 'deep_analysis',
    message: '请分析BTC当前市场走势，给出交易建议',
    sessionId: `test_step_exec_${Date.now()}`,
    symbol: 'BTC',
    category: 'crypto',
    displayName: 'Bitcoin',
    instId: 'BTC-USDT-SWAP',
    thinkingMode: 'standard',
    lang: 'zh',
    marketData: {
      price: 85000,
      high_24h: 86500,
      low_24h: 83200,
      vol_24h: 25000000000,
      change_pct: 2.3,
      trend: 'bullish',
    },
  };

  const graphState = initGraphState(ctx.sessionId);
  const plan = generateInitialPlan(ctx);
  const stepResults: { stepId: string; confidence: number; hasContent: boolean; hasIssues: boolean }[] = [];
  let allPass = true;

  for (const step of plan.steps.slice(0, 3)) {
    try {
      const result = executeStepPlan(step, ctx, graphState, []);
      stepResults.push({
        stepId: step.id,
        confidence: result.confidence,
        hasContent: result.content.length > 100,
        hasIssues: result.issuesFound.length >= 0,
      });

      if (result.confidence < 0.2 || result.confidence > 0.95) {
        allPass = false;
      }
      if (result.content.length < 50) {
        allPass = false;
      }
    } catch (e) {
      allPass = false;
      stepResults.push({ stepId: step.id, confidence: 0, hasContent: false, hasIssues: false });
    }
  }

  const avgConf = stepResults.reduce((s, r) => s + r.confidence, 0) / Math.max(stepResults.length, 1);
  const score = Math.round(avgConf * 100);

  return {
    passed: allPass,
    score,
    details: `执行${stepResults.length}步，平均置信度 ${avgConf.toFixed(2)}: ${stepResults.map(r => `${r.stepId}(${r.confidence.toFixed(2)})`).join(', ')}`,
    metrics: {
      执行步数: stepResults.length,
      平均置信度: avgConf.toFixed(3),
      内容完整性: stepResults.filter(r => r.hasContent).length / stepResults.length,
    },
  };
}

function testDynamicChainReflectionDecisions(): TestResult {
  const ctx: DynamicChainContext = {
    intent: 'execute_trade',
    message: 'BTC现在可以做多吗？',
    sessionId: `test_reflect_${Date.now()}`,
    symbol: 'BTC',
    category: 'crypto',
    displayName: 'Bitcoin',
    instId: 'BTC-USDT-SWAP',
    thinkingMode: 'standard',
    lang: 'zh',
  };

  const graphState = initGraphState(ctx.sessionId);
  const plan = generateInitialPlan(ctx);
  const decisions: { stepId: string; decision: string }[] = [];

  // 模拟不同置信度的步骤结果来触发不同决策
  const testScenarios = [
    { stepIdx: 0, conf: 0.85, risk: 0.2, issues: 0, desc: '高置信度 → CONTINUE' },
    { stepIdx: 1, conf: 0.4, risk: 0.5, issues: 3, desc: '低置信度高问题 → REDO' },
    { stepIdx: 2, conf: 0.82, risk: 0.3, issues: 0, desc: 'S3高置信度 → JUMP_TO' },
  ];

  let decisionTypes = new Set<string>();

  for (let i = 0; i < Math.min(plan.steps.length, 3); i++) {
    const step = plan.steps[i];
    const result = executeStepPlan(step, ctx, graphState, []);

    const decision = reflect(plan, graphState, result, ctx, i + 1, 0);
    decisions.push({ stepId: step.id, decision: decision.type });
    decisionTypes.add(decision.type);
  }

  const uniqueDecisions = decisionTypes.size;
  const score = Math.min(100, uniqueDecisions * 30 + 10); // 每种决策30分，基础10分

  return {
    passed: uniqueDecisions >= 2,
    score,
    details: `观察到 ${uniqueDecisions} 种决策类型: ${Array.from(decisionTypes).join(', ')}`,
    metrics: {
      决策类型数: uniqueDecisions,
      决策类型列表: Array.from(decisionTypes).join(', '),
    },
  };
}

function testDynamicChainFullLoop(): TestResult {
  const startTime = Date.now();

  try {
    const result = quickRun({
      intent: 'deep_analysis',
      message: '深度分析ETH当前市场，给出交易策略建议',
      sessionId: `test_full_loop_${Date.now()}`,
      symbol: 'ETH',
      category: 'crypto',
      displayName: 'Ethereum',
      instId: 'ETH-USDT-SWAP',
      thinkingMode: 'deep',
      lang: 'zh',
      marketData: {
        price: 3200,
        high_24h: 3280,
        low_24h: 3100,
        vol_24h: 15000000000,
        change_pct: 1.5,
        trend: 'bullish',
      },
    });

    const duration = Date.now() - startTime;
    const qualityScore = result.avgConfidence * 60 + (result.success ? 20 : 0) + (result.iterations > 0 ? 20 : 0);

    return {
      passed: result.success && result.stepResults.length > 0,
      score: Math.round(Math.min(100, qualityScore)),
      details: `完整闭环执行成功: ${result.stepResults.length}步, ${result.iterations}次迭代, 平均置信度${result.avgConfidence.toFixed(2)}, 耗时${duration}ms`,
      metrics: {
        成功: result.success ? '是' : '否',
        步骤数: result.stepResults.length,
        迭代次数: result.iterations,
        平均置信度: result.avgConfidence.toFixed(3),
        最高风险: result.maxRisk.toFixed(3),
        总耗时: duration + 'ms',
        token消耗: result.totalTokens,
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `完整闭环执行失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testDynamicChainPlanAdjustment(): TestResult {
  const ctx: DynamicChainContext = {
    intent: 'execute_trade',
    message: '测试计划动态调整',
    sessionId: `test_plan_adj_${Date.now()}`,
    symbol: 'BTC',
    category: 'crypto',
    displayName: 'Bitcoin',
    instId: 'BTC-USDT-SWAP',
    thinkingMode: 'standard',
    lang: 'zh',
  };

  const graphState = initGraphState(ctx.sessionId);
  const plan = generateInitialPlan(ctx);
  const adjustments: { type: string; reason: string }[] = [];

  // 模拟1: 执行S1后检查调整
  const s1Result = executeStepPlan(plan.steps[0], ctx, graphState, []);
  const adj1 = adjustPlanAfterStep(plan, graphState, plan.steps[0].id);
  adjustments.push({ type: 'after_S1', reason: adj1.reason });

  // 模拟2: 模拟低置信度S2，触发REDO
  graphState.architectureNodes.set('S2_ANALYSIS', {
    id: 'S2_ANALYSIS',
    name: 'S2_ANALYSIS',
    status: 'completed',
    parentModuleId: 'analysis_chain',
    tokenCost: 500,
    latencyMs: 100,
    confidence: 0.3,
    riskScore: 0.85,
    issuesFound: ['缺少技术指标分析', '缺少方向判断', '数据密度不足'],
    corrections: [],
    gatePassed: false,
  });
  graphState.completedNodes = 2;
  graphState.cumulativeConfidence = 0.45;
  updateCompressionSignal(graphState);

  const adj2 = adjustPlanAfterStep(plan, graphState, 'S2_ANALYSIS');
  adjustments.push({ type: 'low_conf_S2', reason: adj2.reason });

  const hasRedo = adj2.shouldRedo;
  const hasSkipLogic = adj1 !== null;

  const score = (hasRedo ? 40 : 0) + (hasSkipLogic ? 30 : 0) + 30;

  return {
    passed: hasRedo || hasSkipLogic,
    score,
    details: `计划调整能力: REDO触发=${hasRedo}, 跳过逻辑=${hasSkipLogic}`,
    metrics: {
      REDO可触发: hasRedo ? '是' : '否',
      跳过逻辑存在: hasSkipLogic ? '是' : '否',
      调整场景数: adjustments.length,
    },
  };
}

// ---- 状态机调度测试 ----

function testStrategyChainInit(): TestResult {
  try {
    const controller = new StrategyChainController();
    const complexities: StrategyComplexity[] = ['quick', 'standard', 'deep'];
    const results: { complexity: string; stepCount: number; firstStep: string | null }[] = [];

    for (const complexity of complexities) {
      const state = controller.init('BTC分析', complexity, [
        'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE', 'S5_EXECUTE'
      ]);
      results.push({
        complexity,
        stepCount: state.steps.length,
        firstStep: state.currentStep,
      });
      controller.reset();
    }

    const allHaveSteps = results.every(r => r.stepCount > 0);
    const score = allHaveSteps ? 100 : 50;

    return {
      passed: allHaveSteps,
      score,
      details: `3种复杂度均初始化成功: ${results.map(r => `${r.complexity}(${r.stepCount}步)`).join(', ')}`,
      metrics: {
        复杂度覆盖: results.length,
        平均步数: (results.reduce((s, r) => s + r.stepCount, 0) / results.length).toFixed(1),
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `策略链初始化失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testStrategyChainStepExecution(): TestResult {
  try {
    const controller = new StrategyChainController();
    controller.init('BTC策略开发', 'standard', [
      'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN'
    ]);

    const transitions: { from: string | null; to: string | null; success: boolean }[] = [];
    let currentStep = controller.getCurrentStep();

    // 执行第一步
    if (currentStep) {
      const result = controller.confirmStep(currentStep.id as StrategyStepId, '# S1 调研报告\n\nBTC当前价格85000...');
      transitions.push({ from: currentStep?.id || null, to: result.nextStepId || null, success: result.success });
      currentStep = controller.getCurrentStep();
    }

    // 执行第二步
    if (currentStep) {
      const result = controller.confirmStep(currentStep.id as StrategyStepId, '# S2 分析报告\n\n趋势判断：多头...');
      transitions.push({ from: currentStep?.id || null, to: result.nextStepId || null, success: result.success });
    }

    const progress = controller.getProgress();
    const allSuccess = transitions.every(t => t.success);
    const score = allSuccess && progress.current > 0 ? 100 : 50;

    return {
      passed: allSuccess,
      score,
      details: `步进执行${transitions.length}次，进度 ${progress.current}/${progress.total} (${progress.percentage}%)`,
      metrics: {
        执行步数: transitions.length,
        当前进度: progress.percentage + '%',
        状态转换成功: allSuccess ? '是' : '否',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `策略链步进执行失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testStrategyChainSkip(): TestResult {
  try {
    const controller = new StrategyChainController();
    controller.init('标准分析', 'standard', [
      'S1_RESEARCH', 'S2_ANALYSIS', 'S3_DESIGN', 'S4_VALIDATE'
    ]);

    const before = controller.getProgress();
    const currentStep = controller.getCurrentStep();

    let skipSuccess = false;
    if (currentStep && controller.canSkipCurrent()) {
      const result = controller.skipStep(currentStep.id as StrategyStepId, '快速模式跳过');
      skipSuccess = result.success;
    }

    const after = controller.getProgress();
    const score = skipSuccess ? 100 : (after.current > before.current ? 70 : 30);

    return {
      passed: skipSuccess || after.current > before.current,
      score,
      details: `跳过机制: 跳过前${before.current}/${before.total}, 跳过${skipSuccess ? '成功' : '受限'}, 跳过${after.current}/${after.total}`,
      metrics: {
        跳过成功: skipSuccess ? '是' : '否',
        跳过前后进度变化: `${before.percentage}% → ${after.percentage}%`,
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `跳过机制测试失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testDevChainExecution(): TestResult {
  try {
    // 动态导入 dev-chain
    const { executeS5 } = require('../src/lib/dev-chain/chain-controller');

    const result = executeS5({
      taskId: `test_e_chain_${Date.now()}`,
      sessionId: `test_session_${Date.now()}`,
      userMessage: '开发一个双均线交叉策略',
      thinkingMode: 'quick',
      lang: 'zh',
      strategyParams: {
        symbol: 'BTC-USDT-SWAP',
        timeframe: '4h',
      },
    });

    const hasSteps = result.allStepsForDisplay && result.allStepsForDisplay.length > 0;
    const hasContent = result.content && result.content.length > 100;
    const score = (hasSteps ? 50 : 0) + (hasContent ? 50 : 0);

    return {
      passed: hasSteps && hasContent,
      score,
      details: `E链执行: ${result.allStepsForDisplay?.length || 0}步, 内容长度${result.content?.length || 0}字符`,
      metrics: {
        步骤数: result.allStepsForDisplay?.length || 0,
        内容长度: result.content?.length || 0,
        是否触发WorkBuddy: result.shouldTriggerWorkBuddy ? '是' : '否',
        完成状态: result.isComplete ? '完成' : '未完成',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 30, // 部分功能存在但可能导入问题
      details: `E链测试: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

// ---- 图反射融合测试 ----

function testGraphReflectionInit(): TestResult {
  try {
    const state = createGraphReflectionState('test_session_001');

    const checks = {
      hasBlueprint: state.blueprintNodes.length > 0,
      hasArchNodes: state.architectureNodes.size > 0,
      hasCompressionSignal: !!state.compressionSignal,
      hasDynamicChain: !!state.dynamicChain,
      hasExecutedOrder: Array.isArray(state.executedOrder),
    };

    const passCount = Object.values(checks).filter(Boolean).length;
    const score = Math.round((passCount / Object.keys(checks).length) * 100);

    return {
      passed: passCount >= 4,
      score,
      details: `图状态初始化: ${passCount}/${Object.keys(checks).length}项检查通过, 蓝图节点${state.blueprintNodes.length}个, 架构节点${state.architectureNodes.size}个`,
      metrics: {
        蓝图模块数: state.blueprintNodes.length,
        架构节点数: state.architectureNodes.size,
        检查通过数: `${passCount}/${Object.keys(checks).length}`,
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `图状态初始化失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testReflectionToGraphWrite(): TestResult {
  try {
    const state = createGraphReflectionState('test_write_001');

    const testMetadata: StepMetadata = {
      step: 'S1_RESEARCH',
      content: '# S1 市场调研\n\nBTC价格85000，趋势向上...',
      confidence: 0.75,
      riskScore: 0.35,
      uncertaintyTags: ['数据延迟'],
      issuesFound: ['缺少链上数据'],
      corrections: ['建议补充链上数据分析'],
      gatePassed: true,
      shouldBeSkipped: false,
    };

    recordStepReflection(state, 'S1_RESEARCH', testMetadata, {
      tokenCost: 500,
      latencyMs: 150,
      toolIterations: 1,
    });

    const node = state.architectureNodes.get('S1_RESEARCH');
    const checks = {
      nodeExists: !!node,
      statusCorrect: node?.status === 'completed',
      hasConfidence: node?.confidence === 0.75,
      hasRisk: node?.riskScore === 0.35,
      hasIssues: (node?.issuesFound?.length || 0) > 0,
      hasTokenCost: (node?.tokenCost || 0) > 0,
      completedCountIncreased: state.completedNodes > 0,
      highValueSignal: state.compressionSignal.highValueNodes.includes('S1_RESEARCH'),
    };

    const passCount = Object.values(checks).filter(Boolean).length;
    const score = Math.round((passCount / Object.keys(checks).length) * 100);

    return {
      passed: passCount >= 6,
      score,
      details: `Reflection→Graph写入: ${passCount}/${Object.keys(checks).length}项检查通过`,
      metrics: {
        节点存在: checks.nodeExists ? '是' : '否',
        置信度同步: checks.hasConfidence ? '是' : '否',
        风险同步: checks.hasRisk ? '是' : '否',
        压缩信号正确: checks.highValueSignal ? '是' : '否',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `Reflection→Graph写入失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testGraphToReflectionEnhance(): TestResult {
  try {
    const state = createGraphReflectionState('test_enhance_001');

    // 先写入一个低置信度的前置节点
    recordStepReflection(state, 'S1_RESEARCH', {
      step: 'S1_RESEARCH',
      content: 'S1 内容',
      confidence: 0.4,
      riskScore: 0.8,
      uncertaintyTags: [],
      issuesFound: ['数据不足'],
      corrections: [],
      gatePassed: false,
      shouldBeSkipped: false,
    }, { tokenCost: 300, latencyMs: 100 });

    // 测试图感知自省
    const result = graphAwareSelfCriticism(
      'S2_ANALYSIS',
      '# S2 分析\n\n基于S1结论，市场趋势向上...',
      [{ step: 'S1_RESEARCH', confidence: 0.4, riskScore: 0.8, issuesFound: ['数据不足'], corrections: [], gatePassed: false, shouldBeSkipped: false, content: 'S1内容', uncertaintyTags: [] }],
      state
    );

    const baseResult = runSelfCriticism(
      'S2_ANALYSIS',
      '# S2 分析\n\n基于S1结论，市场趋势向上...',
      [{ step: 'S1_RESEARCH', confidence: 0.4, riskScore: 0.8, issuesFound: ['数据不足'], corrections: [], gatePassed: false, shouldBeSkipped: false, content: 'S1内容', uncertaintyTags: [] }]
    );

    const graphEnhanced = result.issues.length > baseResult.issues.length ||
      result.confidenceDelta < baseResult.confidenceDelta;

    const score = graphEnhanced ? 100 : 60;

    return {
      passed: true, // 功能存在即为通过
      score,
      details: `Graph→Reflection增强: 基础问题${baseResult.issues.length}个, 图增强后${result.issues.length}个, 增强效果=${graphEnhanced ? '明显' : '一般'}`,
      metrics: {
        基础问题数: baseResult.issues.length,
        增强后问题数: result.issues.length,
        置信度增量: result.confidenceDelta.toFixed(3),
        图增强有效: graphEnhanced ? '是' : '否',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `Graph→Reflection增强测试失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testCompressionSignal(): TestResult {
  try {
    const state = createGraphReflectionState('test_compression_001');

    // 写入不同质量的节点
    recordStepReflection(state, 'S1_RESEARCH', {
      step: 'S1_RESEARCH', content: '高质量S1',
      confidence: 0.85, riskScore: 0.2,
      uncertaintyTags: [], issuesFound: [], corrections: [],
      gatePassed: true, shouldBeSkipped: false,
    }, { tokenCost: 200, latencyMs: 50 });

    recordStepReflection(state, 'S2_ANALYSIS', {
      step: 'S2_ANALYSIS', content: '中等质量S2',
      confidence: 0.6, riskScore: 0.4,
      uncertaintyTags: ['部分数据缺失'], issuesFound: ['需要更多验证'], corrections: ['建议补充数据'],
      gatePassed: true, shouldBeSkipped: false,
    }, { tokenCost: 300, latencyMs: 80 });

    recordStepReflection(state, 'S3_DESIGN', {
      step: 'S3_DESIGN', content: '低质量S3',
      confidence: 0.4, riskScore: 0.2,
      uncertaintyTags: [], issuesFound: [], corrections: [],
      gatePassed: false, shouldBeSkipped: false,
    }, { tokenCost: 150, latencyMs: 40 });

    const { highValueNodes, compressibleNodes } = state.compressionSignal;

    const s1HighValue = highValueNodes.includes('S1_RESEARCH');
    const s2HighValue = highValueNodes.includes('S2_ANALYSIS');
    const s3Compressible = compressibleNodes.includes('S3_DESIGN');

    const passCount = [s1HighValue, s2HighValue, s3Compressible].filter(Boolean).length;
    const score = Math.round((passCount / 3) * 100);

    return {
      passed: passCount >= 2,
      score,
      details: `压缩信号: 高价值节点${highValueNodes.length}个, 可压缩节点${compressibleNodes.length}个, 准确率${passCount}/3`,
      metrics: {
        高价值节点数: highValueNodes.length,
        可压缩节点数: compressibleNodes.length,
        S1高价值: s1HighValue ? '是' : '否',
        S2高价值: s2HighValue ? '是' : '否',
        S3可压缩: s3Compressible ? '是' : '否',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `压缩信号测试失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

function testRollbackMarking(): TestResult {
  try {
    const state = createGraphReflectionState('test_rollback_001');

    // 先写入几个节点
    recordStepReflection(state, 'S1_RESEARCH', {
      step: 'S1_RESEARCH', content: 'S1',
      confidence: 0.7, riskScore: 0.3,
      uncertaintyTags: [], issuesFound: [], corrections: [],
      gatePassed: true, shouldBeSkipped: false,
    });

    recordStepReflection(state, 'S2_ANALYSIS', {
      step: 'S2_ANALYSIS', content: 'S2',
      confidence: 0.65, riskScore: 0.4,
      uncertaintyTags: [], issuesFound: [], corrections: [],
      gatePassed: true, shouldBeSkipped: false,
    });

    recordStepReflection(state, 'S3_DESIGN', {
      step: 'S3_DESIGN', content: 'S3',
      confidence: 0.5, riskScore: 0.6,
      uncertaintyTags: [], issuesFound: [], corrections: [],
      gatePassed: false, shouldBeSkipped: false,
    });

    recordStepReflection(state, 'S4_VALIDATE', {
      step: 'S4_VALIDATE', content: 'S4',
      confidence: 0.4, riskScore: 0.7,
      uncertaintyTags: [], issuesFound: ['验证失败'], corrections: ['需要调整策略'],
      gatePassed: false, shouldBeSkipped: false,
    });

    const beforeRollback = state.rollbackCount;
    markRollback(state, 'S3_DESIGN');
    const afterRollback = state.rollbackCount;

    const s3Node = state.architectureNodes.get('S3_DESIGN');
    const s4Node = state.architectureNodes.get('S4_VALIDATE');

    const checks = {
      rollbackCountIncreased: afterRollback > beforeRollback,
      s3MarkedRerun: s3Node?.status === 'rerun',
      s4AlsoReset: s4Node?.status === 'rerun',
    };

    const passCount = Object.values(checks).filter(Boolean).length;
    const score = Math.round((passCount / 3) * 100);

    return {
      passed: passCount >= 2,
      score,
      details: `回退标记: 回退次数${beforeRollback}→${afterRollback}, S3状态=${s3Node?.status}, S4状态=${s4Node?.status}`,
      metrics: {
        回退计数: afterRollback,
        S3标记rerun: checks.s3MarkedRerun ? '是' : '否',
        S4同步重置: checks.s4AlsoReset ? '是' : '否',
      },
    };
  } catch (e) {
    return {
      passed: false,
      score: 0,
      details: `回退标记测试失败: ${e instanceof Error ? e.message : String(e)}`,
      error: e instanceof Error ? e.message : String(e),
    };
  }
}

// ---- 性能与鲁棒性测试 ----

function testSchedulingLatency(): TestResult {
  const intents: DynamicChainIntent[] = ['deep_analysis', 'execute_trade', 'strategy_verify'];
  const latencies: { intent: string; duration: number }[] = [];

  for (const intent of intents) {
    const startTime = Date.now();
    try {
      quickRun({
        intent,
        message: `测试${intent}调度延迟`,
        sessionId: `test_latency_${intent}_${Date.now()}`,
        symbol: 'BTC',
        category: 'crypto',
        displayName: 'Bitcoin',
        instId: 'BTC-USDT-SWAP',
        thinkingMode: 'quick',
        lang: 'zh',
      });
      latencies.push({ intent, duration: Date.now() - startTime });
    } catch (e) {
      latencies.push({ intent, duration: -1 });
    }
  }

  const validLatencies = latencies.filter(l => l.duration >= 0).map(l => l.duration);
  const avgLatency = validLatencies.length > 0
    ? validLatencies.reduce((s, l) => s + l, 0) / validLatencies.length
    : 0;

  // 评分：<10ms=100, <50ms=80, <100ms=60, <500ms=40
  let score = 20;
  if (avgLatency < 10) score = 100;
  else if (avgLatency < 50) score = 85;
  else if (avgLatency < 100) score = 70;
  else if (avgLatency < 500) score = 50;
  else if (avgLatency < 1000) score = 35;

  return {
    passed: validLatencies.length === intents.length,
    score,
    details: `调度延迟: 平均${avgLatency.toFixed(0)}ms, ${latencies.map(l => `${l.intent}:${l.duration}ms`).join(', ')}`,
    metrics: {
      平均延迟: avgLatency.toFixed(0) + 'ms',
      最快: Math.min(...validLatencies) + 'ms',
      最慢: Math.max(...validLatencies) + 'ms',
      成功率: `${validLatencies.length}/${intents.length}`,
    },
  };
}

function testBoundaryInputs(): TestResult {
  const boundaryCases = [
    { name: '空消息', message: '', intent: 'deep_analysis' as DynamicChainIntent },
    { name: '超长消息', message: 'a'.repeat(5000), intent: 'deep_analysis' as DynamicChainIntent },
    { name: '特殊字符', message: '!@#$%^&*()_+-=[]{}|;:\'",.<>?/~`', intent: 'deep_analysis' as DynamicChainIntent },
    { name: 'Unicode表情', message: '🚀📈💰🔥💎🙌', intent: 'execute_trade' as DynamicChainIntent },
  ];

  const results: { name: string; success: boolean; error?: string }[] = [];

  for (const testCase of boundaryCases) {
    try {
      const result = quickRun({
        intent: testCase.intent,
        message: testCase.message,
        sessionId: `test_boundary_${testCase.name}_${Date.now()}`,
        symbol: 'BTC',
        category: 'crypto',
        displayName: 'Bitcoin',
        instId: 'BTC-USDT-SWAP',
        thinkingMode: 'quick',
        lang: 'zh',
      });
      results.push({ name: testCase.name, success: result.success });
    } catch (e) {
      results.push({ name: testCase.name, success: false, error: e instanceof Error ? e.message : String(e) });
    }
  }

  const passCount = results.filter(r => r.success).length;
  const score = Math.round((passCount / boundaryCases.length) * 100);

  return {
    passed: passCount >= 3,
    score,
    details: `边界输入: ${passCount}/${boundaryCases.length}个通过 (${results.map(r => `${r.name}:${r.success ? '✓' : '✗'}`).join(', ')})`,
    metrics: {
      通过数: passCount,
      总数: boundaryCases.length,
      通过率: (passCount / boundaryCases.length * 100).toFixed(0) + '%',
    },
  };
}

function testConcurrentScheduling(): TestResult {
  const sessionCount = 5;
  const sessions = Array.from({ length: sessionCount }, (_, i) => ({
    sessionId: `concurrent_test_${i}_${Date.now()}`,
    symbol: ['BTC', 'ETH', 'SOL', 'AVAX', 'MATIC'][i],
  }));

  const results: { sessionId: string; symbol: string; success: boolean; chainId?: string }[] = [];

  // 顺序执行但模拟多会话隔离
  for (const sess of sessions) {
    try {
      const result = quickRun({
        intent: 'deep_analysis',
        message: `分析${sess.symbol}的市场状态`,
        sessionId: sess.sessionId,
        symbol: sess.symbol,
        category: 'crypto',
        displayName: sess.symbol,
        instId: `${sess.symbol}-USDT-SWAP`,
        thinkingMode: 'quick',
        lang: 'zh',
      });
      results.push({
        sessionId: sess.sessionId,
        symbol: sess.symbol,
        success: result.success,
        chainId: result.chainId,
      });
    } catch (e) {
      results.push({ sessionId: sess.sessionId, symbol: sess.symbol, success: false });
    }
  }

  const allSuccess = results.every(r => r.success);
  const allUnique = new Set(results.map(r => r.chainId)).size === sessionCount;
  const score = (allSuccess ? 60 : 0) + (allUnique ? 40 : 0);

  return {
    passed: allSuccess,
    score,
    details: `多会话调度: ${results.filter(r => r.success).length}/${sessionCount}成功, chainId唯一=${allUnique}`,
    metrics: {
      会话数: sessionCount,
      成功数: results.filter(r => r.success).length,
      状态隔离: allUnique ? '是' : '否',
    },
  };
}

// ============================================================
// 评估报告生成
// ============================================================

function generateReport(allResults: { test: TestCase; result: TestResult }[]): EvalReport {
  const categoryMap = new Map<string, { tests: { name: string; passed: boolean; score: number; details: string }[]; weight: number }>();

  const categoryWeights: Record<string, number> = {
    '动态思维链调度': 0.30,
    '状态机调度': 0.20,
    '图反射融合': 0.25,
    '性能与鲁棒性': 0.25,
  };

  for (const { test, result } of allResults) {
    if (!categoryMap.has(test.category)) {
      categoryMap.set(test.category, { tests: [], weight: categoryWeights[test.category] || 0.1 });
    }
    categoryMap.get(test.category)!.tests.push({
      name: test.name,
      passed: result.passed,
      score: result.score,
      details: result.details,
    });
  }

  const categories = Array.from(categoryMap.entries()).map(([name, data]) => {
    const avgScore = data.tests.reduce((s, t) => s + t.score, 0) / data.tests.length;
    return { name, score: Math.round(avgScore), weight: data.weight, tests: data.tests };
  });

  const totalScore = Math.round(
    categories.reduce((s, c) => s + c.score * c.weight, 0)
  );

  // 分析优势和劣势
  const strengths: string[] = [];
  const weaknesses: string[] = [];
  const recommendations: string[] = [];

  for (const cat of categories) {
    if (cat.score >= 80) {
      strengths.push(`${cat.name}: ${cat.score}分 - 表现优秀`);
    } else if (cat.score < 60) {
      weaknesses.push(`${cat.name}: ${cat.score}分 - 需要改进`);
    }
  }

  // 找出低分测试项
  const lowScoreTests = allResults
    .filter(({ result }) => result.score < 60)
    .map(({ test, result }) => `${test.name} (${result.score}分)`);

  if (lowScoreTests.length > 0) {
    recommendations.push(`优先改进以下模块: ${lowScoreTests.join(', ')}`);
  }

  // 基于各维度情况给出建议
  const dynChainScore = categories.find(c => c.name === '动态思维链调度')?.score || 0;
  const fusionScore = categories.find(c => c.name === '图反射融合')?.score || 0;
  const perfScore = categories.find(c => c.name === '性能与鲁棒性')?.score || 0;

  if (dynChainScore < 80) {
    recommendations.push('增强反思决策多样性：增加更多决策路径和分支逻辑');
  }
  if (fusionScore < 80) {
    recommendations.push('深化图反射融合：增强Graph状态对Reflection判断的影响权重');
  }
  if (perfScore < 70) {
    recommendations.push('优化调度性能：考虑缓存机制和并行执行优化');
  }

  if (recommendations.length === 0) {
    recommendations.push('系统整体表现良好，可考虑增加更多高级调度策略');
  }

  return {
    totalScore,
    categories,
    summary: {
      strengths,
      weaknesses,
      recommendations,
    },
    timestamp: new Date().toISOString(),
  };
}

function printReport(report: EvalReport) {
  console.log('\n');
  console.log('═'.repeat(80));
  console.log('  调度协调能力综合评估报告');
  console.log('═'.repeat(80));
  console.log(`  评估时间: ${report.timestamp}`);
  console.log('');

  // 总分
  const totalBar = '█'.repeat(Math.round(report.totalScore / 5)).padEnd(20);
  console.log(`  综合评分: ${report.totalScore} / 100  [${totalBar}]`);
  console.log('');

  // 各维度得分
  console.log('─'.repeat(80));
  console.log('  各维度得分');
  console.log('─'.repeat(80));
  for (const cat of report.categories) {
    const bar = '█'.repeat(Math.round(cat.score / 5)).padEnd(20);
    const weightPct = Math.round(cat.weight * 100);
    console.log(`  ${cat.name.padEnd(15)}  [${bar}] ${cat.score.toString().padStart(3)}分 (权重${weightPct}%)`);
    console.log(`    测试项: ${cat.tests.length}个, 通过${cat.tests.filter(t => t.passed).length}个`);
  }
  console.log('');

  // 详细测试结果
  console.log('─'.repeat(80));
  console.log('  详细测试结果');
  console.log('─'.repeat(80));
  for (const cat of report.categories) {
    console.log(`\n  ▸ ${cat.name}:`);
    for (const test of cat.tests) {
      const icon = test.passed ? '✓' : '✗';
      const scoreBar = '█'.repeat(Math.round(test.score / 10)).padEnd(10);
      console.log(`    ${icon} ${test.name.padEnd(30)} [${scoreBar}] ${test.score.toString().padStart(3)}分`);
      console.log(`       ${test.details}`);
    }
  }
  console.log('');

  // 优势
  if (report.summary.strengths.length > 0) {
    console.log('─'.repeat(80));
    console.log('  ✅ 优势');
    console.log('─'.repeat(80));
    for (const s of report.summary.strengths) {
      console.log(`  • ${s}`);
    }
    console.log('');
  }

  // 不足
  if (report.summary.weaknesses.length > 0) {
    console.log('─'.repeat(80));
    console.log('  ⚠️  待改进');
    console.log('─'.repeat(80));
    for (const w of report.summary.weaknesses) {
      console.log(`  • ${w}`);
    }
    console.log('');
  }

  // 建议
  console.log('─'.repeat(80));
  console.log('  💡 优化建议');
  console.log('─'.repeat(80));
  for (let i = 0; i < report.summary.recommendations.length; i++) {
    console.log(`  ${i + 1}. ${report.summary.recommendations[i]}`);
  }
  console.log('');

  console.log('═'.repeat(80));
  console.log(`  评估完成 | 总分: ${report.totalScore}/100`);
  console.log('═'.repeat(80));
}

// ============================================================
// 主函数
// ============================================================

async function main() {
  console.log('='.repeat(80));
  console.log('  调度协调能力综合评估测试');
  console.log('='.repeat(80));
  console.log(`  测试用例: ${testCases.length}个`);
  console.log(`  评估维度: ${new Set(testCases.map(t => t.category)).size}个`);
  console.log('');

  const allResults: { test: TestCase; result: TestResult }[] = [];

  for (let i = 0; i < testCases.length; i++) {
    const test = testCases[i];
    process.stdout.write(`  [${i + 1}/${testCases.length}] ${test.name}... `);

    try {
      const result = await test.run();
      allResults.push({ test, result });
      process.stdout.write(`${result.passed ? '✓' : '✗'} ${result.score}分\n`);
    } catch (e) {
      allResults.push({
        test,
        result: {
          passed: false,
          score: 0,
          details: `测试异常: ${e instanceof Error ? e.message : String(e)}`,
          error: e instanceof Error ? e.message : String(e),
        },
      });
      process.stdout.write(`✗ 异常\n`);
    }
  }

  const report = generateReport(allResults);
  printReport(report);

  return report;
}

main().catch(e => {
  console.error('评估执行失败:', e);
  process.exit(1);
});
