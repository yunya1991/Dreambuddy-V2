# Skill: 资产标的调研

## 描述

基于美林投资时钟框架，跨股票/债券/商品/现金/加密五大类资产，提供经济周期判定和子类资产优先级排序。

## 触发词

- `资产调研`
- `标的调研`
- `美林时钟`
- `资产配置`
- `投资研究`
- `asset research`
- `investment research`

## 输入参数

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| region | string | 否 | 区域: global/us/cn，默认global |
| customIndicators | array | 否 | 自定义宏观经济指标 |

## 输出

```json
{
  "version": "1.0.0",
  "engineName": "Merrill Clock v1",
  "timestamp": "2025-01-01T00:00:00.000Z",
  "cycle": {
    "currentPhase": "recovery",
    "confidence": 0.85,
    "indicators": [...],
    "rationale": "..."
  },
  "assetAllocation": [...],
  "topSubCategories": [...],
  "report": "# 资产标的调研报告\n...",
  "dataSources": [...],
  "confidence": 0.85
}
```

## 使用示例

### 命令行

```bash
npx tsx -e "
import { runAssetResearch } from './6-TRADING/skills/asset-research/src';
const result = await runAssetResearch({ region: 'global' });
console.log(result.report);
"
```

### 代码调用

```typescript
import { AssetResearchOrchestrator, runAssetResearch } from './src';

// 方式1: 快速调用
const result = await runAssetResearch();

// 方式2: 使用编排器
const orchestrator = new AssetResearchOrchestrator();
const multiResult = await orchestrator.run({
  runAllVersions: true  // 运行所有版本对比
});
```

## 报告样例

生成Markdown格式研究报告，包含:
1. 经济周期判定
2. 大类资产配置建议
3. 子类资产优先级
4. 数据来源
5. 风险提示

## 注意事项

- 首次运行会从Tavily获取数据，需设置`TAVILY_API_KEY`
- 无API Key时使用模拟数据
- 建议定期运行以跟踪周期变化
