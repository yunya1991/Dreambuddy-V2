# 单币基本面排名器 (CoinFundamentalRanker) 设计规格

> 日期：2026-09-01
> 上游规格：[2026-08-30-strategic-force-vector-design.md](./2026-08-30-strategic-force-vector-design.md)
> 范围：per-coin 基本面信号生成 → Shadow 审计 → 性能追踪 → 验证后考虑 BCRM2.0 集成
> 阶段：设计阶段

---

## 一、背景与动机

### 1.1 问题陈述

当前战略层五计庙算按 `crypto_usdt / us_stock / precious_metal` 三类资产算全局五维加权总分，输出四档决策（≥75 进攻 / 60-74 防御 / 50-59 轻仓防守 / <50 全禁）。这回答了"大盘能不能开仓"的问题，但**没有回答"在允许的范围内，优先开谁、谁能趋势持仓"**。

### 1.2 用户洞察

用户观察到某些币种具备独立于大盘的趋势持仓条件，且这些案例构成**基本面投资三阶段闭环**：

- **P1 预期驱动（CRCL）**：主网升级预期 → 强势，但预期落地后短期炒作风险升高
- **P2 盈收扩张（UNI）**：费用开关销毁 + Robinhood 接入带来费用收入大幅增长 → 价格大涨、趋势持仓
- **P3 估值修复（HYPE）**：TVL/费用飙升但估值稳定 → 大跌后强势修复，大盘稳定时表现更优

### 1.2.1 三阶段闭环方法论

这三个案例不是独立事件，而是**同一个基本面投资闭环的三个阶段**，标的会在阶段间流转：

| 阶段 | 驱动力 | 信号特征 | 策略匹配 | 切换触发 |
|------|--------|---------|---------|---------|
| **P1 预期驱动** | 主网上线/预期利好 | E6 价值捕获质变 >0.5，E5 供给收缩温和 | 抄新不抄旧，机会最大 | 预期落地/事件兑现 → P2 |
| **P2 盈收扩张** | 盈收增强（如 Robinhood 接入） | E5 供给收缩强度 >0.5，E6 delta >0.5，估值未极端 | 跟踪实际盈收改善，趋势持仓 | 估值到高位/增速放缓 → P3 |
| **P3 估值修复** | 盈收基本面强+估值稳定 | E5/E6 双高，估值分位中性，大跌后修复力强 | 大跌承接，大盘稳定时优先 | 新预期出现 → P1；盈收再扩张 → P2 |

**核心决策**：新机会需先判断所处阶段，再用"案例+算法"输出信号强弱排名，不同阶段匹配差异化策略。现阶段评估：**CRCL(P1) > UNI(P2) > HYPE(P3)**，但 CRCL 预期落地后短期炒作风险上升，需重新评估转 P2 跟踪实际盈收。

**阶段识别四决策**（2026-09-01 用户确认）：
1. 阶段识别器为**独立模块** `coin_fundamental_phase_classifier.py`，与 ranker 解耦，可独立 Shadow 验证
2. 阶段切换触发采用**混合规则**：事件驱动（主网落地/盈收公告）+ 信号阈值（E6 跌破 0.3）+ 估值分位（>80 分位）三者组合
3. **新增阶段匹配策略映射表**：phase × rank → {信号权重, SL/TP 空间, 持仓时间建议}，Shadow 不耦合 BCRM2.0
4. 案例回放脚本升级为**阶段闭环回放**：回放 CRCL(P1→P2)、UNI(P2→P3)、HYPE(P3) 完整流转

### 1.3 机构实证支撑

Artemis Fundamentals 研究（4年回测，Sharpe 1.73）证实：四个近正交的基本面信号在加密货币市场具有系统性定价能力：
1. Revenue Stability（收入稳定性）
2. MC/Fees Mean Reversion（市值/费用均值回归）
3. DAU Growth（活跃用户增长）
4. Revenue Quality（收入质量）

**决策**：以 Artemis 架构为算法基线，本地化到三类资产。

### 1.4 设计原则

1. **独立信号生成**：先生成 per-coin 专属基本面信号，不耦合 BCRM2.0，控制变量做好研究
2. **Shadow 模式**：只计算 + 记录 + 审计，不参与任何交易决策
3. **三类资产统一框架**：crypto_usdt / us_stock / precious_metal 共用输出格式，信号定义按资产类差异化
4. **等权起步 → IC 加权**：初始等权，后续按信息系数动态优化权重
5. **FAIL-OPEN**：数据不足或异常 → 中性默认值，不阻塞流程
6. **已有数据优先**：先用已有 collector 数据，后续扩展新数据源

---

## 二、架构

### 2.1 模块位置

```
11-易经推理系统/force_vector/
  ├─ force_vector_calculator.py          # 已有：全局五维力向量
  ├─ feature_correlation_calculator.py    # 已有
  ├─ pca_resonance_analyzer.py           # 已有
  ├─ cycle_comparator.py                 # 已有
  ├─ elasticity_beta_calculator.py       # 已有
  ├─ contradiction_transform_detector.py  # 已有
  ├─ strategic_mapper.py                 # 已有
  │
  ├─ coin_fundamental_ranker.py          # 新建：主模块，调度三类信号计算
  ├─ coin_fundamental_crypto.py          # 新建：加密货币四信号
  ├─ coin_fundamental_stock.py           # 新建：美股四信号
  ├─ coin_fundamental_metal.py           # 新建：贵金属四信号
  └─ coin_fundamental_shadow.jsonl       # 新建：Shadow 审计日志
```

### 2.2 数据流

```
18-数据获取中心 (data_center.db)
  ├─ records (source=defillama, category=protocol)   ← 扩展 collector
  │   └─ metrics: {tvl, fees_24h, fees_7d, fees_30d, ...}
  ├─ records (source=coingecko, category=coin)       ← 新建 collector
  │   └─ metrics: {market_cap, total_supply, circulating_supply, ...}
  ├─ records (source=yfinance, category=stock/metal)  ← 新建 collector
  │   └─ metrics: {revenue, earnings, pe_ratio, operating_margin, ...}
  ├─ records (source=fred, category=macro)            ← 新建 collector
  │   └─ metrics: {real_rate, t10yie, ...}
  └─ records (source=odaily_newsflash)                ← 已有
      └─ metrics: {tickers_hit, event_strength, ...}
      │
      ▼ SQLite 读取
      │
11-易经推理系统/force_vector/coin_fundamental_ranker.py
  ├─ 按 asset_class 分派到对应子模块
  ├─ coin_fundamental_crypto.py  → 4 信号 → z-score
  ├─ coin_fundamental_stock.py   → 4 信号 → z-score
  ├─ coin_fundamental_metal.py   → 4 信号 → z-score
  └─ 等权合成 → CoinFundamentalSignal → JSONL
      │
      ▼ 独立输出
      │
coin_fundamental_shadow.jsonl (Shadow 审计)
  ├─ 信号记录
  ├─ 价格追踪（7d/14d/30d 后回填）
  └─ IC / 命中率 / Sharpe 统计
```

### 2.3 与现有系统的关系

| 系统 | 关系 | 说明 |
|------|------|------|
| 五计庙算 | 并列 | 五计庙算 = 全局四档决策；CoinFundamentalRanker = per-coin 排名。互不干扰 |
| BCRM2.0 | 独立 | 当前不耦合。验证通过后（PR+CR）再决定集成方式 |
| force_vector 7模块 | 并列 | 全局力向量 → 战略层；per-coin 基本面 → per-coin 排名 |
| 9-基本面 signal_engine | 方法论参考 | 复用 `_adaptive_weight()` Beta 分布自适应权重的**设计思路**，不直接调用 |

---

## 三、三类资产信号定义

### 3.1 加密货币 (crypto_usdt)

基于 Artemis 四信号直接本地化：

| 信号 | 公式 | 数据源 | z-score 归一化 |
|------|------|--------|---------------|
| Revenue Stability | `sharpe = mean(fees_30d_diff) / std(fees_30d_diff)` | DeFiLlama `/summary/fees/{protocol}` | 横截面 z-score |
| MC/Fees Mean Reversion | `z = (mc_fees_ratio - mean_30d) / std_30d; signal = -z`（高估→负信号） | CoinGecko market_cap + DeFiLlama fees | 时间序列 z-score |
| TVL Growth Momentum | `(tvl_now - tvl_7d_ago) / tvl_7d_ago` | DeFiLlama `/protocols` | 横截面 z-score |
| Revenue Quality | `fees_30d_avg / tvl_current`（资本效率） | DeFiLlama fees + TVL | 横截面 z-score |

**coin → protocol 映射**：
```python
CRYPTO_MAP = {
    "UNI": ("uniswap", "uniswap"),    # (DeFiLlama slug, CoinGecko id)
    "AAVE": ("aave", "aave"),
    "HYPE": ("hyperliquid", "hyperliquid"),
    # ...
}
```

**缺失映射处理**：DeFiLlama 无对应 protocol → TVL/费用类信号标记 `data_quality="partial"`，只用 CoinGecko 市值类信号。

### 3.2 美股 (us_stock)

对标 Artemis 四信号，用美股财务指标替代：

| 对标 Artemis 信号 | 本地化信号 | 公式 | 数据源 |
|-----------------|-----------|------|--------|
| Revenue Stability | Earnings Stability | 营收 4 季度滚动 Sharpe | yfinance `financials` |
| MC/Fees Mean Reversion | P/E Mean Reversion | `z = (pe_ratio - mean_4q) / std_4q; signal = -z` | yfinance `info.trailingPE` |
| DAU Growth | Revenue Growth | 营收 YoY 增长率 | yfinance `financials` |
| Revenue Quality | Profitability Quality | 营业利润率或 ROE | yfinance `info.operatingMargins / returnOnEquity` |

**coin → ticker 映射**：
```python
STOCK_MAP = {
    "NVDA": "NVDA",
    "COIN": "COIN",
    "GOOGL": "GOOGL",
    # ...
}
```

### 3.3 贵金属/大宗商品 (precious_metal)

对标 Artemis 四信号，用宏观/商品指标替代：

| 对标 Artemis 信号 | 本地化信号 | 公式 | 数据源 |
|-----------------|-----------|------|--------|
| Revenue Stability | Price Trend Stability | 价格 30 天滚动 Sharpe | yfinance `GC=F` / `SI=F` |
| MC/Fees Mean Reversion | Real Rate Mean Reversion | 实际利率 Z-score 反向（利率↑→金价↓） | FRED `T10YIE` |
| DAU Growth | Flow Momentum | ETF 持仓量 7d/30d 变化率 | yfinance GLD/SLV 持仓 |
| Revenue Quality | Seasonal/Macro Quality | 金银比 Z-score + 季节性因子 | yfinance `GC=F/SI=F` |

**coin → 数据源映射**：
```python
METAL_MAP = {
    "XAUUSD": ("GC=F", "T10YIE", "GLD"),  # (yfinance_ticker, FRED_series, ETF_ticker)
    "XAGUSD": ("SI=F", "T10YIE", "SLV"),
    # ...
}
```

### 3.4 统一输出格式

```python
@dataclass
class CoinFundamentalSignal:
    coin: str                          # "UNI" / "NVDA" / "XAUUSD"
    asset_class: str                   # "crypto_usdt" / "us_stock" / "precious_metal"
    timestamp: int                     # ms
    fundamental_score: float            # [-1.0, +1.0] 综合基本面信号
    rank: str                           # "S" / "A" / "B" / "C"
    sub_signals: Dict[str, float]      # 4 个子信号各自 z-score，key 按 asset_class 不同
    data_sources: Dict[str, str]       # 各子信号的数据源标记
    data_quality: str                  # "ok" / "partial" / "insufficient"
    confidence: float                  # [0, 1] 数据充分度
```

### 3.5 等级映射

| 等级 | 条件 | 含义 |
|------|------|------|
| S（趋势持仓候选） | score > 0.6 且 ≥2 个子信号 > 0.5 | 大盘震荡也可持仓，回调=加仓机会 |
| A（优先关注） | score > 0.3 | 信号来时优先扫描 |
| B（正常） | -0.3 ~ 0.3 | 正常流程 |
| C（谨慎） | score < -0.3 | 即使有信号也减仓/不开 |

### 3.6 综合得分公式

```
fundamental_score = w1 × s1 + w2 × s2 + w3 × s3 + w4 × s4

初始等权：w1 = w2 = w3 = w4 = 0.25
后续优化：按 IC（信息系数）动态调整权重
```

### 3.7 阶段识别器（Phase Classifier）

基于 1.2.1 三阶段闭环方法论，新增独立阶段识别模块，输入 E5/E6 信号 + 估值分位 + 事件时间线，输出当前所处阶段。

**模块**：`coin_fundamental_phase_classifier.py`（独立于 ranker，Shadow 模式）

**阶段枚举**：
- `P1_EXPECTATION`：预期驱动阶段（主网落地前/预期利好发酵）
- `P2_REVENUE_EXPANSION`：盈收扩张阶段（盈收增强兑现）
- `P3_VALUATION_RECOVERY`：估值修复阶段（盈收强+估值稳+大跌修复力）

**混合切换规则**（三因子组合，任一触发即评估切换）：
1. **事件驱动**：主网落地/盈收公告/Robinhood 接入等离散事件 → P1→P2 或 P2→P3 边界
2. **信号阈值**：E6 质变跌破 0.3（预期消退）/ E5 收缩强度跌破 0.3（盈收放缓）→ 阶段流转信号
3. **估值分位**：>80 分位 → P3 倾向；30-80 分位 → P2 倾向；<30 分位 + E6>0.5 → P1 倾向

**输出数据类**：
```python
@dataclass
class PhaseClassification:
    coin: str
    current_phase: str          # P1_EXPECTATION / P2_REVENUE_EXPANSION / P3_VALUATION_RECOVERY
    phase_confidence: float     # [0, 1] 三因子一致性
    switch_triggers: List[str]   # 触发评估的事件/阈值清单
    evidence: Dict[str, float]  # E5/E6/估值分位等输入证据
    strategy_hint: Dict[str, Any]  # 来自 3.8 阶段策略映射表的提示
```

### 3.8 阶段匹配策略映射表

`phase × rank → {信号权重偏移, SL 空间建议, TP 空间建议, 持仓时间建议}`，Shadow 不耦合 BCRM2.0：

| Phase | Rank S | Rank A | Rank B |
|-------|--------|--------|--------|
| P1 预期 | TP 空间↑(预期溢价)、持仓短(预期落地前撤离) | 轻仓试错、SL 空间↓(预期波动大) | 不开 |
| P2 盈收 | 趋势持仓、TP 空间↑(盈收扩张持续)、SL 常规 | 跟踪盈收兑现、趋势轻持 | 观察 |
| P3 修复 | 大跌承接、SL 空间↓(修复力强)、持仓中长 | 大盘稳定时轻仓 | 观察 |

**案例锚定**：每个 phase 用 UNI/CRCL/HYPE 作为基准锚点，新标的与案例相似度（CBR）越高，策略越向案例靠拢。

---

## 四、数据源

### 4.1 数据源总表

| 数据源 | 费用 | 加密货币 | 美股 | 贵金属 | 状态 |
|--------|------|---------|------|--------|------|
| DeFiLlama `/protocols` + `/summary/fees` | 免费，~500 req/5min | ✅ | — | — | 需扩展 collector |
| CoinGecko `/coins/{id}` + `/market_chart` | 免费 Demo，100 req/min | ✅ | — | — | 需新建 collector |
| yfinance | 免费 | — | ✅ | ✅ | 需新建 collector |
| FRED | 免费 | — | — | ✅ | 需新建 collector |
| odaily_newsflash | 已有 | ✅ | — | — | ✅ 已有 |
| DeFiLlama `/chains` | 已有 | ✅(全局) | — | — | ✅ 已有 |

### 4.2 DeFiLlama Collector 扩展

现有 [defillama_collector.py](../../../18-数据获取中心/data_center/collectors/chain/defillama_collector.py) 已支持 `chains`、`historicalChainTvl`、`fees` 路由。需扩展：

| 新增 route | API 路径 | 数据 | 存储 |
|-----------|---------|------|------|
| `protocols` | `https://api.llama.fi/v2/protocols` | per-protocol TVL 列表 | records (source=defillama, category=protocol, sub_category={protocol_slug}) |
| `protocol_fees` | `https://api.llama.fi/summary/fees/{protocol}` | per-protocol 费用 | records (source=defillama, category=protocol_fees, sub_category={protocol_slug}) |

### 4.3 CoinGecko Collector（新建）

| route | API 路径 | 数据 |
|-------|---------|------|
| `coin_info` | `https://api.coingecko.com/api/v3/coins/{id}` | market_cap, total_supply, circulating_supply, max_supply |
| `coin_chart` | `https://api.coingecko.com/api/v3/coins/{id}/market_chart?days=30` | 历史 价格/市值 |

存储：records (source=coingecko, category=coin, sub_category={coin_id})

### 4.4 yfinance Collector（新建）

| route | 数据 | 覆盖资产类 |
|-------|------|-----------|
| `stock_financials` | 营收/盈利/PE/利润率 | us_stock |
| `stock_info` | market_cap, trailingPE, operatingMargins, returnOnEquity | us_stock |
| `metal_price` | GC=F/SI=F 历史 价格 | precious_metal |
| `etf_holdings` | GLD/SLV 持仓量 | precious_metal |

存储：records (source=yfinance, category=stock/metal, sub_category={ticker})

### 4.5 FRED Collector（新建）

| route | API 路径 | 数据 |
|-------|---------|------|
| `series` | `https://api.stlouisfed.org/fred/series/observations?series_id=T10YIE&api_key={key}` | 实际利率 TIPS |

存储：records (source=fred, category=macro, sub_category={series_id})

### 4.6 媒体数据源调研（Phase C 并行）

| 媒体 | 调研方向 | 目标 |
|------|---------|------|
| 星球日报 (odaily.com) | DeFi/Layer1/Layer2/Meme/RWA 等板块分类结构 | per-coin 结构化基本面数据 |
| 区块律动 (blockbeats.com) | 深度/研报分离结构 | 代币经济模型/解锁计划等深度数据 |

调研产出：页面结构分析报告 → 决定是否新增 collector 或 NLP 提取。

---

## 五、Shadow 审计与性能追踪

### 5.1 Shadow JSONL 格式

```jsonl
{
  "coin": "UNI",
  "asset_class": "crypto_usdt",
  "ts_ms": 1788230000000,
  "fundamental_score": 0.72,
  "rank": "S",
  "sub_signals": {
    "revenue_stability": 0.65,
    "mc_fees_mean_reversion": 0.81,
    "tvl_growth_momentum": 0.43,
    "revenue_quality": 0.55
  },
  "data_quality": "ok",
  "confidence": 0.8,
  "price_at_signal": null,
  "price_7d_after": null,
  "price_14d_after": null,
  "price_30d_after": null,
  "return_7d": null,
  "return_14d": null,
  "return_30d": null
}
```

价格字段在信号生成时留空，由定时任务在 7d/14d/30d 后回填，用于计算 IC 和命中率。

### 5.2 性能追踪指标

| 指标 | 公式 | 用途 |
|------|------|------|
| IC（信息系数） | `spearman(fundamental_score, return_7d)` | 信号预测力 |
| 命中率 | `P(sign(signal) == sign(return_7d))` | 方向准确率 |
| Sharpe 模拟 | `mean(long_s_rank / short_c_rank) / std` | S 级做多 C 级做空的模拟 Sharpe |
| 衰减分析 | IC vs 时间窗口（7d/14d/30d） | 信号有效期 |

### 5.3 优化循环

```
等权起步 → Shadow 运行 ≥30 天 → IC 监控
  ├─ IC > 0.05 的子信号 → 保留，按 IC 加权
  ├─ IC < 0.02 的子信号 → 剔除或降权
  └─ walk-forward 验证 → 确认非过拟合
      │
      ▼ 验证通过（PR+CR）
      │
考虑 BCRM2.0 集成方式（前置预筛 / 仓位加权 / 双模式）
```

---

## 六、开关与配置

### 6.1 开关架构

```python
# 总开关（默认 False，Shadow 模式）
enable_coin_fundamental_ranker = False

# 子开关
enable_coin_fundamental_crypto = True   # 三类可独立开关
enable_coin_fundamental_stock = True
enable_coin_fundamental_metal = True
```

### 6.2 配置项

```python
# 数据采集间隔
COIN_FUNDAMENTAL_COLLECT_INTERVAL = "6h"  # 每 6 小时采集一次

# 信号计算间隔
COIN_FUNDAMENTAL_COMPUTE_INTERVAL = "1h"  # 每 1 小时计算一次

# IC 监控窗口
IC_MONITOR_WINDOW_DAYS = 30  # 30 天滚动窗口

# 信号有效期
SIGNAL_DECAY_DAYS = 7  # 信号 7 天后视为过期

# Shadow 审计日志路径
COIN_FUNDAMENTAL_SHADOW_JSONL = "11-易经推理系统/scripts/runtime/coin_fundamental_shadow.jsonl"
```

### 6.3 FAIL-OPEN 设计

| 异常场景 | 处理 |
|---------|------|
| 数据源 API 不可用 | 该子信号取中性值 0.0，标记 `data_quality="partial"` |
| coin 无映射 | 跳过该 coin，不生成信号 |
| 全部子信号数据不足 | `fundamental_score=0.0, rank="B", data_quality="insufficient"` |
| 模块异常 | FAIL-OPEN 中性默认 + 6 层堆栈日志，不阻塞交易 |

---

## 七、与 BCRM2.0 的关系

### 7.1 当前阶段（Shadow）

- `enable_coin_fundamental_ranker = False`
- 只计算 + 记录 + 审计，不参与任何交易决策
- BCRM2.0 完全不感知 CoinFundamentalRanker 的存在

### 7.2 后续阶段（验证通过后）

验证通过条件：
1. Shadow 运行 ≥30 天
2. IC > 0.05（信号有预测力）
3. walk-forward 非过拟合
4. PR + Code Review 通过

验证通过后，通过 PR+CR 决定耦合方式：
- **前置预筛**：排名低的币不扫描（减少 BCRM2.0 无效计算）
- **仓位加权**：排名高的币仓位弹性放大
- **双模式**：两者结合

**当前不预设耦合方式，由数据回测决定。**

---

## 八、实施阶段

| 阶段 | 内容 | 前置条件 | 预计产出 |
|------|------|---------|---------|
| **Phase A** | 数据源扩展：DeFiLlama protocols + CoinGecko + yfinance + FRED collector | 无 | 4 个 collector 就绪 |
| **Phase B** | CoinFundamentalRanker 模块：四信号计算 + 等权 + Shadow JSONL | Phase A | coin_fundamental_ranker.py + 3 子模块 |
| **Phase C** | 媒体页面调研：星球日报/区块律动分类结构 | 可与 A/B 并行 | 调研报告 → 决定是否新增 collector |
| **Phase D** | Shadow 运行 + 性能追踪 + IC 监控 + 权重优化 | Phase B | ≥30 天 Shadow 数据 + IC 报告 |
| **Phase E** | 阶段闭环方法论：E5/E6 信号 + 阶段识别器 + 策略映射表 + 闭环回放 | Phase B + D1 | 阶段识别器 + 闭环回放报告 |
| **Phase F** | walk-forward 回测验证 → 验证通过 → 考虑 BCRM2.0 集成方式 | Phase D + E | 回测报告 + 集成方案决策 |

---

## 九、文件清单

### 新建文件

| 文件 | 用途 |
|------|------|
| `11-易经推理系统/force_vector/coin_fundamental_ranker.py` | 主模块 |
| `11-易经推理系统/force_vector/coin_fundamental_crypto.py` | 加密货币四信号 + E5/E6 |
| `11-易经推理系统/force_vector/coin_fundamental_stock.py` | 美股四信号 |
| `11-易经推理系统/force_vector/coin_fundamental_metal.py` | 贵金属四信号 |
| `11-易经推理系统/force_vector/coin_fundamental_phase_classifier.py` | 阶段识别器（Phase E） |
| `11-易经推理系统/force_vector/coin_fundamental_phase_strategy_map.py` | 阶段匹配策略映射表（Phase E） |
| `11-易经推理系统/scripts/memory_l4/scripts/coin_fundamental_phase_replay.py` | 阶段闭环回放脚本（Phase E） |
| `18-数据获取中心/data_center/collectors/coin/coingecko_collector.py` | CoinGecko per-coin |
| `18-数据获取中心/data_center/collectors/stock/yfinance_collector.py` | yfinance 美股+贵金属 |
| `18-数据获取中心/data_center/collectors/macro/fred_collector.py` | FRED 宏观 |
| `11-易经推理系统/tests/test_coin_fundamental_ranker.py` | TDD 测试 |
| `11-易经推理系统/tests/test_coin_fundamental_phase_classifier.py` | 阶段识别器 TDD |

### 扩展文件

| 文件 | 修改内容 |
|------|---------|
| `18-数据获取中心/data_center/collectors/chain/defillama_collector.py` | 新增 `protocols` + `protocol_fees` route |
| `18-数据获取中心/data_center/scheduler.py` | 注册新采集任务 |
| `18-数据获取中心/data_center/core/dispatcher.py` | 注册新 collector |
