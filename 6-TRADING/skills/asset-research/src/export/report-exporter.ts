/**
 * 报告导出器
 * 支持多种格式导出：HTML、PDF、JSON、CSV
 */

import {
  ResearchResult,
  MultiVersionResult,
  BacktestResult,
  ExportFormat
} from '../types';

export interface ExportOptions {
  format: ExportFormat;
  includeRawData?: boolean;
  template?: 'default' | 'minimal' | 'detailed';
  language?: 'zh-CN' | 'en-US';
}

const PHASE_NAMES: Record<string, string> = {
  recovery: '复苏期',
  overheat: '过热期',
  stagflation: '滞胀期',
  recession: '衰退期',
};

const DIRECTION_ICONS: Record<string, string> = {
  up: '⬆️',
  down: '⬇️',
  neutral: '➡️',
};

const CATEGORY_NAMES: Record<string, string> = {
  stock: '股票',
  bond: '债券',
  commodity: '商品',
  cash: '现金/货币',
  crypto: '加密货币',
};

/**
 * 报告导出器
 */
export class ReportExporter {
  /**
   * 导出单版本报告
   */
  static export(result: ResearchResult, options: ExportOptions): string {
    switch (options.format) {
      case 'html':
        return this.toHTML(result, options);
      case 'json':
        return this.toJSON(result);
      case 'csv':
        return this.toCSV(result);
      default:
        return result.report;
    }
  }

  /**
   * 导出多版本报告
   */
  static exportMultiVersion(result: MultiVersionResult, options: ExportOptions): string {
    switch (options.format) {
      case 'html':
        return this.toMultiVersionHTML(result, options);
      case 'json':
        return JSON.stringify(result, null, 2);
      default:
        // 文本格式：拼接所有报告
        return result.results.map(r => r.report).join('\n\n' + '='.repeat(70) + '\n\n');
    }
  }

  /**
   * 导出回测报告
   */
  static exportBacktest(result: BacktestResult, options: ExportOptions): string {
    switch (options.format) {
      case 'html':
        return this.toBacktestHTML(result, options);
      case 'json':
        return JSON.stringify(result, null, 2);
      default:
        // 文本格式
        return this.generateBacktestText(result);
    }
  }

  /**
   * 转换为HTML格式
   */
  static toHTML(result: ResearchResult, options?: Partial<ExportOptions>): string {
    const template = options?.template || 'default';

    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>资产调研报告 - ${result.engineName}</title>
  <style>
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
      line-height: 1.6;
      color: #333;
      background: #f5f5f5;
      padding: 20px;
    }
    .container { max-width: 900px; margin: 0 auto; }
    .header {
      background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
      color: white;
      padding: 30px;
      border-radius: 10px;
      margin-bottom: 20px;
    }
    .header h1 { font-size: 24px; margin-bottom: 10px; }
    .header .meta { opacity: 0.9; font-size: 14px; }
    .card {
      background: white;
      border-radius: 10px;
      padding: 20px;
      margin-bottom: 20px;
      box-shadow: 0 2px 10px rgba(0,0,0,0.1);
    }
    .card h2 {
      font-size: 18px;
      color: #667eea;
      margin-bottom: 15px;
      padding-bottom: 10px;
      border-bottom: 2px solid #f0f0f0;
    }
    .phase-badge {
      display: inline-block;
      padding: 5px 15px;
      border-radius: 20px;
      font-weight: bold;
      font-size: 14px;
    }
    .phase-recovery { background: #4CAF50; color: white; }
    .phase-overheat { background: #FF9800; color: white; }
    .phase-stagflation { background: #F44336; color: white; }
    .phase-recession { background: #2196F3; color: white; }
    .allocation-bar {
      display: flex;
      height: 30px;
      border-radius: 5px;
      overflow: hidden;
      margin: 15px 0;
    }
    .allocation-segment {
      display: flex;
      align-items: center;
      justify-content: center;
      color: white;
      font-size: 12px;
      font-weight: bold;
      transition: all 0.3s;
    }
    .allocation-segment:hover { opacity: 0.8; transform: scaleY(1.1); }
    .category-stock { background: #4CAF50; }
    .category-bond { background: #2196F3; }
    .category-commodity { background: #FF9800; }
    .category-cash { background: #9C27B0; }
    .category-crypto { background: #F44336; }
    .asset-list { list-style: none; }
    .asset-item {
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: 10px;
      border-bottom: 1px solid #f0f0f0;
      transition: background 0.2s;
    }
    .asset-item:hover { background: #f9f9f9; }
    .asset-name { font-weight: 500; }
    .asset-direction { font-weight: bold; padding: 3px 10px; border-radius: 10px; font-size: 12px; }
    .direction-up { background: #E8F5E9; color: #2E7D32; }
    .direction-neutral { background: #FFF3E0; color: #E65100; }
    .direction-down { background: #FFEBEE; color: #C62828; }
    .indicator-grid {
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 15px;
    }
    .indicator-card {
      background: #f9f9f9;
      padding: 15px;
      border-radius: 8px;
      text-align: center;
    }
    .indicator-value { font-size: 24px; font-weight: bold; color: #667eea; }
    .indicator-label { font-size: 12px; color: #666; margin-top: 5px; }
    .footer {
      text-align: center;
      color: #999;
      font-size: 12px;
      margin-top: 30px;
      padding: 20px;
    }
    @media print {
      body { background: white; }
      .card { box-shadow: none; border: 1px solid #ddd; }
    }
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>📊 资产标的调研报告</h1>
      <div class="meta">
        <div>版本: ${result.engineName} | ${result.version}</div>
        <div>日期: ${new Date(result.timestamp).toLocaleDateString('zh-CN')}</div>
        <div>区域: ${result.region === 'global' ? '全球/美国' : '中国'}</div>
      </div>
    </div>

    <div class="card">
      <h2>📈 经济周期判定</h2>
      <p>
        当前周期: <span class="phase-badge phase-${result.cycle.currentPhase}">${PHASE_NAMES[result.cycle.currentPhase]}</span>
        &nbsp;&nbsp;
        置信度: <strong>${(result.cycle.confidence * 100).toFixed(0)}%</strong>
      </p>
      <div class="indicator-grid" style="margin-top: 15px;">
        ${result.cycle.indicators.map(ind => `
          <div class="indicator-card">
            <div class="indicator-value">${ind.value}${ind.name.includes('率') ? '%' : ''}</div>
            <div class="indicator-label">${ind.name} ${DIRECTION_ICONS[ind.trend] || ''}</div>
          </div>
        `).join('')}
      </div>
    </div>

    <div class="card">
      <h2>💰 大类资产配置</h2>
      <div class="allocation-bar">
        ${result.assetAllocation.map(item => `
          <div class="allocation-segment category-${item.category}" style="width: ${item.allocation}%;" title="${CATEGORY_NAMES[item.category]}: ${item.allocation}%">
            ${item.allocation > 10 ? `${item.allocation}%` : ''}
          </div>
        `).join('')}
      </div>
      <table style="width: 100%; border-collapse: collapse; margin-top: 15px;">
        <thead>
          <tr style="background: #f9f9f9;">
            <th style="padding: 10px; text-align: left;">资产类别</th>
            <th style="padding: 10px; text-align: right;">配置比例</th>
            <th style="padding: 10px; text-align: center;">配置方向</th>
          </tr>
        </thead>
        <tbody>
          ${result.assetAllocation.map(item => `
            <tr>
              <td style="padding: 10px;">${CATEGORY_NAMES[item.category] || item.category}</td>
              <td style="padding: 10px; text-align: right; font-weight: bold;">${item.allocation}%</td>
              <td style="padding: 10px; text-align: center;">
                <span class="asset-direction direction-${item.direction === 'overweight' ? 'up' : item.direction === 'underweight' ? 'down' : 'neutral'}">
                  ${item.direction === 'overweight' ? '⬆️ 超配' : item.direction === 'underweight' ? '⬇️ 低配' : '➡️ 标配'}
                </span>
              </td>
            </tr>
          `).join('')}
        </tbody>
      </table>
    </div>

    <div class="card">
      <h2>🏆 子类资产优先级（Top 10）</h2>
      <ul class="asset-list">
        ${result.topSubCategories.slice(0, 10).map((sub, i) => `
          <li class="asset-item">
            <div>
              <span class="asset-name">${i < 3 ? '🥇' : i < 6 ? '🥈' : i < 10 ? '🥉' : ''} ${sub.subCategory}</span>
              <span style="color: #999; font-size: 12px; margin-left: 10px;">${CATEGORY_NAMES[sub.category as string] || sub.category}</span>
            </div>
            <span class="asset-direction direction-${sub.direction === 'overweight' ? 'up' : sub.direction === 'underweight' ? 'down' : 'neutral'}">
              ${sub.direction === 'overweight' ? '⬆️ 超配' : sub.direction === 'underweight' ? '⬇️ 低配' : '➡️ 标配'}
            </span>
          </li>
        `).join('')}
      </ul>
    </div>

    <div class="card">
      <h2>⚠️ 风险提示</h2>
      <ul style="padding-left: 20px; color: #666;">
        <li>美林投资时钟基于历史规律，未来市场可能呈现与历史不同的特征</li>
        <li>宏观经济数据通常存在发布延迟，周期判定可能滞后</li>
        <li>美林时钟在美国市场验证较多，其他市场表现可能存在差异</li>
        <li>未能预见的地缘政治、疫情等突发事件可能颠覆周期规律</li>
      </ul>
    </div>

    <div class="footer">
      <p>本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。</p>
      <p>生成时间: ${new Date().toLocaleString('zh-CN')}</p>
    </div>
  </div>
</body>
</html>`;
  }

  /**
   * 转换为JSON格式
   */
  static toJSON(result: ResearchResult): string {
    return JSON.stringify({
      metadata: {
        version: result.version,
        engineName: result.engineName,
        timestamp: result.timestamp,
        region: result.region,
        confidence: result.confidence,
      },
      cycle: {
        currentPhase: result.cycle.currentPhase,
        phaseName: PHASE_NAMES[result.cycle.currentPhase],
        confidence: result.cycle.confidence,
        indicators: result.cycle.indicators,
        rationale: result.cycle.rationale,
      },
      assetAllocation: result.assetAllocation.map(a => ({
        category: a.category,
        categoryName: CATEGORY_NAMES[a.category] || a.category,
        allocation: a.allocation,
        direction: a.direction,
        description: a.description,
      })),
      topSubCategories: result.topSubCategories.map(s => ({
        rank: s.rank,
        subCategory: s.subCategory,
        category: s.category,
        categoryName: CATEGORY_NAMES[s.category as string] || s.category,
        direction: s.direction,
        score: s.score,
        rationale: s.rationale,
      })),
    }, null, 2);
  }

  /**
   * 转换为CSV格式
   */
  static toCSV(result: ResearchResult): string {
    const lines: string[] = [];

    // 子类资产CSV
    lines.push('排名,子类,大类,配置方向,得分,推荐理由');
    for (const sub of result.topSubCategories) {
      lines.push([
        sub.rank,
        sub.subCategory,
        CATEGORY_NAMES[sub.category as string] || sub.category,
        sub.direction === 'overweight' ? '超配' : sub.direction === 'underweight' ? '低配' : '标配',
        sub.score?.toFixed(0) || '',
        `"${(sub.rationale || '').replace(/"/g, '""')}"`,
      ].join(','));
    }

    return lines.join('\n');
  }

  /**
   * 多版本HTML报告
   */
  private static toMultiVersionHTML(result: MultiVersionResult, options?: Partial<ExportOptions>): string {
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>资产调研报告 - 多版本对比</title>
  <style>
    body { font-family: -apple-system, BlinkMacSystemFont, sans-serif; max-width: 1200px; margin: 0 auto; padding: 20px; }
    .version-section { border: 1px solid #ddd; border-radius: 10px; margin-bottom: 30px; overflow: hidden; }
    .version-header { background: #667eea; color: white; padding: 15px 20px; }
    .version-content { padding: 20px; }
    .comparison-table { width: 100%; border-collapse: collapse; margin: 20px 0; }
    .comparison-table th, .comparison-table td { border: 1px solid #ddd; padding: 10px; text-align: center; }
    .comparison-table th { background: #f5f5f5; }
  </style>
</head>
<body>
  <h1>📊 资产调研报告 - 多版本对比</h1>
  <p>生成时间: ${new Date().toLocaleString('zh-CN')}</p>

  <h2>版本对比摘要</h2>
  <table class="comparison-table">
    <tr>
      <th>版本</th>
      <th>周期判定</th>
      <th>置信度</th>
      <th>Top资产</th>
    </tr>
    ${result.results.map(r => `
      <tr>
        <td><strong>${r.engineName}</strong></td>
        <td>${PHASE_NAMES[r.cycle.currentPhase]}</td>
        <td>${(r.cycle.confidence * 100).toFixed(0)}%</td>
        <td>${r.topSubCategories.slice(0, 3).map(s => s.subCategory).join(', ')}</td>
      </tr>
    `).join('')}
  </table>

  ${result.results.map(r => `
    <div class="version-section">
      <div class="version-header">
        <h2>${r.engineName} (${r.version})</h2>
      </div>
      <div class="version-content">
        ${this.toHTML(r, options)}
      </div>
    </div>
  `).join('')}
</body>
</html>`;
  }

  /**
   * 回测HTML报告
   */
  private static toBacktestHTML(result: BacktestResult, options?: Partial<ExportOptions>): string {
    return `<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>回测报告</title>
  <style>
    body { font-family: -apple-system, sans-serif; max-width: 1000px; margin: 0 auto; padding: 20px; }
    .metrics-grid { display: grid; grid-template-columns: repeat(4, 1fr); gap: 15px; margin: 20px 0; }
    .metric-card { background: #f5f5f5; padding: 20px; border-radius: 10px; text-align: center; }
    .metric-value { font-size: 24px; font-weight: bold; color: #667eea; }
    .metric-label { font-size: 12px; color: #666; margin-top: 5px; }
  </style>
</head>
<body>
  <h1>📈 回测报告</h1>
  <p>回测周期: ${result.startDate} ~ ${result.endDate}</p>

  <div class="metrics-grid">
    <div class="metric-card">
      <div class="metric-value">${((result.metrics.totalReturn || 0) * 100).toFixed(2)}%</div>
      <div class="metric-label">总收益</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${((result.metrics.annualizedReturn || 0) * 100).toFixed(2)}%</div>
      <div class="metric-label">年化收益</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${(result.metrics.sharpeRatio || 0).toFixed(2)}</div>
      <div class="metric-label">夏普比率</div>
    </div>
    <div class="metric-card">
      <div class="metric-value">${((result.metrics.maxDrawdown || 0) * 100).toFixed(2)}%</div>
      <div class="metric-label">最大回撤</div>
    </div>
  </div>
</body>
</html>`;
  }

  /**
   * 生成回测文本报告
   */
  private static generateBacktestText(result: BacktestResult): string {
    const lines: string[] = [];
    lines.push('='.repeat(70));
    lines.push('回测报告');
    lines.push('='.repeat(70));
    lines.push(`回测周期: ${result.startDate} ~ ${result.endDate}`);
    lines.push(`初始资金: ${result.initialCapital.toLocaleString()}`);
    lines.push(`最终价值: ${result.finalValue.toLocaleString('zh-CN', { maximumFractionDigits: 2 })}`);
    lines.push('');
    lines.push('## 风险指标');
    lines.push(`  总收益率: ${((result.metrics.totalReturn || 0) * 100).toFixed(2)}%`);
    lines.push(`  年化收益率: ${((result.metrics.annualizedReturn || 0) * 100).toFixed(2)}%`);
    lines.push(`  夏普比率: ${(result.metrics.sharpeRatio || 0).toFixed(2)}`);
    lines.push(`  最大回撤: ${((result.metrics.maxDrawdown || 0) * 100).toFixed(2)}%`);
    lines.push(`  胜率: ${((result.metrics.winRate || 0) * 100).toFixed(2)}%`);
    return lines.join('\n');
  }
}
