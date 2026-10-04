# SPEC-20260919: 基于 DreamOS 的四子交易系统统一编排与反射治理

- **文档ID**: SPEC-20260919-SUBSYSTEM-UNIFIED-ORCHESTRATION
- **类型**: 架构设计规格（Architecture SPEC）
- **创建时间**: 2026-09-19
- **状态**: 🔵 DRAFT（待评审，不落地）
- **维护者**: DreamOS Core Team
- **关联文档**: [TRADING_ORCHESTRATION_PLAN.md](../TRADING_ORCHESTRATION_PLAN.md) | [TECHNICAL_DESIGN.md](../TECHNICAL_DESIGN.md)
- **代码基线**: `1-ARCHITECTURE/dreamos/` (v2.4.0 SACG) + `11-易经推理系统/scripts/memory_l4/`

---

## 0. 文档说明

### 0.1 目标

用 DreamOS 操作系统的图编排（GraphPlanner + GraphExecutor）和反射治理（Reflector）能力，统一管理四个子交易系统——BCRM2.0、BDSM、战略层（五计庙算）、自进化系统，解决当前 `polling_trader.py` 作为 17000+ 行 God Class 直接编排导致的耦合混乱问题。

### 0.2 范围

| 范围 | 包含 | 不包含 |
|------|------|--------|
| 子系统封装 | BCRM2.0 / BDSM / 战略层 / 自进化 → DreamOS Node | 子系统内部算法改造 |
| 编排 | DreamOS Graph 定义子系统依赖与执行顺序 | polling_trader 下单/持仓逻辑 |
| 状态 | DreamOS State 作为统一信号总线 | 持久化持仓状态（仍由 polling_trader 管理） |
| 治理 | Reflector 处理子系统间冲突 | 子系统内部风控逻辑 |
| OrchestratorV2 | 标记为"仅回测用"，不纳入实盘编排 | 废弃或删除（后期处理） |

### 0.3 决策记录

| # | 决策项 | 结论 |
|---|--------|------|
| D1 | OrchestratorV2 处理方式 | 后期仅作回测用，不纳入实盘统一编排 |
| D2 | 实施范围 | 完整做"图编排 + 反射治理"（Phase 1-4） |
| D3 | 性能参数 | 由本 SPEC 评估给出最佳参数（见 §7） |
| D4 | 落地策略 | 先完善 DreamOS 操作系统能力，再接入交易子系统，不改交易代码 |

---

## 1. 背景与问题

### 1.1 现状

四个子交易系统当前由 `polling_trader.py`（17000+ 行）直接编排，存在三类访问模式并存：

| 子系统 | 访问模式 | 耦合方式 |
|--------|----------|----------|
| BCRM2.0 | 直接函数调用 | `BCRM2Adapter.infer()` |
| BDSM | 文件快照 | JSON 文件 + 5min TTL 缓存 |
| 战略层 | 直接函数调用 | `FiveDomainHeuristicScorer.score()` + `StrategyAlgorithmLayer.select()` |
| 自进化 | 状态属性读取 | `SubSystemBridge` 读取 `trader._last_*` 属性 |

### 1.2 核心问题

**P1 — 缺乏统一管理层**：无 `SubsystemManager` 类，polling_trader 直接 import 和调用所有子系统，17000+ 行难以维护。

**P2 — 状态散落**：子系统输出散落在 `trader._last_bcrm2_result`、`trader._last_bdsm_snapshot`、`trader._five_domain_state_shadow/cache` 等隐式属性中，无统一契约。

**P3 — 隐式依赖**：BDSM → 战略层的 `force_vectors` 依赖是隐式的（five_domain_scorer 内部读取），不在编排层可见。

**P4 — 功能重叠**：BDSM 的 `strategic_mapper` 和战略层的 `FiveDomainHeuristicScorer` 都产出 `war_state/cap/mask`，边界不清。

**P5 — 冲突无统一治理**：子系统间矛盾（如 BCRM2.0 反向信号 vs BDSM 同向约束）散落在各消费点处理，无集中治理。

### 1.3 DreamOS 现有能力

DreamOS v2.4.0 SACG 架构已具备统一管理层所需的核心能力：

| 能力 | 实现位置 | 说明 |
|------|----------|------|
| Node 接口 | `shared/interfaces.py` L30-113 | `execute(state)→NodeResult` + `validate` + `fallback` |
| BaseNode 模板 | `registry/base.py` L73-136 | `execute()` 封装校验/计时/异常/fallback，子类实现 `execute_core` |
| State 状态总线 | `shared/state.py` L91-171 | 全局 State，`update(node_id, result)` / `get_result(node_id)` |
| GraphPlanner | `core/arrange/graph_planner.py` | 构建 SequentialGraph / ConditionalGraph |
| GraphExecutor | `core/compute/graph_executor.py` | 按图执行，NodeRunner 驱动单节点 |
| Reflector | `core/compute/reflector.py` | 6 种决策：CONTINUE/REDO/INSERT_BEFORE/JUMP_TO/EARLY_TERMINATE/SKIP |
| Capability 注册 | `capability/registry.py` | 能力域注册、节点发现、启停管理 |

**现有差距**：`capabilities/trading/nodes/subsystem_adapter_nodes.py` 中的 `CS3TrendNode`/`AYJInferNode`/`CMartinV15Node` 均为 `_simulate_*` 模拟实现，未真正接入 polling_trader 的四个子系统。

---

## 2. 目标架构

### 2.1 分层定位

```
┌─────────────────────────────────────────────────────┐
│  polling_trader.py (执行层)                          │
│  职责: run_once 触发 → 消费 State → 下单/持仓/风控   │
└───────────────────────┬─────────────────────────────┘
                        │ 构建 State(market_data) / 消费 State.results
┌───────────────────────▼─────────────────────────────┐
│  DreamOS Graph 编排层 (统一管理层)                    │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌────────┐ │
│  │BCRM20Node│ │ BDSMNode │ │StrategyN │ │EvolNode│ │
│  └────┬─────┘ └────┬─────┘ └────┬─────┘ └───┬────┘ │
│       │            │            │            │      │
│       └────────────┴─── State 信号总线 ───────┘      │
│              Reflector 冲突治理                      │
└─────────────────────────────────────────────────────┘
```

### 2.2 核心设计原则

1. **子系统封装为 Node**：四个子系统各封装为一个 DreamOS Node，实现 `execute_core(state)`，内部调用已有适配器。
2. **State 作为信号总线**：替代散落的 `_last_*` 属性，子系统输出写入 `state.results[node_id]`，消费者通过 `state.get_result()` 读取。
3. **Graph 边显式定义依赖**：BDSM → 战略层的 `force_vectors` 依赖通过图边显式表达，不再隐式。
4. **Reflector 集中治理冲突**：子系统间矛盾统一由 Reflector 决策，不在各消费点分散处理。
5. **polling_trader 仅作执行层**：不再直接编排子系统，改为构建 State → 执行 Graph → 消费 State。

---

## 3. 子系统 Node 封装规范

### 3.1 Node 基类与生命周期

所有子系统 Node 继承 `registry.base.BaseNode`，遵循以下生命周期：

```
execute(state)
  ├── validate(state) → None 表示通过，str 表示失败原因
  ├── execute_core(state) → NodeResult   ← 子类实现
  ├── 异常时 → fallback(state) → NodeResult  (FAIL-OPEN)
  └── 返回 NodeResult (含 latency_ms / degraded 标记)
```

### 3.2 四个子系统 Node 定义

#### 3.2.1 BCRM20Node

| 属性 | 值 |
|------|-----|
| node_id | `SUBSYS_BCRM2` |
| chain | `SUBSYSTEM` |
| 输入 | `state.market[symbol]` (K线/指标) |
| 内部调用 | `BCRM2Adapter.infer(symbol, timeframe, market_data)` |
| 输出 (NodeResult.outputs) | `direction`, `confidence`, `hexagram`, `a0_analysis`, `triangle_verification`, `risk_params` |
| validate | 检查 market_data 非空、symbol 合法 |
| fallback | `direction=NEUTRAL, confidence=0.0, degraded=True` |
| 超时 | 30s |

#### 3.2.2 BDSMNode

| 属性 | 值 |
|------|-----|
| node_id | `SUBSYS_BDSM` |
| chain | `SUBSYSTEM` |
| 输入 | `state.market[symbol]`, `state.extra["bdsm_coins"]` |
| 内部调用 | `force_vector.bdsm_snapshot_writer.load_today_snapshot(symbol)` (优先内存缓存，5min TTL) |
| 输出 (NodeResult.outputs) | `direction_constraint`, `cap_multiplier`, `exit_action`, `bds_score`, `valuation_percentile`, `data_quality`, `force_vectors` |
| validate | 检查 symbol 是否在 BDSM_COINS |
| fallback | `direction_constraint=NEUTRAL, cap_multiplier=1.0, data_quality=insufficient, degraded=True` |
| 超时 | 5s |

**职责边界**：BDSMNode 仅输出单币基本面约束，不再输出 `war_state/cap/mask`（该职责归属战略层，见 §6.2）。

#### 3.2.3 StrategyLayerNode

| 属性 | 值 |
|------|-----|
| node_id | `SUBSYS_STRATEGY` |
| chain | `SUBSYSTEM` |
| 输入 | `state.get_result("SUBSYS_BDSM").outputs["force_vectors"]`, `state.market` (全局) |
| 内部调用 | `FiveDomainHeuristicScorer.score(force_vectors, market)` → `StrategyAlgorithmLayer.select(five_scores, ...)` |
| 输出 (NodeResult.outputs) | `war_state`, `direction_state`, `cap_pct`, `five_scores`, `style_mask`, `front_layer_band` |
| validate | 检查 BDSM 结果存在（依赖边保证） |
| fallback | `war_state=ALLOW, direction_state=NEUTRAL, cap_pct=1.0, style_mask=all, degraded=True` |
| 超时 | 3s |

#### 3.2.4 EvolutionNode

| 属性 | 值 |
|------|-----|
| node_id | `SUBSYS_EVOLUTION` |
| chain | `SUBSYSTEM` |
| 输入 | `state.get_result("SUBSYS_BCRM2")`, `state.get_result("SUBSYS_BDSM")`, `state.get_result("SUBSYS_STRATEGY")` |
| 内部调用 | `dreambuddy_evolution` 引擎（entry_signal_governor / exit_engine / path_discovery） |
| 输出 (NodeResult.outputs) | `entry_weight_factor`, `exit_decision`, `path_recommendations`, `rl_weights` |
| validate | 检查前三个子系统结果存在 |
| fallback | `entry_weight_factor=1.0, exit_decision=HOLD, degraded=True` |
| 超时 | 10s |

### 3.3 Node 输出契约 (NodeResult)

所有子系统 Node 统一使用 DreamOS 的 `NodeResult` 结构（`shared/state.py` L45-64）：

```python
@dataclass
class NodeResult:
    node_id: str
    status: str                    # "success" | "fallback" | "error"
    outputs: Dict[str, Any]        # 子系统输出数据
    confidence: float = 0.0
    direction: str = "NEUTRAL"
    error: Optional[str] = None
    latency_ms: float = 0.0
    tokens_used: int = 0
    retries: int = 0
    degraded: bool = False
    warnings: List[str] = field(default_factory=list)
    suggestions: List[str] = field(default_factory=list)
```

---

## 4. State 信号总线设计

### 4.1 State 结构复用

复用 DreamOS 现有 `State` 类（`shared/state.py` L91-150），利用以下字段：

| State 字段 | 用途 |
|------------|------|
| `market` | 市场数据（K线、指标），由 polling_trader 注入 |
| `results` | 各子系统 Node 的 NodeResult 输出 |
| `trace` | 执行轨迹（含每个节点的 latency_ms） |
| `extra` | 扩展字段（BDSM_COINS、配置开关等） |
| `final_action` / `final_confidence` | Graph 执行后的聚合决策 |

### 4.2 子系统输出命名空间

为避免 key 冲突，子系统输出采用 `subsystem.领域.字段` 命名空间存入 `outputs`：

| Node | outputs 命名空间示例 |
|------|---------------------|
| SUBSYS_BCRM2 | `bcrm2.direction`, `bcrm2.confidence`, `bcrm2.hexagram` |
| SUBSYS_BDSM | `bdsm.direction_constraint`, `bdsm.cap_multiplier`, `bdsm.force_vectors` |
| SUBSYS_STRATEGY | `strategy.war_state`, `strategy.cap_pct`, `strategy.style_mask` |
| SUBSYS_EVOLUTION | `evolution.entry_weight_factor`, `evolution.exit_decision` |

### 4.3 数据流转

```
polling_trader.run_once():
  1. 构建 State(market={...}, extra={"bdsm_coins": [...], "config": {...}})
  2. GraphExecutor.execute(graph, state)
     → 各 Node 从 state.market / state.get_result(前序节点) 读取输入
     → 各 Node 将 NodeResult 写入 state.results[node_id]
  3. polling_trader 从 state.results 读取四子系统输出
  4. 执行下单/持仓/风控逻辑
```

### 4.4 兼容性设计

Phase 2 引入 State 时，保留 polling_trader 原有 `_last_*` 属性作为兼容层：
- Node 执行后同时写入 `state.results` 和 `trader._last_*`
- 消费者逐步迁移到从 State 读取
- Phase 3 完成后移除 `_last_*` 兼容层

---

## 5. Graph 编排设计

### 5.1 子系统依赖图

四个子系统的依赖关系：

```
SUBSYS_BCRM2 ──────────────────────────┐
                                       │
SUBSYS_BDSM ──── force_vectors ────► SUBSYS_STRATEGY
     │                                       │
     └──────────────────────────────────► SUBSYS_EVOLUTION ◄──── SUBSYS_BCRM2
```

依赖说明：
- **SUBSYS_STRATEGY 依赖 SUBSYS_BDSM**：战略层需要 BDSM 的 `force_vectors`（估值分位、离场动作）作为五维评分输入
- **SUBSYS_EVOLUTION 依赖 SUBSYS_BCRM2 + SUBSYS_BDSM + SUBSYS_STRATEGY**：自进化系统需要三个子系统的输出计算入场权重因子和路径发现
- **SUBSYS_BCRM2 和 SUBSYS_BDSM 无依赖**：可并行执行

### 5.2 图类型选择

采用 **ConditionalGraph**（`core/arrange/execution_graph.py` L140-210）而非 SequentialGraph，原因：
1. BCRM2.0 和 BDSM 可并行，需要 DAG 而非纯顺序
2. 支持条件边（如 BDSM data_quality=insufficient 时战略层走降级路径）
3. 支持 Reflector 的 INSERT_BEFORE 动态插入节点

### 5.3 图定义（示意）

```python
graph = ConditionalGraph()
graph.add_node(BCRM20Node())
graph.add_node(BDSMNode())
graph.add_node(StrategyLayerNode())
graph.add_node(EvolutionNode())

# 依赖边
graph.add_edge("SUBSYS_BDSM", "SUBSYS_STRATEGY")     # BDSM → 战略层
graph.add_edge("SUBSYS_BCRM2", "SUBSYS_EVOLUTION")    # BCRM2 → 自进化
graph.add_edge("SUBSYS_BDSM", "SUBSYS_EVOLUTION")     # BDSM → 自进化
graph.add_edge("SUBSYS_STRATEGY", "SUBSYS_EVOLUTION") # 战略层 → 自进化

# 入口：BCRM2.0 和 BDSM 同时启动
graph.set_entry(["SUBSYS_BCRM2", "SUBSYS_BDSM"])
```

### 5.4 拓扑执行

GraphExecutor 按拓扑排序执行：
1. **Wave 1**（并行）：SUBSYS_BCRM2, SUBSYS_BDSM
2. **Wave 2**：SUBSYS_STRATEGY（等待 BDSM 完成）
3. **Wave 3**：SUBSYS_EVOLUTION（等待 BCRM2 + BDSM + 战略层完成）

**性能收益**：BCRM2.0（耗时最长）与 BDSM 并行，总耗时 ≈ max(BCRM2, BDSM) + 战略层 + 自进化，而非串行累加。

---

## 6. Reflector 冲突治理设计

### 6.1 现有 Reflector 能力

DreamOS Reflector（`core/compute/reflector.py`）支持 6 种决策：
- `CONTINUE`：正常继续
- `REDO`：重试当前节点（防无限循环）
- `INSERT_BEFORE`：在当前节点前插入补充节点
- `JUMP_TO`：跳转到指定节点
- `EARLY_TERMINATE`：提前终止
- `SKIP`：跳过当前节点

### 6.2 子系统冲突场景与治理策略

| 冲突场景 | 检测条件 | Reflector 决策 |
|----------|----------|----------------|
| BCRM2.0 方向 vs BDSM 方向约束 | `bcrm2.direction` 与 `bdsm.direction_constraint` 矛盾 | `INSERT_BEFORE` 插入冲突仲裁节点，或 `SKIP` 自进化节点并标记 degraded |
| 战略层 direction_state vs BCRM2.0 方向 | `strategy.direction_state=LONG_ONLY` 但 `bcrm2.direction=DOWN` | 降低最终 confidence，输出 warning |
| 自进化 entry_weight=0 | `evolution.entry_weight_factor <= 0` | `EARLY_TERMINATE` 并标记"无开仓信号" |
| BDSM data_quality=insufficient | `bdsm.data_quality != "sufficient"` | 战略层和自进化走降级路径（cap=1.0, NEUTRAL） |
| 多子系统连续低置信度 | 3+ 节点 confidence < 0.3 | `EARLY_TERMINATE`，本轮不开仓 |

### 6.3 冲突仲裁节点 (ConflictResolverNode)

新增一个可选的 `ConflictResolverNode`，由 Reflector 在检测到冲突时 `INSERT_BEFORE` 到自进化节点前：

| 属性 | 值 |
|------|-----|
| node_id | `SUBSYS_CONFLICT_RESOLVER` |
| 触发条件 | Reflector 检测到子系统间方向/置信度冲突 |
| 输入 | 前序所有子系统的 NodeResult |
| 输出 | `resolved_direction`, `resolved_confidence`, `resolution_rationale` |
| 决策逻辑 | 按置信度加权投票 + BDSM 硬约束优先 |

### 6.4 Reflector 扩展点

在现有 Reflector 的 `decide()` 方法中增加子系统冲突检测逻辑（不修改 SACG 语义，仅增加启发式规则）：
1. 执行完 SUBSYS_STRATEGY 后，检测 BDSM vs BCRM2.0 方向矛盾
2. 执行完 SUBSYS_EVOLUTION 后，检测最终决策合理性
3. 冲突时返回 `INSERT_BEFORE(SUBSYS_CONFLICT_RESOLVER)` 或 `EARLY_TERMINATE`

---

## 7. 性能参数评估

### 7.1 现有热路径特征

| 指标 | 当前值 | 来源 |
|------|--------|------|
| 默认轮询间隔 | 3600s (1h) | `polling_trader.py` L760 `interval=3600` |
| CLI 示例间隔 | 300s (5min) | `polling_trader.py` L20 `--interval 300` |
| 每轮币种数 | 按 MODE 分流（Full/Coarse/Top1），非全量 | `run_once()` L17082-17278 |
| BDSM 快照 TTL | 5min | `_load_bdsm_snapshot()` 缓存逻辑 |
| BDSM 快照生成频率 | 每日一次（每日快照） | `bdsm_snapshot_writer` |

### 7.2 DreamOS Graph 执行开销评估

| 开销项 | 估计值 | 说明 |
|--------|--------|------|
| 图构建（静态预定义） | < 1ms | 子系统图静态，不每次走 GraphPlanner |
| State 构建 | < 1ms | 轻量 dict |
| NodeRunner 调度开销 | ~0.5ms/节点 | validate + 计时 + fallback 包装 |
| Reflector 决策 | ~0.2ms/节点 | 启发式规则，无 LLM |
| **4 节点总调度开销** | **~3ms** | 可忽略 |

**结论**：DreamOS 图编排的调度开销（~3ms）远小于子系统本身的计算耗时（BCRM2.0 单次推理秒级），对热路径性能影响可忽略。

### 7.3 推荐性能参数

| 参数 | 推荐值 | 理由 |
|------|--------|------|
| 子系统图构建方式 | 静态预构建（启动时一次） | 避免每轮 GraphPlanner 规划开销 |
| BCRM20Node 超时 | 30s | 单次推理耗时，超时降级不阻塞 |
| BDSMNode 超时 | 5s | 读快照（内存缓存命中 < 1ms，文件读取 < 1s） |
| StrategyLayerNode 超时 | 3s | 五维评分计算轻量 |
| EvolutionNode 超时 | 10s | 路径发现 + RL 权重计算 |
| 单轮 Graph 总预算 | 120s | 300s 间隔内有充足余量 |
| Node 重试次数 | 1 次 | 交易热路径不等待，快速降级 |
| State 结果缓存 | 跨轮共享（币种级 TTL） | BDSM 快照已缓存，BCRM2.0 结果可缓存 1 轮 |
| 并行执行 | Wave 内并行（BCRM2.0 + BDSM） | 总耗时 ≈ max(BCRM2, BDSM) + 战略层 + 自进化 |

### 7.4 最坏情况耗时估算

```
Wave 1 (并行): max(BCRM2 30s, BDSM 5s) = 30s
Wave 2: 战略层 3s
Wave 3: 自进化 10s
调度+反射开销: ~3ms
─────────────────────────────
总计最坏: ~43s (远小于 300s 间隔)
```

即使 BCRM2.0 满 30s 超时，单轮总耗时 43s，在 300s 间隔内安全。

---

## 8. 分阶段实施路径 (Phase 1-4)

### Phase 1: 子系统 Node 封装（零风险，不改交易逻辑）

**目标**：将四个子系统封装为真实 Node，验证输出与原调用一致。

**任务**：
1. 新建 `BCRM20Node`（替换 `AYJInferNode` 的模拟实现）
2. 新建 `BDSMNode`（调用真实 force_vector 快照）
3. 新建 `StrategyLayerNode`（调用 FiveDomainHeuristicScorer + SAL）
4. 新建 `EvolutionNode`（调用 dreambuddy_evolution）
5. 单元测试：每个 Node 的 happy path + validate 失败 + fallback 降级

**验证**：Node 输出与 polling_trader 原调用输出逐字段对比一致。

**风险**：无（不改变 polling_trader 调用方式，仅新增 Node 类）。

### Phase 2: State 信号总线（低风险）

**目标**：引入 DreamOS State 作为信号总线，替代散落的 `_last_*` 属性。

**任务**：
1. polling_trader 构建 State 并注入 market_data
2. 各子系统 Node 执行后写入 `state.results`
3. 兼容层：同时写入 `trader._last_*` 供现有消费者使用
4. 新增 State 消费者测试

**验证**：State.results 内容与 `_last_*` 属性内容一致。

**风险**：低（兼容层保证不破坏现有逻辑）。

### Phase 3: Graph 编排接入（中风险）

**目标**：polling_trader 推理阶段改为执行 DreamOS Graph。

**任务**：
1. 定义子系统 ConditionalGraph（依赖边见 §5.3）
2. polling_trader `run_once` 推理阶段改为：构建 State → GraphExecutor.execute → 消费 State
3. 保留原推理代码作为 fallback（配置开关切换）
4. 灰度：先 shadow_mode 对比，再实盘切换

**验证**：Graph 编排输出与原串行编排输出一致（允许并行带来的微小时序差异）。

**风险**：中（需验证并行执行的正确性和 FAIL-OPEN 行为）。

### Phase 4: Reflector 冲突治理（中风险）

**目标**：用 Reflector 统一处理子系统间冲突。

**任务**：
1. 扩展 Reflector 增加子系统冲突检测规则（§6.2）
2. 实现 ConflictResolverNode（可选插入）
3. 移除各消费点的分散冲突处理逻辑
4. 回测验证：冲突场景下的决策合理性

**验证**：冲突场景下 Reflector 决策与原分散处理结果一致或更优。

**风险**：中（冲突决策逻辑需充分回测验证）。

---

## 9. DreamOS 需完善的能力

在接入子系统前，需先完善 DreamOS 以下能力：

### 9.1 ConditionalGraph 并行执行支持

**现状**：`ConditionalGraph.get_next()` 单次返回一个节点，GraphExecutor 串行执行。

**需求**：支持 Wave 内多节点并行执行（BCRM2.0 + BDSM）。

**方案**：GraphExecutor 增加拓扑排序，同层级节点并行执行（线程池或 asyncio）。

### 9.2 Node 超时与降级增强

**现状**：NodeRunner 已有超时和 fallback，但超时配置在 Node 级别未标准化。

**需求**：BaseNode 增加 `timeout_seconds` 类属性，NodeRunner 统一应用。

### 9.3 State 币种级多实例

**现状**：State 是单次执行全局状态，不支持多币种各自的子系统结果。

**需求**：State.results 支持 `{node_id: {symbol: NodeResult}}` 结构，或每币种独立 State 实例。

**方案**：推荐每币种独立 State 实例（`state[symbol]`），保持 State 结构不变。

### 9.4 Reflector 子系统冲突规则扩展

**现状**：Reflector 主要处理预算、低置信度、提前终止。

**需求**：增加子系统间方向矛盾检测和仲裁逻辑（§6.2）。

### 9.5 Capability 子系统开关

**现状**：CapabilityDomain 支持注册/注销，但缺少子系统级别的运行时开关。

**需求**：支持运行时启停单个子系统 Node（如临时关闭自进化）。

**方案**：在 `extra` 中增加 `subsystem_switches` 配置，Node.validate 中检查。

---

## 10. 风险与约束

### 10.1 技术风险

| 风险 | 等级 | 缓解措施 |
|------|------|----------|
| Graph 并行执行引入竞态 | 中 | Wave 间有依赖屏障，Wave 内节点无数据依赖 |
| State 结构变更影响现有代码 | 中 | Phase 2 兼容层，渐进迁移 |
| Reflector 冲突决策误判 | 中 | 回测验证 + 灰度 + 配置开关可回退 |
| 子系统 Node 封装改变原有行为 | 低 | Phase 1 逐字段对比验证 |

### 10.2 非功能约束

- **FAIL-OPEN 铁律**：任何子系统异常 → Node fallback → 中性默认值，绝不阻塞交易
- **不修改 SACG 语义**：仅扩展 Reflector 规则和新增 Node，不改变 S/A/C/G 四层定义
- **不改交易代码**：Phase 1-2 不改 polling_trader 交易逻辑，Phase 3-4 通过配置开关灰度
- **HC-1a 合规**：不修改 `dreamos/` 内核代码的核心语义，仅通过扩展实现

### 10.3 决策点（待确认）

| # | 决策项 | 建议 |
|---|--------|------|
| Q1 | ConditionalGraph 并行执行用线程池还是 asyncio？ | 线程池（子系统调用多为 CPU/IO 混合，线程池更简单） |
| Q2 | BDSM strategic_mapper 的 war_state/cap 输出是否直接废弃？ | 是，统一由战略层产出，BDSM 只管单币约束 |
| Q3 | 自进化双实现（SelfEvolutionEngine + EvolutionPipeline）如何协调？ | EvolutionPipeline 负责交易层闭环，SelfEvolutionEngine 负责元层反思，由 SubsystemManager 协调 |
| Q4 | ConflictResolverNode 是否在 Phase 4 实现？ | 是，作为可选节点由 Reflector 动态插入 |

---

## 11. 验收标准

### Phase 1 验收
- [ ] 四个子系统 Node 全部实现真实调用（非模拟）
- [ ] 每个 Node 有 happy path + validate 失败 + fallback 降级三类测试
- [ ] Node 输出与 polling_trader 原调用逐字段一致

### Phase 2 验收
- [ ] polling_trader 可构建 State 并注入 market_data
- [ ] State.results 与 `_last_*` 属性内容一致
- [ ] 现有消费者未受影响（兼容层生效）

### Phase 3 验收
- [ ] polling_trader 推理阶段可通过配置开关切换为 Graph 执行
- [ ] Graph 并行执行结果与原串行结果一致
- [ ] 单轮总耗时 < 60s（BCRM2.0 满超时情况下 < 45s）

### Phase 4 验收
- [ ] Reflector 可检测并处理 §6.2 中所有冲突场景
- [ ] 冲突场景下决策不劣于原分散处理
- [ ] 回测中冲突场景占比 > 5% 时，整体胜率不下降

---

## 附录 A: 相关代码位置索引

| 组件 | 路径 |
|------|------|
| Node 接口 | `1-ARCHITECTURE/dreamos/shared/interfaces.py` L30-113 |
| BaseNode | `1-ARCHITECTURE/dreamos/registry/base.py` L73-136 |
| State / NodeResult | `1-ARCHITECTURE/dreamos/shared/state.py` L45-171 |
| GraphPlanner | `1-ARCHITECTURE/dreamos/core/arrange/graph_planner.py` |
| ConditionalGraph | `1-ARCHITECTURE/dreamos/core/arrange/execution_graph.py` L140-210 |
| GraphExecutor | `1-ARCHITECTURE/dreamos/core/compute/graph_executor.py` |
| NodeRunner | `1-ARCHITECTURE/dreamos/core/compute/node_runner.py` L50-130 |
| Reflector | `1-ARCHITECTURE/dreamos/core/compute/reflector.py` |
| ReflectAction 枚举 | `1-ARCHITECTURE/dreamos/core/compute/types.py` L23-72 |
| CapabilityRegistry | `1-ARCHITECTURE/dreamos/capability/registry.py` |
| 现有子系统模拟节点 | `1-ARCHITECTURE/dreamos/capabilities/trading/nodes/subsystem_adapter_nodes.py` |
| BCRM2Adapter | `11-易经推理系统/scripts/memory_l4/bcrm2_adapter.py` |
| FiveDomainHeuristicScorer | `11-易经推理系统/scripts/memory_l4/five_domain_scorer.py` |
| BDSM 快照 | `11-易经推理系统/scripts/memory_l4/force_vector/bdsm_snapshot_writer.py` |
| SubSystemBridge | `23-四层闭环自进化交易架构/dreambuddy_evolution/adapters/subsystem_bridge.py` |
| polling_trader | `11-易经推理系统/scripts/memory_l4/polling_trader.py` |

---

## 附录 B: 术语表

| 术语 | 含义 |
|------|------|
| SACG | DreamOS 四层架构：Sense / Arrange / Compute / GraphStore |
| Node | DreamOS 执行图的最小执行单元，实现 `execute(state)→NodeResult` |
| State | 执行图全局状态，所有节点读写同一份状态 |
| NodeResult | 节点执行结果，含 outputs/confidence/direction 等 |
| Graph | 执行图，定义节点和依赖边 |
| Reflector | 反射决策器，节点执行后决定 CONTINUE/REDO/JUMP 等 |
| FAIL-OPEN | 失败时降级为中性默认值，不阻塞主流程 |
