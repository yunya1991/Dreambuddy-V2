# Evolution P0 Day2 Acceptance Report (2026-05-12)

## 1. 验收范围

本次执行 `P0 Day2` 验收，覆盖：

- Decision Gate 自动判定（approve/reject）
- rollback pointer 自动生成（仅 approve）
- PromotionRecord 生成（仅 approve）
- fail-closed 阻断路径（reject）

## 2. 验收输入

### 正样本

- Candidate: `artifacts/evolution/feedback/candidate_positive_20260511.json`
- Reports:
  - `artifacts/evolution/audit/audit_positive_20260511.json`
  - `artifacts/evolution/sandbox/sandbox_positive_20260511.json`

### 反样本

- Candidate: `artifacts/evolution/feedback/candidate_negative_20260511.json`
- Reports:
  - `artifacts/evolution/audit/audit_negative_20260511.json`

## 3. 运行命令

```bash
python scripts/ci/evolution_decision_gate.py \
  --candidate artifacts/evolution/feedback/candidate_positive_20260511.json \
  --reports artifacts/evolution/audit/audit_positive_20260511.json,artifacts/evolution/sandbox/sandbox_positive_20260511.json \
  --to-version v0.1.1 \
  --artifacts-dir artifacts/evolution/decision \
  --rollback-dir artifacts/evolution/rollback \
  --timestamp 2026-05-12T09:00:00Z

python scripts/ci/evolution_decision_gate.py \
  --candidate artifacts/evolution/feedback/candidate_negative_20260511.json \
  --reports artifacts/evolution/audit/audit_negative_20260511.json \
  --to-version v0.1.1 \
  --artifacts-dir artifacts/evolution/decision \
  --rollback-dir artifacts/evolution/rollback \
  --timestamp 2026-05-12T09:05:00Z
```

## 4. 验收结果

### 正样本（通过）

- Decision: `artifacts/evolution/decision/decision-20260512T090000Z.json`
  - `decision=approve`
  - `reason_codes=[]`
- Promotion: `artifacts/evolution/decision/promotion-20260512T090000Z.json`
- Rollback Pointer: `artifacts/evolution/rollback/rollback-pointer-20260512T090000Z.json`

状态机映射：

- `C0_COLLECTED -> C1_AUDIT_PASSED -> C2_SANDBOX_PASSED -> C6_APPROVED`

### 反样本（阻断）

- Decision: `artifacts/evolution/decision/decision-20260512T090500Z.json`
  - `decision=reject`
  - `reason_codes` 包含：
    - `EVIDENCE_MISSING`
    - `REPORT_NOT_PASSED`
    - `REPORT_VIOLATION_FOUND`
    - `REPORT_STAGE_MISSING`
- 未生成 Promotion 与 Rollback Pointer（符合 fail-closed）。

状态机映射：

- `C0_COLLECTED -> C_FAIL`

## 5. DoD 对照更新

- [x] candidate ingest 可入队并生成 Candidate 契约实例
- [x] audit gate 可阻断字段/来源/证据链不合格候选
- [x] sandbox gate 可阻断回归候选
- [x] decision gate 仅全绿候选可批准
- [x] promotion 前生成 rollback pointer
- [x] 每个阶段输出结构化 ValidationReport
- [x] artifacts 路径可追溯且与候选 ID 对齐

## 6. 结论（Go/No-Go）

结论：`GO (P0 Day2 自动化闭环通过)`

说明：

- Day2 已完成“判定 + 回滚指针 + 审计产物”自动化基线；
- 下一步建议进入 P1：接入 `stress/scenario/backtest` 并扩展多门禁聚合判定。
