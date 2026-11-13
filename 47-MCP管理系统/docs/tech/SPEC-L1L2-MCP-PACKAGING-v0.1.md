# SPEC:L1/L2 层级 MCP 封装（Packaging）— 契约、边界与实施路线

> **版本**: v0.1 ｜ **更新日期**: 2026-11-13 ｜ **状态**: ✅ 已批准——DEC-01~DEC-06 全部落定，Phase 0 已启动。由 [RESEARCH_20261113_L1_L2_LAYER_ARCH_AND_MCP](../../1-ARCHITECTURE/RESEARCH_20261113_L1_L2_LAYER_ARCH_AND_MCP.md) 收敛
> **上游 SSoT**:
> · [SYSTEM_ARCHITECTURE_OVERVIEW v4.2](../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md)
> · [3+3架构模块映射 v1.0](../../1-ARCHITECTURE/3+3架构模块映射.md)
> · [49-交易框架协议/SPEC v0.14.2](../../49-交易框架协议/SPEC.md)（双决策链口径）
> · [SPEC-L0-MCP-PACKAGING v0.3](./SPEC-L0-MCP-PACKAGING-v0.3.md)（L0 封装范式，本 SPEC 延伸）
> · [SPEC-L0-MCP-GATEWAY v0.1](./SPEC-L0-MCP-GATEWAY-v0.1.md)（网关架构，本 SPEC 新增 L1/L2 层投影）
> **依赖**: registry schema v1.2-mcp（本 SPEC §4）· 45 评测门禁（训练写工具）· 53 插件白名单（插件化）
> **定位**: 实施 SPEC。回答"L1/L2 能力如何按层级封装为 MCP + 如何治理层级间读写 + 如何为插件化铺路"。
> **不做什么**: 不改 L0 七壳契约（由 SPEC-L0-MCP-PACKAGING v0.3 覆盖）；不直接封装 Cordis 插件（由 53 域消费→封装→治理三维递进覆盖）；不把 L1 热路径（判定/下单/止损）搬去 MCP（硬约束 H1）。

---

## 0. 决策摘要（评审前必须落定）

以下六项为 v0.1 草案内嵌决策，评审时如需推翻需明确给出替代方案：

| # | 决策点 | 决议 | 理由 |
|---|---|---|---|
| **DEC-01** | L1 拆分四域 | intent / trading / strategy / ops 四壳并行注册 | 意图域消费方（Trae/Claude Code）与交易域消费方（L2 研究/外部审计）完全不同；聚合会让 L2 角色看到不该看的 forward_signal 写工具 |
| **DEC-02** | L2 首批范围 | 仅 l2.debate + l2.dreamos | 先验证"异步 submit/poll + token 计量"范式；34/48 壳顺延 P2 |
| **DEC-03** | 命名迁移 | `agent.debate.mcp` → `l2.debate.mcp` + 1 迭代别名 | 层级命名是后续插件化索引前提；别名避免已有配置立即断裂 |
| **DEC-04** | 工具上限 | 单一上限 80 改为分层配额 {L0:60, L1:30, L2:30}，总 120 | 57 + 21（P0+P1）= 78/80 已顶格；分层配额比单一总数更可控 |
| **DEC-05** | 层级网关 | 复用 `l0_gateway` 实现 + `--layer {L0,L1,L2}` 参数，不新增三份代码 | 网关逻辑零差异（role projection + shell routing）；三份代码会制造维护负担 |
| **DEC-06** | 插件化时点 | 本轮只注册壳 + 能力卡 + `plugin_ready` 标记；不封 Cordis 插件 | 遵守 53 域「先消费社区插件 → 再封装自有能力 → 接入量 >5 后治理」三维递进；当前自有插件仅 3 个 |

---

## 1. 定位（对齐 L0-P，延伸 L1-P/L2-P）

**MCP = 三层架构的对外统一出口（边界适配层），不是内部调用链改造。**

```
外部宿主（Trae / Claude Code / Cursor / 云端 Agent / 研究工具）
        │ MCP stdio（一层壳=一能力域）
        ▼
┌────────────────────────────────────────────────────┐
│ l0_gateway --layer {L0,L1,L2} --role <role>        │
│ tools/list = worker_roles[role].tools              │
│ tools/call = 角色白名单 → 壳路由 → 信封治理         │
└────┬──────────┬──────────────────┬─────────────────┘
     │          │                  │
  l0.<domain> l1.<domain>       l2.<domain>
  (七壳)       (四壳首批)       (两壳首批)
```

| 层级 | 定位 | 驱动 | 成本 | 暴露默认 |
|---|---|---|---|---|
| **L0-P**（已有） | 数据/事实/经验的对外统一出口 | 数据库/管线/规则/认知 | 0 token | 按 role 裁剪（只读为默认） |
| **L1-P**（本 SPEC 新建） | 零 token 确定性金融能力的对外出口 | 算法/规则/统计/意图识别 | 0 token | **默认 readonly-observe**；写工具需 mandate + 45 门禁 |
| **L2-P**（本 SPEC 新建） | 大模型驱动编排/推理/生成的对外出口 | LLM（DreamOS + DSH + 子 Agent） | token 成本 | control（submit/poll 异步）+ readonly 状态；写工具需 mandate + 预算 + trace |

### 1.1 三条硬约束（继承 + 新增）

| 继承自 L0-P | H1 | L1 交易热路径（判定/下单/止损）**必须 in-process**，永不 MCP |
|---|---|---|
| 继承自 L0-P | H2 | 实盘链路（11 live / 51 真实下单）**永不暴露 MCP** |
| 继承自 L0-P | H3 | 壳内**零业务逻辑**：只允许 协议解析 → port/域入口调用 → 信封映射 三段 |
| **本 SPEC 新增** | H4 | L2 对 L1 只能只读观察；L2 永不触发 L1 写操作 |
| **本 SPEC 新增** | H5 | L2 自身壳的写工具（trigger_run / trigger_training / dispatch）必须 Mandate + 预算 + trace 三件套 |
| **本 SPEC 新增** | H6 | L2 壳返回信封必须带 `meta.tokens_used / meta.budget_remaining / meta.model` |
| **本 SPEC 新增** | H7 | L2 永不直连 DB；数据一律经 L0 壳或 in-process DAL |
| **本 SPEC 新增** | H8 | 插件化必须遵守 53 域「先消费 → 再封装 → 后治理」三维递进；`in-process-only` 壳永不插件化 |

---

## 2. 三维合理性裁决

### 2.1 金融维度：8/10，合理

- L1-P 暴露的是**确定性信号/状态/指标**，与金融机构对"模型可解释输出"的监管期望（SR 11-7、EU AI Act 日志可追溯）一致。
- L2-P 暴露的是**编排/推理能力**，而非交易执行——隔离了 token 成本的不确定性与实盘风险。
- H4（L2 对 L1 只读）对应 Citadel 「risk as product」原则：LLM 规划层不能越权操纵执行层。
- 写工具三重门禁（Mandate + 预算 + trace）对齐 JPMorgan Ask David 多 Agent 受控工具面实践。

### 2.2 代码工程维度：8.5/10，合理

- **延伸 L0-P 六边形架构外延**：L1/L2 壳是 driving adapter 的第二层，端口/业务/协议三层清晰。
- **registry 分层配额**（DEC-04）替代单一 max_tools_per_shell——层级内可各自扩缩，不互相挤压。
- **统一网关复用**（DEC-05）避免写三份 gateway；与 SPEC-L0-MCP-GATEWAY v0.1 架构零差异。
- **插件化前置标记**（DEC-06）让壳在设计期就声明"是否可插件化"，避免后续双事实源。
- 已知替代方案（写工具全走 HTTP 常驻、L1 热路径也搬 MCP）均已否决，理由同 L0-P PACKAGING v0.3 §2.2。

### 2.3 AI 发展维度：8/10，合理且前瞻

- MCP 2025 `tool.annotations.readOnlyHint` 可直接承载 H4（L2 对 L1 只读）语义；宿主可据此刻意拦截。
- 异步 submit/poll + token 计量（H6）对齐 MCP 官方"长任务"演进方向（`initialize` capability `supportsLongRunningTools`）。
- 插件化递进（DEC-06 / H8）预留 Cordis 生态接入点，但不过早承诺——避免 53 域治理悬空。

---

## 3. 判据与归属契约

### 3.1 唯一分界判据（沿用 v1.3）

> **是否依赖生成式 LLM 推理** —— 依赖 → L2；不依赖 → L0 或 L1。

| 判定问题 | L1 | L2 |
|---|---|---|
| 是否发起 chat/completion 类调用 | 否 | 是 |
| 同输入是否确定性可复现 | 是 | 否（采样） |
| 成本 | 0 token | token |
| 延迟承诺 | 毫秒~秒级 | 秒~分钟级 |
| 失败形态 | 确定性降级（FAIL-OPEN/降级值） | 语义降级、需裁决/复核 |

### 3.2 灰区处理规则（v0.1 新增，用于消除 L1/L2 拉扯）

| 规则 | 内容 | 例子 |
|---|---|---|
| R1 本地模型不算 L2 | 嵌入 / FinBERT 情感 / KNN / 贝叶斯 / 统计检验 → L1 | 9 基本面 FinBERT、34 语义嵌入、48 度量 |
| R2 工具链不算 L2 | pandas / numpy / ta-lib / 规则引擎 / 调度器 → L0/L1 | 10 经典指标、13 风控、22 执行引擎 |
| R3 主体唯一、形态可降级 | 混合组件按主体能力归层；其无 LLM 子集可作为 L1 意图或只读工具暴露，但归属不变 | 11 易经、23 自进化、33 REA、35 认知、48 涌现 |
| R4 编排 ≠ 生成 | 图执行 / 节点调度 / 重试 / 聚合 → 确定性（可归 L1）；只有「规划/反思/裁决的理由生成」才是 L2 | DreamOS C 层 GraphExecutor 属机制，Reflector 用 LLM 的部分属 L2 |
| R5 一次 LLM 调用即 L2 | 只要某路径**必须**经过生成式 LLM 才能完成，该路径归 L2；L2 内部可再拆「LLM 必需 / LLM 可选」 | 52 提案、32 辩论、34 主动训练 |

### 3.3 层级声明规范（registry schema 强制字段）

每个 shell 必须声明三件事，缺一不可（registry v1.2-mcp 新增字段）：

```yaml
shells:
  - id: l1.intent.mcp
    layer: L1                       # L0 | L1 | L2（新增枚举）
    capability_domain: intent       # 层级内能力域
    exposure: readonly-observe     # in-process-only | readonly-observe | control | not-exposed
    source_modules: ["3.1-FRONTEND", "34"]   # 能力来源模块，便于溯源
    plugin_ready: false             # 是否可作为 Cordis/DSH 插件封装对象
    llm_dependency: none           # none | optional | required
```

**字段约束**：

| 组合 | 合法性 | 理由 |
|---|---|---|
| L1 + control | ✅ | L1 编排内部写（forward_signal） |
| L2 + control | ✅ | L2 触发写（需 H5 三件套） |
| L2 + in-process-only | ❌ | L2 必须对外暴露 token 计量与异步接口 |
| exposure=in-process-only + plugin_ready=true | ❌ | 插件化即跨进程，违反 H8 |
| L2 + write tool 且无 mandate | ❌ | 违反 H5 |

---

## 4. Registry Schema v1.2-mcp 增量（最小改动）

### 4.1 `shells[]` 新增字段（全部可选，向后兼容）

```yaml
shells:
  - id: <shell_id>
    # ... 既有字段不动（transport, port, domain, read_write, status, envelope_version ...）
    layer: L0 | L1 | L2              # 新增：层级归属（枚举）
    capability_domain: string         # 新增：层级内能力域（intent/trading/strategy/ops/dreamos/dsh/train/emergence/debate ...）
    exposure: enum                    # 新增：exposure mode
    source_modules: [string]          # 新增：能力来源模块编号
    plugin_ready: boolean             # 新增：是否可插件化
    llm_dependency: enum              # 新增：none | optional | required
```

### 4.2 `enums` 增补

```yaml
enums:
  # ... 既有枚举不动
  layer: [L0, L1, L2]
  exposure: [in-process-only, readonly-observe, control, not-exposed]
  capability_domain:
    L0: [data, rea, cognition, semantic-39, eval, store-admin, trade-exec]
    L1: [intent, trading, strategy, ops]
    L2: [debate, dreamos, dsh, train, emergence]
  llm_dependency: [none, optional, required]
  layer_quota:                        # 新增：分层配额，替代单一 max_total_tools
    L0: 60
    L1: 30
    L2: 30
    total: 120
```

### 4.3 校验器增量（`validate_mcp_registry.py` 新增规则）

| 规则 | 校验 | 错误码 |
|---|---|---|
| V1 | 所有 shell 必须声明 `layer` | E-LAYER-MISSING |
| V2 | `layer` 值在枚举内 | E-LAYER-INVALID |
| V3 | 各层工具数 ≤ `layer_quota[layer]` | E-QUOTA-EXCEEDED |
| V4 | 总量 ≤ `layer_quota.total` | E-TOTAL-EXCEEDED |
| V5 | `exposure=in-process-only` 时 `plugin_ready` 必须 false | E-PLUGIN-CONFLICT |
| V6 | L2 shell 含 `read_write=write` 工具时必须声明 `requires_mandate=true` | E-MANDATE-MISSING |
| V7 | 层级命名 `l[012].*.mcp` 与 `layer` 一致（`agent.debate.mcp` 是唯一例外，DEC-03 别名期内） | E-NAME-LAYER-MISMATCH |

---

## 5. 层级架构收敛（模块归属）

### 5.1 L1 三子层

```
L1-A 意图执行层（对外第一跳，in-process，零 token）
  意图注册表(10 意图：data_query/data_insight/contradiction_inference/macro_snapshot/...）
  + 路由器 + 意图执行器 + 案例沉淀(l1_case_store)
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

### 5.2 L2 五子层

```
L2-K 内核编排（DreamOS · 新 SACG）
  S 认知驱动规划入口 / A OKR 节点验收 / C 执行驱动 / G 压缩沉淀
  横切：NodeRegistry / Evolution / Budget / Adapters
        ↓
L2-E 执行编排（DSH Router/Worker）
  常驻 Router + Worker 角色池（≤10 工具/角色）+ Ticket/Mandate + 会话可续
  实现载体：34-core
        ↓
L2-G 生成式能力层
  34 训练 / 48 涌现(D1/D2/D3) / 32 对抗辩论 / 30 E2E / 3-EVOLUTION
        ↓
L2-P 协议接入层
  46 DSH Harness / 52 LobeHub / 53 Cordis / 24 图压缩
        ↓
L2-A 应用与前端
  3.1 主前端 / 6 交易中台
```

### 5.3 暴露矩阵（谁能调谁）

| 调用方 ↓ / 被调方 → | L0 壳 | L1 壳 | L2 壳 | in-process |
|---|---|---|---|---|
| 外部宿主 | ✅ 按 role | ✅ 按 role（默认只读） | ✅ 按 role | ❌ |
| L2 编排（DreamOS/DSH） | ✅ 按 role | ✅ **只读 9 工具** | ✅ 自身 | ✅（L0 port） |
| L1 内部编排 | ✅ | ✅（含写） | ❌ | ✅ |
| L2 Worker | ✅ 按 role | ✅ 只读 9 工具 | ❌（不自调） | ❌ |

**不可逆红线**：L2 → L1 写 = 禁止；L1 热路径 → MCP = 禁止；实盘 → MCP = 禁止。

---

## 6. 注册清单与预算

### 6.1 P0（本轮）

| 壳 | layer | exposure | 工具 | 数量 | 前置 |
|---|---|---|---|---|---|
| `l1.trading.mcp`（已有壳，补 registry v1.2 字段） | L1 | readonly-observe | 现有 10 | 0 新增 | 无 |
| `l2.debate.mcp`（由 `agent.debate.mcp` 重命名，保留别名 1 迭代） | L2 | control | `start_debate / get_debate_result / debate_health` | 0 新增 | 无 |
| `l1.intent.mcp`（新建） | L1 | readonly-observe | `list_intents / classify_intent / execute_intent` | +3 | 3.1-FRONTEND `l1-intent-registry.ts` 暴露 HTTP 或 in-process 适配 |

**P0 后总量**：57 + 3 = 60（远低于原 80），因 DEC-04 同时提额到 120。

### 6.2 P1

| 壳 | layer | exposure | 工具（草案） | 数量 | 前置 |
|---|---|---|---|---|---|
| `l1.strategy.mcp` | L1 | readonly-observe | `list_strategies / get_strategy_version / get_approval_state / list_signal_triggers` | +4 | 25-28 端口只读暴露 |
| `l2.dreamos.mcp` | L2 | control | `submit_run / poll_run / get_result / get_intent / get_budget` | +5 | DreamOS API 适配 + 异步 job store |

**P1 后总量**：60 + 9 = 69 / 120。

### 6.3 P2（暂定，不承诺本轮落地）

| 壳 | layer | exposure | 工具（草案） | 数量 | 前置 |
|---|---|---|---|---|---|
| `l1.ops.mcp` | L1 | readonly-observe | `list_alerts / get_health / get_bus_state` | +3 | 15/36 只读暴露 |
| `l2.train.mcp` | L2 | control | `get_training_status / list_runs / trigger_training`(Mandate) | +3 | 34 + 45 门禁 |
| `l2.emergence.mcp` | L2 | readonly-observe | `get_emergence_metrics / list_experiments / get_experiment_report` | +3 | 48 度量接口 |

**P2 后总量**：69 + 9 = 78 / 120。

### 6.4 预算测算

| 层 | 配额 | P0 后 | P1 后 | P2 后 | 预留 |
|---|---|---|---|---|---|
| L0 | 60 | 57 | 57 | 57 | 3 |
| L1 | 30 | 13（10+3） | 17（+4） | 23（+6） | 7 |
| L2 | 30 | 3 | 8（+5） | 14（+6） | 16 |
| **合计** | **120** | **73** | **82** | **94** | **26** |

### 6.5 角色矩阵（新增，均 ≤10 工具）

| 角色 | 层 | 壳 | 工具（≤10） | 用途 |
|---|---|---|---|---|
| `l1_observer` | L1 | l1.intent + l1.trading | `list_intents, classify_intent, execute_intent, get_signal_state, get_constraint_state, get_cycle_state, get_strategic_extension` | 外部只读观察 L1（Trae/Claude Code） |
| `l1_ops` | L1 | l1.strategy + l1.trading | 策略 4 + 交易只读 5 | 运维与策略审计 |
| `l2_planner` | L2 | l2.dreamos | `submit_run, poll_run, get_result, get_intent, get_budget` | L2 规划编排 |
| `l2_researcher` | L2 | l2.debate + l0.cognition | debate 3 + recall/unified_search | 研究与辩论（L2 可跨层取 L0） |
| `l2_trainer` | L2 | l2.train（P2） | `get_training_status, list_runs, trigger_training`(Mandate) | 训练运维（写受限） |

---

## 7. 实施路线

### 7.1 Phase 0 — Registry Schema v1.2-mcp（评审后首个工作）

1. 改 [mcp_capabilities.yaml](../registry/mcp_capabilities.yaml)：补所有存量壳的 `layer/exposure/source_modules`；`enums` 增 layer/exposure/llm_dependency/capability_domain/layer_quota。
2. 改 [validate_mcp_registry.py](../registry/scripts/validate_mcp_registry.py)：新增 V1-V7 校验规则。
3. 跑 validator：存量壳全部通过 v1.2 校验。
4. 同步 [mcp_profiles.json](../registry/mcp_profiles.json) / [agent_cards.json](../registry/agent_cards.json)：按新 schema 投影。
5. `mcpctl verify` 漂移检查 → 零漂移。

### 7.2 Phase 1 — P0 注册

| 子任务 | 产出 |
|---|---|
| `l1.trading.mcp` 补 registry v1.2 字段 | `layer: L1, exposure: readonly-observe, source_modules: [11, 40, 42, 43, 50]` |
| `l2.debate.mcp` 重命名（+别名） | registry 增 `l2.debate.mcp`；`agent.debate.mcp` 保留一迭代 alias |
| `l1.intent.mcp` 新建 | `mcp_shells/l1_intent/server.py`（stdio，壳内三段）；契约测试 3 个 |
| 网关升级 | `l0_gateway --layer` 参数 + 角色投影适配 |
| 角色注册 | `worker_roles` 增 `l1_observer / l2_planner`（P0 级简化版） |
| 49 SPEC §3.8 修正 | 「设计态」→「已落地」 |

### 7.3 Phase 2 — P1 注册

| 子任务 | 产出 |
|---|---|
| `l1.strategy.mcp` 新建 | 4 只读工具 |
| `l2.dreamos.mcp` 新建 | 5 工具（submit/poll/get_result/get_intent/get_budget）；异步 job store 适配 |
| 角色补全 | `l1_ops / l2_planner` 完整版 |

### 7.4 Phase 3 — P2 + 插件化准备

1. `l1.ops.mcp / l2.train.mcp / l2.emergence.mcp` 三壳注册。
2. 能力卡升级：`mcpctl cards` 输出增 `layer/exposure/llm_dependency/source_modules/plugin_ready` 字段。
3. 53 域插件白名单补 `mcp_shell_required: true` 字段（插件必须经壳，不得直连业务）。
4. Cordis 插件封装：**仅消费侧 + 已有壳的能力卡映射**，不写新插件代码（DEC-06）。

---

## 8. 风险册

| # | 风险 | 触发条件 | 缓解 | 责任域 |
|---|---|---|---|---|
| R-1 | 工具面膨胀推高上下文成本 | 每层都建壳，外部宿主加载全量工具 | 强制走角色网关（≤10/角色）；禁止宿主直连全量壳 | 47 |
| R-2 | 双事实源 | 壳内重新实现业务逻辑 | H3 硬约束：壳零业务逻辑；`validate_mcp_registry.py` 漂移门禁 | 47 |
| R-3 | L2 越权写 L1 | 未来新增 forward_signal 类工具进 L2 角色 | V6 校验 + 网关启动校验（`requires_mandate=true` 拒绝）+ H4 | 47 |
| R-4 | 层级命名迁移破坏已有配置 | `agent.debate.mcp` 改名 | DEC-03：保留别名 1 迭代 + `mcpctl` 迁移提示 | 47 |
| R-5 | 插件化绕过壳 | 直接写 Cordis 插件调业务 | P2 阶段 53 白名单加 `mcp_shell_required: true` | 53 |
| R-6 | 文档漂移 | 49 SPEC 与实现不一致 | Phase 1 同步修正；漂移门禁纳入评审 checklist | 49 / 47 |
| R-7 | 分层配额超限 | L1/L2 新增壳过多 | V3/V4 校验 + 评审前 budget 复核 | 47 |
| R-8 | L2 无 token 计量导致无法审计 | L2 壳未实现 H6 | P0 壳实现 H6 信封字段 + 校验器加字段存在性检查 | 47 |

---

## 9. 评审 Checklist（评审者对照）

| # | 维度 | 检查项 | 证据 |
|---|---|---|---|
| C-1 | 定位一致性 | L1-P/L2-P 定位与 L0-P（SPEC-L0-MCP-PACKAGING v0.3 §1）是否延伸而非冲突 | §1 定位表 |
| C-2 | 硬约束完整性 | H1-H8 是否覆盖 SSoT 已有约束（H1/H2/H3 继承、H4-H8 新增） | §1.1 |
| C-3 | 判据边界 | L1/L2 判据（§3.1）与 SPEC-v1.3-L0L1L2-architecture.md §1 是否完全一致；灰区规则（§3.2）是否消除了所有已知拉扯 | §3 |
| C-4 | registry schema | v1.2-mcp 增量（§4）是否向后兼容存量壳；校验器 V1-V7 是否可实现 | §4 |
| C-5 | 注册清单 | P0/P1 壳的 tool count 是否不超分层配额；工具语义是否可审计 | §6 |
| C-6 | 风险覆盖 | 风险册 §8 是否覆盖 R-1~R-8；缓解是否可执行 | §8 |
| C-7 | 插件化衔接 | DEC-06/H8 是否与 53 域 plugin_whitelist.yaml 硬约束对齐 | §0 DEC-06 / §1.1 H8 |
| C-8 | 实盘红线 | H2（实盘永不 MCP）是否未被任何注册清单违反 | §6 |
| C-9 | L1 热路径 | H1（L1 热路径 in-process）是否未被任何注册清单违反 | §6 |
| C-10 | 评审前决策 | DEC-01~DEC-06 是否全部需要用户最终签字；如推翻是否已准备替代方案 | §0 |

---

## 10. 评审记录

> **评审状态**: ✅ 已批准（2026-11-13，zhangjiangtao 全过，无推翻项）

| 日期 | 评审人 | 结论 | 要点 | 决议 |
|---|---|---|---|---|
| 2026-11-13 | zhangjiangtao | ✅ 通过，无推翻项 | DEC-01 拆四域 / DEC-02 L2 首批两壳 / DEC-03 命名迁移+别名 / DEC-04 提额 120 分层 60/30/30 / DEC-05 复用 l0_gateway --layer / DEC-06 插件化仅标记，全部认可；Checklist C-1~C-10 无硬冲突 | 按 §7 Phase 0→1 执行 |

---

## 11. 维护

- v0.1 评审通过后冻结；registry v1.2-mcp 与 Phase 0 执行顺序绑定。
- 与 SSoT 冲突时，以 `SYSTEM_ARCHITECTURE_OVERVIEW.md` v4.2 + `49-交易框架协议/SPEC.md` v0.14.2 为准。
- 模块归属变更时，必须同步更新本 SPEC §5.1/§5.2 + `3+3架构模块映射.md`。
- registry schema 变更时，必须先升版本号（v1.3-mcp / v2.0）并附变更日志。
