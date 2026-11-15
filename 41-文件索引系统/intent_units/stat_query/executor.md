# stat_query 执行器规范

- 执行入口：`exec_stat_query`。
- 数据/能力链路：54 l1agg.capabilities.run_capability。

## 边界条件

- 沿用能力层 min_n 与 quality 门禁；样本不足不得伪造统计结论。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
