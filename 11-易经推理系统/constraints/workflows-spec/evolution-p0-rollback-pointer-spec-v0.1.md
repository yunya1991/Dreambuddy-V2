# Evolution P0 Rollback Pointer Spec v0.1

## 1. 目标

`rollback pointer` 是约束发布前必须生成的恢复锚点，保证 `C7_PROMOTED` 后出现异常时可以在约定 RTO 内回退到上一个稳定版本。

## 2. 生成时机

仅在以下条件同时满足时生成：

- Decision Gate 输出 `approve`
- `from_version` 与 `to_version` 明确
- 存在可追溯证据链（`evidence_refs`）

若任一条件不满足，禁止生成 pointer，发布必须阻断（fail-closed）。

## 3. 数据契约

```json
{
  "pointer_id": "rp-cand-20260512-001-v0.1-to-v0.1.1",
  "candidate_id": "cand-20260512-001",
  "trace_id": "trace-xyz-002",
  "from_version": "v0.1",
  "to_version": "v0.1.1",
  "constraint_snapshot_ref": "constraints/releases/v0.1.json",
  "restore_ref": "constraints/releases/v0.1.json",
  "restore_command": "python scripts/ci/constraint_rollback.py --restore-ref constraints/releases/v0.1.json",
  "evidence_refs": [
    "artifacts/evolution/audit/audit_positive_20260511.json",
    "artifacts/evolution/sandbox/sandbox_positive_20260511.json"
  ],
  "created_at": "2026-05-12T08:00:00Z",
  "schema_version": "evolution-p0-rollback-pointer-v0.1"
}
```

## 4. 字段约束

- `pointer_id`：全局唯一，推荐 `<candidate_id>-<from_version>-to-<to_version>` 模式
- `constraint_snapshot_ref`：必须指向可恢复的稳定快照
- `restore_ref`：P0 与 `constraint_snapshot_ref` 保持一致
- `restore_command`：必须可复制执行，且不依赖交互输入
- `evidence_refs[]`：不少于 1 条

## 5. 存储与审计

- 存储目录：`artifacts/evolution/rollback/`
- 文件命名：`rollback-pointer-<timestamp>.json`
- 审计要求：
  - 与 `DecisionRecord` 通过 `candidate_id`、`trace_id` 关联
  - 在 `PromotionRecord.rollback_pointer` 留存 pointer 文件路径

## 6. 故障处理

Pointer 生成失败必须：

1. 标记 `decision` 为 `reject`；
2. 追加 `ROLLBACK_POINTER_BUILD_FAILED` 错误码；
3. 输出失败审计产物到 `artifacts/evolution/decision/`；
4. 阻断后续 promotion。

## 7. P1 兼容预留

P1 可扩展字段：

- `rto_target_seconds`
- `risk_tier`
- `post_promotion_watch_window_minutes`

P0 不强制这些字段，但不禁止提前写入。
