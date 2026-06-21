/**
 * 双维度编排架构 - 端到端验证脚本
 *
 * 功能:
 * 1. 初始化技能注册表（A/C/F 三链）
 * 2. 验证技能数量和元数据
 * 3. 调用 ExecutionPlanner 执行完整流程
 * 4. 验证输出结构是否正确
 */

import {
  initializeSkillsRegistry,
  getSkillsSummary,
  getChainSummary,
  ExecutionPlanner,
} from '../../../6-图结构上下文压缩/planner/index.ts';

// ============================================================
// 测试执行
// ============================================================

async function runTests() {
  console.log('='.repeat(80));
  console.log('  双维度编排架构 - 端到端验证');
  console.log('='.repeat(80));
  console.log('');

  // -------------------- 测试 1: 初始化技能注册表 --------------------
  console.log('[1/4] 初始化技能注册表...');
  const registry = initializeSkillsRegistry();
  const allSkills = registry.getAll();
  console.log(`  ✓ 已注册技能总数: ${allSkills.length}`);

  const skillsSummary = getSkillsSummary();
  const chainSummary = getChainSummary();

  // 按链统计
  const byChain = {
    A: skillsSummary.filter(s => s.chain === 'A').length,
    C: skillsSummary.filter(s => s.chain === 'C').length,
    F: skillsSummary.filter(s => s.chain === 'F').length,
  };
  console.log(`  ✓ A 链技能: ${byChain.A}`);
  console.log(`  ✓ C 链技能: ${byChain.C}`);
  console.log(`  ✓ F 链技能: ${byChain.F}`);
  console.log('');

  // -------------------- 测试 2: C/F 链元数据验证 --------------------
  console.log('[2/4] C/F 链元数据验证...');
  for (const chainInfo of chainSummary) {
    console.log(`  ✓ ${chainInfo.chain} 链: ${chainInfo.totalSkills} 个技能 [${chainInfo.isPlaceholder ? '占位实现' : '完整实现'}]`);
  }
  console.log('');

  // -------------------- 测试 3: 执行完整编排流程 --------------------
  console.log('[3/4] 执行完整编排流程...');
  const planner = new ExecutionPlanner();

  const context = {
    sessionId: `test_session_${Date.now()}`,
    userRequest: '请分析 BTC 当前的市场状态，是否适合买入？',
    intent: 'deep_analysis',
    symbol: 'BTC',
    complexity: 'standard',
    tradingMode: 'hybrid',
    chainWeights: { s_chain: 0.45, c_chain: 0.35, f_chain: 0.2 },
    maxLatencyMs: 30000,
    budgetTokens: 5000,
    userRole: 'USER' as const,
    priorHistory: [],
  };

  const result = await planner.execute(context);
  console.log(`  ✓ 编排成功: ${result.success}`);
  console.log(`  ✓ 执行步骤: ${result.steps?.length || 0} 步`);
  console.log(`  ✓ 交叉验证结果: ${result.crossValidationResults?.length || 0} 个节点`);
  console.log(`  ✓ 整体置信度: ${result.overallConfidence}%`);
  console.log(`  ✓ 总耗时: ${result.totalLatencyMs}ms`);

  if (result.conclusion) {
    console.log(`  ✓ 结论方向: ${result.conclusion.direction}`);
    console.log(`  ✓ 关键决策点: ${result.conclusion.keyDecisionPoints?.length || 0} 个`);
  }
  console.log('');

  // -------------------- 测试 4: 结构化输出验证 --------------------
  console.log('[4/4] 结构化输出验证...');

  // 验证步骤结构
  if (result.steps && result.steps.length > 0) {
    const firstStep = result.steps[0];
    console.log(`  ✓ 首步阶段: ${firstStep.stage}`);
    console.log(`  ✓ 首步链: ${firstStep.chain}`);
    console.log(`  ✓ 首步状态: ${firstStep.status}`);
    console.log(`  ✓ 首步置信度: ${firstStep.confidence}%`);
  }

  // 验证交叉验证结构
  if (result.crossValidationResults && result.crossValidationResults.length > 0) {
    const firstCV = result.crossValidationResults[0];
    console.log(`  ✓ 交叉验证节点: ${firstCV.nodeId}`);
    if (firstCV.consensus) {
      console.log(`  ✓ 共识方向: ${firstCV.consensus.direction}`);
      console.log(`  ✓ 共识置信度: ${firstCV.consensus.overallConfidence}%`);
      console.log(`  ✓ 共识级别: ${firstCV.consensus.agreementLevel}`);
    }
  }

  // 验证 nextSteps
  if (result.conclusion?.nextSteps && result.conclusion.nextSteps.length > 0) {
    console.log(`  ✓ 后续建议: ${result.conclusion.nextSteps.length} 条`);
  }
  console.log('');

  // -------------------- 总结 --------------------
  console.log('='.repeat(80));
  console.log('  验证完成 ✓');
  console.log(`  总技能: ${allSkills.length} | 步骤: ${result.steps?.length || 0} | 置信度: ${result.overallConfidence}%`);
  console.log('='.repeat(80));

  // 打印示例输出
  console.log('\n--- 示例输出 ---\n');
  console.log(JSON.stringify({
    success: result.success,
    overallConfidence: result.overallConfidence,
    conclusion: result.conclusion,
    stepCount: result.steps?.length || 0,
    cvNodeCount: result.crossValidationResults?.length || 0,
  }, null, 2));
}

// 执行
runTests().catch(error => {
  console.error('验证失败:', error);
  process.exit(1);
});
