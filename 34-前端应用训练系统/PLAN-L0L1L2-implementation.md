# PLAN — L0/L1/L2 三层能力架构实施计划

> 版本: v1.0 | 日期: 2026-10-16 | 依据: `SPEC-v1.3-L0L1L2-architecture.md` §3/§5/§6 + `L0-接口规范-fetchContext.md` v0.1 + `SPEC-CDrive-CognitiveSystem-Integration.md` §7
> 定位: 把 SPEC-v1.3 的「待推进项」拆解为可执行、可验证、可分阶段落地的工程任务。
> 状态标记: ✅ 已落地 / 🔄 本次落地 / ⬜ 待落地

---

## 0. 目标与总原则

**总目标**: 把 L0（数据/经验/工程供给）、L1（零 token 确定性能力）、L2（大模型驱动）三层从"文档规范"推进到"可运行代码"，并保证**零回归**（已验证的十意图执行链路行为不变）。

**总原则**:
1. **主体唯一 · 形态可降级**（SPEC §3）：不因暴露形态改变层归属；
2. **零回归优先**：每次收敛只改"数据访问方式"，不改"答案格式与业务语义"；
3. **FAIL-OPEN**：任一 scope 不可用返回 degraded，绝不抛错阻塞（无大模型渐进降级）；
4. **TDD 落地**：RED（断言 ModuleNotFoundError）→ GREEN（实现）→ 回归（端到端）。

---

## 1. 现状基线（2026-10-16 代码核对）

| 项 | 现状 | 证据 |
|---|---|---|
| L1 十意图执行器 | ✅ 已落地 | `3.1-FRONTEND/scripts/data_query_executor.py`（10 个 exec_*） |
| L1 意图注册表 + 路由器 | ✅ 已落地 | `3.1-FRONTEND/src/lib/l1-intent-registry.ts`（canHandleL1/fallbackIntent） |
| L1 沉淀分流 | ✅ 已落地 | `settle_to_cognitive()`（案例库 + 认知价值沉淀） |
| C3 匹配度评分 | ✅ 已落地 | `34-前端应用训练系统/core/cognitive_router.py` `evaluate_match` |
| C4 预测误差门控 | ✅ 已落地 | `34-前端应用训练系统/core/jev_gate.py` |
| L0 fetchContext 抽象 | ✅ 已落地（2026-10-16 P1） | `34-前端应用训练系统/core/l0_foundation.py`（L0Foundation + 10 scope）；exec_* 已全部收敛 |
| L1 路由器置信度门控 | ✅ 信号+端到端已落地（2026-10-19 P3 接线） | `core/route_confidence.py` 产出信号 → `scripts/l1_route_signal.py` → `POST /api/data/query` → ChatPanel `canHandleL1WithSignal` 消费；v2 requiredPattern 保留为静态兜底 |
| L1 路由 HTTP 入口 | ✅ 已落地（2026-10-19 P3） | `3.1-FRONTEND/src/app/api/data/query/route.ts`（execFile，信封 {ok,data}，FAIL-OPEN；此前路由 404，L1 链路从未生效） |
| L2 交接协议 | ✅ 已落地（2026-10-19 P3b+P3.2） | `l1_intent_hint` 全链路：ChatPanel → `/api/task/stream` → `task.metadata` 落盘 → S 层档案消费 + `CDriveV3Router.run_v3` recall context 注入 |
| S→A→C→G 编排骨架 | ✅ P3.1 已落地（2026-10-19） | `core/sacg_orchestrator.py`：route_confidence 入口门 + C-drive 全程调度（节点决策委托 `CDriveV3Router`），10 单测；P3.2-P3.5 各层实质接入待续 |
| 认知接口暴露（MCP） | 🔄 工具就绪 | `cognitive_mcp_server.py` 可用；L2 侧实际调用未接 |
| 19 DAL | 🔄 包就绪未接线 | `19-数据访问层/dreambuddy_dal/` 存在；迁移计划面向交易子系统 |

---

## 2. 任务分解

### P1 — L0 数据访问抽象层（✅ 已落地 2026-10-16）

**目标**: 落地 `FoundationLayer.fetchContext`，把十意图的硬编码数据访问收敛到统一抽象（SPEC §6 待推进项 1「阶段二 包装收敛」）。

| 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|
| P1.1 L0Foundation 类 + scope 注册表（10 scope） | `34-前端应用训练系统/core/l0_foundation.py`（新建） | pytest 全绿 | ✅ |
| P1.2 TDD 测试 | `34-前端应用训练系统/tests/test_l0_foundation.py`（新建，45 测试） | RED→GREEN | ✅ |
| P1.3 执行器收敛：十意图 exec_* 改为 `fetch_context(scope)` | `3.1-FRONTEND/scripts/data_query_executor.py`（改） | 十意图端到端输出不变 | ✅ |

**落地证据（2026-10-16）**:
- 10 scope 全部注册（含新增 `cognitive.recall`），统一信封 `{ok,data,source,timestamp,degraded,meta}`，FAIL-OPEN（unknown_scope/invalid_params/source_missing/read_error/upstream_unavailable/cognitive_unavailable/fetch_error 全降级不抛错）；
- settle 分流（案例库 jsonl + 认知价值 record）上收至 `L0Foundation.settle`，executor 侧薄封装委托，行为不变；
- 十意图收敛前后各跑一轮真实环境端到端对比：answer 模板/data 结构/degraded 路径全一致（ZERO-REGRESSION PASS，活数据数值差异除外）；
- 全量 `pytest 34-前端应用训练系统/tests`：511 基线 → 556（+45）全绿。

**scope 契约**（对齐 `L0-接口规范-fetchContext.md` §3）:
`fetch_context(scope, params) -> {ok, data, source, timestamp, degraded, meta}`

| scope | params | 数据源 |
|---|---|---|
| `datacenter.record` | `{source}` | 18 中心 data_center.db |
| `evolution.contradiction` | — | 23 系统 evolution_pipeline.log |
| `evolution.snapshot` | — | 23 系统 evolution_snapshots.json |
| `yijing.bcrm2` | — | 11 系统 bcrm2_hourly_summary.json |
| `yijing.bdsm` | — | 11 系统 bdsm_snapshot_*.json |
| `yijing.strategic` | — | 11 系统 polling_trader 日志 |
| `event.state` | — | 11 系统 event_driven_state.json |
| `riskcontrol.trailing` | — | 16 系统 trailing_runner 日志 |
| `market.ticker` | `{symbol}` | OKX 公开行情 API |
| `cognitive.recall` | `{context, top_k}` | 4-MEMORY 认知系统 |

**边界**: L0 只返回**原始数据**（data），答案格式化仍留在 L1 exec_*；不改业务语义。

### P2 — L1 置信度门控信号接入（✅ 信号产出器 + TS 入口已落地 2026-10-16；端到端消费随 P3 接线）

**目标**: 用 C3/C4 产出的 `route_confidence` 替换注册表侧静态置信度（SPEC §6 待推进项 2/4、CDrive SPEC §7）。

| 任务 | 文件 | 验收 | 状态 |
|---|---|---|---|
| P2.1 信号产出器（C3+C4 → route_confidence） | `34-前端应用训练系统/core/route_confidence.py`（新建） | pytest + 阈值一致性 | ✅ |
| P2.2 路由器消费（TS 侧读信号） | `3.1-FRONTEND/src/lib/l1-intent-registry.ts`（改，可选） | canHandleL1 保留静态兜底 + 预留信号入口 | ✅ |

**落地证据（2026-10-16）**:
- `route_confidence.evaluate_route()` 复用 `cognitive_router.evaluate_match`（C3）与 `jev_gate` 常量（C4），不重写第二套；严格按公式 `match − 0.3(predErr>0.3) − 0.2(density<3)`，阈值边界（=0.3 不扣、=0.7 放行）有测试锁定；
- FAIL-OPEN 矩阵全覆盖：recall 空→0 转 L2 / C4 不可用或异常→纯 C3 / 认知整体不可用→静态置信度兜底（`tests/test_route_confidence.py`，24 测试）；
- TS 侧新增 `RouteConfidenceSignal` 类型 + `canHandleL1WithSignal()`：有信号以信号为准，缺失/非法 FAIL-OPEN 退回 v2 静态 `canHandleL1`；15 Jest 测试通过，`tsc --noEmit` 本次改动文件 0 错误；
- 全量 `pytest 34-前端应用训练系统/tests`：556 → 580（+24）全绿；
- 剩余接线（前端路由实际透传信号、C-drive 侧消费）随 P3 SACG 编排一起落地，本阶段只预留入口。

**阈值硬约束**（CDrive SPEC §7.7，跨系统统一，禁止自定义第二套）:
`THRESHOLD_HIGH=0.7`、`CASE_DENSITY_MIN=3`、`PREDICTION_ERROR_MAX=0.3`、`FAST_PATH: match≥0.8 & density≥5`。

### P3 — L2：C-drive 驱动的 SACG 编排落地（🔄 P3.1 骨架 + 门控信号端到端已落地 2026-10-19；P3.2-P3.6 待续）

**审计结论（文档 vs 代码）**: L2 的核心 —— **C-drive 驱动的 SACG 新架构** —— 目前**只有"节点级反思决策门"落了地**，**"S→A→C→G 全程编排调度"仍停留在 SPEC-v1.2 文档**。这是"感觉不全"的根因。

**逐层审计**（新逻辑依据 `SPEC-v1.2-SACG-orchestration.md` §3；旧实现依据 `v3-frontend-architecture.md` §3.2）：

| SACG 层 | 新逻辑（SPEC-v1.2） | 代码现状 | 状态 |
|---|---|---|---|
| **C-drive** | 贯穿 S→A→C→G 的**全程调度者** | `core/c_drive_v3_router.py`：五步**节点级反思决策门**（evaluate_match→route→jev_gate→close_loop），已 wire 到 `c_drive_agent.run_v3` | 🔄 只有决策门，**无编排调度** |
| **S** | 认知驱动规划入口：①认知意图识别（以 `l1_intent_hint` 为先验）②REA 架构识别 ③触发外部调研 ④开工 Skill→**Spec/Plan** | IntentEngine 本地分类（旧）；`l1_intent_hint` 由前端透传但 C-drive 侧未消费 | ❌ ①-④ 全缺 |
| **A** | **OKR 节点验收体系**（依 Spec/Plan 分解，每节点验收标准） | GraphPlanner（preset 工具组合器，旧）；无验收节点 | ❌ 全缺 |
| **C** | DSH 子 agent + GraphExecutor 执行，Reflector 内反思；**结果回传 A 验收** | Reflector 6 决策 ✅；DSH 子 agent ✅；回传 A ❌ | 🔄 部分 |
| **G** | GraphStore 图压缩 ✅；**收尾 Skill 联动四分流沉淀** | GraphStore/BAC 压缩 ✅；收尾 Skill 未 Skill 化 | 🔄 部分 |

**任务拆解**:

| 任务 | 内容 | 落点 | 验收 |
|---|---|---|---|
| P3.1 | ✅ **C-drive 调度层**（2026-10-19）：S→A→C→G 编排骨架 `SACGOrchestrator.handle()`，route_confidence 门控入口（L1_DIRECT 不编排 / L2_HANDOFF 全程调度），C 层节点决策委托 `CDriveV3Router.run_v3`，S/A/G 可注入扩展点，层间异常隔离 FAIL-OPEN | `core/sacg_orchestrator.py` + `tests/test_sacg_orchestrator.py`（10 测试） | ✅ 单测：请求入口 → S→A→C→G 流转（617 passed） |
| P3.2 | ✅ **S 层认知接入**（2026-10-19）：`S_LAYER_INTENT_PROFILES` 十意图档案（与 TS 注册表对齐）驱动规划展开 + Spec 草案 `{intent,depth,source}` 产出；hint 透传 C 层 `run_v3(l1_intent_hint=)` 注入 recall context（`hint:xxx` 先验）；开工 Skill 实质触发已由 SPEC-v1.4 闭合（见下行） | `core/sacg_orchestrator.py`（S 层）+ `core/c_drive_v3_router.py` 消费 hint | ✅ 单测：hint 注入 → 规划产出（8 新测试，634 passed） |
| P3.2b | ✅ **S 层完整化（SPEC-v1.4，2026-10-16）**：`core/sufficiency.py` 充分性评估器（S0 入口四态 + S2 规划四态，只引用 0.7/3/0.3 派生，禁新阈值）；**S-1b jev 终裁接入**（默认分支经 `jev_gate`，`rea_confidence=match` 中和预测误差仅留 believability/HOT；信号矛盾两形态 → NEED_CLARIFY；jev 改写 → NEED_CLARIFY `jev_override_to_clarify`；`JevAntiOscillation` 抗振荡参数；空计划态与双低 NEED_RESEARCH 路径绕过 jev）；`SLayerPlanner` 充分性状态机替换默认 s_planner（新契约 `{plan,sufficiency,action,clarification,research_request,kickoff_trigger}`，旧契约兼容）；NEED_CLARIFY/EARLY_TERMINATE 短路停在 S 层；开工 Skill 触发门（depth=deep + NEED_RESEARCH 或显式「开工」→ async_stub 打桩）；深度升级 light→standard→deep；§3.5 能力调用链（认知经验 top3 注入 plan + REA 逆向拆解 engineering_okr 供 A 层优先消费 + kickoff post_research_rea 契约，REA FAIL-OPEN） | `core/sufficiency.py`（新建+S-1b）+ `core/sacg_orchestrator.py`（SLayerPlanner）+ `tests/test_s_layer_sufficiency.py`（30 测试）+ `tests/test_s_layer_capability_chain.py`（8 测试） | ✅ 675 passed + tsc 0；依据 `SPEC-v1.4-S-layer-design.md` |
| P3.3 | ✅ **A 层 OKR 验收**（2026-10-16）：`core/okr_nodes.py` OKR 节点验收体系（SPEC-v1.2 §2.2）——Spec/Plan → OKR 节点 `{node_id, objective, criteria, source, verify, evidence_id?}`，每节点带验收标准；verify 按来源分派（rea_evidence→evidence_backed / rea_known_gap→gap_closed / plan_item→c_action，禁新阈值）；engineering_okr 优先于 plan_items；criteria 一律字符串；node_id+criteria 键向后兼容 C 层；`_default_a_decomposer` 实质化委托 | `core/okr_nodes.py`（新建）+ `core/sacg_orchestrator.py`（接线）+ `tests/test_a_layer_okr.py`（8 测试） | ✅ 单测：Plan → OKR 节点集（683 passed + tsc 0） |
| P3.4 | ✅ **C 层回传 A 验收**（2026-10-16）：`core/okr_acceptance.py` OKR 验收器——C 层 node_results 回传 A 层逐节点对账式核对（非总额）；三态 verdict（pass/degraded/fail）按 verify 类型分派：c_action（action∉{REDO,EARLY_TERMINATE,FAILED} 且无 error→pass；REDO 或带 error→degraded；EARLY_TERMINATE/FAILED/result_missing→fail）、evidence_backed/gap_closed 首版规则化（action 正常→degraded `evidence_pending` 待验）；对账差异分类（result_missing 节点有结果无 / extras 结果有节点无 / action_rejected）；整体 any fail→fail / any degraded 或 extras→degraded / else pass；红旗清单=fail 节点；禁新阈值、全程 FAIL-OPEN（非法输入→degraded 骨架）；`handle()` C 段后接线输出 `acceptance` 字段，主流程不阻断。借鉴 dream-acceptance-verify 三态+证据必录、CI Quality Gate 显式规则+warning 中间档、金融对账逐笔核对+差异四分类；与 Reflector 粒度区分（过程决策 vs 结果验收）；**金融调研四维验收扩展**（2026-10-16，用户拍板方案A）：domain=finance_research 节点分流走四维验收（practice 实践/theory 理论/backtest 回测/data_source 数据真实，证据载体 `detail.finance_evidence`）——数据造假标记→fail(data_fabricated 硬门，不能造数据)、来源缺失→degraded(data_unverified)、含糊来源（"公开数据"等不可核验）→degraded(source_vague)、backtest 仅样本内→degraded(oos_pending)/含样本外·walk-forward 表述→pass、维度缺失→degraded({dim}_pending)；domain 解析序 item>plan>research_request 推断，无 domain 走代码开发规则；外部调研依据（Bailey & López de Prado 样本外纪律、FinGround 原子声明可溯源、MiFID II 研究质量评估义务）；禁新阈值、全程 FAIL-OPEN | `core/okr_acceptance.py`（新建）+ `core/okr_nodes.py`（domain 传播）+ `core/sacg_orchestrator.py`（接线+plan_for_a 透传）+ `tests/test_a_layer_acceptance.py`（35 测试） | ✅ 单测：执行结果 → 节点验收（718 passed） |
| P3.5 | ✅ **G 层收尾联动**（2026-10-16）：`_default_g_closer` 实质化为四分流沉淀路由（SPEC-v1.2 §2.4），消费 P3.4 acceptance 结果——案例分流（verdict==pass 且有节点 → `{type:"case", nodes}` async_stub 描述符）、流程分流（red_flags 非空 → `{type:"skill", red_flags}`）、文档分流（存在 degraded 节点 → `{type:"doc", pending:[node_ids]}`）、认知分流（必走，委托 `cognitive_loop.close_loop`，verdict→outcome 映射 pass→success/degraded→partial/fail→failure）；sediments 均为 async_stub 打桩（与 S 层 kickoff_trigger 同款模式），真实触发归会话级收尾 Skill，G 层不直接调案例库/skill 系统；规则化路由禁新阈值；acceptance=None FAIL-OPEN 退化为只走认知分流；构造器新增 record_fn/verify_fn/limiter 注入点；`handle()` G 段传 acceptance 并兼容旧 2 参 g_closer | `core/sacg_orchestrator.py`（G 段）+ `tests/test_g_layer_closure.py`（14 测试） | ✅ 单测：收尾 → 四分流（732 passed） |
| P3.6 | ✅ **文档对齐**（2026-10-16）：`v3-frontend-architecture.md` §3.2 从旧 SACG 更新为新 SACG——口径说明升级（新语义 S=认知规划/A=OKR验收/C=执行驱动/G=压缩沉淀 + P3.1-P3.5 落地证据 + C-drive 双语义边界：CDriveV3Router 节点决策门 vs SACGOrchestrator 全程调度者）；四层 UI 表达模型重写（S 充分性状态机四态/十意图档案深度、A OKR 节点三态验收+红旗+金融四维、C C-drive 调度+Reflector 6 决策、G BAC 压缩+四分流沉淀面板）；新增「C-drive 全程调度可视化」小节（入口门控/阶段进度/验收回传/收尾沉淀/降级标记/短路形态 + handle() 返回契约数据源）；组件名不改名约束保留 | `3.1-FRONTEND/docs/v3-frontend-architecture.md` §3.2 | ✅ 无断链 |

**另需拍板的一致性冲突**:
- **OKR 归属漂移**: 前端文档 §3.2 把「OKRSet」放在 **S 层三层价值模型**，SPEC-v1.2 把「OKR 验收」放在 **A 层** —— 同一概念两个归属，需统一（建议：S 层产 OKR 草案，A 层做 OKR 验收，职责分离）；
- **C-drive 双语义**: `SPEC-CDrive-*`（35 模块）里 C-drive = 认知反思执行手臂；`SPEC-v1.2` 里 C-drive = L2 全程调度者 —— 需在文档统一「调度者(SACG 编排) vs 反思器(节点 jev 决策)」边界。

### P3b — L2 交接/接口补全（✅ 已落地 2026-10-19）

| 任务 | 落点 | 验收 |
|---|---|---|
| P3b.1 record_hook/verify_hook MCP 接线 | ✅ L2 SSE 链路：`scripts/l2_cognitive_settle.py` + `/api/task/stream` done 分支 fire-and-forget（9 单测） | ✅ 实测 record 返回 memory_id（VM-1792151811358-e198fc1e） |
| P3b.2 fetchContext 认知 scope 暴露 | ✅ L0 `cognitive.recall` scope（P3 接线已用） | ✅ 回归可用（634 passed） |

### P4 — L0 阶段三：19 DAL 切换（⬜ 依赖 DAL 成熟）

| 任务 | 落点 | 验收 |
|---|---|---|
| P4.1 `datacenter.record` 实现从 sqlite 直查切换 DAL | `core/l0_foundation.py`（内部实现替换） | 上层 exec_* 无感知，输出不变 |

---

## 3. 落地顺序与回归策略

```
P1（L0 抽象+收敛） → P2（L1 置信度信号） → P3（L2 交接/接口） → P4（DAL 切换）
     ✅ 已落地 2026-10-16    ✅ 信号层已落地（接线随 P3）
```

**回归策略**: 每个 exec_* 收敛后，用 `python data_query_executor.py '{"intent":"...","message":"..."}'` 对比收敛前后 `answer` 与 `data` 结构；全量 `pytest 34-前端应用训练系统/tests` 零回归。

---

## 4. 风险与降级

| 风险 | 缓解 |
|---|---|
| 收敛引入回归 | 逐意图收敛 + 端到端对比 + FAIL-OPEN 兜底 |
| 数据源路径差异 | scope 注册表集中登记路径，改一处生效 |
| C3/C4 不可用 | route_confidence FAIL-OPEN → 退回注册表静态置信度 |
| DAL 未成熟 | P4 暂不落地，保留 sqlite 实现（上层已抽象，切换零感知） |
