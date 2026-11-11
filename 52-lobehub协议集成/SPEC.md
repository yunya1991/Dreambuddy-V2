# SPEC: 52-LobeHub 协议集成（Agent 前台与模型路由叠加层）

> 版本：v0.10.0（Phase 5 收尾：side-B 同量级结构扣分，消除双链分不对称）
> 日期：2026-11-11
> 状态：🟢 Phase 0/1/3/4/4.5/4.6 已实施（本地）；Phase 5 已实施（限量）；Phase 2 云端部署待定
> 文档对齐：2026-11-11 全量核对代码/测试/trace 后回填本节状态（见 §3.0 落地状态总表）
> 归属：52-LobeHub协议集成（叠加层，非主骨架）
> 上游：47-MCP 管理系统（L0 能力面唯一事实源）、46-DSH 架构（子域能力供给）
> 下游：DreamOS/SACG（主骨架编排）、33-REA / 48-涌现架构（反思与涌现回流）
> 外部依赖：`lobehub/lobehub`（上游开源项目，协议对接，不 fork 改源码）

---

## §0 定位与决策

### 0.1 一句话定位

**52 把 LobeHub 作为"Agent 前台 + 模型路由"叠加层，通过 MCP 协议消费 L0 能力面；主骨架（DreamOS/DSH/REA）不变。**

52 **不是**主骨架、**不是**能力实现层、**不是**认知记忆库、**不是**交易系统。

### 0.2 调研结论摘要（2026-11-11 GitHub 调研）

| 项 | 事实 |
|---|---|
| 仓库 | lobehub/lobehub（原 LobeChat），84.8k stars，v2.3.2，TS/Next.js 16 + React 19 monorepo |
| 定位 | "Super-Agents on Your Team"：**完整 Agent OS**——自研 agent-runtime（loop+executors）、proactive 任务调度（tasks.automation_mode）、expertise 专长系统、goal/signal 体系、IM 渠道接入、skills/plugins 市场 |
| 关键能力 | 50+ 大模型 provider（model-runtime + RouterRuntime + openaiCompatibleFactory）、**原生 MCP 客户端**（stdio 走 desktop 主进程 / 远程走 HTTP gateway）、acceptance e2e 验收框架 |
| 部署形态 | 独立服务（docker-compose 四套：dev/deploy/production/eval），Postgres（drizzle 100+ 表），desktop(Electron)/cli/workbench 多 app |
| 迭代速度 | 每日多个 nightly PR build，fork 改源码会被上游拖死 |

> **R-A 修正（2026-11-11 源码评审）**：v2 不是纯聊天前台，自带完整 agent runtime / expertise 记忆 / 任务调度。其 expertise 系统（backtest/canon/enforcement）与我方认知记忆高度同构——边界治理见 D4。

**我方缺口（调研确认）**：全仓 Python 代码内**零 LLM client**（无 anthropic/openai/qwen 任何调用），"大脑"完全外挂于 AI 宿主。LobeHub 补的正是这一结构性缺口——**接入任意大模型即可驱动现有能力**。

### 0.3 用户决策（2026-11-11，已确认）

| 编号 | 决策 | 对 52 的约束 |
|---|---|---|
| D1 | 52 定位 = **内置协议层**（v0.5.0 修正，v0.6.1 澄清） | **唯一前端 = 3.1 前端**；不部署任何独立 LobeHub 应用（desktop 已卸载、server/docker 形态弃用）。LobeHub 降级为协议与设计参考，集成落点 = 3.1 前端内置 LLM 协议层（Vercel AI SDK 模型路由 + MCP client → l0_gateway）。依据：@lobechat/* 全部 `private: true` 未发布 npm，代码级嵌入 = vendor fork 违反 D2 |
| D2 | **协议集成，禁止 fork 改源码** | 上游 nightly 迭代极快；不 vendor 其代码进 3.1，只在 3.1 协议层实现同构模式（模型工厂/MCP 消费/loop 语义），持续跟踪其 release 做协议对齐 |
| D3 | 能力边界：**3.1 协议层只做模型路由 + MCP 消费** | 能力执行、认知记忆、交易执行归现有架构；3.1 是唯一前端，不引入第二套 UI |
| D4 | **双轨治理**（v0.5.0 修正） | 3.1 协议层的 agent loop 仅作"执行器"，编排主权归 DreamOS；协议层侧产生的会话/辩论数据**不直写认知库**，Phase 3 蒸馏桥建成后经桥回流 |
| D5 | **执行+监督双链协作**（2026-11-11 用户确认） | 统一入口 → 双方意图规划 → Debate MCP 辩论 → 评估器裁决 → 胜者方案执行/败者后勤+门禁监督 → L0 统一沉淀 → 涌现回流。四条修正铁律见 §7.2 |

> **D1 澄清（v0.6.1，2026-11-11 用户裁定）**："唯一前端"指**只保留一套 UI（3.1 前端）**，不建第二个聊天界面；**不是删除协议层**。具体边界：
> - ❌ 删除：`src/app/agent/page.tsx`（独立第二 UI）
> - ✅ 保留：`src/lib/agent/{providers,mcp-client,distill-outbox,plancard}.ts`（模型路由 / MCP 消费 / 蒸馏写入 / PlanCard 契约）
> - ✅ 保留：`src/app/api/agent/{chat,plan}`（后端 API，非 UI，供 3.1 既有界面消费）
> - 背景：远端 `360e1f78dd`（云端提交）误读为"删除整个 3.1 agent 协议层"并回退 SPEC 至 v0.5.0（脑暴章节被删），**该提交作废，以本地为准**。

### 0.4 不做什么

| 禁止 | 原因 |
|---|---|
| **不部署任何独立 LobeHub 应用形态**（desktop/server/docker/Web 版） | v0.5.0 用户修正：唯一前端 = 3.1 前端；第二 UI = 双轨 |
| **不新建第二个聊天页面**（`/agent` 等独立 UI） | v0.6.1 用户裁定：协议层保留，UI 只有一个（3.1 既有界面） |
| **不删除协议层能力件**（providers/mcp-client/plan/chat/distill 写入器） | v0.6.1 用户裁定：这些是能力件非 UI，删除即误伤 |
| 不 fork / vendor lobehub 源码进 3.1 | D2：上游日更，分叉维护成本不可控；其包均 private 未发布，vendor 是唯一代码路径，已排除 |
| 不让 3.1 协议层直接读写 4-MEMORY / 认知库 | 认知写入仍走 L0 cognition 壳（worker 只读治理不变） |
| 不在 52/3.1 协议层内实现交易/策略/风控能力 | 能力供给归 DSH 各域 + L0 壳；协议层只做消费方 |
| 不把 3.1 协议层的 agent loop 替代 DreamOS NodeRegistry | 双轨风险：DreamOS 是主骨架，3.1 协议层是执行器 |
| 不将 LobeHub 的 expertise / userMemories 与我方认知库互写 | D4：其 agent 成长数据锁在其 PG；认知记忆唯一事实源是 35 协作模块 |
| 不采用集成路径 B（heterogeneous agent / lobehub-gateway 接入 DSH 为异构 agent） | R-D：与 MCP 路径互斥、复杂度更高，仅记录为备选 |
| 不将 LobeHub 会话存储与认知记忆混用 | 会话上下文归 LobeHub Postgres；认知记忆归 35 协作模块 |
| 首期不接入 live 交易链路 | 首验证只挂只读壳；交易壳挂载需独立评审 |
| 辩论/竞争永不进入 live 交易执行链 | D5：live 执行保持单决策链；辩论结果仅作信号输入，裁决与执行仍走 27 治理审批 |

---

## §1 在现有架构中的位置

```text
用户（唯一前端 = 3.1 前端 Web UI）
        │
┌───────▼─────────────────────────┐
│  3.1 前端内置 LLM 协议层（52 落点） │  模型路由（Vercel AI SDK，任意 LLM）
│  src/app/api/agent/*            │  + MCP client 桥 + PlanCard 执行语义
└───────┬─────────────────────────┘
        │ MCP 协议（唯一接口，stdio 本地 / sse 云端）
┌───────▼────────────────┐
│  L0 MCP 网关（47）       │  ← 现有壳零改造；mcp_capabilities.yaml 仍是唯一事实源
├────────────────────────┤
│  DSH 子域能力（46）      │
├────────────────────────┤
│  DreamOS/SACG（1）       │  意图识别 / NodeRegistry / 编排（主骨架不变）
├────────────────────────┤
│  REA + 做梦器（33/48）   │  反思/涌现经 cognition record 回流，协议层无感知
└────────────────────────┘
（LobeHub = 协议与设计参考，不作为应用存在；持续跟踪其 release 做协议对齐）
```

**关键边界：**

- 52 与现有架构之间**只有 MCP 一个接口**；不新增直连数据库、直连 Python 模块的旁路。
- L0 壳注册仍走 47 的 mcp_capabilities.yaml + drift 检查门禁；52 挂载任何新壳前必须先完成注册。
- LobeHub 看到的工具面 = 47 registry 按角色生成的 profile（只读优先，写工具需授权主体）。

---

## §2 集成契约

### 2.1 MCP 挂载契约（唯一对接面）

```text
LobeHub MCP 配置 ──▶ l0_gateway server（stdio）或远端 sse endpoint
```

- 复用 [mcpctl.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/47-MCP管理系统/registry/scripts/mcpctl.py) 生成 LobeHub 专用 profile（角色：`lobehub_frontend`，默认只读）。
- 新壳上线门禁不变：registry 登记 → drift 检查通过 → 方可被 52 挂载。
- **部署形态（v0.5.0 修正）**：本地开发 = 3.1 dev server 内经 stdio 直连 l0_gateway（复用 Phase 0 已验证的 `/tmp/lobehub_frontend_profile.json` 参数）；云端 = l0_gateway 包 SSE/HTTP 小服务（Phase 2 实施），3.1 协议层经 sse endpoint 接入。

### 2.2 模型路由契约

| 项 | 约定 |
|---|---|
| Provider 配置 | 全部在 3.1 前端服务端环境变量配置（.env.local / 云端 env）；仓内不存任何 API Key |
| 模型切换 | 换模型 = 改 provider 配置（AI SDK 工厂模式，同构 LobeHub RouterRuntime），不动现有架构任何代码 |
| 能力发现 | LLM 通过 MCP `tools/list` 发现 L0 能力；工具描述质量由 47 registry 保证 |

### 2.3 数据边界契约

| 数据类别 | 归属 | 52 的行为 |
|---|---|---|
| 会话/消息/agent 配置 | LobeHub Postgres | 自管理，不回写 |
| 认知记忆 | 4-MEMORY / cognitive_memory.db | 仅经 L0 cognition 壳访问，遵守只读/授权治理 |
| 交易数据/决策账本 | 各交易域 | 不经 52；首期不挂载交易壳 |
| 反思/涌现产物 | 33/48 | 由既有 hermes/cognition 通道回流，52 无感知 |

---

## §3 分阶段落地路线

### 3.0 落地状态总表（2026-11-11 全量核对）

| Phase | 状态 | 关键交付物 | 核对证据 |
|---|---|---|---|
| 0 PoC | ✅ 完成 | 三模型（kimi/sonnet/opus）经路由调通 recall | 2026-11-11 协议层验收 |
| 1 内置协议层 | ✅ 完成 | `src/lib/agent/{mcp-client,providers,plancard,plan-variant,distill-outbox}.ts` + `/api/agent/chat` | 5 个 vitest 文件 |
| 2 云端部署 | ⏸ 未开工 | l0_gateway SSE/HTTP；44 登记 52 拓扑 | 44-三端协作架构系统当前无 52 条目（grep 0 命中） |
| 3 蒸馏桥 | ✅ 建成 / ⚠ 未常态运行 | `bridge/distill_bridge.py`（19 tests，R6 映射 + 游标幂等） | outbox 89 条，`.cursor=1` → 88 条待消费；未接定时 |
| 4 脑暴编排器（shadow） | ✅ 完成 | `orchestrator/{brainstorm_orchestrator,proposers,plancard,registry_tools,debate_client}.py` | traces 70 条 / shadow 批次 40 条 |
| 4.5 补齐 | ✅ 完成 | `adjudicator.py`（grounded semantics A/B）、N-per-side、铁律⑤ fail-closed | test_adjudicator + test_brainstorm |
| 4.6 意图路由 + 入口 | ✅ 完成 | `router.py`（r9-v1 五分流）、`POST /api/agent/brainstorm`、ChatPanel「择优脑暴」开关 | test_router 16 例 |
| 5 45 域适配层 | ✅ 限量 | `domain_eval.py` + 结构分 + side-B 同量级扣分 | orchestrator 75 / bridge 19 / debate 壳 22 全绿 |
| 5.5 定时任务 | ⏸ 受阻 | `ops/com.dreambuddy.shadow.plist` 模板 + `shadow_batch.py` | macOS TCC：launchd bootstrap EIO、crontab operation not permitted；当前手动执行 |

> 说明：状态以**代码 + 可复跑测试 + 真实 trace** 三重证据为准，不以文档声明为准；`⏸` 项均已标注阻塞原因与替代入口。

### Phase 0 — PoC ✅ 已完成（2026-11-11，协议层验收）

1. ~~本地部署 LobeHub desktop~~（v0.5.0 弃用，已卸载）→ 改为**协议层直接验证**：registry 新增 `lobehub_frontend` 只读角色（verify 9 壳 0 漂移）+ mcpctl 生成 profile。
2. **A1 模型无关性实证**：kimi-k3 / claude-sonnet / claude-opus 三模型经同一 stdio 链路全部 PASS（initialize / recall 命中 52 认知 / 写门禁 record 被拒）。
3. 产物：commit 85e2bd7297（SPEC+REVIEW+registry）、fcf36548df（PlanCard schema）。

### Phase 1 — 3.1 前端内置协议层（v0.5.0 修订）✅ 已实施（2026-11-11）

1. 在 3.1-FRONTEND 新建 `src/app/api/agent/chat` 路由：**Vercel AI SDK**（依赖已存在）做模型路由（OpenAI/Anthropic/Google/Qwen 走 openai-compatible 工厂），**MCP client**（stdio 起 l0_gateway，参数复用 lobehub_frontend profile）桥接 L0 工具（首挂 recall）。
2. UI 侧复用 3.1 现有组件，不引入第二套前端；**不新建独立 `/agent` 聊天页**（v0.6.1）。
3. 验收：dream-acceptance-verify 五维 + 三模型（Trae 内 kimi/sonnet/opus 经路由）调通 recall 的 E2E。
4. 能力面扩展：unified_search 已完成（零代码同壳复用，commit e2af60ba2e，12/12 测试）。
   **⏸️ 18/19/41 数据域壳挂载暂缓（2026-11-11 用户决策）**：等待实际需求场景出现再做——它们是独立 server，需扩 registry 角色 + mcpctl 新 profile + 3.1 前端多 MCP 连接支持（当前单例 client），避免无消费方的能力面膨胀。届时按本 Phase 验收流程补齐。

### Phase 2 — 云端部署（v0.5.0 修订）

1. l0_gateway 包 SSE/HTTP 小服务上云（systemd），3.1 前端随既有部署链路走 dream-code-deploy-pipeline。
2. 三端协同更新：44-三端协作架构登记 52（3.1 协议层）拓扑与健康检查。
3. ~~LobeHub 独立服务部署~~（v0.5.0 弃用）。

### Phase 3 — 蒸馏桥（v0.5.0 修订）✅ 已实施（2026-11-11）

1. 建桥：3.1 协议层会话摘要/辩论 trace/PlanCard 回填产物 → 经 L0 cognition 壳（record，授权主体 orchestrator，仅放行 record/verify）→ 35 认知库。
2. 桥的写入仍遵守 worker 只读治理：桥本身不直连 cognitive_memory.db，只调壳。
3. 验收：桥数据可在 recall 中命中，且来源标签可溯（tags 含 protocol-bridge）。
4. **运行现状（2026-11-11 核对）**：桥代码 + 19 tests 已完成（R6 映射 canon≥B / 候选 C / 胜 B / 败 D，游标幂等）；入口为手动 CLI，未接定时。`bridge/outbox.jsonl` 89 条、`.cursor=1` → **88 条待消费**，即"桥已建成、回流未常态"。接入定时（与 Phase 5.5 同批）后再做"recall 可命中"的终验。

### Phase 4 — 脑暴编排器 + Debate 壳扩展（shadow 模式）✅ 已实施（2026-11-11）

**落点决议**（2026-11-11 用户确认）：编排器放 `52-lobehub协议集成/orchestrator/`（Python），不放 3.1、不改 DreamOS 源码（保 A3 零侵入）。理由：编排器含裁决/分派/门禁属主权件（D3/D4），依赖全在 Python 侧，shadow 期需常驻/定时。

**双链划分**：
- side-A：3.1 `/api/agent/plan`（3.1 模型链 + unified_search/recall 独立取证）
- side-B：DreamOS `/api/v1/intent`（chain 规划 + recall 取证）→ 经 `plancard.from_dreamos_intent` 转 PlanCard
- 编排列：收集 → 多样性校验（铁律⑤）→ gate(G1-G4) → score → recall 取证 → T1-T4 → 升级 Debate 或 shadow 记 dispatch 意图 → trace jsonl + 蒸馏桥 outbox

**交付**：
- `orchestrator/{brainstorm_orchestrator.py, plancard.py, registry_tools.py, scoring.py, proposers.py, debate_client.py, tests/}`
- 3.1 侧 `src/lib/agent/plancard.ts` + `src/app/api/agent/plan/route.ts`
- 桥 R6 新增 `brainstorm_winner→B` / `brainstorm_loser→D`
- `agent.debate.mcp` 壳新增可选 `model_pair`/`plancards`（同模型开题在壳层拒绝，铁律⑤契约强制）

**已知差距（Phase 5 前需补）**：
- 评估器目前为确定性启发式（`45.heuristic@1.0.0`）；45 域评测器输入为领域产物（EngineeringScan/回测统计等），PlanCard 无法直接喂入 → 需补"PlanCard→领域产物"适配层
- live 执行分支未实现（`--no-shadow` 抛 NotImplementedError），符合 Phase 5 门禁

**运行方式**：以手动 CLI / `shadow_batch.py` 批量触发为主。`ops/com.dreambuddy.shadow.plist` 模板已备（每日 22:30、`--max 5`），但 macOS TCC 拦截导致无法自动装载（`launchctl bootstrap` EIO、`crontab` operation not permitted），定时落地见 §3.0 的 Phase 5.5。shadow 2-4 周收集 trace 后评审激活。

### Phase 4.5 — 补齐项（2026-11-11 实施）

1. **N-per-side 发散 ✅**：双链各发散 N 张候选（默认 N=2，`--n-per-side` 可调 1-3），候选池按 card_id 去重后逐张 gate+score；Top1 → winner、其余 → loser 入蒸馏桥。详见 §7.7.1。
2. **grounded semantics shadow A/B ✅**：新增 `orchestrator/adjudicator.py`（标准库 ≤220 行）：论点=card/step 两级，攻击边 R-a/R-b/R-c 全确定性，标准最小不动点求解 IN/OUT/UNDEC；与启发式打分并行写入 trace `adjudication`，**不改变 shadow 决策**（仍取启发式 Top1）。
3. **铁律⑤ 加固 ✅**：`validate_diversity` fail-closed——model 空/unknown/none/null、跨侧同 model、跨侧 evidence_path 相同或为空一律拒绝；拒绝时仍写 trace 但不写 outbox、不升级 Debate，CLI 摘要标注原因；SideB model 可由 `SIDE_B_MODEL` 配置，trace 新增 `model_kind`（llm / deterministic_planner）。
4. **45 域评测器适配层 ✅ v0.9.0 已接入（限量，见 Phase 5）**：45 evaluator 输入为领域产物（EngineeringScan/回测统计等），规划期 PlanCard 无产物 → 适配器只做契约接入与 provenance，一律 `INCONCLUSIVE`，不编造 PASS/BLOCK。

**Phase 4.5 交付**：`adjudicator.py`、`tests/test_adjudicator.py`；`proposers.py`/`plancard.py`/`scoring.py`/`brainstorm_orchestrator.py` 增量；3.1 侧 `src/lib/agent/plan-variant.ts` + `/api/agent/plan` variant 支持。

### Phase 4.6 — 意图路由与用户入口（2026-11-11 实施）

1. **router.py 五分流 ✅**：`orchestrator/router.py`（纯确定性、零 token、零三方依赖），规则版本 `ROUTE_RULES_VERSION = "r9-v1"` 随每条 trace 落盘。`route(intent, risk_flags=None, intent_type=None)` 严格按序返回 `trade_deny / high_risk_human / debate / direct_answer / workers`；DreamOS 六类意图映射：`TREND_FOLLOWING/MEAN_REVERSION/FUNDAMENTAL_PLAY/BREAKOUT → trade_deny`、`KNOWLEDGE_MATCH → direct_answer`、`UNCERTAIN` 回退关键词；`reason` 标注来源 `dreamos_intent` / `keyword` / `risk_flags`。
2. **编排器接路由 ✅**：`run(..., route_hint=None, force=False)` 在候选池生成**之前**分流；`force=False` 且 route ∉ {debate, workers} 时只写 trace 后返回 `{skipped:true, route, reason}`（不生成候选、不调 Debate、不写 outbox）。`workers` = 单边语义（side-B DreamOS 规划 + side-A 一次，`n_per_side` 强制 1），T1-T4 只记录不升级，trace 标 `mode:"workers"`；`debate` 保持双链 + N-per-side + T1-T4 不变。CLI 新增 `--force`（人工指定跳过路由）与 `--json-out`（stdout 单行 JSON 摘要：`route/skipped/winner/trace_id/outbox_written/diversity_violations/adjudication/mode`）；trace 新增 `route` / `route_rules_version` / `mode`。
3. **3.1 用户入口 ✅**：新增 `POST /api/agent/brainstorm`（intent 非空且 ≤2000 字；`spawn` 调编排器 CLI，`ORCHESTRATOR_PY` 可覆盖 python 路径，180s 超时 kill；成功解析 stdout 末行 JSON，失败/非 JSON/超时一律 200 degraded 信封，GET 405）；前端入口落在既有 `ChatPanel` 输入区（"择优脑暴"开关，不新建页面、不改路由结构），结果以助手消息展示 route 中文名 / skipped+reason / winner+score / 蒸馏写入数，`trade_deny` 与 `high_risk_human` 显式提示"已拦截"。
4. **尚缺项**：真实 shadow 数据（Phase 5 激活前仍需 2-4 周 trace 积累）；45 域评测器适配层已于 v0.9.0 接入（契约可用、产物缺 → `INCONCLUSIVE`）。`--force` 仅供人工观察全链路，不得作为线上默认。

### Phase 5 — 竞争模式激活（非交易任务）

> **状态：已实施（限量）** — 评测器契约接入 + 结构分上线；真实产物评测待产物落盘接入。

1. 对研究/分析/工程类任务激活"脑暴-裁决-分工"全链路（争议时升级 Debate）。
2. 交易域：脑暴/辩论结果仅作信号输入，裁决与执行仍走 27 治理审批（§0.4 硬约束）。
3. 激活门槛：评估分差分布、T1-T4 触发率、翻盘率、败方负样本蒸馏价值达标（Phase 4 shadow 数据支撑）。

**Phase 5 实施（v0.9.0，2026-11-11）**

1. **45 评测器适配层 ✅**：新增 `orchestrator/domain_eval.py`。
   - `discover()`：临时隔离导入 `45-评测系统`（不改 45 源码、不污染宿主同名包），调 `evaluators.registry.load_defaults()`；任何异常 fail-open 返回 `{available: False, error}`，绝不抛。
   - `DOMAIN_MAP`：`engineering→engineering-scan`、`finance→finance-backtest-stats`、`ai→ai-stress`；域判定顺序 = `plan_steps[].tool` 前缀（`backtest.*→finance`、`scan.*/tests.*→engineering`、`stress.*→ai`）→ 意图关键词 → 默认 engineering。
   - `evaluate_plan()`：45 不可用 → `INCONCLUSIVE/45_unavailable`；评测器未注册 → `INCONCLUSIVE/evaluator_not_found`；缺 `45-评测系统/artifacts/inputs/{run_id}.json` → `INCONCLUSIVE/missing_artifacts`；产物存在但领域对象映射未接 → `INCONCLUSIVE/artifact_not_evaluated`。**缺产物时严禁 PASS/BLOCK**。
2. **结构分替代退化常数 ✅**：`structural_score()` 确定性 0-1（3 位小数），权重：tool 合法率 0.25 / 步骤数 0.15 / validation 0.20 / evidence_refs 0.20 / risk_flags 0.20（`max(0.4, 1-0.15n)`）/ cost_estimate 0.10；权重和 1.10，按总权重归一化避免满分饱和。明细 `{name, raw, weight, contribution}` 全量入 trace。
3. **scoring 接入 ✅**：`score()` = 结构分基线叠加域结果（BLOCK→0 且排除候选池；PASS→`min(1, base+0.05)`；INCONCLUSIVE→仅 base）。每条 scored 新增 `evaluator_provenance {source: structural|45, evaluator, verdict, reason, structural_detail}`；45 不可用时 `source=structural` 且不抛。
4. **trace / 摘要 ✅**：trace 每条新增 `domain_eval {available, names, verdicts}`；`--json-out` 新增 `evaluators {available, names:int}`。
5. **候选池同侧去重 ✅**：side-B 多个 variant 在 `extend_nodes` 为空时内容完全相同，保留会使 Top1/Top2 恒同分（gap 恒 0、T1 恒命中）。`dedupe_pool` 增加同侧结构指纹去重（跨侧不合并，保留争议检测）。
6. **真实复跑（2026-11-11）✅**：`pool=3`、`evaluators.available=true/names=7`、`evaluator_provenance.verdict=INCONCLUSIVE/missing_artifacts`（未编造分数）。结构分替代退化常数后 gap 不再恒 0：`--n-per-side 1` 复跑 gap `0.109 > 0.1` → 5 轮 `dispatch`、`outbox_written=2`。
7. **已知局限 / 后续接入时机**：
   - 规划期无领域产物，真实评测器**一律不执行**，`verdict` 恒 `INCONCLUSIVE`；`source=45` 仅代表契约可用，不代表已评测。
   - 真实产物评测需上游先把 `artifacts/inputs/{run_id}.json` 映射为 45 领域对象（EngineeringScan/BacktestStats/StressPlan）；接入时机 = shadow trace 累计 2-4 周且产物落盘格式冻结后，届时仅替换 `evaluate_plan()` 的 `artifact_not_evaluated` 分支。
   - T1 阈值（0.1）暂不下调：side-B 分不对称已由第 8 条修复，阈值调整需更多 trace 支撑。
8. **side-B 同量级结构扣分 ✅（v0.10.0）**：side-B 由确定性意图引擎生成，原卡 `risk_flags` 为空、evidence 仅 `dreamos.*` 自证 → 结构分恒 `1.0`，与 A 侧 0.89–0.92 不可比（Top1 恒为 B，T1 gap 恒 0.082 → 假争议）。
   - `_enrich_side_b_card()`：注入 3 条真实局限 risk（`deterministic_planner_no_independent_evidence` / `registry_mapping_unvalidated` / `single_intent_call_no_variant_diversity`），已有人工 risk 时不覆盖。
   - `_evidence_raw()`：`dreamos.*` 自证引用不计入独立取证，仅 `recall:` / `unified_search:` 等外部取证计分。
   - 实测：B 由 `1.0` 降至 `0.736`；Top2 回归**同侧 A vs A**（gap 0.027），T1 仅在真实变体分歧时触发。扣分依据是可证伪的规划器局限，未来 B 侧接入独立取证/多 intent 后分数自动回升，无需改代码。

---

## §4 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 上游日更导致协议漂移 | 低 | v0.5.0：不消费其代码/应用，仅跟踪 release 做协议语义对齐（月节奏） |
| 双轨：3.1 协议层 loop vs DreamOS 编排 | 高 | D3+D4 边界硬约束；能力实现零迁入；SPEC 评审时逐条核对 |
| 协议层会话/成长数据与认知库分叉 | 高 | D4：不直写；Phase 3 蒸馏桥统一回流；此前协议层数据视为易失 |
| 功能面膨胀诱导越界（协议层长出 task/goal 等编排侵蚀 D3） | 中 | §0.4 禁止清单 + 评审时重申"只做模型路由与 MCP 消费" |
| proactive 旁路（定时/自动动作绕过 MCP） | 中 | A6 验收硬门禁；3.1 侧任何自动化动作只允许调 MCP 工具 |
| 辩论裁判漂移递归（LLM 裁 LLM） | 高 | D5 修正铁律①：裁判必须是评估器（45评测+acceptance证据+回测），LLM 仅有限仲裁 |
| 竞争成本翻倍（双份规划 token） | 中 | 竞争仅对高价值任务开启（意图路由分流）；shadow 期先量化成本收益 |
| 败方监督能力错配 | 中 | D5 修正铁律③：监督交确定性门禁，败方只做后勤 |
| 数据双写/记忆混乱 | 高 | §2.3 数据边界契约；认知写入只走 L0 壳 |
| ~~引入第二运维栈~~ | ✅ 已消除 | v0.5.0：无独立应用，3.1 同栈（Next/Prisma 现有依赖） |
| stdio 云端不可用（无头服务器） | 低 | Phase 2：l0_gateway 包 SSE/HTTP 小服务 |
| MCP 工具面膨胀失控 | 低 | 47 registry 唯一事实源 + drift CI 门禁（现有机制复用） |

---

## §5 验收标准（Phase 0 出口条件）

| # | 验收项 | 判据 |
|---|---|---|
| A1 | 模型无关性 | 同一 L0 工具，3 家模型调用均成功返回正确结果 |
| A2 | 协议唯一性 | LobeHub 与现有架构之间除 MCP 外无任何直连（代码审查） |
| A3 | 零侵入 | 现有架构代码改动行数 = 0（仅 47 registry 新增 profile 配置） |
| A4 | 治理合规 | 挂载壳全部来自 mcp_capabilities.yaml，drift 检查通过 |
| A5 | 可回滚 | 停掉 LobeHub 容器后，现有系统功能无任何退化 |
| A6 | proactive 无旁路（R-F 新增） | LobeHub 内 schedule/heartbeat 自动化任务产生的全部动作均经 MCP 工具面，无直连 DB/API |

---

## §6 评审决议（R1-R9 全部闭环，2026-11-11）

| # | 议题 | 决议 |
|---|---|---|
| R1 | Phase 0 首挂壳 | ✅ **cognition（recall）**。理由：只读零风险、无外部依赖、直接展示"记忆检索"差异化能力；unified_search 次之（Phase 1 第二个挂）；41 文件索引不做首批（价值密度低） |
| R2 | LobeHub acceptance 引入与否 | ✅ **不引入为依赖**。其思路（可观测 check + 证据包）与 dream-acceptance-verify 同构，我方工具链已覆盖；Phase 1 验收统一用 dream-acceptance-verify 五维。52 层自身 agent 行为验收若未来需要再单独立项 |
| R3 | 写工具白名单与授权主体 | ✅ 三级开放：①`lobehub_frontend` 角色**恒只读**（drift 检查强制）；②蒸馏桥进程 = `orchestrator` 主体**仅放行 cognition.record/verify 两工具**（Phase 3）；③debate 壳 = `orchestrator` 主体（Phase 4）。**trade-exec 及一切交易写工具永不对 52 开放**。白名单落在 mcp_capabilities.yaml，registry CI 校验 |
| R4 | 云端 Postgres | ✅ **独立 database、共享 PG 服务器**：LobeHub 用独立 db（lobehub_prod），不与我方任何库互连；物理上复用云端现有 PG 实例省资源；备份纳入 38-数据库管理体系巡检。其 drizzle migration 只许动自己的 db |
| R5 | Debate 评估器指标集 | ✅ 直接复用 45 评测 registry（(name,version) 唯一、lock() 钉版）：工程类→engineering/{scan,tests}；交易信号类→finance/backtest；稳健性→ai/stress；通用→common/{e3,split}。verdict 映射其 PASS/BLOCK/INCONCLUSIVE 三态；hard item 任一失败即判负（BLOCK），INCONCLUSIVE 触发弃权政策（双方方案均不执行，转人工或重辩） |
| R6 | 蒸馏桥 schema | ✅ 见 §7.4 修订（quality 映射 + 必填字段） |
| R7 | 论证学裁决器 A/B | ✅ Phase 4 shadow 双裁决器并行：同一 trace 分别过评估器裁决与 grounded semantics 求解器（自研最小实现 ~200 行，不引外部依赖，论点=claims、攻击=反驳边）。转 active 条件：与评估器一致率 ≥90% 且人工抽检可解释性更优；否则保持评估器裁决 |
| R8 | PlanCard schema | ✅ 见 §7.5（新增） |
| R9 | 意图路由分流规则 | ✅ 见 §7.6（新增） |

---

## §7 双链协作架构（D5，2026-11-11 用户确认）

### 7.1 统一闭环

```text
用户意图（统一入口：3.1 前端）
      │
  意图规划 ×2 ───────────────────────────┐
  ├─ DreamOS 侧（NodeRegistry/SACG）      │
  └─ 3.1 协议层侧（Vercel AI SDK loop，    │
     同构 LobeHub agent-runtime 语义）     │
      ▼                                   │
  Debate MCP（复用现有 agent.debate.mcp 壳：start_debate/get_debate_result）
      ▼
  评估器裁决（45 评测 + acceptance 证据 + 回测，非 LLM）
      ▼
  分工：胜出方案 → DreamOS 执行（唯一执行体）
        败方 → 后勤（数据/上下文组装）
        监督 = 确定性门禁（13 风控 / 27 审批 / drift 检查）
      ▼
  统一沉淀 L0：①能力壳入 47 registry
               ②认知经验经蒸馏桥入 35 认知库（含败方方案——负样本蒸馏价值）
      ▼
  涌现回流（48/REA）：意图涌现 → 意图识别与预测；工程涌现 → 逆向沉淀最优方法
```

### 7.2 四条修正铁律（对用户原始设想的工程修正）

| # | 铁律 | 原因 |
|---|---|---|
| ① | **裁判必须是评估器，不是第三个 LLM** | LLM 裁 LLM 只是漂移上移；裁决依据 = 45 评测指标 + acceptance 可观测证据 + 回测数据，LLM 仅在评估器无法判定时有限仲裁 |
| ② | **竞争限定在规划层，不到执行层** | 能力天然不对称：执行工具只在 DreamOS 侧，渠道只在 LobeHub 侧；"谁赢谁执行"只对双方都能做的"思考/方案"成立 |
| ③ | **监督交确定性门禁，败方只做后勤** | 次优执行者≠好监督者；监军靠军法（13/27/drift 门禁，不会漂移），败方承担渠道/数据/上下文后勤 |
| ④ | **live 交易执行链永不进竞争模式** | 实盘保持单决策链；辩论结果仅作信号输入，裁决执行走 27 治理审批（§0.4 已列禁令） |

### 7.2.1 成熟实践对标补充（v0.3.1，GPT/Claude 生态调研）

| 补充铁律 | 依据 |
|---|---|
| ⑤ **辩论多样性契约化**：双方禁止同模型配置；证据路径差异化（DreamOS 侧走 L0 数据壳，3.1 协议层侧经 web 检索/独立数据源取证）；裁决三态含 INCONCLUSIVE（对齐 45 评测契约）。**Phase 4.5 加固**：`model` 为空/`unknown`/`none`/`null` 一律拒绝开题（fail-closed）；跨侧同 model、evidence_path 相同或为空同样拒绝；trace 标注 `model_kind`（`llm` / `deterministic_planner`），区分"真模型多样性"与"架构异质性" | arXiv《More Debate, Same Evidence》：同模型+同证据池的辩论错误强相关，加轮次/改 persona 无效，增益只来自模型/证据多样性 + 弃权政策 |
| ⑥ **任务类型分流**：探索性复杂任务 → 单边规划 + orchestrator-workers；方案择优任务 → 才进 Debate | Anthropic Building Effective Agents：orchestrator-workers 适合子任务不可预测场景；辩论研究实证收益仅 1-3pp 且成本高 |
| ⑦ **结构化产物交接**：胜负方案以 PlanCard schema（非自然语言）交执行方；蒸馏桥产物同 schema | Anthropic harness 长时任务教训：structured artifacts 是跨会话/跨系统交接唯一可靠方式 |

### 7.3 Debate MCP 壳契约草案（Phase 4 实施基线）

```text
debate.open(topic, context_refs, rounds=N) -> debate_id        # 开题（双方各持正反）
debate.argue(debate_id, side, content, evidence_refs) -> ok    # 分轮提交论据（可引用 L0 工具证据）
debate.trace(debate_id) -> {rounds, claims, evidence}          # 全程 trace（只读）
debate.adjudicate(debate_id, evaluator_refs) -> verdict        # 评估器裁决（调用 45 评测/acceptance）
                                                               # verdict ∈ {WIN_A, WIN_B, INCONCLUSIVE}（铁律⑤对齐 45 三态）
```

- 壳类型：**写壳**（产生 debate 状态），需 registry 登记 + 授权主体，drift 门禁同其他壳。
- 裁决器 `evaluator_refs` 只允许指向确定性评估资源（评测任务/验收用例/回测句柄），不允许 LLM endpoint——铁律①在契约层强制。
- `debate.open` 增加 `model_pair` 字段声明双方模型配置，壳层拒绝同模型开题（铁律⑤契约层强制）。
- trace 落盘格式复用 50 域 decisions.jsonl 范式（jsonl append-only），供 shadow 期分析与蒸馏桥消费。
- **可选升级（R7）**：Phase 4 shadow 期并行实现计算论证学裁决器（论点攻击图 + grounded semantics），与评估器裁决 A/B 对比可解释性与一致性，优者转 active（依据：《A Theory of Post-hoc Debate Judgement》）。

### 7.4 蒸馏桥契约（Phase 3 实施基线，R6 已决议）

- 数据源：LobeHub 侧 expertise 条目、辩论 trace（胜负双方案+裁决证据）、高价值会话摘要。
- 通道：桥进程 → L0 cognition 壳 `record`（授权主体 `orchestrator`，仅放行 record/verify 两工具，R3）→ 35 认知库；桥自身无任何 DB 直连。
- **quality 映射（R6）**：

| 来源类型 | quality_level | 说明 |
|---|---|---|
| expertise canon 条目（其侧已固化） | B | 进入后走我方 verify 升级链 |
| expertise 候选/insight（未固化） | C | 假设级，待验证 |
| 辩论胜方方案 | B | 附 PlanCard + verdict 证据链接 |
| 辩论败方方案 | D | 反模式，附裁决证据（负样本价值） |
| 会话摘要 | C | 仅高价值会话（人工/规则筛选） |

- 必填字段：`content`（≤300字精炼）、`tags`（必含 `protocol-bridge` + 来源域 + 类型）、`source_ref`（3.1 协议层侧可追溯 ID/trace 链接）、`bridge_ts`。
- 回流验证：桥数据可被 recall 命中、可被 verify 升级，与本地经验同权参与贝叶斯蒸馏。

### 7.5 PlanCard schema（R8 已决议，铁律⑦落地）

辩论胜负方案交接与蒸馏桥产物共用的结构化载体（JSON，存 52/schemas/plancard.schema.json）：

```json
{
  "id": "pc-<ulid>",
  "intent": "用户意图原文摘要",
  "context_refs": ["L0 工具证据引用"],
  "plan_steps": [{"step": 1, "action": "...", "tool": "l0.<shell>.<tool>", "args_hint": {}}],
  "evidence_refs": ["debate trace / recall id / backtest id"],
  "risk_flags": ["触及的禁令/风控域"],
  "cost_estimate": {"tokens": 0, "tool_calls": 0},
  "expected_outcome": "可验证的结果描述",
  "validation": {"evaluator_refs": ["45.<name>@<version>"], "acceptance_checks": ["..."]},
  "debate_meta": {"debate_id": "...", "side": "A|B", "verdict": "WIN|LOSE|INCONCLUSIVE"}
}
```

- 硬约束：`plan_steps[].tool` 只允许引用 47 registry 已注册工具（执行前校验，未注册即拒绝）——D2/治理在 schema 层强制。
- 执行方（DreamOS）按 PlanCard 逐步执行并把实际结果回填 `validation.outcome`，回填产物回流蒸馏桥。

### 7.6 意图路由分流规则（R9 已决议，铁律⑥落地）

统一入口（LobeHub 渠道）→ DreamOS 意图识别（现有 6 类零 token 分类）→ 路由：

| 任务类型 | 判定特征 | 路由 |
|---|---|---|
| 方案择优类 | 有可判定优劣的客观标准（策略参数/架构选型/研究结论对比） | **Debate 双链**（§7.1 全链路） |
| 探索性复杂类 | 子任务不可预测（多文件改动/开放调研） | 单边规划 + orchestrator-workers（不进 Debate） |
| 查询/检索类 | 事实性、单步可答 | 直答（不进辩论、不双规划，省 token） |
| 交易执行类 | 任何 live/paper 下单相关 | **永不进 Debate**；信号走 27 治理审批（铁律④） |
| 高风险类 | risk_flags 命中 13 风控域 | 强制人工审批节点，无论类型 |

- 路由规则版本化（存 47 registry 同仓），变更需评审；初期按上表保守分流，shadow 数据驱动调优。
- **已实现（Phase 4.6）：`orchestrator/router.py`，版本 `r9-v1`**；交易/高风险分支在候选池生成前拦截，workers 单边不升级 Debate。

### 7.7 发散与收敛执行基线（Phase 4.5）

#### 7.7.1 N-per-side 候选发散

- **实现默认 N=2，池内 ≤2N 张**；`--n-per-side` 可调 **1-3**，越界 CLI 直接报错退出（退出码 2）。
- side-A：对 3.1 `/api/agent/plan` 调用 N 次，body 携带 `variant: {focus, seed}`，focus 轮转 `risk-first` / `cost-first` / `speed-first`；任一调用失败仅记 error，不整体失败。
- side-B：只调 DreamOS `/api/v1/intent` 一次；variant 0 = 完整链（base_chain + extend_nodes），variant 1 = 仅 base_chain（为空则取 extend_nodes 子集），variant ≥2 = 反转 extend_nodes 顺序；每张卡 `card_id` 唯一，`selection_basis` 记录变体依据。
- 候选池按 `card_id` 去重，池内每张各自 gate(G1-G4) + score；Top1 → `brainstorm_winner`（B），其余全部 → `brainstorm_loser`（D）。
- trace 新增 `n_per_side` / `pool_size`；T1 语义不变：Top1 与 Top2 分差 < 0.1 触发升级 Debate。
- grounded 裁决与启发式并行写入 trace `adjudication`（`heuristic_top` / `grounded_winner` / `agree`），**不参与决策**；`--adjudicator heuristic|grounded|both`（默认 both）。

