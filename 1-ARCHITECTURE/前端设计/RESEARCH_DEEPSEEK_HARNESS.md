# DeepSeek Harness 调研 Spec — 与 DreamOS 的相似性研究与借鉴方向

> **版本**: v0.1 (调研稿)
> **状态**: 🔬 调研中 / 待持续研究
> **创建日期**: 2026-09-13
> **调研动机**: DeepSeek 官方发布的 agent harness 框架，其"Agent = Model + Harness"哲学与 Dreambuddy OS"调度层纯编排、不重复建设"信条高度相似，需评估借鉴价值与落地路径
> **调研来源**:
> - 官方仓库: https://github.com/deepseek-ai/deepseek-harness
> - 官方文档: https://deepseek.com/harness/en/
> - 架构文档: docs/architecture.md
> - Cordis 论文: https://arxiv.org/abs/2608.25512
> - 技术评论: SitePoint / InfoQ / dev.to / seventnews / Cloudsway / DeepThink / 阿里云 Model Studio 集成文档

---

## ⚠️ 文档定位

本文件是**调研稿**，非实施 Spec。目的：
1. 沉淀首次调研结论，避免后续重复检索
2. 标注后续待研究的开放问题
3. 为未来可能的落地提供参考基线

落地决策需在后续独立 Spec 中重新评估（因 Harness 仍处于 developer preview，API/契约会变）。

---

## 一、DeepSeek Harness 概览

### 1.1 项目基本信息

| 项目 | 详情 |
|------|------|
| 名称 | DeepSeek Harness (dsh) |
| 发布方 | DeepSeek 官方 |
| 首发日期 | 2026-08-13 |
| 当前版本 | v0.1.x (developer preview, rc.8+ 截至 2026-08-19) |
| License | MIT |
| 主仓库 | github.com/deepseek-ai/deepseek-harness |
| 技术栈 | TypeScript / Node.js (≥18) |
| 底层框架 | Cordis 微内核 (arxiv.org/abs/2608.25512) |
| 启动方式 | `npx @deepseek-ai/dsh web` 或 `git clone` 源码 |
| 配置文件 | `~/.dsh/settings.yaml` |
| 提交规模 | 16,511 commits (截至调研) |

### 1.2 核心哲学

官方公式: **Agent = Model + Harness**

> "The model is the soul of an agent. A harness lets an agent understand its environment, use tools, and keep working in real-world settings."

模型是灵魂，Harness 是让 agent 在真实环境中持续工作的工程外壳 — 文件访问、工具调用、记忆、沙箱、错误重试、任务分解、结果交付。

### 1.3 四种运行模式 (Presets)

| Mode | 定位 | 工具集 |
|------|------|--------|
| **Standard** | 完整编码 agent | 文件编辑、shell、文件/网页搜索、skills、planning、goals、subagents、workflows |
| **Code (PTC)** | TypeScript 程序化编排 | Standard 全集 + Code Mode SDK 让模型在一个 TS 程序里组合多步工具调用 |
| **Minimal** | 基准测试极简环境 | 双工具：persistent bash + str_replace_editor |
| **Creator** | 运行时检查与 preset 创作 | Standard 全集 + 运行时检查 + 内存中 Cordis 插件实验 + preset 创作引导 |

### 1.4 关键 rc 版本里程碑

| 版本 | 日期 | 重点 |
|------|------|------|
| v0.1.0 首发 | 2026-08-13 | MIT 开源，4 个 preset，Cordis 内核 |
| rc.7 | 2026-08-17 | (略) |
| rc.8 | 2026-08-19 | 原生视觉输入、Claude Code/Codex 作为 subagent bundle、web_search 并发、Windows PowerShell PTY、SQLite 大会话性能优化 |
| v0.1.5 | 2026-09-10 | (master 分支最新) |

---

## 二、Harness 架构核心机制

### 2.1 Cordis 微内核 — Everything is a Plugin

Cordis 是 dsh 之下的 meta-framework：
- Plugins 向 shared context 贡献 **services** / **typed events** / **reversible effects**
- **没有特权内核可补丁**：扩展 dsh = 在其他 plugin 旁挂载一个 plugin
- 注册即 effect，plugin 卸载时 effect 自动回滚（temporal composability）
- 组件可声明依赖（spatial composability）

**Everything is a Plugin 覆盖范围**：
model adapter / tools / skills / sessions / sandboxes / storage / agent loop / scheduling / UI — 全部都是 plugin，全部可从配置替换。

### 2.2 Profiles & Bundles — 配置即产品

- **Profile**: 命名组合，存在 Harness home 中，列出它堆叠的 bundles + 自有 plugin + `cordis.patch.yml`
- **Bundle**: Cordis config rows + 它们挂载的代码的发行格式
- 模板: `web` / `headless` / `sdk` / `sdk-minimal` / `acp`
- `dsh-base` 是 web/headless/sdk/acp 的共享首层（model adapter、tools、persistence、sandbox、approval policy、settings、credentials、telemetry）
- 层叠顺序: profile 列出的 bundles → profile `cordis.patch.yml` → home 级 → `--patch` overlay
- **patch 是整行替换，非深度合并**（高频陷阱）
- `dsh --profile web --dump-config` 查看实际加载的 plugin 树

### 2.3 Capability Seams — 三角色分离

每个可替换能力是 **seam**，分三个角色：

| 角色 | 职责 |
|------|------|
| **Service Definition** | 声明接口 |
| **Service Provider** | 实现接口 |
| **Consumer** | 使用接口（通常是 model-facing tool） |

**示例**：Filesystem 与 subprocess provider 共享一个执行世界，所以指向远程 sandbox 时 Bash / PTY / LSP 一起跟着走，无需 provider fork。

**意义**：定义能力、实现能力、向模型呈现能力是三件不同的事，不要写在一处。

### 2.4 Append-only Session Log — 可追溯根基

**Model-visible means logged** — 任何到达 model 请求的东西都必须可从 log 重建，运行时 invariant 断言之。

记录内容：system prompts / reasoning / tool calls & results / subagent scheduling / 任何 context injection。

衍生能力：
- **Trajectory view**: 按来源检视记录
- **Resume / Fork / Search / Replay** 都基于同一事件流
- SessionEventMap 扩展即可让新 model-visible 输入被记录

存储格式：
- JSONL v0: `session.jsonl[.zstd]`
- v1+: `session.vN.jsonl[.zstd]`
- 相邻迁移包负责 `vN → vN+1`，已提交的 generation 路径永不重命名/替换/删除

### 2.5 Turn/Step 生命周期

```
turn/start
  claim next-step input + 1 queued message
  assemble prompt sections + tool schemas; project runtime context
  -> agent/pre-step   reject | enter(messages, startsRequestSeries?)
     reject 或首次 enter 重写为空 → 无 step 关闭 turn
     step/start
     agent/request -> prepareCall
     reconcile system/message
     append entered messages as user/message
     derive and freeze model history
     stream bound prepared call -> llm/stream -> agent/assistant-stream start
       agent/assistant-stream chunk*
       assistant/message | assistant/attempt -> agent/assistant-stream end
     tool/call* -> tools/pre-execute -> tools/execute -> tools/post-execute -> tool/result*
     step/end
     tools 欠另一个请求 OR next-step input 到达 → claim → next step
  -> agent/turn-stopping
turn/end
```

三类事件域：
- **Session 事件**: durable，append 到 log，通过 `session/event` 广播
- **Agent 事件** (`agent/*`): live，携带 Agent 实例 — inbox/step/status/request/validation/continuation
- **Capability 事件**: 挂载 policy 与 adapter 到 seam (`fs/*` / `tools/*` / `telemetry/*`) 而不导入 loop

### 2.6 Extension Points 映射表

| 目标 | 机制 |
|------|------|
| 加 model provider | 在 ctx.llm 上注册 adapter |
| 加 model-facing 能力 | 在 ctx.tools 注册；其 schema 加入 prompt assembly |
| 给一个 session 不同能力集 | compose agent preset |
| 加 shell 执行 | 注册 ctx.shell backend；本地通过 ctx.subprocess spawn |
| 加持久终端 | 注册 ctx.terminals backend + dsh-tool-terminal |
| 加人类命令 | ctx.commands 注册，无 model turn 分发 |
| 加后台工作 | ctx.jobs 注册；job_* 工具收集/停止 |
| 从外部 webhook 启动 Session | ctx.webhookRuntime 注册可信规则 + provider adapter |
| 加文件系统访问或策略 | 注册 ctx.fs provider 或监听 fs/* 事件 |
| 限制 spawn 进程 | ctx.sandbox backend；consumer 在 spawn 前包 argv |
| 拦截请求/工具/turn | 用 agent/* 或 tools/* 事件；agent/turn-stopping 停 turn |
| 加 model-facing context | 调 agent.inject() → 落入下次 admitted 请求 |
| 加 UI/编辑器集成 | 驱动 ctx.agents + 从 session/event 渲染 |
| 在新 backend 存 session | 实现 SessionPersistence (create/open/stat/list/export) |
| 把注册限定到一个 agent | 用该 agent 的 agent.ctx |
| Fork session 在 turn 边界 | `ctx.agents.create({ sessionId, seed, meta: { parentSession, seedLength } })` |

### 2.7 rc.8 重点新特性

1. **原生图像输入**: `/goal` / `/plan` 等核心命令支持截图直传
2. **Claude Code / Codex 作为 subagent bundle**: 装入 bundle 即可作为 task executor 被编排；Codex 支持非交互权限模式 + 多命名实例并行；`reportDelivery` 机制唤醒父任务，消除阻塞等待
3. **`web_search` 并发查询**: 多问题研究延迟大幅降低
4. **"Folk Vision" 文字降级**: 模型不支持图像时，调 OCR / 颜色统计 / 像素扫描把图像转结构化文本
5. **SQLite 大会话性能优化**: schema 变更，升级需备份

### 2.8 DSBench 评测与自纠错

- 内置 pytest 自动化测试 + 编译器 Error 堆栈智能精简提取
- DSBench / LM-Eval 权威评测套件度量 Pass@1
- 实时触发 agent 闭环逻辑自纠错

### 2.9 DeepSeek KV Cache 专属优化

- 深度契合 DeepSeek-V3/R1 前缀缓存 Prefix Caching
- 多轮复杂代码工程重构 99.93% 前缀缓存命中率
- 降低 80%+ 长上下文 Token 算力成本

---

## 三、DreamOS 现状对照

### 3.1 Dreambuddy OS 内核 SKILL 摘要

来源: [SKILL.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md)

**SACG 四层架构**：
```
S 层 Sense 感知层  — IntentGateway · 6 种意图类型 · 零 Token 本地计算
A 层 Architecture 编排层 — GraphOrchestrator · NodeRegistry(35模块+11本地) · 四维过滤
C 层 Compute 执行层 — UnifiedNodeExecutor · 适配器模式 · 重试机制 · 降级策略 · 反思决策
G 层 Graph 存储层  — GraphCompressor · 执行记录持久化 · 上下文压缩 · 历史回溯
```

**核心信条**: 调用的不重复建设；能力清单在总架构中已存在；架构检查模块可定期验证执行效果。

**关键文件**：
- [registry/node_registry.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/registry/node_registry.py): NodeRegistry 节点唯一真相源，支持 register/get/list/unregister，YAML 批量加载，线程安全
- [registry/base.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/registry/base.py): BaseNode 模板方法 — validate → execute_core → 异常 fallback → 自动计时 → F 链 EWMA+MAD 信号平滑
- [adapters/base.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/base.py): AdapterRegistry — FunctionAdapter/SkillAdapter/APIAdapter 三适配器分发
- [evolution/engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/evolution/engine.py): EvolutionEngine — LessonDistiller + GapAnalyzer + NodeOptimizer + TradingAnalysisEvaluator，含沙箱验证（新方案回测得分 > 现有 × 1.1）
- G 层快照: [data/graph_store/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/data/graph_store/) 当前为 `ckpt_{timestamp}_{hash}.json` 快照式

### 3.2 维度对照表

| 维度 | DeepSeek Harness | DreamOS (dreambuddy-os SKILL) | 相似度 | 备注 |
|------|------------------|------------------------------|-------|------|
| **核心哲学** | Agent = Model + Harness，纯编排不重复建设 | 调度层纯编排，不重复建设 | ★★★★★ | 几乎一致 |
| **插件化机制** | Cordis 微内核，Everything is a Plugin，挂载/卸载可逆 | NodeRegistry + Adapter (Skill/API/Function) | ★★★★☆ | 同理念不同实现 |
| **能力契约** | TypeScript Tool Contracts，schema 自动入 prompt | SKILL.md 文档契约 + Adapter 配置 | ★★★☆☆ | 同目标不同契约 |
| **运行模式** | Standard/Code/Minimal/Creator 4 个 preset | lean/standard/full 3 档 Token budget | ★★★☆☆ | 概念相通 |
| **可追溯机制** | Append-only session log + Trajectory view，fork/resume/replay | G 层 GraphCompressor 图存储压缩，快照式 JSON | ★★★★☆ | DreamOS 有图但缺事件流 |
| **自进化** | Creator mode 试插件 + rc.8 subagent 编排 | EvolutionEngine + A7/A8 + 做梦部 + D-Z-E 开发链 | ★★★★☆ | DreamOS 更深（领域特化） |
| **子代理编排** | Subagent provider + Agent Teams (rc.8) | 35 个节点分工，无显式子代理概念 | ★★☆☆☆ | DreamOS 可借鉴 |
| **沙箱** | Docker 隔离 + sandbox policy + approval policy | 无显式沙箱（交易执行而非代码执行） | ★☆☆☆☆ | 场景不同 |
| **降级链** | plugin 替换即可 | LLM 降级链 DeepSeek→Qwen + 熔断器（已有记忆） | ★★★☆☆ | DreamOS 已有 LLM 维度 |
| **Model-as-Plugin** | model adapter 是 ctx.llm 上的 plugin | LLMClient 可注入但仍偏耦合 | ★★☆☆☆ | DreamOS 可借鉴彻底化 |
| **Capability Seams** | Service Definition / Provider / Consumer 三角色分离 | Adapter 模式但三角色未明确分离 | ★★☆☆☆ | DreamOS 可借鉴 |
| **领域深度** | 通用 agent runtime（编码/文件/shell/web） | 交易专用（A0-A9 SKILL/经典指标/基本面/交易执行） | — | 不同领域 |
| **技术栈** | TypeScript/Node.js | Python | — | 不同生态 |
| **评测** | DSBench / LM-Eval Pass@1 + 自纠错 | 回测 + Bayesian 认知验证 + 沙箱验证 × 1.1 | ★★★☆☆ | 各有特色 |

### 3.3 相似性的本质

相似点为真：两者都把"agent 内核 = 调度 + 编排 + 进化"作为信条，都拒绝把能力焊死在内核里。

但相似性**不可直接复用**：
1. 技术栈不兼容（TS/Node.js vs Python）
2. 领域差异大（通用编码 agent vs 交易专用）
3. Harness 仍处于 developer preview，API 会变

借鉴价值在于**概念与机制**，不在代码层迁移。

---

## 四、借鉴方向（按 ROI 排序）

### P0 — 高价值低成本（推荐优先评估落地）

#### P0-1: Append-only 事件流升级 G 层

**现状**: G 层是 [data/graph_store/](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/data/graph_store/) 下的 `ckpt_{timestamp}_{hash}.json` 快照式存储，每轮一个 JSON。

**借鉴点**: Harness 的 `session/event` 机制 — 所有 model-visible 内容都 append 到事件流，支持 fork/resume/replay/search。

**对 DreamOS 的价值**:
- A7/A8 自进化需要历史执行数据喂养，事件流比快照更易增量消费
- 回测可基于事件流重放任意历史时刻的决策上下文
- "做梦部"反事实推演可 fork 历史事件流做对照推演
- 认知记忆系统的 verify 机制可基于事件流追溯

**落地草图**:
- 新增 `core/event_log/` 包，提供 `SessionEvent` / `SessionEventMap` / `EventStore`
- G 层从单快照 JSON 升级为 `session.v1.jsonl[.zstd]`，按 turn/step 边界写事件
- `deriveMessages()` 等价物从事件流投影出 model history
- 旧快照做一次性迁移

**风险**: schema 变更需要相邻迁移包（参考 Harness vN→vN+1 设计）

#### P0-2: Profile/Bundle 模式升级 budget_mode

**现状**: 当前只有 lean/standard/full 3 档 Token budget。

**借鉴点**: Harness 的 Profile/Bundle 组合 — 同一代码基线可组合成不同产品形态。

**对 DreamOS 的价值**: 与现有硬约束高度契合。可定义复合 profile：
- `trial_profile` = lean budget + 试错仓 SL/TP 下限 + BCRM2 测试仓上限 (MAX_TRIAL_POSITIONS=2)
- `standard_profile` = standard budget + 常规仓 SL≥4%/TP≥12%
- `aggressive_profile` = full budget + 战略层开放 + 五计庙算进攻档
- `freeze_profile` = war_state=FREEZE → 0 仓位 + 仅观察

**落地草图**:
- 把 Token 三档 + 仓位 SL/TP + 战略开关 + 风控约束打包为 named profile
- profile 间可继承（profile 列出 bundles，bundle 是配置行 + 代码）
- patch overlay 机制支持临时覆盖

### P1 — 中价值中成本

#### P1-1: Capability Seams 三角色分离

**现状**: [adapters/base.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/base.py) 的 Adapter 已有 FunctionAdapter/SkillAdapter/APIAdapter 三种，但 Service Definition / Provider / Consumer 三角色未明确分离。

**借鉴点**: Harness 的 seam 模型 — 定义能力、实现能力、向模型呈现能力是三件不同的事。

**对 DreamOS 的价值**:
- "换 LLM provider" 和 "换数据源" 走同一套机制
- 未来若把经典指标系统从本地 HTTP 切到云端，只换 Provider 实现，不动 tool schema 和 Node 接口

**落地草图**:
- 每个 capability 拆 Service Definition（ABC）/ Provider（具体实现）/ Consumer（model-facing tool 包装）
- 现有 Adapter 升级为 Consumer 角色，新增 Provider 接口

#### P1-2: Model-as-Plugin 彻底化

**现状**: LLM 降级链 DeepSeek→Qwen 已有（记忆库 VM-1786782871311-63f74e37），通过 `get_default_client()` 获取，但 LLMClient 仍是注入式单例，非显式 plugin。

**借鉴点**: Harness 把 model adapter 也作为 ctx.llm 上的 plugin，"换模型"和"换节点"同构。

**对 DreamOS 的价值**:
- LLM 降级链从硬编码升级为配置驱动
- 不同场景用不同模型（如 A1 深度调研用强模型，F 链信号扫描用快模型）成为配置

#### P1-3: Subagent 化外部 API

**现状**: 经典指标系统 (`http://127.0.0.1:8092`)、基本面 API (`http://49.233.123.96:3456`) 都是固定 HTTP 调用，每次 invoke 阻塞主链。

**借鉴点**: Harness 的 Subagent provider — 把外部能力包装成带自己 ctx 与生命周期的子代理，可并行 + 可降级。

**对 DreamOS 的价值**:
- 多个外部 API 可并行调用，降低端到端延迟
- 单个 API 失败不影响其他，更易降级
- 与 DreamOS 既有的重试/降级机制天然契合

### P2 — 探索性

#### P2-1: Trajectory 可视化审计

借鉴 Harness Trajectory view，给 DreamOS G 层做可视化审计 UI — 按 turn/step/tool 维度检视历史决策。

#### P2-2: Creator mode 等价物

DreamOS 已有"做梦部"+"D-Z-E 开发链"，可整合为一个 Creator-style 模式：用于试新节点 / 内存中实验编排 / 创作新 preset。这与 P0-2 profile 化升级天然耦合。

#### P2-3: 社区 plugin 生态

Harness 有 `dsh-plugin` topic。DreamOS 暂为专用系统不需要社区生态，但内部可借鉴 plugin 发现/分发机制。

---

## 五、不建议采用的部分

| 项目 | 不采用原因 |
|------|-----------|
| Cordis 微内核整体迁移 | TypeScript/Node.js 生态与 Python 不兼容，重写成本远大于收益 |
| Docker 沙箱隔离 | DreamOS 不执行任意代码，无需 |
| Subagent 编排 Claude Code/Codex | DreamOS 是交易系统，不需要嵌套外部编码 agent |
| 直接依赖 developer preview API | v0.1.x 仍会有 breaking changes，作为生产系统参考即可 |
| TypeScript Tool Contracts | DreamOS 用 Python，工具契约应保持 Python 风格 |

---

## 六、开放问题 / 后续研究方向

### 6.1 待深挖机制

| 编号 | 问题 | 优先级 |
|------|------|--------|
| OQ-1 | Cordis 论文 (arxiv.org/abs/2608.25512) 中 temporal/spatial composability 的形式化定义与 DreamOS NodeRegistry 的差距 | 中 |
| OQ-2 | Harness session log 的 `vN → vN+1` 相邻迁移包具体实现 — DreamOS 事件流升级是否需要同等复杂度 | 高（P0-1 落地前必研究） |
| OQ-3 | Capability Seams 在 Python 中如何等价实现 — ABC + Protocol + 具体类是否足够 | 中 |
| OQ-4 | Harness Trajectory view 的事件源标注机制 — DreamOS 是否需要按 S/A/C/G 四层标注事件源 | 低 |
| OQ-5 | rc.8 subagent `reportDelivery` 唤醒机制 — 与 DreamOS 反思决策 (CONTINUE/REDO/INSERT_BEFORE/JUMP_TO) 的可融合性 | 中 |
| OQ-6 | Harness Creator mode 的"内存中 Cordis 插件实验"如何等价映射到 DreamOS 做梦部 + D-Z-E | 低 |

### 6.2 待实证验证

| 编号 | 待验证项 | 验证方式 |
|------|---------|---------|
| EV-1 | P0-1 事件流升级后，A7/A8 自进化数据喂养效率是否显著提升 | A/B 回测对比 |
| EV-2 | P0-2 profile 化后，硬约束（MAX_TRIAL_POSITIONS 等）是否仍被一致执行 | 单元测试 + 集成测试 |
| EV-3 | P1-3 subagent 化外部 API 后，端到端延迟降低比例 | 性能压测（参考 DreamOS ST-02 场景） |

### 6.3 待持续跟踪

| 编号 | 跟踪项 | 频率 |
|------|--------|------|
| TR-1 | DeepSeek Harness 版本演进与 breaking changes | 月度 |
| TR-2 | Cordis 论文引用与社区反馈 | 季度 |
| TR-3 | dsh-plugin 社区生态成熟度 | 半年 |
| TR-4 | Harness 在交易/金融领域的应用案例（如有） | 季度 |

---

## 七、与现有 DreamOS 硬约束的兼容性评估

引用 project_memory.md 中的硬约束，评估借鉴方向是否冲突：

| 硬约束 | 借鉴方向 | 兼容性 | 说明 |
|--------|---------|--------|------|
| BDSM direction_constraint | P0-2 profile | ✅ 兼容 | profile 内嵌 direction_constraint 即可 |
| BCRM2.0 测试仓上限 MAX_TRIAL_POSITIONS=2 | P0-2 profile | ✅ 兼容 | trial_profile 内嵌此约束 |
| 战略层模块化开关 enable_five_domain (默认 False) | P0-2 profile | ✅ 兼容 | aggressive_profile 启用开关，其他默认关 |
| 战略层开关关断时取中性默认值 | P0-2 profile | ✅ 兼容 | standard_profile 即中性默认 |
| SL/TP 价格空间下限保护 | P0-2 profile | ✅ 兼容 | 各 profile 内嵌对应下限 |
| 数据清洗 Medallion Architecture | P0-1 事件流 | ✅ 兼容 | 事件流可作为 Gold 层下游消费者 |
| FAIL-OPEN 铁律 | P0-1/P1-1/P1-3 | ✅ 兼容 | 所有借鉴方向均需遵守 FAIL-OPEN |
| 自进化系统 reward 信号 | P0-1 事件流 | ✅ 增强 | 事件流提供更细粒度 reward 来源 |
| 自进化系统 8 个核心组件 | P0-1 事件流 | ✅ 兼容 | 事件流作为数据源，不改变组件逻辑 |
| G-05 不可逆级联熔断 | P0-1 事件流 | ✅ 增强 | 事件流可记录 G-05 4 判据信号触发历史 |

**结论**: 所有借鉴方向与现有硬约束兼容，部分（自进化/G-05）会被增强。

---

## 八、调研结论

1. **相似性为真**：哲学层面"Agent = Model + Harness"与"调度层纯编排"高度一致
2. **相似性不可直接复用**：技术栈 + 领域差异大，重写成本 > 收益
3. **最高价值借鉴**：P0-1（事件流升级 G 层）+ P0-2（profile 化 budget_mode），与 DreamOS 自进化、A7/A8、硬约束高度契合
4. **落地前必做**：P0-1 落地前需完成 OQ-2（研究 Harness vN→vN+1 迁移包具体实现）
5. **持续跟踪**：Harness 仍处于 developer preview，建议月度跟踪版本演进

---

## 九、参考来源

- 官方仓库: https://github.com/deepseek-ai/deepseek-harness
- 官方文档: https://deepseek.com/harness/en/
- 架构文档: https://github.com/deepseek-ai/deepseek-harness/blob/master/docs/architecture.md
- Cordis 论文: https://arxiv.org/abs/2608.25512
- 技术评论:
  - SitePoint: https://www.sitepoint.com/deepseek-harness-developer-preview/
  - InfoQ: https://www.infoq.com/news/2026/08/deep-seek-harness/
  - dev.to: https://dev.to/hunter_g_50e2ec233acd07b5/deepseek-harness-is-open-source-everything-is-a-plugins-579l
  - seventnews: https://www.seventnews.com/en/articles/deepseek-ships-an-agent-harness-where-even-the-model-is-a-plugin
  - Cloudsway: https://www.cloudsway.ai/resources/deepseek-harness-tutorial-architecture-and-quick-start?id=16
  - DeepThink: https://deepthink.ltd/blog/deepseek-harness-rc8-claude-codex-subagent-2026/
  - 阿里云 Model Studio 集成: https://www.alibabacloud.com/help/en/model-studio/deepseek-harness
- DreamOS 内部参考:
  - [dreambuddy-os SKILL.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/skills/dreambuddy-os/SKILL.md)
  - [NodeRegistry](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/registry/node_registry.py)
  - [BaseNode](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/registry/base.py)
  - [AdapterRegistry](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/adapters/base.py)
  - [EvolutionEngine](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/evolution/engine.py)
  - [G 层快照目录](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/1-ARCHITECTURE/dreamos/data/graph_store/)

---

## 十、变更记录

| 版本 | 日期 | 变更 |
|------|------|------|
| v0.1 | 2026-09-13 | 首次调研稿，覆盖 Harness 概览/架构核心/DreamOS 对照/借鉴方向/开放问题 |
