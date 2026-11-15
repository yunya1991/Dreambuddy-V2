# contradiction_insight 执行器规范

- 执行入口：`exec_contradiction_insight`。
- 数据/能力链路：L0 evolution.contradiction。

## 边界条件

- 仅解读日志已记录维度；无矛盾记录或读取失败时如实返回。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
