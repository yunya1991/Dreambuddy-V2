# SPEC: 主要矛盾识别与最小阻力路径设计

> **状态：** Spec（待评审·v1）
> **创建：** 2026-09-11
> **前置：** [SPEC-AGI升级蓝图.md](./SPEC-AGI升级蓝图.md) §4.2.6 HJB/变分法求解器已落地
> **目标：** 修复 L3 路径计算层哲学断裂——从"所有矛盾平均化下求最小阻力"升级为"识别主要矛盾→主要矛盾下调制阻力→最小阻力路径"
> **硬约束：** FAIL-OPEN 铁律不可破坏；模块化开关默认关闭；不破坏现有 715 测试；HC-AGI-15/16/17 不可降级

---

## 一 · 问题陈述

### 1.1 哲学意图

> **最优路径 = 发现主要矛盾 → 主要矛盾下求阻力最小方向**

核心逻辑链（5 环节）：

```
① 多路径生成 = 多矛盾并行收集
      ↓
② 识别主要矛盾 = 矛盾间对抗→主导者
      ↓
③ 融入趋势延续性 = 延续性信号回流路径层
      ↓
④ 回测+小仓验证 = 验证结果回流确认矛盾
      ↓
⑤ 最小阻力计算 = 主要矛盾下调制 HJB lagrangian
```

### 1.2 现状差距（v1.5 代码考古）

| 环节 | 哲学要求 | 实现度 | 核心差距 | 代码位置 |
|:---|:---|:---:|:---|:---|
| ① 多路径=多矛盾 | 6 路径来源对应 6 类矛盾 | 85% | 路径并行收集，无对抗/共振分析 | [evolution_pipeline.py:_discover_paths](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py#L329-L560) |
| ② 识别主要矛盾 | 矛盾间对抗→主导者 | **30%** | **核心断裂**：独立评分取最高，非矛盾间比较识别主导者 | _select_optimal_path L562-L649 |
| ③ 趋势延续性 | 延续性信号回流路径层 | 40% | trend_strength/ADX 在数据层计算但未回流路径发现层 | resistance_vector.py / market_data |
| ④ 回测+小仓验证 | 验证结果回流确认矛盾 | 50% | ShadowRL/Counterfactual 验证后未回流闭环 | ShadowRLTrainer |
| ⑤ 最小阻力计算 | 主要矛盾内求阻力最小 | 70% | HJB lagrangian 未融入矛盾强度调制 | [hjb_solver.py:lagrangian](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/hjb_solver.py#L106-L148) |

**核心结论：** 数学算法层已完备（HJB PDE + 变分法 + 三级降级链），但哲学意图层存在核心断裂——当前是"所有矛盾平均化下求最小阻力"，不是"识别出的主要矛盾下求最小阻力"。

---

## 二 · 理论基础

### 2.1 矛盾论（毛泽东）— 主框架

来源：[2-KNOWLEDGE/3-THEORY/矛盾分析法.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/2-KNOWLEDGE/3-THEORY/矛盾分析法.md) A0 统一矛盾操作系统

**核心原理映射：**

| 原理 | 交易映射 | 本 SPEC 落地点 |
|:---|:---|:---|
| 主要矛盾 | 一个矛盾起主导作用，方向明确即可行动 | `_identify_primary_contradiction()` 输出 primary_direction |
| 矛盾主要方面 | 优势方即方向，量化力量对比 | 力量对比维度 `\|证据A×质量A - 证据B×质量B\|` |
| 矛盾转化 | 一定条件下相互转化 | 转化监控点 = 止损/止盈条件 |
| 重心原则 | 所有分析资源集中于主要矛盾 | 次要矛盾权重降至 0.3 以下 |

**8 大矛盾维度（C1-C8）→ 6 路径来源映射：**

| 矛盾维度 | 路径来源 | 对立面对应 |
|:---|:---|:---|
| C1 资金面 | BDSM（基本面估值） | ETF 流入/流出 ↔ OI 增/减仓 |
| C2 情绪面 | RegimeGate（趋势/网格） | FGI 贪婪 ↔ 恐惧 |
| C3 技术面 | BCRM2.0 | EMA 多头 ↔ 空头 |
| C4 宏观 | 战略层 | 降息/QE ↔ 加息/QT |
| C5 地缘 | （暂未接入） | — |
| C6 时序 | DeepReasoningEngine | 短期看多 ↔ 长期看空 |
| C7 隐性 | StrategySynthesizer | 被压制信号 ↔ 显性共识 |
| C8 宏观交叉 | L2 基因库 | 风险偏好 ↔ 避险 |

### 2.2 Wyckoff 三法则 — 供求/因果/量价

来源：Richard Wyckoff (~1900-1934)，三法则 + 四阶段

| 法则 | 核心 | 量化映射 |
|:---|:---|:---|
| **Law 1 Supply & Demand** | 价格=供需平衡，需求>供给→涨 | R_up/R_down 阻力向量（已实现） |
| **Law 2 Cause & Effect** | 累积期长度（cause）决定后续行情规模（effect） | `cause_score` = 累积期标准化时长 × 波动率收缩比 |
| **Law 3 Effort vs Result** | 成交量=努力，价格变动=结果，背离=机构行为 | `effort_result_ratio` = volume_change / price_change，背离检测 |

**四阶段识别（Accumulation → Markup → Distribution → Markdown）：**

| 阶段 | 特征 | 主要矛盾方向 |
|:---|:---|:---|
| Accumulation | 横盘+成交量萎缩+低点抬高 | 多方累积→LONG |
| Markup | 趋势上升+量增 | 多方主导→LONG |
| Distribution | 横盘+成交量萎缩+高点降低 | 空方派发→SHORT |
| Markdown | 趋势下降+量增 | 空方主导→SHORT |

### 2.3 Minervini SEPA — 趋势延续性 + VCP

来源：Mark Minervini《Trade Like a Stock Market Wizard》

**趋势模板（Stage 2 确认，8 条件全过）：**

```
1. 当前价 > 150日均线
2. 当前价 > 200日均线
3. 150日均线 > 200日均线
4. 200日均线上升 ≥ 22 个交易日
5. 50日均线 > 150日均线 AND 50日均线 > 200日均线
6. 当前价 > 50日均线
7. 当前价 ≥ 52周最低价 × 1.25
8. 当前价 ≤ 52周最高价 × 1.25（理想 ≤ 1.15）
```

**VCP（波动率收缩形态）量化规则：**

| 指标 | 规则 | 阈值 |
|:---|:---|:---|
| 收缩次数 | 最少 2 次，理想 3-4 次 | ≥2 |
| 收缩递减 | T2 ≤ 0.75×T1，T3 ≤ 0.75×T2 | ratio ≤ 0.75 |
| T1 深度 | 大盘股 8-35%，小盘股可达 50% | 0.08-0.50 |
| 成交量干涸 | 近 10 根 bar 均量 / 50日均量 | < 0.50（理想 <0.30） |
| 突破日量能 | 突破日量 / 50日均量 | ≥ 1.5x（理想 2x） |
| 枢轴点止损 | 最后收缩低点下方 1-2% | 5-8% 风险 |

---

## 三 · 设计目标

### 3.1 核心目标

**G1 修复哲学断裂**：在 _select_optimal_path 前插入 `_identify_primary_contradiction()` 步骤，从"独立评分取最高"升级为"矛盾间对抗→识别主导者"。

**G2 矛盾强度调制 lagrangian**：HJB 的 `lagrangian()` 接受矛盾强度调制，主要矛盾方向阻力降低，次要方向阻力升高。

**G3 趋势延续性回流**：趋势模板 + VCP 指标作为 `continuation_score` 字段回流路径发现层。

**G4 验证闭环**：小仓验证结果回流调整矛盾权重，形成"识别→验证→权重更新→再识别"闭环。

### 3.2 非目标（不做）

- 不改 CS 评分公式（CS = 0.4·d* + 0.3·ESS + 0.3·CBR）
- 不改 BCRM2.0/力向量决策条件
- 不改 HJB PDE 数值求解算法（只扩展 lagrangian 输入）
- 不新增并行矛盾辩论系统（精细管理而非辩论，遵循 SPEC-AGI §架构原则）

---

## 四 · 核心模块设计

### 4.1 模块架构

```
┌──────────────────────────────────────────────────────────────────┐
│  Phase 3.1: PrimaryContradictionIdentifier（新增）                │
│                                                                    │
│  输入: paths[] (6 类路径来源) + market_data + r_out                │
│                                                                    │
│  ┌────────────────┐  ┌────────────────┐  ┌────────────────┐      │
│  │ ① 共振检测      │  │ ② 冲突裁决      │  │ ③ 主导性评估    │      │
│  │ direction_conc │  │ conflict_matrix│  │ dominance_score │      │
│  └───────┬────────┘  └───────┬────────┘  └───────┬────────┘      │
│          └──────────────────┬┴──────────────────┘                │
│                              ▼                                     │
│          primary_contradiction = {                                 │
│            "dimension": "C3" | "C4" | ... ,                        │
│            "direction": "long" | "short",                          │
│            "strength": 0.0-1.0,        # 矛盾强度                  │
│            "confidence": 0.0-1.0,       # 主导置信度                │
│            "cause_score": float,        # Wyckoff 因果             │
│            "effort_result": float,      # Wyckoff 量价             │
│            "continuation_score": float,  # Minervini 趋势延续       │
│          }                                                          │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 3.2: 矛盾强度调制的 HJB lagrangian（扩展）                  │
│                                                                    │
│  lagrangian(price, action, r_vector, primary_contradiction):       │
│    if action 对齐 primary_direction:                               │
│      L = L_base × (1 - 0.3 × strength)    # 阻力降低                │
│    else:                                                           │
│      L = L_base × (1 + 0.5 × strength)    # 阻力升高                │
└──────────────────────────┬───────────────────────────────────────┘
                           │
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Phase 3.3: 趋势延续性回流（扩展 _discover_paths）                │
│                                                                    │
│  每个路径新增字段:                                                  │
│    continuation_score: TrendTemplate(8条件).score × VCP.score     │
│    cause_score: Wyckoff 累积期标准化时长                          │
│    effort_result_ratio: 量价背离检测                              │
└──────────────────────────────────────────────────────────────────┘
```

### 4.2 PrimaryContradictionIdentifier（新增模块）

**文件：** `dreambuddy_evolution/core/contradiction_identifier.py`

**职责：** 从 6 类候选路径中识别主要矛盾，输出矛盾强度与方向。

**核心方法：**

```python
class PrimaryContradictionIdentifier:
    """主要矛盾识别器.

    哲学: 矛盾论 §主要矛盾 + 矛盾主要方面
    输入: 6 类路径（对应 C1-C8 矛盾维度）
    输出: primary_contradiction dict
    """

    MIN_PATHS_FOR_ANALYSIS = 2  # 至少 2 路径才做矛盾分析
    RESONANCE_THRESHOLD = 0.6   # 共振阈值：≥60% 方向一致才算共振
    DOMINANCE_THRESHOLD = 0.55  # 主导阈值：力量对比 > 0.55 才算主导

    def identify(
        self,
        paths: list[dict],
        market_data: dict,
        r_out: dict,
    ) -> dict:
        """识别主要矛盾.

        三步法：
        1. 共振检测：多路径方向一致 → 矛盾强度高
        2. 冲突裁决：方向冲突时 → 4维评分法识别主导者
        3. 主导性评估：量化 dominance_score
        """
        if len(paths) < self.MIN_PATHS_FOR_ANALYSIS:
            return self._neutral_default()  # FAIL-OPEN

        # Step 1: 共振检测
        resonance = self._detect_resonance(paths)

        # Step 2: 冲突裁决（仅共振 < 阈值时）
        if resonance["score"] < self.RESONANCE_THRESHOLD:
            dominance = self._arbitrate_conflicts(paths, market_data, r_out)
        else:
            dominance = resonance  # 共振即主导

        # Step 3: 主导性评估
        primary = self._evaluate_dominance(dominance, paths, market_data)

        return primary
```

**三步法详述：**

#### Step 1: 共振检测 `_detect_resonance()`

```python
def _detect_resonance(self, paths: list[dict]) -> dict:
    """共振检测：多路径方向一致度.

    共振 = 多个矛盾维度指向同一方向
    """
    long_weight = sum(p["confidence"] for p in paths if p["direction"] == "long")
    short_weight = sum(p["confidence"] for p in paths if p["direction"] == "short")
    total_weight = long_weight + short_weight

    if total_weight == 0:
        return {"score": 0.0, "direction": "neutral", "strength": 0.0}

    # 方向占比 = 主要方面 / 总方面
    if long_weight >= short_weight:
        direction = "long"
        score = long_weight / total_weight
    else:
        direction = "short"
        score = short_weight / total_weight

    # strength = 矛盾主要方面占比（矛盾论§矛盾主要方面）
    strength = min(1.0, score * len(paths) / 4)  # 路径数越多共振越强

    return {"score": float(score), "direction": direction, "strength": float(strength)}
```

#### Step 2: 冲突裁决 `_arbitrate_conflicts()`

```python
def _arbitrate_conflicts(
    self,
    paths: list[dict],
    market_data: dict,
    r_out: dict,
) -> dict:
    """冲突裁决：4维评分法识别主导者.

    矛盾论 A0-IRON-2: 主要矛盾只有一个，4维评分法识别
    """
    long_paths = [p for p in paths if p["direction"] == "long"]
    short_paths = [p for p in paths if p["direction"] == "short"]

    # 4维评分（对齐矛盾分析法.md §三 Step2）
    long_score = self._score_side(long_paths, market_data, r_out)
    short_score = self._score_side(short_paths, market_data, r_out)

    # 力量对比维度
    power_diff = abs(long_score["total"] - short_score["total"])
    if long_score["total"] >= short_score["total"]:
        direction, winner_score = "long", long_score
    else:
        direction, winner_score = "short", short_score

    # 主导置信度 = 力量对比归一化
    total = long_score["total"] + short_score["total"]
    confidence = power_diff / total if total > 0 else 0.0

    return {
        "direction": direction,
        "confidence": float(min(1.0, confidence)),
        "strength": float(winner_score["power"]),
        "long_score": long_score,
        "short_score": short_score,
    }

def _score_side(self, side_paths, market_data, r_out) -> dict:
    """4维评分: 力量对比 + 时间紧迫性 + 证据一致性 + 市场影响权重."""
    # 力量对比
    power = sum(p["confidence"] * p.get("expected_return", 0) for p in side_paths)
    # 时间紧迫性（短期信号 > 长期）
    time_urgency = sum(1.0 if p["source"] in ("bcrm", "bdsm") else 0.5 for p in side_paths)
    # 证据一致性（同向路径数占比）
    consistency = len(side_paths) / max(1, len(side_paths) + 1)
    # 市场影响权重（矛盾分析法.md §三）
    weight_map = {"strategic": 0.30, "bdsm": 0.25, "bcrm": 0.20,
                  "trend_following": 0.15, "l2_gene": 0.10}
    market_weight = sum(weight_map.get(p["source"], 0.05) for p in side_paths)

    total = power * 0.4 + time_urgency * 0.15 + consistency * 0.25 + market_weight * 0.20
    return {"power": power, "time": time_urgency, "consistency": consistency,
            "market_weight": market_weight, "total": total}
```

#### Step 3: 主导性评估 `_evaluate_dominance()`

```python
def _evaluate_dominance(self, dominance, paths, market_data) -> dict:
    """主导性评估 + Wyckoff/Minervini 指标融合."""

    # Wyckoff Cause & Effect（累积期长度→后续行情规模）
    cause_score = self._compute_cause_score(market_data)

    # Wyckoff Effort vs Result（量价背离检测）
    effort_result = self._compute_effort_result_ratio(market_data)

    # Minervini 趋势模板 + VCP
    continuation = self._compute_continuation_score(market_data, dominance["direction"])

    # 综合强度 = 基础矛盾强度 × (1 + 因果加成 + 量价加成 + 趋势延续加成)
    base_strength = dominance["strength"]
    enhanced = base_strength * (1.0 + 0.2*cause_score + 0.2*effort_result + 0.3*continuation)
    enhanced = min(1.0, enhanced)  # 上限截断

    # 矛盾维度识别（权重最高路径的来源 → 映射 C1-C8）
    dim_map = {"bdsm": "C1", "trend_following": "C2", "bcrm": "C3",
               "strategic": "C4", "deep_reasoning": "C6",
               "synthesized": "C7", "l2_gene": "C8"}
    primary_source = max(paths, key=lambda p: p["confidence"])["source"]
    dimension = dim_map.get(primary_source, "C3")

    return {
        "dimension": dimension,
        "direction": dominance["direction"],
        "strength": float(enhanced),
        "confidence": float(dominance["confidence"]),
        "cause_score": float(cause_score),
        "effort_result": float(effort_result),
        "continuation_score": float(continuation),
    }
```

### 4.3 矛盾强度调制的 lagrangian（扩展）

**文件：** [hjb_solver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/core/hjb_solver.py) `lagrangian()` 方法

**变更：** 新增可选参数 `primary_contradiction`，不传则保持现有行为（向后兼容）。

```python
def lagrangian(
    self,
    price: float,
    action: str,
    r_vector: dict | None = None,
    primary_contradiction: dict | None = None,  # 新增
) -> float:
    """计算瞬时 Lagrangian L(p, u), 可选矛盾强度调制.

    矛盾论 §矛盾主要方面: 主要矛盾方向阻力降低, 次要方向阻力升高
    """
    L_base = self._lagrangian_base(price, action, r_vector)  # 现有逻辑

    if primary_contradiction is None:
        return L_base  # 向后兼容

    pc_dir = primary_contradiction.get("direction", "neutral")
    pc_strength = float(primary_contradiction.get("strength", 0.0))
    pc_strength = max(0.0, min(1.0, pc_strength))

    if pc_dir == "neutral" or pc_strength < 0.01:
        return L_base

    action_dir = {"long": "long", "short": "short"}.get(action, "neutral")
    if action_dir == pc_dir:
        # 对齐主要矛盾: 阻力降低（阻力最小路径哲学）
        L = L_base * (1.0 - 0.3 * pc_strength)
    else:
        # 逆向主要矛盾: 阻力升高
        L = L_base * (1.0 + 0.5 * pc_strength)

    return float(max(0.001, L))  # 阻力下限保护
```

**调制系数设计依据：**

| 情形 | 系数 | 哲学依据 |
|:---|:---|:---|
| action 对齐主要矛盾 | `× (1 - 0.3×strength)` | 阻力最小方向=主要矛盾方向 |
| action 逆向主要矛盾 | `× (1 + 0.5×strength)` | 次要方向阻力升高（重心原则） |
| 无主要矛盾/neutral | 不调制 | FAIL-OPEN 向后兼容 |

### 4.4 趋势延续性回流（扩展 _discover_paths）

**文件：** [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py) `_discover_paths()`

**变更：** 每个路径新增 3 个字段（cause_score / effort_result / continuation_score），由 `TrendContinuationScorer` 统一计算。

**新增辅助模块：** `dreambuddy_evolution/core/trend_continuation.py`

```python
class TrendContinuationScorer:
    """趋势延续性评分器 (Minervini SEPA + Wyckoff)."""

    def score(self, market_data: dict, direction: str) -> dict:
        return {
            "continuation_score": self._minervini_score(market_data, direction),
            "cause_score": self._wyckoff_cause(market_data),
            "effort_result": self._wyckoff_effort_result(market_data),
        }

    def _minervini_score(self, md, direction) -> float:
        """8 条件趋势模板 (Stage 2 确认) + VCP 收缩比."""
        kline = md.get("kline_data", {})
        passed = 0
        # 8 条件逐项检查 (简化版, 加密市场适配)
        if kline.get("price", 0) > kline.get("ma150", 0): passed += 1
        if kline.get("price", 0) > kline.get("ma200", 0): passed += 1
        if kline.get("ma150", 0) > kline.get("ma200", 0): passed += 1
        if kline.get("ma200_slope", 0) > 0: passed += 1
        if kline.get("ma50", 0) > kline.get("ma150", 0): passed += 1
        if kline.get("price", 0) > kline.get("ma50", 0): passed += 1
        if kline.get("price", 0) >= kline.get("low_52w", 0) * 1.25: passed += 1
        if kline.get("price", 0) <= kline.get("high_52w", 0) * 1.25: passed += 1

        template_score = passed / 8.0

        # VCP 收缩比 (需历史 bar 数据)
        vcp_score = self._vcp_contraction(kline)  # 0-1

        return float(template_score * 0.6 + vcp_score * 0.4)

    def _vcp_contraction(self, kline) -> float:
        """VCP: T2/T1 ≤ 0.75, T3/T2 ≤ 0.75 → 1.0."""
        contractions = kline.get("contractions", [])
        if len(contractions) < 2:
            return 0.5  # 无足够数据, 中性
        ratios = []
        for i in range(1, len(contractions)):
            if contractions[i-1] > 0:
                r = contractions[i] / contractions[i-1]
                ratios.append(1.0 if r <= 0.75 else max(0.0, 1.0 - (r - 0.75)))
        return float(sum(ratios) / len(ratios)) if ratios else 0.5

    def _wyckoff_cause(self, md) -> float:
        """Cause & Effect: 累积期标准化时长 → 后续行情规模."""
        consolidation_bars = md.get("kline_data", {}).get("consolidation_bars", 0)
        # 标准化: 20-60 bars 累积期 → 0.5-1.0
        return float(min(1.0, max(0.0, (consolidation_bars - 10) / 50)))

    def _wyckoff_effort_result(self, md) -> float:
        """Effort vs Result: 量价背离检测."""
        kline = md.get("kline_data", {})
        vol_change = kline.get("volume_change_pct", 0)
        price_change = kline.get("price_change_pct", 0)
        if price_change == 0:
            return 0.5
        # effort/result 一致性: 量价同向 → 高分
        if (vol_change > 0) == (price_change > 0):
            return 0.8
        return 0.3  # 背离 → 低分
```

### 4.5 _select_optimal_path 集成（扩展）

**文件：** [evolution_pipeline.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/23-四层闭环自进化交易架构/dreambuddy_evolution/evolution_pipeline.py) `_select_optimal_path()` L562-L649

**变更：** 在 HJB solve 前调用 PrimaryContradictionIdentifier，将结果传入 lagrangian。

```python
def _select_optimal_path(self, paths: list[dict], r_out: dict, market_data: dict) -> dict:
    # ... 现有 HJB 块 ...

    # === 新增: 主要矛盾识别 (开关 + FAIL-OPEN) ===
    primary_contradiction = None
    try:
        from dreambuddy_evolution.agi_config import get_switch
        if get_switch("enable_contradiction_identifier", True):
            from dreambuddy_evolution.core.contradiction_identifier import (
                PrimaryContradictionIdentifier,
            )
            identifier = PrimaryContradictionIdentifier()
            primary_contradiction = identifier.identify(paths, market_data, r_out)
    except Exception as e:
        logger.debug("[FO-AGI][Contradiction] fail: %s", e)

    # HJB solve 时传入 primary_contradiction (需 solver 支持)
    if hjb_policy is not None and primary_contradiction is not None:
        # lagrangian 调制已在 _value_iteration 内部调用时注入
        # 此处仅记录用于审计
        pass

    # === 扩展: 评分公式融入矛盾强度 ===
    scored = []
    for p in paths:
        score = (
            float(p["expected_return"])
            * float(p["confidence"])
            * (1.0 - float(p["resistance"]))
        )
        # HJB 增强 (现有)
        if hjb_policy is not None:
            v_adjust = max(0.0, 1.0 - hjb_policy["total_cost"])
            score = score * (0.7 + 0.3 * v_adjust)

        # 矛盾强度增强 (新增): 对齐主要矛盾 → 加分
        if primary_contradiction is not None:
            pc_dir = primary_contradiction.get("direction", "neutral")
            pc_strength = primary_contradiction.get("strength", 0.0)
            if p["direction"] == pc_dir:
                score = score * (1.0 + 0.2 * pc_strength)  # 对齐加分
            elif p["direction"] != "neutral":
                score = score * (1.0 - 0.3 * pc_strength)  # 逆向减分

        # 趋势延续性增强 (新增)
        cont = float(p.get("continuation_score", 0.5))
        score = score * (0.8 + 0.4 * cont)  # 延续性高 → 加分

        scored.append({**p, "score": round(score, 6)})

    # ... 现有排序 + 统计验证 ...

    return {
        # ... 现有字段 ...
        "primary_contradiction": primary_contradiction,  # 新增审计字段
    }
```

### 4.6 小仓验证结果回流闭环（Phase 3.4）

**目标：** 验证结果回流调整矛盾权重，形成闭环。

**文件：** `dreambuddy_evolution/engines/shadow_rl_trainer.py`（扩展）

```python
# 在 ShadowRL 验证完成后, 回流调整矛盾权重
def _feedback_to_contradiction_weights(
    self,
    verified_primary: dict,
    outcome: dict,  # {pnl, success, n_trials}
) -> dict:
    """验证结果回流调整矛盾权重.

    矛盾论 §矛盾转化: 验证失败 → 降低矛盾权重, 验证成功 → 升级
    """
    weight_adjustment = {}
    if outcome["success"]:
        # 成功: 矛盾权重升级 (Bayesian 更新)
        weight_adjustment["weight_factor"] = 1.0 + 0.1 * min(1.0, outcome["n_trials"] / 10)
    else:
        # 失败: 矛盾转化, 权重降级
        weight_adjustment["weight_factor"] = max(0.3, 1.0 - 0.2 * outcome.get("fail_streak", 1))

    return {**verified_primary, "weight_adjustment": weight_adjustment}
```

---

## 五 · 集成点（精确到文件/行号）

| 变更 | 文件 | 方法 | 行号 | 类型 |
|:---|:---|:---|:---|:---|
| 新增 PrimaryContradictionIdentifier | `core/contradiction_identifier.py` | identify() | 全新 | 新建 |
| 新增 TrendContinuationScorer | `core/trend_continuation.py` | score() | 全新 | 新建 |
| lagrangian 接受矛盾调制 | `core/hjb_solver.py` | lagrangian() | L106-L148 | 扩展 |
| _value_iteration 传入矛盾调制 | `core/hjb_solver.py` | _value_iteration() | L206-L282 | 扩展 |
| _discover_paths 注入延续性字段 | `evolution_pipeline.py` | _discover_paths() | L329-L560 | 扩展 |
| _select_optimal_path 调用矛盾识别 | `evolution_pipeline.py` | _select_optimal_path() | L562-L649 | 扩展 |
| 新增开关 enable_contradiction_identifier | `agi_config.py` | — | — | 新增 |
| 新增开关 enable_trend_continuation | `agi_config.py` | — | — | 新增 |
| ShadowRL 回流闭环 | `engines/shadow_rl_trainer.py` | _feedback_to_contradiction_weights() | 全新 | 扩展 |

---

## 六 · 量化指标定义

### 6.1 主要矛盾识别指标

| 指标 | 计算方式 | 阈值/范围 |
|:---|:---|:---|
| `resonance_score` | max(long_weight, short_weight) / total_weight | 0-1, ≥0.6 共振 |
| `dominance_score` | \|long_total - short_total\| / (long_total + short_total) | 0-1, ≥0.55 主导 |
| `power` | Σ(confidence × expected_return) | 0-∞ |
| `time_urgency` | 短期信号路径数权重 | 0-1 |
| `consistency` | 同向路径数 / 总路径数 | 0-1 |
| `market_weight` | Σ(来源权重映射) | 0-1 |

### 6.2 Wyckoff 指标

| 指标 | 计算方式 | 阈值 |
|:---|:---|:---|
| `cause_score` | (consolidation_bars - 10) / 50 | 0-1, ≥0.5 充分累积 |
| `effort_result_ratio` | volume_change / price_change 同向=0.8, 背离=0.3 | 0-1 |

### 6.3 Minervini 指标

| 指标 | 计算方式 | 阈值 |
|:---|:---|:---|
| `trend_template_score` | 8 条件通过数 / 8 | ≥0.75 (6/8) Stage 2 |
| `vcp_contraction_score` | 收缩比 T(i)/T(i-1) ≤ 0.75 → 1.0 | ≥0.5 有效 |
| `volume_dry_up_ratio` | 近 10 bar 均量 / 50 日均量 | <0.50 理想 <0.30 |
| `breakout_volume_ratio` | 突破日量 / 50 日均量 | ≥1.5x |

### 6.4 矛盾调制系数

| 情形 | 调制系数 | 效果 |
|:---|:---|:---|
| action 对齐 primary_direction | `L × (1 - 0.3×strength)` | 阻力降低 30% |
| action 逆向 primary_direction | `L × (1 + 0.5×strength)` | 阻力升高 50% |
| neutral / 无矛盾 | 不调制 | 向后兼容 |

---

## 七 · 硬约束

| 编号 | 约束 | 违反后果 |
|:---|:---|:---|
| **HC-AGI-18** | PrimaryContradictionIdentifier 异常必须 FAIL-OPEN，返回 neutral 兜底 | 阻塞交易 |
| **HC-AGI-19** | 矛盾调制系数 strength ∈ [0, 1]，调制后 L ≥ 0.001 | L=0 导致除零 |
| **HC-AGI-20** | 趋势延续性字段缺失时取 0.5 中性兜底 | 字段缺失导致评分偏移 |
| **HC-AGI-21** | `enable_contradiction_identifier` 默认 True，但可关断退化为 argmin | 开关失效 |
| **HC-AGI-22** | 验证回流权重因子 ∈ [0.3, 1.5]，下限 0.3 防止矛盾权重归零 | 权重归零导致方向丢失 |
| **HC-AGI-23** | 矛盾识别至少 2 路径，否则返回 neutral（不强行识别） | 单路径误判主导 |

**与现有硬约束的关系：**
- HC-AGI-15/16/17（HJB 求解器）不可降级，本 SPEC 只扩展 lagrangian 输入
- HC-AGI-18-23 全部遵循 FAIL-OPEN 铁律

---

## 八 · 开关架构

| 开关 | 默认 | 作用 | 关断效果 |
|:---|:---|:---|:---|
| `enable_contradiction_identifier` | True | 启用主要矛盾识别 | 退化为 argmin（v1.5 行为） |
| `enable_trend_continuation` | True | 启用趋势延续性回流 | 路径无 continuation_score 字段 |
| `enable_contradiction_feedback` | True | 启用验证回流闭环 | 矛盾权重不更新（静态） |

**关断等价性：** 三个开关全关 → 系统等价于 v1.5（HJB + argmin），不影响现有 715 测试。

---

## 九 · 落地阶段规划（TDD）

### Phase 3.1: PrimaryContradictionIdentifier（新建模块）

**TDD 步骤：**

1. RED: 写 `test_contradiction_identifier.py`，断言 `from dreambuddy_evolution.core.contradiction_identifier import PrimaryContradictionIdentifier` 触发 ModuleNotFoundError
2. GREEN: 实现 `PrimaryContradictionIdentifier`，覆盖三步法
3. 测试用例：
   - test_identify_resonance_all_long（共振全多）
   - test_identify_resonance_all_short（共振全空）
   - test_arbitrate_conflict_long_vs_short（冲突裁决）
   - test_neutral_default_when_single_path（单路径 neutral 兜底）
   - test_fail_open_on_exception（异常 FAIL-OPEN）
   - test_dominance_threshold（主导阈值）
   - test_dimension_mapping（C1-C8 映射）

### Phase 3.2: TrendContinuationScorer（新建模块）

1. RED: `test_trend_continuation.py`
2. GREEN: 实现 8 条件模板 + VCP + Wyckoff 指标
3. 测试用例：
   - test_minervini_8_criteria_all_pass
   - test_vcp_contraction_valid
   - test_vcp_contraction_invalid_ratio
   - test_wyckoff_cause_score
   - test_effort_result_divergence

### Phase 3.3: lagrangian 矛盾调制（扩展）

1. RED: 扩展 `test_hjb_variational_solver.py`，断言 lagrangian 接受 primary_contradiction 参数
2. GREEN: 扩展 lagrangian()，保持向后兼容
3. 测试用例：
   - test_lagrangian_with_contradiction_aligned（对齐降阻）
   - test_lagrangian_with_contradiction_opposed（逆向升阻）
   - test_lagrangian_without_contradiction（向后兼容）
   - test_lagrangian_floor_0_001（HC-AGI-19）

### Phase 3.4: _select_optimal_path 集成（扩展）

1. RED: 扩展 `test_evolution_pipeline.py`
2. GREEN: 集成矛盾识别 + 延续性 + 评分增强
3. 测试用例：
   - test_select_with_contradiction_aligned_path_wins
   - test_select_with_continuation_score
   - test_select_failopen_contradiction_exception
   - test_all_switches_off_equivalent_v15

### Phase 3.5: 验证回流闭环（扩展）

1. RED: `test_contradiction_feedback.py`
2. GREEN: 实现 _feedback_to_contradiction_weights
3. 测试用例：
   - test_feedback_success_increases_weight
   - test_feedback_failure_decreases_weight
   - test_feedback_weight_floor_0_3（HC-AGI-22）

---

## 十 · 测试策略

### 10.1 单元测试（TDD）

| 模块 | 测试文件 | 用例数 |
|:---|:---|:---|
| PrimaryContradictionIdentifier | test_contradiction_identifier.py | 7 |
| TrendContinuationScorer | test_trend_continuation.py | 5 |
| lagrangian 调制扩展 | test_hjb_variational_solver.py（扩展） | 4 |
| _select_optimal_path 集成 | test_evolution_pipeline.py（扩展） | 4 |
| 验证回流 | test_contradiction_feedback.py | 3 |
| **合计** | — | **23** |

### 10.2 全量回归

- 现有 715 测试必须 0 失败
- 三个新开关全关时，行为等价于 v1.5
- 三个新开关全开时，主要矛盾方向路径评分应高于逆向路径

### 10.3 集成测试

- 端到端：run_symbol() 调用链完整跑通
- FAIL-OPEN：注入异常，验证降级到 argmin
- 开关矩阵：8 种开关组合全部跑通

---

## 十一 · 预期效果

### 11.1 哲学逻辑链修复

| 环节 | v1.5 实现度 | v3.0 目标 | 修复方式 |
|:---|:---:|:---:|:---|
| ① 多路径=多矛盾 | 85% | 90% | 路径增加矛盾维度标签 |
| ② 识别主要矛盾 | 30% | **85%** | PrimaryContradictionIdentifier 三步法 |
| ③ 趋势延续性 | 40% | **80%** | TrendContinuationScorer 回流 |
| ④ 回测+小仓验证 | 50% | **75%** | _feedback_to_contradiction_weights |
| ⑤ 最小阻力计算 | 70% | **90%** | lagrangian 矛盾调制 |

### 11.2 交易决策改善

- **方向准确率**：主要矛盾识别 → 方向误判降低
- **入场精准度**：趋势延续性回流 → 避免逆势入场
- **风控闭环**：验证回流 → 矛盾转化时自动调权

---

## 十二 · 风险与缓解

| 风险 | 缓解 |
|:---|:---|
| 矛盾识别误判（单路径强信号误为主导） | HC-AGI-23 强制 ≥2 路径 + dominance_threshold ≥ 0.55 |
| 趋势模板加密市场不适配（加密无 52 周数据） | 标准化为 365 日滚动窗口，缺失时取 0.5 中性 |
| VCP 数据不足（新币历史短） | contractions < 2 时返回 0.5 中性兜底 |
| 矛盾调制过强导致路径倾斜 | 调制系数 0.3/0.5 上限 + strength ∈ [0,1] + L ≥ 0.001 下限 |
| 验证回流冷启动无数据 | weight_factor 默认 1.0，等验证样本积累后生效 |

---

## 十三 · 后续演进

- **Phase 4**: 因果推断（CausalEngine）融入矛盾识别，从相关性→因果性
- **Phase 5**: 元认知门（MetaCognitionGate）对矛盾识别结果做二阶校验
- **Phase 6**: 深度学习驱动矛盾权重学习（替代手工 0.4/0.15/0.25/0.20 权重）

---

> **评审检查清单：**
> - [ ] 哲学逻辑链 5 环节是否全覆盖
> - [ ] 硬约束 HC-AGI-18-23 是否合理
> - [ ] 开关架构是否支持关断等价 v1.5
> - [ ] TDD 用例是否覆盖 FAIL-OPEN
> - [ ] 集成点是否精确到文件/行号
> - [ ] 量化指标是否可计算
