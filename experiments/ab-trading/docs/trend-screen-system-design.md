# 三屏趋势交易系统技术文档

> 版本: v1.1  (基于代码实现 + 核心设计理念整理)
> 核心模块: `screen_engine.py` / `screen_executor.py` / `strategy_params.py`
> 主入口: `compute_full_trading_signal()`

---

## 1. 系统核心理念

**趋势一致性确定方向，置信度评估确定仓位。**

这是三屏趋势交易系统的核心设计哲学。系统通过技术指标和基本面两个维度，分别在周线和日线上判定趋势方向与置信度，最终撮合形成统一的趋势方向和置信度，以此驱动交易决策。

### 1.1 核心创新点

| 创新点 | 说明 |
|--------|------|
| **三维动态 + 动态优先原则** | 传统系统仅看静态指标方向，本系统引入方向+速度+加速度三维度，动态优先权重更高。可能出现"静态牛市但动态熊市 → 最终判定熊市"的情况，捕捉趋势逆转的早期信号 |
| **双维度趋势一致性** | 技术面（周线+日线指标）和基本面（AI研报）各自独立形成趋势一致性判定，再撮合为最终方向 |
| **置信度驱动的仓位模型** | 仓位不固定，由置信度动态映射（5%~60%），高置信度重仓、低置信度轻仓 |
| **Freqtrade量化框架集成** | 通过策略库提供日内入场信号，多策略投票机制确保信号质量 |

### 1.2 系统三层结构

| 层级 | 名称 | 周期 | 核心职责 |
|------|------|------|---------|
| 第一屏 | 战略层 | 周线 | 趋势方向判定（周线准确度更高，权重更重要） |
| 第二屏 | 战术层 | 日线 | 趋势一致性检测 + 仓位计算 + 动态止损止盈 |
| 第三屏 | 执行层 | 4h/1h | Freqtrade入场信号 + 实时持仓监控 + 交易执行 |

### 1.3 主框架数据流

```
                    ┌─────────────────────────────────────────────┐
                    │           技术指标维度                        │
                    │                                             │
                    │  周线TOP5指标 ──▶ 定期回测(vs 日线MA200基线)  │
                    │     │              优于基线 → 分配权重         │
                    │     │              形成置信度评估               │
                    │     ▼                                        │
                    │  静态方向 + 三维动态(方向/速度/加速度)         │
                    │     │                                        │
                    │     ▼  动态优先原则(权重更高)                  │
                    │  周线最终方向 + 置信度                         │
                    │                                             │
                    │  日线TOP5指标 ──▶ 同理(周线权重 > 日线权重)    │
                    │     │                                        │
                    │     ▼                                        │
                    │  日线最终方向 + 置信度                         │
                    │     │                                        │
                    │     ▼                                        │
                    │  周线 vs 日线 → 趋势一致性检测                 │
                    │  + 贝叶斯参数寻优 → 置信度                     │
                    └────────────────┬────────────────────────────┘
                                     │
                    ┌────────────────┼────────────────────────────┐
                    │                ▼                             │
                    │           基本面维度                          │
                    │                                             │
                    │  AI研报: 周报 + A1日报                       │
                    │     │                                        │
                    │     ▼                                        │
                    │  基本面趋势一致性 + 置信度                    │
                    └────────────────┬────────────────────────────┘
                                     │
                                     ▼
                    技术面 + 基本面撮合
                    → 最终趋势方向 + 最终置信度
                                     │
                                     ▼
                    Freqtrade量化框架 (策略库)
                    → 1h/4h 多策略投票入场信号
                    → 信号校准(同向增益/反向扣减)
                                     │
                                     ▼
                    置信度 → 仓位映射 (5%~60%)
                    + 逆势加仓(1次, 40%预算)
                    + 顺势加仓(置信度跃迁≥15%)
                    + 动态止损/止盈
```

### 1.4 五大算法在框架中的定位

五大算法不是并列关系，而是服务于"趋势一致性 + 置信度"这一核心目标的技术手段：

| 算法 | 在框架中的角色 | 代码函数 |
|------|---------------|---------|
| 静态指标投票 | 趋势方向的**基础判定**（传统方法） | `_calc_trend_direction_static()` |
| 三维动态融合 | 趋势方向的**核心创新**（动态优先，权重更高） | `_calc_trend_direction_dynamic()` |
| 动态权重调整 | 指标权重的**定期回测排名**（vs 日线MA200基线） | `_calc_dynamic_weights()` |
| 贝叶斯参数寻优 | 置信度的**参数寻优工具**（寻找最优组合） | `_calc_bayesian_confidence()` |
| 技术面+基本面撮合 | 最终方向与置信度的**融合层** | `_fuse_technical_fundamental()` |

---

## 2. 技术指标维度 — 趋势一致性与置信度

### 2.1 指标筛选与权重分配

周线和日线各采用真实回测筛选的 TOP5 优质指标。指标必须**优于基线（日线MA200买入持有策略）**才能入选，并根据回测表现分配权重。

#### 周线指标组（权重更高，准确度更好）

| 指标 | 类型 | 说明 |
|------|------|------|
| RSI_50 | 动量 | 50周期RSI |
| SuperTrend | 趋势 | 超级趋势指标 |
| StochRSI_Cross | 动量 | 随机RSI金叉死叉 |
| OBV_Trend | 量能 | 能量潮趋势 |
| Keltner_Channel | 波动率 | 肯特纳通道突破 |

代码位置: [`SCREEN1_INDICATORS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L568-L570)

#### 日线指标组

| 指标 | 类型 | 说明 |
|------|------|------|
| GoldenCross_50_200 | 趋势 | 50/200日均线金叉死叉 |
| MACD_Cross | 动量 | MACD金叉死叉 |
| Vortex | 趋势 | 漩涡指标 |
| TEMA | 趋势 | 三重指数移动平均 |
| EMA_Align_20_50_200 | 趋势 | 三条EMA排列方向 |

代码位置: [`SCREEN2_INDICATORS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L572-L574)

#### 权重分配原则

- **定期回测**：每周对指标进行回测，与日线MA200买入持有基线对比
- **优于基线**：只有跑赢基线的指标才保留在指标组中
- **权重排名**：根据超额收益、夏普比率、胜率综合排名分配权重
- **周线权重 > 日线权重**：周线 60%，日线 40%（周线准确度更高）

代码位置: [`WEEKLY_WEIGHT`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L577-L578) / [`_calc_dynamic_weights()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1116-L1215)

### 2.2 趋势方向判定 — 静态 + 三维动态

#### 静态指标投票（基础判定）

对周线/日线各自的5个指标进行投票，多数决定方向（BULL/BEAR/NEUTRAL）。

核心函数: [`_calc_trend_direction_static()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L927-L935)

#### 三维动态融合（核心创新，动态优先）

每个指标计算三个维度：

| 维度 | 范围 | 含义 |
|------|------|------|
| direction | BULL/BEAR | 当前趋势方向 |
| speed | 0-100 | 方向变化快慢（动量强度） |
| acceleration | 0-100 | 速度变化快慢（加速/减速） |

**逆转检测**：`speed < 30 且 acceleration > 20` → 潜在逆转信号

逆转分数 > 50% 时，方向前缀 `REVERSAL_`。

核心函数: [`_calc_trend_direction_dynamic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L938-L1014)

#### 动态优先原则

**这是系统的核心创新点。** 动态维度的权重高于静态，可能出现：

> **静态牛市，但动态是熊市 → 最终判定熊市**

```
逆转信号 > 60% → 以动态方向为准（覆盖静态）
动态方向 = NEUTRAL → 以静态方向为准（回退）
其他情况 → 以动态方向为准
```

核心函数: [`_calc_trend_consistency_with_dynamics()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1017-L1106)

### 2.3 趋势一致性检测

周线和日线各自形成最终方向后，进行趋势一致性检测：

- **一致**（周线=日线且非NEUTRAL）→ 确认趋势方向，置信度 = 周线置信度×60% + 日线置信度×40%
- **不一致** → 趋势不确认，置信度 = min(周线, 日线) × 0.5

### 2.4 贝叶斯参数寻优（置信度计算工具）

贝叶斯方法用于**参数寻优**，寻找指标权重的最优组合，而非直接决定方向：

```
P(趋势|信号) ∝ Σ[权重 × (0.5 + speed/200 + acceleration/200)]
```

- **似然概率** = 动态权重 × 动态因子（0.5 + speed/200 + acceleration/200）
- **先验** 隐含在历史权重排名中
- **周线 60%，日线 40%**（周线准确度更高）

核心函数: [`_calc_bayesian_confidence()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1216-L1292)

---

## 3. 基本面维度 — AI研报趋势一致性

基本面通过 **AI研报**（周报 + A1日报）形成独立的趋势一致性和置信度评估：

| 数据源 | 周期 | 用途 |
|--------|------|------|
| Screen1 周报 | 周线 | 宏观趋势方向、市场情绪 |
| A1 日报 | 日线 | 短期事件驱动、资金流向 |

基本面数据获取: [`_fetch_fundamental_data()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1303-L1338)

---

## 4. 技术面 + 基本面撮合 — 最终方向与置信度

技术面和基本面各自独立形成趋势方向和置信度后，进行撮合，产生**最终趋势方向**和**最终置信度**：

| 场景 | 融合规则 | 置信度计算 |
|------|---------|-----------|
| 方向一致 | 以技术面为主 | 加权平均（技术60% + 基本面40%） |
| 基本面中性 | 以技术面为主 | 直接用技术面置信度 |
| 方向矛盾 | 以技术面为主 | 取较低值，按矛盾程度最大扣减30% |

> **核心原则**：趋势方向以技术面为主，基本面影响置信度调整。

核心函数: [`_fuse_technical_fundamental()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1513-L1569)

---

## 5. 置信度驱动的仓位模型

**置信度评估确定仓位** — 这是系统的第二条核心主线。

### 5.1 置信度 → 入场仓位映射

| 置信度 ≥ | 入场仓位 | 实际仓位 (×25%) |
|---------|---------|----------------|
| 85% | 60% | 15% |
| 75% | 45% | 11.25% |
| 65% | 30% | 7.5% |
| 55% | 15% | 3.75% |
| 45% | 5% | 1.25% |

- 总仓位上限: 80%（预留20%防范风险）
- 逆势加仓预算: 固定40%
- 最大加仓次数: 1次（战略缓冲）

代码位置: [`_POSITION_TIERS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_executor.py#L51-L57)

### 5.2 动态止损线

四条均线中取价格下方最近的一条作为止损线：

| 均线 | 周期 | 收盘价确认 |
|------|------|-----------|
| 日MA200 | 日线 | 昨日收盘价 |
| 日EMA200 | 日线 | 昨日收盘价 |
| 周MA200 | 周线 | 上周收盘价 |
| 周EMA200 | 周线 | 上周收盘价 |

**收盘价确认规则**：仅使用已收盘K线计算，当前未完成的K线不算跌破。
**全部跌破时禁止开多仓**。

核心函数: [`get_dynamic_stop_loss()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/strategy_params.py#L71-L170)

### 5.3 波动率调整止盈/加仓幅度

BTC基准参数：
- 止盈: 4%
- 加仓跌幅: 8%

其他币种按 **30天波动率与BTC的比率** 动态调整，范围 0.5x ~ 2.5x：

```
币种止盈 = BTC止盈 × vol_mult
币种加仓跌幅 = BTC加仓跌幅 × vol_mult
vol_mult = 币波动率 / BTC波动率  (clamp 0.5 ~ 2.5)
```

核心函数: [`get_vol_adjusted_params()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/strategy_params.py#L193-L219)

---

## 6. 第三屏 · 执行层（Freqtrade + 持仓监控）

### 6.1 Freqtrade 策略信号整合

通过多策略投票机制获取1h/4h入场信号：

#### 4h 波段策略

| 策略 | 权重 | 说明 |
|------|------|------|
| MultiGroupStrategy | 55% | 评分100，信号率100% |
| TrendConfirmationStrategy | 45% | 评分94，信号率80% |

#### 1h 短线策略

| 策略 | 权重 | 说明 |
|------|------|------|
| RegimeHybridStrategy | 60% | 评分41，信号率20% |
| Bot2StrategyTrend | 40% | 评分35，备用 |

#### 信号校准规则

- 同向时 +置信度×权重（1h×10%, 4h×15%）
- 反向时 -10%
- 1h或4h任一同向即为 freqtrade_consistent = true

核心函数: [`_fetch_freqtrade_signals()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1426-L1511)

### 6.2 跨周期数据对齐

参考 Backtrader 的 resampling 机制，将低周期K线聚合成高周期：

| 源周期 | 目标周期 | 聚合根数 |
|--------|---------|---------|
| 5m | 1h | 12 |
| 1h | 4h | 4 |
| 1h | 1D | 24 |
| 4h | 1D | 6 |

聚合规则：Open=首根开盘, High=最高, Low=最低, Close=末根收盘, Volume=求和。

核心函数: [`_resample_candles()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1340-L1398)

### 6.3 加仓机制

#### 逆势加仓（防御性）

- **触发条件**: 价格触达预设加仓价位（入场价 × (1 - 加仓跌幅)）
- **预算**: 固定40%
- **最大次数**: 1次（战略缓冲，与V15-CT马丁完全隔离）
- **标记**: `has_counter_trend_addon = true`

#### 顺势加仓（进攻性）

- **触发条件**: 置信度跃迁 ≥ 15%
- **预算**: 新置信度对应仓位 - 入场仓位
- **与逆势加仓互斥**: 触发顺势加仓时需检查未触发过逆势加仓

代码位置: [`screen_executor.py 1060-1155`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_executor.py#L1060-L1155)

### 6.4 执行决策（五大算法模式）

```
1. 趋势不一致 → WAIT
2. 方向 = BULL/BEAR 且 置信度 ≥ 60% → 正常仓位入场
3. 方向 = BULL/BEAR 且 置信度 ≥ 45% → 轻仓试探
4. 其他 → WAIT
```

核心函数: [`_five_algo_decision()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_executor.py#L447-L518)

---

## 7. 最终信号结构

`compute_full_trading_signal()` 返回完整信号：

```python
{
    "symbol": "BTC",
    "price": 64433.7,
    "generated_at": "2026-07-10T12:00:00Z",
    "timeframes": {"weekly": 210, "daily": 250, "4h": 42, "1h": 168},
    "trend_consistency": {
        "weekly": {
            "static_direction": "BULL",
            "dynamic_direction": "BULL",
            "final_direction": "BULL",
            "confidence": 72.5,
            "reversal_score": 0,
            "avg_speed": 45.2,
            "avg_acceleration": 12.8,
            "signals": [...],
        },
        "daily": {...},
        "consistent": true,
        "overall_direction": "BULL",
        "consistency_confidence": 68.3,
    },
    "bayesian_confidence": {
        "direction": "BULL",
        "confidence": 73.2,
        "bull_probability": 0.732,
        "bear_probability": 0.268,
        "weekly_weights": {"weights": {...}, "performance": {...}},
        "daily_weights": {...},
    },
    "freqtrade_signals": {
        "1h": {"signal": "BUY", "confidence": 60, "strategy": "Freqtrade_1h_Vote"},
        "4h": {"signal": "BUY", "confidence": 55, "strategy": "Freqtrade_4h_Vote"},
    },
    "technical_fundamental_fusion": {
        "technical": {"direction": "BULL", "confidence": 73.2},
        "fundamental": {"direction": "BULL", "confidence": 65},
        "consistent": true,
        "final_direction": "BULL",
        "final_confidence": 69.9,
        "weights": {"technical": 0.6, "fundamental": 0.4},
        "conflict_level": 0,
    },
    "final_signal": {
        "direction": "BULL",
        "confidence": 79.2,
        "trend_consistent": true,
        "fusion_consistent": true,
        "freqtrade_consistent": true,
    },
}
```

核心函数: [`compute_full_trading_signal()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L1576-L1707)

---

## 8. 关键参数汇总

### 8.1 screen_engine.py

| 参数 | 值 | 位置 |
|------|----|------|
| 周线指标数 | 5个 (RSI_50等) | L568 |
| 日线指标数 | 5个 (GoldenCross等) | L572 |
| 周线权重 | 60% | L577 |
| 日线权重 | 40% | L578 |
| 逆转覆盖阈值 | 60% | L1035 |
| 技术面权重 | 60% | L1525 |
| 基本面权重 | 40% | L1526 |
| 矛盾最大扣减 | 30% | L1552 |

### 8.2 screen_executor.py

| 参数 | 值 | 位置 |
|------|----|------|
| 最大加仓次数 | 1次 | L32 |
| 基准加仓跌幅 | 8% | L33 |
| 基准止盈 | 4% | L34 |
| 总仓位上限比例 | 25%权益 | L38 |
| 最低入场仓位 | 5% | L40 |
| 最高入场仓位 | 60% | L41 |
| 逆势加仓预算 | 40% | L42 |
| 总仓位硬上限 | 80% | L43 |
| 顺势加仓置信度跃迁 | 15% | L45 |
| 正常入场阈值 | 60% | L47 |
| 试探入场阈值 | 45% | L48 |
| 固定止损比例 | 10% | L49 |

### 8.3 strategy_params.py

| 参数 | 值 | 位置 |
|------|----|------|
| BTC基准止盈 | 4% | L195 |
| BTC基准加仓跌幅 | 8% | L196 |
| 最小波动率倍数 | 0.5x | L204 |
| 最大波动率倍数 | 2.5x | L204 |
| 波动率周期 | 30天 | L60 |

---

## 9. 候选币种池

| 币种 | spot | swap | 是否BTC |
|------|------|------|---------|
| BTC | BTC-USDT | BTC-USDT-SWAP | 是 |
| ETH | ETH-USDT | ETH-USDT-SWAP | 否 |
| SOL | SOL-USDT | SOL-USDT-SWAP | 否 |
| BNB | BNB-USDT | BNB-USDT-SWAP | 否 |
| DOGE | DOGE-USDT | DOGE-USDT-SWAP | 否 |
| XRP | XRP-USDT | XRP-USDT-SWAP | 否 |
| UNI | UNI-USDT | UNI-USDT-SWAP | 否 |
| HYPE | HYPE-USDT | HYPE-USDT-SWAP | 否 |
| OKB | OKB-USDT | OKB-USDT-SWAP | 否 |

BTC币种使用全六维评分，其他币种使用三维评分（技术65/宏观20/跨市场15）。

代码位置: [`CANDIDATE_COINS`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/experiments/ab-trading/screen_engine.py#L25-L35)

---

## 8. 与旧三屏马丁系统的区别

| 维度 | 旧三屏马丁 | 新三屏趋势 |
|------|-----------|-----------|
| 核心逻辑 | 六维评分 + V9马丁 | 五大算法 + 趋势捕捉 |
| 加仓策略 | 最多3次(4层) 马丁摊平 | 最多1次(逆势) + 顺势加仓(置信度跃迁) |
| 止损方式 | 固定比例(10%) | 动态均线止损(日/周 MA200/EMA200) |
| 止盈方式 | 固定比例(4%×vol_mult) | 波动率动态调整(0.5x~2.5x) |
| 入场信号 | 六维加权评分 | 贝叶斯置信度 + Freqtrade多策略投票 |
| 仓位计算 | 固定首仓比例 | 置信度动态映射(5%~60%) |
| 基本面 | 无 | 技术面60% + 基本面40%撮合 |
| 执行策略 | 与V15-CT共享马丁逻辑 | 完全独立，战略缓冲1层 |

> 注：`strategy_params.py` 的动态止损/止盈模块已实现但尚未完全集成到 `screen_executor.py` 的主执行循环中，当前执行器仍使用固定10%止损和波动率调整止盈。

---

## 11. API 接口

### 11.1 /api/trend-screen

获取单个币种的完整三屏趋势信号。

```
GET /api/trend-screen?symbol=BTC
```

响应: 完整信号结构（见第5节）+ 动态参数 + 持仓信息 + 账户信息。

代码位置: `data_server.py` 中 `/api/trend-screen` 端点

### 11.2 /api/token-signals

获取8个主流币种的信号概览。

```
GET /api/token-signals
```

响应: 币种列表，每个包含 direction, confidence, price, trend_consistent, freqtrade_4h, freqtrade_1h 等。

---

## 12. 演进路径

当前系统的后续优化方向：

- [ ] 动态均线止损集成到 screen_executor 主循环（替换固定10%）
- [ ] 每周指标回测 + 权重自动更新
- [ ] 移动止盈（盈利后止盈价上移）
- [ ] 分批离场（50% → 30% → 20%）
- [ ] 系统进化（连续亏损3笔或月度定期触发A8-做梦部）
