# 二元矛盾推理模型（BCRM）设计稿

**日期**: 2026-07-05
**状态**: v0.2（实现版，已通过回测基线验证）
**类型**: 上层推理层架构设计
**定位**: 只读消费 QMM + L4 + A0，输出推演契约，不修改任何现有组件
**命名**: BCRM（Binary Contradiction Reasoning Model）
**核心算法**: 唯物辩证法 + 易经六十四卦推理系统
**上游约束**: `constraints/qmm/` 全部铁律（0.1~0.8）、`constraints/workflows-spec/l4-memory/`

---

## 〇、核心方法论

### 0.1 三层架构

> BCRM 以**数据统计与知识库为核心基础**，以**辩证唯物论为科学理论基础**，以**易经的卜算逻辑为推理计算过程**，推理计算出具体结果。

```
第三层：推理计算过程（易经卜算逻辑）    → 如何算
第二层：科学理论基础（辩证唯物论）      → 为什么这样算
第一层：核心基础（数据统计 + 知识库）   → 算什么
```

三层缺一不可：缺基础=玄学，缺理论=数字游戏，缺过程=无法计算。

### 0.2 核心认知：推理过程而非预测结果

> **本质上交易不是百分百，BCRM 用的是易经的推理过程，不是预测结果。**

易经的价值在于：在数据与哲学理论基础上，通过**仪式化的随机机制**（多维数据全息投射，非物理随机），提取当下的时空信息，将其映射到包含 **64 种基本情境**的符号模型中，再结合事物发展的辩证法（阴阳转化、物极必反），为 AI 时代交易者提供**多维度的决策参考框架**。

| 维度 | 预测模型 | BCRM（推理过程）|
|---|---|---|
| 目标 | 预测未来价格 | 推理当下情境与可能演变 |
| 输出 | 单一数值/方向 | 多分支策略 + 概率 |
| 评价标准 | 预测准确率 | 决策质量（盈亏比+胜率）|
| 不确定性 | 视为噪声 | 视为本质，用分支应对 |

详见 [易经价值定位](../../skills/1-TRADE/A8-theory-practice-verification/references/yijing_value_positioning.md)。

---

## 一、定位与边界

### 1.1 一句话定位

BCRM 是一个**以矛盾为推理原语**的上层推理层。它不同于 LLM 的语义推理（token→token），而是以客观市场矛盾为对象，按辩证法步进推演下一行情状态与分支应对策略。

### 1.2 与 LLM 推理的本质区别

| 维度 | LLM 语义推理 | BCRM 矛盾推理 |
|---|---|---|
| 推理原语 | token / 语义相关性 | 二元矛盾（正/反对立统一）|
| 推理依据 | 统计共现 | 辩证法三规律 + 历史记忆 + 回测 + 情景推演 |
| 推理输出 | 文本续接 | next_state + strategy_branches + practice_directive |
| 可解释性 | 弱（黑盒）| 强（每步带哲学依据 + 证据引用）|
| 可回测 | 难 | 可（契约固定，可 walk-forward）|
| 约束 | 无客观规律约束 | 受辩证法规律约束（量变质变/否定之否定）|

### 1.3 边界（强制）

- **只读消费**：QMMOutput / L4 cases+distills+stats / A0 contradiction_list / 知识库 / 回测产物 / 情景推演
- **不修改** A0/QMM/L4 任何现有代码、契约、schema
- **不接管主链**：A1~A9 主链路不变，BCRM 输出经门禁后由 A3/A7 可选消费
- **单入口单契约**：遵循 QMM 铁律 0.7（模块化≠SKILL 拆分），初期只暴露一个入口与一个固定输出契约
- **进化路径**：BCRM 自身改进走 `memory -> evolution -> constraints`，不直接改模型

### 1.4 架构位置

```
┌──────────────────────────────────────────────────────────┐
│  A3 战略合成 / A7 实践（可选消费 BCRM 输出，经门禁）       │
├──────────────────────────────────────────────────────────┤
│  BCRM 二元矛盾推理层（本设计稿，只读消费 ↓）              │
│  ┌──────────────────────────────────────────────────┐    │
│  │ 推理循环：矛盾识别→张力量化→质变判定→正反合裁决→  │    │
│  │           否定之否定→策略分支→实践指令            │    │
│  │ 核心算法：易经六十四卦推理引擎（重卦→动爻→变卦）   │    │
│  └──────────────────────────────────────────────────┘    │
├──────────────────────────────────────────────────────────┤
│  QMM 量化内核契约   │  L4 记忆(cases/distills/stats)      │
│  (trend/mrd/unc)   │  A0 矛盾清单   知识库   回测/情景推演 │
└──────────────────────────────────────────────────────────┘
```

### 1.5 三层架构（数据-哲学-算法）

BCRM 的核心理念：**数据是底层，哲学是指导，易经是算法。**

| 层次 | 内容 | 作用 |
|------|------|------|
| **数据层** | 供需/技术/资金/情绪 四维评分 + 量价指标 | 提供客观市场数据输入 |
| **哲学层** | 唯物辩证法三规律 + 矛盾论 + 黑格尔正反合 | 规定推理的形式和规律约束 |
| **算法层** | 易经六十四卦推理引擎（重卦/动爻/变卦） | 具体的方向计算与置信度评估 |

---

## 二、哲学基础三源整合

> **关键澄清**：三源不是并列拼凑，而是层叠传统。黑格尔发现辩证形式（唯心），马克思/恩格斯做唯物倒转（规律属于自然/社会而非观念），毛泽东发展为具体分析的操作方法。BCRM 同时需要三者，缺一则推理要么无形式、要么无规律、要么无方法。

### 2.1 三源分工

| 源 | 提供什么 | 在 BCRM 中的作用 |
|---|---|---|
| **唯物辩证法**（Marx/Engels）| 动力学规律 | 矛盾如何随时间演化（量变→质变、否定之否定、对立统一、普遍联系）|
| **矛盾论**（毛泽东）| 操作方法 | 如何识别主矛盾、主要方面、转化条件（已蒸馏于 A0）|
| **黑格尔辩证法** | 推理步结构 | 每一步推理的形式：正题→反题→合题（扬弃 Aufheben）|

### 2.2 唯物辩证法三规律在交易中的映射

| 规律 | 原义 | 交易映射 | BCRM 用法 |
|---|---|---|---|
| **对立统一** | 矛盾双方相互依存、相互转化 | 多空/风险收益/长短周期互为前提 | 张力量化：对立双方强度对比 + 转化可能 |
| **量变质变** | 量变积累到阈值引发质变 | 资金流出累积→趋势反转；情绪极端→反转 | 质变判定：累积度超回测阈值→质变即将发生 |
| **否定之否定** | 发展是螺旋，两次否定回到高级阶段 | 上涨→回调→再上涨（更高点）| 螺旋定位：识别当前在否定链的第几环 |

### 2.3 矛盾论操作方法（继承 A0，不重写）

BCRM 直接消费 A0 的 `contradiction_list` 与 `primary_contradiction`，不重新发明矛盾识别。A0 提供的：
- 8 维矛盾分类（C1~C8）
- 4 维评分法选主矛盾
- 矛盾主要方面 → 方向暗示
- 转化条件

BCRM 在此之上做的是：**把 A0 的多维矛盾，收敛为当前推理步的二元对立（正/反），然后按辩证法推演其合题。**

### 2.4 黑格尔正反合推理步

每个推理步的内部结构：

```
正题(Thesis)   = 当前主导方（A0 primary.dominant_side，QMM mrd.direction 佐证）
反题(Antithesis)= 对立面（被压制但蕴含转化力量的一方）
合题(Synthesis) = 扬弃：保留双方的真理性，消除对立 → 下一状态
```

**扬弃（Aufheben）的交易含义**：合题不是折中，而是矛盾运动的结果——
- 量变阶段：合题 = 正题延续（主导方尚稳）
- 质变阶段：合题 = 反题升级 + 螺旋（否定之否定）

### 2.5 三源协同的推理元逻辑

```
唯物辩证法（地）：矛盾是客观的、发展的、螺旋的
    ↓ 规定推理必须遵循的规律
矛盾论（法）：找主矛盾、主要方面、转化条件
    ↓ 提供每步推理的操作内容
黑格尔正反合（步）：正→反→合的形式
    ↓ 给出每步推理的输出结构
BCRM 推理循环：可回测、可解释、fail-closed 的辩证推理
```

---

## 三、输出契约（Contracts First）

> 遵循 QMM 铁律 0.1：只输出固定结论集，不生成长文本；可审计、可追溯。

### 3.1 BCRMOutput 契约

```python
@dataclass
class BCRMOutput:
    version: str = "bcrm-v0.1"
    snapshot_ts: str = ""
    # 版本三元组（遵循 QMM 0.6）
    data_version: str = ""              # L4 cases 切片版本
    feature_def_version: str = ""       # 二元矛盾特征口径版本
    bcrm_version: str = "bcrm-v0.1"

    # 核心推演结论
    contradiction_state: Dict           # 当前主导二元矛盾
    dialectical_step: Dict              # 正反合推理步
    next_state: Dict                    # 推演的下一行情状态
    transformation_trigger: Dict        # 量变→质变转化触发条件
    strategy_branches: List[Dict]       # 分支应对策略
    practice_directive: Dict            # A7 实践指令（知行合一）

    # 元信息
    spiral_position: Dict               # 否定之否定螺旋定位
    uncertainty: float = 1.0            # 0-1
    reason_codes: List[str] = []        # 全英文大写枚举
    evidence_refs: List[str] = []       # 指向 case_id/distill_id/qmm_ts
    philosophy_basis: List[str] = []    # 哲学依据枚举
```

### 3.2 字段细化

```yaml
contradiction_state:
  thesis: "ETF 连续净流入，资金面主导多方"        # 正题
  antithesis: "OI 减仓，杠杆多方未跟进"           # 反题
  dominant_side: "THESIS"                        # THESIS/ANTITHESIS/EQUAL
  tension: 0.62                                  # 张力 0-1
  source_contradiction_id: "CX_001"             # 指向 A0 矛盾清单
  philosophy_basis: ["MAO_CONTRADICTION", "MATERIALIST_DIALECTIC"]

dialectical_step:
  thesis: {...}                                  # 正题详情
  antithesis: {...}                              # 反题详情
  synthesis: "多方延续但动能衰减，进入量变累积期"  # 合题
  adjudication:                                  # 裁决依据
    quantitative_change: true                    # 仍处量变
    qualitative_change: false                    # 未到质变
    spiral_phase: "FIRST_AFFIRMATION"            # 螺旋阶段
  evidence_refs: ["case_2026xxxx", "distill_xxx"]

next_state:
  direction: "UP"                                # UP/DOWN/FLAT/TRANSITIONING
  confidence: 0.68                               # 0-1
  horizon: "中期"                                # 短/中/长
  derivation: "量变阶段，正题延续；质变未触发"     # 推导说明

transformation_trigger:
  condition: "ETF 连续 3 日净流出 且 OI 周环比降 5%"
  probability: "MODERATE"                        # LOW/MODERATE/HIGH
  accumulation: 0.45                             # 量变累积度 0-1
  threshold: 0.70                                # 回测所得质变阈值
  monitoring_point: "每日 ETF 流量 + OI 周环比"

strategy_branches:
  - id: "B1"
    condition: "量变延续，质变未触发"
    action: "顺主矛盾做多，标准仓位"
    position_modifier: 1.0
    stop_condition: "transformation_trigger 触发"
  - id: "B2"
    condition: "transformation_trigger 触发"
    action: "减仓 50%，启动对冲"
    position_modifier: 0.5
    rationale: "质变发生=否定之否定启动"
  - id: "B3"
    condition: "螺旋定位=SECOND_NEGATION"
    action: "警惕趋势加速反转，止损上移"
    position_modifier: 0.3
    rationale: "否定之否定第二环=螺旋将完成"

practice_directive:
  action: "执行 B1 主路径"
  verification_condition: "持仓 48h 内 PnL 不低于 -1.5%"
  feedback_loop: "A7 实践后结果回写 L4 为新 case"
  theory_practice_alignment_score: 0.0           # A7/A8 评分，初始 0

spiral_position:
  phase: "FIRST_AFFIRMATION"                     # 见 3.3
  negation_count: 0                              # 历史否定次数
  historical_analogy_ref: "case_2025xxxx"

uncertainty: 0.42
reason_codes: ["BULLISH_ALIGNMENT", "QUANTITATIVE_CHANGE_PHASE"]
evidence_refs: ["case_20260628_a", "distill_2026q2_03", "qmm_snap_20260704"]
philosophy_basis: ["HEGELIAN", "MAO_CONTRADICTION", "MATERIALIST_DIALECTIC"]
```

### 3.3 螺旋阶段枚举（否定之否定）

```
FIRST_AFFIRMATION     正题确立（趋势形成）
FIRST_NEGATION        第一次否定（回调/反弹）
SECOND_NEGATION       否定之否定（再创新高/低，螺旋完成→可能加速）
```

由 L4 历史 distills 的否定链比对得出。

### 3.4 六十四卦推理结果（HexagramResult）

```python
@dataclass
class HexagramResult:
    hexagram_name: str          # 卦名英文（如 "qian"）
    hexagram_name_cn: str       # 卦名中文（如 "乾为天"）
    inner_gua: str              # 内卦（下卦）
    outer_gua: str              # 外卦（上卦）
    gua_ci: str                 # 卦辞
    tuan_zhuan: str             # 彖传
    xiang_zhuan: str            # 象传
    yao_results: List[Dict]     # 六爻结果（含动爻标记）
    changing_yaos: List[int]    # 动爻位置（1-6）
    changed_hexagram: str       # 变卦卦名
    changed_hexagram_cn: str    # 变卦卦名中文
    overall_meaning: str        # 整体含义（市场解读）
    direction_hint: str         # 方向暗示 UP/DOWN/FLAT/TRANSITIONING
    confidence: float           # 易经推理置信度 0-1
```

---

## 四、易经六十四卦推理算法

> 核心理念：**易经是算法**。六十四卦构成结构化推理系统，每卦代表一种市场状态，动爻指示趋势转折点，变卦预测未来演化方向。

### 4.1 算法总览

```
四维评分 → 重卦（内外卦组合）→ 动爻识别 → 变卦推演 → 综合方向推理
                                      ↓
                              置信度多因子加权
```

### 4.2 八卦基础（经卦）

八卦是构成六十四卦的基本单元，每个经卦由三爻组成：

| 卦名 | 符号 | 二进制 | 自然象征 | 五行 | 市场含义 |
|------|------|--------|---------|------|---------|
| 乾（qian） | ☰ | 111 | 天 | 金 | 强势上涨、纯阳 |
| 坤（kun） | ☷ | 000 | 地 | 土 | 强势下跌、纯阴 |
| 震（zhen） | ☳ | 001 | 雷 | 木 | 启动、反弹 |
| 巽（xun） | ☴ | 110 | 风 | 木 | 缓涨、渗透 |
| 坎（kan） | ☵ | 010 | 水 | 水 | 危险、下跌 |
| 离（li） | ☲ | 101 | 火 | 火 | 明丽、上涨 |
| 艮（gen） | ☶ | 100 | 山 | 土 | 止跌、震荡 |
| 兑（dui） | ☱ | 011 | 泽 | 金 | 喜悦、顶部 |

二进制编码规则：阳爻=1，阴爻=0，从下到上（初爻→上爻），初爻在最低位。

### 4.3 重卦算法（六十四卦生成）

内卦（下卦）代表**内在本质**，由供需 + 技术面计算：
- 初爻（第1爻）：供需评分 > 低阈值（0.35）→ 阳
- 二爻（第2爻）：技术评分 > 中阈值（0.55）→ 阳
- 三爻（第3爻）：供需+技术综合 > 高阈值（0.65）→ 阳

外卦（上卦）代表**外在环境**，由资金 + 情绪面计算：
- 四爻（第4爻）：资金评分 > 低阈值（0.35）→ 阳
- 五爻（第5爻）：情绪评分 > 中阈值（0.55）→ 阳
- 上爻（第6爻）：资金+情绪综合 > 高阈值（0.65）→ 阳

三爻组合为八卦，内外卦组合为六十四卦（8×8=64）。

### 4.4 动爻识别算法（变爻）

动爻代表市场中的变化力量，是趋势转折的信号。识别依据：

| 因素 | 动爻触发条件 | 对应爻位 |
|------|-------------|---------|
| **价格位置** | 价格在底部（<0.3）→ 初爻动；价格在顶部（>0.7）→ 上爻动 | 1 / 6 |
| **波动率** | 波动率 > 0.7 → 二爻/五爻动 | 2 / 5 |
| **量比** | 量比 > 1.5 → 三爻/四爻动 | 3 / 4 |

动爻数量含义：
- 0 动爻：趋势稳定，本卦为主
- 1-2 动爻：小幅变化，变卦为辅
- 3-4 动爻：大幅变化，变卦权重上升
- 5-6 动爻：剧烈反转，变卦主导

### 4.5 变卦算法

将本卦的动爻翻转（阳变阴、阴变阳），得到变卦。变卦代表：
- 未来可能演化的市场状态
- 当前趋势的潜在转折方向
- 矛盾转化后的新状态

### 4.6 综合方向推理（五维加权投票）

方向不是单一卦象决定，而是五个维度的加权投票：

| 维度 | 权重 | 计算方式 |
|------|------|---------|
| 四维评分均值 | 0.35 | 供需+技术+资金+情绪的平均分 > 0.55 → UP；< 0.45 → DOWN |
| 均线排列 | 0.25 | MA5 > MA10 > MA20 → UP；MA5 < MA10 < MA20 → DOWN；否则 → FLAT |
| 卦象方向_hint | 0.20 | 本卦的 direction_hint 字段 |
| 变卦方向 | 0.15 | 本卦与变卦方向不一致 → TRANSITIONING；否则取变卦方向 |
| 动量方向 | 0.05 | 短期动量方向 |

决策规则：
- 转折信号强（变卦与本卦方向不一致 + 权重差 < 0.15）→ TRANSITIONING
- UP 权重最大 → UP
- DOWN 权重最大 → DOWN
- 否则 → FLAT

### 4.7 置信度计算（六因子）

```
confidence = base × yao_factor × trend_factor
           × consistency_factor × dir_factor × deviation_factor
```

| 因子 | 说明 | 范围 |
|------|------|------|
| base | 卦象基础置信度（0.6-0.85） | 卦象固有属性 |
| yao_factor | 动爻惩罚：0动=1.0, 1动=0.95, 2动=0.85, 3动=0.75, 4+动=0.65 | 0.65-1.0 |
| trend_factor | 趋势强度加成：0.6 + 0.4 × trend_strength | 0.6-1.0 |
| consistency_factor | 四维评分一致性：1 - min(方差×4, 0.5)，然后 0.7 + 0.3 × consistency | 0.7-1.0 |
| dir_factor | 方向明确性：UP/DOWN=1.0, FLAT=0.85, TRANSITIONING=0.75 | 0.75-1.0 |
| deviation_factor | 信号偏离度：0.8 + 0.2 × |avg_score-0.5|×2 | 0.8-1.0 |

### 4.8 六十四卦知识库

64 卦每卦包含：
- **卦辞（gua_ci）**：易经原文卦辞
- **彖传（tuan_zhuan）**：卦义解释
- **象传（xiang_zhuan）**：卦象象征
- **六爻爻辞**：每爻的原文与小象传
- **direction_hint**：市场方向暗示
- **confidence_base**：基础置信度
- **market_meaning**：市场含义解读
- **risk_level**：风险等级（low/medium/high）

---

## 五、推理循环（核心算法）

> 七步循环，每步可审计、可回测、可降级。
>
> **核心变化（v0.2）**：Step 4 的正反合裁决由易经六十四卦推理引擎主导，辩证法框架提供形式约束，易经提供具体方向计算。

### Step 1: 矛盾识别（矛盾论）

```
输入: A0 contradiction_list + market_snapshot
处理:
  - primary = contradiction_list[0]（取主矛盾）
  - primary_type 映射到正题/反题描述
  - dominant_side 取自 A0
  - 输出 ContradictionState
输出: contradiction_state {thesis, antithesis, dominant_side, tension, source_id, philosophy_basis}
```

**实现说明（v0.2）**：
- 暂无 QMM mrd.direction 与 A0 dominant_side 的冲突校验（待接入 QMM 后补充）
- 正题/反题描述基于矛盾类型映射，支持：supply_demand / trend_countertrend / sentiment_fear_greed / volume_price

### Step 2: 张力量化（对立统一规律）

```
输入: contradiction_state + market_snapshot 四维评分 + memory_cases
处理:
  - base_tension = A0 主矛盾的 tension 字段
  - 计算四维评分的一致性：
    avg_score = (sd + tech + cf + sent) / 4
    variance = Σ(score - avg_score)² / 4
    consistency = 1 - min(variance, 1.0)
  - tension = base_tension × (0.5 + 0.5 × consistency)
  - accumulation：
    - 有记忆 → 历史同向案例比例
    - 无记忆 → 默认 0.5
输出: tension(0-1), accumulation(0-1)
```

**与 v0.1 设计差异**：
- v0.1 设计用 `|F_thesis - F_antithesis| / (F_thesis + F_antithesis)`
- v0.2 实现用基础张力 × 四维评分一致性，更贴合数据驱动原则

### Step 3: 质变判定（量变质变规律）

```
输入: tension + accumulation + qualitative_threshold(默认0.7)
处理:
  - 质变条件：tension > 0.7 AND accumulation > threshold
  - 概率评估：
    - 质变触发 → HIGH
    - 张力>0.6 或 积累>阈值 → MODERATE
    - 否则 → LOW
输出: is_qualitative_change(bool), transformation_trigger
```

**实现说明（v0.2）**：
- 阈值冷启动默认值 0.7（与设计一致）
- 暂未从回测动态更新阈值（Phase 2 基线验证后迭代）
- 质变需同时满足高张力 + 高积累，双重条件

### Step 4: 正反合裁决（黑格尔 + 易经推理）

> **核心变更（v0.2）**：正反合的裁决内容由易经六十四卦推理引擎提供。辩证法提供推理形式（正→反→合），易经提供具体的方向与置信度计算。

```
输入: contradiction_state + 质变判定 + yijing_result
处理:
  - thesis = 主导方描述 + 张力
  - antithesis = 对立面描述 + (1 - 张力)
  - 合题（synthesis）：
    - 量变阶段 → "量变延续，主导方保持：{易经含义}"
    - 质变阶段 → "质变发生，矛盾转向：{易经含义}"
  - adjudication：
    - quantitative_change / qualitative_change 标记
    - 裁决依据文字说明
  - next_state 方向由易经推理结果决定（见第四章）
输出: dialectical_step, next_state {direction, confidence, horizon, derivation}
```

**next_state 判定规则**：
- direction = 易经推理 direction_hint（五维加权投票结果）
- confidence = 易经推理 confidence（六因子加权）
- horizon：动爻 ≤1 → 中期；≤3 → 短期；>3 → 短期（波动剧烈）
- derivation：易经推理 + 质变状态的组合说明

### Step 5: 螺旋定位（否定之否定规律）

```
输入: memory_cases + yijing_result + price_position
处理:
  - 基于价格位置分段：
    - price_position < 0.3 → FIRST_AFFIRMATION（趋势形成）
    - price_position < 0.6 → FIRST_NEGATION（回调/反弹）
    - >= 0.6 → SECOND_NEGATION（再创新高/低）
  - 记忆不足（<3 case）→ 降级为 UNKNOWN
输出: spiral_position {phase, negation_count, historical_analogy_ref}
```

**与 v0.1 设计差异**：
- v0.1 设计：从 L4 distills 比对历史否定链
- v0.2 实现：用 price_position 简化替代，待接入 L4 否定链后升级

### Step 6: 策略分支生成

```
输入: next_state + transformation_trigger + spiral_position + yijing_result
处理:
  - B1 主路径：沿 next_state.direction 顺势操作，position_modifier=1.0
  - B2 对冲路径：质变触发时减仓50%，启动反向对冲，position_modifier=0.5
  - B3 螺旋路径（可选）：SECOND_NEGATION 时，止损上移，position_modifier=0.3
输出: strategy_branches[B1, B2, (B3)]
```

每个分支包含：branch_id / condition / action / position_modifier / stop_condition / rationale

### Step 7: 实践指令（实践论 / A7 知行合一）

```
输入: strategy_branches
处理:
  - 取 B1 主路径为 practice_directive.action
  - 设定验证条件：持仓24h内PnL波动不超过预期范围
  - 反馈闭环：实践结果回写L4为新case
输出: practice_directive {action, verification_condition, feedback_loop, theory_practice_alignment_score}
```

规则：必须可执行、可验证、可回测；不输出则 fail-closed

### 推理循环图

```
   ┌── Step1 矛盾识别(矛盾论) ──────────────────┐
   │                                            │
   │   Step2 张力量化(对立统一)                  │
   │        ↓                                   │
   │   Step3 质变判定(量变质变)                  │
   │        ↓                                   │
   │   Step4 正反合裁决(黑格尔+易经)             │
   │        ↓  （调用易经六十四卦推理引擎）      │
   │   Step5 螺旋定位(否定之否定)                │
   │        ↓                                   │
   │   Step6 策略分支                            │
   │        ↓                                   │
   │   Step7 实践指令(实践论)                    │
   │        ↓                                   │
   └─── 反馈回 L4（新 case）→ 下一轮 ───────────┘
```

---

## 六、失败语义（Fail-Closed）

> 遵循 QMM 铁律 0.2：关键输入缺失/对齐失败 → fail-closed 或显式降级，必须输出 reason_codes + evidence_refs。

### 6.1 Fail-Closed 触发条件（拒绝推理）

| 触发条件 | 处置 | reason_code | 实现状态 |
|---|---|---|---|
| QMM uncertainty > 0.8 | 拒绝推理，返回最小契约 | `HIGH_UNCERTAINTY` | ✅ 已实现 |
| A0 contradiction_list 为空 | 拒绝（A0-IRON-1：空清单=调研失败）| `NO_CONTRADICTION_DATA` | ✅ 已实现 |
| 易经推理置信度 < min_confidence_threshold(0.45) | 拒绝，置信度不足 | `LOW_CONFIDENCE` | ✅ 已实现（v0.2新增）|

### 6.2 降级触发条件（仍输出，标记警告）

| 触发条件 | 处置 | reason_code | 实现状态 |
|---|---|---|---|
| L4 相似 case < 3 | 螺旋定位降级为 UNKNOWN | `INSUFFICIENT_MEMORY` | ⚠️ 部分实现（仅影响螺旋定位）|
| 质变阈值冷启动（用默认值 0.7）| 用默认阈值，标记 | `COLD_START_THRESHOLD` | ⚠️ 未显式标记 |
| spiral 历史否定链不足 | 降级：phase=UNKNOWN | `INSUFFICIENT_NEGATION_HISTORY` | ⚠️ 未显式标记 |
| QMM mrd.direction 与 A0 dominant_side 冲突 | 拒绝 | `CONTRADICTION_UNRESOLVED` | ❌ 待实现（需接入 QMM）|
| 情景推演两路径胜率差 < 5% | 降级：next_state=NEUTRAL | `AMBIGUOUS_SCENARIO` | ❌ 未实现（无情景推演模块）|

### 6.3 其他 Reason Code（状态标记用）

| reason_code | 含义 | 使用场景 |
|---|---|---|
| `BULLISH_ALIGNMENT` | 多方信号一致 | 推理成功，向上方向 |
| `BEARISH_ALIGNMENT` | 空方信号一致 | 推理成功，向下方向 |
| `QUANTITATIVE_CHANGE_PHASE` | 量变阶段 | 推理成功，质变未触发 |
| `QUALITATIVE_CHANGE_TRIGGERED` | 质变已触发 | 推理成功，质变触发 |
| `HIGH_CHAOS` | 高混沌状态 | 市场不确定性极高 |

### 6.4 最小契约（fail-closed 输出）

```python
BCRMOutput(
    next_state={"direction": "UNKNOWN", "confidence": 0, "horizon": "UNKNOWN", "derivation": "fail-closed"},
    uncertainty=1.0,
    reason_codes=[<触发码>],
    evidence_refs=[...],
    # 其余字段为默认空值
)
```

**判断方法**：`output.is_fail_closed() == (next_state.direction == "UNKNOWN")`

---

<<<<<<< HEAD
## 六、变爻机制（实时动态修正）
=======
## 六.5、变爻机制（实时动态修正）
>>>>>>> origin/trae/agent-TBnFsw

> 来源：外部输入评估（千问分析）— 易经精髓之一，BCRM 的关键增量
> 详见 [外部输入评估](../../skills/1-TRADE/A8-theory-practice-verification/references/external_input_evaluation_qwen.md)

<<<<<<< HEAD
### 5.2.1 变爻与卦象转化的区别

| 维度 | 卦象转化（§5.6 已有）| 变爻机制（本节新增）|
=======
### 变爻与卦象转化的区别

| 维度 | 卦象转化（第四章已有）| 变爻机制（本节新增）|
>>>>>>> origin/trae/agent-TBnFsw
|---|---|---|
| 时间尺度 | 渐进（多期累积）| 即时（单期突变）|
| 触发依据 | accumulation ≥ threshold | 微观维度突变 |
| 推理性质 | 预判下一步 | 修正当前判断 |
| 哲学对应 | 量变质变规律 | 变易原则（易经三原则之一）|
| 输出影响 | 转化路径 + 概率 | 即时变卦 + 重新推演 |

**两者互补**：
- 卦象转化：基于历史累积，预判下一步（前瞻）
- 变爻机制：基于实时突变，修正当前判断（即时）

<<<<<<< HEAD
### 5.2.2 变爻触发条件
=======
### 变爻触发条件
>>>>>>> origin/trae/agent-TBnFsw

```python
def detect_yao_change(current_snapshot: Dict, previous_snapshot: Dict,
                      change_threshold: float = 0.4) -> Dict:
    """
    变爻检测：当任一四象维度发生突变时，触发变爻
<<<<<<< HEAD
    
=======

>>>>>>> origin/trae/agent-TBnFsw
    变爻原则（易经）:
      - 初爻变（本质层）：供需突变 → 卦的根本改变
      - 二爻变（表现层）：技术/资金/情绪突变 → 卦的表象改变
      - 三爻变（趋势层）：宏观/微观主导权切换 → 卦的级别改变
<<<<<<< HEAD
    
=======

>>>>>>> origin/trae/agent-TBnFsw
    单爻变 = 小变（卦象微调）
    双爻变 = 中变（卦象转换）
    三爻变 = 大变（卦象完全反转，变卦）
    """
<<<<<<< HEAD
    changes = {
        'bottom': False,  # 初爻（供需）
        'middle': False,  # 二爻（技术+资金+情绪）
        'top': False,     # 三爻（宏观/微观主导）
    }
    
    # 初爻变：供需突变
    sd_change = abs(current_snapshot['supply_demand'] - previous_snapshot['supply_demand'])
    if sd_change >= change_threshold:
        changes['bottom'] = True
    
    # 二爻变：表现层综合突变
    cur_mid = (current_snapshot['technical'] + current_snapshot['capital_flow'] 
               + current_snapshot['market_sentiment']) / 3
    prev_mid = (previous_snapshot['technical'] + previous_snapshot['capital_flow'] 
                + previous_snapshot['market_sentiment']) / 3
    if abs(cur_mid - prev_mid) >= change_threshold:
        changes['middle'] = True
    
    # 三爻变：宏观/微观主导权切换
    cur_macro_dom = abs(current_snapshot['macro']) > abs(current_snapshot['micro'])
    prev_macro_dom = abs(previous_snapshot['macro']) > abs(previous_snapshot['micro'])
    if cur_macro_dom != prev_macro_dom:
        changes['top'] = True
    
    # 变爻等级
    change_count = sum(changes.values())
    if change_count == 0:
        level = 'NO_CHANGE'
    elif change_count == 1:
        level = 'MINOR'   # 小变
    elif change_count == 2:
        level = 'MODERATE' # 中变
    else:
        level = 'MAJOR'    # 大变（变卦）
    
    return {
        'changes': changes,
        'level': level,
        'requires_recast': change_count >= 2,  # 中变以上需重新卜算
    }
```

### 5.2.3 变爻后的处置流程

```python
def handle_yao_change(yao_change: Dict, current_bcrm: BCRMOutput,
                      market_data: Dict) -> BCRMOutput:
    """
    变爻处置：根据变爻等级，决定是否重新卜算
    
    处置原则:
      - NO_CHANGE: 维持当前卦象
      - MINOR: 标记变爻，调整置信度，不重新卜算
      - MODERATE: 重新卜算，标记变爻原因
      - MAJOR: 立即重新卜算，标记为变卦，触发预警
    """
    level = yao_change['level']
    
    if level == 'NO_CHANGE':
        return current_bcrm  # 维持
    
    elif level == 'MINOR':
        # 小变：调整置信度
        current_bcrm.uncertainty = min(1.0, current_bcrm.uncertainty + 0.1)
        current_bcrm.reason_codes.append(f'YAO_MINOR_CHANGE_{list(yao_change["changes"].keys())[0].upper()}')
        return current_bcrm
    
    elif level in ('MODERATE', 'MAJOR'):
        # 中变/大变：重新卜算
        new_bcrm = run_bcrm_pipeline(market_data)  # 重新走八步推理
        new_bcrm.reason_codes.append(f'YAO_RECAST_{level}')
        if level == 'MAJOR':
            new_bcrm.reason_codes.append('HEXAGRAM_TRANSFORMATION')  # 变卦
        return new_bcrm
    
    return current_bcrm
```

### 5.2.4 变爻机制的工程实现

变爻机制作为推理循环的**动态修正层**，位于八步推理循环之外：

```
┌─────────────────────────────────────────────┐
│  八步推理循环（太极→...→乾坤）              │
│  产出 BCRMOutput                            │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  变爻监测层（持续运行）                      │
│  检测四象维度突变 → 触发变爻                │
└──────────────────┬──────────────────────────┘
                   ↓
┌─────────────────────────────────────────────┐
│  变爻处置（NO_CHANGE/MINOR/MODERATE/MAJOR）  │
│  决定是否重新卜算                           │
└─────────────────────────────────────────────┘
```

### 5.2.5 变爻与辩证法的关系

变爻机制不是孤立的，而是与辩证法三规律对应：
=======
```

### 变爻等级与处置

| 变爻等级 | 爻变数 | 处置方式 |
|---------|--------|---------|
| NO_CHANGE | 0 | 维持当前卦象 |
| MINOR | 1 | 标记变爻，调整置信度（+0.1不确定性），不重新卜算 |
| MODERATE | 2 | 重新卜算，标记变爻原因 |
| MAJOR | 3 | 立即重新卜算，标记为变卦，触发预警 |

### 变爻与辩证法的关系
>>>>>>> origin/trae/agent-TBnFsw

| 辩证法规律 | 变爻体现 |
|---|---|
| 对立统一 | 爻变即矛盾双方力量对比变化 |
| 量变质变 | 单爻变=量变，三爻变=质变（变卦）|
| 否定之否定 | 变卦后的新卦象是螺旋的下一环 |

**关键**：变爻机制让 BCRM 具备了**易经的"变易"特性**——卦象不是静态标签，而是动态流转的状态，符合"市场永远在变"的客观规律。

<<<<<<< HEAD
=======
> **实现状态**：v0.2 代码中动爻识别算法（第四章 4.4 节）已实现类似功能，但尚无独立的变爻监测层。待 Phase 3 集成时补充。

>>>>>>> origin/trae/agent-TBnFsw
---

## 七、版本三元组与可复现

> 遵循 QMM 铁律 0.5 / 0.6。

- `data_version`：L4 cases 切片版本（与 QMM 对齐）
- `feature_def_version`：二元矛盾特征口径版本（v0.2 为 `bcrm-fd-v0.2`）
- `bcrm_version`：推理模型版本（v0.2 为 `bcrm-v0.2`）

**可复现约束**：
- 事件为事实源：L4 cases 不可变；BCRM 输出为可再生成产物
- 黄金样本回放集：复用 QMM 的黄金样本集（多 regime + 黑天鹅段）作为回归门禁输入
- 纯确定性计算（Phase 1）：相同输入必然相同输出

---

<<<<<<< HEAD
## 八、工程实践借鉴（来自 GitHub 调研）

> 调研了 30+ 个开源项目后，以下工程实践经评估为"必须借鉴"，直接整合进 BCRM。
> 详见 [外部输入评估](../../skills/1-TRADE/A8-theory-practice-verification/references/external_input_evaluation_qwen.md) 调研附件。

### 8.1 Seeded PRNG + Replay（确定性卜算）

**借鉴来源**：seeded-iching-engine
**哲学基础**："确定性伪装成随机性"——卦象生成是确定性的，"随机性"来自输入数据本身。

**实现方案**：

```python
def mulberry32(seed: int) -> Callable[[], float]:
    """
    Mulberry32 伪随机数生成器，种子确定则序列完全确定
    用于 BCRM 的"太极→两仪→四象→八卦"展开
    same seed → same hexagram → same output，every time
    """
    a = seed & 0xFFFFFFFF
    def next():
        nonlocal a
        a = (a + 0x6D2B79F5) & 0xFFFFFFFF
        t = a
        t = (t ^ (t >> 15)) * (t | 1)
        t ^= t + ((t ^ (t >> 7)) * (t | 61))
        return ((t ^ (t >> 14)) & 0xFFFFFFFF) / 4294967296
    return next

def compute_bcrm_seed(market_snapshot: Dict) -> int:
    """
    从市场数据快照生成 BCRM 推理的种子
    种子由当下时空信息的哈希决定——这才是"易经提取当下时空"的真正含义
    
    种子构成:
      - 时间戳（时）
      - 四象评分（空）
      - L4 相似 case 指纹（历史）
    """
    seed_components = [
        str(market_snapshot['timestamp']),
        str(round(market_snapshot['supply_demand'], 4)),
        str(round(market_snapshot['technical'], 4)),
        str(round(market_snapshot['capital_flow'], 4)),
        str(round(market_snapshot['market_sentiment'], 4)),
        str(market_snapshot.get('similar_case_fingerprint', '')),
    ]
    seed_str = '|'.join(seed_components)
    return zlib.crc32(seed_str.encode()) & 0xFFFFFFFF
```

**replay 函数**：

```python
def replay_bcrm(seed: int) -> BCRMOutput:
    """
    从 seed 重放整个推理链
    用于: 回测验证、审计追溯、回归测试
    
    哲学含义: 易经的"卜"不是预测未来，而是"当下的全息投射"——
    同一时刻的同一组数据，必然得到同一卦象，这是可验证的
    """
    prng = mulberry32(seed)
    # 用 prng 驱动八步推理的每一步"随机"选择
    # （实际上是确定性的，只是从 seed 展开）
    # ...
    return bcrm_output
```

### 8.2 LangGraph 状态机编排（推理流程）

**借鉴来源**：TradingAgents
**适用场景**：BCRM 的八步推理循环 + 变爻机制

**状态机节点设计**：

```python
# BCRM 状态机节点（对应八步推理 + 变爻修正）
NODES = [
    "taiji",           # Step 1: 太极混沌度
    "liangyi",         # Step 2: 两仪判定
    "sixiang",         # Step 3: 四象评分
    "bagua",           # Step 4: 八卦判定
    "zhibian",         # Step 5: 质变判定（量变质变）
    "zhengfanhe",      # Step 6: 正反合裁决
    "spiral",          # Step 7: 螺旋定位
    "qiankun",         # Step 8: 乾坤判断
    "strategy",        # 策略分支生成
    "practice",        # 实践指令
]

# 边（流转条件）
EDGES = [
    ("taiji", "liangyi"),          # 混沌度 < 0.7
    ("taiji", "END_FAIL"),         # 混沌度 > 0.7（fail-closed）
    ("liangyi", "sixiang"),
    ("sixiang", "bagua"),
    ("bagua", "zhibian"),
    ("zhibian", "zhengfanhe"),
    ("zhengfanhe", "spiral"),
    ("spiral", "qiankun"),
    ("qiankun", "strategy"),
    ("strategy", "practice"),
    ("practice", "END_SUCCESS"),
]

# 变爻机制：从任意节点跳到 taiji 重新卜算（变卦）
YAO_CHANGE_EDGES = [
    ("sixiang", "taiji"),     # 中变以上 → 重卜
    ("bagua", "taiji"),       # 变卦 → 重卜
]
```

**为什么用状态机**：
1. **可追溯**：每个节点的输入输出都可记录，推理链完整可审计
2. **可重放**：给定 seed 和输入，状态机路径完全确定
3. **可扩展**：新增节点/边不破坏现有结构
4. **fail-closed 天然支持**：边条件不满足就停在当前节点或跳到 FAIL

### 8.3 符号模板 + 可执行代码（64 卦情境）

**借鉴来源**：FINCHAIN
**适用场景**：64 卦情境建模为参数化符号模板，每个卦配可执行 Python 代码

**模板结构**：

```python
@dataclass
class HexagramTemplate:
    """64 卦情境模板——参数化 + 可执行"""
    hexagram_id: str           # 如 "qian_qian"（乾为天）
    name: str                  # 卦名
    upper_gua: str             # 上卦
    lower_gua: str             # 下卦
    situation: str             # 情境描述
    dialectical_nature: str    # 辩证性质（量变质变阶段/对立统一特征）
    parameters: Dict[str, ParameterSpec]  # 参数规格
    executable: Callable       # 可执行 Python 函数（情境推理）
    output_schema: Dict        # 输出 schema

# 示例：乾为天（纯阳，极致上涨）
QIAN_QIAN_TEMPLATE = HexagramTemplate(
    hexagram_id="qian_qian",
    name="乾为天",
    upper_gua="qian",
    lower_gua="qian",
    situation="纯阳至极，强势上涨，趋势确立",
    dialectical_nature="阳的极限，物极必反，向阴转化的前夜",
    parameters={
        "extreme_level": ParameterSpec(type="float", min=0, max=1, default=0.8),
        "reversal_risk": ParameterSpec(type="float", min=0, max=1, default=0.3),
    },
    executable=execute_qian_qian,  # 可执行函数
    output_schema={"direction": "UP", "confidence": "float", "reversal_risk": "float"}
)

def execute_qian_qian(params: Dict, market_data: Dict) -> Dict:
    """
    乾为天的可执行推理函数
    输入: 参数 + 市场数据
    输出: 结构化推理结果（机器可验证）
    """
    extreme = params.get('extreme_level', 0.8)
    sd_score = market_data['supply_demand']
    
    # 乾卦推理：纯阳至极，但物极必反
    # 1. 确认纯阳：供需、技术、资金、情绪全部为阳
    all_yang = all(market_data[k] > 0.5 
                   for k in ['supply_demand', 'technical', 'capital_flow', 'market_sentiment'])
    
    # 2. 计算物极必反风险
    reversal_risk = extreme * 0.6 + (1 - abs(sd_score - 1.0)) * 0.4
    
    # 3. 输出结构化结果
    return {
        "direction": "UP" if all_yang else "UNCERTAIN",
        "confidence": extreme if all_yang else 0.5,
        "reversal_risk": round(reversal_risk, 4),
        "dialectical_status": "阳的极致，向阴转化前夜",
    }
```

**为什么用符号模板**：
1. **机器可验证**：每个卦的推理都是可执行代码，不是自然语言
2. **可组合**：上卦 + 下卦 = 64 卦，两仪 × 四象 = 八卦，可自由组合
3. **可回测**：每个模板的历史命中率可单独统计
4. **可迭代**：优化单个模板不影响其他模板

### 8.4 Fail-Closed Guardrail（可执行护栏）

**借鉴来源**：GuardAgent
**适用场景**：把 fail-closed 规则翻译为可执行 guardrail 代码

**Guardrail 设计**：

```python
@dataclass
class Guardrail:
    """护栏规则——可执行的 fail-closed 检查"""
    id: str                         # 规则 ID
    name: str                       # 规则名称
    check: Callable[[Dict], bool]   # 检查函数（True=通过，False=触发）
    severity: str                   # FAIL / DEGRADE
    reason_code: str                # 触发时的 reason_code
    evidence_keys: List[str]        # 触发时需要记录的证据字段

# 示例护栏
GUARDRAILS = [
    Guardrail(
        id="gr_high_uncertainty",
        name="QMM 不确定性过高",
        check=lambda d: d.get('qmm_uncertainty', 1.0) <= 0.8,
        severity="FAIL",
        reason_code="HIGH_UNCERTAINTY",
        evidence_keys=["qmm_uncertainty"],
    ),
    Guardrail(
        id="gr_no_contradiction",
        name="矛盾清单为空",
        check=lambda d: len(d.get('contradiction_list', [])) > 0,
        severity="FAIL",
        reason_code="NO_CONTRADICTION_DATA",
        evidence_keys=["contradiction_list_len"],
    ),
    Guardrail(
        id="gr_essence_phenomenon_conflict",
        name="本质与表现严重背离",
        check=lambda d: abs(d.get('supply_demand', 0) - 
                           (d.get('technical', 0) + d.get('capital_flow', 0) + d.get('market_sentiment', 0)) / 3) <= 0.6,
        severity="DEGRADE",
        reason_code="ESSENCE_PHENOMENON_DEVIATION",
        evidence_keys=["supply_demand", "technical", "capital_flow", "market_sentiment"],
    ),
    # ... 更多护栏
]

def run_guardrails(data: Dict) -> Tuple[bool, List[str], List[str]]:
    """
    运行所有护栏，返回 (是否通过, reason_codes, evidence_refs)
    FAIL 级别 → 直接 fail-closed
    DEGRADE 级别 → 降级推理
    """
    passed = True
    reason_codes = []
    evidence_refs = []
    
    for g in GUARDRAILS:
        if not g.check(data):
            reason_codes.append(g.reason_code)
            evidence_refs.extend(g.evidence_keys)
            if g.severity == "FAIL":
                passed = False
    
    return passed, reason_codes, evidence_refs
```

**为什么用 guardrail**：
1. **规则可代码化**：fail-closed 不是说说而已，是可执行代码
2. **分级处理**：FAIL（拒绝）vs DEGRADE（降级），不是一刀切
3. **可审计**：每条护栏的触发记录都是 evidence
4. **可扩展**：新增护栏就是新增 Guardrail 对象

### 8.5 Walk-Forward + Zero-Look-Ahead（严格回测）

**借鉴来源**：Jesse + Walk-Forward Validation Framework
**适用场景**：BCRM 的回测必须做严格 walk-forward，防 look-ahead bias

**回测协议**：

```python
class WalkForwardTester:
    """
    Walk-Forward 回测器
    
    核心原则:
    1. 严格信息集纪律：每个时间点的推理只能用该时间点及之前的数据
    2. 滚动窗口：训练窗口 + 测试窗口，滚动推进
    3. 真实交易成本：滑点、手续费、资金费率全部计入
    4. 可重放：每个推理的 seed 都保存，可逐笔重放
    """
    
    def __init__(self, data: pd.DataFrame, 
                 train_window: int = 252,  # 1 年
                 test_window: int = 20,    # 1 月
                 bcrm_config: Dict = None):
        self.data = data
        self.train_window = train_window
        self.test_window = test_window
        self.bcrm_config = bcrm_config or {}
    
    def run(self) -> Dict:
        """执行 walk-forward 回测"""
        results = []
        n = len(self.data)
        
        for i in range(self.train_window, n - self.test_window, self.test_window):
            train_data = self.data.iloc[i - self.train_window : i]
            test_data = self.data.iloc[i : i + self.test_window]
            
            # 只用 train_data 校准阈值（无 look-ahead）
            calibrated_config = self._calibrate_thresholds(train_data, self.bcrm_config)
            
            # 在 test_data 上逐行推理（每行只用该行及之前的数据）
            for j in range(len(test_data)):
                snapshot = test_data.iloc[:j+1]  # 严格：只用到当前行
                seed = compute_bcrm_seed(snapshot.iloc[-1].to_dict())
                bcrm_out = run_bcrm_with_seed(seed, calibrated_config, snapshot)
                results.append({
                    'timestamp': test_data.index[j],
                    'seed': seed,
                    'bcrm_output': bcrm_out,
                    # 后续用未来数据评估（但推理时不允许用）
                })
        
        return self._evaluate(results)
```

**为什么必须这样做**：
1. **防 look-ahead bias**：这是量化回测最常见的陷阱
2. **真实可信**：walk-forward 比简单 backtest 更接近实盘
3. **可比较**：不同版本的 BCRM 可在同一 walk-forward 协议上对比
4. **契约验证**：验证 BCRMOutput 契约在所有 regime 下都稳定

### 8.6 总结：必须借鉴的 5 大工程实践

| # | 工程实践 | 来源 | BCRM 应用 | 优先级 |
|---|---------|------|----------|--------|
| 1 | seeded PRNG + replay | seeded-iching-engine | 确定性卜算 + 可重放推理链 | P0 |
| 2 | LangGraph 状态机 | TradingAgents | 八步推理 + 变爻机制的编排 | P0 |
| 3 | 符号模板 + 可执行代码 | FINCHAIN | 64 卦情境建模 | P0 |
| 4 | fail-closed guardrail | GuardAgent | 护栏规则可代码化 | P0 |
| 5 | walk-forward + zero-look-ahead | Jesse / WFVF | 严格回测，防 look-ahead | P0 |

这 5 项共同构成 BCRM 的**工程基石**，缺一不可。它们确保了 BCRM 既是"哲学的"，也是"工程的"；既是"推理的"，也是"可验证的"。

---

## 九、与现有系统边界
=======
## 八、与现有系统边界
>>>>>>> origin/trae/agent-TBnFsw

| 系统 | BCRM 关系 | 交互方式 | 实现状态 |
|---|---|---|---|
| **QMM** | 只读消费其输出契约 | QMMOutput → BCRM Step1 输入 | ⚠️ 待接入 |
| **L4 记忆** | 只读 cases/distills/stats；写入仅经 A7 实践闭环 | L4 相似检索 → Step2/3/5；A7 结果 → L4 新 case | ⚠️ Mock 实现 |
| **A0 矛盾论** | 只读 contradiction_list / primary_contradiction | A0 输出 → BCRM Step1 输入 | ✅ 接口已定义 |
| **知识库** | 只读蒸馏规则 / regime 模式 | 知识 → 六十四卦知识库 | ✅ 部分实现 |
| **回测产物** | 只读 evolution/backtest | 阈值 → Step3；胜率 → Step4 | ✅ walk_forward 模块 |
| **情景推演** | 调用 war_game_simulator | Step4 跑两路径 | ❌ 未实现（易经替代）|
| **易经推理引擎** | BCRM 核心算法组件 | 重卦/动爻/变卦 → 方向与置信度 | ✅ 已实现（v0.2新增）|
| **A3 战略** | A3 可选消费 BCRM 输出（经门禁）| BCRM strategy_branches → A3 | ⚠️ 待集成 |
| **A7 实践** | A7 执行 practice_directive | BCRM → A7 → L4 闭环 | ⚠️ 待集成 |
| **A8 验证** | A8 批评 BCRM 推理（知行合一）| A8 评 theory_practice_alignment_score | ⚠️ 待集成 |

**输出目录**（独立，不改 L4）：

```
.workbuddy/memory_l4/bcrm/
├── bcrm_snapshot_{ts}.json        # 完整推理快照
└── signals_index.json             # 最新推理索引
```

---

<<<<<<< HEAD
## 十、落地阶段

> 遵循 QMM 铁律 0.3（先确定性基线）/ 0.4（Backtest as Gate）。
> 工程实践按 P0/P1/P2/P3 优先级落地（来自 GitHub 调研结论）。

### 10.1 阶段总览

| 阶段 | 内容 | 依赖 | 产物 |
|---|---|---|---|
| **Phase 0（本轮）** | 设计稿 + 契约定义 + 理论蒸馏 | 无 | 本文档 + 6 份理论蒸馏文档 |
| **Phase 1** | 确定性 baseline 实现（纯 Python，零依赖）| QMM Phase A 收敛 | `scripts/memory_l4/bcrm/` 单入口 |
| **Phase 2** | 回测门禁：walk-forward 验证 next_state 胜率 | Phase 1 | 胜率报告 |
| **Phase 3** | 通过门禁后，A3/A7 可选消费 BCRM 输出 | Phase 2 通过 | 集成 |
| **Phase 4** | 引入学习型权重 / LLM 增强（可选）| Phase 2 显著优于基线 | 可选 |
=======
## 九、工程实践借鉴（来自 GitHub 调研）

> 调研了 30+ 个开源项目后，以下工程实践经评估为"必须借鉴"，直接整合进 BCRM。
> 详见 [外部输入评估](../../skills/1-TRADE/A8-theory-practice-verification/references/external_input_evaluation_qwen.md) 调研附件。

### 9.1 Seeded PRNG + Replay（确定性卜算）
>>>>>>> origin/trae/agent-TBnFsw

**借鉴来源**：seeded-iching-engine
**哲学基础**："确定性伪装成随机性"——卦象生成是确定性的，"随机性"来自输入数据本身。

核心思想：从市场数据快照生成种子，种子确定则卦象确定，实现可重放的推理链。

### 9.2 状态机编排（推理流程）

**借鉴来源**：TradingAgents / LangGraph
**适用场景**：BCRM 的推理循环 + 变爻机制

状态机节点对应推理步骤，边条件对应 fail-closed 规则，变爻机制可从任意节点跳回重新卜算。

### 9.3 符号模板 + 可执行代码（64 卦情境）

**借鉴来源**：FINCHAIN
**适用场景**：64 卦情境建模为参数化符号模板，每个卦配可执行 Python 代码

每个卦都是可执行函数而非自然语言描述，确保机器可验证、可组合、可回测。

### 9.4 Fail-Closed Guardrail（可执行护栏）

**借鉴来源**：GuardAgent
**适用场景**：把 fail-closed 规则翻译为可执行 guardrail 代码

规则可代码化、分级处理（FAIL/DEGRADE）、可审计、可扩展。已在 [guardrail.py](file:///workspace/scripts/memory_l4/bcrm/guardrail.py) 中实现基础版本。

### 9.5 Walk-Forward + Zero-Look-Ahead（严格回测）

**借鉴来源**：Jesse / Walk-Forward Validation Framework
**适用场景**：BCRM 的回测必须做严格 walk-forward，防 look-ahead bias

已在 [walk_forward.py](file:///workspace/scripts/memory_l4/bcrm/walk_forward.py) 中实现基础版本，包含滚动窗口、方向打标、合成数据生成。

### 9.6 总结：必须借鉴的 5 大工程实践

| # | 工程实践 | 来源 | BCRM 应用 | 实现状态 |
|---|---------|------|----------|---------|
| 1 | seeded PRNG + replay | seeded-iching-engine | 确定性卜算 + 可重放推理链 | ⚠️ 部分（确定性计算已有，seed 机制待补）|
| 2 | 状态机编排 | TradingAgents | 推理循环 + 变爻机制 | ⚠️ 部分（七步循环已有，状态机待补）|
| 3 | 符号模板 + 可执行代码 | FINCHAIN | 64 卦情境建模 | ✅ 已实现（sixty_four_guas.py）|
| 4 | fail-closed guardrail | GuardAgent | 护栏规则可代码化 | ✅ 已实现（guardrail.py）|
| 5 | walk-forward + zero-look-ahead | Jesse / WFVF | 严格回测，防 look-ahead | ✅ 已实现（walk_forward.py）|

### 10.2 Phase 1 工程实践落地优先级

<<<<<<< HEAD
Phase 1 内部分为 P0/P1/P2 三级，严格按顺序：
=======
## 十、配套模块

### 9.1 Guardrail（护栏）

**文件**：`scripts/memory_l4/bcrm/guardrail.py`

职责：输入验证和数据质量检查，确保 BCRM 推理的输入满足最低质量要求。

| 检查项 | 类型 | 说明 |
|--------|------|------|
| 市场快照必填字段 | warning | price / volume 缺失时警告 |
| 矛盾列表数量 | fail | 少于 min_contradictions(=1) 时失败 |
| QMM 不确定性 | fail | uncertainty > max_uncertainty(=0.8) 时失败 |
| 价格数据有效性 | fail | price <= 0 时失败 |

输出：`GuardResult { passed, fail_reasons[], warnings[] }`

### 9.2 Walk-Forward 回测引擎

**文件**：`scripts/memory_l4/bcrm/walk_forward.py`

职责：通过滚动窗口回测验证 BCRM 推理的方向准确率。

#### 核心流程

```
滑动窗口:
  [ 训练窗口 ][ 测试窗口 ]
  ^^^^^^^^^^^^ ^^^^^^^^^^
  train_size  test_size
  →→→→→→→→→→→→ step_size →→→
```

#### 关键函数

| 函数 | 说明 |
|------|------|
| `run_walk_forward()` | 执行 walk-forward 回测 |
| `run_bcrm_backtest()` | BCRM 专用回测入口 |
| `build_bcrm_predict_fn()` | 构建 BCRM 预测函数 |
| `generate_synthetic_data()` | 生成合成测试数据（bull/bear/ranging 三态） |
| `default_direction_label()` | 默认方向打标函数 |

#### 方向打标规则

用未来 5 根 K 线均价与当前价比较：

| 预测方向 | 打标正确条件 |
|---------|-------------|
| UP | 未来均价 > 当前价 × 1.001 |
| DOWN | 未来均价 < 当前价 × 0.999 |
| FLAT | 未来均价在 ±0.3% 以内 |
| TRANSITIONING | 近期趋势与未来趋势相反 |

#### 合成数据生成

- 三种市场状态：bull / bear / ranging，每 60 根切换
- Bull：drift=+0.3%，vol=0.8%
- Bear：drift=-0.3%，vol=1.0%
- Ranging：drift=0，vol=0.5%
- 四维评分围绕 regime 中心值加独立高斯噪声

### 9.3 Backtest Gate（回测门禁）

**文件**：`scripts/memory_l4/bcrm/backtest_gate.py`

职责：验证 BCRM 是否达到上线门槛（仿 QMM 双轨门禁）。

#### 门禁指标

| 指标 | 默认阈值 | 说明 |
|------|---------|------|
| 方向准确率 | 0.55 | next_state.direction 正确率 |
| 分 Regime 准确率 | 0.50 | 每个 regime 都需达到 |
| Fail-closed 率 | 0.40 | 不能超过 40% |
| 最少有效样本 | 20 | 有效预测样本数 |

#### 输出

```python
GateResult {
    passed: bool
    metrics: BacktestMetrics {
        total_bars, correct_predictions, direction_accuracy,
        fail_closed_count, avg_confidence,
        regime_stats: {regime → {accuracy, total}},
        gua_stats: {gua → {accuracy, total}},
        hexagram_stats: {hex → {accuracy, total}},
    }
    reasons: List[str]
}
```

### 9.4 其他配套模块

| 模块 | 文件 | 职责 |
|------|------|------|
| **Knowledge Base** | `knowledge_base.py` | 八卦知识、技术知识、交易规则 |
| **Memory Adapter** | `memory_adapter.py` | L4 记忆检索适配（含 Mock 实现）|
| **Case Writer** | `case_writer.py` | 推理结果写回 L4 案例 |
| **A-Series Bridge** | `a_series_bridge.py` | A股市场专属适配 |

---

## 十一、落地阶段

> 遵循 QMM 铁律 0.3（先确定性基线）/ 0.4（Backtest as Gate）。

| 阶段 | 内容 | 状态 | 产物 |
|---|---|---|---|
| **Phase 0** | 设计稿 + 契约定义 | ✅ 完成 | v0.1 设计稿 |
| **Phase 1** | 确定性 baseline 实现（易经六十四卦 + 七步推理 + 输出契约）| ✅ 完成 | `scripts/memory_l4/bcrm/` 13 个模块 |
| **Phase 2** | 回测门禁：walk-forward 验证 next_state 胜率 | ✅ 基线通过 | 方向准确率 ~64%（合成数据）|
| **Phase 3** | 通过门禁后，A3/A7 可选消费 BCRM 输出 | ⏳ 待启动 | 集成到主链路 |
| **Phase 4** | 引入学习型权重（仅当 Phase 2 增量稳定）| ⏳ 待启动 | 可选 |

**收敛判断**（仿 QMM 双轨）：
- Phase 2 next_state 胜率 > 55% 且跨 regime 稳定 → 进入 Phase 3
- 否则 → 退回优化，BCRM 不进入线上消费链路

**v0.2 基线回测结果**（合成数据，500 bars，3 种 regime）：
- 方向准确率：~64%（高于 55% 门槛）
- 卦象覆盖：八卦 7/8，六十四卦 10+ 个
- Fail-closed 率：~42%（待优化覆盖率）
- 多种子稳定性：64%-69% 区间

---

## 十二、开放问题（待你定夺）
>>>>>>> origin/trae/agent-TBnFsw

#### P0（必须先做，工程基石）— 5 项

| # | 工程实践 | 来源 | 说明 |
|---|---------|------|------|
| 1 | seeded PRNG + replay | seeded-iching-engine | Mulberry32，same seed → same output |
| 2 | LangGraph 状态机编排 | TradingAgents | 八步推理 + 变爻机制的状态机实现 |
| 3 | 符号模板 + 可执行代码 | FINCHAIN | 八卦（先 8 卦，后 64 卦）参数化模板 |
| 4 | fail-closed guardrail | GuardAgent | 护栏规则可执行代码化 |
| 5 | walk-forward 框架 | Jesse / WFVF | 严格信息集纪律，防 look-ahead |

**P0 通过标准**：
- 给定 seed 和输入，replay 输出与原始输出逐字段一致
- 状态机覆盖 10 个节点 + 变爻回边，路径可记录
- 8 卦符号模板各有可执行函数
- guardrail 覆盖 5+ 条 FAIL 级规则
- walk-forward 跑通 QMM 黄金样本集

#### P1（核心推理功能）— 5 项

| # | 内容 | 来源 | 说明 |
|---|-----|------|------|
| 6 | 八步推理循环完整实现 | 设计稿 §四 | 太极→两仪→四象→八卦→质变→正反合→螺旋→乾坤 |
| 7 | 对立统一规律（正反合裁决）| Hegelion | Thesis→Antithesis→Synthesis 三阶段 |
| 8 | 量变质变规律（卦象转化 + 变爻）| 设计稿 §五之二 | accumulation + threshold + 三爻变 |
| 9 | 否定之否定规律（螺旋定位）| 设计稿 §5.7 | FIRST_AFFIRMATION / FIRST_NEGATION / SECOND_NEGATION |
| 10 | BCRMOutput 结构化输出 | 设计稿 §三 | 契约固定，可 JSON 序列化 |

#### P2（增强能力）— 4 项

| # | 内容 | 来源 | 说明 |
|---|-----|------|------|
| 11 | L4 记忆接入（相似 case 检索）| 设计稿 §七 | cases/distills/stats 作为事实源 |
| 12 | 知识库接入 | 设计稿 §七 | 蒸馏规则 + regime 模式 |
| 13 | 情景推演集成（war_game）| 设计稿 §5.4 | 两条路径模拟 |
| 14 | 回测评估仪表盘 | Walk-Forward Framework | 胜率 + 辩证一致性 + 跨 regime 稳定性 |

#### P3（后期 LLM 化，可选）

| # | 内容 | 来源 | 条件 |
|---|-----|------|------|
| 15 | LoRA 微调金融推理 LLM | FinGPT | Phase 2 胜率 > 60% |
| 16 | 过程奖励模型（PRM）| OpenR / Trading-R1 | Phase 2 胜率 > 60% |
| 17 | 多 LLM backend 抽象 | Hegelion | 按需 |
| 18 | 64 卦扩展 | 易经蒸馏 | Phase 2 胜率 > 55% 且 8 卦稳定 |

### 10.3 Phase 2 回测门禁标准

| 指标 | 阈值 | 说明 |
|---|---|---|
| qiankun_judgment 方向胜率 | > 55% | 跨 regime 稳定 |
| transformation_trigger 命中率 | > 50% | 质变触发后 5 个 bar 内实际反转 |
| fail-closed 覆盖率 | < 30% | UNKNOWN 占比不超过 30% |
| 辩证一致性 | > 0.7 | 推理过程与辩证法三规律的符合度（参考 SIEV ΔDS）|
| 最大回撤 | < 基线的 80% | 风险控制优于基线 |

---

<<<<<<< HEAD
## 十一、开放问题与决议

### 11.1 核心算法问题（已决议）

#### 问题 1：螺旋阶段判定算法 ✅ 已决议

**问题**：Step 5 如何从 L4 distills 比对否定链？需要定义"否定"的形式化判据。

**决议方案**：**三维度综合判据**（价格反转 40% + 矛盾主导方反转 35% + 卦象翻转 25%）

**形式化定义**：

```python
def detect_negation(current_state: Dict, last_turning_point: Dict,
                    historical_cases: List) -> Tuple[bool, float]:
    """
    否定判定：综合三个维度判定是否发生"否定"
    
    三维度:
      1. 价格反转（40%）：从最近转折点反转幅度
      2. 矛盾主导方反转（35%）：主矛盾的主要方面切换
      3. 卦象翻转（25%）：八卦状态从阳卦翻转到阴卦或反之
    
    返回: (是否否定, 综合得分)
    """
    # 维度 1：价格反转
    price_reversal = abs(current_state['price'] - last_turning_point['price']) / last_turning_point['price']
    price_score = min(1.0, price_reversal / 0.05)  # 5% 反转 = 满分
    price_score *= 0.40
    
    # 维度 2：矛盾主导方反转
    cur_dominant = current_state['primary_contradiction_aspect']
    prev_dominant = last_turning_point['primary_contradiction_aspect']
    contradiction_reversed = (cur_dominant != prev_dominant)
    contradiction_score = (1.0 if contradiction_reversed else 0.0) * 0.35
    
    # 维度 3：卦象翻转
    cur_gua_yin_yang = get_gua_yin_yang(current_state['bagua'])  # 'yang' or 'yin'
    prev_gua_yin_yang = get_gua_yin_yang(last_turning_point['bagua'])
    gua_flipped = (cur_gua_yin_yang != prev_gua_yin_yang)
    gua_score = (1.0 if gua_flipped else 0.0) * 0.25
    
    # 综合得分
    total_score = price_score + contradiction_score + gua_score
    
    # 否定阈值：0.6（保守，宁可错过不可错判）
    is_negation = total_score >= 0.6
    
    return is_negation, total_score
```

**螺旋阶段判定**：

```python
def determine_spiral_stage(negation_count: int, current_direction: str,
                           initial_direction: str) -> str:
    """
    螺旋阶段判定（否定之否定规律）
    
    阶段定义:
      FIRST_AFFIRMATION（正题）: 初始方向，否定次数=0
      FIRST_NEGATION（反题）  : 第一次否定，方向反转，否定次数=1
      SECOND_NEGATION（合题） : 第二次否定，方向再次反转，否定次数=2
                                  这是更高层次的"回到起点"，不是简单重复
    
    超过 2 次否定: 重置计数，从 FIRST_AFFIRMATION 重新开始
    """
    if negation_count == 0:
        return 'FIRST_AFFIRMATION'
    elif negation_count == 1:
        return 'FIRST_NEGATION'
    elif negation_count == 2:
        return 'SECOND_NEGATION'
    else:
        # 超过 2 次，重置（螺旋的下一圈）
        return 'FIRST_AFFIRMATION'  # 调用方需重置 negation_count
```

**权重设计理由**：
- 价格反转 40%：唯物论强调客观实在，价格是最直接的客观指标
- 矛盾主导方 35%：矛盾论的核心，主要方面决定性质
- 卦象翻转 25%：易经的符号确认，作为辅助验证

**阈值 0.6 的理由**：
- 价格反转单一维度最多贡献 0.4，不足以触发否定
- 必须有至少两个维度同时反转才能触发
- 符合"矛盾双方力量对比变化"的辩证法要求

---

#### 问题 2：质变阈值回测 ✅ 已决议

**问题**：Step 3 的 threshold 如何从 L4 历史 cases 回测得到？需定义"质变已发生"的标签。

**决议方案**：**双标签法**（主标签：卦象状态机切换 + 辅标签：事后 PnL 反转）

**质变已发生的形式化标签**：

```python
def label_qualitative_change(cases: List[Dict], window: int = 5) -> List[Dict]:
    """
    在 L4 历史 cases 上标注"质变已发生"的样本
    
    双标签法:
      主标签: 卦象从蓄势（艮/兑）切换到趋势（乾/坤）
      辅标签: 切换后 window 个 bar 内 PnL 反转幅度 > 3%
    
    只有同时满足主+辅标签，才视为"真质变"
    """
    labeled = []
    for i in range(len(cases) - window):
        case = cases[i]
        future_cases = cases[i+1 : i+1+window]
        
        # 主标签：蓄势 → 趋势
        pre_gua = case['bagua']
        post_guas = [c['bagua'] for c in future_cases]
        zhishi_to_qushi = (
            pre_gua in ('gen', 'dui') and  # 蓄势卦
            any(g in ('qian', 'kun') for g in post_guas)  # 出现趋势卦
        )
        
        # 辅标签：PnL 反转
        pre_pnl = case['pnl']
        future_pnls = [c['pnl'] for c in future_cases]
        max_reversal = max(abs(p - pre_pnl) for p in future_pnls)
        pnl_reversed = max_reversal > 0.03  # 3% 反转
        
        # 真质变：主+辅同时满足
        is_real_qualitative_change = zhishi_to_qushi and pnl_reversed
        
        labeled.append({
            **case,
            'pre_gua': pre_gua,
            'zhishi_to_qushi': zhishi_to_qushi,
            'pnl_reversed': pnl_reversed,
            'is_real_qualitative_change': is_real_qualitative_change,
            'accumulation_at_trigger': case['accumulation'],  # 触发前的累积度
        })
    
    return labeled
```

**threshold 回测流程**：

```python
def calibrate_threshold(labeled_cases: List[Dict]) -> float:
    """
    从标注样本中校准质变 threshold
    
    方法:
      1. 取所有"真质变"样本的 accumulation_at_trigger
      2. 取 25 分位数作为 threshold（保守策略）
      
    保守策略理由:
      - 宁可错过质变（false negative），不可错判（false positive）
      - 错过质变只是少赚，错判质变可能亏损
      - 25 分位数意味着 75% 的真质变会被触发，同时过滤 25% 的低累积度噪声
    """
    real_changes = [c for c in labeled_cases if c['is_real_qualitative_change']]
    accumulations = [c['accumulation_at_trigger'] for c in real_changes]
    
    if not accumulations:
        return 0.8  # 默认值
    
    threshold = np.percentile(accumulations, 25)
    
    # 边界约束：threshold 必须在 [0.5, 0.9] 之间
    threshold = max(0.5, min(0.9, threshold))
    
    return threshold
```

**为什么用双标签法**：
- 单用卦象切换：可能误判（卦象切换不一定意味着真实质变）
- 单用 PnL 反转：可能滞后（等 PnL 反转时已经晚了）
- 双标签法：卦象切换是"因"，PnL 反转是"果"，因果同时验证才可靠

**为什么用 25 分位数**：
- 保守策略，宁可错过不可错判
- 错过质变 = 少赚，错判质变 = 亏损
- 75% 召回率已足够，剩余 25% 用变爻机制兜底

---

#### 问题 3：与 A0 的张力 ✅ 已决议

**决议方案**：**层级隔离 + 显式声明**

- BCRM 的 fail-closed 是**输入层失败**（数据缺失/对齐失败），输出 UNKNOWN
- A0 铁律适用于 **A0 自身输出层**（A0 不能无方向）
- 两者不冲突：A0 看到 BCRM 的 UNKNOWN 时，应保持其原有方向判断，不被 BCRM 影响
- **显式声明**：在 BCRM 输出契约中标注 "fail-closed 状态不进入 A0 消费链路"，A0 消费时跳过 UNKNOWN

---

#### 问题 4：情景推演两路径定义 ✅ 已决议

**决议方案**：**量变延续 vs 质变反转**（按辩证阶段分叉）

- **路径 A（量变延续）**：accumulation 继续积累，不达到 threshold，当前趋势延续
- **路径 B（质变反转）**：accumulation 达到 threshold，发生质变，趋势反转

**不用 thesis vs antithesis 的理由**：
- thesis/antithesis 是正反合的结构，属于 Step 6（正反合裁决）
- Step 4 是情景推演，应按辩证阶段（量变/质变）分叉，不是按正反分叉
- 两者层次不同，避免混淆

---

#### 问题 5：practice_directive 与 A5 执行的边界 ✅ 已决议

**决议方案**：**三者职责严格分离**

| 角色 | 职责 | 不做的事 |
|---|---|---|
| **BCRM** | 输出 practice_directive（应该做什么）| 不执行下单 |
| **A5** | 执行 practice_directive（实际怎么做）| 不做推理 |
| **A7** | 验证 practice_directive 的执行结果（做对了吗）| 不下单 |

**接口契约**：
- BCRM → A5：`practice_directive` 字段（包含 action / size / stop_loss / take_profit）
- A5 → A7：执行结果（filled_order / slippage / cost）
- A7 → L4：新 case（含 BCRM 推理 + A5 执行 + A7 验证）

---

#### 问题 6：是否新建 SKILL ✅ 已决议

**决议方案**：**Phase 1 不新建 SKILL**

- 初期按"模块化≠SKILL 拆分"原则
- BCRM 作为 `scripts/memory_l4/bcrm/` 模块存在
- 通过 Phase 2 门禁后再评估是否提升为 SKILL

---

### 11.2 工程实践问题（已决议）

#### 问题 7：LangGraph vs 自研状态机 ✅ 已决议

**决议方案**：**Phase 1 自研轻量状态机，Phase 3 后再评估**

- Phase 1 严格遵循"纯 Python 零依赖"，不引入 LangGraph
- 自研状态机用 ~100 行 Python 实现（节点 + 边 + 条件转移）
- Phase 3 通过门禁后，若需复杂编排再评估是否迁移到 LangGraph

---

#### 问题 8：seeded PRNG 的种子构成 ✅ 已决议

**决议方案**：**Phase 1 只用当前快照，Phase 2 后加 L4 指纹**

- Phase 1：种子 = 时间戳 + 四象评分（简单可验证）
- Phase 2 后：种子 += L4 相似 case 指纹（融入历史记忆）
- 理由：Phase 1 先确保确定性，再加复杂性

---

#### 问题 9：符号模板的粒度 ✅ 已决议

**决议方案**：**统一函数 + 参数化**

- 8 卦用 1 个统一函数 `execute_hexagram(gua_id, params, market_data)` + 8 套参数
- 不为每卦写独立函数（避免代码重复）
- 参数化模板更灵活，便于回测调优
- 64 卦扩展时同理：1 个函数 + 64 套参数

---

#### 问题 10：辩证一致性度量 ✅ 已决议

**决议方案**：**三子维度加权**

```python
def compute_dialectical_consistency(bcrm_output: BCRMOutput, 
                                     actual_outcome: Dict) -> float:
    """
    辩证一致性度量（参考 SIEV ΔDS）
    
    三子维度:
      1. 对立一致性（40%）：主矛盾和主要方面是否正确识别
      2. 量变一致性（30%）：accumulation 和 threshold 是否符合历史规律
      3. 否定一致性（30%）：螺旋阶段判定是否符合实际反转
    
    返回: 0.0 ~ 1.0，> 0.7 视为一致
    """
    # 1. 对立一致性
    predicted_contradiction = bcrm_output.contradiction_state
    actual_contradiction = infer_actual_contradiction(actual_outcome)
    opposition_consistency = 1.0 if predicted_contradiction == actual_contradiction else 0.5
    
    # 2. 量变一致性
    predicted_transformation = bcrm_output.transformation_trigger
    actual_transformation = detect_actual_transformation(actual_outcome)
    quantitative_consistency = 1.0 if predicted_transformation == actual_transformation else 0.3
    
    # 3. 否定一致性
    predicted_spiral = bcrm_output.spiral_position
    actual_spiral = detect_actual_spiral(actual_outcome)
    negation_consistency = 1.0 if predicted_spiral == actual_spiral else 0.3
    
    # 加权
    total = (opposition_consistency * 0.40 + 
             quantitative_consistency * 0.30 + 
             negation_consistency * 0.30)
    
    return round(total, 4)
```

**阈值 0.7 的理由**：
- 单一维度满分 = 0.4，不足以达到 0.7
- 必须至少两个维度一致才能达到 0.7
- 符合"辩证法三规律协同"的要求

---

#### 问题 11：64 卦 vs 8 卦 ✅ 已决议

**决议方案**：**Phase 1 先 8 卦，Phase 2 通过门禁后扩展 64 卦**

- Phase 1：8 卦（基础维度评估）
- Phase 2：用 8 卦跑通 walk-forward 回测
- Phase 3 后：若 8 卦稳定（胜率 > 55%），扩展到 64 卦（情境识别）
- 理由：先验证核心逻辑，再增加情境粒度

---

#### 问题 12：变爻概率的来源 ✅ 已决议

**决议方案**：**Phase 1 用传统概率，Phase 2 回测后校准**

- Phase 1：用易经传统概率做基线
  - 老阴（变）：1/16
  - 少阳（不变）：5/16
  - 少阴（不变）：5/16
  - 老阳（变）：5/16
- Phase 2：用 L4 历史 cases 回测实际变爻频率
- Phase 3 后：若回测概率与传统概率偏差 > 20%，用回测概率替换

**理由**：先用传统概率确保体系完整，再用数据校准，体现"基础层（数据）校验理论层（易经）"的三层架构原则。

---

### 11.3 决议汇总

| # | 问题 | 决议方案 | 优先级 |
|---|------|---------|--------|
| 1 | 螺旋阶段判据 | 三维度综合（价格40%+矛盾35%+卦象25%），阈值0.6 | P0 |
| 2 | 质变阈值标签 | 双标签（卦象切换+PnL反转3%），25分位数校准 | P0 |
| 3 | 与 A0 的张力 | 层级隔离 + 显式声明 | P0 |
| 4 | 情景推演两路径 | 量变延续 vs 质变反转 | P1 |
| 5 | practice/A5/A7 边界 | 三者职责严格分离 | P1 |
| 6 | 是否新建 SKILL | Phase 1 不新建 | P2 |
| 7 | LangGraph vs 自研 | Phase 1 自研轻量状态机 | P0 |
| 8 | 种子构成 | Phase 1 只用当前快照 | P0 |
| 9 | 符号模板粒度 | 统一函数 + 参数化 | P0 |
| 10 | 辩证一致性度量 | 三子维度加权，阈值0.7 | P1 |
| 11 | 64 卦 vs 8 卦 | Phase 1 先 8 卦 | P0 |
| 12 | 变爻概率来源 | Phase 1 传统概率，Phase 2 校准 | P1 |

---

## 十二、版本记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-07-04 | 初始设计稿：定位+三源哲学基础+输出契约+七步推理循环+失败语义+落地阶段 |
| v0.2 | 2026-07-04 | 补充§〇核心方法论三层架构 + §0.2 推理过程而非预测结果 |
| v0.3 | 2026-07-04 | 新增§六 变爻机制（实时动态修正），来自千问分析评估的关键增量 |
| v0.4 | 2026-07-04 | 新增§八 工程实践借鉴（seeded PRNG + 状态机 + 符号模板 + guardrail + walk-forward），来自 GitHub 30+ 项目调研；更新§十 落地阶段 P0/P1/P2/P3 优先级；§十一 开放问题分核心算法/工程实践两类 |
| v0.5 | 2026-07-04 | §十一 12 个开放问题全部决议：螺旋判据（三维度综合+阈值0.6）、质变标签（双标签+25分位数）、A0 张力（层级隔离）、情景两路径（量变vs质变）、A5/A7 边界、辩证一致性度量（三子维度+阈值0.7）等 |
| v0.5.1 | 2026-07-04 | 修复章节编号：变爻机制升为§六独立章节，工程实践借鉴§八，系统边界§九，落地阶段§十，开放问题§十一，版本记录§十二 |
| v0.6 | 2026-07-05 | 合并 trae/agent-TBnFsw：新增易经六十四卦推理算法（重卦/动爻/变卦/五维方向投票/六因子置信度）；更新七步推理循环的实际算法实现；补充 guardrail/walk_forward/backtest_gate 等配套模块；新增 36→64 卦知识库 |
