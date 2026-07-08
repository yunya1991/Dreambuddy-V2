---
name: dream-pretrade-gatekeeper
description: 统一执行"交易前门禁"：数据完整性、评分冲突、账户回撤熔断、执行成本/滑点阈值、事件风险与 Dream Mode 降级，输出 PASS/SKIP 与理由码。
license: Internal
---

# Dream-Pretrade-Gatekeeper: 统一交易前门禁

> **⚠️ 顾问集成 (v2.0)**: 门禁规则本身不直接调用顾问评审，但 A5 执行链路在门禁通过后会调用 `advisor_direct_call.advisors_review(scene="RISK_REVIEW")` 进行 RM 最终确认。见 `dream-tactical-executor` 铁律四。

## 目标
- 把所有"一票否决"规则集中，避免 dream-multiSkill 分散判断导致遗漏。
- 输出标准化 PASS/SKIP + reason codes，便于审计与复盘。

## 输入（建议字段）
- `strategy_directive`（来自 `dream-strategy-parser`） ⭐ 新增 P0
  - `matched_strategy`: string | null
  - `directive_bias`: "LONG" | "SHORT" | "WAIT" | "REDUCE" | null
  - `position_modifier`: 0.0-1.0
  - `leverage_cap`: number | null
  - `exclusion_conditions_checked`: string[]
  - `match_confidence`: 0-1
- `data_health`
  - `candles_ok`: boolean
  - `funding_ok`: boolean
  - `oi_ok`: boolean
  - `macro_ok`: boolean
- `scores_result`（来自 `dream-signal-scoring-spec`）
  - `scores`: { `trend_strength`: 0-10, `macro_fund_tailwind`: 0-10, `memory_safety`: 0-10, `strategy_match`: 0-10, `total`: 0-70 } ⭐ 更新：增加strategy_match，总分0-70
  - `expected_return`: { `expected_return_bps`: number, `expected_return_range_bps`: object }
  - `gates`: { `pass`: boolean, `reason_codes`: string[] }
- `position_result`（来自 `dream-risk-position-sizing`）
  - `pass`: boolean
  - `reason_codes`: string[]
  - `position`: { `notional_usdt`: number, `lever`: number }
- `execution_cost_result`（来自 `dream-execution-cost-model`）
  - `pass`: boolean
  - `reason_codes`: string[]
  - `costs`: { `worst_case_slippage_bps`: number, `total_cost_bps_est`: number }
- `validation_result`（可选）
  - `hit_ratio_rolling`: number | null
  - `profit_factor_rolling`: number | null
  - `stability_flag`: "stable" | "unstable" | "unknown"
- `regime_result`（可选）
  - `market_regime`: "trend" | "range" | "unknown"
  - `vol_regime`: "high" | "low" | "unknown"
- `account_snapshot`（可选）
  - `today_drawdown_pct`: number
  - `dream_mode_active`: boolean
- `policy`
  - `min_dim_score`: number (default 3)
  - `min_total_score`: number (default 12)
  - `max_worst_slippage_bps`: number (default 60)
  - `lambda_risk`: number (default 1.0)
  - `edge_min_bps`: number (default 0)
  - `execution_blackout_windows`: string[] (如宏观数据发布窗口/交易所维护窗口)

## 输出（必须结构化）
- `decision`: "PASS" | "SKIP"
- `reason_codes`: string[]
- `degradations`: string[]
- `edge_eval`（新增）
  - `expected_return_bps`: number
  - `costs_bps`: number
  - `risk_bps`: number
  - `lambda_risk`: number
  - `edge_bps`: number

## 决策规则（最小可执行版）
- 数据完整性 fail-closed：
  - 任一核心数据源缺失 → `SKIP` + `HARD_FAIL_MISSING_CORE_DATA`
- ⭐ 杠杆门禁（P003 落地 — 在评分门禁之前检查）：
  - **实际杠杆计算**: `actual_lever = notional_value / total_equity` (使用equity，非frozen)
  - **杠杆上限检查**:
    - 全仓模式: 实际杠杆 > 2x → `SKIP` + `HARD_FAIL_LEVERAGE_EXCEEDS_CAP`
    - 若 `strategy_directive.leverage_cap` 有值: 实际杠杆 > leverage_cap → `SKIP` + `HARD_FAIL_LEVERAGE_EXCEEDS_CAP`
  - **OKX显示杠杆 vs 实际杠杆校验**:
    - 若输入包含 `position_result.position.lever` (OKX显示杠杆)
    - 计算差异率: `|actual_lever - okx_display_lever| / actual_lever`
    - 若差异率 > 20%: 记录 `HARD_FAIL_LEVERAGE_MISMATCH` 但不阻断（给出警告）
  - **⚠️ 关键教训**: OKX显示杠杆 ≠ 实际杠杆，因显示杠杆 = 名义/frozen，实际杠杆 = 名义/equity
- ⭐ 战略门禁（新增 P0 — 最高优先级，在评分门禁之前检查）：
  - `strategy_directive.exclusion_conditions_checked` 非空（战略被排除条件命中） → `SKIP` + `HARD_FAIL_STRATEGY_EXCLUDED`
  - `strategy_directive.directive_bias` == "REDUCE" → 允许 `PASS` 但强制降级（仓位上限 * position_modifier, 杠杆上限 * leverage_cap）+ `DEGRADE_STRATEGY_REDUCED_RISK`
  - `strategy_directive.directive_bias` == "WAIT" → 允许 `PASS` 但输出 `SOFT_WARN_STRATEGY_DIRECTS_WAIT`（战术可在极强信号时覆盖，但必须记录理由）
  - `strategy_directive` 为 null 且 `scores.strategy_match <= 3` → `SKIP` + `HARD_FAIL_NO_STRATEGY_EXTREME_REGIME`（极端行情且无战略指导，fail-closed）
  - `strategy_directive.directive_bias` == "LONG" → 仅允许 BUY 方向通过，SHORT 被拦截 + `HARD_FAIL_STRATEGY_DIRECTION_MISMATCH`
  - `strategy_directive.directive_bias` == "SHORT" → 仅允许 SHORT 方向通过，BUY 被拦截 + `HARD_FAIL_STRATEGY_DIRECTION_MISMATCH`
- 评分门禁：
  - 任一维度 < `min_dim_score` → `SKIP` + `HARD_FAIL_LOW_DIM_SCORE`
  - 总分 < `min_total_score` → `SKIP` + `HARD_FAIL_LOW_TOTAL_SCORE`
  - `scores_result.gates.pass=false` → `SKIP` 并透传其 reason codes
- 执行风险门禁：
  - `execution_cost_result.pass=false` → `SKIP` 并透传
  - `worst_case_slippage_bps > max_worst_slippage_bps` → `SKIP` + `HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH`
- 收益-风险-成本统一判定（新增，强约束）：
  - 计算 `edge_bps = E[R]_bps - Costs_bps - λ * Risk_bps`
  - 其中：
    - `E[R]_bps = scores_result.expected_return.expected_return_bps`
    - `Costs_bps = execution_cost_result.costs.total_cost_bps_est`
    - `Risk_bps` 由仓位风险占用/止损风险换算（若无精确口径，采用保守代理并加 `ASSUMPTION_*`）
    - `λ = policy.lambda_risk`
  - 若 `edge_bps <= policy.edge_min_bps`：`decision=SKIP` + `HARD_FAIL_NEGATIVE_EDGE`
- 账户层门禁：
  - 当日回撤熔断由 `position_result` 或 `account_snapshot` 触发时 → `SKIP`
- 事件黑窗门禁（新增）：
  - 若当前时段落入 `execution_blackout_windows`（宏观数据发布、交易所维护等）→ `SKIP` + `HARD_FAIL_EXECUTION_BLACKOUT_WINDOW`
- Dream Mode（降级而非必停）：
  - 若 `dream_mode_active=true`：允许 PASS，但要求降级执行（例如限制杠杆/名义），并输出 `DEGRADE_DREAM_MODE_RISK_REDUCTION`
- 统计与 Regime（可选门禁增强）：
  - 若 `stability_flag=unstable` 或 `profit_factor_rolling` 低于策略阈值：允许 PASS 但强制降级，并输出 `DEGRADE_VALIDATION_WEAK`
  - 若 `vol_regime=high` 且滑点压力高：优先触发降级而非直接放行高杠杆

## 理由码（建议集合）
- `HARD_FAIL_MISSING_CORE_DATA`
- `HARD_FAIL_LOW_DIM_SCORE`
- `HARD_FAIL_LOW_TOTAL_SCORE`
- `HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH`
- `HARD_FAIL_NEGATIVE_EDGE`
- `HARD_FAIL_EXECUTION_BLACKOUT_WINDOW`
- `HARD_FAIL_STRATEGY_EXCLUDED` ⭐ 新增 P0 — 战略排除条件命中
- `HARD_FAIL_NO_STRATEGY_EXTREME_REGIME` ⭐ 新增 P0 — 极端行情无战略匹配
- `HARD_FAIL_STRATEGY_DIRECTION_MISMATCH` ⭐ 新增 P0 — 交易方向与战略指令冲突
- `DEGRADE_DREAM_MODE_RISK_REDUCTION`
- `DEGRADE_VALIDATION_WEAK`
- `DEGRADE_STRATEGY_REDUCED_RISK` ⭐ 新增 P0 — 战略指令REDUCE强制降级
- `SOFT_WARN_STRATEGY_DIRECTS_WAIT` ⭐ 新增 P0 — 战略指令WAIT但评分达标
- `HARD_FAIL_LEVERAGE_EXCEEDS_CAP` ⭐ P003新增 — 杠杆超出上限
- `HARD_FAIL_LEVERAGE_MISMATCH` ⭐ P003新增 — OKX显示杠杆与实际杠杆不符

## 约束
- 不负责下单；只负责"是否允许进入执行阶段"与必要的降级指令输出。

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`
- 输出必须包含：`decision`、`reason_codes`、`degradations`
- 任何上游 `pass=false` 必须被透传为 `decision=SKIP`（除非是显式的降级信号）

## Integration
- 上游：`dream-signal-scoring-spec` + `dream-risk-position-sizing` + `dream-execution-cost-model` + `dream-strategy-parser` ⭐ 新增 P0
- 下游：`swap_place_order`（仅当 PASS）、`learning-episode-writer`（记录 SKIP/PASS 与理由码）
- 约定：门禁优先级最高，禁止在此处"补救性改参数"
- ⭐ 战略校验规则：战略门禁在评分门禁之前执行；`position_modifier` 和 `leverage_cap` 透传至 `dream-risk-position-sizing` 作为硬性上限

## Fail-Closed
- 缺失核心数据、无法判定风险阈值、或出现严重冲突：一律 `decision=SKIP`


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 交易前门禁 |
| **目标邮箱** | 秘书汇总邮箱 (secretary) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
| **投递命令** | 直接写入文件到 `~/.workbuddy/skills/boss-secretary/reports/<文件名>.md` |

### 投递工作流

```
1. 本部门完成工作（自动化任务/手动触发）
2. 整理工作总结（Markdown格式）
3. 确定优先级: P0(紧急)/P1(重要)/P2(观察)/P3(正常)
4. 执行投递命令
5. 确认邮件ID返回 → 投递完成
```

### 代码入口

- **投递方式**: 直接写入Markdown文件到指定邮箱目录
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`
