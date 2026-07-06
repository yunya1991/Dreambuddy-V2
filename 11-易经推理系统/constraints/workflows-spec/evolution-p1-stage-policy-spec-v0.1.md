# Evolution P1 Stage Policy Spec v0.1

## 1. 目标

在 P1 阶段为 Decision Gate 引入 `stage_policy`，支持每个验证阶段的独立判定策略，在保持 fail-closed 的前提下提升可扩展性。

## 2. 适用阶段

P1 默认 required stages：

- `audit`
- `sandbox`
- `stress`
- `scenario`
- `backtest`

## 3. Stage Policy 契约

`stage_policy` 为 `stage -> policy` 映射，单阶段策略结构：

```json
{
  "require_pass": true,
  "allow_warnings": false,
  "max_violation_count": 0,
  "severity_blocklist": ["high", "critical"]
}
```

字段语义：

- `require_pass`：是否要求该阶段 `pass=true`
- `allow_warnings`：是否允许告警类型 violations（在阈值以内）
- `max_violation_count`：该阶段允许的最大 violation 数
- `severity_blocklist`：命中即阻断的 severity 列表

## 4. 聚合判定规则

对每个 required stage：

1. 阶段缺失 -> `REPORT_STAGE_MISSING`
2. `require_pass=true && pass=false` -> `REPORT_NOT_PASSED`
3. `violation_count > max_violation_count` -> `REPORT_VIOLATION_COUNT_EXCEEDED`
4. 命中 `severity_blocklist` -> `REPORT_SEVERITY_BLOCKED`
5. 有 violations 且 `allow_warnings=false` -> `REPORT_VIOLATION_FOUND`

任一阶段失败即整体 `reject`，全部通过才 `approve`。

## 5. 审计与可追溯

- DecisionRecord 新增 `stage_policy_snapshot`
- 建议 policy 文件路径：`artifacts/evolution/policy/*.json`
- 推荐基线样例：`artifacts/evolution/policy/stage_policy_p1_relaxed_scenario.json`

## 6. 工程接口

脚本参数扩展：

- `--required-stages`
- `--stage-policy-json`

工作流入口：

- `.github/workflows/evolution-decision-gate.yml`

P1.5 增量说明：

- `policy_version` 与模板库机制见 `evolution-p1-5-policy-template-versioning-spec-v0.1.md`
