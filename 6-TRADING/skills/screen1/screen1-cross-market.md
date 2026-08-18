# /screen1-cross-market

**Screen 1 — 维度F：跨市场周期深度研究**

跨市场周期 SKILL。结合美林时钟四象限定位 + 跨资产相对表现 + 领先滞后关系，判断 BTC 当前所处宏观周期位置，写入 `screen1_cross_market_annotation.json`。

> **BTC-only**: 跨资产周期分析以 BTC 在全球资产中的角色定位为核心，ETH/SOL 跳过此维度。

---

## 一、美林时钟框架

### 1.1 四象限结构

美林时钟是宏观周期定位的核心工具，以 GDP 增长（横轴）和 CPI 通胀（纵轴）将宏观环境划分为四个象限，每个象限对应不同的资产表现顺序。

```
              CPI ↑ (通胀高)
                    │
  Overheat          │         Stagflation
  GDP↑ CPI↑         │         GDP↓ CPI↑
  商品>债券>股票>BTC  │         现金>商品>BTC/股票
  score: 0          │         score: -5
                    │
GDP↓ ───────────────┼─────────────────── GDP↑
                    │
  Reflation         │         Recovery
  GDP↓ CPI↓         │         GDP↑ CPI↓
  债券>BTC>股票      │         BTC>股票>债券>商品
  score: +5         │         score: +10
                    │
              CPI ↓ (通胀低)
```

### 1.2 各象限深度分析

**Recovery（复苏）— BTC 最优阶段**
```
条件: GDP>3% + CPI<2%（理想"金发姑娘"环境）
机制: 
  增长强劲 → 企业盈利上行 → 风险偏好提升
  通胀低  → Fed 无加息压力 → 利率环境宽松
  BTC表现: 历史上 Recovery 阶段 BTC 领涨全球资产
历史案例: 2020-2021 Recovery → BTC +1700%（领先所有资产）
```

**Overheat（过热）— BTC 中性**
```
条件: GDP>3% + CPI>2%
机制:
  增长仍强 → 但通胀升温 → Fed 开始讨论加息
  商品受益于通胀 → 债券受压 → 股票高位震荡
  BTC表现: 加息预期初期 BTC 通常跟随股票高位波动
历史案例: 2021Q3-2022Q1 Overheat末 → BTC 从 $69K 开始回落
警告信号: GDP 依然强劲但 BTC 开始走弱 = 过热见顶前兆
```

**Stagflation（滞胀）— BTC 最差阶段**
```
条件: GDP<0%（或接近衰退）+ CPI>2%
机制:
  增长萎缩 → 企业盈利恶化 → 风险资产估值收缩
  通胀顽固 → Fed 无法降息 → 利率高位维持
  双重打击: BTC 既没有经济增长支撑，又没有宽松流动性
历史案例: 2022 经典滞胀 → BTC -75%（最大跌幅历史第二）
```

**Stagflation Lite（轻度滞胀）— 当前 2026-06**
```
条件: GDP>0% 但 <3%（非衰退）+ CPI>2%（通胀顽固）
机制:
  增长正但偏弱（美国 GDP ~+2%）
  通胀 CPI ~3.5%，高于 Fed 2% 目标
  失业率 ~4.5% 且上升 → 劳动力市场开始松动
  → 既无衰退的确认（不像经典 Stagflation）
  → 也无宽松条件（通胀未回目标）
BTC表现: 承压，但比经典 Stagflation 更容易出现阶段性反弹
```

**Reflation（再通胀/复苏前期）— BTC 等待拐点**
```
条件: GDP<0%（或刚脱离衰退）+ CPI<2%（通胀已回落）
机制:
  衰退期通胀自然压低 → Fed 降息空间打开
  央行开始 QE/降息 → 流动性注入开始传导
  BTC表现: 通常领先其他资产反弹（敏感度最高）
历史案例: 2023 Reflation → BTC +300%（超过预期）
关键识别: 10Y 收益率从峰值开始回落 = Reflation 启动信号
```

### 1.3 当前定位规则

| GDP增速 | CPI水平 | 象限 | 评分 |
|--------|--------|------|------|
| >3% | <2% | **RECOVERY** | +10 |
| >0% 且 <3% | >2% | **STAGFLATION_LITE** | -5 |
| >3% | >2% | **OVERHEAT** | 0 |
| <0% | >2% | **STAGFLATION** | -5 |
| <0% | <2% | **REFLATION** | +5 |

---

## 二、BTC 角色演变历史（关键背景）

理解 BTC 当前角色是跨市场分析的前提。BTC 的"本质属性"在不同时期有本质区别：

```
2020-2021: BTC = "数字黄金" + "超级风险资产"
  - Fed QE → 放水受益最大
  - 黄金 vs BTC: 均上涨，BTC 更猛（+1700% vs 黄金 +25%）
  - 与 NASDAQ 相关: ~0.5（部分独立行情）

2022: BTC = "高贝塔科技股"
  - 加息周期 → BTC 与 NASDAQ 同步崩跌
  - 相关系数: 与 NASDAQ ~+0.85 (同向下跌)
  - 黄金逆势抗跌 → BTC 失去"数字黄金"属性

2023-2024: BTC = "ETF 驱动独立行情"
  - 现货 ETF 预期 → 机构资金抢跑 → 与传统资产解耦
  - 与 NASDAQ 相关: 阶段性降至 ~0.3（独立行情期）

2025-2026: BTC = "高贝塔科技股 2.0"
  - 关税政策 + Stagflation Lite → BTC 重归科技股属性
  - 与 NASDAQ 相关: -0.9（近似同步）  ← 2026Q1-Q2
  - 黄金 YTD +39% vs BTC -22% → BTC 明确 ≠ 数字黄金

⚠️ 当前 (2026-06):
  BTC 不是"数字黄金"，不具备黄金的避险属性
  BTC 是"高贝塔科技股"，NASDAQ 方向决定 BTC 方向
  分析框架必须基于此，否则导致方向性判断错误
```

---

## 三、跨资产相对表现框架

### 3.1 黄金 vs 股票（防御/进攻模式判断）

```
黄金 YTD > SPX YTD + 10%  → GOLD_STRONG（防御模式）
  含义: 机构在对冲不确定性，风险偏好下降
  BTC 影响: 负面（BTC = 高贝塔科技股，防御模式下承压）
  历史案例: 2026 YTD 黄金 +39% vs SPX -7% → GOLD_STRONG → BTC -22%

黄金 YTD 与 SPX YTD 相差 <10%  → NEUTRAL（过渡模式）
  含义: 防御 vs 进攻力量均衡
  BTC 影响: 中性，其他因素决定方向

SPX YTD > 黄金 YTD + 10%  → STOCKS_STRONG（进攻模式）
  含义: 风险偏好上升，机构在追求增长
  BTC 影响: 正面（BTC 作为高贝塔资产跟随受益）
  历史案例: 2020-2021 → SPX 强于黄金 → BTC 最强
```

**评分**: GOLD_STRONG=-3 | NEUTRAL=0 | STOCKS_STRONG=+3

### 3.2 BTC vs NASDAQ 相关性（角色判断）

```
相关 > 0.7:
  BTC = 高贝塔科技股
  → NASDAQ 涨则 BTC 涨更多，NASDAQ 跌则 BTC 跌更多
  → 当前 (~-0.9 相关，2026Q1-Q2) → 策略上等同于 3× NASDAQ

相关 0.3-0.7:
  BTC = 部分独立行情
  → 需要结合链上指标 + ETF资金流综合判断
  → 通常出现在 ETF 审批预期或减半期间

相关 < 0.3:
  BTC = 走独立行情
  → 链上事件（减半）or 机构 ETF 驱动
  → 传统跨市场框架部分失效，需重点看链上 + 减半周期维度
```

---

## 四、领先滞后关系框架

### 4.1 10Y 收益率领先规律

```
机制: 10Y 收益率是机构资金配置的"分水岭"
  10Y 从峰值开始回落 → 机构重新评估风险资产配置
  → 约 3-6 个月后 BTC 开始上涨趋势

历史验证:
  2019: 10Y 从 3.2% 回落 → 约 6 个月后 BTC 开始上涨
  2023: 10Y 从 5.0% 高点回落 → 约 4 个月后 BTC 底部确认
  当前: 10Y 从 ~5.0% 高点回落 ~0.7pp → BTC 3-6 个月反弹预期形成中

评分规则:
  RISING: -3（收益率上升 = 流动性收紧）
  FLAT:    0
  FALLING <0.5pp: +1（回落趋势形成但未确认）
  FALLING ≥0.5pp: +3（趋势确认，约 6 个月内传导至 BTC）
```

### 4.2 全球 M2 领先规律（跨市场视角）

```
与宏观维度的 M2 分析不同点:
  宏观维度: 看 M2 绝对水平 → 流动性高低
  跨市场维度: 看 M2 与 BTC 的相对位置 → 补涨时间窗口

当 M2 YoY 高但 BTC 未跟上时（背离状态）:
  历史规律: 6-12 个月内 BTC 补涨
  判断标准: M2 增速 vs BTC 价格变化是否同向

评分规则（跨市场视角下，分值更保守）:
  M2 >+10% YoY: +3
  M2 +5~10%: +1
  M2 ±5%: 0
  M2 <-5%: -3
```

### 4.3 DXY 趋势（风险资产支撑/阻力）

```
机制: DXY 趋势直接影响全球风险资产流动性
  DXY 下降 → 美元流出 → 非美资产（含 BTC）流动性改善
  DXY 上升 → 资本回流美元 → 全球风险资产承压

评分规则（跨市场维度聚焦趋势方向）:
  RISING:  -2
  FLAT:     0
  FALLING: +2
```

---

## 五、历史情景验证

| 时期 | 时钟阶段 | 黄金/股 | 收益率 | DXY | M2 | 总分 | 信号 | BTC表现 |
|------|--------|--------|------|-----|-----|------|------|---------|
| 2020-2021 QE | RECOVERY | STOCKS_STRONG | FLAT | FALLING | +16% | +18 | BULL | +1700% |
| 2021末 过热 | OVERHEAT | STOCKS_STRONG | RISING | RISING | +12% | +1 | NEUTRAL | 高位震荡 |
| 2022 加息高峰 | OVERHEAT | GOLD_STRONG | RISING | RISING | -3% | -11 | BEAR | -75% |
| 2022Q4 底部 | STAGFLATION | GOLD_STRONG | FLAT | FLAT | -2% | -8 | BEAR | 底部筑底 |
| 2023 复苏初期 | REFLATION | NEUTRAL | FALLING -0.6pp | FALLING | +5% | +11 | BULL | +300% |
| 2024 ETF批准 | RECOVERY | STOCKS_STRONG | FALLING -0.3pp | FALLING | +7% | +17 | BULL | +150% |
| **2026-06 当前** | **STAGFLATION_LITE** | **GOLD_STRONG** | **FALLING -0.7pp** | **FALLING** | **+12%** | **0** | **NEUTRAL** | -22% |

> **2026-06 解读**: 总分 0（NEUTRAL），信号内部矛盾：
> - **偏空**: Stagflation Lite（-5）+ GOLD_STRONG（-3）= 当期环境不利 BTC
> - **偏多**: 收益率回落 0.7pp（+3）+ DXY 走弱（+2）+ M2 +12%（+3）= 领先信号积累
> 这种"当期空 vs 领先多"的矛盾 = 经典的底部积累特征

---

## 六、评分体系

| 指标/状态 | 分数 |
|---------|------|
| **美林时钟阶段** | |
| Recovery (GDP↑ CPI↓) | **+10** |
| Reflation (GDP↓ CPI↓) | +5 |
| Overheat (GDP↑ CPI↑) | 0 |
| Stagflation (GDP↓ CPI↑) | -5 |
| Stagflation Lite (GDP正 CPI↑) | -5 |
| **跨资产相对强弱** | |
| STOCKS_STRONG（股票 > 黄金）| +3 |
| NEUTRAL（相差 <10%）| 0 |
| GOLD_STRONG（黄金 > 股票）| -3 |
| **10Y 收益率趋势** | |
| 上升趋势 | -3 |
| 平稳 | 0 |
| 回落 <0.5pp | +1 |
| 回落 ≥0.5pp（趋势确认）| +3 |
| **DXY 趋势** | |
| 上升 | -2 |
| 平稳 | 0 |
| 下降 | +2 |
| **M2 领先信号** | |
| >+10% YoY | +3 |
| +5~10% | +1 |
| ±5% | 0 |
| <-5% | -3 |

**信号阈值**: score ≥ +5 → BULL | score ≤ -5 → BEAR | 其他 → NEUTRAL

---

## 七、执行步骤

### Step 1 — 运行代码基线

```bash
cd /c/tmp && python cross_market_detector.py
```

查看历史周期情景对比，确认评分映射表。

> **AI 不可用回退**: 若 Step 2 全部搜索失败，基于宏观公开已知信息（GDP 约+2%，CPI 约3.5%，M2 +12%）直接定位时钟阶段，写入 annotation，`score_adjustment=0`，`confidence=0.50`，流程继续。

---

### Step 2 — 搜索跨市场数据（Tavily）

使用 `mcp__tavily__tavily-search`。**禁止使用 WebSearch/WebFetch/curl。**

按顺序搜索：

1. `"US GDP growth CPI inflation Q2 2026 stagflation"` — 确定美林时钟象限
2. `"gold vs S&P 500 performance YTD 2026"` — 跨资产相对强弱
3. `"Bitcoin NASDAQ correlation 2026"` — BTC 当前资产角色定位
4. `"US 10 year treasury yield peak decline 2026"` — 收益率趋势（与宏观维度可复用）
5. `"global M2 money supply acceleration 2026"` — M2 领先信号（与宏观维度可复用）

> 注：第 4、5 条与 `/screen1-macro-finance` 有重叠。若宏观 annotation 近期（≤7天）已更新，可直接读取 `screen1_macro_annotation.json` 中的 `m2_yoy_pct`、`dxy_trend`、`yield_10y_pct` 值，无需重复搜索。

---

### Step 3 — 美林时钟精确定位

根据搜索结果，回答以下 4 个核心问题：

| 问题 | 参考数据 | 象限判断 |
|------|---------|---------|
| GDP 是否正增长？ | ~+2.2% | 偏右（非衰退）|
| CPI 是否高于目标（2%）？ | ~3.5% | 偏上（通胀顽固）|
| 增长是否强劲（>3%）？ | 否 | 非经典 Overheat |
| 失业率趋势？ | 4.5% 上升 | 偏左压力 |

定位规则：
- GDP>3% + CPI>2% → **OVERHEAT**
- GDP>0% + CPI>2% 但 GDP<3% → **STAGFLATION_LITE**
- GDP<0% + CPI>2% → **STAGFLATION**
- GDP<0% + CPI<2% → **REFLATION**
- GDP>3% + CPI<2% → **RECOVERY**

---

### Step 4 — 跨资产相对表现评估

**黄金 vs 股票对比（YTD 数据）**:
- 黄金 YTD > SPX YTD + 10% → GOLD_STRONG（防御模式，BTC 不利）
- 黄金 YTD 与 SPX YTD 相差 <10% → NEUTRAL
- SPX YTD > 黄金 YTD + 10% → STOCKS_STRONG（风险偏好，BTC 受益）

**BTC vs NASDAQ 当前相关性**:
- 相关 > 0.7：BTC = 高贝塔科技股，NASDAQ 方向决定 BTC 方向
- 相关 0.3-0.7：部分独立，需综合判断
- 相关 < 0.3：BTC 走独立行情（通常 ETF 驱动或链上事件驱动）

---

### Step 5 — 计算分数与 score_adjustment

```
时钟阶段 = [STAGFLATION_LITE] → 分: -5
黄金/股票 = [GOLD_STRONG]      → 分: -3
10Y 趋势 = [FALLING -0.7pp]   → 分: +3
DXY 趋势 = [FALLING]          → 分: +2
M2 领先  = [+12% YoY]         → 分: +3
代码总分                        = 0
```

`score_adjustment` 定性因素（±5）：
- 时钟阶段转换的时间进程（接近转换点 → +1~2）
- BTC 与 NASDAQ 相关性是否开始下降（解耦信号 → +1~2）
- 地缘政治对商品/黄金的暂时性提振是否已消退（→ ±1）
- 跨资产信号内部一致性 vs 矛盾程度（全一致 → +1，强矛盾 → -1）

`confidence`:
- 5 条搜索全有数据且一致 → 0.85~0.90
- 3-4 条有效 → 0.65~0.80
- 1-2 条有效 → 0.50~0.65
- 0 条（AI 不可用）→ 0.50，使用公开已知数据定位时钟，`score_adjustment=0`

---

### Step 6 — 撰写跨市场叙事（narrative）

2~4 句中文，结构：
```
[时钟阶段定位] + [BTC当前角色] + [领先信号状态] + [周期转换预期时间]
```

示例：
> "当前处于'Stagflation Lite'象限（GDP+2.2%，CPI 3.5%），黄金 YTD +39% vs SPX -7%，市场处于防御模式，BTC 作为高贝塔科技股（与 NASDAQ 相关 ~-0.9）同步承压，而非数字黄金。但领先信号正在积累：10Y 收益率从 5.0% 高点回落 0.7pp（历史上领先 BTC 3-6 个月），M2 +12%（领先 1-2 季），DXY 走弱——这些信号指向美林时钟可能在 2026Q3-Q4 转向 Reflation。参照 2023 年 Reflation 期（BTC +300%），当前是周期转换前的底部积累窗口。"

---

### Step 7 — 写入注释文件

写入 `C:\tmp\Dreambuddy-V2\6-TRADING\screen1_cross_market_annotation.json`：

```json
{
  "updated": "<今日日期 YYYY-MM-DD>",
  "clock_stage": "<RECOVERY/OVERHEAT/STAGFLATION/STAGFLATION_LITE/REFLATION>",
  "gold_vs_stocks": "<GOLD_STRONG/NEUTRAL/STOCKS_STRONG>",
  "yield_trend": "<FALLING/FLAT/RISING>",
  "yield_drop_pct": <从峰值回落百分点>,
  "dxy_trend": "<FALLING/FLAT/RISING>",
  "m2_yoy_pct": <数值>,
  "btc_nasdaq_correlation": <相关系数>,
  "btc_role": "<高贝塔科技股/数字黄金/独立行情>",
  "score_adjustment": <[-5,+5]>,
  "final_signal": "<BULL/BEAR/NEUTRAL>",
  "confidence": <0.50~0.90>,
  "narrative": "<跨市场叙事>",
  "clock_transition_outlook": "<下一个时钟阶段预期及时间>",
  "signal_conflict_note": "<当期空 vs 领先多的矛盾说明>",
  "dimension_scores": {
    "clock_stage": <分数>,
    "gold_vs_stocks": <分数>,
    "yield_trend": <分数>,
    "dxy_trend": <分数>,
    "m2_leading": <分数>,
    "qualitative_adj": <score_adjustment>
  }
}
```

---

### Step 8 — 输出摘要

```
=== Screen 1 跨市场周期分析 ===
当前日期: YYYY-MM-DD
美林时钟: [阶段] (GDP~X%, CPI~Y%)     → 分: +/-X
黄金/股票: [状态]                      → 分: +/-Y
10Y 趋势: [FALLING/FLAT/RISING] -X.Xpp → 分: +/-Z
DXY 趋势: [方向]                       → 分: +/-W
M2 领先:  X.X% YoY                     → 分: +/-V
代码总分: +/-T | 定性调整: +/-U | 最终分: +/-S
最终信号: [BULL/BEAR/NEUTRAL] | 置信度: X%
BTC 角色: [高贝塔科技股/数字黄金/独立行情]
时钟转换展望: [预期时间与下一象限]
注释已写入: C:\tmp\Dreambuddy-V2\6-TRADING\screen1_cross_market_annotation.json
```

---

## 八、回退逻辑

| 场景 | 行为 | 数据来源 |
|------|------|---------|
| SKILL + 所有搜索成功 | 五维全量跨市场评分 | Tavily 实时数据 |
| 部分搜索成功 | 可用指标评分 | 部分实时 + 推断 |
| AI 不可用 | GDP/CPI 公开数据定位时钟，其他项为空 | 公开宏观数据 |
| `cross_market_detector` import 失败 | signal=NEUTRAL，控制台警告 | 维度关闭 |
| annotation 不存在 | `calc_cross_market()` 无参 → NEUTRAL | no_data |

> 与宏观维度的协作: 若 `screen1_macro_annotation.json` 近期已更新，可直接读取其中的 `m2_yoy_pct` 和 `dxy_trend` 字段，避免重复搜索。跨市场维度与宏观维度的差异在于**视角**——宏观看因子水平，跨市场看因子趋势与资产相对排位。

---

## 九、注意事项与常见误区

| 误区 | 正确认知 |
|------|---------|
| "BTC = 数字黄金，通胀高时买 BTC" | 2025-2026 BTC = 高贝塔科技股，黄金涨时 BTC 可能跌 |
| "黄金涨说明通胀 → BTC 受益" | 当 BTC 与 NASDAQ 高相关时，黄金涨 = 防御模式 = BTC 承压 |
| "Stagflation 下 BTC 必须清仓" | 领先信号（收益率/M2/DXY）可能指向 6 个月后反转，需综合判断 |
| "美林时钟信号一致才能入场" | 当期空 + 领先多 = 底部积累特征，也是低估窗口 |
| "相关性是固定的" | BTC 角色动态变化，需每季度更新相关系数确认 |

- **搜索工具**: 必须使用 `mcp__tavily__tavily-search`，禁止 WebSearch/WebFetch/curl
- **BTC 角色认知**: 当前 BTC = 高贝塔科技股，非数字黄金；分析时需基于此判断跨资产关系
- **时钟阶段转换节点**: 每次 GDP 初值发布（每季度）和 CPI 数据后必须重新定位
- **领先信号 vs 当期表现**: 时钟阶段看当期（偏空），领先信号看未来（偏多）——两者并存不矛盾，是底部积累的核心特征
- **调整上限**: `score_adjustment` 限制 ±5
- **更新频率**: 每月至少一次（跟随 CPI/GDP 数据发布节奏）
