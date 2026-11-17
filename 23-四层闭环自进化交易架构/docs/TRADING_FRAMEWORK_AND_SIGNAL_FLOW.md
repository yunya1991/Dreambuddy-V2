# 23 交易框架与信号流（SSoT）

> **版本**: v1.0 | **创建日期**: 2026-11-17 | **状态**: Active
> **定位**: 23 域交易主链唯一事实源（SSoT），覆盖分层框架、三类信号、开/平仓数据流、关联键与产物。
> **边界**: 本文描述“交易怎么做、信号怎么传”；基因三层准入见 [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md)，接口签名见 [API_SPEC.md](./API_SPEC.md)，逐节点代码映射见 [ENGINEERING_INDEX.md §4](./ENGINEERING_INDEX.md#4-核心流程索引n0n15--e0e6)。
> **监控口径**: 直接引用 [15-监控告警系统/TECHNICAL_DESIGN.md §13](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md#13-分类监控模型与-23-交易链路逐节点监控v27)，本文不复制指标与告警定义。

---

## 1. 分层交易框架

23 的结构是「四层纵向 + 双链路横向 + 执行权内收」。

### 1.1 四层纵向

| 层 | 回答的问题 | 核心实现 | 关键输出 |
|---|---|---|---|
| L1 状态空间 | 当前阻力结构如何 | `core/resistance_vector.py` | `R_up/R_down/R_smooth/R_flow/R_reflexivity/quality_score` |
| Level0 路径代价 | 哪个方向阻力最小 | `core/level0_path_cost.py` | `d_star`、`level0_confidence`、`level0_costs` |
| 路径发现 | 有哪些路径、哪条最优 | `core/path_discovery_service.py`、`engines/engine_router.py` | `paths[]`、`path_scores`、`optimal_path`、`path` |
| L2 策略基因 | 哪类策略适配当前状态 | `core/strategy_gene.py`、`weights.py` | `l2_top_combo`、ESS |
| L3 Shadow-RL | 该动作的历史期望如何 | `core/shadow_rl.py`、`shadow_rl_trainer.py` | 影子样本、策略权重 |
| L4 Bellman | 当前状态的长期价值 | `core/bellman_tracker.py` | `l4_v` |

### 1.2 双链路横向

| 链路 | 作用 | 实现 | 输出 |
|---|---|---|---|
| 矛盾论链路 | 识别当前主要矛盾 | `core/contradiction_identifier.py`（生产主矛盾）；`engines/primary_contradiction_detector.py`（事件 4 类矛盾，默认关） | `primary_contradiction{dimension,direction,strength,timeframe}` |
| 矛盾 Transformer 交叉验证 | 过去维度 × 现在维度互相校验 | `core/cross_validation_gate.py` + Granger/Attention 适配器 | `cross_validation{confidence_mult,shift_signal,divergence_count,degraded_mode,quality_change,...}` |

约束：

1. 交叉验证只调制路径评分、开仓阈值与 NeuralSDE head 权重，不替代 `d_star`，也不进入 `position_mult` 乘数链；门禁异常按 FAIL-OPEN 处理并记录降级状态。
2. 门禁实例挂在 `EvolutionPipeline` 上跨周期复用，`divergence_count / SPRT / 冷却期` 才能累积并触达 `persistence_threshold`（质变判定）；禁止按周期重建实例，否则质变永不触发。
3. 矛盾链路对 L1 阻力场的调制使用上一轮 `primary_contradiction`（1 根 K 线延迟）；当轮仅作用于路径评分、HJB、成对支配与弹性约束。
4. `strength` 语义是"多空对立度"：单边共识时趋于 0，低于调制门槛（0.01）即不产生任何调制，属预期行为而非链路故障。
5. head 权重的落点是 `_last_head_multipliers` → `DeepReasoningEngine.reason(head_multipliers=)` → `NeuralSDE.forecast`，在**下一轮**路径生成时生效（跨轮），而不是当轮。
6. 输入口径统一为 `market_data["close"]`；外部驱动传入的 `closes` / `kline_close` 在 `run_symbol` 与 `_select_optimal_path` 入口一次性归一，否则 L1 阻力维度回退 0.5 且 G_dim 恒为 None。
7. G 侧供给状态写入 `cross_validation.g_dim_status` ∈ `{ok, short_history, no_significant_granger, no_price_series, switch_off, error}`，并附 `g_min_p`；`no_significant_granger` 属统计降级，不是链路故障。实测：1H 序列几乎不显著，1D 且 ≥200 根才稳定给出 G_dim。

### 1.3 执行权内收

| 环节 | 归属 | 说明 |
|---|---|---|
| 开仓闸门/定容/SL/TP | 23 `execution/entry_loop.py` | 11 侧只保留薄 adapter |
| 平仓决策/减仓/清理 | 23 `execution/exit_loop.py` + `engines/exit_engine/` | 独立于开仓链 |
| 下单网关 | 22 `TradeExecutionGateway` | v1.2 契约校验（观察期 alert-only） |
| 风控与交易所 | 13 `PreTradeGate` + OKX | 最终成交 |
| 落账与反馈 | 22 账本 + 23 `TradeSettlementBridge` | 成交/平仓落 22 `PositionLedger`；23 消费执行结果进入反思/ESS/Bellman |

---

## 2. 三类信号

### 2.1 A 类：推理信号（N1–N9）

| 字段 | 含义 | 产生节点 |
|---|---|---|
| `r_vector` | 5 维阻力 + 质量分 | N2 |
| `primary_contradiction` | 主矛盾维度/方向/强度 | N5 |
| `cross_validation` | 交叉验证置信度乘数、位移、分歧、降级 | N6 |
| `statistical_validation` | `validated/best_score/score_gap/low_conviction` | N7 |
| `elastic_result` | 弹性约束结果 | 路径发现 |
| `d_star` / `action` | Level0 方向与最终动作 | N8 |
| `ri` / `tier` / `position_mult` | 信号强度、仓位分层、仓位乘数 | N1/N8 |

推理段由 `trace_id` 贯穿；`action=WAIT` 时记录 `reason_category ∈ {low_ri, d_star_wait, direction_conflict, unknown}`。

### 2.2 B 类：执行信号（N10–N14，FinalDecisionSignal v1.2）

权威契约：[final_decision_signal.v1.2.json](../../49-交易框架协议/contracts/final_decision_signal.v1.2.json)。

顶层必需字段：

```text
signal_id, source, symbol, direction, confidence, expires_at,
decision_id, action, pos_side, sz, sl_px, tp_px, reason, tier
```

`payload` 必需 12 字段：

```text
action, position_tier, position_mult, d_star, ri, l4_v, regime,
primary_contradiction, contradiction_shift, elastic_result,
cross_validation, path
```

当前实现额外写入（允许扩展）：

```text
payload.trace_id, payload.chain_id, payload.upstream_decision_id,
payload.coin, payload.sl_pct, payload.tp_pct
```

`action` 枚举：`open, close, reduce, stop_loss, take_profit, long, short, light_long, light_short, WAIT`。

### 2.3 C 类：执行反馈（N15 / E5–E6）

| 字段 | 含义 | 落点 |
|---|---|---|
| `executed` / `reason_code` | 网关是否执行、失败原因 | 22 返回、N14 事件 |
| outbox 状态 | `pending/submitting/submitted/filled/failed` | `execution/outbox.py` SQLite |
| `order_id` / `fill_id` | 交易所订单与成交 | 22/16 回报 |
| `pnl` / `filled_sz` / `avg_px` | 平仓与成交结果 | `TradeSettlementBridge` |
| L3/L4 反馈 | 样本、reward、`l4_v` | `shadow_rl`、`bellman_tracker` |

---

## 3. 开仓数据流（N0–N15）

```text
[18/19/OKX/情绪/资金轮动/子系统]
        │  market_data + regime + ripples + ess
        ▼
N0 数据就绪
        ▼
N1 K线事件 + trace_id
        ├─ N2 L1 阻力向量
        ├─ N3 高阶因子调制
        ├─ N4 路径发现
        ├─ N5 主矛盾识别
        ├─ N6 矛盾 Transformer 交叉验证
        ├─ N7 统计验证
        └─ N8 d* / action / ri / tier
        ▼
N9 L3/L4 记录
        ▼
N10 首个信号（v1.2，decision_id #1 = chain_id）
        ▼
N11 23 闸门 → 定容 → SL/TP
        ▼
N12 最终信号（decision_id #2 + upstream_decision_id）
        ▼
N13 outbox 幂等状态机
        ▼
N14 22 网关 → 13 风控 → OKX
        ▼
N15 成交回报 → 落账 → 反思/ESS/Bellman
```

关键规则：

1. N8 为 WAIT 时不进入 N10，链路以 `N8 status=skip` 结束。
2. N10 与 N12 各生成一次 `decision_id`；复盘以 `chain_id`（N10 id）+ `upstream_decision_id` 串联。
3. N13 重复信号以 outbox `decision_id` 幂等去重，不重复下单。
4. N14 契约违规在观察期只告警，不阻断订单。

---

## 4. 平仓数据流（E0–E6）

```text
E0 持仓同步（交易所 ↔ 账本）
        ▼
E1 离场决策（SL/TP/时间/反向信号/RL）
        ▼
E2 RL 覆盖
        ▼
E3 影子记录
        ▼
E4 平仓信号（action=close/reduce，sz 必须可确定）
        ▼
E5 提交/风控/成交（共用 N13/N14 通道）
        ▼
E6 部分减仓刷新 / 全平清理 / 落账
```

关键规则：

1. `sz <= 0` 视为 `SIZE_UNKNOWN`，必须记录并告警，不能静默跳过。
2. 平仓失败代表风险未释放，优先级高于开仓拦截。
3. 全平后必须清理持仓级状态，避免同币二次开仓继承旧 peak/partial。

---

## 5. 反馈闭环

```text
成交/平仓 → 交易索引库 → ReflectionScanner（内省 RI）
          → ReflectionEngine（CS 一致性 + ESS 奖惩）
          → L3 Shadow-RL 样本
          → L4 Bellman V(s)
          → 下一轮阻力向量/路径/仓位
```

---

## 6. 关联键与产物

### 6.1 id 串联（复盘唯一路径）

```text
trace_id（N1 生成，贯穿推理段）
  └─ chain_id = N10 首个 decision_id
       └─ upstream_decision_id（写入 N12 payload）
            └─ decision_id（N12/N14，22 幂等主键）
                 └─ order_id / fill_id（N15 成交回报）
```

平仓链独立生成 `trace_id` 与 `decision_id`，从 E4 起复用 N13/N14/N15。

### 6.2 落盘产物

| 产物 | 路径 | 写入方 | 用途 |
|---|---|---|---|
| 执行审计 | `23/runtime/execution_decisions.jsonl` | `EvolutionSignalDispatcher` | 信号与提交结果 |
| 链路事件 | `23/runtime/chain_events-YYYYMMDD.jsonl` | `execution/chain_events.py` | N/E 节点时间线、WAIT 归因、复盘 join |
| 发件箱 | outbox SQLite | `execution/outbox.py` | 幂等、重试、卡单检测 |
| 入场快照 | `runtime/pre_trade_snapshot` | `KlineEventHandler` | 复盘当时的市场状态 |
| 网关审计 | `22-执行引擎中心/audit/gateway.jsonl` | 22 网关 | 下单请求/结果 |
| 契约违规 | `22-执行引擎中心/audit/contract_violations.jsonl` | 22 网关 | v1.2 违规样本 |

### 6.3 监控

节点指标、告警级别、SLO 与复盘查询统一以 [15 TD §13](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md#13-分类监控模型与-23-交易链路逐节点监控v27) 为准；本文只维护链路语义，不重复维护监控规则。

---

## 7. 变更规则

1. 新增/修改信号字段：先改 `49-交易框架协议/contracts/final_decision_signal.v1.2.json`，再同步本文与 API_SPEC。
2. 新增链路节点：在本文登记语义，在 ENGINEERING_INDEX §4 登记代码入口与字段，在 15 TD §13 登记监控项。
3. 任何影响 `d_star/action/ri/tier/payload` 的变更，必须同时更新 churn 测试与链路事件断言。
