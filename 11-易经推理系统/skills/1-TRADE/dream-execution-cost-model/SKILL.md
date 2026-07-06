---
name: dream-execution-cost-model
description: 在下单前评估手续费、滑点与最坏成交假设，给出是否允许市价单/是否需要降级执行的建议，供 dream-multiSkill 做执行前门禁。
license: Internal
---

# Dream-Execution-Cost-Model: 交易成本与滑点评估

## 目标
- 把“市价单+保护单”的执行风险显式化：成本、滑点、流动性不足、极端波动时的最坏情形。
- 为 pretrade gatekeeper 提供可审计的执行风险信号。

## 输入（建议字段）
- `symbol`: string
- `side`: "buy" | "sell"
- `ord_type_candidate`: "market" | "limit"
- `notional_usdt`: number
- `market_snapshot`（可选，若可取到）
  - `best_bid`: number
  - `best_ask`: number
  - `spread_bps`: number
  - `depth_1pct_usdt`: number（±1%深度）
  - `orderbook_imbalance`: number
  - `volatility_regime`: "low" | "mid" | "high"
- `portfolio_snapshot`（可选）
  - `fee_tier`: string
  - `position_mode`: "net" | "long_short" | "unknown"
- `fee_bps`（可选，若已知账户费率）
  - `taker_bps`: number
  - `maker_bps`: number

## 输出（必须结构化）
- `costs`
  - `fee_bps_est`: number
  - `slippage_bps_est`: number
  - `total_cost_bps_est`: number
  - `worst_case_slippage_bps`: number
- `execution_recommendation`
  - `allow_market`: boolean
  - `preferred_ord_type`: "market" | "limit"
  - `atomic_bracket_required`: boolean
  - `fallback_on_protection_fail`: "immediate_reduce_only_exit" | "cancel_and_flatten" | "skip"
  - `notes`: string[]
- `pass`: boolean
- `reason_codes`: string[]

## 估算逻辑（最小可执行版）
- 手续费：优先使用已知 `taker_bps`，否则给出保守默认并标注假设。
- 滑点：
  - 若有 `spread_bps` 与 `depth_1pct_usdt`：用名义金额/深度估算冲击，并加上半个点差作为基础滑点。
  - 若 `orderbook_imbalance` 极端偏离：对 `worst_case_slippage_bps` 加惩罚项（避免单边薄簿误判）。
  - 若缺少盘口深度：根据 `volatility_regime` 给出保守区间，并将 `pass=false` 或输出降级建议（fail-closed 或 require limit）。
- 最坏情形：
  - `worst_case_slippage_bps` 用于 gatekeeper：若超过阈值（例如 30-80 bps，按你的偏好），则禁止市价单或直接跳过。
- 原子性执行语义（新增）：
  - 若策略要求“开仓后立即保护单”，默认 `atomic_bracket_required=true`。
  - 若保护单下发失败，必须给出回退策略：`immediate_reduce_only_exit` 或 `cancel_and_flatten`。

## 理由码（建议）
- `HARD_FAIL_NO_LIQUIDITY_DATA`
- `HARD_FAIL_WORST_SLIPPAGE_TOO_HIGH`
- `HARD_FAIL_PROTECTION_ORDER_NOT_CONFIRMED`
- `SOFT_WARN_EXECUTION_BLACKOUT_WINDOW`
- `SOFT_WARN_HIGH_SPREAD`
- `SOFT_WARN_HIGH_VOLATILITY`
- `ASSUMPTION_FEE_DEFAULTED`

## 约束
- 不负责把估算“变成订单算法”；只输出建议与风险信号。
- 若关键数据不可得，倾向 fail-closed 或强制降级为限价单建议。

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`
- 输出必须包含：`pass`、`reason_codes`、`costs.worst_case_slippage_bps`、`execution_recommendation.preferred_ord_type`

## Integration
- 上游：盘口/点差/深度（如可得）+ 计划下单名义（来自 `dream-risk-position-sizing`）
- 下游：`dream-pretrade-gatekeeper`（执行风险门禁输入）、`learning-episode-writer`（落盘估算与实测偏差）
- 约定：当关键流动性数据缺失时，不输出乐观估计

## Fail-Closed
- 缺少盘口深度且无法给出保守区间时：`pass=false` + `HARD_FAIL_NO_LIQUIDITY_DATA`


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 交易成本部 |
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
