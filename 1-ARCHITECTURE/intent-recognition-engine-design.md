# 意图识别引擎技术方案

**版本**: v4.0
**日期**: 2026-07-01
**状态**: 待评审

---

## 1. 核心思考框架

### 1.1 三层价值模型：从单点到工程化

**核心洞察**：意图识别引擎的本质是一个**价值转换器**，它将用户的模糊需求，经过三次转化，最终变成可执行的工程蓝图。

```
用户模糊需求（自然语言）
    │
    │  Layer 1: 意图识别层
    │  价值：收敛 —— 从混沌到单点
    │  输出：Objective（一个清晰的目标点）
    ▼
单点目标（Objective）
    │
    │  Layer 2: OKR目标分解层
    │  价值：展开 —— 从单点到线/网
    │  输出：OKRSet（单线 或 多线）
    ▼
目标结构（OKRSet）
    │
    │  Layer 3: B层工程化
    │  价值：落地 —— 从线/网到可执行图
    │  输出：ExecutionBlueprint（执行蓝图）
    ▼
工程蓝图（ExecutionBlueprint）
    │
    ▼
GraphOrchestrator 执行 → A链执行闭环
```

### 1.2 每层的独特价值

| 层级 | 价值定位 | 输入 | 输出 | 核心问题 |
|-----|---------|------|------|---------|
| **Layer 1 意图识别层** | **收敛**：从混沌到单点 | 用户自然语言/市场数据/信号 | Objective（单点目标） | 用户到底想要什么？ |
| **Layer 2 OKR分解层** | **展开**：从单点到线/网 | Objective（单点目标） | OKRSet（单线/多线KRs） | 怎么衡量目标达成了？ |
| **Layer 3 B层工程化** | **落地**：从线/网到可执行图 | OKRSet（目标结构） | ExecutionBlueprint（执行蓝图） | 具体怎么执行？ |

### 1.3 与现有系统的定位关系

```
┌─────────────────────────────────────────────────────────────────┐
│                     S链：意图识别引擎 (Intent Engine)             │
│                                                                 │
│  Layer 1: 收敛 → Layer 2: 展开 → Layer 3: 落地                   │
│  （意图识别）    （OKR分解）     （B层工程化）                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ 输出：ExecutionBlueprint
┌─────────────────────────────────────────────────────────────────┐
│                   GraphOrchestrator (图编排引擎)                  │
│                   执行蓝图 → 节点编排 → 结果聚合                    │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼ 调用：模块/SKILL
┌─────────────────────────────────────────────────────────────────┐
│              A链：执行闭环（三屏交易 + 三大闭环）                   │
│              C链：经典量化  |  F链：基本面                         │
└─────────────────────────────────────────────────────────────────┘
```

### 1.4 GitHub项目借鉴（三层映射）

| 项目 | 核心概念 | 映射到哪一层 | 借鉴点 |
|------|---------|------------|--------|
| **CrewAI** | Task + Agent + Process | Layer 2 (OKR层) | Process模式=单线/多线；Task=KR |
| **LangGraph Plan-and-Execute** | Plan Step → Execute Steps → Replan | Layer 2+3 | 规划-执行-重规划循环 |
| **DeepAgents** | 规划 + 子Agent委托 | Layer 3 (B层) | 复杂KR委派给子编排器 |
| **AutoGPT / BabyAGI** | 目标→任务清单→执行→评估循环 | Layer 2+3 | 目标驱动的自循环 |
| **HTN层次任务网络** | 目标→子目标→可执行动作 | 整体三层 | Objective→KR→Node 三层分解 |
| **OKR管理理论** | O + KR | Layer 2 | 目标与关键结果的分离 |

---

## 2. Layer 1：意图识别层（收敛：从混沌到单点）

### 2.1 核心价值：收敛

这一层的价值在于**"收敛"**——从用户模糊的、多义的、可能包含干扰信息的输入中，精准提取出一个清晰的、单一的目标点。

**收敛的含义**：
- 从一段话 → 一个目标
- 从多个可能 → 一个最可能
- 从模糊描述 → 结构化目标

### 2.2 输入输出

```
输入（多源、多模态）：
  ├─ 用户自然语言（"帮我看看BTC怎么样"）
  ├─ 市场数据异动（价格突破、成交量放大）
  ├─ 信号触发（技术指标信号、基本面信号）
  └─ 上下文信息（历史对话、持仓状态）
        │
        │  收敛
        ▼
输出（单点目标）：
  Objective { type, domain, priority, ... }
```

### 2.3 Objective 结构

```python
@dataclass
class Objective:
    """目标 (Objective) - 用户想要完成的单点目标
    
    Layer 1 的输出：从混沌收敛到单点
    核心特征：只有一个、清晰明确、可被分解
    """
    id: str
    title: str                             # 目标标题（一句话概括）
    description: str                       # 详细描述
    
    # 目标分类（决定后续OKR分解路径）
    type: str                              # 目标类型（9种）
    domain: str                            # 领域（trading/analysis/risk/portfolio）
    
    # 约束条件
    priority: int                          # 优先级 (1-10)
    time_constraint: Optional[str]         # 时间约束
    
    # 来源追踪
    source: str                            # 来源（nl/market/signal/context）
    source_confidence: float               # 来源可信度
    
    # 识别结果
    extracted_keywords: List[str]          # 提取的关键词
    confidence: float                      # 目标识别置信度
    
    # 澄清机制
    clarify_needed: bool                   # 是否需要澄清
    clarify_question: Optional[str]        # 澄清问题
    clarify_options: Optional[List[Dict]]  # 澄清选项
```

### 2.4 目标类型体系（9种）

每种目标类型预定义了复杂度和OKR模式，作为Layer 2的输入：

```python
OBJECTIVE_TYPES = {
    # === 查询类（Simple）===
    'market_query': {
        'name': '行情查询',
        'complexity': 'simple',
        'okr_mode': 'single',          # 单线单KR
        'description': '简单的行情数据查询',
        'keywords': ['行情', '价格', '涨跌', '走势', '现在', '多少钱'],
    },

    # === 分析类（Standard/Deep）===
    'trend_analysis': {
        'name': '趋势分析',
        'complexity': 'standard',
        'okr_mode': 'single',          # 单线多KR（顺序依赖）
        'description': '单维度趋势分析',
        'keywords': ['分析', '趋势', '方向', '看涨', '看跌'],
    },
    'deep_analysis': {
        'name': '深度分析',
        'complexity': 'deep',
        'okr_mode': 'multi',           # 多线并行+聚合
        'description': '多维度综合分析',
        'keywords': ['深度分析', '研究', '全面', '详细', '完整'],
    },

    # === 交易类（Standard/Deep）===
    'trading_decision': {
        'name': '交易决策',
        'complexity': 'standard',
        'okr_mode': 'single',          # 单线：三屏交易顺序
        'description': '完整的交易决策流程',
        'keywords': ['买入', '卖出', '做多', '做空', '开仓', '入场'],
    },
    'exit_evaluation': {
        'name': '离场评估',
        'complexity': 'standard',
        'okr_mode': 'single',
        'description': '持仓离场评估',
        'keywords': ['离场', '出场', '止盈', '止损', '平仓'],
    },
    'strategy_design': {
        'name': '策略设计',
        'complexity': 'deep',
        'okr_mode': 'multi',           # 多线：技术面+基本面+风控 并行
        'description': '完整交易策略设计',
        'keywords': ['策略', '设计', '参数', '回测', '优化'],
    },

    # === 风控类（Standard）===
    'risk_assessment': {
        'name': '风险评估',
        'complexity': 'standard',
        'okr_mode': 'single',
        'description': '风险评估与管理',
        'keywords': ['风险', '风控', '评估', '仓位', '杠杆'],
    },

    # === 组合类（Deep）===
    'portfolio_review': {
        'name': '组合回顾',
        'complexity': 'deep',
        'okr_mode': 'multi',           # 多线：收益+风险+持仓 并行
        'description': '投资组合综合回顾',
        'keywords': ['持仓', '组合', '收益', '回顾', '总结'],
    },

    # === 三屏交易（Standard）===
    'three_screen_trade': {
        'name': '三屏交易分析',
        'complexity': 'standard',
        'okr_mode': 'single',          # 单线：Screen1→Screen2→Screen3
        'description': 'Elder三屏交易体系分析',
        'keywords': ['三屏', '周线', '日线', '日内', 'screen'],
    },
}
```

### 2.5 收敛算法（简化版）

```
Phase 1: 信号收集
  ├─ NLP解析：关键词提取、意图分类
  ├─ 市场打分：当前市场状态与目标匹配度
  └─ 上下文匹配：历史对话/持仓状态

Phase 2: 多源融合
  ├─ 加权投票：各来源按置信度加权
  └─ 冲突消解：不同来源冲突时的处理规则

Phase 3: 收敛决策
  ├─ 最高置信度目标 → 确认输出
  ├─ 置信度不足 → 发起澄清
  └─ 无匹配目标 → 拒绝/转人工
```

---

## 3. Layer 2：OKR目标分解层（展开：从单点到线/网）

### 3.1 核心价值：展开

这一层的价值在于**"展开"**——将一个单点目标，拆解为多个可衡量的关键结果（KR），形成**单线**或**多线**的目标结构。

**展开的含义**：
- 从一个目标点 → 一条或多条衡量线
- 从"想要什么" → "怎么衡量达成了"
- 从模糊目标 → 结构化的目标体系

### 3.2 两种模式：单线 vs 多线

```
┌─────────────────────────────────────────────────────────┐
│                    单线模式 (Single)                      │
│                                                         │
│  Objective                                               │
│      │                                                  │
│      ▼                                                  │
│   KR1 ──▶ KR2 ──▶ KR3 ──▶ ... ──▶ KRN                   │
│   (基础)   (进阶)   (深化)        (最终)                 │
│                                                         │
│  特征：顺序依赖，前一个KR的结果是后一个的基础                │
│  适用：有明确先后顺序的任务（如三屏交易）                    │
└─────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────┐
│                    多线模式 (Multi)                       │
│                                                         │
│              Objective                                  │
│                  │                                      │
│       ┌──────────┼──────────┐                           │
│       ▼          ▼          ▼                           │
│     KR1        KR2        KR3    ← 并行线               │
│  (技术面)    (资金面)    (情绪面)                        │
│       │          │          │                           │
│       └──────────┼──────────┘                           │
│                  ▼                                      │
│              KR_aggregate    ← 聚合线                   │
│            (综合决策)                                   │
│                                                         │
│  特征：多条线独立并行，最后汇总决策                         │
│  适用：可从多个维度独立分析的任务（如深度分析）              │
└─────────────────────────────────────────────────────────┘
```

### 3.3 KeyResult 结构（纯目标管理，不含执行细节）

```python
@dataclass
class KeyResult:
    """关键结果 (Key Result) - 衡量目标达成的具体指标
    
    Layer 2 的输出：从单点目标展开为可衡量的KR
    核心特征：只关注"衡量什么"，不关注"怎么执行"
    
    注意：这里不包含模块/节点信息，那是B层的职责
    """
    id: str
    objective_id: str

    # ===== 目标管理属性（Layer 2 核心）=====
    title: str                             # KR标题
    description: str                       # 描述
    metric: str                            # 衡量指标（如 trend_direction, technical_score）
    target_value: float                    # 目标值
    current_value: Optional[float]         # 当前值（执行过程中更新）
    unit: str                              # 单位

    # 权重与顺序
    weight: float                          # 权重 (0-1)，所有KR权重和为1
    order_index: int                       # 顺序索引（同index=并行）
    line_id: str                           # 所属线ID（多线模式用）

    # 状态
    status: str                            # pending / in_progress / achieved / failed

    # ===== 依赖关系（决定线的结构）=====
    depends_on: List[str]                  # 依赖的KR ID列表
    is_parallel: bool                      # 是否可并行执行

    # ===== B层映射提示（非强制，仅作参考）=====
    # 这些是"建议的能力标签"，B层会根据这些标签去匹配具体模块
    capability_tags: List[str]             # 需要的能力标签（如 'technical_analysis'）
    complexity_hint: str                   # 复杂度提示（simple/standard/deep）
```

### 3.4 OKRSet 结构

```python
@dataclass
class OKRSet:
    """OKR集 - 包含一个目标和其对应的所有关键结果
    
    Layer 2 的最终输出：完整的目标结构
    """
    objective: Objective
    key_results: List[KeyResult]

    # ===== 模式配置 =====
    mode: str                              # single / multi
    complexity: str                        # simple / standard / deep

    # ===== 目标结构 =====
    lines: List[Dict]                      # 线结构（多线模式用）
    dependency_graph: Dict[str, List[str]] # KR依赖图（adjacency list）

    # ===== 统计信息 =====
    total_weight: float                    # 总权重（应为1.0）
    parallel_line_count: int               # 并行线数量
    sequential_depth: int                  # 顺序深度（最长链的长度）

    # ===== 置信度 =====
    confidence: float                      # OKR整体置信度
    rationale: str                         # 推理过程（为什么这么分解）
```

### 3.5 单线模式详解

**适用场景**：目标有明确的先后顺序，前一个KR的结果是后一个的基础

**典型案例**：三屏交易决策

```
Objective: 用三屏交易法分析ETH是否入场
    │
    ▼  单线展开
KR1: 周线方向确认（Screen1）
  ├─ 衡量指标：trend_direction
  ├─ 目标值：明确的趋势方向（看涨/看跌/震荡）
  ├─ 权重：0.30
  ├─ 依赖：无
  └─ 能力标签：['trend_analysis', 'weekly_timeframe']
    │
    ▼
KR2: 日线入场预设（Screen2）
  ├─ 衡量指标：entry_setup_quality
  ├─ 目标值：高质量入场信号
  ├─ 权重：0.35
  ├─ 依赖：[KR1]
  └─ 能力标签：['technical_analysis', 'daily_timeframe', 'entry_setup']
    │
    ▼
KR3: 日内执行确认（Screen3）
  ├─ 衡量指标：execution_signal
  ├─ 目标值：明确的执行信号
  ├─ 权重：0.20
  ├─ 依赖：[KR2]
  └─ 能力标签：['intraday_execution', 'timing']
    │
    ▼
KR4: 门禁检查（Gate）
  ├─ 衡量指标：gate_pass
  ├─ 目标值：通过门禁检查
  ├─ 权重：0.15
  ├─ 依赖：[KR3]
  └─ 能力标签：['risk_management', 'gate_keeping']
```

### 3.6 多线模式详解

**适用场景**：目标可从多个维度独立分析，最后汇总决策

**典型案例**：深度分析BTC

```
Objective: 深度分析BTC，给出综合判断
    │
    ▼  多线展开
┌─────────────┬─────────────┬─────────────┐
│ 技术面线     │ 资金面线     │ 情绪面线     │  ← 三条并行线
│             │             │             │
│ KR1:        │ KR2:        │ KR3:        │
│ 技术面得分   │ 资金面得分   │ 情绪面得分   │
│ weight:0.35 │ weight:0.25 │ weight:0.20 │
│             │             │             │
│ 能力标签:    │ 能力标签:    │ 能力标签:    │
│ ['technical',│ ['fundamental',│ ['sentiment',
│  'indicators',│  'fund_flow',│  'market_sentiment']
│  'pattern']  │  'macro']    │             │
└──────┬──────┴──────┬──────┴──────┬──────┘
       │             │             │
       └─────────────┼─────────────┘
                     ▼
              KR4: 综合决策
              （聚合线）
              weight: 0.20
              依赖: [KR1, KR2, KR3]
              能力标签: ['synthesis', 'decision_making']
```

### 3.7 复杂度分级与模式对应

| 复杂度 | OKR模式 | KR数量 | 特征 | 示例 |
|-------|---------|--------|------|------|
| **Simple** | single | 1 | 单线单KR，直接出结果 | "BTC现在多少钱？" |
| **Standard** | single | 3-5 | 单线多KR，顺序依赖 | "分析ETH走势" / "三屏交易" |
| **Deep** | multi | 4+ | 多线并行+聚合，3+条并行线 | "深度分析BTC" / "策略设计" |

---

## 4. Layer 3：B层工程化（落地：从线/网到可执行图）

### 4.1 核心价值：落地

这一层的价值在于**"落地"**——将OKR层的目标结构，映射为可执行的工程蓝图，考虑所有执行层面的工程问题。

**落地的含义**：
- 从"要衡量什么" → "用什么模块执行"
- 从"KR依赖关系" → "节点执行顺序/DAG"
- 从"目标结构" → "完整的执行计划（含超时、重试、降级、监控）"

### 4.2 B层工程化的5大工程问题

```
OKRSet（目标结构）
    │
    ├─ 问题1：节点展开 —— 每个KR对应哪些模块/节点？
    ├─ 问题2：依赖映射 —— KR间的依赖如何映射为节点间的依赖？
    ├─ 问题3：执行模式 —— 用顺序、并行还是混合模式？
    ├─ 问题4：容错设计 —— 失败了怎么办？超时了怎么办？
    └─ 问题5：资源配置 —— 超时、重试、优先级怎么设？
    │
    ▼
ExecutionBlueprint（执行蓝图）
```

### 4.3 ExecutionBlueprint 结构

```python
@dataclass
class ExecutionBlueprint:
    """执行蓝图 - B层工程化输出
    
    Layer 3 的输出：可直接交给 GraphOrchestrator 执行的工程蓝图
    核心特征：包含执行所需的所有工程细节
    """
    blueprint_id: str
    objective_id: str

    # ===== 基础信息 =====
    complexity: str                        # simple / standard / deep
    okr_mode: str                          # single / multi

    # ===== 执行图 =====
    node_sequence: List[str]               # 节点执行序列（拓扑排序结果）
    execution_mode: str                    # sequential / parallel / hybrid
    dependencies: Dict[str, List[str]]     # 节点依赖图（DAG）
    parallel_groups: List[List[str]]       # 可并行执行的节点组

    # ===== KR → 节点映射（用于结果回溯）=====
    kr_to_nodes: Dict[str, List[str]]      # KR ID → 节点ID列表
    node_to_kr: Dict[str, str]             # 节点ID → KR ID（反向映射）

    # ===== 工程配置 =====
    total_timeout_ms: int                  # 总超时时间
    node_timeout_ms: Dict[str, int]        # 每个节点的超时时间
    retry_policy: Dict[str, Dict]          # 每个节点的重试策略
    fallback_policy: Dict[str, str]        # 每个节点的降级模块

    # ===== 执行控制 =====
    early_stop_condition: Optional[str]    # 提前终止条件（如某KR失败时）
    required_nodes: List[str]              # 必须成功的节点
    optional_nodes: List[str]              # 可选节点（失败不影响整体）

    # ===== 重规划配置（仅deep复杂度）=====
    replan_enabled: bool
    replan_triggers: List[str]             # 触发重规划的条件
    max_replans: int                       # 最大重规划次数

    # ===== 置信度 =====
    confidence: float
    rationale: str                         # 蓝图构建的推理过程
```

### 4.4 蓝图构建算法（5步）

```python
class BlueprintBuilder:
    """执行蓝图构建器 - 将OKR映射为执行图"""

    def build(self, okr_set: OKRSet, registry: ModuleRegistry) -> ExecutionBlueprint:
        """
        根据OKR集构建执行蓝图
        
        5步工程化过程：
        1. 节点展开：KR → 具体模块节点
        2. 依赖映射：KR依赖 → 节点依赖（DAG）
        3. 拓扑排序：DAG → 可执行序列
        4. 并行识别：识别可并行执行的节点组
        5. 工程配置：超时、重试、降级等工程参数
        """
        # Step 1: 节点展开
        kr_node_map = self._expand_krs_to_nodes(okr_set, registry)
        
        # Step 2: 依赖映射
        dep_graph = self._build_dependency_graph(okr_set, kr_node_map)
        
        # Step 3: 拓扑排序
        sorted_nodes = self._topological_sort(dep_graph)
        
        # Step 4: 并行识别
        parallel_groups = self._identify_parallel_groups(dep_graph, sorted_nodes)
        
        # Step 5: 工程配置
        engineering_config = self._configure_engineering(okr_set, registry, sorted_nodes)
        
        return ExecutionBlueprint(
            blueprint_id=f"bp_{uuid.uuid4().hex[:8]}",
            objective_id=okr_set.objective.id,
            complexity=okr_set.complexity,
            okr_mode=okr_set.mode,
            node_sequence=sorted_nodes,
            execution_mode=self._determine_execution_mode(parallel_groups),
            parallel_groups=parallel_groups,
            dependencies=dep_graph,
            kr_to_nodes=kr_node_map,
            node_to_kr=self._build_reverse_map(kr_node_map),
            **engineering_config,
        )
```

### 4.5 Step 1：节点展开（KR → 节点）

**核心策略**：能力标签匹配 + 注册表查询

```python
def _expand_krs_to_nodes(
    self,
    okr_set: OKRSet,
    registry: ModuleRegistry,
) -> Dict[str, List[str]]:
    """
    将每个KR展开为对应的节点列表
    
    匹配策略：
    1. 根据KR的 capability_tags 在注册表中搜索匹配的模块
    2. 按匹配度排序，选择最合适的1-3个模块
    3. 考虑模块的依赖关系，自动加入依赖模块
    4. 检查模块可用性（active状态）
    5. 为每个模块配置降级备选
    """
    kr_node_map = {}
    
    for kr in okr_set.key_results:
        # 在注册表中按能力标签搜索
        candidates = registry.search_by_tags(kr.capability_tags)
        
        # 过滤可用模块
        active_candidates = [m for m in candidates if m.lifecycle.status == 'active']
        
        # 选择最佳匹配（考虑置信度、延迟、历史准确率等）
        selected = self._select_best_modules(active_candidates, kr)
        
        # 自动加入依赖模块
        all_nodes = self._resolve_dependencies(selected, registry)
        
        kr_node_map[kr.id] = all_nodes
    
    return kr_node_map
```

### 4.6 Step 2：依赖映射（KR依赖 → 节点依赖）

```python
def _build_dependency_graph(
    self,
    okr_set: OKRSet,
    kr_node_map: Dict[str, List[str]],
) -> Dict[str, List[str]]:
    """
    构建节点依赖图
    
    依赖来源：
    1. KR内部的节点顺序依赖（如A2分析依赖A0矛盾论）
    2. KR之间的依赖映射（当前KR的第一个节点依赖上游KR的最后一个节点）
    3. 模块自身声明的依赖（从注册表读取）
    """
    dep_graph = {}
    
    # 1. KR内部的节点顺序依赖
    for kr_id, nodes in kr_node_map.items():
        for i in range(1, len(nodes)):
            if nodes[i] not in dep_graph:
                dep_graph[nodes[i]] = []
            dep_graph[nodes[i]].append(nodes[i-1])
    
    # 2. KR之间的依赖映射到节点
    for kr in okr_set.key_results:
        if not kr.depends_on:
            continue
        kr_first_node = kr_node_map[kr.id][0] if kr_node_map[kr.id] else None
        if not kr_first_node:
            continue
        if kr_first_node not in dep_graph:
            dep_graph[kr_first_node] = []
        for dep_kr_id in kr.depends_on:
            dep_nodes = kr_node_map.get(dep_kr_id, [])
            if dep_nodes:
                # 当前KR的第一个节点 依赖于 上游KR的最后一个节点
                dep_graph[kr_first_node].append(dep_nodes[-1])
    
    # 3. 模块自身的依赖（从注册表补充）
    # ...
    
    return dep_graph
```

### 4.7 Step 3-4：拓扑排序 + 并行识别

这两步是图算法的标准操作，目的是将DAG转换为可执行的序列和并行组。

### 4.8 Step 5：工程配置

```python
def _configure_engineering(
    self,
    okr_set: OKRSet,
    registry: ModuleRegistry,
    sorted_nodes: List[str],
) -> Dict:
    """
    配置工程参数
    
    配置项：
    - 超时时间：根据模块 estimated_latency_ms 计算，留2倍余量
    - 重试策略：根据模块 security_level 和 importance 配置
    - 降级策略：从注册表 fallback 字段读取
    - 必选/可选：根据KR权重和模块重要性判断
    """
    node_timeout_ms = {}
    retry_policy = {}
    fallback_policy = {}
    required_nodes = []
    optional_nodes = []
    
    for node_id in sorted_nodes:
        module_info = registry.get(node_id)
        if not module_info:
            continue
        
        # 超时：预估延迟 × 2
        node_timeout_ms[node_id] = module_info.estimated_latency_ms * 2
        
        # 重试：R1级2次，R2级1次，R3级0次
        retry_count = {'R1': 2, 'R2': 1, 'R3': 0}.get(module_info.security_level, 1)
        retry_policy[node_id] = {'count': retry_count, 'delay_ms': 1000}
        
        # 降级
        if module_info.fallback.get('enabled'):
            fallback_policy[node_id] = module_info.fallback['fallback_module']
        
        # 必选/可选（根据KR权重判断）
        # ...
    
    total_timeout = sum(node_timeout_ms.values())
    
    return {
        'total_timeout_ms': total_timeout,
        'node_timeout_ms': node_timeout_ms,
        'retry_policy': retry_policy,
        'fallback_policy': fallback_policy,
        'required_nodes': required_nodes,
        'optional_nodes': optional_nodes,
    }
```

---

## 5. 端到端数据流（三层贯通）

### 5.1 简单场景：查询行情（单线单KR）

```
用户: "BTC现在多少钱？"
    │
    ▼  [Layer 1: 收敛] 目标提取
    │  从一句话中识别出：行情查询
    │
Objective: {
    type: 'market_query',
    complexity: 'simple',
    title: '查询BTC当前价格',
    confidence: 0.95,
}
    │
    ▼  [Layer 2: 展开] OKR分解（单线单KR）
    │  简单查询不需要复杂分解，直接一个KR
    │
OKRSet: {
    mode: 'single',
    complexity: 'simple',
    key_results: [
        {
            id: 'kr_price',
            title: '获取当前价格',
            metric: 'current_price',
            weight: 1.0,
            capability_tags: ['market_data', 'price_query'],
        }
    ]
}
    │
    ▼  [Layer 3: 落地] 蓝图构建
    │  KR → 经典指标系统的价格查询接口
    │
ExecutionBlueprint: {
    node_sequence: ['classic-indicator-scan'],
    execution_mode: 'sequential',
    total_timeout_ms: 5000,
    node_timeout_ms: {'classic-indicator-scan': 5000},
}
    │
    ▼
GraphOrchestrator.execute() → 输出价格
```

### 5.2 标准场景：三屏交易（单线多KR）

```
用户: "用三屏交易法分析一下ETH能不能进"
    │
    ▼  [Layer 1: 收敛] 目标提取
    │  识别出：三屏交易分析
    │
Objective: {
    type: 'three_screen_trade',
    complexity: 'standard',
    title: 'ETH三屏交易决策',
    confidence: 0.88,
}
    │
    ▼  [Layer 2: 展开] OKR分解（单线4KR）
    │  三屏交易有明确的先后顺序：周线→日线→日内→门禁
    │
OKRSet: {
    mode: 'single',
    complexity: 'standard',
    key_results: [
        { id: 'kr_screen1', order: 0, metric: 'trend_direction',   weight: 0.30, capability_tags: ['trend_analysis', 'weekly'] },
        { id: 'kr_screen2', order: 1, metric: 'entry_setup',       weight: 0.35, depends_on: ['kr_screen1'], capability_tags: ['technical_analysis', 'daily'] },
        { id: 'kr_screen3', order: 2, metric: 'execution_signal',  weight: 0.20, depends_on: ['kr_screen2'], capability_tags: ['intraday', 'timing'] },
        { id: 'kr_gate',    order: 3, metric: 'gate_pass',         weight: 0.15, depends_on: ['kr_screen3'], capability_tags: ['risk_management', 'gate'] },
    ]
}
    │
    ▼  [Layer 3: 落地] 蓝图构建
    │  每个KR → 对应的SKILL模块，顺序依赖
    │
ExecutionBlueprint: {
    node_sequence: [
        'dream-screen1-first',     # Screen1: 周线方向
        'dream-screen2-swing',     # Screen2: 日线预设
        'dream-screen3-intra',     # Screen3: 日内执行
        'dream-gate-keeper',       # 门禁检查
    ],
    execution_mode: 'sequential',
    dependencies: {
        'dream-screen2-swing': ['dream-screen1-first'],
        'dream-screen3-intra': ['dream-screen2-swing'],
        'dream-gate-keeper': ['dream-screen3-intra'],
    },
    total_timeout_ms: 300000,  # 5分钟
    node_timeout_ms: {
        'dream-screen1-first': 120000,
        'dream-screen2-swing': 90000,
        'dream-screen3-intra': 60000,
        'dream-gate-keeper': 30000,
    },
}
    │
    ▼
GraphOrchestrator.execute(sequential) → 三屏交易结果
```

### 5.3 复杂场景：深度分析（多线并行+聚合）

```
用户: "深度分析一下BTC，各方面都看看，给个综合判断"
    │
    ▼  [Layer 1: 收敛] 目标提取
    │  识别出：深度分析
    │
Objective: {
    type: 'deep_analysis',
    complexity: 'deep',
    title: 'BTC深度综合分析',
    confidence: 0.85,
}
    │
    ▼  [Layer 2: 展开] OKR分解（多线4KR：3条并行线 + 1条聚合线）
    │  深度分析从多个维度独立进行，最后汇总
    │
OKRSet: {
    mode: 'multi',
    complexity: 'deep',
    lines: [
        { id: 'line_tech',  name: '技术面线',  krs: ['kr_technical'] },
        { id: 'line_fund',  name: '资金面线',  krs: ['kr_fundamental'] },
        { id: 'line_sent',  name: '情绪面线',  krs: ['kr_sentiment'] },
        { id: 'line_agg',   name: '聚合线',    krs: ['kr_synthesis'] },
    ],
    key_results: [
        { id: 'kr_technical',   order: 0, line: 'line_tech', metric: 'technical_score',   weight: 0.35, is_parallel: true,  capability_tags: ['technical_analysis', 'indicators', 'pattern'] },
        { id: 'kr_fundamental', order: 0, line: 'line_fund', metric: 'fundamental_score', weight: 0.25, is_parallel: true,  capability_tags: ['fundamental', 'fund_flow', 'macro'] },
        { id: 'kr_sentiment',   order: 0, line: 'line_sent', metric: 'sentiment_score',   weight: 0.20, is_parallel: true,  capability_tags: ['sentiment', 'news', 'social'] },
        { id: 'kr_synthesis',   order: 1, line: 'line_agg',  metric: 'final_decision',    weight: 0.20, depends_on: ['kr_technical','kr_fundamental','kr_sentiment'], capability_tags: ['synthesis', 'decision_making'] },
    ]
}
    │
    ▼  [Layer 3: 落地] 蓝图构建
    │  技术面/资金面/情绪面 三条线并行执行，最后聚合
    │
ExecutionBlueprint: {
    node_sequence: [
        # 第一阶段：三条线并行
        'dream-first-principles',      # 技术面线
        'classic-indicator-scan',
        'dream-fundamental-analyzer',  # 资金面线
        'dream-sentiment-analyzer',    # 情绪面线
        # 第二阶段：聚合
        'dream-strategy-research',     # 综合决策
        'dream-gate-keeper',           # 门禁
    ],
    execution_mode: 'hybrid',  # 混合模式：先并行后顺序
    parallel_groups: [
        # 第一组并行：技术面 + 资金面 + 情绪面
        [
            ['dream-first-principles', 'classic-indicator-scan'],  # 技术面线内部顺序
            ['dream-fundamental-analyzer'],                         # 资金面线
            ['dream-sentiment-analyzer'],                           # 情绪面线
        ],
        # 第二组顺序：聚合
    ],
    total_timeout_ms: 120000,  # 2分钟
    replan_enabled: true,
    max_replans: 3,
}
    │
    ▼
GraphOrchestrator.execute(hybrid) → 深度分析结果
```

---

## 6. 核心接口设计

### 6.1 Python侧核心接口

```python
@dataclass
class IntentRecognitionResult:
    """意图识别最终结果（三层完整输出）"""
    # Layer 1 输出
    objective: Objective

    # Layer 2 输出
    okr_set: OKRSet

    # Layer 3 输出
    blueprint: ExecutionBlueprint

    # 状态
    state: str                           # confirmed / clarifying / rejected
    confidence: float                    # 整体置信度
    rationale: str                       # 完整推理过程

    # 澄清信息
    clarify_question: Optional[str]
    clarify_options: Optional[List[Dict]]


class IntentRecognitionEngine:
    """
    意图识别引擎 (S链核心)
    
    三层价值转换：
    Layer 1: 收敛（混沌 → 单点）
    Layer 2: 展开（单点 → 线/网）
    Layer 3: 落地（线/网 → 可执行图）
    """

    def recognize(
        self,
        user_message: Optional[str] = None,
        mkt_data: Optional[Dict] = None,
        signals: Optional[List[Dict]] = None,
        session_id: Optional[str] = None,
    ) -> IntentRecognitionResult:
        """
        完整的意图识别流程（三层贯通）
        
        Phase 1: 收敛 —— 目标提取（Layer 1）
        Phase 2: 展开 —— OKR分解（Layer 2）
        Phase 3: 落地 —— 蓝图构建（Layer 3）
        """
        # Phase 1: 收敛 —— 从混沌到单点
        objective = self._extract_objective(user_message, mkt_data, signals)
        
        if objective.clarify_needed:
            return IntentRecognitionResult(
                objective=objective,
                okr_set=None,
                blueprint=None,
                state='clarifying',
                confidence=objective.confidence,
                clarify_question=objective.clarify_question,
                clarify_options=objective.clarify_options,
                rationale=f'需要澄清目标：{objective.clarify_question}',
            )

        # Phase 2: 展开 —— 从单点到线/网
        okr_set = self._build_okr_set(objective)

        # Phase 3: 落地 —— 从线/网到可执行图
        blueprint = self._build_blueprint(okr_set)

        # 最终决策
        state = 'confirmed' if blueprint.confidence >= 0.5 else 'clarifying'

        return IntentRecognitionResult(
            objective=objective,
            okr_set=okr_set,
            blueprint=blueprint,
            state=state,
            confidence=blueprint.confidence,
            rationale=(
                f'[Layer1] 收敛: {objective.title} (置信度:{objective.confidence:.2f}) → '
                f'[Layer2] 展开: {okr_set.mode}模式, {len(okr_set.key_results)}个KR → '
                f'[Layer3] 落地: {blueprint.execution_mode}模式, {len(blueprint.node_sequence)}个节点'
            ),
        )

    def clarify(
        self,
        answer: str,
        session_id: str,
    ) -> IntentRecognitionResult:
        """处理澄清回答"""
        pass

    def register_objective_type(self, definition: dict) -> None:
        """注册新的目标类型（可扩展）"""
        pass

    def get_supported_objectives(self) -> List[str]:
        """获取支持的目标类型列表"""
        pass
```

### 6.2 与GraphOrchestrator的对接

```python
def analyze_with_intent(
    user_message: str,
    mkt_data: Dict,
    session_id: str = None,
) -> Union[GraphExecutionResult, Dict]:
    """
    快捷函数：意图识别 + 图编排执行
    
    完整链路：
    用户输入 → [S链] 意图识别（三层）→ [B层] 执行蓝图 → [A链] 执行闭环
    """
    # 1. S链：意图识别（三层处理）
    engine = IntentRecognitionEngine()
    result = engine.recognize(
        user_message=user_message,
        mkt_data=mkt_data,
        session_id=session_id,
    )

    # 2. 检查状态
    if result.state == 'clarifying':
        return {
            'state': 'clarifying',
            'question': result.clarify_question,
            'options': result.clarify_options,
        }
    elif result.state == 'rejected':
        return {
            'state': 'rejected',
            'message': '无法识别有效目标',
        }

    # 3. B层蓝图 → GraphOrchestrator 执行
    orchestrator = GraphOrchestrator()
    context = create_default_context(session_id or uuid.uuid4().hex)
    context.intent = result.objective.type
    context.mkt = mkt_data
    context.extra['objective'] = result.objective
    context.extra['okr_set'] = result.okr_set
    context.extra['blueprint'] = result.blueprint

    mode = ExecutionMode(result.blueprint.execution_mode)

    return orchestrator.execute(
        context=context,
        node_ids=result.blueprint.node_sequence,
        execution_mode=mode,
        parallel_groups=result.blueprint.parallel_groups,
        dependencies=result.blueprint.dependencies,
        timeout_ms=result.blueprint.total_timeout_ms,
    )
```

---

## 7. 与现有系统的关系

### 7.1 现有系统盘点

| 组件 | 位置 | 职责 | 与新引擎的关系 |
|-----|------|------|--------------|
| **chain_planner.py** | core/ | 基于规则的意图分类 | Layer 1的基础/降级方案 |
| **chain_router.py** | core/ | 动态思维链调度 | 被GraphOrchestrator替代/整合 |
| **graph_orchestrator.py** | core/ | 图编排引擎 | Layer 3的下游消费者 |
| **module_registry.py** | core/modules/ | 模块注册表 | Layer 3节点展开的数据源 |
| **nodes/** | core/nodes/ | 节点实现 | B层的执行单元 |
| **skills/** | skills/agent-a-trading/ | SKILL方法论 | A链执行的方法论 |

### 7.2 演进路径

```
当前状态：
  用户输入 → chain_planner（规则意图） → chain_router（固定链路由） → 节点执行

目标状态：
  用户输入 → [Layer1]意图识别（收敛） → [Layer2]OKR分解（展开） → [Layer3]B层工程化（落地）
           → GraphOrchestrator（图编排） → 节点执行

演进步骤：
  Phase 1: 新增IntentRecognitionEngine，与现有chain_planner并行
  Phase 2: Layer1+Layer2上线，替代chain_planner的意图分类
  Phase 3: Layer3上线，Blueprint直接喂给GraphOrchestrator
  Phase 4: 逐步淘汰chain_router的固定路由逻辑
```

---

## 8. 实现计划

### Phase 1: 核心三层 (P0)

| 任务 | 说明 | 优先级 |
|------|------|--------|
| 类型定义 | Objective/KeyResult/OKRSet/ExecutionBlueprint 完整结构 | P0 |
| Layer 1实现 | 目标提取 + 关键词匹配 + 分类 + 澄清 | P0 |
| Layer 2实现 | OKR分解（single模式模板 + multi模式模板） | P0 |
| Layer 3实现 | 蓝图构建（节点展开 + 依赖图 + 拓扑排序 + 工程配置） | P0 |
| 引擎整合 | IntentRecognitionEngine 完整流程 | P0 |
| Bridge API | /api/v1/intent/* 接口 | P0 |
| 单元测试 | 三层各组件 + 端到端测试 | P0 |

### Phase 2: 增强功能 (P1)

| 任务 | 说明 | 优先级 |
|------|------|--------|
| 重规划器 | Replanner（借鉴 LangGraph Plan-and-Execute） | P1 |
| 澄清引擎 | LLM生成澄清问题 + 多轮澄清 | P1 |
| 上下文管理 | 会话状态 + 多轮对话 + 历史目标追踪 | P1 |
| 市场数据打分 | MktScorer 增强，支持多源信号融合 | P1 |
| 动态KR生成 | LLM根据目标动态生成KR（而非模板匹配） | P1 |

### Phase 3: 高级特性 (P2)

| 任务 | 说明 | 优先级 |
|------|------|--------|
| 子图委派 | 复杂KR委派给子编排器（借鉴 DeepAgents） | P2 |
| 目标学习 | 基于用户反馈的目标模板优化 | P2 |
| 自定义目标 | registerObjectiveType 完整实现 | P2 |
| 多目标管理 | 支持同时追踪多个目标（多Objective） | P2 |
| 目标冲突检测 | 多目标冲突检测与优先级协调 | P2 |

---

## 9. 文件结构

```
experiments/ab-trading/
├── core/
│   ├── intent_engine/                     # 意图识别引擎 (S链)
│   │   ├── __init__.py
│   │   ├── engine.py                     # 主编排器（三层贯通）
│   │   ├── types.py                      # 类型定义（Objective/KR/OKRSet/Blueprint）
│   │   │
│   │   ├── layer1_intent/                # Layer 1: 收敛（意图识别层）
│   │   │   ├── __init__.py
│   │   │   ├── objective_extractor.py    # 目标提取器
│   │   │   ├── nl_parser.py              # 自然语言解析
│   │   │   ├── mkt_scorer.py             # 市场数据打分
│   │   │   └── clarify_engine.py         # 澄清引擎
│   │   │
│   │   ├── layer2_okr/                   # Layer 2: 展开（OKR目标分解层）
│   │   │   ├── __init__.py
│   │   │   ├── okr_builder.py            # OKR构建器
│   │   │   ├── complexity_assessor.py    # 复杂度评估器
│   │   │   └── templates/                # KR模板库
│   │   │       ├── __init__.py
│   │   │       ├── single_line.py        # 单线模式模板
│   │   │       └── multi_line.py         # 多线模式模板
│   │   │
│   │   └── layer3_blueprint/            # Layer 3: 落地（B层工程化）
│   │       ├── __init__.py
│   │       ├── blueprint_builder.py     # 蓝图构建器（主入口）
│   │       ├── node_expander.py         # 节点展开器（KR→节点）
│   │       ├── dependency_mapper.py     # 依赖映射器（KR依赖→节点依赖）
│   │       ├── topo_sorter.py           # 拓扑排序器
│   │       ├── parallel_identifier.py   # 并行组识别器
│   │       ├── engineering_config.py    # 工程配置（超时/重试/降级）
│   │       └── replanner.py             # 重规划器（deep复杂度用）
│   │
│   └── ...
├── bridge_server.py                      # 更新：添加 /api/v1/intent/* 接口
└── test_intent_engine.py                # 测试文件
```

---

**待评审后实施**
