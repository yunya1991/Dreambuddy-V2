# technical_analysis 执行器规范

- 执行入口：`exec_technical_analysis`。
- 数据/能力链路：L0 yijing.bcrm2。

## 边界条件

- 无汇总或标的无法解析时请求澄清；快照读取失败时降级。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
