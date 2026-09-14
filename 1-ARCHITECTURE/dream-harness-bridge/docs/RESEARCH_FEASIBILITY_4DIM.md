# dream-harness-bridge 四维度可行性深度调研报告

> **版本**: v0.1
> **状态**: 🔬 调研完成，待 SPEC 修正
> **创建日期**: 2026-09-13
> **方法论**: A1 SKILL 四维验证（假设→A哲学+C案例→B流派+D实证）
> **前置文档**: [SPEC.md](../SPEC.md) v0.2 | [RESEARCH_DEEPSEEK_HARNESS.md](../../前端设计/RESEARCH_DEEPSEEK_HARNESS.md)

---

## 一、调研背景与核心假设

### 1.1 调研目标

对 SPEC v0.2 的"路径 E 分层嵌入"方案，从四个维度验证可行性：
- **维度A**（代码工程开发原理和实践准则）
- **维度C**（经典代码工程拆解）
- **维度B**（传统代码开发流程和方案）
- **维度D**（实际成熟工程实证）

### 1.2 五个核心假设

| 编号 | 假设 |
|------|------|
| H1 | 跨语言（TS+Python）的 agent runtime 整合是可行的 |
| H2 | 分层嵌入（而非重写或黑盒）是正确的整合模式 |
| H3 | IPC（stdio NDJSON）是合适的跨语言通信机制 |
| H4 | Harness preview 阶段（v0.1.x）可以作为基座（配合版本锁定） |
| H5 | 硬约束（交易安全规则）可以在跨进程场景下保持生效 |

### 1.3 调研方法论

遵循 A1 SKILL 四步路径：
1. 提出假设（SPEC v0.2 的 5 个假设）
2. 维度A 哲学 + 维度C 案例验证
3. 维度B 流派 + 维度D 实证验证
4. 综合判据与 SPEC 修正建议

### 1.4 已知经验引用（来自认知记忆库 recall）

| 记忆 ID | 经验 | 对调研的价值 |
|---------|------|-------------|
| VM-1789089211280 | segfault 几乎总是原生库 ABI/OMP 问题，隔离 import 链可证伪 | 跨语言原生库风险真实，需 lazy import |
| VM-1789171650348 | 写入链路断裂反模式：模块实现+测试通过但数据流断裂 | 跨语言下此反模式更高发，需链路活性测试 |
| VM-1789187703090 | FAIL-OPEN + 开关控制（默认关）是已验证模式 | 跨进程需升级为分路径 fail 策略 |

---

## 二、维度A：代码工程开发原理和实践准则

### A1. 微内核架构原理（OSGi / Eclipse 风格）

**对 5 假设的判断**：H1 支持 / H2 支持 / H3 有条件支持 / H4 有条件支持 / H5 支持

微内核"内核极简+能力皆 plugin"是设计原则，不是语言约束。OSGi/Eclipse 的 bundle 机制依赖 JVM classloading——这是 JVM 实现选择，不是微内核本质。

**关键洞察**：跨语言 plugin 的正确接入方式不是"让 Python 直接成为 Cordis plugin"，而是"TS adapter 是 Cordis plugin（同语言），adapter 包装 Python IPC server"。Cordis 看到的始终是同语言 plugin，跨语言复杂性被封装在 adapter 内。

**边界**：微内核的"能力发现"在跨语言下退化为 IPC 服务发现。TS adapter 必须把 Python 能力翻译成 Cordis Service Definition。这个翻译层是不可避免的复杂度来源。

### A2. 防腐层模式（Anti-Corruption Layer, ACL）

**对 5 假设的判断**：H1 支持 / H2 支持 / H3 有条件支持 / H4 有条件支持 / H5 支持

DreamBuddy SACG 作为 Cordis plugin 接入，TS adapter 就是 ACL。它翻译 Harness 概念（session、agent turn、tool call）↔ DreamBuddy 概念（intent、strategy gene、contradiction、memory unit）。

**"0 修改"硬约束强化了 ACL**：DreamBuddy Python 侧完全不知道 Harness 存在，概念污染无入口。

**风险点**：ACL 可能泄漏——如果 adapter 把 Harness 专有类型（如 Cordis context 对象、turn id）直接透传给 Python。IPC 契约必须是 DreamBuddy 领域形状的，不是 Harness 形状的。

### A3. 契约式设计（Design by Contract）

**对 5 假设的判断**：H1 有条件支持 / H2 支持 / H3 有条件支持 / H4 有条件支持 / H5 支持

跨语言 IPC 契约必须用语言中立形式表达。JSON Schema 是 stdio NDJSON 的自然载体，但**对 DbC 是必要不充分**：

- **前置条件**（请求验证）：JSON Schema 验证结构，不验证语义。"leverage ∈ [1,125]" schema 能做；"不超过风险预算"需要逻辑。
- **后置条件**（响应验证）：schema 验证响应形状，"必须包含 risk_check_timestamp"需要逻辑。
- **不变式**（恒真）："未通过硬约束的交易不得发出"——会话级状态不变式，无法逐消息检查，需要协议级断言。

**跨进程 DbC 核心要求**：前后双端验证。不变式必须通过协议设计强制（硬约束检查是 IPC 序列的强制步骤，不可跳过）。

### A4. 事件溯源（Event Sourcing）

**对 5 假设的判断**：H1 支持 / H2 支持 / H3 支持 / H4 有条件支持 / H5 有条件支持

Harness append-only session log 作为事件流，G 层消费做交易领域压缩——模式在事件溯源理论下成立，前提：(a) 事件是 source of truth，(b) G 层是 projection，(c) 事件不可变且带时间戳。

**跨语言事件 schema 信息损失风险**：Harness 事件是通用语义；G 层想要交易领域事件。解决方案：adapter 发"信封事件"——外层通用 Harness 事件，payload 是 DreamBuddy 领域类型。G 层消费 payload。

**stdio NDJSON 对事件溯源是优势**：单流、行分隔、天然有序。事件溯源要求 total order，stdio 单流保证顺序。

### A5. 插件架构设计原则

**对 5 假设的判断**：H1 有条件支持 / H2 支持 / H3 有条件支持 / H4 有条件支持 / H5 支持

Plugin 生命周期在跨语言下复杂性激增：

- **注册**：TS adapter 向 Cordis 注册（同语言，正常）。Python 侧注册=spawn Python IPC server。
- **激活**：跨进程激活=进程启动成本（Python cold start ~200-500ms + 重库 import）。
- **卸载**：Cordis"可逆 plugin"在跨进程下**只能近似**。进程 kill 是不可逆的（内存状态丢失）。可逆性成立当且仅当 plugin 无状态或状态外置。

**DreamBuddy 是有状态的**（memory DB、持仓）。真可逆卸载需要状态迁移或外置持久化。SPEC 应明确：plugin 卸载语义是"停止进程"，重启=从持久化恢复，不是内存级可逆。

### A6. 跨语言通信原理

**对 5 假设的判断**：H1 支持 / H2 支持 / H3 支持（有条件）/ H4 支持 / H5 有条件支持

| 维度 | stdio NDJSON | gRPC | Thrift | HTTP JSON-RPC |
|------|-------------|------|--------|--------------|
| 延迟 | ~0.1-1ms（pipe） | ~1-5ms | ~1-5ms | ~5-20ms |
| 类型安全 | 无（JSON） | 强（proto） | 强（IDL） | 无 |
| 调试 | 极佳（cat 流） | 难（二进制） | 难 | 好（文本） |
| 流式 | 行分隔天然支持 | 双向流 | 支持 | 有限 |
| 错误传播 | JSON error 字段 | status code | 异常 | HTTP code |

**stdio NDJSON 在 preview 阶段是正当默认**：调试性 > 类型安全（preview 期快速迭代）。类型安全可由共享 JSON Schema + 代码生成补偿。

**SPEC 修正**：必须定义迁移路径——当类型安全/性能成为瓶颈时，迁移到 gRPC + proto。Grafana 案例（C3）证明 gRPC 是生产级跨语言 plugin 传输。

### A7. FAIL-OPEN 原则

**对 5 假设的判断**：H1 支持 / H2 支持 / H3 有条件支持 / H4 支持 / H5 强支持

**跨语言边界 FAIL-OPEN 与同语言本质不同**：
- 同语言：异常沿调用栈传播，可捕获，上下文保留。
- 跨语言：进程崩溃、IPC 断裂、上下文丢失。segfault 在 TS adapter 中无法"捕获"。

**进程级故障传播特性**：Python segfault 杀死 IPC 流。TS adapter 看到 stdin EOF。这是 HARD failure。

**关键洞察（对 H5 至关重要）**：物理进程隔离实际上**强化**了硬约束。"FAIL-OPEN + 开关默认关"模式在进程内依赖开关状态；跨进程下，"Python 不可达 = 开关关"由物理隔离强制。死掉的 Python 无法发出交易=安全默认。

**但需要分路径策略**：
- 交易路径：FAIL-CLOSED（Python 不可达=不交易）
- 非交易路径（memory recall）：FAIL-OPEN（降级为无操作）

### A8. Strangler Fig 模式

**对 5 假设的判断**：H1 中性 / H2 支持 / H3 中性 / H4 中性 / H5 中性

分层嵌入**不是经典 Strangler Fig**。Strangler Fig 是渐进替换——新系统逐步覆盖旧系统行为，旧系统最终被"绞杀"退役。dream-harness-bridge 中没有"旧系统要退役"——DreamBuddy 持续存在。

这是**稳定共存**模式，更接近"Sidecar"或"Adapter + Facade"。不要把 SPEC 包装成 Strangler Fig 叙事，那会误导评审者期待"渐进替换"。

---

## 三、维度C：经典代码工程拆解

### C1. VSCode 插件架构 — 启示价值：高

VSCode 是最成功的 plugin 生态。**Extension Host 是独立 Node.js 进程**，主进程通过 IPC 与 Extension Host 通信。

**启示**：
1. 进程隔离在规模上已被证明（VSCode 千级扩展）。方案可行。
2. TS adapter = Extension Host 等价物；Python IPC server = extension。模型契合。
3. **IPC 协议必须版本化**——VSCode 的 proposed/stable API 区分是关键。Harness preview API 不稳定，必须有版本协商。
4. **懒激活至关重要**——不要启动就 spawn Python（cold start 拖累 Harness 启动）。
5. Extension Host 可被 kill 重启，但扩展状态外置——有状态 plugin 重启需状态外置。

### C2. Eclipse 插件架构（OSGi） — 启示价值：中

OSGi bundle 生命周期是 gold standard：installed → resolved → starting → active → stopping → uninstalled。基于 JVM classloader 的解析。

**启示**：
1. **不要尝试复制 OSGi 完整生命周期**。跨语言 plugin 用子集：installed/active/stopped/health-check。
2. OSGi service registry 的跨语言等价=IPC 服务发现。
3. **不支持运行时 provider 热替换**，provider 变更=重启。

### C3. Grafana plugin 系统 — 启示价值：高

Grafana：Go 后端 + TS 前端 plugin。三类：datasource/panel/app。**后端 plugin 用 gRPC**；前端 plugin 是浏览器内 JS。

**启示**：
1. **"Plugin SDK"抽象层比传输选择更重要**。即便用 stdio，TS 侧和 Python 侧都应有薄 SDK 隐藏 wire format。
2. **Grafana 生产用 gRPC**——印证 stdio 适合 preview，gRPC 是生产级跨语言 plugin 传输。
3. Grafana 的 plugin 类型分层（datasource/panel/app）映射到 DreamBuddy：S 层=intent datasource；A 层=orchestration app；C 层=execution panel；G 层=storage datasource。

### C4. Airflow plugin / Operator — 启示价值：中

Airflow 是 Python 生态。方向相反——orchestrator 是 Python，能力也是 Python。

**启示**：
1. Airflow 的 **Operator 模式**（execute(context) 单一接口）证明"领域能力作为编排单元"在接口小且清晰时工作良好。DreamBuddy SACG 各层应暴露**小接口** over IPC。
2. Airflow Operator 重上下文传递（context dict 极大）。跨语言下，巨型 context dict 序列化成本高——SPEC 应限制单次 IPC payload 大小。

### C5. Claude Code plugin/skill 系统 — 启示价值：高

Claude Code 用 **SKILL.md 机制**——markdown + YAML frontmatter 描述 skill，按需加载。subagent 运行 skill（隔离 context，返回 summary）。

**启示**：
1. SKILL.md 的**声明式按需加载**是"薄 plugin manifest"模型。DreamBuddy SACG 各层可各有 manifest。
2. **不要混淆调用模型**：Claude Code skill 是 LLM 触发；DreamBuddy SACG 是程序化调用。SPEC 不应把 SACG 层设计成"自然语言触发"。
3. Claude Code 是"外部 agent 作为 subagent"的成熟模式实证（rc.8 subagent bundle）。

### C6. Cordis 本身的设计 — 启示价值：高（待验证）

Cordis（arxiv 2608.25512）提出 **temporal/spatial composability** 与 **Capability Seams（Service Definition / Provider / Consumer）**。

**Capability Seams 三角色跨语言映射**：
- Service Definition（what）= IPC 契约（JSON schema + 协议）
- Provider（who offers）= Python IPC server
- Consumer（who uses）= TS adapter（它同时也是向 Cordis 的 Provider）

**adapter 的双重角色是关键**：它是 Python 的 Consumer，是 Cordis 的 Provider。这个 dual-role adapter 是方案的核心，sound 当且仅当契约稳定。

**风险**：Cordis 的 composability 可能假设进程内类型安全。跨语言在 seam 失去编译时类型安全，运行时验证（JSON Schema）是补偿——但不是等价物。

### C7. Strangler Fig 经典案例 — 启示价值：低

Amazon.com 从单体到服务化迁移（2001-2006）。判据：新系统与旧共存→增量切换→旧系统在新覆盖足够时可退役。

**对 dream-harness-bridge**：没有旧系统要退役，Strangler Fig 的 exit 判据不适用。这是稳定共存，不是 strangler。

---

## 四、维度B：传统代码开发流程和方案

### B1. 微服务集成模式 — 支持 H1/H2/H3

dream-harness-bridge 最接近 **Sidecar 模式**：Python IPC server 作为 TS Harness 的"伴生进程"。

- API 网关模式让 Harness 成为状态瓶颈，违反 HC-3。
- Service Mesh 过度引入运维负担。
- Sidecar 最贴切：主进程编排、Sidecar 执行，stdio 如同 Sidecar 的本地管道。

**警示**：Sidecar 模式的经典风险是"主进程与 Sidecar 生命周期不同步"，SPEC 需补充进程健康检查与孤儿进程清理。

### B2. ESB 企业服务总线 — 有条件支持 H2

ESB 是集中式编排，Harness Cordis 是组合式编排。ESB 的历史教训警示：若 Harness 试图成为所有 DreamBuddy 调用的"必经之路"，会成为单点。SPEC 的设计（Harness 只编排不持有交易状态）已规避此风险。

**警示**：G 层 consumer 需坚守"消费"而非"回流编排"，防止退化为 ESB。

### B3. Adapter 模式 / Facade 模式 — 支持 H2

是 **Adapter 模式**而非 Facade。Facade 会屏蔽细粒度事件流，与 DP-2 分层嵌入矛盾。Adapter 转换接口使不兼容的类协作，保留内部结构。

**警示**：Adapter 的"翻译损耗"——SACG 反思维决策在 TS↔Python 翻译时语义可能漂移。

### B4. Strangler Fig 应用迁移 — 有条件支持 H2

不是标准 Strangler Fig，是"前半段变体"。本项目明确"不重写 DreamBuddy"（DP-1），没有"逐步替换→移除"意图。

**警示**：若团队潜意识把本项目当 Strangler Fig 起点，会侵蚀 DP-1 边界。

### B5. 跨语言通信方案比较 — 支持 H3

| 维度 | stdio NDJSON | gRPC | HTTP JSON-RPC | WebSocket |
|------|-------------|------|--------------|-----------|
| 延迟 | 极低(<1ms) | 中(5-15ms) | 高(50-100ms) | 低 |
| 类型安全 | 运行时 | 编译期 | 运行时 | 运行时 |
| 调试 | 难(stderr) | 中 | 易(curl) | 中 |
| 流式 | 行流 | 双向流 | 无 | 双向 |
| 错误传播 | exit code+stderr | status code | HTTP code | 自定义 |
| 运维复杂度 | 极低(无端口) | 中(注册中心) | 低(端口) | 高 |

**实证**：MCP 协议（Claude/Gemini/Codex 均采用）已用 stdio NDJSON 验证了"无端口低延迟"模式在 agent 工具调用场景的可行性。LSP（Language Server Protocol）使用 Content-Length + JSON-RPC 2.0 over stdio 是最成熟的跨语言 agent 通信协议。

**警示**：stdio 的"调试难"在跨语言失败传播时会被放大，需配套 stderr JSON 协议+日志聚合+进程级 trace 工具。

### B6. 混合栈架构管理（monorepo + polyglot） — 支持 H1/H4

TS + Python 同 git 仓库的实践成熟（如 OpenHands、Cursor、VS Code 本身）。

**意外收益**：Python 原生库 ABI 风险（记忆库 VM-1789089211280 已记录 segfault 源于 cv2/numpy ABI），跨进程反而**降低**此风险（IPC server 独立进程，崩溃不拖累 Harness）。

### B7. preview 阶段软件作为依赖 — 有条件支持 H4

把 v0.1.x developer preview 作为生产基座，业界准则：
1. 版本锁定不够——需"pin + 抽象 IPC 层 + 季度升级评估"
2. **Fork 准备**——需在内部维护 fork
3. **契约测试**——对 Cordis API 写契约测试
4. **降级预案**——能否"卸掉 Harness，DreamBuddy 独立运行"（Plan B 满足）
5. preview 不等于不稳定——DeepSeek 是商业化公司，Harness 有论文+Cordis 学术基础

---

## 五、维度D：实际成熟工程实证

### D1. LangChain + LangGraph — 参考价值：中

LangGraph 的"State 是单一真相源、Node 无状态、Checkpoint 可恢复"与 SPEC HC-3 高度一致。但 LangChain/LangGraph **都是 Python**，没有跨语言整合实证。

### D2. CrewAI — 参考价值：中

CrewAI 的"Flow 管理 state + Crew 执行任务"分层，与 Harness+DreamBuddy 同构。但全 Python，且其"中心化编排"与 SPEC 的"C 层反思维决策保留在 DreamBuddy"有张力。

### D3. OpenHands / OpenDevin — 参考价值：高

OpenHands V1 是 Python SDK + Agent Server（FastAPI REST/WebSocket）。V0→V1 重构四条原则：
1. Clear Boundaries（研究/生产边界清晰）——对应 HC-1a/b/c
2. Optional Isolation（可选隔离）——DreamBuddy 不需 Docker 沙箱
3. Stateless by Default——Harness Agent 无状态，DreamBuddy 持有状态
4. Composition Over Inheritance——Cordis plugin tree 正是组合

**关键**：OpenHands 证明了"Python agent + 事件流 + 外部编排"可行，但其外部编排是 HTTP 客户端，不是嵌入式 TS plugin。跨语言嵌入程度本项目更深。

### D4. Aider — 参考价值：中

Aider 的 repo map（tree-sitter + PageRank 上下文选择）对 DreamBuddy G 层 GraphCompressor 有直接参考——把"快照压缩"升级为"基于图重要性的压缩"。但单进程 Python，无跨语言经验。

### D5. Cursor — 参考价值：高

Cursor 是 VS Code fork，TypeScript + Rust。Cursor SDK 提供 harness + skills + hooks + subagents + MCP。

**关键**：Cursor 的 plugin 规范（.cursor-plugin/plugin.json）是"TS runtime + plugin 体系"的成熟实证。其 MCP 支持"stdio 或 HTTP"双模式，印证 stdio 是 plugin 接入的合理选择。但 Cursor 的 plugin 是 TS 原生，**没有 Python 领域 plugin 实证**。

### D6. Claude Code — 参考价值：高

Claude Code 的扩展体系：CLAUDE.md + Skills + Subagents + Hooks + MCP + Plugins。Claude Code 是"外部 agent 作为 subagent"的成熟模式实证。但 Claude Code 是单一 TS runtime，**没有 TS 编排 + Python 领域 plugin 的跨语言实证**。

### D7. MetaGPT / ChatDev — 参考价值：低

全 Python，同语言进程内通信，无跨语言经验。其"环境共享"与 SPEC HC-3（状态不共享）相反。

### D8. Dify / Coze / FastGPT — 参考价值：中

单语言后端 + 可视化编排，没有"TS runtime + Python plugin"跨语言。plugin 声明式配置可参考 Model-as-Plugin。

### D9. Airflow / Prefect / Dagster — 参考价值：中

Airflow DAG 与 DreamBuddy A 层 GraphOrchestrator 同构。Prefect 的状态机和 Dagster 的 asset 都强调"可恢复、可观测、可重放"，与 Harness session log 一致。但都是 Python 内编排。

### D10. 跨语言 agent runtime 实际案例 — 参考价值：关键

**业界是否有"TS agent runtime + Python 领域 plugin"的成功先例？**

**结论：无明确成功先例，但非全新发明，属"有计划的创新"。**

- **无先例的原因**：业界要么全栈统一语言（避免 IPC 成本），要么用 HTTP 解耦（OpenHands 模式）。把 Python 领域 runtime **嵌入** TS harness plugin tree，需要同时解决"跨语言 IPC + 插件生命周期 + 事件流细粒度 + 硬约束跨进程"四重难题，无人尝试。
- **不是红旗的理由**：
  1. MCP 已验证 TS-host+Python-server+stdio 模式可行（工具级）
  2. Cordis 的"everything is a plugin"理论天然支持跨语言 plugin
  3. SPEC 的 Phase 0 POC + V0-1~V0-7 门槛设计严谨
  4. 物理隔离（子目录单独项目，Plan B 删目录即可）控制了失败成本
- **仍是红旗的理由**：
  1. 无踩坑经验可复用
  2. Harness v0.1.x preview 阶段自身不稳定
  3. 5 项真协同的"1+1>2"尚未实证
  4. 跨进程硬约束审计无前例

**最终判断**：**有条件的创新**——若 Phase 0 POC 全绿，则此创新可行；若任一门槛红，应回退到 OpenHands 式"Python agent + HTTP 外部编排"（路径 B）。

### D-Web. WebSearch 补充发现

1. **Composio 实验**（DeepSeek Harness 发布时）：同一模型 8 种 harness 配置，通过率 14-20/30，成本 4.3x 差异 → "模型决定天花板，harness 决定能达多少" — 支持 dream-harness-bridge 的价值主张。
2. **"harness 从未是难的部分"**：一篇分析文章指出 harness 是 plumbing，难的是"agent 该看什么、决策后会发生什么" — 支持 DreamBuddy SACG 作为领域知识的价值。
3. **stdio Bus 论文**（techrxiv）：专门研究多进程 agent 传输的 C11 内核，使用 NDJSON + JSON-RPC，证明 stdio 是 agent 跨进程通信的学术级验证。
4. **agent-lsp**（Go MCP server 包装 Python/TS LSP subprocess，通过 JSON-RPC over stdio 通信）：证明"外部系统包装 Python 子进程通过 stdio JSON-RPC 通信"是成熟模式。
5. **Copilot SDK**：4 种语言 SDK 通过 Content-Length + JSON-RPC 2.0 over stdio 与 CLI 通信，证明跨语言 stdio 通信在 4 语言级别可行。

---

## 六、五假设四维验证矩阵

| 假设 | 维度A（原理） | 维度C（案例） | 维度B（流程） | 维度D（实证） | 综合判断 |
|------|-------------|-------------|-------------|-------------|---------|
| **H1 跨语言整合可行** | ✅ 支持（adapter 间接接入） | ✅ 支持（VSCode Extension Host / Grafana） | ✅ 支持（Sidecar / polyglot monorepo） | ⚠️ 无先例但有 MCP 基础 | **有条件支持** |
| **H2 分层嵌入正确** | ✅ 支持（ACL / 微内核 + adapter） | ✅ 支持（Adapter 非 Facade） | ✅ 支持（Sidecar / Adapter 模式） | ✅ 支持（OpenHands 四原则） | **支持** |
| **H3 stdio NDJSON 合适** | ⚠️ 有条件（preview 正当，需迁移路径） | ✅ 支持（VSCode IPC / LSP） | ✅ 支持（MCP / LSP 实证） | ✅ 支持（Cursor 双模式 / stdio Bus 论文） | **支持（需定义 gRPC 迁移路径）** |
| **H4 Harness preview 可基座** | ⚠️ 有条件（版本锁定 + 契约协商） | ✅ 支持（需版本协商） | ⚠️ 有条件（HC-6 偏弱，需契约测试 + fork） | ⚠️ 有条件（Composio 证明 harness 价值，但 preview 不稳定） | **有条件支持（需补强 HC-6）** |
| **H5 硬约束跨进程生效** | ✅ 支持（物理隔离强化硬约束） | ✅ 支持（VSCode 进程隔离） | ✅ 支持（独立进程） | ⚠️ 无前例（最大风险） | **有条件支持（需协议级强制 + 分路径 fail）** |

---

## 七、关键发现

### 7.1 跨语言 plugin 的核心挑战（按严重度排序）

1. **类型安全降级**（编译时→运行时）：跨语言边界失去共享类型系统。补偿=共享 JSON Schema + 双端代码生成。
2. **"写入链路断裂"反模式跨语言下更高发**：无法 grep 跨 TS+Python 的调用链；静态分析弱化。模块已实现+测试通过但 IPC pipeline 不调用的情形，跨语言下更隐蔽。
3. **生命周期复杂化**（进程管理 vs 对象生命周期）：进程 spawn/kill 成本、有状态 plugin 重启需状态外置、运行时 provider 热替换成本极高。
4. **故障模式差异**（进程崩溃 vs 异常）：segfault 不可捕获，IPC 断裂=EOF。对交易安全是双刃——物理隔离强化硬约束，但故障检测要靠 EOF 而非异常。
5. **契约版本化**：无共享类型系统，schema 版本必须显式管理。Harness preview API 不稳定放大此风险。
6. **原生库兼容性**：Python IPC server 的 import 链若含重原生库（causalml/shap/cv2），segfault 风险跨进程传导。但独立进程反而**降低**此风险（崩溃不拖累 Harness）。

### 7.2 分层嵌入方案是否成立

**成立**，有条件：

- **原理层**：ACL、微内核+adapter、事件溯源+领域 payload、FAIL-CLOSED-on-trading-path——均支持。
- **案例层**：VSCode Extension Host、Grafana backend plugin 证明跨语言 plugin 在规模上可行。
- **流程层**：Sidecar、Adapter、polyglot monorepo、stdio NDJSON 都是成熟实践。
- **实证层**：无直接先例，但 MCP 工具级模式可扩展到 runtime 级，属有计划的创新。
- **成立条件**：
  - (a) 契约稳定性 + 版本协商
  - (b) 状态外置策略
  - (c) 生命周期子集（不承诺 OSGi 全状态）
  - (d) 双端 SDK 抽象
  - (e) 分路径 fail 策略
  - (f) Phase 0 POC V0-1~V0-7 全绿

### 7.3 关键洞察

1. **"harness 从未是难的部分"**：WebSearch 发现的分析文章指出，harness 是 plumbing，难的是"agent 该看什么、决策后会发生什么"。这**支持** DreamBuddy SACG 作为领域知识的价值——领域知识才是 1+1>2 中的"1"，Harness 是另一个"1"。
2. **物理进程隔离实际强化硬约束**：死掉的 Python 无法发出交易=安全默认。这是跨进程的意外收益。
3. **跨进程反而降低原生库 ABI 风险**：IPC server 独立进程，崩溃不拖累 Harness。
4. **stdio NDJSON 有学术级验证**：stdio Bus 论文 + LSP + MCP + agent-lsp + Copilot SDK 共同证明此模式在多语言 agent 通信中成熟。
5. **Composio 实验证明 harness 价值真实**：同一模型不同 harness 通过率差 6 任务、成本差 4.3x，证明 harness 编排骨架确实影响实际效果。

---

## 八、SPEC 修正建议（按优先级排序）

### P0 — 必须修正（阻塞 Phase 0 启动）

| 编号 | 修正内容 | 理由 |
|------|---------|------|
| **F-01** | IPC 契约必须版本化 + 显式版本协商 | Harness preview（v0.1.x）API 不稳定，无版本协商=静默破坏。SPEC 需定义 schema version 字段 + adapter 拒绝不兼容版本。 |
| **F-02** | 协议级不变式强制硬约束 | 硬约束检查必须是交易 IPC 序列的 mandatory step。adapter 在缺少 `constraint_passed: true` 时拒绝转发交易请求。不依赖运行时断言。 |
| **F-03** | 写入链路断裂的跨语言检测 | 定义端到端契约测试：每个 IPC 方法必须验证 TS adapter → Python → 响应完整流转。已知反模式跨语言下高危。SPEC 需包含"链路活性测试"。 |

### P1 — 强烈建议（影响 Phase 0 质量）

| 编号 | 修正内容 | 理由 |
|------|---------|------|
| **F-04** | Plugin 生命周期用子集 | start/stop/health-check 三态足够。卸载语义="停止进程"，重启=从持久化恢复。明确不支持运行时 provider 热替换。 |
| **F-05** | 分路径 fail 策略 | 交易路径 FAIL-CLOSED（Python 不可达=不交易），非交易（memory recall）FAIL-OPEN（降级 no-op）。单一策略不足。 |
| **F-06** | Python IPC server 原生库隔离 | import 链必须与重原生库（causalml/shap/cv2）惰性隔离。记忆 VM-1789089211280 已验证 segfault 风险。 |
| **F-07** | 双端 SDK 抽象 | TS 侧 adapter SDK + Python 侧 server SDK，隐藏 wire format。共享 JSON Schema 作为 single source of truth，双端 codegen。 |
| **F-08** | 进程健康检查 | Sidecar 模式经典风险。Python IPC server 心跳、孤儿进程清理、Harness 退出时优雅关闭 IPC server。 |
| **F-09** | HC-6 补强 | 补充：对 Cordis 核心 API 写契约测试套件，每次升级先跑契约；维护内部 fork 准备；定期降级演练。 |
| **F-10** | 反思维决策跨语言语义等价性 | OQ-5 升级为 Phase 0 必验项。REDO/INSERT_BEFORE/JUMP_TO 在 TS↔Python 翻译后语义等价性测试。 |

### P2 — 建议补充（提升长期可维护性）

| 编号 | 修正内容 | 理由 |
|------|---------|------|
| **F-11** | stdio→gRPC 迁移路径定义 | stdio 是 v0.1 选择，Grafana 证明 gRPC 是生产级跨语言 plugin 传输。SPEC 需明确迁移判据。 |
| **F-12** | 事件信封模式 | adapter 发"信封事件"——外层通用 Harness 事件，payload DreamBuddy 领域类型。G 层消费 payload。 |
| **F-13** | 不要包装成 Strangler Fig 叙事 | 本方案是稳定共存（Sidecar/Adapter），不是渐进替换。错误叙事会误导评审。 |
| **F-14** | 调试工具配套 | stdio 调试难是真实成本。补充进程级 trace 脚本 + stderr JSON 日志聚合 + 双向消息录回放。 |
| **F-15** | 限制 IPC payload 大小 | Airflow Operator 的巨型 context dict 教训。跨语言下序列化成本高。 |

---

## 九、开放问题更新

基于四维调研，更新 SPEC 第九章的开放问题：

| 编号 | 问题 | 调研后状态 | 优先级 |
|------|------|-----------|--------|
| OQ-1 | Cordis plugin 接入 DreamBuddy Python 节点的具体 Cordis API | **Phase 0 必验**（F-01 契约版本化前置） | 高 |
| OQ-2 | Harness session log 事件 schema 对 SACG 事件的覆盖度 | 需验证 F-12 事件信封模式 | 高 |
| OQ-3 | stdio NDJSON vs HTTP JSON-RPC 延迟差异 | **已回答**：stdio 优（B5+D-Web 实证），但需定义 gRPC 迁移路径（F-11） | ~~高~~ → 已解答 |
| OQ-4 | agent/pre-step listener 读取 IntentGateway 输出 | **Phase 0 必验**（V0-5 门槛） | 高 |
| OQ-5 | agent/* event listener 触发反思维决策的机制 | **升级为 Phase 0 必验**（F-10 语义等价性） | 高 |
| OQ-6 | Cordis 可逆 plugin 卸载时回滚 DreamBuddy 副作用 | **已回答**：跨进程只能近似（A5），用 start/stop/health-check 子集（F-04） | ~~中~~ → 已解答 |
| OQ-7 | G 层消费 session log 的 projection 机制 | 需验证 F-12 事件信封模式 | 中 |
| OQ-8 | Model-as-Plugin 配置驱动的 LLM 降级链 schema | 不变 | 中 |
| OQ-9 | Trajectory view 自定义 event source 标注 S/A/C/G | 不变 | 低 |
| OQ-10 | Cordis 论文 temporal/spatial composability 在 Python 等价实现的差距 | **部分回答**：C6 拆解了 Capability Seams 三角色映射，论文细节仍待验证 | 低→中 |
| **OQ-11** (新) | "TS runtime + Python 领域 plugin" 无先例的风险评估 | **新建**：D10 结论"有计划的创新"，需持续评估 | 高 |
| **OQ-12** (新) | 进程健康检查与孤儿进程清理的具体实现 | **新建**：F-08 Sidecar 模式经典风险 | 中 |

---

## 十、调研结论

### 10.1 总判断

**路径 E 分层嵌入方案在四维验证下成立，有条件。**

- **原理层（维度A）**：8 项原理/准则中 6 项支持、2 项有条件支持。ACL、微内核+adapter、事件溯源、FAIL-OPEN 均支持。
- **案例层（维度C）**：7 个经典案例中 4 个启示价值高。VSCode Extension Host 和 Grafana plugin 证明跨语言 plugin 在规模上可行。
- **流程层（维度B）**：7 项传统方案中 5 项支持。Sidecar 模式、Adapter 模式、polyglot monorepo、stdio NDJSON 均成熟。
- **实证层（维度D）**：10 个实际工程中无直接先例，但 MCP 工具级模式可扩展。属"有计划的创新"。

### 10.2 成立条件

1. **F-01/F-02/F-03 三项 P0 修正必须落地**（契约版本化、协议级硬约束、链路活性测试）
2. **Phase 0 POC V0-1~V0-7 全绿**（SPEC 已设门槛，设计正确）
3. **HC-6 补强**（F-09：契约测试套件+fork 准备+降级演练）
4. **分路径 fail 策略**（F-05：交易 FAIL-CLOSED / 非交易 FAIL-OPEN）

### 10.3 最大风险

**不在技术可行性，而在两个无前例领域**：

1. **跨进程硬约束审计**（H5，无前例）— 需 F-02 协议级强制 + F-03 链路活性测试
2. **"TS runtime + Python 领域 plugin" 嵌入式先例缺失**（D10）— 需 Phase 0 POC 严格验证

### 10.4 如果 Phase 0 失败的回退方案

若 V0-1（session log 记录细粒度事件）或 V0-2（状态隔离）或 V0-7（FAIL-OPEN）任一门槛红：
- **回退到路径 B**（OpenHands 式"Python agent + HTTP 外部编排"）
- **放弃嵌入式分层**，DreamBuddy 作为独立 HTTP 服务被 Harness 调用
- Plan B 删 dream-harness-bridge/ 目录，现有项目零影响

---

## 十一、变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-09-13 | 首版：四维调研（A 原理 8 项 + C 案例 7 项 + B 流程 7 项 + D 实证 10 项 + WebSearch 补充 5 项）；5 假设验证矩阵；15 条 SPEC 修正建议；3 条新开放问题 |
