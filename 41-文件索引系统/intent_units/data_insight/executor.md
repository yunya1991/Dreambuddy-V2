# data_insight 执行器规范

- 执行入口：`exec_data_insight`。
- 数据/能力链路：INSIGHT_KNOWLEDGE。

## 边界条件

- 仅解释已登记指标与变化模式；无知识命中时明确返回暂无解读。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
