# ANALYSIS:Super-agent × DreamOS 架构与数据流双维梳理

> **版本**: v1.0 ｜ **日期**: 2026-11-02 ｜ **状态**: 定稿(评审输入件)
> **依据三份文档**:
> 1. [Super-agent 调研与对比分析](../../../2-KNOWLEDGE/7-EXTERNAL-RESEARCH/technical/architecture/2026-11-02-DeepSeek-Super-agent架构调研与DreamOS对比分析.md)(调研+逐项映射,第一~九章)
> 2. [SACG_A_SUPERAGENT_CONNECTION_SPEC](../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md)(契约桥接,待评审)
> 3. [SPEC-EVENT-DRIVEN-L1-GATEWAY](SPEC-EVENT-DRIVEN-L1-GATEWAY.md)(事件驱动网关,待评审)
> **口径**: v4.0 新 SACG(S=认知规划/A=OKR验收/C=执行驱动/G=压缩沉淀)

---

## 一、架构维度

### 1.1 Super-agent 六项先进性(架构层)

| # | 先进性 | 机制本质 | 实测/证据 |
| --- | --- | --- | --- |
| 1 | **Router/Worker 双层分离** | Router=全局上下文+统一对外+分派;Worker=隔离会话并发执行 | 原型已验证 Issue→PR 无人干预 |
| 2 | **事件驱动+两级过滤** | Trigger 统一抽象;程序规则+LLM 两级;**Thread 订阅直通** | 取消直通→Router 决策 +30%、缓存读 +37% |
| 3 | **Router 批处理** | 按周期聚合积压事件成单轮,摊销 LLM 成本 | 40 条/分高负载 1.6s/决策 |
| 4 | **Ticket 双内核** | 协作任务单(Mandate)+资源账单(预算上限+扣减) | 原型 2.7k 行已含扣减逻辑 |
| 5 | **三级状态全生命周期** | Thread 5 态 / Ticket 8 态 / Session;连续+持久 | tests 覆盖状态迁移 |
| 6 | **Watchdog 独立监督** | 独立会话巡查:进展真实性/目标偏离/风险升级/资源约束 | 定位=外部控制回路 |

贯穿性思想:**注意力预算**(人只能跟进 3-5 个 Session → 并行+批处理+投机执行+静默原则)。

### 1.2 组件级映射(Super-agent ↔ DreamOS)

| Super-agent | DreamOS(v4.0) | 差距判定 |
| --- | --- | --- |
| Router | C-drive 调度者语义 + S 层入口 | ⚠️ 有种子,无独立常驻形态 |
| Worker(Harness session) | C 层 DSH 子 agent | ✅ 零适配(同源:DSH=DeepSeek Harness) |
| Ticket Mandate | A 层 OKR 节点契约(objective/criteria/verify) | ✅ 结构同构,缺状态机 |
| Ticket 资源账单 | 预算约束散落(Memory/37) | ⚠️ 未契约化 |
| Trigger+两级过滤 | L1 意图注册表+路由器(零 token) | ✅ 我们更强(三级梯度,见下) |
| Thread 订阅直通 | 无(subagent 一次性调用) | ❌ 明确缺口 |
| Inline & Spill / Chain of Recall | L0 fetchContext 六维供给 + 认知 recall | ✅ 我们远超(领域供给层) |
| Watchdog | C-drive 反思器语义(jev 门) | ⚠️ 有种子,链内而非独立回路 |
| Store(会话状态) | L0 云端 PG/认知库 + 37 memory | ✅ 状态层更强 |
| 自研 eval 脚本 | 45-评测系统(收口门禁+证据链) | ✅ 我们远超(工程级门禁) |
| (无) | 广义认知 C1-C4 / A1 混合编排 / REA | ✅ 我们独有 |

### 1.3 架构维度结论

**互补而非替代**:Super-agent 强在**多任务广度与持续性**(并行、常驻、事件驱动、人机注意力);我们强在**单任务深度与质量闭环**(认知规划、OKR 验收、独立评测收口、自进化)。同源关系使吸收成本低:Worker 层零适配,连接点落在 **A 层契约翻译**(SPEC #2)与 **L1 事件网关**(SPEC #3)两个点,而非架构改造。

---

## 二、数据流维度

### 2.1 四条流逐项对比

**流① 事件流(触发→分派)**

| | Super-agent | DreamOS 现状 | 融合设计(SPEC #3) |
| --- | --- | --- | --- |
| 入口 | Trigger 统一抽象(IM/GitHub/日程/系统) | 同步用户请求为主;轮询散落各进程 | Trigger 契约 + SourceAdapter(定时器/行情阈值/文件落盘先行) |
| 过滤 | 程序规则→LLM(两级,token) | L1 意图路由(零 token) | **三级梯度**:L1 过滤→L1 确定性闭环→L2 |
| 分派 | Router→Thread/Ticket | (无) | 升级 L2 时携带 thread_id,为直通预留 |
| 成本控制 | 批处理摊销(1.6s/决策) | L1 零 token=无限批处理 | 批合并+冷却窗口+L1 覆盖率驱动 |

**流② 上下文流(给 LLM 喂什么)**

| | Super-agent | DreamOS |
| --- | --- | --- |
| 机制 | Inline & Spill + Chain of Recall(**会话历史管理**,限于事件流本身) | L0 fetchContext **六维领域供给**:实时数据指标(medallion Gold)/SKILL/知识库/认知经验/CBR 真实案例/REA 逆向解析(最优路径) |
| 判定 | ❌ 无领域供给层 | ✅ 核心差异化:**事件带完整作战地图进 L2** |

**流③ 状态流(存算分离)**

| | Super-agent | DreamOS 现状 | 缺口 |
| --- | --- | --- | --- |
| 状态 | 云端 Store(Thread/Ticket/Session 持久化) | L0 云端 PG/认知库/REA ✅ | — |
| 计算 | 云端 Agent | L2 推理可云端 ✅;L1 无状态任意端 ✅ | — |
| 执行环境 | 本地轻量 daemon(BYOM) | 本地 37-一键启动分层管理 ⚠️ 雏形 | ❌ 会话级离线续跑 |
| 分离轴 | **会话连续性轴** | **职能轴**(本地评审/GitHub 存证/云端运行) | 两轴叠加为终态 |

**流④ 反馈流(结果→沉淀→下次更聪明)**

| | Super-agent | DreamOS(45 入环后) |
| --- | --- | --- |
| 结果验收 | Ticket status=done(Worker 自报为主) | **45 评测门禁**(PASS/BLOCK/INCONCLUSIVE)+ Evidence Bundle(WORM 哈希链) |
| 沉淀 | Session 历史 | settle→L0(认知蒸馏/CBR 案例/记忆),**沉淀前过 45** 防污染 |
| 自进化 | (无) | 下次事件 recall 命中 = 事件驱动自进化循环 |

### 2.2 融合后的目标数据流(一张图)

```
外部事件 → [L1 事件网关] 零token三级梯度 ──命中──→ L1 确定性闭环
                │未命中+高价值
                ▼
        [L0 fetchContext 六维供给] ←──┐
                ▼                     │ REA/经验/案例/实时数据
        [L2 新 SACG:S→A→C→G]          │
          C层=DSH Worker(同源零适配)  │
                ▼                     │
        [45 评测门禁] PASS/BLOCK/INCONCLUSIVE
                │ PASS                │
                ▼                     │
        [settle 沉淀 L0] ─────────────┘
        (A层 evidence_backed 消费 45 Evidence Bundle)
```

### 2.3 数据流维度结论

- Super-agent 数据流是**"事件-会话"闭环**,以注意力为中心;我们是**"数据-认知-沉淀"闭环**,以知识与质量为中心;
- 它的长板(事件流入口、批处理、直通)恰是我们的缺口;我们的长板(六维供给、45 门禁、自进化沉淀)恰是它的空白;
- 融合不是两套系统对接,而是**同一条流的上下游补全**:它补我们的"入口",我们补它的"腹地"。

---

## 三、双维交叉:先进性吸收矩阵

| Super-agent 先进性 | 架构吸收点 | 数据流吸收点 | 落档 |
| --- | --- | --- | --- |
| 事件驱动+两级过滤 | L1 事件网关(三级梯度) | 流① 统一 Trigger+三分流 | SPEC #3 P0 |
| Thread 订阅直通 | A 层节点状态机化 | 流① 后续事件绕 Router 直送 | SPEC #2 P1 |
| Ticket 双内核 | OKR→Mandate 契约翻译器 | 流① 分派单元+预算扣减 | SPEC #2 P0 |
| Watchdog | C-drive 反思器外化独立会话 | 流④ 外部监督回路 | SPEC #2 P2 |
| 存算分离/BYOM | 三端职能轴+会话连续性轴叠加 | 流③ 离线续跑 | SPEC #2 P1/后续 |
| Router 批处理 | L1 批合并+冷却窗口 | 流① 成本控制 | SPEC #3 P0 |
| (我方独有输出) | 45 评测收口+A 层验收 | 流②④ 供给与防污染 | 45 入环三接入点 |

## 四、落地索引与评审焦点

1. **SPEC #2(SACG_A 契约桥接)**:P0=试用 bundle+翻译器;评审焦点=翻译器归属边界、Ticket 数据库选型、45 证据包消费;
2. **SPEC #3(事件驱动 L1 网关)**:P0=Trigger 契约+网关+2 事件意图+45 shadow;评审焦点=与 SPEC #2 先后关系、事件意图归属、shadow 转正判据;
3. **45 入环**:settle 前置门禁(shadow→强制)、evidence_backed 消费 Evidence Bundle、大模型开发后验收;
4. 两个 SPEC 评审通过后,按 P0→P1→P2→P3 推进,全程模块化开关+FAIL-OPEN+9 条既有架构硬约束。
