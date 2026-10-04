# SPEC: 美国宏观事件驱动交易策略 — 数据采集 + 利空出尽识别 + 不确定性消除/深层利空权衡 + 自进化学习

> **状态：** Spec（v2.0，已纳入深度调研）
> **创建：** 2026-09-17
> **更新：** 2026-09-17（v2.0 增加深度调研：传统机构做法、GitHub 开源库、不确定性消除 vs 深层利空权衡机制）
> **目标：** 为自进化系统补充美国重要金融事件（FOMC 利率决议、CPI、非农等）的数据采集、"利空出尽"模式识别策略，以及**"不确定性消除"与"深层利空"的动态权衡机制**，使系统能在重大宏观事件窗口期做出更优的多空决策，避免 relief rally 陷阱。
> **约束：** FAIL-OPEN 铁律不可破坏；工业级代码标准；不新增不必要文件；复用现有 ESE `_eval_macro` 消费端；策略默认关闭，需显式开关激活。

***

## 零 · 问题总结

### 0.1 调研触发的业务背景

2026-09-16 美联储加息 25bp（2023 年以来首次），CME FedWatch 显示 93% 概率已定价。落地后 BTC 守住 $75K 支撑反冲高 $76K，纳指收复大部分失地仅跌 0.01%，费城半导体逆势 +0.63%，海力士深跌后收出下影线。此为经典"利空出尽（Priced In）"底部信号，但系统当前**无能力识别此类事件驱动机会**。

### 0.2 当前系统缺口全景

调研发现系统存在"消费端已就绪、供给端缺失"的断层：

| 层级 | 组件 | 现状 | 缺口 |
|:--|:--|:--|:--|
| **数据采集** | `FredCollector` | ✅ 已采集 FRED 月度序列（CPI/PPI/M2/FEDFUNDS） | ❌ 无 FOMC 决议事件数据（actual/forecast）<br>❌ 无 CME FedWatch 加息概率<br>❌ 无美国经济日历事件<br>❌ 无事件前后市场反应快照 |
| **数据管线** | `data_pipeline.py` | ✅ 接入 BCRM/BDSM/五计/ETF/链上/期权等 | ❌ 未注入 `cpi_actual`/`cpi_expected`/`rate_hike_prob`/`monetary_cycle` |
| **策略评估** | `ESE._eval_macro()` | ✅ 已实现消费上述 4 字段，输出 macro short/medium/long | ⚠️ 因上游无数据，macro 维度恒为 0.5（中性退化） |
| **策略基因** | `combination.json` | ✅ `strategy_type` 含 `event_arbitrage` | ❌ `event_arbitrage` 无具体基因实现 |
| **自进化** | `ReflectionEngine`/`ShadowRL` | ✅ 真实 PnL reward 闭环 | ❌ 无事件上下文快照供学习 |

### 0.3 "利空出尽"模式的可量化定义

基于前序调研，模式需同时满足：

1. **定价充分度**：CME FedWatch 事件概率 ≥ 85%
2. **落地抗跌**：决议后 4h 内价格未破前低，或收回失地 ≥50%
3. **下影线确认**（可选增强）：事件当日 K 线下影 ≥ 实体 2 倍 + 放量
4. **跨资产验证**（可选增强）：半导体/高 beta 板块走强、DXY 走弱

满足 ≥3 项 → 标记为 `priced_in_bottom` 事件，策略倾向平空转多。

### 0.4 深度调研补充：不确定性消除 vs 深层利空的权衡（核心问题）

> **用户提出的关键质疑**：利空出尽只是不确定性消除，深层利空（高利率持续、信用收缩、通胀粘性）并不支持过分看涨，中间如何权衡？

#### 0.4.1 传统机构的做法

**桥水（Dalio）— 短期债务周期框架**：
- 短期债务周期 5-8 年，紧缩阶段的反弹是"信用收缩周期中的喘息"，不改变大方向
- 核心传导链：加息→借贷成本上升→债务偿还压力→支出下降→信用收缩→资产价格承压
- 反弹的本质是"不确定性消除"带来的情绪修复，而非信用周期反转
- 桥水事件前布局工具：**利率期权（对冲）+ 国债期货（跟踪）+ 黄金ETF（避险）**，三腿组合而非单边

**AQR / Two Sigma 系统化宏观**：
- 四因子框架：`carry / value / momentum / defensive`，每个信号**等波动率贡献**
- 事件驱动只是其中一个因子，不单独主导仓位
- 仓位缩放公式：`Position Size = Base Size × (1/Volatility) × (1/Event Proximity)` — 越靠近事件、波动率越高，仓位越小

**文艺复兴（Renaissance）**：
- 事件前用利率期权对冲，事件后快速调仓（10年期国债期货），跟踪而非长期持有

#### 0.4.2 Relief Rally 的持续时间规律

| 研究来源 | 结论 |
|:--|:--|
| Positioned.app 定义 | Relief Rally 通常**几天到两周**，1-2 周内消退，因情绪驱动非基本面改善 |
| GoldPriceForecast | FOMC 后价格反应通常 **5-9 个交易日**，5-6 天最常见 |
| 2023 年 Fed 加息案例 | 2023.07 加息后市场跌 9% 直到 10 月，10 月底因鸽派+CPI 回落才反弹 12.2% — 加息周期中的反弹很短暂 |
| 2026.04 空头回补案例 | S&P 500 空仓 2.916M 合约（10年高点），但 days-to-cover 仅 1.9 天 → 燃料快速耗尽 |

**核心规律**：Relief Rally 的持续时间取决于**空头回补的燃料量**。当 short interest ratio（days to cover）< 2 天时，反弹通常在 1-2 周内结束。

#### 0.4.3 深层利空重新主导的 5 个条件

| 条件 | 信号 | 权重 |
|:--|:--|:--|
| **更高更久（Higher for longer）** | 美联储点阵图中位数上移 / 鹰派发言 / 年内加息预期升温 | 高 |
| **通胀粘性** | CPI/PPI 再度超预期 / 核心通胀回落停滞 | 高 |
| **信用收缩传导** | 信贷标准收紧 / 企业债利差走阔 / 违约率上升 | 中 |
| **盈利无法支撑估值** | EPS 增长不及预期 / 估值-盈利背离扩大 | 中 |
| **空头回补耗尽** | short interest ratio < 2 天 / CTA 资金流入完成 | 中 |

**满足 ≥2 项高权重条件 或 ≥3 项任意条件** → relief rally 结束，深层利空主导，策略从多头转回中性/空头。

#### 0.4.4 三层权衡机制（本 SPEC 的核心创新）

基于深度调研，设计**三阶段动态权衡**：

```
事件落地后
    │
    ▼
┌─────────────────────────────────────┐
│ Phase A: Relief 阶段（事件后 0-5 天） │
│ 主导力量：不确定性消除 + 空头回补      │
│ 策略：平空 + 轻仓试多（probe）        │
│ 仓位：base × 0.5                     │
│ 止损：下影线最低点                    │
└──────────────┬──────────────────────┘
               │ 5 天后检查
               ▼
┌─────────────────────────────────────┐
│ Phase B: 验证阶段（事件后 5-15 天）   │
│ 关键问题：基本面是否真的改善？         │
│ 检查清单：                            │
│   - 通胀是否继续回落？                 │
│   - 信贷是否重新扩张？                 │
│   - 盈利预期是否上修？                 │
│   - 空头回补是否完成？                 │
│ 策略：                                │
│   - ≥2项改善 → 升级为标准多仓          │
│   - 0-1项改善 → 减仓观望              │
│   - 恶化 → 反手做空                   │
└──────────────┬──────────────────────┘
               │ 15 天后
               ▼
┌─────────────────────────────────────┐
│ Phase C: 趋势阶段（事件后 15 天+）    │
│ 主导力量：债务周期位置（Dalio 框架）   │
│  - 短期债务周期扩张期 → 继续持有多头    │
│  - 短期债务周期紧缩期 → 深层利空主导    │
│  - 长期债务周期后期 → 避险为主          │
└─────────────────────────────────────┘
```

#### 0.4.5 经典理论支撑

- **Dalio 短期债务周期**：紧缩阶段→信用收缩→支出下降。反弹是周期噪声，不改变收缩趋势
- **索罗斯反身性**：价格与基本面自我强化/毁灭。事件后反弹若无基本面跟进，反身性反向作用
- **EMH + 预期差**：市场定价预期差，不确定性消除但基本面未改善时，价格缺乏持续动力

#### 0.4.6 GitHub 开源库与学术成果参考

| 项目/论文 | 类型 | 可借鉴点 |
|:--|:--|:--|
| **CAMEF**（KDD 2025） | 学术论文 | 因果增强多模态事件驱动预测；发现 FOMC Minutes 预测力最强，CPI/PPI 较弱；LLM 反事实事件增强 |
| **gs-quant**（高盛开源） | Python 库 | 事件驱动策略回测引擎、因子风险模型 |
| **NautilusTrader**（26.4K★） | Rust+Python | 事件驱动回测框架，backtest-to-live parity |
| **zipline-reloaded** | Python | Quantopian 开源事件驱动回测引擎 |
| **backtrader** | Python | 经典量化框架，支持事件驱动+向量化双模式 |
| **FXMacroData** | API 服务 | FOMC/CPI 日历 + 宏观信号 REST API |

**本系统的差异化定位**：不引入完整回测框架（已有自研引擎），重点借鉴 CAMEF 的**因果增强事件建模**和**反事实数据增强**思路，以及 AQR 的**等波动率仓位管理**。

### 0.5 议息交易周期（FOMC Trade Cycle）与资产分化

> 用户核心观察：黄金 8/25 开始下跌、BTC 同期滞涨、海力士走势不同——围绕议息存在一个可交易的周期，不同资产反应分化。
> **关键修正**：议息交易周期不是"前 3 天"，而是从 **CME FedWatch 概率开始变化**的那一刻就启动，可长达 4-6 周。

#### 0.5.1 完整议息交易周期：从预期演化到落地（6 阶段）

以 2026.9.16 FOMC 加息 25bp 为案例，还原完整时间线：

| 阶段 | 时间窗口 | 关键事件 | FedWatch 概率 | 资产表现 |
|:--|:--|:--|:--|:--|
| **① 预期积累期** | FOMC 前 4-6 周 | 上次会议后，市场开始积累下次预期 | 36%（8月中） | 黄金从 $5,589 高点开始回落 |
| **② 预期升温期** | FOMC 前 2-4 周 | Jackson Hole（8/27-29）沃什鹰派讲话 | 48%→59% | 黄金 8/25 起加速下跌，BTC 滞涨 |
| **③ 预期跳变期** | FOMC 前 1-2 周 | **CPI（9/11）+ PPI（9/10）超预期** | 59%→88% | 10Y 美债破 5%，黄金急跌，美元走强 |
| **④ 预期消化期** | FOMC 前 3 天 | 概率接近充分定价 | 88%→93% | 黄金技术性反弹（空头获利了结） |
| **⑤ 事件落地期** | FOMC 当天 | 决议 + 点阵图 + 发布会 | 93%（落地） | 沃什鹰派→黄金跌 1%，道指跌 1.21% |
| **⑥ 预期重定价期** | FOMC 后 1-3 周 | 市场定价下次会议 + FOMC 纪要 | 10 月加息 53% | 方向取决于通胀/就业数据 |

**核心规律**：
- **CPI/PPI 是概率跳变的触发器**：9/10 PPI + 9/11 CPI 超预期，概率从 59% 跳到 88%
- **Jackson Hole（8 月底）是政策信号窗口**：沃什鹰派讲话启动升温期
- **FOMC 纪要（会议后 3 周）**：20+ 页内部讨论，揭示分歧，常引发市场重新定价
- **实际利率与黄金的量化关系**：实际利率每上升 1 个百分点，金价平均回调 **15%**（2000-2025 回测）

**FOMC 当天五阶段**（pro-scalper 研究，叠加在阶段④⑤之上）：

| 子阶段 | 时间窗口 | 市场行为 |
|:--|:--|:--|
| Pre-FOMC Drift | 前 3 个交易日 | 沿预期方向漂移，加息预期→黄金日跌 15-25 pips |
| Statement Spike | 决议后 5 分钟 | 最高波动窗口，30-80 pips，预期差驱动 |
| Press Conference Reversal | 决议后 30-60 分钟 | 主席讲话常反转方向 |
| Trend Establishment | 决议后 1-2 小时 | 方向确立，40-80 pips，最可靠入场点 |
| Cross-Session Follow-Through | 决议后 24-48 小时 | 亚盘欧盘继续趋势 |

**NBER 周效应补充**（Cieslak et al. 2014）：股权溢价仅在 FOMC 周期的第 **0、2、4、6 周**获得（偶数周），奇数周（1、3、5）收益接近零。因 Fed 信息处理/决策倾向双周发生。**137 个议息间周期平均 33 个交易日**。

#### 0.5.2 不同资产在议息周期中的分化表现

| 资产 | 议息周期驱动因子 | 2022-2023 紧缩期表现 | 2026.9 本次表现 |
|:--|:--|:--|:--|
| **黄金** | 实际利率（名义利率 - 通胀预期） | 先跌后涨，加息落地后 6 个月均 +6.6% | 8/25 起提前下跌，加息落地后或修复 |
| **BTC** | 2022-2023 与利率强负相关；历史总体低相关 | 与加息强负相关，2022 年跌 65% | 同期滞涨，9/16 守 $75K 不破 |
| **半导体（海力士）** | AI 超级周期 + 利率双驱动 | AI 周期强势对冲利率压力 | 外资 9 月抛售 4 万亿韩元，但 HBM 需求强劲 |
| **纳指/科技股** | 盈利增长 + 估值（利率压制） | 2022 年跌 33%，2023 年反弹 43% | 9/16 纳指 +0.67%，半导体 +0.63% |
| **原油** | 经济需求 + 供应 | 加息周期中 6/7 轮上涨，均 +25.6% | 油价高企推升通胀预期 |

**分化根因**：
- **黄金** = 实际利率的直接函数（机械关系）
- **BTC** = 2022-2023 紧缩期表现得像高 beta 科技股，而非"数字黄金"（纽约联储论文：BTC 对宏观新闻正交，除 CPI）
- **半导体** = AI 超级周期（HBM 需求）的强势可**对冲**利率压力。海力士 2025 财年营收 97 万亿韩元、利润率 49%，HBM 2026 几乎售罄

#### 0.5.3 主要矛盾/次要矛盾框架（国金证券研究范式）

国金证券关于美债收益率的研究框架：**一个主要矛盾 + 两个次要矛盾 + 一个灰犀牛**。

**当前（2026.9）主要矛盾**：科技公司大规模外部融资推高实际利率，挤出主权债
- 五大云厂商 2026 资本开支 $750-800B，2027 年 $1.0-1.1T
- 科技巨头从"现金创造者"变为"长期资本需求者"
- 2026 年发债约 $250B，2027 年约 $400B

**次要矛盾**：①美联储可信度下降（Warsh 弱化前瞻指引）②油价高企推升通胀
**灰犀牛**：日元脆弱性引发美债抛售

**对本系统的启示**：当 AI 资本开支（主要矛盾）与美联储加息（次要矛盾）同时作用于半导体时，**主要矛盾（AI 周期）决定方向，次要矛盾（利率）决定波动幅度**。这解释了为什么海力士在加息预期升温时仍可因 AI 需求而走强。

#### 0.5.4 议息交易周期的可操作规则（6 阶段）

基于完整周期规律，提炼分阶段操作规则：

```
阶段① 预期积累期（FOMC 前 4-6 周）：
  - 监控 FedWatch 概率变化趋势（而非绝对值）
  - 概率从 <20% 开始持续上升 → 黄金进入"预期定价"下跌通道
  - 操作：观察为主，等待趋势确认（概率突破 40% 后启动）

阶段② 预期升温期（FOMC 前 2-4 周）：
  - 触发条件：Jackson Hole / Fed 官员鹰派讲话 / 强就业数据
  - 概率 40%→70% → 黄金趋势性下跌，可做空黄金
  - BTC：看 30 天与利率相关性，>0.3 时跟随做空，<0.3 时不参与
  - 半导体：AI 景气度 > 0.7 时不做空（AI 周期对冲）

阶段③ 预期跳变期（FOMC 前 1-2 周）⚠️ 关键交易窗口：
  - 触发条件：CPI / PPI 超预期（actual > forecast）
  - 概率 1 周内跳升 >20%（如 59%→88%）→ 加仓做空黄金
  - 10Y 美债收益率破关键位（如 5%）→ 确认实际利率上行
  - 跨资产确认：DXY 走强 + 黄金 ETF 持仓流出

阶段④ 预期消化期（FOMC 前 3 天）：
  - 概率 >85% → 预期充分定价，下跌动能减弱
  - 黄金可能技术性反弹（空头获利了结）→ 减仓观望
  - 不新开空单，等事件落地

阶段⑤ 事件落地期（FOMC 当天）：
  - 实际值 = 预期（概率已充分定价）→ relief rally，平空转多（轻仓）
  - 实际值 > 预期（鹰派超预期，如点阵图上修）→ 顺势做空黄金
  - 实际值 < 预期（鸽派超预期）→ 做多黄金 + 半导体
  - 发布会窗口谨慎，等方向确立（1-2 小时后）

阶段⑥ 预期重定价期（FOMC 后 1-3 周）：
  - 监控下次会议概率变化 + FOMC 纪要（会议后 3 周）
  - 纪要鹰派（加息阵营扩大）→ 黄金继续承压
  - 纪要鸽派（内部分歧大）→ 黄金反弹
  - 检查通胀/就业数据是否支持继续加息
```

**风险控制**：
- 阶段②③做空黄金时，止损设在前高 + 1.5×ATR
- 阶段⑤转多后，止损设在事件当天最低点
- 任何阶段，若 FedWatch 概率趋势反转（如加息概率骤降），立即平仓

### 0.6 研究方法论应用：议息交易周期的 4 步验证

> 按照硬约束研究方法论，对"议息交易周期可交易"这一核心假设进行 4 步验证。

#### 第 1 步：观点假设

**假设 H1**：FOMC 议息交易周期中，黄金在**预期升温期（阶段②③）**趋势性下跌，在**事件落地后（阶段⑤⑥）**出现 relief rally。

**可证伪条件**：若历史回测中阶段②③黄金下跌胜率 < 55%，或阶段⑤⑥上涨胜率 < 55%，则假设不成立。

#### 第 2 步：理论分析 + 案例分析

**理论分析**：
- 机会成本理论：加息预期↑ → 实际利率↑ → 黄金（无息资产）机会成本↑ → 黄金↓
- 不确定性消除理论：事件落地 → 不确定性消除 → 空头回补 + 风险偏好恢复 → relief rally
- 实际利率量化关系：实际利率每升 1%，金价回调 ~15%（2000-2025）

**案例分析**（3 个历史案例）：

| 案例 | 事件 | 阶段②③表现 | 阶段⑤⑥表现 |
|:--|:--|:--|:--|
| **2015.12 首次加息** | 加息 25bp（已充分定价） | 黄金从 $1,190 跌至 $1,050（-12%） | 加息后 6 个月涨 30% |
| **2022.11 加息 75bp** | 连续激进加息 | 黄金从 $1,720 跌至 $1,615（-6%） | 加息后 1 个月涨 12%（英国 LDI 危机助推） |
| **2026.9 加息 25bp** | 93% 已定价 | 黄金从 $5,589（1月）跌至 $4,174（6月，-25%），8/25 起加速 | 待验证 |

#### 第 3 步：案例拆解 + 金融实践

**2026.9 案例拆解**（因果链）：
```
8月中：加息概率 36%（coin flip）→ 黄金高位震荡
  ↓
8/27-29：Jackson Hole 沃什鹰派 → 概率升至 48% → 黄金开始趋势性下跌
  ↓
9/10：PPI 超预期 → 概率跳升至 70%+ → 黄金加速下跌
  ↓
9/11：CPI 超预期 → 概率升至 88% → 10Y 美债破 5%，黄金急跌
  ↓
9/12-15：概率 88%→93%（充分定价）→ 黄金技术性反弹（空头获利了结）
  ↓
9/16：加息 25bp 落地 + 鹰派点阵图 → 黄金先涨后跌 1%
  ↓
9/17+：市场定价 10 月加息 53% → 黄金继续承压
```

**金融实践**（跨资产验证三角）：
```
黄金下跌确认条件（3 选 2 为强信号）：
  ① 实际利率上升（10Y TIPS）
  ② 美元指数走强（DXY）
  ③ 黄金 ETF 持仓流出（SPDR/iShares）

黄金反弹确认条件（relief rally）：
  ① FedWatch 概率 > 85%（预期充分定价）
  ② 实际利率止涨回落
  ③ 跨资产分歧消失（美元/实际利率不再创新高）
```

#### 第 4 步：回测验证

**MKS PAMP 回测**（2015-2018 年 9 次加息 FOMC）：
- 每次加息后 **60 天**，黄金平均上涨 **4%**
- 9 次中 7 次上涨（胜率 78%）

**世界黄金协会回测**（1997-2023 年 44 次加息）：
- 加息后 **1 个月**（21 个交易日），黄金**中位回报率为正**
- 超过 **50%** 的时间黄金带来正面惊喜

**结论**：假设 H1 获得回测支持——阶段②③下跌 + 阶段⑤⑥ relief rally 的模式在历史上成立。

### 0.7 跨资产验证框架：阻力最小方向识别

> 核心设计：用跨资产验证确定"阻力最小方向"，而非单一信号。

**黄金三角验证系统**（nexusfi 研究）：

| 组合 | 信号 | 含义 |
|:--|:--|:--|
| 黄金↑ + 实际利率↓ + 美元↓ | ✅ 强确认做多 | 三因素共振，阻力最小向上 |
| 黄金↓ + 实际利率↑ + 美元↑ | ✅ 强确认做空 | 三因素共振，阻力最小向下 |
| 黄金↑ + 实际利率↑ | ⚠️ 分歧信号 | 地缘/货币不确定性驱动，非趋势 |
| 黄金↓ + 实际利率↓ | ⚠️ 分歧信号 | 可能是技术性抛售 |

**跨资产评分卡**（用于计算确认度）：

```python
def cross_asset_score(asset: str) -> float:
    """
    返回 0.0 ~ 1.0 的跨资产确认度。
    对黄金：检查实际利率、DXY、铜/金比、黄金ETF持仓四个维度
    """
    checks = [
        real_rate_direction(),      # 实际利率方向（与黄金反向为确认）
        dxy_direction(),             # 美元方向（与黄金反向为确认）
        copper_gold_ratio(),         # 铜/金比（下降为黄金利好）
        gold_etf_flow(),             # ETF 持仓变化（流入为利好）
    ]
    confirmed = sum(1 for c in checks if c == "confirm")
    return confirmed / len(checks)
```

**收敛-发散预警**（FibAlgo 研究）：
- 极端跨资产相关性（>90 百分位）后 10 天内，**73%** 概率发生发散
- 平均发散幅度 **2.7 倍标准差**
- 当所有信号一致时，反而要警惕"coiled spring"即将反转

***

## 一 · 架构设计

### 1.1 整体数据流

```
┌──────────────────────────────────────────────────────────────────────┐
│                    美国宏观事件数据采集层（新增）                        │
│  18-数据获取中心/data_center/collectors/macro/                         │
│  ├─ fed_event_collector.py    FOMC 决议 + FedWatch 概率               │
│  └─ us_economic_calendar.py   CPI/非农/PPI/零售 actual/forecast       │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ SQLite (data_center.db)
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    数据管线接入层（修改）                               │
│  dreambuddy_evolution/adapters/data_pipeline.py                       │
│  新增字段注入: cpi_actual, cpi_expected, rate_hike_prob,              │
│               monetary_cycle, event_context, event_window              │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ kline_data
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    策略评估层（已有 + 增强）                            │
│  core/exogenous_strength_evaluator.py  _eval_macro()  ← 数据到位激活   │
│  engines/event_driven_strategy.py     利空出尽模式识别（新增）          │
└───────────────────────┬──────────────────────────────────────────────┘
                        │ signal + event_context
                        ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    自进化学习层（新增）                                 │
│  engines/event_case_library.py      事件案例库（pre/post snapshot）    │
│  reflection_engine.py               事件上下文纳入 reward 计算          │
└──────────────────────────────────────────────────────────────────────┘
```

### 1.2 设计原则

1. **复用消费端**：ESE `_eval_macro()` 已就绪，只需补供给端，不重写评估逻辑
2. **事件窗口三阶段**：`pre_event`（落地前 24-48h）、`event`（落地当日）、`post_event`（落地后 4-24h）
3. **FAIL-OPEN**：采集失败 → 字段缺失 → ESE macro 维度走 0.5 中性兜底，不阻塞交易
4. **开关隔离**：策略总开关 `ENABLE_EVENT_DRIVEN_STRATEGY`（默认 False），子开关按事件类型独立控制
5. **轻仓试错**：事件驱动策略初始仅在 probe 子池开仓，经自进化验证后升级到 standard

***

## 二 · 数据采集层设计

### 2.1 新增 Collector 1: `FedEventCollector`

**文件**：`18-数据获取中心/data_center/collectors/macro/fed_event_collector.py`
**继承**：`BaseCollector`，`source="fed_event"`, `category="macro"`

**采集内容**：

| 字段 | 来源 | 频率 | 说明 |
|:--|:--|:--|:--|
| `fomc_decision` | 美联储官网 / FRED `FEDFUNDS` | 每次 FOMC 后 | actual rate, decision_type(hike/cut/hold), vote_count |
| `fedwatch_prob` | CME FedWatch（网页抓取 / 第三方 API） | 每日 | 下次会议 hike/cut/hold 概率 |
| `monetary_cycle` | 由 FOMC 历史决议推导 | 每次决议后 | tightening/easing/neutral |
| `dot_plot_median` | 美联储 SEP 投影 | 每季度 | 年底利率中位数预期 |
| `press_conference_tone` | NLP 分析发布会文本 | 每次发布会后 | hawkish/dovish/neutral 评分 |

**FAIL-OPEN**：无 API Key 或抓取失败 → 返回空列表，不抛异常。

### 2.2 新增 Collector 2: `UsEconomicCalendarCollector`

**文件**：`18-数据获取中心/data_center/collectors/macro/us_economic_calendar.py`
**继承**：`BaseCollector`，`source="us_calendar"`, `category="macro"`

**采集内容**（重点事件）：

| 事件 | 字段 | 频率 | 影响等级 |
|:--|:--|:--|:--|
| CPI | actual, forecast, previous | 每月 | 高 |
| 核心 CPI | actual, forecast, previous | 每月 | 高 |
| 非农就业 (NFP) | actual, forecast, previous | 每月 | 高 |
| PPI | actual, forecast, previous | 每月 | 中 |
| 零售销售 | actual, forecast, previous | 每月 | 中 |
| FOMC 利率决议 | actual, forecast, previous | 8次/年 | 极高 |

**数据结构**（DataRecord.metrics）：
```python
{
    "event_type": "cpi",
    "event_date": "2026-09-10",
    "actual": 3.4,
    "forecast": 3.3,
    "previous": 3.4,
    "surprise": 0.1,           # actual - forecast
    "surprise_pct": 3.03,      # surprise / forecast * 100
    "impact_level": "high",
    "released": true
}
```

### 2.3 新增 Collector 3: `EventMarketReactionCollector`

**文件**：`18-数据获取中心/data_center/collectors/macro/event_market_reaction.py`
**继承**：`BaseCollector`，`source="event_reaction"`, `category="macro"`

**采集内容**：事件落地后定时抓取关键资产的价格反应，供自进化学习：

| 字段 | 说明 |
|:--|:--|
| `event_id` | 关联事件唯一 ID |
| `symbol` | BTC/ETH/SOL 等 |
| `price_pre_event` | 事件前 1h 价格 |
| `price_event` | 事件落地瞬间价格 |
| `price_post_1h` | 落地后 1h 价格 |
| `price_post_4h` | 落地后 4h 价格 |
| `price_post_24h` | 落地后 24h 价格 |
| `low_post_event` | 落地后最低价 |
| `wick_ratio` | 当日下影/实体比 |
| `volume_ratio` | 当日量/前5日均量 |

### 2.4 调度配置

在 `18-数据获取中心/data_center/scheduler.py` 的任务配置中新增：

```yaml
- category: macro
  source: fed_event
  cron: "0 */6 * * *"        # 每6小时检查 FOMC/FedWatch
  params: {}
- category: macro
  source: us_calendar
  cron: "0 8 * * *"          # 每日8点同步经济日历
  params: {days_ahead: 30}
- category: macro
  source: event_reaction
  cron: "0 * * * *"          # 每小时检查待采集的事件反应
  params: {}
```

***

## 三 · 数据管线接入层设计

### 3.1 修改 `data_pipeline.py`

在 `DataPipelineAdapter.assemble()` 中新增"宏观事件数据"组装段（约第 224 行 SubSystemBridge 之后）：

```python
# 5c. 宏观事件数据（ESE _eval_macro 消费端）
if self._data_center is not None:
    try:
        macro_event = self._data_center.query_latest_macro_event()
        if macro_event:
            # CPI surprise → ESE 短期
            if macro_event.get("event_type") == "cpi":
                kline_data["cpi_actual"] = macro_event.get("actual")
                kline_data["cpi_expected"] = macro_event.get("forecast")
            # FedWatch 概率 → ESE 中期
            fw = self._data_center.query_fedwatch_prob()
            if fw:
                kline_data["rate_hike_prob"] = fw.get("hike_prob", 0.5)
            # 货币周期 → ESE 长期
            cycle = self._data_center.query_monetary_cycle()
            if cycle:
                kline_data["monetary_cycle"] = cycle
    except Exception as e:
        logger.debug("[FO] macro_event fetch fail: %s", e)

# 5d. 事件窗口上下文（事件驱动策略消费）
try:
    event_ctx = self._event_window.get_current_context()
    if event_ctx:
        kline_data["event_context"] = event_ctx
        kline_data["event_window"] = event_ctx["phase"]  # pre/event/post
except Exception as e:
    logger.debug("[FO] event_window fail: %s", e)
```

### 3.2 新增 `EventWindowTracker`

**文件**：`dreambuddy_evolution/adapters/event_window_tracker.py`

职责：根据经济日历事件，判定当前处于哪个事件窗口阶段：

```python
class EventWindowTracker:
    def get_current_context(self) -> dict | None:
        """
        Returns:
            None if no near-term event
            {
                "event_type": "fomc" | "cpi" | "nfp" | ...,
                "event_time": ISO datetime,
                "phase": "pre_event" | "event" | "post_event",
                "hours_to_event": float,
                "hours_since_event": float,
                "priced_in_prob": float,       # FedWatch 或市场隐含概率
                "expected_surprise": float,    # forecast - previous
            }
        """
```

**窗口判定规则**：
- `pre_event`：事件前 48h ~ 事件前 1h
- `event`：事件前 1h ~ 事件后 4h
- `post_event`：事件后 4h ~ 事件后 24h

***

## 四 · 事件驱动策略设计

### 4.1 新增 `EventDrivenStrategy` 引擎

**文件**：`dreambuddy_evolution/engines/event_driven_strategy.py`

**核心方法**：

```python
class EventDrivenStrategy:
    def evaluate(self, kline_data: dict) -> dict:
        """
        评估事件驱动信号。

        Returns:
            {
                "signal": "LONG" | "SHORT" | "FLAT" | "WAIT",
                "confidence": float,          # [0, 1]
                "pattern": "priced_in_bottom" | "surprise_continuation" | None,
                "event_type": str,
                "rationale": str,
            }
        """
```

### 4.2 "利空出尽底部"模式识别逻辑

```python
def _detect_priced_in_bottom(self, data: dict) -> dict | None:
    """
    利空出尽底部识别（基于前序调研的 4 维打分）。
    """
    event_ctx = data.get("event_context")
    if not event_ctx or event_ctx["phase"] != "post_event":
        return None

    scores = {}

    # 维度1: 定价充分度（25%）
    priced_prob = event_ctx.get("priced_in_prob", 0.5)
    scores["pricing"] = 1.0 if priced_prob >= 0.85 else (0.5 if 0.70 <= priced_prob < 0.85 else 0.0)

    # 维度2: 落地抗跌（25%）
    low_post = data.get("low_post_event")
    pre_low = data.get("pre_event_low")
    if low_post is not None and pre_low is not None:
        scores["resilience"] = 1.0 if low_post >= pre_low else (
            0.5 if low_post >= pre_low * 0.98 else 0.0
        )
    else:
        scores["resilience"] = 0.5

    # 维度3: 下影线确认（25%，可选增强）
    wick_ratio = data.get("wick_ratio", 0)
    vol_ratio = data.get("volume_ratio", 1.0)
    if wick_ratio >= 2.0 and vol_ratio >= 1.5:
        scores["wick"] = 1.0
    elif wick_ratio >= 1.5:
        scores["wick"] = 0.5
    else:
        scores["wick"] = 0.0

    # 维度4: 跨资产验证（25%，可选增强）
    cross_asset = self._check_cross_asset(data)
    scores["cross_asset"] = cross_asset  # 0.0/0.5/1.0

    total = sum(scores.values()) / len(scores)
    if total >= 0.75:
        return {
            "pattern": "priced_in_bottom",
            "signal": "LONG",
            "confidence": total,
            "rationale": f"利空出尽底部: pricing={scores['pricing']}, "
                         f"resilience={scores['resilience']}, wick={scores['wick']}, "
                         f"cross={scores['cross_asset']}",
        }
    return None
```

### 4.3 事件驱动信号如何接入开仓决策

在 `KlineEventHandler` 的开仓评分链路中，事件驱动信号作为**修饰子（modifier）**叠加，而非直接覆盖技术面信号：

- `priced_in_bottom` 信号 → 对 LONG 方向 +0.10 信心加成，对 SHORT 方向 -0.15 惩罚
- `surprise_continuation`（实际值大幅超预期）→ 顺势方向加成
- 信号 `confidence < 0.60` 时不生效（FAIL-OPEN 到中性）

### 4.4 三阶段动态权衡引擎（核心，基于深度调研）

**文件**：`dreambuddy_evolution/engines/event_phase_manager.py`

对应 0.4.4 节的三阶段机制，实现事件后的动态仓位与方向管理：

```python
class EventPhaseManager:
    """
    事件后三阶段权衡引擎：
    - Phase A (Relief, 0-5天): 不确定性消除+空头回补主导
    - Phase B (验证, 5-15天): 检查基本面是否真改善
    - Phase C (趋势, 15天+): 债务周期位置主导
    """

    PHASE_A_DAYS = 5
    PHASE_B_DAYS = 15

    def get_phase(self, event_time: datetime) -> str:
        days_since = (datetime.now() - event_time).days
        if days_since <= self.PHASE_A_DAYS:
            return "relief"
        elif days_since <= self.PHASE_B_DAYS:
            return "validation"
        else:
            return "trend"

    def get_position_modifier(self, phase: str, fundamental_check: dict) -> dict:
        """
        Returns:
            {
                "direction_bias": "long" | "neutral" | "short",
                "position_scale": float,   # 0.0 ~ 1.0
                "stop_loss_tighten": bool,  # 是否收紧止损
            }
        """
        if phase == "relief":
            # Phase A: 轻仓试多，止损收紧（下影线最低点）
            return {"direction_bias": "long", "position_scale": 0.5, "stop_loss_tighten": True}

        elif phase == "validation":
            # Phase B: 检查基本面改善项数
            improved_count = sum(1 for v in fundamental_check.values() if v == "improved")
            if improved_count >= 2:
                return {"direction_bias": "long", "position_scale": 1.0, "stop_loss_tighten": False}
            elif improved_count <= 1:
                return {"direction_bias": "neutral", "position_scale": 0.3, "stop_loss_tighten": True}
            else:  # worsened
                return {"direction_bias": "short", "position_scale": 0.5, "stop_loss_tighten": False}

        else:  # trend
            # Phase C: 由债务周期位置决定（Dalio 框架）
            cycle = self._get_debt_cycle_phase()
            if cycle == "expansion":
                return {"direction_bias": "long", "position_scale": 1.0, "stop_loss_tighten": False}
            elif cycle == "contraction":
                return {"direction_bias": "short", "position_scale": 0.7, "stop_loss_tighten": False}
            else:
                return {"direction_bias": "neutral", "position_scale": 0.3, "stop_loss_tighten": True}

    def _get_debt_cycle_phase(self) -> str:
        """
        基于 Dalio 短期债务周期判定：
        - 信贷增速 > GDP 增速 → expansion
        - 信贷增速 < GDP 增速 + 利率上行 → contraction
        - 其他 → neutral
        数据来源：FredCollector 的 WALCL（资产负债表）+ 商业银行信贷增速
        """
        pass  # 实现见 T8
```

**基本面检查清单（Phase B 用）**：

| 检查项 | 数据来源 | "改善"判定 |
|:--|:--|:--|
| 通胀回落 | CPI/PPI actual vs previous | actual < previous 且 < forecast |
| 信贷扩张 | 商业银行信贷增速 | 环比转正或加速 |
| 盈利上修 | 分析师 EPS 预期 | 预期上调 > 下调 |
| 空头回补完成 | short interest ratio | days_to_cover < 2 或空仓环比下降 |

**深层利空监控（贯穿三阶段）**：

```python
def check_deep_bearish_conditions(self) -> dict:
    """
    监控 0.4.3 节的 5 个深层利空条件。
    满足 ≥2项高权重 或 ≥3项任意 → relief rally 结束信号
    """
    conditions = {
        "higher_for_longer": self._check_fed_hawkish(),       # 高权重
        "inflation_sticky": self._check_inflation_sticky(),    # 高权重
        "credit_contraction": self._check_credit_tightening(), # 中权重
        "earnings_miss": self._check_earnings_divergence(),    # 中权重
        "short_covering_done": self._check_short_interest(),   # 中权重
    }
    high_weight_triggered = sum([conditions["higher_for_longer"], conditions["inflation_sticky"]])
    total_triggered = sum(conditions.values())
    is_deep_bearish = (high_weight_triggered >= 2) or (total_triggered >= 3)
    return {"conditions": conditions, "deep_bearish": is_deep_bearish}
```

### 4.5 主要矛盾驱动的参数调整机制（核心创新）

> 设计目标：当识别到 FOMC 议息这一"主要矛盾"时，系统应自动调整各策略层的参数权重，使主要矛盾主导交易决策，次要矛盾退居其次。

#### 4.5.1 主要矛盾识别器

```python
class PrimaryContradictionDetector:
    """
    识别当前市场的主要矛盾，输出矛盾类型 + 强度 + 影响资产范围。
    当前支持的主要矛盾类型：
    - "fomc_rate_decision": FOMC 议息会议（Tier 1 事件）
    - "inflation_shock": 通胀超预期（Tier 2 事件，actual >> forecast）
    - "credit_event": 信用事件（利差走阔 / 违约）
    - "ai_capex_cycle": AI 资本开支周期（中期，非事件型）
    """

    def detect(self) -> dict:
        """
        Returns:
            {
                "primary": "fomc_rate_decision",
                "intensity": 0.85,           # 0.0 ~ 1.0，由 FedWatch 概率变化幅度决定
                "cycle_phase": "expectation_build",  # 6 阶段之一
                "probability": 0.88,         # 当前 FedWatch 加息概率
                "probability_trend": "rising",  # rising | falling | stable
                "affected_assets": ["gold", "btc", "semiconductors", "dxy"],
                "secondary": ["inflation", "ai_capex"],
            }
        """
        # 1. 检查是否在 FOMC 主要矛盾周期内（前 6 周 ~ 后 3 周）
        if self._in_fomc_cycle():
            fomc_prob = self._get_fedwatch_prob()
            prob_trend = self._get_probability_trend()  # 7 天变化率
            cycle_phase = self._get_fomc_cycle_phase()
            # 强度由概率绝对值 + 变化幅度共同决定
            intensity = min(fomc_prob * 0.6 + abs(prob_trend) * 0.4, 0.95)
            return {
                "primary": "fomc_rate_decision",
                "intensity": intensity,
                "cycle_phase": cycle_phase,
                "probability": fomc_prob,
                "probability_trend": prob_trend,
                "affected_assets": ["gold", "btc", "dxy", "us10y"],
                "secondary": ["inflation", "ai_capex"],
            }
        # 2. 其他主要矛盾类型...
        pass

    def _in_fomc_cycle(self) -> bool:
        """FOMC 前 6 周到后 3 周为主要矛盾周期（覆盖完整 6 阶段）"""
        next_fomc = self.event_calendar.get_next_fomc()
        last_fomc = self.event_calendar.get_last_fomc()
        days_to_next = (next_fomc - datetime.now()).days
        days_since_last = (datetime.now() - last_fomc).days
        # 下次会议前 42 天内，或上次会议后 21 天内
        return days_to_next <= 42 or days_since_last <= 21

    def _get_fomc_cycle_phase(self) -> str:
        """
        判定 FOMC 周期 6 阶段：
        - expectation_build: 前 4-6 周，概率 <40%
        - expectation_rise: 前 2-4 周，概率 40-70% 且上升
        - expectation_jump: 前 1-2 周，概率 1 周内跳升 >20% 或 >70%
        - expectation_digest: 前 3 天，概率 >85%
        - event: FOMC 当天
        - repricing: 后 1-3 周
        """
        next_fomc = self.event_calendar.get_next_fomc()
        days_to = (next_fomc - datetime.now()).days
        prob = self._get_fedwatch_prob()
        prob_change_7d = self._get_probability_change(7)

        if days_to < 0:
            return "repricing"  # 会议已过
        elif days_to <= 3 and prob > 0.85:
            return "expectation_digest"
        elif days_to <= 1:
            return "event"
        elif days_to <= 14 and (prob_change_7d > 0.20 or prob > 0.70):
            return "expectation_jump"
        elif days_to <= 28 and 0.40 <= prob <= 0.70:
            return "expectation_rise"
        else:
            return "expectation_build"
```

#### 4.5.2 参数调整矩阵（6 阶段）

当识别到 FOMC 主要矛盾时，各策略层参数按周期阶段自动调整：

| 参数 | 常规 | ①积累 | ②升温 | ③跳变 | ④消化 | ⑤事件 | ⑥重定价 |
|:--|:--|:--|:--|:--|:--|:--|:--|
| `conf_threshold` | 0.60 | 0.65 | 0.55 | 0.50 | 0.60 | 0.70 | 0.58 |
| `position_scale` | 1.0 | 0.5 | 1.0 | **1.5** | 0.8 | 0.5 | 1.0 |
| `sl_distance_mult` | 1.5 | 1.5 | 2.0 | 2.0 | 1.5 | 1.0 | 1.5 |
| `macro_weight` | 0.15 | 0.20 | 0.25 | **0.35** | 0.30 | 0.40 | 0.25 |
| `tech_weight` | 0.60 | 0.55 | 0.50 | **0.40** | 0.45 | 0.35 | 0.50 |
| `max_hold_hours` | 72 | 72 | 48 | 36 | 24 | 12 | 72 |

**核心逻辑**：
- 阶段③（预期跳变）是**最强信号窗口**：仓位 ×1.5，宏观权重最高，技术权重最低
- 阶段⑤（事件当天）：仓位降至 0.5 避险，门槛提高到 0.70
- 阶段①（积累期）：轻仓观察，门槛略高

```python
class ParameterAdjuster:
    """根据主要矛盾类型 + 周期阶段动态调整策略参数"""

    FOMC_PARAM_OVERRIDES = {
        "expectation_build": {     # ① 积累期
            "conf_threshold": 0.65, "position_scale": 0.5,
            "sl_distance_multiplier": 1.5, "macro_weight": 0.20,
            "tech_weight": 0.55, "max_hold_hours": 72,
        },
        "expectation_rise": {      # ② 升温期
            "conf_threshold": 0.55, "position_scale": 1.0,
            "sl_distance_multiplier": 2.0, "macro_weight": 0.25,
            "tech_weight": 0.50, "max_hold_hours": 48,
        },
        "expectation_jump": {      # ③ 跳变期（最强窗口）
            "conf_threshold": 0.50, "position_scale": 1.5,
            "sl_distance_multiplier": 2.0, "macro_weight": 0.35,
            "tech_weight": 0.40, "max_hold_hours": 36,
        },
        "expectation_digest": {    # ④ 消化期
            "conf_threshold": 0.60, "position_scale": 0.8,
            "sl_distance_multiplier": 1.5, "macro_weight": 0.30,
            "tech_weight": 0.45, "max_hold_hours": 24,
        },
        "event": {                 # ⑤ 事件当天
            "conf_threshold": 0.70, "position_scale": 0.5,
            "sl_distance_multiplier": 1.0, "macro_weight": 0.40,
            "tech_weight": 0.35, "max_hold_hours": 12,
        },
        "repricing": {             # ⑥ 重定价期
            "conf_threshold": 0.58, "position_scale": 1.0,
            "sl_distance_multiplier": 1.5, "macro_weight": 0.25,
            "tech_weight": 0.50, "max_hold_hours": 72,
        },
    }

    def get_adjusted_params(self, primary: str, phase: str) -> dict:
        """返回合并后的参数字典（常规值 + 主要矛盾覆盖）"""
        base = self._get_base_params()
        if primary == "fomc_rate_decision":
            override = self.FOMC_PARAM_OVERRIDES.get(phase, {})
            base.update(override)
        return base
```

#### 4.5.3 资产分化的方向偏置

基于 0.5.2 节的资产分化规律，FOMC 窗口内不同资产的方向偏置：

```python
def get_asset_bias(self, asset: str, fomc_phase: str, rate_expectation: str) -> str:
    """
    rate_expectation: "hike" | "cut" | "hold"
    返回: "long_bias" | "short_bias" | "neutral"
    """
    # 黄金：实际利率直接驱动
    if asset == "gold":
        if rate_expectation == "hike":
            return "short_bias" if fomc_phase == "pre_event" else "neutral"
        elif rate_expectation == "cut":
            return "long_bias"

    # BTC：看 30 天与利率相关性
    elif asset == "btc":
        corr = self._get_btc_rate_correlation(30)
        if abs(corr) < 0.3:
            return "neutral"  # 脱钩期，不参与宏观方向
        elif rate_expectation == "hike" and corr < 0:
            return "short_bias" if fomc_phase == "pre_event" else "neutral"

    # 半导体：AI 周期对冲利率
    elif asset in ("semiconductors", "sk_hynix"):
        ai_score = self._get_ai_cycle_score()
        if ai_score > 0.7:
            return "neutral"  # AI 强势对冲，不做空
        elif rate_expectation == "hike":
            return "short_bias"

    return "neutral"
```

### 4.6 置信度驱动的仓位与策略映射

> 设计目标：基于综合置信度自动切换"震荡市→趋势市"模式，不确定时少做，确定性高时加仓做趋势。

#### 4.6.1 综合置信度计算

综合置信度由 5 个维度加权得出：

```python
class ConvictionScorer:
    """
    综合置信度 = 主要矛盾强度 × 0.30 + 跨资产确认度 × 0.25
              + 技术面一致性 × 0.20 + 资金面确认 × 0.15 + 数据质量 × 0.10
    """

    WEIGHTS = {
        "primary_contradiction": 0.30,   # 主要矛盾强度（FOMC 周期阶段 + FedWatch 概率）
        "cross_asset": 0.25,              # 跨资产确认度（0.7 节三角验证）
        "technical": 0.20,                # 技术面一致性（趋势/动量/位置）
        "capital_flow": 0.15,             # 资金面（ETF 持仓/期货持仓/成交量）
        "data_quality": 0.10,             # 数据质量（sufficient / degraded）
    }

    def score(self) -> dict:
        return {
            "conviction": sum(self._each() * w for w in self.WEIGHTS.values()),
            "breakdown": {...},  # 各维度分项
        }
```

#### 4.6.2 置信度档位与策略映射

类似震荡市 vs 趋势市的动态切换：

| 置信度 | 档位 | 市场状态 | 仓位系数 | 策略模式 | 开仓频率 |
|:--|:--|:--|:--|:--|:--|
| 0.00-0.30 | 极低 | 高不确定性 | **0.0** | 观望 | 0 |
| 0.30-0.50 | 低 | 震荡市 | **0.3** | 轻仓试错 + 宽止损 | 低 |
| 0.50-0.70 | 中 | 趋势初现 | **0.7** | 标准仓位 + 趋势跟踪 | 中 |
| 0.70-0.85 | 高 | 趋势确立 | **1.2** | 加仓 + 持有 + 移动止损 | 高 |
| 0.85-1.00 | 极高 | 强趋势 | **1.5** | 重仓 + 趋势加仓 | 极高 |

**核心原则**：
- 置信度 < 0.30 → **不开仓**（宁可少做）
- 置信度 0.30-0.50 → **震荡市模式**：轻仓、宽止损、快进快出
- 置信度 > 0.70 → **趋势市模式**：加仓、持有、移动止损

#### 4.6.3 置信度与 FOMC 周期阶段的联动

不同 FOMC 阶段的置信度基线不同：

```python
FOMC_PHASE_CONVICTION_BASELINE = {
    "expectation_build": 0.30,   # 积累期：低基线，等趋势确认
    "expectation_rise": 0.55,    # 升温期：中基线，可开仓
    "expectation_jump": 0.75,    # 跳变期：高基线，加仓做趋势
    "expectation_digest": 0.60,  # 消化期：中基线，减仓
    "event": 0.40,               # 事件当天：低基线（不确定性最高）
    "repricing": 0.50,           # 重定价期：中基线
}
```

最终置信度 = `min(baseline + cross_asset_adjustment + technical_adjustment, 1.0)`

#### 4.6.4 震荡市 vs 趋势市策略参数对照

| 参数 | 震荡市（置信度 0.30-0.50） | 趋势市（置信度 > 0.70） |
|:--|:--|:--|
| 仓位系数 | 0.3 | 1.2-1.5 |
| 止损间距 | ATR × 2.5（宽） | ATR × 1.5（紧） |
| 止盈间距 | ATR × 1.5（快出） | ATR × 3.0（持有） |
| 移动止损 | 不启用 | 启用（+0.5% 后上移） |
| 加仓 | 不允许 | 允许（信号确认后） |
| 最大持仓时长 | 12 小时 | 72 小时 |

### 4.7 主导策略控制（Event Dominance Controller）

> **方案评估**：用户提出"自进化议息事件交易策略高置信度时起主导作用，为其他子交易系统设置开关"。
> **结论**：✅ 方案合理。符合 Cascade Strategies（级联策略）和 Override System（覆盖系统）两种成熟架构模式。

#### 4.7.1 方案合理性论证

| 维度 | 评估 | 依据 |
|:--|:--|:--|
| **哲学一致性** | ✅ | 符合"抓主要矛盾"核心交易哲学 |
| **风险控制** | ✅ | 避免子系统对赌，统一方向降低组合风险 |
| **机构实践** | ✅ | Cascade Strategies：主策略优先挤出后备策略；Override System：特定条件覆盖所有信号 |
| **信号质量** | ✅ | 高置信度时宏观面压制噪音，减少假信号 |
| **多样性损失** | ⚠️ | 需设分档过滤，避免过度压制有效技术信号 |

#### 4.7.2 三档过滤机制

不是简单的"开/关"，而是按置信度分档：

| 置信度 | 过滤模式 | 对其他子系统的影响 | 设计逻辑 |
|:--|:--|:--|:--|
| **> 0.85** | 🔴 **硬过滤**（Hard Filter） | 只允许与主要矛盾**同向**的开仓；反向信号直接拦截 | 极高置信度=强趋势，反向交易=逆势 |
| **0.70-0.85** | 🟡 **软过滤**（Soft Filter） | 反向信号仓位降权至 0.3；同向信号加权 1.2 | 高置信度但保留技术面多样性 |
| **< 0.70** | 🟢 **不过滤**（Pass-through） | 各子系统完全自主交易 | 置信度不足，不干预 |

```python
class EventDominanceController:
    """
    议息事件主导策略控制器。
    当自进化议息事件策略置信度足够高时，对其他子交易系统（BCRM2.0/BDSM/庙算）
    的开仓信号进行方向过滤。
    """

    # 过滤阈值
    HARD_FILTER_THRESHOLD = 0.85
    SOFT_FILTER_THRESHOLD = 0.70

    def __init__(self):
        self.manual_override = False  # 用户手动覆盖开关
        self.fail_open = True         # FAIL-OPEN：议息策略异常时自动解除过滤

    def filter_signal(self, signal: dict, event_ctx: dict) -> dict:
        """
        对其他子系统的开仓信号进行过滤。
        
        Args:
            signal: 子系统开仓信号 {symbol, direction, confidence, ...}
            event_ctx: 议息事件上下文 {dominant_direction, conviction, phase}
        
        Returns:
            {
                "allowed": bool,              # 是否允许开仓
                "position_multiplier": float, # 仓位调整系数
                "reason": str,                # 过滤原因
                "filter_mode": str,           # hard / soft / pass_through
            }
        """
        # 1. 用户手动覆盖 → 不过滤
        if self.manual_override:
            return {"allowed": True, "position_multiplier": 1.0, "reason": "manual_override", "filter_mode": "pass_through"}

        # 2. FAIL-OPEN：议息策略异常或数据不足 → 不过滤
        if not event_ctx.get("conviction") or event_ctx.get("data_quality") != "sufficient":
            return {"allowed": True, "position_multiplier": 1.0, "reason": "fail_open", "filter_mode": "pass_through"}

        conviction = event_ctx["conviction"]
        dominant_dir = event_ctx["dominant_direction"]  # "long" / "short" / "neutral"
        signal_dir = signal["direction"]

        # 3. 置信度不足 → 不过滤
        if conviction < self.SOFT_FILTER_THRESHOLD:
            return {"allowed": True, "position_multiplier": 1.0, "reason": "low_conviction", "filter_mode": "pass_through"}

        # 4. 主导方向为中性 → 不过滤
        if dominant_dir == "neutral":
            return {"allowed": True, "position_multiplier": 1.0, "reason": "neutral_dominant", "filter_mode": "pass_through"}

        # 5. 同向信号 → 放行 + 加权
        if signal_dir == dominant_dir:
            if conviction >= self.HARD_FILTER_THRESHOLD:
                return {"allowed": True, "position_multiplier": 1.2, "reason": "same_dir_hard", "filter_mode": "hard"}
            else:
                return {"allowed": True, "position_multiplier": 1.1, "reason": "same_dir_soft", "filter_mode": "soft"}

        # 6. 反向信号 → 按置信度拦截或降权
        if conviction >= self.HARD_FILTER_THRESHOLD:
            return {"allowed": False, "position_multiplier": 0.0, "reason": "opposite_dir_hard_block", "filter_mode": "hard"}
        else:
            return {"allowed": True, "position_multiplier": 0.3, "reason": "opposite_dir_soft_reduce", "filter_mode": "soft"}
```

#### 4.7.3 对子系统的接入方式

各子交易系统（BCRM2.0 / BDSM / 庙算五计）的开仓信号统一经过 `EventDominanceController.filter_signal()`：

```
子系统信号 → EventDominanceController → 风控层 → 执行
                  ↑
         议息策略上下文（conviction + dominant_direction）
```

**接入原则**：
- 不改子系统内部逻辑，只在开仓信号出口处加过滤层
- 过滤层是"装饰器"模式，可随时移除
- 已有持仓不受过滤影响（只拦截新开仓）
- 平仓信号不受过滤（允许止损止盈正常触发）

#### 4.7.4 安全机制

| 机制 | 触发条件 | 行为 |
|:--|:--|:--|
| **FAIL-OPEN** | 议息策略异常 / 数据质量 != sufficient | 自动解除所有过滤，子系统自主交易 |
| **手动覆盖** | 用户设置 `manual_override = True` | 立即解除过滤，恢复子系统自主权 |
| **连续亏损降档** | 过滤模式下连续 3 笔亏损 | 自动从 hard 降为 soft，再连续亏损则 pass_through |
| **置信度漂移监控** | conviction 1 小时内下降 >0.15 | 立即降档（hard→soft→pass_through） |
| **日志审计** | 每次过滤决策 | 记录 signal + event_ctx + filter_result 供回测分析 |

#### 4.7.5 与置信度仓位映射的联动

`EventDominanceController` 和 `ConvictionScorer` 协同工作：

```
高置信度 (>0.85)：
  → ConvictionScorer：仓位 1.2-1.5（趋势市模式）
  → EventDominanceController：硬过滤，只允许同向交易
  → 效果：重仓 + 方向统一 = 集中火力在主要矛盾方向

中置信度 (0.70-0.85)：
  → ConvictionScorer：仓位 0.7-1.2
  → EventDominanceController：软过滤，反向降权
  → 效果：适度集中，保留技术面多样性

低置信度 (<0.70)：
  → ConvictionScorer：仓位 0-0.3（观望/轻仓）
  → EventDominanceController：不过滤
  → 效果：子系统自主，分散风险
```

### 4.8 策略基因实现（event_arbitrage）

在 `gene_data/strategy_combinations/library.json` 中新增 `event_arbitrage` 策略基因组合，条件类型使用已有的 `macroeconomics`：

```json
{
  "combo_id": "CB-EVENT-PRICED-IN",
  "strategy_type": "event_arbitrage",
  "conditions": [
    {"type": "macroeconomics", "param": "event_window", "op": "eq", "value": "post_event"},
    {"type": "macroeconomics", "param": "priced_in_score", "op": "gte", "value": 0.75}
  ],
  "action": {"type": "entry", "direction": "long", "tier": "probe"},
  "weight": 1.0
}
```

***

## 五 · 自进化学习机制设计

### 5.1 事件案例库 `EventCaseLibrary`

**文件**：`dreambuddy_evolution/engines/event_case_library.py`

存储每次重大事件的完整快照，供 ShadowRL 训练和 CBR 检索：

```python
@dataclass
class EventCase:
    event_id: str
    event_type: str           # fomc / cpi / nfp
    event_date: str
    priced_in_prob: float
    actual_vs_forecast: float
    pre_event_snapshot: dict  # 开仓前市场状态
    post_event_reaction: dict # 价格反应、下影线、量比
    trade_decision: str       # LONG/SHORT/FLAT
    trade_pnl: float          # 事后验证盈亏
    pattern_label: str        # priced_in_bottom / surprise / neutral
```

**存储**：`gene_data/event_cases/event_cases.json`（追加写入）

### 5.2 反思引擎增强

修改 `reflection_engine.py` 的 `create_snapshot`，在 `pre_trade_snapshot` 中加入 `event_context` 字段：

```python
snapshot["event_context"] = {
    "event_type": ...,
    "event_window": ...,
    "priced_in_prob": ...,
    "pattern_signal": ...,
}
```

在 `apply_reward` 中，若交易发生在事件窗口内，reward 权重 ×1.2（事件驱动交易的学习权重更高，因为样本稀少但信息量大）。

### 5.3 事件模式统计与进化

`EventCaseLibrary` 提供统计接口，定期计算各模式的历史胜率：

```python
def get_pattern_winrate(self, pattern: str, event_type: str = None) -> dict:
    """
    返回:
        {
            "pattern": "priced_in_bottom",
            "sample_count": 12,
            "win_rate": 0.75,
            "avg_pnl_pct": 2.3,
            "avg_holding_hours": 18.5,
        }
    """
```

当某模式 `win_rate >= 0.65` 且 `sample_count >= 10` 时，自动提升该策略基因的 weight；若 `win_rate < 0.40`，自动降级。

***

## 六 · 开关与降级设计

### 6.1 开关层级

| 开关 | 环境变量 | 默认 | 说明 |
|:--|:--|:--|:--|
| 总开关 | `ENABLE_CONTRADICTION_DRIVEN_LAYER` | `False` | 关闭时所有事件驱动主要矛盾参数调整逻辑不执行 |
| 主要矛盾识别 | `ENABLE_PRIMARY_CONTRADICTION_DETECTOR` | `False` | T10d 主要矛盾识别器 |
| 参数调整 | `ENABLE_PARAMETER_ADJUSTER` | `False` | T10e 6阶段×7参数调整矩阵 |
| 资产偏置 | `ENABLE_ASSET_BIAS_RESOLVER` | `False` | T10f gold/btc/semiconductors 方向偏置 |
| 置信度仓位映射 | `ENABLE_CONVICTION_POSITION_MAPPER` | `False` | 5档仓位映射 |
| 债务周期 | `ENABLE_DEBT_CYCLE_PHASE` | `False` | T13b Dalio 短期债务周期 |
| AI周期 | `ENABLE_AI_CYCLE_SCORER` | `False` | T13c AI 资本开支周期评分 |
| 权重自动调整 | `ENABLE_AUTO_WEIGHT_ADJUSTMENT` | `False` | T13 自进化权重升降级闭环 |
| 数据采集 | `ENABLE_US_MACRO_COLLECTORS` | `True` | 关闭时不采集美国宏观事件 |
| FOMC 策略 | `ENABLE_FOMC_EVENT_STRATEGY` | `True` | FOMC 利率决议策略 |
| CPI 策略 | `ENABLE_CPI_EVENT_STRATEGY` | `True` | CPI 数据策略 |
| 非农策略 | `ENABLE_NFP_EVENT_STRATEGY` | `False` | 非农数据策略（初期关闭） |

### 6.2 FAIL-OPEN 降级链

```
采集失败 → 字段缺失
    → ESE._eval_macro() 取 0.5 中性（已有逻辑）
    → EventDrivenStrategy.evaluate() 返回 WAIT
    → 修饰子不生效
    → 交易链路等价于"事件驱动策略不存在"
```

***

## 七 · 实施任务分解

### Phase 1: 数据采集（基础）
- [x] T1: 实现 `FedEventCollector`（FOMC 决议 + FedWatch 概率）
- [x] T2: 实现 `UsEconomicCalendarCollector`（CPI/非农/PPI actual/forecast）
- [x] T3: 注册到 `registry.py`，配置调度任务
- [x] T4: 实现 `EventMarketReactionCollector`（事件前后价格快照）

### Phase 2: 数据管线接入
- [x] T5: 在 `data_pipeline.py` 注入 `cpi_actual`/`cpi_expected`/`rate_hike_prob`/`monetary_cycle`
- [x] T6: 实现 `EventWindowTracker`，注入 `event_context`/`event_window`
- [x] T7: 验证 ESE `_eval_macro()` 输出非 0.5（脱离退化态）

### Phase 3: 事件驱动策略
- [x] T8: 实现 `EventDrivenStrategy` 引擎 + `priced_in_bottom` 模式
- [x] T9: 将信号作为修饰子接入 `KlineEventHandler` 开仓评分
- [x] T10: 新增 `event_arbitrage` 策略基因组合到 library.json（CB-EVENT-PRICED-IN）
- [x] T10b: 实现三阶段动态权衡（relief/verification/trend，集成于 EventDrivenStrategy）
- [x] T10c: 实现深层利空 5 条件监控（higher_for_longer / inflation_sticky / credit_contraction / earnings_miss / short_covering_done）
- [x] T10d: 实现 `PrimaryContradictionDetector` 主要矛盾识别器（FOMC/inflation/credit/ai_capex）
- [x] T10e: 实现 `ParameterAdjuster` 主要矛盾参数调整矩阵（7 个参数 × 6 阶段）
- [x] T10f: 实现资产分化方向偏置（gold=实际利率 / btc=相关性 / 半导体=AI周期对冲）
- [x] T10g: 实现 `ConvictionScorer` 综合置信度评分（5 维度加权）
- [x] T10h: 实现置信度→仓位/策略映射（5档：0.0/0.3/0.7/1.2/1.5）
- [x] T10i: 实现跨资产验证框架（黄金三角：实际利率/DXY/ETF 持仓）
- [x] T10j: 实现 `EventDominanceController` 主导策略控制器（3 档过滤 + FAIL-OPEN + 手动覆盖）
- [x] T10k: 接入 BCRM2.0/BDSM/庙算 子系统开仓信号出口（装饰器模式，不改内部逻辑）

### Phase 4: 自进化学习
- [x] T11: 实现 `EventCaseLibrary` 事件案例库（含 phase 标签 + relief vs 反转分层）
- [x] T12: 增强 `reflection_engine.py` 纳入事件上下文
- [x] T13: 实现模式胜率统计与权重自动调整（按 phase 分层统计 + persist_library 持久化）
- [x] T13b: 实现债务周期位置判定（Dalio 短期债务周期：信贷增速 vs GDP 增速）
- [x] T13c: 实现 AI 周期评分（HBM 需求/资本开支/半导体景气度）用于资产分化判断

### Phase 5: 验证与上线
- [x] T14: 单元测试（采集 FAIL-OPEN、策略信号、案例库读写、三阶段切换、参数调整）
- [ ] T15: 历史回测（用 2015/2022/2023/2026 四次加息事件验证，重点验证 relief rally 持续时间 + 资产分化）
- [x] T16: 开关默认关闭，小范围灰度验证后开启

***

## 八 · 验收标准

1. **数据采集**：FOMC 决议后 1h 内，`data_center.db` 中可查到 actual/forecast/surprise 数据；FedWatch 概率每日更新
2. **ESE 激活**：有 CPI 数据时，`ESE.evaluate()["macro"]["short"]` 不等于 0.5
3. **策略信号**：构造"93% 定价 + 不破前低 + 下影线≥2倍"的测试数据，`EventDrivenStrategy.evaluate()` 返回 `signal=LONG, confidence>=0.75`
4. **FAIL-OPEN**：采集器无 API Key 时不抛异常，策略返回 WAIT，交易链路不受影响
5. **自进化闭环**：平仓后 `event_cases.json` 中新增一条含 `event_context` + `trade_pnl` 的案例
6. **开关隔离**：`ENABLE_CONTRADICTION_DRIVEN_LAYER=False` 时，开仓决策与未实现该策略时字节等价

***

## 九 · 风险与注意事项

| 风险 | 缓解措施 |
|:--|:--|
| FedWatch 网页抓取不稳定 | 优先用 FRED API + 第三方数据源，多源冗余 |
| 事件样本稀少（每年 FOMC 仅 8 次） | 初期用 probe 轻仓试错，积累 10+ 样本后再升级 |
| 事件驱动信号与技术面冲突 | 事件信号仅作修饰子（±0.10~0.15），不覆盖技术面主信号 |
| 过拟合历史模式 | 模式胜率需 `sample_count >= 10` 才生效，且定期重评估 |
| 数据延迟 | 事件窗口期提高采集频率（每 15min 一次），超时降级 |

***

## 附录 A：深度调研 — 经典书籍理论与 GitHub 开源库

> 本附录为 v2.0 新增的深度调研成果，回答两个核心问题：①传统机构如何处理"不确定性消除 vs 深层利空"的权衡？②GitHub 上有哪些可直接复用的宏观事件驱动算法？

### A.1 经典书籍理论

#### A.1.1 Dalio《Big Debt Crises》— 短期债务周期框架

**核心机制**：短期债务周期约 6 年（±3 年），长期约 75 年（±25 年）。

**紧缩阶段的传导链**（解释为什么 relief rally 不改变大方向）：
```
加息 → 借贷成本↑ → 债务偿还压力↑ → 支出↓ → 信用收缩 → 资产价格↓
```

**七阶段 archetype**：
1. 健康增长 → 2. 泡沫（债务增速 > 收入增速）→ 3. 顶部（央行紧缩 + 收益率曲线平坦/倒挂）→ 4. 萧条（利率近零，违约连锁）→ 5. 去杠杆（紧缩/违约/印钞/财富转移四工具平衡）→ 6. 正常化 → 7. 周期重复

**关键启示**：
- "紧缩阶段的反弹是信用收缩周期中的喘息"，不改变大方向
- 桥水在 2008 年前 **8 年**就建立了 "depression gauge"（萧条监控指标）— 说明机构有长期预警系统
- "beautiful deleveraging" = 名义增长率 > 名义利率，需平衡四工具
- 复苏到前高 GDP 通常需 **5-10 年**

**对本系统的启示**：Phase C（趋势阶段）应直接对接债务周期位置，而非简单看利率方向。

#### A.1.2 Soros《The Alchemy of Finance》— 反身性理论

**核心命题**：价格与基本面之间存在**自我强化/自我毁灭**的双向反馈循环，而非单向的"基本面决定价格"。

**应用于事件驱动**：
- 事件后反弹（价格↑）→ 信心恢复（基本面感知↑）→ 更多买入（价格↑↑）= 自我强化
- 但若反弹缺乏真实基本面跟进 → 价格无法持续 → 反身性反向：价格↓ → 信心↓ → 更多卖出
- **判断标准**：反弹后 5-15 天内基本面（通胀/信贷/盈利）是否改善

#### A.1.3 GSR 加密研究方法论 — 预期值框架

**sum-product 决策模型**：
```
市场展望 = Σ(催化剂概率 × 催化剂影响)
```
- 正面催化剂多 + 高概率 + 大影响 → 偏多
- 负面催化剂多 + 高概率 + 大影响 → 偏空

**成功率认知**：55% 命中率 + 20% 运气带 = 成功基金常态。任何交易初始 50/50，深度研究可推到 55%。

#### A.1.4 宏观事件层级框架（Tier 1-4）

所有宏观事件最终都通过"对 Fed 政策的影响"传导。层级决定交易优先级：

| 层级 | 事件 | 频率 | 说明 |
|:--|:--|:--|:--|
| **Tier 1** | FOMC 利率决议 + 发布会 | 8次/年 | 直接 Fed 决策，最高优先级 |
| **Tier 2** | CPI / NFP / PCE / GDP | 每月 | Fed 双目标输入数据，改变下次决议概率 |
| **Tier 3** | ISM / 消费者信心 / 房屋开工 | 每月 | 领先指标，预示 Tier 2 方向 |
| **Tier 4** | 零售销售 / 工业生产 | 每月 | 同步确认，市场反应最小 |

**原则**：不 over-trade 低信号事件，不 under-trade 高信号事件。

#### A.1.5 经济意外指数（Citi Economic Surprise Index）

- **定义**：实际数据 vs 市场预期的 Z-score 加权和
- **正值** = 数据强于预期 → 支持周期板块（科技/可选消费）
- **负值** = 数据弱于预期 → 支持防御板块（公用事业/必需消费）
- **对本系统的启示**：将 `surprise = actual - forecast` 标准化后可作为 macro 评分的直接输入

### A.2 事件研究法标准方法论

学术标准流程（Fama et al. 1969, Brown & Warner 1985, MacKinlay 1997）：

```
1. 定义事件日 (t=0)
2. 估计窗口：事件前 100-250 天，估计"正常收益"模型（市场模型）
3. 事件窗口：通常 [-10, +20] 天
4. 异常收益 AR = 实际收益 - 预期收益（市场模型）
5. 累计异常收益 CAR = Σ AR
6. 统计检验：t-test 检验 AR/CAR 是否显著 ≠ 0
```

**gs-quant 实现参考**：`gs_quant/timeseries/econometrics.py`（超额收益）、`statistics.py`（显著性检验）

### A.3 GitHub 开源库与工具汇总

| 项目 | 类型 | Stars | 可直接复用 | 说明 |
|:--|:--|:--|:--|:--|
| **`cme-fedwatch`** (PyPI) | Python 库 | — | ✅ **强烈推荐** | 开箱即用的 CME FedWatch 概率获取，**无需 API Key、无需 Selenium**，数据源：CME 结算价 + FRED EFFR |
| **gs-quant**（高盛开源） | Python 库 | — | ⚠️ 部分 | 事件研究法工具链（超额收益/统计检验/LSTM），但较重 |
| **CAMEF**（KDD 2025） | 学术论文 | — | ⚠️ 思路借鉴 | 因果增强多模态事件预测；发现 FOMC Minutes 预测力 > CPI/PPI |
| **NautilusTrader** | Rust+Python | 26.4K | ❌ 框架过重 | 事件驱动回测，backtest-to-live parity |
| **zipline-reloaded** | Python | — | ❌ 框架过重 | Quantopian 开源事件驱动引擎 |
| **digital-oracle** | AI Skill | 814 | ⚠️ 思路借鉴 | 从 13 个金融数据源挖宏观概率，多信号交叉验证 |
| **FMP Economic Calendar API** | REST API | — | ✅ 可选付费 | 经济日历含 consensus forecast + previous |
| **FXMacroData** | REST API | — | ✅ 可选付费 | 政策利率/通胀/breakeven/黄金，含 BTC 宏观策略示例 |
| **Trading Economics / Finnhub** | REST API | — | ✅ 可选付费 | 经济日历，实时 + 历史 surprise 数据 |

### A.4 关键发现对 SPEC 的改进

#### 改进 1：FedWatch 数据采集用 `cme-fedwatch` 库

原 SPEC T1 中 FedWatch 概率需自行抓取，现可直接用 `cme-fedwatch`：

```python
from cme_fedwatch import get_probabilities, get_history

# 下次 FOMC 概率
data = get_probabilities("next")
# 概率历史演变（用于追踪定价充分度变化）
history = get_history("next", days=10)
```

**FedWatch 计算原理**（理解底层逻辑）：
```
R_avg = 100 - P                    # 期货价格隐含月度平均利率
r_post = (R_avg * N - r_pre * d) / (N - d)   # 会议后预期利率
p = |r_post - r_pre| / 0.25        # 加息/降息概率（25bp 步长）
```

#### 改进 2：事件研究法纳入回测验证

T15 历史回测应采用标准事件研究法：
- 估计窗口：事件前 100 天
- 事件窗口：[-10, +20] 天
- 计算 CAR（累计异常收益）
- 统计检验 relief rally 是否显著

#### 改进 3：宏观事件优先级按 Tier 分层

事件驱动策略的信号权重按 Tier 调整：
- Tier 1（FOMC）：confidence 系数 ×1.0
- Tier 2（CPI/NFP）：×0.8
- Tier 3-4：×0.5

#### 改进 4：Phase B 检查清单增加经济意外指数

将 Citi Economic Surprise Index 的方向纳入 Phase B 基本面检查：
- 指数上升 → 周期力量增强 → 偏多
- 指数下降 → 防御力量增强 → 偏空

***

**文档版本**: v2.0
**最后更新**: 2026-09-17
**关联调研**: VM-1789602839825-186e8f2c（利空出尽底部识别经验）、VM-1789603916405-6afed053（不确定性消除 vs 深层利空权衡）
**关联文件**: `exogenous_strength_evaluator.py` `data_pipeline.py` `fred_collector.py`
**参考资料**: Dalio《Big Debt Crises》、Soros《The Alchemy of Finance》、CME FedWatch、gs-quant、CAMEF(KDD 2025)
