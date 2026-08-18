# Evolution P0 Decision Gate Spec v0.1

## 1. 目标与边界

本规范定义 P0 阶段 `Decision Gate` 的自动化判定规则，用于在 `audit` 与 `sandbox` 结果基础上输出唯一决策：

- `approve`：允许进入 `C6_APPROVED -> C7_PROMOTED`
- `reject`：进入 `C_FAIL` 并阻断发布

P0 不包含 `stress/scenario/backtest`，这些由 P1 引入。

## 2. 输入契约

Decision Gate 执行输入由三部分组成：

- `Candidate`：见 `evolution-p0-contracts-v0.1.md`
- `ValidationReport[]`：至少包含 `audit`、`sandbox` 两个阶段
- `gate_config`：本地配置（默认内置）

`gate_config` 最小结构：

```json
{
  "required_stages": ["audit", "sandbox"],
  "fail_closed": true,
  "require_evidence_refs": true
}
```

P1 版本扩展说明：

- 默认 `required_stages` 升级为 `["audit","sandbox","stress","scenario","backtest"]`
- 引入 `stage_policy`，详见 `constraints/workflows-spec/evolution-p1-stage-policy-spec-v0.1.md`

## 3. 判定规则（可执行）

按顺序执行，任一步失败立即 `reject`：

1. `Candidate` 必填字段完整（`candidate_id`、`trace_id`、`constraint_version_base`、`evidence_refs`、`schema_version`）。
2. `ValidationReport` 必须覆盖 `required_stages`。
3. 每个必需阶段 `pass == true`。
4. 每个必需阶段 `violations[]` 为空。
5. 若 `require_evidence_refs == true`，则 `Candidate.evidence_refs` 非空。

全部通过才可 `approve`。

## 4. 输出契约

Decision Gate 输出 `DecisionRecord`：

```json
{
  "candidate_id": "cand-20260512-001",
  "trace_id": "trace-xyz-002",
  "decision": "approve",
  "reason_codes": [],
  "required_stages": ["audit", "sandbox"],
  "stage_results": {
    "audit": true,
    "sandbox": true
  },
  "rollback_pointer_id": "rp-cand-20260512-001-v0.1-to-v0.1.1",
  "timestamp": "2026-05-12T08:00:00Z",
  "schema_version": "evolution-p0-decision-record-v0.1"
}
```

若 `decision=reject`，`rollback_pointer_id` 允许为空字符串，但必须给出 `reason_codes`。

## 5. 错误码映射

- `CANDIDATE_INVALID`：候选契约缺字段或结构不合法
- `REPORT_STAGE_MISSING`：缺少 `audit` 或 `sandbox`
- `REPORT_NOT_PASSED`：存在 `pass=false`
- `REPORT_VIOLATION_FOUND`：存在非空 `violations[]`
- `EVIDENCE_MISSING`：`evidence_refs` 为空

错误码可并存，脚本需完整返回，便于审计复盘。

## 6. 工程执行约定

- CLI 脚本：`scripts/ci/evolution_decision_gate.py`
- 输出目录：`artifacts/evolution/decision/`
- 产物：
  - `decision-<timestamp>.json`
  - `promotion-<timestamp>.json`（仅 `approve` 生成）
  - `rollback-pointer-<timestamp>.json`（仅 `approve` 生成）

推荐命令：

```bash
python scripts/ci/evolution_decision_gate.py \
  --candidate artifacts/evolution/feedback/candidate_positive_20260511.json \
  --reports artifacts/evolution/audit/audit_positive_20260511.json,artifacts/evolution/sandbox/sandbox_positive_20260511.json \
  --to-version v0.1.1 \
  --artifacts-dir artifacts/evolution/decision
```
