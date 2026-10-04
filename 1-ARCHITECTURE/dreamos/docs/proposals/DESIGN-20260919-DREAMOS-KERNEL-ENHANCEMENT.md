# DESIGN-20260919: DreamOS 内核增强设计 — 四子系统统一编排支撑

- **文档ID**: DESIGN-20260919-DREAMOS-KERNEL-ENHANCEMENT
- **类型**: 内核增强设计（Kernel Enhancement Design）
- **创建时间**: 2026-09-19
- **状态**: 🔵 DRAFT（待评审，不落地）
- **维护者**: DreamOS Core Team
- **关联文档**: [SPEC-20260919-SUBSYSTEM-UNIFIED-ORCHESTRATION.md](./SPEC-20260919-SUBSYSTEM-UNIFIED-ORCHESTRATION.md)
- **代码基线**: `1-ARCHITECTURE/dreamos/` (v2.4.0 SACG)

---

## 0. 决策基线

本设计基于 SPEC-20260919 §10.3 的 4 个决策点，采用建议值作为默认：

| # | 决策项 | 采用值 |
|---|--------|--------|
| Q1 | 并行执行方式 | **线程池**（ThreadPoolExecutor，CPU/IO 混合场景更简单） |
| Q2 | BDSM strategic_mapper 的 war_state/cap 输出 | **废弃**（统一由战略层 FiveDomainHeuristicScorer 产出） |
| Q3 | 自进化双实现协调 | EvolutionPipeline = 交易层闭环；SelfEvolutionEngine = 元层反思；由 SubsystemManager 协调 |
| Q4 | ConflictResolverNode | Phase 4 实现，由 Reflector 动态 INSERT_BEFORE |

---

## 1. 增强项 E1: ConditionalGraph 并行执行支持

### 1.1 现状

`ConditionalGraph.get_next(current_id, state)` 每次返回**单个**下一节点 ID。`GraphExecutor.execute()` 按顺序逐节点执行。对于无依赖关系的节点（如 BCRM2.0 和 BDSM），当前只能串行。

**关键代码位置**：
- `core/arrange/execution_graph.py` L140-210: `ConditionalGraph.get_next()` 返回单个节点
- `core/compute/graph_executor.py` L100-167: `execute()` 循环 `get_next` 逐节点执行

### 1.2 设计目标

支持 Wave 级并行：同层无依赖节点并行执行，跨层有依赖节点串行等待。

### 1.3 改动方案

#### 1.3.1 ConditionalGraph 新增 `get_ready_nodes()` 方法

```python
# core/arrange/execution_graph.py — ConditionalGraph 新增方法

def get_ready_nodes(self, executed: Set[str], state: State) -> List[str]:
    """返回所有可执行但尚未执行的节点ID。
    
    可执行条件：
    1. 节点的所有前驱节点已 executed
    2. 节点的条件边评估为 True（或无条件边）
    3. 节点未被 executed
    """
    ready = []
    for node_id in self._nodes:
        if node_id in executed:
            continue
        preds = self._predecessors.get(node_id, set())
        if not preds.issubset(executed):
            continue
        # 检查条件边
        if self._check_conditional_edges(node_id, state):
            ready.append(node_id)
    return ready
```

**关键设计**：
- 需要维护 `_predecessors` 反向邻接表（现有 `ConditionalGraph` 仅存正向边）
- 条件边评估沿用现有 `condition: Callable[[State], bool]` 机制

#### 1.3.2 GraphExecutor 新增 `_execute_wave()` 方法

```python
# core/compute/graph_executor.py — 新增方法

def _execute_wave(self, ready_nodes: List[str], graph, state, budget):
    """并行执行同一 Wave 的多个节点。
    
    使用 ThreadPoolExecutor，Wave 内并行。
    任一节点异常由 NodeRunner fallback 处理，不阻塞其他节点。
    """
    if len(ready_nodes) == 1:
        # 单节点直接串行，避免线程池开销
        return self._execute_single(ready_nodes[0], state, budget)
    
    results = {}
    with ThreadPoolExecutor(max_workers=min(len(ready_nodes), 4)) as pool:
        futures = {
            pool.submit(self._execute_single, nid, state, budget): nid
            for nid in ready_nodes
        }
        for future in as_completed(futures, timeout=self._wave_timeout):
            nid = futures[future]
            try:
                results[nid] = future.result()
            except Exception as e:
                # FAIL-OPEN: 节点异常走 fallback
                results[nid] = self._node_fallback(nid, state, e)
    return results
```

**并行安全保证**：
- 各节点读 `state` 的不同区域（`state.market[symbol]` 各自独立）
- 各节点写 `state.results[node_id]` 各自独立（key 不冲突）
- `state.update()` 需加 `threading.Lock` 保护 `trace` 追加

#### 1.3.3 execute() 主循环改造

```python
# core/compute/graph_executor.py — execute() 改造

def execute(self, graph, state, budget=None):
    executed = set()
    while True:
        ready = graph.get_ready_nodes(executed, state)
        if not ready:
            break  # 所有节点完成
        
        # 并行执行当前 Wave
        wave_results = self._execute_wave(ready, graph, state, budget)
        
        for nid, result in wave_results.items():
            state.update(nid, result)
            executed.add(nid)
            
            # Reflector 决策（仅对 Wave 最后一个节点或特定节点触发）
            decision = self.reflector.decide(nid, result, state, graph, ...)
            if decision.action == ReflectAction.EARLY_TERMINATE:
                return state
            # INSERT_BEFORE / JUMP_TO 在下一 Wave 前处理
        
        if len(executed) >= self._max_nodes:
            break
    return state
```

#### 1.3.4 State.update() 线程安全

```python
# shared/state.py — update() 加锁

class State:
    def __init__(self, ...):
        self._lock = threading.Lock()
    
    def update(self, node_id: str, result: NodeResult):
        with self._lock:
            self.results[node_id] = result
            self.trace.append({...})
```

### 1.4 影响范围

| 文件 | 改动类型 | 说明 |
|------|----------|------|
| `core/arrange/execution_graph.py` | 新增 `get_ready_nodes()` + `_predecessors` 反向索引 | 不改现有 `get_next()` 语义 |
| `core/compute/graph_executor.py` | 新增 `_execute_wave()` + 改造 `execute()` 主循环 | 保留原串行逻辑作为 fallback |
| `shared/state.py` | `update()` 加锁 | 读写线程安全 |

### 1.5 兼容性

- `get_next()` 保留不变，现有 SequentialGraph 调用不受影响
- `execute()` 新增并行路径，但单节点时走原串行逻辑（零开销）
- 配置开关 `GRAPH_PARALLEL_ENABLED`（默认 True），可降级为串行

---

## 2. 增强项 E2: BaseNode 超时与降级标准化

### 2.1 现状

`NodeRunner.run()` (`core/compute/node_runner.py` L50-130) 已有超时和 fallback 调用，但超时配置在各 Node 的 `execute_core` 内部硬编码，无统一类属性。

### 2.2 设计目标

BaseNode 增加标准化超时配置，NodeRunner 统一应用，子系统 Node 可声明式指定。

### 2.3 改动方案

#### 2.3.1 BaseNode 新增类属性

```python
# registry/base.py — BaseNode 新增

class BaseNode(ABC):
    # 现有属性...
    node_id: str
    chain: str
    
    # 新增：超时配置（秒），子类可覆盖
    timeout_seconds: float = 60.0
    
    # 新增：最大重试次数
    max_retries: int = 1
    
    # 新增：是否启用并行（同 Wave 内可与其他节点并行）
    parallelizable: bool = True
```

#### 2.3.2 NodeRunner 超时统一应用

```python
# core/compute/node_runner.py — run() 改造

class NodeRunner:
    def run(self, node, state, budget) -> NodeResult:
        timeout = getattr(node, 'timeout_seconds', 60.0)
        max_retries = getattr(node, 'max_retries', 1)
        
        for attempt in range(max_retries + 1):
            try:
                # 用 ThreadPoolExecutor 实现超时（兼容 CPU-bound）
                with ThreadPoolExecutor(max_workers=1) as pool:
                    future = pool.submit(node.execute, state)
                    result = future.result(timeout=timeout)
                    
                if result and result.status != "error":
                    return result
                    
            except TimeoutError:
                logger.warning(f"Node {node.node_id} timeout ({timeout}s), attempt {attempt+1}")
                if attempt < max_retries:
                    continue
                # 超时走 fallback
                return node.fallback(state)
                
            except Exception as e:
                logger.error(f"Node {node.node_id} error: {e}", exc_info=True)
                if attempt < max_retries:
                    continue
                return node.fallback(state)
        
        return node.fallback(state)
```

#### 2.3.3 子系统 Node 超时声明

```python
# 子系统 Node 声明式指定超时
class BCRM20Node(BaseNode):
    timeout_seconds = 30.0  # BCRM2.0 推理
    max_retries = 0          # 不重试，快速降级

class BDSMNode(BaseNode):
    timeout_seconds = 5.0
    max_retries = 1

class StrategyLayerNode(BaseNode):
    timeout_seconds = 3.0
    max_retries = 0

class EvolutionNode(BaseNode):
    timeout_seconds = 10.0
    max_retries = 0
```

### 2.4 影响范围

| 文件 | 改动类型 |
|------|----------|
| `registry/base.py` | 新增 3 个类属性 |
| `core/compute/node_runner.py` | `run()` 统一应用 timeout + max_retries |

### 2.5 兼容性

- 现有 Node 未设置 `timeout_seconds` 时取默认 60s，行为不变
- `max_retries` 默认 1，与现有行为一致

---

## 3. 增强项 E3: State 币种级多实例

### 3.1 现状

`State` 是单次执行全局状态。polling_trader 每轮处理多个币种（Full/Coarse/Top1 MODE），每个币种需要独立的子系统推理结果。现有 State 无多币种隔离。

### 3.2 设计目标

每币种独立 State 实例，保持 State 结构不变，polling_trader 按币种循环执行 Graph。

### 3.3 设计方案：每币种独立 State 实例

```python
# polling_trader 侧（不改 DreamOS State 定义）

def run_once(self):
    # 1. 构建全局共享数据（市场数据、配置）
    shared_market = self._fetch_market_data(self.coins)
    shared_config = {"bdsm_coins": self.BDSM_COINS, ...}
    
    # 2. 按币种循环执行 Graph
    for symbol in self.coins:
        # 每币种独立 State
        state = State(
            market={symbol: shared_market[symbol]},
            extra={"symbol": symbol, **shared_config}
        )
        
        # 执行子系统 Graph
        state = self.graph_executor.execute(self._subsystem_graph, state)
        
        # 消费结果
        bcrm2_result = state.get_result("SUBSYS_BCRM2")
        bdsm_result = state.get_result("SUBSYS_BDSM")
        strategy_result = state.get_result("SUBSYS_STRATEGY")
        evolution_result = state.get_result("SUBSYS_EVOLUTION")
        
        # 执行开仓/持仓逻辑
        self._process_symbol(symbol, bcrm2_result, bdsm_result, 
                           strategy_result, evolution_result)
```

### 3.4 为什么不用 State 内嵌多币种结构

| 方案 | 优点 | 缺点 |
|------|------|------|
| **A: 每币种独立 State**（推荐） | State 结构不变，Graph 逻辑不变，并行安全 | polling_trader 需循环执行 Graph |
| B: State.results 支持 `{node: {symbol: NodeResult}}` | 一次执行所有币种 | State 结构变更，影响现有 Node/Reflector |

方案 A 更简单，不改 DreamOS 内核，只改 polling_trader 侧。Graph 执行次数 = 币种数，但每次执行很快（~3ms 调度 + 子系统计算）。

### 3.5 优化：跨币种结果缓存

BDSM 快照是按日生成的（所有币种共享），不需要每币种重新读取：
```python
# BDSMNode 内部缓存
class BDSMNode(BaseNode):
    _snapshot_cache = {}  # {symbol: (snapshot, timestamp)}
    CACHE_TTL = 300  # 5min
    
    def execute_core(self, state):
        symbol = state.extra["symbol"]
        cached = self._snapshot_cache.get(symbol)
        if cached and (time.time() - cached[1]) < self.CACHE_TTL:
            snapshot = cached[0]
        else:
            snapshot = load_today_snapshot(symbol)
            self._snapshot_cache[symbol] = (snapshot, time.time())
```

### 3.6 影响范围

| 文件 | 改动类型 |
|------|----------|
| `shared/state.py` | **不改**（State 定义保持不变） |
| polling_trader.py | 新增按币种循环执行 Graph 的逻辑（Phase 3 改动） |

---

## 4. 增强项 E4: Reflector 子系统冲突规则扩展

### 4.1 现状

`Reflector.decide()` (`core/compute/reflector.py` L74-160) 按以下顺序决策：预算 → 低置信度 → 矛盾 → 提前终止 → 正常继续。现有"矛盾"检测仅针对方向冲突（`CONFLICT_NODE_MAP`），不感知子系统语义。

### 4.2 设计目标

在 Reflector 中增加子系统间冲突检测规则，不修改 SACG 语义，仅扩展启发式规则。

### 4.3 冲突规则定义

```python
# core/compute/reflector.py — 新增子系统冲突检测

class SubsystemConflictRule:
    """子系统间冲突检测规则。在 Reflector.decide() 中调用。"""
    
    def check(self, current_node_id: str, result: NodeResult, 
              state: State) -> Optional[ReflectDecision]:
        
        if current_node_id == "SUBSYS_STRATEGY":
            return self._check_bcrm_vs_bdsm(state)
        if current_node_id == "SUBSYS_EVOLUTION":
            return self._check_evolution_result(result)
        return None
    
    def _check_bcrm_vs_bdsm(self, state: State) -> Optional[ReflectDecision]:
        """BCRM2.0 方向 vs BDSM 方向约束矛盾检测。"""
        bcrm2 = state.get_result("SUBSYS_BCRM2")
        bdsm = state.get_result("SUBSYS_BDSM")
        
        if not bcrm2 or not bdsm:
            return None  # 前序节点未执行，跳过
        
        bcrm2_dir = bcrm2.outputs.get("direction", "NEUTRAL")
        bdsm_constraint = bdsm.outputs.get("direction_constraint", "NEUTRAL")
        bdsm_quality = bdsm.outputs.get("data_quality", "insufficient")
        
        # BDSM 数据不足时不检测冲突（降级放行）
        if bdsm_quality != "sufficient":
            return None
        
        # 方向矛盾检测
        conflicts = {
            ("UP", "SHORT_ONLY"): "BCRM2看多 vs BDSM禁止做多",
            ("DOWN", "LONG_ONLY"): "BCRM2看空 vs BDSM禁止做空",
            ("UP", "LONG_BLOCKED"): "BCRM2看多 vs BDSM拦截做多",
        }
        
        conflict_desc = conflicts.get((bcrm2_dir, bdsm_constraint))
        if conflict_desc:
            # 插入冲突仲裁节点
            return ReflectDecision(
                action=ReflectAction.INSERT_BEFORE,
                insert_node_id="SUBSYS_CONFLICT_RESOLVER",
                rationale=conflict_desc
            )
        
        return None
    
    def _check_evolution_result(self, result: NodeResult) -> Optional[ReflectDecision]:
        """自进化结果合理性检测。"""
        weight = result.outputs.get("entry_weight_factor", 1.0)
        if weight <= 0:
            return ReflectDecision(
                action=ReflectAction.EARLY_TERMINATE,
                rationale="自进化入场权重=0，无开仓信号"
            )
        
        # 连续低置信度检测
        bcrm2_conf = result.confidence
        if bcrm2_conf < 0.3 and result.degraded:
            return ReflectDecision(
                action=ReflectAction.EARLY_TERMINATE,
                rationale="多子系统低置信度+降级，本轮不开仓"
            )
        
        return None
```

### 4.4 Reflector.decide() 集成

```python
# core/compute/reflector.py — decide() 扩展

def decide(self, current_node_id, result, state, graph, ...) -> ReflectDecision:
    # ... 现有逻辑（预算/低置信度/矛盾/提前终止）...
    
    # 新增：子系统冲突检测
    if self._subsystem_conflict_rule:
        decision = self._subsystem_conflict_rule.check(current_node_id, result, state)
        if decision:
            return decision
    
    # 默认继续
    return ReflectDecision(action=ReflectAction.CONTINUE)
```

### 4.5 ConflictResolverNode 设计

```python
# capabilities/trading/nodes/conflict_resolver_node.py — 新增

class ConflictResolverNode(BaseNode):
    """冲突仲裁节点，由 Reflector INSERT_BEFORE 动态插入。
    
    决策逻辑：
    1. BDSM 硬约束优先（data_quality=sufficient 时）
    2. 按置信度加权投票
    3. 输出 resolved_direction + resolved_confidence + rationale
    """
    node_id = "SUBSYS_CONFLICT_RESOLVER"
    chain = "SUBSYSTEM"
    timeout_seconds = 2.0
    max_retries = 0
    
    def execute_core(self, state: State) -> NodeResult:
        bcrm2 = state.get_result("SUBSYS_BCRM2")
        bdsm = state.get_result("SUBSYS_BDSM")
        strategy = state.get_result("SUBSYS_STRATEGY")
        
        # BDSM 硬约束优先
        bdsm_constraint = bdsm.outputs.get("direction_constraint", "NEUTRAL")
        bdsm_quality = bdsm.outputs.get("data_quality", "insufficient")
        
        if bdsm_quality == "sufficient":
            resolved = self._respect_bdsm_hard_constraint(
                bcrm2, bdsm, strategy
            )
        else:
            # 数据不足时按置信度加权投票
            resolved = self._weighted_vote(bcrm2, bdsm, strategy)
        
        return NodeResult(
            node_id=self.node_id,
            status="success",
            outputs=resolved,
            confidence=resolved["resolved_confidence"],
            direction=resolved["resolved_direction"],
        )
    
    def _respect_bdsm_hard_constraint(self, bcrm2, bdsm, strategy):
        """BDSM 硬约束优先策略。"""
        bdsm_dir = bdsm.outputs.get("direction_constraint")
        
        # 如果 BDSM 禁止某方向，BCRM2.0 同向 → 降级
        bcrm2_dir = bcrm2.outputs.get("direction", "NEUTRAL")
        
        if bdsm_dir == "LONG_ONLY" and bcrm2_dir == "DOWN":
            # BCRM2.0 看空但 BDSM 只允许做多 → 遵循 BDSM
            return {
                "resolved_direction": "UP",
                "resolved_confidence": bcrm2.confidence * 0.5,
                "resolution_rationale": "BDSM_LONG_ONLY硬约束，BCRM2.0看空降权50%"
            }
        if bdsm_dir == "SHORT_ONLY" and bcrm2_dir == "UP":
            return {
                "resolved_direction": "DOWN",
                "resolved_confidence": bcrm2.confidence * 0.5,
                "resolution_rationale": "BDSM_SHORT_ONLY硬约束，BCRM2.0看多降权50%"
            }
        if bdsm_dir == "LONG_BLOCKED" and bcrm2_dir == "UP":
            return {
                "resolved_direction": "NEUTRAL",
                "resolved_confidence": 0.0,
                "resolution_rationale": "BDSM_LONG_BLOCKED拦截做多，放弃本轮"
            }
        
        # 无冲突
        return {
            "resolved_direction": bcrm2_dir,
            "resolved_confidence": bcrm2.confidence,
            "resolution_rationale": "无方向冲突"
        }
    
    def _weighted_vote(self, bcrm2, bdsm, strategy):
        """置信度加权投票（BDSM 数据不足时）。"""
        # ... 加权逻辑 ...
        pass
```

### 4.6 影响范围

| 文件 | 改动类型 |
|------|----------|
| `core/compute/reflector.py` | 新增 `SubsystemConflictRule` + `decide()` 集成 |
| `core/compute/types.py` | 无改动（现有 ReflectAction 够用） |
| `capabilities/trading/nodes/conflict_resolver_node.py` | 新增文件 |

---

## 5. 增强项 E5: Capability 子系统运行时开关

### 5.1 现状

`CapabilityRegistry` (`capability/registry.py`) 支持能力域注册/注销，但缺少运行时启停单个 Node 的机制。polling_trader 中各子系统开关散落在多处配置（`enable_five_domain`、`enable_bdsm_direction_overlay` 等）。

### 5.2 设计目标

统一子系统级运行时开关，支持临时关闭某个子系统（如关闭自进化），其他子系统正常运行。

### 5.3 设计方案

#### 5.3.1 State.extra 中增加 subsystem_switches

```python
# polling_trader 构建 State 时注入开关
state = State(
    market={...},
    extra={
        "symbol": symbol,
        "subsystem_switches": {
            "SUBSYS_BCRM2": True,      # BCRM2.0 启用
            "SUBSYS_BDSM": True,       # BDSM 启用
            "SUBSYS_STRATEGY": False,  # 战略层关闭（enable_five_domain=False）
            "SUBSYS_EVOLUTION": True,  # 自进化启用
        },
        # 保留现有开关映射
        "enable_five_domain": False,
        "enable_bdsm_direction_overlay": True,
    }
)
```

#### 5.3.2 Node.validate() 中检查开关

```python
# registry/base.py — BaseNode.validate() 扩展

class BaseNode(ABC):
    def validate(self, state: State) -> Optional[str]:
        # 新增：检查子系统开关
        switches = state.extra.get("subsystem_switches", {})
        if self.node_id in switches and not switches[self.node_id]:
            return f"Subsystem {self.node_id} disabled by runtime switch"
        
        # 子类自定义校验
        return self._validate_core(state)
    
    def _validate_core(self, state: State) -> Optional[str]:
        """子类实现自定义校验。"""
        return None
```

#### 5.3.3 NodeRunner 处理 validate 失败

当 validate 返回非 None（开关关闭）时，NodeRunner 跳过该节点并返回降级 NodeResult：

```python
# core/compute/node_runner.py — run() 扩展

def run(self, node, state, budget) -> NodeResult:
    # validate 检查
    error = node.validate(state)
    if error:
        # 子系统关闭 → 返回降级结果（不走 fallback，直接中性默认）
        return NodeResult(
            node_id=node.node_id,
            status="disabled",
            outputs=node.fallback(state).outputs,  # 中性默认值
            confidence=0.0,
            direction="NEUTRAL",
            degraded=True,
            warnings=[f"Node disabled: {error}"]
        )
    
    # 正常执行...
```

#### 5.3.4 开关映射统一

| polling_trader 现有开关 | subsystem_switches 映射 |
|--------------------------|------------------------|
| `enable_five_domain=True` | `SUBSYS_STRATEGY: True` |
| `enable_five_domain=False` | `SUBSYS_STRATEGY: False` |
| `enable_bdsm_direction_overlay=True` | `SUBSYS_BDSM: True` |
| `enable_bdsm_independent_open=True` | `SUBSYS_BDSM: True` |
| `ENABLE_STRATEGY_INDEPENDENT_OPEN=1` | `SUBSYS_STRATEGY: True`（独立开仓链路） |

**注意**：开关关闭时节点仍返回降级 NodeResult（中性默认值），不阻塞依赖它的下游节点。下游节点通过 `result.status == "disabled"` 或 `result.degraded == True` 感知。

### 5.4 影响范围

| 文件 | 改动类型 |
|------|----------|
| `registry/base.py` | `validate()` 新增开关检查 + `_validate_core()` 抽象方法 |
| `core/compute/node_runner.py` | `run()` 处理 validate 失败的 disabled 状态 |
| polling_trader.py | 构建 State 时注入 `subsystem_switches`（Phase 2 改动） |

### 5.5 兼容性

- 现有开关（`enable_five_domain` 等）保留，通过映射表同步到 `subsystem_switches`
- `subsystem_switches` 未设置时，所有子系统默认启用（行为不变）

---

## 6. 实施优先级与依赖关系

```
E2 (BaseNode 超时)  ──────────► 独立，可最先做
E5 (Capability 开关) ─────────► 独立，可与 E2 并行
E3 (State 多实例) ────────────► 独立，不改内核
E1 (Graph 并行)   ───────────► 依赖 E2（超时机制保障并行安全）
E4 (Reflector 扩展) ─────────► 依赖 E1（冲突检测在并行执行后触发）
```

| 优先级 | 增强项 | 依赖 | 工作量 | 改动内核 |
|--------|--------|------|--------|----------|
| P0 | E2: BaseNode 超时标准化 | 无 | 小 | 是（base.py + node_runner.py） |
| P0 | E5: Capability 运行时开关 | 无 | 小 | 是（base.py + node_runner.py） |
| P1 | E3: State 币种级多实例 | 无 | 无 | 否（不改 State 定义） |
| P2 | E1: Graph 并行执行 | E2 | 中 | 是（execution_graph + graph_executor） |
| P3 | E4: Reflector 冲突规则 | E1 | 中 | 是（reflector.py + 新增 Node） |

---

## 7. 风险与约束

### 7.1 技术风险

| 风险 | 等级 | 缓解 |
|------|------|------|
| E1 线程池并行引入死锁 | 中 | State.update() 用 Lock，Wave 内节点无数据依赖 |
| E1 ThreadPoolExecutor 在 CPU-bound 场景无真并行 | 低 | GIL 限制，但子系统多为 IO-bound（API 调用/文件读取），线程池足够 |
| E2 超时导致频繁降级 | 低 | 超时值基于实测（BCRM2.0 30s 远大于实际推理时间） |
| E4 冲突规则误判 | 中 | 先 shadow_mode 验证，配置开关可回退 |
| E5 开关关闭后下游节点行为 | 低 | 降级 NodeResult 保证 FAIL-OPEN |

### 7.2 硬约束

- **不改 SACG 语义**：S/A/C/G 四层定义不变，仅扩展 Reflector 规则和新增 Node
- **FAIL-OPEN 铁律**：任何增强项异常 → 降级中性默认值，不阻塞交易
- **不破坏现有 Graph**：`get_next()` 保留，现有 SequentialGraph 调用不受影响
- **HC-1a 合规**：内核增强通过扩展实现，不修改核心语义

---

## 8. 验收标准

### E1 验收
- [ ] `get_ready_nodes()` 正确返回同层无依赖节点
- [ ] `_execute_wave()` 并行执行 BCRM2.0 + BDSM，结果与串行一致
- [ ] `state.update()` 线程安全（并发写入无数据丢失）
- [ ] `GRAPH_PARALLEL_ENABLED=False` 时走原串行逻辑

### E2 验收
- [ ] BaseNode 子类可声明 `timeout_seconds`
- [ ] NodeRunner 在超时后调用 fallback
- [ ] 未设置 `timeout_seconds` 的现有 Node 行为不变（默认 60s）

### E3 验收
- [ ] 每币种独立 State 实例执行结果正确
- [ ] BDSM 快照跨币种缓存生效（TTL 内不重复读取）

### E4 验收
- [ ] BCRM2.0 vs BDSM 方向矛盾被正确检测
- [ ] ConflictResolverNode 仲裁结果合理（BDSM 硬约束优先）
- [ ] 自进化 entry_weight=0 触发 EARLY_TERMINATE

### E5 验收
- [ ] `subsystem_switches` 关闭某子系统时，该 Node 返回 disabled 降级结果
- [ ] 下游节点正确感知 disabled 状态
- [ ] 现有开关映射表正确同步

---

## 附录: 改动文件清单

| 文件 | 增强项 | 改动类型 |
|------|--------|----------|
| `registry/base.py` | E2, E5 | 新增类属性 + validate 扩展 |
| `core/compute/node_runner.py` | E2, E5 | 超时统一 + disabled 处理 |
| `core/arrange/execution_graph.py` | E1 | 新增 `get_ready_nodes()` + `_predecessors` |
| `core/compute/graph_executor.py` | E1 | 新增 `_execute_wave()` + 改造 `execute()` |
| `shared/state.py` | E1 | `update()` 加锁 |
| `core/compute/reflector.py` | E4 | 新增 `SubsystemConflictRule` |
| `capabilities/trading/nodes/conflict_resolver_node.py` | E4 | 新增文件 |
| `config/` 或 `nodes.yaml` | E5 | 新增 `subsystem_switches` 配置项 |
