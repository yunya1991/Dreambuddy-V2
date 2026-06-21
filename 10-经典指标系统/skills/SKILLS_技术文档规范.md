# Skills 技术文档规范（SSoT）

更新时间：2026-03-14

## 1. 目标与范围

本规范用于统一管理本仓库的 Skills（工具/能力）体系，覆盖：

- 文档与目录结构：把分散在后端/ops/tools/nanoclaw 的能力形成“可浏览、可检索、可审计”的统一归档视图。
- 能力契约：输入/输出、幂等、限流、超时、产物落盘与回执（receipt）的最小标准。
- 能力调用治理：能力分级（R0/R1/R2/R3）、联网边界、密钥边界、审批/审计口径与可回放证据链。
- 索引与查询表：集中列出当前已存在的 Skills/外联通道/脚本入口与文件锚点，便于后续扩展与迁移。

不覆盖（本规范不直接替代）：

- 交易系统生产侧行为边界与 Runbook：以 [技术文档.md](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/技术文档.md) 为准。
- Agent/沙箱闭环与门禁总规范：以 [交易AI Agent 技术文档2.0.md](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/交易AI%20Agent%20技术文档2.0.md) 为准。

## 2. 设计原则（生产可用导向）

- 最小权限：默认只读（R0），可写/可外发（R2/R3）必须可回滚/可审计/可审批。
- 证据先行：任何建议或动作必须能在同一 repo 版本上复现（file:line / outbox 条目 / trace_id）。
- 结构化输出：工具输出结构化且可截断、可脱敏，避免把大段不可信文本直接回注到决策环。
- 规划与执行分离：先生成不可变的执行计划（tool_plan），再由执行器逐步执行，减少注入与误触发风险（参考“Plan-Then-Execute”等安全模式）。[1]
- 运行可观测：工具调用、外联投递、回执、失败重试与节流状态均应可查询、可回放。

补充参考（通用工程经验）：

- 生产级 Agent 架构要围绕 memory/context/tools 做配额与日志治理，特别是控制上下文与工具输出回注。[2]
- 强制 guardrails、隔离不可信输入与高权限动作，避免 prompt injection 影响工具调用链。[1]

## 3. 目录结构（Skills 归档视图）

Stage A（已落地）：不移动旧文件，不改代码逻辑，仅建立归档视图与索引。

- [skills/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills)
  - [skills/catalog/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/catalog)：机器可读索引与查询表
  - [skills/contracts/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/contracts)：契约镜像（pointer/copy）
  - [skills/routing/](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/routing)：路由/治理配置镜像（copy）
  - `skills/playbooks/`：标准 tool_plan 模板（后续补齐）

目录约束：

- `catalog/` 下文件应可被脚本/工具读取（JSON 优先），用于 UI 展示或检索。
- `contracts/` 与 `routing/` 在 Stage A.1 只允许 “copy/pointer”，不得替代原件作为运行时依赖。
- `playbooks/` 用于沉淀标准调用链模板（R0/R1/R2 分层）。

## 4. Skill 类型与运行域（统一口径）

为避免“技能分散”，将所有能力归到统一分类（不要求都注册为 /agent/skills 的 tool，但必须可索引）：

1) In-Process Skill（进程内工具）
- 定义：由后端直接执行并返回结果（例：`binance_web3.query_token_info`）。
- 入口：`GET /agent/skills/list`、`POST /agent/skills/execute`（实现锚点见 [ml_trade_service.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py)）。

2) Outbox Channel（出站通道/入队型工具）
- 定义：工具只负责写入 outbox（jsonl），由 worker/脚本投递并产生回执（receipt）。
- 典型：twitter/telegram/alert 等 outbox 机制。

3) Host Script（宿主侧外联执行器）
- 定义：独立脚本消费 outbox（或定时抓取外部数据），与生产/沙箱隔离；密钥仅在宿主侧。
- 典型：推特 outbox sender、交易所 ingest cron。

4) Sandbox Script（沙箱研究/回测脚本）
- 定义：在沙箱域跑回测/报告/爬虫与摘要，产出落盘产物；默认禁网或受控联网。
- 典型：nanoclaw news crawler/digest。

## 5. 能力分级（R0/R1/R2/R3）

本仓库建议沿用已有分级语义：

- R0：只读（观测/检索/索引/读取片段），允许自动执行；必须落盘证据链。
- R1：沙箱（回测/稳健性/评估/生成报告），允许自动执行但必须产出可复现三件套（数据快照/配置快照/策略版本）。
- R2：受控动作（外联投递、参数应用流水线、受控触发），默认需人工批准或 operator token；必须幂等与可审计。
- R3：高风险（可能改变生产行为或涉及代码/配置写入），默认必须审批 + 回滚点。

## 6. 契约规范（输入/输出/幂等/限流）

### 6.1 输入规范

- 输入必须是结构化 JSON（或可映射为 JSON），字段可选但语义必须稳定。
- 输入不得包含密钥/token；需要鉴权的动作由运行域读取环境变量或受控配置。
- 每个工具必须定义超时策略（默认值 + 上限），避免工具调用阻塞整体执行。

### 6.2 输出规范

- 输出必须能被 JSON 序列化；必须包含 `ok`（boolean）。
- 大输出必须允许截断（返回 `truncated=true` 与 keys 摘要），避免污染上下文。
- 任何回传敏感信息（疑似密钥/token）必须脱敏或直接拒绝返回。

### 6.3 幂等与去重（强制）

- 外联投递（push/send）类必须有 `idempotency_key`，并在 outbox/receipt 层去重。
- 幂等键建议基于（trace_id + 业务主键 + 内容摘要）构建，保证“同一意图不重复发出”。

### 6.4 限流（强制）

- push 类工具必须有频控（每小时/窗口/最小间隔），并可在 outbox/metrics 中观测。
- 触发器（scheduler/cron）必须有冷却，避免告警风暴与重复入队。

## 7. 调用管理规范（tool_plan）

统一调用载体：tool_plan（步骤数组，逐步执行）。

- tool_plan 必须可回放：写入 outbox（`tool.plan` / `tool.start` / `tool.result` / `tool.plan.done`）。
- R2/R3 tool_plan 必须包含：
  - 风险分级（intent_level / capability_level）
  - 审批引用（approval_id / reason）
  - 回滚点引用（rollback_point_id 或等价结构）

## 8. 索引与查询表

### 8.1 机器可读索引（Stage A）

- 最小域索引（binance/twitter/news）：[minimal_skills_catalog.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/catalog/minimal_skills_catalog.json)
- 规范化索引（当前系统能力全集）：`skills/catalog/skills_index_current.json`（本规范要求保持更新）

### 8.2 归档镜像（Stage A.1）

- Router rules（copy）：[skills/routing/agent_llm_router_rules_prod.example.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/routing/agent_llm_router_rules_prod.example.json)
- News schema（pointer）：[skills/contracts/news_contract.schema.pointer.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/skills/contracts/news_contract.schema.pointer.json)

### 8.3 当前 In-Process Agent Skills（后端已注册）

注册锚点：`ml_trade_service.py` 中 `_agent_skill_register(...)` 段落（见 [ml_trade_service.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ml_trade_service.py)）。

| tool | category | 推荐级别 | 类型 | 备注 |
|---|---|---|---|---|
| metrics.recent | read | R0 | inproc | 最近指标 |
| health.get | read | R0 | inproc | 健康检查 |
| signals.recent | read | R0 | inproc | 最近信号 |
| signals.reject_stats | read | R0 | inproc | 拒单原因统计 |
| read.observe | read | R0 | inproc | 观测快照 |
| read.explain | read | R0 | inproc | 解释请求 |
| tracker.stats | read | R0 | inproc | Tracker 状态 |
| tracker.sync.recent | read | R0 | inproc | 最近同步摘要 |
| engineering.index | read | R0 | inproc | 工程入口索引 |
| doc.retrieve | read | R0 | inproc | 文档检索 |
| doc.lines | read | R0 | inproc | 文档按行读取 |
| doc.snippet | read | R0 | inproc | 文档片段读取 |
| config.get | read | R0 | inproc | 读取配置键 |
| code.search | read | R0 | inproc | 代码搜索 |
| code.lines | read | R0 | inproc | 代码按行读取 |
| code.snippet | read | R0 | inproc | 代码片段读取 |
| code_index.query | read | R0 | inproc | 代码索引查询 |
| fs.glob | read | R0 | inproc | 文件查找 |
| agent.trace.replay | read | R0 | inproc | Trace 回放 |
| audit.alerts_evaluate | audit | R0 | inproc | 告警评估 |
| audit.data_quality | audit | R0 | inproc | 数据质量 |
| audit.execution_quality | audit | R0 | inproc | 执行质量 |
| sandbox.backtest | sandbox | R1 | inproc | 沙箱回测 |
| sandbox.robustness | sandbox | R1 | inproc | 稳健性验证 |
| github.fetch | repo | R1 | inproc | GitHub 拉取策略（白名单） |
| telegram.send | push | R2 | inproc(outbox) | TG 入队（非直发） |
| binance_web3.* | read/audit | R0 | inproc | Web3 公共接口洞察与审计 |
| binance_spot.* | read/trade | R0/R2 | inproc | 行情/账户/交易 |
| changeset.draft | governance | R2 | inproc | 变更包草案 |
| pipeline.r2_param | governance | R2 | inproc | R2 参数流水线 |
| pipeline.r3_bugfix | governance | R3 | inproc | R3 修复流水线 |
| approval.request | governance | R2 | inproc | 审批请求 |

### 8.4 当前外联/脚本能力（未必是 Agent tool，但必须索引）

- 推特投递执行器（宿主脚本）：[twitter_outbox_sender.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/twitter_outbox_sender.py)
- 新闻爬取与摘要（nanoclaw 脚本）：
  - [news_crawler.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1/scripts/news_crawler.py)
  - [news_digest_v2.py](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1/scripts/news_digest_v2.py)
  - Schema 原件：[news_contract.schema.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/ops/nanoclaw/core_task1/schema/news_contract.schema.json)
- Router rules 原件：[agent_llm_router_rules_prod.example.json](file:///Users/zhangjiangtao/ft_userdata/经典指标机器学习系统/tools/agent_llm_router_rules_prod.example.json)

## 9. 新增/改造 Skills 的提交清单（Checklist）

新增任何能力（无论 inproc/outbox/host/sandbox）必须满足：

- 目录与索引：在 `skills/catalog` 增加或更新索引条目（至少包含 tool/kind/level/入口文件）。
- 契约：明确 input/output、幂等键、限流、超时、产物落盘与回执位置。
- 边界：明确联网边界与密钥边界（密钥不入模）。
- 审计：至少能用 `trace_id` 串联 tool_plan → outbox → receipt。
- 回滚：若为 R2/R3，必须提供回滚点口径或“只入队不生效”的降级路径。

## 10. 外部参考（联网检索）

- [1] Design patterns for securing LLM agents（强调通过架构约束与“计划-执行分离”等模式降低 prompt injection 风险）：https://labs.reversec.com/posts/2025/08/design-patterns-to-secure-llm-agents-in-action
- [2] Vellum: The ultimate LLM agent build guide（强调 memory/context/tools 的生产工程实践与可观测性）：https://www.vellum.ai/blog/the-ultimate-llm-agent-build-guide
