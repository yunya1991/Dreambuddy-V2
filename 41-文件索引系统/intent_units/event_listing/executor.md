# event_listing 执行器规范

- 执行入口：`L1 无执行器，交 L2`。
- 数据/能力链路：事件/快讯列表由下游链路消费。

## 边界条件

- 保留 intent hint；不得复用 calendar_event 冒充新闻罗列。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
