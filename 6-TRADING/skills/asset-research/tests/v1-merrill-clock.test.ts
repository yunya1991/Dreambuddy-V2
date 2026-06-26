/**
 * 资产标的调研引擎 - 单元测试
 * Asset Research Engine - Unit Tests
 */

import assert from 'assert';
import {
  V1MerrillClockEngine,
  CycleDetector,
  AssetAllocator,
  MarkdownGenerator,
  JsonSerializer,
  runAssetResearch,
  MacroIndicator,
  ResearchOptions
} from '../src';

// ==================== 测试配置 ====================

console.log('=== 资产标的调研引擎 - 单元测试 ===\n');

let passed = 0;
let failed = 0;

function test(name: string, fn: () => void) {
  try {
    fn();
    console.log(`  ✅ ${name}`);
    passed++;
  } catch (e) {
    console.log(`  ❌ ${name}: ${(e as Error).message}`);
    failed++;
  }
}

// ==================== 测试辅助函数 ====================

function createMockIndicator(
  name: string,
  value: string,
  trend: 'up' | 'down' | 'flat' = 'up'
): MacroIndicator {
  return {
    name,
    value,
    trend,
    source: '测试数据',
    timestamp: new Date().toISOString(),
    freshness: 'fresh',
  };
}

// ==================== 周期判定测试 ====================

console.log('--- 周期判定器测试 ---');

test('复苏期判定：增长上行，通胀下行', () => {
  const detector = new CycleDetector();
  const indicators = [
    createMockIndicator('GDP增长率', '3.2', 'up'),
    createMockIndicator('PMI指数', '53.5', 'up'),
    createMockIndicator('CPI通胀率', '1.8', 'down'),
  ];

  const result = detector.determine(indicators);
  assert(result.phase === 'recovery', `期望recovery，实际${result.phase}`);
  assert(result.confidence > 0.5, '置信度应该>0.5');
});

test('过热期判定：增长上行，通胀上行', () => {
  const detector = new CycleDetector();
  const indicators = [
    createMockIndicator('GDP增长率', '4.5', 'up'),
    createMockIndicator('PMI指数', '58', 'up'),
    createMockIndicator('CPI通胀率', '4.5', 'up'),
  ];

  const result = detector.determine(indicators);
  assert(result.phase === 'overheat', `期望overheat，实际${result.phase}`);
});

test('滞胀期判定：增长下行，通胀上行', () => {
  const detector = new CycleDetector();
  const indicators = [
    createMockIndicator('GDP增长率', '1.2', 'down'),
    createMockIndicator('PMI指数', '47', 'down'),
    createMockIndicator('CPI通胀率', '5.5', 'up'),
  ];

  const result = detector.determine(indicators);
  assert(result.phase === 'stagflation', `期望stagflation，实际${result.phase}`);
});

test('衰退期判定：增长下行，通胀下行', () => {
  const detector = new CycleDetector();
  const indicators = [
    createMockIndicator('GDP增长率', '-0.5', 'down'),
    createMockIndicator('PMI指数', '45', 'down'),
    createMockIndicator('CPI通胀率', '0.5', 'down'),
  ];

  const result = detector.determine(indicators);
  assert(result.phase === 'recession', `期望recession，实际${result.phase}`);
});

test('无指标时应返回有效周期', () => {
  const detector = new CycleDetector();
  const result = detector.determine([]);
  const validPhases = ['recovery', 'overheat', 'stagflation', 'recession'];
  assert(validPhases.includes(result.phase), '应返回有效周期');
});

// ==================== 资产配置测试 ====================

console.log('\n--- 资产配置器测试 ---');

test('复苏期：股票应为最高权重', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('recovery');
  const stockAllocation = allocations.find(a => a.category === 'stock');
  assert(stockAllocation, '应该有股票配置');
  assert(stockAllocation!.weight >= 30, '股票权重应>=30%');
});

test('复苏期：科技股应有最高优先级', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('recovery');
  const stockAllocation = allocations.find(a => a.category === 'stock');
  const techSub = stockAllocation!.subCategories.find(s => s.name === 'tech');
  assert(techSub, '应该有科技股子类');
  assert.strictEqual(techSub!.priority, 1, '科技股优先级应为1');
});

test('过热期：商品应为最高权重', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('overheat');
  const commodityAllocation = allocations.find(a => a.category === 'commodity');
  assert(commodityAllocation, '应该有商品配置');
  assert(commodityAllocation!.weight >= 30, '商品权重应>=30%');
});

test('滞胀期：贵金属应有最高优先级', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('stagflation');
  const commodityAllocation = allocations.find(a => a.category === 'commodity');
  const preciousSub = commodityAllocation!.subCategories.find(s => s.name === 'precious_metal');
  assert(preciousSub, '应该有贵金属子类');
  assert.strictEqual(preciousSub!.priority, 1, '贵金属优先级应为1');
});

test('衰退期：债券应为最高权重', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('recession');
  const bondAllocation = allocations.find(a => a.category === 'bond');
  assert(bondAllocation, '应该有债券配置');
  assert(bondAllocation!.weight >= 30, '债券权重应>=30%');
});

test('Top子类获取应返回正确数量', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('recovery');
  const topSubs = allocator.getTopSubCategories(allocations, 10);
  assert.strictEqual(topSubs.length, 10, '应返回10个Top子类');
});

test('Top子类应按优先级排序', () => {
  const allocator = new AssetAllocator();
  const allocations = allocator.generateAllocation('overheat');
  const topSubs = allocator.getTopSubCategories(allocations, 10);

  for (let i = 1; i < topSubs.length; i++) {
    assert(topSubs[i].priority >= topSubs[i - 1].priority, '应按优先级升序排列');
  }
});

// ==================== v1引擎测试 ====================

console.log('\n--- V1美林时钟引擎测试 ---');

test('引擎版本信息正确', () => {
  const engine = new V1MerrillClockEngine();
  assert.strictEqual(engine.version, '1.0.0');
  assert(engine.name.includes('Merrill'));
});

test('引擎运行应返回有效结果', async () => {
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();

  assert(result, '结果不应为空');
  assert.strictEqual(result.version, '1.0.0');
  assert(result.cycle, '应有周期信息');
  assert(result.assetAllocation, '应有资产配置');
  assert(result.topSubCategories, '应有子类配置');
  assert(result.report, '应有报告');
});

test('自定义指标应影响周期判定', async () => {
  const engine = new V1MerrillClockEngine();
  const options: ResearchOptions = {
    customIndicators: [
      createMockIndicator('GDP增长率', '5.0', 'up'),
      createMockIndicator('CPI通胀率', '2.0', 'down'),
    ],
  };

  const result = await engine.run(options);
  assert.strictEqual(result.cycle.currentPhase, 'recovery');
});

test('区域设置应生效', async () => {
  const engine = new V1MerrillClockEngine();
  const result = await engine.run({ region: 'cn' });
  assert.strictEqual(result.region, 'cn');
});

// ==================== 报告生成测试 ====================

console.log('\n--- Markdown报告生成测试 ---');

test('报告应包含标题', async () => {
  const generator = new MarkdownGenerator();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const report = generator.generate(result);

  assert(report.includes('# 资产标的调研报告'), '应有报告标题');
  assert(report.includes(result.version), '应包含版本号');
});

test('报告应包含经济周期章节', async () => {
  const generator = new MarkdownGenerator();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const report = generator.generate(result);

  assert(report.includes('## 一、经济周期判定'), '应包含周期章节');
});

test('报告应包含资产配置章节', async () => {
  const generator = new MarkdownGenerator();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const report = generator.generate(result);

  assert(report.includes('## 二、大类资产配置建议'), '应包含配置章节');
});

test('报告应包含风险提示', async () => {
  const generator = new MarkdownGenerator();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const report = generator.generate(result);

  assert(report.includes('## 五、风险提示'), '应包含风险提示');
  assert(report.includes('模型局限性'), '应包含模型局限性说明');
});

// ==================== JSON序列化测试 ====================

console.log('\n--- JSON序列化测试 ---');

test('应能序列化研究结果', async () => {
  const serializer = new JsonSerializer();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const json = serializer.serialize(result);

  assert(json, 'JSON不应为空');
  assert(JSON.parse(json), '应能解析为JSON');
});

test('应能反序列化', async () => {
  const serializer = new JsonSerializer();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const json = serializer.serialize(result);
  const deserialized = serializer.deserialize(json);

  assert.strictEqual(deserialized.version, result.version);
  assert.strictEqual(deserialized.cycle.currentPhase, result.cycle.currentPhase);
});

test('应能提取摘要', async () => {
  const serializer = new JsonSerializer();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const summary = serializer.extractSummary(result);

  assert(summary.version, '应有版本');
  assert(summary.phase, '应有周期');
  assert(summary.topAssets, '应有Top资产');
  assert(summary.confidence, '应有置信度');
});

test('应能导出CSV', async () => {
  const serializer = new JsonSerializer();
  const engine = new V1MerrillClockEngine();
  const result = await engine.run();
  const csv = serializer.exportToCsv(result);

  assert(csv.includes('优先级,子类名称,大类,配置方向,推荐理由'), '应有CSV表头');
  assert(csv.includes('科技股'), '应包含科技股');
});

// ==================== 端到端测试 ====================

console.log('\n--- 端到端测试 ---');

test('runAssetResearch快捷函数应正常工作', async () => {
  const result = await runAssetResearch();

  assert(result, '结果不应为空');
  assert.strictEqual(result.version, '1.0.0');
  assert(result.report, '应有报告');
  assert(result.assetAllocation.length > 0, '应有资产配置');
});

test('应包含完整的五大类资产', async () => {
  const result = await runAssetResearch();
  const categories = result.assetAllocation.map(a => a.category);

  assert(categories.includes('stock'), '应有股票');
  assert(categories.includes('bond'), '应有债券');
  assert(categories.includes('commodity'), '应有商品');
  assert(categories.includes('cash'), '应有现金');
  assert(categories.includes('crypto'), '应有加密');
});

test('子类资产总数应为22', async () => {
  const result = await runAssetResearch();
  let total = 0;
  for (const allocation of result.assetAllocation) {
    total += allocation.subCategories.length;
  }
  assert.strictEqual(total, 22, '股票5+债券4+商品4+现金4+加密5=22');
});

// ==================== 测试结果汇总 ====================

console.log('\n========================================');
console.log(`测试完成: ${passed} 通过, ${failed} 失败`);
console.log('========================================\n');

if (failed > 0) {
  process.exit(1);
}
