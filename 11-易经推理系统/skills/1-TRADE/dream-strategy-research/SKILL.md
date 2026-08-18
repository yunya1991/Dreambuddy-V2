---
name: dream-strategy-research
description: |
  🌐 深度调研 — 战略制定前的侦察兵
  在制定战略前，系统性地收集市场情报、档案数据、链上信号、宏观环境、宏观资产背景。
  触发词：深度调研、市场调研、情报收集、档案研究、宏观分析、链上数据、调研完成请顾问评审、宏观背景、宏观资产、黄金、原油、铜
license: Internal
version: 1.7.0
created: 2026-04-20
updated: 2026-04-29
---

## 【合规要求】⭐ v1.7 新增

### §合规 问题处理流程

> ⚠️ **合规约束**: 遇到任何问题必须按以下顺序处理：

```
遇到问题
    ↓
Step 1️⃣ 查FAQ
  → WORKSPACE/.workbuddy/faq/OKX_FAQ.md（OKX相关）
  → WORKSPACE/.workbuddy/faq/技术_FAQ.md（技术相关）
  → WORKSPACE/.workbuddy/faq/运营_FAQ.md（运营相关）
    ↓ 有解 → 执行 ✓
    ↓ 无解 → Step 2

Step 2️⃣ 查治理文档
  → ~/.workbuddy/skills/dream-governance-manager/governance_docs/
    ↓ 有解 → 执行 + 补充FAQ ✓
    ↓ 无解 → Step 3

Step 3️⃣ 联网搜索
  → 使用 tavily/agent-reach 搜索
    ↓ 有解 → 执行 + 归档经验 ✓
    ↓ 无解 → Step 4

Step 4️⃣ 自主分析
    ↓ 有解 → 执行 + 输出报告 + 归档 ✓
    ↓ 无解 → 升级处理
```

### §合规 常见问题索引

| 问题类型 | FAQ位置 | 备注 |
|:---|:---|:---|
| OKX API错误 | `faq/OKX_FAQ.md` | CLI命令/API签名 |
| 账户查询问题 | `faq/OKX_FAQ.md` | 权限/配置文件 |
| 技术实现问题 | `faq/技术_FAQ.md` | 脚本/工具问题 |
| 流程协作问题 | `faq/运营_FAQ.md` | 制度/规范问题 |
| 合规判定问题 | `dream-governance-manager/` | 治理文档 |

### §合规 违规处理

| 违规类型 | 判定条件 | 处罚 |
|:---|:---|:---|
| 跳步违规 | 未查FAQ直接联网/分析 | 记过一次 |
| FAQ缺失 | 问题存在但未查阅 | 警告 |
| 归档缺失 | 问题解决但未归档 | 记录 |

---

# 🌐 Dream-Strategy-Research: 深度调研部 (v1.7)

> **核心原则**: 调研是决策的基础，必须遵循"三角准则"，用正确的方法收集证据。

## 目标

1. **全面情报收集**: 收集市场全维度的情报数据
2. **档案研究**: 对接历史案例库，寻找相似情境
3. **宏观扫描**: 宏观环境、风险偏好、资金流向
4. **做梦产物集成**: 纳入潜意识分析洞察，补充被压制的信号
5. **输出结构化简报**: 为A2第一性原理分析提供弹药

---

## ⚠️ 三角准则（必须严格遵守）

> **写死为系统原则，不可绕过**

### 准则一：记忆调研
- **目的**: 调动系统内部记忆资产
- **方法**: 读取MEMORY.md、daily logs、episodes历史
- **重点**: 提取与当前行情相似的历史case
- **证据要求**: 必须引用具体episode_id和时间戳

### 准则二：历史类似行情调研
- **目的**: 寻找可参考的历史模式
- **方法**: 
  1. 档案中心搜索相似行情 (Archive Center)
  2. 外部搜索历史类似走势案例
- **评估维度**: 
  - 价格形态相似度
  - 宏观环境相似度
  - 时间周期相似度
- **输出**: 历史case_id + 相似度评分 + 最终结果

### 准则三：类似交易策略调研
- **目的**: 学习相似情境下的策略应对
- **方法**:
  1. 读取战略库(Strategy Library)类似战略
  2. 蒸馏部查找大师应对记录
  3. Lessons历史查找相关禁令/偏好
- **输出**: 策略模式 + 效果评估

### 准则四：当下市场主流观点调研
- **目的**: 理解市场共识，避免反向踏空
- **方法**:
  1. **主力工具**: Tavily搜索 (默认，写死)
  2. **补充工具**: Odaily (fallback，SSL超时~30%)
  3. 搜索范围: Twitter/X, Reddit, 新闻, 分析师报告
- **评估维度**:
  - 多空比例
  - 主流机构观点
  - 关键阻力/支撑位共识
- **注意**: 必须标注来源可信度

### 准则五：Regime形态调研（新增v1.7）
- **目的**: 对接知识库Regime形态库，匹配当前市场状态
- **方法**: 读取 `research_modules/market_regime_research.md`
- **调研内容**:
  1. 查询 `.knowledge_base/1_regime_patterns/` 当前Regime
  2. 执行三屏检测 (Elder): S1周线/S2日线/S3小时线
  3. 匹配已有Regime形态，评估相似度
  4. 识别未覆盖的新形态
- **输出**: 
  - 技术Regime + 基本面Regime + 综合评分
  - 形态匹配结果 + 新形态建议
  - Regime变化信号列表

---

## 数据源优先级（写死经验）

```
主力搜集: Tavily (AI优化搜索，结构化结果)
     ↓
补充搜集: Odaily (链上/ETF数据，fallback)
     ↓
本地数据: OKX API (行情/资金费率/OI)
     ↓
历史数据: Archive Center / Episodes
```

### FAQ踩坑记录

> ⚠️ **Tavily优先原则**: 宏观/情绪/新闻搜索默认Tavily，Odaily仅作链上数据补充
> 
> ⚠️ **Odaily超时处理**: Odaily SSL超时率约30%，失败时自动切换Tavily
> 
> ⚠️ **数据新鲜度**: OKX行情>5分钟需重新拉取，宏观数据>1小时需重新搜索

---

## 做梦产物集成（核心调研资料 ⭐）

> 做梦部每日17:00产出潜意识分析（dream_brainstorm_daily_*.md），包含被压制的信号、反直觉洞察、噩梦场景。
> **做梦产物是调研报告的核心输入之一，与三角准则同级重要，不是"补充"而是"必须"。**

### 集成规则

1. **必须读取**: 每次调研必须读取最新的做梦产物，不可跳过
2. **必须引用**: 调研报告中必须明确引用做梦部洞察，标注来源文件名和日期
3. **必须评估**: 对做梦洞察进行可信度评估（高/中/低），说明采纳或排除理由
4. **无产物时标注**: 若最新做梦产物>24小时或不存在，必须在报告中标注"做梦产物缺失"

### 读取流程

```
1. 搜索最新产物: search_file("dream_brainstorm_daily_*.md") 或 search_file("dream_journal_*.md")
2. 读取完整内容（不要只看摘要）
3. 提取以下核心字段:
   ├── 被压制的信号 → additional_signals（系统忽视但可能有效的信号）
   ├── 噩梦场景 → risk_warnings（潜在极端风险场景）
   ├── 反直觉信号 → counter_intuitive_signals（需要反向思考的信号）
   ├── 决策优化点 → improvement_suggestions（系统级改进建议）
   ├── 矛盾图谱 → contradiction_map（系统内部逻辑冲突）
   └── 强迫性重复 → compulsive_patterns（系统反复犯错模式）
4. 交叉验证: 将做梦洞察与三角准则调研结果交叉验证
5. 矛盾标记: 做梦洞察与主流信号矛盾时，必须醒目标记"🔮矛盾信号"
```

### 做梦产物关键字段提取

| 做梦产物字段 | 纳入位置 | 优先级 | 说明 |
|:---|:---|:---:|:---|
| 被压制的信号 | `additional_signals` | ⭐高 | 系统忽视但可能有效的信号 |
| 噩梦场景 | `risk_warnings` | ⭐高 | 潜在极端风险场景 |
| 矛盾图谱 | `contradiction_analysis` | ⭐高 | 系统内部逻辑冲突（决策盲区） |
| 强迫性重复 | `pattern_warnings` | 中 | 系统反复犯错模式 |
| 反直觉信号 | `counter_intuitive_signals` | 中 | 需要反向思考的信号 |
| 决策优化点 | `improvement_suggestions` | 低 | 系统级改进建议 |

### 交叉验证规则

| 三角准则结果 | 做梦洞察 | 处理方式 |
|:---|:---|:---|
| 一致 | 一致 | 强信号，可信度↑ |
| 一致 | 矛盾 | ⚠️标记"梦境矛盾"，降低三角准则置信度 |
| 无明确结论 | 有洞察 | 🔮单独成章，注明"仅做梦产物" |
| 无产物 | — | ⚠️标注"做梦产物缺失，调研完整度降级" |

### 做梦产物路径
- 最新产物: `dream_brainstorm_daily_*.md`（workspace根目录）
- 历史产物: `dream_brainstorm_daily_*.md`（按日期搜索）
- 洞察传递: `~/.workbuddy/skills/boss-secretary/reports/dream_insight_*.md`

---

## 输入（建议字段）

| 字段 | 类型 | 说明 |
|:---|:---|:---|
| `inst_id` | string | 标的，默认 "BTC-USDT-SWAP" |
| `lookback_days` | number | 回溯天数，默认 7 |
| `focus_areas` | string[] | 重点领域，可选 ["price", "onchain", "macro", "sentiment"] |
| `archive_query` | string | 档案查询关键词（可选） |
| `incorporate_dream_insights` | boolean | 是否纳入做梦产物，默认 true |
| `macro_assets_background` | boolean | 是否纳入宏观资产背景，默认 true |

---

## 输出（必须结构化）

```json
{
  "research_report": {
    "summary": "一句话市场总结",
    "triangle_compliance": {
      "memory_research": {
        "completed": true,
        "episodes_found": 3,
        "key_findings": ["EP18类似场景...", "连续SKIP模式..."]
      },
      "historical_research": {
        "completed": true,
        "cases_found": 2,
        "similarity_scores": [0.75, 0.68],
        "outcomes": ["反弹成功", "继续下跌"]
      },
      "strategy_research": {
        "completed": true,
        "strategies_found": 1,
        "recommendations": ["sunzi_002适用"]
      },
      "current_sentiment": {
        "completed": true,
        "bullish_ratio": 0.65,
        "key_sources": ["Tavily", "Twitter"],
        "主流观点": "看涨但警惕回调"
      },
      "regime_research": {
        "completed": true,
        "technical_regime": "TREND_BULL",
        "fundamental_regime": "RATE_EASING",
        "composite_score": 45,
        "pattern_match": "RANGE_BOUND",
        "similarity": 0.75,
        "triple_screen": {
          "S1_week": "BULLISH",
          "S2_day": "BULLISH", 
          "S3_hour": "NEUTRAL"
        },
        "regime_change_signals": ["MA200突破"],
        "recommendations": ["继续使用TREND_BULL策略"]
      }
    },
    "market_state": {
      "price": 74389.5,
      "trend_direction": "BULL|BEAR|NEUTRAL_UP|NEUTRAL_DOWN|UNCLEAR",
      "trend_continuation": true,
      "resistance_minimum": "UP|DOWN|NEUTRAL",
      "rsi_1h": 58.3,
      "rsi_state": "oversold|overbought|neutral",
      "atr_pct": 0.25,
      "vol_regime": "high|low|unknown",
      "funding_rate": 0.0001,
      "oi_delta_pct": 1.2
    },
    "macro_snapshot": {
      "sentiment": "risk_on|risk_off|neutral",
      "risk_level": "0-3",
      "key_events": ["事件1", "事件2"]
    },
    "onchain_signals": {
      "whale_activity": "inflow|outflow|neutral",
      "etf_flow": "inflow|outflow|neutral",
      "prediction_bias": "bullish|bearish|neutral"
    },
    "macro_assets_background": {                           ← v1.6 新增 (宏观资产背景) ⚖️
      "enabled": true,
      "assets": [
        {
          "inst_id": "XAU-USDT-SWAP",
          "name": "黄金",
          "price": 2350.50,
          "change_1h_pct": 1.2,
          "trend_direction": "UP",
          "correlation_with_btc": "NEGATIVE",
          "signal_to_btc": "黄金涨→BTC可能面临避险资金流出"
        },
        {
          "inst_id": "CL-USDT-SWAP",
          "name": "原油",
          "price": 78.50,
          "change_1h_pct": -0.8,
          "trend_direction": "DOWN",
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
      "summary": "宏观资产背景摘要：黄金上涨显示避险情绪，BTC同步上涨需警惕通胀预期驱动"
    },
    "dream_insights": {
      "incorporated": true,
      "suppressed_signals": ["RSI超卖反弹信号被压制"],
      "nightmare_scenarios": ["霍尔木兹和平→BTC暴涨15%"],
      "counter_intuitive": ["ETF逆势买入是强信号"]
    },
    "archive_findings": [
      {
        "case_id": "string",
        "similarity_score": 0.75,
        "outcome": "string",
        "lessons": ["lesson1", "lesson2"]
      }
    ],
    "key_insights": ["洞察1", "洞察2", "洞察3"],
    "risk_warnings": ["风险警告1"],
    "signal_sufficiency": {                          ← v1.3 新增 ⭐
      "level": "HIGH|MODERATE|LOW",
      "directional_signals": ["ETF流入$19亿", "交易所储备7年低", "鲸鱼净增270K BTC"],
      "counter_signals": ["美伊冲突升级", "CPI反弹3.3%", "FGI急降30点"],
      "net_direction": "UP|DOWN|MIXED",
      "sufficiency_rationale": "为什么信号充分/不充分"
    },
    "action_pressure": {                             ← v1.3 新增 ⭐
      "consecutive_skip_days": 7,
      "pressure_level": "HIGH|MODERATE|LOW",
      "probe_recommendation": "建议向[方向]派出侦察队",
      "probe_conditions": ["条件1", "条件2"]
    },
    "contradiction_list": {                           ← v1.4 新增(A0集成) ⚖️
      "contradictions": [
        {
          "id": "CX_001",
          "dimension": "C1-C7",
          "name": "矛盾名称",
          "side_a": "多方信号",
          "side_b": "空方/反向信号",
          "strength_a": "HIGH|MODERATE|LOW",
          "strength_b": "HIGH|MODERATE|LOW",
          "dominance": "A|B|EQUAL",
          "evidence": {"a": ["证据1", "证据2"], "b": ["证据1"]},
          "c4_c5_note": "C4/C5矛盾标注（详见下方说明）"   ← v1.5 新增(Q1-P2修复) ⚖️
        }
      ],
      "total_contradictions": 3,
      "contradiction_intensity": "HIGH|MODERATE|LOW",
      "dream_contradictions_included": true,
      "c4_c5_note_standard": {                                           ← v1.5 新增(Q1-P2修复) ⚖️
        "description": "C4(时序矛盾)/C5(隐性与显性矛盾)维度无显著矛盾时的规范化标注规则",
        "annotation_rules": [
          {
            "condition": "C4维度存在显著时序矛盾",
            "note": "C4=存在(描述矛盾内容，如'短期技术超买 vs 长期趋势支撑')",
            "field_filled": true
          },
          {
            "condition": "C4维度无显著时序矛盾",
            "note": "C4=不显著(当前时间框架内各周期方向一致)",
            "field_filled": true
          },
          {
            "condition": "C5维度存在显性 vs 隐性矛盾",
            "note": "C5=存在(描述矛盾内容，如'显性信号看多但C7存在被压制空方')",
            "field_filled": true
          },
          {
            "condition": "C5维度无显性 vs 隐性矛盾",
            "note": "C5=不显著(所有矛盾均已在显性层面体现)",
            "field_filled": true
          }
        ],
        "format": "每个矛盾对象的c4_c5_note字段必须填写，标注'存在'或'不显著'及简要说明，不得留空"
      }
    }
  },
  "data_freshness": {
    "market_data_ts": "ISO时间戳",
    "macro_data_ts": "ISO时间戳",
    "onchain_data_ts": "ISO时间戳",
    "dream_insights_ts": "ISO时间戳"
  },
  "meta": {
    "research_id": "string",
    "researcher_version": "1.1.0",
    "triangle_compliance": true,
    "timestamp": "ISO时间戳"
  }
}
```

---

## ⚡ A0 强制调度门禁 (P0 Fix v1.6)

> **⚠️ 强制执行**: 本SKILL必须在执行第一阶段前首先调用A0矛盾论
> 
> **执行顺序不可跳过**: Phase 0 → Phase 1 → Phase 2 → ...

### Phase 0: A0矛盾论强制调用

**必须首先执行以下操作：**

```python
# Step 0.1: 调用A0矛盾论SKILL
use_skill("dream-contradiction-theory")

# Step 0.2: 将A0输出作为调研框架的输入约束
a0_contradiction_framework = {
    "primary_contradictions": "...",  # A0识别的主要矛盾
    "contrasting_pairs": [...],       # A0矛盾对列表
    "strategic_implications": "..."   # A0战略启示
}
```

**门禁检查清单（必须逐项确认）：**
- [ ] `use_skill("dream-contradiction-theory")` 已执行
- [ ] A0输出的主要矛盾已纳入调研框架
- [ ] Phase 3的A0矛盾发现使用A0的实际输出作为参照
- [ ] 报告中明确引用A0的矛盾分析结论

**违规处理**: 若跳过Phase 0，报告将标记为`a0_integration=FAILED`，A8将发出P0告警

---

## 执行流程

```
Phase 0: A0强制调度门禁 (新增 v1.6) ⚠️
├── [P0] use_skill("dream-contradiction-theory")
├── [P0] 获取A0矛盾框架作为调研输入约束
└── [P0] 门禁检查清单确认

Phase 1: 三角准则执行 (按顺序)
├── 准则一: 记忆调研 (读取MEMORY.md, episodes)
├── 准则二: 历史类似行情调研 (Archive Center + 外部搜索)
├── 准则三: 类似交易策略调研 (战略库 + 蒸馏部)
└── 准则四: 当下市场主流观点 (Tavily优先 > Odaily补充)

Phase 2: 核心数据收集 (并行执行)
├── OKX行情: K线/资金费率/OI
├── 技术指标: EMA/RSI/ATR
├── 链上数据: ETF + 鲸鱼活动
└── ⭐做梦产物: 读取最新brainstorm报告（核心输入，不可跳过）

Phase 2.5: 做梦产物交叉验证 ⭐
├── 将做梦洞察与三角准则结果交叉验证
├── 标记一致性/矛盾/独立洞察
└── 输出做梦产物可信度评估

Phase 3: 情报整合 (5min)
├── ⚖️ A0矛盾发现 (v1.4 新增，核心)
│   ├── 遍历7大矛盾维度(C1-C7): 资金面/情绪面/技术面/宏观/地缘/时序/隐性
│   ├── 对每个矛盾对标注: 对立面A、对立面B、证据数量×质量
│   ├── C7隐性矛盾必须纳入做梦部洞察
│   ├── 过滤无效矛盾(单方证据<1条)
│   └── 输出: contradiction_list (≥2个矛盾对)
├── 矛盾检测（含做梦洞察矛盾，现为A0的子步骤）
├── 一致性评分
├── 三角准则合规检查
├── 🔮做梦部洞察(独立核心章节，非补充)
├── ⭐ 信号充分性评估 (v1.3) — 基于A0矛盾清晰度增强
└── ⭐ 行动压力评估 (v1.3)

Phase 4: 报告生成 (3min)
├── 结构化简报
├── 关键洞察提炼(≤5条)
├── 风险警告(≤3条，含噩梦场景)
├── 🔮做梦部洞察(含可信度评估+交叉验证结论)
├── ⭐ 信号充分性评级 (v1.3 新增: HIGH/MODERATE/LOW)
└── ⭐ 行动压力评估 (v1.3 新增: 连续SKIP天数→压力级别)

Phase 5: 顾问评审 (新增 v1.2) ⭐
├── 识别评审类型（交易/风险/宏观/战略）
├── 选择顾问组合
├── 召唤顾问评审
├── 汇总评审结论
└── 写入待处理邮箱 (pending_tasks/inbox/)
```

---

## Phase 5: 顾问评审流程 (v1.4 更新)

> **⚠️ 宪法强制**: 调研完成后必须召唤顾问评审，评审结论是进入待处理邮箱的前置条件。
>
> **⚠️ v1.4 架构变更**: 顾问评审从"异步分发-等待"改为 **内联同步调用**，使用 `advisor_direct_call` 模块。

### 5.0 调用方式（v1.4 新增）

```python
# 导入方式
import sys
sys.path.insert(0, str(Path.home() / ".workbuddy" / "advisor-team" / "shared"))
from advisor_direct_call import advisors_review

# A1 调用示例
result = advisors_review(
    consultation_id=f"A1-{datetime.now().strftime('%Y%m%d-%H%M%S')}",
    scene="SIGNAL_ASSESSMENT",  # 信号评审场景
    required_advisors=["advisor-qt", "advisor-rm"],  # 按5.1识别的类型选择
    context={
        "market_state": { ... },   # A1调研的市场状态
        "key_signals": [ ... ],     # 核心信号列表
        "risk_warnings": [ ... ],   # 风险警告
        "suggestion": "LONG/SHORT/WAIT",  # A1建议方向
    },
    source="dream-strategy-research"
)

# 关键输出
verdict = result["summary"]["final_verdict"]        # AGREE/PARTIAL/DISAGREE
confidence = result["summary"]["avg_confidence"]     # 0-1
circuit_breakers = result["circuit_breakers"]        # 熔断条件列表
```

### 5.1 评审类型识别

根据调研内容自动识别评审类型：

| 评审类型 | 判断条件 | 顾问组合 |
|:---------|:---------|:---------|
| **交易信号评审** | 涉及 BUY/SELL 信号、价格突破、趋势判断 | QT + RM |
| **风险审查** | 涉及仓位调整、止损设置、杠杆变更 | RM + RP |
| **宏观决策** | 涉及政策解读、地缘政治、利率决策 | MR + TR |
| **战略推演** | 涉及多周期策略、资产配置、组合调整 | SC + QT + MR |
| **紧急响应** | 涉及市场突变、止损触发、熔断告警 | ER + RM + RP |

### 5.2 顾问评审召唤

**⚠️ v1.4: 使用 `advisor_direct_call.advisors_review()` 内联调用，不再使用异步分发。**

调用代码见 §5.0。根据 §5.1 识别的评审类型，映射到 `scene` 参数：

| 评审类型 | scene 参数 | required_advisors |
|:---------|:----------|:-----------------|
| 交易信号评审 | `SIGNAL_ASSESSMENT` | `["advisor-qt", "advisor-rm"]` |
| 风险审查 | `RISK_REVIEW` | `["advisor-rm", "advisor-rp"]` |
| 宏观决策 | `MACRO_ANALYSIS` | `["advisor-mr", "advisor-tr"]` |
| 战略推演 | `STRATEGY_REVIEW` | `["advisor-sc", "advisor-qt"]` |
| 紧急响应 | `EMERGENCY_RESPONSE` | `["advisor-er", "advisor-rm"]` |

**输入给顾问的信息**（通过 `context` 字典传入）:
```
调研报告摘要:
- 市场状态: [关键发现]
- 核心信号: [多空信号]
- 风险警告: [做梦产物+历史教训]
- 建议方向: [待确认]

请输出:
- verdict: AGREE/DISAGREE/PARTIAL/SKIP
- confidence: 0-100
- risk_level: LOW/MEDIUM/HIGH/CRITICAL
- recommendations: [具体建议]
- circuit_breakers: [熔断条件]
```

### 5.3 评审结论汇总

汇总所有顾问评审，生成统一评审报告：

```yaml
# 顾问评审汇总
advisor_review_summary:
  review_type: "交易信号评审"
  consultants_involved: ["ADVISOR-QT", "ADVISOR-RM"]
  overall_verdict: "PARTIAL"
  consensus_level: "HIGH"
  
  qt_review:
    verdict: "AGREE"
    confidence: 75
    reasoning: "信号评分达标，但需注意波动率风险"
    
  rm_review:
    verdict: "PARTIAL"
    confidence: 70
    reasoning: "风险可控但建议降低杠杆至2x"
    
  consolidated_recommendations:
    - action: "可执行信号"
      priority: P1
      conditions: ["止损设$93000", "杠杆≤2x"]
    - action: "不追高"
      priority: P2
      conditions: ["价格>$95000时停止入场"]

  circuit_breakers:
    - "BTC>$96000 → 全平"
    - "回撤>3% → 触发止损"
    - "持仓>24h → 强制检视"

  next_action: "输出到待处理邮箱，等待自动化修复"
```

### 5.4 待处理邮箱投递

**邮箱路径**: `~/.workbuddy/skills/boss-secretary/pending_tasks/inbox/`

**文件名格式**: `advisor_review_{YYYYMMDD}_{HHMMSS}.json`

**投递内容**:
```json
{
  "type": "advisor_review",
  "source": "dream-strategy-research",
  "research_report_ref": "a1_research_YYYYMMDD_HHMM.md",
  "review_type": "交易信号评审",
  "consultants": ["ADVISOR-QT", "ADVISOR-RM"],
  "verdict": "PARTIAL",
  "risk_level": "MEDIUM",
  "recommendations": [...],
  "circuit_breakers": [...],
  "timestamp": "ISO时间戳",
  "priority": "P1"
}
```

### 5.5 评审约束

1. **必须评审**: 调研完成 ≠ 流程完成，必须完成顾问评审才算结束
2. **至少一个顾问**: 每次调研至少召唤一个相关顾问
3. **熔断条件必须**: 每个评审必须包含 circuit_breakers
4. **待处理邮箱投递**: 评审结论必须写入 pending_tasks/inbox/

---

## 集成

| 集成点 | 方向 | SKILL | 说明 |
|:---|:---|:---|:---|
| **输出→A2** | → | `dream-first-principles` | 提供完整情报简报 + **信号充分性评级** + **contradiction_list** ⚖️ |
| **输出→A3** | → | `dream-strategy-designer` | 提供 **行动压力评估** ⭐ |
| **框架←** | ← | `dream-contradiction-theory` | A0矛盾论: Step1发现矛盾 ⚖️ |
| **输入←** | ← | `dream-oneirology` | 做梦产物洞察 |
| **数据源←** | ← | `technical-analyst` | 技术指标计算 |
| **数据源←** | ← | `tavily` | 宏观/情绪数据（主力） |
| **数据源←** | ← | `odaily` | 链上/ETF数据（补充） |
| **数据源←** | ← | `dream-archive-center` | 历史案例 |

---

## 信号充分性评估 (v1.3 新增 ⭐)

> **核心问题**: A1只负责"收集情报"，从不判断"情报是否足以支持行动"。
> 导致A2/A3每次都自己重新评估信号充分性，且默认"信号不足=等待"。
> **修复**: A1必须给出信号充分性评级，作为A2/A3的输入。

### 评估规则

```
信号充分性 = 方向性信号数量 × 信号强度 - 反向信号数量 × 信号强度

方向性信号 (正向/负向):
├── HIGH强度: ETF连续净流入>$5亿/日、RSI<25超卖、OI增仓+价格上涨
├── MODERATE强度: 鲸鱼净增仓、资金费率极端、链上储备新低
└── LOW强度: 社交媒体情绪、新闻语气、分析师观点

评级判定:
├── HIGH: 方向性信号≥3个 且 高强度信号≥1个 且 净方向一致
├── MODERATE: 方向性信号≥2个 或 1个高强度+1个中强度
└── LOW: 方向性信号≤1个 或 信号方向冲突
```

### 评级对A3的影响

| 信号充分性 | A3默认处理 | 仓位限制 |
|:-----------|:----------|:--------|
| HIGH | 正常战略合成 | 标准仓位 |
| MODERATE | 战略合成+缩小仓位 | 标准仓位×0.5 |
| LOW | **禁止输出WAIT**→输出PROBE | 最小试探仓位(10-20U) |

### 关键规则

1. **禁止全LOW**: 即使信号混乱，也要找到"最不差的方向"，给出MODERATE评级
2. **必须给方向**: `net_direction` 必须为 UP/DOWN/MIXED，不允许为空
3. **LOW≠等待**: LOW意味着"信号不足，但应小仓试探"，不是"信号不足，所以等待"

---

## 行动压力评估 (v1.3 新增 ⭐)

> **核心问题**: 系统连续SKIP无代价，空仓让"等待"变得舒适。
> **修复**: 引入行动压力机制，连续SKIP越久，行动压力越大，强制输出试探建议。

### 压力计算

```
连续SKIP天数 (consecutive_skip_days):
├── 查询方法: 搜索最近N天的reports/strategy/目录
│   ├── 读取最近的A3战略报告，统计连续WAIT/SKIP次数
│   └── 或读取memory中的连续SKIP记录
│
├── 1-3天: LOW压力 → 正常流程
├── 4-6天: MODERATE压力 → 建议A3输出PROBE
├── ≥7天: HIGH压力 → 强制A3输出PROBE，不允许WAIT
│   └── 此时触发L_EXISTING_001(连续SKIP→反顾问)教训
│
└── 每增加1天SKIP: 压力+1级
```

### 行动压力输出

```json
{
  "action_pressure": {
    "consecutive_skip_days": 7,
    "pressure_level": "HIGH",
    "probe_recommendation": "连续SKIP已达7天(L_EXISTING_001阈值)。建议向UP方向派出侦察队。",
    "probe_conditions": [
      "BTC守住$76,500支撑",
      "FGI不进一步恶化(<25)",
      "资金费率维持接近零轴"
    ]
  }
}
```

### 压力级别对A3的约束

| 压力级别 | A3约束 |
|:---------|:------|
| LOW | 无特殊约束，正常流程 |
| MODERATE | A3必须在报告中说明为什么选择WAIT而非PROBE |
| HIGH | **A3禁止输出directive_bias=WAIT，必须输出PROBE** |

---

## 约束

1. **三角准则强制**: 必须完成4个准则，否则报告不合规
2. **做梦产物强制**: 必须读取并引用做梦产物，缺失时标注降级
3. **数据源优先级**: Tavily为主，Odaily为辅，不可颠倒
4. **做梦产物交叉验证**: 与三角准则结果交叉验证，矛盾时必须标记
5. **⭐ 方向性判断强制 (v1.3 修复)**: A1必须给出信号充分性评级(HIGH/MODERATE/LOW)和
   net_direction(UP/DOWN/MIXED)。"不决策"指不直接下单，但必须给出方向性情报判断。
   禁止在情报充分时仍输出"方向不明"。
6. **可追溯**: 所有数据源必须标注来源和时间
7. **输出精简**: 关键洞察≤5条，风险警告≤3条
8. **⭐ 顾问评审强制 (v1.2)**: 调研完成 ≠ 流程完成，必须完成Phase 5顾问评审
9. **⭐ 待处理投递强制 (v1.2)**: 顾问评审结论必须写入待处理邮箱
10. **⭐ 信号充分性强制 (v1.3)**: 每次调研必须输出signal_sufficiency评级
11. **⭐ 行动压力强制 (v1.3)**: 每次调研必须输出action_pressure，≥7天连续SKIP时标记HIGH
12. **⚖️ 矛盾发现强制 (v1.4 新增)**: 每次调研必须按A0的7大矛盾维度(C1-C7)生成contradiction_list，≥2个矛盾对。C7隐性矛盾必须包含做梦部洞察。禁止输出"无矛盾"。

---

## FAQ踩坑记录

> ⚠️ **Tavily优先**: 宏观/情绪/新闻搜索默认Tavily，Odaily仅作链上数据补充
> ⚠️ **Odaily超时**: SSL超时率约30%，失败时自动切换Tavily
> ⚠️ **数据新鲜度**: OKX行情>5分钟需重新拉取
> ⚠️ **三角准则不可跳过**: 4个准则必须全部完成才能进入数据收集
> ⚠️ **做梦产物必须读取**: 调研报告需包含做梦洞察章节（核心输入，非补充）
> ⚠️ **做梦产物交叉验证**: 做梦洞察与三角准则矛盾时必须醒目标记，不可忽略
> ⚠️ **v1.3 信号充分性**: 必须评级HIGH/MODERATE/LOW，LOW≠等待而是小仓试探
> ⚠️ **v1.3 行动压力**: 连续SKIP≥7天→HIGH压力→A3禁止WAIT
> ⚠️ **v1.3 禁止方向不明**: 即使信号混乱也要给net_direction，至少MIXED
> ⚠️ **⚖️ v1.4 A0矛盾发现**: 必须按7大维度(C1-C7)生成contradiction_list，≥2个矛盾对，禁止"无矛盾"
> ⚠️ **⚖️ v1.4 C7隐性矛盾**: 必须包含做梦部洞察作为隐性矛盾信号
> ⚠️ **⚖️ v1.5 Q1-P2修复**: 每个矛盾对象必须填写c4_c5_note字段，C4/C5无显著矛盾时填写"不显著"，不得留空

---

## 调度

- **自动化**: `dream-strategy-research` (周一 09:00)
- **触发词**: "深度调研"、"市场调研"、"情报收集"
- **前置条件**: 做梦部已完成当日分析（17:00+）



---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将产物写入交易邮箱。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 深度调研部 (A1) |
| **目标邮箱** | 交易邮箱 (trading) — 统一路径 |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/trading/` |
| **投递方式** | 直接写入Markdown文件到指定目录 |
| **文件名格式** | `a1_research_{YYYYMMDD}_{HHMM}.md` |
| **frontmatter必须（完整7字段）** | 见下方YAML代码块 |
| **双通道投递** | 秘书邮箱 + 前端产物中心（`artifact-alignment-manager` SKILL §一） |

> **已废弃**: 调研部邮箱(research/)不再使用。所有A系列产物统一投递到交易邮箱 trading/。

### 投递工作流

```
Phase 1-4: 调研执行
    ↓
Phase 5: 顾问评审
    ↓
投递: 调研报告 → 交易邮箱 (trading/)  ← 统一路径
    ↓
流程完成
```


> **前端产物center文件frontmatter完整模板（双通道均需包含）**：
> ```yaml
> ---
> title: "产物标题"
> department: trading
> chain_phase: A1
> date: "YYYY-MM-DDTHH:MM:SS"
> type: research_report
> status: completed
> tags: "a1 a1 调研"
> by_a_phase: A1
> ---
> ```
> 完整规范参见 `artifact-alignment-manager` SKILL §三

### 投递检查清单
- [ ] 文件写入 `reports/trading/` 目录
- [ ] 文件名符合 `a1_research_{YYYYMMDD}_{HHMM}.md` 格式
- [ ] 包含完整 YAML frontmatter (chain_phase: A1, department: trading, date)
- [ ] 投递后通过 `ls reports/trading/a1_*` 验证文件存在


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


### 代码入口

- **调研报告投递**: 直接写入Markdown文件到 `~/.workbuddy/skills/boss-secretary/reports/trading/`
- **查看邮箱**: `ls -la ~/.workbuddy/skills/boss-secretary/reports/trading/`
