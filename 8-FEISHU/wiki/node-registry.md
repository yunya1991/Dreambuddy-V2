# Wiki 节点注册表

> Space ID: 7646891742737730517
> Space URL: https://icnic28nu1x5.feishu.cn/wiki/

| # | 节点名 | node_token | obj_token | 内容 | 更新方式 |
|---|--------|------------|-----------|------|---------|
| 1 | 系统概览 | `（待创建）` | — | Dreambuddy 完整架构 | 手动维护 |
| 2 | 策略基线 | `SuN1w0CzMi7uQhk7UXZcShN8nNh` | `T6X6ddozIo1IvSx9R6ec0nyhn6c` | V15 基线+回测 | ProcessD 自动追加 |
| 3 | 市场研判 | `DzzywzNf0iIONnkCuJwcf6wGnQb` | `DnWtdOKpAo18iExwBQBcFalanUg` | 每周Screen1 | screen1-trigger 自动追加 |
| 4 | 风控手册 | `OoRUwHeRaizD0Dkx3e1c1pMYn5g` | `QunpdhiouoF0FgxrmxXcn28unAh` | Gate-C/A9/ESCALATE规则 | 手动维护 |
| 5 | 复盘档案 | `IJaUwEZYgiVR19kFudNctjXunZg` | `HpI4dEIDrojkCyxIfvhcZYBWnRh` | ProcessD复盘历史 | ProcessD 自动追加 |
| 6 | OKR 目标追踪 | `TrqvwpvVsiIygEkJBD8c95Mgnkd` | `IYRfdzJBRovpuexlOu4cBx9RnVb` | 季度OKR | AI自动更新进度 |
| 7 | 系统运行手册 | `（待创建）` | — | Hermes+飞书CLI操作 | 手动维护 |
| 8 | 知识积累 | `（待创建）` | — | 大师权重/象限规律 | ProcessD 自动更新 |

## 自动同步规则

```
screen1-trigger 完成
  └─ 追加到「市场研判」节点（本周研判 + 七维度评分卡）

process-d-trigger 完成
  ├─ 追加到「复盘档案」节点（A8得分+关键发现+改进提案）
  ├─ 覆盖「策略基线」中的回测报告段落（如有新数据）
  └─ 更新「知识积累」中的大师权重/象限规律

OKR KR 更新（ProcessD 或手动）
  └─ lark-cli okr +progress-create 自动写入飞书 OKR
```
