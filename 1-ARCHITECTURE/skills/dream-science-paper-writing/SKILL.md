---
name: dream-science-paper-writing
description: "科研论文写作。将策略研究成果撰写为结构化研究报告，借鉴 Style Calibration 方法平衡学术严谨性与工程可落地性。触发词：论文写作、研究报告、科研写作、paper writing"
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: Internal
status: proposed
category: research
triggers: [论文写作, 研究报告, 科研写作, paper writing, 撰写报告]
depends_on: [dream-science-literature-review, dream-science-hypothesis-verification, dream-science-statistics-check, nature-figure]
provides: [paper-writing, style-calibration]
---

# Dream Science Paper Writing — 科研论文写作 SKILL

> 将策略研究成果撰写为结构化研究报告/论文。
> 借鉴 Style Calibration 方法，平衡学术严谨性与工程可落地性。

> **双位置存储**：
> - `.trae/skills/dream-science-paper-writing/SKILL.md`（TRAE 调用入口）
> - `1-ARCHITECTURE/skills/research/dream-science-paper-writing/SKILL.md`（项目级索引副本）

---

## 一、何时调用

满足以下任一条件即调用：

1. **研究报告撰写**：策略研究完成后，需要撰写结构化报告
   - 触发词：「论文写作」「研究报告」「科研写作」「撰写报告」
2. **风格校准**：需要平衡学术严谨性与工程可落地性
3. **引用管理**：需要规范管理文献引用（DOI/URL 可追溯）
4. **图表嵌入**：需要将 nature-figure 产出的图表嵌入报告

---

## 二、IMRaD 结构模板

### Introduction（引言）

```markdown
## 1. Introduction

### 1.1 研究背景
（市场现象/问题陈述，含数据支撑）

### 1.2 研究问题
（PICO 格式：Population/Intervention/Comparison/Outcome）

### 1.3 研究贡献
（3-5 点，每点含具体成果）

### 1.4 论文结构
（各章节内容概述）
```

### Methods（方法）

```markdown
## 2. Methods

### 2.1 数据
（数据源、时间范围、预处理步骤）

### 2.2 策略设计
（策略逻辑、参数、触发条件）

### 2.3 回测设置
（回测引擎、滑点、手续费、基准）

### 2.4 统计检验
（检验方法、显著性水平、效应量指标）

### 2.5 消融实验
（组件移除实验设计）
```

### Results（结果）

```markdown
## 3. Results

### 3.1 描述性统计
（数据特征、样本量）

### 3.2 主要结果
（收益率、夏普比率、最大回撤等核心指标）

### 3.3 统计检验结果
（p 值、效应量、置信区间）

### 3.4 消融实验结果
（各组件贡献度）

### 3.5 图表
（嵌入 nature-figure 产出的图表）
```

### Discussion（讨论）

```markdown
## 4. Discussion

### 4.1 结果解读
（结果的经济含义和机制解释）

### 4.2 与现有研究对比
（与文献中类似策略的对比）

### 4.3 局限性
（样本偏差、过拟合风险、市场适应性）

### 4.4 结论边界声明
（结论适用的条件和范围）

### 4.5 未来工作
（可扩展的研究方向）
```

---

## 三、风格校准方法

> **借鉴来源**: Style Calibration（学术写作风格校准）

### 三维度校准

| 维度 | 学术端 | 工程端 | 平衡策略 |
|------|--------|--------|---------|
| **严谨性** | 严格统计检验 | 快速原型验证 | 核心结论需统计显著，探索性发现标注 |
| **可复现性** | 完整方法描述 | 代码可执行 | 提供代码 + 完整参数 |
| **可落地性** | 理论推导 | 实盘验证 | 回测 → 模拟盘 → 实盘渐进 |

### 风格校准检查清单

- [ ] 核心结论有统计检验支撑（p 值 + 效应量）
- [ ] 所有参数明确列出（无隐含参数）
- [ ] 数据来源可追溯（DOI/URL/时间戳）
- [ ] 代码可复现（提供运行命令）
- [ ] 结论边界明确声明（不夸大）
- [ ] 图表有标题和坐标轴说明

---

## 四、引用管理规范

### 引用格式

```markdown
[1] Author, A., & Author, B. (Year). Title. Journal, Volume(Issue), Pages. DOI: xxx
[2] Author, C. (Year). Title. arXiv:xxxx.xxxxx
```

### 引用规则

1. **必须可追溯**：每个引用必须有 DOI 或 URL
2. **禁止编造**：不得捏造不存在的文献
3. **直接引用**：原文引用需标注页码
4. **间接引用**：转述需标注来源
5. **自引**：引用自身先前工作需明确标注

### 引用检查（7 模式阻断）

- [ ] 所有引用均可通过 DOI/URL 验证
- [ ] 无虚构文献
- [ ] 引用与正文内容对应
- [ ] 关键论点有引用支撑
- [ ] 不遗漏重要相关工作

---

## 五、图表嵌入规范

### 配合 nature-figure

```markdown
![图1: 策略累计收益对比](path/to/figure.png)
*图1: 策略A vs 基准B的累计收益对比，样本期 2023-2024*
```

### 图表要求

1. **标题**：每个图表有简洁标题
2. **坐标轴**：标注轴名和单位
3. **图例**：多曲线必须有图例
4. **来源**：数据来源标注
5. **说明**：图表下方有一句话说明

---

## 六、结论边界声明

### 声明模板

```markdown
## 结论边界声明

本研究结论基于以下条件：
1. 数据样本：<时间范围> <市场>
2. 回测假设：<滑点> <手续费> <流动性假设>
3. 统计显著性：<p 值阈值> <检验方法>

结论不适用的场景：
1. <场景1>（如：极端市场波动）
2. <场景2>（如：流动性枯竭）

实盘应用建议：
1. 先在模拟盘验证 ≥ 1 个月
2. 初始仓位 ≤ 标准仓位的 50%
3. 设置止损和最大回撤限制
```

---

## 七、金融交易适配

### 适用场景
- 策略研究成果的正式记录和归档
- 策略评审前的结构化报告准备
- 跨团队策略知识传递

### 局限性
- 金融市场非平稳，历史结论不代表未来表现
- 回测存在过拟合风险，需配合样本外验证
- 交易成本（滑点/手续费）在不同市场差异大

### 适配建议
- 所有结论必须声明样本期和市场范围
- 回测结果需标注是否考虑滑点和手续费
- 建议配合 walk-forward 分析验证策略稳健性

---

## 八、输出规范

1. **完整 IMRaD 结构报告**（Markdown 格式）
2. **引用列表**（可追溯）
3. **图表嵌入**（配合 nature-figure）
4. **结论边界声明**

---

## 九、认知闭环

**前置 recall**:
```
recall(context="<研究主题> 论文写作 风格校准", top_k=5, min_quality="C")
```

**后置 record**:
```
record(content="[论文写作] <主题> | IMRaD结构 | 引用 <N> 篇 | 图表 <N> 个",
       quality_level="B",
       tags="科研SKILL,论文写作,风格校准,研究报告,<主题>")
```

---

## 十、相关 SKILL

| 类型 | 名称 | 用途 |
|------|------|------|
| 上游 | `dream-science-literature-review` | 文献综述（引用来源） |
| 上游 | `dream-science-hypothesis-verification` | 假设验证（结果来源） |
| 上游 | `dream-science-statistics-check` | 统计审查（结果验证） |
| 可视化 | `nature-figure` | 图表生成 |
| 编排 | `dream-science-orchestrator` | 科研任务编排 |

---

## 十一、版本历史

| 版本 | 日期 | 变更 |
|------|------|------|
| 1.0.0 | 2026-10-05 | 初始版本：IMRaD 模板 + 风格校准 + 引用管理 + 金融适配 |
