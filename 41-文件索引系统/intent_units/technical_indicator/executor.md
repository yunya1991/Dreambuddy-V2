# technical_indicator 执行器规范

- 执行入口：`exec_technical_indicator`。
- 数据/能力链路：L0 market.candles → 54 l1agg.technical.analyze。

## 边界条件

- OHLC 不全或样本不足时返回 gate；不得伪造高低点和指标值。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
