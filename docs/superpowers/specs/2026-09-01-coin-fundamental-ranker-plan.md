# 实施计划：单币基本面排名器 (CoinFundamentalRanker)

> SPEC：[2026-09-01-coin-fundamental-ranker-design.md](./2026-09-01-coin-fundamental-ranker-design.md)
> 日期：2026-09-01

---

## API 可用性验证结论（Phase A 前置调研）

| 数据源 | collector 现状 | API 可用 | 需要做什么 |
|--------|-------------|---------|-----------|
| DeFiLlama | ✅ 已有 `defillama_collector.py`，支持 chains/historicalChainTvl/fees | ✅ `/v2/protocols` + `/summary/fees/{protocol}` 均可访问，免费无 key | 扩展 2 个 route |
| CoinGecko | ❌ 无统一 collector，散落 10+ 处直连 | ✅ `/coins/{id}` 可访问，免费无 key（10-30 req/min） | 新建统一 collector |
| yfinance | ✅ 已有 `yfinance_collector.py`，仅用 `history()` 取价格 | ✅ `.info` 可获取 trailingPE 等 189 字段 | 扩展 `.info` route |
| FRED | ✅ 已有 `fred_collector.py`，key 已配置 | ✅ T10YIE 可访问 | 已就绪，可能需注册新 series |

---

## Phase A：数据源扩展（4 步）

### A1. DeFiLlama Collector 扩展 — 新增 protocols + protocol_fees route

**文件**：`18-数据获取中心/data_center/collectors/chain/defillama_collector.py`

**修改**：在现有 `collect()` 中新增两个 route 分支：
- `route="protocols"`：GET `https://api.llama.fi/v2/protocols` → 返回 per-protocol TVL 列表
- `route="protocol_fees"`：GET `https://api.llama.fi/summary/fees/{protocol}` → 返回 per-protocol 费用

**存储**：
- protocols → records (source=defillama, category=protocol, sub_category=all_protocols, metrics={tvl_list})
- protocol_fees → records (source=defillama, category=protocol_fees, sub_category={protocol_slug}, metrics={fees_24h, fees_7d, fees_30d, total_30d})

**TDD**：
- test_protocols_route_returns_list
- test_protocol_fees_route_returns_dict
- test_unknown_route_returns_empty

### A2. CoinGecko Collector 新建

**文件**：`18-数据获取中心/data_center/collectors/coin/coingecko_collector.py`（新建）

**route**：
- `coin_info`：GET `/api/v3/coins/{id}` → market_cap, total_supply, circulating_supply, max_supply
- `coin_chart`：GET `/api/v3/coins/{id}/market_chart?days=30` → 历史 prices/market_caps

**存储**：records (source=coingecko, category=coin, sub_category={coin_id}, metrics={market_cap, total_supply, ...}, timeseries={prices: [...]})

**TDD**：
- test_coin_info_returns_market_data
- test_coin_chart_returns_price_history
- test_rate_limit_handling
- test_invalid_coin_id_returns_empty

### A3. yfinance Collector 扩展 — 新增 stock_info route

**文件**：`18-数据获取中心/data_center/collectors/finance/yfinance_collector.py`

**修改**：在现有 `collect()` 中新增 route 分支：
- `route="stock_info"`：`yf.Ticker(symbol).info` → trailingPE, forwardPE, operatingMargins, returnOnEquity, marketCap, revenueGrowth
- `route="stock_financials"`：`yf.Ticker(symbol).financials` → 营收/盈利季度数据

**存储**：records (source=yfinance, category=stock_info, sub_category={ticker}, metrics={trailingPE, operatingMargins, ...})

**TDD**：
- test_stock_info_returns_pe_ratio
- test_stock_financials_returns_revenue
- test_missing_field_defaults_to_none

### A4. Collector 注册 + Scheduler 任务注册

**文件**：
- `18-数据获取中心/data_center/core/dispatcher.py`：注册 CoinGeckoCollector
- `18-数据获取中心/data_center/scheduler.py`：注册新采集任务

**新增任务**：
```python
("defillama_protocols", "chain", "defillama", {"route": "protocols"}, "6h"),
("coingecko_coin_info", "coin", "coingecko", {"route": "coin_info", "coin_id": "{id}"}, "6h"),
("yfinance_stock_info", "finance", "yfinance", {"route": "stock_info", "symbol": "{ticker}"}, "6h"),
```

**TDD**：
- test_dispatcher_registers_coingecko
- test_scheduler_includes_new_tasks

---

## Phase B：CoinFundamentalRanker 模块（5 步）

### B1. CoinFundamentalSignal 数据类 + coin 映射表

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_ranker.py`（新建）

**内容**：
- `@dataclass CoinFundamentalSignal`
- `CRYPTO_MAP / STOCK_MAP / METAL_MAP` 映射表
- `classify_asset_class(coin) -> str`
- `get_protocol_mapping(coin) -> Optional[str]`

**TDD**：
- test_signal_dataclass_fields
- test_classify_asset_class_crypto
- test_classify_asset_class_stock
- test_classify_asset_class_metal
- test_classify_unknown_returns_none
- test_crypto_map_uni_to_uniswap

### B2. 加密货币四信号（coin_fundamental_crypto.py）

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_crypto.py`（新建）

**函数**：
- `compute_revenue_stability(protocol_slug) -> float`：读 DeFiLlama fees 30d → Sharpe → z-score
- `compute_mc_fees_mean_reversion(coin_id, protocol_slug) -> float`：CoinGecko market_cap / DeFiLlama fees → Z-score 反向
- `compute_tvl_growth_momentum(protocol_slug) -> float`：DeFiLlama TVL 7d 变化率 → z-score
- `compute_revenue_quality(protocol_slug) -> float`：fees_30d_avg / TVL → z-score
- `compute_all(coin) -> Dict[str, float]`：调用四个子函数 → 返回 sub_signals dict

**数据读取**：从 data_center.db SQLite records 表读取

**TDD**：
- test_revenue_stability_normal
- test_revenue_stability_insufficient_data_returns_zero
- test_mc_fees_mean_reversion_overvalued_negative
- test_tvl_growth_momentum_positive
- test_revenue_quality_high_efficiency
- test_compute_all_returns_four_signals
- test_compute_all_missing_protocol_partial_quality

### B3. 美股四信号（coin_fundamental_stock.py）

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_stock.py`（新建）

**函数**：
- `compute_earnings_stability(ticker) -> float`：yfinance financials 4Q → Sharpe → z-score
- `compute_pe_mean_reversion(ticker) -> float`：trailingPE Z-score 反向
- `compute_revenue_growth(ticker) -> float`：营收 YoY 增长率 → z-score
- `compute_profitability_quality(ticker) -> float`：operatingMargins / returnOnEquity → z-score
- `compute_all(coin) -> Dict[str, float]`

**TDD**：同 B2 结构，4 个子信号 + compute_all + 缺失数据 FAIL-OPEN

### B4. 贵金属四信号（coin_fundamental_metal.py）

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_metal.py`（新建）

**函数**：
- `compute_price_trend_stability(yfinance_ticker) -> float`：30d 价格 Sharpe → z-score
- `compute_real_rate_mean_reversion(fred_series) -> float`：T10YIE Z-score 反向
- `compute_flow_momentum(etf_ticker) -> float`：ETF 持仓 7d/30d 变化率 → z-score
- `compute_seasonal_macro_quality(yf_gold, yf_silver) -> float`：金银比 Z-score
- `compute_all(coin) -> Dict[str, float]`

**TDD**：同 B2 结构

### B5. 主模块合成 + Shadow JSONL 输出

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_ranker.py`（扩展 B1）

**函数**：
- `compute_signal(coin) -> CoinFundamentalSignal`：
  1. classify_asset_class(coin)
  2. 按 asset_class 分派到 crypto/stock/metal 子模块
  3. 等权合成 fundamental_score = 0.25 × (s1+s2+s3+s4)
  4. 等级映射 S/A/B/C
  5. data_quality + confidence 计算
- `write_shadow(signal) -> None`：追加写入 JSONL
- `compute_for_coins(coin_list) -> List[CoinFundamentalSignal]`：批量计算

**开关**：`enable_coin_fundamental_ranker`（默认 False）

**FAIL-OPEN**：
- 异常 → fundamental_score=0.0, rank="B", data_quality="insufficient"
- 6 层堆栈日志

**TDD**：
- test_compute_signal_crypto_uni
- test_compute_signal_stock_nvda
- test_compute_signal_metal_xauusd
- test_compute_signal_unknown_coin_skipped
- test_rank_s_requires_two_subsignals_above_05
- test_rank_c_when_score_below_neg_03
- test_failopen_on_exception_returns_neutral
- test_shadow_jsonl_appended

---

## Phase C：媒体页面调研（与 A/B 并行）

### C1. 星球日报 + 区块律动页面结构调研

**产出**：调研报告文档，包含：
- 页面分类结构（DeFi/Layer1/Layer2/Meme/RWA 等）
- 是否有 per-coin 结构化基本面数据
- 是否有代币经济模型详情（解锁计划/销毁率）
- 决策：新增 collector / NLP 提取 / 不需要

---

## Phase D：Shadow 运行 + 性能追踪（Phase B 完成后）

### D1. 价格回填定时任务

**功能**：每天定时读取 shadow JSONL，对 7d/14d/30d 前的信号回填当前价格和收益率。

### D2. IC / 命中率 / Sharpe 统计 ✅ 已完成

**功能**：30 天滚动窗口计算 IC、命中率、S-C 模拟 Sharpe。

---

## Phase E：阶段闭环方法论（基于用户三阶段闭环洞察，2026-09-01 确认）

> 前置：Phase B（信号基础）+ D1（价格回填，已完成）
> 目标：把 UNI/CRCL/HYPE 三案例从"独立事件"升级为"P1预期→P2盈收→P3修复"闭环，系统可识别标的所处阶段并匹配差异化策略

### E1. E5/E6 新信号接入

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_crypto.py`（扩展）

**新增信号**：
- `compute_supply_shrinkage_intensity(coin) -> float`（E5）：销毁强度/供给收缩 z-score。数据源：CoinGecko total_supply/circulating_supply 时序 + DeFiLlama fees
- `compute_value_capture_delta(coin) -> float`（E6）：价值捕获质变 delta z-score。数据源：fees_30d 变化率 vs TVL 变化率的差值

**用途**：阶段识别器的核心输入特征。E5 判盈收扩张强度，E6 判预期/质变

**TDD**：
- test_supply_shrinkage_intensity_high_burn
- test_value_capture_delta_positive_on_revenue_expansion
- test_e5_e6_failopen_on_missing_data

### E2. 阶段识别器（独立模块）

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_phase_classifier.py`（新建）

**内容**：
- `@dataclass PhaseClassification`：current_phase, phase_confidence, switch_triggers, evidence, strategy_hint
- `classify_phase(coin, sub_signals, valuation_percentile, event_timeline) -> PhaseClassification`
- 阶段枚举：`P1_EXPECTATION` / `P2_REVENUE_EXPANSION` / `P3_VALUATION_RECOVERY`
- 混合规则（三因子组合，任一触发即评估切换）：
  1. 事件驱动：主网落地/盈收公告/Robinhood 接入 → P1→P2 或 P2→P3 边界
  2. 信号阈值：E6 跌破 0.3（预期消退）/ E5 跌破 0.3（盈收放缓）→ 流转信号
  3. 估值分位：>80 → P3 倾向；30-80 → P2 倾向；<30 + E6>0.5 → P1 倾向

**开关**：`enable_phase_classifier`（默认 False，Shadow）

**FAIL-OPEN**：三因子冲突 → phase_confidence 低 + 默认 P2（中性）

**TDD**：
- test_classify_p1_on_event_and_e6_high
- test_classify_p2_on_e5_e6_both_high
- test_classify_p3_on_valuation_high_percentile
- test_phase_switch_p1_to_p2_on_event_landing
- test_phase_confidence_low_on_conflicting_signals
- test_failopen_returns_neutral_p2

### E3. 阶段匹配策略映射表

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_phase_strategy_map.py`（新建）

**内容**：
- `PHASE_STRATEGY_MAP`：phase × rank → {信号权重偏移, SL 空间建议, TP 空间建议, 持仓时间建议}
- `get_strategy_hint(phase, rank) -> Dict`：查表返回策略提示
- 案例锚定：每个 phase 用 UNI/CRCL/HYPE 作为基准锚点，新标的与案例相似度（CBR）越高，策略越向案例靠拢

**约束**：Shadow 不耦合 BCRM2.0，仅记录策略提示到 JSONL 审计日志

**TDD**：
- test_p1_rank_s_higher_tp_short_holding
- test_p3_rank_s_lower_sl_space_mid_holding
- test_p2_rank_a_track_revenue
- test_unknown_phase_returns_neutral_strategy

### E4. CoinFundamentalSignal 数据类扩展

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_ranker.py`（扩展）

**新增字段**：
```python
current_phase: str = "P2_REVENUE_EXPANSION"  # 默认中性
phase_confidence: float = 0.0
phase_switch_triggers: List[str] = field(default_factory=list)
phase_strategy_hint: Dict[str, Any] = field(default_factory=dict)
```

**集成点**：`compute_signal()` 在等权合成后调用 `classify_phase()`，填充 phase 字段

### E5. 阶段闭环回放脚本

**文件**：`11-易经推理系统/scripts/memory_l4/scripts/coin_fundamental_phase_replay.py`（新建）

**功能**：回放三案例完整阶段流转，验证系统在每个切换点是否及时识别
- CRCL：P1（主网预期）→ P2（落地后盈收跟踪）
- UNI：P2（Robinhood 接入盈收扩张）→ P3（估值到高位）
- HYPE：P3（大跌后修复力）

**输入**：合成事件时间线 + 历史价格 + E5/E6 信号序列
**输出**：回放报告 JSON，含每个切换点的识别延迟、置信度、策略提示变化

**TDD**：
- test_replay_crcl_p1_to_p2_on_mainnet_launch
- test_replay_uni_p2_to_p3_on_valuation_peak
- test_replay_hype_p3_recovery_signal
- test_replay_reports_switch_detection_latency

### E6. 映射扩展

**文件**：`11-易经推理系统/scripts/memory_l4/force_vector/coin_fundamental_ranker.py`（扩展 CRYPTO_MAP）

**扩展**：
```python
CRYPTO_MAP["HYPE"] = {"coingecko_id": "hyperliquid", "defillama_slug": "hyperliquid"}
CRYPTO_MAP["CRCL"] = {"coingecko_id": "acrocalctoken", "defillama_slug": None}  # 视实际可用性调整
```

**TDD**：
- test_crypto_map_hype_to_hyperliquid
- test_crypto_map_crcl_resolves

---

## 依赖关系图

```
A1 (DeFiLlama扩展) ─┐
A2 (CoinGecko新建) ─┤
A3 (yfinance扩展)  ─┼─→ B1 (数据类+映射) ─→ B2 (crypto) ─┐
A4 (注册+调度)      ─┘    B1 ──────────→ B3 (stock)  ─┤
                          B1 ──────────→ B4 (metal)  ─┼→ B5 (合成+Shadow) ─→ D1 (价格回填)✅ ─→ D2 (IC统计)✅
                                                        │                         │
C1 (媒体调研) ──────────────────────────────────────── ┘ (并行)                   │
                                                                                  │
            B2 (crypto) ─→ E1 (E5/E6信号) ─→ E2 (阶段识别器) ─→ E3 (策略映射表) ─┤
                                              │                  │                 │
                                              └→ E4 (数据类扩展)  └→ E5 (闭环回放) ─┘ (依赖 D1 价格数据)
            E6 (映射扩展) ── 独立，可并行 ──────────────────────────────────────────┘
```

---

## 执行顺序

1. **A1-A4**（数据源扩展）：4 个 collector 修改/新建 + 注册 + TDD
2. **B1**（数据类+映射表）：基础设施
3. **B2-B4**（三类信号）：可并行开发
4. **B5**（合成+Shadow）：集成
5. **C1**（媒体调研）：并行进行
6. **D1-D2**（Shadow 追踪）：✅ 已完成
7. **E1**（E5/E6 新信号）：依赖 B2，扩展 crypto 子模块
8. **E2**（阶段识别器）：依赖 E1，新建独立模块
9. **E3**（策略映射表）：依赖 E2，新建映射模块
10. **E4**（数据类扩展）：依赖 E2，扩展 CoinFundamentalSignal
11. **E5**（闭环回放）：依赖 E2/E3 + D1 价格数据
12. **E6**（映射扩展）：独立，可随时插入
