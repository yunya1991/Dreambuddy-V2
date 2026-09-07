# EV雷达离场系统

> **来源：** 11-易经推理系统/scripts/memory_l4/bcrm2/exit_manager.py
> **定位：** 持仓质量评估与离场决策系统

## EV雷达7子分评估

EV雷达通过7个子分评估持仓质量，综合输出EV值：

| EV值 | 动作 |
|------|------|
| EV < -0.35 | 强制离场 |
| EV -0.35 ~ 0 | 监控减仓 |
| EV > 0 | 持有 |

## 离场决策链路（exit_manager.py L83-185）

ExitManager按优先级链调用各ExitStrategy：

```
持仓监控
    │
    ├→ P0: 硬离场（EV<-0.35强制）
    │   └→ EXIT_ACT_EV_FORCE_CLOSE
    │
    ├→ P1: 信号反转
    │   └→ EXIT_ACT_SIGNAL_REVERSE
    │
    ├→ P2: 易经强制
    │   └→ EXIT_ACT_YIJING_FORCE_CLOSE
    │
    ├→ P3: P3提前退出
    │   └→ EXIT_ACT_P3_EARLY_EXIT
    │
    └→ P4: 排名止盈
        └→ EXIT_ACT_RANKED_TP
```

## 5种离场动作

| 动作常量 | 触发条件 | 说明 |
|---------|---------|------|
| EXIT_ACT_SIGNAL_REVERSE | 信号反转 | 原入场信号消失或反向 |
| EXIT_ACT_YIJING_FORCE_CLOSE | 易经卦象变化 | 卦象从吉转凶 |
| EXIT_ACT_P3_EARLY_EXIT | P3保护期结束 | 6小时保护期后提前退出 |
| EXIT_ACT_EV_FORCE_CLOSE | EV<-0.35 | 持仓质量恶化，强制离场 |
| EXIT_ACT_RANKED_TP | 排名止盈 | 持仓排名下降触发止盈 |

## 保护期机制

| 时段 | 规则 |
|------|------|
| 开仓后6小时内 | 仅硬离场（EV强制）生效，其他信号忽略 |
| 6小时后 | 所有离场信号正常生效 |

**POSITION_PROTECTION_HOURS = 6.0**

## 离场确认机制

- **EXIT_CONFIRM_REQUIRED = 2**：2次连续触发才执行
- **EXIT_CONFIRM_WINDOW_SEC = 300**：300秒确认窗口
- **目的：** 防止假信号导致频繁离场

## portfolio_mode

ExitManager支持portfolio_mode子链切换，根据组合状态调整离场策略优先级。

## 策略贡献统计

记录每个ExitStrategy的触发次数和贡献度，用于策略评估和参数调优。

## 与其他模块的关系

| 模块 | 关系 |
|------|------|
| BCRM2.0推理 | 离场信号来自BCRM推理结果 |
| 通用风控 | 离场需通过风控门禁确认 |
| CBR案例库 | 离场结果记录为案例（双时间点闭包） |
| 认知记忆 | 离场结果→record→verify→贝叶斯升级 |

---

_最后更新：2026-08-30 | 来源：exit_manager.py + polling_trader.py_
