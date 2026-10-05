---
name: nature-figure
description: Nature/高影响力期刊投稿级科研图工作流，含多面板证据架构、子图对齐门、PDF碰撞审计
version: 1.0.0
created: 2026-10-05
updated: 2026-10-05
license: MIT
status: active
category: tooling
domain: 1-ARCHITECTURE
triggers:
  - Nature figure
  - 投稿级图片
  - publication plot
  - scientific figure
  - figures4papers
  - 论文示意图
  - 回测图表
  - 策略可视化
depends_on:
  - nature-shared
provides:
  - scientific-figure
  - publication-plot
  - backtest-visualization
cognitive_links: []
---

# nature-figure Skill — Nature 投稿级科研图

> 源自 Yuan1z0825/nature-skills（MIT 协议）。面向 Nature / 高影响力期刊的 Python 或 R 投稿级科研图工作流。

## 何时调用

满足以下任一条件：
1. 需要生成 publication-grade 的回测结果图表
2. 需要将策略性能可视化（收益曲线、回撤、热力图等）
3. 需要多面板证据架构图（展示策略有效性的多维度证据）
4. 需要论文级示意图或概念图

## 核心能力

### 1. Results 级多面板证据架构
- 单个 figure 内组织多个子图，构建完整证据链
- 子图编排遵循 Nature 风格：主图 + 补充证据
- 每个子图有明确的统计学标注（p 值、效应量、置信区间）

### 2. 渲染时子图对齐门
- 渲染前检查所有子图的对齐一致性
- 确保坐标轴、字体大小、图例风格统一
- 防止子图错位或比例失调

### 3. 最终 PDF 自动文字/图形碰撞审计
- 渲染后自动检测文字与图形的碰撞
- 检测标注重叠、坐标轴标签溢出
- 输出碰撞报告和修正建议

### 4. 第三方 figures4papers 参考示例
- 集成 figures4papers 的最佳实践模板
- 提供常用图表类型的参考样式

### 5. 原创模板
- 回测收益曲线图模板
- 回撤分析图模板
- 策略热力图模板
- 多策略对比图模板

### 6. OpenRouter GPT Image 2 论文示意图草稿
- 可选：使用 GPT Image 2 生成论文示意图草稿
- 草稿可人工修改后定稿

## 使用方式

### 回测图表示例
```
请用 nature-figure 生成回测结果图表：
- 主图：策略累计收益 vs 基准累计收益
- 子图A：月度收益热力图
- 子图B：回撤曲线
- 子图C：年度收益柱状图
- 包含统计学标注（夏普比率、最大回撤、胜率）
- 输出 PDF 格式
```

### 多面板证据图示例
```
请用 nature-figure 生成策略有效性的多面板证据图：
- Panel A: 因子 IC 时间序列
- Panel B: 分层收益曲线
- Panel C: 不同市场状态下的策略表现
- Panel D: 参数敏感性热力图
- 每个面板标注 p 值和效应量
```

## 输出规范

1. **格式**：优先 PDF（矢量），可选 PNG/SVG
2. **分辨率**：PDF 矢量无损；PNG ≥ 300 DPI
3. **字体**：使用 Nature 推荐字体（Arial/Helvetica），主标题 8-10pt，轴标签 7-8pt
4. **颜色**：使用 colorblind-friendly 调色板
5. **统计学标注**：p < 0.05 用 *，p < 0.01 用 **，p < 0.001 用 ***
6. **图注**：每个 figure 必须有完整的图注（标题、方法、统计学说明）

## 约束

- 不修改原始数据
- 不在图表中掩盖数据缺失或异常值
- 统计学标注必须基于实际计算，不得伪造
- 图表必须可复现（提供代码和数据）

## 与 dreambuddy-v2 集成

- 与 `dream-backtest` 协同：回测结果用 nature-figure 可视化
- 与 `dream-science-statistics-check` 协同：统计审查结果标注在图表上
- 与 `dream-science-hypothesis-verification` 协同：假设验证结果用图表呈现

## 许可证

MIT License（源自 Yuan1z0825/nature-skills）
