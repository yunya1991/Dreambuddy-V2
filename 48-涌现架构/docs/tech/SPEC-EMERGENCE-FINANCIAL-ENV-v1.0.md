# SPEC — 金融交易涌现环境 v1.0

> **定位**：为金融交易构建"充分涌现环境"的总纲——把**金融事件（E）× 金融语义情绪（S）× 市场情绪（M）× 市场形态（P）**四层异质信号，在**龙头资产宇宙**上做时间轴对齐与联合验证，产出可证伪的组合因子，供 48 涌现判据 / 40 周期神经网络 / 50 决策消费。
> **版本**：v2.8（三处代码缺口收口：① 形态层补 RSI14/MACD → 29→33 列并自动进 `P_score`；② `regime.py` 接入本地 crypto F&G 历史（含 3 天陈旧容忍，缺失即 null）；③ 48 新增 39 S 层适配器 `--semantic-events`，S_score 与 `S×P` 恢复。§9「9 域各维历史统计」明确**需单独开 SPEC**，本轮不实现。数据回填与真实重跑仍交云端）
> **日期**：2026-11-12
> **上游依赖**：39 金融语义蒸馏（语义层 SSoT）、9 基本面分析（统计上下文）、18 数据获取中心（采集）
> **下游消费**：48 涌现判据（E1-E5）、40 周期神经网络、50-NN 决策
> **不重复定义**：L1/L2 契约以 46/47 与 39/9 各自 SPEC 为准；本文件只做**编排与新增契约**（同 FULL-CHAIN-SPEC 的 SSOT 纪律）

---

## §0 执行摘要

### 0.1 本 SPEC 要解决的问题

现有系统已经具备：crypto 快讯情绪（双 FinBERT：中文 `yiyanghkust/finbert-tone-chinese` + 英文 `ProsusAI/finbert`，中文已于 P0-F 接通）、技术指标（21 FeatureHub）、crypto 恐慌贪婪指数。但存在三个结构性缺陷：

1. **信号孤岛**：情绪、事件、量价各自为政，没有统一的时间轴对齐与联合判据 → 无法回答"某个金融事件在什么情绪/形态背景下才有效"
2. **语义层错位**：FinBERT 直接对快讯打分（`9-基本面分析/engines/sentiment_engine.py`），而 39 金融语义蒸馏只处理 trader.log 术语事件（`39-金融语义蒸馏系统/semantic_events.jsonl` 20927 条，`source=trader.log`，无情绪字段）→ 两套语义平行、互不相通
3. **覆盖面偏科**：只有 crypto 快讯源（Odaily/CryptoPanic 等），**没有任何传统金融事件源**（美股财报、FOMC、宏观数据）；中文财经门户（新浪财经、华尔街见闻、财联社、金十）采集器为零（`18-数据获取中心/data_center/collectors/news/` 实测 11 个采集器，全部为 crypto/RSS 类）

### 0.2 四条诚实前提（先承认，再设计）

| # | 前提 | 依据 |
|---|---|---|
| P-1 | **本地已验证的 F&G 信号不构成统计发现** | `fg_delta_3d → ret_3d` IC=-0.4826, p=0.013 约合 t≈2.5；在检查过 >10 个信号后按 Harvey-Liu-Zhu (RFS 2016) 的 **t>3.0** 门槛不显著。只能定性为"方向性线索（contrarian）"，不能作为设计基石 |
| P-2 | **技术指标单独预测力极弱** | 本地实测 7 个技术指标对 BTC 的 IC 全部 <0.04；学术侧 Brock-Lakonishok-LeBaron (1992) 的 MA 规则优势在计入交易成本与数据窥探偏差后大幅缩水 → 形态层定位为**状态描述与确认**，不作独立 alpha |
| P-3 | **情绪反向必须条件化** | Baker-Wurgler 情绪指数的反向有效性集中在"高情绪期 + 难估值/难套利标的"，无条件反向是错的 → 本 SPEC 用 `情绪极值 × 拥挤/估值` 联合触发，替代此前"情绪越乐观越看跌"的单一假设 |
| P-4 | **中文模型可用但未真正接上：`finbert-tone-chinese` 的 `LABEL_0/1/2` 未被映射，中文全部静默回退规则引擎** | 事实链（2026-11-11 核实）：① 云端中文模型 = [`yiyanghkust/finbert-tone-chinese`](https://huggingface.co/yiyanghkust/finbert-tone-chinese)（`bert-base-chinese` 微调，~8k 中文研报句，Acc 0.88 / Macro-F1 0.87，apache-2.0）；② 仓库代码却硬编码 `valuesimplex/FinBERT2`（本地 404）且**中文路径无 env 覆盖**（仅英文有 `FINBERT_EN_MODEL_PATH`，[sentiment_engine.py:330-353](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析/engines/sentiment_engine.py#L330-L353)）；③ 该模型输出 `LABEL_0=Neutral / LABEL_1=Positive / LABEL_2=Negative`，而 `FINBERT_ZH_LABEL_MAP`（[L180-196](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析/engines/sentiment_engine.py#L179-L196)）**没有 `LABEL_*` 任何键** → `label_map.get(label)` 返回 `None` → [L422-425](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析/engines/sentiment_engine.py#L417-L425) 直接 `return None` → **每条中文都回退到 27 关键词规则引擎**；④ 若中文模型缺失，还会跨语言 fallback 到英文 `ProsusAI/finbert`（实测中文分词 UNK 率 54%） |

### 0.3 核心设计（一句话）

> **39 做唯一的语义层；FinBERT 归位为 9 域的打分服务（不迁入 39、不再自建因子），由 39 在事件标准化时写入情绪属性；E/S/M/P 四层统一为 `EventRecord` + `DimensionSignal` 契约，在龙头宇宙上按事件窗口对齐；所有因子必须过"正交化 → 增量 IC → 状态分桶 → DSR/PBO"四道关，且 verdict 只能由 `assert_gate()` 产出。v1 的目标不是找 alpha，而是建立可证伪的验证流水线。**

---

## §1 现状核查与缺口

### 1.1 已有资产（可直接复用，不重建）

| 能力 | 位置 | 状态 |
|---|---|---|
| 技术指标 | `21-特征工程中心/feature_hub/modules/classic_indicators.py`（SMA 10/20/50、EMA 12、RSI14、MACD、BOLL(20,2)、ATR14、ADX14、OBV、Williams %R） | ✅ 有统一库 |
| talib 对齐层 | `feature_hub/modules/talib_aligned.py`（列名与 talib.abstract 100% 对齐，缺库时 pandas 兜底） | ✅ |
| 双 FinBERT | `9-基本面分析/engines/sentiment_engine.py`（中文占比 ≥30% 走 `yiyanghkust/finbert-tone-chinese`，否则 `ProsusAI/finbert`；3 层 FAIL-OPEN） | ✅ 英文 4 键接口可复用；中文模型已于 2026-11-11 接通（P0-F）：`+0.9992/-0.9981/0.0` 实测通过，`with_meta=True` 取 `model` 溯源 |
| crypto 恐慌贪婪 | `18/.../collectors/chain/fear_greed_collector.py`（alternative.me，2018 至今）+ `fear_greed_enhanced_collector.py`（MVRV/NUPL/SOPR/funding/stablecoin/altseason/divergence） | ✅ |
| VIX | ✅ **已单一化（P1-B）**：`18/.../collectors/chain/vix_collector.py` 为唯一实现（主源 FRED `VIXCLS` + CBOE `VIX3M`/`VVIX`，Yahoo `^VIX` 仅当日补充；`RegimeSchema` 见 `48/metrics/regime.py`） | ✅ 单一口径 + 期限结构/二阶；put/call 无稳定公开源按 null 留空（见 §5.2.1） |
| 深度文章三层解构 | `18/.../processing/factor_extractor.py`：`extract_factors()` (F1) / `extract_article_factors()` (F2) / `extract_dominance_claim()` (F3) | ✅ |
| 9 域上下文 | `18/.../processing/dimension_context.py`：`DimensionContext` 8 维（D1/D2/D3/D4/C6/C7/C8/NEWS） | ✅ |
| 39 语义事件流 | `39/semantic_events.jsonl`（20927）、`contradiction_events.jsonl`（1376） | ⚠️ 20927 条 **100% `source=trader.log`（交易日志），零新闻语义事件** — 语义管道存在但未接新闻 |

### 1.2 缺口清单（本 SPEC 要补的）

| ID | 缺口 | 影响 | 优先级 |
|---|---|---|---|
| **G1** | 39 与 FinBERT 无接口：39 事件无 `sentiment` 字段，FinBERT 不产出事件级语义 | 情绪与语义脱节，无法做"事件×情绪"交叉 | P0 |
| **G2** | 无传统金融事件采集源（SEC EDGAR 财报/FOMC/CPI/非农） | 事件层 E 完全空缺 | P0 → **✅ 已修复（P0-C，2026-11-11）**：`collectors/tradefin/` 三官方源 → `data_center/events/events.jsonl`，30 天回填 74 条，`available_at` 完整率 100% |
| **G3** | 中文财经门户采集器为零（新浪财经/华尔街见闻/财联社/金十） | 深度文章仍只覆盖 crypto | P0 → **✅ 已修复（P1-A，2026-11-11）**：4 源落地→`events.jsonl`+`bodies.jsonl`，实测 15 请求 0 失败 |
| **G4** | 无"资产龙头"宇宙定义（全仓库无 leader/watchlist 配置，仅 `experiments/ab-trading/scripts/universe_screener.py` 有 crypto universe） | 无法界定"只针对龙头" | P0 |
| **G5** | VIX 曾有**两套口径**（18 `panewslab_collector` 的 FRED `VIXCLS` 日频 / nanoclaw 的 Yahoo `^VIX` 实时）未合并；无 VIX 期限结构 / VVIX / put-call | 市场情绪层 M 不完整且口径不可比 | P1 → **✅ 已修复（P1-B，2026-11-11）**：`collectors/chain/vix_collector.py` 单一实现，FRED 主源 + CBOE VIX3M/VVIX，30 天连续性 `ok=true` |
| **G6** | MA 缺 5/13/65/128/200 多均线排列；Pivot Point 全仓库零实现（`grep pivot` 于 21-特征工程中心无命中）；缺 OBV 背离；**RSI/MACD 未进 P 层因子** | 形态层 P 不完整 | P1 → **✅ 已修复（P1-C + v2.8）**：`feature_hub/modules/leader_form.py` **33 列**（均线栈/Pivot/量能/OBV 背离/布林状态 + RSI14/MACD），16 条单测 + FeatureHub 集成；新增列经 `_form_long()` 自动进 `P_score` |
| **G7** | E/S/M/P 四层无统一契约，无时间轴对齐器 | 三维联合验证无法执行 | P0 → **✅ 已修复（P2-A，2026-11-12）**：`48/metrics/financial_env_align.py` 统一 `align()`，事件按 `available_at` 落首个可交易时点，市场级信号按 date 广播，前视审计 0 违规 |
| **G8** | 深度文章三层抽象未产出"组合因子"（`factor_prior.json` 当前 `degraded=true, n_factors=0`） | 组合因子链路断 | P1 → **✅ 已修复（P1-D，2026-11-12）**：`deep_factor_prior.py` 产出 `factor-prior-v2`，`n_factors=10`、`n_sources=4`、`degraded=false`，按源分层 + 弱证据隔离 |
| **G9** | 统计**函数**已有（45 评测系统 `deflated_sharpe_ratio`/`pbo_cscv`/`purged_kfold`/`walk_forward`），但**未接入 48 因子评估**，且无试验记账与强制门禁 | 结论不可信 | **P0（先行）** |
| **G10** | 40 域三套价格口径并存（Binance p1 / yfinance p2 / OKX p3），同一资产 MA200/动量/相关性不可比 | U 层无法确定唯一价格源，信号与标签不可信 | P0 → **✅ 代码已收口（2026-11-12）**：18 `data_center/market/price_source.py` 为唯一 OHLCV 实现（OKX `-USDT-SWAP` 主源 + Binance 显式 fallback，`1Dutc` UTC 对齐，只返回已收盘 bar），40 域 p1/p2/p3 共 7 处直连全部改为调用它，静态守护禁 `fetch_ohlcv/ccxt.binance/ccxt.bybit`；**历史数据回填与真实重跑交云端** |
| **G11** | **中文模型"在但没用上"**：云端有 `finbert-tone-chinese`，但代码硬编码已 404 的 `valuesimplex/FinBERT2` 且中文路径无 env 覆盖；同时 `FINBERT_ZH_LABEL_MAP` 缺 `LABEL_0/1/2` → 中文全部静默回退规则引擎 | 64% 有效文本走 27 关键词规则，S 层与"FinBERT 情绪"名不符实 | P0 → **✅ 已修复（P0-F，2026-11-11）**：模型可配置 + `id2label`/契约双来源映射 + 删跨语言 fallback；实测 +0.9992/-0.9981/0.0 |
| **G12** | `EventRecord`（原拟 EventSchema）与 9 域既有三套事件契约（`event_ledger_engine` / `event_mapping_engine` / `news_contract_validator`）可能冲突 | 事件层出现四套互不兼容 schema | P0 → **✅ 设计已关闭**（§3.0 方案 C：三层复用 + 最小扩展，canonical = EventLedger） |
| **G13** | 统计门禁无强制点：无 `trials.jsonl` 写入点、无因子注册闸门、`verdict` 四态无枚举 | §7.5 六道关可被任意脚本绕过 | P0 → **✅ 设计已关闭**（§7.6 唯一入口 `assert_gate()` + 四强制点 + 可审计绕过） |
| **G14** | `RegimeSchema` 支持 `crypto_fng` 入参，但 `regime.py` 的 `--write-history`/`--check` 从未传入 → 285 日 schema 的 `crypto_fng` 全为 null，`M_label` 缺 F&G 方向 | M 层只剩 VIX，F&G 极值无法参与分档 | P1 → **✅ 已修复（v2.8，2026-11-12）**：新增 `load_crypto_fng_history()` 读 18 `data_center.db` 的 `crypto_fear_greed`，当日缺失仅在 `FNG_MAX_STALE_DAYS=3` 内回退，超期即 null；`crypto_fng.as_of` 标注真实观测日 |
| **G15** | 48 联合验证无默认 S 层来源，`--sentiment` 需手工传文件 → `S_score` 全 NaN，L-B 只剩 `E×M` | S 层形同虚设 | P1 → **✅ 已修复（v2.8，2026-11-12）**：新增 `load_semantic_sentiment()`（39 `semantic_events.jsonl` → `symbol/date/score/available_at`，同日聚合 mean + 最晚 `available_at`）+ `--semantic-events` 自动加载，实测 68 个（标的×日期）行 |

---

## §2 总体架构

### 2.1 四层信号 + 一个宇宙

```
┌──────────────────────────────────────────────────────────────┐
│  U 层：龙头资产宇宙（leader_universe.json）                    │
│      crypto / us_equity / cn_equity / macro 四类，每类 5-15 只  │
└──────────────────────────────────────────────────────────────┘
        ↑ 所有信号只在这个宇宙上验证（不做全市场扫描）

┌─ E 层 金融事件 ─┐   ┌─ S 层 金融语义情绪 ─┐  ┌─ M 层 市场情绪 ─┐  ┌─ P 层 市场形态 ─┐
│ 财报 / FOMC     │   │ 39 语义事件         │  │ crypto F&G     │  │ MA 多均线排列   │
│ 宏观数据 / 监管  │   │ + FinBERT 打分      │  │ VIX 三件套      │  │ RSI / MACD     │
│ 公司行动        │   │ + 三权重聚合        │  │ VIX 期限结构    │  │ Pivot / BOLL   │
│     ↓           │   │     ↓              │  │     ↓          │  │ OBV / 量能      │
│  EventRecord    │   │  SentimentSchema   │  │  RegimeSchema  │  │  FormSchema    │
└────────┬────────┘   └────────┬───────────┘  └────────┬───────┘  └────────┬───────┘
         └─────────────────────┴───────────────────────┴───────────────────┘
                                      ↓
                        ┌──────────────────────────────┐
                        │  J 层：对齐与联合验证          │
                        │  时间轴对齐 + 状态分桶 + 消融  │
                        └──────────────────────────────┘
                                      ↓
              DimensionSignal（8 维扩展）→ 48 判据 / 40 NN / 50 决策
```

### 2.2 与 48 FULL-CHAIN 的位置关系

本 SPEC 是 [SPEC-EMERGENCE-FULL-CHAIN-v1.0.md](./SPEC-EMERGENCE-FULL-CHAIN-v1.0.md) 中 **L1（数据地基）→ L2（语义与 9 域上下文）→ L3（深度文章三层解构）** 三段的**加密与扩展**，不改动 L4-L9。新增内容全部落到 L1/L2 契约内部，不新增主链节点。

### 2.3 龙头宇宙定义（U 层）——以 40 域资产分类为准

**核心原则：不另立宇宙。** U 层直接投影 [40-周期神经网络系统/asset_classes.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/asset_classes.py) 与 [ASSET-CLASS-MAP.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/40-周期神经网络系统/ASSET-CLASS-MAP.md) 已核验的 10 大类 + G0/G1/G2 三层拓扑，本 SPEC 只新增**信号覆盖映射**（每个资产配哪些信号层），**不新增资产表**。

**为什么必须衔接 40**：40 已有 OKX 永续合约级别的核验（543 个永续 / 528 个基础标的，`state=live`）、六锚跨类传导矩阵、MA200 锚；若 U 层另起一套标的与价格源，会出现第四套价格口径（现有已有三套：Binance / yfinance / OKX），MA200/动量/相关性全部不可比。

#### U 层 = 40 的 G1 六锚（核心）+ G2 类内龙头（扩展）

| # | 40 资产大类 | G 层 | 龙头 | U 层验证成员 | OKX 合约 | 需覆盖信号层 |
|---|---|---|---|---|---|---|
| 1 | 加密 | G1 | **BTC** | BTC / ETH / SOL / AVAX / LINK | `BTC-USDT-SWAP` 等 | E+S+M+P |
| 2 | 贵金属（避险） | G1 | **XAU 黄金** | XAU / **XAG 白银** / XPT / XPD | `XAU-USDT-SWAP`、`XAG-USDT-SWAP` | E+S+M+P |
| 3 | 工业金属 | G2 | **XCU 铜** | XCU | `XCU-USDT-SWAP` | E+S+M+P |
| 4 | 能源 | G1 | **CL WTI 原油** | CL / BZ 布伦特 / **NG 天然气** / USO | `CL-USDT-SWAP`、`NG-USDT-SWAP` | E+S+M+P |
| 5 | 美股宽基 | G1 | **US500** | US500 / US100 / SPX | `US500-USDT-SWAP` | E+S+M+P |
| 6 | 美股行业 ETF | G2 | **SPY** | SPY / QQQ / IWM / SMH / XLE / XLV / XBI / URNM | 对应 `-USDT-SWAP` | E+S+M+P |
| 7 | 亚太股指 | G1 | **JP225 日经** | JP225 / KR200 | `JP225-USDT-SWAP` | E+S+M+P |
| 8 | 美股个股 | G2 | **NVDA（AI 算力）** | NVDA / AMD / AVGO / TSM / ASML / MU / ARM；AAPL / MSFT / GOOGL / AMZN / META；GS / JPM / V；COIN / MSTR | 对应 `-USDT-SWAP` | E+S+P（M 用大类代理） |
| 9 | 外汇 | **G0** | DXY 美元指数（不可直交易） | `DTWEXBGS` / `DX-Y.NYB` | 无 | 仅 M（regime 门控） |
| 10 | 利率/信用 | G1 | **TLT（20Y 美债）** | TLT 价格 + `DGS10` / `T10Y2Y` / `HY OAS` | `TLT-USDT-SWAP` | E+S+M+P |

**用户点名必含项已全覆盖**：黄金 `XAU`、白银 `XAG`、石油 `CL`/`BZ`、天然气 `NG`、铜 `XCU` —— 全部在 40 已核验的 OKX 永续清单内，**无需新增行情数据源，只需接入 40 现有采集**。

#### 与 40 的三条衔接契约（硬约束）

| # | 契约 | 说明 | 解决 40 的既有缺口 |
|---|---|---|---|
| **U-1** | **价格唯一主源 = OKX `-USDT-SWAP`** | 所有信号层（P 形态 / M 波动 / 标签收益）统一用 OKX 永续日线；yfinance/FRED 仅作 G0 宏观序列，不进因子 | 40 ASSET-CLASS-MAP §五 缺口 1「双源并存」 |
| **U-2** | **黄金双轨沿用 40 已确认方案** | `XAU-USDT-SWAP` 做交易/传导；`XAUT/USDT` spot 仅作宏观背离参考 | 40 缺口 2「黄金标的错位」 |
| **U-3** | **多锚替代单锚** | G1 六锚（BTC/XAU/CL/US500/JP225/TLT）各自承接宏观力，禁止把 G0 宏观力全灌入 BTC | 40 缺口 3「单锚假设」 |

#### 信号覆盖的差异化（不是所有资产都配四层）

| 资产类型 | E 事件层 | S 语义层 | M 情绪层 | P 形态层 | 理由 |
|---|---|---|---|---|---|
| G1 六锚 | ✅ 全覆盖 | ✅ | ✅ | ✅ | 核心验证对象 |
| G2 类内龙头（XAG/NG/XCU/SPY/NVDA） | ✅ | ✅ | M 走大类代理（避免样本量稀释） | ✅ | 类内传导验证 |
| 个股（非龙头） | 仅财报类 | ✅ | ❌ | ✅ | 事件密度足够，情绪 M 层噪音大 |
| G0 宏观（DXY/利率） | ✅ | ❌ | ✅ | ❌ | 只做 regime 门控，不做形态 |

**纪律**：
1. 宇宙按月复核（`universe_reviewed_at`），变更记入 `universe_change_log.jsonl`
2. **回测必须使用 point-in-time 宇宙快照**，禁止用今日宇宙回测历史（幸存者偏差）
3. 若 40 的 `asset_classes.py` 变更，U 层必须同步（同一份常量，不复制）
4. 股票类永续按 40 已确认的 `EQUITY_ALIGNMENT="continuous_24h"` 对齐，但**标签收益必须按共同交易日计算**，避免把休市期算进 horizon

---

## §3 E 层：金融事件

### 3.0 事件契约对齐（关闭 P0-1）

**评审确认的存量事实**（9 域已有三套事件契约，禁止再造第四套）：

| 契约 | 位置 | 形态 | 关键字段 |
|---|---|---|---|
| 批次信封 | `9-基本面分析/ops/nanoclaw/core_task1/schema/news_contract.schema.json` | JSON Schema | 必填 `version` / `generated_at` / `time_window_hours` / `raw_crypto[]` / `raw_macro[]` |
| 事件类型 | `9/.../scripts/event_mapping_policy.map_event_type(topic, category, title, body)` | 函数（FAIL-OPEN → `unknown`） | 已有枚举含 `monetary_policy` / `us_policy` / `us_data` / `geopolitics` / `crypto_regulation` 等 13 类 |
| 事件记录 | `9/.../scripts/event_ledger_generator.EventLedgerGenerator`（经 `engines/event_ledger_engine.generate_ledger()` 暴露） | 记录 list | `event_type` / `risk_dir` / `sentiment_mean` / `sentiment_weighted` / `urgency_score` / `window` / `surprise_bucket` / `risk_action_proposal` |

**处置结论（方案 C：三层复用 + 最小扩展，不新建）**：

| 层 | 处置 | 兼容性 |
|---|---|---|
| 1 信封层 | `news_contract.schema.json` 新增**可选** `raw_tradefin[]` 数组（与 `raw_crypto` / `raw_macro` 并列），`version` 升 `1.1` | 旧消费者不读该字段即无感；`required` 不变 |
| 2 类型层 | 扩展 `event_mapping_policy` 枚举 **+6 类**：`earnings` / `guidance` / `rate_decision` / `mna` / `buyback` / `dividend`；原 13 类与 `unknown` 兜底全部保留 | 纯新增枚举值，无破坏 |
| 3 记录层 | **canonical record = EventLedger entry**（唯一真源）。新增 7 个字段，不改任何原有字段 | 原字段消费者零影响 |

**记录层新增字段（即本 SPEC 的 `EventRecord`，替代原 v1.1 的"新建 EventSchema"）**：

```python
EventLedgerEntry += {                  # 原有字段全部保留
  "event_id": "sha1(source|symbols|event_time|type)[:16]",   # 幂等键
  "available_at": "2026-11-20T21:00:03Z",  # 系统可得时间（回测唯一可用时间）
  "source_url": "...",
  "surprise": 0.8, "surprise_unit": "z | sue | pct | null",  # 原 surprise_bucket 保留为粗分桶
  "confidence": 0.0-1.0,
  "quality": "A | B | C",
  "trace_id": "<event_id>"               # 全链透传（关闭 P1-2）
}
```

**冲突解决规则（硬约束）**：
1. `map_event_type()` 对新 6 类事件必然返回 `unknown`（其词表未覆盖财报类）→ 此时以本 SPEC 的 `type` 为准，并写 `type_source="fin_env_spec"`；`map_event_type` 返回非 `unknown` 时 `type_source="event_mapping_policy"`，**两者并存不覆盖**
2. `sentiment_mean`（已有）与 S 层 `sentiment.score` 是**同一字段的两种命名** → 以 `sentiment_mean` 为准，S 层只做聚合不新增同义字段
3. 新增事件 JSON Schema 文件必须登记进 `event_schema_allowlist.txt`，CI 校验"仓内事件 schema 文件数 ≤ 4"，防第四套悄悄出现
4. **39 只读 canonical record**，不得自带事件库

### 3.1 事件字段定义（EventRecord v1）

```python
EventRecord = {   # = EventLedgerEntry（9 域已有）+ 以下新增字段，见 §3.0
  "event_id": "sha1(source|symbols|event_time|type)[:16]",
  "type": "earnings | guidance | fomc | cpi | nfp | rate_decision | mna | buyback | dividend | regulatory | product | legal | macro_other",
  "subtype": "...",                       # 例如 earnings: "8-K" / "10-Q"
  "symbols": ["NVDA"],                    # 受影响标的
  "sector": "semiconductor",
  "event_time": "2026-11-20T21:00:00Z",   # 事件发生时间（UTC，必填）
  "available_at": "2026-11-20T21:00:03Z", # 系统实际可得时间（防前视，必填）
  "source": "sec_edgar | fed_calendar | sina_finance | wallstreetcn | cls | jin10 | odaily",
  "source_url": "...",
  "title": "...",
  "body_ref": "contents.jsonl#<id>",      # 正文外置，避免事件表膨胀
  "surprise": null,                        # 事件强度（见 §3.4），可空
  "surprise_unit": "z | pct | sue | null",
  "expected": null, "actual": null,
  "confidence": 0.0-1.0,                   # 抽取置信度
  "quality": "A | B | C"                   # A=官方源直采 B=信源单一 C=LLM 推断
}
```

**契约纪律**：
- `available_at` 是唯一可用于回测的时间字段；`event_time` 仅用于窗口对齐。两者缺失时该事件降级为 C 级且不进入回测
- 所有事件写入 `18-数据获取中心/data_center/events/events.jsonl`（append-only，幂等键 `event_id`）
- 正文统一走已有 `backfill/odaily_p0/contents.jsonl` 同构的正文存储，事件表只存引用

### 3.2 新增采集源（对应 G2/G3）

| 采集器 | 文件（新建于 `18-数据获取中心/data_center/collectors/tradefin/`） | 覆盖 | 频率 | 合规 |
|---|---|---|---|---|
| `sec_edgar_collector.py` ✅ | `data.sec.gov/submissions`（8-K/10-Q/10-K/20-F/40-F/6-K，`acceptanceDateTime` 作 `available_at`）+ `company_tickers.json` 映射 CIK | 美股财报、重大事项 | 15min | 官方公开 API，合规 |
| `fed_calendar_collector.py` ✅ | Federal Reserve 官方 FOMC 会议日历（会议最后一日 14:00 ET 声明） | FOMC 议息 | 日 | 官方源 |
| `macro_calendar_collector.py` ✅ | BLS 官方年度发布日历（CPI / Employment Situation / PPI） | CPI / 非农 / PPI | 日 | 官方源优先 |
| `sina_finance_collector.py` ✅ | 新浪财经 7×24 快讯（`zhibo.sina.com.cn/api/zhibo/feed`，兼容 JSONP） | A 股/宏观快讯 | 10min | 公开页面低频，遵守 robots |
| `wallstreetcn_collector.py` ✅ | 华尔街见闻 资讯流 API（`lives` 快讯 + `articles` 深度 + `articles/{id}?extract=1` 正文） | 深度文章、宏观解读 | 30min | 公开接口，限频 |
| `cls_telegraph_collector.py` ✅ | 财联社电报（`v1/roll/get_roll_list`，公开签名 `md5(sha1(sorted_query))`） | A 股快讯 | 5min | 公开接口，限频 |
| `jin10_collector.py` ✅ | 金十快讯（`flash-api.jin10.com/get_flash_list`）；宏观日历接口 2026-11-11 实测下线（502/NoSuchKey）→ 显式 `CALENDAR_ENABLED=False`，日历由 P0-C BLS 官方源覆盖 | 宏观快讯 | 5min | 公开接口，限频 |

**P0-C 落地状态（2026-11-11）**：前 3 个官方源已实现，入口 `python3 -m data_center.cli.collect_events --days N`（18 目录下），统一写入 `data_center/events/events.jsonl`（append-only，`event_id` 幂等，`available_at` 缺失直接拒写）。实测 30 天回填 **74 条**（sec_edgar 69 / macro_calendar 4 / fed_calendar 1），`available_at` 完整率 **100%**、前视违规 **0**、重跑追加 **0**。

**P1-A 落地状态（2026-11-11）**：4 个中文源已实现，`fetch()` 返回 `CollectResult(events, bodies)`；正文 point-in-time 快照写入 `data_center/events/bodies.jsonl`（`body_id=sha1(source|url|date_published)[:16]`），事件表只存 `body_ref="bodies.jsonl#<id>"`；39 `gen_semantic_events.py` 已支持 `body_ref` 解析（`EMERGENCE_BODIES_PATH` 可覆盖）。实测 3 天窗口 **15 次请求 0 失败（失败率 0%）**，产出 **231 条**事件（sina 100 / wallstreetcn 60 / cls 50 / jin10 21）+ **231 条正文**，`available_at` 100%、前视违规 0；重跑 `bodies appended=0`。39 `--source events` 消费 302 条：**227 条走 `finbert-tone-chinese`**、75 条英文走 `ProsusAI/finbert`、`sentiment=null` **0 条**。

**硬红线（强制）**：
1. **禁止绕过登录墙/加密参数/验证码**——2025 修订《反不正当竞争法》第 13 条第 3 款与刑法 285 条已有判例。仅访问 robots.txt 允许的公开页面与官方 API
2. 每个采集器必须实现**全局限频**（≥ 该站点爬虫建议间隔 × 2）、失败退避、UA 标识
3. 抓取失败率 >30% 时自动熔断并降级到已有的 Tavily/GDELT 兜底（FAIL-OPEN）
4. 所有正文必须存 **point-in-time 快照**（含发布时间与修订时间），禁止用修订后正文回填历史

### 3.3 事件强度与衰减（§3.4 内容合并于此）

| 事件类型 | 强度口径 | 事件窗 | 衰减半衰期 |
|---|---|---|---|
| 财报（earnings） | **SUE**（标准化预期外盈余）或 `(actual-expected)/σ(history)` | `[-1,+1]` 即时、`[+2,+60]` 漂移 | 4-24h；漂移期按日线性衰减 |
| FOMC / 议息 | 政策利率 surprise（bp）+ 声明语调变化 | `[-24h,0]` 前漂移、`[0,+1d]` | 24-48h |
| 宏观数据（CPI/非农） | `(actual - consensus) / σ(历史 surprise)` | `[0,+2h]` | 24-48h |
| 监管/公司行动 | 规则分类打分（0-1） | `[0,+3d]` | 48-72h |

**纪律**：`consensus`（市场预期）必须来自可记录来源（如 FRED/官方日历/彭博中值存档），拿不到预期时该事件**只进 E 层描述，不进因子计算**——禁止用事后涨跌反推"预期"。

### 3.4 供 39 的接口（消除 G1 的关键）

39 的语义事件流新增**事件源类型**：

```
现有：source=trader.log  → term / timestamp / symbol / values / raw
新增：source=events.jsonl → 复用同一 5 字段 + 扩展 sentiment 块
```

**新增字段（向后兼容，缺省 null）**：

```json
{
  "term": "美联储降息预期升温",
  "timestamp": "2026-11-20T21:00:03Z",
  "symbol": "BTC",
  "values": ["0.62"],
  "raw": "...",
  "source": "events.jsonl",
  "sentiment": {"score": 0.62, "confidence": 0.81, "model": "finbert-tone-chinese", "half_life_h": 24},
  "event": {"type": "fomc", "surprise": 0.8, "surprise_unit": "z"}
}
```

**改造点（最小侵入）**：
- `39-金融语义蒸馏系统/scripts/gen_semantic_events.py` 增加 `--source events` 分支
- `SentimentEngine.analyze_text()` 输出直接嵌入 `sentiment` 块（已有 4 键接口不变）
- 39 的 `contradiction_events.jsonl` 矛盾检测因此可跨"内部交易日志"与"外部金融事件"两种源 → 直接支撑 SPEC §9.5 的"内外矛盾"能力（原设计缺数据）

---

## §4 S 层：金融语义情绪

### 4.1 「降级」的准确含义：架构归位，不是能力削弱

> 初稿用"FinBERT 降级为 39 的插件"表述**不准确**，容易误读为削弱 FinBERT。准确表述如下。

| 版本 | FinBERT 的架构位置 | S 层是什么 |
|---|---|---|
| **v0（现状）** | 独立情绪管线：自己吃快讯 → 自己打分 → 自己聚合 → 直接产出情绪因子 | S 层 ≡ FinBERT |
| **v1（本 SPEC）** | 打分原语（scoring primitive）：只在被调用时对给定文本返回 `score / confidence / model`，不采集、不聚合、不出因子 | S 层 = 39 语义归一 + FinBERT 打分 + 独立聚合器 |

**能力对比**：打分能力不变（同一个模型），但输入质量提升（39 提供实体链接、事件类型、板块归属、术语上下文）；输出的"自主权"下降（不再自己决定因子口径）。这是**职责收窄 + 上下文增强**，不是能力降级。

#### 判断：FinBERT 是否适合接入 39？——适合，但仅限一个位置

**结论：适合作为「39 事件标准化过程中的情绪属性写入器」，不适合作为 39 的模型基础设施，也不适合让 39 用情绪出因子。**

| # | 判据 | 结论 | 依据 |
|---|---|---|---|
| 1 | 语义互补性 | ✅ 强互补 | 39 有术语/实体/事件类型，缺"极性强度"；FinBERT 有极性，缺上下文。两者正交不重叠 |
| 2 | 边界合规性 | ✅ 不越界 | 39 SPEC §2.1 禁的是「模型训练」，FinBERT 是推理；§8.2 要求描述性输出，情绪打分属描述 |
| 3 | 输出契约 | ✅ 可直接嵌入 | `sentiment_engine.py` 已固定 4 键（`score/sentiment/categories/matches`），可无损映射为事件字段 |
| 4 | 失效一致性 | ✅ 同构 | FinBERT 3 层 FAIL-OPEN 与 39 的 FAIL-OPEN 纪律一致，模型缺失时降级为 `sentiment=null` |
| 5 | 生命周期归属 | ❌ **不适合进 39** | 模型加载 / 显存 / 批量调度 / 重试不应进入 39（39 是零 token 知识生产设施）→ 模型留在 9 域 |
| 6 | 决策权 | ❌ **不适合** | 39 不得用情绪出因子或信号（39 SPEC §8.2 描述边界）；聚合与因子归本 SPEC 的 J 层与 48 |

**落地形态（模型在 9，字段在 39，因子在 48）**：

```
9-基本面分析/engines/sentiment_engine.py          39-金融语义蒸馏系统/scripts/gen_semantic_events.py
   （模型生命周期 / 显存 / 重试 / FAIL-OPEN）  ──►   （只写 sentiment 字段，null 安全）
        score, confidence, model                        ↓
                                              semantic_events.jsonl（含 sentiment/event）
                                                        ↓
                                              48 J 层：三权重聚合 / 衰减 / 因子
```

**四条硬约束**：
1. `sentiment=null` 是**合法状态**（模型不可用/中文模型缺失时），**禁止**填 0 或 `neutral` 冒充已打分
2. 39 **不得** import `torch` / `transformers`；只能调用 9 的稳定函数或走 39 已有的 MCP 工具面
3. 每次打分必须记录 `model` 名与版本，跨模型（finbert-tone-chinese / ProsusAI/finbert / 规则引擎）结果必须可区分，禁止混算
4. **中文模型必须可配置 + 标签映射必须从模型配置读取 + 禁止静默降级**：云端中文模型为 `yiyanghkust/finbert-tone-chinese`（`bert-base-chinese`，输出 `LABEL_0/1/2`），但仓库硬编码 `valuesimplex/FinBERT2`（404）且中文路径无 env 覆盖，`FINBERT_ZH_LABEL_MAP` 又缺 `LABEL_*` → 中文每条都 `return None` 并静默回退规则引擎。**必须**：① 新增 `FINBERT_ZH_MODEL_PATH` / `FINBERT_ZH_MODEL_ID`（默认 `yiyanghkust/finbert-tone-chinese`）；② label 映射改为读 `model.config.id2label`，禁止硬编码猜测；③ 路由目标缺失时返回 `None` 并标 `model="unavailable"`，走规则引擎标 `model="rule_fallback"`，**不得伪装成 FinBERT**，也**不得跨语言 fallback**（英文 `ProsusAI/finbert` 实测中文 UNK 率 54%，不可用于中文）

**为什么值得接**：39 已有 1454 条术语表，能提供 FinBERT 单独拿不到的上下文（这条新闻说的是哪个板块、哪类事件、与哪些术语共现）；单独对快讯打分无法区分"某项目利好"与"美联储转鹰"在语义层级上的差异——而这正是 E 层（事件）与 S 层（情绪）交叉验证的前提。

**但必须承认（评审发现）**：现有 20927 条语义事件 **100% 来自 `trader.log`，零条新闻事件**。因此 P0-A 不是"接线复用"，而是**首次建立新闻语义事件通道**——39 的术语识别/矛盾检测逻辑可复用，但 `--source events` 分支与"新闻正文 → 术语 → 事件"的管道是全新代码。

### 4.2 情绪聚合三权重（对应调研结论）

```
sent_factor = Σ_i  w_attention(i) × w_novelty(i) × w_source(i) × exp(-Δt_i / τ) × score_i
              ─────────────────────────────────────────────────────────────────────
                                    Σ_i  w_attention(i) × w_novelty(i) × w_source(i)
```

| 权重 | 定义 | 数据来源 |
|---|---|---|
| `w_attention` | 事件关注度（新闻条数 + 关联标的相关新闻量 + 搜索/成交异常） | 18 采集计数 |
| `w_novelty` | 首报高、转载衰减（同 `event_id` 相似度聚类，重复转载权重 ×0.2） | 39 实体/术语指纹去重 |
| `w_source` | 来源历史可信度（该源情绪与后续真实市场反应的一致性，滚动 90 日） | 新建 `source_reliability.json` |
| `τ` | 半衰期：快讯 6h、深度文章 48h、政策事件 24h | 配置化 |

**纪律**：`w_source` 必须**滚动前视**（只用 t 之前的样本估计），否则引入前视偏差。

### 4.3 情绪反向的条件化（修正 P-3）

```python
# ❌ 旧假设（无条件反向）
finbert_contrarian = -sent_mean

# ✅ 新设计（条件化反向）
crowding = zscore(funding_rate)  or  percentile(fear_greed_enhanced.mvrv)
valuation = percentile(bdsm_valuation)
is_extreme = (percentile(sent_mean) > 0.85) or (percentile(sent_mean) < 0.15)

sent_signal = 0.0
if is_extreme and (crowding > 1.0 or valuation > 0.8):
    sent_signal = -sign(sent_mean) * abs(sent_mean)   # 反向生效
elif is_extreme and (crowding < -1.0 or valuation < 0.2):
    sent_signal = sign(sent_mean) * abs(sent_mean)    # 极端悲观 + 低拥挤 → 顺向（超跌修复）
```

**验证要求**：必须同时报告"无条件反向"与"条件化反向"两组的增量 IC，若条件化版本不能显著优于无条件版本，则回退到无条件并如实标注（禁止因为"理论上更对"就保留复杂版本——这是过拟合）。

### 4.4 S 层因子清单

| # | 因子 | 定义 | 预期 horizon |
|---|---|---|---|
| S1 | `sent_mean` | 三权重聚合净值 | 3-7d |
| S2 | `sent_dispersion` | 加权标准差（分歧度） | 3-10d |
| S3 | `sent_extreme_ratio` | `\|score\|>0.7` 条数 / 总条数 | 1-5d |
| S4 | `sent_delta` | `S1_t - S1_{t-1}` | 1-3d |
| S5 | `sent_attention` | 当日有效条数（对数） | 辅助 |
| S6 | `sent_asymmetry` | `(pos - neg) / total` | 3-7d |
| S7 | `sent_shock` | `\|S4\| / rolling_std(S4, 60)`（情绪冲击 z） | 1-3d |
| S8 | `sent_event_composite` | 深度文章 F1/F2/F3 组合因子（§8） | 5-20d |

---

## §5 M 层：市场情绪（恐慌指数 + VIX）

### 5.1 统一 RegimeSchema

```python
RegimeSchema = {
  "as_of": "2026-11-11",
  "crypto_fng": {"value": 32, "label": "fear", "percentile_1y": 0.28,
                 "delta_3d": -8, "sub": {"momentum": .., "capital_flow": .., "volatility": .., "funding": ..}},
  "vix": {"level": 18.4, "bucket": "normal", "percentile_1y": 0.61,
          "term_structure": "contango", "vix3m": 20.1, "slope": 0.092,
          "vvix": 92.3, "put_call": 0.87,
          "term_as_of": "2026-11-11"},   # 期限结构/二阶分量所属交易日
  "label": "risk_neutral",           # risk_on | risk_neutral | risk_off | crisis
  "confidence": 0.0-1.0
}
```

**`term_as_of` 语义**：`level` 取当日最新行；`vix3m` / `slope` / `vvix` / `put_call` 允许复用**最近一条 `vix` 与 `vix3m` 均非空的完整行**（通常是 T−1），此时 `term_as_of < as_of` 显式标注分量日期，禁止让 `slope` 因当日 Yahoo 补充行缺 VIX3M 而恒为 null。消费方必须按 `term_as_of` 判断新鲜度，不得假设等于 `as_of`。

### 5.2 VIX 三件套（补齐 G5）

| 组件 | 口径 | 用途 | 采集 |
|---|---|---|---|
| 水平分档 | `<15 低波 / 15-20 正常 / 20-30 偏高 / >30 危机`；叠加与 VIX 200 日均线比较 | 基础状态 | **主源 18 FRED `VIXCLS`（历史/回测）**；Yahoo `^VIX` 仅当日实时补充（见 §5.2.1） |
| 期限结构 | `VIX3M / VIX - 1`：正斜率（contango，常态平静）/ 负值（backwardation，近端恐慌） | **比单看 VIX 水平稳健的 regime 开关** | 新增 CBOE `VIX3M` 采集（18 主链） |
| 二阶确认 | VVIX（波动率的波动率）+ put/call ratio | 恐慌是否"真实" | CBOE 公开数据 / Yahoo |

**纪律（来自调研）**：VIX **无方向信息**，只能当 regime 判别器；阈值是行业惯例而非定律，必须用自身样本校准并预注册；2017/2020 均出现"低 VIX 突然失效"，因此 VIX 分档必须与 crypto F&G 交叉。F&G 极值**按方向区分**（不是任一极端都算危机）：

| F&G | 含义 | 标签 |
|---|---|---|
| `< 25` | 极度恐惧：已经恐慌定价，风险释放中 | `crisis` |
| `25 – 75` | 不改变 VIX 给出的标签 | 沿用 VIX 判定 |
| `> 75` | 极度贪婪：拥挤/回撤风险，不是危机 | `risk_off` |


#### 5.2.1 VIX 迁入口径（关闭 P1-1）

现状（2026-11-11 复查，修正首版判断）：VIX **已有两条链路**，但口径不同——
- 18 [`panewslab_collector.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/18-数据获取中心/data_center/collectors/chain/panewslab_collector.py#L68) 的 `macro_us` 桶采 **FRED `VIXCLS`**（日频，T+1，适合回测）
- [`market_data.py:175`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/9-基本面分析/ops/nanoclaw/core_task1/scripts/market_data.py#L175-L196) 采 **Yahoo `^VIX`**（实时，适合盘面）

**处置：定主源 + 提取提升，不重写。**

1. **主源 = FRED `VIXCLS`**（可回填、point-in-time 明确）；Yahoo `^VIX` 降级为"当日实时补充"，落库必须带 `source` 字段区分
2. 把 `market_data.py` 的解析函数整体迁到 `18-数据获取中心/data_center/collectors/chain/vix_collector.py`，签名与容错逻辑保持不变；nanoclaw 改为 import，**删除本地副本**
3. 新增 `VIX3M`（CBOE）与 `VVIX` / put-call，并入同一 collector
4. 落库字段一次定稿：`vix` / `vix3m` / `vix_ratio`（**= `VIX/VIX3M`，<1=contango**，仅作原始比价；方向量用 `RegimeSchema.slope = VIX3M/VIX-1`，下游禁止直接用 ratio 做阈值）/ `vvix` / `put_call_ratio` / `as_of` / `source`；`RegimeSchema` 另带 `term_as_of` 标注期限结构分量实际所属交易日（允许复用 T−1 完整行）
5. 验收：全仓 `grep -rn "def .*vix"` **只允许 1 处实现**；FRED 与 Yahoo 同日差值 > 0.5 时告警且以 FRED 为准

> 理由：G10 已经证明"同一指标多套口径"会让所有下游不可比（40 域 Binance/yfinance/OKX 三源）。VIX 不得重犯。

**✅ 落地（2026-11-11，P1-B）**：

- **唯一实现**：`18-数据获取中心/data_center/collectors/chain/vix_collector.py`（`fetch_vix` 由 `market_data.py` 原样迁移；nanoclaw 改为 import；11 `MacroFeed` 的 yfinance 第三副本改为转调；11 `coin_fundamental_metal._fetch_vix` 更名为 `_read_stored_price` 仅作 DB 读取）
- **历史序列**：FRED `VIXCLS`（主源）+ CBOE `VIX3M_History.csv` / `VVIX_History.csv`（期限结构/二阶）；put/call ratio 实测无稳定公开 CSV → 按 null 纪律留空，**不填 0**
- **网络约束（实测）**：FRED 边缘对 python-requests 的 TLS 指纹直接断连（HTTP/1.1 与 httpx h2 均失败），实现内置 `curl` 回退，避免主源被静默降级为 Yahoo；CBOE/FRED 连续请求会间歇断连 → 3 次指数退避重试
- **RegimeSchema**：`48-涌现架构/metrics/regime.py`（分档 `<15/15-20/20-30/>30`、`percentile_1y`、期限结构、F&G 极值交叉、confidence=可得分量权重和、`gap_report` 30 天连续性）
- **T−1 完整行复用**：当日行来自 Yahoo 时没有 `VIX3M`，若直接取末行会让 `slope`/`term_structure` 恒为 null。实现改为取**最近一条 `vix3m` 非空的行**计算期限结构与二阶分量，`vix.level` 仍取当日最新行，并在 schema 写入 `term_as_of` 标注分量日期；`confidence` 的 `term`/`vvix` 可用性同样以该行判定
- **F&G 极值方向区分**：`<25 → crisis`（极度恐惧，风险已释放），`>75 → risk_off`（极度贪婪，拥挤/回撤风险），`25–75` 不影响 VIX 判定（原「任一极端即 crisis」已废弃）
- **口径修正（M5，正文级）**：§5.3 原式 `VIX/VIX3M - 1` 与 §5.1 示例（`18.4/20.1 → +0.092`）及 §5.2「正斜率=contango」相反，**已直接把 §5.3 M5 公式改为 `VIX3M/VIX - 1`**。落库 `vix_ratio = VIX/VIX3M`（<1=contango，仅作原始比价）；`RegimeSchema.slope` 为唯一方向量，P2/48 判据禁止用 ratio 做阈值。`|slope| < 0.005` 判 flat（避免浮点精确 0 导致 flat 永不触发）
- **验收实测**：30 天窗口 `observed=22`、`gaps=[]`、`ok=true`；全仓生产代码 `def .*vix` 命中 **1 处**（`tests/chain/test_vix_collector.py` 静态断言守护）

### 5.3 M 层因子清单

| # | 因子 | 定义 |
|---|---|---|
| M1 | `fng_norm` | F&G 归一化（0-1） |
| M2 | `fng_delta_3d` | F&G 3 日变化 |
| M3 | `fng_extreme_days` | 处于极值区（<25 或 >75）的连续天数 |
| M4 | `vix_bucket_code` | VIX 分档编码（0-3） |
| M5 | `vix_term_slope` | `VIX3M/VIX - 1`（正=contango，负=backwardation；原式 `VIX/VIX3M - 1` 方向相反，已修正） |
| M6 | `vix_shock_z` | VIX 相对 60 日均值的 z 值 |
| M7 | `regime_label` | 综合标签（risk_on/neutral/off/crisis） |

---

## §6 P 层：市场形态

### 6.1 已有能力（复用 21 FeatureHub）

SMA 10/20/50、EMA 12、RSI14、MACD、BOLL(20,2)、ATR14、ADX14、OBV、Williams %R —— 全部在 `feature_hub/modules/classic_indicators.py`，**不重写**。例外：`leader_form.py` 的 `rsi14/macd_*` 按 Wilder/EMA12-26-9 口径**独立实现**（classic 的 RSI 用简单均值、MACD 无柱状图），两者口径不同，禁止混用。

### 6.2 新增指标（补齐 G6；v2.8 由 29 → 33 列）

**文件**：`21-特征工程中心/feature_hub/modules/leader_form.py`（新建，注册进 FeatureHub）

| 组 | 指标 | 定义 | 定位 |
|---|---|---|---|
| 多均线栈 | `ma_5 / ma_13 / ma_65 / ma_128 / ma_200` | 各周期 SMA | 描述 |
| 均线排列 | `ma_stack_perfect_bull / perfect_bear / compressed / mixed` | 四态 **one-hot**（相邻均线距离 <1% → compressed；预热期全 NaN）；不用字符串列，否则清洗链数值化失败会把整个集合降级为 raw | 状态 |
| 均线距离 | `ma_dist_pct[i]` | `(close - ma_i)/ma_i` 各周期 | 特征 |
| 趋势开关 | `above_ma200` | 布尔（调研唯一认为相对稳健的长期趋势开关） | 开关 |
| 枢轴点 | `pivot_p, r1, r2, s1, s2` | 标准公式 `P=(H+L+C)/3`, `R1=2P-L`, `S1=2P-H`, `R2=P+(H-L)`, `S2=P-(H-L)`；H/L/C 取**前一根 bar**（当日盘中可得，避免同日收盘前视） | **仅作共识参考位** |
| 枢轴距离 | `dist_to_pivot / dist_to_r1 / dist_to_s1` | 归一化距离 | 辅助 |
| 量能 | `vol_ratio_5_20` | 5 日均量 / 20 日均量 | 特征 |
| OBV | `obv_slope_20` | OBV 20 日线性回归斜率 | 特征 |
| OBV 背离 | `obv_divergence` | 滚动 60 日窗口：`-1` = 价格创新高但 OBV 未创新高（顶背离），`+1` = 价格创新低但 OBV 未创新低（底背离），`0` = 无/预热期 | **仅辅助确认** |
| RSI14 | `rsi14` | **Wilder 平滑**（`ewm(alpha=1/14)`，非 classic 的简单均值口径）；单边上涨 100 / 单边下跌 0 / 完全横盘 50；预热 14 根 NaN | 状态 |
| MACD | `macd_dif / macd_dea / macd_hist` | `DIF=EMA12-EMA26`、`DEA=EMA9(DIF)`、`hist=2*(DIF-DEA)`（A 股惯例；z-score 后与 `DIF-DEA` 等价）；DIF 预热 26 根、DEA 至 34 根 | 状态 + 动量 |
| 布林状态 | `boll_pctb`, `boll_bandwidth`, `boll_squeeze` | `%B`、带宽、挤压（带宽处 20 日低位） | 状态 |

> **P 层接入**：`financial_env_align._form_long()` 对 form 数值列统一加 `P_` 前缀，`layer_scores_from()` 取全部 `P_*` 截面 z 均值 → 新增 4 列**自动进入 `P_score`**，无需改验证器。

### 6.3 形态层自律（来自调研的批判性结论，强制写进代码注释）

1. **5/13/65/128 参数组合没有普适最优**，属参数拟合；本 SPEC 使用它们只因为业务方指定，**结论必须标注"参数敏感性未验证"**
2. **Pivot Point 无学术预测力证据**，只能当"共识参考位"，禁止单独触发交易
3. **OBV 背离证据混合**，只能作辅助确认
4. 形态层任何因子进入决策前，必须过 §7.5 的四道统计关；若增量 IC 不显著 → 如实标记 `falsified`，**不得因为"业务方要求"而保留为信号**

---

## §7 J 层：三维联合验证框架（本 SPEC 核心）

### 7.1 对齐器

**文件**：`48-涌现架构/metrics/financial_env_align.py`（新建）

```python
align(events, sentiment, regime, form, horizon) -> DataFrame
# 索引： (symbol, date)
# 列   ： E_* / S_* / M_* / P_* + forward_ret_{1,3,5,10,20}d + label
```

**对齐纪律**：
- 事件按 `available_at` 落到**第一个可交易时点**（crypto 24/7 → 下一小时；美股 → 下一交易日开盘；A 股 → 下一交易日开盘）
- 所有特征在 `date` 收盘后可得，标签从 `date+1` 开始 —— 严禁同日特征预测同日收益
- 事件窗口内（如财报 `[-1,+1]`）的样本单独标记 `in_event_window=True`，回测时可选剔除（防止事件窗内噪声污染基础因子评估）

**落地（P2-A，2026-11-12）**：`48/metrics/financial_env_align.py`
- `next_tradable_date(available_at, asset_class)`：crypto 取 `floor("h")+1h` 的日期；股票先 `date+1` 再跳过周末（保守，不假设盘中可成交）
- `_split_market` / `_fill_from_market`：**市场级行（`symbol=""`）按 `date` 广播**到全宇宙（FOMC/CPI/大盘形态对所有标的成立），但只补 NaN，不覆盖品种自身同层信号
- `feat_as_of` 取各层可得时刻最大值（S 用 `available_at`，M/P 日频按当日 23:59），`audit_lookahead()` 是硬门禁，结果写入 `df.attrs["lookahead_violations"]`
- `label` 取主评估期收益符号（`horizon` 为列表时取第一个），`forward_ret_{1,3,5,10,20}d` 始终全量输出
- 无价格数据时不伪造收益：`forward_ret_*` 与 `label` 全 NaN，由 §7.2 判定 `insufficient_data`

### 7.2 联合验证的四个问题（分层回答）

| 层 | 问题 | 方法 | 输出 |
|---|---|---|---|
| **L-A 单层** | 每层单独有没有信息？ | 正交化后的 Spearman IC / ICIR | 各因子 IC 表 |
| **L-B 交叉** | E×S、E×M、S×P 两两交叉是否优于单层？ | 交互项 + 分组 IC（事件有/无 × 情绪高/低） | 交叉 IC 矩阵 |
| **L-C 三方** | E+S+M 三路叠加的增量是否 > 任意两路？ | 逐步加入的增量 IC（Δ IC 及 bootstrap CI） | 三路消融表 |
| **L-D 状态** | 是否只在特定 regime 下有效？ | 按 `regime_label` / VIX 分位 / F&G 极值分桶，报**分状态 IC** | 状态依赖矩阵 |

**关键要求（来自 AI 工程调研）**：
- 增量 IC **必须是正交化后的**：新因子先对"已有量价因子 + 已有层因子"做截面回归取残差，再算残差 IC。原始 IC 暴涨通常只是重复计价了量价信息
- 单变量消融：一次只加一层，固定随机种子重复 ≥5 次，报 `mean ± std`
- 门控融合（gated fusion）作为上限对照，late fusion 作为可解释基线，**两套都跑**，若门控不显著优于 late fusion → 用 late fusion（简单优先）

**落地（P2-B，2026-11-12）**：`48/metrics/financial_env_validate.py` → `runtime/financial_env_report.json`
- **IC 口径**：逐日截面 Spearman IC（横截面 <3 个标的的日期丢弃），`ICIR=mean/std`，`t=ICIR·√n_dates`；`n_obs` 用非空配对数喂门禁
- **市场级因子的时序口径（v2.6 补）**：M 层（VIX 档位）对全宇宙同值，截面 IC 无定义 → 退化为**时序 IC**（按日取因子与收益的截面均值，对日期序列求 Spearman，`t=IC·√((n-2)/(1-IC²))`，`n_dates≥30`）；报告用 `mode=cross_section|time_series` 标注口径
- **L-A**：`E_score/S_score/M_score/P_score` + `ALL_layers` 合成因子；`M_score=-VIX 档位/3`（VIX 越高越 risk-off）；`P_score` 为形态数值列截面 z 均值
- **L-B**：`E×S`、`E×M`、`S×P` 交互项 IC + `event/no_event` 分组 IC
- **L-C**：按 `E → S → M → P` 逐步加入，**每步对已加入层做截面回归取残差**再算增量 IC；CI 用按日 block bootstrap（默认 200 轮，固定 seed=7）
- **L-D**：按 `M_label` / VIX 档 / F&G 极值（`<25` / `>75` / 中段）分桶 IC；**描述性统计，不记 trial**
- **门禁接线**：`verdict` 只能来自 `assert_gate()` / `write_verdict()`；未预注册 → 不记 trial、不写 verdict，如实返回 `insufficient_data / not_preregistered`；样本量 `<MIN_N_OBS` 或前视违规 → 只读判定，不污染 `trials.jsonl`
- **诚实降级**：无价格（`forward_ret` 全 NaN）→ `data_status=insufficient_data`、`reason=no_forward_returns`、`L_A={}`；前视违规 → 整体 `falsified`
- **CLI**：`--prices/--klines-dir/--events/--sentiment/--form/--regime-dir/--prereg`，可选 `--dsr/--pbo`（由 45 系统算好后注入）；无任何价格输入时如实产出 `insufficient_data`
- **S 层默认来源（v2.8）**：未显式给 `--sentiment` 时自动调 `load_semantic_sentiment()` 读 39 `semantic_events.jsonl`（`--semantic-events [PATH]` 可覆盖；`nargs="?"` 缺省即默认路径），同日同标的取 mean score + 最晚 `available_at`；`price_source.sentiment` 标注 `39_semantic_events|cli|none`

**真实数据首跑（v2.6，2026-11-12）**：
- 价格：`--klines-dir` 读 11 域 kline 缓存（BTC `1D` 2100 日 / ETH·SOL `1H→1D` 256 日 / AVAX·LINK 89 日），`price_source` 块记录来源与区间；**这是验证级输入，不是 40 域统一价格源（G10 仍未关闭）**
- M 层：`regime.py --write-history` 回写 285 日 `runtime/regime/*.json`（FRED `VIXCLS` + CBOE `VIX3M`/`VVIX`）
- P 层：由同一份日线经 21 域 `leader_form.compute` 派生（复用 P1-C，不另写一套）
- 结果：`data_status=ok`、`lookahead_violations=0`、`n_obs=2790`；`M_score` 时序 IC=`-0.042`(t=-0.62)、`P_score` 截面 IC=`0.048`(t=1.14)、`ALL_layers` 与 `P_score` 同序（E≈0、M 为日频常量）；全部 `inconclusive`（`|t|≤3`）
- 仍未闭合（v2.8 后更新）：S 层**适配器已通**（39 事件流实测 68 个「标的×日期」，2026-10-13→11-11），但历史序列仍短，需云端回填；E 层仅 302 条事件（多数日期无事件 → 无截面变异）；`crypto_fng` 已接入 `RegimeSchema`（36 个有效日，陈旧 >3 天即 null），全历史覆盖仍待云端

### 7.3 组合因子（涌现候选）

只在 L-C/L-D 双通过后构造，且**预注册**（写入 `48-涌现架构/configs/factor_preregistration.json`，事后不得修改）：

| 组合因子 | 公式 | 预注册假设 |
|---|---|---|
| `CF1_event_sent_align` | `sign(E.direction) × S1`（事件与情绪同向时放大） | 事件-情绪共振比单一信号更强 |
| `CF2_event_form_confirm` | `E.surprise × P.ma_stack_state`（事件 + 形态确认） | 形态只作确认，不独立 |
| `CF3_regime_gated_sent` | `S1 × 1[M.regime_label == risk_off]` | 情绪反向仅在 risk_off 生效 |
| `CF4_three_way` | `E.surprise × S1 × 1[VIX bucket ≥ 2]` | 三维共振仅在高波动期 |

**涌现判据接线**：CF1-CF4 若通过验证，作为 48 判据 **E3（非线性耦合）** 的新证据源写入 `48/metrics/emergence_metrics.py`；不通过则写入 `falsified` 记录（同样是有效产出）。

**落地（v2.6，2026-11-12）**：`configs/factor_preregistration.json` 已建立（`financial-env-prereg-v1`），内容为 §7.2 已声明的 **L-A 五个单层/合成假设**（`E_score/S_score/M_score/P_score/ALL_layers`）+ **L-B 三个交叉假设**（`E_scorexS_score/E_scorexM_score/S_scorexP_score`），每条含 `hypothesis / expected_sign / rationale`；文件内显式声明「注册时尚未在真实价格数据上运行过任何联合验证」。
- CF1-CF4 **未预注册**：按本节纪律，须等 L-C/L-D 双通过后再追加，当前一律不过门禁（`not_preregistered`）
- 预注册只追加不修改；`register_factor()`（E-1）会在每次评估前校验条目存在

### 7.4 （保留）五层评估沿用

沿用 [SPEC-EMERGENCE-FINBERT-SENTIMENT-FACTOR-EVAL-v1.0.md](./SPEC-EMERGENCE-FINBERT-SENTIMENT-FACTOR-EVAL-v1.0.md) §2 的五层框架（IC → 分层 → 消融 → 状态依赖 → 衰减），本 SPEC 在其上增加**正交化**与**统计纪律**两层。

### 7.5 统计纪律（G9，硬门禁）

**实现位置（存量复用，不新建统计函数）**：直接接线 [45-评测系统/evaluators/common/split.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/45-评测系统/evaluators/common/split.py) 的 `purged_kfold` / `walk_forward` / `embargo_length` / `verify_no_leakage`，与 [45-评测系统/evaluators/finance/backtest.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/45-评测系统/evaluators/finance/backtest.py) 的 `deflated_sharpe_ratio` / `pbo_cscv` / `probabilistic_sharpe_ratio` / `expected_max_sharpe`。本 SPEC 只新增 `trials.jsonl` 记账层与 `assert_gate()` 强制包装，**不重写任何统计函数**（评审维度 4 结论）。

| 关卡 | 要求 | 不通过后果 |
|---|---|---|
| 试验记账 | 每次参数/信号尝试写入 `trials.jsonl`（累计 N） | 无法报 DSR/PBO |
| t 值门槛 | 单因子 `t > 3.0`（Harvey-Liu-Zhu） | 标记 `not_significant` |
| DSR | Deflated Sharpe Ratio（Bailey & López de Prado） | 标记 `overfit_risk` |
| PBO | 组合对称交叉验证估计回测过拟合概率，`PBO < 0.5` | 标记 `overfit` |
| 嵌套 CV | 特征选择/标准化/超参**全部在训练折内**；purged + embargo（≥ horizon 长度） | 禁止出结论 |
| 样本外冷却 | 最近 20-30% 时间段在最终验收前**完全不可见** | 禁止出结论 |
| 前视审计 | 所有特征 `available_at ≤ date` 校验 | 数据作废 |

**verdict 五态**（与 48 现有 dashboard 对齐，新增 `insufficient_data`）：`candidate` / `candidate_weak` / `inconclusive` / `falsified` / `insufficient_data`

### 7.6 门禁强制点设计（关闭 P0-4）

**问题**：§7.5 六道关若只写在文档里，任何脚本都能绕过后直接落一个 `verdict`。必须做成**唯一入口 + 参数级强制 + 可审计绕过**。

#### 7.6.1 唯一入口

**文件**：`48-涌现架构/registry/factor_gate.py`（新建，唯一允许产出 factor verdict 的模块）

> 与同目录既有 [`accumulation_gate.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/48-涌现架构/registry/accumulation_gate.py) 职责不同：后者校验 E1/E4b 的**证据积累量**（`check_e1` / `check_e4b`），不做统计显著性判定；两者不得互相调用，也不得合并。

```python
def assert_gate(
    factor_id: str,           # 如 "M2_fng_delta_3d"
    horizon: int,             # 1/3/5/10/20
    ic: float, t_stat: float, n_obs: int,
    dsr: float | None = None,
    pbo: float | None = None,
    leakage_ok: bool = True,
    allow_without_trials: bool = False,   # 默认 False（参数级强制）
) -> dict:
    """返回 {"verdict": <五态>, "reasons": [...], "gate_version": "v1"}。
    所有因子结论必须经此函数产出，禁止手写 verdict。"""
```

#### 7.6.2 判定顺序（短路，先严格后宽松）

| 顺序 | 条件 | verdict | reasons 示例 |
|---|---|---|---|
| 1 | `leakage_ok is False` | `falsified` | `lookahead_detected`（数据作废，不得重试掩盖） |
| 2 | `allow_without_trials is False` 且 `trials.jsonl` 中无该 `factor_id` 记录 | `insufficient_data` | `not_preregistered` |
| 3 | `n_obs < 250` | `insufficient_data` | `n_obs=36<250` |
| 4 | `|t_stat| <= 3.0` | `inconclusive` | `t=2.5<=3.0` |
| 5 | `pbo >= 0.5` | `falsified` | `pbo=0.62` |
| 6 | `dsr <= 0` | `falsified` | `dsr=-0.11` |
| 7 | `|t_stat| > 3.0` 且 `dsr > 0` 且 `pbo < 0.5` | `candidate`（`|ic|<0.02` 则 `candidate_weak`） | `pass_all` |

#### 7.6.3 试验记账 `trials.jsonl`

**文件**：`48-涌现架构/runtime/trials.jsonl`（append-only）

```json
{"trial_id":"T-20261111-0007","factor_id":"M2_fng_delta_3d","horizon":3,
 "params":{},"n_obs":36,"ic":-0.4826,"t_stat":2.52,"p_value":0.013,
 "script":"11-易经推理系统/scripts/memory_l4/fear_greed_ablation_eval.py",
 "git_sha":"68ef939d8d","ran_at":"2026-11-11T10:00:00Z","n_trials_so_far":7}
```

**纪律**：每跑一次评估脚本（含调参）必须记 1 条；`n_trials_so_far` 是 DSR/PBO 的输入；**漏记 = 该因子不得申报 candidate**。

#### 7.6.4 四个强制点（缺一不可）

| # | 强制点 | 实现 | 防什么 |
|---|---|---|---|
| E-1 | 因子注册 | `registry/factor_gate.py::register_factor()` 校验预注册文件存在 | 事后改假设（HARKing） |
| E-2 | verdict 落盘 | `write_verdict()` 内部必调 `assert_gate()`，外部模块无写权限 | 手写 verdict 绕过 |
| E-3 | 仪表盘只读 | `metrics/verdict_dashboard.py` 只聚合，不计算 | 二次口径 |
| E-4 | CI 静态检查 | `tests/test_no_direct_verdict_write.py`：grep 非 gate 模块中出现 `"verdict":` 字面量即 fail | 新脚本绕过 |

#### 7.6.5 可审计绕过

任何 `allow_without_trials=True` 调用必须同时写 `runtime/gate_bypass_log.jsonl`（含调用者、理由、`git_sha`）。绕过记录在仪表盘单独计数，**`bypass_count > 0` 的实验不得申报 E1-E5**。

### 7.7 可观测性契约（关闭 P1-2）

**目标**：任取一条 verdict，都能反查到"哪条事件 → 哪个模型 → 哪个因子 → 哪次试验"。

**唯一 join key**：`trace_id`（= `EventRecord.event_id`），全链透传，**不新建第二套 id**。

| 环节 | 必写字段 | 落盘位置 |
|---|---|---|
| E 采集 | `event_id` / `available_at` / `source` / `quality` | 18 collector → `data_center.db` 或 `39/semantic_events.jsonl` |
| S 打分 | `event_id` / `model` / `score` / `confidence` | 39 事件 `sentiment` 字段（`model` 取自 `analyze_text(with_meta=True)`） |
| M/P 聚合 | `trace_id` / `regime` / `form_snapshot_id` | 48 `runtime/dim_signals/<date>.jsonl` |
| J 因子 | `factor_id` / `trace_ids[]` / `trial_id` | 48 `runtime/factor_values/<date>.jsonl` |
| verdict | `factor_id` / `trial_id` / `reasons` / `gate_version` | `registry/factor_gate.py` → `metrics/verdict_dashboard.json` |

**三条硬约束**：
1. 缺 `trace_id` 的记录不得进入因子计算；单批缺失率 > 5% 即判 `quality=C`
2. `model` 落库前必须归一化到四个值：`finbert-tone-chinese` / `ProsusAI/finbert` / `rule_fallback` / `unavailable`。注意 `SentimentEngine._last_model` 当前返回完整 model id 或本地路径（如 `yiyanghkust/finbert-tone-chinese`、`models/finbert-zh`），**归一化在 P0-A 落库层完成，不改引擎返回**
3. verdict 的 `reasons` 必须能定位到具体 `trial_id`，否则一律 `inconclusive`

**验收**：任取一条 verdict，在不改代码的前提下用 3 次 grep 追到原始新闻 URL。

---

## §8 深度文章三层抽象扩展（G8）

### 8.1 现状

`factor_extractor.py` 已实现 F1 因素识别 / F2 方向与合成 / F3 主导主张。P1-A 之前：输入只有 Odaily 文章（`backfill/odaily_p0/contents.jsonl`）；
P1-D（2026-11-12）之后：输入改为 `events.jsonl` + `bodies.jsonl`（含新浪/华尔街见闻/财联社/金十正文），`factor_prior.json` 已产出 `factor-prior-v2` 且 `degraded=false`（快讯先验仍按其双证结论保持关闭，单独记为 `newsflash` 块）。

### 8.2 扩展源（G3）

| 源 | 采集器 | 文章类型 | 三层抽象适配 |
|---|---|---|---|
| 新浪财经 | `sina_finance_collector.py` | 快讯 + 深度 | ✅ 直接复用 F1/F2/F3 |
| 华尔街见闻 | `wallstreetcn_collector.py` | **深度为主**（宏观解读/行业研究） | ✅ 最有价值（F3 主导主张质量最高） |
| 财联社 | `cls_telegraph_collector.py` | 电报快讯 | ✅ F1 为主 |
| 金十 | `jin10_collector.py` | 宏观快讯 + 日历 | ✅ 事件型为主 |

### 8.3 组合因子产出（打通 G8）

```
F1 因素集 → F2 方向+权重 → F3 主导主张
                ↓
     组合因子 = {dominant_factor, direction, horizon, urgency, impact,
                 composite_score, source_mix, article_count}
                ↓
     factor_prior.json（去 degraded）→ 48 训练样本 → 40 先验
```

**新增要求**：
- `factor_prior.json` 必须带 `n_articles` / `n_sources` / `degraded_reason`
- 组合因子必须**按源分层**报告（crypto 源 vs 传统金融源），验证"传统金融深度文章是否提供增量"
- 若某源持续 `n<30` → 标记"弱证据"，不进正式结论（沿用 39 SPEC §7.4）

**落地（P1-D，2026-11-12）**——`18/data_center/processing/deep_factor_prior.py`：

| 项 | 实现 |
|---|---|
| 输入 | `events.jsonl` + `bodies.jsonl`，按 `body_ref = "bodies.jsonl#<id>"` 关联，跳过 `fetch_ok=false`/空正文 |
| 抽取 | `extract_dominance_claim()`（F3）；无 `dominant_factor` 的文章只计入 `n_articles`，不产生 claim |
| 聚合键 | `(dominant_factor, horizon)`；**不按 direction 分组**（先分组会让 `composite_score` 恒为 ±1，失去多空一致度） |
| `composite_score` | `Σ w·sign(direction) / Σ w`，`w = confidence_in_text × impact`，∈[-1,1]；`|score|≤0.15` 归 `neutral` |
| 分层 | `by_source` 三档 `traditional_finance` / `crypto` / `other`，每档带 `n_articles`/`n_sources`/`n_factors`/`weak_evidence`/`sources` |
| 弱证据 | 阈值按**该源已取到正文的文章数**判定（不是 claim 数），`<30` 列入 `weak_evidence_sources` 且不进顶层 `factors` |
| 快讯先验 | 保留 `newsflash` 块如实标注 `newsflash_prior_disabled_by_default`（关闭 ≠ 数据缺失，不因本阶段翻案） |
| FAIL-OPEN | 无事件/无 claim/异常 → `degraded=true` + `degraded_reason`，不抛、不阻断主链 |

**实测（2026-11-12）**：`n_articles=228`、`n_sources=4`、`n_factors=10`、`weak=[jin10]`、`degraded=false`；6 条单测 + 18 新闻套件 296 passed。

---

## §9 9 域统计历史上下文（提供 context）

> **状态（v2.8）**：本节为**待实现设计**，用户已裁决「需单独开 SPEC」，**不在本 SPEC 本轮实现范围**。下文字段定义保留作为新 SPEC 的输入契约；落地前不得声称已具备历史上下文能力。

用户明确要求"9 进一步提供统计上各维历史，提供上下文"。当前 `DimensionContext` 只有单点快照（`direction/strength/z/percentile/data_points`），缺历史叙事。

**扩展字段（向后兼容）**：

```python
DimensionContext += {
  "history": {
     "lookback_days": 250,
     "pct_rank_1y": 0.0-1.0,
     "pct_rank_3y": 0.0-1.0,
     "extreme_days": 0,          # 当前处于历史极值区的连续天数
     "mean_revert_z": 0.0,       # 距 1 年均值的 z
     "trend_20d": 0.0,           # 维度值 20 日斜率
     "regime_switch_30d": 0      # 30 日内方向翻转次数
  }
}
```

**用途**：给 FinBERT 情绪因子提供**历史基准**——同样 `sent_mean=0.4`，在历史 95 分位与 50 分位含义完全不同（这直接决定 §4.3 的条件化反向是否触发）。

**实现位置**：`18-数据获取中心/data_center/processing/dimension_context.py`（定义源仍是 9，按 FULL-CHAIN §4.1 契约边界）

---

## §10 缺口与实施计划

### 10.0 数据前置：P0-E 回填与质量门禁

**为什么单列**：§7.5 的判定阈值（t>3 / DSR / PBO）全部以样本量为基础。回填前 S 层有效日级因子 **13 天**、F&G **36 天**，任何结论都必然是 `insufficient_data`。回填不是优化项，而是 v1 的**准入条件**。F&G 已于 2026-11-11 回填至 3202 天（D1 ✅），S 层日级因子仍待 P0-A。

| # | 对象 | 现状 | 动作 | 验收 |
|---|---|---|---|---|
| D1 | crypto F&G 总指标 | ✅ **已回填 3202 天**（`2018-02-01→2026-11-11`，PG），近 3 年覆盖 99.91%，最长缺口 4 天（2018-04-17 源站缺口） | `18-数据获取中心/backfill/backfill_fear_greed.py`（`limit=0`，逐日 1 行，幂等可重跑） | ✅ 3202≥2500；缺口按质量门禁表「≤5 交易日」判定通过（原行内「≤2 天」与门禁表口径冲突，**以门禁表为准**） |
| D2 | F&G 四子维度 | 30 天 | 同步回填 momentum / capital_flow / volatility / funding | ≥700 天（该源上线较晚） |
| D3 | Odaily 正文 | **实测修正**：3048 条中仅 **195 条**缺 `description`（6.4%）；原「2096 条」为按 `metrics` 而非 `raw` 计数的错判。另：3048/3048 **未存 `url` 字段** | 补 `url` 落库（`https://www.odaily.news/newsflash/{id}`）；195 条按 id 重抓，源站已删标 `unrecoverable` | 可恢复率 ≥80%（当前 93.6% 已有正文，**已达标**） |
| D4 | 传统金融事件 | ✅ **74 条**（30 天：sec_edgar 69 / macro_calendar 4 / fed_calendar 1，PG 无关，落 `events.jsonl`） | P0-C 采集器落地（`collectors/tradefin/` 三官方源） | ✅ `available_at` 完整率 100%、前视违规 0（见 §10.1 P0-C） |
| D5 | 40 龙头 K 线 | ✅ 后端口径已统一：18 `get_sink()` / 40 `scripts/db_access.py` 默认均为 `postgres`；11 F&G 消融脚本已改为跟随同一后端（2026-11-11）。40 产出 `generated_at=2026-11-10` | 校验 10 大类各 ≥1 资产有完整 MA200（起点 ≥2025-01） | 10 大类各 ≥1 资产有完整 MA200 |

**质量门禁（回填后必须全过，否则不得进入 §7 评估）**：

| 关卡 | 阈值 | 不通过处置 |
|---|---|---|
| 覆盖率 | 近 3 年交易日覆盖 ≥95% | 该因子标 `insufficient_data` |
| 缺失连续性 | 最长连续缺口 ≤5 交易日 | 缺口段禁用，**不得前向填充** |
| point-in-time | 每条 `available_at` 早于对应因子计算时点 | 违规即 `falsified`（前视污染） |
| 源一致性 | 同一指标仅 1 个主源（或主源 + 显式 fallback） | 多口径并存即阻塞（G10 教训） |
| 可复现 | 回填脚本记录 `git_sha` + 原始响应哈希 | 不可复现的批次作废 |

**执行顺序**：D1/D3/D5 与 P0-D 并行；D2/D4 跟随 P0-C。**D 的验收报告必须先于任何 factor verdict 产出。**

### 10.1 阶段划分（P0-P3）

> **实施顺序（用户 2026-11-11 裁决：P0-D 先行；评审后调整为 D∥E 并行；P0-F 已完成）**：
> **P0-F ✅（中文模型接线）→ P0-D 统计纪律 ∥ P0-E 数据回填 → P0-A 语义打通 → P0-B 龙头宇宙 → P0-C 事件采集 ✅ → P1-* → P2 → P3**
> **截至 2026-11-11：P0 六个阶段全部落地（A/B/C/D/F ✅，E 部分完成）→ 进入 P1-A 中文财经源。**
> 先做 D 的理由：它会改变已有结论的判定口径（现有 F&G 的 p=0.013 在 t>3/DSR 下预期降级为"不显著"），必须先立标准再进数据，否则后面所有因子评估都要返工。
> 但 D 的验收（重判 F&G）**依赖 ≥250 天样本**，而当前 F&G 仅 36 天、S 层日级因子仅 13 天 → **E 必须与 D 并行**，否则 D 做完也无法验收（评审 P0-2）。

| 阶段 | 内容 | 交付物 | 验收标准 |
|---|---|---|---|
| **P0-A 语义打通** ✅ | 39 增加 `sentiment`/`event`/`trace_id` 字段 + `--source events` 分支；9 域 FinBERT 作为打分服务被调用（不迁入 39），`with_meta` 增加 `confidence` | `39/scripts/gen_semantic_events.py`（`emit_from_events` 按 `trace_id` 幂等）+ `39/tests/test_events_source.py`（6 条）| ✅ **2026-11-11 E2E 通过**：CPI 事件 → `score=-0.9986, confidence=0.9986, model=finbert-tone-chinese`（§7.7 四值归一化）；`sentiment=null` 与旧行不改写均有单测 |
| **P0-B 龙头宇宙** ✅ | `leader_universe.json` 只存信号覆盖，成员/instId 运行时从 40 投影（不复制）+ 月度复核脚本 | `48/configs/leader_universe.json` + `registry/universe.py` + `runtime/universe_snapshots/` + `universe_change_log.jsonl` + 9 条单测 | ✅ 10 大类 / 六锚 / XAU,XAG,CL,BZ,NG,XCU 全覆盖；价格主源 OKX 永续校验；point-in-time 月度快照幂等 |
| **P0-C 事件采集** ✅ | `sec_edgar` / `fed_calendar` / `macro_calendar` 三个官方源采集器（`collectors/tradefin/`）+ `events/store.py`（`event_id` 幂等 + `available_at` 硬校验）+ `cli/collect_events.py` | `18/data_center/events/events.jsonl` + `tests/test_events_collectors.py`（19 条） | ✅ **2026-11-11**：30 天回填 **74 条**（earnings 47 / regulatory 20 / mna 2 / cpi 2 / fomc 1 / nfp 1 / macro_other 1），`available_at` 完整率 **100%**、前视违规 **0**、重跑 `appended=0/skipped=74`；39 `--source events` 消费 74 条，`model=ProsusAI/finbert`、`trace_id` 74/74 唯一（顺带修复 `_normalize_model` 被本地路径 `zhangjiangtao` 误判为中文模型的溯源 bug） |
| **P0-D 统计纪律（先行）** ✅ | 接线 45 评测系统（`purged_kfold`/`walk_forward`/`deflated_sharpe_ratio`/`pbo_cscv`，**不重写统计函数**）+ 新增 `trials.jsonl` 试验记账 + `assert_gate()` 强制封装 | `registry/factor_gate.py` + `runtime/trials.jsonl` + `tests/test_factor_gate.py` + `tests/test_no_direct_verdict_write.py`（E-4，存量 19 模块白名单） | ✅ **2026-11-11 重判完成**：F&G 全历史（n=1761）`M2_fng_delta_3d` IC=-0.0029, t=0.121 → `inconclusive`（t≤3）；旧 36 天样本的 IC=-0.4826/p=0.005 **降级为不显著**，与预期一致 |
| **P0-E 数据回填（与 D 并行）** ⏳ | ① F&G 全历史回填 ✅ ② Odaily 缺正文回填（实测仅 195 条缺正文，已达标；补 `url` 字段仍待做）③ 修复云端 40 后端错配（18/40/11 已统一 `postgres`） | 回填脚本 + 数据质量报告 `48-涌现架构/runtime/data_quality/fear_greed_backfill.json` | F&G ✅ 3202 天；S 层日级因子 ≥250 天待 P0-A；D2 四子维度待 P0-C |
| **P0-F 中文模型接线** ✅ | ① 中文模型可配置（`FINBERT_ZH_MODEL_PATH`/`FINBERT_ZH_MODEL_ID`/本地 `models/finbert-zh`，默认 `yiyanghkust/finbert-tone-chinese`）② label 映射改为 `model.config.id2label` + 模型卡契约双来源，未覆盖时 `RuntimeWarning` ③ 删除跨语言 fallback ④ `analyze_text(with_meta=True)` 追加 `model` + `confidence` 溯源（默认四键不变，规则兜底 confidence=None 不伪造） | `sentiment_engine.py` + 9 条单测 | ✅ **2026-11-11 实测通过**：利好 `+0.9992 positive` / 利空 `-0.9981 negative` / 中性 `0.0 neutral`，`model=yiyanghkust/finbert-tone-chinese`；9 passed，相关回归 14 passed |
| **P1-A 中文财经源** ✅ | 新浪/华尔街见闻/财联社/金十 四采集器 + 正文入库 + 限频熔断 | `collectors/tradefin/{sina_finance,wallstreetcn,cls_telegraph,jin10}_collector.py` + `events/body_store.py` + `tradefin/_guard.py` + `tests/test_cn_finance_collectors.py`（13 条） | ✅ **2026-11-11 实测**：3 天窗口 **15 请求 0 失败（0% < 30%）**，231 事件 + 231 正文（sina 100 / wsc 60 / cls 50 / jin10 21），`available_at` 100%、前视 0、重跑正文 `appended=0`；熔断单测覆盖 75% 打开 / 25% 不打开 / 状态持久化；39 E2E 227 条走 `finbert-tone-chinese` 且 `sentiment=null` 为 0 |
| **P1-B VIX 三件套** ✅ | VIX/VIX3M/VVIX/put-call 入 18 主链；**FRED `VIXCLS` 与 Yahoo `^VIX` 合并为单一口径**（主源 FRED，Yahoo 仅当日补充） | `collectors/chain/vix_collector.py` + `48/metrics/regime.py`（`RegimeSchema`）+ `tests/chain/test_vix_collector.py`（9 条）+ `48/tests/test_regime_schema.py`（19 条） | ✅ **2026-11-11**：30 天窗口 `observed=22`、`gaps=[]`、`ok=true`；生产代码 `def .*vix` **1 处**（单测静态守护）；FRED 主源 + CBOE VIX3M/VVIX，put/call 无稳定公开源按 null 留空；nanoclaw/11 副本已收口；期限结构复用最近一条 `vix`+`vix3m` 完整行并以 `term_as_of` 标注；F&G `<25→crisis` / `>75→risk_off` |
| **P1-C 形态扩展** ✅ | `leader_form.py`（多均线栈/Pivot/OBV 背离/布林状态） | FeatureHub 新模块 + 单测 | ✅ **2026-11-12**：首版 29 列；**v2.8 扩至 33 列**（新增 `rsi14/macd_dif/macd_dea/macd_hist`）；`leader_form_only` 集合注册成功；16 条单测 + 21 单元全绿；`obv_divergence` 为 ±1/0，`boll_pctb` 零带宽记 NaN |
| **P1-D 组合因子** ✅ | `deep_factor_prior.py`（F3 → 组合因子）+ `factor_prior.json` 去 degraded + 按源分层 | 组合因子产出 + 6 条单测 | ✅ **2026-11-12**：`n_articles=228`、`n_sources=4`、`n_factors=10`、`weak=[jin10]`、`degraded=false`、`degraded_reason=null`；18 新闻套件 296 passed；快讯先验状态以 `newsflash` 块如实保留 |
| **P2-A 对齐器** ✅ | `financial_env_align.py`（事件落首个可交易时点 + 市场级广播 + `feat_as_of` 前视审计） | `48/metrics/financial_env_align.py` + `tests/test_financial_env_align.py`（21 条） | ✅ **2026-11-12**：crypto 下一小时 / 股票下一交易日（跳周末）；市场级 E/S/P 按 date 广播；`in_event_window=[-1,+1]`；前视审计 **0 违规**；无价格时 `forward_ret`/`label` 全 NaN 不伪造 |
| **P2-B 联合验证** ✅ | L-A/L-B/L-C/L-D 四层验证 + `factor_gate` 接线 | `48/metrics/financial_env_validate.py` + `tests/test_financial_env_validate.py`（18 条）+ `runtime/financial_env_report.json` | ✅ **2026-11-12**：verdict 五态齐全（`VERDICTS` 全量枚举 + 断言）；未预注册 → `not_preregistered` 不得申报 candidate；`--dsr/--pbo` 可从 45 系统注入。**v2.6 真实首跑**：`--klines-dir` + 285 日 regime 回写 + 预注册文件 → `data_status=ok`、`lookahead=0`、`n_obs=2790`、全部 `inconclusive`（`M_score` t=-0.62 / `P_score` t=1.14）；S/E 历史覆盖不足仍是卡点 |
| **G10 统一价格源** ✅（代码）/⏳（数据） | 40 域 Binance/yfinance/OKX 三套口径合一 | `18/data_center/market/price_source.py` + `tests/test_price_source.py`（16 条）+ 40 域 7 处迁移 | ✅ **2026-11-12 代码收口**：唯一 OHLCV 实现（OKX `1Dutc` 主源 + Binance fallback + 已收盘过滤 + canonical `ts_ms/open/high/low/close/volume/source` + 缓存 `18/data/market/ohlcv/`）+ 静态守护；**⏳ 历史回填与真实重跑由云端执行**（本地已产出 5 标的 2200 日缓存但不作为验收证据） |
| **P3 接线** ✅ | 通过验证的 CF 因子 → 48 metrics / 40 priors | `registry/factor_publication.py` + `tests/test_factor_publication.py`（9 条）+ `runtime/factor_registry.json` | ✅ **2026-11-12**：SSOT `factor_verdicts.jsonl` → 发布视图单向投影；只有 `candidate/candidate_weak` 可进入下游，其余落 `excluded`；`load_approved()` 不回落原始 verdict；`verify_two_way()` 三类问题（mismatch/stale/unpublished）双读一致；首次发布 `approved=0 / excluded=6`、`verify ok=true`（当前无因子过门禁，符合红线 1） |
| **v2.8 缺口收口** ✅ | ① RSI/MACD 进 P 层 ② F&G 接入 `RegimeSchema` ③ 39 → 48 S 层适配器 | `leader_form.py`（33 列）+ `regime.py`（`load_crypto_fng_history/pick_crypto_fng`）+ `financial_env_validate.py`（`load_semantic_sentiment`） | ✅ **2026-11-12 实测**：① 16 条单测（RSI 单边 100/0、横盘 50、MACD 方向与预热）；② 285 日回写中 **36 个有效 F&G 日**，陈旧 >3 天即 null，`crypto_fng.as_of` 溯源；③ 39 事件流产出 **68 个「标的×日期」**，S 层自动加载且 `S_score`/`S×P` 恢复；ruff 全绿 |

### 10.2 v1 的明确非目标

- **不找 alpha**：v1 目标是建立可证伪流水线，允许且预期部分因子被证伪
- 不做全市场扫描（只做龙头宇宙）
- 不做模型训练（34 职责）
- 不做实盘接入（50 维持 shadow）
- 不做 LoRA/自训练（39 SPEC §12.3 已有规划，不在本 SPEC 范围）

---

## §11 风险与红线

| 风险 | 说明 | 缓解 |
|---|---|---|
| R1 前视偏差 | 新闻修订、财报重述、宏观数据修订 | 强制 `available_at` + point-in-time 正文快照 |
| R2 多重检验 | 4 层 × 8-10 因子 × 5 horizon = 200+ 组合 | 试验记账 + t>3 + DSR + PBO |
| R3 数据窥探 | 反复调参直到显著 | 预注册假设 + 样本外冷却 20-30% |
| R4 幸存者偏差 | 用今日龙头回测历史 | point-in-time 宇宙快照 |
| R5 采集合规 | 中文财经源反爬 | 官方 API 优先、限频、robots 遵守、法律红线（§3.2） |
| R6 职责越界 | 39 产出被直接当交易信号 | 39 只出描述性知识；决策走 23/50 门禁（39 SPEC §8.2 已定义） |
| R7 指标玄学 | Pivot/OBV/均线参数被当 alpha | 形态层自律（§6.3）+ 必须过四道统计关 |

**三条不可协商的红线**：
1. 任何因子未过 §7.5 全部门禁，**禁止**进入 40/50 消费链
2. 任何采集器违反 §3.2 合规红线，**立即下线**
3. 任何"看起来很好"的回测结果，若试验次数 N > 20，**默认视为噪声**直到 DSR/PBO 通过

---

## §12 调研结论索引（传统金融 + AI 工程）

### 12.1 传统金融侧（校准设计）

| 结论 | 采纳情况 | 本 SPEC 落点 |
|---|---|---|
| 因子工程流水线：去极值 → 标准化 → 行业/市值中性化 → 正交化 → IC/IR | ✅ 全采纳 | §7.2 |
| 事件研究范式：估计窗 + 短窗 CAR + 长窗漂移 + 事件强度 z（SUE/surprise） | ✅ 全采纳 | §3.3 |
| 情绪聚合三权重（attention/novelty/source reliability）+ 指数衰减 | ✅ 全采纳 | §4.2 |
| 情绪反向必须条件化（高情绪 + 高估值/高拥挤） | ✅ 采纳，修正原假设 | §4.3 |
| VIX 期限结构（VIX vs VIX3M）比单看 VIX 水平稳健 | ✅ 采纳为 regime 开关 | §5.2 |
| 龙头 = 行业 RS 前 30% ∩ 流动性分位 ∩ 趋势模板，两层轮动 | ✅ 采纳 | §2.3 |
| 具体均线参数组合（5/13/65/128）当 alpha | ❌ 不采纳（参数拟合） | §6.3 明确降级为描述 |
| Pivot Point 当预测工具 | ❌ 不采纳（无学术证据） | §6.3 仅作参考位 |
| OBV 背离当独立信号 | ❌ 不采纳（证据混合） | §6.3 仅辅助确认 |
| 无条件"恐慌即抄底 / 高情绪即反向" | ❌ 不采纳 | §4.3 条件化 |

### 12.2 AI 工程侧（纪律）

| 结论 | 本 SPEC 落点 |
|---|---|
| 朴素特征拼接会淹没文本信号，门控/交叉注意力稳定更优 | §7.2 双套并行（late fusion 基线 + gated 上限） |
| 增量 IC 必须正交化后计算 | §7.2 硬要求 |
| LLM 当标注器/抽取器有效，当价格预测器被证伪 | §4.1 职责划分 |
| 情绪衰减应按事件类型分半衰期，且 lag0-5 全部入模 | §4.2 τ 配置化 |
| Regime-gated 优于同容量 MLP；报告分状态 IC 而非全样本均值 | §7.2 L-D |
| 时间戳即真理 / 先正交再宣称 / 试验记账 / 嵌套 purged CV / 单变量消融 / 样本外冷却 | §7.5 六道关 |

---

## §13 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v2.8 | 2026-11-12 | **三处代码缺口收口（第 4 项另开 SPEC）**：① `21/feature_hub/modules/leader_form.py` 由 29 → **33 列**，新增 `rsi14`（Wilder `ewm(alpha=1/14)`；单边 100/0、横盘 50、预热 14 根 NaN）与 `macd_dif/macd_dea/macd_hist`（EMA12/26/9，`hist=2*(DIF-DEA)`，DEA 预热至 34 根）；经 `_form_long()` 自动进 `P_score`，`EXPECTED_COLUMNS` 单测同步，3 条新用例（RSI 单边/横盘/预热、MACD 方向/预热）；② `48/metrics/regime.py` 新增 `load_crypto_fng_history()`（只读 18 `data_center.db` 的 `crypto_fear_greed`，同日取最新、`metrics.date` 优先）+ `pick_crypto_fng()`（当日缺失仅在 `FNG_MAX_STALE_DAYS=3` 内回退，超期即 null，避免把两周前值冒充当日），`--write-history`/`--check` 传入 `crypto_fng` 并带 `as_of` 溯源；285 日回写实测 **36 个有效 F&G 日**；4 条新单测；③ `48/metrics/financial_env_validate.py` 新增 `load_semantic_sentiment()`（39 `semantic_events.jsonl` → `symbol/date/score/available_at`，跳过无 sentiment/空 symbol/坏时间戳，同日同标的 mean + 最晚 `available_at`）+ CLI `--semantic-events [PATH]`（`nargs="?"`），未显式给 `--sentiment` 时自动加载，`price_source.sentiment` 标注来源；39 实测 **68 个「标的×日期」**，`S_score` 与 `S×P` 恢复；4 条新单测；④ §9「9 域各维历史统计」标注**需单独开 SPEC**，本轮不实现；⑤ SPEC §1.2 新增 G14/G15、§6.1/§6.2/§7.2/§10.1 同步 |
| v2.7 | 2026-11-12 | **G10 代码收口 + P3 接线（数据侧交云端）**：① 新增 `18/data_center/market/price_source.py` 作为全仓唯一 OHLCV 实现：主源 OKX `-USDT-SWAP`（`1Dutc`，UTC 零点对齐，避开 OKX 默认 `1D` 的 UTC+8 偏移）、Binance 显式 fallback（每根 bar 带 `source`）、只返回已收盘 bar（OKX `confirm=1` / Binance `closeTime<=now`）、canonical schema `ts_ms/open/high/low/close/volume/source`、缓存 + `meta.json`（`first/last/n_bars/n_gaps` 溯源）；② 40 域 7 处直连迁移（`p1_ma200_anchor` / `p2_asset_rotation` / `p3_sector_transmission` / `p3_cross_asset_matrix` / `p3_resonance_matrix` / `p3_stovall_breadth` / `p3_fund_flow` / `p3_washout_integration`），删除各脚本自有分页重试；③ `tests/test_price_source.py` 16 条（口径映射/分页去重/未收盘丢弃/fallback/缓存 roundtrip/缺口统计/**静态守护 40 域禁 `fetch_ohlcv/ccxt.binance/ccxt.bybit`**）；④ 48 `load_klines` 改为「统一价格源优先 → 11 域 CSV 回退」，provenance 增加 `tier=unified|kline_csv`，新增 `--days/--no-unified-prices`；⑤ 新增 `48/registry/factor_publication.py`：SSOT → `factor_registry.json` 单向投影，仅 `candidate/candidate_weak` 可消费，`load_approved()` 不回落原始 verdict，`verify_two_way()` 报 mismatch/stale/unpublished，首次发布 `approved=0/excluded=6` 且 `ok=true`；⑥ 9 条单测；**⑦ 明确边界：历史回填与真实重跑由云端执行，本地产出仅作代码自测，不作验收证据** |
| v2.6 | 2026-11-12 | **P2 真实数据首跑（价格注入 + regime 历史 + 预注册）**：① `financial_env_validate.py` 新增 `--klines-dir`（读 11 域 kline 缓存，`*_1D.csv` 优先、否则 `*_1H.csv` 聚合日线）、`--symbols`、`--prereg`，P 层由同日线经 21 域 `leader_form.compute` 派生（复用 P1-C），报告新增 `price_source` 溯源块；② 新增市场级因子**时序 IC** 口径（`mode=time_series|cross_section`，`MIN_TS_DATES=30`），修复 M 层因全宇宙同值导致截面 IC 无定义而被静默丢弃的问题；③ `metrics/regime.py` 新增 `--write-history`，回写 285 日 `runtime/regime/*.json`；④ 新建 `configs/factor_preregistration.json`（`financial-env-prereg-v1`，L-A 5 条 + L-B 3 条，声明注册时未跑真实数据）；⑤ 真实首跑：`data_status=ok`、`lookahead_violations=0`、`n_obs=2790`、`M_score` 时序 IC=-0.042(t=-0.62)、`P_score` 截面 IC=0.048(t=1.14)、`ALL_layers` 同序 → 全部 `inconclusive`，并如实记录 S/E 历史覆盖不足；⑥ 测试隔离 `factor_gate.RUNTIME_DIR` 防止测试写入真实 trial 账本；48 全套 326 passed、ruff 全绿 |
| v2.5 | 2026-11-12 | **P2-A / P2-B 落地回写（对齐器 + 联合验证）**：① 新增 `48/metrics/financial_env_align.py`：`align(events, sentiment, regime, form, horizon, prices, asset_class)` 输出 `(symbol,date)` 索引 + E/S/M/P + `forward_ret_{1,3,5,10,20}d` + `label` + `in_event_window` + `feat_as_of`；事件按 `available_at` 落首个可交易时点（crypto 下一小时 / 股票下一交易日跳周末），**市场级行（`symbol=""`）按 date 广播**到全宇宙且只补 NaN；`audit_lookahead()` 前视审计 **0 违规**；无价格时收益与标签全 NaN 不伪造；21 条单测。② 新增 `48/metrics/financial_env_validate.py`：L-A 逐日截面 Spearman IC/ICIR（截面 <3 丢弃）+ `ALL_layers` 合成、L-B `E×S/E×M/S×P` 交互与 `event/no_event` 分组、L-C 逐步加入 + 截面回归残差增量 IC + block bootstrap CI、L-D `label/VIX 档/F&G 极值` 分桶（描述性不记 trial）；`verdict` 严格来自 `assert_gate()`/`write_verdict()`，未预注册 → `insufficient_data/not_preregistered`，样本量不足或前视违规 → 只读判定不污染 `trials.jsonl`；CLI 支持 `--prices/--events/--sentiment/--form/--regime-dir/--dsr/--pbo`；本地无 OHLCV → 如实 `data_status=insufficient_data`；14 条单测，48 全套 326 passed、ruff 全绿。③ §1.2 G7 / §7.1 / §7.2 / §10.1 状态同步 |
| v2.4 | 2026-11-12 | **P1-D 落地回写（组合因子 G8）**：① 新增 `18/data_center/processing/deep_factor_prior.py`，输入 `events.jsonl`+`bodies.jsonl`（`body_ref="bodies.jsonl#<id>"` 关联），复用 F3 `extract_dominance_claim`；② 聚合键 `(dominant_factor, horizon)`，`composite_score=Σw·sign/Σw`（`w=confidence_in_text×impact`，`|score|≤0.15→neutral`）；③ **不按 direction 预分组**（否则 score 恒 ±1，失去多空一致度）；④ `by_source` 三档分层（traditional_finance/crypto/other），弱证据阈值按**源已取正文文章数** `<30` 判定并隔离出顶层 `factors`；⑤ `factor_prior.json` 升级 `factor-prior-v2`：`degraded=false`、`n_articles/n_sources/n_factors/degraded_reason` 齐备，快讯先验以 `newsflash` 块标注 `newsflash_prior_disabled_by_default`（不翻案）；⑥ FAIL-OPEN 降级不抛；⑦ 实测 `n_articles=228 / n_sources=4 / n_factors=10 / weak=[jin10]`，6 条单测 + 18 新闻套件 296 passed；⑧ §1.2 G8 / §8.1 / §8.3 / §10.1 状态同步 |
| v2.3 | 2026-11-12 | **P1-C 落地回写（形态层 P）**：① 新增 `21/feature_hub/modules/leader_form.py`，输出 29 列——`ma_5/13/65/128/200` + `ma_dist_*`、`ma_stack_*` 四态 one-hot、`above_ma200`、`pivot_p/r1/r2/s1/s2` + `dist_to_*`、`vol_ratio_5_20`、`obv_slope_20`、`obv_divergence`、`boll_pctb/bandwidth/squeeze`；② 口径定稿：Pivot 用**前一根 bar** 的 H/L/C（无同日收盘前视），均线栈状态用 one-hot 而非字符串列（字符串会让清洗链 `InfNaNImpute` 数值化失败并整集降级为 raw），`boll_pctb` 在零带宽时记 NaN，`obv_divergence` 顶背离 `-1` / 底背离 `+1` / 无背离 `0`；③ 注册进 `modules/loader._MODULE_IMPORTS` + `config/feature_sets.yaml`（`leader_form_only`）；④ §6.3 四条自律（参数拟合/无预测力/混合证据/必须过统计关）直接写入模块 docstring；⑤ 新增 13 条单测，21 单元测试全绿；⑥ §1.2 G6 / §6.2 / §10.1 状态同步 |
| v2.2 | 2026-11-11 | **P1-B 落地回写（VIX 三件套单一口径）**：① 新增 `18/data_center/collectors/chain/vix_collector.py`（`fetch_vix` 原样迁自 nanoclaw；FRED `VIXCLS` 主源 + CBOE `VIX3M`/`VVIX` 历史 + Yahoo 当日补充；`vix_ratio`/`put_call_ratio`/`source` 字段）；② FRED 边缘对 python TLS 指纹断连（HTTP/1.1/httpx h2 实测均失败）→ 内置 `curl` 回退 + 指数退避重试；CBOE/FRED 断连降级为空（fail-open），put/call 无稳定公开 CSV 按 null 留空；③ nanoclaw `market_data.py` 删除本地副本改为 import；11 `MacroFeed.fetch_vix`（yfinance 第三副本）改为转调 18，`coin_fundamental_metal._fetch_vix` 更名 `_read_stored_price`（仅 DB 读取）；④ 新增 `48/metrics/regime.py`（`RegimeSchema`：分档/1 年分位/期限结构/F&G 极值交叉/confidence/`gap_report`）；⑤ 修正 §5.3 M5 斜率方向：**正文公式改为 `VIX3M/VIX - 1`**（正=contango），`vix_ratio=VIX/VIX3M` 仅作原始比价、P2 禁止直接用于阈值；flat 阈值 `|slope|<0.005`；⑥ 验收：30 天 `observed=22/gaps=[]/ok=true`，生产代码 `def .*vix` 仅 1 处（静态单测守护），9+15 条单测通过；⑦ §1.2 G5 / §5.2.1 / §10.1 状态同步；⑧ 期限结构与二阶分量允许复用最近一条 `vix3m` 非空的 T−1 行，schema 新增 `term_as_of` 标注分量交易日（避免当日 Yahoo 行缺 VIX3M 导致 `slope` 恒 null）；⑨ F&G 极值按方向区分：`<25 → crisis`、`>75 → risk_off`，原「任一极端即 crisis」废弃 |
| v2.1 | 2026-11-11 | **P1-A 落地回写（四中文财经源）**：① 新增 `sina_finance_collector`（JSONP/JSON 快讯）、`wallstreetcn_collector`（快讯 + 深度文章详情正文）、`cls_telegraph_collector`（公开签名 `md5(sha1(sorted_query))`）、`jin10_collector`（快讯；日历接口实测下线故 `CALENDAR_ENABLED=False`，由 P0-C BLS 覆盖）；② 新增 `events/body_store.py`（`bodies.jsonl` point-in-time 正文快照，`body_id=sha1(source\|url\|date_published)[:16]`，事件只存 `body_ref`）+ `tradefin/_guard.py`（单源限频 + 滑动窗口失败率 >30% 熔断 + 状态持久化）+ `_classify.py`/`_util.py`（§3.1 类型/龙头码规则 + 北京时间→UTC）；③ `cli/collect_events.py` 接入 4 源（`--source cn`）并打印各源请求/失败率/熔断状态；④ 39 `gen_semantic_events.py` 支持 `body_ref` 解析（`EMERGENCE_BODIES_PATH`）；⑤ 实测 **3 天 15 请求 0 失败**、231 事件 + 231 正文、`available_at` 100%、前视 0、重跑正文幂等；39 消费 302 条中 227 条走 `finbert-tone-chinese`；⑥ 13 条新单测（18 total 641 passed，2 条既有无关失败：washout/fred 受环境变量影响）；⑦ §1.2 G3 / §3.2 / §10.1 状态同步 |
| v2.0 | 2026-11-11 | **P0-C 落地回写（P0 阶段收官）**：① 新增 `18/data_center/collectors/tradefin/`（`sec_edgar_collector` / `fed_calendar_collector` / `macro_calendar_collector`，官方源、UA 标识、全局限频与重试）；② 新增 `data_center/events/store.py`（canonical EventRecord 契约 + `event_id` 幂等 + `available_at` 硬校验，缺失直接拒写）+ `path=events.jsonl`；③ 新增 `data_center/cli/collect_events.py` 回填/增量入口；④ 实测 **30 天回填 74 条**（sec_edgar 69 / macro_calendar 4 / fed_calendar 1），`available_at` 完整率 **100%**、前视违规 **0**、重跑幂等；⑤ 19 条单测通过；⑥ 39 `--source events` 消费 74 条（`model=ProsusAI/finbert`，`trace_id` 唯一），修复 `_normalize_model` 裸 `"zh"` 子串被本地路径 `zhangjiangtao` 误命中导致英文模型被标成中文的 bug（+1 单测）；⑦ §1.2 G2 / §3.2 / §10.0 D4 / §10.1 P0-C 状态同步 |
| v1.9 | 2026-11-11 | **P0-A / P0-B 落地回写**：① P0-A ✅ 39 `gen_semantic_events.py` 新增 `--source events`（读 canonical EventRecord → 调 9 域 SentimentEngine → 追加 `sentiment`/`event`/`trace_id`，按 `trace_id` 幂等、旧行不改写）；9 `with_meta` 增加 `confidence`（规则兜底为 None，不伪造）；`model` 落库归一化为 §7.7 四值；6 + 9 条单测通过，E2E `CPI→-0.9986/0.9986/finbert-tone-chinese`；② P0-B ✅ `configs/leader_universe.json`（只存信号覆盖，**不复制成员**）+ `registry/universe.py`（校验 10 大类/六锚/必备品种/OKX 主源 + 月度 point-in-time 快照 + 变更日志）；9 条单测通过，已生成 `runtime/universe_snapshots/leader_universe_202611.json` |
| v1.8 | 2026-11-11 | **P0-D / P0-E 落地回写**：① P0-D ✅ 新增 `registry/factor_gate.py`（`assert_gate` 七步短路 + `record_trial` + `register_factor` + `write_verdict` + bypass 留痕）+ `runtime/trials.jsonl` + 16 条单测 + E-4 静态检查（存量 19 模块白名单）；F&G 全历史重判 `M2_fng_delta_3d`（n=1761）IC=-0.0029/t=0.121 → `inconclusive`，旧 36 天样本的"显著"降级；② P0-E D1 ✅ 回填 3202 天（PG，2018-02-01→2026-11-11，近 3 年覆盖 99.91%，max gap 4 天）；③ D3 实测修正：缺正文为 **195/3048（6.4%）**而非 2096，且全部缺 `url` 字段；④ D5 后端口径统一（18/40/11 均跟随 `DATA_CENTER_BACKEND=postgres`），11 消融脚本改走 `get_sink()` |
| v1.7 | 2026-11-11 | **第二轮六维评审后的文档一致性修复**：① 版本头 `v1.0 提案稿` → `v1.6 评审修订稿`（此前只改 §13 未改头）；② §0.1 明确"双 FinBERT"（原只写 ProsusAI）；③ §3.4 示例与 §4.1 硬约束 3 的 `model: finbert2-zh` → `finbert-tone-chinese`；④ §10.0 D1 补数据区间 `2026-09-09→10-29`（已落后 13 天）、D5 修正"停滞 11-05"为实测 `generated_at=2026-11-10` 且 SQLite 停在 10-29；⑤ §7.7 硬约束 2 明确 `_last_model` 归一化在落库层完成（引擎返回完整 id，与契约不一致） |
| v1.6 | 2026-11-11 | **按评审意见补齐文档**：① 新增 §10.0 数据前置（P0-E 五项回填 D1-D5 + 五道质量门禁），关闭评审"待补 P0-E 章节"；② 新增 §5.2.1 VIX 迁入口径（P1-1：提取提升不重写，全仓仅 1 处实现）；③ 新增 §7.7 可观测性契约（P1-2：`trace_id` 五段透传 + 三条硬约束 + 3 次 grep 验收）；④ 术语统一 `EventSchema → EventRecord`；⑤ §0.2 标题三→四条；⑥ §1.1/G11 更新为 P0-F 已修复；⑦ §10.1 顺序纳入 P0-F ✅ |
| v1.5 | 2026-11-11 | **P0-F 实现并实测通过**：中文模型切到 `yiyanghkust/finbert-tone-chinese`（可配置），label 映射改 `id2label` + 模型卡契约双来源，删除跨语言 fallback，新增 `analyze_text(with_meta=True)` 溯源；3 条中文句实测 +0.9992 / -0.9981 / 0.0，9 条单测 + 14 条相关回归全绿 |
| v1.4 | 2026-11-11 | **中文模型事实修正（用户确认 + 仓库核实）**：云端中文模型为 `yiyanghkust/finbert-tone-chinese`（非 FinBERT2）。查实三个真实缺陷：① 代码硬编码已 404 的 `valuesimplex/FinBERT2` 且中文路径无 env 覆盖；② 该模型输出 `LABEL_0/1/2`，而 `FINBERT_ZH_LABEL_MAP` 无 `LABEL_*` 键 → 每条中文 `return None` → 静默回退 27 关键词规则引擎；③ 中文模型缺失时跨语言 fallback 到英文模型（中文 UNK 54%）。据此重写 P-4/G11/§4.1 硬约束 4，并新增 **P0-F 中文模型接线** |
| v1.3 | 2026-11-11 | **关闭 A 阶段两个设计缺口**：① 新增 §3.0 事件契约对齐（P0-1）——实测 9 域三套契约后采用方案 C「三层复用 + 最小扩展」，canonical record 定为 EventLedger entry，`EventSchema` 更名为 `EventRecord`；② 新增 §7.6 门禁强制点设计（P0-4）——唯一入口 `assert_gate()` + 五态 verdict + `trials.jsonl` + 四强制点 + 可审计绕过；③ 补 P-4/G11 的模型实测证据（`ProsusAI/finbert` = `finbertTRC2` 英文模型，中文分词 UNK 率 54%） |
| v1.2 | 2026-11-11 | **六维评审后修订**（[评审报告](./reviews/REVIEW-2026-11-11-financial-env-spec-v1.1.md)，结论：不通过）：① 修正 FinBERT 事实——云端实际为 `ProsusAI/finbert`（英文），本地 FinBERT2 404，路由存在静默跨语言 fallback（新增前提 P-4 / 缺口 G11 / 硬约束 4）；② 承认 39 的 20927 条语义事件 100% `source=trader.log`、零新闻事件；③ P0-D 改为**接线 45 评测系统**而非新建统计函数；④ 新增 P0-E 数据回填（F&G 仅 36 天、S 层仅 13 天，不足以支撑验收）；⑤ 新增 G12（事件契约冲突）/G13（门禁无强制点） |
| v1.1 | 2026-11-11 | 按用户裁决修订：① U 层改为**投影 40 域 10 大类资产分类**（不另立宇宙），补齐黄金/白银/油/气/铜，新增 U-1/U-2/U-3 三条衔接契约与信号覆盖差异化表；② §4.1 澄清"降级"= 架构归位（打分原语），补 6 条适合性判据与 4 条硬约束；③ 明确 P0-D 统计纪律先行；④ 新增缺口 G10（40 三套价格口径并存） |
| v1.0 | 2026-11-11 | 首版提案：四层信号（E/S/M/P）+ 龙头宇宙 + 三维联合验证 + 统计纪律；承接并修正 `SPEC-EMERGENCE-FINBERT-SENTIMENT-FACTOR-EVAL-v1.0` 的因子评估框架（FinBERT 从独立管线降级为 39 的插件） |
