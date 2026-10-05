# DreamOS 意图识别架构（统一文档）

> **版本**: v1.0 | **更新日期**: 2026-10-05
> **定位**: 意图识别子系统的唯一事实源（SSoT），覆盖后端四层链路、前端意图识别、意图体系映射、训练闭环与 API 接口。
> **替代**: 本文件整合 `intent-recognition-engine-design.md`(v4.0)、`intent-recognition-spec/` 下的 intent-taxonomy.md / system_prompt.md，以及 30-真实环境交互系统 的训练闭环设计。

---

## 1. 概述与设计原则

### 1.1 定位

意图识别是 DreamOS S 层（感知层）的核心能力，负责将用户的自然语言输入转化为**结构化意图**，驱动 A 层（编排层）选择正确的执行链路。

### 1.2 设计原则（对标传统金融 + AI 训练最佳实践）

| 原则 | 说明 | 对标实践 |
|------|------|---------|
| **渐进式降级** | 零 Token 规则 → 动态权重 → jev 校验 → LLM，逐层兜底 | 金融语义查询的 rule→ML→LLM 渐进式分类 [DataNinjago] |
| **意图 vs 操作分离** | 意图描述用户目标，操作描述完成目标的动作 | 金融语义查询 "intent: broad objective; semantic operations: actions" |
| **置信度驱动** | 每层输出置信度，低于阈值触发下一层 | Capital One 的 LLM 蒸馏意图标签 + 置信度门控 |
| **FAIL-OPEN** | 任何层异常时降级而非崩溃 | 生产级金融系统的弹性设计 |
| **可解释性** | 每层输出 rationale，便于审计 | 金融合规要求的可解释性 |
| **持续学习** | 识别结果 → 样本 → 贝叶斯权重更新 → eval 门 | DeFi TIM 框架的认知评估器闭环 [arXiv:2511.15456] |

### 1.3 整体架构图

```
用户输入 (自然语言)
      │
      ▼
┌─────────────────────────────────────────────┐
│            后端 IntentEngine                  │
│                                              │
│  L1 RuleBasedRecognizer   (level=local, 0 Token) │
│      ├─ 市场数据打分 (EMA/RSI/ADX/vol_ratio)    │
│      ├─ NLP 关键词匹配                          │
│      └─ A系列深度分析短路                        │
│                                              │
│  L2 DynamicIntentRecognizer (level=hybrid, 0 Token) │
│      └─ 贝叶斯权重 + 自定义意图注册               │
│                                              │
│  L3 IntentEvaluatorAgent (jev/laya)          │
│      ├─ jev choice 重分类                      │
│      └─ jev noul 正确性校验                     │
│                                              │
│  L4 LLMBasedRecognizer    (level=llm, ~370 Token) │
│      └─ DeepSeek/Qwen 深度意图识别               │
│                                              │
│  ── 复杂度分级 T0-T3 (零 Token) ──             │
│  ── Token 预算管理 ──                           │
└─────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────┐
│            前端 FallbackEngine                │
│  (LLM 离线时的保障层，与后端互补)              │
│      ├─ 硬编码关键词规则                        │
│      ├─ 组合词匹配 (action+object)             │
│      ├─ 经验记忆库                              │
│      └─ LLM 调用 (DeepSeek)                    │
└─────────────────────────────────────────────┘
      │
      ▼
┌─────────────────────────────────────────────┐
│         SmartRouter (意图→执行链路)            │
│  market_query → S1_RESEARCH                   │
│  deep_analysis → S1→S2→S3→S4→S5              │
│  execute_trade → S1→S2→S3→S4→S5 (PRO only)    │
└─────────────────────────────────────────────┘
```

---

## 2. 意图体系（三套体系与统一映射）

当前系统存在三套意图体系，分别服务于不同层级。本节明确定义三者及映射关系。

### 2.1 后端策略意图（IntentType，11 种）

**位置**: `dreamos/core/sense/types.py` → `IntentType`

这是后端 IntentEngine 实际使用的意图类型，分为两大类：

1. **通用用户意图**（5 种）— 由 L1 规则/L4 LLM 直接识别，覆盖用户交互全场景
2. **交易策略意图**（6 种）— 由市场数据打分或通用意图的子分类得出

#### 通用用户意图

| 意图 | 中文名 | 触发场景 | 推荐链路 |
|------|--------|---------|---------|
| `MARKET_QUERY` | 行情查询 | 价格/仓位/余额等数据点查询 | S0_DIRECT_ANSWER |
| `EXECUTE_TRADE` | 执行交易 | 开仓/平仓/加仓/减仓 | S1→S2→S3→S4→S5 |
| `STRATEGY_VERIFY` | 策略验证 | 回测/策略有效性/信号质量 | S2→S3→S4 |
| `SCENARIO_SIM` | 情景推演 | 假设/压力测试/极端行情 | S1→S2→S3→S4 |
| `SIMPLE_QA` | 简单问答 | 闲聊/概念解释/通用问答 | S0_DIRECT_ANSWER |

#### 交易策略意图

| 意图 | 中文名 | 触发场景 | 推荐链路 |
|------|--------|---------|---------|
| `TREND_FOLLOWING` | 趋势跟随 | 均线排列、24H 大幅波动、ADX>30 | C1→F2/F3→A2→A4→A5→A9 |
| `MEAN_REVERSION` | 均值回归 | RSI 超买超卖、偏离均线、低波动 | C1→F2/F3→A2→A4→A5→A9 |
| `FUNDAMENTAL_PLAY` | 基本面驱动 | 资金费率异常、新闻/资金流 | A1→F1→F5→A2→A4→A5→A9 |
| `BREAKOUT` | 突破 | 成交量放大、短期大幅波动、接近高低点 | C1→A2→C3→A4→A5→A9 |
| `KNOWLEDGE_MATCH` | 知识库匹配 | 历史模式命中 | C3→A4→A5→A9 |
| `DEEP_ANALYSIS` | 深度分析(A系列) | 显式 A0-A3 标记、"深度分析"等 | A_HERMES_SKILL |
| `UNCERTAIN` | 不确定 | 所有得分<0.25 或多意图接近 | C1→A1→A2→A4→A5→A9 |

**扩展机制**: 通过 `register_intent_type(type_id, definition)` 注册自定义意图，definition 包含 name/description/chain/priority/keywords。

### 2.2 对话意图分类（6×30，领域无关）

**位置**: `dreamos/core/sense/dialogue_intent/taxonomy.py`

这是一套**领域无关**的对话意图分类体系，面向通用对话理解，当前**未被 IntentEngine 集成**（待集成）。

#### 一级意图（6 大类）

| 一级意图 | 风险等级 | 默认能力路由 | 说明 |
|---------|---------|-------------|------|
| `query` | low | database | 查询类 |
| `analysis` | medium | trading_nodes | 分析类 |
| `trade` | high | trading_nodes | 交易类 |
| `strategy` | medium | trading_nodes | 策略类 |
| `risk` | medium | trading_nodes | 风控类 |
| `dialog` | low | direct_response | 对话管理类 |

#### 二级意图（30 种）

| 一级 | 二级意图 |
|------|---------|
| query | market_query, holding_query, order_query, account_query, market_overview |
| analysis | technical_analysis, holding_analysis, deep_analysis, three_screen_analysis, sector_analysis |
| trade | buy, add_position, sell, close_position, conditional_order, order_manage |
| strategy | stock_recommendation, factor_screen, strategy_design, strategy_optimization |
| risk | risk_assessment, risk_advice, alert_setup, portfolio_risk |
| dialog | confirm, cancel, modify, repeat, clarify, chitchat |

### 2.3 前端意图（15 种）

**位置**: `3.1-FRONTEND/src/lib/intent/fallback-engine.ts` → `IntentType`

前端 FallbackEngine 使用的意图类型，覆盖**用户交互全场景**。

| 意图 | 说明 | 触发关键词示例 |
|------|------|--------------|
| `market_query` | 行情查询 | 行情, 价格, 现价, 多少, 报价 |
| `deep_analysis` | 深度分析 | 分析+趋势/走势, 深度分析, 技术分析 |
| `scenario_sim` | 情景推演 | 情景, 假设, 如果, 推演, 压力测试 |
| `strategy_verify` | 策略验证 | 验证+策略, 回测, 策略有效性 |
| `execute_trade` | 执行交易 | 开仓, 买入, 卖出, 做多, 做空 |
| `simple_qa` | 简单问答 | (默认兜底) |
| `command` | 命令 | /行情, /分析, /开仓 等斜杠命令 |
| `system_config` | 系统配置 | 设置, 配置 |
| `credits_query` | 积分查询 | 积分, 额度, 余额 |
| `artifact_query` | 知识库查询 | 查找, 搜索知识库 |
| `risk_alert_response` | 风险告警响应 | 风险, 预警 |
| `triple_chain` | 三链全流程 | 全面规划, 完整策略, 交易策略 |
| `need_clarification` | 需要澄清 | (模糊时) |
| `clarification_result` | 澄清结果 | (用户选择后) |
| `developer` | 策略代码开发 | 策略代码, /策略 |

### 2.4 统一映射表

三套体系的映射关系（2026-10-05 P0 修复后，后端 IntentType 已扩展通用意图）：

| 用户输入示例 | 前端意图 | 后端 IntentType | 对话意图(6×30) | 执行链路 |
|------------|---------|----------------|--------------|---------|
| 查询以太坊价格 | market_query | **MARKET_QUERY** ✅ | query.market_query | S0_DIRECT_ANSWER |
| 分析比特币趋势 | deep_analysis | DEEP_ANALYSIS | analysis.deep_analysis | A_HERMES_SKILL |
| 帮我开仓做多BTC | execute_trade | **EXECUTE_TRADE** ✅ | trade.buy | S1→S2→S3→S4→S5 |
| 回测马丁策略 | strategy_verify | **STRATEGY_VERIFY** ✅ | strategy.strategy_design | S2→S3→S4 |
| 如果BTC跌到50000 | scenario_sim | **SCENARIO_SIM** ✅ | analysis.three_screen_analysis | S1→S2→S3→S4 |

> ✅ 表示后端 IntentType 已能精确表达该意图。P0 修复前这些请求会落 UNCERTAIN 或近似策略意图。

---

## 3. 四层识别链路

### 3.1 L1 规则识别器（RuleBasedRecognizer）

**位置**: `dreamos/core/sense/recognizers/rule_based.py`
**Level**: `local` | **Token**: 0 | **延迟**: <10ms

#### 3.1.1 短路规则（最高优先级）

A 系列深度分析显式标记 → 确定性路由，跳过 LLM 复判：

- 关键词: `深度分析, 深度调研, 深度报告, 调研报告, 战略分析, 战略研究, 矛盾论, 主要矛盾, 第一性原理, 六因子, a系列, a链`
- 编号: `A0/A1/A2/A3`（词边界匹配，避免误伤 MA200/a3 纸等）
- 输出: `DEEP_ANALYSIS`, confidence=0.88

#### 3.1.2 市场数据打分

基于技术指标对每种策略意图打分：

| 意图 | 打分因子 | 权重示例 |
|------|---------|---------|
| TREND_FOLLOWING | 均线排列(+0.30)、24H 涨跌幅(+0.25)、ADX(+0.15) | 最高 0.70 |
| MEAN_REVERSION | RSI 超买超卖(+0.30)、偏离 EMA(+0.20)、低波动(+0.12) | 最高 0.62 |
| FUNDAMENTAL_PLAY | 资金费率异常(+0.25)、regime=fund(+0.20) | 最高 0.45 |
| BREAKOUT | 成交量放大(+0.25)、4H 波动(+0.20)、接近高低点(+0.15) | 最高 0.60 |
| KNOWLEDGE_MATCH | regime 已知(+0.05) | 最高 0.05 |

#### 3.1.3 NLP 关键词匹配

从 `IntentType` 定义的 keywords 中匹配，权重 ×0.7。

#### 3.1.4 置信度计算

```
confidence = min(best_score * 0.7 + gap * 0.3, 0.95)
```
其中 `gap = top1_score - top2_score`（第一名与第二名的分差）。

- best_score < 0.25 → UNCERTAIN
- gap < 0.05 且有多个候选 → 需要澄清

### 3.2 L2 动态识别器（DynamicIntentRecognizer）

**位置**: `dreamos/core/sense/recognizers/dynamic.py`
**Level**: `hybrid` | **Token**: 0

> ✅ **已修复**: intent_engine.py 中 `rec.level in ("local", "hybrid")` 现在正确调用 dynamic 层。P0 修复前 `rec.level == "local"` 导致 L2 永不执行。

#### 功能

- 贝叶斯权重更新：基于历史识别准确率动态调整各意图权重
- 自定义意图注册：通过 `register_intent(type_id, definition)` 扩展
- 运行时权重持久化：`weights.json`

### 3.3 L3 意图评估器（IntentEvaluatorAgent / jev）

**位置**: `dreamos/core/sense/evaluators/intent_evaluator_agent.py`
**依赖**: `jev_fn`（TypeSafe System One）或 `laya_fn`（本地 System 1）

> ✅ **已集成**: intent_engine.py 实例化 `IntentEvaluatorAgent(jev_fn, laya_fn)`，在融合后调用 `evaluate()`。agent.py 通过 `_build_jev_fn()` 复用 DSH 的 `jev_judge.handle_jev_judge`，并通过 `_load_dsh_env()` 加载 `TYPESAFE_API_KEY`。

#### 工作流程

```
confidence < 0.65 (EVAL_TRIGGER_THRESHOLD)
    │
    ▼
1. recall 历史评估经验 (认知闭环)
    │
    ▼
2. jev choice 原语 → 重新分类意图
   jev noul 原语 → 校验原识别是否正确
    │
    ▼
3. 置信度调整:
   - jev choice == 原 intent → +0.1 * jev_confidence
   - jev choice != 原 intent 且 jev_conf >= 0.7 → -0.15, clarified_intent = jev choice
   - jev choice != 原 intent 且 jev_conf < 0.7 → -0.05
   - noul < 0.5 → -0.1
    │
    ▼
4. jev degraded → fallback laya → fallback 规则降级
```

#### 端到端验证示例

```
输入: "看看" (模糊)
  confidence=0.4 < 0.65 → 触发 jev
  jev: choice=UNCERTAIN(conf=1.00), noul=0.89
  original=UNCERTAIN(conf=0.40) → adjusted=0.50
```

### 3.4 L4 LLM 识别器（LLMBasedRecognizer）

**位置**: `dreamos/core/sense/recognizers/llm_based.py`
**Level**: `llm` | **Token**: ~370/次 | **延迟**: 3-10s

#### 触发条件

```python
need_llm = (best_local is None) or (best_local.confidence < 0.55)
```

#### System Prompt 意图类型

当前 LLM system prompt 定义了 11 种意图（与 IntentType 对齐），分为两大类：

```
【通用用户意图】
  MARKET_QUERY / EXECUTE_TRADE / STRATEGY_VERIFY / SCENARIO_SIM / SIMPLE_QA
【交易策略意图】
  TREND_FOLLOWING / MEAN_REVERSION / FUNDAMENTAL_PLAY /
  BREAKOUT / KNOWLEDGE_MATCH / DEEP_ANALYSIS / UNCERTAIN
```

判断优先级：
1. 显式交易动词 → EXECUTE_TRADE
2. 纯数据查询 → MARKET_QUERY
3. 回测/验证 → STRATEGY_VERIFY
4. 假设/推演 → SCENARIO_SIM
5. 深度分析标记 → DEEP_ANALYSIS
6. 市场数据打分 → 策略意图
7. 无法确定 → UNCERTAIN

#### 输出格式

```json
{
  "intent": "DEEP_ANALYSIS",
  "confidence": 0.85,
  "reasoning": "用户要求分析比特币趋势，属于深度分析任务"
}
```

### 3.5 结果融合

**位置**: `intent_engine.py` → `_fuse_results()`

融合策略：
1. 取所有有效结果中置信度最高的
2. 如果 LLM 结果置信度 > 规则结果，优先 LLM
3. 如果规则结果置信度 >= 0.85 且 LLM 结果不同，保留规则结果（高置信规则优先）

### 3.6 澄清机制

当 `final.confidence < 0.55 (clarify_threshold)` 时：
- `clarify_needed = True`
- `clarify_question`: "当前对「{意图名}」的置信度为 {X}%，是否需要进一步确认？"
- `clarify_options`: ["确认", "重新识别"]

---

## 4. 复杂度分级（T0-T3）

**位置**: `dreamos/core/sense/complexity_classifier.py`
**Token**: 0 | **延迟**: <5ms

| 档位 | 名称 | 编排建议 | 触发条件 |
|------|------|---------|---------|
| T0 | 简单查询 | 零编排直答 (≤2s) | 查询词 + 无决策动词 + 无分析词 + ≤30字符 |
| T1 | 单域问题 | phase=1 起步，可深化 | 默认档 |
| T2 | 多域/战略 | 完整多链编排 | 战略触发词 或 显式提及≥2个领域 |
| T3 | 深度研究 | 委托 Harness A 系列 | DEEP_ANALYSIS 意图 或 A0-A3 触发词 |

**示例**:
- "BTC 多少钱" → T0
- "BTC 现在能做多吗" → T1
- "综合评估本周行情并制定策略" → T2
- "对这波回调做深度分析" → T3

---

## 5. Token 预算管理

**位置**: `dreamos/core/sense/token_budget.py`

### 5.1 预算档位

| 模式 | 总预算 | sense 层(10%) | 说明 |
|------|--------|--------------|------|
| `lean` | 3,000 | 300 | 精简模式 |
| `standard` | 6,000 | 600 | 标准模式（默认） |
| `full` | 10,000 | 1,000 | 完整 LLM 链路 |

> 未识别的 mode 回退到 standard（6,000）。

### 5.2 降级策略

| 预算水位（remaining_ratio） | 等级 | 行为 |
|---------------------------|------|------|
| ratio ≥ 0.6 | HEALTHY | 正常调用 LLM |
| 0.4 ≤ ratio < 0.6 | WARNING | 限制非必要 LLM |
| 0.2 ≤ ratio < 0.4 | LOW | 仅关键 LLM |
| 0.05 ≤ ratio < 0.2 | CRITICAL | 禁用 LLM，降级规则 |
| ratio < 0.05 | EXHAUSTED | 建议切换经典指标系统 |

> ✅ **已修复**: token_budget 默认 `enabled=False`，所有方法放行（can_afford=True、consume 不扣除、should_degrade_llm=False）。分析类任务可能较长，预算耗尽会导致 LLM 被跳过，故默认关闭。如需启用预算控制，显式传 `enabled=True`。

---

## 6. 前端意图识别与路由

### 6.1 FallbackEngine（三层降级）

**位置**: `3.1-FRONTEND/src/lib/intent/fallback-engine.ts`

```
用户输入
  │
  ├─ Step 0.1: 组合词匹配 (action+object)
  │    ├─ strategy_verify: 验证/测试 + 策略/回测
  │    └─ deep_analysis: 分析/研判 + 趋势/走势/后市
  │
  ├─ Step 0: 硬编码关键词规则 (HARDCODED_INTENT_RULES)
  │
  ├─ Step 1: 经验记忆库匹配 (intent-memory.ts)
  │
  ├─ Step 2: LLM 调用 (DeepSeek)
  │
  └─ Step 3: 默认兜底 (simple_qa)
```

### 6.2 追问检测

短消息 + 追问词（为什么/原因/详细/如何/还能/然后）→ 延续上一轮意图。

### 6.3 SmartRouter（意图→执行链路）

**位置**: `3.1-FRONTEND/src/lib/intent/smart-router.ts`

核心映射：

| 意图 | FREE 链 | PRO 完整链 | 需确认 |
|------|---------|-----------|--------|
| market_query | S1_RESEARCH | S1_RESEARCH | 否 |
| deep_analysis | S1,S2 | S1→S5 | 是 |
| scenario_sim | S1,S2 | S1→S4 | 是 |
| strategy_verify | S2,S3 | S2→S4 | 是 |
| execute_trade | (PRO only) | S1→S5 | 是 |
| simple_qa | S0_DIRECT_ANSWER | S0_DIRECT_ANSWER | 否 |

### 6.4 IntentClarificationEngine（多问后做）

**位置**: `3.1-FRONTEND/src/lib/planner/intent-clarification-engine.ts`

借鉴 Claude Code Superpower 的 "多问后做" 模式：
1. 评估意图模糊度（置信度、实体缺失、消息长度、多解读）
2. 模糊 → 生成澄清问题（LLM 驱动，one-at-a-time，多选题优先）
3. 用户回答后收敛，重复直到清晰或达最大轮次（3 轮）

---

## 7. API 接口

### 7.1 POST /api/v1/intent（完整链路）

**位置**: `dreamos/docs/API_SPEC.md`

**请求**:
```json
{
  "user_message": "分析比特币趋势",
  "symbol": "BTC-USDT",
  "market": { "price": 67000, "rsi14": 55, ... },
  "budget_mode": "full"
}
```

**响应**:
```json
{
  "intent_type": "DEEP_ANALYSIS",
  "confidence": 0.88,
  "recommended_chain": "A",
  "base_chain": ["A_HERMES_SKILL"],
  "recognizers_used": ["rule_based", "llm_based"],
  "level": "llm",
  "total_tokens": 378,
  "clarify_needed": false,
  "complexity_tier": "T3"
}
```

### 7.2 POST /api/intent/route（仅规则层，35 型正典）

**位置**: `30-真实环境交互系统` 调用

返回 35 型正典意图，映射到 7 型策略意图。

---

## 8. 训练与优化闭环

**位置**: `30-真实环境交互系统/training/`

### 8.1 闭环流程

```
真实用户请求
    │
    ▼
IntentSamplePipeline (生成 IntentSample)
    │  input: {user_query, market_features, scenario_id}
    │  gold: {gold_intent, gold_chain}
    ▼
┌─────────────────────────────┐
│  IntentTrainer.update_weights │  贝叶斯权重更新
│  (alpha/beta 递增)           │
└─────────────────────────────┘
    │
    ▼
weights.json (持久化)
    │
    ▼
EvalGate (eval 集验证)
    │  指标: 准确率 / 波动 / 零Token占比 / 路由命中率
    ▼
通过 → 部署 | 未通过 → 回滚
```

### 8.2 训练样本生成

`gen_p1_scenarios.py` 模板化生成 30 train + 10 eval × 3 意图 = 120 场景。

### 8.3 Eval 门指标

对齐行业标准（LUIS / Watson / Rasa DIET）：
- **准确率**: ≥ 85%
- **波动**: 跨场景标准差 ≤ 0.1
- **零 Token 占比**: ≥ 60%（规则层覆盖）
- **路由命中率**: ≥ 90%

---

## 9. 传统金融实践对标

| 维度 | 传统金融实践 | DreamOS 实现 | 差距 |
|------|------------|-------------|------|
| 意图粒度 | 广义目标 + 语义操作分离 | IntentType(5通用+6策略) + 对话意图(6×30) | 🟡 已对齐通用意图，6×30 待集成 |
| 分类方法 | rule→ML→DL→LLM 渐进式 | rule→dynamic→jev→LLM 四层 | ✅ 对齐 |
| 置信度门控 | 阈值触发下一层 | 0.55 触发 LLM，0.65 触发 jev | ✅ 对齐 |
| 可解释性 | rationale + 审计日志 | 每层输出 rationale | ✅ 对齐 |
| 持续学习 | 主动学习 + 人工标注 | 贝叶斯权重 + eval 门 | ✅ 对齐 |
| 多意图处理 | 多标签分类 + 优先级 | 单意图 + clarify | 🟡 待增强 |
| 领域适配 | FinBERT 等领域预训练 | 通用 LLM + 关键词 | 🟡 待增强 |

---

## 10. 已知问题与路线图

### 10.1 P0 已修复（2026-10-05）

| # | 问题 | 修复方案 | 验证 |
|---|------|---------|------|
| 1 | 后端 IntentType 缺少通用意图 | 扩展 5 种通用意图（MARKET_QUERY/EXECUTE_TRADE/STRATEGY_VERIFY/SCALARIO_SIM/SIMPLE_QA） | "查询以太坊价格"→MARKET_QUERY conf=0.97 ✅ |
| 2 | L2 DynamicIntentRecognizer 不被调用 | `rec.level == "local"` → `in ("local", "hybrid")` | dynamic 出现在 recognizers_used ✅ |
| 3 | L3 jev 层未集成 | intent_engine.py 注入 IntentEvaluatorAgent + agent.py `_build_jev_fn()` 复用 DSH jev_judge | jev choice=UNCERTAIN conf=1.0, noul=0.89 ✅ |
| 4 | token_budget 默认开启导致 LLM 耗尽 | 增加 `enabled` 参数，默认 `False` | can_afford(99999)=True ✅ |

### 10.2 P1 优化

| # | 问题 | 方案 |
|---|------|------|
| 1 | dialogue_intent(6×30) 未集成到 IntentEngine | 建立统一映射层，6×30 作为 canonical |
| 2 | 前端澄清 JSON 渲染为文本 | 修复 MessageItem 对 clarification 的渲染 |
| 3 | MARKET_QUERY 的 base_chain 未正确返回 S0 | 检查 _fuse_results 中 chain 覆盖逻辑 |

### 10.3 P2 增强

| # | 问题 | 方案 |
|---|------|------|
| 1 | 多意图检测 | 集成 dialogue_intent/multi_intent.py |
| 2 | 槽位提取 | 集成 dialogue_intent/slots.py |
| 3 | 领域预训练 | 引入 FinGPT/FinBERT 领域适配 |
| 4 | 主动学习 | 低置信度样本自动入训练集 |

---

## 11. 文件索引

### 11.1 后端核心

| 文件 | 职责 |
|------|------|
| `dreamos/core/sense/intent_engine.py` | 四层链路编排 |
| `dreamos/core/sense/types.py` | IntentType(7种) + IntentResult |
| `dreamos/core/sense/recognizers/rule_based.py` | L1 规则识别器 |
| `dreamos/core/sense/recognizers/dynamic.py` | L2 动态识别器 |
| `dreamos/core/sense/recognizers/llm_based.py` | L4 LLM 识别器 |
| `dreamos/core/sense/recognizers/base.py` | 识别器基类 |
| `dreamos/core/sense/evaluators/intent_evaluator_agent.py` | L3 jev 评估器 |
| `dreamos/core/sense/token_budget.py` | Token 预算管理 |
| `dreamos/core/sense/complexity_classifier.py` | T0-T3 复杂度分级 |
| `dreamos/core/sense/dialogue_intent/taxonomy.py` | 6×30 对话意图体系 |
| `dreamos/core/sense/dialogue_intent/classifier.py` | 对话意图分类器 |
| `dreamos/core/sense/dialogue_intent/multi_intent.py` | 多意图检测 |
| `dreamos/core/sense/dialogue_intent/slots.py` | 槽位提取 |

### 11.2 前端核心

| 文件 | 职责 |
|------|------|
| `3.1-FRONTEND/src/lib/intent/fallback-engine.ts` | 前端意图识别（三层降级） |
| `3.1-FRONTEND/src/lib/intent/smart-router.ts` | 意图→执行链路路由 |
| `3.1-FRONTEND/src/lib/intent/intent-memory.ts` | 经验记忆库 |
| `3.1-FRONTEND/src/lib/planner/intent-clarification-engine.ts` | 多问后做澄清引擎 |

### 11.3 训练与测试

| 文件 | 职责 |
|------|------|
| `30-真实环境交互系统/training/eval_gate.py` | Eval 回归门 |
| `30-真实环境交互系统/training/gen_p1_scenarios.py` | 训练样本生成 |
| `30-真实环境交互系统/core/intent_sample_pipeline.py` | IntentSample 管道 |
| `1-ARCHITECTURE/SPEC-20261004-INTENT-TRAINING-LOOP-30-SYSTEM.md` | 训练闭环设计 |

### 11.4 API 文档

| 文件 | 职责 |
|------|------|
| `dreamos/docs/API_SPEC.md` | /api/v1/intent 接口 |

---

## 12. 参考文献

- [DataNinjago] AI-Native Financial Data Foundation (43): Intent Classification for Semantic Query — 意图分类的 rule→ML→LLM 渐进式方法
- [arXiv:2606.26277] From Clicks to Intent: LLM-Distilled Taxonomy for Financial Services — Capital One 的 LLM 蒸馏意图分类体系
- [arXiv:2511.15456] Know Your Intent: TIM Framework for DeFi User Transaction Intent Mining — 多视角 LLM Agent + 认知评估器闭环
- [arXiv:2510.10526] Integrating LLMs and RL for Sentiment-Driven Quantitative Trading — FinGPT 情感分类 + 置信度打分
