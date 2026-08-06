# 工程索引 — V15 经典马丁策略

> **定位：** 模块级工程索引（L2），对齐系统 `2-KNOWLEDGE/4-OPERATIONS/索引体系.md` 的 Z 轴三层规范
> **版本：** v6.0 | **更新：** 2026-08-06 | **维护者：** DreamBuddy v2
> **v15-final 最终形态：** Phase B+（A+基线 + 子形态微调），Phase C（易经）默认关闭

---

## 目录

- [1. 模块定位](#1-模块定位)
- [2. 目录地图](#2-目录地图)
- [3. 文件清单与职责](#3-文件清单与职责)
- [4. 16项技术指标清单](#4-16项技术指标清单)
- [5. 贝叶斯优化参数](#5-贝叶斯优化参数8个智能系统参数)
- [6. 核心流程索引](#6-核心流程索引)
- [7. 配置参数索引](#7-配置参数索引)
- [8. 智能系统增强与双基线版本管理](#8-智能系统增强与双基线版本管理)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 14 |
| 模块名称 | V15 经典马丁策略 |
| 策略类型 | 马丁格尔 + 纯技术分析 + 智能资金管理 + 智能系统增强 |
| 交易方向 | 多空双向（BTC用DirectionGate MA128+自身MA200，其他币用BTC风向标3日确认+short_only） |
| 交易周期 | 4H |
| 最大加仓 | 3次（共4层仓位） |
| 监控币种 | 30个（大市值+中等市值，已剔除小市值/meme/新币：PEPE/SHIB/SUSHI/WLD/APE） |
| 智能系统 | Phase A+：ATR动态止盈 + 移动止盈 + ELDER-RAY资金调度(0.9-1.5x) + BTC风向标智能模式 |
|  | Phase B+（启用）：BULL/BEAR × Elder-ray 6类子形态微调（TP×1.05-1.15/0.85-0.95，持仓×1.05-1.10/0.85-0.95） |
|  | Phase C（默认关闭）：易经推理桥接 + risk/value 插值（模块化保留，V15_YIJING_ENABLED=true 启用） |
| 版本管理 | 双基线：固定参数基线(138%) + 智能参数基线(210.4%) + 贝叶斯优化双层节奏（60天参数空间+6天易经插值） |
| 依赖关系 | 独立模块，依赖 10-经典指标系统（超时离场切换）+ 11-易经推理系统（Phase C桥接） |
| 数据来源 | OKX API（实盘/模拟盘） |
| 前端展示 | `experiments/ab-trading/monitor.html` 的"马丁策略" Tab（8765端口） |

### 核心架构（15大模块，v6.0）

| 模块 | 核心功能 | 关键算法/指标 |
|------|----------|---------------|
| 币种风控过滤 | 市值等级+上线时间双重过滤 | MarketCapTier(LARGE/MID/SMALL) + listing_date ≥ 365天 |
| 入场信号系统 | 16层入场决策 | Fib/布林/RSI/MACD/ADX/Pivot/OBV/SuperTrend/Keltner/StochRSI/Vortex/TEMA/GoldenCross/EMA排列（16项） |
| 参数设置 | BTC固定 + 波动率放大 + ATR动态止盈 | 止盈/加仓间距/止损按30日波动率调整，ATR因子动态微调 |
| 趋势强度计算器 | Elder-ray三重滤网 | EMA13斜率 + Bull/Bear Power + 背离检测 + 力度衰竭 |
| 资金管理器 | 智能资金分配 + ELDER-RAY资金调度 | 22%底仓+5x杠杆+加仓分配（Elder-ray趋势强度 × 信号置信度 × 波动率 → 每币种预算） |
| 多空方向控制 | DirectionGate + BTC风向标智能模式 | BTC用MA128三状态模型，其他币用BTC风向标3日确认+short_only |
| ATR动态止盈 | BTC 4%基准 + ATR因子 | `calc_atr()` + `get_vol_adjusted_params()` |
| 移动止盈 | 浮盈达80%启动，回撤N×ATR止盈 | `trailing_atr_mult`(1.0-2.5) + `trailing_start_ratio`(0.3-0.8) |
| 动态止损 | 日线/周线MA200风控 | 价格跌破所有均线禁止开仓，保护已有持仓 |
| OCO止盈止损挂单 | 交易所层面条件单同步 | 开仓/加仓同步挂OCO单 + 轮询动态更新 + 平仓前撤单 |
| 持仓超时与离场 | 分层计时 + 经典离场切换 | 底仓48h / 加仓后24h + 黄金窗口12h → 切换ClassicExitSystem（CLOSE/REDUCE/RAISE_TP/HOLD） |
| **Phase B+ 子形态微调** | **BULL/BEAR × Elder-ray 6类子形态** | **3-bar mode 平滑；TP×1.05-1.15/0.85-0.95；持仓×1.05-1.10/0.85-0.95（v15-final启用）** |
| **Phase C 易经推理桥接** | **risk/value 插值 & 币种过滤（默认关闭）** | **K线转8维评分→易经推理→risk连续化→参数插值clamp[0.75,1.25]；前向填充+中性区；模块化保留** |
| 贝叶斯参数优化 | 8参数智能系统寻优 + 自动回退 + 双层节奏 | 智能系统参数(ATR/移动止盈/ELDER-RAY/风向标) + 持仓时间 → 最大化卡尔马比率；60天参数空间+6天易经插值 |
| 贝叶斯自动调度 | orchestrator集成 + 双基线版本管理 | 连亏3笔+每月触发+24h冷却期+PID锁+自动回退验证 |

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
│   ├── v15_signal.py              信号引擎 — 16层入场决策 + 16项技术指标 + SubMorph子形态分类
│   ├── v15_signal_engine.py       信号引擎（新架构：入场判定+趋势强度+子形态）
│   ├── v15_trader.py              自动交易器 — 轮询/开仓/加仓/止盈止损/超时离场 + V15_YIJING_ENABLED开关
│   ├── v15_backtest.py            回测引擎 — 历史K线回测 + 绩效统计 + Phase A+/B+/C + 前向填充
│   ├── v15_monitor.py             状态监控 + 可视化 + 每日摘要锁
│   └── walk_forward_validator.py  Phase C 5段 walk-forward 验证框架（全段退化<5%通过）
├── lib/                           基础工具层
│   ├── config_loader.py           配置加载器（支持 include 语法）
│   ├── okx_client.py              OKX 交易客户端（实盘/模拟/REST API）
│   ├── market_data.py             K线数据获取 + 基础指标
│   ├── strategy_params.py         动态参数：动态止损+波动率+Elder-ray趋势强度+ATR计算
│   ├── strategy_utils.py          通用指标与校验函数
│   ├── position_config.py         币种差异化配置 + ATR动态止盈
│   ├── fund_manager.py            资金管理：智能分配+仓位成本+并发控制+风控 + ELDER-RAY调度 + OCO
│   ├── capital_manager.py         资金管理（旧版，兼容保留）
│   ├── capital_manager_engine.py  资金管理引擎：回测+趋势+贝叶斯优化+月度报告
│   ├── direction_gate.py          多空方向控制 + BTC风向标智能模式 + DirectionGate
│   ├── adaptive_exit.py           超时离场 + 经典离场切换
│   ├── bayesian_optimizer.py      贝叶斯参数优化器（8参数智能系统+双基线+自动回退+双层节奏）
│   ├── kelly_optimizer.py         凯利公式底仓优化（半凯利+收缩估计，默认关闭）
│   ├── symbol_mapper.py           币种映射工具
│   ├── yijing_bridge.py           Phase C 易经推理桥接（importlib跨目录加载，可被外部调用）
│   ├── yijing_param_interpolator.py # Phase C risk/value 参数插值（clamp[0.75,1.25] + 中性区）
│   └── coin_selector.py           Phase C 币种过滤（DANGER剔除 + net_value排序）
├── tests/                         测试套件
│   ├── test_v15_system.py         系统测试
│   ├── test_v15_stress.py         多场景压力测试
│   └── test_symbol_mapper.py      币种映射测试
├── data/
│   ├── v15_state.json             交易状态持久化
│   ├── v15_final_deployment.json  v15-final 最终部署快照（决策依据+激活配置+模块保留）
│   ├── backtest_cache/            回测K线缓存
│   ├── capital_manager/           资金管理引擎数据（优化历史/状态/报告）
│   ├── bayesian_opt/              贝叶斯优化数据（active_params.json/schedule_state.json/优化历史）
│   ├── okx_client/                OKX客户端数据
│   └── yijing_cache/             Phase C 易经推理缓存（按币种/日期分片）
├── docs/                          技术文档
│   ├── ENGINEERING_INDEX.md       本文件 — 工程索引
│   ├── TECHNICAL_DESIGN.md        技术设计文档（架构/数据流/算法 + Phase A+/B+/C演进）
│   ├── CONFIGURATION_GUIDE.md     配置管理规范（含V15_YIJING_ENABLED）
│   ├── CHANGELOG.md                变更日志（含v6.0演进历程）
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
| `v15_signal.py` | ~25 | 信号引擎：16项技术指标 + 16层入场决策 + SubMorph子形态6分类 | `v15_decision()`, `calc_sma()`, `calc_rsi()`, `calc_fibonacci()`, `calc_bollinger_bands()`, `calc_macd()`, `calc_adx()`, `determine_position()`, `calc_pivot_points()`, `calc_obv()`, `calc_supertrend()`, `calc_keltner_channel()`, `calc_stochrsi()`, `calc_vortex()`, `calc_tema()`, `calc_golden_cross()`, `calc_ema_align()`, `detect_sub_morphology()` |
| `v15_signal_engine.py` | ~12 | 信号引擎（新架构）：入场判定+趋势强度+SubMorph子形态 | `SignalEngine`（类），`evaluate_entry()`, `calc_trend_strength()`, `get_sub_morphology()` |
| `v15_trader.py` | ~25 | 自动交易器：轮询信号、开仓（智能资金分配）、加仓、止盈、动态止损、超时离场、OCO挂单同步、多空方向控制、币种风控过滤、状态持久化 + **V15_YIJING_ENABLED开关** + 前向填充 | `run_poll_cycle()`, `execute_open_position()`, `execute_addon()`, `check_take_profit()`, `check_time_exit()`, `_sync_tp_sl_orders()`, `_update_tp_sl_dynamic()`, `_get_direction_ctx()`, `_get_dynamic_params()`, `_get_yiji_bridge()`, `_apply_yijing_multipliers()` |
| `v15_backtest.py` | ~30 | 回测引擎：历史K线回测、绩效统计、超时离场模拟 + **Phase A+/B+/C切换** + 易经前向填充 + walk-forward集成 | `run_backtest()`, `v15_decision()`, `print_report()`, `get_ma200_stop_loss()`, `get_vol_adjusted_params()`, `prepare_ma128_for_4h()`, `_apply_phase_multipliers()`, `_get_sub_morph_multipliers()` |
| `v15_monitor.py` | ~10 | 状态监控 + 可视化 + 每日摘要锁 | `generate_daily_report()`, `render_status_html()`, `lock_daily_summary()` |
| `walk_forward_validator.py` | ~8 | Phase C 5段 walk-forward 验证框架：全段退化<5%才通过 | `split_walk_forward()`, `validate_segment()`, `run_full_validation()`, `print_wf_report()` |
| `direction_gate.py` | ~5 | 多空方向控制：MA128+BTC风向标三状态模型 | `DirectionGate`（类，含 `evaluate()`），`GateResult`（数据类），`MarketRegime`/`TradeDirection`（枚举） |

### 3.2 工具层（lib/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `config_loader.py` | 8 | 配置加载：支持 include 语法、类型解析、环境变量注入 | `load_config()`, `get_config()`, `get_config_float()`, `get_config_int()`, `get_config_list()`, `get_config_bool()` |
| `okx_client.py` | — | OKX REST API 客户端：下单/查仓/查余额/K线获取/OCO止盈止损 | `OKXSimulatedClient`（类，含 `place_order()`, `get_positions()`, `get_balance()`, `get_kline()`, `place_stop_loss_take_profit()`, `cancel_algo_orders()`） |
| `market_data.py` | 7 | K线获取（OKX API/CLI双路降级）+ 基础指标 | `fetch_candles()`, `calc_sma()`, `calc_ema()`, `calc_rsi()` |
| `strategy_params.py` | ~16 | 动态参数：动态止损 + 波动率自适应 + Elder-ray趋势强度 + MA128计算 | `get_dynamic_stop_loss()`, `get_vol_adjusted_params()`, `get_coin_strategy_params()`, `calc_elder_ray()`, `calc_daily_ma200()`, `calc_daily_ma128()`, `calc_30d_volatility()`, `check_trend_filter()` |
| `strategy_utils.py` | ~10 | 通用指标与校验函数 | `validate_coin()`, `check_volume_spike()`, `normalize_price()` |
| `position_config.py` | ~6 | 币种差异化配置 + ATR动态止盈 | `get_coin_config()`, `get_atr_adjusted_tp()`, `get_position_bands()` |
| `fund_manager.py` | ~12 | 资金管理：智能分配 + 仓位成本 + 并发控制 + 风控 + ELDER-RAY调度 + OCO管理 | `FundManager`（类），`allocate_per_coin()`, `elder_ray_scheduler()`, `sync_oco_orders()` |
| `capital_manager.py` | ~12 | 资金管理（旧版兼容）：智能分配 + 仓位成本 + 并发控制 + 风险评级 | `calculate_per_coin_allocation()`, `calculate_capital_allocation()`, `calculate_single_position_cost()`, `get_account_balance()`, `get_current_positions()` |
| `capital_manager_engine.py` | ~15 | 资金管理引擎：回测+趋势过滤+贝叶斯优化+月度报告+HTTP API | `CapitalManagerEngine`（类，含 `run_monthly()`, `run_optimization()`, `get_status()`, `check_open_permission()`） |
| `direction_gate.py` | ~5 | 多空方向控制 + BTC风向标智能模式 + DirectionGate | `DirectionGate`（类，含 `evaluate()`） |
| `adaptive_exit.py` | ~8 | 超时离场 + 经典离场切换（CLOSE/REDUCE/RAISE_TP/HOLD） | `AdaptiveExit`（类），`check_timeout()`, `switch_to_classic_exit()` |
| `bayesian_optimizer.py` | ~18 | 贝叶斯参数优化：8参数智能系统，三轮反馈迭代，自动回退验证，双基线版本管理 + **双层节奏（60天参数空间+6天易经插值）** | `V15CapitalOptimizer`（类），`should_trigger_optimization()`, `run_optimization_with_rollback()`, `rollback_to_baseline()`, `rollback_to_fixed_baseline()`, `print_version_info()`, `SCHEDULE_CONFIG` |
| `kelly_optimizer.py` | — | 凯利公式底仓优化：半凯利+收缩估计（默认关闭） | `KellyOptimizer`（类） |
| `symbol_mapper.py` | — | 币种映射工具 + 马丁风控过滤（市值等级+上线时间） | `to_swap()`, `to_spot()`, `is_martin_safe()`, `filter_martin_safe()`, `get_market_cap_tier()`, `get_listing_date()` |
| `yijing_bridge.py` | ~12 | **Phase C 易经推理桥接（模块化，可被外部调用）**：importlib跨目录加载YijingEngine，K线转8维归一化评分，批量/单次推理+缓存，risk_score连续化（卦象锚点+8维评分微调），前向填充 | `YijingBridge`（类），`batch_infer()`, `infer_once()`, `_compute_continuous_risk()`, `_build_8dim_scores()`, `forward_fill()` |
| `yijing_param_interpolator.py` | ~6 | **Phase C 参数插值**：risk/value→TP/持仓/仓位插值，与子形态倍数叠加，clamp[0.75,1.25]，中性区（\|net_value\|<0.12）不调整 | `interpolate_params()`, `compute_yijing_multipliers()`, `_NEUTRAL_THRESHOLD` |
| `coin_selector.py` | ~5 | **Phase C 币种过滤**：易经因子过滤（DANGER剔除），按net_value排序，优先TREND_FRIENDLY | `filter_coins_by_yijing()`, `rank_by_net_value()`, `classify_coin_risk_value()` |

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

## 5. 贝叶斯优化参数（8个智能系统参数）

> **v5.0 更新：** 优化参数从旧的资金分配参数（addon1/2/3_pct等）切换为智能系统核心参数（ATR/移动止盈/ELDER-RAY/风向标）。

| 参数 | 范围 | 说明 | 类别 | 智能基线值 |
|------|------|------|------|------------|
| `trailing_atr_mult` | 1.0-2.5 | 移动止盈ATR倍数（浮盈回撤N×ATR止盈） | 智能系统 | 1.0 |
| `trailing_start_ratio` | 0.3-0.8 | 移动止盈启动阈值（占止盈比例） | 智能系统 | 0.8 |
| `elder_ray_floor` | 0.5-0.9 | ELDER-RAY仓位下限（弱趋势最小仓位） | 智能系统 | 0.9 |
| `elder_ray_ceil` | 1.2-1.5 | ELDER-RAY仓位上限（强趋势最大仓位） | 智能系统 | 1.5 |
| `btc_windvane_confirm_days` | 1-5 | BTC风向标跌破确认天数 | 智能系统 | 3 |
| `max_base_holding_hours` | 24-96h | 底仓最大持仓时间 | 持仓时间 | 29.9h |
| `max_post_addon_hours` | 12-48h | 加仓后最大持仓时间 | 持仓时间 | 37.7h |
| `golden_window_hours` | 4-24h | 黑天鹅反弹黄金窗口 | 持仓时间 | 11.1h |

**固定参数（不参与优化）：**
- 底仓比例22%（`base_position_pct`，用户经验值）
- 杠杆5x（`leverage`，用户经验值）
- BTC止盈4%（`tp_pct_btc`，其他币种按波动率放大）
- 加仓间距8%基准（`addon_pct`，按波动率放大）
- 最大加仓3次（`max_addons`）

**双基线版本：**
| 版本 | 收益 | 参数键 | 用途 |
|------|------|--------|------|
| 固定参数基线 v1.0 | 138.0% | `FIXED_BASELINE_PARAMS` | 智能系统失效时终极回退 |
| 智能参数基线 v2.0 | 210.4% | `SMART_BASELINE_PARAMS` | 贝叶斯优化无效时回退（当前默认） |

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

### 6.3 贝叶斯优化自动调度流程（智能系统参数寻优 — 双层节奏 v6.0）

```
orchestrator.py（每15分钟被cron调用）
  ├─→ check_bayesian_optimization_trigger()
  │    ├─ 读取 bayesian_optimizer.py SCHEDULE_CONFIG
  │    ├─ 读取 v15_state.json 连亏笔数
  │    └─ should_trigger_optimization()
  │         ├─ 条件1: 连亏 ≥ 3笔（事件驱动，最高优先级）
  │         ├─ 条件2: 双层周期驱动（v6.0双层节奏）
  │         │    ├─ 路径A: 距上次参数空间重算 ≥ 60天 → 重算贝叶斯8参数空间（过拟合护栏）
  │         │    └─ 路径B: 距上次易经插值更新 ≥ 6天 → 仅更新插值倍数（不碰参数空间边界）
  │         └─ 冷却期检查: 距上次优化 < 24h → 跳过
  │
  └─→ run_bayesian_optimization()  ← 后台启动（PID锁防重复，不阻塞交易）
       └─ python3 bayesian_optimizer.py --with-rollback
            ├─ [1/4] 智能参数基线回测（210.4%）
            ├─ [2/4] 贝叶斯参数优化（8参数智能系统寻优 或 6天易经插值更新）
            ├─ [3/4] 优化参数回测验证 + walk-forward 5段全段检查
            └─ [4/4] 对比决定:
                 ├─ 路径A(60天): 收益≥2% + 全段退化<5% → 写入bayesian_opt/active_params.json
                 ├─ 路径B(6天): 收益≥0.5% → 写入易经插值配置（不改变参数边界）
                 └─ improvement < 阈值 → 回退当前活跃参数
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
| `V15_COINS` | 30个币种 | 监控交易对列表（已剔除小市值/meme/新币） |
| `V15_MARTIN_MIN_TIER` | mid | 马丁策略最低市值等级（large/mid/small） |
| `V15_MARTIN_MIN_HISTORY_DAYS` | 365 | 最小上线天数（新币暴涨暴跌风险，要求≥1年历史） |
| `V15_POLL_INTERVAL` | 3600s | 轮询间隔 |
| `V15_LEVERAGE` | 5 | 杠杆倍数 |
| `V15_BASE_POSITION_PCT` | 0.22 | 底仓资金比例 |
| `V15_MAX_CONCURRENT_POSITIONS` | 6 | 最大并发持仓数 |
| `V15_MAX_BASE_HOLDING_HOURS` | 48 | 底仓最大持仓时间(h) |
| `V15_MAX_POST_ADDON_HOURS` | 24 | 加仓后最大持仓时间(h) |
| `V15_GOLDEN_WINDOW_HOURS` | 12 | 黑天鹅反弹黄金窗口(h) |
| `V15_USE_TRAILING_TP` | true | 移动止盈开关（参数从active_params.json加载：trailing_atr_mult, trailing_start_ratio） |
| `V15_YIJING_ENABLED` | **false** | **Phase C 易经推理开关（v6.0新增，v15-final默认关闭）。true=启用risk/value插值；false=仅Phase B+子形态** |
| `V15_DAILY_LOSS_LIMIT` | -50 | 日亏损限制(USDT) |
| `V15_MAX_CONSECUTIVE_LOSSES` | 3 | 连续亏损3次触发资金管理引擎重新优化 |
| `V15_ALLOW_SHORT` | true | 多空方向控制开关（true=启用MA128+BTC风向标做空机制） |
| `V15_TREND_FILTER_MODE` | none | 趋势过滤模式（none/both_bear），当前已禁用 |
| `V15_TREND_FILTER_PERIOD` | 104 | 趋势过滤MA周期 |
| `V15_ADDON1_PCT` | 0.20 | 加仓1资金比例 |
| `V15_ADDON2_PCT` | 0.05 | 加仓2资金比例 |
| `V15_ADDON3_PCT` | 0.10 | 加仓3资金比例 |
| `V15CT_CONFIDENCE_THRESHOLD` | 30 | V15-CT 信号置信度阈值 |
| `BAYESIAN_OPT_LOSS_STREAK_TRIGGER` | 3 | 贝叶斯优化：连续亏损触发笔数 |
| `BAYESIAN_OPT_WEEKLY` | false | 贝叶斯优化：每周触发（已关闭，避免过拟合） |
| `BAYESIAN_OPT_MONTHLY` | true | 贝叶斯优化：每月触发（跨月检查） |
| `BAYESIAN_OPT_MIN_IMPROVE_PCT` | 2.0 | 贝叶斯优化：采用阈值（收益差≥2%才采用） |
| `BAYESIAN_OPT_COOLDOWN_HOURS` | 24 | 贝叶斯优化：冷却期（距上次优化24h内不重复触发） |
| **SCHEDULE_CONFIG** | 在代码 | **v6.0 双层节奏配置**（见 bayesian_optimizer.py）：`param_space_recalc_days=60`（过拟合护栏），`yijing_interp_days=6`（日常微调，不碰边界） |

---

## 8. 智能系统增强 & Phase A+/B+/C 演进 & 双基线版本管理

### 8.1 智能系统增强模块（v15-final 激活状态）

| 增强模块 | 实现文件 | 核心参数 | 默认状态 |
|----------|----------|----------|----------|
| ATR动态止盈（Phase A+） | `lib/strategy_params.py` + `lib/position_config.py` | `calc_atr()`, `calc_atr_pct()` | ✅ 启用（`use_atr=True`） |
| 移动止盈（Phase A+） | `core/v15_backtest.py` | `trailing_atr_mult`, `trailing_start_ratio` | ✅ 启用（`use_trailing_tp=True`） |
| ELDER-RAY资金调度（Phase A+） | `core/v15_backtest.py` + `lib/fund_manager.py` | `elder_ray_floor`(0.9), `elder_ray_ceil`(1.5) | ✅ 启用（`use_elder_ray=True`） |
| BTC风向标智能模式（Phase A+） | `lib/direction_gate.py` + `core/v15_backtest.py` | `btc_windvane_confirm_days`(3), `btc_windvane_short_only`(True) | ✅ 启用（非BTC币种自动启用） |
| **Phase B+ 子形态微调（v15-final核心）** | `core/v15_signal.py`/`v15_signal_engine.py`/`v15_backtest.py`/`v15_trader.py` | SubMorph6分类（BULL/BEAR × STRONG/NORMAL/STABLE），TP×1.05-1.15/0.85-0.95，持仓×1.05-1.10/0.85-0.95 | **✅ 启用（v15-final默认，对比A+收益+2.07%、胜率+1.38%、Calmar+1.18）** |
| Phase C 易经推理桥接（模块化保留） | `lib/yijing_bridge.py` + `lib/yijing_param_interpolator.py` + `lib/coin_selector.py` + `core/walk_forward_validator.py` | `V15_YIJING_ENABLED`（默认false），risk/value→插值clamp[0.75,1.25]，中性区0.12 | ❌ **默认关闭**（walk-forward未全段通过：SOL第2段退化6%；C vs B+收益-0.05%~-0.11%；模块化完整保留，可通过V15_YIJING_ENABLED=true启用或被外部调用） |
| 凯利公式底仓优化 | `lib/kelly_optimizer.py` | `use_kelly`, `kelly_shrinkage` | ❌ 关闭（`use_kelly=False`） |

### 8.1.1 Phase A+/B+/C 技术对比总览

| 维度 | Phase A+（基线） | Phase B+（v15-final，启用） | Phase C（模块化保留，默认关闭） |
|------|-----------------|---------------------------|-------------------------------|
| **核心逻辑** | ATR动态止盈 + 移动止盈 + ELDER-RAY + BTC风向标智能模式 | A+基础上叠加 **6类子形态微调**（BULL/BEAR × Elder-ray强度） | A+ + B+ 基础上叠加 **易经risk/value参数插值** |
| **输入信号** | 4H K线 + 16项指标 + Elder-ray | 同A+ + 3-bar平滑子形态分类 | 同B+ + 易经8维评分（供需/技术/资金流/情绪/趋势强度/波动率/量比/价格位置） |
| **TP调整** | ATR动态 × BTC 4%基准 | 子形态倍数 ×1.05-1.15（BULL）或×0.85-0.95（BEAR） | 子形态倍数 × 易经插值倍数 clamp [0.75, 1.25]；\|net_value\|<0.12中性区不调整 |
| **持仓调整** | 底仓48h / 加仓后24h | 子形态持仓倍数 ×1.05-1.10（BULL）或×0.85-0.95（BEAR） | 子形态倍数 × 易经持仓插值 |
| **仓位调整** | 22%底仓 + ELDER-RAY 0.9-1.5x | 同A+ | 同B+ × 易经仓位插值 |
| **A+回测收益** | 100%基线 | +2.07%（3币种合并） | 未单独测 |
| **B+回测收益** | — | 100%基线 | -0.05%~-0.11%（3币种合并，微退化） |
| **walk-forward通过** | 已验证 | 已验证（5/5段） | BTC/ETH ✅ 5/5；SOL ❌ 4/5（第2段退化6%超容忍线） |
| **在v15-final状态** | 激活 | **激活（最终形态）** | 模块化保留，V15_YIJING_ENABLED=false |
| **过拟合护栏** | 贝叶斯月级调度 | 同A+ | 双层节奏：60天参数空间重算（边界）+ 6天易经插值（日常微调，不碰边界） |

### 8.2 BTC风向标智能模式选择

| 币种 | 方向控制策略 | 止损机制 | 说明 |
|------|-------------|----------|------|
| BTC | DirectionGate（MA128三状态） | 自身MA200动态止损 | BTC走势独立，用自身指标 |
| 其他币 | BTC风向标3日确认 + short_only | BTC MA200全局控方向 | 山寨币跟随BTC，用风向标更稳定 |

### 8.3 双基线版本管理 & v15-final 最终形态快照

| 版本 | 名称 | 收益 | 参数键 | 创建日期 | 用途 |
|------|------|------|--------|----------|------|
| v1.0 | 固定参数基线 | 138.0% | `FIXED_BASELINE_PARAMS` | 2026-07-15 | 智能系统整体失效时终极回退 |
| v2.0 | 智能参数基线 | 210.4% | `SMART_BASELINE_PARAMS` | 2026-07-16 | 贝叶斯优化无效时回退 |
| **v6.0-final** | **Phase B+ 最终部署形态** | A+基线 + **+2.07%**（子形态微调增量） | `v15_final_deployment.json` | 2026-08-06 | **v15-final当前活跃**（Phase C易经默认关闭，模块化保留） |

**三级回退策略：**
1. **v6.0 Phase B+ 活跃参数**（子形态 + A+智能增强）→ v15-final 默认
2. 智能参数基线（210.4%）→ 子形态收益异常或优化收益差 < 2% 时回退
3. 固定参数基线（138%）→ 智能系统整体失效时终极回退

**v15-final 决策记录（见 data/v15_final_deployment.json）：**
- Phase C walk-forward 未全段通过（SOL 第2段退化6% > 5%容忍线）
- Phase C vs B+ 全量回测：3币种合并收益 -0.05%~-0.11%（微退化，马丁对5-8%微调不敏感）
- **最终决策**：以 Phase B+ 作为 v15-final 部署形态；Phase C 4个模块化完整保留，可通过 `V15_YIJING_ENABLED=true` 或被外部系统调用

### 8.4 CLI 版本管理命令

```bash
# 查看版本管理信息（双基线对比 + 当前活跃参数 + 调度状态 + v15-final状态）
python lib/bayesian_optimizer.py --version-info

# 查看 v15-final 最终部署快照
python -c "import json; print(json.dumps(json.load(open('data/v15_final_deployment.json')), indent=2, ensure_ascii=False))"

# 重置为智能参数基线（210.4%，B+异常时）
python lib/bayesian_optimizer.py --reset-to-smart

# 终极回退到固定参数基线（138%，仅智能系统失效时使用）
python lib/bayesian_optimizer.py --reset-to-fixed

# 检查是否应该触发优化（支持双层节奏：60天参数空间 / 6天易经插值）
python lib/bayesian_optimizer.py --check-trigger

# 优化+自动回退验证（定时调度推荐）
python lib/bayesian_optimizer.py --with-rollback
```

### 8.5 数据文件

| 文件 | 路径 | 说明 |
|------|------|------|
| 活跃参数 | `data/bayesian_opt/active_params.json` | 当前生效的参数 + 来源 + 评分 + 时间戳 |
| **v15-final 部署快照** | `data/v15_final_deployment.json` | 决策依据 + 激活配置 + 模块保留状态 + 生成时间 |
| 调度状态 | `data/bayesian_opt/schedule_state.json` | 上次优化时间 + 动作 + 收益改善（双层节奏独立追踪） |
| PID锁 | `data/bayesian_opt/.opt.lock` | 防止优化重复运行的进程锁 |
| 优化历史 | `data/bayesian_opt/v15_optimization_*.json` | 历次优化结果（按时间戳命名） |
| 优化日志 | `logs/bayesian_opt.log` | 贝叶斯优化运行日志 |
| **易经推理缓存** | `data/yijing_cache/` | Phase C 按币种/日期分片的推理结果（命中即跳过重复推理） |

---

_最后更新：2026-08-06 | 维护者：DreamBuddy v2 | 版本：v6.0 v15-final_
