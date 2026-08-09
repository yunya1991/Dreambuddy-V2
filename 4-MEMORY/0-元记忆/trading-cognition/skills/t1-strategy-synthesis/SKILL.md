---
name: t1-strategy-synthesis
description: "Synthesize strategic directive, three-scenario Bayesian deduction, and contingency plan from T0 market cognition output."
---

# T1 战略合成 (Strategy Synthesis)

基于 T0 的 `market_cognition_report`，合成可执行的战略指令、三情景推演与三层应急预案。T1 不重新调研市场，只把 T0 的认知转化为"做什么 + 如果错怎么办"。

## Overview

T1 的职责是把"市场是什么"翻译成"我该怎么做"。它读取 T0 的 Regime + 阻力方向，输出 `directive_bias`（战略指令），生成 S1/S2/S3 三情景推演（概率经贝叶斯校准），并预制 `phase7_contingency` 应急预案。

T1 不重复 T0 的信息采集与冲突分析——如果发现 T0 报告缺维度，必须退回 T0，而不是自己在 T1 里补。

## When to Use

- T0 已输出 `market_cognition_report`，需要据此生成交易战略时
- 用户提到"战略制定 / 沙盘推演 / 情景分析 / 战略合成 / 策略指令 / 应急预案 / directive_bias / 多情景推演 / 黑天鹅 / 战略预案 / 贝叶斯校准"等触发词时
- T1 必须以 T0 为前置；T0 未完成时 T1 拒绝启动

<HARD-GATE>
1. **三情景概率闭合**：S1 + S2 + S3 概率之和必须 = 1.0（贝叶斯校准后），允许 ±0.01 容差，不允许"其他"兜底项。
2. **每情景必有证伪条件**：每个情景必须给出明确的证伪条件 + 止损方案，不允许"看涨就做多"无止损。
3. **WAIT 必有触发入场条件**：当 directive_bias = WAIT 时，必须给出转 LONG / SHORT 的具体触发条件（价格 / 时间 / 信号），不允许无限期等待。
</HARD-GATE>

## Core Steps

### Step 1 — 战略指令合成 (directive_bias)

读取 T0 的 `regime` + `resistance.score` + `direction`，映射为战略指令：

| T0 Regime | T0 方向 | directive_bias |
|-----------|---------|----------------|
| TREND_STRONG | LONG | `LONG` |
| TREND_STRONG | SHORT | `SHORT` |
| TREND_WEAK | LONG/SHORT | `PROBE`（试探性建仓，仓位减半） |
| RANGE_BOUND | NEUTRAL | `WAIT`（须给触发条件） |
| FALSE_BREAKOUT_RISK | * | `REDUCE`（减仓避险） |
| REVERSAL_RISK | * | `HEDGE`（对冲） |
| LOW_LIQUIDITY | * | `WAIT` |
| CHAOS | UNCERTAIN | `WAIT` |
| 区间下沿 + LONG 倾向 | * | `DIP_BUY`（逢低买） |

指令集：`LONG / SHORT / WAIT / REDUCE / PROBE / DIP_BUY / HEDGE`

### Step 2 — 历史模式匹配

从策略库检索相似 Regime + 相似阻力结构下的历史策略：
- 检索键：`(regime, resistance_score_bucket, primary_conflict_type)`
- 返回：历史胜率、平均盈亏比、典型失败模式
- 用途：校准 Step 3 的情景概率，避免主观锚定

若策略库无相似记录，标记 `pattern_match: none`，情景概率须更保守。

### Step 3 — S1/S2/S3 三情景推演

构建三个情景，**贝叶斯校准**概率：

- **S1（基准情景）**：概率最高，T0 主冲突延续
- **S2（次级情景）**：次级冲突升级或主冲突衰减
- **S3（尾部情景）**：黑天鹅或 Regime 切换

每个情景必须包含：
```yaml
scenario_id: S1
probability: 0.55          # 贝叶斯校准后
description: ...
target_price: ...
trigger_conditions:        # 进入该情景的触发条件
  - ...
validation_standards:      # 验证该情景成立的标准
  - ...
falsification_conditions:  # 证伪条件（HARD-GATE 2）
  - ...
stop_loss: ...             # 止损方案
```

**贝叶斯校准流程**：
1. 先验概率 = 历史模式匹配的频率（无记录则 0.5/0.3/0.2）
2. 似然 = T0 证据对每个情景的支持度
3. 后验 = 先验 × 似然，归一化使三者之和 = 1.0

### Step 4 — 沙盘推演

对每个情景执行"假设 → 验证 → 响应"循环：

1. **假设**：若 S1 成立，未来 N 个周期价格 / 持仓 / 情绪如何演化
2. **验证标准**：哪些可观测指标能确认 / 否定该演化
3. **响应动作**：每个验证节点的对应操作（加仓 / 减仓 / 持有 / 止损）

沙盘推演的产物是一张"情景—验证—动作"映射表，供执行层实时对照。

### Step 5 — phase7_contingency 应急预案

预制三层应急预案：

1. **黑天鹅层**：极端不可预见事件（交易所宕机、监管突袭、闪崩）
   - 触发：单日波动 > 历史 99 分位
   - 动作：立即平仓至风险预算下限，禁止加仓
2. **极端情景层**：S3 情景实现
   - 触发：S3 的 validation_standards 命中
   - 动作：按 S3 的 stop_loss 执行，转向对冲
3. **概率情景层**：S1/S2 概率反转
   - 触发：S1 后验概率从基准下降 >0.2，S2 上升对应幅度
   - 动作：减仓至 PROBE 仓位，重新跑 T0

## Output Schema

T1 产出 `strategy_directive`，包含：
```yaml
directive_bias: LONG|SHORT|WAIT|REDUCE|PROBE|DIP_BUY|HEDGE
pattern_match:
  history_hits: ...
  win_rate: ...
  avg_rr: ...
scenarios:
  S1: {probability, target, triggers, validation, falsification, stop_loss}
  S2: {...}
  S3: {...}
scenario_prob_sum: 1.0          # HARD-GATE 1
sandbox:                        # 情景—验证—动作映射
  - {scenario, check, action}
contingency:
  black_swan: {trigger, action}
  extreme: {trigger, action}
  probability_flip: {trigger, action}
wait_trigger: ...               # HARD-GATE 3，仅 WAIT 时填
timestamp: ...
```

## Checklist

执行 T1 时按序勾选：

- [ ] T0 `market_cognition_report` 已读取，Regime / 阻力 / 方向完整
- [ ] directive_bias 已按映射表生成，与 T0 输出一致
- [ ] 历史模式匹配已检索（无记录时标记 `none` 并保守化）
- [ ] S1/S2/S3 三情景已构建，每情景含目标价 + 触发 + 验证 + 证伪 + 止损
- [ ] 三情景概率经贝叶斯校准，之和 = 1.0（±0.01）
- [ ] 沙盘推演映射表已完成
- [ ] phase7_contingency 三层预案齐全
- [ ] 若 directive_bias = WAIT，已给出具体触发入场条件
- [ ] `strategy_directive` 已结构化输出

## Anti-Patterns

- **概率不闭合**：S1+S2+S3 ≠ 1.0，或塞"其他"兜底——违反 HARD-GATE 1
- **无证伪情景**：只讲目标价不讲止损——违反 HARD-GATE 2
- **无限期 WAIT**：WAIT 无触发条件，本质是拒绝决策——违反 HARD-GATE 3
- **T1 内补 T0**：发现 T0 缺维度自己在 T1 补，应退回 T0 重跑
- **主观锚定概率**：跳过历史模式匹配直接拍概率，易受近因偏差
- **沙盘无动作**：推演只写"可能涨"不写"涨了加多少仓"，无法执行
