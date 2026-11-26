# 23 交易框架与信号流（SSoT）

> **版本**: v1.2 | **创建日期**: 2026-11-17 | **更新日期**: 2026-11-18 | **状态**: Active
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
| 开仓闸门/定容/SL/TP | 23 `execution/entry_loop.py` | 11 侧不再参与 |
| 平仓决策/减仓/清理 | 23 `execution/exit_loop.py` + `engines/exit_engine/` | 独立于开仓链 |
| SL/TP 补挂、账本对账、幽灵仓清零 | 22 `sltp_reconcile.py` + `PositionLedger` | 公共执行兜底，各域共用（见 22 TD §7） |
| 下单网关 | 22 `TradeExecutionGateway` | v1.2 契约校验（观察期 alert-only）、幂等、审计 |
| 风控与交易所 | 13 `PreTradeGate` + OKX | 最终成交 |
| 落账与反馈 | 22 账本 + 23 `TradeSettlementBridge` | 成交/平仓落 22 `PositionLedger`；23 消费执行结果进入反思/ESS/Bellman |

**11 域边界**：11 的交易循环 `polling_trader` 已下线（`YIJING_23_ENABLED` 默认 0），
只保留 `yijing-data-server`(8765，前端趋势面板依赖) 与 BCRM/BDSM 非交易能力。
23 不 import 11 模块、不写 11 路径；BCRM 方向、BDSM 估值、BTC regime、方向态由
`adapters/indigenous_factors.py` 自产（开关 `EVOLUTION_INDIGENOUS_FACTORS`，默认 on），
43 战略层仍是 `war_state/five_scores/position_cap` 的优先事实源。

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
E0 持仓同步（交易所 → 22 账本 → 23 巡检集合；每轮 60s）
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
4. E0 每轮先执行 22 `reconcile_ledger()`（补缺/校正受管源数量/同步对账源均价/关闭陈旧行），
   再进行 23 巡检；交易所已无持仓的账本残留由 `close_ghost_position()` 清零，
   不得每轮重复告警。
5. E4 的 `sz` 解析顺序固定：交易所持仓（按 `pos_side` 精确匹配，兼容 `net`/单仓）→
   22 账本 `position_qty/qty/sz` → `position_usdt / 当前价` 名义回退；
   最终按合约 `lotSz` **向下对齐**，对齐后不足 1 手时升级为全平（避免 OKX 拒单）。
   解析结果必须落日志与失败归因（`symbol/reason`），不得静默跳过。


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
| 持仓账本 | `22-执行引擎中心/runtime/position_ledger.db` | 22 `PositionLedger` | 持仓/成交流水/冷却（唯一真相源） |
| SL/TP 补挂审计 | `22-执行引擎中心/audit/sltp_reconcile.jsonl` | 22 `sltp_reconcile` | 补挂/跳过/失败明细 |

### 6.3 监控

节点指标、告警级别、SLO 与复盘查询统一以 [15 TD §13](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md#13-分类监控模型与-23-交易链路逐节点监控v27) 为准；本文只维护链路语义，不重复维护监控规则。

**节点 → 指标 → 告警 → 证据**的一页锚定索引见
[15 TD §13.9](../../15-监控告警系统/docs/TECHNICAL_DESIGN.md#139-监控点--交易链路节点锚定索引v2112026-11-18)。
排查从该表进入：先按告警名定位 N/E 节点，再用 `chain_id`/`decision_id` join 23 事件流与 22 审计/账本；
本文不复制该映射，避免双份漂移。

### 6.4 部署与单一 owner

| 进程 | unit | 参数 | 日志 |
|---|---|---|---|
| 23 开仓 | `dreambuddy-entry23` | `--interval 300 --pool-mode dynamic --scan-top 8`，`EVOLUTION_ENTRY23_ENABLED=on` | `/home/luke/logs/yijing/entry23.log` |
| 23 平仓 | `dreambuddy-exit23` | `--interval 60` | `/home/luke/logs/yijing/exit23.log` |
| 11 数据服务 | `yijing-data-server` | 8765，保留 | 前端趋势面板依赖 |
| 11 交易循环 | `yijing-polling-trader` | **已停用并 disable** | 不再写交易 |

- 单一 owner：23 的持仓只由入口 `--tags`（账本 source）与 `--symbols` 补录决定，
  11 不再巡检或下单；`polling_trader` 内嵌的 23 调用由 `YIJING_23_ENABLED` 控制且默认 0。
- 首次接管存量仓：`exit_runner --reconcile-ledger --reconcile-source 22-reconciled`，
  之后每轮自动对账，无需重复回填。
- 服务契约见 `deploy/dreambuddy-entry23.service`、`deploy/dreambuddy-exit23.service`。

---

## 6.5 ri / tier / d_star 诊断基线（2026-11-18）

**现象**：云端三币持续 `ri=0.500`、`tier=probe`、`d_star=WAIT`。

**根因链**

1. `ESDirectionProvider` 只取 ESS top1。当前 top1 为 `CB-GRID-024`（`ess=1.0`，`n_samples=445`），
   其 `action_ids` 全是 `direction=both` 的离场动作（`AC-EXIT-HALF-AT-1PCT`、`AC-STOP-BREAKEVEN`）。
2. 取不到 `long/short` → `ess_top_direction=""` → `RippleEngine.detect_ripple_source` 的
   `dir_match=False` → `is_source=False` → `ripple_ri` 走硬编码回落 0.50。
3. `reflection_ri` 冷启动同为 0.50 → `ri=0.50`，恰好等于 `PROBE_THRESHOLD=0.50` → 恒 `tier=probe`
   （`base_position_mult=0.4`），永远到不了 `standard/trend`。
4. `d_star=WAIT` 与 ri 无关：`wait_cost = R_smooth × R_reflexivity`。两个 [0,1] 维度相乘，
   量纲系统性低于单维 `R_up/R_down`。实测三币 `R_smooth` p10/p50/p90 = 0.0963/0.1119/0.164，
   `R_reflexivity=0.65` → wait≈0.063~0.107；方向代价最低 0.31（`R_up` 均值 0.3969）。
   要让方向胜出需 `R_smooth > 0.61`，而 R_smooth 的 p90 仅 0.164 → **WAIT 结构性恒胜，属缺陷**
   （不是行情导致，也不是 spec 语义问题，是两维乘积与单维比较的尺度失配）。

**判定**

| 现象 | 判定 | 去向 |
|---|---|---|
| `ess_top_direction` 为空 | 缺陷 | F1（已修，云端 N9 已见 `long`） |
| 放量门槛固定 2.0（1H 触发率 0.12%） | 缺陷 | F2（已修，云端 `vol_threshold` 已随波动率变化） |
| `R_flow=0.0` | 设计内（Wyckoff effort/result 低阻力） | F3 关闭 |
| `d_star=WAIT` | 缺陷（量纲失配） | F4（已修：calibrated 口径 + 30% 中性区，开关默认 legacy） |
| `reflection_ri=0.5` | 冷启动正常 | F5 关闭 |
| 定位字段缺失 | 可观测缺口 | F6（已修） |
| `0.55` vs `0.50` 阈值 | 口径混淆（`0.55` 属 `get_ri_action` / `tight_coupling`） | F7 关闭 |

**F2 门槛公式**：`threshold = clamp(1.20 + 25·σ_day, 1.30, 2.50)`，σ_day 为 20 日已实现波动率
（1H 对数收益 std × √24）。模拟触发率：σ_1h=0.001→13.96%、0.003→3.38%、0.006→0.20%；
固定 2.0 恒为 0.12%，确认「太罕见即异常」。云端重启后实测 `vol_threshold` = 1.9303（BTC）/ 2.1578（ETH）。

**F4 模拟回测**（`scripts/backtest_ri_gate.py`，含 5bps/边）：

| wait 口径 | 累计收益 | 交易数 | WAIT 占比 | 平均 MDD |
|---|---|---|---|---|
| A: `R_smooth×R_refl`（现状） | -118.38% | 2981 | 0.0% | 74.96% |
| B: `(1-R_smooth)×R_refl` | +0.61% | 1093 | 63.3% | 21.84% |

**F4 实际事件（云端 n=339 N2，去重 33 组）**：A=100% WAIT、B=100% long、flip_rate=100%
→ 简单翻符号会退化成单边死多，**不可直接采纳**。

**F4 真实 K 线 walk-forward**（`--klines`，云端 BTC/ETH/SOL × 300×1H，逐 bar 重算 R，含 5bps/边）：

| 口径 | h=4h WAIT/L/S | h=4h 累计/MDD | h=24h 累计/MDD |
|---|---|---|---|
| legacy `R_smooth×R_refl` | 100% / 0% / 0% | 0% / 0% | 0% / 0% |
| flip `(1-R_smooth)×R_refl` | 0% / 0% / 100% | +12.50% / 32.97% | +170.52% / 59.77% |
| flip + 20% 中性区 | 11.1% / 0% / 88.9% | -0.43% / 32.49% | +81.87% / 59.77% |
| **flip + 30% 中性区** | **87.8% / 0% / 12.2%** | **+21.07% / 3.91%** | **-2.72% / 10.37%** |

裁决：legacy 恒 WAIT 属缺陷；单纯翻符号回撤 33%~60%，风险不可接受；**采用「翻符号 + 30% 中性区」**。
落地方式：`compute_d_star` 增加 `wait_mode`（`legacy|calibrated`）与 `wait_margin`（默认 0.30），
开关 `EVOLUTION_DSTAR_WAIT_MODE` **默认 legacy（行为不变）**，N4 事件同时记录 `d_star_shadow`
（`d_star_calibrated` / 两套 costs），云端观察一致后再切换。

**ri 与 d_star 的关系**：F1 修好只是必要条件，不充分。`ri=max(ripple_ri, reflection_ri)`，
`ripple_ri` 还要求 `vol_ratio ≥ threshold`（当前实测 0.42/0.24，确无放量，`ri=0.5` 正确）；
`tier` 升级需 `ri≥0.55/0.60/0.70`，且 `reflection_ri` 冷启动仍为 0.5。因此 ri 不会因 F1 自动脱离 0.5，
要等真实放量或 reflection 样本积累。


**修复清单与逐项状态**：[FIXLIST-ri-tier-dstar-20261118.md](./FIXLIST-ri-tier-dstar-20261118.md)。
修复期间的定位入口：`chain_events` 的 `N0`（数据就绪）/`N2`（R 向量）/`N5`（矛盾）/`N9`（ri·tier）。

---

## 7. 变更规则

1. 新增/修改信号字段：先改 `49-交易框架协议/contracts/final_decision_signal.v1.2.json`，再同步本文与 API_SPEC。
2. 新增链路节点：在本文登记语义，在 ENGINEERING_INDEX §4 登记代码入口与字段，在 15 TD §13 登记监控项。
3. 任何影响 `d_star/action/ri/tier/payload` 的变更，必须同时更新 churn 测试与链路事件断言。
4. 执行权边界（谁下单、谁落账、谁补挂 SL/TP）变更时，必须同步本文 §1.3/§6.4 与
   [22 TD §7](../../22-执行引擎中心/docs/TECHNICAL_DESIGN.md#7-统一持仓账本与执行兜底2026-11-18)；
   23 不得新增对 11 模块或 11 数据路径的依赖。
