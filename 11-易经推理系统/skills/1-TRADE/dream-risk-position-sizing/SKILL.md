---
name: dream-risk-position-sizing
description: 基于风险预算与波动率缩放，将评分结果映射为仓位名义、杠杆、止损金额与账户级风险占用，并输出可审计的仓位建议。
license: Internal
---

# Dream-Risk-Position-Sizing: 风险预算式仓位与杠杆

> **⚠️ 顾问集成 (v2.0)**: 仓位计算本身不直接调用顾问评审，但 A5 执行链路在仓位确定后会调用 `advisor_direct_call.advisors_review(scene="RISK_REVIEW")` 让 RM 确认风险占用是否合理。见 `dream-tactical-executor` 铁律四。

## 目标
- 用“风险预算”替代纯粹“总分档位”，把仓位与杠杆建立在可解释的风险占用上。
- 与 dream-multiSkill 约束保持一致：单笔名义不超过 150 USDT，并支持 Dream Mode 降级。

## 输入（建议字段）
- `symbol`: string（如 BTC-USDT-SWAP）
- `side`: "buy" | "sell"
- `scores`: { `total`: 0-30, `trend_strength`: 0-10, `macro_fund_tailwind`: 0-10, `memory_safety`: 0-10 }
- `vol`: { `atr14_15m`: number, `atr_pct_15m`: number }
- `risk_limits`
  - `max_notional_usdt`: number (default 150)
  - `max_daily_drawdown_pct`: number (default 8)
  - `risk_per_trade_usdt_cap`: number (建议：账户权益的固定比例或固定上限)
  - `dream_mode`: { `enabled`: boolean, `multiplier`: number }（如 0.5 表示减半）
- `account_snapshot`（可选）
  - `equity_usdt`: number
  - `current_exposure_usdt`: number
  - `today_drawdown_pct`: number
- `portfolio_constraints`（可选，组合层约束）
  - `max_net_exposure_usdt`: number
  - `max_gross_exposure_usdt`: number
  - `max_symbol_concentration_pct`: number
  - `max_factor_exposure_pct`: number
  - `corr_bucket_limit`: { `bucket`: string, `max_pct`: number }[]

## 输出（必须结构化）
- `position`
  - `notional_usdt`: number
  - `lever`: number
  - `estimated_stop_distance`: number（价格距离或ATR倍数表达）
  - `estimated_stop_loss_usdt`: number
- `risk_usage`
  - `risk_per_trade_usdt`: number
  - `risk_per_trade_pct_equity`: number | null
  - `flags`: string[]
- `portfolio_usage`（可选）
  - `net_exposure_usdt_after`: number | null
  - `gross_exposure_usdt_after`: number | null
  - `symbol_concentration_pct_after`: number | null
  - `factor_exposure_pct_after`: number | null
- `pass`: boolean
- `reason_codes`: string[]

## 核心逻辑（最小可执行版）
- 1) 风险单位定义
  - 用 Step5 的止损规则：`stop_distance = 2 * ATR(15m)`。
  - 估算单笔最大亏损：`estimated_stop_loss_usdt` 随名义与杠杆变化而变化；若无法精确建模，用保守系数近似并在输出中标注 `ASSUMPTION_*`。
- 2) 风险预算
  - 先确定 `risk_per_trade_usdt`：
    - 以 `risk_per_trade_usdt_cap` 为硬上限；
    - 根据 `scores.total` 做线性缩放（分高允许用足预算，分低自动缩小）。
  - Dream Mode：将 `risk_per_trade_usdt` 乘以 `dream_mode.multiplier`。
- 3) 反推名义与杠杆
  - 在满足 `estimated_stop_loss_usdt <= risk_per_trade_usdt` 的前提下，寻找最大的 `notional_usdt`（但不超过 `max_notional_usdt`）。
  - 杠杆上限可根据 `scores.total` 分档（与主文档保持 2x 基础，极高分才允许提高）。
- 4) 账户级约束
  - 若 `today_drawdown_pct > max_daily_drawdown_pct` → `pass=false`，输出 `HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER`。
  - 若 `memory_safety` 过低，强制压缩风险预算并输出 `SOFT_WARN_LOW_MEMORY_SAFETY`。
- 5) 组合层约束（新增）
  - 若预计下单后净敞口/总敞口/单品种集中度/同向因子暴露超限：优先降级名义与杠杆。
  - 若降级后仍超限：`pass=false`，输出对应 `HARD_FAIL_*`。

## 理由码（建议）
- `HARD_FAIL_DRAWDOWN_CIRCUIT_BREAKER`
- `HARD_FAIL_RISK_BUDGET_TOO_SMALL`
- `HARD_FAIL_PORTFOLIO_NET_EXPOSURE_LIMIT`
- `HARD_FAIL_SYMBOL_CONCENTRATION_LIMIT`
- `HARD_FAIL_FACTOR_EXPOSURE_LIMIT`
- `SOFT_WARN_DREAM_MODE_ACTIVE`
- `SOFT_WARN_LOW_MEMORY_SAFETY`
- `ASSUMPTION_STOPLOSS_MODEL_SIMPLIFIED`

## 约束
- 不决定方向、不做信号，不负责下单；只输出仓位/杠杆建议与风险占用。
- 必须明确写出任何“估算假设”，避免隐藏模型风险。

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`
- 输出必须包含：`pass`、`reason_codes`、`position.notional_usdt`、`position.lever`
- 若无法给出保守风险估算，必须 `pass=false` 并输出 `HARD_FAIL_RISK_BUDGET_TOO_SMALL` 或 `ASSUMPTION_STOPLOSS_MODEL_SIMPLIFIED`

## Integration
- 上游：`dream-signal-scoring-spec` 的结构化评分、15m ATR、账户快照（如有）
- 下游：`dream-pretrade-gatekeeper`（作为仓位侧门禁输入）、`learning-episode-writer`（落盘风险占用）
- 约定：仓位建议不得突破上层硬约束（单笔名义上限等）

## Fail-Closed
- 缺少 ATR 或风险预算上限无法确定时：直接 `pass=false`


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 风险管理部 |
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
