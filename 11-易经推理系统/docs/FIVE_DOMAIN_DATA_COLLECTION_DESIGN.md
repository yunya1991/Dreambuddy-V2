# 五计庙算战略层 — 数据采集设计

> **文档版本**：v1.0 | **创建日期**：2026-08-24
> **上游 Spec**：`docs/superpowers/specs/2026-08-21-sunzi-five-domains-evaluation.md` §三
> **消费方**：`scripts/memory_l4/five_domain_feature_computer.py` 的 `compute(coin_data, system_state)`
> **执行引擎**：`18-数据获取中心/data_center`（M1-M5 已完成，SDK + 爬虫双轨）

---

## 一、数据全景清单（五维 × 三类资产）

`FiveDomainFeatureComputer.compute(coin_data, system_state)` 的输入分两部分：
- **`coin_data`（每类资产独立）**：需通过外部数据 + 市场衍生计算采集
- **`system_state`（系统自省）**：将/法维度读取，来自策略库内部状态，不走外部采集

### 1.1 按资产类分层的 `coin_data` 格式（目标输出形态）

```python
{
  "crypto_usdt": {
    # ── 道 D 类：外部采集 ──
    "fedfunds_rate": 5.25,                # D1 联邦基金利率
    "m2_yoy_pct": 2.3,                    # D2 M2 同比增速
    "fed_balance_sheet_trillion": 7.2,    # D3 央行资产负债表（万亿 USD）
    "us_cpi_yoy_pct": 2.9,                # D4 CPI 同比
    "us_ppi_yoy_pct": 0.8,                # D5 PPI 同比
    "us_indpro_yoy_pct": 1.2,             # D6 工业产出同比（美林增长 proxy）
    "stablecoin_mcap_bln": 105.2,         # D7 稳定币总市值（B USD）
    "defi_tvl_bln": 38.1,                 # D8 DeFi TVL（B USD）
    "gas_eth_gwei": 18,                   # D9 以太坊 Gas 价格（Gwei）
    "policy_sentiment_score": 0.65,       # D10 政策景气度 [-1, 1]，归一化 0.65→友好
    # ── 天 T 类：外部采集 + 本地日历 ──
    "merrill_phase": "RECOVERY",          # T1 美林时钟：由 D4+D6 编排层判定
    "vix_close": 14.2,                    # T2 VIX（^VIX 实时）
    "atr_percentile": 0.42,               # T3 ATR 分位：市场 K 线衍生
    "liquidity_score": 0.58,              # T4 流动性评分：由 D1/D2/D3 编排层归一化
    # ── 地 G 类：市场 K 线衍生（本地计算，不依赖外部采集）──
    "cycle4y_t_rel": 0.31,                # G1 4年周期位置：本地 MorphCycle
    "regime": "trend_up",                 # G2 状态机判定
    "spring_force_score": 72,             # G3 弹簧力场评分
    "price_amplitude": 0.032,             # G4 最近 N 日价格振幅
    "atr": 520.0,                         # G5 ATR
    "ftd_signal": 1,                      # G6 Follow-through Day：>0 正向
    "ma200_distance_percentile": 0.68,    # G7 价格 vs MA200 距离分位
  },
  "us_stock":    { /* 同结构：指标一致但数据源不同（CCXT→yfinance 美股）*/ },
  "precious_metal": { /* 同结构：GLD/SLV/XAUUSD */ },
}
```

### 1.2 将/法维度 — 不从 data_center 读取

| 维度 | 子项 | 来源 |
|---|---|---|
| 將：智/信/仁/勇/严 | factor_coverage_pct / 连续亏损次数 / 最大回撤 / 止损触发达标率 / 硬约束覆盖度 | 读取 polling_trader 内部 TradeRecord / engine_state.json 等 |
| 法：策略库完备/适配度/风控完整度/回测验证/复盘迭代 | 策略库形态 + 风控配置 | 读取 config/sources.yaml + 策略注册表 |

---

## 二、采集映射矩阵（data_center 能力对照）

> G = Green（已有覆盖）；Y = Yellow（已有框架 + 缺 series/route 配置即可）；R = Red（需新增 collector）

| ID | 数据项 | 类别 | collector | 状态 | 备注 |
|---|---|---|---|---|---|
| D1 | 联邦基金利率 FEDFUNDS | 道 | fred | 🟢 | M1 已上线 |
| D2 | M2 同比 M2NS/M2SL | 道 | fred | 🟡 | 已有框架 + 补 series 映射 |
| D3 | 联储总资产 WALCL | 道 | fred | 🟡 | 已有框架 + 补 series 映射 |
| D4 | CPI 同比 CPIAUCSL | 道（天复用） | fred | 🟡 | 美林时钟通胀 proxy |
| D5 | PPI 同比 PPIACO | 道 | fred | 🟡 | 辅助通胀指标 |
| D6 | 工业产出同比 INDPRO | 天 | fred | 🟡 | 美林时钟增长 proxy |
| D7 | 稳定币总市值 | 道 | defillama | 🔴 | 新增 DeFiLlama chain-level 接口 |
| D8 | DeFi 总 TVL / Top 链 TVL | 道 | defillama | 🔴 | 新增 DeFiLlama protocol-level 接口 |
| D9 | ETH Gas 价格 | 道 | etherscan | 🟢 | 已有 etherscan_collector，补 gas_oracle 路由 |
| D10 | 政策景气度（SEC/CFTC/Fed 新闻情绪） | 道 | tavily + gdelt + feedparser | 🟢 | 编排层 query 聚合 + 简易情绪词典 |
| T2 | ^VIX 指数收盘价 | 天 | yfinance | 🟢 | 已有 YFinanceCollector，symbol="^VIX" |
| T3/G5 | BTC/ETH 行情（OHLCV） | 地/天 | ccxt | 🟢 | CcxtCollector 计算 ATR 等 |
| T3/G5 | 美股/黄金 ETF（SPY/QQQ/GLD/SLV） | 地/天 | yfinance | 🟢 | |
| T4 | QE/QT 评分（liquidity_score） | 天 | 编排层派生 | - | 由 D1/D2/D3 归一化合成 |
| T1 | 美林时钟阶段 | 天 | 编排层派生 | - | 由 CPI（↑/↓）+ 工业产出（↑/↓）四象限判定 |
| G1~G7 | 市场结构 7 项 | 地 | 本地 K 线派生 | - | 不占用外部采集配额 |

---

## 三、缺口补全方案

### 缺口 1：FredCollector 补 5 个 series 映射

修改 `collectors/macro/fred_collector.py`，在 series 映射表中追加：
- M2NS / M2SL → sub_category = "M2"（M2 同比/环比）
- WALCL → sub_category = "FED_BALANCE"（联储资产负债表）
- CPIAUCSL → sub_category = "CPI"
- PPIACO → sub_category = "PPI"
- INDPRO → sub_category = "INDPRO"（工业产出）

### 缺口 2：新增 DeFiLlamaCollector（补 D7/D8）

文件：`data_center/collectors/chain/defillama_collector.py`
数据源：**免费、无需 Key** 的 DeFiLlama 公共 API：
- `GET https://api.llama.fi/v2/chains` → 所有链的 TVL（含稳定币市值 proxy + 各链 TVL）
- `GET https://api.llama.fi/v2/historicalChainTvl/Ethereum` → 单链历史 TVL
- `GET https://api.llama.fi/summary/fees/ethereum?dataType=dailyFees` → Gas/手续费（可选，与 D9 Etherscan 互相印证）

### 缺口 3：编排层 FiveDomainFetcher

文件：`scripts/memory_l4/fivedomain_fetcher.py`
职责：
1. 调用 DataCenter 拉取 D1~D10/T2 等所有 raw 数据
2. 编排派生 T1（美林时钟）+ T4（流动性评分）
3. 按三类资产拼出 `coin_data` 分层结构
4. 缓存：sqlite + 12 小时 TTL，避免每天重复调用 API
5. 输出：`Dict[asset_class, Dict[str, Any]]` 可直接喂给 `FiveDomainFeatureComputer.compute(coin_data=...)`

### 缺口 4：政策景气度 D10

**不新增 collector**，用 TavilyCollector 查询三类 query 聚合结果：
- "Fed FOMC monetary policy"
- "SEC CFTC crypto regulation update"
- "China crypto policy news latest"
编排层对结果标题 + 摘要做简易情绪打分（正面关键词 - 负面关键词 归一化）。

---

## 四、实现顺序（TDD）

| 阶段 | 任务 |
|---|---|
| P1 | 补 FredCollector 5 个 series（无 Key 降级）|
| P2 | DeFiLlamaCollector TDD |
| P3 | etherscan_collector 补 gas_oracle 路由（无需 API Key 也行：免费 etherscan 公共端点） |
| P4 | FiveDomainFetcher 编排 TDD（mock 所有上游） |
| P5 | CLI 子命令 `data-center fivedomain fetch --class crypto|all` |
| P6 | 回归 + 对接 `FiveDomainFeatureComputer`（coin_data 自动填外部采集值，不再只 fail-open 50） |

---

## 五、fail-open 约定（与 §九 保持一致）

**任何外部采集失败 / 缺 Key / 超时**：对应字段写入 `None`，由 `FiveDomainFeatureComputer` 的单个子项 try/except 兜底回退中性 50，整个系统不抛异常。
