# metric_series 执行器规范

- 执行入口：`exec_metric_series`。
- 数据/能力链路：L0 datacenter.series。

## 边界条件

- 仅查询 54 序列注册表可解析指标；无序列或数据不足时如实返回。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
