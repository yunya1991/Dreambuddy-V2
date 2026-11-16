# L2 开发端周报（2026-11-16T00:00:00+08:00 ~ 2026-11-23T00:00:00+08:00）

生成时间：2026-11-16T16:22:14.630731+00:00
台账样本：created=0 / settled=0 / abandoned=0 / active=0

## 核心指标

| 指标 | 值 | 口径 |
|---|---|---|
| 修复率 | null（样本不足：0/0） | settled/(settled+abandoned) |
| 回归通过率 | null（样本不足：0/0） | passed/regression_evidence |

## 优化收益

- 窗口内无已结算的优化任务（样本不足，不做收益推断）。

## 口径说明

- 优化收益只报 before/after/delta，方向由指标语义决定，不做自动优劣判定。
- tokens 成本未纳入周报：GAP-17（L2Envelope.tokens_used 未接通）。
- 样本不足：窗口内无 settled/abandoned 事件，修复率为 null（不按 0 记）。
- 样本不足：窗口内无回归证据，回归通过率为 null（不按 0 记）。

