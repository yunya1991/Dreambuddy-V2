---
name: dream-attention-radar
description: |
  📡 注意力雷达部 — 三源多头注意力标的筛选器
  通过资金注意力、情绪注意力、周期注意力三大Query-Key-Value注意力头
  做动态推理+协同注意力融合，输出做多/做空Top N具体标的排名。
  触发词：注意力雷达、资金注意力、情绪注意力、周期注意力、
         三源注意力、标的筛选、多空排名、attention radar
version: 1.0.0
created: 2026-08-11
updated: 2026-08-11
department: 交叉分析部 (Attention-Radar)
chain_phase: AX
---

# 📡 注意力雷达部 (AX) — 三源多头注意力标的筛选器

> **部门定位**：交叉分析部（AX Attention-Radar），独立于 A1~A9 的交叉分析环节。
> **链阶段**：AX （介于 A1→A2 或 A2→A3 之间，双向可用）
> **核心能力**：三源 Multi-Head Attention（资金 / 情绪 / 周期）动态推理，
> 协同注意力融合，输出做多榜 Top 5 / 做空榜 Top 5 + 注意力热力图 + 矛盾预警。
> **标的池**：16 instId（加密主流 10 + 宏观大类 6）

---

## 第一章：SKILL 定位与整体架构

### 1.1 在交易链路中的位置

原有链路：
```
A1 调研 (dream-strategy-research)
  → A2 第一性原理 (dream-first-principles)
  → A3 战略设计 (dream-strategy-designer)
```

AX 注意力雷达插入点（三路径可选，按触发时上游数据存在与否自动选择）：

```
路径① A1→AX→A2：A1 全景数据 → 注意力初筛 → long/short rank 输入A2，
                 调整 A2 cross_dimension 注意力权重
路径② A2→AX→A3：A2 周期+宏观资产结论做 Query
                 + 实时监控精细排序 → 具体 instId 优先级给 A3 三预设
路径③ 独立调用：asset-research v3 cycle 结论 + A6 实时监控
                 → 独立输出多空排名榜
```

### 1.2 整体架构图（Transformer Attention）

```
┌─────────────────────────────────────────────────────────────────────┐
│                 📡 注意力雷达部 — 整体架构                            │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌────────────── Input Embedding Layer ────────────────┐            │
│  │  标的池: 16个 instId × 22维信号特征向量              │            │
│  │  (BTC/ETH/.../LINK × 10 + XAU/CL/.../NDX × 6)        │            │
│  │  ↓ Embedding: 位置编码 + 类型编码(加密/商品/权益)    │            │
│  └──────────────────────────────────────────────────────┘            │
│                              ↓                                       │
│  ┌────────────────────────────────────────────────────┐              │
│  │       Multi-Head Attention (三大注意力头)            │             │
│  │    每个头: Query × Key^T → Softmax → Value 加权     │             │
│  │                                                      │             │
│  │   Head 1️⃣  资金注意力 (Capital)  权重 0.40          │             │
│  │   Head 2️⃣  情绪注意力 (Sentiment) 权重 0.30          │             │
│  │   Head 3️⃣  周期注意力 (Cycle)     权重 0.30          │             │
│  └──────────────────────┬─────────────────────────────┘              │
│                         ↓                                             │
│  ┌────────────────────────────────────────────────────┐              │
│  │     Co-Attention Fusion 协同注意力融合层             │             │
│  │  • 三源同向 → 协同系数 ×1.2~1.3 (放大)               │             │
│  │  • 两源一致一源反 → 半协同系数 ×1.05~1.15            │             │
│  │  • 三源矛盾 → 冲突系数 ×0.5 (衰减50%)                │             │
│  │  • 注意力熵值(H≥0.8)校验 → 低熵额外 ×0.7            │             │
│  └──────────────────────┬─────────────────────────────┘              │
│                         ↓                                             │
│  ┌────────────────────────────────────────────────────┐              │
│  │        Output Ranking Layer (输出排序层)             │             │
│  │  • Long Rank Top-5  做多注意力最高标的               │             │
│  │  • Short Rank Top-5 做空注意力最高标的               │             │
│  │  • Attention Heatmap  16×3 热力图(标的×头)           │             │
│  │  • 矛盾/异常预警  映射A0 C1-C8维度                   │             │
│  └────────────────────────────────────────────────────┘              │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.3 与现有系统的复用关系

| 上游输入（直接复用） | 来源 | 作用 |
|---|---|---|
| 美林时钟四象限 | `asset-research` v2/v3 → `cycle.currentPhase` | 三个头的 Query 初始化 |
| 子资产周期偏好度 | `asset-research` v2 → `PREFERENCE_MAP` | Head 3（周期）Key 基准 |
| 宏观资产共振信号 | `dream-first-principles` v2.6 §2.5 | Head 1（资金）K7 跨资产轮动 |
| 逆向补偿三条规则 | `dream-first-principles` v2.3 §逆向信号补偿 | Head 2（情绪）Value 强制规则 |
| 矛盾框架 C1-C8 | `dream-contradiction-theory` A0 | §3.3 异常维度映射 |
| A6 实时监控 | `dream-intelligence-monitor` | 信号新鲜度更新 |
| 减半周期相位 | `screen1-halving-cycle` | Head 3 Query 组成部分之一 |

### 1.4 标的池定义（16 instId）

```yaml
universe:
  # 加密主流 SWAP 10
  - inst_id: "BTC-USDT-SWAP"   display: "比特币"       cat: crypto / mainstream
  - inst_id: "ETH-USDT-SWAP"   display: "以太坊"       cat: crypto / mainstream
  - inst_id: "SOL-USDT-SWAP"   display: "Solana"      cat: crypto / altcoin_l1
  - inst_id: "BNB-USDT-SWAP"   display: "币安币"       cat: crypto / exchange
  - inst_id: "XRP-USDT-SWAP"   display: "瑞波"         cat: crypto / mainstream
  - inst_id: "DOGE-USDT-SWAP"  display: "狗狗币"       cat: crypto / memecoin
  - inst_id: "AVAX-USDT-SWAP"  display: "Avalanche"   cat: crypto / altcoin_l1
  - inst_id: "ADA-USDT-SWAP"   display: "Cardano"     cat: crypto / altcoin_l1
  - inst_id: "TON-USDT-SWAP"   display: "Telegram"    cat: crypto / altcoin_l1
  - inst_id: "LINK-USDT-SWAP"  display: "Chainlink"   cat: crypto / altcoin_defi
  # 宏观大类 SWAP / CFD 6
  - inst_id: "XAU-USDT-SWAP"   display: "黄金"         cat: commodity / precious
  - inst_id: "XCU-USDT-SWAP"   display: "铜"           cat: commodity / industrial
  - inst_id: "CL-USDT-SWAP"    display: "原油(WTI)"    cat: commodity / energy
  - inst_id: "TSLA-USDT-SWAP"  display: "特斯拉股票"   cat: equity / growth
  - inst_id: "COIN-USDT-SWAP"  display: "Coinbase股"   cat: equity / crypto_exposure
  - inst_id: "NDX-USDT-SWAP"   display: "纳指100"      cat: equity / index
```

---

## 第二章：三大注意力头 Q/K/V 详细定义

> 统一符号：对每个标的 $i$，注意力得分 $=\text{Softmax}(Q_i \cdot K_i^T / \sqrt{d_k}) \cdot V_i$
> 实际落地规则化 softmax：得分排名前 5 分配注意力权重，其余衰减至≈0

---

### 2.1 Head 1️⃣：资金注意力 (Capital Attention) — 权重 0.40

**核心问题**：当前机构资金「真金白银」正在流入/流出哪些具体标的？

```
📌 Query (机构偏好方向) 6维
    初始化来源: asset-research cycle.currentPhase + 减半周期相位 + 美联储周期
    ┌─ Q1-Q4: 美林象限 one-hot (recovery / overheat / stagflation / recession)
    ├─ Q5:    BTC 减半周期相位（前半 / 后半 / 减半年前 / 减半后）数值化 [0..1]
    └─ Q6:    美联储利率周期 easing(+1) / neutral(0) / tightening(-1)
    例: Stagflation Lite → Q = [0, 0.2, 0.7, 0.1, 0.3, -1]

🔑 Key (实时资金流向信号) 每标的 8 个
    ┌──────────────────────────────────────────────────────────┐
    │ 编号 │ 信号名称         │ 多头 Key ↑       空头 Key ↓    │
    │ K1   │ ETF净流入/流出   │ >+$1亿/日       <-$1亿/日      │
    │ K2   │ 合约OI变化率     │ 增仓+价涨       增仓+价跌       │
    │ K3   │ DXY 美元指数     │ DXY日跌幅>0.3%  DXY日涨幅>0.3% │
    │ K4   │ 10Y美债收益率   │ 收益率↓>2bp    收益率↑>2bp     │
    │ K5   │ OKX大单密度     │ buy wall > sell×1.5  sell×1.5>buy│
    │ K6   │ 链上交易所出入金 │ 净提币(吸筹)   净充币(抛压)    │
    │ K7   │ 跨资产资金轮动   │ 见★K7信号表                    │
    │ K8   │ 订单簿1%深度    │ >$10M          <$3M            │
    └──────────────────────────────────────────────────────────┘

★ K7 跨资产资金轮动信号（来自 A2 §2.5 宏观共振）：
    INFLATION_EXPECT  黄金↑+BTC↑           → BTC/XAU Key=+1
    RISK_OFF          黄金↑+BTC↓+VIX>25    → BTC Key=-1 / XAU Key=+1
    RISK_ON           黄金↓+TSLA↑+BTC↑     → BTC/TSLA/NDX Key=+1
    STAGFLATION_FEAR  原油↑+铜↓+10Y-2Y倒挂 → XAU/CL Key=+1 / XCU/TSLA Key=-1
    FED_PIVOT_HOPE    DXY↓+10Y↓            → 成长类(TSLA/NDX/BTC) Key=+1

💰 Value (方向强度 -100 ~ +100)
    = Σ(Key命中项 × 对应权重) × {Query匹配系数}
    权重: K1=0.25, K2=0.2, K3=0.15, K4=0.1, K5=0.1, K6=0.05, K7=0.1, K8=0.05
    Query匹配系数:
      Query偏好方向 与 Value 同向 → ×1.20（信号确认偏好）
      Query偏好方向 与 Value 反向 → ×0.60（信号偏离偏好，降权）

✅ Softmax 后输出: 资金最关注 Top 5 标的 + 方向倾向
```

---

### 2.2 Head 2️⃣：情绪注意力 (Sentiment Attention) — 权重 0.30

**核心问题**：哪些标的当前情绪出现「极端拥挤」或「预期差」？逆向/顺向如何下注？

```
📌 Query (风险偏好模式) 4维
    初始化来源: screen1-cross-market §3.1 + §VIX + FGI 4日变化
    ┌─ Q1: 风险偏好模式 one-hot (GOLD_STRONG / NEUTRAL / STOCKS_STRONG)
    ├─ Q2: VIX regime  LOW(<20) / NORMAL(20-30) / HIGH(>30)
    ├─ Q3: BTC vs NDX 相关性  low(<0.3) / mid(0.3-0.7) / high(>0.7)
    └─ Q4: FGI 4日变化 >20 → 逆向补偿强制开关 = ON

🔑 Key (情绪极值信号) 每标的 7 个
    ┌──────────────────────────────────────────────────────────┐
    │ 编号 │ 信号名称         │ 逆向 Key(反向下注)              │
    │ K1   │ Fear & Greed     │ <25极恐→做多  >75极贪→做空      │
    │ K2   │ 合约资金费率     │ >0.05%拥挤→空  <-0.05%负费率→多 │
    │ K3   │ OKX多空比        │ >1.2多头主导→警惕空 <0.8→警惕多 │
    │ K4   │ 新闻语气 Tavily  │ 一致看多→警惕  一致看空→逆向多  │
    │ K5   │ 10Y-2Y利差       │ 倒挂加深→防御类多 正常→风险类多 │
    │ K6   │ 黄金/铜比价       │ 比值>历史1σ → 防御模式多头     │
    │ K7   │ FGI 4日变化      │ >20点剧变 → 强制逆向补偿       │
    └──────────────────────────────────────────────────────────┘

💰 Value (方向强度 -100 ~ +100)
    = Σ(Key逆向命中项 × 逆向权重 1.5 + Key顺向项 × 顺向权重 0.5)
    + A2 v2.3 逆向补偿三条 强制触发（即使不触发阈值也需明确标注未触发）:
      ① FGI<40 AND |funding|<0.01% → Value 向上补偿 +15
      ② FGI>70 AND |funding|<0.01% → Value 向下补偿 -15
      ③ FGI 4日变化>20 → Value 反向偏移 ±10
      补偿上限 ±20 分（不可单独翻转方向，仅修正）

✅ Softmax 后输出: 情绪极值最显著 Top 5 标的 + 逆向倾向
```

---

### 2.3 Head 3️⃣：周期注意力 (Cycle Attention) — 权重 0.30

**核心问题**：哪些标的处于「美林时钟 + 减半周期 + 多周期MA」三重周期对齐的最佳窗口？

```
📌 Query (周期相位叠加) 4 × 4 × 3 = 48 种组合
    ┌─ 美林象限:  recovery / overheat / stagflation / recession
    ├─ 减半周期:  减半前12月+ / 减半前6-12月 / 减半后0-6月 / 减半后6-18月
    └─ 美联储:    cut / pause / hike
    Query = 该48格子的历史最优做多/空标的分布（胜率×收益中位数）
    例: 减半后6-12月 + Recovery + cut → BTC/ETH 历史胜率=82% → Query高权重

🔑 Key (多周期趋势对齐) 每标的 7 个
    ┌──────────────────────────────────────────────────────────┐
    │ 编号 │ 信号名称         │ 多头对齐 Key     空头对齐 Key    │
    │ K1   │ 周线 MA20/60/120 │ 多头排列(三上)   空头排列(三下) │
    │ K2   │ 日线 MA5/10/20   │ 多头排列        空头排列       │
    │ K3   │ 4H MA斜率        │ >0 拐头上      <0 拐头下       │
    │ K4   │ 周线RSI位置      │ 30-50底部启动区  70-85顶部过热区│
    │ K5   │ ATR 波动率相位   │ 压缩后(低位)放大↑  高位后收缩↓ │
    │ K6   │ 减半周期窗口匹配 │ 历史胜率>70%   历史胜率<30%     │
    │ K7   │ 相似历史模式匹配 │ pattern_score>0.8同向  >0.8反向 │
    └──────────────────────────────────────────────────────────┘

💰 Value (方向强度 -100 ~ +100)
    = (对齐 Key 数量 / 7) × 100 × Query匹配系数
      + K6命中 (历史胜率>70%/<30%) ±15
      + K7命中 (相似模式匹配) ±10
    Query匹配系数:
      该标的在此 48 格的历史胜率 ≥70% → ×1.10
      该标的在此 48 格的历史胜率 ≤30% → ×0.50
      其余 30-70% → ×0.85

✅ Softmax 后输出: 周期对齐度最高 Top 5 标的 + 做多/空倾向
```

---

### 2.4 三注意力头归一化标准

统一映射到 `[-100, +100]` 区间（正数=做多，负数=做空）：

| 头 | +100 满分条件 | -100 满分条件 | 0 中性条件 |
|---|---|---|---|
| Head 1 资金 | 8/8 Key 全命中做多 + Query匹配×1.2 | 8/8 Key 全命中做空 + Query匹配×1.2 | 多空Key平手 Query中性 |
| Head 2 情绪 | 逆向补偿命中 + 极恐+零费率 | 逆向补偿命中 + 极贪+零费率 | 情绪中性 无极值 |
| Head 3 周期 | 7/7 Key 全周期对齐 + Query胜率>70% | 7/7 Key 全空头对齐 + Query胜率<30% | 周期无方向 |

---

## 第三章：Co-Attention 协同注意力融合 + 输出排序层

### 3.1 协同融合五步法

记 $C_i$ = Head 1 资金得分，$S_i$ = Head 2 情绪得分，$Y_i$ = Head 3 周期得分

#### Step 1：方向性判定（阈值 = ±15，窄区间借鉴 A2 中间态思路）
$$
\text{dir}(X) = \begin{cases}
\text{LONG} & X \ge +15 \\
\text{SHORT} & X \le -15 \\
\text{NEUTRAL} & -15 < X < +15
\end{cases}
$$

#### Step 2：协同模式识别 + k 系数

```
协同模式分类表（13种）:
──────────────────────────────────────────────────────────────
Mode   dir(C)  dir(S)  dir(Y)   k系数   含义/星级
──────────────────────────────────────────────────────────────
 M1    LONG    LONG    LONG     1.30   ⭐⭐⭐ 三源强烈一致做多
 M2    SHORT   SHORT   SHORT    1.30   ⭐⭐⭐ 三源强烈一致做空
 M3    LONG    LONG    NEUTRAL  1.10   ⭐⭐  资金+情绪双看多，周期观望
 M4    LONG    NEUTRAL LONG     1.15   ⭐⭐  资金+周期双看多，情绪观望
 M5    NEUTRAL LONG    LONG     1.10   ⭐⭐  情绪+周期双看多，资金观望
 M6    SHORT   SHORT   NEUTRAL  1.10   ⭐⭐  资金+情绪双看空，周期观望
 M7    SHORT   NEUTRAL SHORT    1.15   ⭐⭐  资金+周期双看空，情绪观望
 M8    NEUTRAL SHORT   SHORT    1.10   ⭐⭐  情绪+周期双看空，资金观望
 M9    LONG    SHORT   LONG     0.85   ⚠️   情绪看空反其余
 M10   LONG    LONG    SHORT    0.85   ⚠️   周期看空反其余
 M11   SHORT   LONG    SHORT    0.85   ⚠️   情绪看多反其余
 M12   三源两两矛盾(全不同)      0.50   🔴   严重分歧，降权50%
 M13   其余组合(含NEUTRAL)      1.00   普通模式
──────────────────────────────────────────────────────────────
```

#### Step 3：基础加权合成
$$
B_i = 0.40 \cdot C_i + 0.30 \cdot S_i + 0.30 \cdot Y_i
$$

#### Step 4：协同系数修正
$$
F_i = B_i \times k \times \text{entropy\_penalty}
$$

#### Step 5：熵值多样性校验（Attention Entropy Check）
$$
H = - \sum_{h \in \{C,S,Y\}} p_h \log_2 p_h,\quad p_h = \frac{|h \text{ 在 } B_i \text{ 中的贡献}|}{\sum |\text{各头贡献}|}
$$

熵值区间：
- $H \ge 1.2$ （均匀 $H_{max} = \log_2 3 = 1.58$） → ✅ PASS，`entropy_penalty = 1.00`
- $0.8 \le H < 1.2$ → ⚠️ WARN，`entropy_penalty = 1.00` 但标「某头贡献过高」
- $H < 0.8$ → 🔴 FAIL，`entropy_penalty = 0.70` （额外降权 30%）

---

### 3.2 输出排序层规范

#### 3.2.1 Long Rank Top 5（做多榜，按 $F_i$ 降序）

```yaml
long_rank_top5:
  - rank: 1
    inst_id: "XAU-USDT-SWAP"
    display_name: "黄金"
    asset_category: "commodity / precious_metal"
    final_score: +88.4
    break_down:
      capital_head:     +72 × 0.40 = 28.8
      sentiment_head:   +60 × 0.30 = 18.0
      cycle_head:       +82 × 0.30 = 24.6
      base_weighted:    71.4
      co_mode_k:        ×1.30 (M1 三源一致做多)
      entropy_penalty:  ×1.00 (H=1.42 PASS)
      → final_score:    88.4
    co_mode: "M1"
    co_note: "资金+情绪+周期三源强烈一致做多"
    rationale:
      - "滞胀期黄金历史配置优先级 Top1"
      - "ETF连续5日净流入 +$8.2亿"
      - "周线MA多头排列，RSI处于50启动区"
    recommended_entry_zone: "$2680 - $2720"
    confidence: 0.92
```

#### 3.2.2 Short Rank Top 5（做空榜，按 $F_i$ 升序即做空强度降序）

```yaml
short_rank_top5:
  - rank: 1
    inst_id: "BTC-USDT-SWAP"
    display_name: "比特币"
    asset_category: "crypto / mainstream_crypto"
    final_score: -76.8
    break_down:
      capital_head:     -80 × 0.40 = -32.0
      sentiment_head:   -30 × 0.30 =  -9.0
      cycle_head:       -90 × 0.30 = -27.0
      base_weighted:    -68.0
      co_mode_k:        ×1.30 (M2 三源一致做空)
      entropy_penalty:  ×0.87? 不，H≥1.2则×1.00
      → final_score:    -88.4 (示例数值)
    co_mode: "M9"
    co_note: "⚠️ 资金+周期看空，但情绪微弱多头信号(逆向补偿未达阈值) — 逼空风险提醒"
    rationale: [...]
    confidence: 0.68    # M9模式置信度下调
```

#### 3.2.3 Attention Heatmap（16×3 热力图 + 全局熵报告）

```yaml
attention_heatmap:
  columns: [capital_head, sentiment_head, cycle_head]
  rows:
    - inst_id: BTC-USDT-SWAP
      scores: [-65, +20, -80]        # 值域 [-100, +100]
      note: "周期头极端做空，情绪头未触发逆向补偿阈值"
    - inst_id: XAU-USDT-SWAP
      scores: [+72, +60, +82]
      note: "三高一致"
    # ... 其余14个标的
  global_entropy:
    capital_head_contribution:   41%
    sentiment_head_contribution: 29%
    cycle_head_contribution:     30%
    H: 1.58                       # log2(3) ≈ 1.58 完美均衡
    status: PASS
```

---

### 3.3 矛盾与异常预警（映射 A0 矛盾论 C1-C8）

```yaml
attention_anomalies:
  - id: AX_ANOM_001
    a0_dimension: "C2 市场情绪 vs C1 资金面 矛盾"
    severity: HIGH          # HIGH / MEDIUM / LOW
    inst_ids: ["ETH-USDT-SWAP"]
    description: |
      Head1(-60 资金空) + Head3(-70 周期空) 一致空；
      但 Head2(+35) = FGI极恐<25 且 funding≈0.003%，触发 A2 逆向补偿+15，
      情绪头判定应做多。协同模式=M11(情绪反其余)，k=0.85
    suggested_action: "若做空：止盈减半；若持有现货多头：不必恐慌止损"
    transformation_monitor: "观察 ETH 4H RSI 是否在3日内从<25拐头回升至>35"

  - id: AX_ANOM_002
    a0_dimension: "注意力熵异常 (新增AX维度)"
    severity: MEDIUM
    inst_ids: ["NDX-USDT-SWAP"]
    description: "H=0.55 (<0.8)。Head3周期头贡献82%，资金情绪几乎为0。仅靠历史相似模式匹配，无真金白银验证。"
    suggested_action: "降级为观察标的，不入Top 5榜单；Rank 6位置标注"
    transformation_monitor: "等待纳指ETF/大单数据确认头1后再提升权重"

  - id: AX_ANOM_003
    a0_dimension: "C6 时序周期背离"
    severity: LOW
    inst_ids: ["SOL-USDT-SWAP", "BTC-USDT-SWAP"]
    description: "SOL Head3周线支持做多(+45)但Head3 K3的4H斜率拐头下；BTC Head3做空(-80)但Head2 K4的4H RSI极超卖。"
    suggested_action: "SOL仅轻仓；BTC空单设宽止损(ATR×2)防止超卖反弹"
```

---

### 3.4 最终 JSON 输出总览（供 A2/A3 消费）

```json
{
  "attention_radar_report": {
    "meta": {
      "report_id": "AX_20260811_1430",
      "version": "1.0.0",
      "timestamp": "2026-08-11T14:30:00+08:00",
      "cycle_phase_snapshot": "STAGFLATION_LITE",
      "query_mode": "A2→AX→A3 (路径②)",
      "universe_size": 16
    },
    "head_raw_outputs": {
      "head1_capital_ranking":  ["inst_id","score"],
      "head2_sentiment_ranking":["inst_id","score"],
      "head3_cycle_ranking":    ["inst_id","score"]
    },
    "co_attention_fusion": {
      "pattern_distribution": {"M1":3,"M2":2,"M9":1,"M11":1,"M13":9},
      "entropy_check": {
        "global_H": 1.42,
        "status": "PASS",
        "low_entropy_inst_ids": ["NDX-USDT-SWAP (H=0.55)"]
      }
    },
    "long_rank_top5":  [],
    "short_rank_top5": [],
    "attention_heatmap": {},
    "attention_anomalies": [],
    "a0_contradiction_alignment": {
      "mapped_to_primary_contradiction": "CX_001 资金防御类撤退 vs 高贝塔拥挤",
      "mapped_ranking_align_with_a0_dominant_side": true
    },
    "integration_hints_for_downstream": {
      "to_a2": "建议 cross_dimension.alignment=SAME, synthesis_confidence +=12%",
      "to_a3": "long_rank[0]=XAU / short_rank[0]=BTC 可直接进入三预设优先级队列"
    }
  }
}
```

---

## 第四章：执行流程、铁律约束与投递规范

### 4.1 强制依赖声明（对应 A2 §Phase 0 门禁）

本 SKILL 必须严格遵循宪法 §A 系列编排顺序，执行前强制完成：
1. `use_skill("dream-contradiction-theory")` — 确保矛盾框架一致（A0 C1-C8 映射）
2. 上游输入存在性检查（asset-research / A1 / A2 任一 ≤ 24h）
3. A6 监控数据新鲜度校验（>12h 标记 stale，允许降级模式运行）

---

### 4.2 执行总流程（7 Phases）

```
Phase 0: A0强制调度门禁 + 上游数据预检 ⚠️ (强制)
  [P0-1] use_skill("dream-contradiction-theory")
  [P0-2] 读取 A0 C1-C8 矛盾框架用于 §3.3 异常映射
  [P0-3] 上游输入 3选1任一 ≤24h
           • asset-research v3 cycle 结论
           • A1 调研报告 + contradiction_list
           • A2 macro_asset_analysis
  [P0-4] Phase 0 门禁清单确认（§4.3）
  → 违规处理：跳过 Phase0 → 报告 a0_integration=FAILED，A8 发P1告警

Phase 1: 数据采集与标的池构建 (5min)
  1.1 拉取 16 instId 的资金8/情绪7/周期7 = 22信号/标的
  1.2 信号新鲜度打标 (fresh <4h / acceptable <12h / stale <24h / invalid ≥24h)
  1.3 构建 Input Embedding（位置编码 + 类型编码 crypto/commodity/equity）

Phase 2: 多头注意力推理 — 三Head独立并行 (5min)
  2.1 Head1 资金注意力: Q(美林×减半×Fed) × K(8信号) → Value 16个
  2.2 Head2 情绪注意力: Q(风险偏好+VIX) × K(7信号) → Value 16个
        ⭐ 强制调用 A2 v2.3 逆向补偿三条（即使未触发也必须标注）
  2.3 Head3 周期注意力: Q(48格历史分布) × K(7信号) → Value 16个
  2.4 每头独立 Top 5 Ranking 记录（供合成后对比）

Phase 3: Co-Attention 协同注意力融合 (3min)
  3.1 方向性判定 dir(C)/dir(S)/dir(Y) ×16标的
  3.2 协同模式识别 → 映射13种 → k系数
  3.3 基础加权 B_i = 0.4C + 0.3S + 0.3Y
  3.4 熵值校验 H≥0.8? → entropy_penalty = 1.00 / 0.70
  3.5 最终 F_i = B_i × k × entropy_penalty
  3.6 A0 矛盾清单映射对齐（为 §3.3 标注维度）

Phase 4: 输出排序 + 矛盾/异常检测 (3min)
  4.1 Long Rank Top 5（F_i 降序）
  4.2 Short Rank Top 5（F_i 升序）
  4.3 Attention Heatmap + 全局熵报告
  4.4 ⭐ 矛盾/异常扫描 ≥1条；三源一致也要标「潜在反转型异常」
        否则 → "调研不充分" → 返回 Phase 4 继续扫描
  4.5 生成 integration_hints (to_a2 / to_a3)

Phase 5: A0矛盾一致性校验 + 方向性强制 (2min)
  对应 A0 IRON-3：long_rank[0].final_score > 0  OR  short_rank[0].final_score < 0
    禁止两榜 score ≈ 0（无方向性输出）
  对应 A0 IRON-4：即使 M12 三源矛盾，必须给出方向
    （熵降权可使 confidence 低至 0.35，但依然入榜，不允许 WAIT）
  A0 主矛盾侧对齐检查：不一致 → ⚠️标注并说明

Phase 6: 顾问评审 (2min) — 对齐 A2 §Phase 8 强制
  6.1 评审场景: ATTENTION_RANKING_REVIEW
  6.2 顾问组合: QT(量化) + RM(风控) 必选；若含宏观跨大类 → 追加 MR(宏观)
  6.3 advisors_review(scene="ATTENTION_RANKING")
  6.4 verdict:
        DISAGREE → 🔴 BLOCKED → 回到 Phase 3 重新校验 Head2 逆向补偿 + Head3 Query

Phase 7: 双通道投递 + AAM验证 (2min) — 宪法§12
  7.1 秘书邮箱: reports/trading/ax_attention_radar_YYYYMMDD_HHMM.md
  7.2 前端产物中心: artifacts/trading/ + index.json 更新
  7.3 artifact-alignment-manager 验证
  7.4 同步小白版到 http://8.209.238.108/market-research
```

---

### 4.3 Phase 0 门禁检查清单（强制）

```yaml
phase0_gate_checklist:
  - "[ ] use_skill(\"dream-contradiction-theory\") 已执行"
  - "[ ] A0 C1-C8 矛盾维度框架已加载（§3.3异常映射必须使用）"
  - "[ ] 上游输入数据存在且新鲜度 ≥ acceptable（≤24h）"
  - "[ ] 16 个 instId 的 OKX ticker 连通性测试通过"
  - "[ ] FearGreed / VIX / Tavily 情绪数据源配置完成或降级模拟值就绪"
```

违规处理：任何一项未勾选 → 报告 `a0_integration=FAILED`，A8 发 P1 告警。

---

### 4.4 AX 六大铁律

| 铁律编号 | 内容 | 违反后果 |
|---|---|---|
| **AX-IRON-1** | 三注意力头权重固定 = 资金 0.40 + 情绪 0.30 + 周期 0.30，微调仅 ±0.05 | 不等权重 = 流程不合规，A8 重评 |
| **AX-IRON-2** | A2 v2.3 逆向补偿三条 **必须在 Head 2 强制触发**（未触发需明确标注未触发原因） | 未调用 = Head 2 输出无效，回 Phase 2 |
| **AX-IRON-3** | 方向性强制：long_rank[0] 与 short_rank[0] 至少一方 \|final_score\| ≥ 30。不得全榜≈0 | 违反 = 进入 M12×0.5 再强制排序；confidence 可 0.35 但必须有排名 |
| **AX-IRON-4** | 矛盾预警 ≥ 1 条。三源一致也要标注「潜在反转型异常」（如 K7 历史临近反向窗口） | 0 条异常 = 调研不充分 → 返回 Phase 4 |
| **AX-IRON-5** | M12 模式 或 H < 0.8 → 该标的 final `confidence ≤ 0.5` 且不得进入 Rank 1/2 | 高排位出现低熵或 M12 = A8 批评扣分 |
| **AX-IRON-6** | 必须完成顾问评审（QT+RM/+MR）+ 双通道投递 + AAM 验证才算结束 | 少任一 = 工作未完成（宪法§12） |

---

### 4.5 产物投递规范

| 项目 | 值 |
|---|---|
| 部门名称 | 交叉分析部（注意力雷达 AX） |
| 秘书邮箱 | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| 前端产物中心 | `~/.workbuddy/artifacts/trading/` |
| 产物类型 / file_type | `attention_radar` |
| 文件名格式 | `ax_attention_radar_{YYYYMMDD}_{HHMM}.md` |
| 自动化调度建议 | 路径②：A2 完成后 30 分钟触发；独立路径：周一 11:00 + 周四 21:00 |
| 下游消费者 | A2（cross_dimension 权重） / A3（三预设优先级） |
| 触发词 | 注意力雷达、三源注意力、标的筛选、多空排名、attention radar |

**完整 frontmatter（8字段，对齐A2风格）：**

```yaml
---
title: "AX注意力雷达 2026-08-11 14:30"
department: trading
chain_phase: AX
date: "2026-08-11T14:30:00+08:00"
type: attention_radar
status: completed
tags: "ax attention-radar 多空排名 标的筛选"
by_a_phase: AX
---
```

---

### 4.6 A8 批评与自评机制

SKILL 运行完毕必须附 `§自评章节`，并接受 A8 批评检查：

| A8 维度 | 通过标准 | 本 SKILL 自查项 |
|---|---|---|
| 批判性思维 (Paul 8元素) | ≥75% 覆盖 | 信息(数据新鲜度)、推断(协同模式逻辑)、视角(异常对立视角)、意涵(榜单后果)、假设(Query历史分布)、概念(注意力权重定义)、前提(美林时钟有效性)、问题(是否真的需要注意力排序) |
| 认知偏差 (Kahneman 7偏差) | ≥60% 识别 | 锚定(某个历史模式K7)、确认偏误(挑三源一致标的忽视矛盾)、过度自信(H低却自信)、损失厌恶(空头榜置信度偏低)、可得性(BTC/ETH权重天然偏高)、框架效应(多头表述比空头积极)、基础概率忽略(跨大类胜率先验) |
| 理性评估 (Stanovich) | 理性评分 ≥ 60 | `attention_rationality_self_assessment` 附报告末尾（满分100，需≥60） |
| 知行合一 (实践论) | alignment_score ≥ 60 | `alignment_score = A0对齐度×0.4 + 历史回测一致性×0.3 + A2/A3采纳率×0.3` |

---

### 4.7 FAQ 踩坑预埋

> ⚠️ **权重不可调**：资金/情绪/周期 = 0.4/0.3/0.3 固定 ±0.05 微调上限。违反 AX-IRON-1
> ⚠️ **M12 三源矛盾不可 SKIP**：必须入榜，confidence 可低至 0.35 但不得 WAIT（AX-IRON-3）
> ⚠️ **Head 2 逆向补偿必执行**：即使 FGI=50 也必须写「未触发阈值」。违反 AX-IRON-2
> ⚠️ **熵 H<0.8 必 ×0.7**：某头再自信也必须降权 30%。违反 AX-IRON-5
> ⚠️ **🔴 双通道必投递**：仅秘书邮箱 = 工作未完成。违反 AX-IRON-6 宪法§12
> ⚠️ **矛盾预警 ≥1 条**：三源一致也要找「潜在反向窗口」。违反 AX-IRON-4

---

## 附录：调度（对应 A2 末尾调度触发声明）

**本 SKILL 结束后推荐的下游 SKILL（可链式触发）：**

- 若 `query_mode = A1→AX→A2`（路径①）→ 自动调用
  `use_skill("dream-first-principles", input={attention_radar_long_rank, attention_radar_short_rank, ...})`
- 若 `query_mode = A2→AX→A3`（路径②）→ 自动调用
  `use_skill("dream-strategy-designer", input={target_symbol_priority_from_attention_radar, ...})`
- 若 `query_mode = STANDALONE`（路径③独立运行）→ 通知 A6 监控部 + 秘书归档，不强制下游

---

*文档版本 v1.0.0 | 2026-08-11 | 交叉分析部 注意力雷达 AX*
