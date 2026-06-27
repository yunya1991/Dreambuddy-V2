/**
 * 资产标的调研引擎 - 三版本集成测试
 */

import assert from 'assert';
import {
  AssetResearchOrchestrator,
  runAssetResearch,
  runMultiVersionResearch,
  V1MerrillClockEngine,
  V2MultiFactorEngine,
  V3ScenarioSimEngine,
  MultiFactorCalculator,
  CyclePredictor,
} from '../src';

console.log('=== 资产标的调研引擎 - 三版本集成测试 ===\n');

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log('  ✅ ' + name);
    passed++;
  } catch (e) {
    console.log('  ❌ ' + name + ': ' + (e as Error).message);
    failed++;
  }
}

async function asyncTest(name: string, fn: () => Promise<void>) {
  try {
    await fn();
    console.log('  ✅ ' + name);
    passed++;
  } catch (e) {
    console.log('  ❌ ' + name + ': ' + (e as Error).message);
    failed++;
  }
}

// ==================== v1 测试 ====================

console.log('--- v1 美林时钟经典版 ---');

test('v1 引擎版本信息正确', () => {
  const engine = new V1MerrillClockEngine();
  assert.strictEqual(engine.version, '1.0.0');
});

// ==================== v2 测试 ====================

console.log('\n--- v2 多因子增强版 ---');

test('v2 引擎版本信息正确', () => {
  const engine = new V2MultiFactorEngine();
  assert.strictEqual(engine.version, '2.0.0');
});

test('多因子计算器：计算综合得分', () => {
  const calculator = new MultiFactorCalculator();
  const result = calculator.calculateSubCategoryScore('tech', 'recovery');
  assert(result.scores.total > 0 && result.scores.total <= 100);
});

test('多因子计算器：复苏期科技股周期分应较高', () => {
  const calculator = new MultiFactorCalculator();
  const techResult = calculator.calculateSubCategoryScore('tech', 'recovery');
  const treasuryResult = calculator.calculateSubCategoryScore('treasury', 'recovery');
  assert(techResult.scores.cycle > treasuryResult.scores.cycle);
});

// ==================== v3 测试 ====================

console.log('\n--- v3 情景模拟版 ---');

test('v3 引擎版本信息正确', () => {
  const engine = new V3ScenarioSimEngine();
  assert.strictEqual(engine.version, '3.0.0');
});

test('周期预测器：生成预测结果', () => {
  const predictor = new CyclePredictor();
  const prediction = predictor.predict('recovery', []);

  assert(prediction.currentPhase === 'recovery');
  const totalProb = Object.values(prediction.nextPhaseProbability).reduce(function(a, b) { return a + b; }, 0);
  assert(Math.abs(totalProb - 1.0) < 0.01);
  assert(prediction.expectedDuration > 0);
  assert(prediction.confidence > 0);
});

test('周期预测器：生成情景方案', () => {
  const predictor = new CyclePredictor();
  const prediction = predictor.predict('recovery', []);
  const scenarios = predictor.generateScenarios(prediction);

  assert(scenarios.length >= 3);
  const names = scenarios.map(function(s) { return s.name; });
  assert(names.indexOf('基准情景') >= 0);
  assert(names.indexOf('乐观情景') >= 0);
  assert(names.indexOf('悲观情景') >= 0);
});

test('周期预测器：各周期均可生成情景', () => {
  const predictor = new CyclePredictor();
  const phases = ['recovery', 'overheat', 'stagflation', 'recession'];

  for (var i = 0; i < phases.length; i++) {
    var phase = phases[i] as 'recovery' | 'overheat' | 'stagflation' | 'recession';
    var prediction = predictor.predict(phase, []);
    var scenarios = predictor.generateScenarios(prediction);
    assert(scenarios.length >= 3, phase + '应生成至少3个情景');
  }
});

// ==================== 编排器测试 ====================

console.log('\n--- 编排器与版本对比 ---');

test('编排器注册了三个版本引擎', () => {
  const orch = new AssetResearchOrchestrator();
  const versions = orch.getAvailableVersions();
  assert(versions.indexOf('1') >= 0);
  assert(versions.indexOf('2') >= 0);
  assert(versions.indexOf('3') >= 0);
  assert.strictEqual(versions.length, 3);
});

async function runAllTests() {
  await asyncTest('v2 引擎运行正常', async function() {
    const engine = new V2MultiFactorEngine();
    const result = await engine.run();
    assert.strictEqual(result.version, '2.0.0');
    assert(result.assetAllocation.length > 0);
  });

  await asyncTest('v3 引擎运行正常', async function() {
    const engine = new V3ScenarioSimEngine();
    const result = await engine.run();
    assert.strictEqual(result.version, '3.0.0');
    assert(result.assetAllocation.length > 0);
  });

  await asyncTest('编排器可运行指定版本', async function() {
    const orch = new AssetResearchOrchestrator();
    const v1 = await orch.runV1();
    const v2 = await orch.runV2();
    const v3 = await orch.runV3();
    assert.strictEqual(v1.version, '1.0.0');
    assert.strictEqual(v2.version, '2.0.0');
    assert.strictEqual(v3.version, '3.0.0');
  });

  await asyncTest('多版本并行运行', async function() {
    const result = await runMultiVersionResearch();
    assert.strictEqual(result.results.length, 3);
    assert(result.bestVersion);
    assert(result.comparison);
  });

  await asyncTest('版本对比器结果完整', async function() {
    const result = await runMultiVersionResearch();
    const comp = result.comparison!;
    assert(typeof comp.cycleAgreement === 'number');
    assert(typeof comp.allocationCorrelation === 'number');
    assert(typeof comp.topSubCategoriesOverlap === 'number');
  });

  await asyncTest('三版本报告结构完整', async function() {
    const result = await runMultiVersionResearch();
    for (var i = 0; i < result.results.length; i++) {
      var r = result.results[i];
      assert(r.report.length > 100);
      assert(r.report.indexOf('资产标的调研报告') >= 0);
      assert(r.report.indexOf('风险提示') >= 0);
    }
  });

  await asyncTest('资产类别完整性', async function() {
    const result = await runMultiVersionResearch();
    for (var i = 0; i < result.results.length; i++) {
      var r = result.results[i];
      assert.strictEqual(r.assetAllocation.length, 5);
    }
  });

  await asyncTest('Top子类完整性', async function() {
    const result = await runMultiVersionResearch();
    for (var i = 0; i < result.results.length; i++) {
      var r = result.results[i];
      assert(r.topSubCategories.length >= 5);
    }
  });

  await asyncTest('v2报告有因子分析', async function() {
    const result = await runMultiVersionResearch();
    const v2 = result.results.find(function(r) { return r.version === '2.0.0'; });
    assert(v2!.report.indexOf('因子') >= 0 || v2!.report.indexOf('多因子') >= 0);
  });

  await asyncTest('v3报告有情景分析', async function() {
    const result = await runMultiVersionResearch();
    const v3 = result.results.find(function(r) { return r.version === '3.0.0'; });
    assert(v3!.report.indexOf('情景') >= 0 || v3!.report.indexOf('展望') >= 0);
  });

  await asyncTest('性能测试', async function() {
    const orch = new AssetResearchOrchestrator();
    const start = Date.now();
    await orch.runV1();
    await orch.runV2();
    await orch.runV3();
    const total = Date.now() - start;
    console.log('     三版本总耗时: ' + total + 'ms');
    assert(total < 30000, '总耗时应<30秒');
  });

  console.log('\n========================================');
  console.log('测试完成: ' + passed + ' 通过, ' + failed + ' 失败');
  console.log('========================================\n');

  if (failed > 0) process.exit(1);
}

runAllTests();
