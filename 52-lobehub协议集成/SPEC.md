# SPEC: 52-LobeHub 协议集成（Agent 前台与模型路由叠加层）

> 版本：v0.4.0（R1-R9 全部评审决议落地：首挂壳/白名单/部署/评估器/桥schema/裁决AB/PlanCard/路由）
> 日期：2026-11-11
> 状态：🟢 评审闭环完成，Phase 0 可开工
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

### 0.3 用户决策（2026-11-11，待确认）

| 编号 | 决策 | 对 52 的约束 |
|---|---|---|
| D1 | 52 定位 = **协议叠加层** | 独立部署，不并入主骨架代码；只通过 MCP 与现有架构交互 |
| D2 | **协议集成，禁止 fork 改源码** | 上游 nightly 迭代极快；定制只走配置/插件/MCP 挂载，不修改 lobehub 仓库代码 |
| D3 | 能力边界：**前台接入 + 模型路由** | agent runtime / skills 市场归 LobeHub；能力执行、认知记忆、交易执行归现有架构 |
| D4 | **双轨治理**（R-B 新增） | LobeHub 的 agent runtime 仅作"执行器"，编排主权归 DreamOS；其 expertise/userMemories（agent 成长记忆）**不回写我方认知库**，Phase 3 蒸馏桥建成后经桥回流 |
| D5 | **执行+监督双链协作**（2026-11-11 用户确认） | 统一入口 → 双方意图规划 → Debate MCP 辩论 → 评估器裁决 → 胜者方案执行/败者后勤+门禁监督 → L0 统一沉淀 → 涌现回流。四条修正铁律见 §7.2 |

### 0.4 不做什么

| 禁止 | 原因 |
|---|---|
| 不 fork lobehub 源码做二次开发 | D2：上游日更，分叉维护成本不可控 |
| 不让 LobeHub 直接读写 4-MEMORY / 认知库 | 认知写入仍走 L0 cognition 壳（worker 只读治理不变） |
| 不在 52 内实现交易/策略/风控能力 | 能力供给归 DSH 各域 + L0 壳；52 只做消费方 |
| 不把 LobeHub 的 agent runtime 替代 DreamOS NodeRegistry | 双轨风险：DreamOS 是主骨架，LobeHub 是前台 |
| 不将 LobeHub 的 expertise / userMemories 与我方认知库互写 | D4：其 agent 成长数据锁在其 PG；认知记忆唯一事实源是 35 协作模块 |
| 不采用集成路径 B（heterogeneous agent / lobehub-gateway 接入 DSH 为异构 agent） | R-D：与 MCP 路径互斥、复杂度更高，仅记录为备选 |
| 不将 LobeHub 会话存储与认知记忆混用 | 会话上下文归 LobeHub Postgres；认知记忆归 35 协作模块 |
| 首期不接入 live 交易链路 | 首验证只挂只读壳；交易壳挂载需独立评审 |
| 辩论/竞争永不进入 live 交易执行链 | D5：live 执行保持单决策链；辩论结果仅作信号输入，裁决与执行仍走 27 治理审批 |

---

## §1 在现有架构中的位置

```text
用户 / IM 渠道（Telegram / Discord / 飞书 / Web）
        │
┌───────▼────────────────┐
│  52 LobeHub（叠加层）    │  模型路由（任意 LLM）+ 对话前台 + 渠道接入
│  独立服务 docker/systemd │  + acceptance 验收（可选）
└───────┬────────────────┘
        │ MCP 协议（唯一接口，stdio/sse）
┌───────▼────────────────┐
│  L0 MCP 网关（47）       │  ← 现有壳零改造；mcp_capabilities.yaml 仍是唯一事实源
├────────────────────────┤
│  DSH 子域能力（46）      │
├────────────────────────┤
│  DreamOS/SACG（1）       │  意图识别 / NodeRegistry / 编排（主骨架不变）
├────────────────────────┤
│  REA + 做梦器（33/48）   │  反思/涌现经 cognition record 回流，LobeHub 无感知
└────────────────────────┘
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
- **R-C 部署形态修正（源码实证）**：LobeHub 的 stdio 本地 MCP 由 **desktop（Electron）主进程**执行；远程 MCP 走 HTTP/cloud-gateway。因此：
  - **本地 PoC**：用 LobeHub desktop 版挂 stdio l0_gateway（最简路径）；
  - **云端部署**：需将 l0_gateway 包一层 SSE/HTTP 暴露（Phase 2 时实施，作为独立小服务）。

### 2.2 模型路由契约

| 项 | 约定 |
|---|---|
| Provider 配置 | 全部在 LobeHub 侧环境变量/UI 配置；52 仓内不存任何 API Key |
| 模型切换 | 换模型 = 改 LobeHub 配置，不动现有架构任何代码 |
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

### Phase 0 — PoC（本地跑通，验证最小闭环）

目标：**换 3 家模型（如 Claude / GPT / Qwen）都能经 LobeHub 调通一个 L0 只读能力。**

1. 本地部署 LobeHub **desktop 版**（R-C：stdio MCP 依赖 Electron 主进程；若用 server 版须先完成 l0_gateway SSE 封装，作为备选路径）。版本锁定官方 release tag，不改源码。
2. 用 mcpctl 生成 `lobehub_frontend` 只读 profile，挂载首壳 **cognition（recall）**（R1 已决议：只读零风险、直接展示记忆检索能力）。
3. 验收：3 家模型分别完成"调用 L0 工具并返回正确结果"。

### Phase 1 — 能力面扩展

1. 按 mcp_capabilities.yaml 逐个挂载研究/数据类只读壳（第二个挂 unified_search，R1；随后 18/19/41 等）。
2. 每个壳挂载后统一用 dream-acceptance-verify 五维验证（R2 已决议：不引入 LobeHub acceptance 为依赖）。
3. 评估写工具开放范围（须授权主体 + 独立评审）。

### Phase 2 — 云端部署与渠道接入

1. LobeHub 作为独立 systemd 服务上云（第 23 类服务），走 dream-code-deploy-pipeline。
2. IM 渠道接入（TG/飞书）在 LobeHub 层配置。
3. 三端协同更新：44-三端协作架构登记 52 的部署拓扑与健康检查。

### Phase 3 — 蒸馏桥（D5 新增）

1. 建桥：LobeHub 会话/expertise 成长数据 → 经 L0 cognition 壳（record，授权主体）→ 35 认知库。
2. 桥的写入仍遵守 worker 只读治理：桥本身不直连 cognitive_memory.db，只调壳。
3. 验收：LobeHub 侧产生的经验可在 recall 中命中，且来源标签可溯（tags 含 lobehub-bridge）。

### Phase 4 — Debate MCP 壳上线（shadow 模式）

1. 按 §7.3 契约实现 debate 壳，registry 登记 + drift 检查。
2. **shadow 运行 2-4 周**：辩论全程 trace 落盘（复用 50 域 decisions.jsonl 范式），只记录不影响执行。
3. 验收：trace 完整率、评估器裁决一致性人工抽检达标。

### Phase 5 — 竞争模式激活（非交易任务）

1. 对研究/分析/工程类任务激活"辩论-裁决-分工"全链路。
2. 交易域：辩论结果仅作信号输入，裁决与执行仍走 27 治理审批（§0.4 硬约束）。
3. 激活门槛：评估器裁决率、翻盘率、败方负样本蒸馏价值达标（Phase 4 shadow 数据支撑）。

---

## §4 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 上游日更导致版本漂移 | 中 | 锁定 docker tag 版本升级（周/月节奏）；不追 nightly |
| 双轨：LobeHub runtime vs DreamOS 编排 | 高 | D3+D4 边界硬约束；能力实现零迁入；SPEC 评审时逐条核对 |
| expertise/userMemories 与我方认知库分叉 | 高 | D4：不回写（直连）；Phase 3 蒸馏桥统一回流；此前其成长数据视为易失 |
| 功能面膨胀诱导越界（task/goal/signal 侵蚀 D3） | 中 | §0.4 禁止清单 + 挂载评审时重申"只用前台与路由" |
| proactive 旁路（schedule/heartbeat 动作绕过 MCP） | 中 | A6 验收硬门禁；其自动化任务只允许调 MCP 工具 |
| 辩论裁判漂移递归（LLM 裁 LLM） | 高 | D5 修正铁律①：裁判必须是评估器（45评测+acceptance证据+回测），LLM 仅有限仲裁 |
| 竞争成本翻倍（双份规划 token） | 中 | 竞争仅对高价值任务开启（意图路由分流）；shadow 期先量化成本收益 |
| 败方监督能力错配 | 中 | D5 修正铁律③：监督交确定性门禁，败方只做后勤 |
| 数据双写/记忆混乱 | 高 | §2.3 数据边界契约；认知写入只走 L0 壳 |
| 引入第二运维栈（Node/Next/Postgres） | 中 | 独立容器部署，与 Python 服务进程级隔离 |
| stdio 路径依赖 desktop（无头 CI/服务器不可用） | 低 | R-C：PoC 用 desktop；云端用 SSE 封装（Phase 2） |
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
用户意图（统一入口：LobeHub 渠道层）
      │
  意图规划 ×2 ─────────────────────┐
  ├─ DreamOS 侧（NodeRegistry/SACG） │
  └─ LobeHub 侧（agent-runtime）     │
      ▼                             │
  Debate MCP（新 L0 壳：命题/论据/反驳轮次协议）
      ▼
  评估器裁决（45 评测 + acceptance 证据 + 回测，非 LLM）
      ▼
  分工：胜出方案 → DreamOS 执行（唯一执行体）
        败方 → 后勤（渠道/数据/上下文组装）
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
| ⑤ **辩论多样性契约化**：双方禁止同模型配置；证据路径差异化（DreamOS 走 L0 数据壳，LobeHub 走其 web-crawler/builtin tools 独立取证）；裁决三态含 INCONCLUSIVE（对齐 45 评测契约） | arXiv《More Debate, Same Evidence》：同模型+同证据池的辩论错误强相关，加轮次/改 persona 无效，增益只来自模型/证据多样性 + 弃权政策 |
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

- 必填字段：`content`（≤300字精炼）、`tags`（必含 `lobehub-bridge` + 来源域 + 类型）、`source_ref`（LobeHub 侧可追溯 ID/trace 链接）、`bridge_ts`。
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

