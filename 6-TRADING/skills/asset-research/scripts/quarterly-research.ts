/**
 * 季度深度报告任务
 * 每季度首月5号 09:00 自动执行
 * 输出：完整HTML三版本对比报告 + 历史回顾 + 下季度展望
 */

import { AssetResearchOrchestrator, ResearchResult } from '../src';
import { StandardOutputManager } from '../src/output/standard-output';
import * as fs from 'fs';
import * as path from 'path';

const BASE_DIR = path.join(__dirname, '..');
const OUTPUT_DIR = path.join(BASE_DIR, 'output');
const REPORTS_DIR = path.join(BASE_DIR, 'reports');

async function runQuarterlyResearch() {
  console.log('='.repeat(60));
  console.log('季度深度资产调研任务启动');
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

    // 生成季度目录
    const now = new Date();
    const year = now.getFullYear();
    const quarter = Math.floor(now.getMonth() / 3) + 1;
    const quarterStr = `${year}-Q${quarter}`;
    const quarterDir = path.join(REPORTS_DIR, quarterStr);
    if (!fs.existsSync(quarterDir)) {
      fs.mkdirSync(quarterDir, { recursive: true });
    }

    // 1. 保存标准输出JSON
    const latestPath = path.join(OUTPUT_DIR, 'latest.json');
    StandardOutputManager.saveToFile(v1Result, latestPath, { reportType: 'quarterly' });
    console.log('📄 标准输出已保存:', latestPath);

    // 2. 生成完整HTML报告（三版本对比）
    const htmlPath = path.join(quarterDir, 'full-report.html');
    const htmlReport = generateFullHTMLReport(v1Result, v2Result, v3Result);
    fs.writeFileSync(htmlPath, htmlReport);
    console.log('📄 完整HTML报告已保存:', htmlPath);

    // 3. 保存各版本报告
    ['v1', 'v2', 'v3'].forEach((v, i) => {
      const results = [v1Result, v2Result, v3Result];
      const result = results[i];
      const reportPath = path.join(quarterDir, `${v}-report.md`);
      fs.writeFileSync(reportPath, result.report);
      console.log(`📄 ${v.toUpperCase()}报告已保存:`, reportPath);
    });

    // 4. 保存完整数据
    const dataPath = path.join(quarterDir, 'full-data.json');
    fs.writeFileSync(dataPath, JSON.stringify({
      v1: JSON.parse(JSON.stringify(v1Result)),
      v2: JSON.parse(JSON.stringify(v2Result)),
      v3: JSON.parse(JSON.stringify(v3Result)),
      generatedAt: new Date().toISOString(),
      quarter: quarterStr,
    }, null, 2));
    console.log('📄 完整数据已保存:', dataPath);

    // 5. 生成季度深度分析
    const analysisPath = path.join(quarterDir, 'quarterly-analysis.md');
    const analysis = generateQuarterlyAnalysis(v1Result, v2Result, v3Result);
    fs.writeFileSync(analysisPath, analysis);
    console.log('📄 季度分析已保存:', analysisPath);

    console.log('');
    console.log('='.repeat(60));
    console.log('季度深度调研任务完成');
    console.log('='.repeat(60));
    console.log('');
    console.log('📊 核心结论：');
    console.log('   当前周期:', v1Result.cycle.currentPhase);
    console.log('   置信度:', (v1Result.confidence * 100).toFixed(0) + '%');
    console.log('   季度:', quarterStr);
    console.log('');
    console.log('📁 报告目录:', quarterDir);
    console.log('');

    return { success: true, v1Result, v2Result, v3Result, quarter: quarterStr };

  } catch (error) {
    console.error('');
    console.error('❌ 季度调研任务失败:', error);
    console.error('');
    return { success: false, error };
  }
}

function generateFullHTMLReport(v1: ResearchResult, v2: ResearchResult, v3: ResearchResult): string {
  const PHASE_NAMES: Record<string, string> = {
    recovery: '复苏期',
    overheat: '过热期',
    stagflation: '滞胀期',
    recession: '衰退期',
  };

  const now = new Date();
  const year = now.getFullYear();
  const quarter = Math.floor(now.getMonth() / 3) + 1;

  return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>资产调研季度深度报告 - ${year}年Q${quarter}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body { font-family: -apple-system, "PingFang SC", sans-serif; line-height: 1.7; color: #333; background: #f5f5f5; padding: 20px; }
    .container { max-width: 960px; margin: 0 auto; background: white; box-shadow: 0 2px 20px rgba(0,0,0,0.1); border-radius: 8px; overflow: hidden; }
    .cover { background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 60px 50px; text-align: center; }
    .cover h1 { font-size: 32px; margin-bottom: 10px; }
    .cover .subtitle { font-size: 16px; opacity: 0.9; }
    .section { padding: 40px 50px; border-bottom: 1px solid #eee; }
    .section h2 { font-size: 20px; color: #667eea; margin-bottom: 20px; padding-bottom: 10px; border-bottom: 2px solid #eee; }
    .section h3 { font-size: 16px; color: #444; margin: 20px 0 10px; }
    .summary-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }
    .summary-card { background: #f9f9f9; padding: 20px; border-radius: 8px; text-align: center; }
    .summary-value { font-size: 22px; font-weight: 700; color: #667eea; }
    .summary-label { font-size: 12px; color: #999; margin-top: 5px; }
    table { width: 100%; border-collapse: collapse; margin: 15px 0; font-size: 14px; }
    th { background: #f1f3f5; padding: 10px; text-align: left; border-bottom: 2px solid #ddd; }
    td { padding: 10px; border-bottom: 1px solid #eee; }
    .phase-badge { display: inline-block; padding: 4px 12px; border-radius: 15px; font-weight: 600; color: white; font-size: 13px; }
    .phase-stagflation { background: #dc3545; }
    .phase-recovery { background: #28a745; }
    .phase-overheat { background: #fd7e14; }
    .phase-recession { background: #007bff; }
    .footer { padding: 30px 50px; text-align: center; color: #aaa; font-size: 12px; background: #f9f9f9; }
    .risk-box { background: #fff3cd; border-left: 4px solid #ffc107; padding: 15px 20px; margin: 15px 0; }
    @media print { body { background: white; } .section { page-break-inside: avoid; } }
  </style>
</head>
<body>
  <div class="container">
    <div class="cover">
      <h1>📊 资产调研季度深度报告</h1>
      <div class="subtitle">${year}年第${quarter}季度 | 美林时钟三版本对比分析</div>
    </div>
    <div class="section">
      <h2>一、执行摘要</h2>
      <div class="summary-grid">
        <div class="summary-card">
          <div class="summary-value">${PHASE_NAMES[v1.cycle.currentPhase]}</div>
          <div class="summary-label">当前周期</div>
        </div>
        <div class="summary-card">
          <div class="summary-value">${(v1.confidence * 100).toFixed(0)}%</div>
          <div class="summary-label">置信度</div>
        </div>
        <div class="summary-card">
          <div class="summary-value">${v1.topSubCategories[0]?.displayName || '-'}</div>
          <div class="summary-label">Top 1 标的</div>
        </div>
        <div class="summary-card">
          <div class="summary-value">3</div>
          <div class="summary-label">分析版本</div>
        </div>
      </div>
    </div>
    <div class="section">
      <h2>二、周期判定</h2>
      <p>当前经济周期：<span class="phase-badge phase-${v1.cycle.currentPhase}">${PHASE_NAMES[v1.cycle.currentPhase]}</span></p>
      <p style="margin-top: 10px;">置信度：${(v1.confidence * 100).toFixed(0)}%</p>
      <h3>核心指标</h3>
      <table>
        <tr><th>指标</th><th>数值</th><th>趋势</th><th>来源</th></tr>
        ${v1.cycle.indicators.map(ind => `<tr><td>${ind.name}</td><td>${ind.value}${ind.name.includes('率') ? '%' : ''}</td><td>${ind.trend === 'up' ? '⬆️' : ind.trend === 'down' ? '⬇️' : '➡️'}</td><td>${ind.source}</td></tr>`).join('')}
      </table>
    </div>
    <div class="section">
      <h2>三、三版本对比</h2>
      <table>
        <tr><th>版本</th><th>周期判定</th><th>置信度</th><th>Top 1 标的</th></tr>
        <tr><td>V1 经典版</td><td>${PHASE_NAMES[v1.cycle.currentPhase]}</td><td>${(v1.confidence * 100).toFixed(0)}%</td><td>${v1.topSubCategories[0]?.displayName}</td></tr>
        <tr><td>V2 多因子版</td><td>${PHASE_NAMES[v2.cycle.currentPhase]}</td><td>${(v2.confidence * 100).toFixed(0)}%</td><td>${v2.topSubCategories[0]?.displayName}</td></tr>
        <tr><td>V3 情景模拟版</td><td>${PHASE_NAMES[v3.cycle.currentPhase]}</td><td>${(v3.confidence * 100).toFixed(0)}%</td><td>${v3.topSubCategories[0]?.displayName}</td></tr>
      </table>
    </div>
    <div class="section">
      <h2>四、大类资产配置</h2>
      <table>
        <tr><th>资产类别</th><th>V1配置</th><th>V2配置</th><th>V3基准</th></tr>
        ${v1.assetAllocation.map((item, i) => {
          const v2Item = v2.assetAllocation.find(a => a.category === item.category);
          return `<tr><td>${item.displayName}</td><td>${item.weight}%</td><td>${v2Item?.weight || '-'}%</td><td>${item.weight}%</td></tr>`;
        }).join('')}
      </table>
    </div>
    <div class="section">
      <h2>五、风险提示</h2>
      <div class="risk-box">
        <p>美林投资时钟基于历史规律，未来市场可能呈现与历史不同的特征</p>
        <p>宏观经济数据通常存在发布延迟，周期判定可能滞后</p>
        <p>未能预见的地缘政治、疫情等突发事件可能颠覆周期规律</p>
      </div>
    </div>
    <div class="footer">
      <p>本报告由DreamBuddy资产调研引擎自动生成</p>
      <p>生成时间：${new Date().toLocaleString('zh-CN')}</p>
      <p>免责声明：本报告仅供参考，不构成投资建议</p>
    </div>
  </div>
</body>
</html>`;
}

function generateQuarterlyAnalysis(v1: ResearchResult, v2: ResearchResult, v3: ResearchResult): string {
  const now = new Date();
  const year = now.getFullYear();
  const quarter = Math.floor(now.getMonth() / 3) + 1;

  const lines: string[] = [];

  lines.push(`# ${year}年Q${quarter} 资产调研季度深度分析`);
  lines.push('');
  lines.push(`**生成时间**: ${new Date().toLocaleString('zh-CN')}`);
  lines.push('');

  lines.push('## 一、本季度经济环境回顾');
  lines.push('');
  lines.push('*(此处可回顾本季度主要经济事件和数据变化)*');
  lines.push('');

  lines.push('## 二、周期判定分析');
  lines.push('');
  lines.push(`- **当前周期**: ${v1.cycle.currentPhase}`);
  lines.push(`- **置信度**: ${(v1.confidence * 100).toFixed(0)}%`);
  lines.push(`- **三版本一致性**: ${v1.cycle.currentPhase === v2.cycle.currentPhase && v2.cycle.currentPhase === v3.cycle.currentPhase ? '一致' : '存在分歧'}`);
  lines.push('');

  lines.push('## 三、资产配置建议');
  lines.push('');
  lines.push('*(根据三版本综合给出配置建议)*');
  lines.push('');

  lines.push('## 四、下季度展望');
  lines.push('');
  lines.push('*(基于V3情景模拟给出下季度展望)*');
  lines.push('');

  lines.push('## 五、风险提示');
  lines.push('');
  lines.push('- 宏观经济数据存在滞后性');
  lines.push('- 美林时钟基于历史经验');
  lines.push('- 黑天鹅事件无法预测');
  lines.push('');

  lines.push('---');
  lines.push('*本报告由DreamBuddy资产调研引擎自动生成*');

  return lines.join('\n');
}

// 命令行直接运行
if (require.main === module) {
  runQuarterlyResearch()
    .then(result => {
      process.exit(result.success ? 0 : 1);
    })
    .catch(err => {
      console.error(err);
      process.exit(1);
    });
}

export { runQuarterlyResearch };
