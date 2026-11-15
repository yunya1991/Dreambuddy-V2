# leader_compare 执行器规范

- 执行入口：`exec_leader_compare`。
- 数据/能力链路：_leader_gap。

## 边界条件

- 至少识别一个资产，否则请求澄清；关系/对齐/价格异常时降级。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
