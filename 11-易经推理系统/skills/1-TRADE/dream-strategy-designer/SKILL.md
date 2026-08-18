
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


---
name: dream-strategy-designer
description: |
  🎯 战略制定 — 交易决策的最高指引 (v2.3)
  基于深度调研(A1)和第一性原理分析(A2)，通过特征蒸馏和历史模式匹配，
  生成符合当下的完整战略指令。支持多币种(BTC/ETH/SOL/XAUT/CL/XCU等)和多种交易工具
  (挂单/网格/马丁/DCA/做空/套利等)，包含专属战略记忆库和战略交易工具库。
  新增Phase 8战略顾问评审，为A4/A5链路提供可行性确认。
  
  触发词：战略制定、战略指令、战略选择、战略匹配、制定策略、战略合成、
  交易工具调研、币种调研、战略调研、多币种策略、网格策略、马丁策略、
  战略沙盘推演、应急预案、黑天鹅、极端情景、战略预案、分析完成请顾问评审、宏观资产、黄金、原油、铜
license: Internal
version: 2.7.0
created: 2026-04-20
updated: 2026-04-26
---

# 🎯 Dream-Strategy-Designer: 战略制定部 (v2.6)

> **核心原则**: "战略不是拍脑门，是基于证据的逻辑推演"
> **流程闭环**: A1调研 → A2分析 → A3战略制定 → A4验证 → A5执行
> **⚖️ v2.5核心升级**: A0矛盾论贯穿全流程，矛盾=方向，禁止因矛盾导致WAIT
> **多币种支持**: BTC | ETH | SOL | BNB | XRP
> **多工具支持**: 挂单 | 网格 | 马丁 | DCA | 做空 | 套利 | 波段

---

## 一、与前序SKILL的闭环集成

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    A3战略制定 闭环架构 (v2.3)                            │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│   A1: dream-strategy-research (v1.2) ─── Phase 5 顾问评审 (QT+RM)       │
│   └── 三角准则调研报告 + 顾问评审结论                                    │
│                          ↓                                              │
│   A2: dream-first-principles (v2.1) ─── Phase 8 顾问评审 (MR+TR)      │
│   └── 阻力/趋势分析 + 顾问评审结论                                       │
│                          ↓                                              │
│   A3: dream-strategy-designer (v2.3) ← 当前                            │
│   ├── Phase0: 战略调研                                                  │
│   │   ├── 3.1.1: 交易工具调研                                          │
│   │   ├── 3.1.2: 币种调研                                              │
│   │   ├── 3.1.3: 策略调研                                              │
│   │   └── 3.1.4: 历史策略调研                                          │
│   ├── Phase1: 输入验证                                                  │
│   ├── Phase2: 特征蒸馏                                                  │
│   ├── Phase3: 历史模式匹配                                              │
│   ├── Phase4: 战略合成                                                  │
│   ├── Phase5: 战略记忆库更新                                           │
│   ├── Phase6: 战略做梦                                                  │
│   ├── Phase7: 应急预案生成                                              │
│   └── Phase8: 战略顾问评审 (SC+QT) ← 新增 ⭐                           │
│                          ↓                                              │
│   A4: dream-tactical-validator                                         │
│   └── 战术沙盘推演                                                      │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 输入验证规则

| 前序SKILL | 必须字段 | 验证规则 |
|:---|:---|:---|
| A1调研 | `research_report.summary` | 非空 |
| A1调研 | `market_state.regime` | 6选1 |
| A2分析 | `least_resistance_path` | UP/DOWN/NEUTRAL |
| A2分析 | `market_regime_classification.regime` | 6选1 |
| A2分析 | `trend_analysis.trend_direction` | BULL/BEAR/NEUTRAL |

**验证失败处理**: 拒绝生成战略，返回缺失字段列表，要求补充A1/A2输出

---

## ⚡ A0 强制调度门禁 (P0 Fix v2.7)

> **⚠️ 强制执行**: 本SKILL必须在执行第一阶段前首先调用A0矛盾论
> 
> **执行顺序不可跳过**: Phase 00 → Phase 0 → Phase 1 → ...

### Phase 00: A0矛盾论强制调用

**必须首先执行以下操作：**

```python
# Step 00.0: 调用A0矛盾论SKILL（必须首先执行！）
use_skill("dream-contradiction-theory")

# Step 00.1: 将A0输出作为战略制定的矛盾利用框架
a0_framework = {
    "primary_contradiction": "...",   # A0识别的主要矛盾
    "contradiction_utilization": "...", # 如何利用矛盾制定战略
    "iron_laws": [...],              # A0五大铁律
    "tactical_implications": "..."   # 矛盾转化的战略启示
}
```

**门禁检查清单（必须逐项确认）：**
- [ ] `use_skill("dream-contradiction-theory")` 已执行
- [ ] A0主要矛盾已纳入战略框架
- [ ] Phase 3的矛盾利用使用A0的实际输出
- [ ] 战略指令中明确引用A0的利用策略

**违规处理**: 若跳过Phase 00，报告将标记为`a0_integration=FAILED`，A8将发出P0告警

---

## 二、核心流程：7阶段战略制定

### Phase 0: 战略调研 (10min) ← 新增

> **核心**: 在正式制定战略前，进行全面的工具和策略调研

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Phase 0: 战略调研子任务                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  0.1 交易工具调研 ← 联网搜索                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 调研目标:                                                          │   │
│  │ - 网格交易: 最佳参数、平台对比、盈亏分析                           │   │
│  │ - 马丁策略: 保守版vs激进版、风控要点                              │   │
│  │ - DCA定投: vs一次性投资、历史收益对比                             │   │
│  │ - 追踪止损: 最佳参数、波动率调整                                  │   │
│  │ - 资金费率套利: 盈利条件、风险点                                  │   │
│  │                                                                   │   │
│  │ 搜索关键词:                                                        │   │
│  │ - "grid trading bot best parameters 2024 2025"                   │   │
│  │ - "martingale strategy crypto pros cons"                          │   │
│  │ - "DCA vs lump sum crypto performance"                            │   │
│  │                                                                   │   │
│  │ 输出: tool_research_report                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  0.2 币种调研                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 调研目标:                                                          │   │
│  │ - BTC/ETH/SOL/BNB 特性对比                                        │   │
│  │ - 相关性分析: BTC涨跌对其他币种影响                                │   │
│  │ - 波动率排名: 哪个币种适合哪种策略                                 │   │
│  │ - 流动性分析: 各币种深度和交易量                                  │   │
│  │                                                                   │   │
│  │ 搜索关键词:                                                        │   │
│  │ - "bitcoin ethereum correlation 2024"                             │   │
│  │ - "solana market dynamics analysis"                               │   │
│  │                                                                   │   │
│  │ 输出: coin_research_report                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  0.3 策略调研 ← 联网搜索大V/巨鲸                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 调研目标:                                                          │   │
│  │ - 巨鲸聪明钱策略: 钱包追踪、信号订阅                              │   │
│  │ - 大V交易策略: Twitter/YouTube上的专业交易者                      │   │
│  │ - 做市商策略: 机构级别的交易手法                                  │   │
│  │ - 量化策略: 成功的量化交易系统                                    │   │
│  │                                                                   │   │
│  │ 搜索关键词:                                                        │   │
│  │ - "whale smart money crypto trading strategy 2024"                │   │
│  │ - "crypto market maker strategy"                                   │   │
│  │ - "institutional trading strategy crypto"                         │   │
│  │                                                                   │   │
│  │ 输出: strategy_research_report                                    │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  0.4 历史策略调研 ← 联网搜索经典案例                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 调研目标:                                                          │   │
│  │ - 历史牛熊市策略: 2021牛市、2022熊市的成功策略                    │   │
│  │ - 黑天鹅事件: 312/519等极端事件的应对策略                         │   │
│  │ - 成功案例: 盈利交易的完整分析                                    │   │
│  │ - 失败教训: 爆仓/巨亏的根因分析                                  │   │
│  │                                                                   │   │
│  │ 搜索关键词:                                                        │   │
│  │ - "bitcoin bear market 2022 lessons"                              │   │
│  │ - "crypto bull run 2021 strategy"                                 │   │
│  │ - "black swan crypto event analysis"                              │   │
│  │                                                                   │   │
│  │ 输出: historical_research_report                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  0.5 调研汇总                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 整合四个调研报告，输出:                                            │   │
│  │                                                                   │   │
│  │ {                                                                 │   │
│  │   "recommended_tools": ["网格", "马丁"],                          │   │
│  │   "target_coins": ["BTC", "ETH"],                                │   │
│  │   "strategy_inspirations": [...],                                │   │
│  │   "risk_warnings": [...],                                        │   │
│  │   "current_hot_strategies": [...]                                │   │
│  │ }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  0.6 宏观资产调研 ← v2.7 新增 ⚖️                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 调研目标:                                                          │   │
│  │ - 宏观资产价格趋势（黄金/原油/铜/TSLA/COIN）                    │   │
│  │ - 宏观资产与BTC的相关性变化                                       │   │
│  │ - 共振信号识别（通胀预期/风险偏好/行业Beta/滞胀恐慌）          │   │
│  │ - 背离信号识别（相关性断裂）                                     │   │
│  │                                                                   │   │
│  │ 数据来源:                                                          │   │
│  │ - OKX API: 查询SWAP合约价格（XAU/CL/XCU/TSLA/COIN）          │   │
│  │ - A6监控系统: 读取最新宏观资产监控数据                           │   │
│  │                                                                   │   │
│  │ 输出: macro_assets_research_report                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**工具**: Tavily联网搜索 / Agent-Reach / WebSearch

**输出文件**: `~/.workbuddy/strategy-library/research_cache/{date}_tool_research.yaml`

---

### Phase 1: 输入验证 (2min)

```
验证清单:
□ A1 research_report 完整
□ A2 first_principles_analysis 完整
□ A2 market_regime_classification 有效
□ A2 main_contradiction 已识别
□ 数据新鲜度 < 1小时

IF 验证通过 → 进入Phase2
ELSE → 输出验证失败报告，终止
```

### Phase 2: 特征蒸馏 (5min)

> **核心**: 从A1调研+A2分析中提炼当前市场的核心特征向量

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        特征蒸馏引擎                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 2.1: 提取市场特征向量                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ Feature Vector (特征向量):                                       │   │
│  │                                                                  │   │
│  │ 1. 方向特征: {direction: BULL/BEAR/NEUTRAL, confidence: 0-1}   │   │
│  │ 2. 动能特征: {momentum: ACCELERATING/STABLE/DECELERATING}      │   │
│  │ 3. 阻力特征: {resistance: EASY/HARD/MIXED}                      │   │
│  │ 4. 波动特征: {volatility: HIGH/NORMAL/LOW}                       │   │
│  │ 5. 情绪特征: {sentiment: EXTREME_FEAR/FEAR/NEUTRAL/GREED/...}  │   │
│  │ 6. 资金特征: {capital: INFLOW/OUTFLOW/NEUTRAL}                 │   │
│  │ 7. 宏观特征: {macro: RISK_ON/RISK_OFF/NEUTRAL}                   │   │
│  │ 8. 时序特征: {timing: EARLY/MID/LATE}                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Step 2.2: 矛盾蒸馏 (v2.5 A0升级 ⚖️)
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 从A2的a0_contradiction_analysis中提取:                           │   │
│  │                                                                  │   │
│  │ - 主要矛盾: A0 4维评分排名第一的矛盾                              │   │
│  │ - 主要方面: dominant_side (A|B) → 直接映射方向                   │   │
│  │ - 转化条件: transformation.condition → 纳入监控点               │   │
│  │ - 矛盾排名: contradiction_ranking → 评估矛盾清晰度              │   │
│  │ - 矛盾共识: 统计排名前5的矛盾中几个方向一致                       │   │
│  │                                                                  │   │
│  │ 矛盾清晰度评估:                                                   │   │
│  │ - CLEAR: 主要矛盾dominant_side差距>2 且 排名前3矛盾方向一致      │   │
│  │ - MODERATE: 主要矛盾dominant_side差距≤2 或 方向不一致             │   │
│  │ - FUZZY: 所有矛盾方向冲突                                        │   │
│  │                                                                  │   │
│  │ ⚠️ FUZZY时不允许输出WAIT，应输出PROBE (A0-IRON-4)                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Step 2.3: Regime特征确认                                               │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ A2输出的market_regime:                                          │   │
│  │                                                                  │   │
│  │ TREND_STRONG       → 趋势延续类战略                              │   │
│  │ TREND_EXHAUSTION   → 趋势反转/观望类战略                        │   │
│  │ RANGE_BOUND        → 区间震荡类战略                              │   │
│  │ BREAKOUT_PENDING   → 突破确认类战略                              │   │
│  │ FALSE_BREAKOUT_RISK→ 假突破识别类战略                           │   │
│  │ EXTREME            → 极端风险管理类战略                          │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 3: 历史模式匹配 (8min)

> **核心**: 搜索三大知识库，寻找类似历史经验

```
┌─────────────────────────────────────────────────────────────────────────┐
│                      历史模式匹配引擎                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  3.1 战略记忆库搜索 ← 内部经验                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 搜索条件:                                                          │   │
│  │ - regime_match: 当前regime                                        │   │
│  │ - direction_match: 特征向量方向                                   │   │
│  │ - volatility_match: 波动特征                                     │   │
│  │                                                                  │   │
│  │ 命中输出:                                                         │   │
│  │ - matched_strategies: [战略ID列表]                               │   │
│  │ - success_rate: 历史成功率                                       │   │
│  │ - avg_duration: 平均持仓周期                                      │   │
│  │ - lessons: 历史教训                                               │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  3.2 大师蒸馏库搜索 ← 外部大师经验                                      │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 搜索范围:                                                          │   │
│  │ - neuro-cognitive-modeler: 大师认知模型                          │   │
│  │ - market-practice-simulator: 实战playbook                        │   │
│  │ - right-brain-strategist: 情景推演                               │   │
│  │                                                                  │   │
│  │ 匹配大师类型:                                                      │   │
│  │ - Livermore: 趋势交易、突破确认                                  │   │
│  │ - Tharp: 趋势延续、止损管理                                       │   │
│  │ - 孙子: 以逸待劳、知己知彼                                        │   │
│  │ - 斯佩兰迪奥: 阻力最小路径                                       │   │
│  │                                                                  │   │
│  │ 命中输出:                                                         │   │
│  │ - master_recommendations: [大师建议列表]                         │   │
│  │ - playbook_refs: [playbook引用]                                  │   │
│  │ - regime_fit_score: 适配度评分                                   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  3.3 档案中心搜索 ← 外部历史案例                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 搜索关键词:                                                        │   │
│  │ - 当前价格形态                                                    │   │
│  │ - 类似宏观环境                                                    │   │
│  │ - 类似regime历史case                                              │   │
│  │                                                                  │   │
│  │ 命中输出:                                                         │   │
│  │ - archive_cases: [档案案例列表]                                   │   │
│  │ - similarity_scores: [相似度评分]                                │   │
│  │ - outcomes: [历史结果]                                           │   │
│  │ - takeaways: [可借鉴要点]                                        │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  3.4 联网搜索补充 ← 经典交易案例                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 搜索词模式:                                                        │   │
│  │ - "[大师名] [类似策略] 案例"                                      │   │
│  │ - "[当前regime] 经典操作"                                        │   │
│  │                                                                  │   │
│  │ 数据源优先级:                                                     │   │
│  │ - Tavily (主力)                                                   │   │
│  │ - Agent Reach (补充)                                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 4: 战略合成 (8min)

> **核心**: 基于历史经验，结合当下特征，生成定制化战略

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        战略合成引擎                                     │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  Step 4.1: 经典战略适配                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ FOR each matched_classic_strategy:                              │   │
│  │                                                                  │   │
│  │   1. 检查适用条件是否满足                                         │   │
│  │   2. 识别需要调整的参数                                           │   │
│  │   3. 标注风险边界                                                │   │
│  │   4. 计算适配置信度                                               │   │
│  │                                                                  │   │
│  │ 适配结果:                                                        │   │
│  │ - adapted_strategy: 调整后的战略                                 │   │
│  │ - adaptation_notes: 调整原因                                     │   │
│  │ - confidence: 置信度                                              │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Step 4.2: 矛盾融合 (v2.5 A0升级 ⚖️)
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 基于Phase2的A0矛盾分析:                                          │   │
│  │                                                                  │   │
│  │ 核心原则: 顺着主要矛盾方向行动，矛盾=方向，不是观望理由           │   │
│  │                                                                  │   │
│  │ IF 矛盾清晰度 == CLEAR:                                          │   │
│  │    THEN 战略方向 = 主要矛盾主要方面，标准仓位                     │   │
│  │                                                                  │   │
│  │ IF 矛盾清晰度 == MODERATE:                                       │   │
│  │    THEN 战略方向 = 主要矛盾主要方面，半仓(0.5x)                   │   │
│  │                                                                  │   │
│  │ IF 矛盾清晰度 == FUZZY:                                          │   │
│  │    THEN 战略方向 = 基本面重心方向(A0-IRON-3)，最小仓位(0.25x)    │   │
│  │    ❌ 禁止输出WAIT                                              │   │
│  │    ✅ 必须输出PROBE或DIP_BUY                                    │   │
│  │                                                                  │   │
│  │ 矛盾转化预判:                                                    │   │
│  │ ├── 转化概率HIGH: 准备对冲或止盈，position_modifier-0.25        │   │
│  │ ├── 转化概率MODERATE: 设定监控点，纳入exit_conditions           │   │
│  │ └── 转化概率LOW: 正常持有，监控但不调整                         │   │
│  │                                                                  │   │
│  │ 矛盾共识增强:                                                    │   │
│  │ ├── ≥3个矛盾方向一致: position_modifier+0.25(可加仓)             │   │
│  │ └── 矛盾方向冲突: 严格止损，缩窄止损幅度                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  Step 4.3: 战略组装                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 组装完整战略指令:                                                  │   │
│  │                                                                  │   │
│  │ {                                                                 │   │
│  │   "directive_bias": "LONG|SHORT|WAIT|REDUCE|PROBE|DIP_BUY|HEDGE",
│  │                                                                  │   │
│  │   ⭐ v2.4 新增directive_bias说明:                                  │   │
│  │   ├── LONG: 趋势做多（原保留）                                     │   │
│  │   ├── SHORT: 趋势做空（原保留）                                    │   │
│  │   ├── WAIT: 观望（受限使用，见约束12）                              │   │
│  │   ├── REDUCE: 减仓（原保留）                                       │   │
│  │   ├── PROBE: 小仓试探（v2.4新增）                                  │   │
│  │   │   └── 含义: 信号不足或矛盾时，用最小仓位(10-20U)试探方向        │   │
│  │   │   └── 触发: 信号充分性=LOW / 行动压力≥MODERATE / 矛盾处理2.0   │   │
│  │   ├── DIP_BUY: 超卖抄底（v2.4新增）                                │   │
│  │   │   └── 含义: RSI<30 + 恐惧指数<40时的小仓抄底                   │   │
│  │   │   └── 触发: A2逆向补偿条件A触发 / RSI<25                       │   │
│  │   └── HEDGE: 对冲保护（v2.4新增）                                  │   │
│  │       └── 含义: 方向不明但风险偏高时，双向轻仓对冲                   │   │
│  │       └── 触发: 综合风险>7/10 且 A1信号方向=MIXED                  │   │
│  │                                                                  │   │
│  │   "position_modifier": 0.0-1.0,                                  │   │
│  │   "leverage_cap": 1-5,                                           │   │
│  │   "entry_conditions": [...],                                      │   │
│  │   "exit_conditions": [...],                                      │   │
│  │   "risk_rules": [...],                                           │   │
│  │   "timing_guidance": "...",                                      │   │
│  │   "master_references": [...],                                    │   │
│  │   "lessons_applied": [...],                                       │   │
│  │   "recommended_tools": [...],  ← 新增:推荐工具                    │   │
│  │   "target_coins": [...]        ← 新增:目标币种                   │   │
│  │ }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### Phase 5: 战略记忆库更新 (3min)

> **核心**: 将本次战略制定过程写入战略记忆库，供未来参考

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        战略记忆库更新                                   │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  5.1 案例归档                                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 写入文件: strategy_library.yaml                                  │   │
│  │                                                                  │   │
│  │ 新增条目:                                                        │   │
│  │ - case_id: 唯一ID                                               │   │
│  │ - date: 制定日期                                                 │   │
│  │ - feature_vector: 当时的特征向量                                  │   │
│  │ - regime: 当时的regime                                          │   │
│  │ - strategy_selected: 选择的战略                                  │   │
│  │ - tools_used: 使用的交易工具 ← 新增                              │   │
│  │ - coins_targeted: 目标币种 ← 新增                                │   │
│  │ - rationale: 选择理由                                            │   │
│  │ - execution_result: 执行结果(后续更新)                            │   │
│  │ - lessons_learned: 教训总结(后续更新)                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  5.2 战略库结构更新                                                     │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ IF 本次战略为新类型:                                              │   │
│  │    THEN 在strategy_templates中添加新模板                         │   │
│  │                                                                  │   │
│  │ IF 某经典战略被验证有效:                                         │   │
│  │    THEN 增加该战略的success_count                                │   │
│  │                                                                  │   │
│  │ IF 某经典战略被验证失败:                                         │   │
│  │    THEN 增加该战略的failure_count，更新exclusion_conditions      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  5.3 战略交易工具库更新 ← 新增                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 写入文件: strategy_tools.yaml                                    │   │
│  │                                                                  │   │
│  │ IF 本次使用的工具有效:                                            │   │
│  │    THEN 增加该工具的success_count                                │   │
│  │                                                                  │   │
│  │ IF 本次使用的工具失败:                                            │   │
│  │    THEN 分析失败原因，更新工具参数建议                            │   │
│  │                                                                  │   │
│  │ IF 发现新的有效工具组合:                                          │   │
│  │    THEN 在tool_combinations中记录                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  5.4 记忆库位置                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 路径: ~/.workbuddy/strategy-library/                            │   │
│  │                                                                  │   │
│  │ 文件:                                                            │   │
│  │ ├── strategy_templates.yaml (经典战略模板)                       │   │
│  │ ├── strategy_tools.yaml (交易工具库) ← 新增                      │   │
│  │ ├── historical_cases.yaml (历史案例库)                           │   │
│  │ ├── master_playbooks.yaml (大师实战手册索引)                     │   │
│  │ └── research_cache/ (调研缓存) ← 新增                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

---

### Phase 6: 战略做梦 (5min) ← 新增

> **核心**: 用A1调研和A2分析的资料做梦，挖掘被压制的信号和反直觉的战略机会

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Phase 6: 战略做梦子任务                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  基于弗洛伊德《梦的解析》机制，对A1/A2资料进行潜意识分析                  │
│                                                                         │
│  6.1 凝缩分析 (Condensation)                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 将多个看似无关的信号凝缩为单一战略洞察:                             │   │
│  │                                                                   │   │
│  │ 例: "RSI超卖 + ETF流出 + 巨鲸抄底" → 凝缩为 "被压制的反弹信号"   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  6.2 移置分析 (Displacement)                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 关注那些被忽视的信号，它们可能指向真实方向:                         │   │
│  │                                                                   │   │
│  │ 例: "恐惧情绪被忽视" → 移置为 "逆向买入机会"                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  6.3 象征分析 (Symbolism)                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 解读市场行为背后的象征意义:                                       │   │
│  │                                                                   │   │
│  │ 例: "成交量萎缩" → 象征 "蓄势待发"                               │   │
│  │     "资金费率飙升" → 象征 "逼空风险"                             │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  6.4 二次修正分析 (Secondary Revision)                                  │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 对理性分析进行二次修正，打破常规思维:                             │   │
│  │                                                                   │   │
│  │ 例: "常规判断: 观望" → 二次修正为 "极端恐惧时应逆向"             │   │
│  │     "常规判断: 做空" → 二次修正为 "超卖+支撑=买入机会"           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  6.5 投射分析 (Projection)                                              │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 将内心恐惧/贪婪投射到市场，识别潜在风险:                           │   │
│  │                                                                   │   │
│  │ 例: "系统害怕踏空" → 识别非理性追涨风险                          │   │
│  │     "系统害怕做空" → 识别反向机会                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  6.6 反事实推演 (Counterfactual)                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 推演"如果不这么做会怎样":                                        │   │
│  │                                                                   │   │
│  │ 例: "如果现在不止损，继续持有..." → 可能亏损X%                   │   │
│  │     "如果反向操作..." → 收益/风险对比                            │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  输出: strategic_dream_report                                           │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ {                                                                 │   │
│  │   "dream_insights": [                                           │   │
│  │     {                                                            │   │
│  │       "type": "凝缩",                                           │   │
│  │       "signal": "多信号汇聚",                                    │   │
│  │       "implication": "战略机会",                                 │   │
│  │       "confidence": 0.8                                         │   │
│  │     }                                                            │   │
│  │   ],                                                             │   │
│  │   "contrarian_signals": [...],  ← 反直觉信号                    │   │
│  │   "risk_projections": [...],   ← 投射识别的风险                 │   │
│  │   "alternative_strategies": [...] ← 反事实推演结果              │   │
│  │ }                                                                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**触发条件**: 当以下任一条件满足时必须执行战略做梦:
- Regime = EXTREME 或 TREND_EXHAUSTION
- 连续SKIP次数 ≥ 7
- 战略-战术存在冲突
- 矛盾强度 = HIGH

**工具**: dream-oneirology 做梦部SKILL

**输出文件**: `~/.workbuddy/strategy-library/research_cache/{date}_strategic_dream.yaml`

---

## 三、战略记忆库结构

### 3.1 经典战略模板 (strategy_templates.yaml)

```yaml
strategy_templates:
  - id: "livermore_breakout_001"
    name: "Livermore突破策略"
    category: "趋势追踪"
    regime_applicability: ["BREAKOUT_PENDING"]
    source: "Livermore"
    
    trigger_conditions:
      - type: "price_action"
        condition: "价格突破前高"
      - type: "volume"
        condition: "突破时放量>1.5倍均量"
      - type: "trend"
        condition: "MA多头排列"
    
    exclusion_conditions:
      - type: "extreme_sentiment"
        condition: "Fear&Greed>85"
      - type: "low_liquidity"
        condition: "depth<$5M"
    
    parameters:
      entry_buffer_pct: 0.002
      initial_stop_pct: 0.03
      position_size_max: 0.25
      trailing_stop_method: "swing_low"
    
    playbook_ref: "livermore_breakout_playbook_v1"
    success_count: 12
    failure_count: 3
    avg_duration_hours: 48
    lessons:
      - "突破失败后不要追涨"
      - "量价配合是关键"

  - id: "sunzi_wait_001"
    name: "孙子以逸待劳"
    category: "形势判断"
    regime_applicability: ["FALSE_BREAKOUT_RISK"]  ← v2.4 修复: 解绑RANGE_BOUND和TREND_EXHAUSTION
    source: "孙子兵法"
    
    trigger_conditions:
      - type: "regime"
        condition: "任一高风险regime"
      - type: "momentum"
        condition: "动能衰竭信号"
    
    exclusion_conditions: []
    
    parameters:
      directive_bias: "WAIT"
      position_modifier: 0.0
      leverage_cap: 1
    
    playbook_ref: "sunzi_wait_playbook_v1"
    success_count: 8
    failure_count: 1
    avg_duration_hours: 24
    lessons:
      - "不战而屈人之兵"
      - "等待本身就是策略"

  - id: "tharp_trend_continuation_001"
    name: "Tharp趋势延续策略"
    category: "趋势追踪"
    regime_applicability: ["TREND_STRONG"]
    source: "Tharp"
    
    trigger_conditions:
      - type: "trend"
        condition: "MA轨迹>0.5σ"
      - type: "volatility"
        condition: "ATR正常范围"
    
    exclusion_conditions:
      - type: "sentiment"
        condition: "FundingRate>0.05%"
    
    parameters:
      entry_method: "回踩确认"
      stop_loss: "EMA20下方"
      position_size: "波动率调整"
    
    playbook_ref: "tharp_trend_playbook_v1"
    success_count: 15
    failure_count: 4
    avg_duration_hours: 72
    lessons:
      - "让利润奔跑"
      - "截断亏损"
```

### 3.2 历史案例库 (historical_cases.yaml)

```yaml
historical_cases:
  - case_id: "case_20260415_btc_breakout"
    date: "2026-04-15"
    feature_vector:
      direction: "BULL"
      momentum: "ACCELERATING"
      resistance: "EASY"
      volatility: "NORMAL"
    regime: "BREAKOUT_PENDING"
    strategy_selected: "livermore_breakout_001"
    rationale: "MA多头排列+放量突破"
    execution_result: "PROFIT"
    pnl_pct: 5.2
    lessons_learned:
      - "突破后回踩确认再入场更稳健"
    
  - case_id: "case_20260418_btc_wait"
    date: "2026-04-18"
    feature_vector:
      direction: "NEUTRAL"
      momentum: "DECELERATING"
      resistance: "MIXED"
      volatility: "HIGH"
    regime: "TREND_EXHAUSTION"
    strategy_selected: "sunzi_wait_001"
    rationale: "动能衰竭+高波动+regime危险"
    execution_result: "SKIP"
    lessons_learned:
      - "高波动+动能衰竭=观望为上"
```

---

## 四、输入输出规范

### 4.1 输入（必须完整）

| 字段 | 类型 | 来源 | 验证规则 |
|:---|:---|:---|:---|
| `research_report` | object | A1 | 必须包含summary, market_state |
| `first_principles_analysis` | object | A2 | 必须包含least_resistance_path |
| `market_regime_classification` | object | A2 | 必须包含regime |
| `main_contradiction` | object | A2 | 必须包含primary |
| `feature_vector` | object | A3生成 | 内部生成 |

### 4.2 输出（必须结构化）

```json
{
  "strategy_directive": {
    "directive_id": "dir_20260421_001",
    "directive_bias": "LONG|SHORT|WAIT|REDUCE|PROBE|DIP_BUY|HEDGE",  ← v2.4 扩展
    "probe_config": {                              ← v2.4 新增（PROBE/DIP_BUY时必填）
      "direction": "UP|DOWN",
      "max_position_usdt": 20,
      "stop_loss_pct": 3.0,
      "entry_conditions": ["条件1", "条件2"],
      "exit_conditions": ["止损/止盈/超时"]
    },
    "position_modifier": 0.0-1.0,
    "leverage_cap": 1-5,

    "target_coins": ["BTC", "ETH"],  ← 新增:目标币种

    "recommended_tools": [  ← 新增:推荐工具
      {
        "tool_id": "spot_limit_order",
        "tool_name": "现货限价挂单",
        "allocation": 0.5,
        "parameters": {...}
      },
      {
        "tool_id": "futures_limit_order",
        "tool_name": "合约限价挂单",
        "allocation": 0.3,
        "parameters": {...}
      }
    ],

    "matched_strategy": {
      "template_id": "livermore_breakout_001",
      "name": "Livermore突破策略",
      "source": "Livermore",
      "match_confidence": 0.0-1.0,
      "adaptation_notes": "针对当前市场的调整说明"
    },

    "entry_conditions": [
      { "type": "price_action", "condition": "...", "priority": 1 },
      { "type": "volume", "condition": "...", "priority": 2 }
    ],

    "exit_conditions": [
      { "type": "stop_loss", "trigger": "...", "action": "平仓" },
      { "type": "take_profit", "trigger": "...", "action": "分批止盈" }
    ],

    "risk_rules": [
      { "rule": "最大亏损2%", "enforcement": "HARD" },
      { "rule": "杠杆不超过3x", "enforcement": "HARD" }
    ],

    "timing_guidance": "描述入场时机和节奏",

    "contradiction_handling": {
      "primary_contradiction": "...",
      "strategic_response": "..."
    },
    "a0_contradiction_strategy": {              ← v2.5 新增 (A0集成) ⚖️
      "contradiction_clarity": "CLEAR|MODERATE|FUZZY",
      "primary_contradiction_action": "顺主要矛盾做多/做空",
      "position_modifier_from_contradiction": 1.0,
      "contradiction_consensus": "3/5矛盾方向一致",
      "monitoring_points": [
        {"contradiction_id": "CX_001", "watch": "转化条件", "action": "应对动作"}
      ],
      "transformation_risk": "LOW|MODERATE|HIGH",
      "confirmation_coefficient": {                                  ← v2.6 新增(Q2-P2修复) ⚖️
        "description": "矛盾清晰但缺少独立信号验证时的仓位降级系数",
        "usage": "当contradiction_clarity=CLEAR但缺乏A1/A2中独立信号交叉验证时，position_modifier×confirmation_coefficient",
        "values": {
          "fully_confirmed": 1.0,
          "partially_confirmed": 0.75,
          "unconfirmed": 0.5
        },
        "judgment_criteria": {
          "fully_confirmed": "CLEAR + ≥2个独立信号方向一致 + A1信号充分性=HIGH",
          "partially_confirmed": "CLEAR + 1个独立信号方向一致 或 A1信号充分性=MODERATE",
          "unconfirmed": "CLEAR + 无独立信号方向一致 且 A1信号充分性=LOW"
        },
        "example": "clarity=CLEAR + partial_confirmed → position_modifier=0.75 × 标准仓"
      }
    }
  },
  
    "evidence_chain": {
    "phase0_research": {  ← 新增:战略调研输出
      "tool_research": {...},
      "coin_research": {...},
      "strategy_research": {...},
      "historical_research": {...},
      "macro_assets_research": {  ← v2.7 新增 (宏观资产调研) ⚖️
        "assets_analyzed": ["XAU-USDT-SWAP", "CL-USDT-SWAP", "XCU-USDT-SWAP", "TSLA-USDT-SWAP", "COIN-USDT-SWAP"],
        "resonance_signals": [
          {"signal_type": "INFLATION_EXPECTATION", "description": "...", "direction_implication": "UP"}
        ],
        "divergence_detected": false,
        "divergence_details": [],
        "summary": "宏观资产调研摘要"
      }
    },
    "a1_inputs": {
      "research_summary": "...",
      "key_findings": [...]
    },
    "a2_inputs": {
      "regime": "...",
      "least_resistance_path": "...",
      "main_contradiction": "..."
    },
    "feature_distillation": {
      "direction": "...",
      "momentum": "...",
      "volatility": "...",
      "regime": "..."
    },
    "historical_matches": {
      "strategy_matches": [...],
      "master_recommendations": [...],
      "archive_cases": [...]
    },
    "phase6_dream_output": {  ← 新增:战略做梦输出
      "dream_insights": [...],
      "contrarian_signals": [...],
      "alternative_strategies": [...]
    }
  },
  
  "strategic_rationale": {
    "why_this_strategy": "选择此战略的核心理由",
    "adaptations_from_classic": ["从经典做法做的调整"],
    "lessons_applied": ["应用的历史教训"],
    "contradictions_addressed": ["解决的矛盾"]
  },
  
  "memory_update": {
    "case_to_archive": true,
    "template_updates": [],
    "lessons_to_record": []
  },
  
  "meta": {
    "designer_version": "2.1.0",
    "timestamp": "ISO时间戳",
    "phases_completed": [
      "调研",      // Phase0
      "验证",      // Phase1
      "蒸馏",      // Phase2
      "匹配",      // Phase3
      "合成",      // Phase4
      "归档",      // Phase5
      "做梦"       // Phase6
    ],
    "processing_time_seconds": 120
  }
}
```

---

## 五、经典战略索引

### 5.1 按Regime分类

| Regime | 推荐战略 | 来源 | 置信度 |
|:---|:---|:---|:---|
| TREND_STRONG | tharp_trend_continuation_001 | Tharp | 高 |
| TREND_STRONG | livermore_trend_001 | Livermore | 高 |
| TREND_EXHAUSTION | probe_reversal_001 ⭐ | 通用 | 高 |
| TREND_EXHAUSTION | sunzi_wait_001 (仅矛盾时) | 孙子 | 中 |
| RANGE_BOUND | range_probe_001 ⭐ | 通用 | 高 |
| RANGE_BOUND | dip_buy_support_001 ⭐ | 通用 | 中 |
| BREAKOUT_PENDING | livermore_breakout_001 | Livermore | 高 |
| BREAKOUT_PENDING | spolander_breakout_001 | 斯佩兰迪奥 | 中 |
| FALSE_BREAKOUT_RISK | sunzi_wait_001 | 孙子 | 高 |
| FALSE_BREAKOUT_RISK | napoleon_001 | 拿破仑 | 中 |
| EXTREME | risk_management_001 | 通用 | 高 |
| EXTREME | hedge_dual_001 ⭐ | 通用 | 中 |

> ⭐ v2.4 新增战略模板说明:
> - `probe_reversal_001`: 趋势衰竭时小仓试探反转方向，止损2%，止盈5%
> - `range_probe_001`: 区间震荡时在支撑/阻力附近小仓试探突破方向
> - `dip_buy_support_001`: 触及关键支撑位+超卖信号时小仓抄底
> - `hedge_dual_001`: 风险极高时双向轻仓对冲

### 5.2 按Direction分类

| Direction | 推荐战略 | 前提条件 |
|:---|:---|:---|
| BULL + STRONG | LONG_001 (趋势追踪) | MA多头 + 放量 |
| BULL + WEAK | LONG_002 (谨慎追多) | 必须回踩确认 |
| BEAR + STRONG | SHORT_001 (趋势做空) | MA空头 + 放量 |
| BEAR + WEAK | SHORT_002 (谨慎追空) | 必须反弹确认 |
| NEUTRAL | WAIT_001 (观望) | 任一高风险条件 |
| MIXED | WAIT_001 (观望) | 矛盾未消解 |

---

## 六、FAQ踩坑记录

> ⚠️ **战略不是拍脑门**: 每一项战略决策必须追溯到A1/A2的证据链
>
> ⚠️ **历史经验加权**: 当战略库中有类似案例时，优先适配而非创新
>
> ⚠️ **矛盾优先处理**: 当主要矛盾未消解时，战略倾向保守(WATI/REDUCE)
>
> ⚠️ **记忆库必须更新**: 每次战略制定后必须归档案例，形成闭环学习
>
> ⚠️ **数据新鲜度**: A1/A2输出超过1小时需重新验证
>
> ⚠️ **多币种分散风险**: 单一币种仓位不超过50%，建议分散到2-3个币种
>
> ⚠️ **工具匹配原则**: 不同regime匹配不同工具，参考tool_selection_matrix
>
> ⚠️ **战略调研前置**: Phase0调研不可跳过，为战略合成提供证据支撑
>
> ⚠️ **战略做梦触发**: 极端市场/连续SKIP≥7/矛盾HIGH时必须执行
>
> ⚠️ **v2.4 WAIT受限**: WAIT仅在FALSE_BREAKOUT_RISK+矛盾STRONG时允许，其余用PROBE替代
> ⚠️ **v2.4 新增动作**: PROBE(小仓试探) / DIP_BUY(超卖抄底) / HEDGE(双向对冲)
> ⚠️ **v2.4 RANGE_BOUND解绑**: 不再默认sunzi_wait_001，改用range_probe_001
> ⚠️ **v2.4 连续SKIP**: ≥7天SKIP→A1压力HIGH→A3必须输出PROBE
> ⚠️ **v2.4 信号LOW**: A1信号充分性=LOW→A3必须输出PROBE/DIP_BUY/HEDGE
> ⚠️ **⚖️ v2.5 A0矛盾利用**: 战略方向必须与主要矛盾方向一致，矛盾清晰度决定仓位
> ⚠️ **⚖️ v2.5 矛盾转化监控**: monitoring_points必须包含矛盾转化条件，转化即调仓
> ⚠️ **⚖️ v2.5 FUZZY≠WAIT**: 矛盾方向全冲突时取基本面重心方向+PROBE，禁止WAIT
> ⚠️ **⚖️ v2.6 Q2-P2修复**: a0_contradiction_strategy增加confirmation_coefficient，CLEAR+未确认场景降级至0.5×标准仓

---

## 七、集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---|:---|:---|
| **输入←** | ← | `dream-strategy-research` | A1调研报告(含contradiction_list) |
| **输入←** | ← | `dream-first-principles` | A2分析结果(含a0_contradiction_analysis) |
| **框架←** | ← | `dream-contradiction-theory` | A0矛盾论: Step3利用矛盾 ⚖️ |
| **知识库←** | ← | `dream-distill-department/*` | 大师蒸馏库 |
| **知识库←** | ← | `dream-archive-center` | 历史档案 |
| **知识库←** | ← | `tavily` | 联网搜索经典案例 |
| **输出→** | → | `dream-tactical-validator` | A4战术验证 |
| **输出→** | → | `dream-tactical-executor` | A5战术执行（Phase7预案） |
| **输出→** | → | `dream-signal-scoring-spec` | 评分系统第7维度 |
| **输出→** | → | `dream-pretrade-gatekeeper` | 门禁校验 |
| **记忆→** | → | `strategy_library.yaml` | 战略记忆库 |

---

## 八、调度

- **自动化**: `dream-strategy-designer` (周一 11:00) | `dream-war-game-simulator` (周一 11:30)
- **前置依赖**:
  - `dream-strategy-research` (周一 09:00)
  - `dream-first-principles` (周一 10:30)
  - `tavily` (联网搜索用)
- **触发词**: "战略制定"、"战略指令"、"战略合成"、"制定策略"、"交易工具调研"、"币种调研"、"多币种策略"、"战略沙盘推演"、"应急预案"

---

## 九、约束

1. **证据链必须完整**: A1→A2→A3，每步必须有输出
2. **历史经验优先**: 有类似案例时，优先适配而非创新
3. **矛盾消解优先**: 矛盾未解时，战略保守
4. **记忆库必须更新**: 每次制定后归档
5. **⭐ 方向性输出强制 (v2.4 修复)**: A3必须输出directive_bias。
   WAIT仅限以下情况: (a) FALSE_BREAKOUT_RISK + 矛盾强度=STRONG
   其他情况必须为 LONG/SHORT/REDUCE/PROBE/DIP_BUY/HEDGE 之一。
   PROBE替代大部分原WAIT场景: 信号不充分→PROBE，矛盾未解→PROBE，方向不明→PROBE。
6. **多币种分散**: 单币种仓位≤50%，建议2-3个币种分散
7. **工具匹配**: 必须基于regime选择对应工具
8. **调研前置**: Phase0调研是Phase4合成的必要前提
9. **做梦触发**: 极端/连续SKIP≥7/矛盾HIGH时必须执行
10. **沙盘推演强制**: Phase7每次战略制定后必须执行，生成应急预案库
11. **⭐ 顾问评审强制 (v2.3)**: A3战略制定完成 ≠ 流程完成，必须完成Phase 8顾问评审
12. **⭐ 评审内嵌不投递 (v2.3)**: 顾问评审结论直接追加到报告末尾，不单独投递到pending_tasks/inbox/
13. **⭐ 连续SKIP→PROBE强制转换 (v2.4 新增)**: 当A1报告action_pressure=HIGH时（连续SKIP≥7天），
    A3必须输出directive_bias=PROBE或DIP_BUY，**禁止输出WAIT**。
    触发L_EXISTING_001教训: "连续SKIP≥7→反顾问"。
14. **⭐ 信号充分性=LOW→PROBE强制 (v2.4 新增)**: 当A1报告signal_sufficiency=LOW时，
    A3必须输出PROBE/DIP_BUY/HEDGE之一，**禁止输出WAIT**。
15. **⭐ RANGE_BOUND不再默认WAIT (v2.4 修复)**: RANGE_BOUND推荐range_probe_001或dip_buy_support_001，
    仅在false_breakout风险时才使用sunzi_wait_001。
16. **⚖️ A0矛盾利用强制 (v2.5 新增)**: 战略方向必须与A0主要矛盾方向一致。矛盾清晰度(CLEAR/MODERATE/FUZZY)
    直接决定position_modifier。FUZZY时禁止WAIT，必须输出PROBE/DIP_BUY。战略必须包含矛盾转化
    监控点(monitoring_points)。矛盾共识(≥3个同向)时可加仓，矛盾方向冲突时必须缩窄止损。

---

## 十、Phase 7: 战略沙盘推演 ← 新增

> **核心**: 在完成Phase1-6后，执行战略沙盘推演，为战术SKILL生成应急预案库
> **目标**: 提供至少3套战略预案，应对黑天鹅、极端情景和概率情景
> **输出**: 战略参考库，供dream-tactical-executor调用

### 10.1 沙盘推演流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Phase 7: 战略沙盘推演                               │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  7.1 黑天鹅情景模拟 ← 5类黑天鹅事件                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  事件类型:                                                          │   │
│  │  ├── BS_001: 交易所系统性风险 (FTX/MtGox)                          │   │
│  │  ├── BS_002: 重大监管政策 (SEC/央行打击)                            │   │
│  │  ├── BS_003: 全球金融危机 (战争/银行危机)                            │   │
│  │  ├── BS_004: DeFi协议漏洞/黑客攻击                                  │   │
│  │  └── BS_005: 交易所技术故障/插针                                    │   │
│  │                                                                   │   │
│  │  模拟内容:                                                          │   │
│  │  ├── 价格冲击幅度                                                   │   │
│  │  ├── 恢复周期                                                       │   │
│  │  ├── 流动性影响                                                     │   │
│  │  └── 应急预案                                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  7.2 极端情景模拟 ← 3类极端行情                                        │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  情景类型:                                                          │   │
│  │  ├── EXT_001: 瀑布暴跌 (1h内-15%+)                                 │   │
│  │  ├── EXT_002: 暴涨逼空 (1h内+10%+)                                 │   │
│  │  └── EXT_003: 长期横盘 (ATR<1%持续7天+)                             │   │
│  │                                                                   │   │
│  │  响应策略:                                                          │   │
│  │  ├── 瀑布暴跌: 分批建仓，RSI<25确认底部                             │   │
│  │  ├── 暴涨逼空: 禁止追多，等待回踩                                  │   │
│  │  └── 长期横盘: 网格/套利/观望                                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  7.3 概率情景预案 ← 3套战略预案 (必须)                                │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  PLAN_A: 基准情景 (50%)                                           │   │
│  │  ├── 条件: 市场按当前趋势平稳运行                                  │   │
│  │  ├── 战略: 保持当前战略指令                                       │   │
│  │  └── 战术: 分批入场，止损±3%                                      │   │
│  │                                                                   │   │
│  │  PLAN_B: 乐观情景 (25%)                                           │   │
│  │  ├── 条件: 突破确认，趋势加速                                      │   │
│  │  ├── 战略: 趋势追踪，加仓+25%                                      │   │
│  │  └── 战术: 金字塔加仓，追踪止损                                    │   │
│  │                                                                   │   │
│  │  PLAN_C: 悲观情景 (25%)                                           │   │
│  │  ├── 条件: 趋势反转或深度回调                                      │   │
│  │  ├── 战略: 观望或做空，仓位-50%                                   │   │
│  │  └── 战术: 收紧止损，禁止抄底                                      │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  7.4 背离检测配置 ← 4维度监控                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  检测维度:                                                          │   │
│  │  ├── 价格背离: 价格与MA/成交量背离 (权重30%)                       │   │
│  │  ├── 情绪背离: FGI与价格/资金费率与价格背离 (权重25%)             │   │
│  │  ├── 宏观背离: 美元指数与BTC/美债收益率与BTC (权重25%)              │   │
│  │  └── 技术背离: RSI/MACD顶底背离 (权重20%)                          │   │
│  │                                                                   │   │
│  │  触发阈值:                                                          │   │
│  │  ├── minor (0.3-0.5): 标记观察                                    │   │
│  │  ├── moderate (0.5-0.7): 调整仓位50%                               │   │
│  │  └── major (0.7-1.0): 切换应急预案                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  7.5 战略参考库生成 ← Phase7核心输出                                   │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │  库文件: ~/.workbuddy/strategy-library/strategy_contingency_lib   │   │
│  │                                                                   │   │
│  │  包含:                                                            │   │
│  │  ├── black_swan_contingencies: 5个黑天鹅应急预案                 │   │
│  │  ├── extreme_scenarios: 3个极端情景预案                           │   │
│  │  ├── probability_plans: 3个概率情景预案                           │   │
│  │  └── deviation_detection: 背离检测配置                           │   │
│  │                                                                   │   │
│  │  调用接口:                                                          │   │
│  │  └── 战术SKILL执行前读取，检查预案一致性                           │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 10.2 黑天鹅应急预案模板

```yaml
black_swan_contingencies:
  - contingency_id: "BS_001"
    name: "交易所系统性风险"
    category: "黑天鹅"
    severity: "CRITICAL"
    
    trigger_conditions:
      - type: "news"
        condition: "交易所被盗/暂停提现"
      - type: "price"
        condition: "BTC 1小时内下跌>15%"
    
    immediate_actions:
      - action: "立即平仓所有多头"
        priority: 1
      - action: "停止开新仓位"
        priority: 2
    
    recovery_plan:
      - "等待24-48小时观察"
      - "首笔建仓不超过正常仓位的25%"
      - "采用现货而非合约"
```

### 10.3 概率情景预案模板

```yaml
probability_plans:
  # PLAN_A: 基准情景 (50%)
  - plan_id: "PLAN_A"
    name: "基准情景"
    probability: 0.50
    
    strategic_response:
      primary_strategy: "保持当前战略指令"
      position_modifier: "维持不变"
    
    tactical_adjustments:
      entry_timing: "分批入场"
      stop_loss: "±3%"
      take_profit: "+6%"

  # PLAN_B: 乐观情景 (25%)
  - plan_id: "PLAN_B"
    name: "乐观情景"
    probability: 0.25
    
    trigger_signals:
      - "放量突破关键阻力"
      - "MA多头排列形成"
    
    strategic_response:
      primary_strategy: "趋势追踪"
      position_modifier: "+0.25"
      leverage_cap: "当前上限+1"
    
    tactical_adjustments:
      add_position: "金字塔加仓≤3次"
      trailing_stop: "启动"

  # PLAN_C: 悲观情景 (25%)
  - plan_id: "PLAN_C"
    name: "悲观情景"
    probability: 0.25
    
    trigger_signals:
      - "放量跌破关键支撑"
      - "MA死叉形成"
    
    strategic_response:
      primary_strategy: "观望或做空"
      position_modifier: "降低50%"
    
    tactical_adjustments:
      existing_long: "止损或追踪止损收紧至3%"
      new_short: "轻仓试探，止损3%"
```

### 10.4 战术SKILL调用协议

```yaml
tactical_interface:
  # 调用时机
  invoke_triggers:
    - trigger: "战略制定完成后"
      action: "加载完整预案库"
      
    - trigger: "市场状态发生重大变化"
      action: "检索对应应急预案"
      
    - trigger: "战术SKILL执行前"
      action: "检查预案一致性"
      
    - trigger: "连续信号背离≥3次"
      action: "触发应急预案审查"

  # 预案优先级
  priority_order:
    1: "黑天鹅应急预案 (最高优先级)"
    2: "极端情景预案"
    3: "概率情景预案"
    4: "当前战略指令 (基准)"

  # 背离响应
  deviation_response:
    minor: "通知战术SKILL观察"
    moderate: "战术SKILL自动调整仓位50%"
    major: "切换至对应应急预案"
```

### 10.5 背离检测配置

```yaml
deviation_detection:
  enabled: true
  check_interval: "每轮决策前"
  
  dimensions:
    - name: "价格背离"
      weight: 0.30
      indicators: ["价格与MA背离", "价格与成交量背离"]
      
    - name: "情绪背离"
      weight: 0.25
      indicators: ["FGI与价格背离", "资金费率与价格背离"]
      
    - name: "宏观背离"
      weight: 0.25
      indicators: ["美元指数与BTC", "美债收益率与BTC"]
      
    - name: "技术背离"
      weight: 0.20
      indicators: ["RSI顶底背离", "MACD背离"]

  thresholds:
    minor_deviation: 0.3
    moderate_deviation: 0.5
    major_deviation: 0.7
```

### 10.6 执行脚本

```python
# Phase 7 执行入口
from war_game_simulator import WarGameSimulator

simulator = WarGameSimulator()
results = simulator.simulate(
    current_price=74500,
    regime="BREAKOUT_PENDING",
    direction="UP",
    feature_vector={"position_modifier": 0.5, "leverage_cap": 2},
    primary_directive={"directive_bias": "LONG"}
)

# 保存到战略参考库
simulator.save_to_library(results)
```

**输出文件**:
- `~/.workbuddy/strategy-library/strategy_contingency_library.yaml` (应急预案库)
- `~/.workbuddy/strategy-library/war_game_archive/war_game_{timestamp}.json` (每次推演存档)

---

## 十点五、Phase 7.5: 宏观资产背离应急预案 (v2.7 新增 ⚖️)

> **核心**: 宏观资产与BTC发生背离时，需要独立的应急预案，防止相关性失效导致的策略失效
> **触发**: 宏观共振信号断裂、资产相关性突变、背离检测>0.5

### 10.7.1 背离应急预案模板

```yaml
macro_asset_divergence_contingencies:
  - contingency_id: "MD_001"
    name: "黄金-BTC相关性断裂"
    category: "宏观背离"
    severity: "HIGH"
    
    trigger_conditions:
      - type: "correlation_break"
        condition: "黄金与BTC同时段方向相反持续>4小时"
      - type: "price"
        condition: "黄金涨>2%但BTC跌>2%"
    
    immediate_actions:
      - action: "暂停基于黄金共振的做多策略"
        priority: 1
      - action: "检查是否有新的叙事驱动BTC独立行情"
        priority: 2
    
    recovery_plan:
      - "等待4-8小时观察相关性是否恢复"
      - "若相关性永久断裂，移除黄金共振信号权重"
      - "重新评估BTC独立驱动因素"

  - contingency_id: "MD_002"
    name: "原油-铜滞胀组合"
    category: "宏观背离"
    severity: "CRITICAL"
    
    trigger_conditions:
      - type: "macro_combination"
        condition: "原油涨>3% + 铜跌>2% (滞胀信号)"
    
    immediate_actions:
      - action: "减仓BTC≥50%"
        priority: 1
      - action: "考虑加仓黄金对冲"
        priority: 2
    
    recovery_plan:
      - "观察美联储政策反应"
      - "若滞胀确认，BTC可能面临长期调整"

  - contingency_id: "MD_003"
    name: "TSLA-COIN行业Beta失效"
    category: "行业背离"
    severity: "MODERATE"
    
    trigger_conditions:
      - type: "sector_beta_break"
        condition: "COIN跌>5%但BTC涨>2% (行业Beta断裂)"
    
    immediate_actions:
      - action: "BTC可能独立行情，不跟随COIN"
        priority: 1
      - action: "重新评估BTC独立叙事"
        priority: 2
```

### 10.7.2 背离应急响应流程

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Phase 7.5: 背离应急响应                              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  检测到背离信号 (divergence_detected = true):                           │
│                          ↓                                              │
│  Step 1: 背离确认 (等待4小时确认非噪音)                             │
│  ├── 是噪音 (4小时后相关性恢复) → 忽略，继续原策略                  │
│  └── 真背离 (持续>4小时) → 进入Step 2                          │
│                          ↓                                              │
│  Step 2: 严重性评估                                                   │
│  ├── minor (0.3-0.5): 调整仓位50%                                 │
│  ├── moderate (0.5-0.7): 调整仓位75% + 加强止损                   │
│  └── major (0.7-1.0): 切换至背离应急预案                        │
│                          ↓                                              │
│  Step 3: 叙事重构                                                     │
│  ├── 寻找BTC独立驱动因素                                          │
│  ├── 评估是否新叙事替代旧相关性                                   │
│  └── 更新战略指令中的宏观资产权重                                │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 10.7.3 背离预案调用接口

```yaml
divergence_interface:
  # 调用时机
  invoke_triggers:
    - trigger: "A6监控系统检测到背离"
      action: "加载对应背离应急预案"
      
    - trigger: "战略制定时(Phase 0.6)"
      action: "检查当前是否有活跃背离"
      
    - trigger: "战术执行中"
      action: "每4小时检查背离状态"
      
  # 预案优先级
  priority_order:
    1: "MD_001 (黄金-BTC断裂)"
    2: "MD_002 (滞胀组合)"
    3: "MD_003 (行业Beta失效)"
    
  # 背离恢复检测
  recovery_detection:
    monitor_hours: 24
    recovery_threshold: "相关性恢复>0.5持续8小时"
    action_on_recovery: "移除背离应急预案，恢复原策略"
```

**输出文件**:
- `~/.workbuddy/strategy-library/macro_divergence_contingency.yaml` (背离应急预案库)
- `~/.workbuddy/strategy-library/divergence_archive/divergence_{timestamp}.json` (每次背离存档)

---

## 十一、Phase 8: 战略顾问评审 (v2.6 更新) ← v2.6与SKILL版本对齐

> **⚠️ 宪法强制**: A3战略制定完成后必须召唤顾问评审，评审结论是进入A4/A5的前置条件。
>
> **⚠️ v2.6 架构变更**: 顾问评审从"异步分发-等待"改为 **内联同步调用**，使用 `advisor_direct_call` 模块。

### 11.1 调用方式（v2.6 新增）

```python
# 导入方式
import sys
sys.path.insert(0, str(Path.home() / ".workbuddy" / "advisor-team" / "shared"))
from advisor_direct_call import advisors_review

# A3 调用示例
result = advisors_review(
    consultation_id=f"A3-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    scene="STRATEGY_REVIEW",  # 战略评审场景
    required_advisors=["advisor-sc", "advisor-qt"],
    optional_advisors=["advisor-mr", "advisor-kb", "advisor-tr"],
    context={
        "strategy_directive": { ... },  # A3生成的战略指令
        "market_regime": "TREND/RANGE/BREAKOUT",
        "risk_assessment": { ... },
        "a1_review_verdict": "AGREE",  # A1评审结论
        "a2_review_verdict": "PARTIAL",  # A2评审结论
    },
    source="dream-strategy-designer"
)

verdict = result["summary"]["final_verdict"]   # AGREE→A4; DISAGREE→🔴BLOCKED
```

### 11.2 评审类型识别

| 评审类型 | 判断条件 | 顾问组合 |
|:---------|:---------|:---------|
| **战略可行性评审** | 战略指令与当前市场匹配度 | SC + QT |
| **风险合规评审** | 战略是否符合风控规则 | RM |
| **资源优化评审** | 仓位/工具配置合理性 | RP |

### 11.3 顾问评审召唤

**⚠️ v2.6: 使用 `advisor_direct_call.advisors_review()` 内联调用，不再使用异步分发。**

调用代码见 §11.1。scene 固定为 `STRATEGY_REVIEW`，required_advisors 固定为 `["advisor-sc", "advisor-qt"]`。

**输入给顾问的信息**:
```
A3战略指令摘要:
- 战略方向: [BUY/SELL/HOLD]
- 目标币种: [BTC/ETH/...]
- 交易工具: [挂单/网格/马丁/...]
- Regime匹配: [当前Regime]
- Phase7预案: [应急预案摘要]

请输出:
- verdict: AGREE/DISAGREE/PARTIAL/SKIP
- confidence: 0-100
- feasibility_score: 0-100
- recommendations: [具体建议]
- circuit_breakers: [熔断条件]
```

### 11.3 评审结论处理

- **verdict=AGREE/PARTIAL**: 报告标记🟢/🟡，A4/A5可执行
- **verdict=DISAGREE**: 报告标记🔴BLOCKED，阻断A4/A5执行
- **verdict=SKIP**: 报告标记⚪SKIP，继续但记录

### 11.4 评审约束

1. **必须评审**: Phase7完成 ≠ 流程完成，必须完成顾问评审才算结束
2. **战略+量化双视角**: 至少召唤SC和QT两个顾问
3. **熔断条件必须**: 每个评审必须包含 circuit_breakers
4. **内嵌不投递**: 评审结论直接追加到报告末尾的"## 顾问评审"章节


---

## 十二、完整执行流程 (A1→A8)

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Dream-Strategy-Designer 完整流程 (v2.3)              │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  A1: dream-strategy-research (周一 09:00) ─── Phase 5 顾问评审 (QT+RM)  │
│  └── 深度调研报告 + 顾问评审结论                                         │
│                          ↓                                              │
│  A2: dream-first-principles (周一 10:30) ─── Phase 8 顾问评审 (MR+TR) │
│  └── 第一性原理分析 + Regime分类 + 顾问评审结论                          │
│                          ↓                                              │
│  A3: dream-strategy-designer (周一 11:00)                              │
│  ├── Phase0: 战略调研                                                   │
│  ├── Phase1: 输入验证                                                   │
│  ├── Phase2: 特征蒸馏                                                   │
│  ├── Phase3: 历史模式匹配                                               │
│  ├── Phase4: 战略合成                                                   │
│  ├── Phase5: 战略记忆库更新                                             │
│  └── Phase6: 战略做梦                                                  │
│                          ↓                                              │
│  A4: dream-tactical-validator (周二 09:00)                             │
│  └── 战术沙盘推演 (验证)                                               │
│                          ↓                                              │
│  A5: dream-tactical-executor (周二 14:00)                              │
│  └── 战术执行 (读取Phase7预案)                                          │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**注意**: Phase7沙盘推演在Phase6之后、输出Phase3战略指令之前执行，其输出同时服务于：
1. 作为Phase3的补充输入（极端情景约束）
2. 作为战术SKILL的参考预案库


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将产物写入交易邮箱。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 战略制定部 (A3) |
| **目标邮箱** | 交易邮箱 (trading) — 统一路径 |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **投递方式** | 直接写入Markdown文件到指定目录 |
| **文件名格式** | `a3_strategy_{YYYYMMDD}_{HHMM}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 + 前端产物中心（`artifact-alignment-manager` SKILL §一） |

> **已废弃**: 调研部邮箱(research/)不再使用。所有A系列产物统一投递到交易邮箱 trading/。

> **顾问评审内嵌**: Phase 8顾问评审结论直接追加到战略指令报告末尾的"## 顾问评审"章节，不单独投递。

### 投递工作流

```
Phase 0-7: A3战略制定执行
    ↓
Phase 8: 顾问评审 (SC + QT)
    ↓
投递: A3战略指令 → 交易邮箱 (trading/)  ← 统一路径
    ↓
流程完成
```


> **前端产物center文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "产物标题"
> department: trading
> chain_phase: A3
> date: "YYYY-MM-DDTHH:MM:SS"
> type: strategy
> status: completed
> tags: "a3 a3 推演"
> by_a_phase: A3
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单
- [ ] 文件写入 `reports/trading/` 目录
- [ ] 文件名符合 `a3_strategy_{YYYYMMDD}_{HHMM}.md` 格式
- [ ] 包含完整 YAML frontmatter (chain_phase: A3, department: trading, date)
- [ ] 投递后通过 `ls reports/trading/a3_*` 验证文件存在

### 代码入口

- **交易邮箱**: 直接写入Markdown文件到 `~/.workbuddy/skills/boss-secretary/reports/trading/`
