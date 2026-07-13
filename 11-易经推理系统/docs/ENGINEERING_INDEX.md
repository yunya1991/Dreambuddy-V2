# 易经推理系统工程索引

**版本**: 2.0.0 | **日期**: 2026-07-13

---

## 目录结构

```
11-易经推理系统/
├── configs/                    # 配置文件目录
│   └── baseline_config.json    # BCRM 2.0基线配置
│
├── docs/                       # 技术文档目录
│   ├── README.md               # 项目概览与快速开始
│   ├── TECHNICAL_DESIGN.md     # 技术设计文档
│   ├── architecture.md         # 系统架构图
│   ├── ENGINEERING_INDEX.md    # 本文件
│   └── superpowers/            # Superpowers方法论集成
│       ├── plans/              # 执行计划
│       └── specs/              # 设计规范
│
├── scripts/                    # 核心代码目录
│   └── memory_l4/
│       └── bcrm2/              # BCRM 2.0量化引擎
│           ├── run_phase0_validation.py   # Phase 0回测主入口
│           ├── walk_forward_backtester.py # Walk-Forward回测引擎
│           ├── portfolio_backtester.py    # 组合回测引擎
│           ├── bagua_feature_engine.py    # 八卦特征引擎
│           ├── classic_features.py        # 经典经验特征
│           ├── fibonacci_features.py      # 斐波那契特征
│           ├── pivot_point_features.py    # 枢纽点特征
│           ├── wdh_features.py            # WDH时间维度特征
│           ├── inventory_cycle_features.py # 库存周期特征
│           ├── market_cap_features.py     # 市值等级特征
│           ├── cross_asset_features.py    # 跨资产特征
│           ├── merrill_clock_features.py  # 美林时钟特征
│           ├── meta_labeling_features_v2.py # Meta-Labeling V2
│           ├── rsi_sentiment_features.py  # RSI情绪特征
│           ├── feature_selection.py       # 特征选择模块
│           ├── dialectical_ml_engine.py   # 辩证ML引擎
│           ├── market_regime.py           # 市态切换引擎
│           ├── market_cap.py              # 市值等级配置
│           ├── anomaly_detection.py       # 异常检测
│           ├── data_fetcher.py            # 数据获取服务
│           ├── polling_trader.py          # 实盘交易引擎
│           ├── incremental_learning.py    # 增量学习模块
│           ├── model_version_manager.py   # 模型版本管理
│           └── trade_database.py          # 交易数据库
│
├── data/                       # 数据存储目录
│   ├── bcrm2_phase0/           # Phase 0回测结果
│   │   ├── report_BTC_1H.txt
│   │   ├── report_ETH_1H.txt
│   │   ├── report_SOL_1H.txt
│   │   ├── report_UNI_1H.txt
│   │   ├── trades_BTC_1H.csv
│   │   ├── trades_ETH_1H.csv
│   │   ├── trades_SOL_1H.csv
│   │   ├── trades_UNI_1H.csv
│   │   ├── portfolio_timeline_1H.csv
│   │   └── combined_results/
│   └── training/               # 训练数据与历史回测
│       └── backtest_result_*.json
│
├── models/                     # 模型存储目录
│   └── incremental/            # 增量学习模型
│
└── .workbuddy/                 # WorkBuddy集成
    ├── shared_knowledge/
    │   └── evolved_params.json # 进化参数
    └── ignore_patterns.json
```

---

## 核心模块索引

### 回测引擎

| 文件 | 功能 | 关键函数/类 |
|------|------|------------|
| [run_phase0_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/run_phase0_validation.py) | Phase 0回测主入口 | `main()` |
| [walk_forward_backtester.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/walk_forward_backtester.py) | Walk-Forward回测引擎 | `WalkForwardBacktester`, `run()` |
| [portfolio_backtester.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/portfolio_backtester.py) | 组合回测引擎 | `PortfolioBacktester`, `run()` |

### 特征工程

| 文件 | 功能 | 特征数 |
|------|------|--------|
| [bagua_feature_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/bagua_feature_engine.py) | 八卦特征引擎 | ~111 |
| [classic_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/classic_features.py) | 经典经验特征 | ~30 |
| [fibonacci_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/fibonacci_features.py) | 斐波那契特征 | ~10 |
| [pivot_point_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/pivot_point_features.py) | 枢纽点特征 | ~10 |
| [wdh_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/wdh_features.py) | WDH时间维度 | ~45 |
| [inventory_cycle_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/inventory_cycle_features.py) | 库存周期特征 | ~55 |
| [market_cap_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/market_cap_features.py) | 市值等级特征 | ~10 |
| [cross_asset_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/cross_asset_features.py) | 跨资产特征 | ~33 |
| [merrill_clock_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/merrill_clock_features.py) | 美林时钟特征 | ~55 |
| [meta_labeling_features_v2.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/meta_labeling_features_v2.py) | Meta-Labeling V2 | ~25 |
| [rsi_sentiment_features.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/rsi_sentiment_features.py) | RSI情绪特征 | ~8 |
| [feature_selection.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/feature_selection.py) | 特征选择模块 | - |

### 决策引擎

| 文件 | 功能 | 关键函数/类 |
|------|------|------------|
| [dialectical_ml_engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/dialectical_ml_engine.py) | 辩证ML引擎(L1/L2/L3) | `DialecticalMLEngine` |
| [market_regime.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/market_regime.py) | 市态切换引擎 | `MarketRegimeDetector`, `RegimeParams` |
| [market_cap.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/market_cap.py) | 市值等级配置 | `get_market_cap_features()` |
| [anomaly_detection.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/anomaly_detection.py) | 异常检测 | `AnomalyDetector` |

### 实盘交易

| 文件 | 功能 | 关键函数/类 |
|------|------|------------|
| [polling_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/polling_trader.py) | 实盘交易引擎 | `PollingTrader`, `run()` |
| [incremental_learning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/incremental_learning.py) | 增量学习模块 | `IncrementalLearner` |
| [model_version_manager.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/model_version_manager.py) | 模型版本管理 | `ModelVersionManager` |
| [trade_database.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/trade_database.py) | 交易数据库 | `TradeDatabase` |

### 数据服务

| 文件 | 功能 | 关键函数/类 |
|------|------|------------|
| [data_fetcher.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/data_fetcher.py) | 数据获取服务 | `get_klines()`, `get_bar_value()` |

---

## 配置索引

### 基线配置

**文件**: [configs/baseline_config.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/configs/baseline_config.json)

| 配置项 | 值 | 说明 |
|--------|-----|------|
| 币种 | BTC, ETH, SOL, UNI | 回测币种 |
| K线周期 | 1H | 1小时K线 |
| 数据量 | 6000根 | 约8个月 |
| Walk-Forward折数 | 5 | 80%训练/20%验证 |
| 置信度阈值 | 0.40 | 基础阈值 |
| 止盈 | 3.0x ATR | 动态止盈 |
| 止损 | 2.0x ATR | 动态止损 |
| 最大持仓 | 60根K线 | 约2.5天 |
| 市态切换 | 启用 | 8种市态自适应 |
| 仓位管理 | 启用 | position_factor调整阈值 |
| auto_mcap | 启用 | 按市值等级配置特征 |
| 特征选择 | 启用 | LightGBM重要性+相关性去冗余 |
| 组合回测 | 启用 | 大40%/中35%/小25% |

---

## 文档索引

| 文档 | 内容 | 更新日期 |
|------|------|----------|
| [README.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/README.md) | 项目概览、基线配置、回测结果、快速开始 | 2026-07-13 |
| [TECHNICAL_DESIGN.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/docs/TECHNICAL_DESIGN.md) | 系统架构、核心算法、特征工程、回测引擎、数据流 | 2026-07-13 |
| [architecture.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/docs/architecture.md) | 系统架构图 | - |
| [ENGINEERING_INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/docs/ENGINEERING_INDEX.md) | 目录结构、模块索引、配置索引 | 2026-07-13 |

---

## 回测结果索引

### 最新基线回测 (2026-07-13)

**配置**: 市态切换 + auto_mcap + 特征选择 + 组合回测
**数据**: 6000根1H K线 (2025-11 ~ 2026-07)

#### 单币种表现

| 币种 | 交易数 | 胜率 | 总收益 | 最大回撤 | 盈亏比 | 夏普 |
|------|--------|------|--------|----------|--------|------|
| BTC | 43 | 81.4% | 68.52% | 4.58% | 5.14 | 10.67 |
| ETH | 52 | 71.2% | 53.79% | 14.30% | 2.37 | 5.77 |
| SOL | 65 | 75.4% | 92.92% | 11.20% | 3.02 | 7.88 |
| UNI | 92 | 60.9% | 119.48% | 33.45% | 2.12 | 5.62 |

#### 组合层指标

| 指标 | 数值 |
|------|------|
| 组合总收益 | 86.85% |
| 组合胜率 | 70.2% |
| 组合盈亏比 | 2.61 |
| 组合夏普 | 6.61 |
| 组合最大回撤 | 12.75% |
| 综合夏普(加权) | 7.45 |

### 历史回测记录

| 日期 | 配置 | 综合夏普 | 备注 |
|------|------|----------|------|
| 2026-07-13 | 基线 | 7.45 | 当前基线 |
| 2026-07-13 | 3000根K线 | 1.14 | 4个月数据 |

---

## 快速导航

### 常用命令

```bash
# 单币种回测
cd scripts
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC --timeframe 1H --n-folds 5 --max-bars 6000

# 组合回测（推荐）
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC,ETH,SOL,UNI --timeframe 1H \
  --n-folds 5 --max-bars 6000 --feature-selection --portfolio

# 实盘交易
python -m memory_l4.bcrm2.polling_trader
```

### 关键文件快速定位

| 目标 | 文件路径 |
|------|----------|
| 基线配置 | [configs/baseline_config.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/configs/baseline_config.json) |
| 回测入口 | [scripts/memory_l4/bcrm2/run_phase0_validation.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/run_phase0_validation.py) |
| 市态切换 | [scripts/memory_l4/bcrm2/market_regime.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/market_regime.py) |
| 特征选择 | [scripts/memory_l4/bcrm2/feature_selection.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/feature_selection.py) |
| 实盘交易 | [scripts/memory_l4/bcrm2/polling_trader.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/polling_trader.py) |
| 增量学习 | [scripts/memory_l4/bcrm2/incremental_learning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/scripts/memory_l4/bcrm2/incremental_learning.py) |

---

*Last Updated: 2026-07-13 | BCRM 2.0 Engineering Index*
