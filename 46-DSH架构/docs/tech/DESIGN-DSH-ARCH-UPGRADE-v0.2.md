# DESIGN:DSH 架构升级方案 v0.1

> **版本**: v0.2 ｜ **日期**: 2026-11-02 ｜ **状态**: ✅ 决议落定,可进 P0 ｜ **定位**: **46-DSH架构 域主线设计**
> **v0.2 变更**: 按 [ALIGNMENT-46-47 v1.0](../../../47-MCP管理系统/docs/tech/ALIGNMENT-46-47-v1.0.md) 落定 G1/G3/B2/B4/B5：新增 ADR-9 写主体与 settle 归属、ADR-10 壳实例拓扑；ADR-3 补 paused 子因；ADR-4 改为引用 47 注册表；术语改「45 业务门禁」
> **升级对象**: 当前单会话 DSH(0.1.5-rc.2) → 常驻、多任务、可验收的 DSH 多 agent 架构
> **外部前提(不展开)**: L0 通过稳定工具面(port / MCP)对外供给。**MCP 域设计以 47-MCP管理系统 SPEC v0.3 为 SSoT**([SPEC-L0-MCP-PACKAGING](../../../47-MCP管理系统/docs/tech/SPEC-L0-MCP-PACKAGING-v0.3.md));本设计只依赖"存在稳定工具面 + 主体权限矩阵"这一契约,不依赖具体封装形态。
> **承接文档**: [DESIGN-SUPERAGENT-FUSION v0.2](DESIGN-SUPERAGENT-FUSION.md) ｜ [ANALYSIS 双维梳理](ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md) ｜ [SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2](SPEC-EVENT-DRIVEN-L1-GATEWAY.md) ｜ [SACG_A SUPERVAGENT CONNECTION SPEC v0.2](../../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md)

---

## 一、升级目标(AS-IS → TO-BE)

| # | 维度 | 现状(AS-IS) | 目标(TO-BE) | 判据 |
| --- | --- | --- | --- | --- |
| 1 | **触发** | 同步用户请求为主 | 事件驱动常驻(Trigger 统一抽象) | 无人发起时也能被事件唤醒并按策略行动 |
| 2 | **任务并发** | 单会话串行 | 多 Ticket 并行,每 Ticket 绑定独立 Worker | 同时推进 ≥3 个 Ticket 且互不阻塞 |
| 3 | **上下文** | 单次会话内的历史 | L0 六维供给 + Thread 引用链 | 事件进入 L2 时自动带实时数据/SKILL/知识/经验/案例/REA |
| 4 | **验收** | 人工判断 / Worker 自报 | A 层 OKR verify + 45 门禁 | 产出物未过门禁不得沉淀、不得上线 |
| 5 | **沉淀** | 无(会话结束即蒸发) | settle → 广义认知五系统 | 下次同类事件 recall 命中率可测 |
| 6 | **权限与成本** | 无契约 | Mandate = 工具授权 + 预算上限 | 越权调用被拒;单 Ticket 成本可审计 |

**一句话**:把 DSH 从"一次问一次的会话工具"升级为"被事件驱动、能并行、有契约、可验收、会沉淀的常驻协作者"。

### 1.1 差距确认(基于现有 subagent 契约)

现有 DSH subagent 的官方契约(`DSH_SUBAGENT_ARCHITECTURE_SPEC.md`)明确三条:**隔离执行 / Subagent 之间不通信 / 只返回压缩摘要**。这带来一个必须正视的结构性差距:

> **现状的 subagent 是"一次性隔离执行者",不是"可持续会话"** —— 无法承载跨事件的多轮推进,也就无法直接支持 Thread 直通与 paused 续跑。

因此本次升级的**真正难点不是"加 Router",而是把执行体从"一次性调用"升级为"可按 Thread 持续推进的 Worker"**;隔离与摘要压缩的既有设计要保留(防止上下文爆炸),但需增加"会话可续"维度。


---

## 二、目标架构(七层 + 一个给定出口)

```
┌ ① 入口层 ──────────────────────────────────────────────┐
│  事件网关(Trigger→规则过滤→事件意图→三分流,零 token)     │
│  对话入口(现有用户请求,不改造)                          │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ② 编排层:Router ───────────────────────────────────────┐
│  全局上下文 · 统一对外 · 任务分派 · 批处理聚合 · 能力集路由│
│  (复用 C-drive 调度者语义 + S 层认知规划入口)            │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ③ 契约层:A 层 OKR→Ticket/Mandate ─────────────────────┐
│  节点契约(objective/criteria/verify) + 资源账单(预算)    │
│  状态机:live / paused / waitsForPerson / ended          │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ④ 执行层:Worker(DSH 会话) ────────────────────────────┐
│  按角色分池(研究/工程/交易分析/验收)                    │
│  每 Worker 只见自己的能力集(≤10 工具)                   │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ⑤ 认知层:L0 + 广义认知五系统 ─────────────────────────┐
│  fetchContext 六维供给 · C1-C4 四层 · settle 回写        │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ⑥ 验收层:45 门禁 + Watchdog ──────────────────────────┐
│  Evidence Bundle(WORM 哈希链) · 独立巡查(进展/偏离/风险) │
└───────────────┬────────────────────────────────────────┘
                ▼
┌ ⑦ 沉淀层:settle → 五系统 ────────────────────────────┐
│  认知经验 · SKILL 可复用流程 · 调研知识 · 文档 · 索引    │
└────────────────────────────────────────────────────────┘

    给定出口(横切,不属升级内容):port(in-process) / MCP(跨端)
    观测(横切):trace_id 贯穿 ①→⑦,dreamos_sessions/spans 唯一观测面
```

**分层职责边界**(防止职责回流成"大泥球"):

- Router **不做业务决策**,只做分派/聚合/对外;业务判定在 A 层 verify 与 45
- A 层 **不拥有执行**,只拥有契约与验收判据
- Worker **不自证完成**,完成与否由 A 层 verify 判定
- Watchdog **不改任务**,只产巡查结论并升级给人或 Router
- L0 **不判业务**,只供数据与证据

---

## 三、关键架构决策(ADR)

### ADR-1 Router:常驻但无状态
Router 以批处理循环常驻(可独立进程,也可挂现有调度器 timer),**自身不持有任务状态**,每次 pass 从 L0 读快照、算分派、写回。理由:Router 是单点,无状态才可随时重启;这也与官方"批处理摊销决策成本"实测一致。

### ADR-2 状态单一事实源 = L0
Thread / Ticket / Session 三层状态**全部映射到 L0 存储**(PG + trace_id),DSH `storages` 仅作运行时缓存。理由:融合最常见的失败是"两套状态腐烂";状态双写必然导致对账成本与漂移。**红线:禁止在 DSH 内维护第二套权威状态。**

### ADR-3 会话生命周期四态

> 对应 §1.1 差距:subagent 需从"一次性隔离执行"升级为"可续会话"。保留隔离(独立上下文)与摘要压缩(返回 SubagentOutput),新增 `thread_id + 续跑锚点`,使同一 Thread 的后续事件可直接送原 Worker(不经 Router)。
Ticket 状态机收敛为 **live / paused / waitsForPerson / ended** 四态(由官方 8 态合并,便于工程实现):
- `paused`:释放 Worker 资源(Token/会话槽),等事件或超时唤醒。**子因(G3 定稿)**:`waiting_event`(等外部事件)／`waiting_job`(等异步工具 submit-poll 完成)／`waiting_person`(等人)——异步等待必须走 job 完成事件唤醒,**禁止忙轮询**
- `waitsForPerson`:释放 Worker,挂人工待办(飞书通知),对应官方"人在环"
- 无论 paused 还是 waitsForPerson,**Worker 不占槽**——这是并行度能起来的关键

### ADR-4 能力集(而非全量工具面)
**本设计只定义「Worker 角色清单」与「角色→能力标签」**;「能力标签→工具集」的唯一载体是 `47-MCP管理系统/registry/mcp_capabilities.yaml`(B4 定稿),本设计不另建矩阵。每角色 ≤10 个工具;Router 只感知能力标签,不感知全量工具。理由:MCP 按域封装后工具总量会膨胀,若全量暴露给每个 Worker,Router 决策质量与 token 成本会双恶化(与 Super-agent 注意力预算问题同源)。

### ADR-5 权限与预算合一(Mandate)
Ticket 的 Mandate 同时承载 **"允许调用的工具集" + "预算上限(token/时长/成本)"**。理由:两者都是"这次任务能干多少"的约束,拆成两套契约必然不同步;合并后越权与超预算都在同一处判定。

### ADR-6 验收外置,Worker 不自证
完成判定由 **A 层 verify 分派表**(evidence_backed / gap_closed / c_action)+ **45 业务门禁**共同决定,Worker 输出仅是候选证据。理由:多 agent 下"自报完成"是最容易被幻觉污染的一环。

### ADR-7 观测以 trace_id 为唯一主轴
Router → Worker → 工具面 → L0 全链路透传 `trace_id`,落 `dreamos_sessions` / `dreamos_spans` / `dsh_calls` 三表。理由:链路加深到 5 跳后,**没有 trace 就没有可运维性**;注意 span 必须先有同 trace 的 session 行(既有 DDL 约束,已踩过坑)。

### ADR-8 升级以"独立 profile + 开关"落地
新形态运行于独立 DSH profile(`superagent` 或 `dsh-upgrade`),与 `web` profile 隔离;所有新增路径挂 `enable_*` 开关默认关,关断时字节等价现有行为。

### ADR-9 写主体与 settle 归属(G1/B2 定稿)

**Worker 默认只读;`settle` 由编排侧 Settle 节点执行;Mandate 的授予对象是编排侧,不是 Worker。**

| 主体 | read | write(record/verify/distill) | admin(migrate/sync) |
|---|---|---|---|
| Worker(DSH 会话) | ✅ 能力集内 | ❌ | ❌ |
| Router / Settle 节点(编排侧) | ✅ | ✅ 受 Mandate 约束 | ❌ |
| Verifier / 45 业务门禁 | ✅ | ✅ 仅记录裁决结果 | ❌ |
| 运维 CLI / CI | — | — | ✅ |

理由:认知壳默认 ssh 云端且本地模式写工具禁用;若让 Worker 直接写,settle 会静默失败或形成双事实源。

### ADR-10 壳实例按运行时进程共享(G2 定稿)

`宿主` = DSH 运行时进程;同一进程内**按域共享单壳实例**,Worker 会话只持「工具调用句柄」→ 连接数 = 聚合后域数(3),而非 Worker 数。跨进程(云端/本地)才各自拉起。理由:stdio 下 1 宿主 = 1 壳 = N×连接,若按会话拉起则并发即放大;且壳内禁止自建连接池。

---

## 四、组件复用矩阵(不重复造轮子)

| 组件 | 新建/复用 | 复用源(已核实存在) |
| --- | --- | --- |
| 事件网关 | 新建 `event_gateway.py` | 复用 L1 意图注册表机制与冷却窗口同构逻辑 |
| Router | 复用 + 加常驻循环 | C-drive 调度者语义 + S 层认知规划入口 |
| Worker | **复用 + 加可持续会话** | DSH subagent 与聚合:`1-ARCHITECTURE/dream-harness-bridge/integration/cognitive_loop_adapter.py`(已接认知且 FAIL-OPEN)、`34-前端应用训练系统/adapters/dsh_subagent_collector.py`(结果聚合)、`25-用户策略生成系统/dsh_nodes.py`、`33-REA逆向解析工程/dsh_nodes.py`(领域节点范式) |
| Ticket/OKR 契约 | 复用 + 翻译器 | `34-前端应用训练系统/core/okr_nodes.py`、`experiments/ab-trading/core/intent_engine/layer2_okr/okr_builder.py`,新增 `okr_ticket_bridge.py` |
| 统一信封 / 上下文供给 | **复用** | `34-前端应用训练系统/core/l0_foundation.py`(10 scope + 统一信封,degraded≠ok(None)) |
| 验收门禁 | **复用** | `45-评测系统/api/server.py`(FastAPI,异步两段式适配) |
| 观测 | **复用** | `1-ARCHITECTURE/dreamos/shared/event_writer.py` + observability 三表 |
| 沉淀 | **复用** | 认知 record/verify/knowledge-ingest;settle 面向五系统 |
| 任务状态存储 | **复用** | L0 云端 PG(不新建 Store) |

> 结论:**升级的主体工作是"编排与契约",不是"重写执行体"**。Worker/认知/验收/观测四块均已有实现,升级风险集中在 Router 常驻化与状态机。

---

## 五、演进路径(以 DSH 升级为主线)

| 阶段 | 主题 | 交付物 | 退出判据 |
| --- | --- | --- | --- |
| **P0·骨架** | 单域试点跑通 | 事件网关(shadow 只记录不拦截)+ Router 单轮分派 + Ticket 契约翻译器 + 1 个 Worker 角色 | 1 类事件端到端走通(Router→Ticket→Worker→45→settle),网关未拦截任何事件 |
| **P1·并行** | 多任务与状态机 | 四态状态机 + 能力集矩阵 + Thread 亲和直通(亲和表+TTL)+ 多 Worker 并发 | 同时 3 个 Ticket 并行;越权工具调用被拒 |
| **P2·验收** | 质量门禁闭环 | 45 业务门禁接为硬门(先 shadow 转正)+ Watchdog 独立巡查 + Evidence Bundle 引用调用链 | 未过门禁的产出无法沉淀;Watchdog 能识别偏离目标 |
| **P3·常驻** | 自进化与连续性 | settle 五系统全通道 + 会话级离线续跑 + 投机预取(L1 零 token 预取上下文) | 重启后 Ticket 可续跑;同类事件 recall 命中率提升可测 |

> 阶段间**不强制线性**:P1 的直通与 P2 的门禁可由不同人并行推进,但 **P0 必须先出骨架**(否则契约与观测面无法对齐)。

---

## 六、红线与风险

### 6.1 硬约束(升级不可违反)

| # | 红线 |
| --- | --- |
| H1 | **FAIL-OPEN**:任一新增组件异常 → 退回现有单会话行为,等价"升级不存在" |
| H2 | **开关默认关** `enable_dsh_upgrade`,关断字节等价 |
| H3 | **状态不双写**:权威状态只在 L0(ADR-2) |
| H4 | **Worker 不自证**:完成判定必须经 A 层 verify + 45(ADR-6) |
| H5 | **交易热路径零接入**:polling_trader/开仓链路不参与本升级 |
| H6 | **独立 profile**:不动 web profile,不污染现有链路 |
| H7 | **Worker 只读**:写操作仅由编排侧/Verifier 持有 Mandate 执行(ADR-9) |

### 6.2 风险登记

| # | 风险 | 等级 | 对策 |
| --- | --- | --- | --- |
| U1 | Router 成为单点与瓶颈 | 高 | ADR-1 无状态 + 批处理 + 可重启;异常时降级为同步单会话 |
| U2 | 状态漂移(DSH 缓存与 L0 不一致) | 高 | ADR-2 单源;每次 pass 以 L0 快照为准;禁止在 Worker 内改状态 |
| U3 | 长尾 Ticket 堆积(waitsForPerson 无人处理) | 中高 | TTL + 飞书提醒频次治理(通知本身不得击穿注意力预算) |
| U4 | 多 Worker 并发写认知库污染 | 高 | 写类工具入 Mandate 授权 + 幂等(external_id)+ 45 前置 |
| U5 | 工具面膨胀拖垮 Router/Worker | 中高 | ADR-4 能力集 ≤10;工具分组按需加载 |
| U6 | 五跳链路故障定位困难 | 中 | ADR-7 trace_id;每跳统一信封 |
| U7 | 上下文预取浪费 | 中 | 预取仅 L1 零 token 路径;未命中静默丢弃 |

---

## 七、验收标准(可测)

| # | 标准 |
| --- | --- |
| V1 | 开关关断前后,现有测试套件全绿(字节等价) |
| V2 | 事件端到端:1 类事件 → Ticket 创建 → Worker 产出 → 45 裁决 → settle 落 L0,全链路 trace_id 一致 |
| V3 | 并行度:3 个 Ticket 同时 live,任一 paused 不占 Worker 槽 |
| V4 | 越权:调用未授权工具被明确拒绝(非静默成功),审计留痕 |
| V5 | 状态一致:任意时刻 DSH 侧无权威状态副本;重启后 Ticket 可从 L0 恢复 |
| V6 | 门禁:未过 45 的产出 0 条进入沉淀(抽样核对) |

---

## 八、待决策

| # | 待决 | 建议 |
| --- | --- | --- |
| DD1 | Router 常驻形态:独立进程 vs 挂现有调度器 timer | 先挂 timer(运维简单),P2 再评估独立进程 |
| DD2 | 首批 Worker 角色清单 | 研究 / 工程 / 验收 三类起步,交易分析后置(避热路径) |
| DD3 | Thread 亲和直通 TTL | 初值 30 分钟,按实测命中率调 |
| DD4 | 45 门禁接入方式 | P2 先 shadow,误拦率 <5% 转硬门 |
| DD5 | bundle 原型是否保留作对照 | 保留至 P3,作为"壳退役"前的对照基线 |

---

## 九、与现有文档的关系

| 文档 | 角色 |
| --- | --- |
| **本文件** | DSH 升级主线设计(架构/ADR/路径) |
| [DESIGN-SUPERAGENT-FUSION](DESIGN-SUPERAGENT-FUSION.md) | 吸收策略(借壳灌芯 A→B),为本设计提供"吸收什么" |
| [SPEC-EVENT-DRIVEN-L1-GATEWAY](SPEC-EVENT-DRIVEN-L1-GATEWAY.md) | 本设计 ① 入口层的实现规格(P0) |
| [SACG_A SPEC](../../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md) | 本设计 ③ 契约层的实现规格(P0) |
| [REPORT-L0-MCP-DSH-IMPACT](REPORT-L0-MCP-DSH-IMPACT-v1.1.md) | 给定出口的评估与建议(**上游输入,不在本设计范围**) |
| [SPEC-L0-MCP-PACKAGING v0.3](../../../47-MCP管理系统/docs/tech/SPEC-L0-MCP-PACKAGING-v0.3.md) | **MCP 域 SSoT**:壳契约/写工具治理/能力集注册表(本设计 ADR-4/9/10 的实现依据) |
| [ALIGNMENT-46-47 v1.0](../../../47-MCP管理系统/docs/tech/ALIGNMENT-46-47-v1.0.md) | 双方交界审查与开工顺序(本 v0.2 修订来源) |
| [ANALYSIS 双维梳理](ANALYSIS-SUPERAGENT-ARCH-DATAFLOW.md) | 本设计的差距依据(架构/数据流双维) |
