# 执行引擎中心 — 技术设计

> **版本**：v1.0 | **更新日期**：2026-10-11

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
- 复核（fail-closed，任一不过即跳过并落 `skips`）：kill-switch → 执行权 `live:50-bypass` → `mandate_id` 非空 → 标的 allowlist（`BTC-USDT-SWAP`）→ 单笔名义 ≤100 USDT、杠杆 ≤3 → 幂等 `runtime/x1_live_processed.json`。
- 执行：以子进程调用 11 `scripts/memory_l4/live_order_bridge.py`（22 不持有交易所密钥），bridge 负责下单与 SL/TP（OCO）并写 `11/runtime/live_order_audit.jsonl`。
- 账本：`audit/x1_live_fills.jsonl`，扁平字段 `ts/decision_id/source/mode/symbol/direction/confidence/position_pct/venue/order_placed/order_id/fill_px/request/result`。
- dry-run 语义：`--dry-run` 只打印不落 processed，便于重放真实执行。
