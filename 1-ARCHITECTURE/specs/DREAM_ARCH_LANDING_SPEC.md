# DREAM 架构落地 SPEC — 元 SKILL · C-Drive 驱动 · 模型无关接入

> **版本**：v0.8.12（P0/P1/P2/P3 批次 0-24 已交付；P4 批次 1-2 已交付；T-D0 核实已交付；B1-B3 DSH 桥云端通路已交付；C 端剩余流式组件审计已交付；遗留项 #3/#4 已交付；遗留项 #1/#2 已交付；遗留项 #5 已交付；#5 遗留补齐（真实余额 + 侧栏徽标）已交付；#5 剩余边界清零已交付；技术文档落地核对已通过；GAP-2 trace_id 全链透传 + 两处流式/生命周期边界已交付；链路 C 本地活体验证通过并修复 3 处契约断点）
> **日期**：2026-11-12
> **命名说明**：`DREAM` **只是本 SPEC 的文档代号**，不是架构层、不是新框架。架构分层唯一为 **SACG**（v4.2 SSoT）。
> **定位**：把「架构驱动大模型开发」落成可执行契约：元 SKILL 作唯一入口，C-Drive 作唯一驱动层，SPEC A-C 作第一批手把手验证负载。
> **口径基准**：[SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2。
> **硬约束**：所有外部机制的采纳必须映射到 SACG 现有四层，**不新增层、不引入外部框架作为运行时底座**；外部只借机制，不借框架。
> **复用硬约束**：需补齐的功能先查 SPEC A-C → 现有 SKILL → L0 壳，**禁止重复造基础设施**；允许预先补齐，但只补最小集，其余工作中缺失再补。

---

## 0. 文档关系（口径冲突处置）

| 既有文档 | 关系 | 处置 |
|---|---|---|
| [SYSTEM_ARCHITECTURE_OVERVIEW.md](../SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2 | 唯一事实源 | 层名、职责全部以它为准 |
| [DREAMOS_SKILL_ORCHESTRATION_SPEC.md](./DREAMOS_SKILL_ORCHESTRATION_SPEC.md) v0.2 | 交易域「节点 → SKILL 选择编排」 | 不重复；本文解决**工程开发流程**的驱动与验收 |
| [SACG_A_SUPERAGENT_CONNECTION_SPEC.md](./SACG_A_SUPERAGENT_CONNECTION_SPEC.md) | Router = C-drive 调度语义 + S 层入口；Watchdog = 反思器外化（P2） | 本文沿用该映射，不另立角色 |
| [.trae/skills/dreambuddy-os/SKILL.md](../../.trae/skills/dreambuddy-os/SKILL.md) v1.1 | 旧 SACG（Sense/Arrange/Compute/Graph）+ 指向已归档 `dreamos/` | **标 deprecated**，由元 SKILL 收编 |
| [46-DSH架构/README.md](../../46-DSH架构/README.md) | G0 契约仍标「阻塞待原型」 | 本文以 🟡 标注，不写「已落地」 |

**硬约束**：旧 SACG 四层（S=Sense / A=Arrange / C=Compute / G=Graph）已作废（SSoT §1.2 原文）。新文档、SKILL、注释一律使用 v4.2 口径。

---

## 1. 用户补充与验证结论

### 1.1 输入

1. **驱动层是 C-Drive**，其余定位基本准确。
2. **SPEC A-C 是在增强本构想的基础设施**。
3. 灰度未接线部分**本次开发全部打通、手把手验证**；**后续没有大模型禁止开发**（短期不配置多模型，先手把手打磨）。
4. 「双架构」描述不准：实为 **lobehub 协议接入中的双 AGENT 思维路径**（脑暴阶段两条推理路径）。
5. `DREAM` 仅为 SPEC 名封装，**架构只有 SACG**；缺什么就调研补齐，但硬约束必须按现有架构推进。

### 1.2 验证

#### V1 驱动层 = C-Drive —— **成立，且驱动层已存在代码实现**（v0.1 结论需修正）

v0.1 曾判断「C-Drive 只有文档语义」。本轮代码核查推翻了该判断：

| 事实 | 证据 |
|---|---|
| C-Drive 五动作决策已实现 | [c_drive_agent.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py) `CDriveAgent`；动作 `continue/redo/jump/supplement/debate` |
| 四步循环 | recall → reflect → jeval → supplement/debate |
| 前端协调器 + 人工介入 | [c-drive.ts](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/lib/c-drive.ts#L1-L28)、[SteerPanel.tsx](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/3.1-FRONTEND/src/components/features/chat/SteerPanel.tsx#L9) |
| 分级 effort + FAIL-OPEN | `effort_level: light/standard/deep`；IPC 失败回 `continue` |
| 角色映射 | Router = C-drive 调度语义 + S 层入口；Watchdog = 反思器外化（P2 未做） |

结论：**驱动层不需要从零建设，缺的是「工程开发域的语义与状态」**——现有 `node_id / direction / signals` 全部是交易语义（LONG/SHORT、EMA 等），没有开发节点、没有 run/phase/model 绑定、没有可判定门禁。缺口清单见 §4。

#### V2 SPEC A-C 是基础设施增强 —— 成立，缺两块地基

| SPEC | 对应层 | 增强内容 | 缺口 |
|---|---|---|---|
| A 唯一壳与流治理 | C 层执行面 | 连接与组件解耦、导航单一事实源、REST 单一入口、构建门禁 | 无阶段状态机，流事件无法回放为开发证据 |
| B 交互内核 | 人机通道 | part 渲染、工具四态、PlanCard、会话持久化 | PlanCard 只是展示，未成为 C-Drive 的计划载体 |
| C 契约治理 | C-Drive 观测前提 | 统一信封、错误码、SSE v1、鉴权、边界门禁 | 缺 `run_id/model_id/phase` 三元组，无法证明「有模型参与」 |

#### V3 灰度接线 + 手把手验证 + 无模型禁止开发 —— 可执行，需三条护栏

1. **灰度清单化**：默认开关 + 回滚动作 + 观测指标，未登记不接线。
2. **绑定门禁 G0**：缺 `run_id/model_id/phase` 即拒开工（0 例外）。
3. **FAIL-OPEN 例外**：灰度接线失败只降级，不阻塞 A-C 主链。

#### V4 「双架构」更正 —— 实为双 AGENT 思维路径，且须降级定位

证据：`52-lobehub协议集成/orchestrator/`（`proposers.py`/`adjudicator.py`/`scoring.py`/`router.py`/`live_policy.py`，95 tests，ADR-001 灰度每周 1 次）。

**外部实证警示**：同质多 Agent 辩论的效果区间为 **+8.5 ~ −4.4pp**，谄媚趋同率 85.5%，共识崩塌时 oracle gap 32.3pp（arXiv 2605.00914 / 2608.00243）。因此双路径**只能做候选生成，不能做裁决**；裁决必须交给 A 层门禁或人工。这与灰度策略一致，本文据此固化。

---

## 2. 现状蓝图（只有 SACG）

```
┌──────────────────────────────────────────────────────────────────────┐
│ S 认知规划   recall 先验 + REA 结构事实 + 开工 SKILL → Spec/Plan       │
│              ▲                                                        │
│              │ 选路/预算/jeval                                         │
│ A 验收       ◄──── C-Drive（调度语义 ⇄ 反思器语义）────►  C 执行       │
│  OKR 节点 + 48 度量(verdict)        五动作决策                子 Agent  │
│              │                       continue/redo/jump/       + 执行器 │
│              │                       supplement/debate                  │
│              ▼                                                        │
│ G 压缩沉淀   四分流 + 图压缩 + 收尾 SKILL + 轨迹蒸馏                    │
└──────────────────────────────────────────────────────────────────────┘
```

| 组件 | 声明 | 实测（2026-11-12） | 本轮处置 |
|---|---|---|---|
| C-Drive 调度/反思 | 🟢 | 代码已实现，交易语义 | 补 DEV 节点族与开发信号（§4 GAP-1） |
| C-Drive 运行状态 | 🔴 | 无 run/phase/model 绑定 | 新增 run schema + G0（§5） |
| DSH 子 Agent | 🟢 已落地 | 8 个 subagent 四层齐全并有测试：契约 `subagent_types.py`（`SubagentOutput` v0.3）→ 注册 `subagent_registry.py`（`SUBAGENT_REGISTRY_CONFIG` 8 条）→ 执行 8 个 `*_agent.py` 的 `handle_*_agent` → 接线 `dsh_frontend_bridge.IN_PROCESS_HANDLERS` 8 个 `subagent.*` + `HANDLER_TO_SHELL_ID` 8 条 + 前端 `dsh_adapter.py` 调 `call_handler`；83 例测试通过。46 的「DSH 无 subagent」是 2026-09-24 基线自述，已被实现取代 | 作为 C 层**交易域只读研究执行者**接入（role=research）；不作开发域执行者、不支持 Thread 多轮续跑 |
| 48 涌现度量 | 🟡 研究态 | E1-E3 种子未验证、E4 部分、E5 无度量；verdict 分布 5 candidate / 1 e3_candidate / 1 candidate_weak / 1 falsified / 1 inconclusive / 1 insufficient_data | 只作验收度量层 |
| 脑暴双路径 | 🟡 灰度 | 95 tests，每周 1 次 | S 层候选生成器，默认关 |
| L0 出口 | 🟢 | 10 壳 + 5 worker 角色（engineer 仅 10 工具，无 adapt_plan） | 模型无关的稳定调用面 |
| python-server / DSH 桥 | 🟢 双通路 | 本地 IPC：前端 spawn `dsh_adapter.py` → `call_handler` → `InProcessShell`；云端 HTTP：`execute_http_server.py` 的 `/execute`（复用同一 dispatcher、回显 `trace_id`、零新依赖、Bearer 鉴权、`/health` 探活）；`orchestrator` 支持 async 提交 + `orchestrator.status` 轮询；两条路都不再写死本机解释器路径 | 详见 §11.34（部署口径） |
| SPEC A-C | 🔴 未开工 | 文档齐备 | 本次验证负载 |

---

## 3. 外部调研：传统工程 + AI 工程实践（2026-11 检索）

### 3.1 传统软件工程：成熟点是「可判定的门禁」

- Stage-Gate 的判定标准是 **exit criteria + readiness evidence**，不是「活动已完成」（Umbrex Stage-Gate Playbook）。
- 门禁要真正阻塞，必须把 CI job 写进 branch protection / rulesets 的 **required status checks**；只跑 Action 不设 required check 等于建议性门禁（GitHub Rulesets GA）。
- 产物契约已可机器执行：Kiro 的 requirements/design/tasks 三文件 + EARS 句式（WHEN…THE SYSTEM SHALL…）使需求直接可测（kiro.dev）。
- ADR/RFC 把「决策+理由+后果」独立成档，可版本化并被 recall 复用（adr.github.io）。

### 3.2 Agentic 工程实践：spec 前置 + 每步验证

- **Spec Kit**：`/specify → /plan → /tasks → /implement`，产物落 `specs/`，官方支持 11+ agent——本身就是「换模型能开工」的样板（speckit.org）。
- **Kiro**：任务按序执行，**步骤之间插验证**（kiro.dev CLI specs）。
- **OpenHands 三层验证栈**：agent 级 critic → repo 级 review → QA 真跑 → `/iterate` 循环；实测 MTTR −58%、覆盖率 +25%（openhands.dev）。
- **Aider**：repo map（tree-sitter + PageRank）按 token 预算选上下文，**测试通过才自动 commit**，形成原子提交链。
- **实证警示**：SDD 用户报告 2–3× token、2× 时间；spec decay 普遍，含实现细节（类名/版本）的 spec 衰减更快（75% 样本，arXiv 2608.25202）。

### 3.3 模型无关标准：哪些能做底座

- **MCP**：事实标准，2025-12 捐入 Linux Foundation，2026-07 RC 走向无状态核心 + Tasks 扩展。
- **A2A**：Agent 横向协作，150+ 组织，与 MCP 互补。
- **AGENTS.md**：事实标准（6 万+ 仓库、23+ 工具）；开发手写的约 +4% 成功率、少 35–55% bug，**LLM 生成的反而更差**。
- **SKILL.md / 渐进披露**：Anthropic 事实做法（元数据常驻、正文按需、脚本不入上下文），**跨厂商尚未标准化**。
- **Agent 定义可移植（Agent Spec/ADP）**：仍在演进，属观察区，不作底座。

### 3.4 多 Agent 组织：有实证的边界

- **Orchestrator + worker**：比单 agent 高 +90.2%，但约 15× token，token 量解释约 80% 性能方差（Anthropic multi-agent research）。
- **写必须单线程**：Cognition 2026 修正为「多 agent 只贡献智力，不贡献动作」。
- **verifier 必须外置**：「写代码的 agent 是差的裁判」；异厂商 reviewer + 机械门禁 + 确定性 hooks 路由有效，但「何时停」仍是弱点（arXiv 2610.08900）。
- **debate 不可靠**：见 §1.2 V4，只适合探索。
- **context rot 全模型存在**：文件化状态 + 新上下文（fresh-context subagent 只回传压缩摘要）是正确架构（Chroma research）。

### 3.5 可落地机制清单（已映射到 SACG）

| # | 机制 | 层 | 成本 | 本次是否采纳 |
|---|---|---|---|---|
| 1 | Spec 即执行契约（验收句式 + falsifier） | S | 低 | ✅ |
| 2 | Plan 人工批准门（只读子 Agent 先出计划） | S | 低 | ✅ |
| 3 | 门禁 = 机器可判定证据（命令 + 输出 + 退出码） | A | 低 | ✅ |
| 4 | 绿了才 commit（测试/lint 通过即原子提交） | C | 低 | ✅ |
| 5 | builder/verifier 分离（异模型或异角色） | A | 中 | ✅ |
| 6 | 确定性 hooks 做角色路由（模型不决定晋级） | C | 中 | ✅ |
| 7 | fresh-context 子 Agent 只回传摘要 + 文件路径 | C | 低 | ✅ |
| 8 | 单线程写，并行只用于只读调研 | C | 中 | ✅ |
| 9 | 分层验证栈（critic → review → QA 真跑 → iterate） | A | 高 | ⏳ P3 |
| 10 | Spec 按寿命分层（what 常驻，how 标注本次变更） | S | 中 | ✅ |
| 11 | ADR 记录 how 决策，供 recall 复用 | G | 低 | ✅ |
| 12 | 轨迹 → skill/playbook 蒸馏回写 | G | 中 | ⏳ 已有能力，接流程 |

**不照搬**：Kiro 的 EARS 三文件具体格式、OpenHands critic（需自家 trace 训练）、Humanize 的 72 门禁规模与异厂商采购、Anthropic 式 15× token orchestrator-worker（仅研究型宽任务值）、Devin playbooks、Agent Spec/ADP。

---

## 4. 缺口补齐（GAP → SACG 落点 → owner）

硬约束：每项落点必须是 S/A/C/G 之一，**不新增层**。

| GAP | 现状 | 补齐机制（来自调研） | SACG 落点 | owner SKILL | 成本 |
|---|---|---|---|---|---|
| GAP-1 开发节点语义缺失 | C-Drive 只有交易 `node_id/direction/signals` | 新增 `DEV-intake/context/plan/exec/verify/settle` 六节点 + 开发信号（越界文件数、测试失败率、影响面偏差、spec 漂移） | C（调度语义） | 元 SKILL + C-Drive | 低 |
| GAP-2 无运行状态 | 无 run/phase/model 记录 | `run.schema.json` + `.runs/<run_id>/` + G0 绑定 | C（执行状态） | 元 SKILL | 低 |
| GAP-3 门禁不可判定 | 门禁靠口头/文档 | gates.yaml + 可执行脚本，输出命令与退出码 | A | `dream-acceptance-verify` | 低 |
| GAP-4 计划不可执行 | PlanCard 只展示 | 计划含验收标准 + falsifier + 回滚，作为 D2 契约 | S | 开工 SKILL | 低 |
| GAP-5 判定不自洽 | 写代码者自评 | builder/verifier 分离 + 确定性 hooks 路由 | A | verifier 角色 | 中 |
| GAP-6 模型耦合 | 默认依赖 Trae 子 Agent | 三适配：Trae 子 Agent / AGENTS.md / MCP（L0 出口） | C（宿主适配） | 元 SKILL adapters | 中 |

**不做**：不引入外部框架作为运行时（不 vendor Kiro/OpenHands/Devin/Spec Kit）；只把机制翻译成我们自己的契约与脚本。

### 4.1 C-Drive 的 DEV 节点族（新增定义，不是新代码）

| 节点 | 职责 | 输入 | 输出 | 判定 |
|---|---|---|---|---|
| `DEV-intake` | 意图归类 + 任务切分 | 用户请求 | task 清单 | G0 绑定检查 |
| `DEV-context` | recall + REA 快照 + 影响面 | task | context pack | G1 |
| `DEV-plan` | Spec/Plan + 验收标准 + 回滚 | context | 计划 | G2 人工批准 |
| `DEV-exec` | 分派 owner SKILL，单线程写 | 计划 | 变更集 | G3 越界即停 |
| `DEV-verify` | 五维验收（异角色） | 变更集 | 验收包 | G4 |
| `DEV-settle` | 四分流沉淀 + ADR + 架构问题回写 | 验收包 | 记忆/文档 | G5 |

**C-Drive 复用**：直接复用 `CDriveAgent` 五动作（continue/redo/jump/supplement/debate）与 `effort_level`；`node_id` 换成 `DEV-*`，`signals` 换成开发信号。`debate` 仅用于 D2 计划分歧的**候选生成**，裁决交 G2。

### 4.2 防重复造轮子：GAP 与 SPEC A-C 的复用矩阵

查重顺序（必须逐级过）：**SPEC A-C 既有条款 → 现有 50 个 SKILL → L0 壳（10 个）→ 最后才新建**。任何新建都要在本表登记「为何不能复用」。

| GAP | SPEC A-C 承诺提供（T-D5 实测：全部待建） | 复用方式 | 真实新增量 | 三态 |
|---|---|---|---|---|
| GAP-1 开发节点语义 | B-5 PlanCard（schema 驱动计划）、B-3 AgentPart + ToolCard（工具四态） | 计划用 PlanCard schema 承载；执行状态复用 ToolCard 四态 | 仅补 `DEV-*` 节点映射与开发信号阈值 | 预补齐（配置级） |
| GAP-2 运行状态绑定 | A §3.4 `X-Request-Id` + `ApiException.traceId`；C-C7 `trace_id`/`X-API-Version`；C-3 SSE v1 含 `session_id`/`seq` | **`run_id` 直接取 `trace_id`**，不新造 ID 体系；`phase`/`model_id` 作为 v1 事件新增字段（字段可增不可删） | 两个字段 + 落盘 | 预补齐（字段级） |
| GAP-3 门禁可判定 | A-G5 `tsc --noEmit` / `npm run build`；C-C4 `check:contracts`；C-C8 `check:route-boundary` | 三个现成脚本直接作为 G4/G5 的 gate 实现 | 仅补 G0/G2 的脚本包装 | **完全复用** |
| GAP-4 计划可执行 | B-5 PlanCardView + zod 镜像；C-C4 漂移校验 | 计划契约 = PlanCard + 「验收标准 / falsifier」扩展字段 | 不加新计划格式 | **完全复用** |
| GAP-5 builder/verifier 分离 | 无（A-C 不涉及流程角色） | — | 纯流程规则（谁执行、谁验收），零基础设施 | 预补齐（规则级） |
| GAP-6 模型无关出口 | C-C5 认知/DSH 经 `/api/cognitive/*`、`/api/dsh/*` HTTP 代理（route.ts 禁 spawn/fs）；C-C6 鉴权中间件 | 宿主持有方一律走代理面；Trae 子 Agent 只是 adapter 之一 | 仅补 AGENTS.md / MCP 两个 adapter 文档 | 复用 + 文档级 |

**结论**：6 个 GAP 中 **3 个完全复用 A-C**（GAP-3/4/6），**3 个只需配置/字段/规则级补齐**（GAP-1/2/5），**没有一个需要新建基础设施**。注意：T-D5 实测确认 A-C **全部未落地**，此处"复用"是**依赖语义**（不另建、等交付后消费），不是现状，见 §4.4。
`.runs/` 是唯一新增落盘目录，理由是 B-7 的 `agent-session-store` 面向会话展示、不面向门禁读取，消费方不同；不复用不构成重复建设。

### 4.3 预补齐最小集 vs 工作中再补

| 类别 | 内容 | 理由 |
|---|---|---|
| 开工前必须补（最小集） | `run.schema.json`（复用 `trace_id`）、`phases.yaml`、`gates.yaml`（只包装现有 tsc/build/lint/test；C-C4/C-C8 标 `pending`）、`DEV-*` 节点映射表 | 没有 G0 就无法满足「无模型禁止开发」 |
| 工作中缺失再补 | AGENTS.md / MCP adapter 细则、开发信号阈值标定、分层验证栈（critic→review→QA）、`.runs/` 归档策略 | 等真实缺口暴露再补，不提前造无人用的轮子 |
| 永不新建 | 事件总线、状态数据库、新计划格式、新 ID 体系、新鉴权中间件 | 已分别由 C-3、B-7、B-5、C-C7、C-C6 承担 |

> **依赖倒置说明**：C-C4 `check:contracts`、C-C8 `check:route-boundary`、B-5 PlanCard zod 镜像均为 **SPEC-C/B 待开工产物**。在其落地前，`gates.yaml` 必须把对应 gate 标 `pending:SPEC-C` 并 FAIL-OPEN（只记录、不阻断），否则会把「未来能力」误当成「现有能力」，G4 形同虚设。当前唯一可直接使用的门禁是 `tsc --noEmit` / `npm run build` / `npm run lint` / `npm run test` 四项（T-D5 实测）。

---

### 4.4 T-D5 复用盘点实测（2026-11-12，逐条核对）

**核对范围**：A/B/C 三份 SPEC 的 26 条任务、22 条目标、10 项可执行门禁、18 类契约，逐条比对仓库实测。

**实测总览**

| 类别 | 数量 | 实测结果 |
|---|---|---|
| A-C 声明产物（新文件/新脚本/新路由） | 11 项抽检 | **0 存在，11 项全部 MISS**（`src/lib/contracts`、`src/lib/stream/*`、`src/lib/navigation.ts`、`src/middleware.ts`、`src/stores/agent-session-store.ts`、`src/types/agent-message.ts`、`src/types/plancard.ts`、`src/components/features/agent`、`src/lib/adapters`、`src/components/feedback`） |
| 现有可改造资产 | 9 项 | `api-client.ts`、`v3/api/client.ts`、`sse-client.ts`、`sse-dispatcher.ts`、`use-monitor-data.ts`、`useProactiveSSE.ts`、`dashboard/layout.tsx`、`app/board/**`、`c-drive.ts` 均存在 |
| 现在即可执行的门禁 | 4 项 | `npx tsc --noEmit`（typescript ^5.7.0）、`npm run build`、`npm run lint`、`npm run test`（jest ^29.7.0） |
| 不存在的门禁 | 2 项 | `check:contracts`、`check:route-boundary`（package.json 仅 dev/build/start/lint/test/test:watch/test:intent） |

**逐条核对**

| GAP | 依赖条款（出处） | 仓库实测 | 结论 |
|---|---|---|---|
| GAP-2 run 绑定 | A-T-A5（A:L227）`X-Request-Id`+`traceId`；C-T-C7（C:L209）`trace_id`/`X-API-Version`；C-T-C3（C:L205）SSE v1 | `api-client.ts` 已注入/回读 `X-Request-Id`（支持调用方 `traceId`）；`ApiEnvelope` 已实现（T-C2）；`SSEEventV1` 已实现（T-C3，`src/lib/sse/v1-protocol.ts`）；`/api/dsh/execute` 完成请求头→body→上游→响应头回显 | **已交付**（2026-11-12 §11.39）；`run_id` 可直接取 `trace_id` |
| GAP-3 门禁 | A-G5（A:L42）；C-T-C1（C:L203）/C-T-C8（C:L210） | `next.config.ts` 仍 `ignoreBuildErrors:true`、`ignoreDuringBuilds:true`；无两个 check 脚本 | **部分可用**：tsc/build/lint/test 立即可用；C 侧两脚本待建 |
| GAP-4 计划契约 | B-T-B5（B:L215）；C-T-C1（C:L203） | `types/plancard.ts`、`PlanCardView.tsx`、`src/lib/contracts/` 全部 MISS；JSON Schema 已在 52 工程 | **待建** |
| GAP-6 模型无关出口 | C-T-C5（C:L207）；C-T-C6（C:L208） | `src/middleware.ts` MISS；`/api/cognitive/*`、`/api/dsh/*` 未建；`cognitive-client.ts` 现为 spawn 直连 | **待建**；当前只能走 L0 MCP 出口 |
| GAP-1 节点语义 | B-T-B3（B:L213）/T-B4（B:L214） | `src/components/features/agent/` MISS | **待建** |
| GAP-5 角色分离 | 无条款 | — | 纯规则，立即可用 |

**原文偏差（核对发现，3 处）**

> 状态：**3 处已于 2026-11-12 修入 SPEC-A/C（v0.1.1）**，下表保留原始发现以便追溯。

| # | 偏差 | 证据 | 影响 | 状态 |
|---|---|---|---|---|
| D1 | SPEC-A 的 P-A2/T-A1 引用 `src/app/agent/page.tsx`，实测该目录只有 `.DS_Store`；`src/app/dashboard/agent` 也不存在 | `find src/app/agent -maxdepth 3 -type f` → 仅 `.DS_Store` | T-A1 不能 `git mv`，应改为「新建 `/dashboard/agent`」；P-A2 的「独立 h-screen 壳」需重新取证（实测 `/chat` 才是 `h-screen` 壳） | ✅ 已修 SPEC-A v0.1.1 |
| D2 | 导航实为 12 项、`/board/approval` 已在第 11 项，非"13 项" | `grep href` 输出 12 条 | G1 验收改为「12 项 + 新增 Agent = 13」 | ✅ 已修 SPEC-A v0.1.1 |
| D3 | 边界脚本名不一致：G-C8 写 `check:route-boundary`，T-C8 写 `check-route-boundary.mjs` | C:L42 vs C:L210 | 预补齐 `gates.yaml` 必须先统一命名，建议以 T-C8 为准 | ✅ 已修 SPEC-C v0.1.1（统一 `npm run check:boundary` + `scripts/check-route-boundary.mjs`） |

**实测结论**

1. v0.3.0 把 A-C 写成"已具备"不准确，实测是**待建**；准确表述为「复用 = 不另建，等 A-C 交付后消费」，属依赖关系。
2. 预补齐必须满足「不依赖 A-C 也能跑」：`gates.yaml` 只启用 tsc/build/lint/test 四项，其余 gate 标 `pending:SPEC-A/C` 且 FAIL-OPEN。
3. 新增风险 **R11 顺序耦合**：A-C 长期未开工时，DREAM 驱动层只剩 4 项门禁，G4 的"契约/影响面"两维降级，"回归/边界"可执行。缓解：G0/G1/G2 不依赖 A-C，先让驱动层跑通。

---

## 5. 元 SKILL 设计（唯一入口）

### 5.1 形态：薄提示 + 厚契约

```
.trae/skills/dreamos-dev/
├── SKILL.md                 # ≤2k token：入口 / 路由表 / 门禁速查
├── contracts/
│   ├── run.schema.json      # run_id / model_id / phase / task / artifacts
│   ├── phases.yaml          # 六阶段状态机
│   └── gates.yaml           # G0-G5 判定规则（机器可执行）
├── routing.yaml             # 任务类型 → owner SKILL（唯一事实源）
└── adapters/
    ├── trae.md              # Trae 子 Agent（默认）
    ├── agents-md.md         # AGENTS.md 兼容（跨工具事实标准）
    └── mcp.md               # MCP / L0 出口（去宿主依赖）
```

原则：模型只读 `SKILL.md` + 当前阶段契约；判定在 `gates.yaml`/脚本，不在提示词。

### 5.2 路由表

| 任务类型 | owner SKILL |
|---|---|
| 架构摸底 / 影响面 | `dream-rea-architecture-query` |
| 调研 / SPEC 形成 | `dream-arch-research-orchestrator`（开工 SKILL） |
| 方案分歧候选 | `52/orchestrator` 双路径（默认关）+ adjudicator |
| TDD 实现 | `dream-tdd-dev-workflow` / `tee-red-green-progress` |
| 前端落地 | `dream-feature-landing-workflow` |
| 验收 | `dream-acceptance-verify` |
| 提交 / 同步 | `dream-code-commit-sync-workflow` |
| 文档同步 | `dream-doc-sync-workflow` |
| 收尾 / 沉淀 | `dream-completion-evolution-workflow`（收尾 SKILL） |
| 自迭代 | `dream-self-iteration-workflow` |
| SKILL 治理 | `dream-skill-index-governance` |

禁止：元 SKILL 内联实现步骤；缺项补 `routing.yaml`，不扩正文。

---

## 6. 门禁（机器可判定）

| 门禁 | 规则 | 不通过 |
|---|---|---|
| **G0 绑定** | `run_id/model_id/phase` 非空且合法 | 硬拒开工 |
| **G1 上下文** | recall 记录 + REA `snapshot_id`（或声明跳过理由） | 退回 |
| **G2 计划** | 验收标准 + falsifier + 回滚 + 影响面 + **复用盘点**（A-C 条款 / 现有 SKILL / L0 壳，含"为何不能复用"） | 退回重规划 |
| **G3 执行** | 改动 ⊆ 影响面；越界需重过 G1 | 立即停 |
| **G4 验收** | 五维证据（症状复测/日志/回归/影响面/边界），命令 + 退出码 | 不得宣称完成 |
| **G5 沉淀** | record/verify + 文档索引 + 架构问题回写 | 不得关闭 run |

G4 的「机器可判定」：每条证据必须附 `command` + `exit_code` + 关键输出片段，人工结论不可单独作为证据。

---

## 7. 状态机与产物

```
D0 intake → D1 context → D2 plan → E1 execute → A1 verify → M1 settle → CLOSED
             │            │          │            │
             └─ 失败 → D1  └─ 失败 → D2
```

| 状态 | 产物 | 必需字段 |
|---|---|---|
| D1 | `.runs/<run_id>/context.json` | snapshot_id、影响面、recall_ids |
| D2 | `.runs/<run_id>/plan.md` | 验收标准、falsifier、回滚、任务分解 |
| E1 | `.runs/<run_id>/changes.json` | 文件清单、diff 摘要、越界声明 |
| A1 | `.runs/<run_id>/acceptance.md` | 五维证据（含命令与退出码） |
| M1 | `.runs/<run_id>/settle.json` | record_ids、文档变更、ADR、架构问题 |

`.runs/` 本地运行目录，不入库（加 `.gitignore`）；入库的只有验收包、ADR 与 SPEC 变更。

---

## 8. 本次手把手验证：与 SPEC A-C 接线

| 批次 | 负载 | 验证环节 | 退出条件 |
|---|---|---|---|
| 1 | A 的 T-A1/A2（路由与壳收口） | D1 context（REA 路由表）+ G3 越界门禁 | 13 项导航留壳（12 现有 + 新建 Agent）；5 条 `/board/*` 旧路径 308；拓扑差分为预期 |
| 2 | A 的 T-A3/A4（流单例） | C-Drive 选路 + 运行时边界 | 切页不断流；monitor 单例；仅 1 条 SSE |
| 3 | B 的 P0（part/ToolCard/PlanCard） | D2 计划 → PlanCard 作计划载体 | 6 类 part；未知类型降级 |
| 4 | C 的 P0（契约/错误码/门禁） | G0 绑定 + G4 机器证据 | `check:contracts` / `check:boundary` 可阻断 |
| 收尾 | 三批合并 | M1 四分流 + 架构问题回写 | 验收包 + record + SPEC 修订 |

### 8.1 灰度接线清单（目标 ≥4 条）

| # | 能力 | 默认 | 接线 | 回滚 | 观测 |
|---|---|---|---|---|---|
| 1 | 脑暴双路径 + adjudicator | 关 | 仅 D2 分歧时候选生成 | 关开关回单路 | 采纳率、裁决耗时 |
| 2 | 48 verdict dashboard | 只读 | A1 引用 verdict（不参与判定） | 移除引用 | verdict 分布 |
| 3 | DSH 子 Agent（若 T-D0 证实） | 关 | E1 按 `model_role` 绑定 | 回退单体执行 | 子任务成功率 |
| 4 | L2-8B 灰度部署门禁 | 关 | G5 后人工触发 | `rollback_deploy.sh` | 部署成功率 |
| 5 | REA 增量索引 | 开 | D1 必调 | 关闭后人工影响面 | snapshot 复用率 |

---

## 9. 验收指标

| # | 指标 | 定义 | 阈值 | 不达标 |
|---|---|---|---|---|
| M1 | 冷启动可开工率 | 新模型仅读 SKILL + 契约产出合规 D2 计划 | ≥2/3 宿主 | 收契约 / 压篇幅 |
| M2 | 绑定违规率 | 无 model_id/phase 的运行占比 | 0 | 流程事故 |
| M3 | 跨模型一致性 | D2 关键字段一致度 | ≥80% | 收敛枚举 |
| M4 | 人工纠偏 | 单任务次数 | ≤2 | 回看 G1/G2 |
| M5 | 架构问题回写率 | 有 record/SPEC 变更的问题占比 | 100% | 补 M1 门禁 |
| M6 | 门禁误杀率 | 合规运行被拒比例 | ≤10% | 调规则 |
| M7 | Spec 漂移 | 计划与实现偏离条目 / 计划条目 | ≤15% | 拆分计划、缩短寿命 |
| M8 | 灰度接线数 | 已接线且有回滚 | ≥4 | 只补清单 |

---

## 10. 风险与降级

| # | 风险 | 处置 |
|---|---|---|
| R1 | 口径漂移（旧 SACG 残留） | 新文档一律 v4.2；`dreambuddy-os` 标 deprecated |
| R2 | 文档承诺 ≠ 实现（DSH 尤其） | 只写 🟢/🟡/🔴 + 证据；未核实不写「已落地」 |
| R3 | 元 SKILL 与 50 个既有 SKILL 冲突 | 只做路由表；注册前跑冲突检测 |
| R4 | 模型差异导致门禁绕过 | 门禁代码化，提示词不承担判定 |
| R5 | 灰度接线引入生产风险 | shadow 先行 + 回滚 + 开关降级 |
| R6 | REA 盲区（字符串引用/运行时） | 影响面双轨：REA + Grep；运行时结论必须 E2E |
| R7 | 48 verdict 被误读 | 引用时原样带 `candidate/falsified/inconclusive` |
| R8 | 宿主绑定 | adapters 三套并存；P3 验证非 Trae 路径 |
| R9 | SDD 成本 | 2–3× token / 2× 时间；小任务走轻量档（`effort_level=light`） |
| R10 | debate 谄媚趋同 | 双路径只生成候选；裁决交 G2 或人工 |
| R11 | 顺序耦合：A-C 未开工时门禁只剩 4 项 | G0/G1/G2 不依赖 A-C；其余 gate 标 `pending:SPEC-A/C` + FAIL-OPEN |

---

## 11. 实施路线

| 阶段 | 内容 | 产物 | 出口 |
|---|---|---|---|
| P0 | 事实基线：T-D0 DSH 子 Agent 核实（✅ 已完成，见 §11.30）；T-D1 灰度清单；T-D2 50 SKILL 四层映射；T-D3 口径冲突清单；T-D4 C-Drive 开发域适配点确认（已完成初查）；**T-D5 复用盘点：逐条比对 SPEC A-C 条款，输出 §4.2 矩阵的实测版（✅ 已完成，见 §4.4）** | `FACTS.md` | 三类状态可回答「已实现/部分/未实现」 |
| P1 | 契约**最小集**（run.schema 复用 trace_id / phases / gates 包装既有三脚本） | `contracts/*` | G0 脚本可判定，且无新建基础设施 |
| P2 | 元 SKILL v0.1（薄提示 + routing + adapters） | `dreamos-dev/SKILL.md` | 可从入口分派 |
| P3 | 批次 1-4 手把手验证（接 SPEC A-C） | `.runs/*` + 验收包 | M1-M7 首次实测 |
| P4 | 治理固化：registry 注册、`dreambuddy-os` deprecate、漂移检测、G4 脚本化、认知回写 | 注册记录 + 变更 | 六道门禁全机器可判定 |

依赖：P0 → P1 → P2 → P3（可与 P2 尾部并行）→ P4。

### 11.1 交付状态（2026-11-12）

| 阶段 | 状态 | 证据 |
|---|---|---|
| P0 事实基线 | 🟢 T-D5 已完成 | §4.4 实测矩阵 |
| P1 契约最小集 + G0/G3 可判定 | 🟢 已交付 | `contracts/{run.schema.json, phases.yaml, gates.yaml, dev_nodes.yaml}`；`scripts/g0_check.py`（5 项检查，通过/拒绝双向实测）、`scripts/g3_check.py`（越界即停实测） |
| P2 元 SKILL v0.1 | 🟢 已交付 | `SKILL.md`（薄提示）+ `routing.yaml`（11 条路由，指向既有 SKILL，无内联实现） |
| P3 批次 0 门禁自举 | 🟢 已交付 | `g1/g2/g5_check.py` 落地，六道门禁全通；`run-20261112-p3gate01` 走完 D0→M1，见 §11.2 |
| P3 批次 1 导航与壳收口 | 🟢 已交付 | T-A1/T-A2 落地，旧 `/board/*` 5 条 308；见 §11.4 |
| P3 批次 2-4 手把手验证 | 🟢 已交付 | 批次 2/3/4 均已落地（stream-manager、域客户端、逐页 useQuery 迁移等），见 §11.4~§11.27；`check:contracts`（4 例）/`check:boundary`（fs=41/child_process=31）已实装并通过 |
| P4 治理固化 | 🟢 批次 1-2 已交付 | 批次 1：registry 注册 `dreamos-dev`（186→187）、`dreambuddy-os` deprecated + `replaced_by`、漂移检测固化（§11.28）；批次 2：G4 验收门禁脚本化 `g4_check.py`（evidence.json 五维）+ `fail_open: false`（§11.29） |
| T-D0 DSH 子 Agent 核实 | 🟢 已完成 | 8 个 subagent 契约/注册/执行/接线四层齐全，83 例测试通过；§2 由 🟡 争议改为 🟢 已落地，见 §11.30 |
| B1-B3 DSH 桥云端通路 | 🟢 已交付 | B1 `/execute` HTTP 出口（stdlib，复用 `call_handler`，回显 trace_id）；B2 14 处解释器硬编码清零（`COGNITIVE_PYTHON/PYTHON/python3`）；B3 dreamos 缺失分支独立原因码 `dreamos_archived`；见 §11.31 |
| C 端剩余流式组件 | 🟢 已交付 | 6 个组件的重连/状态一致性审计 + 修 1 处真实竞态（GlobalSearchDialog 相似案例慢响应覆盖）+ 补 2 个此前零覆盖组件的回归测试；见 §11.32 |

已交付：`check:contracts`/`check:boundary` 于 2026-11-12 实装，`gates.yaml` 从 `pending:SPEC-C + fail_open: true` 校准为 `enabled + fail_open: false`；G4 同日脚本化，六道门禁（G0-G5）全部机器可判定。开发信号阈值除 `out_of_scope_files` 外仍标 `uncalibrated`（待更多真实 run 标定）。

### 11.2 首次实测（M1-M7，2026-11-12）

数据来源：`run-20261112-p3gate01`（1 条 run，单宿主单模型，样本不足仅作首测基线）。

| 指标 | 实测值 | 说明 |
|---|---|---|
| M1 冷启动可开工率 | 1/1（样本不足，需 ≥2/3 宿主） | 仅 Trae 单宿主；AGENTS.md/MCP 适配未建 |
| M2 绑定违规率 | 0% | 1/1 run 具备 run_id= trace_id / model_id / phase |
| M3 跨模型一致性 | 未测 | 单模型（deepseek-v4.1-flash），多模型短期不配置 |
| M4 人工纠偏次数 | 0 | 本 run 用户仅下达「继续 P3」，无中途纠偏 |
| M5 架构问题回写率 | 100%（2/2） | `.arch-map` 自噪音、`.runs` 污染架构图 → 均已回写 builder + 本 SPEC |
| M6 门禁误杀率 | 0%（0/1） | 合规 run 未被拒；负样例均按预期拒绝（非误杀） |
| M7 Spec 漂移 | 0%（0/7） | 计划 7 条任务全部落地，无偏离 |

### 11.3 P3 批次 1-4 验证（代码现状，2026-11-12）

> 口径：只核对 §8 批次表的退出条件，不实现。结论为「当前代码是否已满足」。

| 批次 | 退出条件 | 结论 | 证据 |
|---|---|---|---|
| 1 | 13 项导航留壳（12 现有 + 新建 Agent） | ❌ | `dashboard/layout.tsx` L18-L31 仅 12 项，且「人工审批」仍指向旧 `/board/approval`；`src/app/agent/` 为空目录（无 page.tsx） |
| 1 | 5 条 `/board/*` 旧路径 308 | ❌ | 5 个旧页面仍存在（`/board`、`/board/approval`、`/board/proposals`、`/board/proposals/[id]`、`/board/review`）；`next.config.ts` 无 redirects 配置 |
| 2 | 切页不断流 | ⚠️ | `use-monitor-data.ts` L96 有卸载 cleanup，但无跨页保持连接机制 |
| 2 | monitor 单例 | ✅ | `monitor-bus.ts` L171 模块级单例 + RingBuffer(500) |
| 2 | 仅 1 条 SSE | ❌ | 3 处订阅 `/api/monitor/stream`：`use-monitor-data.ts:96`、`useProactiveSSE.ts:38`、`useArchMapLive.ts:152` |
| 3 | 6 类 part + 未知类型降级 | ❌ | 全仓 `.tsx` 无 `.parts` 渲染（0 命中），无 PartRenderer / ToolCard / PlanCard |
| 4 | `check:contracts` / `check:boundary` 可阻断 | ❌ | `package.json` scripts 仅 dev/build/start/lint/test/test:watch/test:intent；`scripts/` 下无边界脚本 |

结论：批次 1/3/4 退出条件全部未达，批次 2 仅「monitor 单例」达标；按 R11 顺序耦合，批次 1（导航与壳收口）应先于 2/3/4。批次 4 落地时需先给既有 `route.ts` 的 `child_process` 用法（如 `api/agent/brainstorm` 的 spawn）建基线白名单，否则门禁会立刻全红。

### 11.4 P3 批次 1 交付（T-A1 + T-A2，2026-11-12）

> run：`run-20261112-p3b1`（`model_id=human`）；G0/G1/G2/G3/G5 全通。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-A1 导航单一事实源 | 新建 `src/lib/navigation.ts`（`NAV_ITEMS`，13 项）；`dashboard/layout.tsx` 改为消费它，不再内联数组 | 渲染 HTML 导航 href 唯一值 13 条，含 `/dashboard/agent` 与 `/dashboard/board/approval`；`href="/board/` 0 条 |
| T-A1 Agent 工作台 | 新建 `src/app/dashboard/agent/page.tsx`（复用 `ChatPanel`/`SteerPanel`，容器 `h-full`） | `GET /dashboard/agent` → 200；`/chat` 未改动 |
| T-A2 board 迁入壳 | 5 个页面 `git mv` 至 `src/app/dashboard/board/**`；`min-h-screen` → `min-h-full`；页内 `/board/*` 链接改新路径 | 5 个新路由全部 200 |
| T-A2 旧路径 308 | 5 个旧页改 `permanentRedirect`（308）；approval 与 proposals/[id] 保留 query/params | `/board` → `/dashboard/board`；`/board/approval?x=1` → `...?x=1`；`/board/proposals/abc123?tab=diff` → `.../abc123?tab=diff`；均 308 |
| 回归 | `npx tsc --noEmit` 仅 1 条预存错误（`.next/types/app/api/agent/plan/route.ts`，与本次无关）；交易域零改动 | G4 |

未做（留待后续批次）：批次 3 part 渲染、批次 4 `check:contracts`/`check:boundary`。

### 11.5 P3 批次 2 交付（T-A3 + T-A4，2026-11-12）

> run：`run-20261112-p3b2`（`model_id=human`）；G0/G1/G2/G3/G5 全通。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-A3 任务流单例 | 新建 `src/lib/stream/task-stream-manager.ts`：模块单例 POST SSE，`startTaskStream` 先 abort 旧流、复用 `createSSEConnection`/`createTaskStreamHandlers`、禁自动重连、SSR 安全 | `isTaskStreaming()` 单测覆盖替换/终止/错误/SSR 5 例 |
| T-A3 切页不断流 | `ChatPanel.tsx` 删除 `sseConnectionRef` 与卸载 close，改调 `startTaskStream`/`abortTaskStream`；错误改读 `session-store.lastTaskError` | 全仓 `sseConnectionRef` 0 命中；`lastTaskError` 单测验证写 store |
| T-A4 monitor 单例 | 新建 `src/lib/stream/monitor-stream-manager.ts`：模块单例 `EventSource`，引用计数（首订阅连接/末退订关闭）、`event.id` LRU 200 去重、1s→30s 退避（抖动，open 重置） | 单测：2 订阅共享 1 实例、重复 id 只分发 1 次、退避后新建连接、无订阅不重连 |
| T-A4 3 处合 1 | `use-monitor-data.ts` 与 `useArchMapLive.ts` 改为 `subscribeMonitor`；删除 0 引用的 `useProactiveSSE.ts` | `grep "new EventSource("` 仅 manager 1 处；`useProactiveSSE` 0 命中 |
| 回归 | `npx tsc --noEmit` 仅 1 条预存错误；`npx jest` 49 套件 / 669 例全绿（含新增 10 例）；`/dashboard/monitor`、`/dashboard/agent`、`/dashboard/trade`、`/chat` 均 200 | G3 10 个改动全部在影响面内 |

未做（留待后续批次）：批次 3 part 渲染、批次 4 `check:contracts`/`check:boundary`。浏览器多页 Network 计数（A4 手工项）未在本轮自动化，已由单例+引用计数单测覆盖其实现前提。

### 11.6 P3 批次 3 交付（T-B3 + T-B4 + T-B5，2026-11-12）

> run：`run-20261112-p3b3`（`model_id=human`）；G0/G1/G2/G3/G5 全通；退出条件「6 类 part + 未知类型降级」达标。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-B3 契约 | 新建 `src/types/agent-message.ts`：`AgentPart` 六类判别联合（text / reasoning / tool / plan-card / artifact / verification）+ `AgentMessage` + `UnknownAgentPart`；不依赖 AI SDK 类型 | 6 类渲染各 1 正例 |
| T-B3 渲染器 | 新建 `src/components/features/agent/PartRenderer.tsx`：`Record<AgentPart['type'], ComponentType>` 注册表，新增类型只注册不改列表；未知类型 → `UnknownPart`（`<details>` + JSON + console.warn），FAIL-OPEN | `PartRenderer.test.tsx` 8 例（含「未知类型降级为 JSON 折叠，不抛错、不白屏」） |
| T-B4 ToolCard | 四态 pending/running/success/error；success 默认折叠、error 默认展开；结果 >12 行折叠；`navigator.clipboard` 不可用降级「复制不可用」；`onRetry` 仅注入时显示（交易域不传） | `ToolCard.test.tsx` 9 例 |
| T-B5 PlanCard | 新建 `src/types/plancard.ts`（`plancard.schema.json` 的 zod 镜像：严格 `planCardSchema` + 视图宽松 `planCardViewSchema`）与 `PlanCardView.tsx`（verdict 徽标、步骤、风险组、验收引用可复制；未知工具名标红；zod 失败降级 JSON） | `PlanCardView.test.tsx` 5 例 |
| T-B3 适配器 | `src/lib/adapters/sse-to-parts.ts`（10 类交易域事件单向映射，未知忽略）与 `ui-message-to-parts.ts`（`text`/`reasoning`/`tool-*` 四态，`step-start` 等忽略） | 两套件 14 例 |
| 回归 | `npx tsc --noEmit` 仅 1 条预存错误（并清除批次 2 遗留的未使用 `@ts-expect-error`）；`npx jest` 54 套件 / 705 例全绿；冒烟 `/dashboard/agent`、`/dashboard/monitor`、`/chat` 均 200 | G3：14 个改动全部在影响面内 |

未做：T-B6 协议层页面接入——仓库当前不存在 `useChat` 协议页（`src/app/agent/` 为空，`/dashboard/agent` 按批次 1 为交易域 ChatPanel），且 SPEC B 非目标禁止改造交易域 UI；内核与适配器已就绪，协议页出现后 `<PartList parts={uiMessageToParts(m)} />` 一行接入。T-B1/T-B2 与 T-B7~T-B10 仍待后续。

### 11.7 P3 批次 4 交付（T-C1 + T-C8，2026-11-12）

> run：`run-20261112-p3b4`（`model_id=human`）；G0/G1/G2/G3/G5 全通；退出条件「两条 npm 门禁能真实阻断」达标。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-C8 边界门禁 | 新建 `scripts/check-route-boundary.mjs`：递归扫描 `src/app/api/**/route.ts`（110 个），对 `fs` / `child_process` 做三重校验（总量不增、单文件不增、不在白名单的新文件即失败），违规输出 `文件:行号`；支持 `--update-baseline` / `--json` | 现状 exit 0；临时加含 `spawn` 的 route → `失败：3 处违规`、exit **1** |
| T-C8 基线 | 新建 `scripts/route-boundary-baseline.json`：实测 `fs=41 / child_process=31`，逐文件白名单 30 项（含 `api/agent/brainstorm`、`api/cognitive/knowledge`） | 既有使用零误报；SPEC C §3.8 的 36/30 为旧快照，已在验收包注明 |
| T-C1 漂移校验 | 新建 `src/lib/contracts/__tests__/plancard-drift.test.ts`：JSON Schema ↔ zod 镜像递归比对必填字段集合、属性键集合、类型分类（含 integer）、`verdict`/`side` 枚举、`tool` pattern，并做合法/缺字段行为断言 | 现状 4 例全绿；篡改 `verdict.enum` 加 `TIE` → exit **1** 并输出 diff |
| 门禁入口 | `package.json` 新增 `check:contracts`（`jest src/lib/contracts --runInBand`）与 `check:boundary`（`node scripts/check-route-boundary.mjs`） | 两条命令均可被 CI/pre-commit 直接调用 |
| 回归 | `npx tsc --noEmit` 仅 1 条预存错误；`npx jest` **55 套件 / 709 例全绿**；负样例临时文件已清理，基线恢复 110/41/31 | G3：5 个改动全部在影响面内 |

未做：CI workflow 接入（无 `.github/workflows` 变更授权）；`check:contracts` 目前只覆盖 PlanCard，SSE v1 与响应信封的漂移门禁（T-C2/T-C3）待后续。

### 11.8 P3 批次 5 交付（T-A6 + T-B1 + T-B2 + T-C6，2026-11-12）

> run：`run-20261112-p3b5`（`model_id=human`）；G0/G1/G2/G3/G5 全通；退出条件「构建门禁通过 + 设计 token 收口 + 错误边界/Toast + 鉴权中间件」达标。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-A6 构建门禁 | 修复 `src/app/api/agent/plan/route.ts` 的 `export function loadRegisteredTools` → `function loadRegisteredTools`（去掉 export，消除 Next.js route 类型错误）；`npm run build` 成功 | `npx tsc --noEmit` **零错误**（之前 1 条预存清零）；`npm run build` exit 0 |
| T-B1 设计 token | `src/app/globals.css` 补全 `@theme inline`：背景（bg-primary/secondary/tertiary）、文字（primary/secondary/muted）、边框、SACG 四色、状态（success/warning/danger/info）；新建 `src/lib/design-tokens.test.ts` 扫描 `src/**/*.{ts,tsx,css}` 中所有 `var(--color-*)`，断言均有定义 | 3 例全绿（self refs resolve + src 扫描零悬空 + critical pages 抽样） |
| T-B2 错误边界 | 新建 `src/app/error.tsx`（App Router 错误页）+ `src/app/global-error.tsx`（全局崩溃）；均不展示堆栈，提供重试 | Next.js 自动识别；`console.warn` 记录错误消息 |
| T-B2 Toast | 新建 `src/components/feedback/ToastProvider.tsx`：zustand store + `<ToastProvider>` + `ToastViewport`（success/error/info 三态，3s 自动消失）；`src/app/dashboard/layout.tsx` 在根挂 `<ToastProvider>` | `useToast().show({ type: 'error', message: 'xxx' })` 可直接调用；data-testid 覆盖 |
| T-C6 鉴权中间件 | 新建 `src/middleware.ts`：复用 `auth.ts` 的 NextAuth v5 `auth`，matcher `/dashboard/:path*`；`AUTH_REQUIRED` 开关——**dev 默认关闭**（`process.env.NODE_ENV !== 'production'` 或显式设 `false` 时跳过）；未登录且开启鉴权时重定向 `/login?next=<原路径>` | `AUTH_REQUIRED=false`（默认）不拦截；`AUTH_REQUIRED=true` 未登录访问 → 302 到 /login |
| 回归 | `npx tsc --noEmit` 零错误；`npx jest` **56 套件 / 712 例全绿**（批次 4 基础上新增 1 套件 3 例）；`npm run build` 成功；批次 4 两条门禁 `check:contracts`/`check:boundary` 仍 exit 0 | G3：9 个改动全部在影响面内，未触碰批次 3/4 交付文件 |

未做：T-B6 协议页接入（仓库无 `useChat` 协议页）；T-B7~T-B10 会话/虚拟化/输入器/命令面板（P1）；T-C3 SSE v1（P1）。

### 11.9 P3 批次 6 交付（T-C2 + T-C7，2026-11-12）

> run：`run-20261112-p3b6`（`model_id=human`）；G0/G1/G2/G5 全通；退出条件「信封三形态兼容 + 错误码映射 + trace_id/version」全部达标；**零 route.ts 改动、零消费者改动**。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-C2 信封类型 | 新增 `ApiEnvelope<T>`：`{ success, data?, error?, trace_id?, version? }`；保留 `ApiError` + `ApiException`；导出 `ERROR_CODE` 枚举（7 标准码） | `src/lib/api-client.ts`；`api.envelope<T>()` 新增高级方法返回完整信封 |
| T-C2 响应解析（3 形态） | ① 有 `success` → 原生信封；② 有 `ok` 无 `success` → 兼容信封（`success=ok`，`data = body.data ?? body`）+ `console.warn` 按 URL 去重一次；③ 裸 JSON → 自动包装 `{ success: true, data: body }` + `console.warn` 按 URL 去重 | 14 例全绿：规范信封通过、规范信封 `success:false` 抛 ApiException、旧 ok 信封兼容、裸 JSON 自动包装 |
| T-C2 HTTP 错误码映射 | 401→AUTH_REQUIRED、404→NOT_FOUND、422→VALIDATION_FAILED、429→RATE_LIMITED、504→UPSTREAM_TIMEOUT、其余 5xx→UPSTREAM_ERROR；fetch 超时（AbortError）→ UPSTREAM_TIMEOUT | 14 例全绿：401/404/429/504 各 1 例 + 超时 1 例 |
| T-C7 trace_id + 版本头 | 请求自动带 `X-API-Version: 1`；响应头读 `X-Request-Id` 填 envelope.trace_id，缺则本地 `crypto.randomUUID()`；响应头 `X-API-Version` 写入 envelope.version，缺则 'legacy' + warn 一次 | 3 例：X-Request-Id 注入、X-API-Version 缺失 → 'legacy'、请求头自动注入 |
| 回归 | `npx tsc --noEmit` 零错误；批次 4 两条门禁 exit 0；批次 3 组件 44 例全绿；**零 route.ts 改动**、**零 35 个消费者改动** | G3：changes.json 列 3 个文件全部在 scope 内 |

未做：T-B6 协议页接入（仓库无 `useChat` 协议页）；T-B7~T-B10 会话/虚拟化/输入器/命令面板（P1）；T-C4 缓存层（P1）；T-C5 认知/DSH 代理（P2）；CI workflow 接入。

### 11.10 P3 批次 7 交付（T-C3 SSE v1 契约一致性，2026-11-12）

> run：`run-20261112-p3b7`（`model_id=human`）；G0/G1/G2/G5 全通；退出条件「G-C3 六条客户端规则可机器判定」达标；**既有 10 类交易事件分发语义零变更**。

| G-C3 条目 | 交付 | 证据 |
|---|---|---|
| 事件含 id/type/seq/trace_id/session_id/ts/payload | 新建 `src/lib/sse/v1-protocol.ts`：`SSEEventV1` + `normalizeSSEEvent`（v1 全字段保留） | 1 例 8 字段全匹配 |
| 旧事件可兼容 | 缺 seq/type → `legacy=true`，不丢弃不抛错；id 缺失用 `type:ts:djb2(payload)` 生成稳定键 | 2 例（legacy 归一化 + 聚合通过） |
| 重复不消费 | `SSEDeduper` LRU 200 + `sse-client` 带 `id:` 帧去重（无 id 旧帧不受影响） | 3 例（LRU 淘汰、重复计数、接入层只分发一次） |
| 乱序丢弃 | `SeqTracker` 按 `session_id` 比较 seq，回退/重复均丢弃 | 3 例（回退、同 seq、缺 session/legacy 不判定） |
| 未知类型忽略 | `UnknownTypeCounter` 忽略并计数，v1 8 类 + 交易域 5 类扩展不误判 | 2 例 |
| 顺序告警 | `OrderMonitor`：`done`/`error` 早于 `started` 只 warn 一次，不阻断；heartbeat 不告警 | 2 例 |
| lastEventId | `SSEProtocolState.lastEventId` + `sse-client` 新增可选 `onEventMeta` 回调（含 id/retry/heartbeat） | 2 例（心跳元数据、id/retry/lastEventId） |

**关键实现约束（已写入认知库）**：处理顺序必须 `dedupe → 未知类型过滤 → seq 判定`——未知类型若在 seq 判定之后，会把被忽略事件的 seq 抬为水位，导致后续正常事件被误判乱序。去重仅在帧显式带 `id:` 时启用。

回归：`npx tsc --noEmit` 零错误；SSE/适配器/流相关 **7 套件 / 62 例全绿**（含批次 2 流单例）；批次 3 组件 21 例全绿；批次 4 双门禁 exit 0（110 文件 fs=41 / child_process=31）。

未做：monitor 断线重连（Last-Event-ID）、45s 半开检测、task 重试 3 次——需改 `monitor-stream-manager.ts` / `task-stream-manager.ts`，与批次 2 已验收行为耦合，单独批次评估（arch issue `AI-20261112-09`）。

### 11.11 P3 批次 8 交付（T-B6 ~ T-B10 交互内核收口，2026-11-12）

> run：`run-20261112-p3b8`（`model_id=human`）；G0/G1/G2/G3 全通；**交易域 `ChatPanel` 与所有 `route.ts` 零改动**；新增测试 28 例、受影响目录回归 8 套件 / 60 例全绿。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-B6 协议层页面接入 | 新建 `src/components/features/agent/AgentChatPanel.tsx`：`useChat` + `DefaultChatTransport('/api/agent/chat')`，UIMessage 经 `uiMessageToParts` → `PartList`（批次 3 资产）；`app/dashboard/agent/page.tsx` 从交易域 `ChatPanel` 切换为 `AgentChatPanel` | `npx tsc --noEmit` 零错误；`/api/agent/chat` 未改动 |
| T-B7 会话 store + 持久化 + 深链 | 新建 `src/stores/agent-session-store.ts`：create/rename/delete/select/appendMessage/setMessages；最多 50 会话、单会话 500 条；localStorage 写入节流 500ms；配额失败静默降级；`?session=<id>` 深链 + `history.replaceState` 同步 | 11 例：增删改选、裁剪边界、节流落盘、hydrate、损坏数据、深链命中/回退、配额异常不抛 |
| T-B8 长会话虚拟化 | 新建 `src/lib/virtualization.ts`：`shouldVirtualize(>50)` + `content-visibility:auto` + `contain-intrinsic-size:auto 120px` 行样式，`AgentChatPanel` 按消息数启用 | 4 例：阈值边界、非法值、行样式 |
| T-B9 输入器增强 | `ChatInput.tsx` 新增全可选 props：`onStop` / `onRegenerate` / `draftKey`（sessionStorage 草稿）/ `historyKey`（↑↓ 历史，上限 50）/ `suggestions`（@ 候选）/ `onAttachFiles`（仅文件名）；`onSend` 允许携带附件名列表 | 7 例：基线 Enter/Shift+Enter 不变、草稿恢复、历史上下键、发送写入历史、@ 候选插入、停止回调、附件文件名回传 |
| T-B10 命令面板 | 新建 `src/lib/command-palette.ts`（NAV_ITEMS + 最近会话 + 3 个固定动作，大小写不敏感，上限 20）；`GlobalSearchDialog` 增加动作/导航/最近会话分组，与搜索结果共用 ↑↓/Enter 导航；新建会话走 T-B7 深链 | 6 例：分组、全部导航项可跳转、label/hint 匹配、20 条上限、深链格式、无匹配 |

**关键实现约束**：增强能力一律以「可选 props / 可选模块」叠加，交易域调用点不传新 props 即保持原行为；`AgentChatPanel` 外层以 `key={sessionId}` 重挂载，规避 `useChat` 初始 messages 仅挂载生效的限制。

未做（下一批次）：T-C4 缓存层（需引入 `@tanstack/react-query`）、T-C5 认知/DSH 代理化（`/api/dsh/execute` + `cognitive-client` HTTP 优先）、CI workflow 接入前端门禁。

### 11.12 P3 批次 9 交付（T-C4 / T-C5 / CI 接入，2026-11-12）

> run：`run-20261112-p3b9`；G0/G1/G2/G3/G5 全通；新增测试 13 例、依赖相关回归 12 套件 / 151 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 任务 | 交付 | 证据 |
|---|---|---|
| T-C4 REST 缓存层 | 新增唯一依赖 `@tanstack/react-query ^5`（锁文件仅 +24 行）；`lib/query-keys.ts`（`['domain','resource',params?]` / 默认 30s / 行情 5s / 按 domain 失效）；`components/providers/QueryProvider.tsx`（`createQueryClient` 工厂 + Provider，staleTime 30s / gcTime 5min / retry 1 / 关闭窗口聚焦刷新）；dashboard layout 挂载 | 3 + 3 例：key 形状、staleTime 分级、按 domain 失效；默认值；同请求 staleTime 内重复挂载仅 1 次 |
| T-C5 认知代理化 | `cognitive-client.ts` 增 HTTP 分支：`COGNITIVE_API_BASE` 存在时 `POST {base}/cognitive/{tool}`（10s 超时），非 JSON 裸数据包装，失败回退既有 spawn IPC（FAIL-OPEN）；对外签名 `callCognitive` / `CognitiveResult` 不变 | 4 例：HTTP-only 不 spawn、裸数据包装、HTTP 失败回退 spawn、未配置保持 IPC |
| T-C5 DSH 代理化 | `dsh-execution-engine.ts` 拆分 `callDshHandler`（HTTP 优先 → spawn 回退）与 `callDshSpawn`；新增 `app/api/dsh/execute/route.ts`：只 `fetch` 转发 `{capability,payload,trace_id}`，未配置 `DSH_API_BASE` → 503 + `degraded:true`，超时 504；`GET` 提供探活 | 3 例：HTTP 路径与 body 契约、失败回退 spawn、未配置仅 IPC；边界门禁 0 增量 |
| CI 接入 | `.github/workflows/ci.yml` 新增 `frontend` job（pnpm 11 + Node 20 + 缓存 → `pnpm install --frozen-lockfile` → `tsc --noEmit` → `jest --ci --runInBand` → `check:boundary`）；`quality-gate.needs` 增加 `frontend`，其 failure 直接阻断 | workflow 语法与门禁顺序见文件；GitHub Actions 实际执行需 push 后验证 |

**关键实现约束**：HTTP 与 IPC 双路径均以「配置存在才启用 HTTP」为准，**默认行为与旧版完全一致**（未配置即走 spawn），因此不改变任何现有部署；代理 route 只允许 `fetch`，由 `check:boundary` 机器保证。

**待确认（沿用 SPEC-C §3.5）**：后端 HTTP adapter 尚未提供，`COGNITIVE_API_BASE` / `DSH_API_BASE` 的上游路径 `/cognitive/{tool}` 与 `/execute` 为本 SPEC 约定，后端落地时按此对齐；未落地时自动走 IPC，不阻塞。

### 11.13 P3 批次 10 交付（T-C4 逐页迁移第 1 批，2026-11-12）

> run：`run-20261112-p3b10`；G0/G1/G2/G3/G5 全通；新增 3 套件 13 例、影响面回归 40 套件 / 518 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| market | `useEffect` + 4 个 `useState`（data/loading/error），切 tab 每次重发 | 双 `useQuery`（`market/route`、`market/content`）+ `enabled` 懒加载 + `staleTime 5s`；导出变量名不变，JSX 零改 | 3 例：首屏只请求当前 tab；切 tab 触发对应请求；切回/重挂载在 staleTime 内不重复请求 |
| briefing | 裸 `fetch` + 手写 loading/detailLoading，`{success,briefings}` 非标准信封 | `briefingApi.list/detail`（`lib/v3/api/briefing.ts`）+ 列表/详情两个 `useQuery`，详情由 `selectedId` 驱动；刷新按钮改 `refetch` | 5 例：信封解析、`success:false`、非 2xx、缺 `briefing` 抛错 |
| ranking | 裸 `fetch` + `useState`，失败/空回落 mock | `rankingApi.today`（失败返回 `null`）+ `useQuery`，页面按 `items.length` 回落 mock；`dataSource` 由数据派生 | 5 例：成功、空列表、`success:false`、非 2xx、网络异常均符合 mock 降级契约 |

**顺带修复**：`src/lib/v3/api/board.test.ts` 4 处 `fetch` mock 缺 `headers`，导致 `api-client` 读取 `response.headers` 抛错（批次 6 引入的既有红测）；补 `headers: new Headers()` 后该套件 10/10 通过，CI `frontend` job 可全绿。

**迁移纪律（后续批次沿用）**：单页独立、只换取数段、保留原变量名让 JSX 零改；SSE 与 `setInterval` 轮询页不迁（按 SPEC-C §3.4 归 zustand）；非标准信封页先建域客户端，不强行接 `api-client` 的 `data` 归一化。

**剩余**：dashboard 共 49 页，已迁 3 页；待迁按 `market/* → monitor/* → board/* → memory/* → 其余` 推进。

### 11.14 P3 批次 11 交付（T-C4 逐页迁移第 2 批，2026-11-12）

> run：`run-20261112-p3b11`；G0/G1/G2/G3/G5 全通；新增 5 例、影响面回归 42 套件 / 523 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| board/proposals | `useEffect` + 3 个 state 拉 `boardApi.listProposals()` | 单 `useQuery(['board','proposals'])`；状态筛选保留为纯前端派生 | 3 例：首屏 1 次、筛选不重发、重挂载 staleTime 内不重发 |
| board/review | `Promise.all` 两个裸 `fetch`，信封手写解析 | 两个 `useQuery`（`['board','review']`、`['board','approval-summary']`），走 `api-client` 信封归一化 | 2 例：`listReviews` URL/method + 信封解包；页面双接口各 1 次且摘要渲染 |

**域客户端补齐**：`boardApi.listReviews()`（`GET /api/board/review`）；`ReviewRecord` 落入 `board.ts` 并从 index 导出；`ApprovalSummary` 补 `approved` / `rejected`（页面实际消费字段，服务端本已返回）。

**扫描结论（不迁移项）**：`monitor/arrange|compute|graph|sense` 四页无 `useEffect` / `fetch`，属静态或子组件驱动，不在迁移范围；`board/approval` 含 30s `setInterval` 轮询，按 SPEC-C §3.4 归 zustand 侧，不迁。

**进度**：dashboard 49 页已迁 5 页（market、briefing、ranking、board/proposals、board/review）。

### 11.15 P3 批次 12 交付（T-C4 逐页迁移第 3 批，2026-11-12）

> run：`run-20261112-p3b12`；G0/G1/G2/G3/G5 全通；新增 4 例、影响面回归 43 套件 / 527 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| market/audit | `useEffect` + 3 state 拉 `marketApi.getAudit()` | 单 `useQuery(['market','audit'])`，派生 `entries/loading/error` 同名 | 2 例：首屏 1 次 + 空态；重挂载 staleTime 内不重发 |
| market/segments | `useEffect` + 3 state 拉 `getSegments()` | 单 `useQuery(['market','segments'])`，`stats` 派生不变 | 1 例：首屏 1 次 + 总计渲染 |
| market/effectiveness | `useEffect` + 3 state 拉 `getEffectiveness()` | 单 `useQuery(['market','effectiveness'])`，`records` 派生不变 | 1 例：首屏 1 次 + 空态 |

**未新建域客户端**：三页均复用既有 `marketApi`，返回值仍为 `Record<string, unknown>` / `MarketSegment[]`，页面沿用 `as unknown as` 收窄，接口契约零改动。

**扫描结论（不迁移项）**：`memory/page.tsx` 与 `memory/user/page.tsx` 的取数在 zustand store（`useCognitiveAutoLoad` / `fetchPreferences` / `fetchNotes`）且含写操作，页面无独立 `useEffect` 取数段，迁移需改 store 层，超出逐页迁移边界；`three-screens/page.tsx` 为三路 `setInterval` + 指数退避重轮询页，按 SPEC-C §3.4 不迁。

**进度**：dashboard 49 页已迁 8 页（market、briefing、ranking、board/proposals、board/review、market/audit、market/segments、market/effectiveness）。

### 11.16 P3 批次 13 交付（T-C4 逐页迁移第 4 批，2026-11-12）

> run：`run-20261112-p3b13`；G0/G1/G2/G3/G5 全通；追加 2 例（测试文件累计 6 例）、影响面回归 43 套件 / 529 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| market/campaigns | `useEffect` + 3 state 拉 `marketApi.getCampaigns()`，状态筛选本地 state | 单 `useQuery(['market','campaigns'])`；`filterStatus` 保留纯前端派生 | 1 例：首屏 1 次 + 筛选不重发 + 筛选后列表正确 |
| market/distribution | `useEffect` + 3 state 拉 `getDistribution()` | 单 `useQuery(['market','distribution'])`，`byChannel` 派生不变 | 1 例：首屏 1 次 + 空态 |

**扫描结论（不迁移项）**：`ops`（可调 5/10/30/60s 轮询）、`board`（30s 轮询）、`bdsm`（`setInterval`）按 SPEC-C §3.4 不迁；`agent` / `classic/[subtab]` / `notebook` / `memory` 的 `useEffect` 为 store hydrate、路由重定向或 mock 初始化，非取数段，不迁。

**进度**：dashboard 49 页已迁 10 页。

### 11.17 P3 批次 14 交付（T-C4 逐页迁移第 5 批，2026-11-12）

> run：`run-20261112-p3b14`；G0/G1/G2/G3/G5 全通；新增 1 套件 4 例、影响面回归 44 套件 / 533 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| feed | 裸 `fetch('/api/feed?workflow_type=')` + `useCallback`+`useEffect`，手写 success 判定 | `feedApi.list(workflowType?)` + `useQuery(['feed','list',{workflowType}])`，筛选变化由 key 驱动新请求，刷新按钮改 `refetch` | 2 例：首屏 1 次 + 空态；切 V2 触发带 `trading_v2` 的第二次请求 |
| board/proposals/[id] | `useEffect` + `boardApi.getProposal(id)` + 3 state | `useQuery(['board','proposal',{id}], enabled: !!id)` | 2 例：按 id 1 次且渲染标题；id 缺失不请求 |

**域客户端补齐**：`feed.ts` 新增 `list(workflowType?)`，复用 `api.get` 的 `params`；原 `get()` 保留。

**进度**：dashboard 49 页已迁 12 页。

### 11.18 P3 批次 15 交付（T-C4 逐页迁移第 6 批，2026-11-12）

> run：`run-20261112-p3b15`；G0/G1/G2/G3/G5 全通；新增 2 套件 5 例、影响面回归 46 套件 / 538 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| meta-labeling | 裸 `fetch('/api/meta-labeling')` + `results/loading/dataSource` 三 state + `useEffect` | `fetchMetaLabeling()` + `useQuery(['meta-labeling','results'])`；`usingApi` 派生 results/dataSource，`MOCK_RESULTS` 提为模块级常量 | 页面 2 例：失败降级「（演示数据）」+ mock 信号；成功展示 API 信号且无演示标记 |
| 域客户端 | 无 | 新建 `lib/v3/api/meta-labeling.ts`，解析非标准信封 `{success, results}`，失败/非 2xx/空返回 null | 客户端 3 例：成功解包 / `success:false` → null / 网络异常 → null |

**进度**：dashboard 49 页已迁 13 页；剩余含 `useEffect` 的页面均为轮询（ops/board/bdsm/three-screens）或 store/路由/mock 初始化（agent/classic/notebook/memory），无可迁移取数段。

### 11.19 P3 批次 16 交付（T-C4 逐页迁移第 7 批：轮询页，2026-11-12）

> run：`run-20261112-p3b16`；G0/G1/G2/G3/G5 全通；追加 3 例（board-pages-query 累计 6 例）、影响面回归 46 套件 / 541 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

**§3.4 改判**：轮询页可用 `refetchInterval` 语义等价迁移（去重、共享缓存、卸载即停），优于裸 `setInterval`；SSE/事件流页仍不迁。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| board 总览 | `setInterval(fetchData, 30000)` + `Promise.all(getMetrics, getApprovalSummary)` | 两个 `useQuery`（`['board','metrics']`、`['board','approval-summary']`）均 `refetchInterval: 30000`；审批摘要与 review 页共享缓存 | 1 例：两接口各 1 次 + 指标渲染 |
| board/approval | `setInterval(load, 30000)` + 手写 loading/error/lastRefresh | `useQuery(['board','pending-approvals'], refetchInterval: 30000)`；`lastRefresh` 用 `dataUpdatedAt`；POST 决策保留，错误拆为 actionError + queryError | 2 例：首屏 1 次渲染待审批；批准后 POST 1 次并移入已决策 |

**进度**：dashboard 49 页已迁 15 页。

### 11.20 P3 批次 17 交付（T-C4 逐页迁移第 8 批：bdsm、ops，2026-11-12）

> run：`run-20261112-p3b17`；G0/G1/G2/G3/G5 全通；新增 1 套件 4 例、影响面回归 47 套件 / 545 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| bdsm | `setInterval(fetchSnapshot, 60000)` + 4 state | `useQuery(['bdsm','snapshot'], refetchInterval: 60000)`；`lastFetch` 用 `dataUpdatedAt`；刷新按钮 `refetch` | 2 例：首屏 1 次渲染快照日期；失败渲染错误 |
| ops | 可调间隔 `setInterval(fetchData, refreshInterval*1000)` + mock 降级 | `useQuery(['ops','dashboard'], refetchInterval: refreshInterval*1000)`；queryFn 合并 `getQueues+getDecisionLevels`，失败 `usingMock` 回落 MOCK | 2 例：两接口各 1 次渲染统计；失败回落 mock 并提示「已加载模拟数据」 |

**进度**：dashboard 49 页已迁 17 页。

### 11.21 P3 批次 18 交付（T-C4 逐页迁移第 9 批：three-screens 三路轮询，2026-11-12）

> run：`run-20261112-p3b18`；G0/G1/G2/G3/G5 全通；新增 1 套件 3 例、影响面回归 48 套件 / 548 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 页面 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| three-screens | 三条自调度轮询链（`setTimeout` + `runWithBackoff` + `failRef`）+ `waveStarted/dataDrivenStarted` starter effect + 手写 `ApiStatus` | 三个 `useQuery`（`['three-screens','trend'|'wave'|'data-driven',{symbol}]`）；`refetchInterval` 按 `fetchFailureCount` 调 `nextBackoff` 保持指数退避封顶 10min；wave / data-driven 用 `enabled: trendQuery.data !== undefined` 保证单线程后端错峰；query 数据经 `useEffect` 同步 zustand（`setScreen1/2/3`），JSX 零改；错误横幅改本地 `errorDismissed` 关闭 | 3 例：首屏只请求 trend；trend 成功后 wave+driven 各 1 次；trend 失败时后两者不启动 |

**轮询页迁移收口**：board / board-approval / bdsm / ops / three-screens 五个轮询页全部完成；dashboard 剩余未迁页面均为 store/SSE/事件流驱动，不在取数段迁移范围。

**进度**：dashboard 49 页已迁 18 页。

### 11.22 P3 批次 19 交付（T-C4 逐页迁移第 10 批：页面专属取数组件/hook，2026-11-12）

> run：`run-20261112-p3b19`；G0/G1/G2/G3/G5 全通；新增 1 套件 3 例、影响面回归 49 套件 / 551 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。
>
> 说明：dashboard 首页与 monitor 页的 `page.tsx` 本身无取数段，取数位于页面专属组件/hook，故本批迁移这两个文件。

| 位置 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| dashboard 首页 `LiveStatusPanel` | `setInterval(fetchStats, 30000)` + 3 个 useState + 静默 catch | `useQuery(['dashboard','live-status'], refetchInterval: 30000)`；`loading` 用 `isLoading`、`lastUpdate` 用 `dataUpdatedAt`；queryFn 非 200 / 非信封抛错，失败保留上次数据（FAIL-OPEN 无错误 UI） | 2 例：首屏 1 次并渲染 12 / 2.0KB；失败不崩溃显示 0 |
| monitor 页 `useMonitorData` | 10s `setInterval` + `alive` 标志 + 手写 try/catch 写 store | 统计轮询改 `useQuery(['monitor','stats'], refetchInterval: 10000, retry: false)`，数据经 `useEffect` 订阅写入 `setThroughput`；**SSE 订阅链保持原实现不迁** | 1 例：首屏 1 次 `api.get('/api/monitor/stats')` 且 store 收到换算后对象 |

不迁判定：`useTokenMonitor` 为本地 `TokenMonitor` 状态机（定时器 + 命令式 pause/resume/trigger），非网络轮询，不属 react-query 范围。

**进度**：dashboard 取数段（页面 + 页面专属组件/hook）已迁 20 处；剩余只读面板（fundamental / reports / governance / memory / settings / notebook 等）为组件级取数，未纳入页级迁移范围。

### 11.23 P3 批次 20 交付（T-C4 逐页迁移第 11 批：fundamental 基本面页 9 面板，2026-11-12）

> run：`run-20261112-p3b20`；G0/G1/G2/G3/G5 全通；新增 1 套件 5 例、影响面回归 50 套件 / 556 例全绿；边界门禁 `fs=41 / child_process=31` 与基线一致。

| 面板 | 迁移前 | 迁移后 | 证据 |
|---|---|---|---|
| OverviewPanel | 3 个 `useEffect`（快照 + `/api/price/btc` + `/api/market/global`）+ 6 个 useState | 3 个 `useQuery`（`['fundamental','snapshot']` / `['price','btc']` / `['market','global']`）；行情类 `retry:false` FAIL-OPEN；`loading/error` 由快照 query 派生，JSX 零改 | 首屏快照 1 次；渲染 `2.500` 与 `$65.0K`、`54.2%` |
| ValuationPanel / BreadthPanel / IntermarketPanel / FlowPanel / OnchainPanel / MacroPanel / SentimentPanel | 各 1~2 个 `useEffect` 手写请求 + useState | 统一改为 `useQuery(['fundamental','snapshot'])`；行情附加 query（Breadth=market/global、Intermarket=market/yahoo `{symbols}`、Valuation=price/btc）；变量名 `mod`/`flow`/`quotes` 等保持 | 同页多面板共享缓存仅 1 次 `getSnapshot()`；Breadth 行情失败仍用快照渲染 `52.0%` |
| ModuleDetail | `useCallback(load)` + `useEffect(load)` 手写 fetch + 3 个 useState；重试按钮调用 `load` | `useQuery(['fundamental','module-snapshot',{module}])`；`load` 改为 `refetch()`，`loading` 用 `isFetching` 保留"刷新中…" | 按 module 拼 URL；点击刷新触发第 2 次 fetch |

**共享缓存收益**：9 个面板共用 `['fundamental','snapshot']`，同页切换 tab 直接命中 30s 缓存，快照请求次数由「每次挂载一次」降为「每 30s 一次」。

不纳入本批：`FundamentalGrid.tsx` 全仓无引用（死代码），不触碰。

**进度**：dashboard 取数段已迁 29 处（含本批 9 个组件）；剩余批次为 settings / memory / notebook·artifact·cycle / reports·governance。

### 11.24 P3 批次 21 交付（T-C4 逐页迁移第 12 批：settings 页 5 面板，2026-11-12）

> run：`run-20261112-p3b21`；G0/G1/G2/G3/G5 全通；新增 1 套件 5 例、影响面回归 51 套件 / 561 例全绿；边界 `fs=41 / child_process=31` 与基线一致。

| 面板 | key | 迁移要点 | 证据 |
|---|---|---|---|
| ApiKeyManager | `['settings','api-keys']` | `useEffect+fetchKeys` 手写请求 → `useQuery`；`keys` 由 `data ?? []` 派生，`loading=isFetching`；`fetchKeys` 改为 `refetch()`，供刷新按钮与 CRUD 后复用 | 首屏 1 次；刷新按钮触发第 2 次 |
| ChannelManager | `['settings','channels']` | 同上；`channels` 派生，`fetchChannels` → `refetch()` | 首屏 1 次 |
| StrategyManager | `['settings','strategies']` | 列表读取入 `queryFn`（返回 `data.strategies`）；`fetchStrategies` → `refetch()`，5 处 CRUD 后复用不变 | 首屏 1 次 |
| CompletenessWizard | `['settings','completeness']` | `compute()` 整体内联进 `queryFn`，`Promise.all` 拉 api-keys/trading-params/strategies/channels（各带 catch 降级）；`steps` 派生、`loading=isLoading` | 4 端点各 1 次；汇总 `6/6 · 必填 3/3`、`100%` |
| TradingParamsPanel | `['settings','trading-params']` | `params` 改为 query 派生；保存后 `setQueryData` 即时更新 + 定向 `invalidateQueries` 替代原 `setParams`；`error` 仍为本地表单错误 | 渲染 `5x`；保存后 `patch` 1 次 + 重取第 2 次 |

**写后策略**：CRUD 刷新仍走原函数名（内部 `refetch`），不新增 mutation 层；参数保存用「写缓存 + 定向失效」，不做全量 `invalidateQueries()`。

**进度**：dashboard 取数段已迁 34 处；剩余批次为 memory / notebook·artifact·cycle / reports·governance。

### 11.25 P3 批次 22 交付（T-C4 逐页迁移第 13 批：memory 页视图，2026-11-12）

> run：`run-20261112-p3b22`；G0/G1/G2/G3/G5 全通；新增 1 套件 5 例、影响面回归 52 套件 / 566 例全绿；边界 `fs=41 / child_process=31` 与基线一致。

| 视图 | key | 迁移要点 | 证据 |
|---|---|---|---|
| DocIndexView | `['memory','docs-index']` | 手写 fetch 改 `useQuery`；`docs`/`reconcile` 由 `data` 派生；`loading=isLoading`，`degraded=isFetched && !docs` 复刻原"空/失败均降级"；sync 成功后改 `refetch()`（原 `setDocs` 局部改） | 首屏 1 次；`2 个文件待重索引`；不可达展示降级 |
| SkillIndexView | `['memory','skills-index']` | 原 `Promise.all` 双请求整体入 `queryFn`（保留第二请求，不改网络行为）；`skills`/`stats` 由 `data` 派生；`degraded` 同构 | 两 URL 各 1 次、总数 `3`；不可达展示降级 |
| DZEChainView | `['cognitive','stats']` | 内联 fetch 改 `useQuery`，`typeDist` 派生；`dzeChains` 仍来自 memory store | 1 次请求；分类轴标题渲染 |
| MemoryTimeline | — | **不迁**：数据源是共享 memory store 的 `fetchRecall`，迁移会改变 store 归属（违反不新增架构层）。与批次 19 `useTokenMonitor` 同级判定 | 本批未改 |

**不迁判定补充**：`useEffect` 存在 ≠ 应迁。判定标准仍是「网络取数是否由组件自行持有」；store action 驱动的取数留在 store。

**进度**：dashboard 取数段已迁 37 处；剩余批次为 notebook·artifact·cycle / reports·governance。

### 11.26 P3 批次 23 交付（T-C4 逐页迁移第 14 批：notebook / cycle 组件，2026-11-12）

> run：`run-20261112-p3b23`；G0/G1/G2/G3/G5 全通；新增 1 套件 5 例、影响面回归 53 套件 / 571 例全绿；边界 `fs=41 / child_process=31` 与基线一致。

| 组件 | key | 迁移要点 | 证据 |
|---|---|---|---|
| ArtifactGallery | `['artifacts','list',{filter}]` | `useEffect+fetch` 改 `useQuery`；URL/limit 原样保留；`artifacts=data ?? []`、`loading=isLoading`；切换类型自动按新 key 请求，切回命中缓存 | 首屏 1 次 `/api/artifacts?limit=50`；点击 report 后请求 `?type=report&limit=50` |
| CycleThinkingPanel | `['cycle','research']` | `setInterval(60s)+useCallback(load)` 改 `useQuery(refetchInterval:60_000)`；`data/loading/error` 派生；失败保留旧数据并展示错误 | 首屏 1 次 `/api/cycle`、渲染象限；`success:false` 展示错误 |
| NotebookPanel | `['notebook','state']` | `notebookApi.getState()` 改 `useQuery`；`serverState` 派生；data 变化经 `useEffect` 调 `syncFromServer` 写回 notebook store；`fetchServer` 改 `refetch()` | 首屏 1 次 `getState` |

**边界说明**：NotebookPanel 仍以 store 为落点（`syncFromServer`），只是数据来源改由 query 托管；未改变 store 归属。

**进度**：dashboard 取数段已迁 40 处；剩余批次为 reports·governance 收尾。

---

### 11.27 P3 批次 24 交付（T-C4 逐页迁移第 15 批：reports / governance 收尾，2026-11-12）

> run：`run-20261112-p3b24`；G0/G1/G2/G3/G5 全通；新增 1 套件 5 例 + 既有 8 例补 Provider、影响面回归 55 套件 / 584 例全绿；边界 `fs=41 / child_process=31` 与基线一致。

| 组件 | key | 迁移要点 | 证据 |
|---|---|---|---|
| ReportsScreen（报告） | `['reports','report',{taskId}]` | 命令式 `loadReport` 改 `useQuery(enabled: !!activeTaskId)`；`report= data ?? null`（`isError` 强制 null，保持原 `setReport(null)` 语义）；`loading=isFetching`；同 id 点「加载」走 `refetch()`，不同 id 改 `activeTaskId` | `lastReportId` 就绪后请求 `/api/task/result/t-1` 恰好 1 次并渲染摘要；无 taskId 首屏 0 请求 + 空态 |
| ReportsScreen（联想） | `['search','reports',{q}]` | 300ms `setTimeout + setSuggestions` 改 `debouncedQuery` state + `useQuery(enabled: q!=='')`；失败静默（`retry:false`） | 输入 `BTC` 后 300ms 请求 `/api/search?query=BTC&module=report&limit=8` 并展示建议 |
| GovernanceScreen | `['governance','proposals']` | `listProposals` + `Promise.all(getProposalVotes)` 合并进单 queryFn，返回 `{proposals,votes,dataSource}`；`voteCounts` 保留本地 state + `useEffect` 从 `query.data` 同步；投票错误独立 `voteError` | 首屏 `listProposals` 1 次 + `getProposalVotes` N 次；点击赞成调用 `vote('p1','FOR')` |

**测试改造**：`GovernanceScreen.test.tsx` 8 个既有用例补 `QueryClientProvider` 包装（`renderScreen()`，每例独立 client，`retry:false`）；新增 `reports-governance-query.test.tsx` 5 例。

**不做（SSE/命令式保持不动）**：`agent/AgentChatPanel`、`chat/ChatPanel`、`chat/SteerPanel`、`sacg/BACTimeline`、`search/GlobalSearchDialog`、`useTokenMonitor`。

**进度**：dashboard 取数段已迁 43 处（+3）；T-C4 逐页迁移 5 批次（20~24）全部收官。

---

### 11.28 P4 批次 1 交付（治理固化：门禁校准 / registry 注册 / 旧入口 deprecate / 漂移固化，2026-11-12）

> run：`run-20261112-p4a`；G0/G1/G2/G3/G5 全通。

| 项 | 动作 | 证据 |
|---|---|---|
| 门禁校准 | `contracts/gates.yaml`：`contracts`/`boundary` 从 `status: pending:SPEC-C` + `fail_open: true` 改为 `status: enabled` + `fail_open: false`，附实装日期与基线说明 | `npm run check:contracts` 4 例通过；`npm run check:boundary` 基线 `fs=41 / child_process=31` |
| registry 注册 | `1-ARCHITECTURE/skills/_registry/registry.json` 新增 `dreamos-dev`（role=coordinator、tier=[local]、category=orchestration、content_hash=sha256(SKILL.md)），`total_count` 186→187 | `python3 1-ARCHITECTURE/skills/_registry/validate_registry.py` 条数=187、schema=1.1；依赖图 26→27 节点 |
| 旧入口 deprecate | `.trae/skills/dreambuddy-os/skill.override.yaml`：`lifecycle.status: deprecated` + `deprecated_at` + `replaced_by: dreamos-dev`；`SKILL.md` 顶部加 DEPRECATED 横幅；registry 内该条 `status: deprecated` | 文件 diff + registry 查询 |
| 漂移检测固化 | 固化为可复现命令并落盘产物：`python3 1-ARCHITECTURE/skills/dream-skill-index-governance/skill_indexer.py detect-drift --roots .trae/skills 1-ARCHITECTURE/skills > .../drift-report.json` | 实测输出 `total_drifted: 1`（仅 `dreamos-dev` 缺 project-index 副本，属设计性单位置，判定为预期） |

**遗留（v0.9 候选）**：
1. ~~registry 内 186 条历史 `path` 需 `skill_indexer build` 重建~~ → **已决策取消（2026-11-12，用户）**：`path` 是机器相关字段，本地与云端会互相覆写，重建无收益；registry 只作条目/角色/状态索引，路径以运行时所在机器为准。
2. `dreamos-dev` 双位置漂移：若需归零，可在 `1-ARCHITECTURE/skills/dreamos-dev` 建薄索引（仅 SKILL.md 指针），但 `contracts/`/`scripts/` 必须保持单源。
3. 开发信号阈值（除 `out_of_scope_files`）仍 `uncalibrated`。

---

### 11.29 P4 批次 2 交付（G4 验收门禁脚本化，2026-11-12）

> run：`run-20261112-p4b`；G0/G1/G2/G3/G4/G5 全通（首条全六道机器门禁的 run）。

| 项 | 动作 | 证据 |
|---|---|---|
| 新增 G4 脚本 | `.trae/skills/dreamos-dev/scripts/g4_check.py`：按 `gates.yaml` 的 `G4.dimensions` 逐维判定 `evidence.json`，要求 `command + exit_code + 关键输出`，不适用须 `skip_reason` | 负向三例 `bad_exit=1 missing_dim=1 no_file=2`；正向 `ok: true` |
| 门禁校准 | `gates.yaml` G4：`fail_open: true → false`，补 `checker`，头部注释标注 G4 已脚本化 | `fail_open= False \| status= enabled \| checker= scripts/g4_check.py \| dims= 5` |
| 契约扩展 | `run.schema.json` 的 `artifacts` 允许 `evidence`（保持 `additionalProperties: false`），G0 `schema_valid` 通过 | G0 `ok: true` |
| 回归 | 存量 `run-20261112-p4a` 上 G0/G1/G2/G3/G5 全 ok；`check:boundary` 基线不变（fs=41 / child_process=31） | 五道门禁 True + boundary OK |

**口径**：G4 脚本化只对新增 run 生效，存量 run 不回补 `evidence.json`（已在 `gates.yaml` note 注明）。
**遗留**：G4 的 `evidence_commands` 仍是「可选项清单」，尚未按 run 类型（前端/后端/治理）自动选必跑集——待真实 run 样本足够后再定矩阵。

---

### 11.30 T-D0 交付（DSH 子 Agent 事实核实，2026-11-12）

> run：`run-20261112-td0`；G0-G5 全通。只改 SPEC 状态与证据，不改生产代码。

**结论**：8 个 subagent **全部落地且接线可达**；46 的「DSH 当前没有 subagent 概念」是 2026-09-24 的基线自述，已被后续实现取代。

| 层 | 事实 | 证据 |
|---|---|---|
| 契约 | `SubagentOutput` v0.3：`module/summary/signals/charts/raw_data` + `confidence/reasoning_chain/evidence_refs/artifact_uri` | `subagent_types.py` L46-L77 |
| 注册 | `SUBAGENT_REGISTRY_CONFIG` 恰好 8 条（technical/sentiment/macro/flow/valuation/onchain/risk/portfolio），`create_subagent_nodes` / `register_subagents` / `register_subagents_with_bailian` 可用；risk 为纯算法不注入 LLM（HC-3），异常一律 FAIL-OPEN | `subagent_registry.py` L31-L112、L319-L389 |
| 执行 | 8 个 `handle_*_agent(params) -> dict` 一一对应 | `technical_agent.py` L148、`sentiment_agent.py` L130、`macro_agent.py` L148、`flow_agent.py` L164、`valuation_agent.py` L148、`onchain_agent.py` L162、`risk_agent.py` L368、`portfolio_agent.py` L302 |
| 接线 | `IN_PROCESS_HANDLERS` 8 个 `subagent.*` → `HANDLER_TO_SHELL_ID` 8 条 → `HANDLER_TO_ROLE` 全为 `research`；前端 `dsh_adapter.py` 以 `handler_name` 调 `call_handler`（经 `ShellHandleManager` 单例，transport=in-process） | `dsh_frontend_bridge.py` L38-L79、L1372-L1400；`dsh_adapter.py` L56-L58 |
| 测试 | 5 个文件 83 例，exit 0：`test_subagent_types`(9) / `test_subagent_registry_m3`(13) / `test_e2e_subagent_aggregation` / `test_technical_agent` / `test_risk_agent` | `python3 -m pytest ... -q` → `collected=83 exit=0` |

**口径（防过度声明）**：

1. 这 8 个是 **C 层交易域分析执行者**（技术面/情绪面/宏观/资金/估值/链上/风险/组合），不是开发域执行者；SPEC 的 `DEV-*` 节点族仍由 `dreamos-dev` + owner SKILL 承担。
2. 按 §1.2 与 46 §1.4 的既有契约，它们是**一次性隔离执行**（独立上下文、只回 `SubagentOutput` 摘要、之间不通信），**不支持 Thread 多轮续跑**；续跑能力属 `46-DSH架构` 主线设计的升级项，不在本轮范围。
3. 角色恒为 `research`（只读），不参与裁决（裁决在 A 层门禁/人工）。

**遗留**：`register_subagents*` 目前依赖 `dreamos.registry.node_registry`，若 `dreamos/` 归档后不可导入则返回 0（FAIL-OPEN 静默）——这只影响 NodeRegistry 注册路径，不影响 IPC/壳层调用路径；后续如需可观测性应补一条注册计数日志。

---

### 11.31 B1-B3 交付（DSH 桥云端通路，2026-11-12）

> run：`run-20261112-b1`；G0-G5 全通。目标：云端（最终主要运行地）不再依赖本地 spawn 解释器。

**实测结论（先纠正一条旧判断）**：`1-ARCHITECTURE/dreamos/` **目录仍存在**（并非已归档），`orchestrator` 可真实运行；但其单次调用会触发交易域监控（马丁币种池、信号扫描、持仓管理），**耗时 > 15s**，必然撞上前端 15s 超时。因此「orchestrator 恒降级」的判断不成立，改为「可运行但需要异步化」。

| 项 | 交付 | 位置 |
|---|---|---|
| B1 HTTP 出口 | 新增 `execute_http_server.py`：`GET /health`（bridge 可用性 + capability 清单）、`POST /execute`（`{capability,payload,trace_id}` → 复用 `34-core` 的 `call_handler`，**与本地 IPC 同一 dispatcher**）；统一信封回显 `trace_id`；`bridge_unavailable` 503、`bad_request` 400、未知 capability `not_found` 200；零新增依赖（stdlib `http.server`） | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/execute_http_server.py` |
| B2 去硬编码 | **14 处** `/opt/anaconda3/bin/python3` → `COGNITIVE_PYTHON \|\| PYTHON \|\| 'python3'`，`grep -rn "/opt/anaconda3" src` 归零。库层 8：dsh 引擎、认知客户端、案例库客户端、进化 agent、认知上下文抓取、认知上下文构建、用户记忆客户端、知识入库；路由层 5：cognitive/unified、cognitive/knowledge、docs/index、docs/sync、skills/index；另有 agent/mcp-client | `3.1-FRONTEND/src/lib/**`、`3.1-FRONTEND/src/app/api/**` |
| B3 显式原因码 | dreamos 根缺失分支由 `dreamos_root_not_found` 改为 `dreamos_archived`（结构性归档 ≠ 运行时故障），并补分支单测 | `34-前端应用训练系统/core/dsh_frontend_bridge.py` L269-L275 |
| 测试 | 新增 `test_execute_http_server.py` 6 例（health / not_found+trace / dreamos 分支 / bad_json 400 / 缺 capability 400 / 未知路径 404） | 同上目录 |

**验收证据**：`pytest test_execute_http_server.py` 6 passed；`npx tsc --noEmit` exit 0；`npm run test` 全量通过；`check:boundary` fs=41/child_process=31 不变；`check:contracts` 4 passed。

**遗留（按优先级）**：

1. ~~`/execute` 尚未接入部署与鉴权（云端需要 `DSH_API_BASE` + 反代 + 令牌），HTTP 分支当前只被单测覆盖~~ → **已接，见 §11.34**。
2. ~~`orchestrator` 需要异步化（长任务 + 单据回传）才能走 HTTP 同步出口；当前前端 15s 超时会降级~~ → **已异步化，见 §11.34**。
3. ~~`src/lib/agent/mcp-client.ts` 的 `DEFAULT_ARGS` 仍写死本机绝对路径~~ → **已修，见 §11.33**。
4. ~~DSH 引擎的 spawn 回退分支仍无专属测试（超时 / 非零退出 / ENOENT 三种）~~ → **已补，见 §11.33**。

---

### 11.32 C 端交付（剩余流式/命令式组件审计，2026-11-12）

> run：`run-20261112-c1`；G0-G5 全通。范围：6 个刻意留到最后的组件，只查「重连」与「状态一致性」。

**审计结论**：这 6 个组件**没有一个直接用 `EventSource`**，因此不存在重复订阅/双连接；SSE 已全部收口在 `task-stream-manager`（切页不断流、generation 防串流）与 `monitor-stream-manager`（引用计数 + id 去重 + 退避）。

| 组件 | 取数/接流 | 清理 | 竞态 | 重连 | 测试 | 结论 |
|---|---|---|---|---|---|---|
| ChatPanel | `fetch` + `task-stream-manager` 单例 | 无需卸载清理（流走模块单例） | `startTaskStream` 先 abort 旧连接 + generation | 不自动重连（by design） | 无专属测试 | 无缺陷 |
| AgentChatPanel | `useChat`（ai-sdk） | useChat 自带 | 依赖 sendMessage 串行 | 无（库默认） | 无 | 无缺陷，升级需换 transport |
| SteerPanel | `fetch` 提交 | 无 effect 取数 | `submitting` 串行化 | 不适用 | 无 | 无缺陷 |
| BACTimeline | `useEffect` + `api.get` | `cancelled` 守卫 | 单次挂载取数 | 不适用 | **本轮新增** | 无缺陷 |
| GlobalSearchDialog | 防抖 + `api.get` | 清 timer | **原缺旧响应守卫 → 已修** | 不适用 | **本轮新增** | 已修复 |
| useTokenMonitor | 定时器 + `monitor.stop()` | 有（含 `monitorRef`） | 单实例 | 不适用 | 无 | 无缺陷；`TokenMonitorProvider` 定义但未挂载（P2 死代码） |

**本轮唯一真实缺陷**：GlobalSearchDialog 的相似案例分区没有请求作废机制——输入 "a" 后再输入 "ab"，若 "a" 的响应后到，会覆盖 "ab" 的结果，用户看到与当前关键词不匹配的案例。修复为在防抖 effect 内加 `cancelled` 守卫（query/moduleFilter/open 变更即作废旧请求）。

**新增测试（此前这些组件测试覆盖为 0）**：

- `GlobalSearchDialog.test.tsx`：构造「慢响应后到」的乱序场景，断言旧结果不覆盖新结果。
- `BACTimeline.test.tsx`：请求未返回即卸载，断言返回后无状态写入、无 `console.error`。

**证据**：`npx tsc --noEmit` 0；`npm run test` **86 套件 863 例全绿**（+2 套件/+2 例）；`check:boundary` fs=41/child_process=31 不变；`check:contracts` 4 passed。

**遗留**：

1. ~~`TokenMonitorProvider` 未被任何布局挂载，与 `dashboard/token-monitor` 页面里的 `useTokenMonitor` 并存——现在不冲突，但将来一挂载就会双轮询，需二选一~~ → **已挂载且已消除双轮询风险，见 §11.35**。
2. `AgentChatPanel` 依赖 ai-sdk 默认 transport，断网后不会续流（不做重连是当前明确选择，若产品要求需换自研 transport）。
3. `BACTimeline` 只有 `cancelled` 守卫，请求本身未取消（无 `AbortController`），仅浪费一次已发出的请求。

---

### 11.33 遗留项 #3/#4 交付（路径去硬编码 + spawn 失败分支测试，2026-11-12）

> run：`run-20261112-r3r4`；G0-G5 全通。范围仅限 §11.31 遗留第 3、4 条。

| 项 | 交付 | 位置 |
|---|---|---|
| #3 路径去硬编码 | `DEFAULT_ARGS` 与 `PYTHONPATH` 不再写死 `/Users/zhangjiangtao/...`：新增 `REPO_ROOT = DREAMBUDDY_ROOT \|\| path.resolve(process.cwd(), '..')`，脚本路径 `COGNITIVE_MCP_SERVER \|\| REPO_ROOT/4-MEMORY/9-工具与接口/cognitive_mcp_server.py`；沿用仓库既有的 `resolve(cwd,'..')` 约定（同 `jsonl-writer.ts`） | `3.1-FRONTEND/src/lib/agent/mcp-client.ts` L14-L32 |
| #4 失败分支测试 | 新增 3 例：①超时 → `timeout_15000ms` + `SIGKILL`；②非零退出且无输出 → `exit_code_1`；③ENOENT → `spawn_failed: ...ENOENT` | `3.1-FRONTEND/src/lib/__tests__/dsh-execution-engine.http.test.ts` |
| 缺陷修复（#4 暴露） | close 回调原先忽略退出码：非零退出且 stdout 为空时把 `'{}'` 当信封返回（`ok` 为 `undefined`、无 `degraded`）。现改为「无有效 JSON 且 `code !== 0` → `degraded: true, error: exit_code_N`」；有合法输出时仍以上游信封为准 | `3.1-FRONTEND/src/lib/dsh-execution-engine.ts` L212-L228 |

**证据**：`npx tsc --noEmit` exit 0；目标套件 6 passed（原 3 + 新增 3）；`mcp-client.test.ts` 6 passed（真实 spawn 冒烟）；`check:boundary` fs=41/child_process=31 不变。

---

### 11.34 遗留项 #1/#2 交付（`/execute` 鉴权与部署口径 + orchestrator 异步化，2026-11-12）

> run：`run-20261112-r1r2`；G0-G5 全通。范围仅限 §11.31 遗留第 1、2 条。

#### #2 orchestrator 异步化（先做，因为 #1 的 HTTP 出口受它约束）

| 层 | 改动 | 位置 |
|---|---|---|
| 桥 | 拆出 `_run_orchestrator_cycle()`（原同步主体，语义不变）；`_handle_orchestrator_v2` 增加 `async=True` / `mode="async"` 分支：建作业 → daemon 线程执行 → 立即返回 `{status:"accepted", job_id}` | `34-前端应用训练系统/core/dsh_frontend_bridge.py` |
| 桥 | 新增内联 capability `orchestrator.status`：`pending` → `{status:"pending"}`；`done` → 把结果放进 `data.output`，使 `call_handler` 透传后与**同步调用完全同构**（`{ok, output}`） | 同上（`IN_PROCESS_HANDLERS` / `HANDLER_TO_SHELL_ID` / `HANDLER_TO_ROLE` 三处登记） |
| 桥 | 作业表 `_ORCH_JOBS` + `threading.Lock`，完成后保留 1h（`_ORCH_JOB_TTL_S`），每次提交前惰性清理；worker 捕获异常也落库，前端不会永久 pending | 同上 |
| 前端 | `callDshHandler('orchestrator', ...)` 在配置了 `DSH_API_BASE` 时改走「提交 → 每秒轮询 `orchestrator.status`」；总预算 `DSH_ORCHESTRATOR_TIMEOUT_MS`（默认 120s），轮询间隔 `DSH_ORCHESTRATOR_POLL_MS`（默认 1s）；HTTP 不可用仍回退本地 spawn（原降级语义保留） | `3.1-FRONTEND/src/lib/dsh-execution-engine.ts` |

**为什么必须异步**：`OrchestratorV2.run_cycle()` 实测 >15s 且触发交易域副作用（马丁币种池/信号扫描/持仓管理），同步塞进 `DSH_API_BASE` 的 15s HTTP 超时必然降级。异步化后单次 HTTP 请求都是毫秒级，长任务在桥内后台线程跑。

#### #1 `/execute` 鉴权与部署

| 项 | 实现 |
|---|---|
| 鉴权 | `DSH_EXECUTE_TOKEN` 设置后，`POST /execute` 必须带 `Authorization: Bearer <token>`；缺失/错误 → **401 unauthorized** + `WWW-Authenticate: Bearer`；比较用 `hmac.compare_digest`（常量时间）；token 每次请求读 env，便于本机切换与测试 |
| 探活 | `GET /health` 不鉴权（供负载均衡），返回 `{ok, service, bridge, auth:"bearer"\|"disabled", capabilities}` |
| 前端 | `DSH_API_TOKEN` 设置时自动附 `Authorization` 头；收到 401/403 时**不回退 spawn**，直接返回 `{ok:false, degraded:true, error:"unauthorized"}`——鉴权失败是配置错误，静默降级会掩盖问题 |
| 部署口径 | ① `DSH_EXECUTE_TOKEN` **必须**非空（空值仅限本机开发，`/health` 显示 `auth:"disabled"`）；② 反代前置 TLS，`/execute` 不对公网裸暴露；③ 前端 `DSH_API_BASE` 指向反代地址、`DSH_API_TOKEN` 与桥同值；④ 启动 `DSH_EXECUTE_TOKEN=... python3 execute_http_server.py --host 127.0.0.1 --port 8791`；⑤ 探活 `GET /health` 必须 `ok:true` 且 `bridge:true` |
| 零新依赖 | 仍只用 stdlib（`http.server` / `hmac` / `threading` / `uuid`） |

#### 验收证据

- `pytest test_execute_http_server.py -q` → **14 passed**（原 6 + 鉴权 4 + 异步 3 + 同步不回退 1），exit 0。
- `npx jest src/lib/__tests__/dsh-execution-engine.http.test.ts` → **9 passed**（原 6 + 异步轮询 1 + 401 不回退 1 + Bearer 头 1）。
- `npx tsc --noEmit` → exit 0；全量 jest 86 套件 **869 passed**（基线 866，+3）；`check:boundary` fs=41/child_process=31 不变。

#### 已知边界

- 作业表是**进程内单例**：多 worker/多实例部署时 `orchestrator.status` 只能命中提交它的那个进程；需要跨实例时再换 Redis/DB 作业表（当前单实例，不做）。
- async 仅在前端配置 `DSH_API_BASE` 时启用；纯本地（无 `DSH_API_BASE`）仍走同步 spawn，15s 超时问题保留（本地为开发态）。
- 前端只有 orchestrator 走异步；其余 capability 仍是一问一答同步，超时仍为 15s。

---

### 11.35 遗留项 #5 交付（TokenMonitorProvider 全局挂载，2026-11-12）

> run：`run-20261112-r5`；G0-G5 全通。范围仅限 §11.32 遗留第 1 条「Provider 与页面 hook 二选一」。

**方案选择**：选 Provider 侧挂载，但把 `useTokenMonitor` 改成 context-aware —— 否则一旦挂载 Provider，页面内的 `useTokenMonitor` 会再建一份实例，直接变成双轮询（正是 §11.32 预留的隐患）。

| 层 | 交付 | 位置 |
|---|---|---|
| Context 下沉 | `TokenMonitorContext` 从 Provider 文件移到 hook 文件并导出；`useTokenMonitor` 先 `useContext`，命中即返回全局实例，未命中才走内部实现 | `3.1-FRONTEND/src/lib/use-token-monitor.ts` L54-L74 |
| 防双轮询 | 内部实现的初始化 effect 增加 `if (!enabled) return`：Provider 内的消费者只读 Context，不 `new TokenMonitor`、不 `start()`、不留 interval（hooks 调用顺序仍无条件） | 同上 L76-L118 |
| Provider 收口 | 复用导出的 Context；删掉无效的 `useMemo(() => monitor, [monitor])`；导出 `DEFAULT_TOKEN_MONITOR_CONFIG` 与 `fetchTokenBalance`（当时为页面 mock 上移，**§11.36 已改为真实接口**） | `3.1-FRONTEND/src/lib/token-monitor-provider.tsx` |
| 挂载点 | `dashboard/layout.tsx` 最外层包 `<TokenMonitorProvider>`，侧栏与 main 同域共享一个监控器 | `3.1-FRONTEND/src/app/dashboard/layout.tsx` L64-L123 |
| 页面改造 | `/dashboard/token-monitor` 由 `useTokenMonitor` 改为 `useTokenMonitorContext()`，不再自建实例 | `3.1-FRONTEND/src/app/dashboard/token-monitor/page.tsx` |

**验收证据**

- `npx tsc --noEmit` → exit 0。
- 新增 `src/lib/__tests__/token-monitor-provider.test.tsx` → **2 passed**（当时；§11.36 扩至 4 例）：①Provider 内两个消费者（各自用 `useTokenMonitorContext` 与 `useTokenMonitor`）共享实例——`TokenMonitor` 构造 **1 次**、`checkNow` 引用唯一；②Provider 外调用仍自建 1 次（向后兼容）。
- 全量 jest → **87 套件 871 passed**（基线 86/869，+1 套件/+2 例）；`check:boundary` fs=41/child_process=31 不变；`check:contracts` 4 passed。

**已知边界**

- `fetchTokenBalance` 当时仍是静态 mock → **已接真实接口，见 §11.36**。
- 监控器生命周期 = dashboard 布局生命周期：进入 dashboard 立即拉一次 + 5min 轮询，离开 dashboard 自动 `stop()`。
- 本轮只做挂载，未新增任何消费 UI → **侧栏徽标已在 §11.36 接入**。

---

### 11.36 遗留补齐：真实余额接口 + 侧栏徽标（2026-11-12）

> run：`run-20261112-r5b`；G0-G5 全通。补齐 §11.35 的两条已知边界。

| 项 | 交付 | 位置 |
|---|---|---|
| 真实余额来源 | 数据源本就是 `prisma.creditsAccount`（`balance/totalEarned/totalSpent`，充值链路 `/api/recharge` 已维护），缺的只是读出口。新增 `GET /api/token/balance`：未登录 401；无账户返回全 0；异常 500 | `3.1-FRONTEND/src/app/api/token/balance/route.ts` |
| `fetchTokenBalance` | 由静态 mock 改为 `api.get('/api/token/balance')`，缺字段回填 0；错误向上抛给 `TokenMonitor.handleError`（状态转 `error`、5s 后自动重试），不静默吞掉 | `3.1-FRONTEND/src/lib/token-monitor-provider.tsx` |
| 侧栏徽标 | 新增 `SidebarTokenMonitor`（layout 内私有组件）消费 `useTokenMonitorContext`；展开态渲染 `TokenMonitorBadge`（`size="sm"`），收起态渲染等级色圆点；点击进入 `/dashboard/token-monitor` | `3.1-FRONTEND/src/app/dashboard/layout.tsx` |
| 防误导 | 徽标在 `state.lastChecked === 0`（首次成功取数前 / 401 未登录）不渲染，避免展示 0 tokens | 同上 |

**验收证据**

- `npx tsc --noEmit` → exit 0。
- `token-monitor-provider.test.tsx` → **4 passed**（原 2 + `fetchTokenBalance` 走接口并映射字段 + 缺字段回填 0）。
- 全量 jest → **87 套件 873 passed**（基线 87/871，+2）；`check:boundary` route 111→112、fs=41/child_process=31 不变；`check:contracts` 4 passed。

**已知边界**

- `/api/token/balance` 是 cookie 会话鉴权（`auth()`），未登录 401 → 徽标不渲染。**决策保留**（dashboard 需登录，不做匿名口径），见 §11.37。
- 无 API 路由单测 → **已在 §11.37 补齐 4 例三态测试**。
- 徽标无充值入口 → **已在 §11.37 接入低余额充值入口**。
- 积分口径与阈值 → **已在 §11.37 校正**。

---

### 11.37 剩余边界清零（2026-11-12）

> run：`run-20261112-r5c`；G0-G5 全通。逐条处置 §11.36 的四条已知边界。

| # | 边界 | 处置 |
|---|---|---|
| 1 | 未登录 401 → 徽标不渲染 | **决策保留**：dashboard 全站需登录，匿名展示余额需新增公开读接口，收益不抵成本；路由测试已锁定 401 语义 |
| 2 | 无 route handler 单测 | **补齐** `src/app/api/token/balance/__tests__/route.test.ts` 4 例：未登录 401（且不查库）、正常三字段 + `findUnique` 入参断言、无账户全 0、prisma 异常 500。jsdom 无 Web `Response`，故 `jest.mock('next/server')` 把 `NextResponse.json` 降级为 `{status, body}` |
| 3 | 积分口径 / 阈值失真 | 余额单位本就是 `creditsAccount` 的积分，文案 `tokens` → `积分`（Badge + Panel）；`dailyQuota` 50000→**5000**（对齐专业包）作为健康刻度 → `<250` 严重、`<500` 偏低、`<2500` 中等、`≥2500` 充足；`recoveryThreshold` 20% = 1000 积分恢复 |
| 4 | 徽标无充值入口 | 侧栏：低余额/严重/已降级时徽标下方出现「积分不足 · 去充值」，收起态圆点直接链到 `/recharge`；详情页：同条件显示横幅 + 「去充值 →」。入口复用既有 `/recharge` 页与套餐（500/2000/5000/15000 积分） |

**验收证据**

- `npx tsc --noEmit` → exit 0。
- 路由测试 → **4 passed**；全量 jest（`--forceExit`）→ **88 套件 877 passed**（基线 87/873，+1 套件/+4 例）。
- `check:boundary` → route 112、fs=41 / child_process=31 不变；`check:contracts` 4 passed。

**已知边界**

- `dailyQuota` 字段名沿用原义（百分比基准），当前语义是「健康刻度 5000 积分」，已在 Provider 注释写明；若后续有真实「每日预算」需求需改名。
- 充值入口只做跳转，不内嵌支付；`/recharge` 仍是模拟支付。
- 历史套件存在未释放句柄，全量 jest 需 `--forceExit`（非本轮引入，未处理）。

---

### 11.38 技术文档落地核对（审计，2026-11-12）

> 只做「文档声明 ↔ 代码事实」核对与文档修正，无功能改动。

| 区域 | 核对点 | 结论 |
|---|---|---|
| DSH 桥 §11.33/§11.34 | Bearer 常量时间比较、401 + `WWW-Authenticate`、`/health.auth`、async 提交 + `status` 轮询、`data.output` 同构、进程内作业表 TTL、前端 `DSH_API_BASE` 门控、401 不回退、`exit_code_N`、`mcp-client` 无绝对路径 | **PASS**（逐条有 file:line 证据） |
| Token 监控 §11.35-§11.37 | Context 下沉与 `enabled` 门控、Provider 挂载、页面改 context、`/api/token/balance` 三态、积分文案、`dailyQuota=5000`、侧栏徽标与充值入口、路由/Provider 测试 | **PASS** |
| 文档引用路径 | SPEC 中 32 个仓库相对路径 | 0 个真实缺失（11 个是 `<run_id>` / `**` 模板或已声明的双位置漂移） |
| run 七件套 | `run-20261112-r1r2 / r3r4 / r5 / r5b / r5c` | 均 7 文件齐全 |
| 实测复核 | jest 3 套件 17 例（9+4+4）、pytest 14 例、全量 88/877 | 与文档记录一致 |
| 文档修正 | §11.35 「TODO 指向尚未实现接口」陈旧、测试例数未标注后续扩展、`layout.tsx` 行号范围 | 已修正 3 处 |

**核对当时登记、随后清零（见 §11.39）**

- ~~§11.32 遗留 2：`AgentChatPanel` 断网不续流~~ → 已交付：断网中断标记 + 恢复联网自动重试一次。
- ~~§11.32 遗留 3：`BACTimeline` 无 `AbortController`~~ → 已交付：卸载即 `abort()` 在途请求。
- ~~§2 GAP-2：`trace_id` 透传 / `ApiEnvelope` / `SSEEventV1` 待建~~ → 已交付：后两者早已落地（T-C2/T-C3），`trace_id` 全链透传本轮补齐。

---

### 11.39 三项遗留边界交付：断网续流 · 请求可中断 · trace_id 全链透传（2026-11-12）

> run：`run-20261112-r6`（`model_id=human`）；G0-G5 全通。

| # | 原缺口 | 交付 | 证据 |
|---|---|---|---|
| 1 | `AgentChatPanel` 断网不续流（原记为「设计选择」） | 流因网络中断（`status='error'`）时打中断标记；监听 `offline`/`online`，恢复联网后自动 `regenerate()` **一次**（`retriedRef` 防重复，新一轮 `submitted/streaming` 时重置；`messages` 判空 + `catch` 兜底）；`online=false` 时显示「网络已断开…恢复联网后将自动重试」 | `AgentChatPanel.online.test.tsx` 3 passed（自动重试 1 次且不重复；`status=ready` 不触发；`messages` 为空不调用） |
| 2 | `BACTimeline` 无 `AbortController`，卸载只做 `cancelled` 守卫 | 新增 `AbortController`，卸载时 `controller.abort()`；`api-client` 支持调用方 `signal`（与内部超时共用同一 fetch signal，卸载中断报「请求已取消」而非「请求超时」） | `BACTimeline.test.tsx` +1（卸载后 `signal.aborted===true`）；`api-client.test.ts` +2（外部 abort / 正常透传） |
| 3 | §2 GAP-2：`trace_id` 全链透传 | ①`api-client`：新增 `traceId` 选项，请求自动注入 `X-Request-Id`，响应回显优先、缺省回退本地值，错误也带同一 `traceId`；②`/api/dsh/execute`（浏览器侧代理）：入站 `X-Request-Id`/`X-Trace-Id` → `body.trace_id` → 上游请求头 → 上游响应 `trace_id` → 响应头，503/400/504 均回显；③`dsh-execution-engine`：`callDshHandler` 只解析一次链路 ID，HTTP（请求头 + `body.trace_id`）与 IPC（spawn args JSON 的 `trace_id`）共用 | `dsh execute route.test.ts` 5 passed；`api-client.test.ts` +2；`dsh-execution-engine.http.test.ts` +3（HTTP 有/无 trace、IPC 有 trace） |

#### 11.39.1 功能链路梳理（逐环核实）

**链路 A｜断网续流**

`handleSend` → `sendMessage` → `DefaultChatTransport` POST `/api/agent/chat`（无状态：只吃 `messages[]`）→ `streamText` 流式 → `useChat.status` 因网络中断变 `error` → 浏览器 `offline`（UI 提示）→ `online` → `messages.length>0` 时 `regenerate()` 一次 → 重新 POST 同一路由 → 流恢复。

- 断点（已修）：`regenerate()` 在 `messages` 为空时抛 `message not found`；已加判空 + `.catch()` 兜底。
- 重放安全性：已确认 `/api/agent/chat` 不持久化会话（纯 `messages[]` 入参），重试不会产生服务端重复状态。

**链路 B｜请求可中断**

`BACTimeline` 挂载 → `api.get('/api/compression/stats', undefined, { signal })` → `requestEnvelope` 把外部 signal 转发到内部 controller → `fetch` → 卸载 `abort()` → `AbortError` → `ApiException('请求已取消')` → 组件 `catch` 静默 + `cancelled` 守卫不再 setState。

- 上游契约已核：`/api/compression/stats` 返回 `{ success, data: { stats, health, sessions } }`，`api.get` 解包为 `data`，与组件消费的 `stats` / `sessions` 一致。

**链路 C｜trace_id 全链**（两条 DSH 通路都补齐）

- 浏览器侧代理：`api-client`（注入 `X-Request-Id`）→ `/api/dsh/execute` → 上游 `/execute`（请求头 + `body.trace_id`）→ 上游回显 `trace_id` → 响应头 `X-Request-Id` → `envelope.trace_id`。
- 服务端真实通路（生产在用）：Next 入站 `X-Request-Id` → `dsh-execution-engine.callDshHttp` 的 `inboundTraceId()`（`next/headers`）→ 上游请求头 `X-Request-Id` + `body.trace_id` → `execute_http_server.dispatch` 原样回显 `trace_id`。
- **断点（本轮发现并修复）**：`callDshHttp` 此前**直连上游且完全不带 trace**，而 `/api/dsh/execute` 当前无前端调用方（只有测试）——若只改代理路由，真实通路的 trace 会断在第一跳。已补 `inboundTraceId()`（脚本/测试/无请求作用域下 FAIL-OPEN 返回 `undefined`，不改变旧请求形状）。
- **IPC 通路（本地默认模式）**：`DSH_API_BASE` 未配置时 `callDshHttp` 直接返回 `null`，运行时实际走 `spawn dsh_adapter.py`。本轮把同一 `trace_id` 写进 spawn 的 args JSON（`dsh_adapter` 原样透传给 `call_handler`），使默认模式也不丢链；`callDshHandler` 只解析一次链路 ID，HTTP / IPC 共用。

**明确未做（避免误读）**

- 「续流」是**新一轮请求**级别的恢复，不是 HTTP/SSE 断点续传：AI SDK 5 的 `resume` 需服务端可恢复流存储（Redis 等），属 §12「不新建基础设施」，故不做。
- `ApiEnvelope` / `SSEEventV1` 未改：二者在 T-C2/T-C3 已交付，本轮只补 `trace_id` 链路。
- `trace_id` 只覆盖「前端 → Next 路由 → DSH 上游」这条链；其余路由仍由 `api-client` 单端生成（响应头未回显时取本地值，行为等价）。

**验证**：`npx tsc --noEmit` exit 0；全量 jest **90 套件 893 例全绿**（基线 88/877，+2 套件/+16 例）；`check:boundary` route 112、fs=41/child_process=31 不变；`check:contracts` 4 passed。

#### 11.39.2 链路 C 本地活体验证（2026-11-13，非 mock）

起本地 `execute_http_server.py` 逐层打真（`DSH_EXECUTE_TOKEN` 开启，验证含鉴权分支）：

```
DSH_EXECUTE_TOKEN=local-dev-token python3 \
  1-ARCHITECTURE/dream-harness-bridge/packages/python-server/execute_http_server.py \
  --host 127.0.0.1 --port 8791
```

| 层 | 观测 | 结果 |
|---|---|---|
| `/health` | `{ok:true, bridge:true, auth:"bearer", capabilities:18}` | PASS |
| 鉴权 | 无 `Authorization` → 401；带 Bearer → 200 | PASS |
| 上游回显 | `POST /execute` 带 `body.trace_id` → 原样回显（含 `not_found` 错误分支） | PASS |
| 浏览器代理 | tsx 直调真实 route handler：`GET configured:true`；入站 `X-Request-Id` **优先于** `body.trace_id`；无链路 ID 时不注入空响应头 | PASS |
| orchestrator 异步 | 提交 + 轮询 89.4s → `{ok:true, cycle-2899, status:COMPLETED, selection 存在}` | PASS（修复后） |
| IPC 分支 | `python3 scripts/dsh_adapter.py technical '{"trace_id":"…"}'` → `{ok:true, degraded:false}` | PASS |

**活体暴露并已修的三处断点（均为此前单测未覆盖的契约错位）**

| # | 断点 | 后果 | 修复 |
|---|---|---|---|
| 1 | 轮询写 `orchestrator.status`（点号），后端 `HANDLER_TO_SHELL_ID` 只有 `orchestrator_status`（下划线） | 云端异步路径恒 `unknown handler` → `ok:false` | 前端改下划线；测试断言同步 |
| 2 | 作业完成时 `call_handler` 会剥掉 `status`（`{ok,output:{ok,output:{…}}}`），前端死等 `status==='done'` | 必然空转到 120s 超时 | 改以「output 自带布尔 `ok`」判终态 |
| 3 | `/api/dsh/execute` 代理不带 `DSH_API_TOKEN` | 云端开鉴权后一律 401 | 与 `callDshHttp` 对齐补 Bearer，并加 1 例测试 |

**副作用提示**：`orchestrator` 能力会真实跑一个交易周期（含持仓管理、下单尝试），**不可当作只读探针**。本次实测 `平仓:0 加仓:0`，TP/SL 设置返回 422（与链路 C 无关）。探活请用 `/health` 或 `orchestrator_status` + 不存在的 `job_id`。

**验证**：`tsc` exit 0；全量 jest **90 套件 894 例全绿**（+1 例）；`check:boundary` route 112、fs=41/child_process=31；`check:contracts` 4 passed。

---

## 12. 不做清单

- 不新增架构层；`DREAM` 仅为文档代号。
- 不把 `1-ARCHITECTURE/dreamos/` 重新当作运行时底座（目录仍在，仅存量能力可用；不新增依赖）。
- 不让 C-Drive 直接改代码或改交易链；执行与验收分离。
- 不把 48 涌现模块当驱动层。
- 不把脑暴双路径设为默认，也不让它做裁决。
- 不在提示词里实现门禁判定。
- 不 vendor 外部开发框架作为运行时。
- 不新建与 SPEC A-C 重叠的基础设施（事件总线 / 状态库 / 计划格式 / ID 体系 / 鉴权中间件）。

---

## 13. 开放问题（默认决策）

| # | 问题 | 默认 |
|---|---|---|
| O-D1 | 「无模型禁止开发」是否允许纯手写例外 | 不允许；人工改动也挂 `run_id`，`model_id=human` |
| O-D2 | `.runs/` 是否入库 | 不入库 |
| O-D3 | 元 SKILL 命名 | `dreamos-dev`（注册前查重） |
| O-D4 | 首批是否启用 DSH 子 Agent | 已核实（§11.30）：8 个全部落地，默认只作只读研究执行者（role=research），不参与裁决、不用于开发域执行 |
| O-D5 | 48 度量是否参与 G4 | 只作参考，不参与判定 |

---

## 14. 证据索引

| 事实 | 位置 |
|---|---|
| 新 SACG 与旧口径作废 | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md` §1.1-§1.2 |
| C-Drive 双语义 | 同上 L121-L123 |
| C-Drive 代码实现 | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/c_drive_agent.py` |
| C-Drive 前端协调器 | `3.1-FRONTEND/src/lib/c-drive.ts` L1-L28、L40-L72 |
| 人工介入 | `3.1-FRONTEND/src/components/features/chat/SteerPanel.tsx` L9 |
| Router/Watchdog 映射 | `1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md` L25、L55、L59 |
| 48 verdict | `48-涌现架构/README.md` L23-L27、L56 |
| 脑暴编排器与灰度 | `52-lobehub协议集成/orchestrator/`、`0-系统文档管理/INDEX.md` L196-L197 |
| L0 壳与角色 | `47-MCP管理系统/registry/mcp_capabilities.yaml` L44-L580 |
| DSH 无 subagent 的历史自述（2026-09-24 基线，已被实现取代） | `1-ARCHITECTURE/dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md` §2.2 |
| 8 个 subagent 契约 / 注册 | `1-ARCHITECTURE/dream-harness-bridge/packages/python-server/subagent_types.py` L46-L77、`subagent_registry.py` L31-L112 |
| 8 个 subagent 执行入口 | 同目录 `technical_agent.py` L148、`sentiment_agent.py` L130、`macro_agent.py` L148、`flow_agent.py` L164、`valuation_agent.py` L148、`onchain_agent.py` L162、`risk_agent.py` L368、`portfolio_agent.py` L302 |
| 8 个 subagent 前端接线 | `34-前端应用训练系统/core/dsh_frontend_bridge.py` L38-L79（`IN_PROCESS_HANDLERS`）、L1372-L1390（`HANDLER_TO_SHELL_ID`）；`3.1-FRONTEND/scripts/dsh_adapter.py` L56-L58 |
| `dreamos/` 已归档 | `1-ARCHITECTURE/dreamos/README.md` L1 |
| 外部调研来源 | Umbrex Stage-Gate Playbook；GitHub Rulesets GA；kiro.dev specs；speckit.org；openhands.dev verification-stack；Aider 架构；arXiv 2608.25202（SDD 成本）；MCP 2026-07-28 RC；Linux Foundation A2A；AGENTS.md 跨工具报告；Anthropic multi-agent research；Cognition 2026 修正；arXiv 2610.08900（verifier 外置）；arXiv 2605.00914 / 2608.00243（debate）；Chroma context-rot |

---

## 15. 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1.0 | 2026-11-12 | 初稿：元 SKILL + 门禁 + SPEC A-C 接线 |
| v0.2.0 | 2026-11-12 | ①取消 D/R/E/A/M 五环表述，`DREAM` 降为文档代号，架构只保留 SACG；②代码核查修正「C-Drive 只有文档」为「已实现、缺开发域语义」；③新增传统工程与 AI 工程实践调研（§3）与 12 条机制采纳表；④新增 GAP-1~6 补齐方案与 DEV 节点族；⑤新增 R9/R10 与 M7/M8；⑥标注 debate 仅生成候选 |
| v0.3.0 | 2026-11-12 | ①新增「复用硬约束」与 §4.2 GAP × SPEC A-C 复用矩阵（3 个完全复用、3 个配置级补齐、0 个新建基础设施）；②新增 §4.3 预补齐最小集 / 工作中再补 / 永不新建三态；③G2 门禁增加「复用盘点」；④P0 增加 T-D5 复用盘点、P1 收窄为最小集；⑤不做清单补充禁止重叠建设 |
| v0.4.0 | 2026-11-12 | ①执行 T-D5：逐条核对 A/B/C 的 26 条任务、22 条目标、10 项门禁、18 类契约，新增 §4.4 实测表；②实测发现 A-C 声明产物 0 存在，"复用"修正为依赖语义；③记录 3 处原文偏差（D1 agent 页面不存在、D2 导航 12 项、D3 边界脚本命名不一致）；④新增 R11 顺序耦合；⑤确认当前可用门禁仅 tsc/build/lint/test 四项 |
| v0.4.1 | 2026-11-12 | 把 D1/D2/D3 修入 SPEC-A/C（v0.1.1）：D1 Agent 页改为新建（UI 复用 `/chat`，`/agent` 无旧路由）；D2 导航口径统一为「12 现存 + Agent = 13」、旧 redirect 5 条；D3 边界门禁统一为 `npm run check:boundary` + `scripts/check-route-boundary.mjs`。§4.4 偏差表加状态列，§8 批次 1 退出条件同步 |
| v0.5.0 | 2026-11-12 | P1/P2 落地：新建 `.trae/skills/dreamos-dev/`（SKILL.md + routing.yaml + contracts 四件 + g0_check.py/g3_check.py）；G0 与 G3 由「文档门禁」变为可执行门禁（JSON 证据 + 退出码，双向实测）；`.runs/` 入 `.gitignore`；新增 §11.1 交付状态表。同步 ARCH-ENGINEERING-MAP v0.1.2（builder 排除 `.arch-map` + 新增 `S.devgate`，orphan=0 且 drift=PASS） |
| v0.6.0 | 2026-11-12 | P3 批次 0（门禁自举）：新增 `g1/g2/g5_check.py`，G0-G5 六道门禁全部可机器判定（G1/G2/G5 由 `pending` 转 `enabled`、`fail_open: false`）；`.runs` 加入 builder 排除项；`run-20261112-p3gate01` 走完 D0→M1 并产出验收包；新增 §11.2 M1-M7 首次实测。RECALL：G1 保留 `skips` 显式跳过通道，避免轻量任务被误杀（R9/M6） |
| v0.6.1 | 2026-11-12 | P3 批次 1-4 验证（只核验不实现）：批次 1/3/4 退出条件全部未达，批次 2 仅 monitor 单例达标；新增 §11.3 验证矩阵与证据行号，明确按 R11 先做批次 1；并标注批次 4 需先为既有 `child_process` 用法建基线白名单 |
| v0.6.2 | 2026-11-12 | P3 批次 1 交付（T-A1/T-A2）：新建 `navigation.ts` 导航单一事实源（13 项）与 `/dashboard/agent`；board 5 页 `git mv` 入壳并做 `min-h-full` 适配；旧 `/board/*` 5 条改 `permanentRedirect` 308（query/params 保留）；`run-20261112-p3b1` 过 G0/G1/G2/G3/G5，tsc 仅 1 条预存错误 |
| v0.6.3 | 2026-11-12 | P3 批次 2 交付（T-A3/T-A4）：新增 `task-stream-manager`（切页不断流）与 `monitor-stream-manager`（3 处 EventSource 合 1，引用计数 + id 去重 + 退避）；ChatPanel 连接迁出组件；删除孤立 `useProactiveSSE.ts`；`run-20261112-p3b2` 过 G0-G3/G5，jest 49 套件 669 例全绿 |
| v0.7.0 | 2026-11-12 | 补记 P3 批次 3-24：域客户端抽取、逐页 `useQuery` 迁移（fundamental 9 面板 / settings 5 面板 / memory 3 视图 / notebook·cycle 3 组件 / reports·governance 2 屏），见 §11.5~§11.27；最终收口 55 套件 584 例、tsc 0、boundary 零增量 |
| v0.8.0 | 2026-11-12 | P4 批次 1（治理固化）：`gates.yaml` 的 `contracts`/`boundary` 由 `pending + FAIL-OPEN` 校准为 `enabled`；registry 注册 `dreamos-dev`（186→187）并 deprecate `dreambuddy-os`（`replaced_by: dreamos-dev`）；漂移检测固化为 `skill_indexer.py detect-drift` 可复现命令 + 落盘 `drift-report.json`（实测 1 条，设计性单位置）；见 §11.28 |
| v0.8.1 | 2026-11-12 | P4 批次 2（G4 脚本化）：新增 `scripts/g4_check.py`，按 `G4.dimensions` 判定 `.runs/<run_id>/evidence.json`（command + exit_code + 关键输出，不适用须 `skip_reason`），G4 `fail_open: true → false`；`run.schema.json` 的 `artifacts` 允许 `evidence`；`run-20261112-p4b` 成为首条 G0-G5 全通 run；存量 run 回归通过。同时决策取消 registry 历史 `path` 重建（路径机器相关，本地/云端互相覆写、重建无收益）；见 §11.29 |
| v0.8.2 | 2026-11-12 | T-D0 交付（DSH 子 Agent 事实核实）：§2 该行由 🟡 争议改为 🟢 已落地——8 个 subagent 契约/注册/执行/接线四层齐全 + 83 例测试通过，46 §2.2 的「无 subagent」为 2026-09-24 基线自述已被实现取代；同时写明三条防过度声明口径（交易域只读、一次性隔离执行、不参与裁决）；§8 P0 / §11.1 / O-D4 / §14 证据索引同步；见 §11.30 |
| v0.8.3 | 2026-11-12 | B1-B3 交付（DSH 桥云端通路）：B1 新增 `execute_http_server.py` 的 `/execute` HTTP 出口（stdlib、复用 `call_handler`、回显 trace_id、health 报 capability 清单）；B2 14 处 `/opt/anaconda3/bin/python3` 改为 `COGNITIVE_PYTHON\|PYTHON\|python3`（grep 归零）；B3 dreamos 缺失分支独立原因码 `dreamos_archived`；纠正「dreamos 已归档 / orchestrator 恒降级」的旧判断（目录仍在、可运行但 >15s 需异步化）；§2 增 python-server 行、§11.1 增 B 行、§12 口径修正；见 §11.31 |
| v0.8.4 | 2026-11-12 | C 端交付（剩余流式组件审计）：6 个组件（ChatPanel / AgentChatPanel / SteerPanel / BACTimeline / GlobalSearchDialog / useTokenMonitor）无一直接用 `EventSource`，无重复订阅；修唯一真实竞态——GlobalSearchDialog 相似案例缺请求作废，慢响应会覆盖新查询；补 2 个此前零覆盖组件的回归测试（乱序响应、卸载后写状态）；jest 86 套件 863 例全绿；见 §11.32 |
| v0.8.5 | 2026-11-12 | 遗留项 #3/#4 交付：`mcp-client.ts` 的 `DEFAULT_ARGS` / `PYTHONPATH` 去本机绝对路径（`REPO_ROOT` + env 覆盖）；DSH 引擎补 3 个 spawn 失败分支测试并顺带修掉「非零退出且空输出被当成功信封」；版本 v0.8.4→v0.8.5；见 §11.33 |
| v0.8.6 | 2026-11-12 | 遗留项 #1/#2 交付：`orchestrator` 异步化（`async` 提交 + `orchestrator.status` 轮询，done 结果经 `data.output` 与同步信封同构；前端仅在 `DSH_API_BASE` 时提交/轮询，总预算 120s）；`/execute` 加 Bearer 鉴权（`DSH_EXECUTE_TOKEN`，常量时间比较，401 不回退 spawn）并写明部署口径；pytest 14 passed、jest 86/869、tsc 0；见 §11.34 |
| v0.8.7 | 2026-11-12 | 遗留项 #5 交付：选定「挂载 Provider」路线，并把 `useTokenMonitor` 改为 context-aware（Context 下沉至 hook 文件并导出；内部 effect 以 `enabled` 门控，Provider 内不建第二实例）——从根上消除双轮询；`dashboard/layout.tsx` 挂载、token-monitor 页改 `useTokenMonitorContext`；新增 2 例单实例测试，jest 87/871、tsc 0、boundary 与 contracts 不变；见 §11.35 |
| v0.8.8 | 2026-11-12 | #5 遗留补齐：新增 `GET /api/token/balance`（读 `prisma.creditsAccount`，401/0 值/500 三态）；`fetchTokenBalance` 由静态 mock 改为真实取数；侧栏新增 `SidebarTokenMonitor`（展开态 Badge、收起态圆点、点击进详情、首次成功取数前不渲染）；新增 2 例契约测试，jest 87/873、tsc 0、boundary fs/child_process 不变（route 111→112）；见 §11.36 |
| v0.8.9 | 2026-11-12 | #5 剩余边界清零：路由三态单测 4 例（mock `next/server` 规避 jsdom 无 `Response`）；积分口径校正（文案 tokens→积分，`dailyQuota` 50000→5000，阈值 250/500/2500）；低余额时侧栏与详情页接入 `/recharge` 入口；未登录 401 明确为设计决策；jest 88/877、tsc 0、boundary 112/41/31；见 §11.37 |
| v0.8.10 | 2026-11-12 | 技术文档落地核对（无功能改动）：DSH 桥与 Token 监控共 14 组声明逐条对齐代码，全部 PASS；SPEC 32 个仓库路径 0 真实缺失；5 个 run 包均 7 文件；实测 jest 3 套件 17 例 / pytest 14 例；修正 3 处陈旧表述（§11.35 TODO、测试例数、layout 行号）；如实登记 3 项未交付；见 §11.38 |
| v0.8.11 | 2026-11-12 | 3 项遗留边界交付 + 链路梳理：①`AgentChatPanel` 断网中断标记 + 恢复联网自动重试一次（`retriedRef` 防重复、`messages` 判空、catch 兜底）+ 断网提示；②`BACTimeline` 卸载即 `AbortController.abort()`，`api-client` 支持调用方 `signal`（报「请求已取消」）；③GAP-2 `trace_id` 全链透传（`api-client` 注入 `X-Request-Id`、`/api/dsh/execute` 头→body→上游→响应头回显、`dsh-execution-engine.callDshHttp` 补 `inboundTraceId()`）；**链路梳理发现 `/api/dsh/execute` 无生产调用方，真实通路在 `callDshHttp`，且本地未配 `DSH_API_BASE` 时走 IPC**，两处均已补；jest 90/893、tsc 0、boundary 112/41/31、contracts 4 passed；见 §11.39 |
| v0.8.12 | 2026-11-13 | 链路 C 本地活体验证（起 `execute_http_server.py` 打真，非 mock）：`/health` bridge:true/18 capability、Bearer 401/200、`trace_id` 回显、真实 route handler 入站头优先、orchestrator 异步 89.4s 通过、IPC 带 trace 通过；**活体暴露 3 处此前单测未覆盖的契约断点并修复**——①轮询能力名 `orchestrator.status`（点号）≠ 后端 `orchestrator_status`（下划线）→ 云端恒 `not_found`；②作业完成时 `call_handler` 剥掉 `status`，前端死等 `status==='done'` → 必然 120s 超时，改以信封布尔 `ok` 判终态；③`/api/dsh/execute` 未带 `DSH_API_TOKEN` → 云端开鉴权后一律 401；另标注 `orchestrator` 会真实跑交易周期、不可当只读探针；jest 90/894、tsc 0、boundary 与 contracts 不变；见 §11.39.2 |
