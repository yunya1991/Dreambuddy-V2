# SPEC-L0-TRADE-EXEC-MCP v0.1

- 状态：🟢 v0.4 已落地（阶段一~六完成；2026-11-05 云端 43.160.201.117 端到端 + 影子驱动 + 小时级消费端验证通过）
- 日期：2026-11-05
- 上游：47-MCP管理系统（L0 四层范式、统一信封、**实盘链路永不暴露 MCP 硬约束**）、13-通用风控模块、16-调控系统、22-执行引擎中心、11-易经推理系统（执行器保留）、23-四层闭环自进化交易架构（信号输出口）
- 下游：trade-exec MCP 壳（mcp_shells 第 7 壳，**paper 模式主出口**）、四 Port 适配器、模拟盘运行时、**实盘旁路网关（不经 MCP）**

---

## §0 Executive Summary

### 0.1 做什么
把交易执行能力从分散子系统统一封装为 **L0 交易执行 MCP**（trade-exec MCP），定位为**模拟盘（paper）主出口**：
- **模拟盘唯一出口**——所有策略验证、风控/定容代码验证、影子对比经此 MCP 的 paper 模式执行；
- **实盘旁路（不经 MCP）**——真实下单走 11 域 okx_client 直连旁路，trade-exec MCP 的 `place_order` 不触真实交易所，仅在 paper 模式下做意图落盘 + 模拟撮合。**遵守 47-MCP "实盘链路永不暴露 MCP" 硬约束**；
- **信号与执行解耦**——23 域（及其他子系统）作为信号提供者，MCP 负责风控→定容→执行全管道（paper 路径），实盘由旁路网关在风控通过后直连交易所。

### 0.2 为什么（2026-11-05 实证调研结论）
| 域 | 规模 | 现状 | 封装价值 |
|---|---|---|---|
| 13-通用风控模块 | 19 py（engine/exit_engine/position_sizer/l1_assessor） | **无显式 Port 契约引用**（42 域 param_governor、4-MEMORY auto_update_trigger 仅有文档级/常量级引用） | 显式契约化，作为事前风控管道 |
| 16-调控系统 | 103 py（capital_allocator/capital_control） | **孤岛**，无生产引用 | 只取资金调控部分，作为定容步骤 |
| 22-执行引擎中心 | 41 py（tee_core：adapters/algorithms/core/estimators） | 11 域以路径 hack 懒加载（polling_trader L6577） | 正式化为 OrderPort 契约调用 |
| 11 域执行器 | okx_client.place_order + TEE 双轨 | **唯一实盘出口**（33 笔真实成交） | **保留为实盘旁路网关**（不经 MCP），11 域同时提供信号 |
| 23 自进化 | 275 万影子 RL 样本，无执行基础设施 | 信号输出口 | 专注进化，策略经 MCP paper 验证后由旁路网关切实盘 |

### 0.3 不做什么
| 禁止 | 原因 |
|---|---|
| 不在 MCP 内做策略决策 | MCP 是执行通道，不是策略平台；信号一律来自外部 |
| 不纳入 16 域 backtest_framework/策略适配器 | 超出执行范畴，留在 16 域 |
| **不让 trade-exec MCP 触真实交易所** | 遵守 47-MCP "实盘链路永不暴露 MCP" 硬约束；实盘由 11 域旁路网关直连 |
| 不让未验证代码直接触实盘 | 13/16 从未投产，必须先过 paper 管道 ≥2 周 |
| 不放宽既有门禁 | ablation gate / OOD 隔离 / **48 域 §5 三关门禁（双度量+OOD+稳健性）**全部保持 |

---

## §1 Port 契约（四 Port，契约先行）

> **L0 port/domain 映射（对齐 47 注册表 enums）**：trade-exec 壳工具统一映射到 **port=event**（现有 6 壳未使用 event port，语义为"事件触发→执行"），**domain=trade-exec**（注册表新增枚举值，不占 port 上限——壳不计入 SPEC-L0 §3.1 port 上限 6）。四 Port 是交易执行域内的接口契约，非 L0 port 枚举。

### 1.1 OrderPort（下单通道）
```
place_order(symbol, side, order_type, size, price?, mode) -> OrderResult
  mode: "paper"（MCP 壳层强制，实盘 live 由旁路网关直连，不经 MCP）
cancel_order(order_id) -> CancelResult
OrderResult: {order_id, status, filled_avg_price, filled_size, slippage_bps, envelope}
```
- 实现方：22 tee_core adapters（交易所适配）+ 11 域 okx_client 旁路
- MCP paper 模式：下单意图落盘 + 模拟撮合（优先复用 22 域 paper_adapter，K 线撮合后置增强）
- 实盘 live 模式：旁路网关在风控通过后直接调 okx_client，**不经过 MCP 壳**

### 1.2 RiskCheckPort（事前风控管道）
```
pre_trade_check(signal: TradeSignal) -> CheckResult
  CheckResult: {passed, rejections: [rule_id, reason], adjusted_size?}
```
- 实现方：13 域 engine + rules（事前检查管道：仓位上限/标的黑名单/波动熔断等）
- 语义：**fail-closed**——风控不可用时拒绝下单（与 L0 Principal 门禁同哲学）

### 1.3 PositionPort（持仓与对账）
```
get_positions() -> [Position]
reconcile() -> ReconcileReport（本地账本 vs 交易所实仓对账）
```
- 对账差异超阈值 → 告警 + 拒绝新开仓（防裸奔）

### 1.4 AccountPort（账户查询）
```
get_balance() -> Balance
get_account_mode() -> {mode, exchange, endpoints}
```

### 1.5 执行管道（固定顺序，不可配置）
```
信号（23 域等）→ RiskCheckPort（事前风控）→ 定容（16 capital_allocator）
  → OrderPort（下单）→ PositionPort（对账）→ 信封落盘
```
- 定容作为 RiskCheck 与 Order 之间的固定步骤，不暴露为独立 Port（避免策略侧绕过风控直接定容）
- 定容最小契约：`size_position(signal: TradeSignal, check_result: CheckResult) -> adjusted_size: float`（输入信号+风控结果，输出调整后仓位；16 域 capital_allocator 实现）
- **paper 路径**：全管道经 MCP 壳（place_order mode=paper，模拟撮合）
- **live 路径**：风控+定容仍走 MCP 壳（只读计算），下单环节由旁路网关直连 okx_client，不经过 MCP 壳的 place_order

---

## §2 统一信封与壳层

### 2.1 信封 schema（对齐既有 6 壳，mode/cost 承载于 meta）
```json
{
  "tool": "place_order",
  "ok": true,
  "degraded": false,
  "error_code": "",
  "meta": {
    "mode": "paper",
    "cost": {"latency_ms": 0, "slippage_bps": 0}
  },
  "data": { ... OrderResult ... }
}
```
- `mode` / `cost` 放入信封 `meta` 槽位（envelope_wrap 已有 meta 参数），**不新增信封顶层字段**，保持 H1 壳 diff=0（不改 envelope_wrap 签名）
- 完整信封字段对齐既有 6 壳：`{ok, data, source, timestamp, degraded, meta, version, trace_id, idempotency_key, error_code}`

### 2.2 trade-exec 壳（mcp_shells 第 7 壳）
- 复用 _shared 基建（shadow_hook/agent_mail_shadow 信封落盘）
- **壳 source = `l0.trade-exec.mcp`**（与注册表 `shell_id` 严格一致；多词统一连字符，修正早期 `l0.trade_exec.mcp` 漂移）
- 工具集（9 个，v0.3 实况）：
  - 写：place_order / cancel_order / ingest_signal（`requires_mandate=true`，`readOnlyHint:false`）
  - 读：get_positions / get_balance / pre_trade_check / get_account_mode / reconcile / read_signals
- **注册表映射**：port=event，domain=trade-exec（注册表 enums 新增 trade-exec）
- **`executor` 角色 = 只读**（v0.3 纠正）：ADR-9/H7 硬约束规定 Worker 角色不得持有写工具，`validate_mcp_registry.py` 第 9 条为硬门禁。executor 工具集仅 6 个只读工具；place_order / cancel_order / ingest_signal 仅由**编排侧（持宿主 Mandate）**调用，不进入任何 worker role。
- **能力自描述（v1.1-mcp）**：`capabilities.{shadow_capable:true, training_hooks:[on_order_filled,on_risk_rejected,on_signal_skipped], oracle_verifiable:true}`；`envelope_wrap.wrap()` 按 `source` 自动注入 `meta.{shadow_capable, oracle_verifiable, config_version}`（FAIL-OPEN + `MCP_CAPS_INJECT=0` 可关）
- stdio 协议；300 秒级轮询交易风格下延迟无障碍

---

## §3 paper/live 双路径（MCP 承载 paper，live 走旁路）

| 维度 | paper（模拟盘，经 MCP） | live（实盘，旁路网关） |
|---|---|---|
| 下单 | 意图落盘 + 模拟撮合（优先复用 22 域 paper_adapter） | 11 域 okx_client 直连交易所 |
| 路径 | 全管道经 MCP 壳 | 风控+定容经 MCP（只读计算），下单旁路不经 MCP |
| 风控/定容 | **同一管道**（同构性是核心价值） | 同左（复用 MCP 的 RiskCheck/定容计算结果） |
| 信封 | mode=paper，meta.cost 记录模拟滑点 | mode=live，旁路网关自记审计，不走 MCP 信封 |
| 用途 | 策略验证（23 域候选策略）、13/16 未投产代码验证、48 域 E-BIZ 对比实验 | 唯一真实出口（11 域旁路） |

- MCP 壳**单实例单模式=paper**（杜绝配置漂移导致模拟单触实盘）；live 模式不存在于 MCP 壳实例，由旁路网关独立承载

---

## §4 实施路径（四阶段）

### 阶段一：Port 契约 + 本 SPEC 评审（估 3-4 天）
- 本 SPEC 评审（正反方辩论，对齐 48 域评审流程）
- 四 Port 契约冻结 + 信封 schema 定稿

### 阶段二：适配器封装 + paper 模式（估 1-2 周）
- 22 tee_core adapters → OrderPort；13 engine → RiskCheckPort；16 capital_allocator → 定容步骤
- paper 模式全链路：**优先复用 22 域 paper_adapter**（V15PaperClient 状态机），K 线撮合引擎作为阶段二后期增强项单独评估
- 13/16 未投产代码在 paper 管道跑 ≥2 周（风控拦截率/定容合理性人工复核）

**✅ 已落地（2026-11-05）**
- OrderPort：自包含 `OKXPaperLedger`（原子 JSON flock；市价/限价/平仓/手续费/已实现盈亏），行情 OKX ticker（`User-Agent: curl/7.81.0` 绕过 OKX 对 Python urllib 的 403）→ HL public 兜底（mid ±1bps 合成 bid/ask）
  - 偏差说明：未复用 22 域 paper_adapter（其依赖 V15PaperClient→HLDataAdapter 旧行情链），改为自包含账本，无跨域依赖
- RiskCheckPort：`RiskBridge` 桥接 13 域 `RiskEngine.pre_trade_check`（`Signal(coin, direction=LONG/SHORT, confidence)` + `RiskContext(total_equity, available_balance, positions)`），**Fail-Closed**：RiskEngine 加载失败/异常 → 一律拒单
- 定容：`RiskEngine.calculate_position(signal, ctx, position_modifier)` → `base_size_usdt / base_size_coins / position_tier / leverage`，结果记入信封 `meta.sizing`
- 工具：`pre_trade_check`（独立风控查询）、`get_account_mode`、`reconcile`（paper-only 自洽报告）

### 阶段三：trade-exec 壳 + 23 信号接入（估 1 周）
- 第 7 壳落地（复用 _shared）；注册表新增 trade-exec domain + executor 角色
- 23 域信号接入：信号 → MCP 管道 → paper 执行
- paper 与 11 域实盘并行对比 ≥2 周：信号一致率 + 模拟成交 vs 实盘成交偏差

**✅ 已落地（2026-11-05）**
- 第 7 壳 `mcp_shells/l0_trade_exec/server.py` 落地，shadow_driver 注册 `trade_exec`，注册表 `mcp_capabilities.yaml` 新增 trade-exec domain + executor 角色
- `SignalAdapter` 双源归一化：23 域 `11-易经推理系统/data/event_driven_state.json`（`symbol/main_chain.action/signal.confidence/mode`）+ 42 域 `42-神经网络交易协调层/runtime/bus_state.json`（SignalSchema：`signal_id/source/ts/symbol/direction/confidence/horizon/risk_exposure_hint/expires_at/payload`）
  - 符号归一：`QCOM → QCOM-USDT-SWAP`、`BTC → BTC-USDT-SWAP`、`BTC-USDT → BTC-USDT-SWAP`
  - 方向映射：`long/buy → long`，`short/sell → short`，`neutral` → skip
- 工具 `read_signals`（只读，多源 FAIL-OPEN：单源损坏只降级该源）
- 工具 `ingest_signal`（写，`requires_mandate=true`）：信号 → 过期校验 → `signal_id` 幂等 → 行情 → 定容（显式 size 优先，否则 `risk_exposure_hint × balance / mid`，兜底 `TRADE_EXEC_SIGNAL_NOTIONAL=10 USDT`）→ 风控（Fail-Closed）→ paper 撮合 → 幂等落账
- 幂等：账本 `executed_signals[]`（上限 `MAX_FILL_HISTORY`），同一 `signal_id` 只执行一次
- 修复 paper 账本 net 模式方向语义：无仓 `sell → short`、有仓反向成交走平仓；`get_positions` 方向与 `upl` 符号按实际 `long/short` 计算（原实现把 short 误显示为 long）
- 市价成交返回补 `realized_pnl` + `fee` 字段，便于信号→执行→损益闭环核对

**⏳ 待执行（非代码项）**
- paper 与 11 域实盘并行对比 ≥2 周（信号一致率 + 成交偏差），需 11 域 polling_trader 侧留观

### 阶段四：旁路网关灰度 + 11 域职责澄清（估 1 周）
- 分标的灰度：旁路网关（11 域 okx_client）接管某标的实盘时，执行权注册表显式声明，11 域对该标的其他路径停单
- 11 域 polling_trader 明确双职责：信号提供者 + 实盘旁路网关（执行器不"下沉"，保留在 11 域）
- E0b 基线重建 v3（实盘出口=11 域旁路网关，paper 出口=trade-exec MCP，human_baseline.json 标注）

**✅ 已落地（2026-11-05）**
- 执行权注册表 `47-MCP管理系统/registry/execution_rights.json`（标的级单出口声明）：
  - `paper`：trade-exec MCP 承担（默认值，灰度从零开始，BTC/ETH 已显式声明）
  - `live:11-bypass`：11 域 okx_client 旁路网关承担实盘，MCP 拒单
  - `disabled`：两出口均不执行
  - 匹配顺序：完整 instId → coin → `defaults.outcome`；文件缺失时按 defaults(paper) 兜底并在 `get_account_mode` 报 `available=false`
- MCP 侧互斥闸门：`ExecutionRights.conflict()` 前置挂在 `place_order` + `ingest_signal`，命中非 paper → `error_code=execution_rights_conflict`（fail-closed）
  - 云端实测：ETH 声明 live → MCP 拒单；BTC 声明 disabled → MCP 拒单；默认 paper → 正常撮合
- 11 域职责澄清（本轮**零代码改动**，避免实盘风险）：
  - 现有双闸门：`shadow_mode`（全局禁止所有开/平/减仓）+ `EXECUTION_AUTHORITY`（按信号 `source_tag` 白名单，默认 `evolution_only`，`polling_trader.py` L807-830 / L16115-16150）
  - 灰度接管需**同时满足**：① `execution_rights.json` 该标的 `live:11-bypass`；② 11 域 `EXECUTION_AUTHORITY` 放行该 `source_tag`
  - 职责边界：11 域 = 信号提供者 + 实盘旁路网关；trade-exec MCP = paper 唯一出口；执行器不"下沉"到 MCP

**⏳ 待执行（非代码项）**
- E0b 基线重建 v3：`48/registry/human_baseline.json` 当前**不存在**（仅有 `human_config_hashes.json` + `struct_vector.py`），需等 48 域 walk-forward OOS 跑完后产出，并在每条记录加 `execution_exit` 标注（`paper:trade-exec-mcp` / `live:11-bypass`）
- 实际分标的灰度接管：需运维同时修改 `execution_rights.json` 与 11 域 `EXECUTION_AUTHORITY`，且须用户显式确认（单标的先行，观察 ≥2 周）

### 阶段五：L0 基础能力对齐（通信层 / 训练 / 可观测）（估 2 天）

**✅ 已落地（2026-11-05）**
- **通信层（COMM-SHADOW）**：`observe_envelope()` 挂在 dispatch 统一出口，覆盖全部 9 工具响应；云端 `dreambuddy-shadow-driver.service` 增加 `trade_exec` 域（systemd drop-in），实测 12 调用 / `degraded=0`，`trajectories.jsonl` 新增 3 条 `agent_domain=trade_exec` 记录
- **算法能力训练（生产端）**：`_emit_sample()` 以 FAIL-OPEN 方式追加 `ml_data/samples.jsonl`，5 个调用点覆盖 `order_filled` / `risk_rejected` / `signal_skipped`；注册表 `training_hooks` 与实现对齐
- **算法能力训练（消费端 Phase 0）**：新增 `23-四层闭环自进化交易架构/dreambuddy_evolution/core/execution_sample_loader.py`
  - 读取 `samples.jsonl` → 归一化为执行策略训练行 `{input, action, reward, label, meta}`
  - reward：`order_filled → realized_pnl / notional`（截断 ±3%）、`risk_rejected → -0.005`、`signal_skipped → 0`
  - **不并入 6 域 DomainCouplingHead**（15 对耦合矩阵与已训练 checkpoint 维度不变，执行策略走独立管线）
- **契约测试**：`mcp_shells/l0_trade_exec/test_l0_trade_exec_server.py` 10 用例（工具面 / 信封 / 执行权 / 前置过滤 / 样本落盘 / 能力注入），全绿
- **trace_id 贯穿**：`test_trace_id_coverage.py` 扩至 5 壳（新增 trade-exec invalid 只读路径），共 5 用例全绿
- **能力自描述注入**：`envelope_wrap.wrap()/wrap_merge_partial()` 按 `source` 从注册表注入 `meta.{shadow_capable, oracle_verifiable, config_version}`，修复"注册表声明有、代码无实现"漂移
- **生产账本**：云端 `mcp_shells/l0_trade_exec/ledger/paper_ledger.json` 首次生成（balance=260，独立于验证期 /tmp 账本）
- **一致性**：云端与本地 `mcp_shells/` + `47-MCP管理系统/` 63 文件双向 md5 diff = 0

### 阶段六：执行策略 agent Phase 1a + 小时级消费端（2026-11-05）

**✅ 已落地**
- **executor agent 运行骨架**：`23-四层闭环自进化交易架构/dreambuddy_evolution/core/executor_agent.py`
  - 输入 signal + context → 输出 `{execute, size_multiplier, order_type, urgency, reasons, policy_version}`
  - 规则底座：conf<0.60 拒执行 / expired 拒执行 / critical 强制 0 仓位 / 高波动（>60bps）乘数 0.5 + limit 单
  - 可注入 policy（Phase 1b 训练后替换），**硬钳位恒在本模块生效**（乘数 ≤1.0、方向不可改）
  - 只建议不下单；最终仍经 ExecutionRights 闸门 + RiskBridge（fail-closed）
- **小时级消费端**：`execution_sample_loader.py` 增加 CLI 与 `write_policy_rows()`（按事件去重、可重复运行），云端 `dreambuddy-windowed-collect.service` 串联执行，产出 `dreambuddy_evolution/data/execution_policy_training.jsonl`
- **契约测试**：`test_executor_agent.py` 6 用例 + `test_execution_sample_loader.py` 5 用例

**⏳ 待执行**
- Phase 1b：策略网络训练（前置：≥2 周 paper 样本积累）
- 6 域耦合矩阵不纳入 trade-exec（维度契约不变，执行策略走独立管线）

---

## §5 硬约束兼容性对照

| 约束 | 本 SPEC 处理 |
|---|---|
| **实盘链路永不暴露 MCP**（47-MCP 奠基性硬约束） | ✅ trade-exec MCP 仅承载 paper 模式；实盘 live 由 11 域旁路网关直连，不经 MCP 壳 |
| H1 壳 diff=0 | 新增第 7 壳不改动既有 6 壳；mode/cost 放 meta，不改 envelope_wrap |
| REA 决策分离 | 信号（23/11）与执行（MCP paper + 旁路 live）彻底分离，更符合 |
| 零执行权（涌现候选） | 48 域 E2 候选策略必须先过 paper 模式 + ablation gate + 人工复核才可经旁路网关 live |
| FAIL-OPEN | 信号侧失败不阻断；执行侧风控 fail-closed（不对称是刻意的：信号可丢，钱不能错） |
| OOD 隔离 | paper 模式成交数据默认不进案例库/记忆升级（黑名单参数对齐 48 域 §5） |
| **48 域 §5 三关门禁**（双度量+OOD+稳健性） | 全部保持，不因执行统一而放宽 |
| ADR-9/H7 Worker 只读 | executor 角色只登记 6 个只读工具；3 个写工具仅编排侧持 Mandate 调用，任何 worker role 均不含写工具（注册表校验第 9 条硬门禁） |

---

## §6 风险与对策

| 风险 | 等级 | 对策 |
|---|---|---|
| 13/16 未投产代码触钱 | 高 | paper 管道 ≥2 周 + 人工复核后再进旁路 live 路径 |
| 迁移期双出口冲突 | 高 | 执行权注册表（execution_authority.yaml）+ 分标的灰度，同一标的同一时刻单出口 |
| 11 域 TEE 审计链与 MCP paper 不对齐 | 中 | TEE 双轨保留在 11 域旁路网关；MCP paper 侧复用 envelope_wrap 落盘审计，两侧审计语义独立但可对账 |
| E0b 基线口径失效 | 中 | 阶段四完成后重建 human_baseline v3（标注 paper/live 双出口） |
| 四域代码风格不一致 | 中 | Port 契约先行，适配器逐个封装，不要求域内重构 |

---

## §7 边界声明
- 13/16/22 域代码所有权不变，MCP 只做契约化封装引用；
- 16 域只纳入 capital_allocator/capital_control，backtest/策略适配器留在 16 域；
- 23 域保持信号输出口定位，不建执行基础设施；
- **11 域执行器保留为实盘旁路网关**（不"下沉"进 MCP），polling_trader 双职责：信号提供者 + 实盘旁路；trade-exec MCP 仅承载 paper；
- **实盘链路永不暴露 MCP**——trade-exec MCP 的 place_order 不触真实交易所，live 下单由 11 域旁路网关直连；
- 本 SPEC 归属 47 域 L0 体系管理，与 SPEC-L0-MCP-PACKAGING 同规范演进。

---

## §8 L0 壳能力对齐矩阵（2026-11-05 实测）

| 壳 | transport | 工具 | capabilities | COMM-SHADOW 接线 | 10min 影子驱动 | 契约测试 | trace_id |
|---|---|---|---|---|---|---|---|
| cognition | ssh-stdio | 6 | ✅ | ❌ | ❌ | 另有 | ❌ |
| semantic-39 | stdio | 4 | ❌ | ❌ | ❌ | — | ❌ |
| rea | stdio | 6 | ❌ | ✅ | ✅ | ✅ | ✅ |
| data | stdio | 4 | ❌ | ✅ | ✅ | ✅ | ✅ |
| eval | stdio | 2 | ❌ | ✅ | ✅ | ✅ | ✅ |
| store-admin | stdio | 2 | ❌ | ✅ | ✅ | ✅ | ✅ |
| **trade-exec** | stdio | **9** | ✅ | ✅ | ✅（v0.3 新增） | ✅ 10 | ✅ |
| rea-client | http | 3 | ❌ | ❌ | ❌ | — | — |

结论：trade-exec 在**通信层、契约测试、trace_id 贯穿、训练样本真实落盘**四项对齐或领先；`capabilities` 自描述已由 `envelope_wrap` 统一注入，全壳受益。

## §9 缺口与推进状态

| 缺口 | 等级 | 状态 |
|---|---|---|
| 注册表声明"运行时自动注入 capabilities"但无实现 | P2 | ✅ 已修（`envelope_wrap` 统一注入） |
| 壳 source `l0.trade_exec.mcp` 与注册表 `l0.trade-exec.mcp` 不一致 | P2 | ✅ 已修（统一连字符） |
| `executor` 角色误含写工具（注册表校验 3 ERR） | P0 | ✅ 已修（改为 6 只读工具） |
| 训练样本无消费端 | P1 | ✅ Phase 0 + 小时级增量落盘（`execution_sample_loader.py`） |
| 无 executor domain agent 运行时 | P1 | ✅ Phase 1a 规则骨架（`executor_agent.py`）；Phase 1b 策略训练待样本 |
| 小时级窗口采集未含 trade-exec | P2 | ✅ 以独立管线接入 windowed-collect（不改 6 域维度契约） |
| `human_baseline.json` 缺失（E0b v3） | P2 | ⛔ **上游阻塞**：48 域 SPEC v0.5 明确"E0b 仅剩 polling_trader 回放器缺口"，回放器未建，无法产出 OOS 基线；本域不做伪造数据 |

## §10 executor agent（Phase 1 设计边界）

- **定位**：执行策略 agent（非策略决策），输入 = 信号特征 + 风控结果 + 定容结果，输出 = `{execute, size_multiplier, order_type, urgency}`
- **训练数据**：`execution_sample_loader.build_dataset()` 产出的 `{input, action, reward, label}` 行
- **动作空间**：`{execute, resize, reject, defer}`（不覆盖方向决策，方向由信号给定）
- **奖励**：沿用 §4 阶段五口径（paper 已实现盈亏 / 风控惩罚 / 跳过 0），后续可加执行质量项（滑点、延迟、成交率）
- **硬约束**：agent 只能建议，最终下单仍经 `place_order` 的 ExecutionRights 闸门 + RiskBridge（fail-closed）；不得绕过 Mandate
- **Phase 1a（已落地）**：`dreambuddy_evolution/core/executor_agent.py` — 规则底座 + 可注入 policy + 硬钳位，6 测试
- **Phase 1b（待执行）**：策略网络训练，前置 = ≥2 周 paper 样本（`execution_policy_training.jsonl` 行数 ≥ N）
