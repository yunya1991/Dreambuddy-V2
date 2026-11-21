# 外部编排/调度设计对标：Dify / LangGraph / OpenAI Agents SDK

- **版本**: v0.1 ｜ **日期**: 2026-11-18 ｜ **范围**: 仅 3 个项目，不扩散
- **用途**: 逆向对照 DreamOS「总装与调度协调能力」（L0 数据/工具、L1 路由、L2 编排；SACG；DSH Router/Ticket/Worker；47 registry）
- **证据分级**:
  - ✅ **官方文档**：厂商文档站原文
  - 📄 **官方源码/配置**：GitHub 源码、`.env.example`、契约文件
  - ◐ **源码导读（第三方）**：DeepWiki 等对官方仓库的索引，结论指向具体类/文件路径
  - ⚠️ **未证实**：官方文档未见明确机制；仅作“文档层面不存在”表述，不推断内部实现

> 结论写法约束：每条尽量落到机制名 / 类名 / 配置项 / 事件名。凡属推测，标 ⚠️。

---

## 一、Dify

### 1.1 编排模型：画布式有向图（节点 + 边 + 类型化节点）

- ✅ Workflow 由 **节点（node）与边（edge）** 组成；节点按类型提供不同语义（Start / LLM / HTTP / Code / Tool / If-Else / Iteration / Loop / Agent / Human Input / End / Variable Aggregator 等），边表达执行顺序。
- ✅ **串行**：后节点可引用链路上任意前节点的变量；**并行**：并行分支之间不能互读变量，汇聚节点可读取所有分支输出。
- ✅ 单条执行路径最多 **50 个节点**；循环必须显式放进 `Iteration`（按列表逐项）或 `Loop`（按条件）节点，不能靠任意回边自造死循环。
- 📄 规模上限由环境变量兜底：`MAX_TREE_DEPTH=50`、`MAX_PARALLEL_LIMIT=10`、`MAX_ITERATIONS_NUM=99`（`docker/.env.example`，1.16.0 分支）。

**来源**：
- https://docs.dify.ai/en/cloud/use-dify/build/orchestrate-node
- https://docs.dify.ai/en/cloud/use-dify/nodes/start
- https://github.com/langgenius/dify/blob/1.16.0/docker/.env.example

### 1.2 调度与并发：HTTP 触发 → 队列 → GraphEngine → SSE 事件

- ◐ 调用链可定位到类：`POST /workflows/run` → `WorkflowRunApi` → `AppGenerateService` → `WorkflowAppService` → `GraphEngineManager`（`graphon/graph_engine/manager.py`）→ `AppQueueManager` 事件队列 → SSE 返回。
- ✅ 两种响应模式：`blocking`（等全量结果）与 `streaming`（SSE 持续推送节点级事件）。
- ✅ 并发/时长有全局闸：`APP_MAX_ACTIVE_REQUESTS`（0=不限制）、`APP_MAX_EXECUTION_TIME=1200s`、`WORKFLOW_GENERATION_TIMEOUT_MS=180000`、`MAX_PARALLEL_LIMIT=10`。
- ✅ 节点级重试：LLM / HTTP / Code / Tool 四类节点支持“异常重试”，可配尝试次数与间隔；**先重试，重试耗尽后再走异常处理策略**。
- ✅ 人工介入是“节点”而非旁路：`Human Input` 节点暂停工作流，支持 Web App / Email 投递、表单字段、动作按钮、默认 3 天超时分支。

**来源**：
- ◐ https://deepwiki.com/langgenius/dify/9.3-component-architecture-and-key-features（类名与事件流；索引自 `api/` 源码）
- ✅ https://legacy-docs.dify.ai/zh-hans/guides/workflow/error-handling
- ✅ https://docs.dify.ai/en/cloud/use-dify/nodes/human-input
- 📄 https://github.com/langgenius/dify/blob/1.16.0/docker/.env.example

### 1.3 工具治理：以“工具来源”为单位，而非以“单次写操作”为单位

- ✅ 工具入口：`Integrations > Tools`，四类来源 = Tool Plugin / Swagger(OpenAPI) / Workflow-as-Tool / MCP。
- ✅ MCP 仅支持 **HTTP transport**；以 `server identifier` 被应用引用（改 identifier 会导致旧应用工具失效）；认证支持 Dynamic Client Registration(OAuth) 或自定义 `Authorization` 头；可配请求超时与 SSE 读超时。
- ✅ Workflow 可作为工具被复用（要求以 User Input 起始；含 Human Input 节点时只能作为独立 Tool 节点使用）。
- ✅ Dify 自身应用也可发布为 **MCP Server**（需安装 mcp-server 插件并配置 App + App Input Schema）。
- ⚠️ **未证实**：文档未见“per-tool allowlist”或“写工具调用前强制审批”的字段；可验证的审批能力是流程级 `Human Input` 节点，而非工具调用级 gate。MCP 侧只有“导入服务器工具列表”，未见按工具粒度设白名单/审批策略的文档。

**来源**：
- ✅ https://docs.dify.ai/en/cloud/use-dify/workspace/tools
- ✅ https://docs.dify.ai/en/cloud/use-dify/nodes/human-input
- ✅ https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support

### 1.4 可观测与可回放：事件流 + WorkflowRun + 节点状态快照

- ✅ SSE 事件序列：`workflow_started` → `node_started` → `node_finished` → `workflow_finished`；暂停时发 `workflow_paused`，人工表单场景另发 `human_input_required`（携带 `form_token` 与 `workflow_run_id`）。
- ✅ 每次运行落 `WorkflowRun` 记录；日志查询支持状态过滤（`succeeded` / `failed` / `stopped`）、关键词、时间窗、创建者/终端用户。
- ✅ 分布式追踪：请求可带 `trace_session_id`，API 侧用 `get_external_trace_id` / `get_trace_session_id` 透传，便于把 API → workflow → node 级 span 串起来。
- ✅ **可回放**：暂停后可用 `workflow_run_id` 重新打开 `Stream Workflow Events`；`include_state_snapshot=true` 会先回放已执行节点的状态，再继续后续事件。
- ✅ 非二值状态：节点有 `成功 / 失败 / 异常`（异常=已被异常策略接住）；工作流有 `成功 / 失败 / 局部成功(Partial success)`。

**来源**：
- ◐ https://deepwiki.com/langgenius/dify/9.3-component-architecture-and-key-features
- ✅ https://docs.dify.ai/en/api-reference/guides/human-input-flow
- ✅ https://legacy-docs.dify.ai/zh-hans/guides/workflow/error-handling

### 1.5 失败恢复：前进式降级 + 人工暂停恢复，不是通用断点续跑

- ✅ 节点失败后的三条路：`无`（中断整个流程）/ `默认值`（用预设值替代异常输出）/ `异常分支`（走预编排备用路径）；重试优先于异常策略。
- ✅ 人工暂停可恢复：`human_input_required` → `GET /form/human_input/<form_token>` 取表单 → `Submit Human Input Form` 提交 → 沿对应 action 分支继续；提交后 `form_token` 失效。
- ⚠️ **未证实 / 文档未见**：进程崩溃或机器重启后的“从最近 checkpoint 续跑”没有文档化 API；异常分支是向前改道，不是回滚重放。可验证的“恢复”只覆盖 Human Input 暂停与事件流重连。

**来源**：
- ✅ https://legacy-docs.dify.ai/zh-hans/guides/workflow/error-handling
- ✅ https://docs.dify.ai/en/api-reference/guides/human-input-flow

### 1.6 与 SACG/DSH 的差异（可验证表述）

**他们有、我们没有：**
1. **节点级声明式异常分支/默认值**：Dify 每个 LLM/HTTP/Code/Tool 节点可独立配 `异常分支` 与 `默认值`，属于编排 DSL 的一部分；我们的 `router_loop.py` 八步里只有 FAIL-OPEN 返回 `{ok:False, degraded:True}`，未见节点级 fallback 分支声明。
2. **应用级并发/时长硬闸**：Dify 有 `APP_MAX_ACTIVE_REQUESTS` / `APP_MAX_EXECUTION_TIME` / `MAX_PARALLEL_LIMIT`；我们的 `worker_pool.dispatch_concurrent()` 只做“空闲花名册→不抢占”，未见全局并发配额与单次运行墙钟上限配置。
3. **Workflow-as-Tool / 发布为 MCP Server**：Dify 把同一条工作流复用到 Tool 节点或对外 MCP；我们的 47 registry 是静态 `mcp_capabilities.yaml` 注册，未见“把 SACG 链自动发布成 MCP 工具”的契约。

**我们有、他们没有：**
1. **默认拒绝的写工具门禁**：`core/mandate_gate.py` 的 `deny-by-default` + registry `requires_mandate`（`validate_mcp_registry.py` 强制 write 工具 `requires_mandate: true`），Dify 文档未见工具调用级同类硬闸（⚠️ 仅文档层面）。
2. **Ticket 四态与 Worker 槽位语义**：`core/ticket_state.py` 定义 `live / paused / waitsForPerson / ended`，`paused` 必带 `waiting_event|waiting_job|waiting_person`，且 paused/waitsForPerson 释放 `worker_id`；Dify 的暂停只是工作流级 `PAUSED`，未见“释放执行槽”的状态语义。
3. **A 阶段 OKR 验收**：SACG 的 A 是独立验收相位（`okr_acceptance`），Dify 没有“验收相位”，只有节点成功/失败/局部成功。

---

## 二、LangGraph

### 2.1 编排模型：StateGraph + 共享状态 reducer + Pregel 超步

- ✅ `StateGraph`：以共享 state schema（`TypedDict` / dataclass / `StateSchema`）为中心，节点是普通函数，返回“状态增量”；多节点写同一 key 时用 **reducer**（如 `Annotated[list, operator.add]`）合并。
- ✅ 控制流原语：`add_node` / `add_edge` / 条件边；`Send` 用于运行期才知道条目数的 **map-reduce / orchestrator-worker fan-out**；`Command` 用于“一次返回里同时更新状态 + 选下一节点”，也是 `interrupt()` 的恢复载体。
- ✅ 执行模型是 Google Pregel 风格 **super-step**：并行节点共享一个超步，串行节点分属不同超步；无待处理消息即结束。
- ✅ 子图（subgraph）可独立 state schema，并拥有自己的 checkpoint namespace；`compile(checkpointer=False)` 可关闭子图检查点。

**来源**：
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/use-graph-api

### 2.2 调度与并发：节点级策略对象，而非全局调度器

- ✅ 每个节点可挂 `RetryPolicy`：`retry_on` 可按异常类型定制（默认不重试 `ValueError/TypeError/RuntimeError/OSError` 等，对 `requests`/`httpx` 仅在 5xx 重试）、`max_attempts` 可配。
- ✅ 每个节点可挂 `timeout`（数字 / `timedelta` / `TimeoutPolicy(run_timeout, idle_timeout)`）；**只对 async 节点生效**，同步节点设置会在 compile 期失败；超时抛 `NodeTimeoutError`，且每次重试独立计时。
- ✅ 每个节点可挂 `error_handler(state, NodeError) -> Command`，在“重试耗尽”后执行补偿路径（如 `goto="finalize"`）；`set_node_defaults()` 可一次给全图设 `retry_policy` / `timeout` / `cache_policy` / `error_handler`，单节点配置覆盖默认。
- ✅ 并行由拓扑决定（同一超步内多节点并发），动态并发由 `Send` 决定；`recursion limit` 用于给循环封顶（文档在 “Build sequences, branches, and loops” 中列为终止手段）。
- ◐ LangGraph **Agent Server/平台**层另有 double-texting 策略：`enqueue`（排队）/ `reject`（拒绝）/ `interrupt`（保留进度插入新输入）/ `rollback`（回滚并删除原 run）。属于平台能力，不是 OSS 图库本身。

**来源**：
- https://docs.langchain.com/oss/python/langgraph/graph-api-nodes
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://docs.langchain.com/langsmith/double-texting

### 2.3 工具治理：库不提供权限系统，审批用 `interrupt()` 表达

- ✅ 工具注册就是普通可调用对象/`BaseTool`，图编排层没有内置 allowlist、角色、写操作审批字段。
- ✅ MCP 接入走 `MCPAdapter`（`langchain[mcp]>=1.4.0`，beta，底层 FastMCP）：支持 in-memory / stdio / Streamable HTTP / 多服务器 `MCPConfig`，认证见 FastMCP OAuth/Bearer。
- ✅ 人工审批通过 `interrupt()` 实现：节点内 `approved = interrupt("Do you approve this action?")`，恢复时 `Command(resume=True)` 成为 `interrupt()` 的返回值；文档给出 Approve/Reject、Review & Edit State、Interrupts in tools 等模式。
- ✅ 关键约束：`interrupt()` 不能包在 try/except 里、不能重排、payload 必须可 JSON 序列化、interrupt 前的副作用必须幂等。

**来源**：
- https://docs.langchain.com/oss/python/langchain/mcp
- https://docs.langchain.com/oss/python/langgraph/interrupts

### 2.4 可观测与可回放：LangSmith trace + 可枚举 checkpoint

- ✅ LangSmith 提供端到端 trace（输入→每一步→输出），LangGraph 应用可用一个环境变量开启追踪。
- ✅ 运行内可读 `runtime.execution_info`：`thread_id` / `run_id` / `checkpoint_id` / `checkpoint_ns` / `task_id` / `node_attempt` / `node_first_attempt_time`，可据此在重试时切换 fallback。
- ✅ 事件流 `graph.stream_events(..., version="v3")`：`stream.interrupts` 暴露中断 payload，`stream.interrupted` 表示暂停，`stream.output` 取最终状态。
- ✅ checkpoint 可枚举 → **time travel**：同一 `thread_id` 可回到历史 checkpoint 重放；修改图拓扑后旧 thread 仍可 resume（用“当前编译图 + 历史 state”）。

**来源**：
- https://docs.langchain.com/langsmith/observability-quickstart
- https://docs.langchain.com/oss/python/langgraph/graph-api-nodes
- https://docs.langchain.com/oss/python/langgraph/interrupts

### 2.5 失败恢复：超步边界 checkpoint + 三种持久化强度

- ✅ Checkpointer 在 **super-step 边界**落 checkpoint，不是函数中间；`thread_id` 是恢复指针，复用即续跑，新值即新线程。
- ✅ `durability` 三档：`"exit"`（仅退出/异常/中断时落盘，崩溃不可恢复）、`"async"`（下一步执行时异步落盘，崩溃有小窗口丢失）、`"sync"`（下一步前同步落盘，最稳但最慢）。
- ✅ 恢复语义：从最近 checkpoint 重放，**受影响节点函数从头重跑**；节点内多副作用应拆成 `@task` 或独立节点，已完成 task 的结果从 checkpoint 取回；必须幂等（幂等键/upsert/read-before-write）。
- ✅ 子图有独立 checkpoint namespace；父子图状态默认不互通，需通过 store 或显式写父 checkpoint 共享。

**来源**：
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/durable-execution
- https://docs.langchain.com/oss/python/langgraph/graph-api

### 2.6 与 SACG/DSH 的差异（可验证表述）

**他们有、我们没有：**
1. **节点级 `RetryPolicy` / `TimeoutPolicy` / `error_handler` 三件套**：LangGraph 把它们作为 `add_node()` 参数与 `set_node_defaults()` 默认值；我们的重试散落在 `worker_tool_call.py` 的 try-retry-degrade 与 `worker_receipts.py` 的 `failure_class=retryable|manual` 分类，没有“每个 C 节点声明重试/超时/补偿”的统一策略对象。
2. **超步级 checkpoint + time travel + durability 档位**：LangGraph 在超步边界自动落盘并可回放；我们的 `contracts/checkpoint.schema.json` 目前只定义 `state=paused` 的恢复点（P2，`resume_guard.max_age_s=604800`），不是每步自动 checkpoint，也无 time travel。
3. **`Send` 动态 fan-out**：运行期按条目数生成 N 个 worker 调用；我们的 `dispatch_concurrent()` 是“花名册槽位分派”，plan 必须是已展开的 `tickets` 列表，未见运行期由数据条目动态生成子任务的 API。

**我们有、他们没有：**
1. **能力注册表驱动的授权**：`47-MCP管理系统/registry/mcp_capabilities.yaml` 作为唯一载体，`mandate_gate.py` 只读引用；LangGraph 库本身无 registry/角色/`requires_mandate` 概念（需应用自建）。
2. **Ticket 暂停子因与槽位释放**：`paused_reason ∈ {waiting_event, waiting_job, waiting_person}` + `_RELEASE_WORKER_STATES`；LangGraph 的 `interrupt()` 只有“暂停/恢复”，不区分等待类型，也不管 worker 槽位。
3. **G 沉淀相位**：SACG 在 C 之后有独立 G（压缩沉淀/回写 L0）；LangGraph 图结束后是否沉淀完全由应用节点决定，框架无相位语义。

---

## 三、OpenAI Agents SDK

### 3.1 编排模型：Agent + Handoff-as-Tool，无图原语

- ✅ 基本单元是 `Agent`（`name` / `instructions` / `tools` / `handoffs`）；`Runner.run()` 驱动 **agent loop**：模型产出 → 若有 tool call 则执行并回灌 → 再跑，直到得到最终输出或触发 `max_turns`。
- ✅ **Handoff 被建模为工具**（默认工具名 `transfer_to_<agent_name>`）；`handoff(agent, tool_name_override, tool_description_override, on_handoff, input_type, input_filter, is_enabled, nest_handoff_history)`。
- ✅ `input_type` 用 Pydantic 定义 handoff 工具参数（模型在交接时生成 `reason/priority` 等元数据），SDK 本地校验后传给 `on_handoff`；`input_filter` 控制下一 Agent 能看到的历史（`HandoffInputData.input_history / pre_handoff_items / new_items / input_items`）。
- ✅ `Agent.as_tool(parameters=...)` 提供“不转移对话、只调用专家”的另一种组合方式。
- ⚠️ 结构性判断：SDK 文档目录无 graph/DAG/conditional-edge 原语；控制流只能由 Runner 循环 + handoff/agent-as-tool 组合表达。

**来源**：
- https://openai.github.io/openai-agents-python/handoffs/
- https://openai.github.io/openai-agents-python/running_agents/

### 3.2 调度与并发：Runner 循环 + max_turns + RunConfig 统一执行策略

- ✅ `max_turns` 是硬闸：超过抛 `MaxTurnsExceeded`；`max_turns=None` 可关闭。
- ✅ `RunConfig` 统一覆盖单次运行：`model` / `model_settings` / `session_settings` / `input_guardrails` / `output_guardrails` / `handoff_input_filter` / `tool_execution` 等。
- ✅ `RunConfig.tool_execution` 承载工具执行侧策略；官方在 Programmatic Tool Calling 一节明确：tool input/output guardrails、hooks、**timeouts、concurrency limits**、approvals、sessions、`RunState` pause/resume 在子调用中继续生效。
- ✅ Guardrail 可并行或阻塞：输入 guardrail 默认 `run_in_parallel=True`（与 Agent 同时跑，可能已花 token/已执行工具）；`run_in_parallel=False` 则先判定再启动 Agent。输出 guardrail 只在最终 Agent 上跑，无并行开关。
- ✅ MCP 客户端自带重试：`max_retry_attempts`、`retry_backoff_seconds_base`、`retry_backoff_seconds_max`；`client_session_timeout_seconds` 默认 5s（stdio/SSE/Streamable HTTP）。

**来源**：
- https://openai.github.io/openai-agents-python/running_agents/
- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/mcp/

### 3.3 工具治理：四类工具 + tool_filter + 审批/guardrail 双闸

- ✅ 工具面：Hosted tools（web/file search、code interpreter、hosted MCP、image gen）、Local runtime tools（Shell/ApplyPatch/Computer）、Function tools、Agents-as-tools。
- ✅ MCP 四种接入：Hosted MCP、Streamable HTTP、HTTP+SSE、stdio；`MCPServerStdio/SSE/StreamableHttp` 支持 `cache_tools_list`、`max_retry_attempts`、`tool_filter`（静态/动态子集）、`require_approval`、`failure_error_function`、`tool_meta_resolver`。
- ✅ 审批两层：`needs_approval=True|callable`（function/agent-as-tool/shell/apply_patch）与 MCP 的 `require_approval`；hosted MCP 用 `tool_config={"require_approval": "always"}` + `on_approval_request`。
- ✅ 审批失败语义是 **fail-closed**：参数缺失、空、空白、非法 JSON、非 object、含 `NaN/Infinity` → 不调用审批函数，直接转人工。
- ✅ Shell 工具有 `network_policy`：`disabled` / `allowlist`（allowlist 模式可配 `domain_secrets`）。
- ✅ Tool guardrails 包在 `FunctionTool` 执行管线上：输入前可 skip/replace/raise tripwire，输出后可 replace/raise；本地 MCP 可在 server 级挂 `tool_input_guardrails` / `tool_output_guardrails`。

**来源**：
- https://openai.github.io/openai-agents-python/tools/
- https://openai.github.io/openai-agents-python/mcp/
- https://openai.github.io/openai-agents-python/human_in_the_loop/

### 3.4 可观测与可回放：内建 trace/span 树 + processor 脱敏

- ✅ 默认追踪层级：`Runner.run*` → `trace()`；每次 runner 调用 → `task_span()`；每个模型轮次 → `turn_span()`；Agent 运行 → `agent_span()`；LLM 生成 → `generation_span()`；每个 function tool → `function_span()`；guardrail → `guardrail_span()`；handoff → `handoff_span()`。
- ✅ Trace 字段：`workflow_name`、`trace_id`（格式 `trace_<32_alphanumeric>`）、`group_id`（可放 chat thread ID，用于串联多 trace）、`metadata`、`disabled`。
- ✅ Span 字段：`started_at` / `ended_at` / `trace_id` / `parent_id` / `span_data`（按类型区分的 `AgentSpanData` / `GenerationSpanData` 等）。
- ✅ 可自定义 `TracingProcessor` 做导出前脱敏（`Redaction before export`）；可关闭自动 task/turn span 以压缩层级，agent/generation/function/guardrail/handoff span 仍保留。

**来源**：
- https://openai.github.io/openai-agents-python/tracing/

### 3.5 失败恢复：RunState 序列化 + interruptions 恢复

- ✅ 审批暂停：`RunResult.interruptions` 含 `ToolApprovalItem`（`agent.name` / `tool_name` / `arguments`）→ `result.to_state()` → `state.approve(...)` / `state.reject(...)` → `Runner.run(agent, state)` 续跑。
- ✅ `RunState` 可序列化：`state.to_string()` / `RunState.from_string()` / `state.to_json()` / `RunState.from_json()`；sticky 决策（`always_approve=True` / `always_reject=True`）随 `RunState` 持久化。
- ✅ 审批面是 **run-wide**：当前 Agent、handoff 后的 Agent、`Agent.as_tool()` 嵌套 Agent 的审批都冒泡到外层 run，由外层 `RunState` 统一批准；嵌套工具审批也在外层 run 的中断流里处理。
- ✅ 可按需逐条处理：一次只批准部分 interruption，已解决调用继续，未解决项让 run 再次暂停。
- ✅ Sessions 负责跨轮记忆：`SQLiteSession` / SQLAlchemy session；运行前取历史、运行后写新条目；`SessionSettings(limit=N)` 限制取回条数；暂停后用同一 session 恢复同一段历史。
- ⚠️ 恢复边界是 run/tool 级，不是任意 Python 函数中间；官方未提供“函数内断点”机制。

**来源**：
- https://openai.github.io/openai-agents-python/human_in_the_loop/
- https://openai.github.io/openai-agents-python/sessions/

### 3.6 与 SACG/DSH 的差异（可验证表述）

**他们有、我们没有：**
1. **带 schema 的 handoff 契约**：`input_type` + `on_handoff` + `input_filter` + `is_enabled` 让“交班”本身可校验、可裁剪历史、可运行时禁用；我们的 `ticket_router.route_single_round()` 只做 role→worker 分派，Ticket 记录里没有“交接 payload schema / 输入过滤”字段。
2. **声明式 guardrail + tripwire**：输入/输出/工具三层 guardrail，tripwire 触发即抛 `InputGuardrailTripwireTriggered` 等异常，且支持并行/阻塞两种执行模式；我们未见独立的“输入/输出/工具”三层声明式校验契约。
3. **`RunState` 可序列化 + sticky 审批**：暂停 run 可落字符串/JSON，审批决策随状态持久化并可跨进程恢复；我们的 `checkpoint.schema.json` 只存 `ticket_id` / `state=paused` / `content_hash` / git / artifacts，不含“待审批动作 + 已批准决策”的结构化字段（P2 才启用）。

**我们有、他们没有：**
1. **A 相位 OKR 验收**：SACG 把“验收标准”作为独立相位与门禁；OpenAI SDK 的 guardrail 是输入/输出校验，不是“对执行结果按 OKR 逐项验收”。
2. **47 registry 能力授权**：`mcp_capabilities.yaml` 的 `read_write` + `requires_mandate` 是注册期校验（`validate_mcp_registry.py` 强制写工具必须 `requires_mandate: true`）；SDK 的审批是调用期 `needs_approval`，没有注册期能力清单/角色映射。
3. **事件唤醒式暂停**：`ticket_state.py` 的 `paused_reason=waiting_event|waiting_job` + `router_loop` 的“事件唤醒”步，明确禁止忙轮询；OpenAI 的暂停只等服务端/人工恢复调用，无事件驱动唤醒语义。

---

## 四、6 维度 × 3 项目对照表

| 维度 | Dify | LangGraph | OpenAI Agents SDK |
|---|---|---|---|
| **1. 编排模型** | 画布有向图：typed nodes + edges；串行/并行/Iteration/Loop；单路径 ≤50 节点；`MAX_TREE_DEPTH=50` | `StateGraph`：共享 state + reducer；nodes/edges/conditional edges；`Send` 动态 fan-out；`Command` 更新+路由+恢复；subgraph；Pregel super-step | 无图原语：`Agent` + handoff-as-tool + `Agent.as_tool`；`Runner` agent loop |
| **2. 调度与并发** | HTTP→`AppGenerateService`→`GraphEngineManager`→`AppQueueManager`→SSE；并行分支 fan-out/fan-in；`APP_MAX_ACTIVE_REQUESTS` / `APP_MAX_EXECUTION_TIME` / `MAX_PARALLEL_LIMIT` / `MAX_ITERATIONS_NUM` | 并行节点同 super-step；`RetryPolicy` / `TimeoutPolicy` / `error_handler` / `set_node_defaults`；平台层 double-texting（enqueue/reject/interrupt/rollback） | `max_turns` + `MaxTurnsExceeded`；`RunConfig.tool_execution`（timeouts/concurrency/approvals）；guardrail 并行或阻塞；MCP `max_retry_attempts`/退避 |
| **3. 工具治理** | Tools：Plugin / Swagger / Workflow / MCP；MCP 仅 HTTP + OAuth(DCR)/自定义头；workspace 级授权；**无工具级 allowlist/审批字段（未证实）**，审批靠 Human Input 节点 | 库无内置权限层；工具=普通 callable；MCP 走 `MCPAdapter`（FastMCP）；审批靠 `interrupt()`；无 registry/角色概念 | function/hosted/local/MCP；`tool_filter` 静态/动态；`needs_approval` / `require_approval`（fail-closed）；tool guardrails；shell `network_policy=allowlist` |
| **4. 可观测与可回放** | SSE `workflow_started/node_started/node_finished/workflow_paused/workflow_finished`；`WorkflowRun` 日志（succeeded/failed/stopped）；`trace_session_id` 透传；`include_state_snapshot=true` 回放已执行节点 | LangSmith trace；`stream_events(v3)` 暴露 `interrupts`；`execution_info`（thread/run/checkpoint/node_attempt）；checkpoint 可枚举 → time travel | 内建 trace/span 树（task/turn/agent/generation/function/guardrail/handoff）；`trace_id`/`group_id`；`TracingProcessor` 导出前脱敏 |
| **5. 失败恢复** | 节点异常：重试 → `默认值` / `异常分支`；Human Input 暂停可 API 恢复（`form_token` + `workflow_run_id`）；**崩溃后续跑未见** | super-step 边界 checkpoint；`thread_id` 为恢复指针；`durability=exit/async/sync`；节点重跑需幂等；`@task` 缓存结果；子图 namespace | `RunState.to_string/to_json` + `interruptions` → approve/reject → resume；sticky 审批；Sessions 跨轮记忆；**无函数内断点** |
| **6. 与 SACG/DSH 差异（净增量）** | 他们有：节点级 fallback、并发/墙钟硬闸、Workflow-as-Tool / Publish-MCP；我们有：Mandate deny-by-default、Ticket 四态+槽位释放、A 验收 | 他们有：节点级策略对象、超步 checkpoint+time travel、`Send`；我们有：registry 授权、暂停子因+槽位、G 沉淀 | 他们有：typed handoff、guardrail tripwire、RunState sticky approval；我们有：OKR 验收、注册期能力授权、事件唤醒 |

---

## 五、对 DreamOS 的 5 条可执行启示

> 每条包含：动作 → 落点（文件/机制）→ 验收口径 → 依据来源。避免“应该学习”式表述。

### 启示 1：把 Ticket 恢复点升级为“超步级 checkpoint + 幂等重放”

- **动作**：以 C 阶段每个执行节点为 checkpoint 边界，在 `contracts/checkpoint.schema.json` 增加 `node_id` / `attempt` / `input_hash` / `output_hash` / `pending_tool_calls`；resume 时只重跑“未提交”节点，已完成节点从 checkpoint 取回结果；所有副作用工具要求幂等键。
- **落点**：`56-L2架构能力聚合层/contracts/checkpoint.schema.json`（现为 `state=paused` 单态）、`34-前端应用训练系统/core/router_loop.py` 的“快照”步、`ticket_state.py` 的 `paused` 迁移。
- **验收**：同一 `ticket_id` 在第 N 节点崩溃后恢复，产物 hash 与不崩溃运行一致；`resume_guard.content_hash` 不匹配时拒绝恢复。
- **依据**：
  - LangGraph 超步边界 checkpoint 与 `thread_id` 恢复：https://docs.langchain.com/oss/python/langgraph/persistence
  - 恢复重放 + 幂等要求：https://docs.langchain.com/oss/python/langgraph/durable-execution
  - 本地现状：`contracts/checkpoint.schema.json`（`state: const "paused"`、`resume_guard.max_age_s=604800`）

### 启示 2：给 DSH 节点加“重试/超时/补偿”三件套，收敛散落的重试逻辑

- **动作**：定义 `NodePolicy`（`retry_on` / `max_attempts` / `backoff_s` / `run_timeout_s` / `error_handler`），按角色或工具类型挂到 Ticket 分派记录；把 `worker_tool_call.py` 的 try-retry-degrade 与 `worker_receipts.py` 的 `failure_class=retryable|manual` 映射进同一策略；重试耗尽后走 `error_handler` 产出补偿 Ticket。
- **落点**：`34-前端应用训练系统/core/worker_pool.py`、`worker_tool_call.py`、`worker_receipts.py`；契约加到 `47-MCP管理系统/registry/mcp_capabilities.yaml` 的 shell/tool 条目。
- **验收**：同一 `failure_class=retryable` 的失败在 `max_attempts` 内自动重试，超限后 Ticket 进 `waitsForPerson`；配置缺省不影响现有 FAIL-OPEN 行为。
- **依据**：
  - LangGraph `RetryPolicy` / `timeout` / `error_handler` / `set_node_defaults`：https://docs.langchain.com/oss/python/langgraph/graph-api-nodes
  - 本地现状：`core/worker_receipts.py` 的 `retryable → paused + waiting_job`、`manual → waitsForPerson`

### 启示 3：把 Mandate 从“调用前门禁”扩展为“审批票据 + tool_set_hash 绑定”

- **动作**：写工具调用先生成 `approval_request`（含 `tool_name` / `arguments` / `tool_set_hash` / `mandate_id`），Ticket 进 `waitsForPerson`；审批通过后写入 `approval_ticket` 再放行；审批记录必须引用同一 `tool_set_hash`，避免“审批时工具面与执行时工具面不一致”。
- **落点**：`core/mandate_gate.py`（现为 deny-by-default + registry 只读引用）、`ticket_state.py`（`waitsForPerson`）、`checkpoint.schema.json`（补审批字段）。
- **验收**：未授权工具 100% 拒绝且留痕；审批后被替换工具列表的调用被拒；`requires_mandate: true` 的写工具在 Worker 侧永不直接持有。
- **依据**：
  - OpenAI `needs_approval` / `require_approval` / `RunState` sticky 审批：https://openai.github.io/openai-agents-python/human_in_the_loop/
  - Dify Human Input 表单 + action 分支：https://docs.dify.ai/en/cloud/use-dify/nodes/human-input
  - 本地现状：`core/mandate_gate.py` 头注释 ADR-4/ADR-9、`47-MCP管理系统/registry/scripts/validate_mcp_registry.py`（write 必须 `requires_mandate: true`）

### 启示 4：把 `trace_id` 贯穿升级为“span 树 + 按 run 回放”

- **动作**：定义 span 类型（`plan` / `accept` / `dispatch` / `tool_call` / `worker_receipt` / `settle`），每个 span 带 `trace_id` / `run_id` / `ticket_id` / `parent_id` / `started_at` / `ended_at` / `status`；对外提供“按 `run_id` 回放”接口，返回已执行节点状态快照后再续流。
- **落点**：`router_loop.py` 的“观测”步（第 8 步）、`worker_tool_call.py`、`ticket_state.history`；输出可落到 L0 事件表，供 3.1 前端与 48/54 消费。
- **验收**：任取一次运行，能从 `run_id` 还原 S→A→C→G 全链路 span；50 个会话样本 100% 可 join（对齐 SPEC-56 的“可归因”指标）。
- **依据**：
  - OpenAI 默认 span 层级与 `trace_id`/`group_id`：https://openai.github.io/openai-agents-python/tracing/
  - Dify SSE 节点事件 + `include_state_snapshot` 回放：https://docs.dify.ai/en/api-reference/guides/human-input-flow
  - 本地现状：`router_loop.py` 第 8 步“观测”、`ticket_state.py` 的 `trace_id` 字段

### 启示 5：增加“能力发布面”，把 SACG 链/Workflow 发布为 `l2.*.mcp` 工具

- **动作**：为可复用的 SACG 链路声明输入 schema 与 `read_write` 标注，发布为 MCP 工具（或 MCP Server），由 47 registry 统一登记 `requires_mandate` / `status`；调用方（3.1 前端、外部宿主）只依赖工具契约，不重复接内部 API。
- **落点**：`47-MCP管理系统/registry/mcp_capabilities.yaml`、`L2-P` 协议接入层；发布物与 `l2.<domain>.mcp` 命名对齐。
- **验收**：同一条链既能在前端内调用，也能作为 MCP 工具被外部调用；工具清单变更产生 diff，审批引用同一 `tool_set_hash`；写类工具默认 `requires_mandate: true`。
- **依据**：
  - Dify Workflow-as-Tool 与 Publish as MCP Server：https://docs.dify.ai/en/cloud/use-dify/workspace/tools
  - Dify 双向 MCP（v1.6.0）：https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support
  - 本地现状：`47-MCP管理系统/registry/validate`（`shell_id` 唯一、`read_write`、`requires_mandate` 校验）

---

## 六、未证实清单（明确标注，避免把“文档未见”当“实现不存在”）

1. **Dify 工具级 allowlist / 写操作审批字段**：官方 Tools 文档只描述工具来源、MCP 连接、认证与超时；未见 per-tool allowlist 或 `require_approval` 类字段。可验证的审批是 `Human Input` 节点（流程级）。
2. **Dify 崩溃后断点续跑**：官方文档只覆盖 Human Input 暂停/恢复与 `workflow_run_id` 重连；未见“进程崩溃后从 checkpoint 恢复”的 API。
3. **Dify 重试次数/间隔的官方数值**：官方旧文档给出“可配置尝试次数与间隔”，未给统一上限；镜像文档提到 10 次 / 5000ms，但未在 `docs.dify.ai` 官方域名复核，故不写入结论。
4. **LangGraph OSS 库的内置权限/审批系统**：文档只提供 `interrupt()` 模式与 `MCPAdapter`；未见内置 allowlist/角色模型。
5. **OpenAI SDK 的 per-tool 默认超时值**：仅确认 MCP `client_session_timeout_seconds` 默认 5s；普通 function tool 的默认超时未在文档中给出明确数值。
6. **DreamOS 侧“每节点自动 checkpoint”**：仓库现有 `checkpoint.schema.json` 明确只覆盖 `state=paused`（P2 启用），不能表述为已具备 LangGraph 式超步 checkpoint。

---

## 七、来源汇总（优先级：官方文档 > 官方仓库 > 第三方源码导读）

**Dify**
- https://docs.dify.ai/en/cloud/use-dify/build/orchestrate-node
- https://docs.dify.ai/en/cloud/use-dify/nodes/start
- https://docs.dify.ai/en/cloud/use-dify/nodes/human-input
- https://docs.dify.ai/en/cloud/use-dify/workspace/tools
- https://docs.dify.ai/en/api-reference/guides/human-input-flow
- https://legacy-docs.dify.ai/zh-hans/guides/workflow/error-handling
- https://dify.ai/blog/v1-6-0-built-in-two-way-mcp-support
- https://github.com/langgenius/dify/blob/1.16.0/docker/.env.example
- ◐ https://deepwiki.com/langgenius/dify/9.3-component-architecture-and-key-features

**LangGraph**
- https://docs.langchain.com/oss/python/langgraph/graph-api
- https://docs.langchain.com/oss/python/langgraph/use-graph-api
- https://docs.langchain.com/oss/python/langgraph/graph-api-nodes
- https://docs.langchain.com/oss/python/langgraph/persistence
- https://docs.langchain.com/oss/python/langgraph/durable-execution
- https://docs.langchain.com/oss/python/langgraph/interrupts
- https://docs.langchain.com/oss/python/langchain/mcp
- https://docs.langchain.com/langsmith/observability-quickstart
- https://docs.langchain.com/langsmith/double-texting

**OpenAI Agents SDK**
- https://openai.github.io/openai-agents-python/handoffs/
- https://openai.github.io/openai-agents-python/running_agents/
- https://openai.github.io/openai-agents-python/guardrails/
- https://openai.github.io/openai-agents-python/tools/
- https://openai.github.io/openai-agents-python/mcp/
- https://openai.github.io/openai-agents-python/human_in_the_loop/
- https://openai.github.io/openai-agents-python/sessions/
- https://openai.github.io/openai-agents-python/tracing/
