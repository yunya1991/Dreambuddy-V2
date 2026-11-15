# price_query 执行器规范

- 执行入口：`exec_price_query`。
- 数据/能力链路：L0 market.ticker，失败后回查 18 中心。

## 边界条件

- 无法识别标的时请求澄清；不得静默默认 BTC；行情异常时降级。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
