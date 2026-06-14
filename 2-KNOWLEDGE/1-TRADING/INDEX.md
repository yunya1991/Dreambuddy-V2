# 1-TRADING — 交易领域知识

> 交易系统核心知识：三屏架构、马丁仓位管理、信号体系、风控、参数。
> L3 领域知识层 — 上层：[0-SCHEMA/](../0-SCHEMA/) |
> 同层：其他L3域 [2-TECHNICAL/](../2-TECHNICAL/)、[3-THEORY/](../3-THEORY/)、[4-OPERATIONS/](../4-OPERATIONS/) → 下层：[5-METHODOLOGY/](../5-METHODOLOGY/)
> 三链交叉引用：关联 5-METHODOLOGY/ 三链方法论（调研→规划→执行）

## 文件列表

| 文件 | 说明 | 来源 Skill |
|:---|---|:---|
| [V9-马丁基线](./V9-马丁基线.md) | 马丁仓位管理 V9 规则（不可修改） | dream-risk-position-sizing |
| [三屏系统架构](./三屏系统架构.md) | Screen1→Screen2→Screen3 架构总览 | screen1, dream-screen2, dream-screen3 |
| [Screen1-七维牛熊评分](./Screen1-七维牛熊评分.md) | 周线方向判定框架 | screen1 |
| [Screen2-日线入场信号](./Screen2-日线入场信号.md) | 日线入场信号规则 | dream-screen2-second |
| [Screen3-监控与离场](./Screen3-监控与离场.md) | 实时监控与离场策略 | dream-screen3-third |
| [A系列调度链](./A系列调度链.md) | A1-A9 任务链概览 | multiple dream-* |
| [交易参数速查](./交易参数速查.md) | vol_mult、仓位、币种等参数 | dream-risk-position-sizing |
|| [风控体系](./风控体系.md) | 风险评估与预算控制 | dream-pretrade-gatekeeper |
|| [信号生成体系](./信号生成体系.md) | 信号分类/组合逻辑/阈值决策/仓位映射表 | 信号体系蒸馏 |

## 知识流

```
行情数据 → 指标计算 → 多维评分 → 方向判定 → 入场信号 → 仓位管理 → 执行 → 监控/离场
  (Screen2)   (Screen2)   (Screen1)   (Screen1)    (Screen2)   (V9/V14)  (Screen3)  (A6/A9)
```

## 三链交叉引用

| 链 | 对应方法论 | 交易域应用 |
|:---|:---|---|
| **D链（调研）** | D-调研方法论 | Screen1 七维评分调研、A1 深度市场调研 |
| **Z链（规划）** | Z-规划方法论 | Screen2 入场信号规划、A2-A3 战略制定 |
| **E链（执行）** | E-执行方法论 | Screen3 实时执行、A4-A5 战术验证与执行 |

> 完整三链协议参见 [5-METHODOLOGY/三链接力协议](../5-METHODOLOGY/三链接力协议.md)

_最后更新：2026-06-13 | 来源：知识库完善 | 总文件数：10（含INDEX）_
