/**
 * 资产调研演示脚本
 * 运行三版本并输出对比报告
 */

import {
  runMultiVersionResearch,
  AssetResearchOrchestrator,
  JsonSerializer
} from './src';

async function main() {
  console.log('========================================');
  console.log('  资产标的调研引擎 - 三版本演示');
  console.log('========================================\n');

  const serializer = new JsonSerializer();

  console.log('⏳ 正在运行三版本对比研究...\n');

  const result = await runMultiVersionResearch();

  console.log('✅ 研究完成！\n');

  // 输出各版本摘要
  console.log('📊 版本对比摘要\n');
  console.log('| 版本 | 周期 | 置信度 | Top3资产 |');
  console.log('|------|------|--------|----------|');

  for (const r of result.results) {
    const top3 = r.topSubCategories.slice(0, 3).map(s => s.displayName).join('、');
    const conf = (r.confidence * 100).toFixed(0) + '%';
    console.log('| ' + r.version + ' | ' + r.cycle.currentPhase + ' | ' + conf + ' | ' + top3 + ' |');
  }

  // 输出对比结果
  if (result.comparison) {
    console.log('\n📈 版本对比指标\n');
    console.log('周期一致度: ' + (result.comparison.cycleAgreement * 100).toFixed(0) + '%');
    console.log('配置相关性: ' + (result.comparison.allocationCorrelation * 100).toFixed(0) + '%');
    console.log('Top资产重合度: ' + (result.comparison.topSubCategoriesOverlap * 100).toFixed(0) + '%');
    console.log('\n💡 建议: ' + result.comparison.recommendation);
  }

  if (result.bestVersion) {
    console.log('\n🏆 最佳版本: v' + result.bestVersion);
  }

  // 输出v3完整报告
  console.log('\n\n========================================');
  console.log('  v3 情景模拟版 - 完整报告');
  console.log('========================================\n');

  const v3Result = result.results.find(r => r.version === '3.0.0');
  if (v3Result) {
    console.log(v3Result.report);
  }

  // 保存JSON结果
  console.log('\n💾 JSON数据已就绪，可通过 result.results 访问各版本数据');
}

main().catch(console.error);
