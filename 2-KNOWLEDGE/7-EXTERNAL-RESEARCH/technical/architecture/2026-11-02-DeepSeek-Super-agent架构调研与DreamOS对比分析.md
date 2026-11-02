# DeepSeek Super-agent 架构调研 × DreamOS 对比分析

> 日期：2026-11-02 ｜ 类型：外部调研 + 架构对比
> 信息源：DeepSeek Harness 团队《Super-agent 设计探索：迈向更自主的 Agent 系统》(2026-10-31 发布）、dsh-superagent-prototype 开源原型（MIT）、IT之家/腾讯云等报道

---

## 一、核心结论（TL;DR)

1. **Super-agent 是 DeepSeek Harness 团队 2026-10-31 发布的 Agent 系统架构设计 + MIT 开源原型**，目标是把 Agent 从"单会话被动工具"升级为"持续在线、并行多任务、主动推进的自主协作者"，优化目标是**人的注意力**而非单任务能力（观察：一个人只能同时跟进 3-5 个活跃 Session)。
2. **架构五件套**：Router/Worker 双层架构 + 事件驱动（Trigger/Thread/两级过滤/订阅直通）+ 面向人交互（异步 ReAct + 投机执行）+ 计算/状态/环境分离（BYOM, 24h 在线）+ Watchdog 外部控制回路；记忆机制为 Inline & Spill + Chain of Recall。
3. **与我们关系极大的一点：本项目 `.dsh-home` 运行的 DSH (0.1.5-rc.2) 就是 DeepSeek Harness**，Super-agent 原型是标准 Harness bundle，理论上可零迁移装入独立 profile 试用——这是所有外部架构调研中罕见的"同平台可直接复用"情况。
4. **对比结论**：我们（DreamOS SACG + DSH subagent + C-Drive-Agent + 认知记忆 + 三端协同）在"单任务深度"（辩论/反思/评审门禁/认知闭环）上强于 Super-agent 原型；Super-agent 在"多任务广度与持续性"（事件驱动、Thread 直通、投机执行、Watchdog、存算分离）上领先。两者是**互补而非替代**关系。
5. **建议路径**:P0 直接试用原型 bundle（研发协作场景）→ P1 引入 Thread 订阅直通 + 两级过滤 → P2 引入 Watchdog 外部监督 + 注意力预算纪律 → P3 异步 ReAct 改造。全部按我们惯例走模块化开关 + FAIL-OPEN + 先评审后落地。

---

## 二、DeepSeek Super-agent 架构详解

### 2.1 问题定义与四大特征

- **问题**：模型单任务能力变强后，瓶颈转移到人的注意力。主流 Agent 以单 Session 为单位、Session 间相互独立，多任务需人肉切换+转述上下文；CLI/MCP/连接器扩展仍有单会话同步阻塞、多任务上下文混乱、本地离线任务停止三大问题。
- **四大特征**:
  - **连续**：同一 Agent 跨 IM 群聊、GitHub 评论等多渠道交互，能理解"群聊里定方案 A、PR 评论里改方案 B"属于同一项工作；
  - **高效**：并行处理多个复杂任务；
  - **主动**：持续观察环境事件，自行推进值得做的事；
  - **持久**:24h 在线，长期运行中从异常恢复。

### 2.2 五大架构组件

**① 双层架构（Router + Worker)**
- Router：承接人类交互、维护全局上下文、分派任务、统一对外沟通（Worker 不直接回用户）。
- Worker：相互隔离的 Agent 会话，并发执行具体任务，向 Router 汇报状态与结果。

**② 事件驱动**
- 外部信息（群聊消息/邮件/日程/PR 评论/CI 结果）统一抽象为 **Trigger**；同一话题/PR 的连续 Trigger 构成 **Thread**。
- **两级过滤**：程序规则先筛除无关消息 → 大模型再判断是否行动，降低 Token 消耗。
- **订阅与直通（关键设计）**:Worker 接手任务后直接订阅对应 Thread，后续事件由程序直送 Worker，不再经 Router 转发。实验显示去掉直通后 Router 决策次数 +30%、缓存读 Token +37%。

**③ 面向人的交互**
- **异步 ReAct Loop**：耗时工具调用改为异步 `start()/stop()`,Agent 返回 Started 即可继续接收新指令，后台结果作为新事件回流（已在 DeepSeek Harness 实现，**尚未默认开启**)。
- **投机执行**：根据环境信号后台提前开工（群里讨论 Bug 时后台复现定位），**找到可行方案才交付，没找到就保持安静**。
- **注意力经济学**（原型 000-philosophy 核心）:"take as little human attention as possible, give as much value as possible"——只在被请求或团队规则允许时行动，只在必须有人行动或有可用结果时发声。

**④ 计算、状态与环境分离**
- 计算逻辑 + 会话持久化状态放云端；执行环境留在用户本地，仅部署轻量 daemon 执行命令并回传结果。
- 支持 **BYOM**(Bring Your Own Machine)：个人开发机/云托管机/按需计算环境均可接入；本地离线时云端维持任务状态，重连后续跑。

**⑤ Watchdog 外部控制回路**
- 独立于主架构的 Watchdog Session：既监控接口报错、状态恢复失败等**基础设施问题**，也用模型判断 **Worker 是否有实质进展、是否偏离目标**，异常时介入修复。

### 2.3 记忆机制

- **Inline & Spill**：近期可能用到的信息直接放入上下文窗口；超预算/低频内容留在窗口外，模型按需读取。
- **Chain of Recall**:Trigger、Thread、Worker Session 等对象之间用引用 ID 互链，模型沿关联 ID 逐步找回历史任务信息（结构化召回，非纯语义检索）。

### 2.4 原型实现要点（dsh-superagent-prototype, MIT)

- 形态：DeepSeek Harness **bundle**，监听一个 GitHub 仓库（可选飞书），被允许的人请求工作时开 work item，在独立会话+独立目录执行，结果（如 PR）回到原会话；配 web panel 展示"需要人处理的事"。
- 领域模型：**Trigger / Thread / Eval / Decision / Ticket / Assignment / Mandate / Subscription / Policy**。
- **Engine 单写者**：所有方法同步，每个命令一个事务；端口（Repositories/Policy/Assessor/Executor/Outbox）在事务内入队、提交后由 adapter 执行；领域事件外发（`ticket.ended` 等）。
- **MasterAssessor 门**：Eval 批量评估（batching)+ 期限 + 升级 unavailable;Decision ∈ {accept, stop, ignore, unavailable},accept 原子创建 Ticket+Mandate+Assignment+Subscription+确认回执。
- 明确声明：**研究原型，非正式产品**，部分设计（如异步 ReAct、投机执行）是方向性内容，未完全实现。

### 2.5 实验数据与已承认局限

- 合成负载（约 300 条消息/20 项工作请求，5 次重复）:Super-agent 任务完成 p50 **12.4min** / p95 **15.7min**；单 Session+Subagent 中性提示 p95 **29.5min**。
- Router 压测：Trigger 1→40 条/分钟时，批处理 1.0→2.8，单请求 2.5→3.9s，**单决策摊销推理 6.4→1.6s**（事件突发时合并积压提升吞吐）。
- 局限：多层架构有额外 Token 开销；实验规模有限；异步 ReAct 与投机执行未默认开启；**开放问题**含 Router 扩展性、跨月长程记忆、脱离 Session 的人机协作、Agent 间 A2A 通信、安全隐私（提示词注入/端侧凭据/跨设备权限）。

---

## 三、我们架构现状速览（对标基线)

| 层 | 我们的实现 |
| --- | --- |
| 操作系统内核 | DreamOS **新 SACG(v4.0 口径)**:S=认知驱动规划入口(recall 先验+元认知门控→Spec/Plan)→ **A=OKR 节点验收体系**(Spec/Plan 分解 OKR 节点+每节点验收标准)→ C=执行驱动(DSH 子 agent+GraphExecutor+**Reflector** 执行内反思)→ G=压缩沉淀(图压缩+收尾认知沉淀);**C-drive 双语义**(调度者⇄反思器)贯穿四层 |
| 多智能体 | DSH Subagent:**Orchestrator + 隔离 subagent**(subagent 间禁止通信）,Cordis 插件 + Python server IPC,8 个金融子 agent(technical/sentiment/onchain/valuation/flow/macro/risk/portfolio) |
| 决策深度 | **C-Drive-Agent 四步**:recall → 反思+Bull/Bear 辩论 → jeval → 路由；分级触发（>0.75 跳过 / 0.65-0.75 只 recall / 0.50-0.65 加辩论 / <0.50 全链路）;Aggregator 多路合并 + Synthesizer 综合卡片 |
| 质量门禁 | Jev Judge(turn-stopping 三档/step-end REDO/pre-step 意图门控）+ dream-acceptance-verify 五维验收 + hermes 反思 |
| 记忆 | 认知记忆 recall/record/verify + 贝叶斯蒸馏 + TAG_HOOKS 自动触发 + Wiki 编译层 + RAG(ChromaDB/Whoosh/知识图谱） |
| 三端协同 | 本地评审中枢 / GitHub 存证 / 云端运行（21 服务+13 timer),G1-G7+ 门禁链，模块租约 RACI |
| 交易运行时 | polling_trader 轮询 + 模块化开关（战略层 8 开关/方案C 8 开关）+ FAIL-OPEN 铁律 + SL/TP 兜底 + 主动推送 SSE |

---

## 四、逐项对比映射

| Super-agent 概念 | 我们最接近的对应 | 差距判定 |
| --- | --- | --- |
| Router（全局上下文+分派+唯一对外出口） | IntentEngine + GraphPlanner(A 层）/ DSH Orchestrator | ⚠️ 我们 Orchestrator 是**任务级一次性**编排，非持续在线的全局上下文维护者+统一对外出口 |
| Worker 隔离会话并发 | DSH subagent 隔离执行、禁止互通 | ✅ 理念对齐；⚠️ 但我们 subagent 是"调用→返回摘要"的**一次性调用**，不是持续跟踪 Thread 的长会话 |
| Trigger 统一抽象 + 两级过滤 | polling 轮询 + SSE 推送 + 认知 TAG_HOOKS | ❌ 无统一 Trigger 抽象；无"程序规则→LLM"两级过滤门 |
| Thread + 订阅直通 | 无 | ❌ **最大差距**：已派任务的后续事件仍需顶层重新路由；我们甚至明文禁止 subagent 间通信（对一次性调用是对的，但缺直通通道） |
| Inline & Spill / Chain of Recall | 认知 recall + Wiki + RAG | ⚠️ 同构但路径不同：我们是语义检索召回，缺"沿对象引用链（trade→thread→session）找回"的结构化召回 |
| 异步 ReAct(start/stop) | SSE 流式 + ThreadPoolExecutor 并行 5 subagent | ⚠️ deep_analysis 并行是同步阻塞等待全部返回，非事件回流 |
| 投机执行 | 主动推送 SSE(/api/monitor/proactive)+ attention-radar | ⚠️ 有雏形，缺"无结果就安静"的注意力预算纪律 |
| Watchdog 外部控制回路 | Reflector(C 层内）+ Jev Judge + hermes 反思 | ⚠️ Reflector 是**链内**反思；缺独立于主架构、判断"是否有实质进展/偏离目标"的外部监督会话 |
| 存算分离 / BYOM / 离线续跑 | 三端协同（云端 21 服务常驻） | ⚠️ 云端常驻已有；缺"本地离线→云端维持会话状态→重连续跑"的会话级连续性 |
| Engine 单写者+事务+领域事件 | GraphStore + 统一信封 | ⚠️ 可借鉴 Trigger/Decision/Ticket/Mandate 领域建模与单写者事务风格 |
| MasterAssessor 评估门 | C-Drive-Agent 分级触发 + Jev Judge | ✅ 我们更强（辩论+置信度分级 vs 单方评估） |
| 注意力预算哲学 | 用户偏好"核心结论优先" | ✅ 理念天然契合，可直接引用其原则文本 |

## 五、交易场景映射（我们的主战场）

Super-agent 原文是研发协作场景，映射到交易：
- Trigger ≈ 行情事件/信号/公告/链上异动；Thread ≈ **单币种持仓生命周期**（从候选→开仓→持仓→离场全事件链）;
- Router ≈ 战略层（五计庙算/war_state);Worker ≈ 子池（BCRM/BDSM/evolution 隔离并发）——隔离理念已对齐；
- Watchdog ≈ 外部巡检（我们已有 SL/TP 兜底+离场巡检，可升级为"判断策略是否偏离目标"的模型级监督）;
- 投机执行 ≈ 盘前预研/信号预计算，只在高置信时推送。

---

## 六、落地建议（按优先级，全部遵循模块化开关 + FAIL-OPEN + 先评审后落地）

| 优先级 | 动作 | 理由/切入点 |
| --- | --- | --- |
| **P0** | **直接试用 dsh-superagent-prototype bundle**：装入独立 DSH profile（不动现有 web profile)，监听本项目 GitHub 仓库做研发协作试验（Issue/PR 评论响应） | 我们 DSH 就是 DeepSeek Harness,**零迁移成本**；与三端协同的 GitHub 存证层天然契合；MIT 协议可改造 |
| **P1** | 引入 **Thread + 订阅直通**：三端协同评审-修复闭环中，评审意见 Thread 直通到负责修复的 subagent 会话，不再每次过 Orchestrator 全量路由 | 对齐其实验结论：直通取消→决策 +30%/Token +37%，直通是已被验证的降本设计 |
| **P1** | **两级过滤门**用于 attention-radar/主动推送降噪：程序规则硬筛（白名单/阈值）→ LLM 判断是否行动 | 直接降低主动推送的打扰率与 Token 成本 |
| **P2** | **Watchdog 外部监督会话**：独立于 Reflector，监控 polling_trader/子池是否"无实质进展/无效循环/偏离目标"（如反复开平仓、信号抖动），异常介入 | 我们链内反思已强，缺外部回路；交易场景价值直接 |
| **P2** | **Chain of Recall 增强认知记忆**：为 trade_id/持仓/会话建立对象引用链，补充现有语义检索召回 | 提升长程追溯能力（跨月记忆正是双方共同的开放问题） |
| **P3** | **异步 ReAct 改造**:deep_analysis 多 subagent 从同步阻塞改为 start/stop 事件回流，前台先回"已启动" | 注意该机制在官方也未默认开启，成熟度待观察，放最后 |
| 全程 | 风险红线：评估 Token 开销；原型非正式产品需代码评审；BYOM/云端接入本地设备需防提示词注入与凭据泄露 | 官方已明示的开放安全问题，我们金融场景要求更高 |

---

## 七、信息来源

- DeepSeek Harness 团队《Super-agent 设计探索：迈向更自主的 Agent 系统》(2026-10-31，经 IT之家 1020615 报道）
- GitHub: deepseek-ai/dsh-superagent-prototype(README + docs/000-philosophy + docs/007-architecture)
- 腾讯云开发者社区两篇解读（2773523 / 2773284)
- 澎湃新闻相关报道


---

## 八、A 层(OKR)× Super-agent 连接点专项评估(2026-11-02 补充,v4.0 口径)

### 8.1 用户假设

SACG 的 A 层(OKR 验收体系)适合多 agent 场景,可作为与 Super-agent 架构的连接点;且双方架构同源(本项目 DSH 即 DeepSeek Harness)。

### 8.2 评估结论:方向成立,但需精确定位——A 层是「契约与验收」连接点,不是 Router 本身

**成立的依据(结构同构)**:

1. **OKR 节点 ≡ Ticket+Mandate 的契约内核**:Super-agent 原型中 Ticket = Mandate(授权+目标) + Assignment + Subscriptions;我们 A 层 OKR 节点契约 {node_id, objective, criteria, source, verify, evidence_id?} 恰好提供「可分派任务单元 + 完成判定标准」这一 Router/Worker 协作的硬通货(见 34-前端应用训练系统/core/okr_nodes.py)。verify 分派表(evidence_backed/gap_closed/c_action)即完成判定器。
2. **OKRBuilder 已具备多 agent 并行结构**:experiments/ab-trading/core/intent_engine/layer2_okr/okr_builder.py 支持 single/multi 模式、KR 依赖图、parallel_line_count、sequential_depth——「哪些 KR 可并行分给不同 Worker、哪些有顺序依赖」的结构已经存在。
3. **C-drive 双语义 ≈ Router+Watchdog 的种子**:调度者语义→Router;反思器语义(jev 门)→可外化为 Watchdog 独立监督会话。
4. **架构同源属实且超出预期**:C 层执行体本来就是「DSH 子 agent」,与 Super-agent Worker(Harness session)完全同构,执行层零适配成本。

**需要警惕的三处错位**:

1. **生命周期错位**:A 层 OKR 节点目前是单任务内的无状态验收节点(decompose→list 纯函数);Super-agent Ticket 是跨渠道、事件驱动、可 pause/resume、持续数小时/天的长生命周期工作项。缺口:OKR 节点状态机化(live/paused/waitsForPerson/ended)。
2. **验收时机错位**:我们 verify 是 C 层执行后同步比对;Super-agent 是事件驱动完成判定(Thread closed→followsDone→Ticket end,人的后续消息可 resume 已结束 Ticket)。缺口:外部事件触发验收。
3. **Router 角色不在 A 层**:Router 的核心职责(全局上下文维护+统一对外+触发分派)更接近 C-drive 调度者语义+S 层入口的合体。v4.0 已明确「A 层不包含业务节点」,把连接点全压在 A 层会超载其定位。

### 8.3 精确映射(v4.0 口径)

| Super-agent | 我们(新 SACG) | 缺口 |
| --- | --- | --- |
| Router | C-drive 调度者语义 + S 层认知规划入口 | 全局上下文常驻化 |
| Worker | C 层 DSH 子 agent(同源) | 一次性调用→持续会话 |
| **Ticket+Mandate** | **A 层 OKR 节点+verify 分派(连接点核心)** | 节点状态机化 |
| MasterAssessor 评估门 | S 层元认知门控 + C-drive jev 门 | 基本对齐 |
| Thread/Subscription | G 层图存储承载引用链 | 需新增 |
| Watchdog | C-drive 反思器语义外化 | 需独立会话化 |
| Inline & Spill | 24-图结构上下文压缩(BAC 模型) | 已同构 |
| Chain of Recall | G 层压缩沉淀 + 认知 recall 引用链增强 | 部分存在 |

### 8.4 落地路径修正(替代原第六章 P0-P3 的表述侧重)

- **P0**:试用 dsh-superagent bundle 时,其 Ticket/Mandate 由我们 A 层 decompose_okr_nodes 输出映射生成,验证「OKR→Ticket」契约翻译器(最小可行连接点);
- **P1**:OKR 节点状态机化 + Thread 订阅(事件驱动 resume),使 A 层节点具备 Ticket 生命周期;
- **P2**:C-drive 反思器语义外化为 Watchdog 独立会话;G 层承载 Thread 引用链(Chain of Recall);
- **P3**:异步 ReAct。
- 全程模块化开关 + FAIL-OPEN + 先评审后落地;注意统一按 v4.0 新 SACG 口径撰写文档(旧 Sense/Arrange 口径已作废,避免新旧混杂)。


---

## 九、事件驱动 × 存算分离:L0/L1/L2 三层架构视角(2026-11-02 补充)

### 9.1 三层心智模型(用户口径,与 v4.0 一致)

- **L0 = 打通的基础能力**:数据库/采集管线/广义认知 C1-C4/REA 逆向解析/索引系统;独立双向层(fetchContext⇄settle),零 token;
- **L1 = 规则下的能力训练**:意图注册表+十意图执行器,确定性规则/统计/向量检索,零 token 秒级;
- **L2 = 大模型在 L0+L1 上下文之上推进**:新 SACG 编排(S→A→C→G + C-drive),token 成本。

### 9.2 事件驱动:Super-agent 两级过滤 vs 我们三级梯度

| | Super-agent | 我们(L0-L2) |
| --- | --- | --- |
| 第一道 | 程序规则过滤(零 token) | L1 规则/注册表(零 token) |
| 第二道 | LLM 判断是否行动(token) | L1 确定性**直接响应**(零 token,如阈值告警/已知模式) |
| 第三道 | —(无) | L2 生成式推理(token,带 L0 上下文) |

**关键差异**:Super-agent 的规则层只能"过滤",我们 L1 能"过滤+直接闭环"——大量事件(价格阈值、已知告警模式、数据查询类)根本到不了 LLM。且 Super-agent 两级是"价值路由+任务路由"(值不值得做/分给谁),我们两级是"能力路由"(L1 能不能处理),叠加后形成更细的成本梯度。Super-agent 实测 Router 批处理摊销至 1.6s/决策,我们 L1 零 token 等于无限批处理,前提是 L1 事件意图覆盖率。

### 9.3 上下文供给:我们独有的核心差异化

Super-agent 的 Inline & Spill / Chain of Recall 本质是**会话历史管理**,内容限于事件流本身(Trigger→Thread→Session 引用链)。

我们 L0 fetchContext 在事件命中 L2 时供给的上下文维度:

| 维度 | L0 来源 | 回答的问题 |
| --- | --- | --- |
| 实时数据指标 | 18采集/19DAL/20清洗(medallion Gold)/21特征 | 这个事件"是什么" |
| SKILL | 1-ARCHITECTURE/skills 注册表 | "用什么工具做" |
| 知识库 | 2-KNOWLEDGE/wiki/RAG | "背景知识是什么" |
| 经验 | 认知记忆 recall + 贝叶斯蒸馏 | "历史上怎么做的" |
| 真实案例 | CBR 案例库/evolution 案例 | "类似案例结果如何" |
| REA 逆向解析 | 33(依赖图/调用链/架构模式/工程风控) | "最优路径+完整链路是什么" |

**结论:事件触发 + L0 供给 = 每个事件带着完整作战地图进入 L2**,这是 Super-agent 原型不具备的(它没有领域知识/经验/案例供给层)。

### 9.4 存算分离:两种分离轴的叠加

| | Super-agent | 我们现状 |
| --- | --- | --- |
| 分离轴 | 会话连续性(计算/会话状态/执行环境三解耦,BYOM) | 职能分离(本地评审中枢/GitHub 存证/云端运行 21 服务+13 timer) |
| 状态 | 云端 Store | L0 天然云端化(PG/认知库/REA 已在云端)✅ |
| 计算 | 云端 Agent | L2 推理可云端 ✅ |
| 执行环境 | 本地轻量 daemon | 本地 37-一键启动分层管理,雏形已有 ⚠️ 会话级离线续跑是缺口 ❌ |

叠加后的完整图景:**事件驱动解决"何时醒来",L0 fetchContext 解决"醒来带什么",存算分离解决"在哪算、状态存哪",settle 沉淀回 L0 解决"下次更聪明"**——构成事件驱动的自进化循环:事件→L1→L2(S→A→C→G)→45 评测门禁→settle→L0→下次事件 recall 命中(沉淀前先过评测收口,防止低质产出污染认知/案例库)。

### 9.5 风险与红线

1. **FAIL-OPEN 铁律不变**:事件驱动先用于非热路径(研究/评审/告警);L0 源不可用=degraded、源可达无数据=ok+None 的区分必须沿用(recall 已命中此硬约束);
2. **Token 放大**:事件持续到达时成本=L1 未命中率×L2 单价,需为事件类意图扩展 L1 注册表(现 10 个查询类意图,需加 alert_confirm/event_triage 类);
3. **事件风暴降级**:突发时 L1 批处理聚合(对齐 Super-agent Router 合并积压事件的设计)。

### 9.6 对 SPEC 的影响

刚完成的 SACG_A_SUPERAGENT_CONNECTION_SPEC v0.1 聚焦契约桥接(P0);本章分析表明**事件驱动网关应作为独立 L1 组件**(零 token 第一道门)。**已定(2026-11-02 用户决策):事件驱动单独成 SPEC**,见 46-DSH架构/docs/tech/SPEC-EVENT-DRIVEN-L1-GATEWAY.md v0.1(待评审);DSH 相关技术文档统一归集于新建 46-DSH架构/ 域。


### 9.7 评测系统入环(45-评测系统,2026-11-02 用户决策补充)

45-评测系统(L0 基础能力,统一评测收口底座)加入事件驱动自进化闭环,三个接入点:

| 接入点 | 机制 | 价值 |
| --- | --- | --- |
| **settle 前置门禁** | L2 产出沉淀 L0 前过 45 Gate(PASS/BLOCK/INCONCLUSIVE) | 防止低质产出污染认知库/案例库,保护"下次 recall 命中"质量;正是 v4.0 L0"工程检验"职责的具象化 |
| **A 层 evidence_backed 验收** | A 层 OKR verify=evidence_backed 消费 45 Evidence Bundle(spec_hash/签名/WORM 哈希链) | 验收从"C 层执行自报"升级为"独立评测收口",可追溯可复算 |
| **大模型开发后验收** | L2/DSH 子 agent 新能力(SKILL/subagent)上线前过 45;Scorer 三态(code/model/human),LLM 裁判需过校准协议 | 与既有 jev judge 对齐,45 提供校准与统计门禁(DSR/PBO/CPCV、INCONCLUSIVE 默认不放行) |

与 FAIL-OPEN 的关系:45 是**沉淀与上线的门禁**,不是交易热路径门禁;热路径 FAIL-OPEN 铁律不受影响。INCONCLUSIVE(样本不足/CI 跨阈值)默认不放行,与我们"信号不足不干预"的约束层哲学一致。
