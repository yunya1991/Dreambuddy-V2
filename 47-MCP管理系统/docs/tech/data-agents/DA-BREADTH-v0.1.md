# DA-BREADTH — 市场宽度数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "breadth"}`（P1 已落地）

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| 稳定币 Top10 市值 | stablecoin_transparency | 4h | stablecoins_top_10 |
| 社交讨论量与新闻数 | social_volume 采集链路 | 30min | social_volume |
| panewslab 市场总览/周期判断 | panewslab_collector | 4h | overview_market / cycle_signals |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| usdt_bln | stablecoins_top_10 | USDT_bln | USDT 市值（十亿） |
| usdc_bln | stablecoins_top_10 | USDC_bln | USDC 市值（十亿） |
| social_volume | social_volume | social_volume | 社交讨论量 |
| news_count_24h | social_volume | news_count_24h | 24h 新闻数 |

## 3. 待补数据源（当前 null 占位）

| 指标 | 现状 | 规划 |
|---|---|---|
| btc_dominance | null | 待接入 coinglass/coinmarketcap 类采集 |
| breadth_confirmation | null | 待定义派生口径（涨跌家数比） |
| global_change_24h | null | 待接入全市场涨跌幅采集 |
| market_participation_index | null | 待定义派生口径 |

## 4. 质量分级

- **good**: social_volume 与稳定币市值均有真实值（当前达标）；
- **empty**: 全部缺失（FAIL-OPEN）。

## 5. 训练挂钩

- 采集成功率：stablecoin/social_volume 采集链路调度成功比（Beta verify）；
- 数据新鲜度：30min-4h 阈值分级；
- 覆盖率：§2 登记指标非空占比（§3 待补项不计入）。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P1 落地后的真实指标口径登记，标注四项待补数据源 |
