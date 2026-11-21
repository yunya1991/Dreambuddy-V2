---
name: dream-trading-chain-monitoring
description: '交易链路监控方案设计与复用模板：A/B 分类监控（A 类逐节点可复盘、B 类结果导向可粗糙）、chain_event 事件模型、trace_id/chain_id 串联、指标与告警治理、五步接入法、反模式清单、多交易系统复用映射。Invoke when 设计或补齐交易系统监控、复盘断链、治理告警噪声、把 23 链路监控模式复用到其他交易系统时。'
version: 1.0.0
created: 2026-11-18
updated: 2026-11-18
status: active
category: observability
role: template
triggers:
- 监控方案
- 链路监控
- 逐节点监控
- 交易链路可观测
- 链路事件
- chain_event
- 静默断链
- WAIT 归因
- 复盘链路
- 告警噪声
- 复用监控模式
- 新系统接监控
- 监控埋点
depends_on:
- 15-监控告警系统
- 23-四层闭环自进化交易架构
- dream-module-post-dev-verify-workflow
- dream-bugfix-workflow
provides:
- ab-classification
- chain-node-table
- chain-event-schema
- id-linkage
- metric-and-alert-conventions
- onboarding-five-steps
- reuse-mapping
- anti-patterns
---

# Dream Trading Chain Monitoring — 交易链路监控方案设计 SKILL

> **来源（SSoT）**：
> - `15-监控告警系统/docs/TECHNICAL_DESIGN.md` §10–§13（指标、告警、锚定索引）
> - `23-四层闭环自进化交易架构/docs/TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md`（节点语义、数据流、关联键）
>
> **定位**：设计/接入模板，不重复实现运行时。运行时组件仍是 15 的 Prometheus 栈 + exporter，以及各交易系统的 `chain_events` 旁路。
> **一句话**：**A 类沿信号逐节点监控并可按 chain_id 复盘；B 类只做结果导向、允许粗糙；观测永不改变交易判定。**

---

## 一、适用边界

**适用**

1. 新交易系统上线前设计监控（先有节点表，再有代码）。
2. 存量系统补监控：能下单但说不清「为什么没交易」。
3. 告警噪声治理：告警多但无法定位断点。
4. 把 23 已验证的链路模式复制到 50/17/29 等系统。

**不适用**

- 监控栈本身的部署（用 `15-监控告警系统/deploy/` 的 compose）。
- 纯主机/端口/容器监控（用 node_exporter + blackbox）。
- 非交易模块的逐字段契约监控（B 类粗糙即可）。

**本 SKILL 产物**

节点表 → 埋点 → 导出指标 → 告警规则 + runbook → 复盘查询 → 验收证据。

---

## 二、五条不变量（违反任一条即视为方案不合格）

| # | 不变量 | 说明 |
|---|---|---|
| I1 | **A/B 分类** | 按「是否参与真实下单 / 可否归因到单笔 / 是否需事后复盘」分两类，投入不同 |
| I2 | **指标 + 事件双轨** | 指标回答「节点是否健康」，事件回答「这一笔为什么发生/没发生」；缺一不可 |
| I3 | **一条链一个 id** | `trace_id → chain_id → upstream_decision_id → decision_id → order_id/fill_id`，复盘只走这条路 |
| I4 | **观测 FAIL-OPEN** | 埋点、导出、写事件全部只读旁路，任何异常不得影响交易主链 |
| I5 | **告警可治理** | P0–P3 分级 + runbook 强绑定 + 单出口 + 观察期 `alert_only` + 降噪门槛 |

---

## 三、A/B 分类判据

| 类别 | 范围 | 监控方式 | 强度 | 目标 |
|---|---|---|---|---|
| **A 类：交易链路** | 推理 → 信号构造 → 闸门 → outbox → 网关 → 风控 → 交易所 → 回报/反馈 | 沿信号传递**逐节点**采集，每节点一条 stage event，按 `chain_id` 汇总 | 高：状态、字段语义、时延、完整性 | 一笔交易可完整复盘 |
| **B 类：其他模块** | 训练、基因治理、数据生产、非交易子系统、存量策略 | **结果导向**：进程存活 + 心跳/产物新鲜度 + 核心计数 | 低：每模块 ≤3 个指标，允许抽样 | 确认在工作、结果基本正确 |

**为什么 A 类必须逐节点**：交易故障多为**静默断链**——某节点返回空/默认值，上下游都不报错，最终只表现为「不交易」或「仓位不对」。只看成交数与 PnL，无法区分「策略主动 WAIT」和「链路断了」。

**B 类四个可验收条件**

1. 进程/单元存活（systemd active 或心跳 < TTL）；
2. 最近一次成功产物存在且新鲜（文件 mtime / 表最新分区）；
3. 核心计数不突变（产出量、错误量在历史分位内）；
4. 下游可消费（每日一次端到端 spot check，不逐笔校验）。

**边界判定表**

| 场景 | 归类 | 处理 |
|---|---|---|
| 信号传递的每个决策/执行节点 | A | stage event + 节点指标 + 告警 |
| 基因库、反思、权重学习、影子训练 | B | 每日产物 + 样本量 + 晋升/淘汰计数 |
| 数据生产（A 类系统的入口） | B（但作为 A 的 N0 门禁） | 只监控新鲜度/空值率/行数增量 |
| 存量老策略 | B | 存活 + 产物新鲜度，不参与 P0 路由 |

**成本纪律**：A 类单系统建议 ≤25 个节点、每节点 3–5 条时间序列（总量 ≤120）；禁止把 payload 全字段展开成 label（高基数）。高频中间量只保留最新值 + 分位摘要。

---

## 四、五步接入法（SOP）

### Step 1 — 画链路并产出节点表

先定义节点，再写代码。每个节点必须能回答六件事：

| 字段 | 要求 |
|---|---|
| 节点号 | `N0…Nn`（开仓链）、`E0…En`（平仓链）；编号由该系统的 SSoT 定义 |
| 环节名 | 一句话说明该节点做什么决策 |
| 代码入口 | 精确到 `文件:函数`，不写模块名了事 |
| 输入/输出 | 只列关键字段（决定资金动作的），不列全部 |
| 关联键 | 该节点能拿到 `trace_id` / `chain_id` / `decision_id` 中的哪些 |
| 静默失败模式 | 空值、默认值、吞异常、跳过——这是监控要抓的东西 |

节点表模板见 §6.1。**节点表的 owner 是交易系统 SSoT，指标与告警的 owner 是监控系统**，两侧不互相复制定义。

### Step 2 — 埋点 `chain_event`

在每个节点出口写一条事件，只读旁路。参考实现：`23-四层闭环自进化交易架构/dreambuddy_evolution/execution/chain_events.py`。

```python
def emit_stage(stage, node, symbol, status="pass", *, data=None,
               chain_id=None, decision_id=None, upstream_decision_id=None,
               trace_id=None, duration_ms=None, ts=None) -> None:
    """写入一条链路事件；失败静默，不影响调用方。"""
```

埋点纪律：

1. 全部 `try/except` 吞异常，只 `logger.debug`；
2. 不写密钥、不写完整订单原始报文；
3. `status` 取值统一：`enter / pass / blocked / failed / skip`；
4. 每个节点都要能写入 `symbol + trace_id`（多 symbol 并发时防止张冠李戴）；
5. 主动不交易（WAIT）也要写 `status=skip` 并带 `reason_category`，否则无法区分「策略不交易」与「系统坏了」；
6. 按 UTC 日轮转：`runtime/chain_events-YYYYMMDD.jsonl`。

事件模型见 §6.2。

### Step 3 — 导出指标

只读扫描事件流与周边产物，暴露 `/metrics`。参考实现：`15-监控告警系统/exporter/business_metrics_exporter.py`。

必备指标族：

| 指标族 | 关键指标 | 回答的问题 |
|---|---|---|
| 节点计数 | `chain_stage_total{stage,status}` | 每个节点进入/通过/拦截/失败/跳过多少 |
| 链路完整性 | `chain_completion_ratio`、`chain_missing_stage_total{stage}` | 有多少链走完、断在哪 |
| WAIT 归因 | `wait_vs_broken_ratio`、`chain_broken_total` | 不交易是策略选择还是链路故障 |
| 执行健康 | `outbox_stuck`、`signal_reject_ratio`、`decision_fill_join_ratio` | 信号到成交是否顺畅 |
| 风险未释放 | `exit_size_unknown_total`、`exit_close_failed_total` | 平仓是否失败（优先级高于开仓拦截） |
| 进程/账本 | `{system}_active`、`ledger_*`、`sltp_*` | 进程是否活、账本是否漂移 |

命名与标签约定见 §6.3。

### Step 4 — 规则、路由与 runbook

告警分级固定为：

| 级别 | 语义 | 路由 | 响应 |
|---|---|---|---|
| P0 | 资金/合规/失控，或平仓链停机、监控自身死亡 | 风控群 + @all | 5min 确认，10min 未确认重发 → 电话 |
| P1 | 链路断点/决策受损 | 交易台 | 30min |
| P2 | 降级/漂移/趋势 | 交易台 | 当日 |
| P3 | 摘要/周报 | 管理看板 | 周会 |

规则纪律：

1. 无 runbook 的规则不得进 P0/P1；
2. 单出口：Alertmanager → feishu-receiver，禁止业务代码各自发告警；
3. 观察期（新系统上线前 2 周）全部 `alert_only`；
4. 自动动作只允许「冻结/收紧」，且复用既有 kill-switch，不新增下单权；
5. 同一 `chain_id` 的同一 stage 10min 内只告警一次。

降噪门槛（缺一不可）：

- 语义类指标必须带 `samples_recent > 0` 守卫，避免「无信号 → ratio=0 → 误报」；
- 所有规则 `for:` ≥5min；
- P3 只进 Grafana，不进飞书；
- 指纹去重 30min 冷却，未恢复每 6h 复报，恢复发「已恢复」；
- P0 永不禁默。

### Step 5 — 复盘与验收

**四步定位法**

1. **告警 → 节点**：按告警名在锚定表定位节点，先看节点不先看日志。
2. **指标 → 范围**：`symbol` 级异常查该 symbol 的 `chain_id`；全局异常查进程 active 与数据新鲜度。
3. **证据 → join**：`chain_id` 串事件流 + 审计；`decision_id` 串网关审计 + 账本成交表。
4. **归属 → 边界**：执行/落账异常查执行引擎（22）；决策/定容异常查策略系统；都不是再查数据层与风控。

**验收门禁**见 §8。

---

## 五、23 参考实现（标准答案）

| 层 | 文件 | 职责 |
|---|---|---|
| 节点语义 SSoT | `23/docs/TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md` | 分层框架、三类信号、N0–N15 / E0–E6 数据流、关联键 |
| 事件埋点 | `23/dreambuddy_evolution/execution/chain_events.py` | `new_trace_id()` / `emit_stage()`，FAIL-OPEN，UTC 日轮转 |
| 执行链 | `23/dreambuddy_evolution/execution/{entry_loop,exit_loop,outbox,decision_signal}.py` | N10–N15 / E4–E6 埋点 |
| 导出器 | `15/exporter/business_metrics_exporter.py` | `signal_metrics / outbox_metrics / chain_metrics / contract_metrics / semantic_metrics / execution_metrics / artifact_metrics / cell_metrics` |
| 告警规则 | `15/deploy/prometheus/rules/dreambuddy-monitoring.yml` | `signals / execution / trading / platform` 分组 |
| 判定参数 | `15/config/monitoring.yaml` | 产物 TTL、任务间隔、信号阈值、执行阈值 |
| 域注册表 | `15/config/domains.yaml` | 3×3 监控格、owner、成熟度、探针 |
| 运行证据 | `23/runtime/chain_events-*.jsonl`、`execution_decisions.jsonl`、outbox SQLite | 复盘 join 的唯一来源 |

**23 已落地的关键修复（可作为复用时的检查项）**：推理段 `trace_id`、pc/cv 返回值透传、`regime/ri/l4_v` 参数退化、WAIT 归因落盘、双 `decision_id` 三键并存、平仓链 E0–E6 事件、`SIZE_UNKNOWN` 显式告警。

---

## 六、复制模板

### 6.1 节点表模板

```markdown
| 节点 | 环节 | 代码入口 | 输入（关键） | 输出（关键） | 关联键 | 静默失败模式 |
|---|---|---|---|---|---|---|
| N0 | 数据就绪 | module/loader.py:load | symbol/kline | market_data{} | (symbol, ts) | 空 K 线 → 下游默认值 |
| N1 | 引擎调度 | module/engine.py:on_event | 事件 | action/ri | trace_id | 异常被吞 → 周期静默跳过 |
| ... | | | | | | |
| N10 | 信号构造 | module/signal.py:build | 上游上下文 | signal_id/decision_id | chain_id 起点 | 构造异常被吞 → 信号丢失 |
| N12 | 最终信号 | module/dispatch.py:dispatch | 上游 payload | decision_id/upstream_decision_id | decision_id | 二次构造丢字段 |
| N13 | 发件箱 | module/outbox.py | 最终信号 | pending/submitting/filled/failed | decision_id | 卡在 submitting |
| N14 | 网关/风控 | gateway.submit | 最终信号 | executed/reason_code | decision_id | 规则 0 条仍放行 |
| N15 | 回报落账 | settlement bridge | 成交 | pnl/filled_sz | order_id/fill_id | 成交不回带 decision_id |
```

### 6.2 事件模型 `chain_event.v1`

```json
{
  "schema": "chain_event.v1",
  "source": "23-evolution",
  "chain_id": "23-evolution|BTC-USDT-SWAP|open|20261117T121837",
  "trace_id": "evt-20261117T121837-BTC",
  "stage": "N12",
  "node": "entry_loop.dispatch",
  "symbol": "BTC-USDT-SWAP",
  "ts": "2026-11-17T12:18:37.412+00:00",
  "status": "pass",
  "duration_ms": 3,
  "decision_id": "evo23-...-final",
  "upstream_decision_id": "evo23-...-first",
  "data": {
    "action": "open",
    "tier": "standard",
    "notional_usdt": 120.0,
    "confidence": 0.62,
    "d_star": "long",
    "ri": 0.62,
    "regime": "TREND_UP",
    "pc": {"dimension": "structure", "direction": "long", "strength": 0.66},
    "cv": {"confidence_mult": 0.8, "signal": true, "degraded_mode": "partial"}
  }
}
```

> `source` 为复用新增字段（向后兼容，缺省视为 `23-evolution`）；导出器按 `source` 分组，避免多系统共用指标名时串台。

### 6.3 指标命名与标签

- 前缀：`dreambuddy_`；
- 业务指标统一带 `chain / layer / cell / module`（对接 OpenTelemetry 时映射 `service.namespace / service.name`）；
- 链路指标额外带 `source`（系统标识）与 `stage`（节点号）；
- 禁止把 `decision_id / chain_id` 作为 label（高基数）；它们只进事件与日志；
- 高基数字段（payload 全量）只保留「最新值」指标，不做逐笔时序。

### 6.4 告警规则模板

```yaml
- alert: <System>ChainBroken
  expr: dreambuddy_chain_missing_stage_total{source="<system>"} > 0
  for: 30m
  labels: {severity: P1, channel: alert}
  annotations:
    summary: "<system> 链路存在缺失节点"
    runbook_url: "<系统 TD 锚点>"

- alert: <System>ExitFailed
  expr: increase(dreambuddy_exit_close_failed_total{source="<system>"}[10m]) > 0
  for: 10m
  labels: {severity: P0, channel: alert}
  annotations:
    summary: "平仓/减仓执行失败，风险持续暴露"

- alert: <System>ProcessDown
  expr: dreambuddy_<system>_active == 0
  for: 5m
  labels: {severity: P1, channel: alert}
```

### 6.5 看板四面板（最小集）

1. **链路漏斗**：各 stage 计数（进入 → 通过 → 提交 → 成交）；
2. **断链与 WAIT**：`chain_missing_stage_total` 时间线 + `wait_vs_broken_ratio`；
3. **执行健康**：outbox 状态堆叠、拒绝率、join 率、平仓失败；
4. **语义快照**：最新主矛盾/交叉验证/regime（每 symbol 一格，不画时序）。

### 6.6 验收清单

- [ ] 节点表每行都有 `文件:函数`；
- [ ] 一笔开仓、一笔平仓可按 `chain_id` 还原完整时间线；
- [ ] WAIT 可归因 ≥95%，其余计入 `chain_broken`；
- [ ] 平仓失败有 P0 且带 `symbol/reason`；
- [ ] 所有语义告警带 `samples_recent` 守卫；
- [ ] 每条 P0/P1 规则有 runbook；
- [ ] 观察期结束前误报率 <5%。

---

## 七、其他交易系统复用映射

### 7.1 复用前置改造（做一次，全系统受益）

当前 `chain_events.py` 与导出器只服务 23。复用到第二个系统前需完成三项轻量改造：

| # | 改造 | 位置 | 兼容性 |
|---|---|---|---|
| R1 | 事件增加 `source` 字段，`emit_stage(source=...)` | 各系统 `chain_events` 模块 | 缺省 `23-evolution`，旧事件不受影响 |
| R2 | 导出器按注册表扫描多个 `runtime/` 目录 | `business_metrics_exporter.chain_metrics()` | 新增 `source` label |
| R3 | 告警规则加 `source` 选择器 | `dreambuddy-monitoring.yml` | 现有规则补 `source="23-evolution"` 即等价 |

同时把新系统登记到 `15/config/domains.yaml`（cell / owner / maturity / probes），新增覆盖只改注册表 + 加探针，不改告警代码。

### 7.2 50-NN 主矛盾评估器（首选试点）

**为什么先选 50**：已有 shadow + live 双轨决策与 22 执行入口，链路与 23 同构度最高；但 `runtime/decisions.jsonl` 只有结果，无法回答「这条决策怎么来的」。

**现有可复用产物**

| 用途 | 现有资产 |
|---|---|
| 证据入口 | `42/runtime/bus_state.json`、`50/runtime/bus_state.json` |
| 决策账本 | `50/runtime/decisions.jsonl`、`50/runtime/audit/decisions.jsonl` |
| live 通道 | `50/runtime/live/outbox.jsonl`、`50/runtime/live/latest.json` |
| 执行与回报 | `22` `x1_live_executor.py`、`22/audit/x1_live_fills.jsonl` |
| 归因 | `50/tools/live_attribution.py`（已按 `decision_id` join） |

**建议节点表（`source=50-nn`）**

| 节点 | 环节 | 代码入口 | 静默失败模式 |
|---|---|---|---|
| N0 | 42 证据就绪 | `42/signal_bus.py`、`bus_state.json` | 证据空 → 下游默认 |
| N1 | 触发/唤醒 | `core/trigger_flap.py` | 长期不触发，无计数 |
| N2 | 维度力量 | `core/dimension_forces.py` | 全零/NaN |
| N3 | 宏观力传导 | `core/macro_force.py` | 宏观缺失 → 降级不报 |
| N4 | 共振/路径合成 | `core/resonance_sensor.py`、`core/path_synthesis.py` | 路径为空 |
| N5 | 主矛盾 | `core/contradiction.py` | unknown |
| N6 | 反射弧/训练门禁 | `core/reflection_arcs.py`、`core/w6.py`、`core/training_gate.py` | 权重不更新 |
| N8 | 决策 | `core/decision.py` | 置信度退化 |
| N10 | shadow 落账 | `core/shadow_decision.py` → `decisions.jsonl` | 只落结果无上下文 |
| N11 | live 过滤 | `tools/run_live.py` | 过期证据静默丢弃 |
| N12 | live 出箱 | `live/outbox.jsonl`、`latest.json` | 状态不推进 |
| N13 | 22 执行 | `x1_live_executor.py` | 幂等/持仓守卫拦截无归因 |
| N14 | 风控/网关 | 13 `PreTradeGate`、22 网关 | 规则 0 条放行 |
| N15 | 成交归因 | `tools/live_attribution.py` | join 失败无告警 |

**已知必须先处理的两个坑**

1. `decisions.jsonl` 曾出现测试 symbol `BTC-FLAP-PAYLOAD` → 接入前加 symbol 白名单与 `ForbiddenSymbolOrder` 规则；
2. live `decision_id` 由证据批次 sha1 生成（幂等设计，正确），但缺少 `trace_id` → 需在证据入口生成并贯穿，否则无法回溯到当时的维度力量。

**接入顺序**：R1–R3 改造 → N0/N1/N8/N10 最小事件（先能复盘一条决策）→ N11–N15 执行段 → 语义指标 → 告警规则 → 观察期 2 周 `alert_only`。

### 7.3 其他系统分级

| 系统 | 复用级别 | 现有基础 | 需补 | 优先级 |
|---|---|---|---|---|
| 50-NN | **A 类** | 双轨决策 + 22 执行 + 归因脚本 | `source` 改造、trace_id、节点事件、语义指标 | P1 |
| 29 事件驱动 | **A 类（轻量）** | 事件→信号链路天然清晰 | 事件 ID 贯穿、执行段事件 | P2 |
| 17 v4-wave | A 类（轻量） | 独立引擎 + live 目录 | 埋点 4–6 个节点即可 | P2 |
| 12 三屏 / 14 V15 | **B 类** | 状态文件 + 既有 heartbeat adapter | 产物新鲜度、核心计数；不做逐节点 | P3 |

**判定原则**：有独立下单权且需要复盘 → A 类；只产出信号或已停用 → B 类。不要为了统一而给 B 类做逐节点埋点。

---

## 八、验收门禁（G1–G5）

| 门禁 | 判定 | 证据 |
|---|---|---|
| G1 节点表完整 | 每个节点有 `文件:函数` + 静默失败模式 | 节点表评审通过 |
| G2 链路可 join | 一笔开仓 + 一笔平仓可由 `chain_id` 还原 | `chain_events-*.jsonl` 时间线 |
| G3 WAIT 可解释 | `wait_vs_broken_ratio ≤ 0.05` | Prometheus 查询 |
| G4 告警可触发 | 停进程 / 伪造卡单 / 伪造 amount 未知，均能触发对应 P0/P1 | 演练记录 |
| G5 低噪声 | 观察期误报率 <5%，P0/P1 规则 100% 有 runbook | 观察期统计 |

**验证命令**

```bash
# 事件流是否在写
tail -n 20 23-四层闭环自进化交易架构/runtime/chain_events-$(date -u +%Y%m%d).jsonl

# 指标是否暴露
curl -s http://127.0.0.1:9101/metrics | grep -E 'chain_|exit_|outbox_|ledger_|sltp_'

# 规则语法
promtool check rules 15-监控告警系统/deploy/prometheus/rules/dreambuddy-monitoring.yml

# 链路测试
cd 23-四层闭环自进化交易架构 && python -m pytest tests/test_chain_events_and_signal_params.py -q
```

---

## 九、反模式（踩过的坑，复用前先对照）

| # | 反模式 | 症状 | 根因 | 正确做法 |
|---|---|---|---|---|
| 1 | **数据源消失但指标保留** | 某告警永久触发，实际无业务 | 上游已退役，规则仍在算旧文件 | 下线指标与规则（如 `universe.enabled=false`），或换数据源后再启用 |
| 2 | **用「最近一次写入」判停摆** | 稳定持仓时对账每分钟误报 | 对账无变化本就不写库 | 改用进程 `active` 判存活，写入频率只作观察 |
| 3 | **无样本算比率** | 无信号时 ratio=0 → 误报 | 分母为 0 | 所有语义规则加 `samples_recent > 0` 守卫 |
| 4 | **WAIT 不落盘** | 长期「不交易」，查不出原因 | 只在有信号时写审计 | WAIT 也写 `status=skip` + `reason_category` |
| 5 | **双 decision_id 只留一个** | 成交能查到，推理上下文丢失 | 两段各生成一次 id | `chain_id` + `upstream_decision_id` + 最终 `decision_id` 三键并存 |
| 6 | **平仓失败只记日志** | 仓位该平未平，无人知晓 | 平仓链未纳入告警 | `SIZE_UNKNOWN` / 平仓失败一律 P0 |
| 7 | **payload 全字段做 label** | Prometheus 内存暴涨、查询变慢 | 高基数 | 只保留 stage/status/symbol 等低基数标签 |
| 8 | **观测代码抛异常影响交易** | 日志满、偶发交易中断 | 埋点未隔离 | 全部 try/except + `logger.debug`，FAIL-OPEN |
| 9 | **两个告警引擎并存** | 同一故障重复通知 | Grafana 也配了告警 | Prometheus 唯一判定源，Grafana 只展示 |
| 10 | **给 B 类做逐节点** | 告警淹没 A 类 | 未分类 | B 类每模块 ≤3 个结果指标 |

---

## 十、维护与变更规则

1. **节点编号只认交易系统 SSoT**；监控侧只维护「节点 → 指标 → 告警 → 证据」映射，不复制节点定义。
2. 新增/改名节点：同时改 SSoT、锚定索引、节点指标表；三处不一致视为文档缺陷。
3. 新增信号字段：先改 `49-交易框架协议/contracts/` 契约，再改事件与导出器。
4. 任何影响 `action / d_star / ri / tier / payload` 的变更，必须补链路事件断言与 churn 测试。
5. 执行权归属变化（谁下单、谁落账、谁补挂 SL/TP）时，必须同步监控对象与告警路由，并下线旧指标。

---

## 十一、快速索引

| 需要什么 | 去哪看 |
|---|---|
| 23 节点语义与数据流 | `23/docs/TRADING_FRAMEWORK_AND_SIGNAL_FLOW.md` |
| A/B 分类与逐节点指标 | `15/docs/TECHNICAL_DESIGN.md` §13.1–§13.3 |
| 事件模型与链路汇总 | 同上 §13.4 |
| 执行链与公共执行监控 | 同上 §13.8 |
| 告警 ↔ 节点锚定索引 | 同上 §13.9 |
| 探针分层 / TTL / 告警治理 | 同上 §10.4–§10.6 |
| 3×3 注册表与成熟度 | 同上 §11.3 + `15/config/domains.yaml` |
| 事件埋点实现 | `23/dreambuddy_evolution/execution/chain_events.py` |
| 指标导出实现 | `15/exporter/business_metrics_exporter.py` |
| 告警规则 | `15/deploy/prometheus/rules/dreambuddy-monitoring.yml` |
