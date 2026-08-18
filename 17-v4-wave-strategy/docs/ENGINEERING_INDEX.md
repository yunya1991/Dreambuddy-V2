# 工程索引 — V4 减半周期 + 艾略特波浪互斥融合趋势策略

> **版本**: v1.0 | **更新日期**: 2026-07-31
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) §3.1
> **关联文档**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) · [API_SPEC.md](./API_SPEC.md) · [CHANGELOG.md](./CHANGELOG.md) · [README.md](../README.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 17 |
| 模块名称 | v4-wave-strategy（V4 减半周期 + 艾略特波浪互斥融合趋势策略） |
| 核心职责 | V4 减半周期定方向 + 艾略特波浪择时加仓 + 互斥融合输出 final_signal |
| 主入口 | `v4_wave_engine.py` → `compute_v4_wave_signal()` |
| 实盘入口 | `live/v4_wave_trader.py` → `V4WaveTrader.run_forever()` |
| 回测入口 | `backtest_v4_wave.py` → `run_backtest()` |
| 依赖关系（上游） | `12-三屏趋势系统/ml/`（physics_enhancer、pitd_confidence_scorer、pitd_kinematics_engineer、pitd_dynamics_engineer、market_cap_provider）；`12-三屏趋势系统/live/aster_executor.py`；`dreamllm/services/registry.py`（OKX 适配器） |
| 依赖关系（下游） | 无（独立终端策略子系统） |
| 数据来源 | OKX API（实盘/模拟）；本地 `data/BTC_1D_9year.json`（回测） |
| 文档状态 | ✅ 完整（5 文档全） |

---

## 2. 目录地图

```
17-v4-wave-strategy/
├── docs/                              # 文档目录
│   ├── ENGINEERING_INDEX.md           # 本文件 — 工程索引
│   ├── TECHNICAL_DESIGN.md            # 技术设计（架构/算法/数据流）
│   ├── API_SPEC.md                    # 接口规格（公开 API）
│   └── CHANGELOG.md                   # 变更日志
├── data/                              # 数据层
│   ├── __init__.py
│   ├── market_data.py                 # K 线获取 + 跨周期重采样
│   ├── BTC_1D_9year.json              # BTC 9 年日线数据（回测）
│   └── v4_position_sltp.json          # 实盘持仓 SL/TP 元数据（运行时生成）
├── live/                              # 实盘执行层
│   ├── __init__.py
│   └── v4_wave_trader.py              # V4+波浪实盘交易器
├── backtest_results/                  # 回测产物
│   ├── v4_wave_9year_btc.json         # 9 年 BTC 回测结果
│   └── v4_wave_independent_btc.json   # 独立模块对比回测结果
├── __init__.py
├── v4_wave_engine.py                  # 核心引擎（V4+波浪融合）
├── halving_top_exit_strategy.py       # V4 减半周期逃顶策略
├── ewave_recognizer.py                # 艾略特波浪识别器
├── ewave_strategy_adapter.py          # 波浪策略适配器（互斥融合）
├── backtest_v4_wave.py                # 回测脚本
└── README.md                          # 用户文档
```

**代码统计**：根目录 5 个核心 Python 文件 + `data/` 1 个 + `live/` 1 个 = **7 个核心 Python 文件**。

---

## 3. 文件清单与职责

### 3.1 核心层（根目录）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `v4_wave_engine.py` | 5 | 核心引擎：编排 V4+波浪+物理增强，输出 final_signal | `compute_v4_wave_signal()`, `V4WaveEngine.compute_from_dataframes()`, `_compute_value_risk()`, `_position_to_action()` |
| `halving_top_exit_strategy.py` | 12 | V4 减半周期逃顶策略：MA200 趋势 + 减半周期顶部预警 + MA128 破位分批减仓 + 周线 MA200 抄底 | `HalvingTopExitStrategy.generate_signals()`, `_get_halving_phase()`, `_calc_halving_position()`, `_calc_high_to_sell_position()`, `_calc_ma128_exit_position()`, `_calc_fib_tp_position()`, `_detect_bounce()`, `_compute_weekly_ma200()`, `get_stats()` |
| `ewave_recognizer.py` | 9 | 艾略特波浪识别器：ZigZag 转折点 + 分形确认 + 三大硬规则判定五浪 | `ElliottWaveRecognizer.identify_waves()`, `_compute_zigzag()`, `_confirm_with_fractals()`, `_classify_realtime_wave()`, `_classify_partial_wave()`, `_classify_impulse_wave()`, `_generate_signal()`, `generate_signal_series()` |
| `ewave_strategy_adapter.py` | 5 | 波浪策略适配器：互斥融合 + 物理增强 + 动态 SL/TP | `EWaveStrategyAdapter.evaluate()`, `_fuse_positions()`, `_compute_wave_position()`, `_parse_wave_direction()`；dataclass `WaveConfig` |
| `backtest_v4_wave.py` | 8 | 回测验证：多策略对比 + 含/无成本 + 9 年/4 年样本外 | `run_backtest()`, `calc_metrics()`, `compute_v4_positions()`, `generate_wave_signals()`, `compute_v4_wave_fusion()`, `compute_v4_wave_fusion_with_physics()`, `load_coin_data()`, `parse_wave_direction()` |

### 3.2 数据层（data/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `data/market_data.py` | 7 | K 线数据获取（OKX SDK/CLI 双通道）+ 跨周期重采样 + DataFrame 转换 | `fetch_candles()`, `fetch_historical_candles()`, `resample_candles()`, `candles_to_dataframe()`, `_get_okx_client()`, `_run_okx()`, `_infer_timeframe()` |
| `data/BTC_1D_9year.json` | - | BTC 9 年日线历史数据（2017-10-10 ~ 2026-07-27，3213 天） | - |

### 3.3 实盘层（live/）

| 文件 | 函数数 | 职责 | 关键函数 |
|------|--------|------|----------|
| `live/v4_wave_trader.py` | 14 | V4+波浪实盘交易器：60s 轮询 + 动态 SL/TP + 移动止盈 + Aster 执行器集成 | `V4WaveTrader.run_forever()`, `V4WaveTrader.run_once()`, `V4WaveTrader._handle_entry()`, `V4WaveTrader._handle_exit()`, `V4WaveTrader._check_sltp()`, `V4WaveTrader._dynamic_adjust_sltp()`, `V4WaveTrader._sync_sltp_orders()`, `_compute_sltp()`, `V4WaveTrader.initialize()`, `V4WaveTrader.get_positions()`, `V4WaveTrader._calc_notional()`, `main()` |

### 3.4 文档层（docs/）

| 文件 | 职责 |
|------|------|
| `docs/ENGINEERING_INDEX.md` | 本文件，文件级工程索引 |
| `docs/TECHNICAL_DESIGN.md` | 技术设计文档（架构、算法、数据流） |
| `docs/API_SPEC.md` | 公开接口规格 |
| `docs/CHANGELOG.md` | 变更日志 |

### 3.5 回测产物（backtest_results/）

| 文件 | 职责 |
|------|------|
| `backtest_results/v4_wave_9year_btc.json` | BTC 9 年回测完整结果（含/无成本 × 9 年/4 年） |
| `backtest_results/v4_wave_independent_btc.json` | 独立模块 8 年/4 年对比回测结果 |

---

## 4. 核心流程索引

### 4.1 信号生成主流程

```
日线 K 线 → V4 定方向 → 价值风险评估 → 物理置信度调节 → 波浪互斥融合 → final_signal
   ↓           ↓              ↓                ↓                 ↓               ↓
fetch_candles  HalvingTopExitStrategy  _compute_value_risk  physics_enhancer  EWaveStrategyAdapter  V4WaveEngine
market_data.py  halving_top_exit_       v4_wave_engine.py    (12-三屏)          .evaluate()            .compute_from_dataframes
                 strategy.py                                                    ewave_strategy_
                                                                                adapter.py
```

**步骤锚点**：

| 步骤 | 函数 | 文件 |
|------|------|------|
| 1. 获取日线 K 线 | `fetch_candles()` | `data/market_data.py` |
| 2. K 线转 DataFrame | `candles_to_dataframe()` | `data/market_data.py` |
| 3. V4 减半周期定方向 | `HalvingTopExitStrategy.generate_signals()` | `halving_top_exit_strategy.py` |
| 4. 价值风险评估 | `_compute_value_risk()` | `v4_wave_engine.py` |
| 5. 物理置信度调节 | `PhysicsEnhancer.compute_features()`（外部） | `12-三屏趋势系统/ml/physics_enhancer.py` |
| 6. 波浪识别 | `ElliottWaveRecognizer.identify_waves()` | `ewave_recognizer.py` |
| 7. 互斥融合 | `EWaveStrategyAdapter._fuse_positions()` | `ewave_strategy_adapter.py` |
| 8. 组装 final_signal | `V4WaveEngine.compute_from_dataframes()` | `v4_wave_engine.py` |

### 4.2 回测流程

```
加载 BTC 9 年数据 → 计算 V4 仓位 → 预计算波浪信号 → 互斥融合 → 计算指标 → 输出 JSON
       ↓                 ↓                 ↓                 ↓             ↓           ↓
   load_coin_data   compute_v4_       generate_wave_    compute_v4_     calc_metrics   run_backtest
   backtest_v4_    positions         signals            wave_fusion                    backtest_v4_
   wave.py                                              _with_physics                  wave.py
```

### 4.3 实盘流程

```
启动 → 60s 轮询 → 获取持仓 → 检查 SL/TP → 逐币种计算信号 → 开仓/平仓/持有 → 动态调 SL/TP
 ↓        ↓          ↓           ↓                ↓                  ↓                  ↓
main    run_once   get_       _check_        compute_v4_        _handle_entry/     _dynamic_adjust_
       run_forever positions  sltp           wave_signal         _handle_exit      sltp
       live/       live/      live/          v4_wave_engine.py   live/             live/
       v4_wave_    v4_wave_   v4_wave_                           v4_wave_          v4_wave_
       trader.py   trader.py  trader.py                          trader.py         trader.py
```

---

## 5. 配置参数索引

### 5.1 引擎级常量（`v4_wave_engine.py`）

| 常量 | 默认值 | 说明 |
|------|--------|------|
| `MAX_LEVERAGE` | 3 | 最大杠杆倍数 |
| `MAX_POSITION_PCT` | 0.25 | 单币种最大仓位占比 |

### 5.2 V4 减半周期策略参数（`HalvingTopExitStrategy.__init__`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `ma_period` | 200 | 主均线周期 |
| `ma128_period` | 128 | MA128 周期（破位减仓） |
| `slope_period` | 5 | 均线斜率计算周期 |
| `max_position` | 1.0 | V4 最大仓位 |
| `warmup_periods` | 250 | 预热期 |
| `use_halving_timing` | True | 启用减半周期顶部逃顶 |
| `halving_warn_months` | 12 | 减半后预警起始月数 |
| `halving_danger_months` | 15 | 减半后高危起始月数 |
| `halving_peak_months` | 18 | 减半后顶部目标月数 |
| `halving_end_months` | 24 | 减半周期结束月数 |
| `halving_warn_min_position` | 0.7 | 预警期最小仓位倍数 |
| `halving_danger_min_position` | 0.3 | 高危期最小仓位倍数 |
| `halving_peak_min_position` | 0.0 | 顶部期最小仓位倍数 |
| `use_high_to_sell` | True | 越高越卖 |
| `high_to_sell_step_pct` | 5.0 | 创新高卖出步长(%) |
| `high_to_sell_portion` | 0.15 | 每步卖出比例 |
| `use_ma128_exit` | True | MA128 破位分批减仓 |
| `ma128_exit_levels` | 4 | MA128 破位减仓层级 |
| `use_bounce_sell` | True | 反弹卖出 |
| `bounce_sell_pct_per_bounce` | 0.25 | 每次反弹卖出比例 |
| `weekly_ma200_dip_buy` | True | 周线 MA200 抄底 |
| `dip_buy_max_position` | 0.9 | 抄底最大仓位 |
| `dip_buy_levels` | 6 | 抄底层数 |
| `bear_short_level2_pct` | 0.6 | 熊市 L2 做空仓位 |
| `fib_take_profit` | True | 斐波那契做空止盈 |

### 5.3 波浪识别参数（`ElliottWaveRecognizer.__init__`）

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `zigzag_threshold` | 0.05 | ZigZag 转折点阈值（5%） |
| `fractal_window` | 5 | 分形确认窗口 |
| `min_wave_points` | 6 | 最小波浪转折点数 |
| `wave2_retrace_max` | 1.0 | 浪 2 回撤上限（规则 1） |
| `wave3_min_ratio` | 0.382 | 浪 3 最小比例（规则 2） |
| `wave4_overlap_max` | 0.0 | 浪 4 重叠上限（规则 3） |

### 5.4 互斥融合参数（`WaveConfig`）

详见 [README.md §配置说明](../README.md#配置说明) 与 [TECHNICAL_DESIGN.md §7 配置管理](./TECHNICAL_DESIGN.md)。

### 5.5 实盘环境变量（`live/v4_wave_trader.py`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `TREND_SYMBOLS` | `BTC,ETH,SOL,UNI` | 监控币种列表 |
| `SCHEDULER_INTERVAL_SECONDS` | 60 | 轮询间隔（秒） |
| `AUTO_EXECUTE` | `true` | 是否实盘下单 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `MAX_POSITION_PCT` | 25 | 单币种最大仓位占比(%) |
| `INITIAL_CAPITAL` | 200 | 初始资金（USDT，回退用） |

### 5.6 配置加载优先级

```
环境变量（TREND_SYMBOLS / AUTO_EXECUTE 等）
    ↓ 覆盖
17-v4-wave-strategy/.env 文件
    ↓ 覆盖
live/v4_wave_trader.py 代码默认值
```

`WaveConfig` 参数当前为代码内常量（dataclass 默认值），未支持 .env 加载；后续可扩展。

---

## 6. 测试体系

| 文件 | 测试内容 | 类型 |
|------|----------|------|
| `backtest_v4_wave.py` | 9 年/4 年 BTC 多策略对比回测（纯 V4 / V4+波浪默认 / V4+波浪优化 / 买入持有） | 回测验证脚本 |
| `backtest_results/v4_wave_9year_btc.json` | 9 年回测产物（含/无成本 × 9 年/4 年样本外） | 回测产物 |
| `backtest_results/v4_wave_independent_btc.json` | 独立模块 8 年/4 年对比回测产物 | 回测产物 |

**运行命令**：

```bash
# 9 年回测（默认 BTC）
python backtest_v4_wave.py --symbol BTC

# 单次信号验证
python -c "from v4_wave_engine import compute_v4_wave_signal; print(compute_v4_wave_signal('BTC-USDT', is_btc=True)['final_signal'])"
```

> 当前子系统无独立 `tests/` 单元测试目录；测试以回测脚本为主。技术债务见 §7。

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 | 关联 |
|--------|----------|------|------|
| 缺少单元测试 | 中 | `ewave_recognizer._classify_realtime_wave` 等核心算法无单元测试覆盖 | 后续补 `tests/test_ewave_recognizer.py` |
| `WaveConfig` 不支持 .env | 低 | dataclass 默认值硬编码，无外部配置文件覆盖路径 | 后续可扩展 `config_loader` |
| 物理引擎跨模块依赖 | 中 | 强依赖 `12-三屏趋势系统/ml/`，导入失败需降级处理 | 已有 `try/except` 降级，但耦合度高 |
| 回测与实盘融合规则重复实现 | 低 | `backtest_v4_wave.compute_v4_wave_fusion` 与 `EWaveStrategyAdapter._fuse_positions` 规则重复 | 后续可统一调用 |
| 实盘 SL/TP 状态文件并发安全 | 低 | `data/v4_position_sltp.json` 无锁，多进程并发可能冲突 | 单进程运行无影响 |

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 用户文档 | [README.md](../README.md) |
| 技术设计 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规格 | [API_SPEC.md](./API_SPEC.md) |
| 变更日志 | [CHANGELOG.md](./CHANGELOG.md) |
| 项目文档规范 | [0-系统文档管理/1-规范体系/DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md) |
| V15 标杆参照 | [14-V15经典马丁策略/docs/](../../14-V15经典马丁策略/docs/) |
| 上游物理引擎 | `../12-三屏趋势系统/ml/physics_enhancer.py` |
| 上游执行器 | `../12-三屏趋势系统/live/aster_executor.py` |

---

**文档版本**: v1.0
**最后更新**: 2026-07-31
