# DA-CHAIN — 链上数据子 agent 协议

> **版本**: v0.1 ｜ **创建日期**: 2026-11-05 ｜ **状态**: 🟡 草案
> **上游**: [SPEC-L0-DATA-AGENT-v0.1](../SPEC-L0-DATA-AGENT-v0.1.md)
> **查询命令**: `data.dal_query {command: "chain"}`

## 1. 数据源清单

| 数据源 | 采集器 | 频率 | 落库 sub_category |
|---|---|---|---|
| BTC 链上指标（难度/mempool/区块高度） | mempool_collector / blockchain_info_collector | 5min | btc_onchain |
| 交易所与巨鲸（美股/VIX/美元指数快照） | panewslab_collector | 4h | exchanges_whales |
| ccxt BTC ticker | ccxt_collector | 5min | BTC/USDT |
| DeFiLlama TVL | defillama_collector | 5min | chains_summary / all_protocols |
| Etherscan gas | etherscan_collector | 5min | — |

## 2. 指标口径（DAL 输出键 → 库内来源）

| 输出键 | sub_category | metric_name | 说明 |
|---|---|---|---|
| difficulty_change_pct | btc_onchain | difficulty_change_pct | 难度变化% |
| difficulty_progress_pct | btc_onchain | difficulty_progress_pct | 难度周期进度% |
| mempool_count | btc_onchain | mempool_count | mempool 交易数 |
| mempool_fee_btc | btc_onchain | mempool_fee_btc | mempool 手续费 (BTC) |
| mempool_size_kb | btc_onchain | mempool_size_kb | mempool 大小 (KB) |
| remaining_blocks | btc_onchain | remaining_blocks | 下次难度调整剩余块 |
| tip_height | btc_onchain | tip_height | tip 区块高度 |
| sp500_equity_value | exchanges_whales | us_SP500_value | 标普500 快照 |
| vix_value | exchanges_whales | us_VIXCLS_value | VIX 快照 |
| dollar_index_value | exchanges_whales | us_DTWEXBGS_value | 美元指数快照 |

## 3. 质量分级

- **good**: btc_onchain 核心指标（难度/mempool/高度）均有真实值（当前达标）；
- **partial**: 仅部分指标可用；
- **empty**: 全部缺失（FAIL-OPEN）。

## 4. 派生逻辑归属

- onchain_trend / accumulation 等趋势判断：由消费层基于原始指标推导，口径变更须在本文件登记。

## 5. 训练挂钩

- 采集成功率：mempool/ccxt/defillama/etherscan collector 调度成功比（Beta verify）；
- 数据新鲜度：5min 级采集器阈值分级；
- 覆盖率：§2 登记指标非空占比。

## 6. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-05 | 初版：基于 P0/P1 落地后的真实指标口径登记 |
