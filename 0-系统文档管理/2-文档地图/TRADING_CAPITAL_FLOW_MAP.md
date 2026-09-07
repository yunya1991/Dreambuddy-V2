# 交易实盘资金流和决策链路图 — TRADING_CAPITAL_FLOW_MAP

> **版本**: v1.0 | **更新日期**: 2026-09-03
> **定位**: 描述两个交易子系统实盘资金边界、daemon决策链路、持仓账本与支撑系统关系
> **关联**: [SYSTEM_MAP.md](./SYSTEM_MAP.md) · [ARCHITECTURE_MAP.md](./ARCHITECTURE_MAP.md)
> **数据快照**: 2026-09-03 13:50 北京时间进程列表 + 持仓文件

---

## 1. 核心结论

1. **两个OKX实盘账户独立运行**：易经推理系统使用账户A（API d988a164-…），V15马丁策略使用账户B（API 5af4066c-…），`OKX_SIMULATED=false` 均为实盘
2. **两个daemon各自管理持仓，互不直接通信**：易经管理5持仓（BTC/BMNR/PUMP/SNDK/SPCX），V15管理3持仓（ETH/SOL/BTC）
3. **BTC多头暴露重叠**：两个系统在不同账户都持有BTC LONG（易经 entry 77236 · V15 entry 76558），行情反转时双账户同步承压
4. **trailing_stop_runner 同时服务两系统**：16-调控系统的 PID 2003 以 `--real --interval 300` 运行，可能同时管理两个daemon的止损单
5. **认知系统为两系统提供经验支撑**：cognitive_daemon PID 4595 + MCP recall/record/verify

---

## 2. 资金流和决策链路

```
┌─────────────────┐      ┌─────────────────────────────┐      ┌────────────────────────┐
│  OKX 实盘账户 A  │ ───→ │  易经推理 daemon             │ ───→ │  持仓账本（5个）       │
│  API: d988a164   │      │  polling_trader.py          │      │  BTC · BMNR · PUMP    │
│  SIMULATED=false │      │  PID 86382 · 300s 轮询     │      │  SNDK · SPCX          │
│                 │      │  11-易经推理系统/            │      │  .workbuddy/…/        │
└─────────────────┘      │  scripts/memory_l4/        │      │  open_positions/      │
                         │                             │      └────────────────────────┘
                         │  功能链：                   │
                         │  BCRM2.0 + 八卦力学         │
                         │  + 五象力场 + CBR            │
                         │  + BDSM价值建仓 + A7门禁    │
                         │  + 五域战略层（道天地将法）  │
                         └─────────────────────────────┘

┌─────────────────┐      ┌─────────────────────────────┐      ┌────────────────────────┐
│  OKX 实盘账户 B  │ ───→ │  V15马丁 daemon             │ ───→ │  持仓账本（3个）       │
│  API: 5af4066c   │      │  light_poll + orchestrator  │      │  ETH · SOL · BTC ◀重叠 │
│  SIMULATED=false │      │  PID 4176(300s)/3795(900s) │      │  v15_state.json        │
│  .env.local      │      │  14-V15经典马丁策略/        │      └────────────────────────┘
│                 │      │                             │
└─────────────────┘      │  功能链：                   │
                         │  斐波那契回调 + 布林带       │
                         │  + RSI/MACD/ADX            │
                         │  + DirectionGate(MA128)     │
                         │  + TimingGate(Fib回撤评分)  │
                         │  + Phase D动态加仓          │
                         │  + V9基线红线               │
                         └─────────────────────────────┘

         ⚠ BTC多头暴露重叠：两系统都持有BTC LONG，方向同向叠加
```

---

## 3. 持仓明细

### 3.1 易经推理系统持仓（5个，账户A）

来源：`11-易经推理系统/.workbuddy/memory_l4/open_positions/`

| Inst ID | 方向 | Entry Price | Confidence | Source Tag | Strategy |
|---------|------|------------|------------|-----------|----------|
| BTC-USDT-SWAP | long | 77236.2 | 0.971 | bcrm | bcrm |
| BMNR-USDT-SWAP | long | 22.89 | 0.9577 | bcrm | bcrm |
| PUMP-USDT-SWAP | long | 0.004314 | 0.9907 | none | bcrm |
| SNDK-USDT-SWAP | long | 1483.47 | 0.9885 | none | bcrm |
| SPCX-USDT-SWAP | long | 139.85 | 0.8499 | none | bcrm |

### 3.2 V15马丁策略持仓（3个，账户B）

来源：`14-V15经典马丁策略/data/v15_state.json`

| Symbol | 方向 | Entry Price | Addons | TP% | Vol Mult |
|--------|------|------------|--------|-----|----------|
| ETH | LONG | 2470.22 | 0 | 0.0824 | 0.7 |
| SOL | LONG | 103.74 | 0 | 0.0938 | - |
| BTC | LONG | 76558.1 | 0 | 0.0396 | - |

### 3.3 BTC暴露重叠详情

| 系统 | Entry | 方向 | 账户 |
|------|-------|------|------|
| 易经 | 77236.2 | long | A |
| V15 | 76558.1 | LONG | B |

两个账户同向持多头，BTC下跌时双账户同步亏损。建议评估是否需要跨账户风险预算控制。

---

## 4. 支撑系统进程清单

来源：`ps aux` 快照 2026-09-03 13:50

| 进程 | PID | 启动时间 | 命令 | 职责 |
|------|-----|---------|------|------|
| cognitive_daemon | 4595 | Fri 10AM | `--watch . --interval 5 --debounce 8 --verbose` | 认知系统守护，git hook触发记忆闭环 |
| cognitive_mcp_server | 12440 | 今日02:45 | MCP server | 暴露 recall/record/verify/stats/health |
| trailing_stop_runner | 2003 | Fri 10AM | `--real --interval 300` | 16-调控系统移动止损，管理两系统止损单 |
| DreamOS start_scheduler | 2002 | Fri 10AM | `1-ARCHITECTURE/dreamos/cli/start_scheduler.py` | DreamOS A0-A9决策链调度 |
| DreamOS dynamic_evaluator | 4795 | Fri 10AM | `--interval 21600` | 动态评估器，6小时一次 |
| data_center_scheduler | 15193 | Tue 12AM | `18-数据获取中心/data_center_scheduler.py` | 数据中心调度 |
| data_server_fixed | 53594 | Sun 02PM | `11-易经推理系统/data_server_fixed.py` | 易经数据服务（1.1GB内存） |
| start_phase2_repair | 1985 | Fri 10AM | `subsystems/llm_department/start_phase2_repair_scheduler.py` | LLM部门修复调度 |
| frontend_skeleton | 1996 | Fri 10AM | `uvicorn …:app --port 8125` | 前端骨架API |

---

## 5. 关键风险点

### 5.1 BTC多头暴露重叠（P0）

两个独立OKX账户都持有BTC LONG，行情反转时双账户同步承压。当前无跨账户风险预算控制。

**建议**：
- 评估跨账户总BTC暴露上限
- 或在 trailing_stop_runner 中增加跨账户同symbol暴露检测

### 5.2 trailing_stop_runner跨系统管理边界（P1）

PID 2003 以 `--real` 模式运行，可能同时管理两个daemon的止损单。需确认：
- 止损单是否按账户隔离
- 是否存在误触对方账户持仓的风险

### 5.3 两daemon未通过launchd管理（P1）

当前通过 bash while 循环（PID 4176/3795）和 `python -m` 直接启动（PID 86382），机器重启后不会自动恢复。launchd plist 存在但未加载：
- `com.dreambuddy.yijing.polling-trader.plist`
- `com.dreambuddy.v15_light_poll.plist`
- `com.dreambuddy.v15_orchestrator.plist`

**建议**：确认 launchd 未加载原因，或改用 bash 循环 + launchd KeepAlive 双保险。

### 5.4 V15 .env.v15 配置曾缺失（已修复）

记忆 VM-1786327018938 记录 `.env.v15` 从未创建，现已在 `14-V15经典马丁策略/config/.env.v15` 创建（2026-09-01 01:38），配置缺口已修复。

---

## 6. 文档对齐清单（P0-1 产出）

本文档基于实际进程快照和持仓文件，对齐以下代码实现：

- [x] 易经 polling_trader.py daemon 实盘运行状态
- [x] V15 light_poll + orchestrator 双进程架构
- [x] 两个OKX实盘账户独立运作
- [x] 持仓账本路径（.workbuddy/open_positions vs v15_state.json）
- [x] trailing_stop_runner 跨系统服务关系
- [x] 认知系统支撑角色
- [ ] polling_trader.py 内部决策链路（P1-1 待产出）
- [ ] V15 v15_trader.py 内部决策链路（P1 待产出）

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-09-03 | v1.0 | 首版，基于进程快照和持仓文件建立资金流图，识别BTC重叠风险 |
