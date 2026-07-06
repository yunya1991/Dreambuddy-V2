# A4 入口映射

- 职责：进行风控门禁校验，给出 PASS/REVIEW/BLOCK。
- 入口：`run_a4_validation(payload, output_dir=None)`
- 输出：`stage_id="A4"` + `risk_gate` + `artifact_path`。
