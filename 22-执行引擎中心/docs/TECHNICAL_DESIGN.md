# 执行引擎中心 — 技术设计

> **版本**：v1.1 | **更新日期**：2026-11-18

## 1. 架构设计

TEE 采用分层架构：

```
策略信号 → [协议层 protocol] → [路由层 router] → [算法层 algorithms] → [适配器层 adapters] → 交易所
                ↓                    ↓                   ↓                    ↓
            [契约 contract]      [熔断 kill_switch]  [滑点估计 estimators]  [审计 auditor]
                                     ↓
                               [FAIL-OPEN failopen]
```

### 1.1 核心层 core/

| 模块 | 职责 |
|------|------|
| engine.py | 执行引擎主类，协调各子系统完成订单执行 |
| config.py | 配置加载与校验，支持环境变量覆盖 |
| protocol.py | 订单协议定义（OrderRequest/OrderResponse/Fill） |
| contract.py | 执行契约（前置条件/后置条件/不变量） |
| router.py | 订单路由，根据策略/标的/账户选择交易所 |
| kill_switch.py | 熔断开关，异常时自动停止下单 |
| failopen.py | FAIL-OPEN 降级策略，主路径失败时降级执行 |
| auditor.py | 全链路审计，记录每笔订单的完整生命周期 |

### 1.1.1 根目录公共执行模块

| 模块 | 职责 |
|------|------|
| trade_execution_gateway.py | `TradeExecutionGateway`：统一下单入口（v1.2 契约、幂等、风控桥、审计、落账） |
| position_ledger.py | `PositionLedger`：持仓数量与已实现盈亏唯一真相源（positions/fills/cooldowns） |
| sltp_reconcile.py | 存量持仓 SL/TP 补挂巡检（各域共用，11 交易循环下线后仍兜底） |

### 1.2 适配器层 adapters/

| 适配器 | 用途 |
|--------|------|
| okx_adapter.py | OKX 实盘交易所适配 |
| paper_adapter.py | 模拟盘适配（纸面交易） |
| lark_bridge.py | 飞书通知桥接（下单/成交/异常告警） |

### 1.3 算法层 algorithms/

| 算法 | 策略 |
|------|------|
| direct_market | 直连市价单，追求即时成交 |
| smart_passive | 智能被动单，挂单吃单结合降低滑点 |
| smart_twap | 智能 TWAP，时间加权平均价格执行 |

### 1.4 集成层 integrations/

| 集成 | 说明 |
|------|------|
| v15_integration | V15 马丁策略信号接入与执行 |
| yijing_integration | 易经推理系统信号接入 |

## 2. 关键设计决策

### 2.1 FAIL-OPEN 优先
任何子系统异常时，TEE 降级为基础直连执行，保证交易不中断。熔断开关仅在资金安全受威胁时触发。

### 2.2 审计不可绕过
所有订单必须经过 auditor 记录，审计日志写入 `audit/` 目录（JSONL 格式），用于事后复盘与影子对比。

### 2.3 滑点估计前置
执行算法决策前先通过 slippage estimator 预估滑点，选择最优执行策略。

## 3. 数据流转

1. 策略层产生信号（V15/易经/事件驱动）
2. protocol 层封装为标准 OrderRequest
3. contract 层校验前置条件
4. router 选择交易所与账户
5. kill_switch 检查熔断状态
6. algorithms 选择执行算法（参考滑点估计）
7. adapters 下发到交易所
8. auditor 记录完整生命周期
9. failopen 在任意环节失败时降级

## 4. 异常处理

| 异常类型 | 处理策略 |
|----------|---------|
| 交易所 API 超时 | 重试 → 降级备用交易所 → FAIL-OPEN |
| 滑点超阈值 | 切换被动算法 → 熔断 |
| 审计写入失败 | 内存缓冲 → 后台落盘 |
| 配置缺失 | 使用默认值 → 告警 |

## 5. NN 链 live 执行器（x1_live_executor.py，2026-11-13）

- 输入：50 `runtime/live/outbox.jsonl`（仅 `source=50-nn`、`mode=live`、`shadow=false`、方向非 neutral 的决策）。
- 复核（fail-closed，任一不过即跳过并落 `skips`）：kill-switch → 执行权 `live:50-bypass` → `mandate_id` 非空 → 标的 allowlist（`config/live_symbols.json` 注册表 72 标的 / 9 类，与 40 `asset_classes.py` 的 G1/G2 可交易全集对齐；fx/DXY 无 USDT 永续故排除；文件缺失 fail-closed 仅 `BTC-USDT-SWAP`）→ 单笔名义 ≤ 类别上限（默认 100 USDT；`us_index`/`apac_index`/`us_etf` 300 USDT）、杠杆 ≤3 → 幂等 `runtime/x1_live_processed.json`。
- 定容与仓位额度：13 定容（约权益 10%）经 `risk_bridge.precheck(notional_cap, notional_floor)` 按类别钳制——非指数类低于 100U 抬回（`notional_floor_default=100`），指数/高价 ETF 抬到 150U、上限 300U（`notional_policy=class_floor`）；并发上限 `max_positions_default=12`，50 域请求携带 `position_scope=registry`，bridge 只统计注册表内标的，不被其他域持仓挤占。
- 50 侧声明名义上限（M4-4，2026-11-14）：决策可携带 `notional_usdt`（`run_live` 默认 100，`50_LIVE_NOTIONAL_USDT`）；执行器取 `min(risk_bridge 定容, 声明值)`，**只降不升**，仍受类别 cap 约束。声明值低于标的 `minSz` 时 `_usdt_to_sz` 向下取整为 0，bridge 以 `size_zero` fail-closed 拒单——因此 50 侧把默认对齐到 100U，而非更小的 20U。
- 执行：以子进程调用 22 `executors/live_order_bridge.py`（凭据来自 22 域加密库 `executors/credentials.py`），bridge 负责下单与 SL/TP（OCO）并写 `22/runtime/live_order_audit.jsonl`。
- 账本：`audit/x1_live_fills.jsonl`，扁平字段 `ts/decision_id/source/mode/symbol/direction/confidence/position_pct/venue/order_placed/order_id/fill_px/request/result`。
- dry-run 语义：`--dry-run` 只打印不落 processed，便于重放真实执行。

## 6. live 链路强化（P0-1/2/3 + P0-4，2026-11-14）

### 6.1 13 事前风控接入（risk_bridge.py）

执行器在 `_check()` 复核之后、调用 11 bridge 之前统一走 `risk_bridge.precheck(decision)`：

1. `CapitalControlComponent().evaluate()` 取 `snapshot.total_equity`（真实权益；不可用才回落 `22_RISK_EQUITY_DEFAULT`，默认 10000）
2. 13 `PreTradeGate.check(Signal, RiskContext(total_equity))` 判定；neutral 直接 `NO_DIRECTION`
3. `CapitalAllocatorComponent.get_allocation_advice(base_symbol, "50-nn", equity)` 定容 → `position_usdt`
4. 名义金额 = `min(position_usdt, 100)`；`< 10` 拒单（`SIZING_BELOW_MIN`）

返回契约：`{passed, reason_code, reason, equity, equity_source, notional_usdt, leverage, position_pct, allocator_mode, source}`。
13 模块加载失败 → `RISK_MODULE_LOAD_FAILED`，`reason` 携带真实异常。

**包名隔离**：13/12/14/16/50 都存在顶层 `core` 包。加载 13 时临时把 13 与其 `risk_capital` 路径置顶、摘除并恢复 `core.*`、退出时恢复 `sys.path`，避免 `import core` 命中错误模块。

### 6.2 决策幂等（P0-4）

50 `run_live.py` 的 `decision_id` 由决策时刻改为**证据批次 sha1**（`50-nn|<16hex>`）：同一批 42 证据重复调度得到同一 id，证据集变化才产生新 id。22 的 `processed` 幂等因此生效。

### 6.3 持仓守卫与冷静期

| 守卫 | 触发点 | 行为 |
|---|---|---|
| 持仓守卫 | 真实下单前查 11 `status` | 同标的 `pos != 0` → `symbol_already_open`；查询失败 → `position_query_failed`（fail-closed） |
| 冷静期 | `_check` 之后 | 距上次真实成功开仓不足 `COOLDOWN_HOURS`（默认 8h）→ `cooldown`，写 `last_entry[symbol]` 仅在真实下单成功后 |

两类跳过都会写 `processed`，避免冷静期结束后补执行过期信号。

### 6.4 云端运行

- systemd：`dreambuddy-nn-live-chain.service/.timer`，`OnCalendar=*:02/5:00`，`User=luke`，`WorkingDirectory=/home/luke/dreambuddy`
- 顺序：50 `tools/run_live.py` → 22 `x1_live_executor.py --limit 20`
- 运维：`sudo systemctl start dreambuddy-nn-live-chain.service` 手动跑一轮；`journalctl -u` 查看日志；真实下单记录落 `audit/x1_live_fills.jsonl`
- 回退：在 unit 的 ExecStart 加 `--dry-run` 即回到只读演练

## 7. 统一持仓账本与执行兜底（2026-11-18）

23 域独立运行、11 交易循环（`polling_trader`）下线后，22 承接全部「公共执行」能力：
下单、幂等、落账、SL/TP 补挂、对账与幽灵仓清理。本节是该边界的唯一说明。

### 7.1 PositionLedger（position_ledger.py）

SQLite 单库 `22-执行引擎中心/runtime/position_ledger.db`，可用 `POSITION_LEDGER_PATH` 覆盖。

| 表 | 语义 |
|---|---|
| `positions` | 当前持仓聚合（`inst_id,pos_side` 主键）：`qty/avg_entry/entry_known/realized_pnl/source` |
| `fills` | 追加式成交流水：`action ∈ open/close/reduce/reconcile/reconcile_update` |
| `cooldowns` | 全平冷却（替代 11 `last_close_info`），供开仓侧 `is_in_cooldown()` 查询 |

- 只落账，不做风控与决策；异常由 Gateway 吞掉（FAIL-OPEN），不影响下单。
- `source` 是持仓归属：`23-evolution`/`evolution`/`bcrm`/`strategy`/`event_arbitrage` 归 23 巡检；
  `22-reconciled` 为对账回填；50-NN 链写自己的 source。无 source 的历史手工流水不参与自动校正。
- `apply_partial_close()` 在剩余量为 0 时写冷却；`entry_known=0`（P2 之前的仓）不臆造已实现盈亏。

### 7.2 账本对账 reconcile_ledger()

`TradeExecutionGateway.reconcile_ledger(source="22-reconciled")` 每轮拉取交易所持仓并调用
`PositionLedger.reconcile()`，返回 `{ok,inserted,updated,closed,skipped,...}`：

1. **补缺**：交易所存在、账本缺失 → 插入，`source=<source>`，写 `fills.action=reconcile`。
2. **校正数量**：仅对「受管源」——本对账源、`23-*`、`evolution`、`bcrm`、`strategy`、
   `event_arbitrage`——以交易所数量为准；无 source 的历史手工流水保持不动（幂等测试基线）。
3. **同步均价**：仅本对账源（`22-reconciled`）随交易所 `avg_px` 漂移更新，写
   `fills.action=reconcile_update`；23 自己开的仓保留真实开仓成本。
4. **关闭陈旧行**：交易所已无持仓、账本仍开 → 仅关闭 `source` 以本对账源开头的行，
   `exit_reason=ghost_stale`，避免每轮重复报幽灵仓。

调用方：23 `exit_runner` 每轮（默认 60s）先对账再巡检，因此数量/均价漂移最多滞后一个周期。

### 7.3 幽灵仓清零 close_ghost_position()

`TradeExecutionGateway.close_ghost_position(inst_id, pos_side, exit_px, source="23-evolution")`：
交易所已无持仓但账本仍开着时，按传入价（缺省用账本均价）全平，`exit_reason=ghost_exchange_flat`。
23 `exit_runner` 的 `on_ghost` 回调直接调用，保证一次告警后账本归零。

### 7.4 SL/TP 补挂 reconcile_sltp()

`sltp_reconcile.reconcile_sltp(okx_client, sl_pct=0.05, tp_pct=0.08,
breakeven_upl_pct=3.0, log_fn=None, audit_path=None)`：

- 逐 inst 查 `get_algo_orders`，只补**缺失的一侧**（已在的一侧传 0），避免重复/覆盖。
- 止损方向必须安全：long 止损 < 当前价，short 止损 > 当前价，否则 OKX 会
  `Order would immediately trigger`。
- 浮盈超过 `breakeven_upl_pct` 时止损上移至保本。
- 审计落 `22-执行引擎中心/audit/sltp_reconcile.jsonl`：每次补挂写明细，**每轮另写一条
  `kind=summary`（patched/skipped/failed/reason）**，无持仓或全部跳过时也留痕，供 15 监控判断巡检新鲜度；
- FAIL-OPEN，任何异常只记录不抛。
- 调用方：23 `exit_runner` 每轮入口。11 交易循环下线后这是存量持仓条件单的统一兜底。

### 7.5 职责边界

| 能力 | 归属 |
|---|---|
| 契约校验 / 幂等 / 路由 / 风控桥 / 审计 | 22 Gateway |
| 持仓数量与已实现盈亏真相源、冷却 | 22 PositionLedger |
| SL/TP 补挂、对账、幽灵仓清零 | 22（`sltp_reconcile` + `reconcile_ledger`/`close_ghost_position`） |
| 开仓闸门、定容、平仓决策、sz 解析 | 23 `execution/entry_loop.py`、`execution/exit_loop.py` |
| 最终风控与成交 | 13 `PreTradeGate` + OKX |

22 不感知策略语义；23 不直接调用交易所下单接口，也不写 11 的路径或数据文件。

