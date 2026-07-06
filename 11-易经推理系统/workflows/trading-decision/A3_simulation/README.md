# A3 入口映射

- 职责：根据评分与波动环境输出策略模式（trend/mean-revert/neutral）。
- 入口：`run_a3_simulation(payload, output_dir=None)`
- 输出：`stage_id="A3"` + `strategy_mode` + `artifact_path`。
