---
title: "大师知识库索引"
department: knowledge
type: master_index
tags: [masters]
date: "2026-04-18T00:00:00"
status: completed
---

# 大师知识库索引

> **版本**: v1.1  
> **更新日期**: 2026-04-18  
> **管理者**: ADVISOR-KB  

---

## 概览

大师知识库收录交易领域传奇人物的核心原则与经验，按以下分类组织：

| 大师 | 专长 | 著作 | 状态 | 路径 |
|:---|:---|:---|:---:|:---|
| Richard Dennis | 趋势跟踪 | Turtle Trading | ✅ 已完成 | [rules.md](./turtle/rules.md) |
| Edwin Lefevre | 投机哲学 | Reminiscences of a Stock Operator | ✅ 已完成 | [summary.md](./livermore/summary.md) |
| Mark Douglas | 交易心理 | Trading in the Zone | ✅ 已完成 | [summary.md](./douglas/summary.md) |
| Van Tharp | 期望值系统 | Trade Your Way to Financial Freedom | ✅ 已完成 | [summary.md](./tharp/summary.md) |

---

## 快速导航

### 🐢 海龟交易法则 (Richard Dennis)

**核心原则**:
- 趋势跟踪优于预测
- N 的 2% 法则
- 让利润奔跑，截断亏损
- 一致性决定成败

**关键文件**:
- `turtle/rules.md` - 完整交易规则
- `turtle/examples.md` - 5个实战案例

**案例摘要**:
| 案例 | 结果 | 教训 |
|:---|:---:|:---|
| BTC 趋势跟踪 | +4.5% | 突破入场，趋势持有 |
| ETH 假突破 | -0.7% | 需等待确认 |
| SOL 双共振 | +3.6% | 双系统信号更强 |
| BTC 连续亏损 | +1.75% | 保持纪律 |
| ETH 让利润跑 | +19.8% | 耐心持有16天 |

---

### 📈 大作手 (Edwin Lefevre)

**核心原则**:
- 时机就是一切
- 关键点突破
- 阻力最小的方向
- 金字塔加仓

**关键文件**:
- `livermore/summary.md` - 完整总结

---

### 🧠 交易心理 (Mark Douglas)

**核心原则**:
- 概率思维
- 期望值思维
- 市场无记忆
- 一致性执行

**关键文件**:
- `douglas/summary.md` - 完整总结

---

### 📊 期望值系统 (Van Tharp)

**核心原则**:
- R-Multiple 标准化
- 仓位管理决定成败
- 期望值公式
- 心理蓝图

**关键文件**:
- `tharp/summary.md` - 完整总结

---

## 四位大师核心要点对比

| 大师 | 核心概念 | 第一优先 | 关键指标 |
|:---|:---|:---|:---|
| 海龟 | 趋势跟踪 | 突破系统 | ATR, N |
| 大作手 | 时机把握 | 关键点 | 盘整突破 |
| Douglas | 概率思维 | 心理控制 | 期望值 |
| Tharp | 仓位管理 | R-Multiple | 风险% |

---

## 教训提炼矩阵

| 教训 | 来源 | Dream 应用 |
|:---|:---|:---|
| 让利润奔跑 | 海龟 + 大作手 | 动态止盈 |
| 截断亏损 | 海龟 + Douglas | 严格止损 |
| 仓位管理 | Tharp | risk-position-sizing |
| 概率思维 | Douglas + Tharp | 期望值评分 |
| 时机把握 | 大作手 | Step 1-2 分析 |
| 一致性执行 | 全部 | Step 6 质量门禁 |

---

## 核心教训提炼

### 从海龟学到的 (已实施)

| 教训 | Dream 实现 |
|:---|:---|
| 趋势跟踪 | Step 3 信号评分偏向趋势 |
| N 的 2% 法则 | dream-risk-position-sizing |
| 让利润奔跑 | 动态止盈机制 |
| 一致性执行 | Step 6 质量门禁 |

---

## 引用格式

当需要引用大师知识时，使用以下格式：

```
引用: {大师名} - {著作} - {章节}
示例: Richard Dennis - Turtle Trading - 第二章
```

---

## 贡献指南

### 添加新大师

1. 在 `masters/` 下创建 `{name}/` 目录
2. 创建 `{name}/summary.md` 作为主文件
3. 在本索引更新条目
4. 更新 `company_structure.yaml` 的 masters 列表

### 更新现有大师

1. 修改对应 `{name}/{file}.md`
2. 在版本记录中添加修订说明
3. 通知 ADVISOR-KB 知识库已更新

---

## 版本历史

| 版本 | 日期 | 变更 |
|:---:|:---|:---|
| v1.0 | 2026-04-18 | 初始版本，完成海龟交易法则蒸馏 |
