# event_analysis 执行器规范

- 执行入口：`exec_event_analysis`。
- 数据/能力链路：L0 event.state。

## 边界条件

- 无事件驱动信号时明确返回；状态读取失败时降级。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
