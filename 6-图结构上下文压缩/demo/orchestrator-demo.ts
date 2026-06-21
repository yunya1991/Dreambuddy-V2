/**
 * 编排器演示脚本
 *
 * 位置: 6-图结构上下文压缩/demo/orchestrator-demo.ts
 *
 * 演示如何使用双维度编排架构
 */

import {
  // 类型
  ExecutionContext,
  PlannerContext,
  SkillCapability,
  SkillResult,
  createSuccessResult,
  createFailureResult,
  createDefaultContext,

  // 注册表
  SkillsRegistry,
  getSkillsRegistry,

  // 规划器
  ExecutionPlanner,
  orchestrate,

  // 评估器
  getConfidenceEvaluator,

  // 投票计算器
  VotingCalculator,
  getVotingCalculator,

  // 交叉验证器
  getCrossValidator,
} from '../planner';

// ============================================================
// 模拟技能实现
// ============================================================

/**
 * 创建模拟技能
 */
function createMockSkill(
  id: string,
  name: string,
  outputs: Record<string, unknown>,
  confidence: number = 75
): SkillCapability {
  return {
    metadata: {
      id,
      name,
      description: `Mock skill: ${name}`,
      chain: 'A',
      category: 'execution',
      version: '1.0.0',
      tags: ['mock'],
      estimatedTokens: 200,
      estimatedLatencyMs: 1000,
      confidenceRange: [confidence - 10, confidence + 10],
      applicableIntents: ['deep_analysis', 'execute_trade'],
      applicableStages: ['analysis', 'design'],
    },
    inputSchema: [],
    outputSchema: [],

    async execute(_inputs: Record<string, unknown>, _context: ExecutionContext): Promise<SkillResult> {
      // 模拟执行延迟
      await new Promise(resolve => setTimeout(resolve, 100));

      return createSuccessResult(id, outputs, confidence);
    },
  };
}

// ============================================================
// 演示1: 基本使用
// ============================================================

async function demoBasic() {
  console.log('\n========================================');
  console.log('演示1: 基本编排流程');
  console.log('========================================\n');

  // 创建规划器
  const planner = new ExecutionPlanner();

  // 执行编排
  const result = await planner.execute({
    sessionId: 'demo_session_001',
    userRequest: 'BTC 下周应该怎么操作？',
    intent: 'deep_analysis',
    symbol: 'BTC',
    tradingMode: 'hybrid',
    complexity: 'standard',
    chainWeights: {
      s_chain: 0.35,
      c_chain: 0.45,
      f_chain: 0.20,
    },
  });

  // 输出结果
  console.log('执行结果:');
  console.log(`  成功: ${result.success}`);
  console.log(`  计划ID: ${result.planId}`);
  console.log(`  总体置信度: ${result.overallConfidence}%`);
  console.log(`  总Token消耗: ${result.totalTokensUsed}`);
  console.log(`  总延迟: ${result.totalLatencyMs}ms`);
  console.log('');

  console.log('执行的步骤:');
  for (const step of result.steps) {
    console.log(`  ${step.stepId}: ${step.label || step.stepId}`);
    console.log(`    置信度: ${step.confidence}%`);
    console.log(`    决策: ${step.decision}`);
    console.log(`    调用技能: ${step.skillsCalled.map(s => s.skillName).join(', ') || '无'}`);
    console.log('');
  }

  if (result.conclusion) {
    console.log('最终结论:');
    console.log(`  方向: ${result.conclusion.direction}`);
    console.log(`  置信度: ${result.conclusion.confidence}%`);
    console.log(`  参与链: ${result.conclusion.participatingChains.join(', ')}`);
  }
}

// ============================================================
// 演示2: 技能注册表
// ============================================================

async function demoRegistry() {
  console.log('\n========================================');
  console.log('演示2: 技能注册表');
  console.log('========================================\n');

  const registry = new SkillsRegistry();

  // 注册模拟技能
  registry.register(createMockSkill(
    'dream-regime-detector',
    '市场状态识别',
    { direction: 'long', confidence: 80, regime: 'trending' },
    80
  ));

  registry.register(createMockSkill(
    'dream-signal-scoring-spec',
    '信号评分',
    { direction: 'long', score: 62, signals: ['rsi_bullish', 'macd_bullish'] },
    75
  ));

  registry.register(createMockSkill(
    'dream-risk-position-sizing',
    '仓位风险',
    { direction: 'neutral', position: 0.5, risk: 'medium' },
    70
  ));

  // 查询技能
  console.log('所有注册的技能:');
  const allSkills = registry.getManifest();
  for (const skill of allSkills) {
    console.log(`  - ${skill.id}: ${skill.name}`);
    console.log(`    链: ${skill.chain}, 分类: ${skill.category}`);
    console.log(`    预估Token: ${skill.estimatedTokens}, 延迟: ${skill.estimatedLatencyMs}ms`);
  }
  console.log('');

  // 推荐技能
  const context = createDefaultContext('demo_session');
  context.intent = 'analysis';
  context.symbol = 'BTC';

  console.log('基于上下文推荐的技能:');
  const recommendations = registry.recommend(context);
  for (const rec of recommendations.slice(0, 3)) {
    console.log(`  - ${rec.skill.metadata.id} (得分: ${rec.score.toFixed(2)})`);
    console.log(`    原因: ${rec.reason}`);
  }
}

// ============================================================
// 演示3: 置信度评估
// ============================================================

async function demoConfidence() {
  console.log('\n========================================');
  console.log('演示3: 置信度评估');
  console.log('========================================\n');

  const evaluator = getConfidenceEvaluator();

  // 模拟技能结果
  const skillResults: SkillResult[] = [
    createSuccessResult('skill1', { direction: 'long', analysis: '市场呈上涨趋势' }, 85),
    createSuccessResult('skill2', { direction: 'long', regime: 'trending' }, 78),
    createSuccessResult('skill3', { direction: 'neutral', risk: 'medium' }, 65),
  ];

  // 评估置信度
  const evaluation = evaluator.evaluate(skillResults, {
    id: 'S2',
    stage: 'analysis',
    chain: 'S',
    label: 'S2_分析',
    icon: '🧠',
    description: '多维度分析',
    coreQuestion: '这意味着什么？',
    expectedOutputs: ['分析结论', '信号强度', '风险评级'],
    confidenceThresholds: { high: 80, medium: 50, low: 30 },
  }, createDefaultContext('demo'));

  console.log('置信度评估结果:');
  console.log(`  综合置信度: ${evaluation.overallScore}%`);
  console.log('');
  console.log('分项评分:');
  console.log(`  数据完整性: ${evaluation.dimensions.dataCompleteness}%`);
  console.log(`  逻辑一致性: ${evaluation.dimensions.logicalConsistency}%`);
  console.log(`  跨源印证: ${evaluation.dimensions.crossValidation}%`);
  console.log(`  历史准确率: ${evaluation.dimensions.historicalPerformance}%`);
  console.log('');
  console.log('决策:', evaluation.recommendation);
  console.log('原因:', evaluation.reason);
  console.log('');

  if (evaluation.gaps.length > 0) {
    console.log('识别的缺口:');
    for (const gap of evaluation.gaps) {
      console.log(`  [${gap.priority}] ${gap.type}: ${gap.description}`);
      console.log(`    建议: ${gap.suggestion}`);
    }
  }
}

// ============================================================
// 演示4: 投票计算
// ============================================================

async function demoVoting() {
  console.log('\n========================================');
  console.log('演示4: 三链投票');
  console.log('========================================\n');

  const calculator = getVotingCalculator();

  // 模拟三链信号
  const signals = [
    { chain: 'S' as const, direction: 'long' as const, confidence: 82, reasoning: 'AI分析看多' },
    { chain: 'C' as const, direction: 'long' as const, confidence: 75, reasoning: '技术指标看多' },
    { chain: 'F' as const, direction: 'neutral' as const, confidence: 60, reasoning: '基本面中性' },
  ];

  // 计算投票
  const result = calculator.calculate(signals);

  console.log('投票结果:');
  console.log(`  共识方向: ${result.direction}`);
  console.log(`  综合置信度: ${result.overallConfidence}%`);
  console.log(`  一致性等级: ${result.agreementLevel}`);
  console.log('');

  console.log('投票详情:');
  for (const vote of result.votes) {
    console.log(`  ${vote.chain}链: 权重 ${(vote.weight * 100).toFixed(0)}%, 置信度 ${vote.rawConfidence}%, 加权贡献 ${vote.weightedContribution.toFixed(3)}`);
  }
  console.log('');

  if (result.conflicts.length > 0) {
    console.log('检测到的冲突:');
    for (const conflict of result.conflicts) {
      console.log(`  [${conflict.type}] ${conflict.description}`);
      console.log(`    涉及链: ${conflict.involvedChains.join(', ')}`);
      console.log(`    解决方案: ${conflict.resolution}`);
    }
  }
}

// ============================================================
// 主函数
// ============================================================

async function main() {
  console.log('╔══════════════════════════════════════════════════════════╗');
  console.log('║     双维度编排架构 (Dual-Dimension Orchestration)        ║');
  console.log('║     演示脚本                                           ║');
  console.log('╚══════════════════════════════════════════════════════════╝');

  try {
    await demoRegistry();
    await demoConfidence();
    await demoVoting();
    await demoBasic();

    console.log('\n========================================');
    console.log('演示完成!');
    console.log('========================================\n');
  } catch (error) {
    console.error('演示出错:', error);
  }
}

// 运行演示
main().catch(console.error);
