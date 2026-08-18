---
name: dream-first-principles
description: |
  🧠 第一性原理分析 — 战略制定的哲学根基
  基于"市场总是沿着阻力最小方向运行"和"趋势具有延续性"两大原理，
  深度分析当前市场状态，推演阻力来源与趋势动力。
  触发词：第一性原理、阻力最小、趋势分析、动力分析、市场本质、分析完成请顾问评审、宏观资产、黄金、原油、铜
license: Internal
version: 2.6.1
created: 2026-04-20
updated: 2026-05-07
---

# 🧠 Dream-First-Principles: 第一性原理分析部 (v2.6.1)

> **核心**: 用左右脑科学方法，进行基本面×技术面的双维度分析，**借助A0矛盾论抓住主要矛盾**。

---

## 核心理论框架

### 原理1: 阻力最小路径 (Least Resistance Path)
> 市场如同流水，总是从阻力最小的地方通过

**阻力来源分解**:
| 阻力类型 | 量化指标 | 来源 |
|:---|:---|:---|
| 成本摩擦 | costs.total_cost_bps, spread_bps | OKX订单簿 |
| 流动性摩擦 | depth_1pct_usdt, orderbook_imbalance | OKX订单簿 |
| 拥挤摩擦 | funding_rate, oi_delta_pct | OKX |
| 波动摩擦 | atr_pct, vol_regime | 技术指标 |

### 原理2: 趋势延续性 (Trend Continuation)
> 趋势一旦形成，会延续直到遇到足够的反向阻力

**趋势阶段**: 启动期 → 加速期 → 衰竭期 → 逆转/盘整

---

## ⚡ 双维度分析框架

### 维度一：基本面分析 (Fundamental Analysis)

> **核心问题**: 什么因素驱动资金流动？

#### 1.1 资金流分析

```
┌─────────────────────────────────────────────────────────────┐
│                        资金流金字塔                          │
├─────────────────────────────────────────────────────────────┤
│  L1: 宏观流动性                                              │
│  ├── 美联储资产负债表                                         │
│  ├── 全球央行政策 (利率/QE/QT)                               │
│  └── 美元指数 DXY                                             │
├─────────────────────────────────────────────────────────────┤
│  L2: 中观资金流向                                            │
│  ├── BTC ETF净流入/流出 (主力数据源)                         │
│  ├── 合约持仓量 OI 变化                                      │
│  └── 链上交易所净流入/流出                                   │
├─────────────────────────────────────────────────────────────┤
│  L3: 微观流动性                                              │
│  ├── 订单簿深度 (买卖盘厚度)                                 │
│  ├── 买卖价差 spread                                         │
│  └── 大单成交密度                                            │
└─────────────────────────────────────────────────────────────┘
```

**量化指标**:
| 层级 | 指标 | 正向信号 | 负向信号 |
|:---|:---|:---|:---|
| L1宏观 | DXY变化率 | DXY下跌 | DXY上涨 |
| L1宏观 | 全球流动性 | 扩张 | 收缩 |
| L2 ETF | ETF净流入 | >$1亿/日 | <-$1亿/日 |
| L2 OI | OI变化率 | 增仓+价格上涨 | 增仓+价格下跌 |
| L3微观 | 订单簿深度 | >$10M depth | <$5M depth |
| L3微观 | Spread | <5bps | >20bps |

#### 1.2 情绪指标分析

```
┌─────────────────────────────────────────────────────────────┐
│                      情绪温度计                              │
├─────────────────────────────────────────────────────────────┤
│  Fear & Greed Index: 0-100                                  │
│  ├── 0-25: 极度恐惧 → 潜在买入机会                          │
│  ├── 25-50: 恐惧 → 观望                                     │
│  ├── 50-75: 贪婪 → 谨慎                                     │
│  └── 75-100: 极度贪婪 → 潜在卖出机会                        │
├─────────────────────────────────────────────────────────────┤
│  资金费率 (Funding Rate):                                   │
│  ├── >0.05%: 多头拥挤 → 反转风险                           │
│  ├── <-0.05%: 空头拥挤 → 轧空风险                          │
│  └── ±0.01%: 中性                                           │
├─────────────────────────────────────────────────────────────┤
│  多空比 (Long/Short Ratio):                                │
│  ├── >1.2: 多头主导                                         │
│  └── <0.8: 空头主导                                         │
└─────────────────────────────────────────────────────────────┘
```

#### 1.3 地缘政治分析

> **数据源**: Tavily搜索地缘新闻（默认），Odaily补充

| 地缘因素 | BTC影响 | 权重 |
|:---|:---|:---|
| 中东冲突 (霍尔木兹) | 正相关 (避险) | 0.15 |
| 中美关系 | 负相关 | 0.10 |
| 俄乌战争 | 中性 | 0.05 |
| 美联储政策 | 强相关 | 0.20 |

**判断规则**:
- 地缘紧张 ↑ → BTC可能上涨 (避险需求)
- 地缘缓和 ↓ → BTC可能承压
- **异常**: 地缘紧张但BTC不涨 → 警惕反转

#### 1.4 政策金融刺激分析

| 政策类型 | 市场影响 | 持续性 |
|:---|:---|:---|
| 降息/QE | 利好风险资产 | 中期 |
| 加息/QT | 利空风险资产 | 中期 |
| BTC ETF批准 | 强利好 | 长期 |
| 监管政策 | 短期波动 | 短期 |

---

### 维度二：技术面分析 (Technical Analysis)

> **数据来源**: 主要来自A1调研报告 + technical-analyst SKILL

#### 2.1 趋势指标

| 指标 | 参数 | 信号逻辑 |
|:---|:---|:---|
| EMA | 20/60/120 | 多头排列(做多)、空头排列(做空) |
| MA | 5/10/20 | 价格穿越均线确认趋势 |
| 趋势斜率 | - | 斜率>0上涨、<0下跌 |

**MA趋势轨迹**:
```
MA处理逻辑:
1. 计算MA(5,10,20,60)序列
2. 检测MA交叉 (Golden Cross / Death Cross)
3. 计算MA斜率变化率
4. 趋势轨迹 = Σ(MA斜率 × 权重)
5. 趋势强度 = |趋势轨迹| / 历史标准差
```

#### 2.2 动量指标

| 指标 | 参数 | 信号逻辑 |
|:---|:---|:---|
| RSI | 14 | >70超买、<30超卖 |
| MACD | 12/26/9 | 金叉/死叉、柱状图背离 |
| Stochastic | 14/3/3 | %K穿越%D |

**RSI超卖反弹识别** (来自做梦部洞察):
- RSI < 25 → 超卖区域，反弹概率 > 70%
- RSI < 20 → 极度超卖，反弹概率 > 85%
- **注意**: 系统可能忽视此信号，需醒目标注

#### 2.3 波动指标

| 指标 | 参数 | 信号逻辑 |
|:---|:---|:---|
| ATR | 14 | 波动率放大/收缩 |
| Bollinger | 20/2 | 触及上下轨突破/回归 |
| 波动率压缩 | - | 极度压缩后放大 |

#### 2.4 支撑阻力

| 类型 | 识别方法 | 信号 |
|:---|:---|:---|
| 支撑位 | 历史低点/EMA50 | 反弹概率高 |
| 阻力位 | 历史高点/EMA20 | 突破/回调 |
| 关键心理位 | 整数关口 | $70K/$80K等 |

---

### 维度二点五：宏观资产分析 (v2.6 新增 ⚖️)

> **核心**: 宏观资产（黄金/原油/铜/股票）与BTC的共振/背离，是重要的趋势确认/反转信号
> **数据来源**: OKX API (SWAP合约) + A6监控系统

#### 2.5.1 宏观资产池

| 资产 | instId | 类别 | 与BTC相关性 | 典型信号 |
|:---|:---|:---|:---|:---|
| 黄金 (Gold) | `XAU-USDT-SWAP` | 商品 | 负相关（避险） | 黄金涨+BTC跌=避险模式 |
| 原油 (Oil) | `CL-USDT-SWAP` | 商品 | 弱相关 | 原油涨→通胀预期→BTC承压 |
| 铜 (Copper) | `XCU-USDT-SWAP` | 商品 | 正相关（工业需求） | 铜涨+BTC涨=风险偏好上升 |
| TSLA | `TSLA-USDT-SWAP` | 股票 | 正相关（科技股） | TSLA涨+BTC涨=科技牛市 |
| COIN | `COIN-USDT-SWAP` | 股票(加密) | 强正相关 | COIN涨→加密板块轮动 |

#### 2.5.2 共振信号识别

```
共振信号类型:
├── INFLATION_EXPECTATION (通胀预期)
│   ├── 触发: 黄金↑ + BTC↑ 同时发生
│   ├── 含义: 通胀预期升温，资金流入硬资产
│   └── 行动: 可考虑加仓BTC多单
│
├── RISK_OFF (风险规避)
│   ├── 触发: 黄金↑ + BTC↓ 同时发生
│   ├── 含义: 避险情绪主导，资金流出风险资产
│   └── 行动: 考虑减仓或做空BTC
│
├── RISK_ON (风险偏好)
│   ├── 触发: 黄金↓ + TSLA↑ + BTC↑
│   ├── 含义: 风险偏好上升，资金流入成长资产
│   └── 行动: 可考虑加仓BTC多单
│
├── INDUSTRY_BETA_CONFIRM (行业Beta确认)
│   ├── 触发: COIN↑ + BTC↑ 同时发生
│   ├── 含义: 加密行业整体向好，Beta行情
│   └── 行动: 可考虑加仓BTC或轮动到COIN
│
├── STAGFLATION_FEAR (滞胀恐慌) ← v4.2 新增
│   ├── 触发: 原油↑ + 铜↓ 同时发生
│   ├── 含义: 通胀+经济衰退预期，最差宏观组合
│   └── 行动: 考虑减仓风险资产，增持黄金
│
└── CORRELATION_BREAK (相关性断裂) ← v4.2 新增
    ├── 触发: 黄金与BTC同时段方向相反且持续>4小时
    ├── 含义: 传统相关性失效，可能有新叙事
    └── 行动: 暂停基于宏观共振的策略，重新评估
```

#### 2.5.3 背离分析

| 背离类型 | 检测方法 | 含义 | 建议行动 |
|:---|:---|:---|:---|
| BTC vs 黄金背离 | BTC↑ 但黄金↑ (同涨) | 可能通胀驱动，非避险 | 观察是否有持续资金流入 |
| BTC vs 铜背离 | BTC↑ 但铜↓ | 需求预期差，BTC上涨可能不可持续 | 考虑减仓或SET加强止损 |
| BTC vs TSLA背离 | BTC↑ 但TSLA↓ | 科技股承压，BTC上涨可能独立叙事 | 分析BTC独立上涨原因 |
| 宏观资产内部背离 | 黄金↑ + 原油↑ + 铜↓ | 复杂宏观环境，滞胀+衰退预期混合 | 降低仓位，等待方向明确 |

#### 2.5.4 宏观资产趋势分析

```
宏观资产趋势评分 = Σ(资产趋势得分 × 相关性权重 × 趋势强度)

评分规则:
├── 黄金趋势: MA20>MA60 → +1分; RSI>50 → +1分
├── 原油趋势: MA20>MA60 → -0.5分 (负相关); RSI>50 → -0.5分
├── 铜趋势: MA20>MA60 → +0.5分 (正相关); RSI>50 → +0.5分
├── TSLA趋势: MA20>MA60 → +0.5分; RSI>50 → +0.5分
└── COIN趋势: MA20>MA60 → +1分; RSI>50 → +1分 (强正相关)

总分解读:
├── 总分 > 3: 宏观环境强烈支持BTC上涨
├── 总分 0-3: 宏观环境中性，技术分析权重增加
└── 总分 < 0: 宏观环境不支持BTC上涨，谨慎做多
```

#### 2.5.5 数据获取方式

```bash
# 黄金
okx market ticker XAU-USDT-SWAP --profile dreamdemo

# 原油
okx market ticker CL-USDT-SWAP --profile dreamdemo

# 铜
okx market ticker XCU-USDT-SWAP --profile dreamdemo

# TSLA
okx market ticker TSLA-USDT-SWAP --profile dreamdemo

# COIN
okx market ticker COIN-USDT-SWAP --profile dreamdemo

# 批量查询（写入A6监控）
okx market ticker XAU-USDT-SWAP XCU-USDT-SWAP CL-USDT-SWAP TSLA-USDT-SWAP COIN-USDT-SWAP --profile dreamdemo
```

---

## 🧬 左右脑科学分析方法

> **核心**: 左脑处理确定性规则，右脑处理模糊性判断，两者辩证统一

### 左脑分析器 (确定性量化)

```
┌─────────────────────────────────────────────────────────────┐
│                    左脑: 确定性量化                          │
├─────────────────────────────────────────────────────────────┤
│  输入: 可量化的硬数据                                         │
│  ├── 资金流: ETF净流入$、OI变化%                            │
│  ├── 价格: 收盘价、涨跌幅                                    │
│  ├── 技术指标: RSI、MACD、EMA具体数值                       │
│  └── 宏观数据: 利率、CPI、GDP                               │
│                                                              │
│  处理: 确定性规则引擎                                         │
│  ├── IF RSI>70 AND 资金费率>0.05% → 超买信号               │
│  ├── IF EMA20>EMA60 AND 价格>EMA20 → 趋势向上              │
│  └── IF ETF净流入>$5亿 AND 多头主导 → 资金面利好           │
│                                                              │
│  输出: 精确的概率值和阈值判断                                  │
│  ├── score: 0-100 精确得分                                  │
│  ├── direction: UP/DOWN/NEUTRAL                            │
│  └── confidence: 0.0-1.0 置信度                            │
└─────────────────────────────────────────────────────────────┘
```

**左脑量化规则库**:
| 条件 | 得分 | 方向 |
|:---|:---:|:---:|
| RSI > 70 | -20 | DOWN |
| RSI < 30 | +20 | UP |
| EMA20 > EMA60 | +15 | UP |
| ETF净流入 > $5亿 | +25 | UP |
| 资金费率 > 0.05% | -15 | DOWN |
| OI增仓 + 价格上涨 | +20 | UP |

### 右脑分析器 (模糊性判断)

```
┌─────────────────────────────────────────────────────────────┐
│                    右脑: 模糊性模式识别                       │
├─────────────────────────────────────────────────────────────┤
│  输入: 非结构化的软信息                                       │
│  ├── 新闻语气 (看涨/看跌/中性)                               │
│  ├── 社区情绪 (Twitter、Reddit讨论热度)                      │
│  ├── K线形态 (头肩顶、三角形、旗形)                         │
│  └── 市场共识与分歧程度                                      │
│                                                              │
│  处理: 模糊模式匹配                                           │
│  ├── 形态识别: "最近走势像2024年3月的上涨"                  │
│  ├── 情绪极值: "Twitter一片看涨声" → 警惕反转              │
│  ├── 机构观点: 多空分歧比例                                  │
│  └── 异常信号: 被左脑忽视的RSI超卖等                        │
│                                                              │
│  输出: 定性的方向判断和置信区间                               │
│  ├── bias: BULLISH/BEARISH/NEUTRAL                         │
│  ├── confidence_interval: [悲观, 基准, 乐观]                 │
│  └── pattern_quality: 高/中/低                               │
└─────────────────────────────────────────────────────────────┘
```

**右脑模式识别**:
| 模式 | 识别特征 | 推断 |
|:---|:---|:---|
| 头肩顶 | 高点递减、低点不破 | 看跌 |
| 旗形整理 | 急涨后横盘 | 延续上涨 |
| 双底 | 两次探底不破 | 看涨反转 |
| 杯柄形态 | U型+回调 | 中期上涨 |

### 辩证统一：A0矛盾论 + 左右脑分析 (v2.4 重构 ⚖️)

```
┌─────────────────────────────────────────────────────────────┐
│              A0矛盾论 + 左右脑辩证统一 (v2.4)                │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│   A1矛盾清单 ──→ A0 Step2: 4维评分 → 主要矛盾排名           │
│                                                              │
│   左脑结论 ──┐                                               │
│              ├──→ A0增强的辩证统一                             │
│   右脑结论 ──┘                       │                       │
│                                    │                        │
│   处理规则 (v2.4):                   │                        │
│   ├── 1. 先用A0确定主要矛盾及其主要方面                      │
│   │   └── 主要矛盾主要方面 = 优先方向                        │
│   ├── 2. 左右脑与A0方向对比                                   │
│   │   ├── 三者一致 → 高置信，标准仓位                        │
│   │   ├── 左右脑一致但与A0相反 → 取A0(A0基于7维全面分析)    │
│   │   └── 左右脑分歧 → 取A0方向 + 降低置信度                 │
│   ├── 3. 矛盾处理2.0 保留                                    │
│   │   └── 但矛盾的"主导方向"现在由A0的4维评分法确定          │
│   └── 4. 被压制信号(C7)                                      │
│       └── 做梦产物纳入A0的C7维度，不再独立处理               │
│                                                              │
│   主要矛盾输出 (A0增强):                                      │
│   ├── primary_contradiction: 主要矛盾描述                    │
│   ├── contradiction_ranking: 排名(基于4维评分)               │
│   ├── dominant_side: A|B (决定方向)                          │
│   ├── direction_implication: UP|DOWN                        │
│   ├── transformation_condition: 转化条件                     │
│   ├── secondary_contradiction: 次要矛盾描述                  │
│   └── 建议: 顺着主要矛盾方向行动                             │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

**权重动态调整规则**:
```
IF 主要矛盾 == "资金外流"
   THEN 基本面权重 += 20%
   THEN 技术面权重 -= 20%

IF 主要矛盾 == "技术超卖+基本面支撑"
   THEN 技术面权重 += 15%
   THEN 标注"反弹概率上升"

IF 左脑与右脑冲突
   THEN 输出矛盾标记
   THEN 降低综合置信度
   THEN 【v2.3 修复】执行矛盾处理2.0（见下方），禁止直接输出"等待方向明确"
```

### 矛盾处理2.0 (v2.3 新增 ⭐ 核心修复)

> **原问题**: 矛盾→"等待方向明确" → 市场混沌时100%触发 → 永久SKIP循环
> **修复**: 矛盾→"识别主导方向+标注小仓试探建议"

```
矛盾处理流程 (v2.3):
├── Step 1: 识别矛盾强度
│   ├── WEAK: 左右脑方向一致但置信度差异>30%
│   ├── MODERATE: 左右脑方向相反，但一方置信度>60%
│   └── STRONG: 左右脑方向相反，双方置信度均>50%
│
├── Step 2: 判断主导方向（禁止输出"无方向"）
│   ├── WEAK: 取置信度更高的方向
│   ├── MODERATE: 取置信度>60%的方向
│   └── STRONG: 取基本面权重更高的方向（第一性原理：基本面决定长期方向）
│
├── Step 3: 输出矛盾处理结论（必须包含方向）
│   ├── reconciled_direction: UP/DOWN (必有值)
│   ├── confidence: 0.3-0.5 (矛盾时降低但不为零)
│   ├── action_advice: "小仓试探" (非"等待")
│   └── probe_conditions: [试探条件列表]
│
└── Step 4: 禁止事项
    ├── ❌ 禁止输出 direction=NEUTRAL
    ├── ❌ 禁止输出 "等待方向明确"
    ├── ❌ 禁止输出 "建议观望直到矛盾消解"
    └── ✅ 必须输出 "在[条件X]时，可[方向]小仓试探"
```

**矛盾处理示例**:
```
场景: 左脑=UP(55分) vs 右脑=BEARISH(FGI暴跌30点)
处理:
1. 矛盾强度: MODERATE (左脑55>50但右脑也有强信号)
2. 主导方向: UP (左脑量化得分略高)
3. 置信度: 0.4 (矛盾降低)
4. 输出: "矛盾处理: 基本面偏多但情绪偏空。主导方向UP，置信度0.4。
          建议在$76,500支撑企稳时小仓试探做多，止损$75,000。"
```

---

## 📊 最小阻力原理 + 趋势追踪

### 阻力最小路径计算 (v2.3 重构 ⭐)

> **⚠️ v2.3 核心修复**: 原NEUTRAL区间占70%（30-70），导致70%的情况输出"观望"。
> 重构为20%中间带，迫使系统在80%的情况下给出方向性判断。

```
阻力评分 = Σ(阻力分量 × 权重)

分量计算:
├── 成本阻力 = f(手续费, 滑点)
├── 流动性阻力 = f(订单簿深度, 买卖价差)
├── 拥挤阻力 = f(资金费率, OI变化)
└── 波动阻力 = f(ATR, 历史波动率)

路径判定 (v2.3 重构):
├── UP:   阻力评分 < 40        ← 从30提升到40，扩大做多区间
├── DOWN: 阻力评分 > 60        ← 从70降低到60，扩大做空区间
└── NEUTRAL: 40 <= 评分 <= 60  ← 从70%缩窄到20%
```

### 逆向信号补偿机制 (v2.3 新增 ⭐)

> **核心原理**: 当市场情绪极端但资金面中性时，往往孕育反转机会。
> 恐惧+费率平衡 = 空头力竭；贪婪+费率平衡 = 多头力竭。

```
逆向补偿触发条件:
├── 条件A: FGI < 40 (恐惧) AND |资金费率| < 0.01% (费率≈零轴)
│   → 阻力评分 -= 15 (降低向上阻力，倾向UP)
│   → 标注 "逆向补偿: 恐惧+费率平衡=空头力竭"
│
├── 条件B: FGI > 70 (贪婪) AND |资金费率| < 0.01% (费率≈零轴)
│   → 阻力评分 += 15 (增加向上阻力，倾向DOWN)
│   → 标注 "逆向补偿: 贪婪+费率平衡=多头力竭"
│
├── 条件C: FGI 4日变化 > 20点 (剧烈变化)
│   → 阻力评分向变化反方向偏移10
│   → 标注 "逆向补偿: 情绪剧变=假突破风险(L_FGI_001)"
│
└── 补偿上限: ±20分（不可单独将NEUTRAL翻转为UP/DOWN）

补偿与阻力评分叠加示例:
  原始评分=55 (NEUTRAL) + 条件A触发(−15) = 40 → UP边界
  原始评分=45 (UP边界) + 条件C触发(+10) = 55 → NEUTRAL
```

### 趋势追踪：MA轨迹法

> **核心**: 用MA处理逻辑，把点连成线，形成趋势变化轨迹

```
┌─────────────────────────────────────────────────────────────┐
│                    MA趋势轨迹追踪                           │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  Step 1: 计算MA序列                                          │
│  ├── MA5, MA10, MA20, MA60                                  │
│  └── 每个时间点记录MA值                                      │
│                                                              │
│  Step 2: MA趋势因子计算                                      │
│  ├── 短期斜率 = (MA5_t - MA5_t-1) / MA5_t-1                │
│  ├── 中期斜率 = (MA20_t - MA20_t-1) / MA20_t-1             │
│  ├── 长期斜率 = (MA60_t - MA60_t-1) / MA60_t-1             │
│  └── 斜率归一化: 除以历史标准差                              │
│                                                              │
│  Step 3: 趋势轨迹合成                                        │
│  ├── 轨迹 = 0.3×短期斜率 + 0.4×中期斜率 + 0.3×长期斜率   │
│  ├── 轨迹 > 0: 上涨趋势                                      │
│  └── 轨迹 < 0: 下跌趋势                                      │
│                                                              │
│  Step 4: 趋势强度判断                                        │
│  ├── |轨迹| > 2σ: 强趋势                                    │
│  ├── |轨迹| > 1σ: 中趋势                                    │
│  └── |轨迹| < 1σ: 盘整/弱趋势                               │
│                                                              │
│  Step 5: 趋势拐点检测                                        │
│  ├── 轨迹由负转正: Golden Cross → 买入信号                   │
│  └── 轨迹由正转负: Death Cross → 卖出信号                   │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### 历史统计 + 数学验证

> **理论不是理论，是数学统计+观察+经验的综合**

```
数据驱动验证:
├── 历史回测: 特定MA组合的历史胜率
├── 统计显著性: p-value检验趋势信号有效性
├── 样本外验证: 用非训练期间数据验证
└── 置信区间: 给出趋势判断的上下界

经验权重:
├── 牛市经验: 下跌趋势中RSI<30更可靠
├── 熊市经验: 反弹往往是卖出机会
└── 震荡市: 区间上下沿操作更有效
```

---

## 输入（必须字段）

| 字段 | 类型 | 来源 | 说明 |
|:---|:---|:---|:---|
| `research_report` | object | A1调研报告 | 完整情报简报(含三角准则结果) |
| `market_state` | object | A1 | 当前市场状态 |
| `macro_snapshot` | object | A1 | 宏观环境 |
| `dream_insights` | object | A1 | 做梦部洞察(可选) |

---

## 输出（必须结构化）

```json
{
  "first_principles_analysis": {
    "dual_dimension_analysis": {
      "fundamental": {
        "capital_flow": {
          "macro_liquidity": { "direction": "EXPAND|CONTRACT", "score": 0-100 },
          "etf_flow": { "direction": "INFLOW|OUTFLOW", "score": 0-100, "amount": "$X亿" },
          "oi_change": { "direction": "UP|DOWN", "score": 0-100 },
          "micro_liquidity": { "depth": "$X", "spread": "Xbps" }
        },
        "sentiment": {
          "fear_greed": 0-100,
          "funding_rate": "X%",
          "long_short_ratio": "X",
          "signal": "BULLISH|BEARISH|NEUTRAL"
        },
        "geopolitical": {
          "key_events": ["事件列表"],
          "impact": "POSITIVE|NEGATIVE|NEUTRAL",
          "weight": 0-1
        },
        "policy": {
          "central_bank": "EASING|TIGHTENING|NEUTRAL",
          "regulatory": "POSITIVE|NEGATIVE|NEUTRAL"
        },
        "synthesis": {
          "fundamental_direction": "BULLISH|BEARISH|NEUTRAL",
          "fundamental_score": 0-100,
          "confidence": 0.0-1.0
        }
      },
      "technical": {
        "trend_indicators": {
          "ema_alignment": "BULLISH|BEARISH|MIXED",
          "ma_slopes": { "short": "X%", "medium": "X%", "long": "X%" },
          "ma_trajectory": "UP|DOWN|NEUTRAL",
          "trajectory_strength": 0-100
        },
        "momentum": {
          "rsi": 0-100,
          "rsi_state": "OVERBOUGHT|OVERSOLD|NEUTRAL",
          "macd": { "signal": "GOLDEN_CROSS|DEATH_CROSS|NEUTRAL" },
          "stochastic": "X%"
        },
        "volatility": {
          "atr": "X%",
          "atr_state": "HIGH|LOW|NORMAL",
          "bollinger_position": "X%"
        },
        "support_resistance": {
          "key_levels": ["$70K", "$75K"],
          "nearest_support": "$X",
          "nearest_resistance": "$X"
        },
        "synthesis": {
          "technical_direction": "BULLISH|BEARISH|NEUTRAL",
          "technical_score": 0-100,
          "confidence": 0.0-1.0
        }
      },
      "cross_dimension": {
        "alignment": "SAME|OPPOSITE|MIXED",
        "synthesis_confidence": 0.0-1.0
      }
    },
    "macro_asset_analysis": {                           ← v2.6 新增 (宏观资产分析) ⚖️
      "assets": [
        {
          "inst_id": "XAU-USDT-SWAP",
          "name": "黄金",
          "price": 2350.50,
          "ma_trend": "UP",
          "correlation_with_btc": "NEGATIVE",
          "signal_to_btc": "黄金涨→BTC可能面临避险资金流出"
        },
        {
          "inst_id": "CL-USDT-SWAP",
          "name": "原油",
          "price": 78.50,
          "ma_trend": "DOWN",
          "correlation_with_btc": "WEAK",
          "signal_to_btc": "原油跌→通胀预期降低→BTC可能受益"
        }
      ],
      "resonance_signals": [
        {
          "signal_type": "INFLATION_EXPECTATION",
          "description": "黄金↑ + BTC↑ 同时发生",
          "assets_involved": ["XAU-USDT-SWAP", "BTC-USDT-SWAP"],
          "direction_implication": "UP",
          "strength": "STRONG",
          "action_suggestion": "可考虑加仓BTC多单"
        }
      ],
      "divergence_detected": false,
      "divergence_details": [],
      "macro_trend_score": 0-10,
      "macro_trend_interpretation": "宏观环境强烈支持BTC上涨",
      "summary": "宏观资产分析摘要"
    },
    "brain_analysis": {
      "left_brain": {
        "quantitative_signals": [...],
        "deterministic_score": 0-100,
        "direction": "UP|DOWN|NEUTRAL"
      },
      "right_brain": {
        "pattern_recognition": [...],
        "fuzzy_bias": "BULLISH|BEARISH|NEUTRAL",
        "confidence_interval": [pessimistic, base, optimistic]
      },
      "contradiction": {
        "detected": true|false,
        "left_vs_right": "LEFT_DOMINANT|RIGHT_DOMINANT|SYNTHESIZED",
        "contradiction_strength": "WEAK|MODERATE|STRONG",  ← v2.3 新增
        "reconciled_direction": "UP|DOWN",                  ← v2.3 新增（必有值）
        "action_advice": "小仓试探|跟踪确认",               ← v2.3 新增
        "probe_conditions": ["条件1", "条件2"]             ← v2.3 新增
      },
      "main_contradiction": {
        "primary": "主要矛盾描述",
        "secondary": "次要矛盾描述",
        "weight_adjustment": { "fundamental": "X%", "technical": "X%" }
      },
      "a0_contradiction_analysis": {                    ← v2.4 新增 (A0集成) ⚖️
        "primary_contradiction": {
          "id": "CX_001",
          "dimension": "C1",
          "description": "主要矛盾描述",
          "dominant_side": "A|B",
          "direction_implication": "UP|DOWN",
          "confidence": 0.65,
          "transformation": {
            "condition": "转化条件描述",
            "probability": "LOW|MODERATE|HIGH"
          }
        },
        "contradiction_ranking": [
          {"id": "CX_001", "score": 4.85, "rank": 1},
          {"id": "CX_003", "score": 3.20, "rank": 2}
        ],
        "action_pressure_from_a1": {                                 ← v2.5 新增(Q3-P1修复) ⚖️
          "consecutive_skip_days": 7,
          "pressure_level": "HIGH|MODERATE|LOW",
          "source": "A1.action_pressure字段",
          "impact_on_direction": "HIGH压力时，方向权重+15%",
          "constraint": "HIGH压力→A3禁止WAIT，必须PROBE"
        }
      }
    },
    "resistance_analysis": {
      "resistance_score": 0-100,
      "resistance_direction": "UP|DOWN|NEUTRAL",
      "resistance_components": {
        "cost_friction": { "score": 0-100, "weight": 0.30 },
        "liquidity_friction": { "score": 0-100, "weight": 0.35 },
        "crowding_friction": { "score": 0-100, "weight": 0.20 },
        "vol_friction": { "score": 0-100, "weight": 0.15 }
      },
      "resistance_minimum_path": "UP|DOWN|NEUTRAL",
      "resistance_confidence": 0.0-1.0,
      "contrarian_compensation": {                    ← v2.3 新增
        "triggered": true|false,
        "condition": "FGI<40+费率平衡|FGI>70+费率平衡|FGI剧变",
        "adjustment": -15|+15|-10|+10,
        "original_score": 55,
        "adjusted_score": 40
      }
    },
    "trend_analysis": {
      "ma_trajectory_method": {
        "ma_slopes": { "MA5": "X%", "MA20": "X%", "MA60": "X%" },
        "trajectory_value": "X",
        "trajectory_normalized": "Xσ",
        "trend_strength": "STRONG|MODERATE|WEAK"
      },
      "trend_phase": "启动期|加速期|衰竭期|逆转|盘整",
      "trend_direction": "BULL|BEAR|NEUTRAL",
      "trend_strength": 0-10,
      "trend_momentum": "accelerating|stable|decelerating",
      "trend_confidence": 0.0-1.0,
      "historical_stats": {
        "similar_patterns": 3,
        "success_rate": "X%",
        "avg_reversal_point": "$X"
      }
    },
    "synthesis": {
      "least_resistance_path": "UP|DOWN|NEUTRAL",
      "path_confidence": 0.0-1.0,
      "contradictions": ["矛盾1"],
      "action_recommendation": "PROBE_LONG|PROBE_SHORT|WAIT|HOLD",  ← v2.3 新增
      "action_rationale": "为什么建议此行动",                        ← v2.3 新增
      "alternative_scenarios": [
        { "scenario": "乐观", "probability": 0.25, "condition": "..." },
        { "scenario": "基准", "probability": 0.50, "condition": "..." },
        { "scenario": "悲观", "probability": 0.25, "condition": "..." }
      ]
    }
  },
  "market_regime_classification": {
    "regime": "TREND_STRONG|TREND_EXHAUSTION|RANGE_BOUND|BREAKOUT_PENDING|FALSE_BREAKOUT_RISK|EXTREME",
    "confidence": 0.0-1.0,
    "signals": ["信号1", "信号2"]
  },
  "meta": {
    "analysis_id": "string",
    "version": "2.0.0",
    "timestamp": "ISO时间戳",
    "left_right_brain_integrated": true,
    "ma_trajectory_method": true
  }
}
```

---

## ⚡ A0 强制调度门禁 (P0 Fix v2.6)

> **⚠️ 强制执行**: 本SKILL必须在执行第一阶段前首先调用A0矛盾论
> 
> **执行顺序不可跳过**: Phase 0 → Phase 1 → Phase 2 → ...

### Phase 0: A0矛盾论强制调用

**必须首先执行以下操作：**

```python
# Step 0.1: 调用A0矛盾论SKILL
use_skill("dream-contradiction-theory")

# Step 0.2: 将A0输出作为第一性原理分析的框架约束
a0_framework = {
    "contradiction_theory": "...",     # A0矛盾论方法论
    "seven_dimensions": [...],         # C1-C7矛盾维度框架
    "iron_laws": [...],                # A0五大铁律
    "methodology_guide": "..."        # A0分析方法指导
}
```

**门禁检查清单（必须逐项确认）：**
- [ ] `use_skill("dream-contradiction-theory")` 已执行
- [ ] A0矛盾论方法论已纳入分析框架
- [ ] Phase 3的A0矛盾分析使用A0的实际输出
- [ ] 报告中明确引用A0的矛盾论指导

**违规处理**: 若跳过Phase 0，报告将标记为`a0_integration=FAILED`，A8将发出P0告警

---

## 执行流程

```
Phase 0: A0强制调度门禁 (新增 v2.6) ⚠️
├── [P0] use_skill("dream-contradiction-theory")
├── [P0] 获取A0矛盾论方法论作为分析框架
└── [P0] 门禁检查清单确认

Phase 1: 基本面分析 (5min)
├── 1.1 资金流分析 (L1宏观/L2中观/L3微观)
├── 1.2 情绪指标分析
├── 1.3 地缘政治分析 (Tavily搜索)
└── 1.4 政策金融刺激分析

Phase 2: 技术面分析 (5min)
├── 2.1 趋势指标 (EMA/MA斜率)
├── 2.2 动量指标 (RSI/MACD/Stochastic)
├── 2.3 波动指标 (ATR/Bollinger)
└── 2.4 支撑阻力识别

Phase 3: 左右脑辩证 + A0抓住矛盾 (5min) ← v2.4 升级
├── Step 1: A0矛盾分析 — 从A1的contradiction_list中抓住主要矛盾 ⚖️
│   ├── 4维评分法: 力量对比+时间紧迫性+证据一致性+市场影响权重
│   ├── 识别主要矛盾: 综合得分最高的矛盾对
│   ├── 识别矛盾的主要方面: dominance_score → 决定方向(UP/DOWN)
│   └── 判断矛盾转化可能性: 转化条件+概率评估
├── 左脑: 确定性规则量化
├── 右脑: 模糊性模式识别
└── 辩证统一: 左右脑结论 + A0主要矛盾 → 最终方向

Phase 4: 阻力分析 (5min)
├── 成本摩擦: f(spread_bps, total_cost_bps)
├── 流动性摩擦: f(depth, orderbook_imbalance)
├── 拥挤摩擦: f(funding_rate, oi_delta_pct)
└── 波动摩擦: f(atr_pct, vol_regime)

Phase 5: 趋势追踪 - MA轨迹法 (5min)
├── 5.1 计算MA序列
├── 5.2 计算MA斜率
├── 5.3 合成趋势轨迹
├── 5.4 历史统计验证
└── 5.5 趋势拐点检测

Phase 6: 综合推演 (3min)
├── IF 阻力最小路径 == 趋势方向 → 同向强化
├── ELIF 阻力最小路径 != 趋势方向 → 方向冲突
└── 生成3种情景: 基准/乐观/悲观

Phase 7: Regime分类 (2min)
└── 基于分析结果分类

Phase 8: 顾问评审 (新增 v2.1) ⭐
├── 识别评审类型（宏观/趋势）
├── 选择顾问组合 (MR + TR)
├── 召唤顾问评审
├── 汇总评审结论
└── 写入待处理邮箱 (pending_tasks/inbox/)
```

---

## Phase 8: 顾问评审流程 (v2.5 更新)

> **⚠️ 宪法强制**: A2分析完成后必须召唤顾问评审，评审结论内嵌到报告中（不单独投递到pending_tasks/inbox/）。
>
> **⚠️ v2.5 架构变更**: 顾问评审从"异步分发-等待"改为 **内联同步调用**，使用 `advisor_direct_call` 模块。

### 8.0 调用方式（v2.5 新增）

```python
# 导入方式
import sys
sys.path.insert(0, str(Path.home() / ".workbuddy" / "advisor-team" / "shared"))
from advisor_direct_call import advisors_review

# A2 调用示例
result = advisors_review(
    consultation_id=f"A2-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    scene="MACRO_ANALYSIS",  # 按8.1识别的类型选择
    required_advisors=["advisor-mr", "advisor-tr"],  # 宏观+趋势双视角
    context={
        "least_resistance_path": "UP/DOWN/NEUTRAL",
        "trend_analysis": { "direction": "BULL/BEAR/NEUTRAL" },
        "market_regime": "TREND/RANGE/BREAKOUT",
        "key_findings": [ ... ],  # A2核心发现
    },
    source="dream-first-principles"
)

verdict = result["summary"]["final_verdict"]
confidence = result["summary"]["avg_confidence"]
```

### 8.1 评审类型识别

| 评审类型 | 判断条件 | 顾问组合 |
|:---------|:---------|:---------|
| **宏观决策评审** | 涉及政策解读、地缘政治、利率决策 | MR + TR |
| **趋势研判评审** | 涉及多周期趋势、MA轨迹、动量判断 | TR + QT |
| **风险窗口评审** | 涉及阻力分析、波动率、熔断条件 | MR + RM |

### 8.2 顾问评审召唤

**⚠️ v2.5: 使用 `advisor_direct_call.advisors_review()` 内联调用，不再使用异步分发。**

调用代码见 §8.0。根据 §8.1 识别的评审类型，映射到 `scene` 参数：

| 评审类型 | scene 参数 | required_advisors |
|:---------|:----------|:-----------------|
| 宏观决策评审 | `MACRO_ANALYSIS` | `["advisor-mr", "advisor-tr"]` |
| 趋势研判评审 | `TREND_ANALYSIS` | `["advisor-tr", "advisor-qt"]` |
| 风险窗口评审 | `RISK_REVIEW` | `["advisor-mr", "advisor-rm"]` |

**输入给顾问的信息**:
```
A2分析摘要:
- 阻力最小路径: [UP/DOWN/NEUTRAL]
- 趋势方向: [BULL/BEAR/NEUTRAL]
- Regime分类: [6选1]
- 主要矛盾: [描述]
- 情景分析: [乐观/基准/悲观]

请输出:
- verdict: AGREE/DISAGREE/PARTIAL/SKIP
- confidence: 0-100
- risk_level: LOW/MEDIUM/HIGH/CRITICAL
- recommendations: [具体建议]
- circuit_breakers: [熔断条件]
```

### 8.3 评审结论处理

- **verdict=AGREE/PARTIAL**: 报告标记🟢/🟡，继续流程
- **verdict=DISAGREE**: 报告标记🔴BLOCKED，暂停A3战略制定
- **verdict=SKIP**: 报告标记⚪SKIP，继续但记录

### 8.4 评审约束

1. **必须评审**: A2分析完成 ≠ 流程完成，必须完成顾问评审才算结束
2. **宏观+趋势双视角**: 至少召唤MR和TR两个顾问
3. **熔断条件必须**: 每个评审必须包含 circuit_breakers
4. **内嵌不投递**: 评审结论直接追加到报告末尾的"## 顾问评审"章节

---

## 集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---|:---|:---|
| **输入←** | ← | `dream-strategy-research` | A1调研报告(含三角准则+contradiction_list) |
| **输入←** | ← | `dream-data-analysis` | MA处理逻辑、统计验证 |
| **输入←** | ← | `technical-analyst` | 技术指标计算 |
| **框架←** | ← | `dream-contradiction-theory` | A0矛盾论: Step1+2发现+抓住矛盾 ⚖️ |
| **增量←** | ← | `dream-intelligence-monitor` | A6 Level 1.5 SIGNIFICANT_SHIFT → A2矛盾图谱增量更新 ⚖️ (PROP_A8_006) |
| **数据源←** | ← | `tavily` | 地缘政治、情绪分析 |
| **数据源←** | ← | `odaily` | 链上数据(补充) |
| **输出→** | → | `dream-strategy-designer` | A3战略制定输入(含a0_contradiction_analysis) |

---

## 约束

1. **双维度必须覆盖**: 基本面×技术面缺一不可
2. **左右脑辩证**: 每项判断必须经过左右脑双重验证
3. **MA轨迹法**: 趋势判断必须用MA处理逻辑，不得凭直觉
4. **历史统计**: 理论结论必须附历史验证数据
5. **⭐ 方向性输出强制 (v2.3 修复)**: A2必须输出方向性判断(UP/DOWN)，
   NEUTRAL仅限阻力评分在40-60的窄区间内。矛盾时执行矛盾处理2.0，
   不得以"不确定性"为由拒绝给出方向。允许低置信度(0.3)的方向判断。
6. **承认不确定性**: 必须识别 key_uncertainty 和 alternative_scenarios
7. **⭐ 顾问评审强制 (v2.1)**: A2分析完成 ≠ 流程完成，必须完成Phase 8顾问评审
8. **⭐ 评审内嵌不投递 (v2.1)**: 顾问评审结论直接追加到报告末尾，不单独投递到pending_tasks/inbox/
9. **⭐ 逆向补偿强制 (v2.3)**: FGI<40+费率≈零轴 或 FGI>70+费率≈零轴时必须触发逆向补偿
10. **⚖️ A0矛盾分析强制 (v2.4 新增)**: 必须从A1的contradiction_list中用4维评分法识别主要矛盾。
    禁止"所有矛盾同等重要"。主要矛盾的主要方面决定方向。必须评估矛盾转化可能性。
    当左右脑结论与A0结论冲突时，优先取A0方向(A0基于7维全面分析)。
11. **🔴 双通道投递强制 (v2.6 新增 ⚠️)**: A2报告必须同时投递到：
    - 秘书邮箱: `~/.workbuddy/skills/boss-secretary/reports/trading/`
    - 前端产物中心: `~/.workbuddy/artifacts/trading/`
    仅投递到秘书邮箱会导致前端产物中心无文件，用户无法在产物看板看到报告。

---

## FAQ踩坑记录

> ⚠️ **左右脑权重**: 基本面权重40-60%，技术面权重40-60%，根据主要矛盾动态调整
> ⚠️ **MA轨迹法**: 必须计算MA斜率，不能只看当前价格位置
> ⚠️ **RSI超卖**: 系统可能忽视RSI<25信号，需醒目标注"被压制信号"
> ⚠️ **趋势验证**: 历史统计胜率<55%时，降低置信度
> ⚠️ **矛盾上报**: 左右脑冲突时，输出矛盾标记，不强制统一
> ⚠️ **v2.3 阻力区间**: NEUTRAL=40-60(20%)，不再使用30-70(70%)
> ⚠️ **v2.3 矛盾处理**: 禁止"等待方向明确"，必须输出reconciled_direction+action_advice
> ⚠️ **v2.3 逆向补偿**: FGI<40+费率≈零轴时阻力-15，FGI>70+费率≈零轴时阻力+15
> ⚠️ **v2.3 方向强制**: NEUTRAL仅限评分40-60窄区间，矛盾时也必须给方向(置信度可低至0.3)
> ⚠️ **⚖️ v2.4 A0抓住矛盾**: 必须用4维评分法(力量对比+时间紧迫性+证据一致性+市场影响权重)识别主要矛盾
> ⚠️ **⚖️ v2.4 A0优先**: 左右脑与A0冲突时取A0方向，A0基于7维全面分析更可靠
> ⚠️ **⚖️ v2.4 矛盾转化**: 必须评估主要矛盾的转化条件和概率，纳入monitoring_points
> ⚠️ **⚖️ v2.5 Q3-P1修复**: a0_contradiction_analysis必须包含action_pressure_from_a1字段，显式传递A1行动压力至A3
> ⚠️ **🔴 v2.6 双投递必做 (2026-05-07踩坑)**: A2报告必须同时写入秘书邮箱 + 前端产物中心。仅写秘书邮箱 = 前端无文件 = 用户看不到！

---

## 调度

- **自动化**: `dream-first-principles` (周一 10:30)
- **前置依赖**: `dream-strategy-research` (周一 09:00)
- **触发词**: "第一性原理"、"阻力分析"、"趋势分析"、"左右脑分析"



---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将产物写入交易邮箱。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 第一性原理部 (A2) |
| **秘书邮箱** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **前端产物中心** | `~/.workbuddy/artifacts/trading/` |
| **文件名格式** | `a2_first_principles_{YYYYMMDD}_{HHMM}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 ✅ + 前端产物中心 ✅ |

### 双通道投递代码

A2报告完成后，必须执行以下双通道投递：

```bash
# 1. 写入秘书邮箱（统一路径）
DEST_DIR="$HOME/.workbuddy/skills/boss-secretary/reports/trading"
cp "$SOURCE_FILE" "$DEST_DIR/"

# 2. 写入前端产物中心（双通道必选）
FRONTEND_DIR="$HOME/.workbuddy/artifacts/trading"
mkdir -p "$FRONTEND_DIR"
cp "$SOURCE_FILE" "$FRONTEND_DIR/"

# 3. 更新前端 index.json（追加条目）
# 使用 artifact-alignment-manager SKILL 或手动追加：
# {
#   "id": "a2_YYYYMMDD_HHMM",
#   "chain_phase": "A2",
#   "title": "A2第一性原理分析",
#   "date": "YYYY-MM-DDTHH:MM:SS",
#   "tags": ["a2", "first-principles"],
#   "department": "trading",
#   "by_a_phase": "A2"
# }

# 4. 验证双通道文件存在
ls "$DEST_DIR/a2_first_principles_"* || echo "❌ 秘书邮箱缺失"
ls "$FRONTEND_DIR/a2_first_principles_"* || echo "❌ 前端产物缺失"
```

> **⚠️ 警示 (2026-05-07踩坑)**: 仅投递到秘书邮箱 = 前端产物中心无文件 = 用户看不到报告！双通道必须同时执行！

> **顾问评审内嵌**: Phase 8顾问评审结论直接追加到A2报告末尾的"## 顾问评审"章节，不单独投递。

### 投递工作流

```
Phase 1-7: A2分析执行
    ↓
Phase 8: 顾问评审 (MR + TR)
    ↓
┌─────────────────────────────────────────────────────────┐
│  双通道投递 (v2.6 强制)                                 │
├─────────────────────────────────────────────────────────┤
│  通道1: 秘书邮箱 → reports/trading/  ← 历史路径        │
│  通道2: 前端产物 → artifacts/trading/ ← 新增必选       │
│  通道3: index.json更新 ← 必检                           │
└─────────────────────────────────────────────────────────┘
    ↓
验证: ls 检查双通道文件存在
    ↓
流程完成 ✅
```


> **前端产物center文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "产物标题"
> department: trading
> chain_phase: A2
> date: "YYYY-MM-DDTHH:MM:SS"
> type: first_principles
> status: completed
> tags: "a2 a2 第一性原理"
> by_a_phase: A2
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单（双通道验证）

- [ ] 文件写入秘书邮箱 `reports/trading/` 目录
- [ ] 文件写入前端产物中心 `~/.workbuddy/artifacts/trading/` 目录 ← **必选**
- [ ] 文件名符合 `a2_first_principles_{YYYYMMDD}_{HHMM}.md` 格式
- [ ] 包含完整 YAML frontmatter (chain_phase: A2, department: trading, date)
- [ ] 秘书邮箱通过 `ls reports/trading/a2_*` 验证文件存在
- [ ] 前端产物通过 `ls ~/.workbuddy/artifacts/trading/a2_*` 验证文件存在 ← **必检**
- [ ] `index.json` 已更新（包含 chain_phase + tags + by_a_phase）← **必检**

### 代码入口

- **交易邮箱**: 直接写入Markdown文件到 `~/.workbuddy/skills/boss-secretary/reports/trading/`

---

## 研报API推送规范 (v2.1)

> **⚠️ 2026-05-10更新**: A2产物完整工作流：落盘原始文件 → 生成小白版 → 同步到展示页面
> 
> **🔴 强制要求**: 小白版必须同步到 `http://8.209.238.108/market-research`，此URL已写死在SKILL中

### 完整工作流 (1:30执行)

```
Step 1: 落盘原始文件
    ↓
Step 2: 生成小白版（按v4小白版模板）
    ↓
Step 3: 同步到展示页面 http://8.209.238.108/market-research ← 新增
    ↓
完成
```

### Step 1: 落盘原始文件

**目标目录**: `reports/trading/`

**文件名**: `a2_first_principles_{YYYYMMDD}_{HHMM}.md`

**版本号规则**: v1=初稿, v2=修订, v3=顾问评审后终稿

### Step 2: 生成小白版

> **⚠️ 必须生成**: 每个A2报告必须同时生成小白版，供对外展示
> 
> **🔴 自动同步目标**: `http://8.209.238.108/market-research` (已写死，无需手动指定)

**文件名**: `a2_first_principles_{YYYYMMDD}_{HHMM}_小白版.md`

**输出位置**: `reports/trading/`

**小白版模板**: 见下方"小白版模板(v4.0)"章节

### Step 3: 同步到展示页面

> **🔴 强制同步**: 小白版生成后，必须自动同步到展示页面
> 
> **目标URL**: `http://8.209.238.108/market-research` (硬编码，不可修改)

**同步命令**:
```bash
# 方式1: 使用推送脚本（推荐）
cd /Users/zhangjiangtao/WorkBuddy/20260415144304
python3 scripts/push_reports_to_api.py --days 1 --target market-research

# 方式2: 直接API调用
python3 << EOF
import requests
import os

API_BASE = "http://8.209.238.108"
API_KEY = "8F_yf4C57w13-HaF3Wlw40uRYcica4Tfn-c93EocnLo"

# 读取小白版内容
with open('reports/trading/a2_first_principles_$(date +%Y%m%d)_小白版.md', 'r') as f:
    content = f.read()

# 推送到展示页面
payload = {
    "title": "BTC 行情分析报告",
    "content": content,
    "category": "market-analysis",
    "tags": ["BTC", "A2", "第一性原理", "$(date +%Y-%m-%d)"]
}

headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
r = requests.post(f"{API_BASE}/api/v1/admin/reports", json=payload, headers=headers)
print(f"推送状态: {r.status_code}")
print(f"响应: {r.text}")
EOF
```

**推送验证**:
```bash
# 验证展示页面是否更新
curl -s http://8.209.238.108/market-research | grep -o "A2第一性原理" && echo "✅ 同步成功" || echo "❌ 同步失败"
```

**推送范围**:

| 文件类型 | 是否推送 | 目标URL | 说明 |
|:---------|:--------:|:-------|:-----|
| `a2_first_principles_*_小白版.md` | ✅ 是 | `http://8.209.238.108/market-research` | A2小白版（**唯一推送对象**） |
| `a2_first_principles_*.md` (专业版) | ❌ 否 | - | 仅存档，不推送 |
| `*_小白版.md` (其他) | ❌ 否 | - | 仅为A2小白版推送 |
| `*research*.md` (A1) | ❌ 否 | - | A1调研报告 |
| `*strategy*.md` (A3) | ❌ 否 | - | A3战略报告 |
| `daily_market_intel_*.md` | ❌ 否 | - | 高频日报不推送 |

### API配置

| 项目 | 值 |
|:-----|:---|
| **API地址** | `http://8.209.238.108/api/v1/admin/reports` |
| **展示页面** | `http://8.209.238.108/market-research` (硬编码) |
| **鉴权方式** | `X-API-Key` Header |
| **API Key** | `8F_yf4C57w13-HaF3Wlw40uRYcica4Tfn-c93EocnLo` |
| **Key存储** | 记忆(MEMORY.md) + 用户环境变量 `INTERNAL_API_KEY` |

### 推送前审查 (隐私保护)

> **⚠️ 必须执行**: 推送前必须过滤敏感个人信息

**必须删除/脱敏的内容**:

| 敏感类型 | 过滤方式 | 示例 |
|:---------|:---------|:-----|
| **持仓信息** | 删除或泛化 | `BTC LONG 6.09张` → 删除 |
| **API密钥** | 删除 | `api_key=f9d0221c-...` → 删除 |
| **账户余额** | 泛化 | `$662.05可用` → 泛化为 `$XXX` |
| **个人身份** | 删除 | 姓名、手机号、邮箱等 |
| **OKX私钥** | 删除 | 任何私钥/种子词 |

**审查检查清单**:
- [ ] 不包含具体持仓数量/方向
- [ ] 不包含API Key/API Secret
- [ ] 不包含账户余额精确数字
- [ ] 不包含个人身份信息
- [ ] 不包含私钥/助记词

### 推送格式

```python
import requests

API_BASE = "http://8.209.238.108/api/v1"
API_KEY = "8F_yf4C57w13-HaF3Wlw40uRYcica4Tfn-c93EocnLo"

payload = {
    "title": "A2第一性原理分析 {日期}",
    "summary": "BTC阻力最小路径分析摘要",
    "category": "A2-市场分析",
    "content": "审查后的内容",
    "tags": ["BTC", "A2", "第一性原理", "{日期}"]
}

headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
r = requests.post(f"{API_BASE}/admin/reports", json=payload, headers=headers)
```

### Markdown产物模板 (v3.0)

> **⚠️ 强制遵循**: 生成A2报告时必须使用此模板格式，否则远端显示异常

```markdown
# A2 第一性原理分析报告

**日期**: {YYYY-MM-DD} HH:MM UTC+8
**Regime**: {REGIME判定}
**参考**: A1调研报告 A1-{YYYYMMDD}-{HHMM}

---

## 执行摘要

**阻力最小路径**: {UP|DOWN|NEUTRAL} ({置信度}%)
**趋势方向**: {UP|DOWN|NEUTRAL} ({置信度}%)

**核心发现**:
1. 发现一
2. 发现二

---

## 1. 基本面分析

### 1.1 资金流分析

- L1 宏观流动性
    - 指标一: 状态 (影响)
    - 指标二: 状态

- L2 中观资金流向
    - ETF净流入: $XXX
    - 合约OI: 状态

### 1.2 情绪指标分析

- FGI: {数值} (状态)
- 资金费率: {数值} (状态)

### 1.3 地缘政治分析

- 事件一: 状态 (影响)
- 事件二: 状态

---

## 2. 技术面分析

### 2.1 趋势指标

- EMA20: $XX,XXX (状态)
- EMA60: $XX,XXX (状态)

### 2.2 动量指标

- RSI: ~XX (状态)
- MACD: 状态

---

## 3. 三叉戟评分

| 维度 | 评分 | 满分 |
|:-----|:----:|:----:|
| 技术面 | XX | 15 |
| 资金流 | XX | 15 |
| 情绪面 | XX | 10 |
| 地缘政治 | XX | 10 |
| 趋势强度 | XX | 10 |
| 动量 | XX | 10 |
| **总计** | **XX** | **70** |

**最终信号**: {BUY|SHORT|SKIP}
```

### 小白友好版模板 (v4.0)

> **说明**: A2报告需生成两个版本：专业版(v3)和通俗版(v4小白版)。小白版供非专业读者阅读，保留核心结论但简化术语。

```markdown
# {COIN} 行情分析报告
**日期**: {YYYY-MM-DD}
**适合阅读**: 加密货币新手及以上

---

## 一句话结论

{简要结论，1-2句话}

---

## 今日重点

- {重点一}

- {重点二}

- {重点三}

---

## 市场发生了什么？

### 价格走势

{CURRENCY}从{上周价格}涨到了{当前价格}，24小时涨幅 **{变化}**。

简单说：{通俗描述}

### 谁在买？谁在卖？

**好消息（多头信号）**:
- {利好一}
- {利好二}

**坏消息（空头信号）**:
- {利空一}
- {利空二}

---

## 术语解释

**FGI（恐惧贪婪指数）**

    0-100分，>60贪婪，<40恐惧

**ETF（交易所交易基金）**

    追踪BTC的基金，买ETF=间接买BTC

**RSI（相对强弱指标）**

    超买超卖指标，>70超买，<30超卖

**EMA（指数移动平均线）**

    均线的一种，用来判断价格趋势方向

**ATR（平均真实波幅）**

    衡量价格波动大小，ATR高=波动大

---

## 现在能买吗？

### 综合评分

**技术面**: XX/70 — {说明}

**资金面**: XX/70 — {说明}

**情绪面**: XX/70 — {说明}

**地缘政治**: XX/70 — {说明}

**总分**: XX/70，结论：{结论}

### 操作建议

**适合的操作**:
- {建议一}
- {建议二}

**需要避免的**:
- {禁忌一}
- {禁忌二}

### 关键价位

```
阻力位（涨到这些位置可能卖压）：
  R1: $XX,XXX  ← 心理关口
  R2: $XX,XXX  ← 前高区域

支撑位（跌到这些位置可能反弹）：
  S1: $XX,XXX  ← 重要防线
  S2: $XX,XXX  ← 止损参考
```

---

## 风险提示

**1. {风险一标题}**

    {风险一说明}

**2. {风险二标题}**

    {风险二说明}

**3. {风险三标题}**

    {风险三说明}

**建议仓位**

    轻仓（不超过总资金的20%）

---

## 下次更新时间

{明日时间}

---

*本报告仅供参考，不构成投资建议。加密货币投资有风险，请量力而行。*
```

### 双版本产物规范

| 版本 | 文件名模式 | 用途 |
|:-----|:-----------|:-----|
| 专业版 | `a2_first_principles_{YYYYMMDD}.md` | 专业分析存档 |
| 小白版 | `a2_first_principles_{YYYYMMDD}_小白版.md` | 对外展示 |

### 推送历史记录

| 日期 | ID | 产物 | 格式版本 |
|:-----|:--:|:-----|:---------|
| 2026-04-23 | 100 | 分析报告v3 | v3.0(专业版) |
| 2026-04-23 | 103 | 分析报告v4小白版 | v4.0(通俗缩进版) |

### 产物文件名规范

| 产物 | 文件名模式 |
|:-----|:-----------|
| 分析报告 | `a2_first_principles_{YYYYMMDD}.md` |
| 矛盾图谱 | `contradiction_map_{YYYYMMDD}.json` |
| 关键价位 | `key_levels_{YYYYMMDD}.json` |

### 推送格式规范 (v3.0)

> **⚠️ 2026-04-23 v3.0更新**: 经实测验证，远端Markdown渲染器对表格支持不佳，改为缩进列表格式

**问题演变**:

| 版本 | 问题 | 方案 |
|:-----|:-----|:-----|
| v1.0 | 代码块ASCII图表乱码 | 禁用代码块 |
| v2.0 | 表格密集(48%)排版混乱 | 减少表格 |
| **v3.0** | **表格仍显示异常** | **改为缩进列表** |

**格式要求**:

| 要求项 | 规范 | 示例 |
|:-------|:-----|:-----|
| **禁用代码块** | 不使用\`\`\` | - |
| **禁用表格** | 使用缩进列表替代表格 | 见下方 |
| **标题层级** | h1-h3为主 | ## 标题 |
| **内容长度** | 建议≤3000字符 | - |
| **emoji使用** | 尽量不用或每节≤2个 | (WARNING) |

**列表格式示例**:

```
❌ 不推荐 (表格):
| 指标 | 数值 | 状态 |
|:-----|:-----|:-----|
| BTC价格 | $78,000 | 上涨 |

✅ 推荐 (缩进列表):
- BTC价格: $78,000 (上涨)
    - 24h变化: +2.5%
    - 成交量: 10亿
```

**嵌套列表规范**:

```
顶级列表: - 内容
    二级缩进: 4个空格 + - 内容
    三级缩进: 8个空格 + - 内容
```

**保留表格的场景**: 仅在三叉戟评分综合表格使用(≤1个)

### 推送历史记录

| 日期 | ID | 产物 | 格式版本 |
|:-----|:--:|:-----|:---------|
| 2026-04-23 | 93,94,95 | 分析报告/矛盾图谱/关键价位 | v1.0(有格式问题) |
| 2026-04-23 | 97 | 分析报告v2 | v2.0(表格密集问题) |
| 2026-04-23 | 100 | 分析报告v3 | v3.0(缩进列表版) |

### 投递后验证（强制调用AD SKILL）

完成秘书邮箱投递后，必须调用 `artifact-alignment-manager` SKILL 执行双通道验证：

1. **调用方式**: 触发词「产物投递验证」或加载 `artifact-alignment-manager` SKILL
2. **验证内容**:
   - ✅ 秘书邮箱文件存在 + frontmatter完整（含 tags, by_a_phase）
   - ✅ 前端产物中心文件存在（`~/.workbuddy/artifacts/trading/`）
   - ✅ `index.json` 已更新（含 `chain_phase` + `tags`）
   - ✅ 前端详情页返回 200
3. **不通过**: 按 AD SKILL 第四章步骤修复，重新验证
4. **通过**: 投递完成

> ⚠️ 没有 AD SKILL 验证通过 = 投递未完成

