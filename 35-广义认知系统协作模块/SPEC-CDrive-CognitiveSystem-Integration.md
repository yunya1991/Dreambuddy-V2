# SPEC: C-Drive × 广义大认知系统深度集成

> **版本**: v0.2 (2026-10-12)
> **状态**: ✅ 复审通过 — 4 Major + 5 Minor 全部解决，7 模式阻断清单全通过，1 项复审新发 Minor（防震荡死代码）已当场修复
> **关联系统**: C-Drive Agent + 广义大认知系统(L1-L4 → 对接口径 C1-C4) + 33-REA逆向解析工程 + 34-前端应用训练系统 + 辩论引擎 + **前端 L0/L1/L2 架构（`34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md`，见 §7 对接细则）**
> **前置条件**: SPEC-CognitiveSystem-Evolution.md P0-P3 24/24 已落地 + P1-P3 决策推导器已实现
> **核心命题**: C-Drive 作为大认知系统的"执行手臂"，四层认知系统作为 C-Drive 的"思考大脑"，训练驱动持续进化
> **适用边界**: 本 SPEC 适用于 C-Drive 反思层（"怎么做"决策），非交易策略层（"做不做"决策）。交易策略路由由 dreambuddy-os 调度层负责。**§7 为与前端 L1 路由器的对接细则（跨系统扩展，只定义信号产出/消费契约，不改 §0-§6 的 C-Drive 反思路由逻辑）。**
> **评审历史**: v0.1 草案 → 同行评审（Devil's Advocate 最高评分 4，2 项让步）→ v0.2 修改 → 复审通过（4 Major + 5 Minor 全解决）

---

## 0. 核心架构

### 0.1 设计理念

> **C-Drive 是"怎么做"的执行器，大认知系统是"想清楚"的大脑。**
>
> 两者深度集成形成闭环：C-Drive 收集执行信号 → 大认知系统四层路由思考 → 产出反射决策 → C-Drive 执行 → 结果反馈训练进化

### 0.2 四层映射

| C-Drive v3 场景 | 大认知系统层级 | 能力来源 | Token |
|---------------|-------------|---------|-------|
| 高匹配度→直接推进 | **L3 路由层** | L2A fast-path(80%) + 三库加权召回 | 0 |
| 低匹配度→反思推理 | **L1 基础层** | 33-REA Evidence-First + PoE | 0 |
| 案例少+低匹配→调研 | **L3 路由层** | Agentic RAG + SKILL 调研 | LLM |
| → 路径分析 | **L1 基础层** | 33-REA 逆向分析 | 0 |
| 多路径复杂→Debate | **L4 元认知层** | Believability-weighted + GWT | LLM |
| 所有情况→jev 裁决 | **L4 元认知层** | 预测误差门控 + HOT | 0/LLM |

### 0.3 整体架构图

```
┌─────────────────────────────────────────────────────────────────────┐
│                    C-Drive v3: 多维升级路由                           │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐      │
│  │  Step 1: L1 认知系统 recall + 匹配度评估                  │      │
│  │  recall(context) → memories[] → match_score + density   │      │
│  └──────────────────────┬───────────────────────────────────┘      │
│                         │                                          │
│  ┌──────────────────────▼───────────────────────────────────┐      │
│  │  Step 2: 四层分级路由                                      │      │
│  └──────────────────────┬───────────────────────────────────┘      │
│                         │                                          │
│    ┌────────────────────┼────────────────────┐                     │
│    │                    │                    │                     │
│ ┌──▼────────┐  ┌───────▼────────┐  ┌───────▼────────┐             │
│ │Tier 1: 高匹配│  │Tier 2: 低匹配   │  │Tier 3: 案例少  │             │
│ │L3 fast-path │  │L1 33-REA 反思  │  │L3 SKILL 调研   │             │
│ │→ 直接推进   │  │→ 证据驱动决策   │  │→ L1 33-REA 路径│             │
│ │(零 token)  │  │(零 token)     │  │(LLM token)    │             │
│ └──────┬─────┘  └───────┬────────┘  └───────┬────────┘             │
│        │                │                    │                     │
│        │                │           ┌────────▼────────┐            │
│        │                │           │ Tier 4: 多路径    │            │
│        │                │           │ L4 Debate 选择    │            │
│        │                │           │ (LLM token)      │            │
│        │                │           └────────┬────────┘            │
│        │                │                    │                     │
│        └────────────────┼────────────────────┘                     │
│                         │                                          │
│  ┌──────────────────────▼───────────────────────────────────┐      │
│  │  Step 3: L4 jev 全局裁决（所有非 skip 场景）               │      │
│  │  预测误差门控 + Believability-weighted + HOT Self-Model   │      │
│  └──────────────────────┬───────────────────────────────────┘      │
│                         │                                          │
│  ┌──────────────────────▼───────────────────────────────────┐      │
│  │  Step 4: C-Drive 决策输出 + 训练反馈                       │      │
│  │  CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE │   │
│  └──────────────────────┬───────────────────────────────────┘      │
│                         │                                          │
│  ┌──────────────────────▼───────────────────────────────────┐      │
│  │  Step 5: 认知闭环 (record + verify)                        │      │
│  │  执行结果 → record → 贝叶斯更新 → 蒸馏 → L4 自进化        │      │
│  └──────────────────────────────────────────────────────────┘      │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 1. 现有基础盘点

### 1.1 C-Drive Agent 现状

**文件**: [c_drive_agent.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py)

**现有阈值** (L200-207):
| 常量 | 值 | 含义 |
|------|---|------|
| CONF_SKIP | 0.75 | > 0.75 跳过循环 |
| CONF_RECALL_ONLY | 0.65 | 0.65-0.75 仅 recall+reflect |
| CONF_FULL_LOOP | 0.50 | < 0.50 全链路 |
| CONF_REDO | 0.20 | < 0.20 → REDO |
| CONF_SUPPLEMENT | 0.30 | max(bull,bear) < 0.30 → SUPPLEMENT |

**现有四步循环** (L330-411):
1. recall — 认知记忆检索 (FAIL-OPEN)
2. debate — Bull/Bear 辩论 (LLM, confidence < 0.65 时触发)
3. jeval — 裁决 (confidence < 0.50 且 CONTINUE 时触发)
4. supplement — 子代理补充 (SUPPLEMENT 时触发)

**关键差距**:
- ❌ 单维路由（仅 confidence，不考虑案例密度）
- ❌ 33-REA 未接入（中置信度即费 LLM token）
- ❌ SKILL 调研未接入
- ❌ 多路径检测无（恒走辩论）
- ❌ jev 条件触发（非全局）

### 1.2 广义大认知系统现状

**SPEC**: [SPEC-CognitiveSystem-Evolution.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/35-广义认知系统协作模块/SPEC-CognitiveSystem-Evolution.md) — P0-P3 24/24 已落地

| 层 | 现状 | 关键能力 |
|---|------|---------|
| **L1 基础层** | ✅ 五系统闭环 | 认知(18K记忆) + SKILL(247) + 知识库(4540 chunks) + 文档(46索引) + 33-REA |
| **L2 记忆层** | ✅ 三层记忆 + ACT-R | working/recall/archival + FSRS 遗忘 + Evidence Ledger |
| **L3 路由层** | ✅ Intent-Engine + RAG | L2A fast-path(80%) + Agentic RAG + 三库加权召回 |
| **L4 元认知层** | ✅ GWT + HOT + 预测误差 | Workspace Bus + FOK/JOL + Believability-weighted |

### 1.3 P1-P3 决策推导器现状

**文件**: [decision_deriver.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/core/decision_deriver.py) + [debate_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/34-前端应用训练系统/core/debate_integration.py)

| 层 | 机制 | Token | 状态 |
|---|------|-------|------|
| P1 | outcome+confidence+action/learned 语义推导 | 0 | ✅ 24/24 |
| P2 | C-Drive 阈值反思 (CDRIVE_CONF_REDO=0.20) | 0 | ✅ 14/14 |
| P3 | 辩论引擎注入 bull/bear confidence | LLM | ✅ 19/19 |

---

## 2. SPEC 详细设计

### 2.1 P4: 33-REA 零 token 反思驱动（L1 层集成）

**目标**: 33-REA 逆向解析产物直接驱动 C-Drive 反思，替代中置信度场景的 LLM 辩论。

#### 2.1.1 33-REA 输出 → 反射决策映射

| 33-REA 输出 | 反思信号 | expected_decision | 依据 |
|------------|---------|------------------|------|
| `known_gaps` 含 "missing/缺失/未实现" | 需要补充 | INSERT_BEFORE | 代码缺口需插入 |
| `known_gaps` 含 "wrong/错误/bug" | 需要重做 | REDO | 实现有误需重做 |
| `known_gaps` 含 "dead/无用/冗余" | 应终止 | EARLY_TERMINATE | 无效路径应终止 |
| `known_gaps` 含 "circular/循环依赖" | 需要重做 | REDO | 架构问题需重构 |
| `call_chain` 有断裂 | 需要插入 | INSERT_BEFORE | 调用链不完整 |
| `dependency_graph` 有环 | 需要重做 | REDO | 依赖循环 |
| `evidence.confidence` < 0.3 | 低置信度 | REDO | 对齐 CDRIVE_CONF_REDO |
| `evidence.level` = UNKNOWN | 无法确定 | EARLY_TERMINATE | 事实不足 |
| 无 known_gaps + confidence 高 | 一切正常 | CONTINUE | 正常继续 |

#### 2.1.2 实现

```python
# 34-前端应用训练系统/core/rea_cdrive_adapter.py (新建)
# 关键词映射外部化到配置文件（m1 修改：便于维护和扩展）

# 配置文件: 34-前端应用训练系统/core/rea_keyword_map.yaml
# ---
# known_gaps_map:
#   - pattern: "missing|缺失|未实现"
#     decision: INSERT_BEFORE
#   - pattern: "wrong|错误|bug"
#     decision: REDO
#   - pattern: "dead|无用|冗余"
#     decision: EARLY_TERMINATE
#   - pattern: "circular|循环依赖"
#     decision: REDO

def derive_decision_from_rea(rea_result: REAParseResult) -> Optional[str]:
    """33-REA 零 token 驱动 C-Drive 反思"""
    # 1. known_gaps 关键词 → 反射决策（从 YAML 配置加载）
    keyword_map = _load_keyword_map()  # 外部化配置，支持热更新
    for gap in rea_result.known_gaps:
        for entry in keyword_map.get("known_gaps_map", []):
            if re.search(entry["pattern"], gap, re.IGNORECASE):
                return entry["decision"]
    # 2. evidence confidence 阈值
    if rea_result.confidence < 0.3:
        return REDO
    if rea_result.evidence_level == "UNKNOWN":
        return EARLY_TERMINATE
    # 3. 无信号 → None（降级 P3/P2/P1）
    return None
```

**关键词配置外部化（m1）**: 关键词映射存储在 `rea_keyword_map.yaml`，支持热更新和扩展，无需修改代码。

#### 2.1.3 集成点

- `ts_http_training_executor.py` — C 层数据构造前调用 33-REA
- `run_active_training_live.py` — 活训练脚本同样调用
- 集成链: P4(33-REA) → P3(Debate) → P2(C-Drive) → P1(语义)

### 2.2 P5: 大认知系统匹配度+案例密度路由（L3 层集成）

**目标**: recall 返回的 memories 数量和 score 作为路由依据，替代单维 confidence。

#### 2.2.1 路由维度

```python
# 匹配度评估
def evaluate_match(memories: List[Memory]) -> Tuple[float, int]:
    """返回 (match_score, case_density)"""
    if not memories:
        return (0.0, 0)
    max_score = max(m.score for m in memories)
    avg_score = sum(m.score for m in memories) / len(memories)
    match_score = max_score * 0.6 + avg_score * 0.4  # 加权
    case_density = len(memories)
    return (match_score, case_density)
```

#### 2.2.2 路由规则

| match_score | case_density | Tier | 路由 |
|------------|-------------|------|------|
| ≥ 0.7 | ≥ 3 | Tier 1 | L3 fast-path → 直接推进 |
| < 0.7 | ≥ 2 | Tier 2 | L1 33-REA 反思（零 token） |
| < 0.4 | < 2 | Tier 3 | L3 SKILL 调研 → L1 33-REA 路径 |
| 多路径 | — | Tier 4 | L4 Debate 选择 |

### 2.3 P6: LLM+SKILL 调研层（L3 Agentic RAG 集成）

**目标**: 案例少+低匹配度时，先调研再分析，避免"无知识下的盲目决策"。

#### 2.3.1 调研链路

```
案例少(case_density < 2) + 低匹配(match_score < 0.4)
    ↓
L3: Agentic RAG → 检索知识库(2-KNOWLEDGE) + 文档(0-系统文档管理)
    ↓
知识不足 → LLM + SKILL 调研 (dream-research-workflow / dream-science-orchestrator)
    ↓
调研产出结构化知识 → 33-REA 逆向分析潜在路径
    ↓
多路径 → Tier 4 Debate
单路径 → 直接输出
```

#### 2.3.2 SKILL 调度

| 场景 | 调度 SKILL | 产出 |
|------|-----------|------|
| 技术调研 | dream-research-workflow | 5维交叉验证报告 |
| 科研论证 | dream-science-orchestrator | 科研级验证报告 |
| 架构调研 | dream-arch-research-orchestrator | SPEC + 评审 + PLAN |

### 2.4 P7: L4 jev 全局裁决（L4 元认知层集成）

**目标**: 所有非 skip 场景都经 jev 裁决，确保决策质量。

#### 2.4.1 jev 实现方式（M4 修改：纯规则，零 token）

> **M4 决议**: jev 采用**纯规则实现**（预测误差 + Believability + HOT），**零 LLM token**。
> 原 `_jeval()` 的 LLM 调用保留为 `jeval_llm()` 方法，仅在纯规则 jev 触发 `JEV_BLOCK` 且 case_density >= 5 时才升级为 LLM 调用（< 5% 场景）。
> Fast-path 跳过: 当 match_score >= 0.8 且 case_density >= 5 时跳过 jev（高可信度无需裁决）。

```python
def jev_gate(decision: str, match_score: float, case_density: int,
             rea_confidence: float, debate_result: Optional[dict]) -> str:
    """L4 全局裁决门控（纯规则，零 token）"""

    # Fast-path: 高可信度跳过（避免 4 倍调用中 80% 被浪费）
    if match_score >= 0.8 and case_density >= 5:
        return decision  # 高可信度，无需裁决

    # 1. 预测误差门控
    expected = match_score
    actual = rea_confidence if rea_confidence else debate_result.get("bull_confidence", 0.5) if debate_result else 0.5
    prediction_error = abs(expected - actual)

    # 2. 高预测误差 → 降级决策
    if prediction_error > 0.3 and decision == CONTINUE:
        return REDO  # 预测与实际差距大 → 不应继续

    # 3. Believability-weighted
    believability = case_density * match_score
    if believability < 0.5 and decision == CONTINUE:
        return INSERT_BEFORE  # 低可信度 → 需要补充

    # 4. HOT Self-Model — 元认知"我觉得对吗"
    if decision in [REDO, EARLY_TERMINATE] and case_density >= 3 and match_score >= 0.6:
        return CONTINUE  # 有足够案例支撑，不需要 redo/terminate

    return decision
```

#### 2.4.2 防震荡机制（M1 新增）

> **M1 决议**: jev 全局门控可能导致"决策震荡"——jev 改写 CONTINUE→REDO，下次 recall 仍高匹配→CONTINUE，jev 又改回 REDO。
> 防震荡三重机制：

```python
class JevAntiOscillation:
    """jev 防震荡控制器"""

    def __init__(self):
        self._consecutive_overrides = 0  # 连续改写计数
        self._last_decision = None       # 上次原始决策
        self._override_history = []       # 改写历史
        self._jev_degraded = False       # jev 是否已降级
        self._degradation_count = 0     # 恢复 jev 权限还需未改写次数

    def check_oscillation(self, original_decision: str, jev_decision: str) -> str:
        """检查并防止决策震荡

        规则:
          1. 连续超过 MAX_CONSECUTIVE_OVERRIDE 次改写 → 信任原始决策
          2. 连续达到 DEGRADATION_THRESHOLD 次改写 → jev 临时降级
          3. 降级期间始终信任原始；需 RECOVERY_COUNT 次未改写才能恢复
        """
        # jev 已降级 → 信任原始决策（但仍追踪恢复进度）
        if self._jev_degraded:
            if original_decision == jev_decision:
                self._degradation_count -= 1
                if self._degradation_count <= 0:
                    self._jev_degraded = False
                    self._consecutive_overrides = 0
            return original_decision  # 降级期间始终信任原始

        if original_decision == jev_decision:
            # 未改写 → 重置计数
            self._consecutive_overrides = 0
            return jev_decision

        # 发生改写
        self._consecutive_overrides += 1
        self._override_history.append((original_decision, jev_decision))

        # 超过改写上限 → 信任原始
        if self._consecutive_overrides >= MAX_CONSECUTIVE_OVERRIDE + 1:
            # 同时达到衰减阈值 → jev 临时降级
            if self._consecutive_overrides >= DEGRADATION_THRESHOLD:
                self._jev_degraded = True
                self._degradation_count = RECOVERY_COUNT
            return original_decision

        return jev_decision
```

**防震荡参数**:
| 参数 | 值 | 含义 |
|------|---|------|
| MAX_CONSECUTIVE_OVERRIDE | 2 | 连续改写上限，第 3 次信任原始 |
| DEGRADATION_THRESHOLD | 3 | 连续改写触发衰减的阈值 |
| RECOVERY_COUNT | 5 | 衰减后恢复 jev 权限所需未改写次数 |

#### 2.4.3 裁决覆盖率

| 场景 | 原始 jev | P7 jev | Token |
|------|---------|--------|------|
| 高匹配度+高密度 (≥0.8, ≥5) | 不触发 | **Fast-path 跳过** | 0 |
| 高匹配度 skip | 不触发 | 不触发 | 0 |
| 中匹配度 CONTINUE | 不触发 | **触发**（纯规则） | 0 |
| 低匹配度 REDO | 不触发 | **触发**（纯规则） | 0 |
| 多路径 Debate 结果 | 不触发 | **触发**（纯规则） | 0 |
| JEV_BLOCK + 高密度 (≥5) | LLM 调用 | **升级为 LLM**（<5%场景） | LLM |

**Token 效率**: 纯规则 jev 零 token，仅 <5% 场景升级为 LLM，相比原始条件触发 LLM 调用更高效。

### 2.5 P8: 认知闭环 + 训练进化（L4 自进化集成）

**目标**: C-Drive 执行结果反馈到认知系统，驱动贝叶斯更新 + 蒸馏 + L4 自进化。

#### 2.5.1 训练进化闭环

```
C-Drive 执行决策 → 结果(成功/失败/部分)
    ↓
record(content=执行经验, quality_level=B, tags="C-Drive,训练进化")
    ↓
TAG_HOOKS: "hermes反思" → dream-self-iteration-workflow
    ↓
L4 自进化:
  ① hermes 反思 → trace 分析 → skill-creator (新 SKILL 发现)
  ② 参数优化 → 贝叶斯 + walk-forward → 阈值调优
  ③ 案例入库 → 4维价值评估 → 训练数据更新
  ④ 文档同步 → checksum → dream-doc-sync
    ↓
verify(memory_id, success) → 贝叶斯置信度更新 → 蒸馏
    ↓
认知系统进化 → 下次 recall 更精准 → C-Drive 路由更优
```

#### 2.5.2 hermes 反思频率限制（m5 新增）

> **m5 决议**: hermes 反思（dream-self-iteration-workflow）是重资源操作（LLM token + skill-creator），不应对每次 C-Drive 执行都触发，需设频率上限。

**频率限制机制**:

```python
class HermesFrequencyLimiter:
    """hermes 反思频率限制器（防止反思风暴）"""

    MAX_DAILY_HERMES = 10  # 每日最大 hermes 触发次数
    MIN_INTERVAL_SECONDS = 300  # 两次 hermes 间最小间隔（5 分钟）

    def __init__(self):
        self._daily_count = 0
        self._last_hermes_ts = 0
        self._date_key = datetime.now().strftime("%Y-%m-%d")

    def should_trigger_hermes(self, case_value_score: float) -> bool:
        """判断是否应触发 hermes 反思

        规则:
          1. 每日次数未超上限
          2. 距上次触发间隔 >= MIN_INTERVAL_SECONDS
          3. 案例价值评分 >= 0.6（高价值案例才值得反思）
        """
        self._reset_if_new_day()
        if self._daily_count >= self.MAX_DAILY_HERMES:
            return False  # 当日配额已用尽
        now = time.time()
        if now - self._last_hermes_ts < self.MIN_INTERVAL_SECONDS:
            return False  # 间隔不足
        if case_value_score < 0.6:
            return False  # 低价值案例不值得反思
        return True

    def record_hermes_trigger(self):
        """记录一次 hermes 触发"""
        self._daily_count += 1
        self._last_hermes_ts = time.time()

    def _reset_if_new_day(self):
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._date_key:
            self._date_key = today
            self._daily_count = 0
```

**频率限制参数**:
| 参数 | 值 | 含义 |
|------|---|------|
| MAX_DAILY_HERMES | 10 | 每日最大 hermes 触发次数 |
| MIN_INTERVAL_SECONDS | 300 | 两次 hermes 间最小间隔（5 分钟） |
| CASE_VALUE_THRESHOLD | 0.6 | 案例价值评分阈值，低于此值不触发 hermes |

**降级策略**: 当 hermes 配额用尽时，record 仍正常写入认知库，但跳过 dream-self-iteration-workflow 调用，仅做基础 verify。配额次日自动恢复。

#### 2.5.3 训练反馈到前端

| 认知系统产出 | 前端训练层 | 用途 |
|------------|----------|------|
| verify 更新后的置信度 | C 层 expected_decision | 修正决策推导 |
| 蒸馏后的高阶记忆 | LLM 层 prompt 优化 | 提示词优化 |
| 新 SKILL | DSH 层 执行路径 | 新执行路径 |
| 案例入库 | S 层 意图训练 | 新意图模式 |

---

## 3. 路线图

### 3.1 P0-P3 已完成（决策推导器）

| 项 | 内容 | 状态 |
|---|------|------|
| P1 | 智能决策推导器 | ✅ 24/24 |
| P2 | C-Drive Agent 阈值反思 | ✅ 14/14 |
| P3 | 辩论引擎注入 | ✅ 19/19 |

### 3.2 P4-P8 待实施

| 项 | 内容 | 优先级 | 依赖 |
|---|------|--------|------|
| **P4** | 33-REA 零 token 反思驱动 | P0 | 33-REA 已就绪 |
| **P5** | 匹配度+案例密度路由 | P0 | L3 路由层已就绪 |
| **P6** | LLM+SKILL 调研层 | P1 | P5 已就绪（需匹配度+密度评估结果） |
| **P7** | L4 jev 全局裁决 | P1 | **P4+P5+P6 全部就绪**（需所有 Tier 决策信号） |
| **P8** | 认知闭环+训练进化 | P1 | L4 自进化已就绪（与 P7 并行） |

### 3.3 实施顺序（M2 修改：P7 依赖 P4-P6 全部就绪）

```
Phase 1: P4(33-REA零token) → P5(匹配度路由) → P6(SKILL调研)
             ↑                    ↑                 ↑
             L1基础层              L3路由层           L3+L1
                                    ↓
Phase 2:                    P7(jev全局) + P8(训练进化)  ← 并行
                                 ↑              ↑
                             L4元认知层      L4自进化
```

**依赖关系**:
- P4 独立，无前置依赖
- P5 独立，无前置依赖（但与 P4 配合使用）
- P6 依赖 P5（需要匹配度+密度评估结果触发调研）
- P7 依赖 P4+P5+P6（需要所有 Tier 的决策信号作为输入）
- P8 与 P7 并行（P8 是 record/verify 闭环，不依赖 P7 的 jev 裁决逻辑）

### 3.4 部署策略（M3 新增）

> **M3 决议**: C-Drive v3 采用**新增 `run_v3()` + 保留 `run()` + feature flag** 策略，确保向后兼容。

```python
class CDriveAgent:
    # Feature flag: v3 路由开关
    _use_v3_router = os.environ.get("CDRIVE_V3", "false").lower() == "true"

    def run(self, node_id, result, state, signals=None):
        """原始 v1/v2 路由（向后兼容）"""
        if self._use_v3_router:
            return self.run_v3(node_id, result, state, signals)
        # ... 原始 run 逻辑保持不变

    def run_v3(self, node_id, result, state, signals=None):
        """v3 多维升级路由（本 SPEC 实现）"""
        # Step 1: recall + 匹配度评估
        # Step 2: 四层分级路由
        # Step 3: L4 jev 全局裁决
        # Step 4: 决策输出 + 训练反馈
        # Step 5: 认知闭环
```

**Feature flag 切换**:
| 环境变量 | 值 | 路由版本 |
|---------|---|---------|
| CDRIVE_V3 | false (默认) | v1/v2 原始路由 |
| CDRIVE_V3 | true | v3 多维路由 |

**灰度策略**: 先在测试环境启用 CDRIVE_V3=true，验证 P4-P8 全量测试通过后，生产环境灰度 10% → 50% → 100%。

---

## 4. 算法优势对比

### 4.1 与同期项目对比

| 维度 | 原始 C-Drive | 本 SPEC | 其他项目 |
|------|-------------|---------|---------|
| 路由维度 | 单维 confidence | **二维(匹配度+密度)** | 单维 |
| 零 token 反思 | 无 | **33-REA 证据驱动** | 无 |
| 调研层 | 无 | **LLM+SKILL 调研** | 无/恒 LLM |
| 多路径处理 | 恒走辩论 | **按需 Debate** | 恒 LLM |
| jev 覆盖率 | 条件触发 | **全局门控** | 无 |
| 认知闭环 | 无 | **L4 自进化** | 无 |
| 训练进化 | 无 | **贝叶斯+蒸馏反馈** | 无 |

### 4.2 Token 效率

| 场景 | 原始 | 本 SPEC | 节省 |
|------|------|---------|------|
| 高匹配度(最常见) | 0 | 0 | — |
| 中匹配度(常见) | LLM ~2K | **0 (33-REA)** | **100%** |
| 低匹配度+少案例 | LLM ~3K | LLM ~5K(调研更深) | 质量提升 |
| 多路径复杂 | 无 | LLM ~10K(按需) | 按需触发 |

**总体**: 中匹配度场景（最常见）从 LLM token → 0 token，是最大节省点。

---

## 5. 验收标准

| 验收项 | 指标 | 门禁 |
|--------|------|------|
| 决策多样性 | decisionCounts ≥ 4 种非零 | 硬门禁 |
| correctionCount | >= 3（m3 修改：避免噪音级纠正触发误判） | 硬门禁 |
| 中匹配度 token | = 0 | 硬门禁 |
| 33-REA 集成 | known_gaps → expected_decision | 硬门禁 |
| 匹配度路由 | recall 量+score 驱动 | 硬门禁 |
| jev 全局覆盖率 | 100% 非 skip | 硬门禁 |
| 认知闭环 | record+verify 链路 | 硬门禁 |
| hermes 频率限制 | 每日 ≤ 10 次（m5 修改：防止反思风暴） | 硬门禁 |
| 对比实验（m2 新增） | P4-P8 前后各 50 案例，decisionCounts 分布对比 | 硬门禁 |
| 全量回归 | pytest+jest 零回归 | 硬门禁 |

### 5.1 对比实验设计（m2）

> **实验目的**: 验证 P4-P8 集成后决策多样性显著提升，纠正信号从 0 增长到有意义的数量。

**实验方案**:
- **对照组（P4-P8 前）**: 使用原始 C-Drive v1/v2 路由，采集 50 个训练案例的 decisionCounts
- **实验组（P4-P8 后）**: 启用 CDRIVE_V3=true，采集同样 50 个训练案例的 decisionCounts
- **对比指标**:

| 指标 | 对照组预期 | 实验组目标 | 判定 |
|------|----------|----------|------|
| decisionCounts 非零种类 | 1 (仅 CONTINUE) | ≥ 4 | 种类数 ≥ 4 为通过 |
| correctionCount | 0 | ≥ 3 | ≥ 3 为通过 |
| REDO 决策比例 | 0% | 5%-25% | 在此范围为合理 |
| INSERT_BEFORE 比例 | 0% | 5%-20% | 在此范围为合理 |
| CONTINUE 比例 | 100% | 50%-80% | 低于 80% 说明路由有效分流 |
| 中匹配度 token 消耗 | ~2K/案例 | 0 | = 0 为通过 |

**执行方式**: 在测试环境运行 `run_active_training_live.py`，分别用 `CDRIVE_V3=false` 和 `CDRIVE_V3=true` 各跑 50 个案例，对比输出统计。

---

## 6. 关联文件

| 文件 | 角色 |
|------|------|
| `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py` | C-Drive Agent 原始实现 |
| `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/debate_engine.py` | 辩论引擎 |
| `33-REA逆向解析工程/core/evidence.py` | 33-REA 证据数据结构 |
| `34-前端应用训练系统/core/decision_deriver.py` | P1-P3 决策推导器 |
| `34-前端应用训练系统/core/debate_integration.py` | P3 辩论集成 |
| `34-前端应用训练系统/adapters/rea_to_tdr_adapter.py` | 33-REA → 训练数据适配 |
| `35-广义认知系统协作模块/SPEC-CognitiveSystem-Evolution.md` | 广义大认知系统 SPEC |
| `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` | 认知系统 MCP 工具 |
| `4-MEMORY/9-工具与接口/cognitive_loop_entry.py` | 认知闭环入口 |
| `34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md` | 前端 L0/L1/L2 架构 SPEC（**§7 对接细则的消费方**，见其 §3.5 / §5 第 4 条） |

---

## 7. 对接细则 — 与前端 L1 路由器的置信度门控契约

> **定位**: 本节是 §0-§6 的**跨系统扩展**，只定义「置信度门控信号」的**产出契约**（L0 认知系统 C3/C4）与**消费契约**（前端 L1 路由器），**不改动** C-Drive 自身的反思路由逻辑。
> - **产出方**: 广义认知系统 **C3 路由层**（匹配度评分）+ **C4 元认知层**（预测误差门控）——即本 SPEC §2.2.1 / §2.4.1 已实现的同一套**零 token 确定性机制**；
> - **消费方**: 前端 L1 路由器（`34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md` §5 第 4 条）——用该信号判决「**L1 直答 / 转 L2**」。
> - **职责边界**: 门控**产出于 L0（认知系统），判决归路由器**——认知系统只给**信号**，不承担路由决策。

### 7.1 为什么同一套机制能服务两个消费方

| 消费者 | 消费同一信号 | 用途 |
|---|---|---|
| C-Drive 反思层（§0-§6） | match_score + case_density + prediction_error | 自身的**反思决策**：CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE |
| 前端 L1 路由器（§7） | route_confidence（由三者归一） | **层路由决策**：L1 直答 / 转 L2 |

> 二者**共用产出、分叉消费**：认知系统只算一次信号，C-Drive 与前端路由器各取所需，不重复计算、不产生第二套阈值。

### 7.2 层名映射（认知内部 C 名 ↔ 本 SPEC 原名）

| 认知内部层（对接口径） | 本 SPEC 原名 | 在门控中的职责 |
|---|---|---|
| **C3 路由层** | L3 路由层 | 产出 **match_score**（匹配度）+ **case_density**（案例密度）+ **intent_hint** |
| **C4 元认知层** | L4 元认知层 | 产出 **prediction_error**（预测误差）+ **fok/jol** + **route_confidence**（归一置信度） |

> 命名说明: 采用 C1-C4（Cognitive Layer 1-4）以与前端 L0/L1/L2 及交易矛盾维度 C1-C8 彻底隔离，见 `SPEC-v1.3-L0L1L2-architecture.md` §3.5。

### 7.3 信号产出契约（C3 + C4 → 统一 JSON，零 token，确定性）

**复用既有实现，不新增算法**:
- **C3（= §2.2.1 `evaluate_match`）**: `match_score = max_score*0.6 + avg_score*0.4`；`case_density = len(memories)`。
- **C4（= §2.4.1 `jev_gate` 的预测误差分支）**: `expected = match_score`；`actual = rea_confidence or debate_bull_confidence or 0.5`；`prediction_error = |expected - actual|`。

**归一置信度（新增，仅一层确定性映射，不引入 LLM）**:
```python
def route_confidence(match_score: float, case_density: int, prediction_error: float) -> float:
    """前端层消费的归一置信度（0~1）——由 C3/C4 既有输出直接映射"""
    conf = match_score
    if prediction_error > PREDICTION_ERROR_MAX:   # 0.3
        conf -= 0.3                                # 预测与实际背离 → 降权
    if case_density < CASE_DENSITY_MIN:            # 3
        conf -= 0.2                                # 案例覆盖不足 → 降权
    return max(0.0, min(1.0, conf))
```

**统一信号载荷（RouterConfidenceSignal）**:
```json
{
  "match_score": 0.82,        // C3
  "case_density": 6,          // C3
  "intent_hint": "data_query",// C3: Intent-Engine 语义召回给出的意图候选
  "prediction_error": 0.12,   // C4
  "fok": true,                // C4: feeling-of-knowing
  "jol": false,               // C4: judgment-of-learning
  "route_confidence": 0.82,   // 归一置信度
  "route_tier": "Tier1",      // C3 §2.2.2 分级
  "produced_at": "ISO8601",
  "schema_version": "1.0"
}
```

### 7.4 消费契约（前端 L1 路由器的判决规则）

| route_confidence | 判决 | 动作 |
|---|---|---|
| ≥ **0.7**（THRESHOLD_HIGH） | **高置信** | 直接 **L1** 零 token 秒答（用户问题被认知库明确覆盖） |
| < **0.7** | **低置信** | 推给**路由器** → 转 **L2**；携带 `l1_intent_hint = intent_hint` 作为 L2 上下文 |

**补充规则**:
- `case_density < 3` 时即使 match_score 高**也不得直落 L1**——覆盖不足易误答，按 §7.3 降权后通常落入 L2；
- `intent_hint` 非空时，L1 先按该意图走**注册表 canHandle** 兜底（对应 SPEC-v1.3 §5 第 3 条）；命中即 L1 直答（此时信号作**闸门**而非**路由源**）；
- 转 L2 时 `intent_hint` 随请求透传（对应 SPEC-v1.3 §4.2-3「C-drive 与 L1 路由器交接协议」，即已落地的 `l1_intent_hint`）。

### 7.5 与现有实现的衔接（不新建系统）

| 事项 | 现状 | 本对接要求 |
|---|---|---|
| `evaluate_match`（C3） | §2.2.1 已实现 | 直接复用，输出即 `match_score / case_density` |
| `jev_gate`（C4） | §2.4.1 已实现（纯规则） | 取其**预测误差分支**输出 `prediction_error`；C-Drive 侧仍走完整裁决（CONTINUE/REDO…） |
| 前端路由器置信度门控 | SPEC-v1.3 §5 第 4 条，当前为**注册表侧静态置信度** | 由本 §7 信号**替换**静态值，落地 SPEC-v1.3 §6-待推进项 2「认知系统接口暴露」 |
| `l1_intent_hint` 交接 | SPEC-v1.3 §6-待推进项 4 标注已落地 | 本 §7 明确其取值来源 = C3 `intent_hint` |

**调用时序（前端层）**:
```
用户请求 → 路由器意图预测(S层+关键词兜底) → intent
         → [调用 L0 认知] recall(context=message) → memories[]
         → C3.evaluate_match(memories) → (match_score, case_density)
         → C4.prediction_error(match_score, actual) → route_confidence
         → 判决: ≥0.7 → L1 直答 ; <0.7 → 转 L2(附 l1_intent_hint)
```

### 7.6 FAIL-OPEN 降级契约（无大模型 / 认知不可用）

> 与 SPEC-v1.3「无大模型渐进降级」一致：**认知信号缺失不得阻塞路由**。

| 异常 | 降级行为 |
|---|---|
| recall 超时 / 返回空 | `match_score=0, case_density=0` → `route_confidence=0` → 按「未命中」转 L2（不阻塞） |
| C4 元认知层不可用 | 退化为**纯 C3 匹配度**（`route_confidence = match_score`），省略预测误差降权 |
| 认知系统整体不可用 | 退化为**注册表侧静态置信度**（SPEC-v1.3 §5 当前实现），路由功能保持可用 |
| 任一字段缺失 | 按默认值补齐（`prediction_error=0.5` 视为未知→不降权；`case_density=0`），**绝不因信号缺失抛错** |

### 7.7 阈值参数表（跨系统统一，禁止各自定义）

| 参数 | 值 | 定义方 | 用途 |
|---|---|---|---|
| THRESHOLD_HIGH | **0.7** | 前端路由器 | route_confidence ≥ 此值 → L1 直答 |
| CASE_DENSITY_MIN | **3** | 前端路由器（对齐 §2.2.2 Tier1 `density ≥ 3`） | 覆盖不足降权门槛 |
| PREDICTION_ERROR_MAX | **0.3** | C4（复用 §2.4.1） | 预测误差超此值 → 降权 0.3 |
| FAST_PATH | `match ≥ 0.8 且 density ≥ 5` | C4（复用 §2.4.1） | 高可信跳过完整裁决 |
| Tier1 路由门限 | `match ≥ 0.7 且 density ≥ 3` | C3（§2.2.2） | 分级路由依据 |

> **一致性硬约束**: 前端路由器**不得**自定义第二套置信度阈值；`THRESHOLD_HIGH` 取 0.7 对齐 C3 §2.2.2 Tier1 门限、`CASE_DENSITY_MIN` 取 3 对齐 Tier1 密度门限——保证「C-Drive 认为高可信」与「前端认为高置信」判定一致，避免同一问题两套结论。

### 7.8 验收对齐（§5 验收标准的扩展项）

| 验收项 | 指标 | 门禁 |
|---|---|---|
| 信号产出契约 | C3/C4 输出符合 §7.3 schema | 硬门禁 |
| 跨消费一致性 | 同一 `memories` 输入下，C-Drive Tier 判定 与 前端 L1/L2 判决 使用同一 `match_score / case_density` | 硬门禁 |
| FAIL-OPEN 降级 | 认知不可用时路由仍可用（转 L2） | 硬门禁 |
| 静态置信度替换 | 前端 §5 第 4 条静态阈值 → C4 信号 | 硬门禁 |
| 零 token | 信号产出全程零 LLM 调用 | 硬门禁 |
