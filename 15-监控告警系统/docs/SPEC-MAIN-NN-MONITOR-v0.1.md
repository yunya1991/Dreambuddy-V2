# SPEC：主神经网络监控模块（main-nn）v0.1

> **状态**：**已并入 `TECHNICAL_DESIGN.md` §14（2026-11-26），仅存档，不再修改、不再 active**。节点定义只在 TD §14 维护。
> **日期**：2026-11-26
> **归属**：15-监控告警系统（监控子模块，`source="main-nn"`）
> **监控对象**：`48 → 40 → 43 →（49 契约）→ 42 → 50 → 22` 主神经网络闭环链
> **上游依据**：48 `SPEC-EMERGENCE-FULL-CHAIN-v1.0`、42 `ARCHITECTURE_OVERVIEW`、40/43/49/50 SPEC、22 `TECHNICAL_DESIGN`
> **监控机制依据**：本域 `TECHNICAL_DESIGN.md` §10–§13（探针分层 / TTL / 告警治理 / A-B 分类 / chain_event）

---

## §0 文档管理体系（先定文档，再定实现）

### 0.1 为什么单独立一份模块 SPEC

主神经网络链跨 6 个域，节点语义与产物散落在 40/42/43/49/50/22 各自文档里。若监控口径也分散到各域，必然出现「同一节点两套编号」「同一告警两处定义」。因此本模块采用**一份模块 SPEC 收敛定义、合并后归位 TD**的方式，不新建文档族。

### 0.2 文档地图（本模块只增一行索引）

| 文档 | 角色 | 是否新增 | Owner | 更新触发 |
|---|---|---|---|---|
| 本文件 `SPEC-MAIN-NN-MONITOR-v0.1.md` | 模块规格：节点表 M0–M14、事件模型、指标、告警、锚定索引的定义源 | 新增（唯一新增文档） | 监控侧 | 节点/指标/告警变更 |
| `TECHNICAL_DESIGN.md` §14 | 合并后的权威章节（并入后本文件归档） | 待合并 | 监控侧 | 同上 |
| `ENGINEERING_INDEX.md` | 文件清单：新增 `exporter` 函数、链事件模块 | 合并时追加 | 监控侧 | 代码文件增删 |
| `API_SPEC.md` | `/metrics` 已有接口，本期不新增接口 | **不改** | 监控侧 | 新增对外接口时 |
| `CHANGELOG.md` | 每阶段一行（P0–P3） | 落地时追加 | 监控侧 | 每次发版 |
| `config/monitoring.yaml` / `config/domains.yaml` | 配置事实源（TTL、阈值、注册表） | 落地时追加 key | 监控侧 | 参数调整 |
| `49/contracts/` | 仅当 `SignalSchema`/`FinalDecisionSignal` 字段变更时先改契约 | **本期不改** | 契约侧 | 契约升版 |
| 40/43/50/22 各域文档 | 业务语义与代码入口（只引用，不复制节点定义） | **不改** | 各域 | 各域自身变更 |

### 0.3 生命周期与合并规则（硬约束）

1. 本文件为 **draft**；评审通过后 48h 内并入 `TECHNICAL_DESIGN.md §14`，文件头部标注「已并入 §14，仅存档」，**不允许两份文档同时保持 active**。
2. 节点编号 `M0–M14` 只在 §14 维护；本文件归档后不再修改。
3. 新增/改名节点必须**同改三处**：TD §14 节点表、`config/domains.yaml` 探针、告警锚定索引；三处不一致视为文档缺陷。
4. 告警规则与指标只登记在 TD + 告警 YAML，不在各业务域文档里复写。

### 0.4 单一事实源（SSoT）分工

| 事实 | SSoT |
|---|---|
| 节点编号、节点语义、静默失败模式 | 本 SPEC → 并入 TD §14 |
| 监控通用机制（A/B 分类、P0–P3、去重、TTL、探针分层） | TD §10–§13 |
| 信号与决策契约字段 | `49-交易框架协议/contracts/` |
| 周期/战略/矛盾业务语义 | 40/43/50 各自 SPEC |
| 执行、账本、SL/TP 归属 | 22 TD §7/§8 |
| 监控格与 owner | `15/config/domains.yaml` |

### 0.5 变更检查清单

- [ ] 节点表是否每行都有 `文件:函数` 与静默失败模式
- [ ] 事件字段是否与 `chain_event.v1` 一致（含 `source="main-nn"`）
- [ ] 指标是否带 `chain/layer/cell/module/source/stage` 低基数标签
- [ ] 新增 P0/P1 规则是否有 runbook 锚点
- [ ] 是否复用了既有规则而未重复造规则
- [ ] `domains.yaml` 与锚定索引是否同步

### 0.6 禁止事项

1. 禁止在 40/43/42/50/22 任一域再建第二份「主神经网络节点表」。
2. 禁止把 `payload` 全字段展开成 label（高基数）。
3. 禁止新增第二个告警引擎（Prometheus 唯一判定源，Grafana 只展示）。
4. 禁止给 B 类模块做逐节点埋点。
5. 禁止监控代码写交易状态或影响主链（FAIL-OPEN）。

---

## §1 定位与边界

### 1.1 定位

本模块是 15 域监控体系的**交易链核心模块之一**，与既有「23 推理信号监控」（TD §12/§13）并列，负责回答主神经网络链的三个问题：

1. **是否在跑**：各层产物是否新鲜、进程/定时任务是否成功；
2. **断在哪里**：一笔决策/一笔成交在哪一节点丢失；
3. **为什么是这个结论**：当时的周期判定、战略总分、主矛盾、约束包络是什么。

### 1.2 A/B 分类

| 类别 | 范围 | 监控方式 | 强度 |
|---|---|---|---|
| **A 类：交易链路** | M0–M14：40 产出 → 43 承接 → 42 总线 → 50 决策 → live 出箱 → 22 执行与回报 | 逐节点 stage event + 节点指标 + `chain_id` 汇总 | 高：四态、字段语义、时延、完整性 |
| **B 类：支撑模块** | 48 训练/度量/基因、40 P5/P6 训练门禁、42 ParamGovernor/FeedbackLoop、43 影子门禁解除 | 存活 + 产物新鲜度 + 核心计数（每模块 ≤3 指标） | 低：允许抽样 |

### 1.3 不在范围

- 13 内部风控规则细节、交易所侧撮合与 OCO 内部状态（只监控结果）；
- 18/19/20/21 数据地基（作为 M0 的上游门禁，只用新鲜度/空值率）；
- 23 自进化链（已有独立监控，见 TD §12/§13）。

### 1.4 与既有监控的关系（防重复）

本模块**优先复用** TD §13 已有的 A 类框架、`chain_event.v1` 事件模型、P0–P3 分级与降噪门槛；仅新增主神经网络特有的节点、语义指标与 3 条缺口告警。复用映射见 §5.1。

---

## §2 链路全景与节点表（M0–M14）

```
[M0 上游供给] → [M1 数据就绪] → [M2 周期判定] → [M3 战略承接] → [M4 战略发布]
      → [M5 总线归一化] → [M6 证据就绪] → [M7 触发] → [M8 路径合成] → [M9 维度力量]
      → [M10 主矛盾/支配] → [M11 约束+决策] → [M12 live 过滤/出箱] → [M13 执行复核]
      → [M14 下单/回报/归因]
```

编号前缀 `M` 表示主神经网络链，避免与 23 的 `N0–N15 / E0–E6` 混淆；指标统一带 `source="main-nn"`。

| 节点 | 环节 | 代码入口 | 输入（关键） | 输出（关键） | 关联键 | 静默失败模式 |
|---|---|---|---|---|---|---|
| M0 | 上游供给与训练门禁 | `40/scripts/refresh_48_feedback.py`、`consume_48_feedback.py`、`factor_contradiction_priors.py` | 48 训练事件/度量 | `40_feedback.json`、`nn_feedback_consumption.json`、`factor_contradiction_priors.json` | `batch_ts` | 网关不刷新 → 40 消费旧反馈；`join_coverage=0` |
| M1 | 宏观/资金数据就绪 | `40/scripts/p1_real_cycle.py`、`p3_fund_flow.py`、`p3_smart_money.py` | FRED、ccxt、yfinance | 周期原始序列、资金流分量 | `(source, as_of)` | 数据源断供 → `stale=true` 静默降级 |
| M2 | 周期与板块判定 | `40/scripts/p1_ma200_anchor.py`、`p2_asset_rotation.py`、`p2_divergence.py`、`p3_sector_transmission.py` | 宏观序列 + 价格 | `cycle_state.json`、`asset_rotation.json`、`sector_transmission.json` | `(symbol, as_of)` | 置信度掉档、背离不计数、`data_coverage=partial` |
| M3 | 战略承接 | `43/strategic_extension/cycle_state_adapter.py`、`five_domain_feature_computer.py`、`sentiment_channel.py` | 40 产出、18 F&G | 五维分数、`merrill_phase`、`regime` | `(asset_class, as_of)` | `CYCLE_STATE_BRIDGE=0` 或超 7d → 全维 fallback 中性 50 |
| M4 | 四档决策与发布 | `43/strategic_extension/signal_publisher.py` | 五维总分、war_state | `runtime/strategic_extension_signal.json` | `signal_id` | 信号过期未刷新、`shadow` 恒 true、`war_state` 恒 FREEZE |
| M5 | 总线归一化 | `42/signal_bus.py`、`42/adapters/*.py` | 各子系统产物 | `runtime/bus_state.json` | `signal_id` | F4 全丢弃、单源缺失、别名双写 |
| M6 | 证据就绪 | `50/adapters/bus_reader.py`、`prior_reader.py`、`constraint_loader.py` | 总线快照、40 先验、40/43 约束 | evidence 列表、约束包络 | `trace_id`（**起点**） | 可用源 <6、TTL 过期、先验陈旧 |
| M7 | 触发/防抖 | `50/core/trigger_flap.py` | evidence、时间窗 | 是否进入裁决 | `trace_id` | 长期不触发且无计数 |
| M8 | 路径合成 | `50/core/path_synthesis.py`、`factor_priors_overlay` | evidence | `paths[]` | `trace_id` | path=0、confidence=0 |
| M9 | 维度力量/宏观传导 | `50/core/dimension_forces.py`、`macro_force.py`、`resonance_sensor.py` | paths、40 宏观 | 维度排序、力量值 | `trace_id` | 全 neutral/NaN、降级不上报 |
| M10 | 主矛盾与支配 | `50/core/contradiction.py`、`dominance.py` | 维度力量 | `primary_contradiction`、dominance 矩阵 | `trace_id` | unknown、仅单一维度可解释 |
| M11 | 约束钳位与决策 | `50/core/constraints.py`、`core/decision.py`、`shadow_decision.py` | paths、约束 | `FinalDecisionSignal` → `runtime/decisions.jsonl` | `decision_id`（**chain_id 起点**） | 约束缺字段 → 过度放开；mode 错标 |
| M12 | live 过滤与出箱 | `50/tools/run_live.py` | shadow 决策 | `runtime/live/outbox.jsonl`、`latest.json` | `decision_id` | 过期证据静默丢、只产 `MULTI` 级 |
| M13 | 执行复核 | `22/x1_live_executor.py`、`22/risk_bridge.py` | outbox 决策 | execute / skip（含归因） | `decision_id` | skip 无归因、`size_zero`、幂等误吞 |
| M14 | 下单与回报归因 | `22/executors/live_order_bridge.py`、`position_ledger.py`、`sltp_reconcile.py`、`50/tools/live_attribution.py` | 执行决策 | `22/audit/x1_live_fills.jsonl`、`position_ledger.db`、归因行 | `order_id`/`fill_id` | 成交不回带 `decision_id`、SL/TP 缺失、join 失败 |

**成本纪律**：15 节点 × 4 条序列 ≈ 60 条，占 TD §13 预算（≤120）的一半以内；`chain_id / decision_id` 只进事件与日志，不做 label。

---

## §3 事件模型（chain_event.v1 扩展）

### 3.1 字段

在 TD §13.4 的 `chain_event.v1` 基础上新增 `source`、`mode`、`reason_category` 三个可选字段（向后兼容）：

```json
{
  "schema": "chain_event.v1",
  "source": "main-nn",
  "chain_id": "main-nn|BTC-USDT-SWAP|open|20261126T121837",
  "trace_id": "mnn-20261126T121837-BTC",
  "stage": "M11",
  "node": "decision.make_decision",
  "symbol": "BTC-USDT-SWAP",
  "ts": "2026-11-26T12:18:37.412+00:00",
  "status": "pass",
  "mode": "shadow",
  "reason_category": "",
  "duration_ms": 4,
  "decision_id": "50-nn|a1b2c3d4e5f60718",
  "upstream_decision_id": "",
  "data": {
    "cycle_state": "plateau",
    "cycle_confidence": "medium",
    "strategic_total": 53,
    "war_state": "ACTIVE",
    "bus_sources_ok": 7,
    "evidence_sources": 6,
    "path_count": 9,
    "dimension_order": ["D1", "D4", "D3"],
    "primary_contradiction": {"dimension": "D1", "direction": "long", "strength": 0.58},
    "constraint_id": "mec-20261126-01",
    "position_pct": 0.35,
    "execution_rights": "paper"
  }
}
```

### 3.2 埋点纪律

1. 全部 `try/except` 吞异常，仅 `logger.debug`，FAIL-OPEN；
2. `status ∈ {enter, pass, blocked, failed, skip}`；
3. **WAIT 必写** `status=skip` + `reason_category ∈ {wait_no_path, wait_low_confidence, wait_conflict, wait_constraint_freeze, wait_trigger_not_fired, wait_evidence_missing}`，否则计入 `chain_broken`；
4. 每个节点必须带 `symbol + trace_id`（多标的并发防张冠李戴）；M0–M5 无 symbol 时用 `symbol="MACRO"`；
5. 按 UTC 日轮转：`runtime/chain_events-YYYYMMDD.jsonl`，热存 30 天、冷存 1 年；
6. 不写密钥、不写完整订单原始报文。

### 3.3 id 串联（复盘唯一路径）

```
trace_id（M6 生成，贯穿 M6→M11）
  └─ chain_id = M11 首个 decision_id
       └─ decision_id（M11/M12/M13，22 幂等主键）
            └─ order_id / fill_id（M14 回报）
```

**必须补的缺口**：50 的 live `decision_id` 由证据批次 sha1 生成（幂等设计正确），但当前无 `trace_id`。M6 生成 `trace_id` 并写入 `payload.trace_id`，`run_live.py` 透传，否则复盘只能看到结果、看不到当时的维度力量。

---

## §4 指标族

### 4.1 通用链路指标（复用 TD §13.4 定义）

| 指标 | 标签 | 说明 |
|---|---|---|
| `dreambuddy_chain_stage_total` | `source,stage,status` | 各节点四态计数 |
| `dreambuddy_chain_completion_ratio` | `source,segment` | 完整走完 M5→M13 的比例 |
| `dreambuddy_chain_missing_stage_total` | `source,stage` | 应出现但缺失的节点 |
| `dreambuddy_chain_latency_seconds` | `source,from,to` | 重点 M11→M13 |
| `dreambuddy_chain_status_total` | `source,final_status` | `opened/rejected/expired/blocked/wait/failed` |
| `dreambuddy_wait_vs_broken_ratio` | `source` | 主动 WAIT / 断链导致 WAIT |
| `dreambuddy_chain_replay_join_ratio` | `source` | 可按 chain_id 还原完整时间线的成交占比 |

### 4.2 主神经网络语义快照（gauge，只保最新值）

| 指标 | 来源 | 用途 |
|---|---|---|
| `dreambuddy_main_nn_cycle_confidence{level}` | `cycle_state.json` | 周期判定是否掉档 |
| `dreambuddy_main_nn_cycle_stale` | `cycle_state.json` | 是否 stale/unavailable |
| `dreambuddy_main_nn_strategic_total{asset_class}` | 43 信号 | 五维总分是否恒 51 |
| `dreambuddy_main_nn_strategic_war_state{asset_class,state}` | 43 信号 | FREEZE 是否长期不解冻 |
| `dreambuddy_main_nn_strategic_shadow` | 43 信号 | 影子门禁是否长期 true |
| `dreambuddy_main_nn_bus_sources_ok` | `42/runtime/bus_state.json` | 可用源数（应 ≥6） |
| `dreambuddy_main_nn_bus_reject_ratio` | 同上 | 过滤器拒绝率 |
| `dreambuddy_main_nn_evidence_sources_ok` | 50 bus_reader | 参与裁决的源数 |
| `dreambuddy_main_nn_path_count` | 50 path_synthesis | 路径是否为 0 |
| `dreambuddy_main_nn_dimension_neutral_ratio` | 50 dimension_forces | 是否全 neutral |
| `dreambuddy_main_nn_contradiction_present` | 50 contradiction | 主矛盾是否为 unknown |
| `dreambuddy_main_nn_constraint_degraded` | 50 constraint_loader | 约束字段缺失数 |
| `dreambuddy_main_nn_decision_confidence{symbol}` | decisions.jsonl | 置信度是否退化 |
| `dreambuddy_main_nn_decision_mode{mode}` | decisions.jsonl | `shadow/live` 比例 |
| `dreambuddy_main_nn_execution_rights_ok` | decisions + 47 注册表 | 单出口是否守约 |
| `dreambuddy_main_nn_x1_skip_total{reason}` | `22/runtime/x1_live_processed.json` | 跳过归因分布 |
| `dreambuddy_main_nn_sltp_coverage{scope}` | `22/audit/sltp_reconcile.jsonl` | 50 持仓保护覆盖率 |
| `dreambuddy_main_nn_decision_fill_join_ratio` | 22 账本 + 归因 | 决策→成交 join |

### 4.3 命名与标签纪律

- 前缀 `dreambuddy_`；所有业务指标带 `chain=trade, layer=L1, cell=L1.trade, module=main-nn`；
- 链路指标额外 `source="main-nn"`、`stage="M0"…"M14"`；
- 禁止 `chain_id / decision_id / signal_id` 做 label；
- 高频中间量（paths、维度力量）只保留最新值与分位摘要。

---

## §5 告警规则与治理

### 5.1 复用映射（先复用，再新增）

| 关注点 | 既有规则（TD §13 + 告警 YAML） | 本模块动作 |
|---|---|---|
| 40 日更失败/迟到 | `Daily40PipelineFailedOrLate`、`JobFailed` | 复用，补 `main-nn` 任务打点 |
| 42 总线停更 | `BusStale` | 复用 |
| 42 源缺失 | `BusSourceMissing`、`BusCriticalSourceMissing` | 复用，30 号源→`11-bcrm-tactical` 按 critical 处理 |
| 43 发布停更 | `Publish43Stale` | 复用 |
| 50 shadow 停更 | `Shadow50Stale`、`DecisionSilence` | 复用 |
| live 链未运行 | `NnLiveChainNoRun` | 复用 |
| 产物陈旧/缺失 | `ArtifactStale`、`ArtifactMissing` | 复用，新增 `artifacts.main_nn` 键 |
| 断链/完成率低 | `ChainBroken`、`ChainCompletionLow`、`ChainWaitBroken` | 复用，规则加 `source="main-nn"` |
| 置信度退化 | `ConfidenceDegenerate` | 复用，补 `symbol` 覆盖 |
| 决策→成交 join 低 | `DecisionFillJoinLow` | 复用 |
| 执行权/契约 | `RiskGateEmpty`、`GatewayContractViolation`、`ForbiddenSymbolOrder` | 复用 |
| SL/TP 缺失/失败 | `SltpReconcileFailed`、`SltpReconcileStale` | 复用，加 `scope="50-nn"` 过滤 |
| 降级事件洪水 | `DegradedEventFlood` | 复用 |

### 5.2 新增规则（仅 3 条真正缺口）

| 告警 | 级别 | 表达式（示意） | 语义 | Runbook 锚点 |
|---|---|---|---|---|
| `MainNNStrategicFallbackDominant` | P1 | `dreambuddy_main_nn_strategic_total == 51` 连续 2 个发布周期，且 `strategic_shadow == 1`、bridge 开关为 1 | 43 承接失效（40 产物过期/字段不匹配），五维退化为全 fallback | TD §14 M3/M4 |
| `MainNNConstraintDegraded` | P2 | `increase(dreambuddy_main_nn_constraint_degraded[1h]) > 0` | 40/43 约束字段缺失，50 按更保守默认钳位，需核对字段契约 | TD §14 M6/M11 |
| `MainNNExecutionRightsMismatch` | P0 | 存在 `mode="live"` 且 (`execution_rights != "live:50-bypass"` 或 `mandate_id=""`) | 单出口契约被破坏，立即停 live | TD §14 M11/M13 |

> `MainNNExecutionRightsMismatch` 属于资金/合规类，P0；`alert_only` 观察期同样只通知，不自动动作。

### 5.3 治理纪律（继承 TD §10.6 / §13.3）

1. 无 runbook 的规则不得进 P0/P1；
2. 单出口：Alertmanager → feishu-receiver；
3. 所有语义规则带 `samples_recent > 0` 守卫；
4. `for:` ≥ 5min；P3 只进 Grafana，不进飞书；
5. 同一 `chain_id` 同一 stage 10min 内只告警一次；
6. 上线前 2 周全部 `alert_only`；
7. 自动动作只允许「冻结/收紧」，复用既有 kill-switch。

### 5.4 保持低噪声的关键判断

- **不做**「裸奔式」规则：例如 `strategic_total == 51` 本身不是异常（分位型评分均值就在 50 附近，历史上 721 次恒 51 是 bug），必须叠加「bridge 开启 + 40 产物新鲜 + shadow 未解除」三条件；
- **不做**「无样本算比率」：`wait_vs_broken_ratio` 在 `chain_stage_total{stage="M6"} == 0` 时不评估；
- **不做**对 B 类（48 训练、42 参数治理）逐节点告警，只保留产物陈旧与任务失败。

---

## §6 看板与 SLO

### 6.1 看板四面板（对齐 TD §13 最小集）

1. **链路漏斗**：M5→M14 各 stage 计数（进入→通过→提交→成交）；
2. **断链与 WAIT**：`chain_missing_stage_total` 时间线 + `wait_vs_broken_ratio` + WAIT 归因堆叠；
3. **执行健康**：outbox 状态、`x1_skip_total{reason}`、join 率、SL/TP 覆盖率；
4. **语义快照**：每标的一格（cycle 相位/战略总分/war_state/主矛盾/约束），不画时序。

### 6.2 SLO

| SLO | 目标 | 判定 |
|---|---|---|
| 链路完整率（M5→M13，24h） | ≥99% | `chain_completion_ratio` |
| WAIT 可归因率 | ≥95%，`wait_vs_broken_ratio ≤ 0.05` | 事件 `reason_category` |
| 决策→成交 join | ≥95% | `decision_fill_join_ratio` |
| 有持仓 SL/TP 覆盖 | 100% | `sltp_coverage` |
| 单出口违约 | 0 | `execution_rights_ok == 0` 计数 |
| 告警误报率（观察期） | <5% | 观察期统计 |

---

## §7 复盘四步法与锚定索引

### 7.1 四步定位

1. **告警 → 节点**：按告警名查 §7.2 表，先看节点指标，不先看日志。
2. **指标 → 范围**：`symbol` 级异常查该 symbol 的 `chain_id`；全局异常查 `main_nn_active` 与产物新鲜度。
3. **证据 → join**：`chain_id` 串 `chain_events-*.jsonl` + `decisions.jsonl`；`decision_id` 串 `outbox.jsonl` + `22/audit/x1_live_fills.jsonl` + `position_ledger.db`。
4. **归属 → 边界**：执行/账本异常查 22；决策/约束异常查 50；战略总分异常查 43；周期/资金异常查 40；都不是再查 18/48。

### 7.2 锚定索引（M0–M14）

| 节点 | 指标 | 告警 | 证据与首查 |
|---|---|---|---|
| M0 | `job_status{job="40_daily"}`、`artifact_age{name="40_feedback.json"}` | `Daily40PipelineFailedOrLate`、`ArtifactStale` | `40/nn_feedback_consumption.json`；`/tmp/40_daily_pipeline_cron.log` |
| M1 | `main_nn_cycle_stale`、数据源错误计数 | `ArtifactStale` | `40/cycle_state.json` 的 `data_coverage/stale` |
| M2 | `cycle_confidence`、`artifact_age{cycle_state}` | `ArtifactStale`、`ChainBroken`(source=main-nn) | `40/cycle_state.json`、`sector_transmission.json` |
| M3 | `strategic_total`、`constraint_degraded` | `MainNNStrategicFallbackDominant`(P1) | `43/runtime/strategic_extension_signal.json` 的 `semantic_view` |
| M4 | `strategic_war_state`、`strategic_shadow` | `Publish43Stale`、`MainNNStrategicFallbackDominant` | `43/runtime/shadow_gate_state.json`；`journalctl -u dreambuddy-43-strategic-publish` |
| M5 | `bus_sources_ok`、`bus_reject_ratio` | `BusStale`、`BusSourceMissing`、`BusCriticalSourceMissing` | `42/runtime/bus_state.json` |
| M6 | `evidence_sources_ok` | `ChainBroken`(source=main-nn)、`DegradedEventFlood` | `50/runtime/bus_state.json`；`stage=M6` 事件 |
| M7 | `chain_stage_total{stage="M7"}` | `DecisionSilence` | `stage=M7` 事件（`skip` 原因） |
| M8 | `path_count` | `ChainBroken` | `stage=M8` 的 `data.path_count` |
| M9 | `dimension_neutral_ratio` | 观察（Grafana） | `stage=M9` |
| M10 | `contradiction_present` | `ContradictionMissing` | `stage=M10` |
| M11 | `decision_confidence`、`decision_mode`、`constraint_degraded` | `ConfidenceDegenerate`、`MainNNConstraintDegraded`(P2)、`MainNNExecutionRightsMismatch`(P0) | `50/runtime/decisions.jsonl`；`stage=M11` |
| M12 | `artifact_age{outbox}`、outbox 状态 | `NnLiveChainNoRun`、`OutboxStuck` | `50/runtime/live/outbox.jsonl`、`latest.json` |
| M13 | `x1_skip_total{reason}` | `RiskGateEmpty`、`ForbiddenSymbolOrder` | `22/runtime/x1_live_processed.json`；`journalctl -u dreambuddy-nn-live-chain` |
| M14 | `sltp_coverage`、`decision_fill_join_ratio` | `SltpReconcileFailed`(scope=50-nn)、`DecisionFillJoinLow` | `22/audit/x1_live_fills.jsonl`、`sltp_reconcile.jsonl`、`position_ledger.db` |

---

## §8 配置与注册

### 8.1 `config/monitoring.yaml`（新增 key，字段名对齐现有结构）

```yaml
artifacts:
  main_nn:                      # 示意；实际字段以现有 artifacts 段 schema 为准
    - {name: cycle_state,        path: 40-周期神经网络系统/cycle_state.json, ttl_minutes: 1560}
    - {name: strategy_mapping,   path: 40-周期神经网络系统/strategy_mapping.json, ttl_minutes: 1560}
    - {name: strategic_signal,   path: 43-战略承接推演层/runtime/strategic_extension_signal.json, ttl_minutes: 90}
    - {name: bus_state_42,       path: 42-神经网络交易协调层/runtime/bus_state.json, ttl_minutes: 15}
    - {name: decisions_50,       path: 50-NN主矛盾评估器/runtime/decisions.jsonl, ttl_minutes: 1440}
    - {name: outbox_50,          path: 50-NN主矛盾评估器/runtime/live/outbox.jsonl, ttl_minutes: 15}

signals:
  main_nn:
    evidence_min_sources: 6
    decision_silence_minutes: 1440
    strategic_total_flat_minutes: 120

execution:
  main_nn:
    live_stale_minutes: 15
    sltp_coverage_min: 1.0
```

### 8.2 `config/domains.yaml`

在 `L1.trade` 中追加 `module: main-nn` 与探针，不新增 cell：

```yaml
  - id: L1.trade
    modules: [..., 40, 43, 42, 50, main-nn]
    probes:
      - main_nn_stage          # M0–M14 四态
      - main_nn_completion     # 链路完整率
      - main_nn_semantics      # 周期/战略/主矛盾快照
      - main_nn_execution      # outbox/执行/join/SLTP
```

### 8.3 导出器

在 `exporter/business_metrics_exporter.py` 新增 `main_nn_metrics()`（只读扫描 40/43/42/50/22 产物与事件流），注册进 `collect()`；复用 `_iter_jsonl_since`、`_read_json`、`_chain_event_age`。

### 8.4 任务打点

新增/补打点必须调用 `push_job.sh`：`40_daily`、`publish_43`、`live_50`、`bus_42`、`shadow_50` 已有；本模块新增 `main_nn_export` 心跳，避免「无数据 ≠ 无告警」。

---

## §9 实施路线与验收

| 阶段 | 内容 | 退出标准 |
|---|---|---|
| P0 基座（观测可见） | `source` 字段与 `trace_id`（M6 生成）；M5/M6/M11/M14 最小事件；`artifacts.main_nn`；`domains.yaml` 登记；导出器 `main_nn_metrics()` | 能复盘一笔 shadow 决策的 M5→M11 时间线 |
| P1 决策语义 | M3/M4/M7/M8/M9/M10 事件与语义指标；`MainNNStrategicFallbackDominant`、`MainNNConstraintDegraded` | 能回答「为什么 WAIT / 主矛盾是什么」 |
| P2 执行与资金安全 | M12/M13 事件；`x1_skip_total`；`sltp_coverage`；`MainNNExecutionRightsMismatch` | 一笔 live 决策可按 chain_id 还原到成交 |
| P3 看板与观察期 | 四面板看板；2 周 `alert_only`；复盘脚本 | 误报 <5%，SLO 达标 |

### 验收门禁（复用 TD G1–G5）

| 门禁 | 判定 | 证据 |
|---|---|---|
| G1 节点表完整 | 每行有 `文件:函数` + 静默失败模式 | §2 评审通过 |
| G2 链路可 join | 一笔开仓/一笔平仓可由 `chain_id` 还原 | `chain_events-*.jsonl` |
| G3 WAIT 可解释 | 归因率 ≥95%，`wait_vs_broken ≤0.05` | Prometheus 查询 |
| G4 告警可触发 | 停 43 发布 / 伪造约束缺失 / 伪造执行权不符，均能触发对应规则 | 演练记录 |
| G5 低噪声 | 观察期误报 <5%，P0/P1 全部有 runbook | 观察期统计 |

**验证命令（落地后）**

```bash
# 事件是否在写
tail -n 20 50-NN主矛盾评估器/runtime/chain_events-$(date -u +%Y%m%d).jsonl
# 指标是否暴露
curl -s http://127.0.0.1:9101/metrics | grep -E 'main_nn_|chain_stage_total'
# 规则语法
promtool check rules 15-监控告警系统/deploy/prometheus/rules/dreambuddy-monitoring.yml
```

---

## §10 反模式（本模块特有）

| # | 反模式 | 症状 | 正确做法 |
|---|---|---|---|
| 1 | 把 `strategic_total==51` 当异常 | 43 长期恒 51 是历史 bug，但分位型评分本就围绕 50 | 叠加 bridge 开关 + 新鲜度 + shadow 三条件 |
| 2 | 只看 `decisions.jsonl` | 能知道「决策了什么」，不知道「为什么」 | M6 起埋点，`trace_id` 贯穿 |
| 3 | 用产物 mtime 判 50 存活 | 50 是批处理，不跑不等于坏 | 用 `NnLiveChainNoRun` + job 打点 |
| 4 | 把 `MULTI` 级决策当归因 | 组合级 `symbol=MULTI` 无法按标的索引 | 用 per-symbol 决策与 `payload.granularity` |
| 5 | 对 48/40 训练做逐节点 | 告警淹没 A 类 | B 类 ≤3 指标 |
| 6 | 直接读 git 跟踪的 40 产物 | 部署 `git pull` 覆盖产物导致假 stale | 部署后重跑 40 日更；长期移出 git 索引 |
| 7 | 新老两条 live 链同时告警 | 23/50 双出口混淆 | 告警带 `source`，锚定表按源区分 |

---

## §11 变更记录

| 版本 | 日期 | 变更 |
|---|---|---|
| v0.1 | 2026-11-26 | 初稿：文档管理体系（§0）、M0–M14 节点表、chain_event 扩展、指标与告警复用映射、看板/SLO、锚定索引、配置与 P0–P3 路线；待评审后并入 TD §14 |
