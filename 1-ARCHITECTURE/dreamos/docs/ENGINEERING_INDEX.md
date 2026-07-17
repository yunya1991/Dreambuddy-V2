# Dream OS 工程索引 v2.1

> **文档层级**: L1 — 系统级 SSoT（单真源）
> **版本**: v2.1.0
> **更新日期**: 2026-07-15
> **维护者**: Dream OS Core Team
> **关联文档**: [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)

---

## 0. 使用规则

### 0.1 SSoT 层级

| 层级 | 文档 | 权威范围 |
|------|------|----------|
| L0 | `/ENGINEERING_INDEX.md` | 全局工程索引 |
| **L1（本文档）** | `1-ARCHITECTURE/dreamos/docs/ENGINEERING_INDEX.md` | **Dream OS 系统级工程索引** |
| L2 | 各子模块 README / 代码注释 | 文件级实现细节 |

### 0.2 变更流程

1. 修改代码 → 同步更新本文档对应章节
2. 架构变更 → 先更新 [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md)，再同步本文档
3. 新增模块 → 在 §3 系统索引中增加条目

### 0.3 必读入口

| 角色 | 推荐入口 |
|------|----------|
| 新开发者 | §1 系统概览 → §2 目录结构 → §3.1 SACG 四层内核 |
| 节点开发者 | §3.4 节点体系 → §3.3 适配器框架 → §3.2 Registry |
| 应用开发者 | §3.6 应用层 → §3.7 CLI 工具 → §5 接口速查 |
| 运维/部署 | §7 部署运维 → §6 配置管理 |

---

## 1. 系统概览

### 1.1 系统定位

Dream OS 是 Dreambuddy-v2 的**操作系统内核**，采用"OS内核 + 能力层 + 应用层"的三层操作系统级架构设计。

**核心设计哲学：纯编排层，不重复建设能力**——OS 内核只负责"调度"，所有具体能力通过适配器接入，不改核心代码。

### 1.2 核心特性

| 特性 | 说明 |
|------|------|
| **意图驱动** | 从自然语言到意图识别再到图编排执行，三层递进 |
| **图是一等公民** | 所有执行以图结构组织，可追溯、可压缩、可展开 |
| **SACG 四层架构** | Sense感知 → Arrange编排 → Compute执行 → GraphStore存储 |
| **节点即能力** | 22个内置节点 + 适配器动态扩展，节点通过 Registry 管理 |
| **适配器框架** | 支持 Function / SKILL / API 三种适配器，统一抽象为 Node |
| **自我进化** | 三层反思闭环 + 经验提炼 + 差距分析 + 优化建议 |
| **预算管控** | 三级预算（lean/standard/full）+ 全局 Token 管控 + 降级策略 |
| **上下文压缩** | G层原生支持状态压缩、历史回放、检查点回滚 |

### 1.3 技术栈

| 层次 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| 核心框架 | 自研 SACG 架构 |
| 节点体系 | 自研 Registry + BaseNode 抽象 |
| 适配器 | FunctionAdapter / SkillAdapter / APIAdapter |
| LLM 接入 | 统一 LLMClient 抽象（支持多后端） |
| 状态管理 | State + NodeResult + GraphStore |
| 配置管理 | YAML + 环境变量 |
| 测试框架 | pytest |
| 包结构 | `dreamos` Python 包 |

### 1.4 关键指标

| 指标 | 值 |
|------|-----|
| 内核版本 | v2.1.0 |
| 核心代码文件 | ~50个 |
| 内置节点数 | 22个（A系列10个 + C系列4个 + F系列5个 + G系列2个 + 1个初始化） |
| 适配器类型 | 3种（Function / SKILL / API） |
| 意图类型 | 6种标准 + 可扩展 |
| 市场场景 | 36种（趋势×3 × 波动率×4 × 动量×3） |
| 编排模式 | 5种（c_chain / c_f_chain / full_chain / f_chain / c_g_chain） |
| 预算模式 | 3档（lean/standard/full） |
| 测试覆盖率 | 5个测试套件（冒烟/感知层/ACG层/多场景/横切） |

---

## 2. 目录结构

```
1-ARCHITECTURE/dreamos/
├── docs/                         # 系统文档（L1级SSoT）
│   ├── ENGINEERING_INDEX.md      # 工程索引（本文档）
│   └── TECHNICAL_DESIGN.md       # 技术设计文档
│
├── core/                         # SACG 四层内核
│   ├── __init__.py
│   ├── sense/                    # S层 — 感知/意图识别
│   │   ├── __init__.py
│   │   ├── intent_engine.py      # 意图引擎主入口
│   │   ├── types.py              # 意图类型定义
│   │   ├── token_budget.py       # Token预算管理（单周期）
│   │   ├── scenario_classifier.py # 场景分类器
│   │   └── recognizers/          # 识别器集合
│   │       ├── __init__.py
│   │       ├── base.py           # 识别器基类
│   │       ├── rule_based.py     # 规则识别器（零Token）
│   │       ├── llm_based.py      # LLM识别器
│   │       └── dynamic.py        # 动态意图识别器
│   │
│   ├── arrange/                  # A层 — 图编排
│   │   ├── __init__.py
│   │   ├── graph_planner.py      # 图规划器主入口
│   │   ├── types.py              # 编排类型定义
│   │   ├── node_selector.py      # 节点选择器
│   │   ├── budget_allocator.py   # 预算分配器
│   │   └── execution_graph.py    # 执行图（顺序图/条件图）
│   │
│   ├── compute/                  # C层 — 执行
│   │   ├── __init__.py
│   │   ├── graph_executor.py     # 图执行器主入口
│   │   ├── types.py              # 执行类型定义
│   │   ├── node_runner.py        # 节点运行器
│   │   ├── reflector.py          # 反射决策器
│   │   └── aggregator.py         # 结果聚合器
│   │
│   ├── graph_store/              # G层 — 图存储
│   │   ├── __init__.py
│   │   ├── store.py              # 图存储主入口
│   │   ├── types.py              # 存储类型定义
│   │   ├── checkpointer.py       # 检查点管理器
│   │   ├── compressor.py         # 上下文压缩器
│   │   └── history.py            # 历史回放器
│   │
│   └── memory/                   # 记忆扩展模块
│       ├── __init__.py
│       ├── execution_feedback.py # 执行反馈收集器（驱动进化）
│       ├── orchestration_memory.py # 编排记忆表（场景-编排映射）
│       └── scenario_backtester.py # 场景回测器
│
├── registry/                     # 节点注册表
│   ├── __init__.py
│   ├── base.py                   # BaseNode 基类
│   ├── node_registry.py          # 节点注册表
│   ├── decorators.py             # 注册装饰器
│   ├── loader.py                 # 节点加载器
│   └── version_manager.py        # 版本管理器
│
├── adapters/                     # 适配器框架
│   ├── __init__.py
│   ├── base.py                   # 适配器基类 + AdapterRegistry
│   ├── function_adapter.py       # 函数适配器
│   ├── skill_adapter.py          # SKILL适配器
│   └── api_adapter.py            # API适配器
│
├── nodes/                        # 内置节点库（22个）
│   ├── __init__.py               # 注册入口 register_all()
│   ├── a0_contradiction.py       # A0 矛盾论分析
│   ├── a1_deep_research.py       # A1 深度调研
│   ├── a2_comprehensive.py       # A2 综合分析
│   ├── a3_strategy.py            # A3 策略制定
│   ├── a4_gate.py                # A4 决策门禁
│   ├── a5_execution.py           # A5 执行规划
│   ├── a6_regime_monitor.py      # A6 市态监控
│   ├── a7_practice_gate.py       # A7 实践门禁
│   ├── a8_unity.py               # A8 统一升华
│   ├── a9_exit_strategy.py       # A9 离场策略
│   ├── c1_tech_scan.py           # C1 技术扫描
│   ├── c2_momentum.py            # C2 动量分析
│   ├── c3_volatility.py          # C3 波动率分析
│   ├── c5_exit_system.py         # C5 离场系统
│   ├── f1_news.py                # F1 新闻分析
│   ├── f2_flow_analysis.py       # F2 资金流分析
│   ├── f3_valuation.py           # F3 估值分析
│   ├── f4_onchain_data.py        # F4 链上数据
│   ├── f5_macro_analysis.py      # F5 宏观分析
│   ├── g1_risk_control.py        # G1 风控
│   └── g2_governance.py          # G2 治理
│
├── evolution/                    # 自我进化引擎
│   ├── __init__.py
│   ├── engine.py                 # 进化引擎主入口
│   ├── types.py                  # 进化类型定义
│   ├── lesson_distiller.py       # 经验教训提炼器
│   ├── gap_analyzer.py           # 知行差距分析器
│   └── node_optimizer.py         # 节点优化建议器
│
├── budget/                       # 预算管理
│   ├── __init__.py
│   ├── global_budget.py          # 全局预算管理器
│   └── cost_tracker.py           # 成本追踪器
│
├── apps/                         # 应用层
│   ├── __init__.py
│   ├── trading_agent/            # 交易Agent应用
│   │   ├── __init__.py
│   │   └── agent.py              # TradingAgent 主类
│   ├── api_server.py             # API 服务
│   └── cli.py                    # CLI 入口
│
├── cli/                          # CLI 工具
│   ├── __init__.py
│   ├── __main__.py               # python -m dreamos.cli
│   ├── app.py                    # CLI 主应用
│   ├── base.py                   # 命令基类 + 上下文
│   ├── commands.py               # 基础命令
│   ├── repl.py                   # 交互式 REPL
│   ├── scheduler.py              # 调度器
│   ├── scheduler_commands.py     # 调度命令
│   ├── auto_commands.py          # 自动化命令
│   ├── auto_scheduler.py         # 自动调度器
│   ├── auto_trader.py            # 自动交易器
│   ├── bcrm2_scheduler.py        # BCRM2 调度器
│   ├── orchestration_commands.py # 编排命令
│   ├── analyze_commands.py       # 分析命令
│   ├── start_scheduler.py        # 启动调度器
│   ├── evolution_test.py         # 进化测试
│   ├── stress_test.py            # 压力测试
│   └── scheduler_data/           # 调度器数据
│       ├── scheduler_jobs.json
│       └── scheduler_history.json
│
├── shared/                       # 共享基础组件
│   ├── __init__.py
│   ├── state.py                  # State / NodeResult / NodeStatus
│   ├── interfaces.py             # Node / Graph / Edge / Registry / Adapter 接口
│   ├── errors.py                 # 错误码 + OSError
│   ├── llm_client.py             # LLM 客户端抽象
│   └── utils.py                  # 工具函数集合
│
├── config/                       # 配置
│   └── nodes.yaml                # 节点配置
│
├── dreamos-tests/                # 测试套件（兄弟目录）
│   ├── test_smoke.py             # 冒烟测试
│   ├── test_sense_layer.py       # 感知层测试
│   ├── test_acg_layers.py        # ACG层测试
│   ├── test_multi_scenario.py    # 多场景测试
│   └── test_cross_cutting.py     # 横切关注点测试
│
├── __init__.py                   # 包入口（v2.0.0）
└── com.dreambuddy.dreamos.plist  # launchd 配置
```

---

## 3. 系统索引

### 3.1 SACG 四层内核

#### 3.1.1 S层 — 感知/意图识别

**主入口**: `core/sense/intent_engine.py` → `IntentEngine`

| 组件 | 文件 | 职责 |
|------|------|------|
| IntentEngine | `intent_engine.py` | 意图引擎主入口，组合多识别器，管理Token预算 |
| TokenBudgetManager | `token_budget.py` | 单周期Token预算管理 |
| ScenarioClassifier | `scenario_classifier.py` | 36 场景分类器（趋势×波动率×动量三维分类） |
| RuleBasedRecognizer | `recognizers/rule_based.py` | 规则识别器（零Token，关键词匹配） |
| LLMBasedRecognizer | `recognizers/llm_based.py` | LLM识别器（高置信度，消耗Token） |
| DynamicIntentRecognizer | `recognizers/dynamic.py` | 动态意图识别器（基于历史反馈） |
| IntentType | `types.py` | 6种标准意图类型枚举 + 可扩展 |

**6种标准意图**:
- `TREND_FOLLOWING` — 趋势跟随
- `MEAN_REVERSION` — 均值回归
- `FUNDAMENTAL_PLAY` — 基本面驱动
- `BREAKOUT` — 突破
- `KNOWLEDGE_MATCH` — 知识库匹配
- `UNCERTAIN` — 不确定/需要澄清

**36 种市场场景分类**（三维笛卡尔积）:
- 趋势方向：BULL / BEAR / NEUTRAL（3种）
- 波动率等级：LOW / NORMAL / HIGH / EXTREME（4种）
- 动量加速度：ACCELERATING / DECELERATING / EXHAUSTION（3种）
- 场景 ID 格式：`{TREND}_{VOLATILITY}_{MOMENTUM}`，如 `BULL_NORMAL_ACCELERATING`

**执行流程**:
```
规则识别（零Token）
    ↓ 置信度 >= threshold ?
┌───┴───┐
是       否
↓        ↓
直接返回  Token预算充足 ?
         ┌───┴───┐
         是       否
         ↓        ↓
      LLM识别   降级返回
         ↓
     结果融合
         ↓
     最终输出
```

#### 3.1.2 A层 — 图编排

**主入口**: `core/arrange/graph_planner.py` → `GraphPlanner`

| 组件 | 文件 | 职责 |
|------|------|------|
| GraphPlanner | `graph_planner.py` | 图规划器主入口，输出ExecutionPlan |
| NodeSelector | `node_selector.py` | 节点选择器（按意图/链/优先级选节点） |
| BudgetAllocator | `budget_allocator.py` | 预算分配器（给各节点分配Token预算） |
| SequentialGraph | `execution_graph.py` | 顺序执行图 |
| ConditionalGraph | `execution_graph.py` | 条件执行图 |
| ExecutionPlan | `types.py` | 执行计划数据结构 |

**执行流程**:
```
IntentResult (from S层)
    ↓
确定链路 (A/C/F)
    ↓
NodeSelector 选节点
    ↓
BudgetAllocator 分配预算
    ↓
构建 ExecutionGraph
    ↓
输出 ExecutionPlan → 写入 state.plan
```

**标准链路配置**（`STANDARD_CHAINS`）:
- A链：A0 → A1 → A2 → A3 → A4 → A5 → A6 → A7 → A8 → A9
- C链：C1 → C2 → C3 → C5
- F链：F1 → F2 → F3 → F4 → F5

**编排记忆表**（`core/memory/orchestration_memory.py` → `OrchestrationMemory`）:
- 存储 36 场景 × 5 种编排模式的最优映射
- 四级降级查询：L0精确匹配 → L1趋势×波动率 → L2仅趋势 → L3默认c_chain
- 5 种编排模式：c_chain / c_f_chain / full_chain / f_chain / c_g_chain

#### 3.1.3 C层 — 执行

**主入口**: `core/compute/graph_executor.py` → `GraphExecutor`

| 组件 | 文件 | 职责 |
|------|------|------|
| GraphExecutor | `graph_executor.py` | 图执行器主入口，输出ExecutionReport |
| NodeRunner | `node_runner.py` | 节点运行器（执行单个节点，支持重试） |
| Reflector | `reflector.py` | 反射决策器（每步后决定下一步动作） |
| Aggregator | `aggregator.py` | 结果聚合器（多节点结果融合） |

**反射决策动作**（`ReflectAction`）:
- `CONTINUE` — 继续下一节点
- `REDO` — 重做当前节点
- `INSERT` — 插入新节点
- `JUMP` — 跳转到指定节点
- `TERMINATE` — 提前终止

**执行流程**:
```
Graph.get_entry()
    ↓
NodeRunner.run(node, state)
    ↓
Reflector.decide(result, state)
    ↓
┌───┴───────────────────┐
CONTINUE   REDO  INSERT  JUMP  TERMINATE
↓          ↓     ↓       ↓     ↓
next_node  redo  insert  jump  aggregate
↓
...循环...
↓
Aggregator.aggregate(state)
↓
ExecutionReport
```

#### 3.1.4 G层 — 图存储

**主入口**: `core/graph_store/store.py` → `GraphStore`

| 组件 | 文件 | 职责 |
|------|------|------|
| GraphStore | `store.py` | 图存储主入口，整合三大子系统 |
| Checkpointer | `checkpointer.py` | 状态检查点（保存/回滚） |
| ContextCompressor | `compressor.py` | 上下文压缩器（State过大时自动压缩） |
| HistoryReplay | `history.py` | 历史回放器（历史查询/模式识别/回放） |

**核心能力**:
- 执行中自动保存检查点（max 50个）
- State 超过阈值自动压缩（默认 10000 tokens）
- 执行完成后记录历史（max 200条）
- 支持历史模式识别和回放
- 支持检查点回滚

---

### 3.2 Registry — 节点注册表

**主入口**: `registry/node_registry.py` → `NodeRegistry`

| 组件 | 文件 | 职责 |
|------|------|------|
| NodeRegistry | `node_registry.py` | 节点注册表（唯一真相源） |
| BaseNode | `base.py` | 节点基类（所有节点的父类） |
| register_node | `decorators.py` | 装饰器方式注册节点 |
| NodeLoader | `loader.py` | 节点加载器（从配置/目录批量加载） |
| VersionManager | `version_manager.py` | 节点版本管理器 |

**设计原则**:
- **单一真相源**: 一个 node_id 只能注册一次
- **线程安全**: 基本操作加 RLock
- **可观测**: `list_nodes()` / `summary()` 提供注册表视图
- **动态可扩展**: 支持运行时动态注册和注销

**BaseNode 核心接口**:
```python
class BaseNode(Node):
    node_id: str           # 节点唯一ID
    name: str              # 节点名称
    chain: str             # 所属链路 (A/C/F/G)
    tags: List[str]        # 标签
    version: str           # 版本号

    def execute_core(self, state: State) -> NodeResult:
        """核心执行逻辑，子类实现"""
        ...
```

---

### 3.3 适配器框架

**主入口**: `adapters/base.py` → `AdapterRegistry`

| 适配器 | 文件 | 适配目标 |
|--------|------|----------|
| FunctionAdapter | `function_adapter.py` | 本地 Python 函数 → FunctionNode |
| SkillAdapter | `skill_adapter.py` | SKILL.md 技能描述 → SkillNode |
| APIAdapter | `api_adapter.py` | HTTP API 接口 → APINode |

**设计理念**: 将外部能力统一包装为 Node，使 OS 内核无需关心能力的具体实现方式。

**AdapterRegistry 使用**:
```python
reg = AdapterRegistry()
reg.register(FunctionAdapter())
reg.register(SkillAdapter())
reg.register(APIAdapter())

node = reg.to_node({"type": "function", "handler": my_func})
node = reg.to_node({"type": "skill", "skill_path": "path/to/skill"})
node = reg.to_node({"type": "api", "url": "https://api.example.com"})
```

---

### 3.4 节点体系（22个内置节点）

**主入口**: `nodes/__init__.py` → `register_all(registry)`

#### 3.4.1 A系列 — 决策链（10个节点）

| 节点 | 文件 | 名称 | 职责 |
|------|------|------|------|
| A0 | `a0_contradiction.py` | 矛盾论分析 | 识别市场主要矛盾和次要矛盾 |
| A1 | `a1_deep_research.py` | 深度调研 | 多维度深度调研，收集信息 |
| A2 | `a2_comprehensive.py` | 综合分析 | 综合各维度信息，形成判断 |
| A3 | `a3_strategy.py` | 策略制定 | 制定具体交易策略 |
| A4 | `a4_gate.py` | 决策门禁 | 风险收益评估，决定是否执行 |
| A5 | `a5_execution.py` | 执行规划 | 制定详细执行计划 |
| A6 | `a6_regime_monitor.py` | 市态监控 | 监控市场状态变化 |
| A7 | `a7_practice_gate.py` | 实践门禁 | 实践验证门禁 |
| A8 | `a8_unity.py` | 统一升华 | 理论实践统一，经验升华 |
| A9 | `a9_exit_strategy.py` | 离场策略 | 制定离场策略 |

#### 3.4.2 C系列 — 技术分析链（4个节点）

| 节点 | 文件 | 名称 | 职责 |
|------|------|------|------|
| C1 | `c1_tech_scan.py` | 技术扫描 | 多周期技术指标扫描 |
| C2 | `c2_momentum.py` | 动量分析 | 动量指标分析（RSI/MACD/KDJ等） |
| C3 | `c3_volatility.py` | 波动率分析 | 波动率分析（ATR/Bollinger等） |
| C5 | `c5_exit_system.py` | 离场系统 | 技术面离场决策 |

#### 3.4.3 F系列 — 基本面链（5个节点）

| 节点 | 文件 | 名称 | 职责 |
|------|------|------|------|
| F1 | `f1_news.py` | 新闻分析 | 新闻情绪与影响分析 |
| F2 | `f2_flow_analysis.py` | 资金流分析 | 资金流向分析 |
| F3 | `f3_valuation.py` | 估值分析 | 估值模型分析 |
| F4 | `f4_onchain_data.py` | 链上数据 | 链上数据分析 |
| F5 | `f5_macro_analysis.py` | 宏观分析 | 宏观经济分析 |

#### 3.4.4 G系列 — 治理链（2个节点）

| 节点 | 文件 | 名称 | 职责 |
|------|------|------|------|
| G1 | `g1_risk_control.py` | 风控 | 风险控制检查 |
| G2 | `g2_governance.py` | 治理 | 合规治理审查 |

---

### 3.5 自我进化引擎

**主入口**: `evolution/engine.py` → `EvolutionEngine`

| 组件 | 文件 | 职责 |
|------|------|------|
| EvolutionEngine | `engine.py` | 进化引擎主入口，输出EvolutionReport |
| LessonDistiller | `lesson_distiller.py` | 经验教训提炼（从历史中提取模式） |
| GapAnalyzer | `gap_analyzer.py` | 知行差距分析（预期 vs 实际） |
| NodeOptimizer | `node_optimizer.py` | 节点优化建议器 |
| ExecutionFeedbackCollector | `core/memory/execution_feedback.py` | 执行反馈收集器（驱动编排优化） |

**进化触发源**:
1. **orchestration_optimization** — 执行反馈驱动的编排优化（主要触发源）
   - 触发条件1：连续 3 笔方向准确率 < 50%
   - 触发条件2：夏普比率偏差 > 30%
   - 优化策略：切换到含风控的编排模式（c_g_chain）

2. **历史数据驱动** — G 层历史数据分析（LessonDistiller）

**进化流程**:
```
G层历史数据 + 执行反馈
    ↓
LessonDistiller → 提炼经验教训
    ↓
GapAnalyzer → 分析知行差距
    ↓
NodeOptimizer → 生成优化建议
    ↓
_check_orchestration_optimization → 编排优化
    ↓
EvolutionReport（教训 + 差距 + 建议 + 编排更新）
```

---

### 3.6 应用层

#### 3.6.1 Trading Agent

**主入口**: `apps/trading_agent/agent.py` → `TradingAgent`

将 S-A-C-G 四层内核串联为完整的交易 Agent：

```
用户输入 + 市场数据
    ↓
S层 (IntentEngine) → 识别交易意图
    ↓
A层 (GraphPlanner) → 编排执行图
    ↓
C层 (GraphExecutor) → 执行节点
    ↓
G层 (GraphStore) → 持久化 + 历史记录
    ↓
返回最终结果（action + confidence + reasoning）
```

**核心特性**:
- 节点可插拔：通过 Registry 管理，新增节点不影响 Agent
- 预算全局管控：GlobalBudgetManager 统一分配
- 状态可追溯：GraphStore 保存每个周期的完整快照
- 自我进化：历史数据驱动 Evolution 持续优化

#### 3.6.2 API Server

**文件**: `apps/api_server.py`

提供 HTTP API 服务，支持远程调用 Dream OS 能力。

#### 3.6.3 CLI

**文件**: `apps/cli.py` + `cli/` 目录

命令行交互入口，支持 REPL 模式和多种子命令。

---

### 3.7 CLI 工具

**主入口**: `cli/app.py` → `CLIApp`

#### 3.7.1 核心命令

| 命令 | 文件 | 说明 |
|------|------|------|
| repl | `repl.py` | 交互式 REPL（默认入口） |
| scheduler | `scheduler.py` | 任务调度器 |
| auto | `auto_commands.py` | 自动化命令集 |
| orchestration | `orchestration_commands.py` | 编排相关命令 |
| analyze | `analyze_commands.py` | 分析命令 |
| start-scheduler | `start_scheduler.py` | 启动调度器 |

#### 3.7.2 自动化工具

| 工具 | 文件 | 说明 |
|------|------|------|
| auto_scheduler | `auto_scheduler.py` | 自动调度器 |
| auto_trader | `auto_trader.py` | 自动交易器（完整自动化交易闭环） |
| bcrm2_scheduler | `bcrm2_scheduler.py` | BCRM2 调度器 |
| evolution_test | `evolution_test.py` | 进化测试 |
| stress_test | `stress_test.py` | 压力测试 |

**AutoTrader 核心能力**:
- 36 场景分类 + 编排记忆四级降级
- 双交易所支持（Hyperliquid / OKX）
- dry_run 模拟交易模式
- 交易反馈自动回写 + 进化引擎触发
- 最小交易间隔保护（30 分钟）
- G1 风控门禁强制检查

#### 3.7.3 调度器

**主类**: `cli/scheduler.py` → `DreamOSScheduler`

**特性**:
- Cron 表达式配置定时任务
- 多币种批量扫描
- 任务状态管理（running/paused/stopped/error）
- 执行历史记录
- 线程安全设计

#### 3.7.4 调度器数据

| 文件 | 说明 |
|------|------|
| `scheduler_data/scheduler_jobs.json` | 调度任务配置（默认 5 分钟扫描 8 个主流币种） |
| `scheduler_data/scheduler_history.json` | 调度历史记录 |

**默认调度配置**:
```json
[
  {
    "name": "scan_main",
    "cron_expr": "*/5 * * * *",
    "enabled": true,
    "symbols": ["BTC", "ETH", "SOL", "AVAX", "LINK", "ARB", "OP", "MATIC"]
  }
]
```

---

### 3.8 预算管理

**主入口**: `budget/global_budget.py` → `GlobalBudgetManager`

| 组件 | 文件 | 职责 |
|------|------|------|
| GlobalBudgetManager | `global_budget.py` | 全局预算管理器（跨周期） |
| CostTracker | `cost_tracker.py` | 成本追踪器 |
| TokenBudgetManager | `core/sense/token_budget.py` | 单周期预算（S层内） |

**预算模式（3档）**:

| 模式 | per_cycle | per_day | per_month | 适用场景 |
|------|-----------|---------|-----------|----------|
| lean | 3,000 | 30,000 | 500,000 | 极简模式，测试用 |
| standard | 6,000 | 60,000 | 1,000,000 | 标准模式，默认 |
| full | 10,000 | 100,000 | 2,000,000 | 全功能模式 |

**降级策略**:
1. 预算充足 → 正常执行
2. 预算预警 → 减少可选节点
3. 预算紧张 → 跳过 LLM 识别，纯规则模式
4. 预算耗尽 → 切换到经典指标系统（零 Token）

---

### 3.9 共享基础组件

**目录**: `shared/`

| 组件 | 文件 | 职责 |
|------|------|------|
| State | `state.py` | 全局状态容器 |
| NodeResult | `state.py` | 节点执行结果 |
| NodeStatus | `state.py` | 节点状态枚举 |
| interfaces | `interfaces.py` | 核心接口（Node/Graph/Edge/Registry/Adapter） |
| ErrorCode | `errors.py` | 错误码枚举 |
| OSError | `errors.py` | OS 异常类 |
| LLMClient | `llm_client.py` | LLM 客户端抽象 |
| utils | `utils.py` | 工具函数（Timer/safe_json/retry/chunk等） |

---

### 3.10 测试体系

**目录**: `dreamos-tests/`（兄弟目录）

| 测试文件 | 测试范围 |
|----------|----------|
| `test_smoke.py` | 冒烟测试 — 核心抽象 import / 基本流程 |
| `test_sense_layer.py` | 感知层测试 — 意图识别 / 预算管理 |
| `test_acg_layers.py` | ACG层测试 — 编排/执行/存储 |
| `test_multi_scenario.py` | 多场景测试 — 多种意图场景端到端 |
| `test_cross_cutting.py` | 横切关注点测试 — Registry/Evolution/Budget |

**运行方式**:
```bash
cd 1-ARCHITECTURE
python -m pytest dreamos-tests/ -v
```

---

## 4. 系统间依赖关系

### 4.1 内部模块依赖

```
                    ┌─────────────────────┐
                    │   shared/（共享基础）  │
                    └─────────┬───────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ↓                   ↓                   ↓
   ┌─────────────┐   ┌─────────────┐   ┌─────────────┐
   │  registry/  │   │  adapters/  │   │  budget/    │
   └──────┬──────┘   └─────────────┘   └──────┬──────┘
          │                                   │
          ↓                                   ↓
   ┌───────────────────────────────────────────────┐
   │              core/ (SACG 四层)                 │
   │  sense → arrange → compute → graph_store      │
   └──────────────┬────────────────────────────────┘
                  ↓
           ┌─────────────┐    ┌─────────────┐
           │  nodes/     │    │ evolution/  │
           └──────┬──────┘    └─────────────┘
                  ↓
           ┌─────────────┐
           │  apps/      │
           │  cli/       │
           └─────────────┘
```

### 4.2 外部系统依赖

| 外部系统 | 依赖方式 | 用途 |
|----------|----------|------|
| LLM API | 通过 `LLMClient` 抽象 | 意图识别、节点执行、反思决策 |
| 易经推理系统 (11) | 节点调用 + 数据交互 | BCRM 推理引擎、L4 记忆 |
| 经典指标系统 (10) | 降级 fallback | 预算耗尽时切换到零 Token 模式 |
| 通用风控 (13) | G1 节点调用 | 风险控制检查 |
| SKILL 体系 | SkillAdapter | 动态接入 SKILL 能力 |
| 产物中台 (7) | 产物读写 | 结果持久化和查询 |

### 4.3 数据流

#### 4.3.1 主执行数据流

```
用户输入 + 市场数据
    │
    ▼
┌─────────┐
│ S层     │  IntentEngine
│ 感知    │  → 规则识别 → LLM识别 → 结果融合
└────┬────┘
     │ IntentResult
     ▼
┌─────────┐
│ A层     │  GraphPlanner
│ 编排    │  → 选节点 → 分配预算 → 构建执行图
└────┬────┘
     │ ExecutionPlan + Graph
     ▼
┌─────────┐
│ C层     │  GraphExecutor
│ 执行    │  → 逐节点执行 → 反射决策 → 结果聚合
└────┬────┘
     │ ExecutionReport
     ▼
┌─────────┐
│ G层     │  GraphStore
│ 存储    │  → 检查点 → 压缩 → 历史记录
└────┬────┘
     │
     ▼
 最终结果
```

#### 4.3.2 进化数据流

```
G层历史数据
    │
    ▼
┌─────────────┐
│ Evolution   │  EvolutionEngine
│ 进化引擎     │  → 提炼教训 → 差距分析 → 优化建议
└──────┬──────┘
       │ EvolutionReport
       ▼
  Registry 更新 / 节点优化
```

---

## 5. 关键接口速查

### 5.1 内核主接口

| 接口 | 位置 | 说明 |
|------|------|------|
| `IntentEngine.recognize()` | `core/sense/intent_engine.py` | S层意图识别入口 |
| `GraphPlanner.plan()` | `core/arrange/graph_planner.py` | A层图规划入口 |
| `GraphExecutor.execute()` | `core/compute/graph_executor.py` | C层图执行入口 |
| `GraphStore.checkpoint()` | `core/graph_store/store.py` | G层检查点保存 |
| `GraphStore.record()` | `core/graph_store/store.py` | G层历史记录 |

### 5.2 Registry 接口

| 接口 | 位置 | 说明 |
|------|------|------|
| `NodeRegistry.register()` | `registry/node_registry.py` | 注册节点 |
| `NodeRegistry.get()` | `registry/node_registry.py` | 获取节点 |
| `NodeRegistry.list_nodes()` | `registry/node_registry.py` | 列出节点（可过滤） |
| `register_node` 装饰器 | `registry/decorators.py` | 装饰器方式注册 |

### 5.3 应用层接口

| 接口 | 位置 | 说明 |
|------|------|------|
| `TradingAgent.run()` | `apps/trading_agent/agent.py` | 交易Agent主入口 |
| `TradingAgent.run_cycle()` | `apps/trading_agent/agent.py` | 单周期执行 |
| `CLIApp.run()` | `cli/app.py` | CLI 主入口 |

### 5.4 适配器接口

| 接口 | 位置 | 说明 |
|------|------|------|
| `AdapterRegistry.to_node()` | `adapters/base.py` | 根据配置生成 Node |
| `BaseAdapter.can_handle()` | `adapters/base.py` | 判断是否能处理配置 |
| `BaseAdapter.to_node()` | `adapters/base.py` | 转换为 Node |

---

## 6. 配置管理

### 6.1 配置层级

```
优先级（从高到低）:
1. 代码传入参数（运行时最高优先级）
2. 环境变量（.env / export）
3. YAML 配置文件（config/nodes.yaml）
4. 默认值（代码内定义）
```

### 6.2 主要配置项

| 配置项 | 默认值 | 说明 | 位置 |
|--------|--------|------|------|
| budget_mode | "standard" | 预算模式 (lean/standard/full) | 各入口参数 |
| llm_trigger_threshold | 0.55 | 规则置信度低于此值触发LLM | `core/sense/intent_engine.py` |
| clarify_threshold | 0.35 | 置信度低于此值需要澄清 | `core/sense/intent_engine.py` |
| max_checkpoints | 50 | 最大检查点数量 | `core/graph_store/store.py` |
| max_history | 200 | 最大历史记录数 | `core/graph_store/store.py` |
| auto_compress | True | 是否自动压缩 | `core/graph_store/store.py` |
| compress_threshold | 10000 | 压缩阈值（tokens） | `core/graph_store/store.py` |
| max_retries | 2 | 节点最大重试次数 | `core/compute/graph_executor.py` |
| max_steps | 20 | 最大执行步数 | `core/compute/graph_executor.py` |

### 6.3 节点配置

**文件**: `config/nodes.yaml`

通过 YAML 配置节点元数据、依赖关系、优先级等，支持动态加载。

---

## 7. 部署与运行

### 7.1 运行模式

| 模式 | 入口 | 说明 |
|------|------|------|
| Python 包 | `import dreamos` | 作为库嵌入其他系统 |
| CLI | `python -m dreamos.cli` | 命令行交互 |
| REPL | `dreamos repl` | 交互式会话 |
| API Server | `apps/api_server.py` | HTTP API 服务 |
| Trading Agent | `apps/trading_agent/agent.py` | 交易Agent应用 |
| launchd | `com.dreambuddy.dreamos.plist` | macOS 后台服务 |

### 7.2 快速开始

```python
# 1. 作为库使用
from dreamos.apps.trading_agent import TradingAgent

agent = TradingAgent(budget_mode="standard")
result = agent.run(
    user_input="BTC 现在怎么看？",
    market_data={"price": 65000, "rsi14": 45},
)
print(result["action"], result["confidence"])
```

```bash
# 2. CLI 方式
cd 1-ARCHITECTURE
python -m dreamos.cli repl
```

### 7.3 launchd 部署

**配置文件**: `com.dreambuddy.dreamos.plist`

```bash
# 安装
launchctl load com.dreambuddy.dreamos.plist

# 启动
launchctl start com.dreambuddy.dreamos

# 查看状态
launchctl list | grep dreambuddy
```

### 7.4 日志与状态

| 类型 | 位置 |
|------|------|
| 运行日志 | 各应用自行管理（TradingAgent 可配置） |
| 调度历史 | `cli/scheduler_data/scheduler_history.json` |
| G层历史 | GraphStore 内存 / 可配置持久化目录 |
| 检查点 | 内存 / 可配置存储目录 |

---

## 8. 性能基准

### 8.1 单周期性能估算

| 预算模式 | 预估Token消耗 | 预估耗时 | 说明 |
|----------|--------------|----------|------|
| lean（纯规则） | ~500 | ~1s | 规则识别 + 最小节点集 |
| standard | ~4,000-6,000 | ~10-30s | 标准链路 + 部分LLM节点 |
| full | ~8,000-10,000 | ~30-60s | 全链路 + 全部LLM节点 |

### 8.2 可扩展性

| 维度 | 扩展方式 |
|------|----------|
| 新增节点 | 继承 BaseNode → 放入 nodes/ → 自动注册 |
| 新增适配器 | 继承 BaseAdapter → 注册到 AdapterRegistry |
| 新增意图 | 调用 `register_intent_type()` |
| 新增应用 | 组合 SACG 四层 + 自定义节点集 |

---

## 9. 技术债务索引

| ID | 描述 | 优先级 | 影响范围 |
|----|------|--------|----------|
| D01 | 节点实现多为骨架，缺少完整业务逻辑 | P0 | nodes/ 全部22个节点 |
| D02 | 缺少完整的端到端集成测试 | P1 | 测试体系 |
| D03 | G层持久化存储未完全实现（内存为主） | P1 | graph_store/ |
| D04 | 进化引擎沙箱验证未接入真实回测（简化版） | P1 | evolution/engine.py _sandbox_validate |
| D05 | 缺少生产级监控和告警 | P2 | 运维体系 |
| D06 | API Server 实现不完整 | P2 | apps/api_server.py |
| D07 | 多租户/多会话隔离未实现 | P3 | 架构层 |
| D08 | 文档与实际代码实现存在偏差 | P1 | 文档体系 |
| D09 | 编排优化策略单一（仅切换到c_g_chain） | P2 | evolution/engine.py |
| D10 | 场景回测器未完整实现 | P2 | core/memory/scenario_backtester.py |

---

## 10. 快速导航

### 10.1 按系统角色

| 你想... | 直接去 |
|---------|--------|
| 理解整体架构 | §1 系统概览 + §2 目录结构 |
| 开发新节点 | §3.2 Registry + §3.4 节点体系 |
| 接入新能力 | §3.3 适配器框架 |
| 开发新应用 | §3.6 应用层 |
| 理解执行流程 | §3.1 SACG四层内核 |
| 自动交易系统 | §3.7.2 自动化工具 + §3.7.3 调度器 |
| 场景分类与编排 | §3.1.1 S层 + §3.1.2 A层编排记忆 |
| 进化优化 | §3.5 自我进化引擎 |
| 部署运维 | §7 部署与运行 |
| 排查问题 | §5 关键接口速查 + §6 配置管理 |

### 10.2 按文件入口

| 找什么 | 去哪里 |
|--------|--------|
| OS内核入口 | `dreamos/__init__.py` |
| S层入口 | `core/sense/intent_engine.py` |
| 36场景分类 | `core/sense/scenario_classifier.py` |
| A层入口 | `core/arrange/graph_planner.py` |
| 编排记忆表 | `core/memory/orchestration_memory.py` |
| C层入口 | `core/compute/graph_executor.py` |
| G层入口 | `core/graph_store/store.py` |
| 执行反馈收集 | `core/memory/execution_feedback.py` |
| 进化引擎 | `evolution/engine.py` |
| 节点列表 | `nodes/__init__.py` |
| 应用入口 | `apps/trading_agent/agent.py` |
| 自动交易器 | `cli/auto_trader.py` |
| 调度器 | `cli/scheduler.py` |
| CLI入口 | `cli/app.py` |
| 测试入口 | `dreamos-tests/test_smoke.py` |

---

## 11. 变更日志

| 版本 | 日期 | 变更内容 |
|------|------|----------|
| v2.1 | 2026-07-15 | 新增 36 场景分类系统、编排记忆表与四级降级、执行反馈收集器、进化引擎编排优化机制、自动交易器（AutoTrader）完整链路、DreamOSScheduler 调度器与默认配置、更新技术债务索引、补充快速导航入口 |
| v2.0 | 2026-07-14 | 新建完整系统级工程索引，覆盖 SACG 四层、Registry、适配器、节点体系、进化引擎、应用层、CLI、预算管理、测试体系 |
