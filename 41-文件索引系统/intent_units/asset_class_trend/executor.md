# asset_class_trend 执行器规范

- 执行入口：`exec_asset_class_trend`。
- 数据/能力链路：L0 yijing.strategic。

## 边界条件

- 仅输出战略层日志中的资产状态；无记录时不生成趋势结论。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
