# top_correlation 执行器规范

- 执行入口：`exec_top_correlation`。
- 数据/能力链路：_top_correlated。

## 边界条件

- 至少识别一个资产，否则请求澄清；沿用 Pearson + BH-FDR 与样本门禁。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
