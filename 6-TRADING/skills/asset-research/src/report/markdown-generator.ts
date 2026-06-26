/**
 * Markdown报告生成器
 */

import {
  ResearchResult,
  AssetAllocation,
  SubCategoryAsset,
  CYCLE_CONFIG,
  ASSET_CATEGORY_CONFIG
} from '../types';

/**
 * 报告生成器
 */
export class MarkdownGenerator {
  /**
   * 生成研究报告
   */
  generate(result: ResearchResult): string {
    const sections: string[] = [];

    // 头部信息
    sections.push(this.generateHeader(result));

    // 经济周期判定
    sections.push(this.generateCycleSection(result));

    // 大类资产配置
    sections.push(this.generateAllocationSection(result.assetAllocation));

    // 子类资产优先级
    sections.push(this.generateSubCategorySection(result.assetAllocation));

    // 数据来源
    sections.push(this.generateSourcesSection(result.dataSources));

    // 风险提示
    sections.push(this.generateRiskSection());

    return sections.join('\n\n');
  }

  /**
   * 生成报告头部
   */
  private generateHeader(result: ResearchResult): string {
    const date = new Date(result.timestamp).toLocaleDateString('zh-CN', {
      year: 'numeric',
      month: 'long',
      day: 'numeric',
    });

    return `# 资产标的调研报告

**版本**: ${result.version}  
**引擎**: ${result.engineName}  
**日期**: ${date}  
**区域**: ${this.getRegionDisplay(result.region)}  
**置信度**: ${(result.confidence * 100).toFixed(0)}%  
`;
  }

  /**
   * 生成经济周期判定章节
   */
  private generateCycleSection(result: ResearchResult): string {
    const cycle = result.cycle;
    const config = CYCLE_CONFIG[cycle.currentPhase];

    return `## 一、经济周期判定

### 当前周期：${config.displayName}

**置信度**: ${(cycle.confidence * 100).toFixed(0)}%

**判定依据**:
${cycle.indicators.map(ind =>
  `- **${ind.name}**: ${ind.value} (${this.getTrendDisplay(ind.trend)})`
).join('\n')}

**分析**:
${cycle.rationale}
`;
  }

  /**
   * 生成大类资产配置章节
   */
  private generateAllocationSection(allocations: AssetAllocation[]): string {
    const cycle = allocations[0]?.subCategories?.[0]
      ? this.getCycleFromSubCategory(allocations[0].subCategories[0])
      : '';

    return `## 二、大类资产配置建议

基于当前经济周期，各资产大类建议配置如下：

| 资产类别 | 配置比例 | 配置方向 | 说明 |
|---------|---------|---------|------|
${allocations.map(a => {
  const directionEmoji = a.direction === 'overweight' ? '⬆️' :
                         a.direction === 'underweight' ? '⬇️' : '➡️';
  const directionText = a.direction === 'overweight' ? '超配' :
                        a.direction === 'underweight' ? '低配' : '标配';
  return `| ${a.displayName} | ${a.weight}% | ${directionEmoji} ${directionText} | ${this.getCategoryRationale(a.category)} |`;
}).join('\n')}
`;
  }

  /**
   * 生成子类资产优先级章节
   */
  private generateSubCategorySection(allocations: AssetAllocation[]): string {
    // 收集所有子类并排序
    const allSubCategories: SubCategoryAsset[] = [];
    for (const allocation of allocations) {
      allSubCategories.push(...allocation.subCategories.map(sub => ({
        ...sub,
        categoryDisplay: allocation.displayName
      })));
    }

    // 按优先级排序
    allSubCategories.sort((a, b) => a.priority - b.priority);

    // 标记前10名
    const top10 = new Set(allSubCategories.slice(0, 10).map(s => s.name));

    return `## 三、子类资产优先级

### Top 10 推荐标的

| 优先级 | 子类 | 大类 | 配置方向 | 推荐理由 |
|-------|------|------|---------|---------|
${allSubCategories.slice(0, 15).map((sub, idx) => {
  const isTop = top10.has(sub.name);
  const marker = isTop ? '🏆' : '';
  const directionEmoji = sub.direction === 'overweight' ? '⬆️' :
                        sub.direction === 'underweight' ? '⬇️' : '➡️';
  return `| ${idx + 1} | ${marker}${sub.displayName} | ${sub.categoryDisplay} | ${directionEmoji} | ${sub.rationale.substring(0, 30)}... |`;
}).join('\n')}

### 详细子类配置

${allocations.map(a => `
#### ${a.displayName}

${a.subCategories.map(sub => {
  const emoji = sub.direction === 'overweight' ? '🟢' :
                sub.direction === 'underweight' ? '🔴' : '🟡';
  return `- ${emoji} **${sub.displayName}**: ${sub.rationale}`;
}).join('\n')}
`).join('')}
`;
  }

  /**
   * 生成数据来源章节
   */
  private generateSourcesSection(sources: { name: string; url?: string; timestamp: string }[]): string {
    if (sources.length === 0) {
      return `## 四、数据来源

暂无数据来源信息（使用模拟数据）`;
    }

    return `## 四、数据来源

${sources.map(s => {
  const date = new Date(s.timestamp).toLocaleDateString('zh-CN');
  return `- [${s.name}](${s.url || '#'}) - ${date}`;
}).join('\n')}
`;
  }

  /**
   * 生成风险提示章节
   */
  private generateRiskSection(): string {
    return `## 五、风险提示

1. **模型局限性**: 美林投资时钟基于历史规律，未来市场可能呈现与历史不同的特征
2. **数据延迟**: 宏观经济数据通常存在发布延迟，周期判定可能滞后
3. **地域差异**: 美林时钟在美国市场验证较多，其他市场表现可能存在差异
4. **黑天鹅风险**: 未能预见的地缘政治、疫情等突发事件可能颠覆周期规律
5. **执行风险**: 实际交易需考虑流动性、交易成本、滑点等因素

---
*本报告仅供参考，不构成投资建议。投资有风险，入市需谨慎。*
`;
  }

  /**
   * 获取趋势显示文本
   */
  private getTrendDisplay(trend: 'up' | 'down' | 'flat'): string {
    const map = { up: '📈 上行', down: '📉 下行', flat: '➡️ 平稳' };
    return map[trend];
  }

  /**
   * 获取区域显示文本
   */
  private getRegionDisplay(region: string): string {
    const map = { global: '全球', us: '美国', cn: '中国' };
    return map[region] || region;
  }

  /**
   * 获取大类推荐理由
   */
  private getCategoryRationale(category: string): string {
    const rationale: Record<string, string> = {
      stock: '经济增长受益，风险资产首选',
      bond: '避险需求，固定收益稳定',
      commodity: '通胀对冲，实物资产保值',
      cash: '流动性储备，防御性配置',
      crypto: '高风险高收益，成长型配置',
    };
    return rationale[category] || '';
  }

  /**
   * 从子类别获取周期信息
   */
  private getCycleFromSubCategory(sub: SubCategoryAsset): string {
    if (sub.cyclePreference.length > 0) {
      return CYCLE_CONFIG[sub.cyclePreference[0]].displayName;
    }
    return '';
  }
}
