# 工程索引 — V15 经典马丁策略

> **定位：** 模块级工程索引（L2），对齐系统 `2-KNOWLEDGE/4-OPERATIONS/索引体系.md` 的 Z 轴三层规范
> **版本：** v4.1 | **更新：** 2026-07-13 | **维护者：** DreamBuddy v2

---

## 目录

- [1. 模块定位](#1-模块定位)
- [2. 目录地图](#2-目录地图)
- [3. 文件清单与职责](#3-文件清单与职责)
- [4. 16项技术指标清单](#4-16项技术指标清单)
- [5. 贝叶斯优化参数](#5-贝叶斯优化参数8个)
- [6. 核心流程索引](#6-核心流程索引)
- [7. 配置参数索引](#7-配置参数索引)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 14 |
| 模块名称 | V15 经典马丁策略 |
| 策略类型 | 马丁格尔 + 纯技术分析 + 智能资金管理 |
| 交易方向 | 只做多 |
| 交易周期 | 4H |
| 最大加仓 | 3次（共4层仓位） |
| 监控币种 | 34个（BTC,ETH,SOL,BNB,XRP,ADA,DOGE,LTC,LINK,AVAX,DOT,UNI,NEAR,APT,ARB,OP,INJ,SUI,SEI,TIA,AAVE,COMP,CRV,DYDX,LDO,PEPE,SAND,SHIB,STX,SUSHI,WLD,ZEC,OKB,HYPE） |
| 依赖关系 | 独立模块，依赖 10-经典指标系统（超时离场切换） |
| 数据来源 | OKX API（实盘/模拟盘） |
| 前端展示 | `experiments/ab-trading/monitor.html` 的"马丁策略" Tab（8765端口） |

### 核心架构（7大模块）

| 模块 | 核心功能 | 关键算法/指标 |
|------|----------|---------------|
| 入场信号系统 | 16层入场决策 | Fib/布林/RSI/MACD/ADX/Pivot/OBV/SuperTrend/Keltner/StochRSI/Vortex/TEMA/GoldenCross/EMA排列（16项） |
| 参数设置 | BTC固定 + 波动率放大 | 止盈/加仓间距/止损按30日波动率调整 |
| 趋势强度计算器 | Elder-ray三重滤网 | EMA13斜率 + Bull/Bear Power + 背离检测 + 力度衰竭 |
| 资金管理器 | 智能资金分配 | 22%底仓+5x杠杆+加仓分配（Elder-ray趋势强度 × 信号置信度 × 波动率 → 每币种预算） |
| 动态止损 | 日线/周线MA200风控 | 价格跌破所有均线禁止开仓，保护已有持仓 |
| 持仓超时与离场 | 分层计时 + 经典离场切换 | 底仓48h / 加仓后24h + 黄金窗口12h → 切换ClassicExitSystem（CLOSE/REDUCE/RAISE_TP/HOLD） |
| 贝叶斯参数优化 | 8参数寻优 | 基于回测数据+资金效率评分，资金分配 + 最佳持仓时间 + 最大持仓数 → 最大化卡尔马比率 |
| 三屏趋势过滤器 | 周线+日线MA104趋势一致性 | both_bear模式：双周期看空时禁止开多 |

---

## 2. 目录地图

### 2.1 V15 独立运行系统（14-V15经典马丁策略/）— 当前运行版本

```
14-V15经典马丁策略/
├── run.py                         统一入口（signal/backtest/trader/capital_engine/test/config）
├── README.md                      用户文档
├── config/
│   ├── .env.common                公共配置（OKX密钥/资金参数/马丁基础参数）
│   ├── .env.v15                   V15专属配置（币种池/风控阈值/超时离场）
│   └── .env.v15ct                 V15CT配置（历史兼容）
├── core/                          核心策略层
│   ├── v15_signal.py              信号引擎 — 16层入场决策 + 16项技术指标
│   ├── v15_trader.py              自动交易器 — 轮询/开仓/加仓/止盈止损/超时离场
│   └── v15_backtest.py            回测引擎 — 历史K线回测 + 绩效统计
├── lib/                           基础工具层
│   ├── config_loader.py           配置加载器（支持 include 语法）
│   ├── okx_client.py              OKX 交易客户端（实盘/模拟/REST API）
│   ├── market_data.py             K线数据获取 + 基础指标
│   ├── strategy_params.py         动态参数：动态止损+波动率+Elder-ray趋势强度
│   ├── capital_manager.py         资金管理：智能分配+仓位成本+并发控制+风控
│   ├── capital_manager_engine.py  资金管理引擎：回测+趋势+贝叶斯优化+月度报告
│   ├── bayesian_optimizer.py      贝叶斯参数优化器（8参数，三轮反馈迭代）
│   └── symbol_mapper.py           币种映射工具
├── tests/                         测试套件
│   ├── test_v15_system.py         系统测试
│   ├── test_v15_stress.py         多场景压力测试
│   └── test_symbol_mapper.py      币种映射测试
├── data/
│   ├── v15_state.json             交易状态持久化
│   ├── backtest_cache/            回测K线缓存
│   ├── capital_manager/           资金管理引擎数据（优化历史/状态/报告）
│   └── okx_client/                OKX客户端数据
├── docs/                          技术文档
│   ├── ENGINEERING_INDEX.md       本文件 — 工程索引
│   ├── TECHNICAL_DESIGN.md        技术设计文档（架构/数据流/算法）
│   └── API_SPEC.md                接口规格文档
└── com.dreambuddy.v15_trader.plist  launchd 守护进程配置
```

### 2.2 V15-CT 实战代码（experiments/ab-trading/）— ⚠️ 已废弃

> V15-CT 实验版已废弃，代码保留作为AB对照参考。独立V15系统（§2.1）为当前运行版本。
> master_daemon 现通过 `run.py poll_once` 调用独立V15系统。

```
experiments/ab-trading/
├── v15ct_signal.py                V15-CT 信号引擎（实验版，已迁移到独立系统）
├── v15ct_trader.py                V15-CT 自动交易器（实验版）
├── capital_manager_engine.py      资金管理引擎（已迁移到 lib/）
├── bayesian_optimizer.py          贝叶斯参数优化器（已迁移到 lib/）
├── monitor.html                   前端监控页面（8765端口，"马丁策略"Tab）
├── data_server.py                 数据服务（/api/v15-ct/* 接口）
└── ...
```

**当前运行版本：** master_daemon 每小时调用 `run.py poll_once`（独立V15系统）

**代码统计：** V15独立运行系统 14 个核心文件，约 8000+ 行；V15-CT实验代码作为AB对照保留

---

## 3. 文件清单与职责

### 3.1 核心层（core/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `v15_signal.py` | ~25 | 信号引擎：16项技术指标 + 16层入场决策 | `v15_decision()`, `calc_sma()`, `calc_rsi()`, `calc_fibonacci()`, `calc_bollinger_bands()`, `calc_macd()`, `calc_adx()`, `determine_position()`, `calc_pivot_points()`, `calc_obv()`, `calc_supertrend()`, `calc_keltner_channel()`, `calc_stochrsi()`, `calc_vortex()`, `calc_tema()`, `calc_golden_cross()`, `calc_ema_align()` |
| `v15_trader.py` | ~20 | 自动交易器：轮询信号、开仓（智能资金分配）、加仓、止盈、动态止损、超时离场（切换经典系统）、状态持久化 | `run_poll_cycle()`, `execute_open_position()`, `execute_addon()`, `check_take_profit()`, `check_time_exit()`, `_get_dynamic_params()`, `trigger_capital_rebuild()` |
| `v15_backtest.py` | ~25 | 回测引擎：历史K线回测、绩效统计、超时离场模拟 | `run_backtest()`, `v15_decision()`, `print_report()`, `get_ma200_stop_loss()`, `get_vol_adjusted_params()` |

### 3.2 工具层（lib/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `config_loader.py` | 8 | 配置加载：支持 include 语法、类型解析、环境变量注入 | `load_config()`, `get_config()`, `get_config_float()`, `get_config_int()`, `get_config_list()`, `get_config_bool()` |
| `okx_client.py` | — | OKX REST API 客户端：下单/查仓/查余额/K线获取 | `OKXSimulatedClient`（类，含 `place_order()`, `get_positions()`, `get_balance()`, `get_kline()` 等） |
| `market_data.py` | 7 | K线获取（OKX API/CLI双路降级）+ 基础指标 | `fetch_candles()`, `calc_sma()`, `calc_ema()`, `calc_rsi()` |
| `strategy_params.py` | ~15 | 动态参数：动态止损 + 波动率自适应 + Elder-ray趋势强度 | `get_dynamic_stop_loss()`, `get_vol_adjusted_params()`, `get_coin_strategy_params()`, `calc_elder_ray()`, `calc_daily_ma200()`, `calc_30d_volatility()`, `check_trend_filter()` |
| `capital_manager.py` | ~12 | 资金管理：智能分配 + 仓位成本 + 并发控制 + 风险评级 | `calculate_per_coin_allocation()`, `calculate_capital_allocation()`, `calculate_single_position_cost()`, `get_account_balance()`, `get_current_positions()` |
| `capital_manager_engine.py` | ~15 | 资金管理引擎：回测+趋势过滤+贝叶斯优化+月度报告+HTTP API | `CapitalManagerEngine`（类，含 `run_monthly()`, `run_optimization()`, `get_status()`, `check_open_permission()`） |
| `bayesian_optimizer.py` | ~15 | 贝叶斯参数优化：8参数，三轮反馈迭代，最大化卡尔马比率 | `V15CapitalOptimizer`（类，含 `iterate_optimize()`, `_objective()`, `_run_backtest_evaluation()`） |
| `symbol_mapper.py` | — | 币种映射工具 | `to_swap()`, `to_spot()` |

### 3.3 入口层

| 文件 | 子命令 | 职责 |
|------|--------|------|
| `run.py` | `signal` | 查看单币种/全币种信号决策 |
| | `backtest` | 运行回测（指定币种+K线数量） |
| | `trader` | 启动自动交易器（轮询模式） |
| | `capital_engine` | 资金管理引擎（monthly/status/trend/check/api） |
| | `test` | 运行全部测试套件 |
| | `config` | 查看当前配置 |

---

## 4. 16项技术指标清单

| Tier | 指标 | 函数 | 说明 | 置信度 |
|------|------|------|------|--------|
| 1 | Fib黄金区+布林双确认 | `calc_fibonacci()` + `calc_bollinger_bands()` | Fib 50%-61.8% + 布林中轨/下轨 | 80% |
| 2 | Fib黄金区 | `calc_fibonacci()` | Fib 50%-61.8% 回调 | 75% |
| 3 | Fib浅区 | `calc_fibonacci()` | Fib 38.2%-50% 回调 | 60% |
| 4 | 布林中轨回调 | `calc_bollinger_bands()` | 价格回调至布林中轨 + RSI<50 | 65% |
| 5 | RSI超卖 | `calc_rsi()` | RSI<45 多头动能持续 | 60% |
| 6 | MACD多头扩张 | `calc_macd()` | MACD>0 且柱状图扩张 | 68% |
| 7 | ADX强趋势 | `calc_adx()` | ADX>25 且 +DI > -DI | 70% |
| 8 | Pivot支撑区 | `calc_pivot_points()` | 价格在S1~Pivot支撑区 | 62% |
| 9 | OBV多头加速 | `calc_obv()` | OBV>均线 且 加速上升 | 66% |
| 10 | SuperTrend多头 | `calc_supertrend()` | SuperTrend趋势向上 | 64% |
| 11 | Keltner下沿/中线 | `calc_keltner_channel()` | Keltner Channel 下沿或中线 | 61% |
| 12 | StochRSI金叉/超卖 | `calc_stochrsi()` | StochRSI 金叉或超卖 | 63% |
| 13 | Vortex多头反转 | `calc_vortex()` | Vortex VI+ > VI- 且反转 | 65% |
| 14 | TEMA多头趋势 | `calc_tema()` | 三重EMA 多头且斜率向上 | 64% |
| 15 | GoldenCross金叉 | `calc_golden_cross()` | EMA50 > EMA200 金叉 | 72% |
| 16 | EMA排列多头 | `calc_ema_align()` | EMA20 > EMA50 > EMA200 完美排列 | 75% |

---

## 5. 贝叶斯优化参数（8个）

| 参数 | 范围 | 说明 | 来源 | 配置键 |
|------|------|------|------|--------|
| `base_position_pct` | 0.22（固定，用户经验值） | 底仓资金比例 | 贝叶斯优化 | `V15_BASE_POSITION_PCT` |
| `addon1_pct` | 0.10-0.30 | 加仓1资金比例（黑天鹅第一档） | 贝叶斯优化 | `V15_ADDON1_PCT` |
| `addon2_pct` | 0.03-0.10 | 加仓2资金比例 | 贝叶斯优化 | `V15_ADDON2_PCT` |
| `addon3_pct` | 0.05-0.20 | 加仓3资金比例 | 贝叶斯优化 | `V15_ADDON3_PCT` |
| `max_concurrent_positions` | 2-8 | 最大持仓币种数 | 贝叶斯优化 | `V15_MAX_CONCURRENT_POSITIONS` |
| `max_base_holding_hours` | 24-96h | 底仓最大持仓时间 | 贝叶斯优化 | `V15_MAX_BASE_HOLDING_HOURS` |
| `max_post_addon_hours` | 12-48h | 加仓后最大持仓时间 | 贝叶斯优化 | `V15_MAX_POST_ADDON_HOURS` |
| `golden_window_hours` | 4-24h | 黑天鹅反弹黄金窗口 | 贝叶斯优化 | `V15_GOLDEN_WINDOW_HOURS` |

**固定参数（不参与优化）：**
- BTC 基础参数：底仓22%，5x杠杆，止盈4%（BTC固定），其他币种按波动率放大
- 其他币种：止盈/加仓间距按30日波动率放大
- 趋势过滤器：both_bear + MA104（周线+日线MA104都看空时禁止开多）
- 底仓比例22%和杠杆5x为用户经验值，固定不参与优化

---

## 6. 核心流程索引

### 6.1 开仓流程（信号 → 资金 → 下单）

```
run_poll_cycle()
  └─→ 收集无持仓币种信号
       └─→ v15_decision(coin)  ← 入场信号系统（16层决策）
            ├─ 16项技术指标计算
            ├─ 4H均线位置判定
            └─→ OPEN_BULL + confidence
                 │
                 └─→ _get_dynamic_params(coin)  ← 参数设置 + 趋势强度
                      ├─ 波动率自适应参数（止盈/加仓间距）
                      ├─ 动态止损（MA200族）
                      └─ Elder-ray趋势强度（日线）
                           │
                           └─→ calculate_per_coin_allocation()  ← 资金管理器
                                ├─ 最大持仓数检查
                                ├─ Elder-ray强度调整 (0.3x-1.5x)
                                ├─ 置信度调整 (0.5x-1.5x)
                                ├─ 波动率反向调整 (0.5x-1.5x)
                                ├─ 每币种预算 + 3次加仓分配
                                └─ 下跌保证金缓冲检查
                                     │
                                     └─→ execute_open_position()  ← 交易执行
                                          ├─ 动态止损检查
                                          ├─ 三屏趋势过滤检查（both_bear + MA104）  ← 新增
                                          │    └─ 周线+日线MA104都看空 → 禁止开多
                                          ├─ 下单量计算
                                          └─ 状态持久化
```

### 6.2 持仓管理流程（止盈 → 止损 → 加仓 → 超时离场）

```
每个持仓币种轮询:
  ├─→ check_take_profit()
  │    ├─ 止盈检查 → 触发则平仓
  │    └─ 动态止损检查 → 触发则平仓
  │
  ├─→ 未止盈止损 → execute_addon()
  │    └─ 跌幅达标 → 加仓（最多3次）
  │
  └─→ check_time_exit()  ← 持仓超时与离场系统
       ├─ 分层计时（底仓/加仓后）
       ├─ 黄金窗口判断
       ├─ 超时判断
       └─ 超时 → 切换经典离场系统（ClassicExitSystem）
            ├─ CLOSE    → 平仓
            ├─ REDUCE   → 减仓
            ├─ RAISE_TP → 提高止盈
            └─ HOLD     → 继续持有
```

### 6.3 月度优化流程（贝叶斯参数寻优）

```
CapitalManagerEngine.run_monthly()
  ├─→ run_backtest()  ← 回测引擎（统计各层触发频率和收益特征）
  ├─→ check_trend_filter()  ← 三屏趋势过滤
  ├─→ run_optimization()  ← 贝叶斯优化器
  │    ├─ 基于回测数据的资金效率评分
  │    ├─ 趋势过滤参数寻优（both_bear + MA104）
  │    └─ 最大化卡尔马比率
  └─→ _update_config_file()  ← 写入配置
```

### 6.4 连续亏损触发流程（事件驱动）

```
v15_trader.py 止损平仓时:
  ├─ consecutive_losses += 1
  ├─ 止盈时 consecutive_losses = 0（重置）
  └─ consecutive_losses >= 3
       └─ 异步触发 capital_manager_engine.py monthly
            └─ 重置 consecutive_losses = 0
```

---

## 7. 配置参数索引

### 7.1 核心配置文件

| 文件 | 作用 | 关键参数 |
|------|------|----------|
| `config/.env.common` | 公共配置 | OKX密钥、杠杆、最小保证金 |
| `config/.env.v15` | V15专属配置 | 币种池、资金参数、风控阈值、超时离场 |
| `config/.env.v15ct` | V15CT配置 | 历史兼容，已迁移至独立系统 |

### 7.2 关键环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `V15_COINS` | 34个币种 | 监控交易对列表 |
| `V15_POLL_INTERVAL` | 3600s | 轮询间隔 |
| `V15_LEVERAGE` | 5 | 杠杆倍数 |
| `V15_BASE_POSITION_PCT` | 0.22 | 底仓资金比例 |
| `V15_MAX_CONCURRENT_POSITIONS` | 6 | 最大并发持仓数 |
| `V15_MAX_BASE_HOLDING_HOURS` | 48 | 底仓最大持仓时间(h) |
| `V15_MAX_POST_ADDON_HOURS` | 24 | 加仓后最大持仓时间(h) |
| `V15_GOLDEN_WINDOW_HOURS` | 12 | 黑天鹅反弹黄金窗口(h) |
| `V15_DAILY_LOSS_LIMIT` | -50 | 日亏损限制(USDT) |
| `V15_MAX_CONSECUTIVE_LOSSES` | 3 | 连续亏损3次触发资金管理引擎重新优化 |
| `V15_TREND_FILTER_MODE` | both_bear | 趋势过滤模式（none/both_bear） |
| `V15_TREND_FILTER_PERIOD` | 104 | 趋势过滤MA周期 |
| `V15_ADDON1_PCT` | 0.20 | 加仓1资金比例 |
| `V15_ADDON2_PCT` | 0.05 | 加仓2资金比例 |
| `V15_ADDON3_PCT` | 0.10 | 加仓3资金比例 |
| `V15CT_CONFIDENCE_THRESHOLD` | 30 | V15-CT 信号置信度阈值 |

---

_最后更新：2026-07-13 | 维护者：DreamBuddy v2_
