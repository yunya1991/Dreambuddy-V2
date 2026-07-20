# 12-三屏趋势系统 · 工程索引

> 模块路径: `12-三屏趋势系统/`
> 版本: v4.0.0 (Phase 6 — 双线策略架构：V4+波浪互斥融合 主线 + V5.5 ML 副线)
> 语言: Python 3.x
> 依赖: numpy, pandas, talib（可选，从10-经典指标系统导入）, lightgbm（ML可选）
> 更新日期: 2026-07-19
> **主线策略**: V4 + 波浪互斥融合 — BTC 年化 56.43%，夏普 1.41，回撤 -43.31%
> **副线策略**: V5.5 ML 基线 — 实验状态，需重新设计特征工程
> **策略线管理**: [docs/STRATEGY_LINES.md](docs/STRATEGY_LINES.md) — 主副线隔离规则

---

## 目录

1. [模块总览](#1-模块总览)
2. [完整目录结构](#2-完整目录结构)
3. [文件详情索引](#3-文件详情索引)
4. [集成推理层（新增）](#4-集成推理层新增)
5. [双线策略架构](#5-双线策略架构)
6. [模块依赖关系](#6-模块依赖关系)
7. [公开 API 清单](#7-公开-api-清单)
8. [配置参数清单](#8-配置参数清单)
9. [数据结构清单](#9-数据结构清单)
10. [外部接口清单](#10-外部接口清单)
11. [测试覆盖](#11-测试覆盖)

---

## 1. 模块总览

### 1.1 系统定位

**V4 定方向，波浪择时加仓，物理引擎评估风险。**

三屏趋势系统 = 「V4主策略方向 + 波浪择时加仓 + 物理置信度评估 + 仓位计算」

| 职责 | 归属 | 说明 |
|------|------|------|
| **V4 主策略（定方向）** | 本模块 | 减半周期逃顶策略，覆盖三屏决策 |
| **波浪择时加仓** | 本模块 | 互斥融合：同向叠加，反向以V4为主 |
| **物理置信度调节** | 本模块 | 弱趋势状态（η<0.10）下仓位微调 |
| BTC风向标闸门 | 本模块 | 全系统宏观方向过滤（日线MA128 + 周线MA200） |
| 趋势方向判定 | 本模块 | 周线 + 日线，静态 + 三维动态（信号源层） |
| 置信度评估 | 本模块 | 贝叶斯置信度 + 基本面撮合 + Freqtrade校准 |
| 价值风险评估 | 本模块 | Elder-ray + 波动率放大 + 风险回报比 |
| 仓位/加仓计算 | 本模块 | V4仓位 + 波浪加仓 + 物理调节 |
| 入场信号 | **10-经典指标系统** | Freqtrade 多策略投票 |
| 离场决策 | **10-经典指标系统** | ClassicExitSystem 四层优先级 |
| 基本面数据 | **A系列研报** | 周报(MD) + A1日报(JSON) |
| K线数据 | **OKX API** | 周线 / 日线 / 小时线 |

### 1.2 决策优先级链

```
优先级0: BTC风向标闸门（宏观方向过滤）
    → 优先级1: 趋势一致性检测（Screen 1，周线+日线）
        → 优先级2: 置信度评估（Screen 2，贝叶斯+经典+Freqtrade）
            → 优先级3: 五大算法 final_signal（信号源层）
                → 优先级4: V4 主策略（定方向，覆盖三屏决策）★ 主线核心
                    → 优先级5: 波浪策略择时加仓（互斥融合）★ 主线核心
                        → 优先级6: 物理置信度调节（弱趋势仓位微调）
                            → 优先级7: 价值风险评估（仓位调整）
```

### 1.3 五层架构

| 层级 | 名称 | 周期/维度 | 核心模块 |
|------|------|----------|---------|
| 第0屏 | 宏观风向 | BTC日线/周线 | `engine.py` → `evaluate_btc_wind_vane()` |
| 第一屏 | 战略层 | 周线 | `core/trend_consistency.py` |
| 第二屏 | 战术层 | 日线 | `core/dynamic_weights.py`, `core/fusion.py` |
| 第三屏 | 执行层 | 4h/1h | `signals.py`, `exit_integration.py`（委托经典系统） |
| 第四屏（新） | 推理层 | 辩证推理 | `ml/algo_ensemble.py`, `ml/llm_reasoning.py` |

---

## 2. 完整目录结构

```
12-三屏趋势系统/
│
├── __init__.py                         # 包入口，版本号 + 核心导出
├── README.md                           # 快速开始 + 简要索引
├── ENGINEERING_INDEX.md                # 本文档 · 完整工程索引
│
├── engine.py                           # ⭐ 主引擎（算法编排 + 公开接口）
│                                        #    BTC风向标闸门 + 五大算法 + 价值风险
├── signals.py                          # 入场信号服务（Freqtrade 多策略）
├── exit_integration.py                 # 离场决策集成（ClassicExitSystem）
├── classic_bridge.py                   # 经典系统 HTTP 桥接
│
├── core/                               # 🔧 核心算法层
│   ├── __init__.py                     #    核心包导出
│   ├── config.py                       #    配置常量（基础+逐仓+价值风险+风向标）
│   ├── indicators.py                   #    指标计算（三维动态 + 静态）
│   ├── trend_consistency.py            #    趋势一致性检测
│   ├── dynamic_weights.py              #    动态权重 + 贝叶斯置信度
│   ├── fusion.py                       #    Path A 融合：技术面+基本面撮合
│   ├── fundamental_screen1.py          #    Path B 核心：7维基本面分析（Tavily+算法）
│   ├── least_resistance.py             #    Phase 3.5 最小阻力方向引擎（第一性原理）
│   ├── composite_predictor.py          #    Phase 3.4 综合预测引擎（技术+基本面调节）
│   ├── risk_control.py                 #    极端行情风控守卫
│   └── risk_reward.py                  #    价值风险评估 + 仓位 + 加仓决策
│
├── data/                               # 📦 数据获取层
│   ├── __init__.py                     #    数据包导出
│   ├── market_data.py                  #    K线数据获取 + 重采样
│   ├── fundamental_data.py             #    Path A 数据源：A系列研报获取
│   └── tavily_data.py                  #    Path B 数据源：Tavily API 实时搜索（4维）
│
├── signal_pool/                        # 📡 Freqtrade信号池
│   ├── pool.json                       #    信号池缓存
│   └── scanner.py                      #    信号池扫描器
│
├── backtest/                           # 📊 回测引擎
│   ├── engine.py                       #    回测核心引擎
│   ├── strategy.py                     #    策略定义（含Platt置信度校准）
│   ├── metrics.py                      #    绩效指标
│   ├── walk_forward.py                 #    滚动向前验证
│   ├── calibration.py                  #    置信度校准（Platt/Isotonic/Beta）
│   ├── overfitting.py                  #    过拟合检测 + 参数敏感性 + 置换检验
│   ├── results.py                      #    回测结果封装
│   └── run_backtest.py                 #    回测入口
│
├── ml/                                 # 🤖 机器学习 + 集成推理 + 策略基线
│   │                                   #    ── 主线代码 [MAIN] ──
│   ├── halving_top_exit_strategy.py    # ⭐ [MAIN] V4基线策略（减半周期逃顶，BTC专用）
│   ├── altcoin_trend_strategy.py       # ⭐ [MAIN] 非BTC趋势跟踪策略（自身MA200+减半影子仓位）
│   ├── ewave_strategy_adapter.py       # ⭐ [MAIN] 波浪策略适配器（V4+波浪互斥融合）
│   ├── ewave_recognizer.py             #    [MAIN] 波浪识别器
│   ├── ewave_backtest.py               #    [MAIN] 波浪策略回测
│   ├── v4_wave_fusion_comparison.py   #    [MAIN] V4+波浪融合对比验证
│   ├── v4_wave_smart_fusion.py         #    [MAIN] V4+波浪智能融合
│   ├── comprehensive_strategy_comparison.py # [MAIN] 综合策略对比回测
│   ├── 9year_strategy_comparison.py    #    [MAIN] 9年策略对比
│   ├── walk_forward_v4_validation.py   #    [MAIN] V4 Walk-Forward 验证
│   │                                   #    ── 共享基础设施 [SHARED] ──
│   ├── pitd_confidence_scorer.py       # 🔧 [SHARED] 物理置信度评估器
│   ├── pitd_kinematics_engineer.py     # 🔧 [SHARED] 运动学特征工程
│   ├── pitd_dynamics_engineer.py       # 🔧 [SHARED] 动力学特征工程
│   ├── pitd_potential_field.py         # 🔧 [SHARED] 势场计算
│   ├── pitd_reasoning_engine.py        # 🔧 [SHARED] 物理推理引擎
│   ├── physics_enhancer.py             # 🔧 [SHARED/MAIN] 物理增强器
│   ├── algo_ensemble.py                # 🔧 [SHARED] LightGBM集成推理（五大算法）
│   ├── llm_reasoning.py                # 🔧 [SHARED] LLM辩证推理（DeepSeek）
│   ├── label_samples.py                # 🔧 [SHARED] 样本标注 + 训练工具
│   │                                   #    ── 副线代码 [ML_BASELINE] ──
│   ├── philosophy_feature_engineer.py  # 🔬 [ML_BASELINE] 哲学特征工程（28维，V5.5）
│   ├── feature_engineer.py             # 🔬 [ML_BASELINE] 价格特征工程
│   ├── v55_baseline/                   # 🔬 [ML_BASELINE] V5.5 ML 副线工作区
│   │   ├── README.md                   #    副线说明文档
│   │   └── __init__.py                 #    包入口
│   ├── v51_*.py                        # 🔬 [ML_BASELINE] V5.1 验证脚本
│   ├── v52_*.py                        # 🔬 [ML_BASELINE] V5.2 验证脚本
│   ├── v53_*.py                        # 🔬 [ML_BASELINE] V5.3 验证脚本（4个）
│   ├── v54_*.py                        # 🔬 [ML_BASELINE] V5.4 验证脚本
│   ├── v55_*.py                        # 🔬 [ML_BASELINE] V5.5 验证脚本
│   ├── ewave_vs_v55_comparison.py      # 🔬 [ML_BASELINE] 波浪 vs V5.5 对比
│   │                                   #    ── 历史策略 + 工具 ──
│   ├── enhanced_ma200_v3_strategy.py   #    V3策略（抄底+逃顶框架）
│   ├── enhanced_ma200_v31_strategy.py  #    V3.1策略
│   ├── v2_baseline_optimization_principles.md # ⭐ V4基线优化原则（完整版）
│   ├── four_objective_framework_design.md # ⭐ 四类目的+动态实践闭环设计
│   ├── engineering_algorithm_roadmap.md # ⭐ V4基线后工程算法实践路线图（5阶段）
│   ├── four_objective_feature_mapper.py #    四类目的特征映射器
│   ├── scenario_backtest_engine.py     #    分场景回测引擎
│   ├── closed_loop_manager.py          #    闭环迭代管理器
│   ├── short_optimization_test.py      #    做空优化测试（V3）
│   ├── final_comparison.py             #    V2 vs 做空优化对比
│   ├── v2_vs_v3_comparison.py          #    V2 vs V3对比回测
│   ├── ml_strategy.py                  #    ML策略核心（价格特征）
│   ├── models.py                       #    价格特征ML模型定义（LightGBM/XGBoost/Logistic）
│   ├── lr_feature_engineer.py          #    最小阻力特征工程（52技术面特征）
│   ├── fundamental_adapter.py          #    基本面特征适配器（42个基本面特征）
│   ├── lr_ml_strategy.py               #    AI增强策略v1（LightGBM单任务）
│   ├── lr_ml_strategy_v2.py            #    AI增强策略v2（多任务+动态权重）
│   ├── multitask_model.py              #    多任务学习模型 + 动态融合权重
│   ├── full_strategy_comparison.py     # ⭐ 全策略统一回测对比（6+策略）
│   ├── enhanced_ma200_v2_config.json   #    v2基线策略配置（回测结果+基线标记）
│   ├── baseline_config_v3.json         #    V3基线配置
│   ├── LIGHTGBM_FEATURE_CATALOG.md     #    LightGBM特征消费分类目录
│   ├── tuner.py                        #    超参调优
│   ├── version_manager.py              #    模型版本管理
│   ├── setup_baseline.py               #    基线模型训练
│   ├── run_ml_backtest.py              #    ML回测入口
│   ├── multi_period_validation.py      #    多周期验证
│   ├── multi_period_validation_v2.py   #    多周期验证v2
│   ├── tuning_experiment.py            #    调优实验
│   └── models/                         #    模型存储
│       ├── current/                    #      当前生产模型（价格特征）
│       ├── baseline/                   #      基线模型
│       ├── ensemble/                   # ⭐ 集成推理模型（五大算法特征）
│       │   └── collected/              #        训练样本（jsonl按日分存）
│       ├── versions/                   #      历史版本
│       ├── perf_logs/                  #      性能日志
│       └── registry.json               #      模型注册表
│
├── tests/                              # ✅ 测试套件
│   ├── __init__.py                     #    测试包
│   └── test_core.py                    #    核心功能测试
│
└── docs/                               # 📚 文档
    ├── TECHNICAL_DESIGN.md             #    技术设计文档（完整版）
    ├── ENGINEERING_INDEX.md            #    简明工程索引
    ├── STRATEGY_LINES.md               # ⭐ 策略线管理总纲（主副线隔离规则）
    └── trend-screen-system-design.md   #    系统设计文档
```

---

## 3. 文件详情索引

### 3.1 根目录文件

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/__init__.py) | 22 | — | 包入口，版本号 v1.0.0 |
| [`engine.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | ~990 | `compute_full_trading_signal()`<br>`compute_trend_signal_from_dataframes()`<br>`five_algo_decision()`<br>`evaluate_btc_wind_vane()`<br>`compute_value_risk_assessment()`<br>`evaluate_addon_decision()`<br>`confidence_to_position()`<br>`fetch_entry_signals_from_classic()`<br>`evaluate_exit_from_classic()` | **主引擎**。BTC风向标闸门 + 五大算法 + 价值风险评估 + 加仓决策 + 公开接口 |
| [`signals.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py) | ~190 | `SignalDirection`<br>`StrategySignal`<br>`MultiStrategySignal`<br>`fetch_freqtrade_signals()`<br>`align_freqtrade_with_trend()` | **入场信号服务**。调用经典系统 Freqtrade 多策略，与趋势方向对齐校准 |
| [`exit_integration.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py) | ~230 | `ExitAction`<br>`PositionInfo`<br>`ExitDecisionResult`<br>`evaluate_exit()`<br>`get_exit_system_classic()` | **离场集成**。调用经典系统 ClassicExitSystem，支持 API/直接导入两种方式 |
| [`classic_bridge.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/classic_bridge.py) | ~90 | `get_classic_base_url()`<br>`_make_request()`<br>`is_classic_system_available()` | **HTTP桥接**。统一封装对经典指标系统的 REST API 调用 |

### 3.2 core/ 核心算法层

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`core/__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/__init__.py) | 72 | — | 核心包导出，统一相对/绝对导入兼容 |
| [`core/config.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) | ~80 | `CANDIDATE_COINS`<br>`SCREEN1_INDICATORS`<br>`SCREEN2_INDICATORS`<br>`POSITION_TIERS`<br>`MARGIN_MODE`, `MAX_LEVERAGE`<br>`MAX_POSITION_PCT`<br>`BASE_TAKE_PROFIT_PCT`<br>`BTC_WIND_VANE_DAILY_MA`<br>`BTC_WIND_VANE_WEEKLY_MA` | **配置常量**。基础+逐仓+价值风险+加仓+风向标，共30+配置项 |
| [`core/indicators.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py) | ~200 | `calc_indicator_dynamics()`<br>`calc_indicator_signal()`<br>`calc_trend_direction_static()`<br>`calc_classic_indicator_confidence()` | **指标计算引擎**。单指标三维动态(direction/speed/acceleration)、静态投票、经典指标综合置信度 |
| [`core/trend_consistency.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py) | ~230 | `calc_trend_direction_dynamic()`<br>`calc_trend_consistency()` | **趋势一致性检测**。静态+动态融合（动态优先原则），周线日线一致性判定 |
| [`core/dynamic_weights.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py) | ~200 | `calc_indicator_performance()`<br>`calc_dynamic_weights()`<br>`calc_bayesian_confidence()` | **动态权重 + 贝叶斯**。指标回测表现评估、动态权重分配、贝叶斯置信度计算 |
| [`core/fusion.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py) | ~100 | `fuse_technical_fundamental()` | **Path A 融合层**。技术面与研报基本面方向/置信度的融合计算 |
| [`core/fundamental_screen1.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fundamental_screen1.py) | ~450 | `calc_fundamental_screen1()`<br>`calc_halving_cycle()`<br>`fuse_tech_fundamental()`<br>`_try_tavily_dimensions()`<br>`load_annotation_dimension()` | **Path B 核心模块**。7维基本面分析框架：减半周期(纯代码)+Tavily API(4维)+annotation回退，加权融合输出方向/置信度 |
| [`core/risk_control.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/risk_control.py) | ~80 | `check_extreme_risk()`<br>`calc_volatility_stop()` | **极端风控守卫**。极端行情检测、波动率止损、强制平仓判定 |
| [`core/risk_reward.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/risk_reward.py) | ~300 | `calc_elder_ray()`<br>`calc_30d_volatility()`<br>`get_vol_adjusted_params()`<br>`calc_risk_reward_ratio()`<br>`evaluate_addon_opportunity()`<br>`calc_position_sizing()` | **价值风险 + 加仓**。Elder-ray趋势强度、波动率放大、RR比值、逆势/顺势加仓评估、仓位计算 |

### 3.3 data/ 数据获取层

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`data/__init__.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/__init__.py) | 1 | — | 数据包导出 |
| [`data/market_data.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py) | ~120 | `fetch_candles()`<br>`resample_candles()`<br>`_get_okx_client()` | **K线数据**。从 OKX API 获取K线，支持跨周期重采样(5m→1h→4h→1D) |
| [`data/fundamental_data.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py) | ~450 | `fetch_fundamental_data()`<br>`fetch_fundamental_by_timeframe()`<br>`_parse_a1_daily()`<br>`_parse_weekly_report()`<br>`_merge_fundamental()` | **Path A 数据源**。解析A系列研报(周报MD + A1日报JSON)，输出方向+置信度 |
| [`data/tavily_data.py`](file:///Users/zhangjiangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/tavily_data.py) | ~510 | `fetch_all_tavily_dimensions()`<br>`collect_miner_economics()`<br>`collect_onchain_valuation()`<br>`collect_macro_finance()`<br>`collect_cross_market()`<br>`tavily_search()`<br>`_parse_number_near()` | **Path B 数据源**。Tavily API 实时搜索4维基本面数据（矿工/链上/宏观/跨市场），30分钟缓存，SDK+HTTP双模式，年份过滤 |

### 3.4 signal_pool/ 信号池

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`signal_pool/pool.json`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signal_pool/pool.json) | — | — | **信号池缓存**。多币种多策略Freqtrade信号缓存 |
| [`signal_pool/scanner.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signal_pool/scanner.py) | ~150 | `scan_signals()`<br>`update_pool()`<br>`get_signal()` | **信号池扫描器**。多币种多策略扫描，信号入池与查询 |

### 3.5 backtest/ 回测引擎

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`backtest/engine.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/engine.py) | ~200 | `BacktestEngine`<br>`run_backtest()` | **回测核心引擎**。K线回放、信号触发、持仓管理、绩效计算 |
| [`backtest/strategy.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/strategy.py) | ~250 | `TrendScreenStrategy`<br>`train_calibration()`<br>`with_calibration()` | **策略定义 + Platt校准**。三屏趋势策略封装，置信度校准训练与集成 |
| [`backtest/metrics.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/metrics.py) | ~100 | `calc_metrics()`<br>`calc_sharpe()`<br>`calc_max_drawdown()` | **绩效指标**。夏普、最大回撤、胜率、盈亏比等 |
| [`backtest/walk_forward.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/walk_forward.py) | ~150 | `WalkForwardAnalyzer` | **滚动向前验证**。避免过拟合的时间序列交叉验证 |
| [`backtest/calibration.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/calibration.py) | ~200 | `platt_scaling()`<br>`isotonic_calibration()`<br>`beta_calibration()`<br>`calculate_ece()` | **置信度校准**。Platt缩放/Isotonic回归/Beta校准，ECE评估 |
| [`backtest/overfitting.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/overfitting.py) | ~250 | `permutation_test()`<br>`parameter_sensitivity_analysis()`<br>`cost_sensitivity_test()` | **过拟合检测**。置换检验、参数敏感性、交易成本敏感性 |
| [`backtest/results.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/results.py) | ~100 | `BacktestResult`<br>`format_comparison_table()` | **回测结果封装**。结果类、对比表格、格式化输出 |
| [`backtest/run_backtest.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/backtest/run_backtest.py) | ~80 | `main()` | **回测入口**。CLI回测启动脚本 |

### 3.6 ml/ 机器学习策略

| 文件 | 行数 | 核心类/函数 | 职责描述 |
|------|------|------------|---------|
| [`ml/ml_strategy.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ml_strategy.py) | ~200 | `MLStrategy`<br>`predict()` | **ML策略核心**。特征工程+模型推理+信号生成 |
| [`ml/models.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/models.py) | ~120 | `TrendClassifier`<br>`train_model()` | **模型定义**。分类/回归模型定义与训练 |
| [`ml/tuner.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/tuner.py) | ~150 | `tune_hyperparams()` | **超参调优**。网格/贝叶斯超参数搜索 |
| [`ml/version_manager.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/version_manager.py) | ~100 | `ModelVersionManager`<br>`promote_model()` | **版本管理**。模型注册、版本切换、灰度上线 |

### 3.7 tests/ 测试

| 文件 | 行数 | 测试函数数 | 覆盖范围 |
|------|------|-----------|---------|
| [`tests/test_core.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/tests/test_core.py) | ~280 | 7个 | 置信度映射、五大算法决策、趋势一致性、贝叶斯、撮合、完整信号、基本面数据 |

### 3.8 docs/ 文档

| 文件 | 说明 |
|------|------|
| [`docs/TECHNICAL_DESIGN.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) | 技术设计文档（完整版，v1.3） |
| [`docs/ENGINEERING_INDEX.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/ENGINEERING_INDEX.md) | 简明工程索引 |
| [`docs/trend-screen-system-design.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/trend-screen-system-design.md) | 系统设计文档（早期版本） |

---

## 4. 集成推理层（新增）

> 本章为 v1.4.0 新增，解决「五大算法固定权重不够智能」和「矛盾信号无法辩证分析」两个问题。

### 4.1 架构总览

```
五大算法 final_signal (规则决策)
            │
            ▼
┌─────────────────────────────────────────────┐
│           集成推理层 (Reasoning Layer)          │
│                                                │
│  Layer 1: LightGBM 集成推理                    │
│  ┌─────────────────────────────────────────┐  │
│  │ 输入: 46维特征（五大算法完整输出）       │  │
│  │ 算法: LightGBM 二分类                   │  │
│  │ 输出: direction + confidence + prob_up  │  │
│  │ 来源: algo_ensemble.py                  │  │
│  └───────────────────┬─────────────────────┘  │
│                      │                        │
│  Layer 2: LLM 辩证推理 (按需触发)              │
│  ┌───────────────────▼─────────────────────┐  │
│  │ 触发条件: 置信<40 或 (40-60 + 有矛盾)   │  │
│  │ 算法: DeepSeek LLM + 辩证提示词         │  │
│  │ 输出: direction + confidence + 推理依据  │  │
│  │ 来源: llm_reasoning.py                  │  │
│  └───────────────────┬─────────────────────┘  │
│                      │                        │
└──────────────────────┼────────────────────────┘
                       ▼
              最终推理结果 (direction, confidence, source, reasoning)
```

### 4.2 LightGBM 集成推理 (algo_ensemble.py)

| 项目 | 说明 |
|------|------|
| 文件 | [`ml/algo_ensemble.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) |
| 特征维度 | 46 维（五大算法完整输出） |
| 模型类型 | LightGBM 二分类（未来7日涨/跌） |
| 模型存储 | `ml/models/ensemble/ensemble_model.pkl` |
| 元数据 | `ml/models/ensemble/meta.json` |
| 样本存储 | `ml/models/ensemble/collected/samples_YYYY-MM-DD.jsonl` |

**核心函数：**

| 函数 | 入参 | 返回 | 说明 |
|------|------|------|------|
| `extract_ensemble_features(full_signal)` | 五大算法输出 | 特征 dict | 从 full_signal 提取 46 维特征 |
| `collect_sample(full_signal, symbol, future_return)` | 信号+标签 | 无 | 收集训练样本（实盘自动调用） |
| `train_ensemble(label_lookahead, test_ratio)` | 前瞻天数/测试比 | 训练结果 dict | 从 collected/ 样本训练模型 |
| `predict_ensemble(full_signal)` | 五大算法输出 | 预测结果 dict | 推理预测，无模型时 fallback |

**46 维特征分组：**

| 分组 | 维度 | 来源 |
|------|------|------|
| 趋势一致性 | 16维 | `trend_consistency` 周线+日线 |
| 贝叶斯置信度 | 3维 | `bayesian_confidence` |
| 经典指标置信度 | 10维 | `classic_indicator_confidence` |
| 技术基本面融合 | 4维 | `technical_fundamental_fusion` |
| 价值风险评估 | 4维 | `value_risk_assessment` |
| Freqtrade信号 | 4维 | `freqtrade_signals` 1h+4h |
| 最终信号 | 5维 | `final_signal` |

**隔离声明：**
- 与 `ml/models.py` 的 `LightGBMModel`（价格特征52维）完全独立
- 与 `11-易经推理系统` 的 `DialecticalMLEngine`（卦象特征）完全独立
- 不共享模型文件、不共享特征、不共享训练代码

### 4.3 LLM 辩证推理 (llm_reasoning.py)

| 项目 | 说明 |
|------|------|
| 文件 | [`ml/llm_reasoning.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) |
| LLM 服务 | DeepSeek API（共享 screen_executor 配置） |
| 触发模式 | 按需触发（节省 token） |
| 配置加载 | 进程环境变量 > experiments/ab-trading/config/.env > 12-三屏趋势系统/.env |

**触发规则：**

| 场景 | 是否触发 | 原因 |
|------|---------|------|
| 集成模型置信 ≥ 60 | 否 | `high_confidence`，直接用集成结果 |
| 集成模型置信 < 40 | 是 | `low_confidence`，低置信度必须人工介入 |
| 置信 40-60 + 有矛盾 | 是 | `uncertain_with_contradictions`，需辩证分析 |
| 置信 40-60 + 无矛盾 | 否 | `uncertain_no_contradictions`，信任集成结果 |
| 模型未训练 (fallback) | 否 | `ensemble_model_not_available` |

**矛盾检测维度（5类）：**
1. 趋势不一致（周线 vs 日线方向不同）
2. 贝叶斯方向与最终信号方向不一致
3. 经典指标趋势不一致
4. 技术面与基本面不一致
5. 逆转信号偏高（>50）

**核心函数：**

| 函数 | 入参 | 返回 | 说明 |
|------|------|------|------|
| `should_trigger_llm(ensemble_pred, full_signal)` | 集成预测+五大算法 | (bool, reason) | 判断是否需要 LLM 介入 |
| `_detect_contradictions(full_signal)` | 五大算法 | 矛盾列表 | 检测内部矛盾信号 |
| `reason_with_llm(full_signal, ensemble_pred)` | 完整输入 | 推理结果 | 调用 DeepSeek 辩证推理 |
| `reason_if_needed(full_signal, ensemble_pred)` | 完整输入 | 推理结果 | 自动判断是否触发 |

### 4.4 样本标注 + 训练工具 (label_samples.py)

| 项目 | 说明 |
|------|------|
| 文件 | [`ml/label_samples.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/label_samples.py) |
| 用途 | 自动标注 + 一键训练 |
| 数据源 | OKX API（日线K线） |

**命令行用法：**

```bash
# 查看样本统计
python3 ml/label_samples.py --list

# 标注样本（未来7日收益）
python3 ml/label_samples.py --lookahead 7

# 标注并训练
python3 ml/label_samples.py --train --lookahead 7
```

**核心函数：**

| 函数 | 说明 |
|------|------|
| `label_collected_samples(lookahead_days=7)` | 从 OKX 拉K线，计算未来收益，回填标签 |
| `train_from_collected(lookahead_days=7)` | 先标注再训练，一条龙 |

---

## 5. 双线策略架构

> 完整策略线管理规则见 [docs/STRATEGY_LINES.md](docs/STRATEGY_LINES.md)

### 5.1 架构总览

三屏趋势系统维护两条可持续演进的策略线，互不干扰、独立优化、统一对比：

```
┌─────────────────────────────────────────────────────────────┐
│                    主策略线 [MAIN]                            │
│              V4 + 波浪互斥融合（实盘部署）                    │
│                                                              │
│  V4 减半周期策略 ──→ 波浪择时加仓 ──→ 物理置信度调节          │
│  (定方向)           (同向叠加)        (弱趋势仓位微调)        │
│                                                              │
│  回测：年化 56.43% | 夏普 1.41 | 回撤 -43.31%                │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  机器学习基线 [ML_BASELINE]                   │
│              V5.5 LightGBM（实验状态）                       │
│                                                              │
│  28维哲学特征 ──→ LightGBM ──→ Walk-Forward 验证             │
│  (特征工程)       (模型)        (样本外评估)                  │
│                                                              │
│  回测：年化 4.31% | 夏普 0.30 | 回撤 -56.48%                 │
│  状态：严重过拟合，需重新设计特征工程                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                  共享基础设施 [SHARED]                        │
│       物理引擎 + 回测引擎 + 数据层 + 核心算法层                │
│                                                              │
│  pitd_* / physics_* / backtest/ / data/ / core/              │
│  （被两条线共同依赖，修改需双重验证）                          │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 主策略线 [MAIN]

**核心算法**：V4 减半周期策略 + 波浪互斥融合 + 物理置信度调节

**实现文件**：
| 文件 | 职责 |
|------|------|
| [`engine.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | 主引擎，V4+波浪互斥融合编排 |
| [`ml/halving_top_exit_strategy.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/halving_top_exit_strategy.py) | V4 减半周期逃顶策略（BTC专用） |
| [`ml/altcoin_trend_strategy.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/altcoin_trend_strategy.py) | 非BTC趋势跟踪策略（自身MA200+减半影子仓位） |
| [`ml/ewave_strategy_adapter.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_strategy_adapter.py) | 波浪策略适配器（择时加仓） |
| [`ml/ewave_recognizer.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_recognizer.py) | 波浪识别器 |

**互斥融合规则**（9年回测验证，BTC年化 56.43%，夏普 1.4112）：
- V4 多头 + 波浪看多 → V4 仓位 + 波浪加仓（同向叠加）
- V4 多头 + 波浪中性/看空 → 保持 V4 仓位（V4 优先）
- V4 空仓 + 波浪看多 → 波浪轻仓抄底（上限 30%）
- V4 空仓 + 波浪看空 → 空仓观望
- V4 空头 + 波浪看空 → 保持 V4 空头
- V4 空头 + 波浪看多 → V4 空头减半（波浪提示反弹）

**主线基线指标**（9年回测，2017-10-10 ~ 2026-07-16）：
| 指标 | 纯V4 | V4+波浪互斥融合 | 买入持有 |
|------|------|-----------------|----------|
| 年化收益 | 53.34% | **56.43%** | 34.80% |
| 总收益 | 1708.54% | **1970.42%** | 655.68% |
| 夏普比率 | 1.3744 | **1.4112** | 0.8024 |
| 最大回撤 | -44.37% | **-43.31%** | -76.40% |
| Calmar | 1.2022 | **1.3031** | 0.4555 |

### 5.3 机器学习基线 [ML_BASELINE]

**核心算法**：LightGBM + Walk-Forward + 28维哲学特征

**实现文件**：
| 文件 | 职责 |
|------|------|
| [`ml/philosophy_feature_engineer.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/philosophy_feature_engineer.py) | V5.5 28维哲学特征工程 |
| [`ml/feature_engineer.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py) | 价格特征工程 |
| [`ml/v55_baseline/`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v55_baseline/) | V5.5 ML 副线工作区 |

**当前状态**：🔬 实验性，严重过拟合
- 9年回测年化仅 4.31%，远低于主线 56.43%
- 夏普 0.3024，风险调整收益差
- 需重新设计特征工程解决长期过拟合问题

**优化方向**：
1. 重新设计特征工程（减少维度，增加稳定性）
2. 探索更长的训练窗口（>730天）
3. 改进标签生成策略
4. 探索时序模型（LSTM/Transformer）

### 5.4 共享基础设施 [SHARED]

被两条策略线共同依赖的基础设施，修改需双重验证：

| 文件 | 职责 | 使用方 |
|------|------|--------|
| `ml/pitd_confidence_scorer.py` | 物理置信度评估器 | MAIN + ML_BASELINE |
| `ml/pitd_kinematics_engineer.py` | 运动学特征工程 | MAIN + ML_BASELINE |
| `ml/pitd_dynamics_engineer.py` | 动力学特征工程 | MAIN + ML_BASELINE |
| `ml/physics_enhancer.py` | 物理增强器 | MAIN（主线使用） |
| `ml/algo_ensemble.py` | LightGBM 集成推理 | 集成推理层 |
| `backtest/` | 回测引擎 | MAIN + ML_BASELINE |
| `data/` | 数据获取层 | MAIN + ML_BASELINE |
| `core/` | 核心算法层 | MAIN + ML_BASELINE |

### 5.5 隔离纪律

**主线代码 [MAIN] 禁止**：
- ❌ 引入 LightGBM/XGBoost 等 ML 模型依赖
- ❌ 引入 `philosophy_feature_engineer.py` 等 V5.5 特征工程
- ❌ 引入 `v51_*/v52_*/v53_*/v54_*/v55_*` 验证脚本
- ❌ 在 `engine.py` 主路径中调用 V5.5 ML 推理

**副线代码 [ML_BASELINE] 禁止**：
- ❌ 修改 `engine.py` 的主决策路径
- ❌ 修改 `halving_top_exit_strategy.py` V4 主策略
- ❌ 修改 `ewave_strategy_adapter.py` 波浪互斥融合规则
- ❌ 直接接入实盘交易系统

**共享基础设施 [SHARED] 修改要求**：
- ⚠️ 修改前必须评估对两条线的影响
- ⚠️ 修改后必须运行两条线的测试
- ⚠️ 物理引擎（pitd_*）的修改需特别谨慎

### 5.6 晋升与回退机制

**副线晋升为主线**（需同时满足）：
1. 9年回测年化 ≥ 56.43%（主线基线）
2. 夏普 ≥ 1.41
3. 最大回撤 ≤ -43.31%
4. Walk-Forward 样本外 AUC ≥ 0.60
5. 多币种验证（BTC + ETH + SOL）均优于主线

**主线回退**（任一触发）：
1. 实盘连续 3 个月跑输纯 V4 基线
2. 最大回撤超过 V4 基线的 120%（即 > 53.24%）
3. 减半周期预测失败（2025年10月后 BTC 未见顶）

### 5.7 相关文件索引

| 文件 | 说明 |
|-----|------|
| [`docs/STRATEGY_LINES.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/STRATEGY_LINES.md) | ⭐ 策略线管理总纲（完整版） |
| [`ml/v55_baseline/README.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v55_baseline/README.md) | V5.5 ML 副线工作区说明 |
| [`ml/halving_top_exit_strategy.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/halving_top_exit_strategy.py) | V4基线策略实现 |
| [`ml/ewave_strategy_adapter.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/ewave_strategy_adapter.py) | 波浪策略适配器（互斥融合） |
| [`ml/comprehensive_strategy_comparison.py`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/comprehensive_strategy_comparison.py) | 综合策略对比回测 |
| [`ml/v2_baseline_optimization_principles.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/v2_baseline_optimization_principles.md) | V4基线优化原则（完整版） |
| [`ml/engineering_algorithm_roadmap.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/engineering_algorithm_roadmap.md) | V4基线后工程算法实践路线图 |
| [`docs/TECHNICAL_DESIGN.md`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/TECHNICAL_DESIGN.md) | 技术设计文档 |

---

## 6. 模块依赖关系

### 6.1 内部依赖图

```
                    ┌─────────────────────────┐
                    │       engine.py         │  主引擎编排
                    │  (compute_full_*)       │
                    │  evaluate_btc_wind_vane │
                    │  compute_value_risk     │
                    │  evaluate_addon         │
                    └────┬───────┬──────┬────┘
                         │       │      │
              ┌──────────┘       │      └──────────────┐
              │                  │                     │
    ┌─────────▼────────┐ ┌──────▼─────────┐ ┌────────▼──────────┐
    │  core/           │ │  signals.py    │ │ exit_integration.py│
    │  五大算法        │ │  Freqtrade信号 │ │ ClassicExitSystem  │
    │  价值风险/加仓   │ │                │ │                   │
    │  极端风控        │ │                │ │                   │
    └────────┬─────────┘ └──────┬─────────┘ └────────┬──────────┘
             │                  │                     │
             │           ┌──────▼─────────┐           │
             │           │ classic_bridge │           │
             │           │   (HTTP)       │           │
             │           └────────────────┘           │
             │                                        │
    ┌────────▼─────────┐                     ┌────────▼──────────┐
    │  data/           │                     │ 10-经典指标系统    │
    │  market_data.py  │                     │ (外部依赖)         │
    │  fundamental.py  │                     └───────────────────┘
    └────────┬─────────┘
             │
    ┌────────▼─────────┐
    │ OKX API / A系列研报│
    │ (外部数据源)      │
    └───────────────────┘

【集成推理层（独立）】
    ┌──────────────────────────────────────────────┐
    │  ml/  (集成推理模块，被动调用，不反向依赖)      │
    │  ┌──────────────┐  ┌─────────────────────┐  │
    │  │ algo_ensemble│  │ llm_reasoning       │  │
    │  │ (LightGBM)   │  │ (DeepSeek LLM)      │  │
    │  └───────┬──────┘  └──────────┬──────────┘  │
    │          └──────────┬─────────┘             │
    │                  label_samples.py            │
    │                (标注+训练工具)                │
    └──────────────────────────────────────────────┘
       ▲
       └── 外部调用 (screen_executor.py) 主动调用
```

### 6.2 内部依赖方向

| 模块 | 依赖 | 被谁依赖 |
|------|------|---------|
| `core/config.py` | 无 | indicators, trend_consistency, dynamic_weights, risk_reward, engine |
| `core/indicators.py` | core/config | trend_consistency, risk_reward, engine |
| `core/trend_consistency.py` | core/config, core/indicators | engine |
| `core/dynamic_weights.py` | core/config, core/indicators | engine |
| `core/fusion.py` | 无 | engine |
| `core/risk_control.py` | core/config | engine |
| `core/risk_reward.py` | core/config, core/indicators | engine |
| `data/market_data.py` | 无 | engine |
| `data/fundamental_data.py` | 无 | engine |
| `signal_pool/scanner.py` | data/market_data | 外部调用 |
| `backtest/*` | core/*, engine, data/* | 外部调用 |
| `ml/*` | core/indicators, backtest | 外部调用 (screen_executor.py 等) |
| `ml/algo_ensemble.py` | 无（纯数据输入输出） | 外部调用 |
| `ml/llm_reasoning.py` | 无（DeepSeek API） | 外部调用 |
| `ml/label_samples.py` | data/market_data, ml/algo_ensemble | 手动运行 |
| `signals.py` | classic_bridge | engine |
| `exit_integration.py` | classic_bridge | engine |
| `classic_bridge.py` | 无 | signals, exit_integration |
| `engine.py` | core/*, data/*, signals, exit_integration | 外部调用 |

### 6.3 导入兼容机制

所有支持模块导入的文件均实现了 **相对导入 / 绝对导入 双兼容**（try-except 模式），确保：
- 作为包导入时（`from core import ...`）正常工作
- 直接运行脚本时（`python engine.py`）也正常工作

---

## 7. 公开 API 清单

### 7.1 主引擎 API

| 函数 | 输入 | 输出 | 用途 |
|------|------|------|------|
| [`compute_full_trading_signal()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L828-L995) | `spot_inst`, `is_btc` | 完整信号 dict | **完整入口**：自动获取K线+基本面，计算完整信号（含风向标+价值风险） |
| [`compute_trend_signal_from_dataframes()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L693-L825) | `weekly_df`, `daily_df`, `symbol`, `price`, `fundamental_data`, `freqtrade_signals`, `is_btc`, `btc_daily_df`, `btc_weekly_df` | 完整信号 dict | **纯计算入口**：数据由调用方提供，适合回测/单元测试 |
| [`five_algo_decision()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L548-L690) | `trend_consistent`, `direction`, `confidence`, `freqtrade_signals`, `freqtrade_consistent`, `btc_wind_vane` | `{action, confidence, position, reason, wind_vane_blocked}` | 五大算法决策 + 风向标闸门（ENTER_LONG/ENTER_SHORT/WAIT） |
| [`evaluate_btc_wind_vane()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L89-L212) | `btc_daily_df`, `btc_weekly_df` | `{long_gate_open, short_gate_open, force_long, ...}` | BTC风向标闸门评估（宏观方向过滤） |
| [`compute_value_risk_assessment()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L271-L314) | `symbol`, `direction`, `current_price`, `daily_df`, `is_btc`, `btc_daily_df` | `{elder_ray, volatility, take_profit_stop_loss, value_gt_risk}` | 价值风险评估（Elder-ray + 波动率 + RR） |
| [`evaluate_addon_decision()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L317-L372) | `symbol`, `direction`, `current_price`, `entry_price`, `is_btc`, `daily_df`, `unrealized_pnl_pct`, `current_position_pct` | `{can_add, addon_type, addon_pct, reason}` | 加仓决策评估（逆势背离 + 顺势趋势强度） |
| [`confidence_to_position()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L215-L233) | `confidence` (0-100) | `{position_pct, tier}` | 置信度 → 仓位映射 |

### 7.2 经典系统集成 API

| 函数 | 输入 | 输出 | 用途 |
|------|------|------|------|
| [`fetch_entry_signals_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L169-L194) | `symbol`, `timeframes` | `{tf: MultiStrategySignal}` | 获取经典系统入场信号 |
| [`evaluate_exit_from_classic()`](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py#L196-L246) | `position_info`, `candles_1h`, `regime` | `{action, confidence, reason, ...}` | 获取经典系统离场决策 |

### 7.3 核心算法 API (core/)

| 函数 | 所在文件 | 输入 | 输出 |
|------|---------|------|------|
| `calc_trend_consistency()` | [trend_consistency.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py#L130) | weekly_df, daily_df | `{weekly, daily, consistent, overall_direction, ...}` |
| `calc_bayesian_confidence()` | [dynamic_weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L140) | weekly_df, daily_df | `{direction, confidence, bull_probability, bear_probability, ...}` |
| `fuse_technical_fundamental()` | [fusion.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py#L33) | technical_result, fundamental_result | `{final_direction, final_confidence, consistent, conflict_level, ...}` |
| `calc_trend_direction_static()` | [indicators.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py#L189) | df, indicators | `"BULL"/"BEAR"/"NEUTRAL"` |
| `calc_trend_direction_dynamic()` | [trend_consistency.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py#L42) | df, indicators | `{direction, confidence, reversal_score, avg_speed, ...}` |
| `calc_dynamic_weights()` | [dynamic_weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py#L78) | df, indicators | `{weights, performance, total_score}` |
| `calc_indicator_dynamics()` | [indicators.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py#L36) | df, indicator_name | `{direction, speed, acceleration, value, ...}` |

### 7.4 价值风险与加仓 API (core/risk_reward.py)

| 函数 | 输入 | 输出 |
|------|------|------|
| `calc_elder_ray()` | klines, period | `{direction, strength, bull_power, bear_power, ema_slope, divergence, ...}` |
| `calc_30d_volatility()` | closes | float（年化波动率） |
| `get_vol_adjusted_params()` | coin_vol, btc_vol, base_tp_pct, base_addon_pct | `{vol_ratio, adjusted_tp_pct, adjusted_addon_pct, ...}` |
| `calc_risk_reward_ratio()` | direction, current_price, entry_price, stop_loss, take_profit | `{rr_ratio, value_gt_risk, risk_amount, reward_amount}` |
| `evaluate_addon_opportunity()` | symbol, direction, current_price, entry_price, ... | `{can_add, addon_type, addon_pct, reason, ...}` |
| `calc_position_sizing()` | confidence, equity, current_price, leverage, ... | `{position_usd, position_size, position_pct}` |

### 7.5 数据层 API (data/)

| 函数 | 所在文件 | 输入 | 输出 |
|------|---------|------|------|
| `fetch_candles()` | [market_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py#L22) | inst_id, bar, limit | `[{o,h,l,c,vol,...}]` |
| `resample_candles()` | [market_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py#L80) | candles, target_tf | `[{o,h,l,c,vol,...}]` |
| `fetch_fundamental_data()` | [fundamental_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L394) | symbol | `{direction, confidence, weekly, daily, reports, ...}` |
| `fetch_fundamental_by_timeframe()` | [fundamental_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py#L435) | symbol | `{weekly: {...}, daily: {...}}` |

### 7.6 集成推理层 API (ml/)

| 函数 | 所在文件 | 输入 | 输出 |
|------|---------|------|------|
| `predict_ensemble()` | [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | full_signal | `{direction, confidence, prob_up, prob_down, source, features}` |
| `collect_sample()` | [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | full_signal, symbol, future_return | 无（写入 jsonl） |
| `train_ensemble()` | [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | label_lookahead, test_ratio | 训练结果 dict |
| `extract_ensemble_features()` | [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | full_signal | 特征 dict（46维） |
| `reason_if_needed()` | [ml/llm_reasoning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) | full_signal, ensemble_pred | 推理结果 dict |
| `should_trigger_llm()` | [ml/llm_reasoning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) | ensemble_pred, full_signal | `(should_trigger, reason)` |
| `reason_with_llm()` | [ml/llm_reasoning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) | full_signal, ensemble_pred | 推理结果 dict |
| `label_collected_samples()` | [ml/label_samples.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/label_samples.py) | lookahead_days | 标注统计 dict |
| `train_from_collected()` | [ml/label_samples.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/label_samples.py) | lookahead_days, test_ratio | 训练结果 dict |

---

## 8. 配置参数清单

### 8.1 指标组配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `SCREEN1_INDICATORS` | 5个 | 周线指标组: RSI_50, SuperTrend, StochRSI_Cross, OBV_Trend, Keltner_Channel | [config.py L17](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L17) |
| `SCREEN2_INDICATORS` | 6个 | 日线指标组: GoldenCross_50_200, MACD_Cross, Vortex, TEMA, EMA_Align_20_50_200, Elder_ray | [config.py L21](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L21) |

### 8.2 权重配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `WEEKLY_WEIGHT` | 0.6 | 周线权重（准确度更高） | [config.py L25](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L25) |
| `DAILY_WEIGHT` | 0.4 | 日线权重 | [config.py L26](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L26) |
| `TECHNICAL_WEIGHT` | 0.6 | 技术面权重（撮合时） | [config.py L32](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L32) |
| `FUNDAMENTAL_WEIGHT` | 0.4 | 基本面权重（撮合时） | [config.py L33](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L33) |

### 8.3 逆转检测配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `REVERSAL_THRESHOLD` | 60.0 | 逆转覆盖阈值(%)，超过则动态方向覆盖静态 | [config.py L28](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L28) |
| `REVERSAL_SPEED_LOW` | 30.0 | 逆转速度下限：speed 低于此值可能逆转 | [config.py L29](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L29) |
| `REVERSAL_ACCEL_HIGH` | 20.0 | 逆转加速度上限：accel 高于此值可能逆转 | [config.py L30](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L30) |

### 8.4 撮合配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `MAX_CONFLICT_DEDUCTION` | 0.3 | 方向矛盾时最大扣减比例 | [config.py L34](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L34) |

### 8.5 决策阈值配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `OPEN_CONFIDENCE_THRESHOLD` | 60.0 | 正常入场置信度阈值(%) | [config.py L36](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L36) |
| `TRIAL_CONFIDENCE_THRESHOLD` | 45.0 | 轻仓试探置信度阈值(%) | [config.py L37](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L37) |

### 8.6 仓位配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `POSITION_TIERS` | 6档 | 置信度→仓位映射: 85→60%, 75→45%, 65→30%, 55→15%, 45→5%, 0→2% | [config.py L39](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L39) |
| `CONFIDENCE_JUMP_THRESHOLD` | 15.0 | 顺势加仓置信度跃迁阈值(%) | [config.py L47](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L47) |
| `COUNTER_TREND_ADDON_BUDGET` | 0.4 | 逆势加仓预算比例（旧版） | [config.py L48](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L48) |
| `TOTAL_POSITION_BUDGET_CAP` | 0.8 | 总仓位硬上限（旧版） | [config.py L49](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L49) |

### 8.7 逐仓模式配置（Phase 3）

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `MARGIN_MODE` | "isolated" | 逐仓模式（风险隔离） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `MAX_LEVERAGE` | 5.0 | 最大杠杆倍数 | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `MAX_POSITION_PCT` | 0.50 | 初始最大仓位（50%） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `MAX_ADDON_POSITION_PCT` | 0.70 | 加仓后最大仓位（70%） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |

### 8.8 价值风险与加仓配置（Phase 3）

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `BTC_DIVERGENCE_ADDON_PCT` | 0.08 | BTC背离加仓亏损阈值（8%） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `BASE_TAKE_PROFIT_PCT` | 0.04 | 基准止盈比例（BTC，4%） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `BASE_STOP_LOSS_PCT` | 0.10 | 基准止损比例（BTC，10%） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `RISK_REWARD_THRESHOLD` | 1.5 | 风险回报比阈值（价值>风险的判定线） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `TREND_STRENGTH_ADDON_THRESHOLD` | 65.0 | 顺势加仓趋势强度阈值 | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `MAX_ADDON_COUNT` | 2 | 最大加仓次数 | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |

### 8.9 BTC风向标配置（Phase 3.1）

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `BTC_WIND_VANE_DAILY_MA` | 128 | 日线MA周期（跌破检测） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `BTC_WIND_VANE_WEEKLY_MA` | 200 | 周线MA周期（站上检测） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `BTC_WIND_VANE_BREAK_DAYS` | 3 | 连续跌破确认天数（避免假跌破） | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |
| `BTC_WIND_VANE_ENABLED` | True | 风向标总开关 | [config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) |

### 8.10 币种池配置

| 参数 | 值 | 说明 | 位置 |
|------|----|------|------|
| `CANDIDATE_COINS` | 9个 | BTC, ETH, SOL, BNB, HYPE, UNI, ARB, ZEC, DOGE | [config.py L5](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L5) |
| `DEFAULT_INST_SPOT` | "BTC-USDT" | 默认现货交易对 | [config.py L51](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L51) |
| `DEFAULT_INST_SWAP` | "BTC-USDT-SWAP" | 默认合约交易对 | [config.py L52](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py#L52) |

---

## 9. 数据结构清单

### 9.1 核心数据类

| 类名 | 所在文件 | 字段 | 用途 |
|------|---------|------|------|
| `SignalDirection` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L19) | LONG, SHORT, HOLD | Freqtrade信号方向枚举 |
| `StrategySignal` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L26) | strategy_name, signal, confidence, reason | 单策略信号 |
| `MultiStrategySignal` | [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py#L35) | symbol, timeframe, direction, confidence, strategy_count, long_votes, short_votes, strategies | 多策略投票信号 |
| `ExitAction` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L23) | CLOSE, REDUCE, HOLD | 离场动作枚举 |
| `PositionInfo` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L30) | symbol, side, entry_price, current_price, quantity, entry_time, notional_usd | 持仓信息 |
| `ExitDecisionResult` | [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py#L44) | action, confidence, reason, priority, reduce_fraction, suggested_price, triggered_by | 离场决策结果 |

### 9.2 完整信号返回结构

`compute_trend_signal_from_dataframes()` 返回的 dict 结构：

```
{
  symbol: str,
  price: float,
  generated_at: str (ISO),
  spot_inst: str,
  is_btc: bool,
  timeframes: { weekly: int, daily: int },
  indicators: { screen1_weekly: [...], screen2_daily: [...] },
  trend_consistency: {
    weekly: { static_direction, dynamic_direction, final_direction, confidence, reversal_score, ... },
    daily: { ... },
    consistent: bool,
    overall_direction: str,
    consistency_confidence: float,
  },
  bayesian_confidence: {
    direction: str,
    confidence: float,
    bull_probability: float,
    bear_probability: float,
    weekly_weights: { ... },
    daily_weights: { ... },
  },
  classic_indicator_confidence: { ... },
  fundamental_data: {
    direction: str,
    confidence: float,
    weekly: { date, direction, confidence, regime, score, source_file },
    daily: { date, direction, confidence, regime, score, source_file },
    reports: [...],
    bull_count: int,
    bear_count: int,
    total_reports: int,
  },
  freqtrade_signals: {
    "1h": { signal, confidence, ... },
    "4h": { ... },
  },
  technical_fundamental_fusion: {
    technical: { direction, confidence },
    fundamental: { direction, confidence },
    consistent: bool,
    final_direction: str,
    final_confidence: float,
    conflict_level: float,
    ...
  },
  btc_wind_vane: {                           // Phase 3.1: BTC风向标状态
    enabled: bool,
    long_gate_open: bool,
    short_gate_open: bool,
    force_long: bool,
    prohibit_short: bool,
    prohibit_long: bool,
    btc_daily_ma128: float,
    btc_weekly_ma200: float,
    btc_last_daily_close: float,
    btc_last_weekly_close: float,
    consecutive_below_ma128: int,
    weekly_above_ma200: bool,
    daily_below_ma128_confirmed: bool,
    reason: str,
  },
  value_risk_assessment: {                   // Phase 3: 价值风险评估
    symbol: str,
    direction: str,
    current_price: float,
    elder_ray: { direction, strength, divergence, ... },
    volatility: { vol_ratio, coin_vol, btc_vol, ... },
    take_profit_stop_loss: {
      take_profit_price: float,
      stop_loss_price: float,
      take_profit_pct: float,
      stop_loss_pct: float,
      risk_reward: { rr_ratio, value_gt_risk, ... },
    },
    value_gt_risk: bool,
  },
  final_signal: {
    direction: str,
    confidence: float,
    trend_consistent: bool,
    fusion_consistent: bool,
    freqtrade_consistent: bool,
    wind_vane_blocked: bool,              // Phase 3.1: 是否被风向标拦截
    action: str (ENTER_LONG/ENTER_SHORT/WAIT),
    position: {
      position_pct: float,
      tier: str,
      original_position_pct: float,
    },
    decision_reason: str,
    leverage: float,                       // Phase 3: 杠杆倍数
    margin_mode: str,                      // Phase 3: 逐仓/全仓
    max_position_pct: float,               // Phase 3: 最大仓位
    max_addon_position_pct: float,         // Phase 3: 加仓后最大仓位
  },
}
```

### 9.3 集成推理层数据结构

**predict_ensemble() 返回结构**（LightGBM 集成推理）：

```
{
  direction: "BULL" | "BEAR" | "NEUTRAL",
  confidence: float (0-100),
  prob_up: float (0-1),
  prob_down: float (0-1),
  source: "ensemble" | "fallback",
  features: { ... 46维特征 ... },
}
```

**reason_if_needed() / reason_with_llm() 返回结构**（LLM 辩证推理）：

```
{
  direction: "BULL" | "BEAR" | "NEUTRAL",
  confidence: int (0-100),
  source: "llm_reasoning" | "ensemble_direct" | "ensemble_fallback",
  contradiction_analysis: str,
  reasoning: str,
  risk_note: str,
  trust_weight: { trend: float, bayes: float, classic: float, fundamental: float },
  contradictions: [str, ...],
  trigger_reason: str,
}
```

**训练样本结构**（collected/samples_*.jsonl 每行）：

```
{
  _symbol: str,
  _timestamp: str (ISO),
  _future_return: float | null,   // 未来N日收益率（标注后填充）
  _price: float,
  ... 46维特征 ...
}
```

---

## 10. 外部接口清单

### 10.1 外部依赖系统

| 外部系统 | 接口方式 | 用途 | 调用模块 |
|---------|---------|------|---------|
| **10-经典指标系统** | HTTP API / 直接导入 | Freqtrade 入场信号 | `signals.py` → `classic_bridge.py` |
| **10-经典指标系统** | HTTP API / 直接导入 | ClassicExitSystem 离场决策 | `exit_integration.py` → `classic_bridge.py` |
| **OKX API** | REST API | K线数据获取 | `data/market_data.py` |
| **A系列研报** | 文件读取 | 基本面数据 | `data/fundamental_data.py` |
| **talib** | Python import | 指标计算（从10-经典系统导入） | `core/indicators.py` |

### 10.2 A系列研报路径

| 研报类型 | 路径 | 格式 | 对应周期 |
|---------|------|------|---------|
| 周报 | `experiments/ab-trading/A系列研报/周报/screen1_YYYYMMDD.md` | Markdown + frontmatter | 周线 |
| A1日报 | `experiments/ab-trading/A系列研报/A1研报/a1_regime_YYYYMMDD.json` | JSON | 日线 |

### 10.3 经典系统 HTTP 接口

| 端点 | 方法 | 用途 | 调用方 |
|------|------|------|-------|
| `/api/freqtrade/signals` | GET | 获取 Freqtrade 多策略信号 | `signals.py` |
| `/api/exit/evaluate` | POST | 获取离场决策 | `exit_integration.py` |
| `/api/health` | GET | 健康检查 | `classic_bridge.py` |

Base URL 配置：环境变量 `CLASSIC_SYSTEM_BASE_URL`，默认 `http://localhost:8092`

---

## 11. 测试覆盖

### 11.1 测试运行

```bash
cd 12-三屏趋势系统
python3 tests/test_core.py
```

### 11.2 测试用例清单

| 测试函数 | 覆盖模块 | 测试点 |
|---------|---------|--------|
| `test_confidence_to_position()` | engine.py | 5档仓位映射正确性 |
| `test_five_algo_decision()` | engine.py | 五大算法决策：OPEN/TRIAL/WAIT |
| `test_trend_consistency()` | core/trend_consistency.py | 趋势一致性：一致/不一致场景 |
| `test_bayesian_confidence()` | core/dynamic_weights.py | 贝叶斯置信度计算 |
| `test_fusion()` | core/fusion.py | 技术面+基本面撮合：一致/中性/矛盾 |
| `test_full_signal()` | engine.py | 完整信号计算 + Freqtrade信号校准 |
| `test_fundamental_data()` | data/fundamental_data.py | A系列研报读取 + 周报/A1日报解析 + 合并 |

### 11.3 合成数据生成

测试使用 `_generate_synthetic_data()` 函数生成合成K线数据，支持 `bull` / `bear` / `sideways` 三种趋势模式，不依赖真实市场数据。

---

**文档版本**: ENGINEERING_INDEX v1.2
**最后更新**: 2026-07-16
