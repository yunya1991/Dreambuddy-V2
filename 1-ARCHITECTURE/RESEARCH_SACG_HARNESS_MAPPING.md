# SACG → Harness 扩展点详细映射设计

> **版本**: v0.1
> **状态**: 🔬 调研设计稿
> **创建日期**: 2026-09-14
> **定位**: 在全栈对齐调研基础上，对 SACG 四层逐一对接 Harness Cordis 扩展点的**工程级详细设计**
> **前置文档**:
> - [RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md](./RESEARCH_DREAMOS_HARNESS_FULL_ALIGNMENT.md) v0.2（全栈对齐 + 边界守护理论）
> - [前端设计/RESEARCH_DEEPSEEK_HARNESS.md](./前端设计/RESEARCH_DEEPSEEK_HARNESS.md) v0.1（Harness 机制）
> - [dream-harness-bridge/SPEC.md](./dream-harness-bridge/SPEC.md) v0.4（分层嵌入 Spec + 硬约束）

---

## ⚠️ 文档定位

本文件是**工程级映射设计稿**，不实施代码变更。目的：
1. 逐层（S/A/C/G）明确每个 DreamOS 组件对应哪个 Harness 扩展点
2. 给出精确的数据流、IPC 契约、状态边界
3. 提供伪代码和降级路径，为后续分阶段落地提供蓝图
4. 确保每条映射都遵守 HC-9/HC-10/HC-11 边界铁律

---

## 一、SACG → Harness 映射总览

| SACG 层 | DreamOS 组件 | Harness 扩展点 | 映射方式 | 已验证 |
|---------|------------|---------------|---------|--------|
| **S 层** | IntentEngine | `agent/pre-step` listener | pre-step 拦截做意图识别+风险评估 | ✅ Phase 0 (intent-gateway) |
| **A 层** | GraphPlanner | agent **preset composer** | 根据意图动态组合 tool 集合 | ❌ 待设计 |
| **C 层** | GraphExecutor + 节点 | `ctx.tools` + `tools/pre-execute`/`tools/post-execute` + `agent/*` events | 节点注册为 tool，反射注册为 event listener | ⚠️ 部分 (indicators/fundamental) |
| **C 层** | Reflector | `agent/*` events (step/end, turn-stopping) | 反射决策映射为 Harness 事件响应 | ❌ 待设计 |
| **G 层** | GraphStore | session log **consumer** (`session/event`) | 消费 append-only 事件流，做交易领域压缩投影 | ✅ Phase 1 (session-consumer) |

---

## 二、S 层 → `agent/pre-step` listener

### 2.1 DreamOS S 层接口

**入口**: `IntentEngine.recognize(user_message, market, signals, memory, knowledge_hits, context, symbol) -> IntentResult`

**IntentResult 关键字段**:
```python
{
  "intent_type": "TREND_FOLLOWING",       # 意图分类
  "confidence": 0.72,                      # 置信度 0~1
  "recommended_chain": "A",                # 推荐链路 A/C/F
  "base_chain": ["A0", "A1", "A2", "A3"],  # 基础节点链
  "extend_nodes": ["A6", "G1"],            # 扩展节点
  "rationale": "...",                      # 识别理由
  "clarify_needed": False,                 # 是否需要澄清
  "clarify_question": "...",               # 澄清问题
  "recognizers_used": ["rule_based"],      # 使用的识别器
  "total_tokens": 0,                       # 消耗 token
  "total_latency_ms": 12.5                 # 延迟
}
```

**执行策略**: 规则识别（零 Token）→ 置信度≥阈值直接返回 → 否则 Token 预算够则调 LLM → 融合结果 → 低置信度触发澄清

### 2.2 Harness 扩展点签名

```typescript
ctx.on("agent/pre-step", async (session, next) => {
  // session: { messages, step, agent, ... }
  // next(): 继续执行 step
  // 可 reject 或修改 messages
});
```

**生命周期位置**: `turn/start → assemble prompt → agent/pre-step → step/start`

### 2.3 映射设计

```
┌──────────────────────────────────────────────────────────────┐
│  Harness agent loop                                          │
│                                                              │
│  turn/start                                                  │
│    └─ agent/pre-step  ──────►  IntentGateway Plugin          │
│         │                        │                           │
│         │                        ├─ 提取 user_input          │
│         │                        ├─ IPC → Python intent_engine│
│         │                        │   (market/signals/memory) │
│         │                        ├─ 返回 IntentResult         │
│         │                        │                           │
│         │                        ├─ 高风险 → 日志+放行        │
│         │                        └─ 正常 → next()            │
│         │                                                    │
│    └─ step/start                                             │
└──────────────────────────────────────────────────────────────┘
```

**IPC 契约**（已在 Phase 0 验证）:
```typescript
// Request
{ method: "intent_gateway", params: { user_input, step, agent_id } }
// Response
{ ok: true, result: { intent, risk_level, advisory, confidence } }
```

### 2.4 增强设计（Phase 2+）

当前 Phase 0 只做风险评估。完整 S 层映射需：
1. **意图分类透传**: 将 `intent_type` + `recommended_chain` 写入 session 上下文，供 A 层 preset composer 使用
2. **澄清机制**: `clarify_needed=true` 时，通过 `agent.inject()` 注入澄清问题，或 `reject` 终止 step
3. **Token 预算联动**: `total_tokens` 反馈给 Harness 的预算管理

**伪代码**:
```typescript
ctx.on("agent/pre-step", async (session, next) => {
  const intent = await ipc.callMethod("intent_engine", { user_input, market });
  
  // 将意图写入 session 上下文，供 A 层使用
  session.dreamosIntent = intent;
  
  if (intent.clarify_needed) {
    // 注入澄清消息到下次请求
    ctx.agents.inject({ type: "text", text: intent.clarify_question });
    return; // 不继续 step，等待用户澄清
  }
  
  if (intent.risk_level === "high") {
    logger.warn(`[S层] 高风险意图: ${intent.advisory}`);
  }
  
  return await next();
});
```

### 2.5 降级路径

| 故障 | 降级行为 | 硬约束 |
|------|---------|--------|
| Python IPC 超时 | FAIL-OPEN：直接 `next()` 放行 | HC-7 |
| 意图识别异常 | 返回 `UNCERTAIN` 意图，走默认 A 链 | HC-2 |
| LLM 预算耗尽 | 只走规则识别，不调 LLM | S 层内部 TokenBudget |

---

## 三、A 层 → agent preset composer

### 3.1 DreamOS A 层接口

**入口**: `GraphPlanner.plan(state) -> ExecutionPlan` 或 `plan_from_intent(...)`

**ExecutionPlan 关键字段**:
```python
{
  "planned_chain": "A",                        # 执行链路
  "selected_nodes": [NodeMeta, ...],           # 选中节点列表
  "budget": { "A0": 800, "A1": 1200, ... },    # 各节点 Token 预算
  "chain_spec": ChainSpec,                     # 链路规格
  "rationale": "链路=A(执行环)，节点=6...",     # 编排理由
  "estimated_total_tokens": 6000,
  "estimated_total_latency_ms": 3500,
  "capability_id": "trading"
}
```

**NodeMeta**:
```python
{
  "node_id": "A1",
  "chain": "A",
  "is_required": True,
  "allocated_tokens": 1200,
  "estimated_latency_ms": 800,
  "tags": ["research", "llm"]
}
```

**编排逻辑**: 确定链路 → NodeSelector 选节点（base_chain + extend_nodes + 编排记忆表）→ BudgetAllocator 分配预算 → 构建 ExecutionGraph

### 3.2 Harness 扩展点：agent preset composer

Harness 通过 **agent preset** 决定一个 session 可用的能力集。preset 可动态组合不同的 tool/plugin 集合。

**关键机制**:
- `compose agent preset`: 给一个 session 不同能力集
- preset 中定义哪些 tools 对 model 可见
- preset 可在运行时切换

### 3.3 映射设计

A 层的核心职责是**根据意图决定用哪些节点（tools）**，这正好对应 Harness 的 preset composer。

```
┌──────────────────────────────────────────────────────────────┐
│  S 层输出 IntentResult                                        │
│    { intent_type, recommended_chain, base_chain, extend_nodes }│
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  A 层 GraphPlanner (作为 preset composer plugin)              │
│                                                              │
│  1. 读取 session.dreamosIntent (来自 S 层)                     │
│  2. IPC → Python graph_planner.plan_from_intent()             │
│  3. 返回 ExecutionPlan: selected_nodes + budget               │
│  4. 动态注册/注销对应节点的 tools                              │
│     - selected_nodes 中的节点 → ctx.tools 可见                 │
│     - 未选中节点 → ctx.tools 隐藏                              │
│  5. 将 budget 写入 session 上下文供 C 层使用                    │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Harness agent loop                                           │
│    - model 只看到 selected_nodes 对应的 tools                  │
│    - 按预算控制 tool 调用                                      │
└──────────────────────────────────────────────────────────────┘
```

**IPC 契约**:
```typescript
// Request
{
  method: "graph_planner",
  params: {
    intent_type, recommended_chain, base_chain, extend_nodes,
    confidence, budget_total, budget_mode, scenario_id
  }
}
// Response
{
  ok: true,
  result: {
    planned_chain, selected_nodes: [{ node_id, allocated_tokens, ... }],
    budget, rationale, estimated_total_tokens
  }
}
```

### 3.4 动态 Tool 可见性控制

A 层编排的核心价值在于**不是所有节点都暴露给 model**，而是根据意图选择性暴露。

**伪代码**:
```typescript
// A 层 plugin: graph-planner
async function composePreset(session) {
  const intent = session.dreamosIntent;
  if (!intent) return; // 无意图，保持默认 preset
  
  const plan = await ipc.callMethod("graph_planner", {
    intent_type: intent.intent_type,
    base_chain: intent.base_chain,
    extend_nodes: intent.extend_nodes,
    confidence: intent.confidence,
  });
  
  // 从全量节点注册表中筛选
  const allNodeTools = await getAllRegisteredNodeTools();
  const selectedIds = new Set(plan.selected_nodes.map(n => n.node_id));
  
  // 动态设置 tool 可见性
  for (const tool of allNodeTools) {
    tool.enabled = selectedIds.has(tool.id);
  }
  
  // 存储预算供 C 层使用
  session.dreamosPlan = plan;
}
```

### 3.5 降级路径

| 故障 | 降级行为 |
|------|---------|
| GraphPlanner IPC 失败 | 默认 preset：暴露 A 链全量节点（A0-A5） |
| 编排记忆表加载失败 | 只用 base_chain，不加 extend_nodes |
| 预算分配异常 | 均摊预算到所有选中节点 |

---

## 四、C 层 → `ctx.tools` + `tools/*` events + `agent/*` events

C 层是最复杂的，包含三部分：**节点执行**、**反射决策**、**检查点**。

### 4.1 节点执行 → `ctx.tools` + `tools/pre-execute` / `tools/post-execute`

#### DreamOS C 层节点接口

**BaseNode 模板方法**（registry/base.py）:
```python
class BaseNode:
    node_id: str
    chain: str  # A/C/F/G
    
    def validate(self, state) -> bool: ...          # 前置校验
    def execute_core(self, state, allocated_tokens) -> NodeResult: ...  # 核心执行
    def fallback(self, state, error) -> NodeResult: ...  # 降级兜底
```

**NodeResult**:
```python
{
  "node_id": "A1",
  "status": "success",  # success/failed/skipped/degraded
  "confidence": 0.85,
  "output": { ... },    # 节点输出
  "tokens_used": 950,
  "latency_ms": 720,
  "error": None
}
```

#### 映射设计

每个 DreamOS 节点注册为一个 Harness tool，通过 IPC 调用 Python 侧执行。

```
┌──────────────────────────────────────────────────────────────┐
│  Harness model 决定调用 tool "A1_research"                     │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  tools/pre-execute  (NodeRunner.validate)                     │
│    - 校验节点前置条件                                          │
│    - 校验 Token 预算是否充足                                    │
│    - 不通过 → 直接返回 degraded 结果，不执行                   │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  tool execute (NodeRunner.run → IPC → Python node.execute_core)│
│    - 调用 Python 节点的 execute_core                           │
│    - 传入 allocated_tokens (来自 A 层预算)                     │
│    - 返回 NodeResult                                           │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  tools/post-execute (NodeRunner.fallback + checkpoint)        │
│    - 执行失败 → fallback 兜底                                  │
│    - 自动保存检查点到 G 层                                     │
│    - 将结果写入 state                                          │
└──────────────────────────────────────────────────────────────┘
```

**Tool 注册伪代码**:
```typescript
// 为每个 DreamOS 节点注册一个 tool
ctx.tools.register({
  id: "A1_research",
  name: "A1_asset_research",
  description: "资产调研：收集多维度情报并综合分析",
  schema: { symbol: z.string() },
  execute: async (args) => {
    const plan = session.dreamosPlan;
    const allocated = plan?.budget?.["A1"] ?? 0;
    
    const result = await ipc.callMethod("execute_node", {
      node_id: "A1",
      args,
      allocated_tokens: allocated,
      state_snapshot: getStateSnapshot(), // 只读快照
    });
    
    if (!result.ok) {
      // FAIL-OPEN: 返回降级结果
      return { status: "degraded", output: neutral_default() };
    }
    return result.result;
  }
});
```

**已验证的节点映射**（Phase 1）:
- `C1_technical_scan` → `get_technical_indicators` tool (8092)
- `F1/F2 基本面` → `get_fundamental_analysis` tool (3456)

### 4.2 反射决策 → `agent/*` events

#### DreamOS Reflector 接口

**Reflector.decide() -> ReflectDecision**:
```python
{
  "action": "CONTINUE",  # CONTINUE / REDO / INSERT_BEFORE / JUMP_TO / EARLY_TERMINATE
  "reason": "...",
  "jump_to": "A5",           # JUMP_TO 时
  "insert_node_id": "A6",    # INSERT_BEFORE 时
  "confidence": 0.7
}
```

**5 种决策语义**:
| 决策 | 含义 | Harness 对应 |
|------|------|-------------|
| CONTINUE | 继续下一节点 | step 自然结束 |
| REDO | 重新执行当前节点 | 重新调用同一 tool |
| INSERT_BEFORE | 在当前节点前插入新节点 | 动态注册新 tool 并优先调用 |
| JUMP_TO | 跳转到指定节点 | 跳过后续 tools，直接调用目标 tool |
| EARLY_TERMINATE | 提前终止 | `agent/turn-stopping` 终止 turn |

#### 映射设计

反射决策通过监听 `agent/step/end` 事件，在每个 step 结束后触发。

```
┌──────────────────────────────────────────────────────────────┐
│  tool 执行完成 → step/end 事件                                 │
└──────────────────────┬───────────────────────────────────────┘
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  agent/step/end listener (Reflector)                          │
│                                                              │
│  1. 收集当前 step 的 tool 结果 + state                         │
│  2. IPC → Python reflector.decide()                           │
│  3. 根据决策执行对应动作:                                      │
│     - CONTINUE: 不做任何事，自然进入下一步                     │
│     - REDO: 重新调用同一 tool                                  │
│     - INSERT_BEFORE: 动态注册新 tool，注入到执行序列前          │
│     - JUMP_TO: 跳过后续 tools，直接调用目标 tool               │
│     - EARLY_TERMINATE: 触发 agent/turn-stopping               │
└──────────────────────────────────────────────────────────────┘
```

**伪代码**:
```typescript
ctx.on("agent/step/end", async (session) => {
  const lastResult = getLastToolResult(session);
  const decision = await ipc.callMethod("reflect", {
    node_id: lastResult.node_id,
    result: lastResult,
    state_snapshot: getStateSnapshot(),
    executed_count: session.executedNodes.length,
    budget_remaining: session.remainingBudget,
  });
  
  switch (decision.action) {
    case "CONTINUE":
      break; // 自然继续
    case "REDO":
      await reExecuteTool(lastResult.node_id);
      break;
    case "INSERT_BEFORE":
      await injectToolBefore(decision.insert_node_id, session);
      break;
    case "JUMP_TO":
      await jumpToTool(decision.jump_to, session);
      break;
    case "EARLY_TERMINATE":
      ctx.emit("agent/turn-stopping", { reason: decision.reason });
      break;
  }
});
```

**反射协议已在 Phase 1 验证**（reflection-protocol.ts）:
- `ReflectionDecision` 类型定义
- `buildReflectionRequest` / `parseReflectionResponse`
- 5 种决策的合法性校验

### 4.3 检查点 → G 层联动

C 层执行过程中自动保存检查点，通过 `tools/post-execute` 触发 IPC 调用 G 层。

```typescript
ctx.on("tools/post-execute", async (result) => {
  // 每个 tool 执行后保存检查点
  await ipc.callMethod("graph_checkpoint", {
    node_id: result.node_id,
    phase: "post_node",
    state_snapshot: getStateSnapshot(),
    tokens_used: result.tokens_used,
  });
});
```

### 4.4 降级路径

| 故障 | 降级行为 |
|------|---------|
| 节点执行 IPC 失败 | fallback 返回 neutral default，不阻塞 |
| Reflector IPC 失败 | 默认 CONTINUE，不中断执行 |
| 检查点保存失败 | 日志警告，不阻塞执行流 |
| INSERT_BEFORE 节点不存在 | 降级为 CONTINUE |
| JUMP_TO 目标节点不在图中 | 降级为 CONTINUE |

---

## 五、G 层 → session log consumer

### 5.1 DreamOS G 层接口

**GraphStore 核心方法**:
```python
store.checkpoint(state, node_id, metadata) -> cp_id    # 保存检查点
store.rollback(cp_id) -> State                           # 回滚
store.compress(state) -> CompressedState                 # 压缩上下文
store.record(state, report) -> HistoryEntry              # 记录历史
store.query_history(**kwargs) -> List[HistoryEntry]      # 查询历史
store.find_patterns() -> Dict                             # 模式识别
store.get_similar(state, limit) -> List[HistoryEntry]    # 相似历史
store.replay(cycle_id) -> HistoryEntry                   # 回放
```

**BAC 三层压缩**:
- **Chronicle**: 细粒度事件流（每个 tool 调用、每个决策）
- **Architecture**: 中间层（节点序列 + 关键结果）
- **Blueprint**: 摘要层（意图 + 最终决策 + 关键指标）

### 5.2 Harness 扩展点：session log consumer

Harness 的 session log 是 append-only 事件流，通过 `session/event` 广播。

**事件类型**:
- `session/start`, `session/end`
- `turn/start`, `turn/end`
- `step/start`, `step/end`
- `tool/call`, `tool/result`
- `agent/assistant-stream`
- 自定义事件

### 5.3 映射设计

G 层作为 session log 的**下游消费者**，将 Harness 的通用事件流投影为 DreamOS 的交易领域压缩结构。

```
┌──────────────────────────────────────────────────────────────┐
│  Harness session log (append-only JSONL)                      │
│    session/start → turn/start → step/start → tool/call →      │
│    tool/result → step/end → turn/end → session/end            │
└──────────────────────┬───────────────────────────────────────┘
                       │ session/event broadcast
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  session-consumer plugin (G 层投影)                            │
│                                                              │
│  1. 过滤：只保留交易领域事件                                   │
│     - tool/call (node_id 前缀 A/C/F/G)                        │
│     - tool/result                                             │
│     - agent/pre-step (intent)                                 │
│     - 自定义 dreamos/* 事件                                   │
│  2. 投影：转换为 DreamOS 事件格式                              │
│     - tool/call → node_execution                              │
│     - tool/result → node_result                               │
│     - agent/pre-step → intent_gate                            │
│     - turn/end → graph_complete                               │
│  3. 写入 g_layer_events.jsonl                                 │
└──────────────────────┬───────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────┐
│  Python G 层 GraphStore                                       │
│    - 消费 g_layer_events.jsonl                                │
│    - BAC 三层压缩                                             │
│    - 喂养 A7/A8 自进化                                        │
│    - 历史回放 / 模式识别 / 相似检索                            │
└──────────────────────────────────────────────────────────────┘
```

**已验证的事件投影**（Phase 1，session-consumer plugin）:
| Harness 事件 | DreamOS 投影 | 状态 |
|-------------|-------------|------|
| `tool/call` | `node_execution` | ✅ |
| `tool/result` | `node_result` | ✅ |
| `agent/pre-step` | `intent_gate` | ✅ |
| `turn/end` | `graph_node` | ✅ |

**事件过滤契约**（HC-11）:
```typescript
const TRADE_EVENT_TYPES = new Set([
  "tool/call", "tool/result",      // 节点执行
  "agent/pre-step",                 // 意图识别
  "turn/end",                       // 图完成
  "dreamos/*"                       // DreamOS 自定义事件
]);

function isTradeEvent(event) {
  // 只消费交易领域事件，过滤 file_edit/shell_command 等
  if (event.type?.startsWith("dreamos/")) return true;
  if (TRADE_EVENT_TYPES.has(event.type)) {
    // 进一步过滤：tool 必须是交易节点
    if (event.type.startsWith("tool/")) {
      return event.tool?.name?.match(/^[ACFG]\d/);
    }
    return true;
  }
  return false;
}
```

### 5.4 双向数据流

```
Harness session log ──(消费)──► G 层 GraphStore
                                      │
                                      │ BAC 压缩 + 模式识别
                                      ▼
                              A7/A8 自进化引擎
                                      │
                                      │ 进化后的节点权重/编排策略
                                      ▼
                              A 层 GraphPlanner (下一轮编排)
```

### 5.5 降级路径

| 故障 | 降级行为 |
|------|---------|
| session log 不可读 | G 层回退到快照式 JSON（现有 ckpt_*.json） |
| 事件投影失败 | 跳过该事件，继续消费后续事件 |
| 认知 DB 写入失败 | 写入本地 buffer，延迟重试 |

---

## 六、完整执行流时序

将 S/A/C/G 四层串联，完整的一次交易决策执行流：

```
Time ──────────────────────────────────────────────────────────────────►

[S 层] agent/pre-step listener
  │  IPC → intent_engine.recognize()
  │  返回 IntentResult { intent_type, base_chain, confidence }
  │  写入 session.dreamosIntent
  ▼
[A 层] preset composer
  │  IPC → graph_planner.plan_from_intent()
  │  返回 ExecutionPlan { selected_nodes, budget }
  │  动态设置 ctx.tools 可见性
  │  写入 session.dreamosPlan
  ▼
[C 层] tool 执行循环
  │  tools/pre-execute → validate + budget check
  │  tool execute → IPC → node.execute_core() → NodeResult
  │  tools/post-execute → fallback + checkpoint (G层)
  │  agent/step/end → IPC → reflector.decide() → ReflectionDecision
  │    ├─ CONTINUE → next tool
  │    ├─ REDO → re-execute
  │    ├─ INSERT_BEFORE → inject new tool
  │    ├─ JUMP_TO → skip to target
  │    └─ EARLY_TERMINATE → turn-stopping
  ▼
[G 层] session log consumer
  │  消费 tool/call, tool/result, step/end 事件
  │  投影为 node_execution, node_result, graph_complete
  │  BAC 三层压缩
  │  喂养 A7/A8 自进化
  ▼
[下一轮] A7/A8 输出进化后的编排策略 → A 层 GraphPlanner
```

---

## 七、Plugin 拆分与职责

| Plugin | 对应层 | 职责 | Harness 接入点 |
|--------|-------|------|---------------|
| `dreambuddy-intent-gateway` | S | 意图识别 + 风险评估 | `agent/pre-step` |
| `dreambuddy-graph-planner` | A | 图编排 + 动态 tool 可见性 | preset composer + `ctx.tools` |
| `dreambuddy-nodes-*` | C | 交易节点执行 | `ctx.tools` + `tools/pre-execute`/`post-execute` |
| `dreambuddy-reflector` | C | 反射决策 | `agent/step/end` + `agent/turn-stopping` |
| `dreambuddy-session-consumer` | G | 事件流投影 | `session/event` |

**已实现**: intent-gateway (Phase 0), indicators/fundamental nodes + session-consumer (Phase 1)
**待实现**: graph-planner, reflector, 更多节点 tools

---

## 八、状态边界对照表

| 数据 | 所有者 | Harness 是否可持有 | 说明 |
|------|--------|------------------|------|
| 仓位/订单/持仓 | DreamOS | ❌ 禁止 | HC-3，IPC 实时查询不缓存 |
| IntentResult | DreamOS | ✅ 只读投影 | S 层写入 session 上下文供 A 层用 |
| ExecutionPlan | DreamOS | ✅ 只读投影 | A 层写入 session 上下文供 C 层用 |
| NodeResult | DreamOS | ✅ 只读投影 | C 层 tool 返回值 |
| 检查点/历史 | DreamOS | ❌ 禁止 | G 层独占，Harness 只产生事件流 |
| Reward 信号 | DreamOS | ❌ 禁止 | HC-5，plugin 只透传原始 PnL |
| Token 预算 | 共享 (双写) | ✅ Harness 管总预算，DreamOS 管分配 | A 层分配，C 层消耗 |

---

## 九、开放问题

| 编号 | 问题 | 优先级 |
|------|------|--------|
| OQ-1 | A 层 preset composer 的动态 tool 可见性如何与 Harness preset 机制对齐——是切换 preset 还是动态 enable/disable tool？ | 高（A 层落地前） |
| OQ-2 | C 层 REDO 在 Harness 中如何实现——是重新调用同一 tool 还是需要特殊机制？ | 高（C 层反射落地前） |
| OQ-3 | G 层事件流消费的背压控制——Harness 事件频率高于 G 层处理能力时如何缓冲？ | 中 |
| OQ-4 | S 层澄清机制与 Harness turn 边界的交互——澄清时是终止 turn 还是注入消息？ | 中 |
| OQ-5 | 多 symbol 并发场景下 session/plan 的隔离——不同 symbol 的意图和计划如何在同一 session 中区分？ | 中 |

---

## 十、参考来源

- [intent_engine.py](../dreamos/core/sense/intent_engine.py) — S 层源码
- [graph_planner.py](../dreamos/core/arrange/graph_planner.py) — A 层源码
- [graph_executor.py](../dreamos/core/compute/graph_executor.py) — C 层源码
- [store.py](../dreamos/core/graph_store/store.py) — G 层源码
- [reflection-protocol.ts](../dream-harness-bridge/packages/bridge-core/src/reflection-protocol.ts) — 反射协议（已实现）
- [intent-gateway plugin](../dream-harness-bridge/packages/cordis-plugin-intent-gateway/lib/index.js) — S 层映射（已实现）
- [dream-harness-bridge/SPEC.md](./dream-harness-bridge/SPEC.md) v0.4 — 硬约束与架构 Spec
