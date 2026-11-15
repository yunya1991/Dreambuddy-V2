# risk_control 执行器规范

- 执行入口：`exec_risk_control`。
- 数据/能力链路：L0 riskcontrol.trailing。

## 边界条件

- 仅输出最新持仓风控状态；无日志或评估记录时不得给出风控指令。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
