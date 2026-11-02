# ANALYSIS:L0 能力 MCP 化评估与分层约定

> **版本**: v0.2 ｜ **日期**: 2026-11-02 ｜ **状态**: 📚 评估归档——**MCP 域设计以 47-MCP管理系统 SPEC 为 SSoT**(本文档仅保留评估依据,不再作为实现依据;数字与现状以 [REPORT-L0-MCP-DSH-IMPACT v1.1](REPORT-L0-MCP-DSH-IMPACT-v1.1.md) 勘误 F1/F2/F6/F7 为准,含『聚合 2-3 个 server』与『连接池收口』两处结论的修正)
> **v0.2 变更**: 新增 §八「面向 DSH 升级的价值分级」——从通用 MCP 优劣转向对 DSH 多 agent 架构的价值高低
> **问题**: 是否将 L0 基础能力(认知/数据/检索/库管/评测/REA)统一通过 MCP 封装?优劣如何?技术文档需否调整?
> **依据**: v4.0 架构总览 L0 定义、35 号域 SPEC-CognitiveSystem-Evolution / COLLABORATION-CONTRACT、[SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2](SPEC-EVENT-DRIVEN-L1-GATEWAY.md)、[DESIGN-SUPERAGENT-FUSION v0.2](DESIGN-SUPERAGENT-FUSION.md)

---

## 一、结论先行

**1. 定位判断(最关键)**:MCP 化应是 **L0 的"对外统一出口"(边界适配层)**,不是内部调用链改造。
- **内部**(L1/L2 同进程调用 L0)→ 继续走 **in-process port**(低延迟、强一致、FAIL-OPEN 天然);
- **外部**(Trae / DSH Worker / 云端其他 Agent / 三端协同)→ 走 **MCP**。

把 MCP 当成"唯一通道"会同时牺牲 L1 的零 token 低延迟承诺和 FAIL-OPEN 语义,**这是最大的误判风险**。

**2. 六域分级**:A 类可直接推进(认知/数据/检索/评测);B 类需异步两段式(REA);**C 类禁止通用写工具(库管)**。

**3. 三份文档的结论**:需要优化 4 处(见 §六),其中 **SPEC#3 事件网关必须改**(L0 调用需明确 port 双通道与 MCP 失败→degraded 映射);SACG_A SPEC 与融合设计 **不需要改**(MCP 化反而是融合的加分项)。

---

## 二、现状核实(代码级)

| 域 | MCP 覆盖 | 实际现状 | 判定 |
| --- | --- | --- | --- |
| 认知 MCP | 4-MEMORY 五类四层 | ✅ 已存在:`cognitive_mcp_server.py`(840 行,stdio JSON-RPC),工具 7 个:recall/record/verify/stats/health/l4_status/**unified_search** | 已有基线,需增强 |
| 检索 MCP | 41 + Chroma + recall | `unified_search` **已在认知 MCP 内** | 已覆盖,只是位置在认知 server |
| 数据 MCP | 18+19+20+21 | 19-DAL 四后端、18 scheduler 已接 job_runs;**无 MCP 面** | 待新建 |
| 库管 MCP | 38 | migrate/sync **为 CLI 脚本**,无 API/服务面 | 待评估(倾向只读) |
| 评测 MCP | 45 | `api/server.py` + `routes.py` 为 **FastAPI**,非 MCP | 待新建(适配层) |
| REA MCP | 33(做梦器+反思) | ✅ 已有 `adapters/rea_mcp_adapter.py`(218 行)+ 单测 | 已有,成熟度待验证 |

**两个现状级发现**:
1. **认知 MCP 当前经 `ssh dreambuddy-remote` 到云端**(见 `.trae/mcp.json`)——本地调用也要跨网,延迟与单点风险已存在,不是理论问题;
2. **MCP 面数量已是 3 个(认知/REA/39 金融语义)但契约不统一**——先统一契约,再扩面,顺序不能反。

---

## 三、MCP 化的收益(6 条)

| # | 收益 | 说明 |
| --- | --- | --- |
| R1 | **统一工具契约** | 一域一 server,工具 schema 版本化;取代"每端一套 SSH/py 脚本/HTTP"的现状 |
| R2 | **Super-agent 融合天然加分** | Worker 本质就是工具调用者;L0 若已是 MCP 面,Worker 零适配直接可用——**这条把融合设计 A 步的成本大幅降低** |
| R3 | **权限与审计边界清晰** | 按域 scope 化(读/写/admin),写工具可单独禁用;审计在 server 入口统一埋点 |
| R4 | **故障隔离** | server 进程崩溃不拖内核;单域降级不影响其他域 |
| R5 | **演进解耦** | L0 内部重构(如 DAL 换后端)对调用方透明 |
| R6 | **三端同一契约** | 本地/云端/GitHub 用同一工具面,消除"本地能跑云端不行"的漂移 |

---

## 四、代价与风险(7 条,含硬约束对策)

| # | 风险 | 对策(建议入硬约束) |
| --- | --- | --- |
| X1 | **延迟破坏 L1 承诺** | 跨进程 ≥ 数十 ms,ssh 远端更甚;L1 热路径**必须 in-process**,MCP 只服务跨端/非热路径。定 SLO:in-process P50 <5ms,MCP 本地 P50 <50ms,MCP 远端 P50 <200ms |
| X2 | **FAIL-OPEN 语义断裂** | MCP 的 error/timeout 不是 `degraded` 信封;必须有**统一信封映射层**:`ok/data/source/timestamp/degraded(reason)/meta` 逐字段还原,`source_missing`/`read_error`/`timeout` 三类 reason 不得混同。**源可达无数据仍须 ok+None**(沿用既有铁律) |
| X3 | **写工具污染认知库** | `record`/`verify` 是写操作;MCP 面必须**读写分域**:外部默认只读,写工具挂 `write` scope 且默认禁用,需显式开关+45 门禁 |
| X4 | **绕开 DAL 直连库** | 数据 MCP **只允许调用 19-DAL**,禁止 server 内直连 PG/CH;库管 MCP 禁止暴露裸 SQL |
| X5 | **契约漂移** | 6 个 server 各自演进 → 需**契约注册表**(工具名/参数/返回/版本/scope),变更走评审;版本号语义化 |
| X6 | **工具数量与上下文成本** | 工具描述本身占 token,与事件网关"注意力预算"同源问题 → 按域分组暴露、支持按需加载,禁止一次性把 6 域全部工具塞进上下文 |
| X7 | **观测断裂** | 跨 MCP 无 trace → 必须透传 `trace_id`,对齐 dreamos_sessions/spans;否则事件闭环无法回到 L0 |

**另有一条运维风险**:6 个常驻 server + ssh 单点 + systemd 单元,运维面上升。建议**先聚合为 2-3 个 server**(认知聚合检索、数据聚合库管只读、评测聚合 REA 异步),而非一域一进程。

---

## 五、分层落地矩阵

| 域 | 建议 | 形态 | 前置/风险 | 优先级 |
| --- | --- | --- | --- | --- |
| **认知 MCP** | 增强 | 已有;补**读写分域**(recall/search/stats 只读;record/verify 挂 write scope 默认禁)、补 **evidence 回执**(供 45/evidence_backed 消费)、**本地直连为主 + 远端可选**(消除 ssh 单点) | X3 / X7 | P0 |
| **检索 MCP** | 保持聚合 | `unified_search` 留在认知 server(拆散会切断"检索→recall→经验"连贯链路),稳定工具名即为契约 | X5 | P0(不新建) |
| **数据 MCP** | 新建 | 工具 = 查询/快照/特征取数;后端只经 19-DAL;**L1 热路径不走 MCP** | X1 / X4 | P1 |
| **评测 MCP** | 新建 | **异步两段式**:`submit_run` 返回 run_id + `poll_run` 查裁决(对齐 45 的 Celery 异步);复用 `api/server.py` 作为后端,不重写逻辑 | X2 / X5 | P1 |
| **REA MCP** | 已验证后推广 | 已有 adapter;逆向解析/做梦器为**长任务**,同样两段式;先 shadow 观察再用 | X1 / X2 | P2 |
| **库管 MCP** | **不做通用写** | 仅暴露**只读**工具(表结构/迁移状态/一致性检查);`migrate`/`sync` 保留 CLI + CI,不进 MCP | X3 / X4 | P2(降级) |

**库管域的理由**:migrate/sync 是**不可逆运维写操作**,一旦成为通用工具面,任何 Agent 都能触发 schema 变更——收益极低、风险极高。这是本次评估唯一建议"明确不做"的项。

---

## 六、技术文档影响(明确清单)

| # | 文档 | 是否需改 | 改什么 |
| --- | --- | --- | --- |
| 1 | 本文 | — | 新增评估(本文件) |
| 2 | [SPEC-EVENT-DRIVEN-L1-GATEWAY](SPEC-EVENT-DRIVEN-L1-GATEWAY.md) | ✅ **必须改** | L0 调用改为 **port 双通道**(in-process 优先 / MCP 兜底),并明确 MCP 失败→degraded 映射(X2) |
| 3 | SYSTEM_ARCHITECTURE_OVERVIEW v4.0 | ⚠️ 建议改(需评审,SSoT) | L0 增一节「统一出口层:port(in-process) / MCP(跨端)」,避免后续文档各自理解 |
| 4 | 35 号域 COLLABORATION-CONTRACT | ✅ 应改 | 把认知 MCP 工具面(含 scope 与写门禁)纳入协作契约,成为跨系统调用的权威定义 |
| 5 | 45-评测系统 SPEC | ⚠️ 可选(P2) | 增加「契约评测」维度:工具 schema 兼容性 + FAIL-OPEN 行为回归,作为 MCP server 上线门禁 |
| 6 | SACG_A SPEC | ❌ 不改 | A 层不涉及 L0 出口 |
| 7 | 融合设计 | ❌ 不改(加分) | Worker 直接用 MCP 面属 R2,不构成新的融合点;§七 可加一句注解 |

**顺序建议**:先改 #4 契约 → 再改 #3 架构总览(评审) → 再改 #2 网关 → 最后 #5 评测门禁。**契约先行,避免 6 个 server 一边建一边改。**

---

## 七、评审焦点

- [ ] 定位是否确认:MCP = 对外出口,内部仍走 in-process port(而非唯一通道)
- [ ] 服务聚合粒度:一域一 server vs 2-3 个聚合 server(建议后者)
- [ ] 库管域是否确认不做通用写工具
- [ ] 认知 MCP 的本地直连改造是否影响现有 Trae 调用(需回归)
- [ ] X1 三条延迟 SLO 取值是否可接受


---

## 八、面向 DSH 升级的价值分级(核心问题)

### 8.1 判断基准的转移

前七章回答「L0 该不该 MCP 化」。真正的问题是:**在我们即将升级的 DSH 架构(Router/Worker 多 agent + 事件驱动)里,按能力域封装 MCP 的价值有多高?**

判断基准随之改变,因为 DSH 升级带来两个结构事实:

1. **Worker 是独立 LLM 会话**,它拿到 L0 能力的**唯一方式就是工具调用**——不存在"直接函数调用"的路径;
2. **DSH 已有 MCP 消费面**:`cognitive_loop_adapter.py` 本就经 MCP 调认知(不可用返回 [] 即 FAIL-OPEN),`.dsh-home/profiles/web` 的工具面来自 bundle。MCP 不是新引入的通道,是**已在用的通道**。

因此价值判断要分两层,结论截然不同:

| 命题 | 价值 | 理由 |
| --- | --- | --- |
| MCP 作为 **Worker 的标准工具面** | ✅ **必需(高价值)** | Worker 没有别的通道;且 MCP 是跨 Harness 通用契约(Claude/Cursor/DSH 均支持),换 harness 不换工具面 |
| MCP 作为 **L0 唯一通道**(含同进程 L1/L2) | ❌ **负价值** | 击穿 L1 零 token 低延迟 + FAIL-OPEN 语义(见 X1/X2) |

### 8.2 价值公式与分域打分

`价值 ≈ (调用频次 × 隔离/权限收益 × 跨端复用度) / (延迟 × 工具面膨胀 × 运维成本)`

| 域 | Worker 调用频次 | 隔离/权限收益 | 跨端复用 | 边际成本 | 综合价值 |
| --- | --- | --- | --- | --- | --- |
| **检索/认知读**(recall/search/stats) | 极高(几乎每次) | 中 | 高 | 低(已有) | ★★★★★ |
| **数据**(18/19/20/21) | 高 | **高**(必须只经 DAL) | 高 | 中 | ★★★★★ |
| **评测**(45) | 中(每 Ticket 1 次) | **极高**(升级后的验收门禁) | 高 | 低(FastAPI 适配) | ★★★★★ |
| **认知写**(record/verify) | 高 | **极高**(多 agent 会放大污染) | 中 | 中(需 scope) | ★★★★☆ |
| **REA**(逆向解析/做梦器) | 中低(研究型 Worker) | 中 | 中 | 中(长任务两段式) | ★★★☆☆ |
| **库管**(38) | 极低 | **极高**(方向是"禁止") | 低 | 低 | ★☆☆☆☆(只读,不做写) |

**加权结论:对 DSH 升级,按能力域封装 MCP 的价值 = 高(★★★★☆),但必须满足三条前提。**

### 8.3 三条前提(否则价值反转)

**前提一:服务端按域拆,客户端按角色裁剪——"server 数 ≠ tool 数"**
这是最容易被误做的一点。按域拆 server 是基础设施层的好事(隔离/权限/部署);但若因此把 6 域全部工具一次性暴露给每个 Worker,就直接恶化 Super-agent 设计想解决的**注意力预算**问题——Router 决策质量下降、token 成本上升、Worker 选错工具。正确做法:server 端按域、Worker 端按角色给**能力集(capability set)**,每类 Worker 只看到 5-10 个工具。

**前提二:写类工具 = 权限单元 = Ticket Mandate 的授权单元**
`record`/`verify` 在多 agent 下不再是单 agent 的"顺手写"——N 个 Worker 并发写会**放大认知污染**。而融合设计 F3 的 Ticket 双内核(Mandate + Budget)恰好提供天然载体:让 Mandate 携带"允许调用哪些 MCP 工具"即**能力授权**,与预算上限同源。**这是 MCP 域化与 DSH Ticket 体系最巧的咬合点**,价值远超技术便利。

**前提三:热路径不迁 MCP**
L1 判定、同进程 L2 编排继续 in-process port;MCP 服务跨端 Worker 与非热路径。这条不满足,前两条都白讲。

### 8.4 DSH 升级才出现的三个新增收益

| 收益 | 说明 |
| --- | --- |
| **连接池收口** | 多 Worker 并发时若各自连 DAL/PG 会出现 N×连接爆炸;MCP server 是天然的单点连接池边界——多 agent 才有的实际问题,单 agent 时代不存在 |
| **失败域隔离** | 一个域 server 挂掉只影响用到它的 Worker,不拖垮整个 Router 编排(与 Watchdog 的资源约束巡查天然配合) |
| **证据边界** | 每次 MCP 调用 = 天然 span 边界,带 trace_id 落 dreamos spans;45 的 Evidence Bundle 因此可直接引用调用链,而非靠 Worker 自报 |

### 8.5 DSH 升级才出现的两个新增代价

| 代价 | 说明 | 对策 |
| --- | --- | --- |
| **并发写冲突** | 多 Worker 同时 record/verify → 认知库写放大、同 entity 冲突 | 写工具串行化 + external_id 幂等(已有 C8 先例) + Mandate 授权 |
| **调试链路变深** | Router→Worker→MCP→DAL→DB 五跳,失败定位困难 | trace_id 全链路 + 每跳统一信封,缺一不可 |

### 8.6 一句话结论

**高价值,但价值来源不是「MCP 这个协议」,而是「按域封装 = 权限边界 + 部署边界 + 证据边界」这三件事恰好对上 DSH 多 agent 的三个刚需。** 协议只是实现手段;若做成"6 个 server 把全部工具摊给所有 Worker",价值立刻从 ★★★★☆ 掉到 ★★☆☆☆。

### 8.7 对 DSH 升级落地的建议顺序

1. **先做能力集设计**(Worker 角色 → 可见工具集),再做 server 拆分——顺序反了会返工;
2. 认知域读/写分 scope(写默认关),与 Ticket Mandate 授权绑定;
3. 评测域先做(升级后的门禁,必须先有);数据域次之(Worker 的实际价值来源);
4. 检索保持聚合,不做独立 server;
5. 库管仅只读;REA 最后(shadow 起步)。
