# L2 能力清单与调度链地图（只读盘点 v0.1）

> 盘点对象：`47-MCP管理系统/registry/mcp_capabilities.yaml`（registry_version 0.5，last_updated 2026-11-08）
> 调度面：34 / 3.1-FRONTEND / 30 / 45 / 48
> 方式：静态读取 + 行号定位，未运行任何服务；未修改任何既有文件。

---

## 1. 壳清单（47 registry，18 个）

### 1.1 概览

| # | shell_id | layer | capability_domain | exposure | status | transport | tools | shell_path |
|---|---|---|---|---|---|---|---|---|
| 1 | `l0.cognition.mcp` | L0 | cognition | control | available | ssh-stdio | 7 | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py` |
| 2 | `l0.semantic-39.mcp` | L0 | semantic-39 | control | available | stdio | 4 | `39-金融语义蒸馏系统/scripts/mcp_server.py` |
| 3 | `l0.rea.mcp` | L0 | rea | readonly-observe | available | stdio | 15 | `mcp_shells/l0_rea/server.py` |
| 4 | `l0.rea-client.mcp` | L0 | rea | readonly-observe | **deprecated** | http | 3 | 空（无 server 文件） |
| 5 | `l0.data.mcp` | L0 | data | control | available | stdio | 4 | `mcp_shells/l0_data/server.py` |
| 6 | `l0.eval.mcp` | L0 | eval | readonly-observe | available | stdio | 2 | `mcp_shells/l0_eval/server.py` |
| 7 | `l0.store-admin.mcp` | L0 | store-admin | control | available | stdio | 2 | `mcp_shells/l0_store_admin/server.py` |
| 8 | `l0.trade-exec.mcp` | L0 | trade-exec | control | available | stdio | 10 | `mcp_shells/l0_trade_exec/server.py` |
| 9 | `l1.trading.mcp` | L1 | trading | readonly-observe | available | stdio | 10 | `mcp_shells/l1_trading/server.py` |
| 10 | `l1.intent.mcp` | L1 | intent | readonly-observe | available | stdio | 3 | `mcp_shells/l1_intent/server.py` |
| 11 | `l1.strategy.mcp` | L1 | strategy | readonly-observe | available | stdio | 4 | `mcp_shells/l1_strategy/server.py` |
| 12 | `l1.ops.mcp` | L1 | ops | readonly-observe | available | stdio | 3 | `mcp_shells/l1_ops/server.py` |
| 13 | `agent.debate.mcp` | L2 | debate | control | **deprecated** | stdio | 3 | `mcp_shells/debate_adversarial/server.py` |
| 14 | `l2.debate.mcp` | L2 | debate | control | available | stdio | 3 | `mcp_shells/debate_adversarial/server.py` |
| 15 | `l2.dreamos.mcp` | L2 | dreamos | control | available | stdio | 5 | `mcp_shells/l2_dreamos/server.py` |
| 16 | `l2.train.mcp` | L2 | train | control | available | stdio | 3 | `mcp_shells/l2_train/server.py` |
| 17 | `l2.emergence.mcp` | L2 | emergence | readonly-observe | available | stdio | 3 | `mcp_shells/l2_emergence/server.py` |
| 18 | `l2.dsh.mcp` | L2 | dsh | readonly-observe | available | stdio | 3 | `mcp_shells/l2_dsh/server.py` |

### 1.2 逐工具明细（name / domain / read_write / requires_mandate）

| shell_id | tool | domain | read_write | requires_mandate |
|---|---|---|---|---|
| l0.cognition.mcp | recall | cognition | read | false |
| l0.cognition.mcp | unified_search | search | read | false |
| l0.cognition.mcp | record | cognition | write | true |
| l0.cognition.mcp | verify | cognition | write | true |
| l0.cognition.mcp | stats | cognition | read | false |
| l0.cognition.mcp | health | cognition | read | false |
| l0.cognition.mcp | l4_status | cognition | read | false |
| l0.semantic-39.mcp | query_entity | semantic | read | false |
| l0.semantic-39.mcp | semantic_lookup | semantic | read | false |
| l0.semantic-39.mcp | distill_aliases | semantic | write | true |
| l0.semantic-39.mcp | training_feed | semantic | write | true |
| l0.rea.mcp | submit_rea_analyze | rea | read | false |
| l0.rea.mcp | poll_rea_analyze | rea | read | false |
| l0.rea.mcp | submit_rea_trace | rea | read | false |
| l0.rea.mcp | poll_rea_trace | rea | read | false |
| l0.rea.mcp | submit_rea_compare | rea | read | false |
| l0.rea.mcp | poll_rea_compare | rea | read | false |
| l0.rea.mcp | get_rea_snapshot | rea | read | false |
| l0.rea.mcp | rea_audit | rea | read | false |
| l0.rea.mcp | get_rea_methodology | rea | read | false |
| l0.rea.mcp | cancel_rea_analyze | rea | read | false |
| l0.rea.mcp | cancel_rea_trace | rea | read | false |
| l0.rea.mcp | cancel_rea_compare | rea | read | false |
| l0.rea.mcp | submit_rea_adapt_plan | rea | read | false |
| l0.rea.mcp | poll_rea_adapt_plan | rea | read | false |
| l0.rea.mcp | cancel_rea_adapt_plan | rea | read | false |
| l0.rea-client.mcp | rea_analyze | rea | read | false |
| l0.rea-client.mcp | rea_trace | rea | read | false |
| l0.rea-client.mcp | rea_compare | rea | read | false |
| l0.data.mcp | data_fetch | data | read | false |
| l0.data.mcp | data_collect_once | data | read | false |
| l0.data.mcp | data_store_read | data | read | false |
| l0.data.mcp | data_store_write | data | write | true |
| l0.eval.mcp | eval_analyze | eval | read | false |
| l0.eval.mcp | eval_report | eval | read | false |
| l0.store-admin.mcp | store_admin_status | store-admin | read | false |
| l0.store-admin.mcp | store_admin_query | store-admin | read | false |
| l0.trade-exec.mcp | place_order | trade-exec | write | true |
| l0.trade-exec.mcp | cancel_order | trade-exec | write | true |
| l0.trade-exec.mcp | get_positions | trade-exec | read | false |
| l0.trade-exec.mcp | get_balance | trade-exec | read | false |
| l0.trade-exec.mcp | pre_trade_check | trade-exec | read | false |
| l0.trade-exec.mcp | check_exit | trade-exec | read | false |
| l0.trade-exec.mcp | get_account_mode | trade-exec | read | false |
| l0.trade-exec.mcp | reconcile | trade-exec | read | false |
| l0.trade-exec.mcp | read_signals | trade-exec | read | false |
| l0.trade-exec.mcp | ingest_signal | trade-exec | write | true |
| l1.trading.mcp | get_signal_state | trade-exec | read | false |
| l1.trading.mcp | get_bus_state | trade-exec | read | false |
| l1.trading.mcp | get_constraint_state | trade-exec | read | false |
| l1.trading.mcp | get_cycle_state | trade-exec | read | false |
| l1.trading.mcp | get_strategic_extension | trade-exec | read | false |
| l1.trading.mcp | get_decision_diagnostics | trade-exec | read | false |
| l1.trading.mcp | get_training_status | trade-exec | read | false |
| l1.trading.mcp | get_positions | trade-exec | read | false |
| l1.trading.mcp | get_balance | trade-exec | read | false |
| l1.trading.mcp | forward_signal | trade-exec | write | true |
| l1.intent.mcp | list_intents | semantic | read | false |
| l1.intent.mcp | classify_intent | semantic | read | false |
| l1.intent.mcp | execute_intent | trade-exec | read | false |
| l1.strategy.mcp | list_strategies | data | read | false |
| l1.strategy.mcp | get_strategy_version | data | read | false |
| l1.strategy.mcp | get_approval_state | data | read | false |
| l1.strategy.mcp | list_signal_triggers | data | read | false |
| l1.ops.mcp | list_alerts | data | read | false |
| l1.ops.mcp | get_health | data | read | false |
| l1.ops.mcp | get_bus_state | data | read | false |
| agent.debate.mcp | start_debate | eval | read | false |
| agent.debate.mcp | get_debate_result | eval | read | false |
| agent.debate.mcp | debate_health | eval | read | false |
| l2.debate.mcp | start_debate | eval | read | false |
| l2.debate.mcp | get_debate_result | eval | read | false |
| l2.debate.mcp | debate_health | eval | read | false |
| l2.dreamos.mcp | submit_run | cognition | write | true |
| l2.dreamos.mcp | poll_run | cognition | read | false |
| l2.dreamos.mcp | get_result | cognition | read | false |
| l2.dreamos.mcp | get_intent | cognition | read | false |
| l2.dreamos.mcp | get_budget | cognition | read | false |
| l2.train.mcp | trigger_training | eval | write | true |
| l2.train.mcp | get_training_status | eval | read | false |
| l2.train.mcp | list_runs | eval | read | false |
| l2.emergence.mcp | get_emergence_metrics | data | read | false |
| l2.emergence.mcp | list_experiments | data | read | false |
| l2.emergence.mcp | get_experiment_report | data | read | false |
| l2.dsh.mcp | get_router_summary | data | read | false |
| l2.dsh.mcp | get_ticket_status | data | read | false |
| l2.dsh.mcp | get_worker_roster | data | read | false |

### 1.3 统计

| 维度 | L0 | L1 | L2 | 合计 |
|---|---|---|---|---|
| 壳数 | 8 | 4 | 6 | **18** |
| 工具数 | 47 | 20 | 20 | **87** |
| 其中 write | 8 | 1 | 2 | **11** |
| 其中 requires_mandate=true | 8 | 1 | 2 | **11** |

其他计数：status `available` 16 / `deprecated` 2；exposure `control` 9 / `readonly-observe` 9；transport `stdio` 16 / `ssh-stdio` 1 / `http` 1。

数据质量备注：
- registry 自身 `max_total_tools: 80`（yaml:1223），**实际 87 超配额 7**。
- `l0.eval.mcp` 的 `capability_id` 被误写成 `l0.rea`（yaml:356），与 `l0.rea.mcp` 冲突。
- `l0.rea-client.mcp` 标 deprecated 但 `plugin_ready:false`、`shell_path:''`，无实现文件。

### 1.4 handler 覆盖核查（"有壳无 handler"迹象）

`mcp_shells/_shared/shell_runtime.py:250-252` 在启动时强校验：注册表工具若无 handler 直接抛 `ShellRuntimeError`。逐个核对结果：

| shell | handler 证据 | 结论 |
|---|---|---|
| l0.cognition.mcp | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py:204/229/299/357/366/975/996` | 7/7 有 |
| l0.semantic-39.mcp | `39-金融语义蒸馏系统/scripts/mcp_server.py:160/169/178/193`，dispatch `:288-298` | 4/4 有 |
| l0.rea.mcp | `mcp_shells/l0_rea/server.py:50-53`（submit 映射）、`:300/:344/:728/:739/:744` | 15/15 有 |
| **l0.rea-client.mcp** | 无 `mcp_shells/l0_rea_client`，`shell_path` 为空 | **3/3 无 handler（死壳）** |
| l0.data.mcp | `l0_data/server.py:360-363` | 4/4 有 |
| l0.eval.mcp | `l0_eval/server.py:125-126` | 2/2 有 |
| l0.store-admin.mcp | `l0_store_admin/server.py:167-168` | 2/2 有 |
| l0.trade-exec.mcp | `l0_trade_exec/server.py:1849-1858` | 10/10 有 |
| l1.trading.mcp | `l1_trading/server.py:591-600` | 10/10 有 |
| l1.intent.mcp | `l1_intent/server.py:259-261` | 3/3 有 |
| l1.strategy.mcp | `l1_strategy/server.py:251-254` | 4/4 有 |
| l1.ops.mcp | `l1_ops/server.py:243-245` | 3/3 有 |
| agent.debate.mcp / l2.debate.mcp | 同一 server，`debate_adversarial/server.py:715-717` | 3/3 有（两壳共用） |
| l2.dreamos.mcp | `l2_dreamos/server.py:490-494` | 5/5 有 |
| l2.train.mcp | `l2_train/server.py:302-304` | 3/3 有 |
| l2.emergence.mcp | `l2_emergence/server.py:276-278` | 3/3 有 |
| l2.dsh.mcp | `l2_dsh/server.py:319-321` | 3/3 有 |

另有 **未注册但已实现的壳**（registry 洞）：
- `mcp_shells/l1_stats/server.py`（4 工具 `stats_list/stats_run/stats_validate/stats_explain`，`:170/184/197/210`），被 `53-DSH插件模块/plugin_whitelist.yaml:109` 直引为 `l1.stats.mcp`，但 47 registry 无此条目。
- `mcp_shells/l0_gateway/server.py`（网关元壳），47 registry 无条目。

---

## 2. 调度面地图

### 2.1 前端任务入口（SSE）

| 位置 | 职责 |
|---|---|
| `3.1-FRONTEND/src/app/api/task/stream/route.ts:49` `POST` | SSE 主入口；`:85` 解构 `message/thinking_mode/l1_intent_hint/trace_id`；`:95-119` 澄清回复关联；`:122` 并发闸 `canCreateTask`；`:154` 调 `createAndExecuteTask`；`:380` `done` 事件携 `chain_trace`；`:399` L2 执行完成后 `settleL2ToCognitive`（`scripts/l2_cognitive_settle.py`，:26-27） |
| `3.1-FRONTEND/src/lib/task-manager.ts:3859` `createAndExecuteTask` | 任务落盘 + 执行装配；`:641 createTask`、`:804 listTasks`、`:3593 triggerWorkBuddyAsync` |
| `3.1-FRONTEND/src/lib/dsh-execution-engine.ts:352` `class DSHExecutionEngine` | 真正调度器：`:361 resolveModule`（skill_id→SubAgent module）、`:392 execute_skill`（节点优先→IPC，失败 LLM 兜底）、`:472 execute_plan`、`:516 getDSHExecutionEngine` 单例 |
| 同上 `:132 callDshHandler` | 与 Python 的唯一桥：`:143 callDshHttp`（云端）→ `:145 callDshSpawn`（本地 spawn bridge handler） |

关键结论：**前端执行引擎只按 handler 名调用 in-process 逻辑，不调用 47 registry 的 MCP 壳**。`dsh-execution-engine.ts:174` 注释明确"能力名必须与 dsh_frontend_bridge.HANDLER_TO_SHELL_ID 一致"。

### 2.2 34 Python 桥（in-process 壳面）

| 位置 | 职责 |
|---|---|
| `34-前端应用训练系统/core/dsh_frontend_bridge.py:41-134` `IN_PROCESS_HANDLERS` | 18 个 in-process shell：8 SubAgent（`:43-82`）、`c-drive`/`c-drive.debate`（`:84-85`）、`synthesizer`（`:87-91`）、`orchestrator`（`:93-97`）、`orchestrator.status`（`:99-103`）、`knowledge.search`（`:105-109`）、`skill.index`（`:111-115`）、`user.memory`（`:117-121`）、`data.dal_query`（`:123-127`）、`shell.stats`（`:129-133`），共 18 壳 / 30 工具标签 |
| `:246-269` `_load_inprocess_handler` | 按 `module`（python-server）或 `module=None`（本模块 globals）加载 handler |
| `:1441` `call_tool` | 完整链路：mandate_gate → shell 规格 → ShellHandleManager → `handle.call(shell_id,args)`；`:1545` 首调、`:1549-1554` 失败重拉一次 |
| `:1605-1624` `HANDLER_TO_SHELL_ID` | 旧 `dsh_adapter.py` 兼容映射（technical/c_drive/orchestrator/…共 18 键）；`:1626-1646` `HANDLER_TO_ROLE` |
| `:1649` `call_handler` | handler 名 → shell_id → `call_tool`，`:1670-1678` 抽取 `output/data` |

### 2.3 L1 路由门控（`l1_route_signal.py` 或同类）

**注意：不存在 `34-前端应用训练系统/core/l1_route_signal.py`。** 实际实现在 `3.1-FRONTEND/scripts/l1_route_signal.py`（由 `/api/data/query` 以 execFile 调起，见脚本 docstring `:4-11`）。

| 位置 | 职责 |
|---|---|
| `3.1-FRONTEND/scripts/l1_route_signal.py:952` `route_query` | 对外入口：`_route_query_impl` + L2 交接时附 `l1_suggest` 建议器与影子记录 |
| `:847` `_route_query_impl` | 意图 → recall → `evaluate_route` → L1 直答 / L2 交接 |
| `:875-883` | 确定性意图/产物型意图/metric_series 跳过 recall 门控直答 |
| `:888-903` | `get_l0().fetch_context("cognitive.recall")`（FAIL-OPEN → `cognitive_available=False`） |
| `:912-914` | 调用 `core.route_confidence.evaluate_route(...)` |
| `:927-928` | `decision != L1_DIRECT` → 原样回传 `route_signal`（L2_HANDOFF） |
| `:932-948` | L1 直答：`EXECUTORSintent` + `settle_to_cognitive` |
| `:169-179` `DETERMINISTIC_INTENTS` | 7 个关键词注册表意图，绕开门控 |

### 2.4 route_confidence 阈值与输出

`34-前端应用训练系统/core/route_confidence.py`

| 位置 | 内容 |
|---|---|
| `:44` `THRESHOLD_HIGH = 0.65` | L1 直答门限 |
| `:45` `CASE_DENSITY_MIN = 3` | 复用 `cognitive_router.TIER1_DENSITY_THRESHOLD` |
| `:46` `PREDICTION_ERROR_MAX = 0.3` | 复用 `jev_gate.PREDICTION_ERROR_THRESHOLD` |
| `:53-54` | 扣分系数 0.3 / 0.2 |
| `:60-61` | 决策常量 `L1_DIRECT` / `L2_HANDOFF` |
| `:116-141` `compute_route_confidence` | `match − 0.3(预测误差>0.3) − 0.2(密度<3)`，clamp [0,1] |
| `:149-230` `evaluate_route` | 认知不可用→静态置信度；recall 空→0→L2；C4 不可用→纯 C3 |
| `:223` | `decision = L1_DIRECT if route_confidence >= 0.65 else L2_HANDOFF` |
| `:233` `should_handle_l1` | 布尔便捷入口 |
| 输出 | `RouteConfidenceResult`（`:71-85`）：route_confidence / decision / match_score / case_density / prediction_error / fast_path / degraded / reasons |

### 2.5 SACG 四段编排

`34-前端应用训练系统/core/sacg_orchestrator.py`

| 段 | 函数 / 行号 | 实际调用 |
|---|---|---|
| 入口 | `:554 handle` | `:564 evaluate_route` 门控；L1_DIRECT 直接返回（`:567-585`） |
| S | `:606 self._s_planner(...)` → 默认 `SLayerPlanner.__call__` `:245-340` | 充分性状态机：`evaluate_entry_sufficiency`（`:255`）、`_expand`（`:305`）、`evaluate_plan_sufficiency`（`:309`）、`_top_experience`（`:332`）、`_rea_breakdown`（`:333`） |
| A | `:658 self._a_decomposer(plan)` → `:409 _default_a_decomposer` | `okr_nodes.decompose_okr_nodes(plan)` |
| C | `:675-677 self._run_node(node)` → `:525 _run_node` → `:537 self._router.run_v3(...)` | 节点级决策委托 `CDriveV3Router.run_v3` |
| A（回传） | `:706 evaluate_nodes(nodes, node_results)` | `okr_acceptance.evaluate_nodes` 对账 |
| G | `:714 self._g_closer(plan, node_results, acceptance)` → `:415 _default_g_closer` | 四分流 + 认知闭环 |

### 2.6 C-Drive v3 五步反思门

`34-前端应用训练系统/core/c_drive_v3_router.py:159 run_v3`

| Step | 行号 | 内容 |
|---|---|---|
| 灰度 | `:67-91 should_use_v3` | `CDRIVE_V3=true` 强制；否则 `CDRIVE_V3_GRAY_PERCENT`（默认 0） |
| Step 1 | `:189-217` | recall（hint 注入 `:191`）+ `41` 向量补充 `:207-214` + `evaluate_match` |
| Step 2 | `:219-274` | `route(match, density, multi_path)` → Tier1 CONTINUE / Tier2 `derive_decision_from_rea` / Tier3 `research_and_analyze` / Tier4 `debate_fn` |
| Step 3 | `:278-292` | `jev_gate` + `JevAntiOscillation.check_oscillation` |
| Step 4 | `:294-295` | 输出 `jev_final` 即最终 action |
| Step 5 | `:297-313` | `close_loop(decision=jev_final, outcome="executed", ...)` |
| 输出 | `:316-340` | `action/steps_executed/match_score/case_density/tier/jev_decision/effort_level` |

### 2.7 DSH Ticket 面对外可调用入口

| 文件 | 入口（函数 + 签名要点） |
|---|---|
| `34/core/ticket_router.py` | `:37 route_single_round(plan, workers, completed_refs=None) -> {assignments, unassigned, deferred}`；`:27 is_router_enabled(flags)`（默认 False） |
| `34/core/worker_pool.py` | `:77 dispatch_concurrent(plan, roster, active_tickets, completed_refs=None)`；`:61 free_roster(roster, tickets)`；`:42 occupied_workers(tickets)`；`:32 is_worker_pool_enabled` |
| `34/core/ticket_store.py` | `:82 save_ticket(ticket, store)`；`:98 recover_tickets(store)`；`:111 load_ticket`；`:121 list_tickets`；`:42 JsonlTicketStore`；`:32 is_ticket_store_enabled`；落盘 `34-前端应用训练系统/dsh_tickets.jsonl`（`:29`） |
| `34/core/router_loop.py` | `:170 run_pass(store, roster=None, affinity=None, triggers=None, plan=None, completed_refs=None, sink=None, flags=None, shadow=True, now=None, gate=None, stats=None)`；`:45 is_loop_enabled`（默认 False） |

开关默认全关：`enable_router_loop` / `enable_superagent_router` / `enable_ticket_store` / `enable_worker_pool`。

### 2.8 G 层四分流沉淀落点

`34/core/sacg_orchestrator.py:415-504 _default_g_closer`：

| 分流 | 条件 | 产物 |
|---|---|---|
| 案例 | `verdict==pass` 且有节点（`:443-446`） | `{"type":"case","mode":"async_stub","nodes":[...]}` |
| 流程 | `red_flags` 非空（`:448-452`） | `{"type":"skill","mode":"async_stub","red_flags":[...]}` |
| 文档 | 存在 `degraded` 节点（`:454-462`） | `{"type":"doc","mode":"async_stub","pending":[...]}` |
| 认知（必走） | `:469 close_loop(...)` → `cognitive_loop.close_loop` | outcome 映射 `:67`（pass→success/degraded→partial/fail→failure） |
| 本地台账 | `:486-501` | append 到 `34-前端应用训练系统/l1_case_store.jsonl` |

### 2.9 一句话调度链

前端 ChatPanel → `POST /api/task/stream` → `createAndExecuteTask`（task-manager）→ `DSHExecutionEngine.execute_skill` → `callDshHandler` → `dsh_frontend_bridge` `handler` 子命令 → `call_tool` → **InProcessShell**（8 SubAgent / C-Drive / Synthesizer / Orchestrator）。L1 旁路：`/api/data/query` → `l1_route_signal.route_query` → `route_confidence`（≥0.65 直答否则 L2_HANDOFF）。

---

## 3. 30-真实环境交互系统 场景盘点

### 3.1 `scenarios/examples/`（9 个，均有断言）

| 场景文件 | 名称 / 模式 | 输入 | 命中端点/能力 | 断言 |
|---|---|---|---|---|
| `frontend_smoke.yaml` | 前端冒烟（脚本模式） | 访问 `:3001`、点击仪表盘 | `/`、`/dashboard`、`/api/` | DOM exists ×3；network `request_exists /api/`；截图 |
| `e2e_market_query.yaml` | 端到端市场查询 | "分析比特币价格" | `:3001/chat`、**断言 `/api/chat`** | DOM count>1、`text_contains "BTC"`；`/api/chat` 200 |
| `ai_verification.yaml` | AI 反幻觉验证 | "比特币当前价格是多少？只返回数字" | `:3001/chat`、`market` API | `text_contains "0"`；`request_exists/status 200 url_pattern=market` |
| `quick_verify.yaml` | 浏览器连通性 | 访问 `example.com` | 外网 | DOM `text_equals "Example Domain"` |
| `ai_semantic_task.yaml` | AI 语义任务（`mode: ai`） | 自然语言：打开 example.com 报告 title/h1 | browser-use agent | DOM exists ×3；network `request_exists`；截图基线 |
| `agent_browser_form.yaml` | agent-browser 表单（`mode: agent_browser`） | 表单填写 | agent-browser CLI | DOM exists |
| `bsk_form.yaml` | bsk 表单含验证码（`mode: bsk`） | 表单 + 人工接管 | bsk | DOM exists |
| `computer_use_cross_app.yaml` | 跨应用三端（`mode: computer_use`） | Chrome→报告→Terminal | 桌面 UI | `file_exists/file_contains/terminal_contains/ui_visual_match` |
| `computer_use_cross_app_native.yaml` | 跨应用三端（`mode: desktop_native`） | 同上，纯 pyautogui/osascript | 桌面 UI | 同上四类 |

### 3.2 `scenarios/intent_training/` 与 `scenarios/trade_intent/`（各 120，均无断言）

- 结构：3 意图 × (train 30 + eval 10) = 120 YAML/目录；两目录文件同名但内容不同（`trade_intent` 打开 `/dashboard/trade` 且多一步 wait；`intent_training` 打开 `/chat`、等待 3s）。
- 元数据：`intent_training.gold_intent / scenario_id / split / market_features`。
- 输入示例：
  - `trend_following`：`BTC 现在是上升趋势吗，要不要顺势加仓`
  - `mean_reversion`：`BTC 震荡，高抛低吸怎么做`
  - `breakout`：`BTC 突破了吗，能追吗`
- 步骤仅 `navigate → type → click → wait`，**无 `verify`/`assertions`**；`selectors.md` 记录了 S 层徽章/链路的 DOM 选择器，但未落到 YAML 断言。
- 命中能力：仅前端页面与 `POST /api/task/stream`（经 UI 提交），不直接触达任何 MCP 壳。

### 3.3 执行入口

| 入口 | 用法 |
|---|---|
| `30-真实环境交互系统/cli.py:57 cmd_run` | `python cli.py run --scenario scenarios/examples/xxx.yaml --mode connect` |
| `cli.py:108 cmd_run_batch` | `python cli.py run-batch --scenarios scenarios/examples/ --mode launch` |
| `cli.py:162/177` | `check`（CDP 状态）、`launch`（独立 Chrome） |
| `cli.py:199/273/335/397/456` | `ai-run` / `agent-browser-run` / `bsk-run` / `computer-use-run` / `desktop-run` |
| `scripts/run_trade_intent_test.py:62 select_scenarios` | `python scripts/run_trade_intent_test.py --count 6`；`--scope all --count 30`；读 `scenarios/trade_intent`，经 `IntentSamplePipeline` 产出准确率/徽章通过率报告 |
| `scenarios` 意图钩子 | `core/scenario_runner.py:193` 当 `intent_training` 且注入 `_pipeline` 时采集；`:442 pipeline.ingest(sample)`；`run_from_file :209`、`run_batch :394` |
| 其它脚本 | `scripts/e2e_smoke.py`、`scripts/run_real_intent_test.py`、`scripts/gen_p1_scenarios.py`、`scripts/gen_trade_scenarios.py`、`scripts/verify_bayesian_trigger.py` |

---

## 4. 现有评测资产

### 4.1 45-评测系统（评的是"交付准入"，不是"能力覆盖"）

| 位置 | 职责 |
|---|---|
| `45-评测系统/api/server.py:1-11` | 生产入口：`EVAL_PG_DSN` fail-closed，uvicorn `api.server:app`（8790） |
| `45-评测系统/api/routes.py:98` | `POST /api/v1/submit`（受理即入队）；`:115 /metrics`、`:130 /{eval_id}`、`:150` 列表、`:195` 取消 |
| `45-评测系统/api/cli.py:1-46` | `evalctl gate/enforce/audit/evidence`；退出码 0 PASS / 2 BLOCK / 3 INCONCLUSIVE / 4 ERROR |
| `45-评测系统/core/runner.py:132` | `Runner`：入队→状态机→执行→重试；`:152` 默认 executor 为占位 `_finalize_empty`（生产由 `api/server.py` 注入 E3Executor） |
| `45-评测系统/evaluators/registry.py:18-24` | 注册 7 个内置评测器：`JudgeCalibration`、`Stress`、`E3Validator`、`EngineeringScan`、`EngineeringTests`、`Availability`、`BacktestStatistics` |

评的对象：三类评测器（AI judge/stress、金融回测统计/数据可用性、工程扫描/测试）+ E3 校验器 → 阈值门禁 → PASS/BLOCK/INCONCLUSIVE + 可签名证据包。**不含"场景→能力覆盖"类评测器**。

### 4.2 48-涌现架构（产物格式）

| 产物 | 格式 |
|---|---|
| `48-涌现架构/experiments/<exp>/results/*.json` | 单次 run：`run_id / run_class / n_train / n_test / system{...} / baselines{B0,B1,B3} / best_baseline / delta_* / bootstrap_ci{n,mean_delta,ci_low,ci_high} / decision{verdict,reason}`（样例 `d3a_intent/results/D3A-000020b26f36.json`） |
| `48-涌现架构/metrics/verdict_dashboard.json` | `{generated_at, metrics_ts, entries:[{experiment, run_id, verdict, metric, value/delta/ci_low/ci_high, evidence}]}` |
| verdict 词表（实测） | `candidate` / `e3_candidate` / `candidate_weak` / `falsified` / `inconclusive` / `insufficient_data`（X-A real 另有 `deferred`） |
| 实验目录 | `d2a_holdout`、`d2b_engineering`、`d3a_intent`、`d3b_intent_combo`、`e2_hypothesis`、`e3_coupling`、`e5_cbr_holdout`、`xa_transfer`、`replay` |
| 消费壳 | `l2.emergence.mcp` 读 `metrics/emergence_metrics.jsonl` + `runtime/trials.jsonl`（`mcp_shells/l2_emergence/server.py:33-34`） |

### 4.3 是否存在"能力覆盖矩阵"或"工具调用统计"

结论：**不存在能力覆盖矩阵，也不存在 per-tool 调用统计**。仅有以下三处近似物：

| 近似物 | 位置 | 粒度与局限 |
|---|---|---|
| Shell 句柄统计 | `34/core/shell_handles.py:193-194 stats()` → `{"shell_id":{"handles_issued":n}}`；经 `dsh_frontend_bridge.py:1291 _handle_shell_stats` 暴露为 `shell.stats` | 仅"拉起次数"，非工具调用次数；只覆盖进程内被拉起的壳 |
| AgentMail 影子轨迹 | `mcp_shells/_shared/agent_mail_shadow.py:40` → `.workbuddy/agent_mail/trajectories.jsonl`；`shadow_gate.py:8-13` 用于数据充分性（10 流/200 观测/180 天） | 用于 S0.5→S1_READY 放行，不是能力覆盖；默认关闭 |
| 30 意图样本 | `30/core/intent_sample_pipeline.py` + `training/eval_gate.py` | 只覆盖意图分类，不覆盖工具/壳 |

`56-L2架构能力聚合层/SPEC-56-L2架构能力聚合层.md` 中"覆盖"仅指回归测试覆盖与副作用回滚覆盖（`:166/:341/:352`），无覆盖矩阵定义。

---

## 5. 能力死角（证据清单）

| # | 死角 | 证据 |
|---|---|---|
| 1 | `l0.rea-client.mcp` 3 个工具完全无实现 | registry `:267-305`（`shell_path:''`、`transport:http`）；`mcp_shells/` 无 `l0_rea_client` 目录 |
| 2 | `l1.stats.mcp` 已实现但未注册 | `53-DSH插件模块/plugin_whitelist.yaml:109` 引用；`mcp_shells/l1_stats/server.py:170/184/197/210` 有 4 工具；47 registry 无条目 |
| 3 | `l0_gateway` 网关壳未注册 | `mcp_shells/l0_gateway/server.py` 存在；47 registry 无条目 |
| 4 | SACG 编排在产品链路中从未执行 | 全仓引用仅测试（`34/tests/test_sacg_orchestrator.py` 等）与压测脚本 `34/scripts/bench_l2_complete_stack.py:114-121`；`/api/task/stream`、`task-manager`、`dsh-execution-engine` 均无引用 |
| 5 | DSH Ticket 面 4 模块默认全关，产品不调度 | 开关默认 False：`ticket_router.py:24`、`worker_pool.py:26`、`ticket_store.py:26`、`router_loop.py:39`；生产引用仅 `1-ARCHITECTURE/.../superagent_p0.py` 与 `34/scripts/run_passive_training.py` |
| 6 | 18 个 MCP 壳无产品执行入口 | 前端只走 `HANDLER_TO_SHELL_ID`（`dsh_frontend_bridge.py:1605-1624`，18 个 in-process handler）；`/api/agent/plan/route.ts:48-80` 只把 `l0.*` 工具名拼进 LLM prompt（`:181`），不执行 |
| 7 | `l2.debate.mcp` 无生产调用方 | `c_drive_v3_router.py:261-274` 仅在注入 `debate_fn` 时使用；`dsh_frontend_bridge.py:85 c-drive.debate` 走 `handle_debate`，非该壳 |
| 8 | 240 个意图场景零断言，且不触达任何壳 | `scenarios/intent_training/*.yaml`、`scenarios/trade_intent/*.yaml` 均无 `verify`；仅 `navigate/type/click/wait` |
| 9 | `e2e_market_query.yaml` 断言已过期端点 | YAML `:49-53` 断言 `/api/chat`；实际入口为 `/api/task/stream`（`route.ts:49`） |
| 10 | registry 配额自相矛盾 | yaml `:1223 max_total_tools: 80` vs 实际 87 |

---

## 6. summary JSON

```json
{
  "snapshot": {
    "registry": "47-MCP管理系统/registry/mcp_capabilities.yaml",
    "registry_version": "0.5",
    "last_updated": "2026-11-08",
    "inventory_date": "2026-11-18",
    "mode": "read-only"
  },
  "counts": {
    "shells_total": 18,
    "tools_total": 87,
    "layers": {
      "L0": {"shells": 8, "tools": 47, "write_tools": 8},
      "L1": {"shells": 4, "tools": 20, "write_tools": 1},
      "L2": {"shells": 6, "tools": 20, "write_tools": 2}
    },
    "status": {"available": 16, "deprecated": 2},
    "exposure": {"control": 9, "readonly-observe": 9},
    "transport": {"stdio": 16, "ssh-stdio": 1, "http": 1},
    "write_tools_total": 11,
    "mandate_required_tools_total": 11,
    "shells_without_handler": 1,
    "unregistered_implemented_shells": 2,
    "in_process_shells": 18,
    "in_process_tool_labels": 30
  },
  "shells": [
    {"shell_id": "l0.cognition.mcp", "layer": "L0", "capability_domain": "cognition", "exposure": "control", "status": "available", "transport": "ssh-stdio", "tool_count": 7,
     "tools": [{"name": "recall", "read_write": "read", "requires_mandate": false}, {"name": "unified_search", "read_write": "read", "requires_mandate": false}, {"name": "record", "read_write": "write", "requires_mandate": true}, {"name": "verify", "read_write": "write", "requires_mandate": true}, {"name": "stats", "read_write": "read", "requires_mandate": false}, {"name": "health", "read_write": "read", "requires_mandate": false}, {"name": "l4_status", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l0.semantic-39.mcp", "layer": "L0", "capability_domain": "semantic-39", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 4,
     "tools": [{"name": "query_entity", "read_write": "read", "requires_mandate": false}, {"name": "semantic_lookup", "read_write": "read", "requires_mandate": false}, {"name": "distill_aliases", "read_write": "write", "requires_mandate": true}, {"name": "training_feed", "read_write": "write", "requires_mandate": true}],
     "handler_ok": true},
    {"shell_id": "l0.rea.mcp", "layer": "L0", "capability_domain": "rea", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 15,
     "tools": [{"name": "submit_rea_analyze", "read_write": "read", "requires_mandate": false}, {"name": "poll_rea_analyze", "read_write": "read", "requires_mandate": false}, {"name": "submit_rea_trace", "read_write": "read", "requires_mandate": false}, {"name": "poll_rea_trace", "read_write": "read", "requires_mandate": false}, {"name": "submit_rea_compare", "read_write": "read", "requires_mandate": false}, {"name": "poll_rea_compare", "read_write": "read", "requires_mandate": false}, {"name": "get_rea_snapshot", "read_write": "read", "requires_mandate": false}, {"name": "rea_audit", "read_write": "read", "requires_mandate": false}, {"name": "get_rea_methodology", "read_write": "read", "requires_mandate": false}, {"name": "cancel_rea_analyze", "read_write": "read", "requires_mandate": false}, {"name": "cancel_rea_trace", "read_write": "read", "requires_mandate": false}, {"name": "cancel_rea_compare", "read_write": "read", "requires_mandate": false}, {"name": "submit_rea_adapt_plan", "read_write": "read", "requires_mandate": false}, {"name": "poll_rea_adapt_plan", "read_write": "read", "requires_mandate": false}, {"name": "cancel_rea_adapt_plan", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l0.rea-client.mcp", "layer": "L0", "capability_domain": "rea", "exposure": "readonly-observe", "status": "deprecated", "transport": "http", "tool_count": 3,
     "tools": [{"name": "rea_analyze", "read_write": "read", "requires_mandate": false}, {"name": "rea_trace", "read_write": "read", "requires_mandate": false}, {"name": "rea_compare", "read_write": "read", "requires_mandate": false}],
     "handler_ok": false},
    {"shell_id": "l0.data.mcp", "layer": "L0", "capability_domain": "data", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 4,
     "tools": [{"name": "data_fetch", "read_write": "read", "requires_mandate": false}, {"name": "data_collect_once", "read_write": "read", "requires_mandate": false}, {"name": "data_store_read", "read_write": "read", "requires_mandate": false}, {"name": "data_store_write", "read_write": "write", "requires_mandate": true}],
     "handler_ok": true},
    {"shell_id": "l0.eval.mcp", "layer": "L0", "capability_domain": "eval", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 2,
     "tools": [{"name": "eval_analyze", "read_write": "read", "requires_mandate": false}, {"name": "eval_report", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l0.store-admin.mcp", "layer": "L0", "capability_domain": "store-admin", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 2,
     "tools": [{"name": "store_admin_status", "read_write": "read", "requires_mandate": false}, {"name": "store_admin_query", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l0.trade-exec.mcp", "layer": "L0", "capability_domain": "trade-exec", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 10,
     "tools": [{"name": "place_order", "read_write": "write", "requires_mandate": true}, {"name": "cancel_order", "read_write": "write", "requires_mandate": true}, {"name": "get_positions", "read_write": "read", "requires_mandate": false}, {"name": "get_balance", "read_write": "read", "requires_mandate": false}, {"name": "pre_trade_check", "read_write": "read", "requires_mandate": false}, {"name": "check_exit", "read_write": "read", "requires_mandate": false}, {"name": "get_account_mode", "read_write": "read", "requires_mandate": false}, {"name": "reconcile", "read_write": "read", "requires_mandate": false}, {"name": "read_signals", "read_write": "read", "requires_mandate": false}, {"name": "ingest_signal", "read_write": "write", "requires_mandate": true}],
     "handler_ok": true},
    {"shell_id": "l1.trading.mcp", "layer": "L1", "capability_domain": "trading", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 10,
     "tools": [{"name": "get_signal_state", "read_write": "read", "requires_mandate": false}, {"name": "get_bus_state", "read_write": "read", "requires_mandate": false}, {"name": "get_constraint_state", "read_write": "read", "requires_mandate": false}, {"name": "get_cycle_state", "read_write": "read", "requires_mandate": false}, {"name": "get_strategic_extension", "read_write": "read", "requires_mandate": false}, {"name": "get_decision_diagnostics", "read_write": "read", "requires_mandate": false}, {"name": "get_training_status", "read_write": "read", "requires_mandate": false}, {"name": "get_positions", "read_write": "read", "requires_mandate": false}, {"name": "get_balance", "read_write": "read", "requires_mandate": false}, {"name": "forward_signal", "read_write": "write", "requires_mandate": true}],
     "handler_ok": true},
    {"shell_id": "l1.intent.mcp", "layer": "L1", "capability_domain": "intent", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "list_intents", "read_write": "read", "requires_mandate": false}, {"name": "classify_intent", "read_write": "read", "requires_mandate": false}, {"name": "execute_intent", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l1.strategy.mcp", "layer": "L1", "capability_domain": "strategy", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 4,
     "tools": [{"name": "list_strategies", "read_write": "read", "requires_mandate": false}, {"name": "get_strategy_version", "read_write": "read", "requires_mandate": false}, {"name": "get_approval_state", "read_write": "read", "requires_mandate": false}, {"name": "list_signal_triggers", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l1.ops.mcp", "layer": "L1", "capability_domain": "ops", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "list_alerts", "read_write": "read", "requires_mandate": false}, {"name": "get_health", "read_write": "read", "requires_mandate": false}, {"name": "get_bus_state", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "agent.debate.mcp", "layer": "L2", "capability_domain": "debate", "exposure": "control", "status": "deprecated", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "start_debate", "read_write": "read", "requires_mandate": false}, {"name": "get_debate_result", "read_write": "read", "requires_mandate": false}, {"name": "debate_health", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l2.debate.mcp", "layer": "L2", "capability_domain": "debate", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "start_debate", "read_write": "read", "requires_mandate": false}, {"name": "get_debate_result", "read_write": "read", "requires_mandate": false}, {"name": "debate_health", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l2.dreamos.mcp", "layer": "L2", "capability_domain": "dreamos", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 5,
     "tools": [{"name": "submit_run", "read_write": "write", "requires_mandate": true}, {"name": "poll_run", "read_write": "read", "requires_mandate": false}, {"name": "get_result", "read_write": "read", "requires_mandate": false}, {"name": "get_intent", "read_write": "read", "requires_mandate": false}, {"name": "get_budget", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l2.train.mcp", "layer": "L2", "capability_domain": "train", "exposure": "control", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "trigger_training", "read_write": "write", "requires_mandate": true}, {"name": "get_training_status", "read_write": "read", "requires_mandate": false}, {"name": "list_runs", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l2.emergence.mcp", "layer": "L2", "capability_domain": "emergence", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "get_emergence_metrics", "read_write": "read", "requires_mandate": false}, {"name": "list_experiments", "read_write": "read", "requires_mandate": false}, {"name": "get_experiment_report", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true},
    {"shell_id": "l2.dsh.mcp", "layer": "L2", "capability_domain": "dsh", "exposure": "readonly-observe", "status": "available", "transport": "stdio", "tool_count": 3,
     "tools": [{"name": "get_router_summary", "read_write": "read", "requires_mandate": false}, {"name": "get_ticket_status", "read_write": "read", "requires_mandate": false}, {"name": "get_worker_roster", "read_write": "read", "requires_mandate": false}],
     "handler_ok": true}
  ],
  "dispatch_surfaces": [
    {"path": "3.1-FRONTEND/src/app/api/task/stream/route.ts", "line": 49, "role": "SSE 任务入口"},
    {"path": "3.1-FRONTEND/src/lib/task-manager.ts", "line": 3859, "role": "createAndExecuteTask"},
    {"path": "3.1-FRONTEND/src/lib/dsh-execution-engine.ts", "line": 392, "role": "DSHExecutionEngine.execute_skill"},
    {"path": "34-前端应用训练系统/core/dsh_frontend_bridge.py", "line": 41, "role": "IN_PROCESS_HANDLERS"},
    {"path": "34-前端应用训练系统/core/dsh_frontend_bridge.py", "line": 1441, "role": "call_tool"},
    {"path": "3.1-FRONTEND/scripts/l1_route_signal.py", "line": 912, "role": "evaluate_route 门控"},
    {"path": "34-前端应用训练系统/core/route_confidence.py", "line": 149, "role": "evaluate_route"},
    {"path": "34-前端应用训练系统/core/sacg_orchestrator.py", "line": 554, "role": "SACG handle"},
    {"path": "34-前端应用训练系统/core/c_drive_v3_router.py", "line": 159, "role": "run_v3 五步"},
    {"path": "34-前端应用训练系统/core/router_loop.py", "line": 170, "role": "run_pass"}
  ],
  "scenarios": {
    "examples": 9,
    "examples_with_assertions": 9,
    "intent_training": 120,
    "trade_intent": 120,
    "intent_scenarios_with_assertions": 0,
    "scenarios_touching_mcp_shells": 0
  },
  "eval_assets": {
    "module_45": {"entry": "api/server.py + api/cli.py", "evaluators": 7, "verdicts": ["PASS", "BLOCK", "INCONCLUSIVE"]},
    "module_48": {"experiments": ["d2a_holdout", "d2b_engineering", "d3a_intent", "d3b_intent_combo", "e2_hypothesis", "e3_coupling", "e5_cbr_holdout", "xa_transfer", "replay"], "verdict_dashboard": "metrics/verdict_dashboard.json"},
    "capability_coverage_matrix": false,
    "per_tool_call_stats": false
  },
  "dead_zones": [
    {"id": "D1", "target": "l0.rea-client.mcp", "tools": 3, "evidence": "registry shell_path 为空；无 mcp_shells/l0_rea_client"},
    {"id": "D2", "target": "l1.stats.mcp", "tools": 4, "evidence": "53/plugin_whitelist.yaml:109 引用；47 registry 未注册"},
    {"id": "D3", "target": "l0_gateway", "evidence": "mcp_shells/l0_gateway/server.py 存在；47 registry 未注册"},
    {"id": "D4", "target": "SACGOrchestrator", "evidence": "仅测试与 34/scripts/bench_l2_complete_stack.py:114-121 引用"},
    {"id": "D5", "target": "DSH ticket plane", "evidence": "四个开关默认 False；生产无入口"},
    {"id": "D6", "target": "18 MCP shells", "evidence": "前端仅调 in-process handler；/api/agent/plan 只生成计划不执行"},
    {"id": "D7", "target": "l2.debate.mcp", "evidence": "c_drive_v3_router.py:261-274 需注入 debate_fn，无生产注入"},
    {"id": "D8", "target": "240 intent scenarios", "evidence": "均无 verify/assertions"}
  ]
}
```
