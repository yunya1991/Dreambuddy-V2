# 总装线对标：LobeHub / OpenAI / Claude × DreamOS 逐模块优化（v0.1）

> **日期**: 2026-11-16 ｜ **方法**: 三源官方文档/GitHub 调研（子代理并行）+ 本仓模块核对 + 前序 REA 报告
> **结论口径**: 我们缺的不是「更多能力」，而是把 L0/L1/L2 装成一条线的 **7 段契约**；DreamOS 已有 6 段零件，缺 3 个统一契约与 2 条反馈回路。
> **前序**: [REA-lobehub协议逆向解析-v0.1.md](./REA-lobehub协议逆向解析-v0.1.md)、[TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)

---

## §0 结论（先看五条）

1. **三家总装线的骨架高度收敛**：入口分流 → 规划/编排 → 工具解析 → 执行循环 → 验收/护栏 → 记忆/压缩 → 观测/调度。差异只在「契约粒度」，不在概念。
2. **DreamOS 的零件其实齐全**：`sense/`（分流）、`arrange/`（规划）、`capability/`（能力）、`compute/`（执行）、`graph_store/`（记忆）、`scheduler/`（调度）、`artifact/`（产物）七目录与七段一一对应。**缺的是段与段之间的机器可判定契约**。
3. **三个必须抄的硬契约**：
   - **停止原因唯一化**：LobeHub 7 值（含 `no_next_context`）、OpenAI `max_turns`、Claude `max_turns + max_budget_usd`；我们目前只有 Ticket 四态 + `stopWhen=5`，两套推导必然漂移。
   - **工具集单副本 + 受众可见性**：LobeHub `operationToolSet` 单份、`model/app` 受众；OpenAI approvals；Claude 权限判定顺序 `hooks → deny → mode → allow → canUseTool`。
   - **两级预算**：软收尾（剥工具、出总结）与硬停（返回 `max_steps/cost_limit`）分开，我们只有单一预算。
4. **L0/L1 目前没有进总装线**：L0 只在被调用时给事实，L1 的发现不驱动 L2 任务队列；导致 L2 的「优化」仍是凭感觉。正确形态是 **L1 发现 → 任务入队 → L2 修复 → 45 验收 → 回写 L0**。
5. **落地顺序**：先冻契约（不改行为）→ 再改单模块（执行循环/工具面/压缩）→ 最后接两条反馈回路（L1→L2 任务、L2→L0 台账）。

---

## §1 三源事实矩阵（官方文档，2026-11-16）

### 1.1 执行循环与终止

| 组件 | LobeHub | OpenAI Agents SDK | Claude Agent SDK |
|---|---|---|---|
| 循环形态 | loop 只决定「何时停、下一步喂什么」，每步 host 持久化 | `Runner`：模型→final/handoff/tool→回填→再跑 | `query()` 单次调用内自主多轮 |
| 终止枚举 | `done/error/interrupted/parked/cost_limit/max_steps/no_next_context` | 最终输出 / `MaxTurnsExceeded` | `max_turns` + `max_budget_usd` |
| 软/硬停 | `maxSteps` 软收尾 `forceFinish`（剥工具+总结） vs loop 硬停 | `max_turns` 硬停；`None` 关闭 | 预算/轮次双上限 |
| 暂停 | `parked` 三态：`waiting_for_human/async_tool/client`，恢复是独立入口 | `RunState` 暂停/恢复 | `resume(id)` / `fork` |

### 1.2 编排与控制权

| 组件 | LobeHub | OpenAI | Claude |
|---|---|---|---|
| 编排 | Supervisor 决策 `speak/broadcast/delegate/execute_task(s)/finish` | LLM 编排 + 代码编排；**handoff**（交控制权） vs **agents-as-tools**（保留控制权） | 5 种 workflow：chaining / routing / parallelization / orchestrator-workers / evaluator-optimizer |
| 子 agent | `groupOrchestration` + heterogeneous adapters | `Agent.as_tool()` 主管汇总；handoff 切换活跃指令 | `AgentDefinition` 新上下文、工具白名单、**子 agent 不可再派子 agent** |

### 1.3 工具、权限、可见性

| 组件 | LobeHub | OpenAI | Claude |
|---|---|---|---|
| 工具集 | `operationToolSet` 唯一副本（enabled/manifest/source/executor） | function + hosted（WebSearch/FileSearch/CodeInterpreter/MCP/ToolSearch） | 内置 Read/Write/Edit/Bash/Glob/Grep/Web/AskUserQuestion + MCP |
| 审批 | `request_human_approve` 持久化 pending + `deferredHumanApproval` | `require_approval=always/never` + `on_approval_request` | `canUseTool`，循环内处理不终止 |
| 权限顺序 | 按 agent 禁用插件过滤 + MCP audience | guardrails + approval | **hooks → deny → mode → allow → canUseTool**；mode 含 plan/bypassPermissions 等 |
| 可见性 | `metadata.visibility`（`model`/`app`）；指纹只做资源归属，非 RBAC | hosted/远端工具统一目录 | 工具白名单 + skill/mcp 声明 |

### 1.4 上下文、观测、调度

| 组件 | LobeHub | OpenAI | Claude |
|---|---|---|---|
| 压缩 | 阈值 `maxWindow×0.5`，保留最近 user 原文并重注入，独立小模型摘要，1.25 drift 估算 | `context_management.compact_threshold` + `/responses/compact` + input filter | 服务端 compaction + context editing（`clear_tool_uses`/`clear_thinking`） |
| 观测 | `ExecutionSnapshot`：traceId/model/steps/tokens/totalCost/completionReason；`StepSnapshot`：toolsCalling/Result/context 快照 | 默认 tracing：agent/turn/generation/function/guardrail/handoff span | 无内建 trace；hooks 审计 + 逐 step token/`total_cost_usd` |
| 调度 | `tasks.automation_mode=heartbeat\|schedule`，动作走同一 runtime 工具面 | `background=true` 轮询/取消/续读 | Managed Agents：SSE 事件流 + cron 部署 |
| 模型路由 | `RouterRuntime` 多渠道 failover；**成本/能力自动选模=unknown** | 模型参数显式 | 模型显式 |

> 来源：LobeHub [loop](https://github.com/lobehub/lobehub/blob/main/packages/agent-runtime/src/loop/index.ts)、[runtime](https://github.com/lobehub/lobehub/blob/main/packages/agent-runtime/src/core/runtime.ts)、[toolSet](https://github.com/lobehub/lobehub/blob/main/packages/mecha/src/toolSet/index.ts)、[compressContext](https://github.com/lobehub/lobehub/blob/main/packages/agent-runtime/src/executors/compressContext.ts)、[task schema](https://github.com/lobehub/lobehub/blob/main/packages/database/src/schemas/task.ts)、[tracing](https://github.com/lobehub/lobehub/blob/main/packages/agent-tracing/src/types.ts)；OpenAI [running agents](https://openai.github.io/openai-agents-python/running_agents/)、[multi-agent](https://openai.github.io/openai-agents-python/multi_agent/)、[tools](https://openai.github.io/openai-agents-python/tools/)、[guardrails](https://openai.github.io/openai-agents-python/guardrails/)、[sessions](https://openai.github.io/openai-agents-python/sessions/)、[tracing](https://openai.github.io/openai-agents-python/tracing/)、[compaction](https://developers.openai.com/api/docs/guides/compaction)、[background](https://developers.openai.com/api/docs/guides/background)；Claude [Agent SDK](https://platform.claude.com/docs/en/agent-sdk/overview)、[subagents](https://platform.claude.com/docs/en/agent-sdk/subagents)、[permissions](https://platform.claude.com/docs/en/agent-sdk/permissions)、[hooks](https://platform.claude.com/docs/en/agent-sdk/hooks)、[sessions](https://platform.claude.com/docs/en/agent-sdk/sessions)、[Building effective agents](https://www.anthropic.com/engineering/building-effective-agents)、[context editing](https://platform.claude.com/docs/en/build-with-claude/context-editing)、[Managed Agents](https://platform.claude.com/docs/en/managed-agents/overview)。

**局限**：文档随版本变化；LobeHub 部分结论来自源码路径而非文档；「成本/能力自动选模」在 LobeHub 未证实，标 `unknown`。

---

## §2 参考总装线（7 段）

```text
① 入口分流 sense/          路由 + 复杂度 + 预算预估 + 能力目录
        ↓  route_signal + budget_plan
② 规划编排 arrange/        显式 Plan（步骤/工具/验收）+ 软硬预算
        ↓  Plan artifact（PlanCard 同构）
③ 工具解析 capability/     唯一 tool_set 副本 + 受众可见性 + 审批策略
        ↓  resolved_tools
④ 执行循环 compute/        loop：final | tool_calls | handoff；stop_reason 唯一
        ↓  step trace + artifact
⑤ 验收护栏 45/gate         tripwire 硬失败 + evaluator-optimizer（迭代上限）
        ↓  verdict + evidence
⑥ 记忆压缩 graph_store/    锚点保留 + 摘要 + 证据外置（不被摘要覆盖）
        ↓  context / memory
⑦ 观测调度 scheduler/      span（run_id/model_id/tokens/cost）+ background/heartbeat
```

---

## §3 DreamOS 逐模块改造面

| 段 | DreamOS 现有模块 | 现状 | 对标目标 | 改法（最小） | L0/L1 发力 | 优先级 |
|---|---|---|---|---|---|---|
| ① 入口 | `core/sense/intent_engine.py`、`complexity_classifier.py`、`capability_router.py`、`token_budget.py` | 意图/复杂度/预算各自算 | OpenAI routing + Claude routing workflow | 统一输出 `route_signal{lane, route, budget_plan, stop_policy}`；`token_budget` 产软/硬双阈值 | **L1** 提供 case_density/语义相似度作为路由证据；**L0** 提供能力目录与历史成本 | P0 |
| ② 规划 | `core/arrange/graph_planner.py`、`node_selector.py`、`budget_allocator.py`、`execution_graph.py` | 图规划有，无显式 Plan 契约 | orchestrator-workers；PlanCard | 让 `execution_graph` 直接产出 PlanCard 同构（steps/tool/validation/max_steps） | **L1** 相似案例检索给候选步骤；**L0** 节点/工具注册表约束可执行性 | P0 |
| ③ 工具 | `core/capability/registry.py`、`router.py` + 47 MCP | 两套静态清单（registry/roles） | `operationToolSet` 单副本 + audience + 权限顺序 | 建 `tool_set` 运行时快照（enabled/tools/manifest/visibility/approval）；权限按 `deny→mode→allow→human` 排序 | **L0** 壳/工具/配额是事实源；**L1** 按任务类型给工具建议（只建议不授权） | P0 |
| ④ 执行 | `core/compute/graph_executor.py`、`node_runner.py` | 有执行，无统一 stop_reason | loop 三出口 + 7 值停止 + soft/hard | loop 返回值唯一为 `stop_reason`；`parked` 单列 `waiting_for_human/async_tool/client`；恢复走独立入口 | **L0** Ticket/快照持久化；**L1** 不参与循环 | P0 |
| ⑤ 验收 | `compute/aggregator.py`、`gate_45_adapter`、`45` | 45 shadow、INCONCLUSIVE 不拦 | guardrail tripwire + evaluator-optimizer | 定义 `tripwire`（硬失败码）与迭代上限；45 不可用不得当 PASS | **L1** 统计证据（n≥30、p_adj）作为验收输入；**L0** 落 verdict/证据 | P1 |
| ⑥ 记忆 | `graph_store/compressor.py`、`memory/*`、24 BAC | 有压缩件，未接协议层循环 | 锚点保留 + 证据外置 | 压缩保留「最新 user 指令 + 未完成 Plan 步骤」原文并重注入；工具结果写 trace 不进摘要 | **L1** 相似案例/反思检索；**L0** 图存储为唯一事实源 | P1 |
| ⑦ 观测调度 | `core/scheduler/dynamic_evaluator.py`、`token_budget.py`、52 `supervisor.py` | 无 span 契约；调度不跨重启 | tracing spans + background/heartbeat | 统一 span：`run_id/model_id/step/tokens/cost/stop_reason/context_hash`；调度持久化 + heartbeat | **L0** 计量/账本/调度状态；**L1** 异常检测触发重跑 | P1 |
| ⑧ 进化 | `compute/auto_bugfix.py`、`hermes_reflector.py`、`param_optimizer.py`、`canary_registry.py`、`case_ingest_gate.py` | 零件多，未串成闭环 | Claude/OpenAI 的 evaluator-optimizer + 自扩展 | 串成「L1 发现 → 任务 → 修复 → 45 → 台账 → 案例」；插件先 inspect/experiment 再 install | **L1** 发现与统计验证；**L0** 台账与案例库 | P1 |

---

## §4 L0 / L1 在总装线上的正确位置

| 层 | 在总装线里的角色 | 允许 | 禁止 |
|---|---|---|---|
| **L0** | 事实底座：工具/注册表/状态/Ticket/预算/账本/trace | 被任何段读取；写只能经壳 | 不产生判断，不做统计结论 |
| **L1** | 证据底座：路由证据、相似案例、异常/漂移、统计检验 | 作为 ①②⑤⑦ 的输入；只读出口 | 不进热路径；不写执行；不直接改 Plan |
| **L2** | 动作底座：规划/生成/修复/编排 | 消费 L0 事实 + L1 证据；产出 Plan/动作/理由 | 不替 L1 做统计判定；不自证验收 |

三条硬规则：

1. **先 L0 后 LLM**：任何请求先走 L0 事实/能力目录；能确定性回答就不进 L2（3.1 chat 已实现 L1 直答优先，可推广到 DreamOS）。
2. **L1 只给证据不给结论**：路由用 `case_density/semantic margin`，验收用 `n/p_adj/CI`，由 L2 决定怎么用。
3. **L1 发现必须能入队**：异常/漂移/失效假设生成 `repair_ledger.trigger`，否则 G-L2-7 的「发现权在 L1」落不了地。

---

## §5 新增缺口（承接 GAP-17~23）

| # | 缺口 | 证据 | 影响 | 优先级 |
|---|---|---|---|---|
| **GAP-24** | 无统一 loop 契约（`stop_reason` / `max_turns` / soft-hard budget / `parked` 三态） | `chat/route.ts` `stepCountIs(5)`；`ticket_state.py` 四态；DreamOS `graph_executor` 无停止枚举 | 调度不可复盘，恢复语义错 | **P0** |
| **GAP-25** | 工具集非单副本、无受众可见性、无权限顺序 | `capability/registry.py` + 47 roles + 3.1 profile 三处静态清单 | 权限漂移与工具面不一致 | **P0** |
| **GAP-26** | 上下文压缩无锚点、未接 24 BAC，压缩后目标可能丢失 | `graph_store/compressor.py` 未接协议层；`24` 未接线 | 长任务跑偏 | P1 |
| **GAP-27** | 验收无 tripwire 硬失败，45 仍 shadow/INCONCLUSIVE | `gate_45_adapter`、45 `INCONCLUSIVE` | 无验收 = 无总装线闭环 | **P1** |
| **GAP-28** | handoff 与 agents-as-tools 未区分 | PlanCard 只表达「交接产物」，无控制权语义 | 主控/专家权责不清 | P1 |
| **GAP-29** | L1 发现不驱动 L2 任务队列 | `repair_ledger.trigger` 契约已冻结，但无生成方 | 「优化」退化为凭感觉 | **P1** |
| **GAP-30** | 无 trace span 契约（`run_id/model_id/step/tokens/cost/stop_reason/context_hash`） | DreamOS trace / 52 trace / 3.1 trace 三套字段 | 无法跨段对账 | P1 |

---

## §6 落地路线（先契约、后模块、再回路）

> **A0 状态（2026-11-16）**：✅ **已关闭**。四契约 v1.1 冻结（`stop_reason`/`tool_set`/`span`/`plan_handoff`）；全量自检 `SELF-TEST PASSED (28/28)`；运行时行为未改。评审记录见 [REVIEW-20261116-A0契约与总装线对标评审.md](./REVIEW-20261116-A0契约与总装线对标评审.md)。下一步：A1-1 `graph_executor` 统一 `stop_reason`。
>
> **A1-1 状态（2026-11-16）**：✅ **已落地**。`ExecutionReport.stop_contract()` 输出 7 值出口（done / cost_limit / max_steps / parked / error 已由运行时产生；`interrupted` 由 `should_interrupt` 回调产生；`no_next_context` 留待 handoff 语义）；软预算软收尾、硬预算硬停、`resume_from` 独立恢复入口已实现。证据：`1-ARCHITECTURE/dreamos/tests/test_a1_graph_executor_stop_reason.py` 8/8 绿；三份抽样 `--stop-reason` 校验 0 violation。下一步：A1-2 `capability` 产出唯一 `tool_set`。
>
> **A1-2 状态（2026-11-16）**：✅ **已落地**。`core/capability/tool_set.py` 从 47 registry 生成唯一 `tool_set` 快照（78 工具 / 44·20·14 分层 / 3 退役 denied / 4 交易工具强制 `human`）；`quota_report()` 完成 D3 交叉校验并显式暴露 GAP-18 口径不一致 warning；3.1 `mcp-multi-shell.ts` 多壳聚合（FAIL-OPEN、冲突留痕）已接入 `api/agent/chat`。证据：`test_a1_tool_set.py` 9/9、`mcp-multi-shell.test.ts` 6/6、`--tool-set` 0 violation。下一步：A1-3 `graph_store.compressor` 接 24 BAC 锚点压缩。
>
> **A1-3 状态（2026-11-16）**：✅ **已落地**。`ContextCompressor` 接 24 BAC 锚点语义：Blueprint 目标 / 最新用户指令 / 未完成 Plan 节点原文保留并重注入 `state.extra.compression_anchors`；trace 首部 `anchor_nodes`（默认 2）强制保留、只压中段；Plan `is_required` 节点证据不降级；工具结果只进 trace 不进摘要。证据：`test_a1_compressor_anchors.py` 5/5 绿。
>
> **A1-4 状态（2026-11-17）**：✅ **已落地，A1 收口**。`compute/tripwire.py` 双模（shadow 记录 / hard 熔断）+ 内置 `G-L2-10` 出口契约、`G-L2-11` 工具集门禁；`GraphExecutor` 在门禁节点与出口评估，`INSERT_BEFORE` 受 `max_inserts` 约束，循环内按阈值自动压缩（GAP-26 关闭）。证据：`test_a1_tripwire_and_limits.py` 8/8；A1 四组合并 30/30 绿。
>
> **A2-1 状态（2026-11-17）**：✅ **已落地**。台账契约升 v1.1（初始 `reported→reported` 自迁移，自检 29/29）；新增 `34/core/l2_repair_ledger.py`：L1 发现（`54.discovery_path`）→ `trigger` → 台账入队，fail-closed（ref/symptom/复现证据不合规即拒写）、幂等（同 ref+symptom 不重复入队）、`task_id` 按日递增、复现产物自动 sha256；优化类强制 45/stats 证据与 metrics。证据：`test_l2_repair_ledger.py` 12/12，产出经 `--ledger` 0 violation。GAP-29 生成侧关闭。下一步：A2-2 L2 settle 回写台账/周报。
>
> **A2-2 状态（2026-11-17）**：✅ **已落地，A2 收口**。`34/core/l2_settle.py`：只允许 `regression_passed → settled`（回归失败/缺 `run_ids`/非法状态 fail-closed），补齐回归证据与四分流后原子替换台账；案例回写 L0 `l1_case_store.jsonl`（`case_type=l2_repair`，按 task_id 幂等，`case=skipped` 不写）；周报出修复率/回归通过率/优化收益，0 样本记 `null`（不造数）。证据：`test_l2_settle.py` 10/10，A2 合并 22/22，`--self-test` 29/29，`reports/l2_weekly_2026-W47.md` 已生成。
>
> **A3-1 状态（2026-11-17）**：✅ **已落地（inspect 只读）**。`1-ARCHITECTURE/dreamos/core/capability/plugin_inspect.py`：读 DSH profile `package.json` + 本地插件包清单/源码，静态产出 IF-6 `inspect.response`（插件/依赖/事件通道/能力面）；`file:` 缺失进 `graph.unresolved`，依赖环 fail-closed（契约只允许 `acyclic=true`）；全程只读不写盘。实测 headless：17 插件 / 0 unresolved / 8 tools / 9 subscribe / 1 publish，响应经 `--plugin` 0 violation。证据：`test_a3_plugin_inspect.py` 9/9、A1+A3 合并 39/39。下一步：A3-2 experiment（沙箱内存试跑，`disk_writes=0`）。
>
> **A3-2 状态（2026-11-17）**：✅ **已落地（experiment 沙箱预检）**。`1-ARCHITECTURE/dreamos/core/capability/plugin_experiment.py`：manifest 合法性 + 依赖可解析 + 发布通道冲突 + 权限面预检，复用 A3-1 只读插件图；不执行第三方代码、零落盘（`disk_writes=0`），错误走 IF-6 六码枚举。实测 headless：合法 manifest → `ok/loaded=true`；发布 `agent/turn-stopping` → `E_CHANNEL_CONFLICT`（已由 reflector 发布）。证据：`test_a3_plugin_experiment.py` 15/15、A1+A3 合并 54/54、两份响应 `--plugin` 0 violation。下一步：A3-3 unload 四类副作用回滚验证（通过后才开 install）。
>
> **A3-3 状态（2026-11-17）**：✅ **已落地（unload 四类副作用验收）**。`1-ARCHITECTURE/dreamos/core/capability/plugin_unload.py`：校验 `rollback_token`（未过期 + idempotency_key）+ Mandate（scope=`plugin.unload`），对 before/after 快照逐类比对 `subscription`/`connection`/`handle`/`timer`——插件自有副作用必须清零、其他插件副作用不得误删，全清且插件已消失才 `ok=true`。不执行卸载、不伪造运行时状态，缺快照即拒绝。演练：干净卸载四类全回滚；残留 `timer` 正确 `ok=false` 且不列入已回滚。证据：`test_a3_plugin_unload.py` 12/12、A1+A3 合并 66/66、两份响应 `--plugin` 0 violation。下一步：A3-4 install 门禁。
>
> **A3-4 状态（2026-11-17）**：✅ **已落地（install 门禁）**。`1-ARCHITECTURE/dreamos/core/capability/plugin_install.py`：四道硬门禁——request（含 `rollback_verified=true`）、Mandate（scope=`plugin.install`/未过期）、53 白名单（approved/非 forbidden/permitted_profiles/生产 profile 需 sandbox+FAIL-OPEN）、`plugin_ready`（A3-2 experiment 通过且 `disk_writes=0` + A3-3 四类回滚证据齐全）。门禁全过仍需注入 `InstallAdapter` 才落盘；未注入即 fail-closed，禁止伪造 `installed=true`。真实预检：`dreambuddy-c1 @ sandbox` 通过；未登记插件 deny-by-default 拒绝。证据：`test_a3_plugin_install.py` 16/16、A1+A3 合并 82/82、合法 install.response `--plugin` 0 violation。**adapter 接缝已落地（2026-11-17）**：`plugin_runtime_adapter.py` 生成 `dsh plugin add/remove` 命令、执行后回读 profile 确认、runner 可注入、四类副作用只认 probe 快照，默认 dry-run；fake 端到端跑通 `install → token → remove → 四类验收`，10/10 绿。**真实 apply（2026-11-17）**：项目内 `DSH_HOME` 的 sandbox profile 上 `dsh plugin add/remove dreambuddy-stats` 均 rc=0，`package.json` 与 `pnpm-lock.yaml` SHA-256 前后一致；期间修复 `file:` 相对路径受 cwd 影响、包名与目录名不一致两处缺陷。**loader 探针已落地（2026-11-17）**：`probes/dsh_probe_plugin.mjs` patch `Fiber.prototype.effect`，在真实 Cordis 上验证订阅归属与 `fiber.dispose()` 自动注销；挂到实际 profile 见 A3-5。
>
> **A3-5 状态（2026-11-17）**：✅ **已落地（探针挂进 sandbox profile），GAP-21 关闭**。新增 DSH bundle 包 `1-ARCHITECTURE/dreamos/probes/dsh-probe-plugin/`：`package.json` 声明 `dsh.bundle.patch`，`index.mjs` 单文件自包含（采集器 + Cordis 插件），`cordis.patch.yml` 以 `insert` 挂 `dreambuddy-side-effect-probe`。`DSH_HOME=<repo>/.dsh-home dsh plugin add file:<abs> --profile sandbox` rc=0 并自动写入 `dsh.profile.bundles`；`dsh --profile sandbox --dump-config` 出现 `# == dreambuddy-side-effect-probe` entry；用 node_modules 内「已安装副本」跑真实 Cordis，`probe.complete=true`、订阅 `sub:p-installed:agent/pre-step`、`dispose()` 后四类清零，Python `require_complete` 通过。踩坑：pnpm `file:` 依赖是硬链接，只同步同名文件，新增文件不会被复制 → 改单文件自包含，父目录两个 `.mjs` 保留为转发入口。证据：A1+A3+capability 140/140、`test_a3_dsh_loader_probe.py` 1/1、`--self-test` 29/29。
>
> **P08 状态（2026-11-17）**：✅ **导出落地**。`preset_export.py` 从 A3-1 插件图 + 53 白名单生成可部署集合，插件按 id 排序、`preset_hash` 不含时间戳、篡改/乱序拒绝；headless 实测 12 plugins / 5 skipped（均为 unregistered）。一键加载已落地（`preset_load.py`：先校验后加载，默认 dry-run，apply 需 adapter）。

```text
A0 契约冻结（不改行为，1 周内可完成）
   A0-1 stop_reason 枚举 + parked 三态（GAP-24）
   A0-2 tool_set 运行时快照 schema + 权限顺序（GAP-25）
   A0-3 trace span schema（GAP-30）
   A0-4 Plan 契约与 PlanCard 对齐（GAP-28）

A1 单模块改造（按依赖顺序）
   A1-1 graph_executor 返回 stop_reason（软/硬预算）
   A1-2 capability 层生成 tool_set 单副本 + 3.1 多壳消费
   A1-3 graph_store.compressor 接 24 BAC，锚点保留
   A1-4 45 tripwire + 迭代上限（先 shadow 记录，再硬失败）

A2 两条反馈回路
   A2-1 L1 发现 → repair_ledger.trigger → L2 任务入队（GAP-29）
   A2-2 L2 settle → 台账/案例 → L0；周报出修复率/回归通过率/优化收益

A3 自扩展
   A3-1 inspect（只读插件图）
   A3-2 experiment（内存/沙箱试跑）
   A3-3 unload 四类副作用回滚通过后才开 install（ADR-10）
   A3-4 install 门禁（Mandate + 白名单 + experiment + 四类回滚证据）
   A3-5 adapter 接缝 + sandbox 真实 apply（DSH_HOME 需显式指定）
```

### 6.1 对照实验（承接 H1–H3，新增 H4–H5）

| 假设 | 样本 | 分组 | 指标 | 判定 |
|---|---|---|---|---|
| H1 统一信封不降质 | 30 条 trace 回放 | 无信封 vs 加字段 | 完整率/一致率/成本偏差 | 100% / ≥95% / ≤2% |
| H2 多壳聚合提效 | 20 个开发端任务 | 单壳 vs 多壳 | 完成率/步数/失败率 | +10pp 且回归不降 |
| H3 stop_reason 可解释 | 7 天全量 trace | 现状 vs 新契约 | unclassified 占比 | <5% |
| H4 L1 驱动任务更有效 | 10 个 L1 发现 + 10 个人工指定 | 发现驱动 vs 人工 | 修复率/回归通过率/收益 | 修复率不低且收益更高 |
| H5 锚点压缩不跑偏 | 20 个 ≥20 轮长任务 | 普通摘要 vs 锚点压缩 | 目标保持率/完成率 | 目标保持率 ≥90% |

---

## §7 与前序结论的关系

- GAP-17（计量双轨）、GAP-19（单壳）、GAP-20（终止语义）、GAP-21（插件回滚）、GAP-22（调度）在本报告中被合并进 **A0/A1** 的契约层，避免重复建设。
- 本报告新增的 GAP-24~30 全部是「段与段之间」的契约/回路问题，**不新增业务能力**。
- 一句话：**DreamOS 不需要再长器官，需要神经与筋膜**——把 L0 的事实、L1 的证据、L2 的动作用统一契约连起来。
