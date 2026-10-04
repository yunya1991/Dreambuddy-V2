# 行业对标调研结论与架构优化方案 SPEC (SPEC-B)

> **版本**: v1.0
> **日期**: 2026-09-28
> **状态**: 📋 调研完成，待用户 review
> **作者**: dreambuddy-v2 架构对标（基于 3 维度并行调研）
> **定位**: 基于 SPEC-A 的 11 缺口，结合 2025-2026 行业最新趋势，提出 dreambuddy-v2 架构优化方案
> **调研方法**: 3 个并行 Agent 调研（金融产品 / AI multi-agent / GitHub 开源） + recall 认知记忆 + WebSearch/WebFetch
>
> **与既有文档关系**:
> | 既有文档 | 关系 |
> |----------|------|
> | [SPEC-A: 全局架构现状与 11 缺口](./FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md) (v1.0, 2026-09-28) | **本 SPEC 是其延续**：§八 给出 11 缺口的优化方案对应关系 |
> | [WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md](../WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md) (v1.0, 2026-07-01) | **增量更新**：保留 UFO²/Skill Compose/Nacos，新增 2025-2026 最新趋势 19 个产品/项目 |
> | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) (v0.2) | **升级依据**：§六 DSH 层优化方案 D1-D5 是 v0.3 spec 的输入 |
>
> **认知记忆**: VM-1790607800376-993061bf（金融对标，B 级）+ VM-1790607836656-587dad72（AI multi-agent，B 级）

---

## 一、调研方法与范围

### 1.1 三维度并行调研

| 维度 | Agent | 调研对象数 | 关键产出 |
|------|-------|-----------|---------|
| 金融产品 | Agent #1 | 5（Bloomberg/FactSet/TradingAgents/AI-Hedge-Fund/专业 risk portfolio 子系统） | 5 条启示 + 横向对比表 |
| AI multi-agent | Agent #2 | 7（Anthropic multi-agent/Claude Code Task/OpenAI agents-as-tools/Cognition Devin/Cursor Background/LangGraph/AutoGen） | 5 条启示 + 横向对比表 |
| GitHub 开源 | Agent #3 | 7（TradingAgents/LangGraph/AutoGen/CrewAI/AI-Hedge-Fund/OpenAI Swarm/SWE-agent） | 5 条启示 + 横向对比表 + Matryoshka 学术背书 |
| **合计** | — | **19 个产品/项目** | **15 条启示 → 去重整合为 12 条** |

### 1.2 调研新发现（与旧 COMPETITIVE_ANALYSIS 对比）

| 新增项 | 旧文档未覆盖 | 本 SPEC 新增 |
|--------|-------------|-------------|
| Anthropic multi-agent research system | ✗ | ✅ Orchestrator+并行 subagent+15× token 经济学 |
| Claude Code Task/Subagent | ✗ | ✅ 上下文隔离+worktree+auto-compaction |
| OpenAI agents-as-tools / Swarm / Agents SDK | ✗ | ✅ as-tool vs handoff 双模式 + evaluator-in-loop |
| Cognition Devin / Cursor Background | ✗ | ✅ 长时任务+sleep+ACU 仪表 |
| LangGraph Pregel + DeltaChannel | ⚠ 仅基础 | ✅ super-step 三阶段 + DeltaChannel 40× 存储降 |
| AutoGen 进维护模式（2025-10） | ✗ | ✅ Microsoft Agent Framework 转向 |
| Matryoshka Agent 论文（arxiv 2607.25090, 2026-07） | ✗ | ✅ Orchestrator+Sub-Agents+Tools 三层学术背书 |
| TradingAgents v0.5.1（2026-09） | ✗ | ✅ checkpoint resume + Pydantic structured + decision log |
| AI-Hedge-Fund 18-agent（63K stars） | ✗ | ✅ Risk Manager 纯算法 + Portfolio LLM + 确定性夹断层 |

---

## 二、三维度调研结果

### 2.1 金融产品调研（5 个）

| 产品 | 核心架构要点 |
|------|-------------|
| **Bloomberg Terminal** | 四面板硬网格+命令行混合交互；Launchpad workspace 的 component linking（一 panel 改证券关联组件同步）；PORT Workspace 多组合对比+技术指标叠加+Chart Grid |
| **FactSet** | 模块化开放架构（Workstation+Widget Library+104+ RESTful API）；Portfolio API v4 schema/holdings 解耦+异步 jobId；MAC Risk Models 三档（参数化/Monte Carlo/全估值）+ 多层风险归因 |
| **TradingAgents** (44K stars) | LangGraph StateGraph 编排 12 LLM agent；**Bull/Bear 显式辩论**（`max_debate_rounds` 多轮+Research Manager 综合）；双层 LLM 策略（deep_thinking/quick_thinking） |
| **AI-Hedge-Fund** (63K stars) | Fan-Out+Fan-In 拓扑 19 analyst 并行；**Risk Manager 纯算法化（无 LLM）**+Portfolio LLM+`compute_allowed_actions` 确定性夹断层；统一 Signal 契约 typed 对象 |
| **专业 risk/portfolio 子系统** | 4-agent LangGraph 基准（HN 75 分，6 个月 14.7% 收益/1.34 Sharpe）；ML 压力测试 PCA/AE/VAE 三管线；Thrive 实时相关性矩阵+portfolio heat 三层（nominal/correlation-adjusted/max potential loss） |

### 2.2 AI multi-agent 产品调研（7 个）

| 产品 | 核心架构要点 |
|------|-------------|
| **Anthropic multi-agent** | orchestrator-worker：LeadAgent spawn 3-5 subagent 并行；**搜索即压缩**（subagent 独立 context 仅回传关键 tokens）；token 经济学 15× chat，解释 BrowseComp 80% 方差；LLM-as-judge rubric |
| **Claude Code Task/Subagent** | 强制上下文隔离（subagent 独立会话，中间 tool 调用不外泄）；仅最终消息回传父 agent；支持 fork 会话/worktree 隔离/深度并发花费上限/auto-compaction/resume |
| **OpenAI agents-as-tools** | 双模式：as-tool（manager 保控制权）vs handoff（专家接管本轮）；Swarm（教育）→ Agents SDK（v0.9, 2026-02, 19K stars, 生产推荐）；**evaluator-in-loop** 反思评估范式 |
| **Cognition Devin** | 递归控制环 Plan→Action→Observation→Correction；云沙箱+shell+browser+editor；Spaces 多 agent 共享 context/git worktree；Agent Command Center Kanban；自调度/sleep/ACP 协议 |
| **Cursor Background Agents** | 隔离 Ubuntu VM（AWS），克隆 repo/独立分支/自主 push PR；并行 10+；多 repo 环境/Dockerfile 即代码/环境版本可回滚/密钥按环境隔离 |
| **LangGraph** (1.0 GA 2025-10) | Pregel/BSP 模型，super-step 三阶段 Plan→Execute→Update；Channel 类型 4 种（LastValue/Topic/BinaryOperatorAggregate/**DeltaChannel 1.2+ 40× 存储降**）；durable execution；interrupt() HITL；time-travel |
| **AutoGen** (maintenance 2025-10) | GroupChat（RoundRobin/Selector）vs Magentic-One（Orchestrator+WebSurfer/FileSurfer/Coder）；v0.4 事件驱动重写；**进维护模式，并入 Microsoft Agent Framework (2026-04 GA)，typed-graph 新方向** |

### 2.3 GitHub 开源项目调研（7 个）

| 项目 | 核心架构要点 |
|------|-------------|
| **TradingAgents** v0.5.1 (2026-09) | LangGraph 状态机+7 角色；**checkpoint resume opt-in**（crash 后从最后成功节点恢复）；**Pydantic structured outputs**；persistent decision log（`~/.tradingagents/memory/trading_memory.md` 跨标的反思注入）；two-tier LLM；15+ providers 含 Qwen/GLM 双区域 |
| **LangGraph** 1.0 GA (2025-10-22) | Pregel/BSP runtime；super-step 三阶段+pending writes 持久化；thread_id 持久 cursor；Checkpointer 支持 SQLite/Postgres/in-memory；Interrupts HITL 四决策 approve/edit/reject/respond |
| **AutoGen** (维护模式) | 见 §2.2；不应再以 GroupChat 为对标 |
| **CrewAI** (~49K stars) | 任务式编排四原语 Agents/Tasks/Tools/Crew；Sequential/Hierarchical 双 Process；Hierarchical `manager_llm` 必填+`allow_delegation` 默认禁用；YAML 配置；**role+task-based 比 conversation 更工程化** |
| **AI-Hedge-Fund** (~63K stars) | LangGraph DAG+**18 个 agent**（13 Persona+5 Quant+News）；`ANALYST_CONFIG` 注册表模式；Risk+Portfolio 独立；`analyst_signals` TypedDict 共享契约；每个 agent 输出 `signal+confidence+reasoning` 三元组 |
| **OpenAI Swarm** (~22K stars, educational) | 两原语 Agents+handoffs；stateless `client.run()`；已被 OpenAI Agents SDK 取代；**handoff pattern=agent-as-tool，与 dreambuddy-v2 HC-7 一致** |
| **SWE-agent** (Princeton NLP, NeurIPS 2024) | ACI (Agent-Computer Interface)：LM agents 是新用户类别，需专用接口；v2.0 self-reflection 循环；衍生 SWE-ReX（并行云执行）/SWE-smith（训练轨迹）/EnIGMA（网络安全） |

### 2.4 学术背书（重要新发现）

**Matryoshka Agent** (arxiv 2607.25090, 2026-07, Georgia Tech)：
- 三层架构：Orchestrator（决策层，长程状态）+ Sub-Agents（执行层，环境交互）+ Tools（中介层）
- **与 dreambuddy-v2 SACG+DSH+Tools 高度同构**，提供长时任务最佳实践学术背书

---

## 三、行业共识（已收敛）

### 3.1 Orchestrator + 隔离 Subagent 模式已成行业共识

2025-2026 行业已收敛到 Orchestrator + 隔离 subagent 模式，peer collaboration (GroupChat) 衰落：

| 收敛证据 | 来源 |
|---------|------|
| Anthropic multi-agent + Claude Code Task + OpenAI agents-as-tools + Cognition Managed Devins | 全部采用 Orchestrator+隔离 |
| Magentic-One (AutoGen 团队转向) | 已放弃 GroupChat，采用 Orchestrator |
| **AutoGen 进入维护模式（2025-10）** | 微软推荐 Microsoft Agent Framework (typed-graph) |
| Matryoshka Agent 论文（2026-07） | 学术界确认 Orchestrator+Sub-Agents+Tools 三层 |

**dreambuddy-v2 应用**：
- ✅ DreamOS SACG = Orchestrator（持完整上下文：意图+执行图+所有节点结果）
- ✅ DSH Subagent = 隔离执行者（独立上下文：接收任务→执行→返回 SubagentOutput 摘要）
- ✅ **HC-7（subagent 间禁通信）继续保持**，行业已验证
- ⚠️ 不应再以 AutoGen GroupChat 为对标，转向 LangGraph 1.0 GA + MAF 1.0 GA

### 3.2 长时任务标配：Checkpoint + Resume + Cost 仪表

| 来源 | 机制 |
|------|------|
| LangGraph 1.0 GA | per-super-step 持久化 graph state + pending writes；durable execution 崩溃/部署后可恢复 |
| LangGraph DeltaChannel 1.2+ | 只存增量避免长会话 checkpoint 膨胀，40× 存储降（200 轮 5.3GB→129MB） |
| TradingAgents v0.2.4+ | checkpoint resume opt-in，crash 后从最后成功节点恢复 |
| Cognition Devin | sleep 状态 + ACU 仪表 |
| Cursor Background | 环境版本可回滚 |

**dreambuddy-v2 应用**：DreamOS GraphStore 当前缺 checkpoint 持久化，是 P0 优化项（见 §六 O3）。

### 3.3 Subagent 输出契约标准化趋势

| 来源 | 契约形态 |
|------|---------|
| AI-Hedge-Fund | `analyst_signals` TypedDict + 每个 agent 输出 `signal+confidence+reasoning` |
| TradingAgents v0.2.5+ | Pydantic structured outputs（Research Manager/Trader/Portfolio Manager） |
| Anthropic multi-agent | 压缩摘要 + artifact 引用（subagent 直接写 artifact 到 filesystem，仅回传轻量引用） |
| Claude Code Subagent | 仅最终消息回传，中间 tool 调用不外泄 |

**dreambuddy-v2 应用**：SubagentOutput v0.2 已有 signals/charts/raw_data，但需升级 4 字段（见 §六 D1）。

---

## 四、横向对比表（19 产品/项目）

| 维度 | Bloomberg | FactSet | TradingAgents | AI-Hedge-Fund | 专业 risk 子系统 | Anthropic | Claude Code | OpenAI | Devin | Cursor | LangGraph | AutoGen | CrewAI | OpenAI Swarm | SWE-agent |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 编排模式 | 四 panel+cmd | 模块化 API | LangGraph StateGraph | Fan-Out+Fan-In | 4-agent LangGraph | Orch+并行 sub | Orch+sub | as-tool/handoff | 递归环 | 并行 VM | 有向图 | GroupChat/Magentic | Sequential/Hierarchical | handoff | ACI 命令式 |
| Subagent 隔离 | function-based | API 域 | role prompt | 独立 agent 函数 | 独立 agent | 独立 ctx+Memory | 独立会话+worktree | manager/接管 | 云沙箱 | 独立 VM | PregelNode actor | actor model | role-based | Agent 实例 | 单 agent |
| 输出契约 | function-security pair | RESTful JSON+jobId | Pydantic AgentState | typed Signal 对象 | typed | 压缩摘要+artifact 引用 | 仅最终消息 | as-tool 返 manager | Spaces 共享 | follow-up 接管 | typed reducer | 对话历史 | Task output→context | 无 stateless | ACI commands |
| Checkpoint | PORT workspace | 历史/假设 | opt-in (v0.2.4+) | 无 | 无 | Memory+resume | auto-compact+resume | 无原生 | sleep | 环境版本回滚 | 内置核心+Delta 40× | 无内置 | 无 | 无 | 无 |
| 图表能力 | 技术叠加+Chart Grid | Widget Library | Backtrader 回测 | Web UI 决策管线 | 热力图+矩阵 | artifact | 无 | 无 | Kanban | 无 | 无 | 无 | 无 | 无 | ACI commands |
| 风险组合独立性 | PORT 独立 workspace | Risk/Perf/Reporting 三合一 | Risk Mgmt Team 独立 | Risk 纯算法+Portfolio LLM | Risk+Portfolio 独立 | N/A | N/A | N/A | N/A | N/A | N/A | N/A | 可定制 | N/A | N/A |
| Cost 控制 | — | — | two-tier LLM | compute_allowed_actions | — | 分级 effort+token 预算 | 深度/并发/花费上限 | guardrail | ACU 仪表 | 按 token | DeltaChannel 40× | 终止条件 | max_rpm | — | — |

> **dreambuddy-v2 现状对标**：DreamOS SACG（Orchestrator）+ DSH 9 Subagent（隔离执行）+ SubagentOutput v0.2（signals/charts/raw_data）+ Bull/Bear HC-8（置信度<0.65 触发）+ risk/portfolio P2 全缺。

---

## 五、对 dreambuddy-v2 的整合启示（12 条，15 条去重）

### 启示 1：架构模式已对齐行业共识（继续坚持 HC-7）

**来源**：Anthropic + Claude Code + OpenAI + Devin + Magentic-One + Matryoshka 论文
**应用**：DreamOS SACG=Orchestrator，DSH Subagent=隔离执行者，**HC-7（subagent 间禁通信）继续保持**
**约束**：不应再以 AutoGen GroupChat 为对标，转向 LangGraph 1.0 GA + MAF 1.0 GA

### 启示 2：SubagentOutput 契约升级 4 字段

**来源**：金融启示4（AI-Hedge-Fund Signal+confidence+reasoning 三元组）+ AI 启示2（Anthropic artifact 引用）+ GitHub 启示2（AI-Hedge-Fund ANALYST_CONFIG）
**应用**：SubagentOutput v0.3 应补：
- `confidence` (0-1 浮点，驱动 Bull/Bear 分级触发)
- `reasoning_chain` (LLM 推理过程，audit 用)
- `evidence_refs` (引用节点 indicators 原始数据 hash，可追溯)
- `artifact_uri` (承载结构化产物如图表/报告，C-Drive-Agent 聚合时按引用拉取，避免"传话游戏"信息损失)

### 启示 3：C-Drive-Agent 4 步循环升级分级 effort

**来源**：AI 启示3（Anthropic 按 query 复杂度分 1/2-4/10+ subagent 档位）+ OpenAI evaluator-in-loop
**应用**：在 0.75/0.65/0.50 阈值外，叠加 effort 预算按信号复杂度动态调 subagent 触发数，避免简单信号走全链路烧 token

### 启示 4：Reflector 引入 Jev 决策模型替 LLM judge

**来源**：AI 启示4（LangGraph 生态 Jev：system-one 决策模型，比 LLM 快 200×/便宜 400×，自一致、返回 typed 概率）+ Anthropic 端态评估
**应用**：jeval 对有明确答案判据的场景用轻量决策模型替 LLM judge，长链路只做 end-state 评分

### 启示 5：Checkpoint + Resume + Cost 仪表长时任务标配

**来源**：AI 启示5（LangGraph DeltaChannel 40× 存储降 + Devin sleep/ACU + Cursor 环境版本回滚）+ GitHub 启示1（TradingAgents checkpoint resume opt-in）
**应用**：DreamOS GraphStore 引入 per-step 状态快照+delta 增量（借鉴 LangGraph super-step + DeltaChannel），C-Drive 加 token 预算仪表+ACU 类消耗看板，支撑长链路部署与失败 resume

### 启示 6：Bull/Bear 辩论多轮化（LangGraph conditional edges）

**来源**：金融启示2（TradingAgents `max_debate_rounds`）
**应用**：当前 HC-8 < 0.65 触发并行调用一次，应升级为 2-3 轮显式辩论：
- 第 1 轮立论（Bull/Bear 各自提取信号生成论据）
- 第 2 轮互相驳斥
- 第 3 轮 Research Manager（C-Drive-Agent 兼任）综合
- LangGraph conditional edges + Pydantic AgentState 比 DSH IPC 更适合辩论循环（状态可持久化、可中断恢复）

### 启示 7：Risk Agent 纯算法化 + Portfolio Agent LLM + 确定性夹断层

**来源**：金融启示1（AI-Hedge-Fund defense-in-depth）+ GitHub 启示4（TradingAgents/AI-Hedge-Fund 均独立）
**应用**：
- `risk_agent` 拆分为纯算法（相关性矩阵/波动率/VaR），**不调 LLM**，确定性可复现
- `portfolio_agent` 用 LLM 综合多 subagent 信号产出 buy/sell/hold+数量
- 加一层 `compute_allowed_actions` 确定性夹断作为 defense-in-depth，即使 LLM 输出 10000 股，硬数学夹断到 risk-approved 上限
- 是 HC-1（数据驱动避幻觉）的自然延伸

### 启示 8：Risk Agent 补压力测试三层

**来源**：金融启示5（FactSet MAC + arXiv 2507.02011 + Thrive）
**应用**：
- 实时相关性矩阵热力图（ChartSpec 新增 heatmap 类型）
- portfolio heat 三层指标（nominal / correlation-adjusted / max potential loss）
- ML 压力测试（PCA/AE/VAE 三管线，输出 VaR + Expected Shortfall）
- FactSet 的"历史/假设/极端 + 因子可调"是产品化形态，arXiv VAE Monte Carlo 是技术路径

### 启示 9：9 Subagent 显式注册到 NodeRegistry

**来源**：GitHub 启示2（AI-Hedge-Fund `ANALYST_CONFIG` 注册表模式 + 18-agent 注册）
**应用**：将 DSH 9 Subagent 显式注册到 DreamOS NodeRegistry，参考 AI-Hedge-Fund 的 ANALYST_CONFIG 模式
- 输出 schema 升级为 Pydantic（OpenAI provider 用 function calling，其他 provider 用 system prompt + Pydantic 后验证，同 TradingAgents 模式）

### 启示 10：前端3.1 学 Bloomberg Launchpad 多 panel workspace

**来源**：金融启示3（Bloomberg Launchpad component linking + Column Set）
**应用**：
- 多 panel workspace（每 panel 独立加载证券/function）
- component linking（一 panel 改 symbol 时关联图表/insight 同步更新）
- "数据列组 (Column Set)"概念，一键切换 ESG/技术/基本面视角
- 命令行+图表混合交互保留（专业用户）

### 启示 11：前端3.1 图表消费路径自建（开源空白）

**来源**：GitHub 启示3（七个开源项目均无内置 K线/Sankey/热力图能力）
**应用**：图表层是开源空白，dreambuddy-v2 前端3.1 必须自建
- 参考 TradingAgents 的 `on_message` callback 机制（每个 LangGraph message 触发 Rich panel 渲染）作为 SSE 推送至前端的桥梁
- ECharts 集成 8 类图表类型（candlestick/line/bar/sankey/gauge/scatter/heatmap/pie）

### 启示 12：长时任务 Pydantic structured + decision log

**来源**：GitHub 启示5（TradingAgents v0.2.4 structured-output agents + `~/.tradingagents/memory/trading_memory.md` 跨标的反思注入）
**应用**：
- DSH Subagent 输出从自由文本升级为 Pydantic schema，字段含 `signal/action + confidence + reasoning + evidence_refs`
- OpenAI provider 用 function calling，其他 provider 用 system prompt + Pydantic 后验证
- DSH 长链路调度引入 opt-in checkpoint（每个 Subagent 调用后持久化，thread_id 复用），`clear_checkpoint_on_success` 防止 stale state
- 引入跨标的 decision log（持久化反思，注入 C-Drive recall）

---

## 六、架构优化方案（按 4 层组织）

### 6.1 SACG 层优化方案（3 项）

| # | 优化项 | 优先级 | 关联启示 | 关联缺口 |
|---|--------|--------|---------|---------|
| **O1** | GraphStore 引入 LangGraph Pregel super-step + DeltaChannel 增量存储 | P1 | 启示5 | #2 Reflector |
| **O2** | Reflector 引入 Jev 决策模型替 LLM judge（明确答案判据场景） | P1 | 启示4 | #2 Reflector |
| **O3** | Checkpoint 持久化 + thread_id 持久 cursor + resume 机制 | **P0** | 启示5 | #2 Reflector |

**O1 实施要点**：
- 借鉴 LangGraph super-step 三阶段 Plan→Execute→Update
- 引入 DeltaChannel 增量存储（40× 存储降），避免长会话 checkpoint 膨胀
- thread_id 作为持久 cursor，借鉴 SACG session_id

**O2 实施要点**：
- jeval 对有明确答案判据用 Jev system-one 决策模型（比 LLM 快 200×/便宜 400×）
- 长链路只做 end-state 评分（Anthropic 端态评估）
- 返回 typed 概率，自一致

**O3 实施要点**：
- GraphPlanner 引入 per-step 状态快照+delta 增量
- C-Drive 加 token 预算仪表+ACU 类消耗看板
- 支撑 rainbow 部署与失败 resume

### 6.2 DSH 层优化方案（5 项）

| # | 优化项 | 优先级 | 关联启示 | 关联缺口 |
|---|--------|--------|---------|---------|
| **D1** | SubagentOutput 契约升级：补 confidence/reasoning_chain/evidence_refs/artifact_uri 四字段 | **P0** | 启示2,12 | #1 DSH 图表 |
| **D2** | C-Drive-Agent 4 步循环升级：分级 effort + max_debate_rounds 多轮化 Bull/Bear | P1 | 启示3,6 | #2 Reflector |
| **D3** | Risk Agent 纯算法化 + Portfolio Agent LLM + compute_allowed_actions 夹断层 | **P2** | 启示7 | #8 risk/portfolio |
| **D4** | Risk Agent 补压力测试三层（相关性矩阵/portfolio heat/ML 压力测试） | P2 | 启示8 | #8 risk/portfolio |
| **D5** | 9 Subagent 显式注册到 NodeRegistry + Pydantic schema + 跨标的 decision log | P2 | 启示9,12 | #8 risk/portfolio |

**D1 实施要点**（升级 SubagentOutput v0.3）：
```typescript
interface SubagentOutput {
  module: string;
  summary: string;
  signals: Signal[];
  charts: ChartSpec[];
  raw_data?: any;
  // 新增 4 字段
  confidence: number;          // 0-1 浮点，驱动 Bull/Bear 分级触发
  reasoning_chain: string;    // LLM 推理过程，audit 用
  evidence_refs: string[];     // 引用节点 indicators 原始数据 hash
  artifact_uri?: string;       // 结构化产物（图表/报告）的引用，C-Drive 按引用拉取
}
```

**D2 实施要点**：
- 在 0.75/0.65/0.50 阈值外叠加 effort 预算（按信号复杂度动态调 subagent 触发数）
- Bull/Bear 多轮化：第 1 轮立论→第 2 轮互相驳斥→第 3 轮 C-Drive 综合
- LangGraph conditional edges + Pydantic AgentState 比 DSH IPC 更适合辩论循环

**D3 实施要点**：
- `risk_agent` 拆分为纯算法（相关性矩阵/波动率/VaR），不调 LLM
- `portfolio_agent` 用 LLM 综合 buy/sell/hold+数量
- 加 `compute_allowed_actions` 确定性夹断层（即使 LLM 输出 10000 股，硬数学夹断到 risk-approved 上限）

**D4 实施要点**：
- 实时相关性矩阵热力图（ChartSpec 新增 heatmap 类型）
- portfolio heat 三层指标（nominal/correlation-adjusted/max potential loss）
- ML 压力测试（PCA/AE/VAE 三管线，输出 VaR+Expected Shortfall）

**D5 实施要点**：
- DSH 9 Subagent 显式注册到 NodeRegistry（参考 AI-Hedge-Fund ANALYST_CONFIG 模式）
- 输出 schema 升级为 Pydantic
- OpenAI provider 用 function calling，其他 provider 用 system prompt + Pydantic 后验证
- 引入跨标的 decision log（持久化反思，注入 C-Drive recall）

### 6.3 前端3.1 优化方案（7 项）

| # | 优化项 | 优先级 | 关联启示 | 关联缺口 |
|---|--------|--------|---------|---------|
| **F1** | Bloomberg Launchpad 多 panel workspace + component linking | P3 | 启示10 | #1 DSH 图表 |
| **F2** | SubagentOutput charts 消费组件（ECharts + 8 类图表） | **P0** | 启示11 | #1 #5 DSH 图表 |
| **F3** | C-Drive-Agent 4 步循环可视化（recall/反思/jeval/路由 4 步进度） | **P0** | 启示3 | #3 C-Drive 可视化 |
| **F4** | Bull/Bear 辩论 UI（bull_confidence vs bear_confidence + 论据列表） | P1 | 启示6 | #4 Bull/Bear UI |
| **F5** | SACG 监控 4 子页（sense/arrange/compute/graph） | P2 | — | #6 监控 4 子页 |
| **F6** | Meta-Labeling 前端入口 | P2 | — | #7 Meta-Labeling 入口 |
| **F7** | **Muse 启发的产品体验优化**（移植+升级 3.1→3-FRONTEND + 新增 Daily Briefing/Mood Board/实时干预/产物归一） | P1 | Muse Spark 1.1 | #11 Muse 已澄清 |

**F1 实施要点**：
- 多 panel workspace（每 panel 独立加载证券/function）
- component linking（一 panel 改 symbol 时关联图表/insight 同步更新）
- "数据列组 (Column Set)"概念，一键切换 ESG/技术/基本面视角

**F2 实施要点**：
- ECharts 集成 8 类图表类型（candlestick/line/bar/sankey/gauge/scatter/heatmap/pie）
- 参考 TradingAgents 的 `on_message` callback 机制作为 SSE 推送至前端的桥梁

**F3 实施要点**：
- 实时显示 recall/反思/jeval/路由 4 步进度
- 与 SACG 监控 4 子页（F5）协同

**F4 实施要点**：
- 显示 bull_confidence vs bear_confidence + 关键论据列表
- 显示辩论轮数（max_debate_rounds=2-3）

**F7 实施要点**（Muse 启发的产品体验优化）：

> **背景**：Muse = Meta 公司 2026-07 推出的消费级 AI 智能体（Muse Spark 1.1）。Muse 的产品体验强调"AI 不只思考，还代为行动"，对 dreambuddy-v2 的产品体验优化有以下启示：

**子项 F7.1 — 3-FRONTEND 移植 Muse 启发组件**（P1，前置依赖）：
- 现状：3.1-FRONTEND 已有 `InsightCard.tsx` / `RecommendationCard.tsx` / `SynthesisChart.tsx`(sankey/heatmap/gauge/line/bar) / `ReportExport.tsx`(MD+PDF 导出) 共 4 个 Muse 启发的卡片组件；dream-harness-bridge 已有 `synthesized_cards` 字段；3-FRONTEND/dream-universal-gateway 仅有 `TaskCard.tsx`+`MessageItem.tsx`，**未移植**这 4 个组件
- 目标：将 4 个组件移植到 `3-FRONTEND/dream-universal-gateway/src/components/chat/` 并接入 `MessageItem.tsx` 渲染分发（与 TaskCard 并列）
- 数据契约：复用 dream-harness-bridge `synthesized_cards`（已有）+ FinalSynthesisData 类型
- 关联：与 D1（SubagentOutput v0.3）协同，artifact_uri 字段直接喂给 ReportExport

**子项 F7.2 — Daily Briefing 每日简报**（P1）：
- Muse 体验：用户设置一次任务后，Meta AI 持续交付（如每周一早晨推送训练计划）
- dreambuddy-v2 应用：每日固定时段（如 8:00 / 13:00 / 21:00）推送 briefings：盘前综述/盘中异动/盘后总结 + 持仓 PnL/止损触发/BCRM2.0 状态/S3/S4 信号
- 实现：DreamOS S 层 IntentEngine 添加 cron trigger + 产物中台（M1 完成后）持久化 briefings 列表 + 前端 `/dashboard/briefing/*` 子页面
- 数据源：BCRM2.0 推理 + BDSM 出场巡检 + 战略层影子模式 + 自进化每日采纳

**子项 F7.3 — Mood Board 情绪板可视化产物**（P2）：
- Muse 体验：Mood Board 把多源信息综合成视觉化"情绪板"
- dreambuddy-v2 应用：交易决策的可视化情绪板——多空信号+相关性矩阵+风险热力图+资金流向 Sankey 一屏综合展示
- 实现：复用 SynthesisChart 的 sankey/heatmap 类型 + 新增 `MoodBoardPanel.tsx` 容器组件，Aggregator 输出 `mood_board_artifact` 字段
- 关联：与 D4（Risk Agent 压力测试三层）+ F1（Bloomberg 多 panel）协同

**子项 F7.4 — 实时干预（steer in real time）**（P2）：
- Muse 体验：用户在 LLM 生成报告/计划/幻灯片过程中可改变方向、调语气、裁剪章节
- dreambuddy-v2 应用：用户在 C-Drive-Agent 4 步循环执行中可"介入"——跳过某节点、强制 Bull/Bear、改置信度阈值、补资料
- 实现：SSE 流式推送 `c_drive_step` 事件（已有 chain_trace SSE）+ 前端"介入按钮"发回 `/api/intent/steer` + DreamOS GraphExecutor 增加 `user_steer` 钩子
- 关联：与 F3（C-Drive 4 步循环可视化）+ O3（Checkpoint 持久化）协同——steer 后从 checkpoint 重放

**子项 F7.5 — 产物归一存储**（P2，依赖 M1）：
- Muse 体验：所有 AI 创建的产物（训练计划/slides/mood boards）归一存储可回看可分享
- dreambuddy-v2 应用：所有深度分析报告/InsightCard 产物/Mood Board/Bull-Bear 辩论记录归一存储到产物中台，用户可回看/导出/分享
- 实现：产物中台（M1 完成后）扩展 `artifact_type` 枚举（`insight_card`/`mood_board`/`bull_bear_debate`/`briefing`），DSH Subagent 写入 `artifact_uri`，前端 `/dashboard/notebook/*` 展示
- 关联：与 D1（artifact_uri 字段）+ M1（产物路径迁移）协同

### 6.4 中台优化方案（3 项）

| # | 优化项 | 优先级 | 关联启示 | 关联缺口 |
|---|--------|--------|---------|---------|
| **M1** | 产物路径迁移完成（7-ARTIFACT_HUB → 中台统一管理） | P2 | — | #10 产物路径 |
| **M2** | 百炼集成完成（API+KB+RAG+Function Calling 闭环） | P2 | — | #9 百炼集成 |
| **M3** | 百炼与 DSH Subagent 接入路径明确 | P2 | — | #9 百炼集成 |

---

## 七、优先级实施路线图（P0-P3）

### P0（架构闭环，4 项）

| # | 优化项 | 关联启示/缺口 | 预估工作量 |
|---|--------|--------------|-----------|
| O3 | Checkpoint 持久化 + thread_id + resume | 启示5 / 缺口#2 | 中（借鉴 LangGraph） |
| D1 | SubagentOutput 契约升级 4 字段 | 启示2,12 / 缺口#1 | 小（schema 升级） |
| F2 | SubagentOutput charts 消费组件 | 启示11 / 缺口#1 #5 | 中（ECharts 8 类） |
| F3 | C-Drive 4 步循环可视化 | 启示3 / 缺口#3 | 中（前端组件） |

> **P0 验收**：DSH 图表能力闭环（D1+F2），Reflector 接入 checkpoint（O3），C-Drive 4 步循环可视化（F3）

### P1（决策质量 + Muse 体验闭环，5 项）

| # | 优化项 | 关联启示/缺口 |
|---|--------|--------------|
| O1 | GraphStore 引入 Pregel super-step + DeltaChannel | 启示5 / 缺口#2 |
| O2 | Reflector 引入 Jev 决策模型 | 启示4 / 缺口#2 |
| D2 | C-Drive 4 步循环升级分级 effort + Bull/Bear 多轮化 | 启示3,6 / 缺口#2 #4 |
| F4 | Bull/Bear 辩论 UI | 启示6 / 缺口#4 |
| F7.1 | 3-FRONTEND 移植 Muse 启发组件（InsightCard/SynthesisChart/ReportExport/RecommendationCard） | Muse Spark 1.1 / 缺口#11 |
| F7.2 | Daily Briefing 每日简报 | Muse Spark 1.1 / 缺口#11 |

> **P1 验收**：Reflector 从仅 REDO 升级为 4 步循环（O1+O2+D2），Bull/Bear 多轮化辩论闭环（D2+F4），3-FRONTEND 完成 Muse 启发组件移植（F7.1），每日简报推送上线（F7.2）

### P2（risk/portfolio 补齐 + 中台完工 + Muse 体验深化，11 项）

| # | 优化项 | 关联启示/缺口 |
|---|--------|--------------|
| D3 | Risk Agent 纯算法化 + Portfolio LLM + 夹断层 | 启示7 / 缺口#8 |
| D4 | Risk Agent 压力测试三层 | 启示8 / 缺口#8 |
| D5 | 9 Subagent 注册 + Pydantic + decision log | 启示9,12 / 缺口#8 |
| F5 | SACG 监控 4 子页 | — / 缺口#6 |
| F6 | Meta-Labeling 前端入口 | — / 缺口#7 |
| F7.3 | Mood Board 情绪板可视化产物 | Muse Spark 1.1 / 缺口#11 |
| F7.4 | 实时干预（steer in real time） | Muse Spark 1.1 / 缺口#11 |
| F7.5 | 产物归一存储 | Muse Spark 1.1 / 缺口#11（依赖 M1） |
| M1 | 产物路径迁移完成 | — / 缺口#10 |
| M2 | 百炼集成完成 | — / 缺口#9 |
| M3 | 百炼与 DSH Subagent 接入 | — / 缺口#9 |

> **P2 验收**：risk/portfolio subagent 完整实现（D3+D4+D5），前端3.1 监控+Meta-Labeling 入口完工（F5+F6），中台三大组件全部 ✅（M1+M2+M3），Muse 体验深化（F7.3+F7.4+F7.5）

### P3（前端 workspace 升级，1 项）

| # | 优化项 | 关联启示/缺口 |
|---|--------|--------------|
| F1 | Bloomberg Launchpad 多 panel workspace + component linking | 启示10 / 缺口#1 |

> **P3 验收**：前端3.1 升级为专业金融 workspace（多 panel+component linking+Column Set）

---

## 八、与 SPEC-A 11 缺口的对应关系

| SPEC-A 缺口 | SPEC-B 优化方案 | 优先级 |
|------------|----------------|--------|
| #1 DSH 图表能力完全缺失 | D1（SubagentOutput 升级）+ F2（charts 消费组件） | **P0** |
| #2 Reflector 仅 REDO 未接入认知/jeval/subagent | O1（Pregel）+ O2（Jev）+ O3（Checkpoint）+ D2（4步循环升级） | P0-P1 |
| #3 前端3.1 缺 C-Drive-Agent 4 步循环可视化 | F3 | **P0** |
| #4 缺 Bull/Bear 辩论 UI | F4 + D2 | P1 |
| #5 缺 SubagentOutput charts 字段消费组件 | F2 + D1 | **P0** |
| #6 前端3.1 缺 SACG 监控 4 子页 | F5 | P2 |
| #7 缺 Meta-Labeling 前端入口 | F6 | P2 |
| #8 DSH risk/portfolio 节点全缺 | D3 + D4 + D5 | P2 |
| #9 百炼集成未完工 | M2 + M3 | P2 |
| #10 产物路径待迁移 | M1 | P2 |
| #11 Muse 已澄清（Meta 公司 2026-07 推出的 Muse Spark 1.1） | F7.1（移植）+ F7.2（Daily Briefing）+ F7.3（Mood Board）+ F7.4（实时干预）+ F7.5（产物归一） | P1-P2 |

---

## 九、调研 Sources（关键文献）

### 9.1 AI multi-agent 关键文献

- [How we built the multi-agent research system](https://www.anthropic.com/engineering/built-multi-agent-research-system) — Anthropic orchestrator-worker
- [Subagents in the SDK (Claude Code)](https://code.claude.com/docs/en/agent-sdk/subagents) — 上下文隔离契约
- [Create custom subagents (Claude Code)](https://code.claude.com/docs/en/sub-agents) — fork/worktree/auto-compaction
- [Agent orchestration (OpenAI Agents SDK)](https://openai.github.io/openai-agents-python/multi_agent/) — as-tool vs handoff
- [Cognition/Devin vendor profile](https://agenticindex.io/vendors/cognition) — 递归控制环+sleep+ACU
- [Cursor changelog 0.50 (Background Agent)](https://cursor.com/changelog/0-50) — 隔离 VM
- [Delta Channels: Evolving agent runtime](https://www.langchain.com/blog/delta-channels-evolving-agent-runtime) — 40× 存储降
- [Building Prod with Jev and LangGraph](https://www.langchain.com/blog/building-prod-with-jev-and-langgraph) — Jev system-one 决策模型
- [AutoGen to Microsoft Agent Framework migration](https://learn.microsoft.com/en-au/agent-framework/migration-guide/from-autogen/) — AutoGen 维护模式转向

### 9.2 金融产品关键文献

- TradingAgents (44K stars): https://github.com/TauricResearch/TradingAgents — Bull/Bear + checkpoint resume + Pydantic
- AI-Hedge-Fund (63K stars): https://github.com/virattt/ai-hedge-fund — Risk 纯算法+Portfolio LLM+compute_allowed_actions
- FactSet Portfolio API v4 + MAC Risk Models — 多层风险归因
- arXiv 2507.02011 — ML 压力测试 PCA/AE/VAE 三管线
- arXiv 2607.25090 — Matryoshka Agent 三层架构学术背书

### 9.3 GitHub 开源关键文献

- LangGraph 1.0 GA (2025-10-22): https://github.com/langchain-ai/langgraph — Pregel super-step + DeltaChannel
- AutoGen maintenance mode (2025-10): https://github.com/microsoft/autogen
- CrewAI (~49K stars): https://github.com/crewAIInc/crewAI — role+task-based
- OpenAI Swarm: https://github.com/openai/swarm — handoff pattern
- SWE-agent: https://github.com/SWE-agent/SWE-agent — ACI (Agent-Computer Interface)

### 9.4 Meta Muse 关键文献（F7 优化项依据，2026-09-28 WebSearch 调研）

- [Introducing Muse Spark 1.1](https://ai.meta.com/blog/introducing-muse-spark-meta-model-api/) — 2026-07-09，多模态推理 Agent 模型，1M token 上下文+active context compaction+多 subagent 并行编排+Computer Use+Coding
- [Meta AI Doesn't Just Think, It Acts](https://about.fb.com/news/2026/07/meta-ai-muse-spark-doesnt-just-think-it-acts/) — 2026-07-24，产品体验：实时干预+产物归一+Daily Briefing+Research Deep Dives+mood boards+slides
- [Introducing Muse Spark: MSL's First Model](https://about.fb.com/news/2026/04/introducing-muse-spark-meta-superintelligence-labs/) — 2026-04-08，Meta Superintelligence Labs 首个 LLM
- [迎战 Meta Muse! OpenAI 据称将紧急推出个人 AI 助手](https://m.chinastarmarket.cn/detail/2493802) — 2026-09-28，摩根大通将 Muse 列为最顶尖 AI 智能体，每个智能体运行在专用安全计算机上

---

## 十、下一步行动

| 阶段 | 行动 | 状态 |
|------|------|------|
| ✅ 完成 | recall 检索（硬约束）+ 两轮盘点 + SPEC-A | 已完成 |
| ✅ 完成 | 3 维度行业对标调研（19 产品/项目 + 12 启示） | 已完成 |
| ✅ 完成 | 本 SPEC-B 形成（4 层优化方案 + P0-P3 路线图） | 本文档 |
| ✅ 完成 | 用户已 review 并批准 SPEC-A+B | 已批准 |
| ✅ 完成 | Muse 调研与 SPEC 完善（F7.1-F7.5 5 子项）+ §9.4 文献 | 2026-09-28 |
| ⏳ 进行中 | hermes 反思：是否形成新 SKILL（dream-arch-gap-analysis-workflow） | 用户已要求创建 |

### 10.1 用户 review 后的可能路径

1. **review 通过** → 推进 P0 实施路线（O3+D1+F2+F3）
2. **review 调整** → 修改 SPEC-B 后再推进
3. **需要 brainstorming SKILL** → 启动 brainstorming 走完整设计流程
4. **需要 dream-research-workflow SKILL** → 启动 5 步研究流程深化某维度

---

## 十一、本 SPEC 不覆盖项（明确边界）

| 不覆盖项 | 责任文档 |
|---------|---------|
| SPEC-A 11 缺口的现状详述 | [SPEC-A](./FRONTEND3_DREAMOS_DSH_GLOBAL_ARCH_SPEC.md) |
| DSH Subagent v0.2 完整 spec | [DSH_SUBAGENT_ARCHITECTURE_SPEC.md](../dream-harness-bridge/docs/DSH_SUBAGENT_ARCHITECTURE_SPEC.md) |
| 模块层面缺口（A5/A6/A7 等） | [WORKBUDDY_OS_GAP_ANALYSIS.md](../WORKBUDDY_OS_GAP_ANALYSIS.md) |
| 2026-07 之前的行业对标 | [WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md](../WORKBUDDY_OS_COMPETITIVE_ANALYSIS.md) |
| 前端3.1 完整技术文档 | [v3-frontend-architecture.md](../../3.1-FRONTEND/docs/v3-frontend-architecture.md) |
| Muse 相关优化 | §6.3 F7（5 子项） + §9.4 文献 |

---

*SPEC-B 版本: v1.1 | 日期: 2026-09-28 | 调研范围: 19 产品/项目 + Meta Muse | 启示: 12 条 | 优化方案: 18 项（O3+D5+F7+M3）含 5 子项 F7.1-F7.5 | 状态: 用户已批准 + Muse 调研已补充*
