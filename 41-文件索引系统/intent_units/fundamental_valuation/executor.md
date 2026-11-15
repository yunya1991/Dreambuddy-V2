# fundamental_valuation 执行器规范

- 执行入口：`exec_fundamental_valuation`。
- 数据/能力链路：L0 yijing.bdsm。

## 边界条件

- 仅使用 available 的币种快照；无快照时不生成估值结论。
- 执行异常与数据缺失遵循现有执行器 FAIL-OPEN，不阻塞 L1 路由。
- 完整正例/反例位于同目录 JSONL，仅在本单元被 retrieve 时加载。
