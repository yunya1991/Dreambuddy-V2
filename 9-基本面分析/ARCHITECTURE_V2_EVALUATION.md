# 基本面分析架构 V2 评估与重构设计

## 一、原架构核心逻辑评估

### 1.1 原架构文件分布

```
9-基本面分析/ops/nanoclaw/core_task1/
├── flow/scripts/
│   ├── regime_classifier.py          # 三层信号计算 + Regime分类
│   ├── signal_fusion.py              # 新闻+资金流信号融合 -> 买卖建议
│   ├── flow_brief_generator.py       # 资金流简报生成
│   └── flow_collector.py             # 数据源采集
├── narrative/scripts/
│   └── narrative_analyzer.py         # 叙事主题分析（10个分类体系）
└── scripts/
    ├── event_ledger_generator.py     # 事件账本（时间衰减加权）
    └── backtest_flow.py              # 回测流程
```

### 1.2 原架构三层信号体系（核心价值保留）

#### Layer 1: 外生层 (Exogenous) - 宏观资金环境
| 指标 | 计算逻辑 | 市场含义 | 数据来源 |
|------|---------|---------|---------|
| ETF资金流向 | BTC/ETH ETF净流入/流出加权评分 | 机构资金态度 | ETF数据/Tavily |
| 稳定币供应量 | 当前供应量 vs 90日历史均值 | 场内可用弹药 | Glassnode/替代 |
| CEX储备 | 交易所储备量变化 | 潜在卖压 | Glassnode/替代 |
| DXY指数 | 美元强度（与加密市场反向） | 宏观流动性环境 | FRED |
| FED政策利率 | 利率变化（下降=正分） | 货币政策立场 | FRED |
| 实际收益率 | 10Y实际收益率变化 | 无风险收益率环境 | FRED |

**评分公式**: `composite_exo = 0.30*etf + 0.20*stablecoin + 0.10*cex + 0.20*dxy + 0.20*fred`

#### Layer 2: 杠杆层 (Leverage) - 衍生品市场压力
| 指标 | 计算逻辑 | 市场含义 | 数据来源 |
|------|---------|---------|---------|
| 资金费率 | 异常高正费率=多头过热（负分）, 异常高负费率=空头过热（正分） | 杠杆方向拥挤度 | Binance/OKX |
| 持仓量(OI) | OI绝对值和变化率 | 市场参与度 | CoinGlass |
| 清算压力 | 24h清算量 / OI比值 | 强制平仓风险 | CoinGlass |

**评分公式**: `composite_lev = 0.35*funding + 0.35*oi + 0.30*liquidation`

#### Layer 3: 链上层 (On-chain) - 链上行为信号
| 指标 | 计算逻辑 | 市场含义 | 数据来源 |
|------|---------|---------|---------|
| 鲸鱼活动 | 大额转账/交易所净流向统计 | 聪明钱动向 | Glassnode/替代 |
| 地址追踪 | 链上Deep模式升级/资金路径风险 | 机构链上行为 | Dune/替代 |
| 交易所净流入 | BTC净流入/流出（流入=卖压） | 散户/机构进出 | Glassnode |
| Gas价格 | ETH Gas价格水平 | 市场活跃度 | Etherscan |

**评分公式**: `composite_onc = 0.30*whale + 0.40*address_tracking + 0.20*exchange_flow + 0.10*gas`

#### 综合Regime分类
```
composite_raw = 0.35*exo + 0.35*lev + 0.30*onc
composite = composite_raw * data_quality_factor * coverage_factor

bias分类:
- composite > 0.6 → bullish（多头）
- composite < -0.6 → bearish（空头）
- 其他 → neutral（中性）

filter:
- 信号分歧过大(std > 0.5) → disable
- 数据过时(>6h) → disable
- 数据覆盖率不足(<67%) → disable

risk_off = (leverage_score < -0.7) || (onchain_score < -0.7) || (composite < -0.8)
```

### 1.3 原架构叙事分析体系（保留核心）

**10大叙事分类**（narrative_analyzer.py 的 NARRATIVE_CATEGORIES）：
1. ETF/机构
2. Layer2/扩容
3. DeFi
4. NFT/元宇宙
5. GameFi
6. 稳定币
7. 监管政策
8. 技术创新
9. 安全事件
10. 宏观金融

**每个叙事的关键指标**:
- heat_score（热度）：事件数×0.4 + 互动量×0.35 + 时间新鲜度×0.25
- sentiment_score（情绪）：加权平均 sentiment
- lifecycle（生命周期）：emerging → growing → mature → declining

### 1.4 原架构问题诊断

| 问题 | 严重度 | 描述 |
|------|--------|-----|
| 数据源依赖过多 | 🔴 高 | 依赖15+个外部数据源（Glassnode/FRED/Glassnode等），实际环境中难以全部接入 |
| 文件路径混乱 | 🟠 中 | outputs/raw/flow/narrative 多层目录嵌套，路径依赖脆弱 |
| 代理数据膨胀 | 🔴 高 | 大量 fallback/proxy 逻辑，真实数据与代理数据混合，信号可信度下降 |
| 时间线缺失 | 🟠 中 | 只有单点快照，没有时间序列变化的直观可视化 |
| 最小阻力理论不够显式 | 🟠 中 | 方向判断隐含在 bias 中，速度/加速度没有单独提取 |
| 前端展示不直观 | 🟡 低 | 复杂JSON结构 -> 前端渲染负担大 |

---

## 二、新架构设计（V2: 基于最小阻力理论的简化版）

### 2.1 核心设计理念

```
┌────────────────────────────────────────────────────────────┐
│                     最小阻力理论 (Path of Least Resistance) │
│                                                             │
│   市场价格运动就像水流，总是沿着"阻力最小"的方向前进。       │
│                                                             │
│   ┌─ 方向 (Direction): 当前合力指向 (+/-)                    │
│   ├─ 速度 (Velocity): 变化的快慢程度                         │
│   └─ 加速度 (Acceleration): 趋势的增强/减弱                  │
│                                                             │
│   三个独立维度 + 新闻叙事验证 = 高置信度买卖信号              │
└────────────────────────────────────────────────────────────┘
```

### 2.2 新架构文件结构（极简）

```
9-基本面分析/
├── data_engine/                # 数据采集引擎（替换原有多层scripts）
│   ├── tavily_news_crawler.py # Tavily新闻抓取 + 事件分类
│   ├── flow_signal_collector.py # 资金流信号采集（简化版）
│   └── market_data_fetcher.py   # 价格/OI/费率等市场数据
├── core_engine/                 # 核心计算引擎
│   ├── least_resistance.py     # ⭐ 最小阻力三维计算（方向/速度/加速度）
│   ├── narrative_engine.py      # 叙事热度+情绪引擎（简化版）
│   └── signal_generator.py      # ⭐ 买卖点信号生成器
├── storage/                      # 统一数据存储
│   └── timeseries.json         # 时间序列数据（最近30天/每小时快照）
├── backend/                      # 后端API
│   └── ml_trade_service.py     # Flask服务（API路由）
└── frontend_reference/           # 前端参考设计（不实现，仅规范）
    └── DESIGN_SPEC.md           # 前端渲染规范
```

### 2.3 数据模型：时间序列快照（每小时）

```json
{
  "ts": "2026-06-21T08:00:00Z",
  "price": {
    "btc_usd": 65432.10,
    "change_24h_pct": 2.35
  },
  "resistance_3d": {
    "direction": "up | down | neutral",
    "direction_score": 0.65,       // [-1, 1]
    "velocity": 0.42,              // [-1, 1] 变化速度
    "acceleration": 0.18,          // [-1, 1] 趋势增强/减弱
    "confidence": 0.72             // [0, 1] 数据质量置信度
  },
  "signals": {
    "news_sentiment_index": 62,    // [0, 100] 50=中性
    "flow_composite_index": 58,    // [0, 100] 50=中性
    "narrative_heat_score": 0.45,  // [0, 1]
    "leveraged_stress_level": "low | medium | high"
  },
  "narrative": {
    "top_3": [
      {"category": "etf_institutional", "heat": 0.78, "sentiment": 0.65},
      {"category": "regulation_policy", "heat": 0.55, "sentiment": -0.30},
      {"category": "macro_finance", "heat": 0.48, "sentiment": 0.40}
    ]
  },
  "trading_signals": [
    {
      "type": "buy | sell | hold | reduce",
      "strength": 0.75,             // [0, 1] 信号强度
      "reason": "新闻情绪指数62+资金流指数58双正面，加速度转正",
      "confidence": 0.68,
      "time_horizon": "short_term | medium_term"
    }
  ]
}
```

### 2.4 最小阻力三维度计算逻辑（核心）

#### 维度1: 方向 (Direction) - "当前趋势是什么？"

```python
direction_score = weighted_sum(
    0.35 * news_sentiment_index,      # 新闻情绪（利多/利空占比）
    0.30 * flow_composite,            # 资金流综合（外生+杠杆+链上简化）
    0.20 * narrative_consensus,       # 叙事共识（主叙事情绪一致性）
    0.15 * price_momentum             # 价格动量（24h变化率归一化）
)

where:
    news_sentiment_index = 50 + 25*tanh(avg_sentiment * N_event_factor)
                         + 15*tanh((bull_count/bear_count - 1)/2)

    flow_composite = 简化版三层信号（用代理数据兜底）
                    = 0.40*etf_flow_proxy + 0.35*funding_proxy + 0.25*onchain_proxy

    narrative_consensus = top_narrative_sentiment * narrative_heat

    price_momentum = tanh(price_change_24h / 5.0)  # 5%波动映射到~0.46

分类阈值:
    direction_score > 0.3 → "up"
    direction_score < -0.3 → "down"
    其他 → "neutral"
```

#### 维度2: 速度 (Velocity) - "变化有多快？"

```python
# 计算方向得分的时间导数（过去24小时）
velocity_score = direction_score_now - mean(direction_score_24h_window)

# 归一化到 [-1, 1]
velocity = tanh(velocity_score / 0.3)  # 0.3的变化映射到~0.76

含义:
    velocity > 0.3 → 趋势加速形成
    velocity 在 [-0.3, 0.3] → 趋势稳定/横盘
    velocity < -0.3 → 趋势正在消退/反转
```

#### 维度3: 加速度 (Acceleration) - "趋势在增强还是减弱？"

```python
# 计算速度的变化率
acceleration_score = velocity_now - mean(velocity_recent_window)
acceleration = tanh(acceleration_score / 0.2)  # 加速度更敏感

含义:
    acceleration > 0.3 → 趋势正在增强（确认信号）
    acceleration 在 [-0.3, 0.3] → 趋势稳定（延续现有方向）
    acceleration < -0.3 → 趋势正在减弱（警惕反转信号）
```

### 2.5 核心买卖点信号生成逻辑

```python
def generate_trading_signals(direction, velocity, acceleration,
                              news_index, flow_index, narrative_heat,
                              stress_level):
    signals = []

    # 规则1: 强买入 - 方向向上 + 速度正向 + 加速度正向（三重确认）
    if direction == "up" and velocity > 0.2 and acceleration > 0.1:
        if news_index > 55 and flow_index > 55:
            signals.append({
                "type": "strong_buy",
                "strength": min(1.0, 0.6 + velocity*0.5 + acceleration*0.3),
                "reason": "方向向上+速度正向+加速度正向，新闻与资金流双重确认",
                "time_horizon": "medium_term"
            })

    # 规则2: 普通买入 - 方向向上 + (新闻或资金流正面)
    elif direction == "up" and (news_index > 52 or flow_index > 52):
        signals.append({
            "type": "buy",
            "strength": 0.5 + velocity*0.3,
            "reason": "方向向上，配合正面新闻或资金流入",
            "time_horizon": "short_term"
        })

    # 规则3: 强卖出 - 方向向下 + 速度负向 + 加速度负向（三重确认）
    elif direction == "down" and velocity < -0.2 and acceleration < -0.1:
        if news_index < 45 or flow_index < 45 or stress_level == "high":
            signals.append({
                "type": "strong_sell",
                "strength": min(1.0, 0.6 - velocity*0.5 - acceleration*0.3),
                "reason": "方向向下+速度负向+加速度负向，或高杠杆压力",
                "time_horizon": "medium_term"
            })

    # 规则4: 卖出 - 方向向下 + 新闻或资金流负面
    elif direction == "down" and (news_index < 48 or flow_index < 48):
        signals.append({
            "type": "sell",
            "strength": 0.5 - velocity*0.3,
            "reason": "方向向下，配合负面新闻或资金流出",
            "time_horizon": "short_term"
        })

    # 规则5: 减仓 - 高压力状态（不管理方向）
    if stress_level == "high":
        signals.append({
            "type": "reduce",
            "strength": 0.6,
            "reason": "高杠杆压力/清算风险/叙事过热，建议降低仓位",
            "time_horizon": "risk_management"
        })

    # 规则6: 持有（默认）
    if not signals:
        signals.append({
            "type": "hold",
            "strength": 0.3,
            "reason": "信号不明朗，建议观望",
            "time_horizon": "observation"
        })

    return signals
```

### 2.6 压力测试/风险检测规则

```python
leveraged_stress_level = "high" if (
    (funding_rate > 0.0005 AND oi_increasing_pct > 5)  # 多头过热
    OR (funding_rate < -0.0005 AND oi_increasing_pct < -5)  # 空头过热
    OR narrative_heat > 0.8  # 叙事过热（情绪极端）
    OR fear_greed_index > 75  # 贪婪
    OR fear_greed_index < 25  # 恐慌
    OR liquidation_24h / total_oi > 0.05  # 高清算
) else "medium" if (
    (|funding_rate| > 0.0003)
    OR narrative_heat > 0.6
    OR fear_greed_index > 65 or fear_greed_index < 35
) else "low"
```

### 2.7 API 接口设计（简化版）

```
GET /api/fundamental/latest          → 当前完整快照（含交易信号）
GET /api/fundamental/timeline?days=7 → 最近7天时间序列
GET /api/fundamental/resistance_3d  → 最小阻力三维度
GET /api/fundamental/narrative       → 叙事热度排名
GET /api/fundamental/signals        → 仅交易信号
POST /api/fundamental/refresh       → 强制刷新数据（调用Tavily等）
```

### 2.8 前端渲染建议（Dashboard V2）

```
┌────────────────────────────────────────────────────────┐
│                  基本面分析 Dashboard                    │
├────────────────────────────────────────────────────────┤
│  [最小阻力三维罗盘]                                      │
│  ┌──────────┐  方向: 🔴 向上 (0.65)                     │
│  │    ↑     │  速度: 🟡 中等 (0.42)                      │
│  │   / \    │  加速度: 🟢 增强 (0.18)                    │
│  │  /   \   │  置信度: 72%                               │
│  │ /     \  │                                          │
│  └──────────┘  综合判断: 趋势向上且在加速 (Bullish)       │
│                                                           │
│  [时间线图表 - 最近7天 方向得分曲线]                       │
│  +------------------------------------------------+     │
│  |    ████                                       |     │
│  |   ████████                                    |     │
│  |  ███████████  ← 当前值0.65                    |     │
│  |         ████                                  |     │
│  |             ███                              |     │
│  +------------------------------------------------+     │
│                                                           │
│  [资金流 / 新闻情绪 双指标面板]                           │
│  ┌──────────────┐  ┌──────────────┐                     │
│  │ 资金流指数 58 │  │ 新闻情绪 62  │                     │
│  │ 正面偏多     │  │ 利多新闻主导 │                     │
│  └──────────────┘  └──────────────┘                     │
│                                                           │
│  [叙事热度TOP3]                                           │
│  1. ETF/机构 🔥 热度 0.78 情绪 +0.65                       │
│  2. 监管政策 ⚠️ 热度 0.55 情绪 -0.30                       │
│  3. 宏观金融 📊 热度 0.48 情绪 +0.40                       │
│                                                           │
│  [交易信号卡片]                                           │
│  ┌──────────────────────────────────────────┐           │
│  │ 🔵 STRONG BUY | 强度 0.75                │           │
│  │ 方向向上+速度正向+加速度正向              │           │
│  │ 新闻与资金流双重确认                       │           │
│  │ 建议时间范围: 中期 (1-4周)                │           │
│  └──────────────────────────────────────────┘           │
│                                                           │
│  [风险管理: 低压力]                                        │
│  资金费率正常 | OI稳定 | 恐慌贪婪指数 58（中性）           │
└────────────────────────────────────────────────────────┘
```

---

## 三、改造实施计划

### Phase 1: 数据采集层（1-2天）
- 重写 `tavily_news_crawler.py`：简化新闻分类到6-8个核心类别
- 重写 `flow_signal_collector.py`：移除复杂代理，仅保留核心3-5个信号源
- 实现 `market_data_fetcher.py`：简化价格/费率/OI数据

### Phase 2: 核心计算引擎（2-3天）
- ✅ 实现 `least_resistance.py`：方向/速度/加速度三维计算
- ✅ 实现 `narrative_engine.py`：叙事热度+情绪简化版
- ✅ 实现 `signal_generator.py`：买卖信号生成规则

### Phase 3: API & 前端（1-2天）
- 重写 `ml_trade_service.py`：简化路由，返回结构化JSON
- 更新 `FundamentalPanel.tsx`：渲染最小阻力罗盘 + 时间线图表

### Phase 4: 测试与调优（1天）
- 验证信号逻辑合理性
- 压力测试（无数据/部分数据）
- 回测验证（与历史数据对比）

**总估算: 5-8天可完成从原架构到V2的完整迁移**

---

## 四、保留的原架构精华 vs 删除的冗余

| 保留精华 | 删除冗余 |
|---------|---------|
| 三层信号计算框架（外生/杠杆/链上） | 15+个数据源的复杂代理fallback链 |
| 时间衰减权重计算 | Polymarket/OKX Market Intel等额外API |
| bull/bear/neutral regime分类 | 过于细致的10+叙事分类合并到6个 |
| 新闻情绪加权算法 | web3_skill_snapshot多层代理映射 |
| risk_off风险检测 | backfill/suspect/missing复杂数据质量管理 |

---

## 五、关键指标定义（便于监控）

```
每日监控指标:
1. direction_score 稳定性（连续3天同向 = 趋势确认）
2. velocity 符号变化（从正转负 = 趋势消退）
3. acceleration 符号变化（从正转负 = 趋势反转前信号）
4. news_index vs flow_index 分歧度（>20 = 市场分化，谨慎）
5. narrative_heat > 0.8 = 情绪过热（警惕反转）

信号准确率回测指标:
- strong_buy信号后，未来7天BTC上涨概率
- strong_sell信号后，未来7天BTC下跌概率
- stress_level=high触发后，未来3天最大回撤
```
