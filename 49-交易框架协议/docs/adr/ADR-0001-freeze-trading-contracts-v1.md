# ADR-0001: Freeze Trading Contracts v1

- 状态：accepted
- 日期：2026-11-06
- 决策人：49 交易框架协议 owner
- 关联契约：SignalSchema v1 / FinalDecisionSignal v1 / MacroElasticConstraint v1 / UpperLayerContext v1

## Context

B 轨道（B-01～B-08）与 M0-03 基线已落地。此前契约在评审过程中多次调整（`mode`、`strategic_tier`/`position_tier`、source 枚举），需要一份可校验的冻结基线，避免实现过程中再次漂移。

## Decision

冻结以下四份 v1 契约，作为 `contracts/contract_manifest.v1.json` 的唯一事实源：

1. `SignalSchema v1`
2. `FinalDecisionSignal v1`
3. `MacroElasticConstraint v1`
4. `UpperLayerContext v1`

冻结规则：

- v1 必填字段不可删除、不可改语义、不可改类型。
- 允许新增**可选字段**，但必须同时更新 manifest 并提交 ADR。
- 任何 breaking change 必须升 v2 + ADR；v1 保持兼容。
- 所有实现必须通过 `validate_contracts.py` 与 `freeze_contracts.py --check`。

## Consequences

- 23/42/43/11/L0 执行层的对接字段有稳定基线，减少“文档落后/字段漂移”。
- 新增能力需要走 ADR，短期增加流程成本，长期降低联调成本。
- 本地与 CI 可用 manifest SHA256 检查契约是否被意外修改。

## Contract Impact

Breaking：无。新增文件：四份 JSON Schema、示例、manifest、本 ADR。
版本：保持 v1；manifest `spec_version=v0.11`。

## Alternatives

- 继续只维护 SPEC 字段表：可读性好，但无法机器校验，易漂移。
- 直接升 v2：当前接口尚未广泛实现，升 v2 成本高且无收益。

## Rollback

- 回滚：删除 manifest 并将 `status` 恢复为 draft（需 ADR-0002）。
- 实现侧：所有 B 轨道开关默认关闭；回滚只需保持默认值并重启进程。
- 验证：`python 49-交易框架协议/scripts/rollback_drill.py`。