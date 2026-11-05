# DA-CAPITAL-FLOW — 主力资金数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "capital_flow"}`（P1 已落地）

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| 多空比（账户/持仓） | theblockbeats 衍生品信号链路 | 30min | long_short_ratio |
| 资金费率 | binance_funding_rate_collector | 30min | funding_rate |
| 持仓量 | theblockbeats / coinglass 链路 | 30min | open_interest |
| 期权指标 | deribit_options_collector | 30min | options |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| long_short_ratio | long_short_ratio | long_short_ratio | 多空比 |
| long_account_pct | long_short_ratio | long_account_pct | 多头账户占比% |
| funding_rate_pct | funding_rate | funding_rate_pct | 资金费率% |
| funding_rate_annualized_pct | funding_rate | funding_rate_annualized_pct | 年化资金费率% |
| open_interest_value | open_interest | open_interest_value | 持仓量价值（USD） |
| open_interest_amount | open_interest | open_interest_amount | 持仓量（币） |

## 3. 质量分级

- **good**: 六项指标均有真实值（当前达标，P1 验证 6/6）；
- **partial**: 部分指标可用；
- **empty**: 全部缺失（FAIL-OPEN）。

## 4. 派生逻辑归属

- 主力资金方向判断：规划基于多空比+费率+持仓量变化下沉 DAL 侧实现。

## 5. 训练挂钩

- 采集成功率：funding_rate/long_short_ratio 采集链路调度成功比（Beta verify）；
- 数据新鲜度：30min 阈值分级；
- 覆盖率：§2 登记指标非空占比。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P1 落地后的真实指标口径登记（六项指标全量真实） |
