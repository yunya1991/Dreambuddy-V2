# Asset Research Engine

基于美林投资时钟框架的资产标的调研引擎。

## 功能特性

- **v1.0.0**: 美林投资时钟经典框架
  - 经济周期四象限判定（复苏/过热/滞胀/衰退）
  - 五大类资产配置（股票/债券/商品/现金/加密）
  - 子类资产优先级排序
  - Tavily API宏观经济数据获取
  - Markdown报告 + JSON结构化输出

## 快速开始

```typescript
import { runAssetResearch } from './src';

// 运行研究
const result = await runAssetResearch({
  region: 'global',  // global/us/cn
});

// 输出报告
console.log(result.report);

// 输出JSON
console.log(JSON.stringify(result, null, 2));
```

## API

### runAssetResearch(options?)

运行资产标的调研。

**选项**:
- `region`: 区域 (`global` | `us` | `cn`)
- `customIndicators`: 自定义宏观经济指标
- `runAllVersions`: 是否并行运行所有版本

**返回**: `ResearchResult`

### MultiVersionResult

多版本对比结果:

```typescript
{
  results: ResearchResult[];        // 各版本结果
  comparison?: VersionComparison;   // 版本对比
  bestVersion?: string;             // 最佳版本
}
```

## 数据来源

默认使用Tavily API获取宏观经济数据。设置环境变量:

```bash
export TAVILY_API_KEY=your_api_key
```

## 版本说明

| 版本 | 名称 | 状态 |
|------|------|------|
| v1.x | 美林时钟经典版 | ✅ 可用 |
| v2.x | 多因子增强版 | 🚧 开发中 |
| v3.x | 情景模拟版 | 🚧 规划中 |

## License

MIT
