---
name: dream-signal-scoring-spec
description: 将多源输入（技术/宏观/记忆/团队评审）标准化为可复现的三维评分与冲突判定，输出结构化评分与理由码，供 dream-multiSkill 调度。
license: Internal
---

# Dream-Signal-Scoring-Spec: 信号评分协议与落地

## 目标
- 把"雷达图三维评分(0-10)"从主观描述升级为可计算、可复现、可审计的评分协议。
- 让 dream-multiSkill 只负责路由与汇总，不在主调度里隐式"拍分"。

## 输入（建议字段）
- 战略指令（来自 `dream-strategy-parser`） ⭐ 新增 P0
  - `strategy_directive.matched_strategy`: string | null
  - `strategy_directive.strategy_name`: string | null
  - `strategy_directive.match_confidence`: 0-1
  - `strategy_directive.directive_bias`: "LONG" | "SHORT" | "WAIT" | "REDUCE" | null
  - `strategy_directive.position_modifier`: 0.0-1.0
  - `strategy_directive.leverage_cap`: number | null
  - `strategy_directive.exclusion_conditions_checked`: string[]
  - `market_regime_classification.regime`: string
  - `market_regime_classification.confidence`: 0-1
- 技术面（来自本地指标或 `technical-analyst`）
  - `trend_4h`: { `ema20`: number, `ema60`: number, `ema_spread_pct`: number, `slope_ema20`: number }
  - `momentum_1h`: { `rsi14`: number, `rsi_divergence`: "bull" | "bear" | "none" }
  - `vol_15m`: { `atr14`: number, `atr_pct`: number }
- 衍生品（OKX）
  - `funding_rate`: number
  - `open_interest_delta_pct`: number
- 微观结构（OKX 市场数据）
  - `spread_bps`: number
  - `depth_1pct_usdt`: number
  - `orderbook_imbalance`: number
- 宏观与链上摘要（来自 `tavily`）
  - `macro_sentiment`: "risk_on" | "risk_off" | "neutral"
  - `headline_risk_level`: 0 | 1 | 2 | 3
- 新闻与事件摘要（来自 `odaily`，仅研究/解释）
  - `odaily_today_watch`: object | null
  - `odaily_market_analysis`: object | null
  - `odaily_tomorrow_events`: object | null
  - `odaily_prediction_whale`: object | null
  - `odaily_onchain_btc_whale`: object | null
  - `odaily_btc_eth_etf_flow`: object | null
  - `odaily_prediction_btc_eth`: object | null
- 记忆检索（来自 `ontology`）
  - `memory_warning`: boolean
  - `memory_tags`: string[]
- 团队评审（来自 `agent-team-orchestration`）
  - `team_alignment`: "aligned" | "mixed" | "conflict"

## 输出（必须结构化）
- `scores`
  - `trend_strength`: 0-10
  - `macro_tailwind`: 0-10
  - `onchain_signals`: 0-10
  - `prediction_market`: 0-10
  - `memory_safety`: 0-10
  - `etf_flow`: 0-10
  - `strategy_match`: 0-10  ⭐ 新增 P0 — 战略匹配度维度
  - `geopolitical_risk`: 0-10  ⭐ 新增 P1 (PROP_A8_005) — 地缘风险维度
  - `total`: 0-80  ⭐ 更新：7维→8维（原0-70→0-80）
- `direction`
  - `primary_bias`: "long" | "short" | "flat"
  - `confidence`: 0-1
- `expected_return`（用于门禁边际判定）
  - `expected_return_bps`: number
  - `expected_return_range_bps`: { `low`: number, `mid`: number, `high`: number }
- `gates`
  - `pass`: boolean
  - `reason_codes`: string[]
- `explanations`
  - `key_factors`: string[]
  - `contradictions`: string[]
- `validation`（可选）
  - `hit_ratio_rolling`: number | null
  - `profit_factor_rolling`: number | null
  - `stability_flag`: "stable" | "unstable" | "unknown"
- `regime`（可选）
  - `market_regime`: "trend" | "range" | "unknown"
  - `vol_regime`: "high" | "low" | "unknown"
  - `risk_regime`: "risk_on" | "risk_off" | "unknown"

## 评分口径（7维评分协议 v3.0 — 2026-04-20 战略维度升级）

> ⚠️ **严格命名约束**: 7个维度名是系统标准名，禁止使用别名。
> | 标准名 | 禁用别名 |
> |:---|:---|
> | `trend_strength` | technical_trend / tech_trend / trend |
> | `macro_tailwind` | macro_fund_tailwind / macro |
> | `onchain_signals` | onchain_signal / chain_signal |
> | `prediction_market` | predict_market / polymarket |
> | `memory_safety` | memory / memory_score |
> | `etf_flow` | etf_flows / etf_fund_flow |
> | `strategy_match` | strategy / strategy_score / strategic_fit |
> | `geopolitical_risk` | geo_risk / geopolitical / geo |

- 技术趋势强度 `trend_strength`（0-10）
  - 以 4H EMA20 与 EMA60 的相对位置、差值/斜率为主；1H RSI 作为过滤器与加分项。
  - 示例映射（可离散化实现）：
    - 4H：EMA20>EMA60 且差值扩大、EMA20 斜率>0 → 基础 6-8
    - 4H：EMA20<EMA60 且差值扩大、EMA20 斜率<0 → 基础 6-8（偏空）
    - 1H RSI：顺趋势在 45-65（多）/35-55（空）→ +1；出现背离与极端超买/超卖 → -1 至 -3
- 宏观顺风指数 `macro_tailwind`（0-10）
  - 以 `macro_sentiment` 与 `headline_risk_level` 为主，配合资金费率/持仓变化做拥挤度校正。
  - 示例：
    - risk_on 且 headline_risk_level<=1 → 6-8
    - risk_off 且 headline_risk_level>=2 → 2-4
    - 资金费率极端且 OI 同向飙升（拥挤）→ 按方向 -1 至 -3
- 链上数据信号 `onchain_signals`（0-10）
  - BTC 巨鲸流入流出、持仓集中度变化、大户持仓偏度。
  - 数据来源: Odaily 链上数据模块。
  - 数据不可用时标记 `DEGRADED`，默认给5分，理由码 `ONCHAIN_DATA_DEGRADED`。
- 预测市场维度 `prediction_market`（0-10）
  - BTC/ETH 预测市场方向概率、赔率变化速度与分歧度。
  - 数据来源: Polymarket API。
  - 数据不可用时标记 `DEGRADED`，默认给5分。
- ETF资金流 `etf_flow`（0-10）
  - BTC/ETH/SOL 现货ETF净流入/流出趋势。
  - 连续净流入(>3日) → 7-10；连续净流出 → 2-4；无数据 → 5(DEGRADED)。
  - 数据来源: Odaily ETF快讯 + SoSoValue。
  - 缓存策略: TTL 4小时 (顾问ADVISOR-SA仲裁)。
- 微观结构校正（新增）
  - 点差显著扩大、深度不足、订单簿失衡极端时，对总分增加 `SOFT_WARN_*` 降权（不直接替代硬门禁）。
- 记忆安全度 `memory_safety`（0-10）
  - `memory_warning=true` → 直接压制到 0-3，并输出对应 `Memory_Warning` 相关理由码。
  - 团队评审 `team_alignment=conflict` → -2 至 -4，且记录矛盾点。
- 战略匹配度 `strategy_match`（0-10）⭐ 新增 P0
  - 由 `dream-strategy-parser` 的 `strategy_directive` 驱动，衡量当前行情与战略库的匹配程度。
  - 评分映射：
    - `matched_strategy` 非空 且 `match_confidence` >= 0.8 → 8-10
    - `matched_strategy` 非空 且 `match_confidence` 0.5-0.8 → 5-7
    - `matched_strategy` 为空（无明确匹配） → 3-5（默认5）
    - `matched_strategy` 非空 但 `exclusion_conditions_checked` 非空（被排除条件命中） → 1-3
  - **方向影响**（影响 `primary_bias`）：
    - `directive_bias=LONG` → `primary_bias` 偏多 +1 置信度
    - `directive_bias=SHORT` → `primary_bias` 偏空 +1 置信度
    - `directive_bias=WAIT` → 输出 `SOFT_WARN_STRATEGY_DIRECTS_WAIT`
    - `directive_bias=REDUCE` → 输出 `DEGRADE_STRATEGY_REDUCED_RISK` + 强制降级
  - **总分更新**：`total = sum(8维)`, 范围 0-80（原 0-70）
  - **数据来源**：`dream-strategy-parser`（Step0），无输出时默认5分 + `DEGRADED` 标记
- 地缘风险度 `geopolitical_risk`（0-10）⭐ 新增 P1 (PROP_A8_005)
  - 与A0矛盾论C5地缘矛盾维度对齐，衡量地缘政治对BTC价格的影响。
  - 数据来源: Tavily搜索地缘新闻 + A2地缘政治分析 + A6宏观资产池监控。
  - 评分映射：
    - 地缘紧张(中东冲突升级/制裁加剧) + BTC避险买入 → 7-10 (利好BTC)
    - 地缘紧张 + BTC未涨(异常) → 3-5 (风险警告，可能与A0 C5矛盾)
    - 地缘缓和 + 风险偏好上升 → 6-8 (利好BTC)
    - 地缘中性/无重大事件 → 5 (默认)
  - **方向影响**（影响 `primary_bias`）：
    - 地缘紧张+避险买入 → `primary_bias` 偏多 +1 置信度
    - 地缘紧张+BTC异常不涨 → 输出 `SOFT_WARN_GEO_ANOMALY` + 降低置信度
    - 地缘缓和 → 风险偏好上升，`primary_bias` 偏多
  - **与A0 C5对齐规则**：
    - A0 C5地缘矛盾dominant_side=A(避险) 且 geopolitical_risk>6 → 一致，无冲突
    - A0 C5地缘矛盾dominant_side=A(避险) 但 geopolitical_risk<4 → 输出 `SOFT_WARN_TRIDENT_VS_A0_GEO`，标记三叉戟与A0冲突
    - 此规则系统性消除L_TRIDENT_VS_A0的人工裁定需求
  - **数据来源**：Tavily + A6宏观资产池，无数据时默认5分 + `DEGRADED` 标记

## Edge加速衰减检测 (EDGE-ACCEL-RESPONDER) 🔴 P0

> **落地来源**: DREAM-PROPOSAL-20260427-002 | rollback_plan_id: ROLLBACK-DREAM-PROPOSAL-20260427-002
> **落地时间**: 2026-04-27 20:30 | 验证状态: PASS (无硬性条件)

### 核心逻辑

检测Edge变化速率 `dEdge/dt`，在Edge加速恶化时触发分级响应，而非仅看Edge绝对值。

### 计算公式

```
dEdge/dt = (Edge_current - Edge_previous) / time_delta_hours
```

### 分级响应阈值

| 级别 | 条件 (4h窗口) | 动作 | 理由码 |
|:---|:---|:---|:---|
| **L1 预警** | dEdge/dt < -15/4h | 输出 `EDGE_ACCEL_WARN` | 标记但不阻断，提醒A4注意 |
| **L2 强制减仓** | dEdge/dt < -25/4h | 输出 `EDGE_ACCEL_FORCE_REDUCE` | 建议减仓50%，触发pretrade降级 |
| **L3 考虑全平** | dEdge/dt < -40/4h | 输出 `EDGE_ACCEL_LIQUIDATE` + `HARD_FAIL_EDGE_COLLAPSE` | 强制HOLD/SKIP，禁止新建仓 |

### 约束规则

- **与PTSD正交**: PTSD影响Edge绝对值(水平)，ACCEL影响响应速度(加速度)，互不干扰
- **与A6 Level 1.5互补**: A6检测方向突变(±30°)，ACCEL检测速度突变(加速度)，可联合触发
- **ATR自适应(建议)**: 后续可引入ATR归一化dEdge/dt，使阈值自适应市场波动率
- **最坏情况**: 多减一次仓，但在强负面市场中是正确行为(误触率~8%)

### 接入点

- 在每次signal-scoring执行时，如检测到dEdge/dt跨级，自动追加对应理由码到 `gates.reason_codes`
- L2/L3理由码同时写入 `DEGRADE_*` 或 `HARD_FAIL_*` 级别
- dEdge/dt值记录在 `explanations.key_factors` 中，便于episode回溯

---

## E[R] 估算口径（门禁输入）
- 目标：为 `Trade if E[R]-Costs > λ·Risk` 提供统一的 `expected_return_bps`。
- 最小可执行映射：
  - 使用 `scores.total`（8维80分制） + `validation.stability_flag` + `regime` + `strategy_directive` 做离散映射，得到 `expected_return_range_bps`。
  - 默认门禁使用 `mid` 作为 `expected_return_bps`；当 `stability_flag=unstable` 或 `directive_bias=REDUCE` 时降级到 `low`。
- 校准要求：
  - 采用滚动窗口回放更新映射表（样本内/样本外分离），至少记录窗口长度、更新时间、覆盖市场状态。
  - 若无可用校准窗口，必须输出 `ASSUMPTION_EXPECTED_RETURN_PROXY`。

## 冲突判定与理由码（可审计）
- `HARD_FAIL_*`：任何出现即 `pass=false`
  - `HARD_FAIL_MISSING_CORE_DATA`
  - `HARD_FAIL_MEMORY_WARNING_STRONG`
  - `HARD_FAIL_TEAM_CONFLICT`
  - `HARD_FAIL_STRATEGY_EXCLUDED` ⭐ 新增 P0 — 战略排除条件命中
  - `HARD_FAIL_NO_STRATEGY_EXTREME_REGIME` ⭐ 新增 P0 — 极端行情无战略匹配
  - `HARD_FAIL_EDGE_COLLAPSE` ⭐ 新增 P0 (DREAM-PROPOSAL-20260427-002) — Edge加速衰减L3，禁止新建仓
- `SOFT_WARN_*`：允许通过但降级
  - `SOFT_WARN_CROWDED_FUNDING_OI`
  - `SOFT_WARN_RSI_DIVERGENCE`
  - `SOFT_WARN_HEADLINE_RISK`
  - `SOFT_WARN_MICROSTRUCTURE_THIN`
  - `SOFT_WARN_REGIME_UNSTABLE`
  - `SOFT_WARN_STRATEGY_DIRECTS_WAIT` ⭐ 新增 P0 — 战略指令=WAIT但评分达标
  - `SOFT_WARN_GEO_ANOMALY` ⭐ 新增 P1 (PROP_A8_005) — 地缘紧张但BTC异常不涨
  - `SOFT_WARN_TRIDENT_VS_A0_GEO` ⭐ 新增 P1 (PROP_A8_005) — 三叉戟地缘评分与A0 C5矛盾冲突
  - `EDGE_ACCEL_WARN` ⭐ 新增 P0 (DREAM-PROPOSAL-20260427-002) — Edge加速衰减L1预警
  - `ASSUMPTION_EXPECTED_RETURN_PROXY`
- `DEGRADE_*`：允许通过但强制降级
  - `DEGRADE_STRATEGY_REDUCED_RISK` ⭐ 新增 P0 — 战略指令=REDUCE强制降级
  - `EDGE_ACCEL_FORCE_REDUCE` ⭐ 新增 P0 (DREAM-PROPOSAL-20260427-002) — Edge加速衰减L2，建议减仓50%

## 约束
- 不负责下单、不改参数、不做资金管理；只做评分协议与门禁判定（评分层面的）。
- 所有输出必须可序列化，便于 dream-multiSkill 记录审计字段与复盘。
- `odaily` 相关输入仅可用于 `explanations` 与研究注释，不得直接触发 `gates.pass=false` 或写入 `HARD_FAIL_*`。
- `odaily_onchain_btc_whale`、`odaily_btc_eth_etf_flow`、`odaily_prediction_btc_eth` 默认仅为解释增强字段，不直接进入硬门禁。

## Contract v0.1（最小审计契约）
- 输入建议包含：`trace_id`、`ts`、`inst_id`
- 输出必须包含：`gates.pass`、`gates.reason_codes`
- 若缺关键输入字段或出现无法判定冲突，必须 `gates.pass=false`，并输出 `HARD_FAIL_MISSING_CORE_DATA`

## Integration
- 上游：`tavily`/`odaily`/`ontology`/`technical-analyst`/`agent-team-orchestration`/`stock-analysis`/`dream-strategy-parser` ⭐ 新增 P0 的结构化摘要或本地指标
- 下游：`dream-risk-position-sizing`、`dream-pretrade-gatekeeper`、`learning-episode-writer`、`dream-posttrade-mrm-audit`
- 约定：方向与评分必须可复现，不允许将"叙事解释"混入可用于门禁的字段；`odaily`（含链上/ETF/预测市场扩展）默认仅 informational
- ⭐ 战略注入规则：`strategy_match` 维度必须从 `dream-strategy-parser` 输出中读取，不可硬编码；无战略解析器输出时默认5分 + `ASSUMPTION_STRATEGY_PROXY` 标记

## Fail-Closed
- 数据缺失、字段口径不一致、团队评审冲突不可化解时：直接 `gates.pass=false`


---

## 邮件投递规范（宪法§12强制）

> **⚠️ 宪法§12规定：本部门完成工作后，必须将工作总结写入指定邮箱目录。没有投递 = 工作未完成。**

### 投递配置

| 项目 | 值 |
|:---|:---|
| **部门名称** | 信号评分部 |
| **目标邮箱** | 秘书汇总邮箱 (secretary) |
| **邮箱路径** | `~/.workbuddy/skills/boss-secretary/reports/` |
| **投递方式** | 直接复制/写入Markdown文件到指定目录 |
| **投递命令** | 直接写入文件到 `~/.workbuddy/skills/boss-secretary/reports/<文件名>.md` |

### 投递工作流

```
1. 本部门完成工作（自动化任务/手动触发）
2. 整理工作总结（Markdown格式）
3. 确定优先级: P0(紧急)/P1(重要)/P2(观察)/P3(正常)
4. 执行投递命令
5. 确认邮件ID返回 → 投递完成
```

### 代码入口

- **投递方式**: 直接写入Markdown文件到指定邮箱目录
- **查看邮箱**: `ls ~/.workbuddy/skills/boss-secretary/reports/`

---

## 新增维度: 入场时机质量评分 (Timing Quality Score)

> **v2.3 回测落地 | P03提案验证通过**

### 评分因素

| 因素 | 权重 | 说明 |
|:-----|:----:|:-----|
| 相对位置 | 40% | 距离最近支撑/压力的百分比 |
| 确认度 | 30% | 是否等待回踩确认 |
| 波动率匹配 | 20% | 入场时机与ATR的关系 |
| 计划服从度 | 10% | 是否遵守A5建议的入场价 |

### 时机评分计算

```
timing_score = 
  relative_position * 0.4 +
  confirmation * 0.3 +
  volatility_match * 0.2 +
  plan_compliance * 0.1

时机等级:
- A (90-100): 回踩确认入场，波动率匹配，计划服从
- B (70-89): 部分确认入场，轻微偏离
- C (50-69): 追涨/追跌入场，明显偏离
- D (0-49): FOMO入场，严重偏离计划
```

### 综合评分调整

```
final_score = direction_score * 0.8 + timing_score * 0.2

# EP46案例:
- direction_score: 85 (方向正确)
- timing_score: 30 (D级时机)
- final_score: 74 (综合B级，但警告时机差)
```

### 与三叉戟整合

- 入场时机纳入"战术评分"分支
- 时机D级时触发额外风险提示
- 时机D级时降低目标仓位上限
- skip_rate超过30%时告警

### 落地参数 (回测验证)

```yaml
timing_score_weight: 0.2  # 综合评分权重
skip_rate_threshold: 0.30  # 超过30%告警
timing_level_D_filter: true  # D级强制SKIP
```

---

*信号评分协议更新 | v2.3 | 2026-04-22 P03提案落地*

---

## §Edge加速衰减响应机制 (EDGE-ACCEL-RESPONDER) 🔴 P0

> **落地来源**: DREAM-PROPOSAL-20260427-002 | rollback_plan_id: ROLLBACK-DREAM-PROPOSAL-20260427-002
> **落地时间**: 2026-04-27 20:40 | 验证状态: ✅ PASS
> **核心洞察**: SI断崖式崩溃(-67%) + Edge恶化(-180%) — 信号加速崩溃时系统响应不足

### 核心问题

"等信号稳定"综合症 — Edge从-10→-57仅用5小时，但系统仍按静态阈值响应，错过最佳减仓时机。

### 规则定义

```
EDGE_ACCEL_RULE:
  # 1. 计算Edge变化速率
  dEdge/dt = (Edge_current - Edge_previous) / time_delta_hours
  # 注意: 使用4h采样窗口的移动平均，消除噪声

  # 2. 分级响应 (基于| dEdge/dt |)
  if |dEdge/dt| >= 15/4h:
    → L1_WARNING ⚠️ (Edge加速衰减预警)
    → 输出: "Edge变化速率异常，建议密切关注"

  if |dEdge/dt| >= 25/4h:
    → L2_FORCE_REDUCE 🔁 (强制减仓50%)
    → 输出: "Edge加速恶化，强制执行减仓"
    → 动作: 当前仓位×50%，保留一半观察

  if |dEdge/dt| >= 40/4h:
    → L3_CLOSE_ALL 🚨 (全平+HARD_FAIL)
    → 输出: "Edge断崖式崩溃，强制全平"
    → 动作: 全部平仓，标记HARD_FAIL禁止开新仓位

  # 3. 特殊场景: 正向加速
  if dEdge/dt >= +20/4h (Edge快速好转):
    → 可选追加入仓(原仓位×30%)，需SI_Index同向确认
```

### 与现有Edge绝对值门禁的关系

| 门禁类型 | 检测对象 | 作用层级 | 关系 |
|:---|:---|:---|:---|
| 现有L_DISTILL_001 | Edge绝对值 | 评分层 | 独立判断 |
| 新增EDGE_ACCEL | dEdge/dt变化速率 | 响应层 | 加速触发 |

**关键区分**:
- PTSD 影响 Edge **水平**（-25分惩罚）
- ACCEL 检测 Edge **速度**（变化快慢）
- 两者正交，可联合触发更高级别告警

### 与A6 SIGNIFICANT_SHIFT的关系

| 机制 | 检测对象 | 触发条件 | 关系 |
|:---|:---|:---|:---|
| A6 Level 1.5 | 方向突变 | ±30°变化 | 互补 |
| ACCEL | 速度突变 | dEdge/dt阈值 | 联合触发更高级别 |

### 落地参数

```yaml
EDGE_ACCEL_PARAMS:
  # 检测参数
  dEdge_window_hours: 4  # 采样窗口
  dEdge_smoothing: "moving_avg"  # 移动平均消除噪声

  # L1阈值 (预警)
  L1_dEdge_threshold: 15  # /4h

  # L2阈值 (强制减仓)
  L2_dEdge_threshold: 25  # /4h
  L2_reduce_ratio: 0.5  # 减仓50%

  # L3阈值 (全平)
  L3_dEdge_threshold: 40  # /4h

  # 正向加速 (可选追加入仓)
  positive_accel_threshold: 20  # /4h
  positive_add_ratio: 0.3  # 原仓位×30%
  positive_confirmation: ["SI_Index >= +20", "Edge改善中"]
```

### 影子回放验证 (EP64)

```
回放场景: 4/27 Edge变化路径

BASELINE (无ACCEL):
  04-26 17:00  Edge=-10 → HOLD
  04-27 17:00  Edge=-28 → 首次升级响应
  04-27 18:39  Edge=-57 → 未到达决策点
  问题: 从-10到-57花了不到24h，仅在17:00首次升级

PATCHED (有ACCEL):
  04-27 14:00  dEdge/dt ≈ -4.5/h → L1预警 ⚠️
  04-27 16:00  dEdge/dt ≈ -9/h → L2减仓50% 🔁
  04-27 18:00  dEdge/dt ≈ -14.5/h → L3考虑全平 🔴
  结果: 在16:00即减仓，避免$90.5→$0.19的利润蒸发
```

### A6/A5执行要求

- A6每次检测到Edge变化时，必须计算dEdge/dt
- dEdge/dt超过L1阈值时，在briefing中输出预警
- dEdge/dt超过L2阈值时，触发A5自动减仓（无需等待确认）
- dEdge/dt超过L3阈值时，触发A5全平并标记HARD_FAIL
- 所有ACCEL触发事件必须记录在episode中

### 与P001(UPL-DECAY)的协同

```
P001 + P002 联合触发场景:
  1. P002 L2触发 → 减仓50%
  2. P001 UPL_DECAY_WARNING 触发 → 浮盈开始衰减警告
  3. P001 UPL_DECAY_ALERT 触发 → 移动TP到成本价
  4. P002 L3触发 → 全平，锁定剩余利润

协同效果:
  - 避免"等反弹"导致利润归零
  - 避免"等信号稳定"错过减仓时机
  - 双重保护: 速度层(P002) + 利润层(P001)
```

### ATR自适应阈值 (v2.1优化建议)

> 验证报告CV-006建议: 可引入ATR归一化dEdge/dt，使阈值自适应

```
OPTIONAL_ATR_ADAPTIVE:
  normalized_dEdge = dEdge / ATR_24h
  # ATR归一化后，高波动期阈值自动放宽
  # 低波动期阈值自动收紧
```

---

*信号评分协议更新 | v2.4 | 2026-04-27 P002提案落地 (EDGE-ACCEL-RESPONDER)*