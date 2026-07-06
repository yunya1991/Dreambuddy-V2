# A7 入口映射

- 职责：输出执行审计结果，判断是否通过。
- 入口：`run_a7_audit(payload, output_dir=None)`
- 输出：`stage_id="A7"` + `audit_status` + `artifact_path`。
