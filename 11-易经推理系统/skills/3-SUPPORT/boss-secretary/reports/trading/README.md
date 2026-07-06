---
title: "交易邮箱目录说明"
department: trading
type: documentation
date: "2026-04-22"
status: completed
tags: ["README"]
---

# 📬 交易邮箱 (Trading Mailbox)

> **用途**: A1-A5 交易决策链路产出物专用目录
> **创建日期**: 2026-04-22
> **管理规则**: 参见 `公司管理制度/04-工作流程/04-08-交易决策链路传递流程.md`

---

## 文件命名规范

| 环节 | 文件名格式 | 示例 |
|:---|:---|:---|
| A1 调研 | `a1_research_{YYYYMMDD}_{HHMM}.md` | `a1_research_20260422_1600.md` |
| A2 第一性原理 | `a2_first_principles_{YYYYMMDD}_{HHMM}.md` | `a2_first_principles_20260422_1620.md` |
| A3 战略指令 | `a3_strategy_{YYYYMMDD}_{HHMM}.md` | `a3_strategy_20260422_1640.md` |
| A4 侦察报告 | `a4_scout_{YYYYMMDD}_{HHMM}.md` | `a4_scout_20260422_1700.md` |
| A5 执行报告 | `a5_execution_{YYYYMMDD}_{HHMM}.md` | `a5_execution_20260422_1710.md` |
| 链路摘要 | `chain_summary_{YYYYMMDD}_EP{N}.md` | `chain_summary_20260422_EP49.md` |

## 标准补齐时间线

```
T+0   → A1 调研 (a1_research_*.md)
T+20m → A2 原理 (a2_first_principles_*.md)
T+40m → A3 战略 (a3_strategy_*.md)
T+60m → A4 侦察 (a4_scout_*.md)
T+70m → A5 执行 (a5_execution_*.md + chain_summary_*.md)
```

## 数据新鲜度

- 报告时间戳 < **4小时** = 新鲜，可使用
- 报告时间戳 > **4小时** = 过时，需重新生成

## ⚠️ 注意事项

- 本目录不走四邮箱信息流（不经过 Secretary-Processor）
- A5执行前直接扫描本目录检查链路完整性
- 文件按EP编号+日期管理，无需手动清理
