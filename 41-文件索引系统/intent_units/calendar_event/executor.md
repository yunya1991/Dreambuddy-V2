# calendar_event 执行器规范

- 执行入口：`exec_calendar_event`。
- 数据/能力链路：L0 datacenter.events。

## 边界条件

- 仅返回事件日程；事件源不可用或为空时不得编造日期。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
