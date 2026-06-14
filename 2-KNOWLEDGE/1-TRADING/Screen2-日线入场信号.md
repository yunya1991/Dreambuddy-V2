# Screen2 — 日线入场信号筛选

> 三屏交易体系**战术层**，基于 Screen1 方向约束，筛选日线入场信号。
> 源：dream-screen2-second, screen2-trigger

## 定位

| 项目 | 内容 |
|:---|---|
| **层级** | 战术层（第二屏） |
| **触发** | Cron 每工作日 07:30（screen2-trigger） |
| **核心方法** | 按7种Regime匹配预设技术信号，筛选入场候选 |
| **模型** | deepseek-v4-pro（dream-screen2-second） |
| **Skill绑定** | dream-screen2-second → dream-backtest → dream-bayesian-opt |

## 工作流

```
Screen1(方向) → Screen2(入场信号) → Screen3(持仓监控)
                    ↓
            Phase 0: 价格漂移检查 + 到期倒计时
            Phase 1: 日线数据采集(FGI/波动率/持仓)
            Phase 2: A1矛盾调查 → A2第一性原理 → A3沙盘推演
            Phase 3: 回测验证 + 贝叶斯参数优化
            Phase 4: 预设输出 + 优先级排序
```

## 信号强度与仓位映射

| 评分区间 | 信号强度 | 仓位系数 |
|:---:|:---:|:---:|
| ≥ 70 | 强 | 100% |
| 50–69 | 中 | 60% |
| < 50 | 弱 | 30% |
| 无信号 | — | 10% |

## 关键规则

- 方向硬约束：Screen2不可翻转Screen1方向
- 冲突处理：A2与Screen1矛盾时遵循Screen1，降低仓位
- 不追高：当前价>预设价时等待回调
- 预设时效：3天新鲜度阈值，过期需刷新

## 关联

- **上游**：Screen1输出方向 + Regime分类
- **下游**：Screen3读取daily-presets.json执行入场
- **降级路径**：dream-screen2-second不可用时走screen2-trigger内联路径

_最后更新：2026-06-13 | 来源：知识库完善_
