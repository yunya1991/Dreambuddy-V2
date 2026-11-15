# ADR-0003：FinalDecisionSignal v1.1 增补 `l1-chart` 来源（加法式）

- **日期**：2026-11-15
- **状态**：已采纳
- **关联**：SPEC-54 §4.6/§8、L1X-01/L1X-02、ADR-0001（契约冻结）

## 背景

54-L1 统计图表化能力按「统计事实 → 方向规则 → 交接执行」分层：L1-D 产出内部 `signal`
（`direction ∈ {-1,0,1}`、`strength`、`rule_version`、`params_hash`），执行统一由
22-执行引擎中心完成。22 现有入口只识别 `23-evolution` 与 `50-nn` 两个来源，L1 信号无
合法契约可依。

## 决策

对 `contracts/final_decision_signal.v1.1.json` 做**加法式**修改，属 ADR-0001
`change_policy` 允许的"additive + manifest update + ADR"路径：

1. `source` 枚举增加 `"l1-chart"`；
2. `payload.required` 改为按来源条件化（draft-07 `if/then`）：
   - `23-evolution` / `50-nn`：仍要求原有 12 字段，口径零变化；
   - `l1-chart`：要求 `decision_id` / `action` / `position_tier` / `position_mult`。
3. 顶层字段、类型、取值范围全部不变；`symbol` 仍限 `*-USDT-SWAP` 或 `MACRO`，
   L1 仅对加密龙头映射执行符号，非加密资产在映射阶段显式拒绝（不伪造）。

## 后果

- 22 网关可对 `source=l1-chart` 做与 23 相同的 `decision_id` 必填 + `expires_at` 过期拒绝；
- 现有两个来源的必填集合、字段语义、示例文件均不受影响；
- `contract_manifest.v1.json` 的 v1.1 条目 sha256 与 `spec_version` 同步更新。
