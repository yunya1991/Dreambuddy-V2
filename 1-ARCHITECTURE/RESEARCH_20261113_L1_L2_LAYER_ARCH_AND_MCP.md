# RESEARCH — L1/L2 层级架构梳理 与 层级 MCP 管理（插件化前置）

> **版本**: v0.1（调研稿，待确认）
> **日期**: 2026-11-13
> **范围**: 在 [3+3架构模块映射.md](./3+3架构模块映射.md) 的 L0/L1/L2 框架下，细化 L1、L2 的层级内部结构，并给出「层级 MCP 管理 → 插件化」的设计口径与注册清单
> **不做什么**: 本文只做调研与设计口径，不改代码、不改注册表、不注册新壳
> **上游 SSoT**: [SYSTEM_ARCHITECTURE_OVERVIEW.md](./SYSTEM_ARCHITECTURE_OVERVIEW.md) v4.2 · [49-交易框架协议/SPEC.md](../49-交易框架协议/SPEC.md) v0.14.2 · [47-MCP管理系统/registry/mcp_capabilities.yaml](../47-MCP管理系统/registry/mcp_capabilities.yaml) v0.5
> **判据来源**: [34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md](../34-前端应用训练系统/SPEC-v1.3-L0L1L2-architecture.md) §1「判据边界定义」

---

## 0. 结论摘要

1. **L0 已形成「六 port + 七壳 + 角色网关 + 能力发现」的完整封装范式**（57 个 active 工具 / 软上限 80，`validate_mcp_registry.py` 实测）。
2. **L1 目前只有 1 个聚合壳** `l1.trading.mcp`（10 工具），仅覆盖交易链「状态只读 + forward_signal」；L1 的意图执行（10 意图）、策略治理（25-28）、监控/总线（15/36）、产物/协作（7/8）**全部零 MCP**。
3. **L2 目前零层级 MCP**。L2 的能力以 HTTP（DreamOS `/api/v1/*`）、IPC（34 core / DSH）、CLI 形态存在；唯一带 MCP 的 L2 模块是 32 辩论，但命名是 `agent.debate.mcp`，未纳入层级体系。
4. **层级 MCP 管理与 L0 不是同一件事**：L0 壳是「对内供给能力」，L1/L2 壳是「对外暴露层级能力 + 层级间只读观察」。三者共用同一注册表与网关，但**暴露语义、授权语义、上限配额不同**，必须在 registry 上增加 `layer` 维度才能分治。
5. **建议分三步**：① registry 增加 `layer/exposure` 维度并补齐 L1 现有壳 → ② 注册 L1 意图域 + L2 两个只读壳（debate/dreamos）→ ③ 再谈插件化（能力卡 → plugin manifest → Cordis），且必须遵守 53 已定的「先消费→再封装→后治理」硬约束。
6. **需用户拍板 6 个决策点**（见 §9），核心是：L1 是否拆四域、L2 首批是否只做两壳、工具总上限是否提额到分层配额。

---

## 1. 事实基线（代码/注册表核对结果）

| # | 事实 | 证据 |
|---|---|---|
| F1 | 注册表 10 个壳、57 个 active 工具、软上限 80（余量 23） | `python3 47-MCP管理系统/registry/scripts/validate_mcp_registry.py` → `✅ 10 存量壳 + 0 规划壳 / 57 active 工具 / 上限 80` |
| F2 | L0 七壳：cognition / semantic-39 / rea / data / eval / store-admin / trade-exec（+ deprecated rea-client） | [mcp_capabilities.yaml](../47-MCP管理系统/registry/mcp_capabilities.yaml) `shells[]` |
| F3 | L1 一壳：`l1.trading.mcp`，10 工具（9 读 + forward_signal 写），已登记 available | 同上 + [mcp_shells/l1_trading/server.py](../mcp_shells/l1_trading/server.py) `_TOOLS`（L509-580） |
| F4 | L2 壳：仅 `agent.debate.mcp`（3 工具，非层级命名） | 同上 |
| F5 | 角色网关仅 L0 形态（`l0_gateway --role`），L1/L2 无网关 profile | [SPEC-L0-MCP-GATEWAY-v0.1.md](../47-MCP管理系统/docs/tech/SPEC-L0-MCP-GATEWAY-v0.1.md)、[mcp_profiles.json](../47-MCP管理系统/registry/mcp_profiles.json) |
| F6 | 已存在 L2 只读角色：`l2_analysis`（debate+cognition）、`l2_trading_analysis`（l1.trading 只读 9 工具） | `worker_roles` 段 |
| F7 | registry **无 `layer` 字段**；校验器不区分层，只校验 shell/role 级约束 | [validate_mcp_registry.py](../47-MCP管理系统/registry/scripts/validate_mcp_registry.py) |
| F8 | L1 意图执行实体在 3.1 前端（`src/lib/l1-intent-registry.ts` + `scripts/data_query_executor.py`），10 意图全零 token | 架构总览 §4.2；commit 69f308ab87 拆解记录 |
| F9 | L2 对外接口现状：DreamOS Flask 12 端点（`/api/v1/intent`、`/run`、`/run/async`、`/result/<id>`、`/budget` 等）；34 通过 `dsh_frontend_bridge.py` 走 IPC（`orchestrator_v2`/`knowledge_search`/`user_memory`/`router_pass` 等） | [dreamos/apps/api_server.py](../1-ARCHITECTURE/dreamos/apps/api_server.py) L98-387；[dsh_frontend_bridge.py](../34-前端应用训练系统/core/dsh_frontend_bridge.py) |
| F10 | 49 SPEC §3.8 仍写「`mcp_shells/l1_trading/` 当前不存在（设计态）」，与 F3 冲突 → 文档漂移 | [49-交易框架协议/SPEC.md](../49-交易框架协议/SPEC.md) L559 |
| F11 | 53 已定插件三维递进硬约束：先消费社区插件 → 再封装 L0 为 DSH 插件 → 接入量>5 后再做治理层 | [plugin_whitelist.yaml](../53-DSH插件模块/plugin_whitelist.yaml) + 认知库硬约束记忆 |
| F12 | L2 已有可复用底座：`ShellHandleManager`（壳生命周期）、`ticket_store/router/resume`、`router_loop`、`mandate_gate`、`gate_45_adapter` | [34 core](../34-前端应用训练系统/core/) |

---

## 2. 判据再定义：L1 与 L2 的唯一分界

### 2.1 唯一判据（沿用 v1.3，不新造口径）

> **是否依赖「生成式 LLM 推理」** —— 依赖 → L2；不依赖 → L0 或 L1。

| 判定问题 | L1 | L2 |
|---|---|---|
| 是否发起 chat/completion 类调用 | 否 | 是 |
| 同输入是否确定性可复现 | 是 | 否（采样） |
| 成本 | 0 token | token |
| 延迟承诺 | 毫秒~秒级 | 秒~分钟级 |
| 失败形态 | 确定性降级（FAIL-OPEN/降级值） | 语义降级、需裁决/复核 |

### 2.2 灰区处理规则（本次新增，用于消除 L1/L2 拉扯）

| 规则 | 内容 | 典型例子 |
|---|---|---|
| R1 本地模型不算 L2 | 嵌入、FinBERT 情感、KNN/CBR、贝叶斯、统计检验 → L1 | 9 基本面 FinBERT、34 语义嵌入、48 度量 |
| R2 工具链不算 L2 | pandas/numpy/ta-lib 计算、规则引擎、调度器 → L0/L1 | 10 经典指标、13 风控、22 执行引擎 |
| R3 主体唯一、形态可降级 | 混合组件按**主体能力**归层；其无 LLM 子集可作为 L1 意图或只读工具暴露，但**归属不变** | 11 易经、23 自进化、33 REA、35 认知、48 涌现 |
| R4 编排 ≠ 生成 | 图执行、节点调度、重试、聚合 → 确定性（可归 L1）；只有「规划/反思/裁决的理由生成」才是 L2 | DreamOS C 层 GraphExecutor 属机制，其 Reflector 用 LLM 的部分属 L2 |
| R5 一次 LLM 调用即 L2 | 只要某路径**必须**经过生成式 LLM 才能完成，该路径归 L2；L2 内部可再拆「LLM 必需 / LLM 可选」 | 52 提案、32 辩论、34 主动训练 |

### 2.3 层级声明规范（建议写入 registry）

每个模块必须声明三件事，缺一不可：

```
layer: L1 | L2 | L1/L2(主体=Lx)
exposure: in-process-only | readonly-observe | control(需Mandate) | not-exposed
llm_dependency: none | optional | required
```

---

## 3. L1 层级架构（零 token 确定性能力）

### 3.1 内部四子层

```
L1-A 意图执行层（对外第一跳，in-process，零 token）
  意图注册表(10 意图) + 路由器 + 意图执行器 + 案例沉淀(l1_case_store)
        ↓ fetchContext（读 L0）/ settle（写 L0）
L1-B 交易确定性能力层（双决策链的 L1 部分）
  B1 输入分析：9 基本面 / 10 经典指标 / 39 语义(主体L0)
  B2 子交易系统：11 BCRM2.0·BDSM·洗盘·事件套利 / 12 三屏 / 14 马丁 / 17 波浪 / 29 事件驱动
  B3 宏观弹性：40 周期NN / 43 战略承接
  B4 协调：42 协调层（插件总线）
  B5 决策：50 NN主矛盾（NN链出口） / 23 自进化（对照链，L1/L2）
  B6 执行：13 风控 → 16 调控/离场 → 22 执行引擎 → 51 OKX CLI / 11 执行器
        ↓
L1-C 确定性服务层（非交易，被全系统复用）
  15 监控告警 / 36 信号总线 / 25-28 策略四件套 / 7 产物中台 / 8 FEISHU
```

### 3.2 模块归属与 MCP 暴露建议

| 子层 | 模块 | 已有 MCP | 建议暴露形态 | 建议壳（P 级） |
|---|---|---|---|---|
| L1-A | 意图注册表 + 10 意图执行器 | ❌ | **readonly-observe**（`classify_intent` / `list_intents` / `execute_intent` 只读意图） | `l1.intent.mcp`（P0） |
| L1-B5 | 50 NN 主矛盾 | 部分（经 l1.trading `get_signal_state`/`get_decision_diagnostics`） | readonly-observe（摘要+置信度，原始权重不下发，遵 R-23-12） | 并入 `l1.trading.mcp`（已有） |
| L1-B3/B4 | 40 / 43 / 42 | ✅ `get_cycle_state`/`get_strategic_extension`/`get_bus_state` | readonly-observe | 已有 |
| L1-B6 | 13/16/22/51/11 执行器 | ✅ 部分（trade-exec paper 壳 + l1.trading 代理持仓/余额） | **hot-path 永不 MCP**；仅只读状态/风控建议 | 已有（不扩） |
| L1-B1/B2 | 9/10/12/14/17/29 | ❌ | readonly-observe（信号/指标/状态查询） | 暂缓，先并入 `l1.trading.mcp` 的只读组或后续 `l1.signal.mcp`（P2） |
| L1-C | 25-28 策略四件套 | ❌ | readonly-observe（策略/版本/审批/触发记录）；写操作留 in-process | `l1.strategy.mcp`（P1） |
| L1-C | 15 监控 / 36 总线 | ❌ | readonly-observe（告警、健康、订阅状态） | `l1.ops.mcp`（P2） |
| L1-C | 7 产物中台 / 8 飞书 | ❌ | readonly-observe（产物索引/进度、群/Bot 状态）；飞书写操作永不 MCP | 暂不注册（无外部消费方） |

**L1 硬约束（建议）**：
- L1 交易热路径（判定/下单/止损）**必须 in-process**，禁止新增 MCP 调用点（H1 不变）。
- L1 壳默认只读；`forward_signal` 是唯一写工具，且仅 L1 内部编排可用，L2 角色不可见。
- 实盘链路（11 live / 51 真实下单）**永不暴露 MCP**。

---

## 4. L2 层级架构（大模型驱动）

### 4.1 内部五子层

```
L2-K 内核编排（DreamOS · 新 SACG）
  S 认知驱动规划入口（recall 先验 + 元认知门控 + 开工 Skill → Spec/Plan）
  A OKR 节点验收
  C 执行驱动（DSH 子 Agent + GraphExecutor + Reflector）
  G 压缩沉淀（GraphStore + 收尾 Skill 四分流）
  横切：NodeRegistry / Evolution / Budget / Adapters
        ↓
L2-E 执行编排（DSH Router/Worker）
  常驻 Router（无状态批处理）+ Worker 角色池（≤10 工具/角色）+ Ticket/Mandate + 会话可续
  实现载体：34-core（router_loop / ticket_* / mandate_gate / gate_45_adapter / shell_handles）
        ↓
L2-G 生成式能力层
  34 训练系统（主动采集训练 + 被动 Trae 辅导） / 48 涌现（D1/D2/D3） / 32 对抗辩论 / 30 真实环境E2E / 3-EVOLUTION
        ↓
L2-P 协议接入层
  46 DSH Harness / 52 LobeHub 协议层（模型路由+PlanCard）/ 53 Cordis 插件生态 / 24 图压缩（G 层实现）
        ↓
L2-A 应用与前端
  3.1 主前端（SACG 意图路由 + 56 页面） / 6 交易中台（A0-A9 流水线 + SKILL 引擎）
```

### 4.2 模块归属与 MCP 暴露建议

| 子层 | 模块 | 现有对外形态 | 建议暴露形态 | 建议壳（P 级） |
|---|---|---|---|---|
| L2-K | DreamOS 内核（intent/run/analyze/budget） | HTTP `/api/v1/*` 12 端点 | **control（submit/poll 异步）+ readonly** | `l2.dreamos.mcp`（P1） |
| L2-E | DSH Router/Worker/Ticket | IPC（34 bridge） | readonly-observe 优先；dispatch 需 Mandate | `l2.dsh.mcp`（P2） |
| L2-G | 32 对抗辩论 | ✅ `agent.debate.mcp`（3 工具） | readonly（异步 submit/poll） | 重命名 `l2.debate.mcp`（P0，保留别名） |
| L2-G | 34 训练系统 | 触发脚本 + IPC | control（trigger 需 Mandate + 45 门禁）+ readonly 状态 | `l2.train.mcp`（P2） |
| L2-G | 48 涌现 | 无 | readonly（度量/实验状态；D1-D3 报告） | `l2.emergence.mcp`（P2） |
| L2-G | 3-EVOLUTION / 30 E2E | 无 | not-exposed（实验态/内部） | 不注册 |
| L2-P | 52 LobeHub / 53 插件 / 46 DSH | 协议层/插件清单 | not-exposed（是宿主侧协议，不是能力面） | 不注册（走插件化，不走 MCP） |
| L2-A | 3.1 前端 / 6 交易中台 | HTTP | not-exposed（宿主/应用） | 不注册 |

**L2 硬约束（建议）**：
- L2 **只能只读观察 L1**（`l1.trading.mcp` 9 只读工具），**不得触发信号/执行/训练写操作**。
- L2 自身壳的写工具（trigger_run / trigger_training / dispatch）必须 Mandate + 预算 + trace 三件套。
- L2 壳必须返回 `meta.tokens_used / budget_remaining / model`，否则无法做层级成本审计。
- L2 永不直连 DB；数据一律经 L0 壳或 in-process DAL。

---

## 5. 现状差距（L0 已清晰，L1/L2 缺什么）

| # | 差距 | 影响 | 优先级 |
|---|---|---|---|
| GAP-1 | registry 无 `layer` 维度 | 无法按层审计工具面、无法按层配额、无法生成层级 Agent Card | P0 |
| GAP-2 | L1 只有交易聚合壳，意图层零 MCP | 外部宿主（Trae/Claude Code/Cursor）无法零 token 直答，只能走 L2 烧 token | P0 |
| GAP-3 | L2 零层级壳（debate 命名游离） | L2 能力无法被外部宿主标准化调用；只能 HTTP/IPC 私有耦合 | P1 |
| GAP-4 | 无 `l1/l2-gateway` | 角色投影只覆盖 L0；L1/L2 只能直连整壳，权限粒度粗 | P1 |
| GAP-5 | 工具预算余量仅 23（57/80） | L2 注册后极易触顶，需先定分层配额 | P0（决策） |
| GAP-6 | 49 SPEC §3.8 仍称 l1_trading 不存在 | 文档与代码漂移，影响评审 | P1（文档修正） |
| GAP-7 | L2 缺统一信封 / trace / token 计量 | 无法做层级成本与证据边界 | P1 |

---

## 6. 层级 MCP 管理设计

### 6.1 命名与目录规范

| 层 | shell_id 模式 | 网关 | 说明 |
|---|---|---|---|
| L0 | `l0.<domain>.mcp` | `l0_gateway --role <role>` | 已有 |
| L1 | `l1.<domain>.mcp` | `l1_gateway --role <role>` | 新增 |
| L2 | `l2.<domain>.mcp` | `l2_gateway --role <role>` | 新增 |
| 过渡 | `agent.*.mcp` | — | 仅保留 `agent.debate.mcp` 兼容别名 1 个迭代 |

域名（`domain`）沿用现有 enums，新增：`intent / strategy / ops / dreamos / dsh / train / emergence / debate`。

### 6.2 Registry Schema v1.2-mcp 增量（最小改动）

在 shell 级新增 4 个字段（全部可选，向后兼容）：

```yaml
layer: L1                      # L0 | L1 | L2（新增枚举）
capability_domain: intent      # 层级内能力域
exposure: readonly-observe     # in-process-only | readonly-observe | control | not-exposed
source_modules: ["3.1-FRONTEND", "34"]   # 能力来源模块，便于溯源
plugin_ready: false            # 是否可作为 Cordis/DSH 插件封装对象（插件化门禁）
```

`enums` 增补：

```yaml
layer: [L0, L1, L2]
exposure: [in-process-only, readonly-observe, control, not-exposed]
layer_quota: {L0: 60, L1: 30, L2: 30}   # 替代单一 max_total_tools，见 G4
```

### 6.3 三层暴露语义矩阵（谁能调谁）

| 调用方 ↓ / 被调方 → | L0 壳 | L1 壳 | L2 壳 | in-process |
|---|---|---|---|---|
| 外部宿主（Trae/Claude/Cursor） | ✅ 按角色 | ✅ 按角色（默认只读） | ✅ 按角色 | ❌ |
| L2 编排（DreamOS/DSH） | ✅ 按角色 | ✅ **只读** | ✅ 自身 | ✅（L0 port） |
| L1 内部编排 | ✅ | ✅（含写） | ❌ | ✅ |
| L2 Worker | ✅ 按角色 | ✅ 只读 9 工具 | ❌（不自调） | ❌ |

**不可逆红线**：L2 → L1 写 = 禁止；L1 热路径 → MCP = 禁止；实盘 → MCP = 禁止。

### 6.4 角色矩阵（新增角色，均 ≤10 工具）

| 角色 | 层 | 壳 | 工具（≤10） | 用途 |
|---|---|---|---|---|
| `l1_observer` | L1 | l1.intent + l1.trading | `list_intents, classify_intent, execute_intent, get_signal_state, get_constraint_state, get_cycle_state, get_strategic_extension` | 外部只读观察 L1 |
| `l1_ops` | L1 | l1.strategy + l1.ops | 策略列表/版本/审批状态/触发记录 + 告警/健康/总线状态 | 运维与策略审计 |
| `l2_planner` | L2 | l2.dreamos | `submit_run, poll_run, get_result, get_intent, get_budget` | L2 规划编排 |
| `l2_researcher` | L2 | l2.debate + l2.emergence + l0.cognition | debate 3 + emergence 3 + recall/unified_search | 研究与辩论 |
| `l2_trainer` | L2 | l2.train | `get_training_status, list_runs, trigger_training`(Mandate) | 训练运维（写受限） |

> 复用 `l0_gateway` 实现即可；新增 `--layer` 用于 Agent Card 与审计标注，不重写网关。

### 6.5 插件化路径（与 53 硬约束对齐）

```
① 层级 MCP 注册（本文 §7 清单）
        ↓ capability_id + layer + exposure 为唯一键
② 能力卡（Agent Card，已有生成器 mcpctl cards）
        ↓ 增 layer/exposure/llm_dependency 三字段
③ 插件清单（plugin manifest）
        ↓ 映射到 53 plugin_whitelist.yaml（deny-by-default）
④ Cordis/DSH 插件封装
        ↓ 先消费社区插件（层级1）→ 再封装自有能力（层级2）→ 治理（层级3，>5 个后）
```

**插件化门禁（建议新增）**：
- 只有 `exposure=readonly-observe` 或 `control(受Mandate)` 的壳允许 `plugin_ready: true`。
- `in-process-only`（L1 热路径）**永不插件化**——插件化即跨进程，违反 H1。
- 插件必须复用 MCP 壳，不得绕过壳直连业务代码（否则双事实源）。

---

## 7. 建议注册清单（分 P 级）

| P | 壳 | layer | 工具（草案） | 数量 | 依赖/前置 |
|---|---|---|---|---|---|
| P0 | `l1.trading.mcp`（补 `layer` 字段 + 迁 shell_runtime） | L1 | 现有 10 | 0 新增 | 无 |
| P0 | `l2.debate.mcp`（由 `agent.debate.mcp` 重命名，留别名） | L2 | `start_debate / get_debate_result / debate_health` | 0 新增 | 无 |
| P0 | `l1.intent.mcp` | L1 | `list_intents / classify_intent / execute_intent` | +3 | 3.1 `l1-intent-registry.ts` 需暴露 HTTP 或 in-process 适配 |
| P1 | `l1.strategy.mcp` | L1 | `list_strategies / get_strategy_version / get_approval_state / list_signal_triggers` | +4 | 25-28 端口只读 |
| P1 | `l2.dreamos.mcp` | L2 | `submit_run / poll_run / get_result / get_intent / get_budget` | +5 | DreamOS API 适配 + 异步 job store |
| P2 | `l1.ops.mcp` | L1 | `list_alerts / get_health / get_bus_state` | +3 | 15/36 |
| P2 | `l2.train.mcp` | L2 | `get_training_status / list_runs / trigger_training`(Mandate) | +3 | 34 + gate_45 |
| P2 | `l2.emergence.mcp` | L2 | `get_emergence_metrics / list_experiments / get_experiment_report` | +3 | 48 度量 |

**预算测算**：57 + 21 = **78 / 80** —— 几乎顶格。因此 **G4（提额到分层配额）是本轮注册的前置决策**，否则只能砍到 P0+P1（57+12=69）。

---

## 8. 风险册

| # | 风险 | 触发条件 | 缓解 |
|---|---|---|---|
| R-1 | 工具面膨胀推高上下文成本 | 每层都建壳，外部宿主加载全量工具 | 强制走角色网关（≤10/角色），禁止宿主直连全量壳 |
| R-2 | 双事实源 | 壳内重新实现业务逻辑 | 壳只做协议转换，业务一律 in-process 调用；49 §R-L0-03 同款约束 |
| R-3 | L2 越权写 L1 | 未来新增 `forward_signal` 类工具进 L2 角色 | 网关启动校验：角色含 `requires_mandate=true` 即拒绝（已有机制，扩展到 L1/L2 角色） |
| R-4 | 层级命名迁移破坏已有配置 | `agent.debate.mcp` 改名 | 保留别名 1 个迭代 + `mcpctl` 迁移提示 |
| R-5 | 插件化绕过壳 | 直接写 Cordis 插件调业务 | 53 白名单加 `mcp_shell_required: true` 字段 |
| R-6 | 文档漂移 | 49 §3.8 与实现不一致 | 本轮同步修正 49 SPEC §3.8 状态 |

---

## 9. 待决问题（需用户拍板）

| # | 决策点 | 选项 | 建议 |
|---|---|---|---|
| **G1** | L1 是否拆「四域」 | A 拆 intent/trading/strategy/ops；B 保持单壳聚合 | **A**：意图域与交易域消费方完全不同，聚合会让 L2 角色看到不该看的交易工具 |
| **G2** | L2 首批范围 | A 只做 debate+dreamos；B 再加 train/emergence | **A**：先验证「L2 壳 = 异步 submit/poll + token 计量」范式，再扩 |
| **G3** | 命名迁移 | A `agent.debate.mcp` → `l2.debate.mcp` 留别名；B 保持原名 | **A**：层级命名是后续插件化的索引前提 |
| **G4** | 工具上限 | A 提到 120 + 分层配额 60/30/30；B 保持 80 并砍工具 | **A**：当前 78/80 已无扩展空间，且分层配额比单一总数更可控 |
| **G5** | 层级网关 | A 新增 `l1_gateway/l2_gateway`（复用实现）；B 直接用 `l0_gateway --layer` | **B**：一个网关 + `--layer` 参数，避免三份代码 |
| **G6** | 插件化时点 | A 本轮只做到「能力卡 + `plugin_ready` 标记」；B 本轮直接封 Cordis 插件 | **A**：遵守 53「先消费→再封装→后治理」，且当前自有插件仅 3 个 |

---

## 10. 确认后的执行顺序（供参考）

1. 修订 [3+3架构模块映射.md](./3+3架构模块映射.md)：补 §L1/L2 子层结构与模块表（本文 §3/§4 收敛为正式口径）。
2. 新增 `47-MCP管理系统/docs/tech/SPEC-L1L2-MCP-PACKAGING-v0.1.md`（基于本文 §6/§7）。
3. 改 `mcp_capabilities.yaml` → schema v1.2-mcp（+layer/exposure/source_modules/plugin_ready、enums.layer、layer_quota）。
4. 同步 `validate_mcp_registry.py`（layer 合法性、分层配额、exposure 与 read_write 一致性）。
5. 按 P0 → P1 注册壳；同步 `mcp_profiles.json` / `agent_cards.json`；`mcpctl verify` 漂移检查。
6. 修正 49 SPEC §3.8 的「设计态」表述。

---

## 11. 维护

- 本文为调研稿；确认后其结论并入 `3+3架构模块映射.md` 与 47 域 SPEC，本文转为历史留档。
- 与 SSoT 冲突时，以 `SYSTEM_ARCHITECTURE_OVERVIEW.md` 与 `49-交易框架协议/SPEC.md` 为准。
