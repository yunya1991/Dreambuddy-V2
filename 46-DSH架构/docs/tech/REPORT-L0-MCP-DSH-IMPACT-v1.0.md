# REPORT:L0 底层能力 MCP 封装对 DSH 架构升级的影响评估与建议

> **版本**: v1.0 ｜ **日期**: 2026-11-02 ｜ **状态**: 🔬 待评审
> **报告类型**: 影响评估与决策建议(非实施方案)
> **范围**: L0 六域(认知/数据/检索/库管/评测/REA)的 MCP 封装形态,及其对 DSH(Router/Worker 多 agent + 事件驱动)升级的影响
> **配套文档**:
> - [ANALYSIS-L0-MCP-ENCAPSULATION v0.2](ANALYSIS-L0-MCP-ENCAPSULATION.md)(评估底稿)
> - [DESIGN-SUPERAGENT-FUSION v0.2](DESIGN-SUPERAGENT-FUSION.md)(融合设计:借壳灌芯)
> - [SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2](SPEC-EVENT-DRIVEN-L1-GATEWAY.md)(事件驱动网关)
> - [SACG_A_SUPERAGENT_CONNECTION_SPEC v0.2](../../../../1-ARCHITECTURE/specs/SACG_A_SUPERAGENT_CONNECTION_SPEC.md)(A 层契约桥接)
> **口径**: v4.0 新 SACG;L0/L1/L2 为系统能力架构,与认知系统 C1-C4 严格区分

---

## 一、执行摘要

### 1.1 五条结论

1. **定位**:MCP 应定位为 **L0 的对外统一出口(边界适配层)**,不是内部调用链改造。内部 L1/L2 继续走 in-process port;外部 Trae/DSH Worker/云端 Agent 走 MCP。把 MCP 当唯一通道会同时击穿 L1 零 token 低延迟与 FAIL-OPEN 语义。
2. **对 DSH 升级的价值 = 高(★★★★☆)**,但**价值来源不是 MCP 协议**,而是"按能力域封装 = **权限边界 + 部署边界 + 证据边界**"恰好对上多 agent 架构的三个刚需。
3. **边际成本低**:DSH 已在消费 MCP(`cognitive_loop_adapter.py` 经 MCP 调认知且 FAIL-OPEN),`.dsh-home/profiles/web` 工具面本就来自 bundle。不是新引入通道,是规范化已有通道。
4. **最大风险**:①**工具面膨胀**——若把 6 域全部工具摊给每个 Worker,直接恶化 Super-agent 设计要解决的注意力预算问题;②**多 Worker 并发写认知库**——污染放大。
5. **分域不要齐步走**:评测(45)与数据(18/19/20/21)优先(Worker 价值来源与升级后门禁);检索保持聚合;库管(38)**只读、不做写**;REA 最后。

### 1.2 一句话建议

**先设计"能力集",再拆 MCP server;写类工具必须 scope 化并与 Ticket Mandate 授权绑定;热路径不迁 MCP。**

### 1.3 需要用户拍板的 4 项

| # | 决策项 | 建议 |
| --- | --- | --- |
| D1 | 是否确认"对外出口"定位(而非唯一通道) | 确认 |
| D2 | 服务聚合粒度:一域一 server vs 2-3 个聚合 server | 2-3 个聚合(认知+检索 / 数据+库管只读 / 评测+REA) |
| D3 | 库管域是否确认不做通用写工具 | 确认(只读 + CLI/CI 保留) |
| D4 | 延迟 SLO 取值(in-process P50 <5ms / MCP 本地 <50ms / 远端 <200ms) | 确认或调整 |

---

## 二、评估基准与现状(代码级核实)

### 2.1 现状核实表

| 域 | 你方口径 | 核实结果 | 代码证据 |
| --- | --- | --- | --- |
| 认知 MCP | 已存在(模板) | ✅ 已存在,stdio JSON-RPC,7 工具(recall/record/verify/stats/health/l4_status/unified_search) | `4-MEMORY/9-工具与接口/cognitive_mcp_server.py`(840 行) |
| 检索 MCP | 41+Chroma+recall,已落地 | ⚠️ **不是独立 server**,`unified_search` **已在认知 MCP 内** | 同上,工具入口约 L575 |
| REA MCP | 成熟度待评估 | ✅ 已有 adapter + 单测(218 行);做梦器/反思为长任务 | `33-REA逆向解析工程/adapters/rea_mcp_adapter.py` |
| 评测 MCP | 刚收口,P2-9 | ⚠️ 为 **FastAPI**(`api/server.py`+`routes.py`),非 MCP;需适配层 | `45-评测系统/api/` |
| 数据 MCP | 19 DAL 四后端、18 已接 job_runs | ❌ **无 MCP 面**;数据链路在进程内 | 19-DAL / 18-scheduler |
| 库管 MCP | migrate/sync 脚本现状 | ❌ 仅 CLI,无服务面 | `38-数据库管理系统` |

### 2.2 三个现状级发现(影响价值判断)

1. **认知 MCP 当前经 `ssh dreambuddy-remote` 到云端**(`.trae/mcp.json`)——本地调用也跨网,延迟与单点已实际存在,不是理论风险;
2. **已有 3 个 MCP 面(认知/REA/39 金融语义),但契约不统一**——先统一契约再扩面,顺序不能反;
3. **DSH 已在用 MCP**:`DSH_SUBAGENT_ARCHITECTURE_SPEC.md` L62-85 明确"recall 封装已存在,MCP 不可用时返回 []"(HC-3 FAIL-OPEN);web profile 的 `cordis.patch.yml` 为空 patch,工具面来自 bundle。

---

## 三、对 DSH 升级的影响评估(六维矩阵)

### 3.1 架构维度

| 影响点 | 评估 |
| --- | --- |
| Worker 工具面 | **正向,决定性**:Worker 是独立 LLM 会话,接触 L0 唯一方式是工具调用;MCP 提供跨 Harness 稳定契约(换 harness 不换工具面) |
| Router 决策负担 | **负向,需治理**:工具面越大,Router 选择成本与误选率越高;必须用"能力集"限流 |
| bundle 装配 | 正向:MCP server 可作为 bundle 依赖声明,profile 级启用/禁用,天然契合"独立 profile 试用" |
| 内核耦合 | 正向:server 进程边界使 L0 内部重构对内核透明 |
| 架构风险 | **若把 server 数当 tool 数,架构收益反转为负债**(详见 §5 R1) |

### 3.2 数据流维度

目标链路:`事件 → L1 网关 → L2(S→A→C→G) → Worker → [MCP] → L0 → settle → L0 → recall`

| 环节 | 影响 |
| --- | --- |
| L1 判定 | **不得走 MCP**(零 token 与低延迟承诺);in-process port |
| L2 → Worker 工具调用 | 走 MCP,天然带 span 边界 |
| Worker → L0 上下文 | MCP 返回须经**统一信封映射层**还原 `ok/data/source/timestamp/degraded/meta`;MCP error/timeout ≠ degraded,源可达无数据仍 ok+None |
| settle | 经 MCP 写回认知/案例/知识/SKILL/文档索引(五系统口径);须幂等(external_id) |
| 观测 | trace_id 必须跨 Router→Worker→MCP→DAL 透传,否则五跳链路不可定位 |

### 3.3 权限与安全维度

| 影响 | 说明 |
| --- | --- |
| 正向 | 按域 scope 化(读/写/admin),取代"任意脚本可读写"的现状 |
| 正向 | **Mandate 即能力授权**:Ticket 携带"允许调用的 MCP 工具集",与预算上限同源(融合设计 F3) |
| 风险 | `record`/`verify` 为写工具,N 个 Worker 并发写会放大认知污染 → 写工具默认禁用 + 显式授权 + 45 门禁 |
| 风险 | 数据 MCP 必须**只经 19-DAL**,禁止 server 内直连 PG/CH;库管禁止暴露裸 SQL |

### 3.4 质量与证据维度

| 影响 | 说明 |
| --- | --- |
| 正向 | 每次 MCP 调用 = 天然 span 边界,45 的 Evidence Bundle 可直接引用**调用链**而非 Worker 自报 |
| 正向 | 工具 schema 可版本化 → 45 可对 MCP server 做**契约评测**(schema 兼容性 + FAIL-OPEN 行为回归) |
| 风险 | 契约漂移(6 server 各自演进)→ 需契约注册表 + 变更评审 |

### 3.5 运维维度

| 影响 | 说明 |
| --- | --- |
| 负向 | 6 个常驻 server + ssh + systemd,运维面上升;故建议 **2-3 个聚合 server** |
| 正向 | 故障域隔离:单域崩溃不影响其他域与内核 |
| 风险 | 认知 MCP 的 ssh 远端单点,需改"本地直连为主 + 远端可选" |

### 3.6 成本维度

| 成本项 | 影响 |
| --- | --- |
| Token(工具描述) | 每个 Worker 上下文都带工具 schema;6 域全量暴露会显著抬升 → 能力集按角色裁剪 |
| Token(Router 决策) | 工具面越大,决策 token 与误选率上升(Super-agent 实测 Router 决策昂贵,故用批处理摊销) |
| 连接 | **正向**:多 Worker 并发时避免 N×DB 连接,server 作单点连接池 |
| 运维人时 | 负向:进程/契约/版本维护 |

---

## 四、价值分级结论

`价值 ≈ (调用频次 × 隔离/权限收益 × 跨端复用度) / (延迟 × 工具面膨胀 × 运维成本)`

| 域 | 频次 | 权限收益 | 跨端 | 综合 | 建议形态 |
| --- | --- | --- | --- | --- | --- |
| 检索/认知读(recall/search/stats) | 极高 | 中 | 高 | ★★★★★ | 保持聚合在认知 server,稳定工具名 |
| 数据(18/19/20/21) | 高 | 高(只经 DAL) | 高 | ★★★★★ | 新建,只读 + 查询/快照/特征 |
| 评测(45) | 中 | 极高(门禁) | 高 | ★★★★★ | 新建适配层,异步两段式 submit/poll |
| 认知写(record/verify) | 高 | 极高 | 中 | ★★★★☆ | scope 化,默认禁,与 Mandate 绑定 |
| REA(逆向解析/做梦器) | 中低 | 中 | 中 | ★★★☆☆ | 已有 adapter,长任务两段式,shadow 起步 |
| 库管(38) | 极低 | 极高(方向=禁止) | 低 | ★☆☆☆☆ | **只读**(表结构/迁移状态/一致性),写走 CLI+CI |

**加权:★★★★☆(高)。** 若违反"能力集"前提 → 降至 ★★☆☆☆。

---

## 五、风险登记册

| # | 风险 | 等级 | 触发条件 | 对策 |
| --- | --- | --- | --- | --- |
| R1 | 工具面膨胀导致 Router/Worker 性能与成本恶化 | **高** | 6 域工具一次性全量暴露 | 能力集按 Worker 角色裁剪(5-10 工具);MCP 工具分组/按需加载 |
| R2 | 多 Worker 并发写认知库,污染放大 | **高** | record/verify 无 scope、无幂等 | 写工具默认禁用 + Mandate 授权 + external_id 幂等(C8 先例) |
| R3 | MCP 失败语义破坏 FAIL-OPEN 与降级文案 | **高** | 直接把 MCP error 当 degraded 或当 ok | 统一信封映射层;degraded/reason 三值不混同;源可达无数据=ok+None |
| R4 | 延迟击穿 L1 零 token 承诺 | 中高 | 热路径走 MCP | 热路径 in-process;三条延迟 SLO |
| R5 | 绕开 DAL 直连数据库 | 中高 | 数据/库管 server 自建连接 | 强制只经 19-DAL;禁止裸 SQL |
| R6 | 契约漂移、工具名不稳定 | 中 | 6 server 独立演进 | 契约注册表 + 语义化版本 + 变更评审 |
| R7 | 观测断裂(五跳无 trace) | 中 | trace_id 未透传 | 全链路 trace_id;每跳统一信封 |
| R8 | 运维面上升与 ssh 单点 | 中 | 一域一进程 + ssh 远端 | 2-3 聚合 server;本地直连优先 |

---

## 六、建议

### 6.1 总体建议(三句话)

1. **定位**:MCP = L0 对外出口;内部 in-process port 不动。
2. **顺序**:先能力集设计,再 server 拆分(反了必返工);先契约,后扩面。
3. **治理**:写工具 = 权限单元 = Ticket Mandate;库管不做写;热路径不迁 MCP。

### 6.2 分阶段路线

| 阶段 | 内容 | 前置 | 验收 |
| --- | --- | --- | --- |
| **P0** | ①能力集设计(Worker 角色→工具集矩阵)②认知 MCP 读/写分 scope(写默认禁)③契约注册表 v1 + 统一信封映射层 | 无 | 能力集矩阵评审通过;写工具越权调用被拒 |
| **P1** | ①评测 MCP(异步 submit_run/poll_run,复用 45 api)②数据 MCP(只经 DAL,只读) | P0 契约注册表 | 两段式跑通;DAL 审计无旁路 |
| **P2** | ①检索工具稳定化(仍聚合)②REA MCP shadow 观察③认知 MCP 本地直连改造(消 ssh 单点) | P1 | shadow 期无回归;远端不再单点 |
| **P3** | ①库管只读工具(表结构/迁移状态/一致性)②45 增加"契约评测"维度 | P2 | 契约评测可拦截 schema 破坏 |

### 6.3 文档变更清单(与本报告配套)

| # | 文档 | 状态 | 动作 |
| --- | --- | --- | --- |
| 1 | [ANALYSIS-L0-MCP-ENCAPSULATION v0.2](ANALYSIS-L0-MCP-ENCAPSULATION.md) | ✅ 已更新 | 评估底稿(§八 DSH 价值分级) |
| 2 | [SPEC-EVENT-DRIVEN-L1-GATEWAY v0.2](SPEC-EVENT-DRIVEN-L1-GATEWAY.md) | ✅ 已打补丁 | L0 访问 port 双通道 + MCP 信封映射(HC-3) |
| 3 | `35-广义认知系统协作模块/COLLABORATION-CONTRACT.md` | ⏳ 待改 | 认知 MCP 工具面(含 scope 与写门禁)纳入协作契约——**建议第一个改** |
| 4 | `1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md`(v4.0 SSoT) | ⏳ 待评审 | L0 增「统一出口层:port / MCP」小节 |
| 5 | `45-评测系统/SPEC-评测系统.md` | ⏳ P3 可选 | 增「契约评测」维度 |

### 6.4 可测验收标准

| # | 标准 |
| --- | --- |
| V1 | 能力集矩阵覆盖全部 Worker 角色,每角色工具数 ≤10 |
| V2 | 越权调用写工具返回明确拒绝(非静默降级),审计留痕 |
| V3 | MCP 通道返回统一信封,degraded/reason 与 ok+None 三态可区分(单测覆盖) |
| V4 | 热路径 P50 延迟不劣化(in-process 基线对比) |
| V5 | trace_id 端到端贯穿率 100%(Router→Worker→MCP→DAL) |

---

## 七、结论

对即将升级的 DSH 架构而言,**L0 按能力域封装 MCP 是必要基础设施,而非可选项**——因为 Worker 只能通过工具获得 L0 能力。但其价值不在协议,而在**三边界**:权限(写工具与 Mandate 授权)、部署(进程隔离与连接池)、证据(span 与 Evidence Bundle)。

**做得对 = 融合 A 步成本大降、Worker"有手有术";做得错 = Router 被工具面压垮、认知库被并发写污染。** 因此本报告的核心建议只有一条:**先能力集,后拆服务;先契约,后扩面;写工具入 Mandate,热路径留 in-process。**
