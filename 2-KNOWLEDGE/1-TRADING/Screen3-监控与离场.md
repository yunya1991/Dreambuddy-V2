# Screen3 — 监控与离场

> 三屏交易体系**执行层**，持仓实时监控 + 完整离场决策链。
> 源：dream-screen3-third, dream-exit-skill-v2

## 定位

| 项目 | 内容 |
|:---|---|
| **层级** | 执行层（第三屏） |
| **触发** | Cron 每工作日 09:00（screen3-teamb） |
| **离场子任务** | A9 每4h由A6动态启停 |
| **模型** | deepseek-v4-pro（dream-screen3-third / dream-exit-skill-v2） |
| **Skill绑定** | dream-screen3-third, dream-exit-skill-v2 |

## 执行流水线

```
Phase 0: 状态检查（持仓/预设新鲜度/连续Skip检测/Sleepwalk警报）
  ├── no_position → Phase 1(入场流程)
  └── holding → Phase 4(监控流程)

【入场路径】
Phase 1: A7门禁 → Phase 2: A4验证 → Phase 3: Gate C门禁 → Phase 3.5: A5下单

【监控路径】
Phase 4: A6实时监控 → 加仓信号 → 执行加仓
Phase 5: A9止盈止损 + 离场决策
```

## SCREEN3 推荐升级检测

连续2天相同的SCREEN3推荐（全SKIP或无操作）且无持仓变化 → **自动触发Sleepwalk警报**：
- `consecutive_skip_count ≥ 2` + `price_drift > 10%`
- 输出 `SCREEN1_REFRESH_REQUIRED`
- 建议全链路刷新 Screen1→Screen2→Screen3

## 离场决策链（A9四层）

| 层 | 名称 | 触发条件 |
|:---:|:---|---|
| L1 | 止盈止损 | 价格触及TP/SL位 |
| L2 | 信号反转 | A2第一性原理确认趋势反转 |
| L3 | 风险事件 | 风险库21事件（黑天鹅/政策突变/流动性枯竭） |
| L4 | 参数优化 | 时间止损/波动率异常 |

**红线**：最大回撤 ≥ 20% → 强制全部平仓，优先于四层

## OKX TP/SL 联动

- Screen3通过OKX CLI设置止盈止损订单
- A6监控期间动态调整TP/SL价位
- A9离场决策直接调用OKX平仓指令（`--profile dreamdemo`）

_最后更新：2026-06-13 | 来源：知识库完善_
