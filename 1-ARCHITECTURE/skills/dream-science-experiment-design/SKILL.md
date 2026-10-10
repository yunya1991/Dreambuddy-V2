---
name: dream-science-experiment-design
description: "科研实验设计。设计回测/对照实验的具体方案，确保实验可复现、可验证。触发词：实验设计、回测设计、对照实验、experiment design"
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Internal
status: proposed
category: research
triggers: [实验设计, 回测设计, 对照实验, experiment design, A/B测试]
depends_on: [dream-science-hypothesis-verification, dream-science-statistics-check, dream-backtest]
provides: [experiment-design, reproducibility]
---

# Dream Science Experiment Design — 科研实验设计 SKILL

> 设计回测/对照实验的具体方案，确保实验可复现、可验证。
> 复用 dream-backtest 的回测能力，配合 dream-science-statistics-check 做统计验证。

> **双位置存储**：
> - `.trae/skills/dream-science-experiment-design/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/research/dream-science-experiment-design/SKILL.md`（项目级索引副本）

---

## 一、何时调用

满足以下任一条件即调用：

1. **实验设计**：需要为策略验证设计回测/对照实验方案
   - 触发词：「实验设计」「回测设计」「对照实验」「A/B测试」
2. **可复现性保障**：需要确保实验结果可被他人复现
3. **统计功效分析**：需要估算样本量是否足够
4. **消融实验设计**：需要设计组件移除实验

---

## 二、实验设计模板

### 实验组/控制组设计

```yaml
experiment:
  name: "<实验名称>"
  hypothesis: "<待验证假设>"
  
  groups:
    - name: "实验组 (Treatment)"
      strategy: "<策略A>"
      parameters: {...}
      
    - name: "控制组 (Control)"
      strategy: "<基准策略B>"
      parameters: {...}
  
  control_variables:
    - time_window: "<统一时间窗>"
    - slippage: "<统一滑点>"
    - commission: "<统一手续费>"
    - data_source: "<统一数据源>"
  
  metrics:
    - return
    - sharpe_ratio
    - max_drawdown
    - win_rate
```

### 控制变量原则

1. **唯一变量**：实验组与控制组仅在待验证因素上不同
2. **环境统一**：时间窗、数据源、滑点、手续费必须一致
3. **随机化**：如涉及随机因素，设置随机种子

---

## 三、回测参数规范

### 必需参数

| 参数 | 说明 | 默认值 |
|------|------|--------|
| `time_window` | 回测时间范围 | 近 2 年 |
| `slippage` | 滑点（bp） | 5 bp |
| `commission` | 手续费（bp） | 1 bp |
| `initial_capital` | 初始资金 | 100,000 USDT |
| `position_size` | 仓位比例 | 100% |
| `leverage` | 杠杆 | 1x |
| `benchmark` | 基准策略 | Buy & Hold |
| `data_frequency` | 数据频率 | 1h |

### 时间窗设置原则

| 实验类型 | 建议时间窗 | 说明 |
|---------|-----------|------|
| 日内策略 | ≥ 6 个月 | 覆盖不同市场状态 |
| 短线策略 | ≥ 1 年 | 包含牛熊周期 |
| 中长线策略 | ≥ 2 年 | 覆盖完整市场周期 |
| 跨周期验证 | ≥ 3 年 | 样本内 + 样本外 |

---

## 四、对照实验设计（A/B 策略对比）

### A/B 对比模板

```yaml
ab_test:
  name: "<对比实验名称>"
  objective: "<对比目标>"
  
  strategy_a:
    name: "<策略A名称>"
    description: "<策略A描述>"
    logic: "<核心逻辑>"
    
  strategy_b:
    name: "<策略B名称>"
    description: "<策略B描述>"
    logic: "<核心逻辑>"
  
  comparison_metrics:
    - return: "收益率"
    - sharpe: "夏普比率"
    - max_dd: "最大回撤"
    - calmar: "卡玛比率"
    - win_rate: "胜率"
  
  statistical_tests:
    - "Mann-Whitney U test (收益率分布)"
    - "Bootstrap (夏普比率置信区间)"
```

### A/B 检验统计方法

| 对比指标 | 推荐检验 | 零假设 |
|---------|---------|--------|
| 收益率均值 | t-test / Mann-Whitney U | 两组收益率均值无差异 |
| 夏普比率 | Bootstrap | 夏普比率无差异 |
| 最大回撤 | 置换检验 | 最大回撤无差异 |
| 胜率 | 卡方检验 | 胜率无差异 |

---

## 五、可复现性检查清单

### 数据可复现

- [ ] 数据源明确（交易所/API/版本）
- [ ] 数据时间戳精确到分钟
- [ ] 数据预处理步骤完整描述
- [ ] 缺失值处理方法说明

### 代码可复现

- [ ] 提供完整代码（策略 + 回测）
- [ ] 依赖版本锁定（requirements.txt / package.json）
- [ ] 随机种子固定
- [ ] 运行命令明确

### 结果可复现

- [ ] 回测参数完整列出
- [ ] 输出指标计算方法说明
- [ ] 图表可重新生成
- [ ] 关键结果数值记录

---

## 六、统计功效分析

### 样本量估算

```
所需样本量 n = (Z_α/2 + Z_β)² × (σ₁² + σ₂²) / δ²

其中:
- Z_α/2: 显著性水平对应的 Z 值（α=0.05 → 1.96）
- Z_β: 统计功效对应的 Z 值（β=0.2 → 0.84）
- σ₁, σ₂: 两组标准差
- δ: 可检测的最小效应量
```

### 功效判断标准

| 功效 (1-β) | 含义 | 建议 |
|-----------|------|------|
| ≥ 0.8 | 充足 | 实验可进行 |
| 0.5–0.8 | 不足 | 增加样本量或放宽效应量 |
| < 0.5 | 严重不足 | 重新设计实验 |

### 金融交易特殊考虑

- 日频数据：1 年 ≈ 252 个样本
- 小时频数据：1 年 ≈ 6,000 个样本
- 分钟频数据：1 年 ≈ 360,000 个样本
- 注意：高频数据存在自相关，有效样本量需打折

---

## 七、金融交易适配

### 适用场景
- 新策略上线前的回测验证
- 策略改进前后的 A/B 对比
- 策略组件贡献度分析（消融实验）

### 局限性
- 回测 ≠ 实盘：滑点、流动性、市场冲击在回测中难以精确模拟
- 过拟合风险：参数优化可能在样本内表现好但样本外失效
- 幸存者偏差：回测数据可能已剔除退市标的
- 前视偏差：策略可能使用了未来信息

### 适配建议
- 必须做样本外验证（walk-forward analysis）
- 建议在模拟盘运行 ≥ 1 个月再考虑实盘
- 回测参数需标注是否考虑滑点和手续费
- 对参数敏感性做分析（±10% 参数变化的影响）

---

## 八、输出规范

1. **实验设计方案**（YAML 格式）
2. **回测参数清单**
3. **可复现性检查清单**
4. **统计功效分析结果**

---

## 九、认知闭环

**前置 recall**:
```
recall(context="<实验主题> 实验设计 回测 可复现", top_k=5, min_quality="C")
```

**后置 record**:
```
record(content="[实验设计] <实验名称> | 实验组 vs 控制组 | 样本量 <N> | 功效 <X.X>",
       quality_level="B",
       tags="科研SKILL,实验设计,回测,可复现,统计功效,<主题>")
```

---

## 十、相关 SKILL

| 类型 | 名称 | 用途 |
|------|------|------|
| 上游 | `dream-science-hypothesis-verification` | 假设验证（实验目标） |
| 工具 | `dream-backtest` | 回测执行 |
| 验证 | `dream-science-statistics-check` | 统计审查 |
| 编排 | `dream-science-orchestrator` | 科研任务编排 |

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-05 | 初始版本：实验设计模板 + 回测参数 + 可复现性 + 统计功效 + 金融适配 |
