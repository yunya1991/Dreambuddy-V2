# DA-FLOW — 资金流数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "flow"}`（P1 已落地）

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| Bitcoin ETF 净流入（farside.co.uk） | etf_flow_collector | 日级 | etf_flow |
| 稳定币 Top10 市值与占比 | stablecoin_transparency | 4h | stablecoins_top_10 |
| USDT 官网供应量快照 | stablecoin_transparency | 1h | tether_current |
| USDC 官网供应量快照 | stablecoin_transparency | 1h | usdc_current |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| etf_total_flow | etf_flow | total_flow | ETF 总净流入（百万美元） |
| stablecoin_dominance_usdt | stablecoins_top_10 | usdt_pct_of_total | USDT 占比% |
| usdt_circulating_bln | tether_current | usdt_circulating_usd_bln | USDT 流通量（十亿） |
| usdc_circulating_bln | usdc_current | usdc_circulating_usd_bln | USDC 流通量（十亿） |

## 3. 质量分级

- **good**: etf_total_flow 与 stablecoin_dominance_usdt 均有真实值（当前达标）；
- **empty**: 全部缺失（FAIL-OPEN）。

## 4. 派生逻辑归属

- fund_flow_score / flow_regime：待定义派生指标，规划下沉 DAL 侧实现（当前前端为 null 占位）。

## 5. 训练挂钩

- 采集成功率：etf_flow/stablecoin collector 调度成功比（Beta verify）；
- 数据新鲜度：ETF 日级 / 稳定币 1h-4h 阈值分级；
- 覆盖率：§2 登记指标非空占比。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P1 落地后的真实指标口径登记 |
