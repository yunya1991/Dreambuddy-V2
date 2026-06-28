/**
 * 月度资产调研任务
 * 每月1号 09:00 自动执行
 * 输出：简版报告 + latest.json 标准输出
 */

import { AssetResearchOrchestrator } from '../src';
import { StandardOutputManager } from '../src/output/standard-output';
import * as fs from 'fs';
import * as path from 'path';

const BASE_DIR = path.join(__dirname, '..');
const OUTPUT_DIR = path.join(BASE_DIR, 'output');
const REPORTS_DIR = path.join(BASE_DIR, 'reports');

async function runMonthlyResearch() {
  console.log('='.repeat(60));
  console.log('月度资产调研任务启动');
  console.log('执行时间:', new Date().toLocaleString('zh-CN'));
  console.log('='.repeat(60));
  console.log('');

  const startTime = Date.now();

  try {
    const orch = new AssetResearchOrchestrator({
      autoSaveHistory: true,
      historyDir: path.join(OUTPUT_DIR, 'history'),
    });

    console.log('[1/3] 运行V1美林时钟经典版...');
    const v1Result = await orch.runV1();

    console.log('[2/3] 运行V2多因子增强版...');
    const v2Result = await orch.runV2();

    console.log('[3/3] 运行V3情景模拟版...');
    const v3Result = await orch.runV3();

    const elapsed = ((Date.now() - startTime) / 1000).toFixed(1);
    console.log('');
    console.log(`✅ 三版本全部完成，耗时 ${elapsed} 秒`);
    console.log('');

    // 确保输出目录存在
    if (!fs.existsSync(OUTPUT_DIR)) {
      fs.mkdirSync(OUTPUT_DIR, { recursive: true });
    }
    if (!fs.existsSync(REPORTS_DIR)) {
      fs.mkdirSync(REPORTS_DIR, { recursive: true });
    }

    // 生成月份目录
    const now = new Date();
    const monthStr = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
    const monthDir = path.join(REPORTS_DIR, monthStr);
    if (!fs.existsSync(monthDir)) {
      fs.mkdirSync(monthDir, { recursive: true });
    }

    // 1. 保存标准输出JSON (供其他模块读取)
    const latestPath = path.join(OUTPUT_DIR, 'latest.json');
    StandardOutputManager.saveToFile(v1Result, latestPath, { reportType: 'monthly' });
    console.log('📄 标准输出已保存:', latestPath);

    // 2. 保存V1报告
    const v1ReportPath = path.join(monthDir, 'v1-merrill-clock.md');
    fs.writeFileSync(v1ReportPath, v1Result.report);
    console.log('📄 V1报告已保存:', v1ReportPath);

    // 3. 保存V2报告
    const v2ReportPath = path.join(monthDir, 'v2-multi-factor.md');
    fs.writeFileSync(v2ReportPath, v2Result.report);
    console.log('📄 V2报告已保存:', v2ReportPath);

    // 4. 保存V3报告
    const v3ReportPath = path.join(monthDir, 'v3-scenario-sim.md');
    fs.writeFileSync(v3ReportPath, v3Result.report);
    console.log('📄 V3报告已保存:', v3ReportPath);

    // 5. 保存JSON数据
    const dataPath = path.join(monthDir, 'data.json');
    fs.writeFileSync(dataPath, JSON.stringify({
      v1: JSON.parse(JSON.stringify(v1Result)),
      v2: JSON.parse(JSON.stringify(v2Result)),
      v3: JSON.parse(JSON.stringify(v3Result)),
      generatedAt: new Date().toISOString(),
    }, null, 2));
    console.log('📄 数据文件已保存:', dataPath);

    // 6. 生成月度摘要
    const summary = generateMonthlySummary(v1Result, v2Result, v3Result);
    const summaryPath = path.join(monthDir, 'summary.md');
    fs.writeFileSync(summaryPath, summary);
    console.log('📄 月度摘要已保存:', summaryPath);

    console.log('');
    console.log('='.repeat(60));
    console.log('月度资产调研任务完成');
    console.log('='.repeat(60));
    console.log('');
    console.log('📊 核心结论：');
    console.log('   当前周期:', v1Result.cycle.currentPhase);
    console.log('   置信度:', (v1Result.confidence * 100).toFixed(0) + '%');
    console.log('   Top 3:', v1Result.topSubCategories.slice(0, 3).map(s => s.displayName).join(', '));
    console.log('');

    return { success: true, v1Result, v2Result, v3Result };

  } catch (error) {
    console.error('');
    console.error('❌ 月度调研任务失败:', error);
    console.error('');
    return { success: false, error };
  }
}

function generateMonthlySummary(v1: any, v2: any, v3: any): string {
  const lines: string[] = [];

  lines.push('# 月度资产调研摘要');
  lines.push('');
  lines.push(`**生成时间**: ${new Date().toLocaleString('zh-CN')}`);
  lines.push('');
  lines.push('## 周期判定');
  lines.push('');
  lines.push(`- **当前周期**: ${v1.cycle.currentPhase}`);
  lines.push(`- **置信度**: ${(v1.confidence * 100).toFixed(0)}%`);
  lines.push(`- **三版本一致性**: ${v1.cycle.currentPhase === v2.cycle.currentPhase && v2.cycle.currentPhase === v3.cycle.currentPhase ? '一致' : '存在分歧'}`);
  lines.push('');
  lines.push('## 大类资产配置');
  lines.push('');
  lines.push('| 资产类别 | V1配置 | V2配置 | V3配置 |');
  lines.push('|---------|--------|--------|--------|');

  const categories = ['commodity', 'cash', 'bond', 'stock', 'crypto'];
  const catNames: Record<string, string> = {
    stock: '股票', bond: '债券', commodity: '商品', cash: '现金/货币', crypto: '加密货币'
  };

  for (const cat of categories) {
    const v1Alloc = v1.assetAllocation.find((a: any) => a.category === cat)?.weight || 0;
    const v2Alloc = v2.assetAllocation.find((a: any) => a.category === cat)?.weight || 0;
    const v3Alloc = v3.assetAllocation?.commodity !== undefined
      ? v3.assetAllocation[cat] || 0
      : v2Alloc;
    lines.push(`| ${catNames[cat]} | ${v1Alloc}% | ${v2Alloc}% | ${v3Alloc}% |`);
  }

  lines.push('');
  lines.push('## Top 5 推荐标的');
  lines.push('');
  lines.push('| 排名 | 标的 | 大类 | 配置方向 |');
  lines.push('|------|------|------|---------|');

  for (let i = 0; i < 5; i++) {
    const sub = v1.topSubCategories[i];
    lines.push(`| ${i + 1} | ${sub.displayName} | - | ${sub.direction} |`);
  }

  lines.push('');
  lines.push('---');
  lines.push('*本报告由DreamBuddy资产调研引擎自动生成*');

  return lines.join('\n');
}

// 命令行直接运行
if (require.main === module) {
  runMonthlyResearch()
    .then(result => {
      process.exit(result.success ? 0 : 1);
    })
    .catch(err => {
      console.error(err);
      process.exit(1);
    });
}

export { runMonthlyResearch };
