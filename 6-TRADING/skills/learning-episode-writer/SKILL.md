---
name: learning-episode-writer
description: 将每轮决策与结果固化为 episode（包含评分/门禁/执行/结果/证据引用），skip 也必须写入，作为学习闭环事实底座。
license: Internal
---

# Learning Episode Writer

## 目标

- 统一 episode 口径：可检索、可回放、可审计
- 明确 evidence_refs：任何结论都能追溯到当时快照与工件

## 何时使用

- 每轮结束（无论开仓、平仓、还是 skip）

## 输入（建议字段）

- `decision_audit`（trace_id、ts、inst_id、action、direction、selected_strategy_id）
- `scoring`（维度分、理由码、冲突点）
- `gate`（PASS/SKIP、reason_codes、数据完整性检查结果）
- `execution`（订单参数、成交回报、滑点/手续费估计与实测偏差）
- `outcome`（PnL、最大回撤、触发止损止盈原因）
- `evidence_refs[]`（material/symbols/patch/audit/market snapshots 路径）
- `skip_tracking`（P006新增）
  - `consecutive_skip_count`: number - 连续SKIP次数
  - `sleeplwalk_alert`: boolean - 是否触发梦游惯性告警
  - `sleeplwalk_force_review`: boolean - 是否需要强制复盘

## 输出

- `episode_path`
- `episode_id`
- `episode_digest`

## 过程

1. 校验字段完整性（缺关键字段则 fail-closed：标注为 `INCOMPLETE` 并写入原因）
2. 归一化 reason_codes 与 evidence_refs
3. **P006新增: 连续SKIP计数**
   - 读取上次episode的`consecutive_skip_count`
   - 若本次decision=SKIP: `consecutive_skip_count += 1`
   - 若本次decision=PASS: `consecutive_skip_count = 0`
   - 若`consecutive_skip_count >= 7`: 触发**梦游惯性强制复盘**
4. 落盘 episode，并输出 digest 供后续 distill 与 recall 使用

## P006 梦游惯性检测机制

> **触发条件**: 连续SKIP ≥ 7次
> **触发动作**: 
> - 在episode中标记 `sleeplwalk_alert: true`
> - 输出 `sleeplwalk_force_review: true`
> - 自动生成复盘提案写入 `pending_tasks/inbox/`

### 梦游惯性特征
- "有仓位就持有，没信号就不动，亏损了就等待"
- 持仓本身变成了继续持有的理由
- 连续SKIP期间无实质市场研判

## 验证

- 每个 episode 必须包含 `trace_id` 与 `ts`
- 每个 episode 必须包含至少一个 `evidence_refs`

## Contract v0.1（最小审计契约）
- 输入必须包含：`decision_audit.trace_id`、`decision_audit.ts`、`decision_audit.inst_id`
- 输出必须包含：`episode_path`、`episode_id`、`episode_digest`

## Integration
- 上游：`dream-signal-scoring-spec`（scoring）、`dream-pretrade-gatekeeper`（gate）、执行回报（execution）、结果（outcome）
- 下游：`learning-lesson-distiller`、`learning-recall-pack`、`memory-session-index`
- 约定：SKIP 也必须落盘，且 SKIP 的 reason_codes 必须可统计

## Fail-Closed
- 缺关键字段时：仍写入 episode，但标注为 `INCOMPLETE` 并写入原因码
