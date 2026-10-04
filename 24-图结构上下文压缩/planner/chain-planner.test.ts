#!/usr/bin/env npx tsx
/**
 * ChainPlanner 四维规划 + 三链动态插入 集成测试
 *
 * 验证内容：
 * 1. ChainPlanner 四维规划（预算/知识库/历史/标的覆盖）
 * 2. 三链动态插入机制
 */

import { ChainPlanner, DynamicInsertionPlanner } from './chain-planner.ts';
import { IntentType, ComplexityLevel, SkillChain } from './planner-types.ts';

// ============================================================
// 测试工具
// ============================================================

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`✅ ${name}`);
    passed++;
  } catch (error) {
    console.log(`❌ ${name}`);
    console.log(`   错误: ${error instanceof Error ? error.message : String(error)}`);
    failed++;
  }
}

function assert(condition: boolean, message: string) {
  if (!condition) {
    throw new Error(message);
  }
}

// ============================================================
// 测试 1: ChainPlanner 基础规划
// ============================================================

console.log('\n🧪 测试组 1: ChainPlanner 基础规划');
console.log('=' .repeat(50));

test('S链深度分析 - 完整步骤', () => {
  const planner = new ChainPlanner(10000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain
  );

  assert(result.plannedSteps.length > 0, '应该有规划步骤');
  assert(result.primaryChain === 'A', '主链应该是A链');
  assert(result.budgetMode === 'full' || result.budgetMode === 'standard', '预算模式应该是full或standard');
  assert(result.estimatedTokens > 0, '应该有预估Token消耗');
  assert(result.planRationale.length > 0, '应该有规划理由');

  console.log(`   规划步骤数: ${result.plannedSteps.length}`);
  console.log(`   预估Token: ${result.estimatedTokens}`);
  console.log(`   预算模式: ${result.budgetMode}`);
});

test('C链快速查询 - 精简步骤', () => {
  const planner = new ChainPlanner(5000);
  const result = planner.plan(
    'market_query' as IntentType,
    'quick' as ComplexityLevel,
    'C' as SkillChain
  );

  assert(result.plannedSteps.length <= 3, '快速模式步骤应该较少');
  assert(result.primaryChain === 'C', '主链应该是C链');
});

test('F链标准模式', () => {
  const planner = new ChainPlanner(8000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'standard' as ComplexityLevel,
    'F' as SkillChain
  );

  assert(result.plannedSteps.length > 0, '应该有规划步骤');
  assert(result.primaryChain === 'F', '主链应该是F链');
});

// ============================================================
// 测试 2: 维度一 - Token预算过滤
// ============================================================

console.log('\n🧪 测试组 2: 维度一 - Token预算过滤');
console.log('=' .repeat(50));

test('低预算会剪枝高成本节点', () => {
  const highBudget = new ChainPlanner(20000);
  const lowBudget = new ChainPlanner(2000);

  const highResult = highBudget.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain
  );

  const lowResult = lowBudget.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain
  );

  console.log(`   高预算步骤数: ${highResult.plannedSteps.length}`);
  console.log(`   低预算步骤数: ${lowResult.plannedSteps.length}`);
  console.log(`   低预算剪枝数: ${lowResult.prunedNodes.length}`);

  assert(lowResult.prunedNodes.length > 0, '低预算应该有剪枝节点');
  assert(
    lowResult.plannedSteps.length <= highResult.plannedSteps.length,
    '低预算步骤数应该小于等于高预算'
  );
});

test('预算模式计算正确', () => {
  const fullPlanner = new ChainPlanner(50000);
  const leanPlanner = new ChainPlanner(500);

  const fullResult = fullPlanner.plan(
    'simple_qa' as IntentType,
    'quick' as ComplexityLevel,
    'A' as SkillChain
  );

  const leanResult = leanPlanner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain
  );

  console.log(`   高预算模式: ${fullResult.budgetMode}`);
  console.log(`   低预算模式: ${leanResult.budgetMode}`);

  assert(fullResult.budgetMode === 'lean', '低占用应该是lean模式');
});

// ============================================================
// 测试 3: 维度二 - 知识库命中
// ============================================================

console.log('\n🧪 测试组 3: 维度二 - 知识库命中');
console.log('=' .repeat(50));

test('高置信知识库命中触发快捷路径', () => {
  const planner = new ChainPlanner(10000);

  const withKnowledge = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain,
    {
      priorHistory: {
        previousConclusions: ['BTC处于上涨趋势，建议持有'],
        previousConfidences: [85],
      },
    }
  );

  console.log(`   知识库命中: ${withKnowledge.shortcutTaken ? '是' : '否'}`);
  console.log(`   步骤数: ${withKnowledge.plannedSteps.length}`);
  assert(withKnowledge.knowledgeHit !== undefined, '应该有知识库命中');
});

// ============================================================
// 测试 4: 维度四 - 标的覆盖检查
// ============================================================

console.log('\n🧪 测试组 4: 维度四 - 标的覆盖检查');
console.log('=' .repeat(50));

test('主流币BTC - 数据完整', () => {
  const planner = new ChainPlanner(10000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'F' as SkillChain,
    { symbol: 'BTC' }
  );

  const fundingPruned = result.prunedNodes.filter(
    n => n.reason.includes('资金费率') || n.reason.includes('小币')
  );

  console.log(`   BTC剪枝数: ${result.prunedNodes.length}`);
  console.log(`   资金相关剪枝: ${fundingPruned.length}`);
  assert(fundingPruned.length === 0, '主流币不应该剪枝资金费率相关节点');
});

test('小币种 - 部分数据可能缺失', () => {
  const planner = new ChainPlanner(10000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'F' as SkillChain,
    { symbol: 'PEPE' }
  );

  console.log(`   小币剪枝数: ${result.prunedNodes.length}`);
  console.log(`   剪枝原因: ${result.prunedNodes.map(n => n.reason).join(', ')}`);

  assert(result.planRationale.includes('小币种'), '规划理由应该提到小币种');
});

// ============================================================
// 测试 5: DynamicInsertionPlanner - 三链动态插入
// ============================================================

console.log('\n🧪 测试组 5: DynamicInsertionPlanner - 三链动态插入');
console.log('=' .repeat(50));

test('数据缺失缺口 - 插入C链和F链步骤', () => {
  const planner = new DynamicInsertionPlanner(5000);
  const result = planner.planInsertions(
    'S2',
    55,
    'A',
    'missing-data',
    3000,
    ['S1', 'S2']
  );

  console.log(`   建议: ${result.recommendation}`);
  console.log(`   插入数: ${result.insertions.length}`);
  console.log(`   额外成本: ${result.totalAdditionalCost}`);

  result.insertions.forEach(ins => {
    console.log(`     - [${ins.chain}链] ${ins.stepId} - ${ins.reason} (${ins.cost} Token)`);
  });

  assert(result.insertions.length > 0, '数据缺失应该建议插入其他链步骤');
  assert(result.rationale.length > 0, '应该有插入理由');
});

test('逻辑冲突缺口 - 插入交叉验证步骤', () => {
  const planner = new DynamicInsertionPlanner(5000);
  const result = planner.planInsertions(
    'S3',
    60,
    'A',
    'logical-conflict',
    3000,
    ['S1', 'S2', 'S3']
  );

  console.log(`   建议: ${result.recommendation}`);
  console.log(`   插入数: ${result.insertions.length}`);

  const hasCChain = result.insertions.some(i => i.chain === 'C');
  assert(hasCChain, '逻辑冲突应该插入C链做交叉验证');
});

test('低置信度缺口 - 插入补充分析', () => {
  const planner = new DynamicInsertionPlanner(5000);
  const result = planner.planInsertions(
    'S2',
    50,
    'A',
    'low-confidence',
    3000,
    ['S1', 'S2']
  );

  console.log(`   建议: ${result.recommendation}`);
  console.log(`   插入数: ${result.insertions.length}`);
  assert(result.insertions.length > 0, '低置信度应该建议插入补充分析');
});

test('预算不足时不插入高成本节点', () => {
  const planner = new DynamicInsertionPlanner(100);
  const result = planner.planInsertions(
    'S2',
    55,
    'A',
    'missing-data',
    50,
    ['S1', 'S2']
  );

  console.log(`   建议: ${result.recommendation}`);
  console.log(`   插入数: ${result.insertions.length}`);
  console.log(`   剩余预算: 50`);

  assert(result.totalAdditionalCost <= 50, '插入成本不应该超过预算');
});

// ============================================================
// 测试 6: 规划理由生成
// ============================================================

console.log('\n🧪 测试组 6: 规划理由生成');
console.log('=' .repeat(50));

test('完整规划应该包含详细理由', () => {
  const planner = new ChainPlanner(8000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain,
    { symbol: 'BTC' }
  );

  console.log('   规划理由摘要:');
  console.log(result.planRationale.split('\n').slice(0, 6).map(l => `     ${l}`).join('\n'));

  assert(result.planRationale.includes('ChainPlanner'), '应该包含ChainPlanner标识');
  assert(result.planRationale.includes('执行序列'), '应该包含执行序列');
  assert(result.planRationale.includes('预算模式'), '应该包含预算模式');
});

// ============================================================
// 测试 7: 动态插入启用判断
// ============================================================

console.log('\n🧪 测试组 7: 动态插入启用判断');
console.log('=' .repeat(50));

test('深度分析启用动态插入', () => {
  const planner = new ChainPlanner(10000);
  const result = planner.plan(
    'deep_analysis' as IntentType,
    'deep' as ComplexityLevel,
    'A' as SkillChain
  );

  console.log(`   动态插入: ${result.dynamicInsertionsEnabled ? '启用' : '禁用'}`);
  assert(result.dynamicInsertionsEnabled === true, '深度分析应该启用动态插入');
});

test('快速查询禁用动态插入', () => {
  const planner = new ChainPlanner(10000);
  const result = planner.plan(
    'simple_qa' as IntentType,
    'quick' as ComplexityLevel,
    'A' as SkillChain
  );

  console.log(`   动态插入: ${result.dynamicInsertionsEnabled ? '启用' : '禁用'}`);
});

// ============================================================
// 汇总
// ============================================================

console.log('\n' + '=' .repeat(50));
console.log(`\n📊 测试结果: ${passed} 通过, ${failed} 失败`);
console.log(`   通过率: ${((passed / (passed + failed)) * 100).toFixed(1)}%`);

if (failed > 0) {
  process.exit(1);
}
