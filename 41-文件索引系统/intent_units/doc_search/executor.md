# doc_search 执行器规范

- 执行入口：`L1 无执行器，交 41 检索链路`。
- 数据/能力链路：41 L1/L2/L3 混合召回。

## 边界条件

- doc_search 不在 l1_route_signal 直接执行；检索失败不得阻塞 L2 交接。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
