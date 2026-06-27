# 资产标的调研引擎（Asset Research Engine）

## 概述

基于美林投资时钟框架的资产标的调研模块，跨股票/债券/商品/现金/加密五大类资产，提供周期判断和子类优先级排序。

**定位**：独立模块，先验证价值再考虑接入A系列系统。

---

## 1. 版本演进策略

三版本并行验证，表现变差自动回退：

| 版本 | 名称 | 核心特性 | 状态 |
|------|------|---------|------|
| v1.x.x | 美林时钟经典版 | 周期判定 + 大类配置 + 子类排序 | 基线 |
| v2.x.x | 多因子增强版 | + 动量/估值/情绪因子打分 | 演进 |
| v3.x.x | 情景模拟版 | + 周期切换概率 + 多情景配置 | 终态 |

---

## 2. v1 美林时钟经典框架

### 2.1 经济周期判定

**核心指标**：
- 经济增长维度：GDP同比、PMI、工业增加值、失业率
- 通货膨胀维度：CPI同比、PPI同比、核心CPI

**四象限判定规则**：

| 周期 | 经济增长 | 通胀 | 经典配置 |
|------|---------|------|---------|
| 复苏 Recovery | 上行 | 下行 | 股票 > 债券 > 商品 > 现金 |
| 过热 Overheat | 上行 | 上行 | 商品 > 股票 > 现金 > 债券 |
| 滞胀 Stagflation | 下行 | 上行 | 现金 > 商品 > 债券 > 股票 |
| 衰退 Recession | 下行 | 下行 | 债券 > 现金 > 股票 > 商品 |

### 2.2 五大类资产配置

| 大类 | 子类 | 复苏 | 过热 | 滞胀 | 衰退 |
|------|------|------|------|------|------|
| **股票** | 科技股 | +++ | + | - | - |
| | 金融股 | ++ | + | - | - |
| | 能源股 | - | +++ | ++ | - |
| | 消费股 | + | + | + | ++ |
| | 周期股 | +++ | ++ | - | - |
| **债券** | 国债 | - | - | - | +++ |
| | 信用债 | ++ | + | - | - |
| | 可转债 | ++ | ++ | - | - |
| | 高收益债 | + | ++ | - | -- |
| **商品** | 贵金属 | - | + | +++ | + |
| | 能源 | - | ++ | ++ | - |
| | 工业金属 | + | +++ | - | - |
| | 农产品 | + | + | ++ | - |
| **现金/货币** | 美元 | - | - | ++ | ++ |
| | 人民币 | ++ | + | - | - |
| | 欧元 | - | - | + | + |
| | 日元 | - | - | + | ++ |
| **加密** | 主流币 | ++ | +++ | - | - |
| | 平台币 | + | ++ | - | - |
| | 二层网络 | + | ++ | - | - |
| | DeFi | ++ | + | - | - |
| | 基建公链 | + | ++ | - | - |

### 2.3 数据获取层

**Tavily搜索策略**：
- 搜索最新GDP/CPI/PMI数据
- 搜索央行利率决议
- 搜索就业/失业率数据
- 搜索权威机构经济展望（IMF/世界银行/高盛等）

**多源交叉验证**：
- 优先官方来源（国家统计局、美联储、IMF）
- 至少2个独立来源确认才采用

**数据新鲜度管理**：
- <7天：新鲜（正常权重）
- 7-30天：可接受（降低权重）
- >30天：陈旧（显著降低置信度）

---

## 3. 输出格式

### 3.1 机器可读数据（JSON）

```typescript
interface AssetResearchResult {
  version: string;
  engineName: string;
  timestamp: string;

  cycle: {
    currentPhase: 'recovery' | 'overheat' | 'stagflation' | 'recession';
    confidence: number; // 0-1
    indicators: {
      name: string;
      value: string;
      trend: 'up' | 'down' | 'flat';
      source: string;
    }[];
  };

  assetAllocation: {
    category: string;
    weight: number;
    direction: 'overweight' | 'neutral' | 'underweight';
    subCategories: {
      name: string;
      priority: number;
      rationale: string;
    }[];
  }[];

  report: string;
  dataSources: string[];
  confidence: number;
}
```

### 3.2 人可读报告（Markdown）

- 经济周期判定及依据
- 大类资产配置建议
- 子类资产优先级排序
- 风险提示
- 数据来源说明

---

## 4. 目录结构

```
6-TRADING/skills/asset-research/
├── SKILL.md                         # Skill定义
├── src/
│   ├── index.ts                     # 入口
│   ├── types.ts                     # 类型定义
│   ├── engines/
│   │   ├── base-engine.ts           # 基类
│   │   ├── v1-merrill-clock/
│   │   │   ├── index.ts
│   │   │   ├── cycle-detector.ts    # 周期判定
│   │   │   └── asset-allocation.ts  # 资产配置
│   │   ├── v2-multi-factor/          # v2 预留
│   │   └── v3-scenario-sim/         # v3 预留
│   ├── data/
│   │   ├── tavily-fetcher.ts        # Tavily获取
│   │   └── indicator-parser.ts      # 指标解析
│   ├── report/
│   │   ├── markdown-generator.ts     # 报告生成
│   │   └── json-serializer.ts       # JSON序列化
│   └── version-comparator.ts        # 版本对比器
├── tests/
│   └── v1-merrill-clock.test.ts
└── README.md
```

---

## 5. 版本对比机制

```typescript
interface VersionComparison {
  versions: string[];
  cycleAgreement: number;              // 周期判断一致度
  allocationCorrelation: number;        // 配置相关性
  topSubCategoriesOverlap: number;     // 推荐子类重合度
  recommendation: string;
  rollbackCandidate?: string;
}
```

---

## 6. 执行模式

- **按需执行**：用户手动触发
- **定期执行**：支持配置定时任务（Hermes调度）

---

## 7. 已知局限性（v1）

1. 地域适应性：美林时钟在美国市场验证较多，其他市场表现可能差异
2. 单周期模型：未处理长中短周期嵌套
3. 无回测验证：v1仅输出建议，不做历史验证

---

## 8. 后续演进方向

| 版本 | 增加内容 |
|------|---------|
| v2 | 动量因子、估值因子、情绪因子多维打分 |
| v3 | 周期切换概率预测、多情景配置建议 |

---

*文档版本：1.0.0*
*创建日期：2026-06-26*
