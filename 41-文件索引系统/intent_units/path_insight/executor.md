# path_insight 执行器规范

- 执行入口：`exec_path_insight`。
- 数据/能力链路：L0 evolution.snapshot。

## 边界条件

- 快照为空或标的无法解析时请求澄清；不得猜测最小阻力路径。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
