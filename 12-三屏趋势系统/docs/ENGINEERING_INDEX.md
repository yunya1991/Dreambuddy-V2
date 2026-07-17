# 三屏趋势系统 - 工程索引

## 1. 概述

三屏趋势系统（Three-Screen Trend System）是基于 Alexander Elder 三重屏幕交易系统理论构建的趋势分析引擎，用于识别跨时间框架的趋势一致性，为交易决策提供趋势过滤信号。

### 1.1 核心定位

| 属性 | 说明 |
|------|------|
| 系统名称 | 三屏趋势系统 |
| 目录位置 | `12-三屏趋势系统/` |
| 主入口 | `engine.py` |
| 核心模块 | `core/` |
| 当前版本 | v1.6（Phase 3.5） |
| 依赖系统 | 经典指标系统（10）、通用风控模块（13）、V15马丁策略（14） |

### 1.2 功能概览

- **趋势分析**：多时间框架趋势分析（周线/日线），静态指标+三维动态融合
- **BTC风向标闸门**：全系统宏观方向过滤器（日线MA128 + 周线MA200）
- **置信度评估**：贝叶斯+经典指标+Freqtrade信号五层融合
- **价值风险评估**：Elder-ray趋势强度、波动率放大、风险回报比
- **逐仓模式**：isolated margin，5x杠杆，50%初始仓位/70%加仓上限
- **加仓系统**：逆势背离加仓 + 顺势趋势强度加仓，最多2次
- **信号池**：Freqtrade多策略信号池（pool.json + scanner）
- **回测引擎**：完整回测、滚动验证、绩效指标、参数敏感性、置信度校准
- **ML策略**：机器学习策略模块，模型版本管理
- **Platt校准**：置信度校准（训练集ECE从22.6%降至1.3%，改善94%）
- **币种池优化**：聚焦9个高流动性币种（BTC/ETH/SOL/BNB/HYPE/UNI/ARB/ZEC/DOGE）
- **综合预测引擎**：技术基线 + 基本面三维度调节（方向/速度/加速度/情绪四维因子）
- **9-基本面分析集成**：接入SignalEngine、SentimentEngine、LeastResistance三维度计算
- **最小阻力方向引擎**（Phase 3.5）：第一性原理，5维度阻力计算（价格/量能/动量/趋势/基本面），动态算法优先于静态指标

### 1.3 决策优先级链

```
优先级0: BTC风向标闸门（宏观方向过滤）
    → 优先级1: 趋势一致性检测
        → 优先级2: 置信度评估
            → 优先级3: Freqtrade入场信号触发
                → 优先级4: 价值风险评估（仓位调整）
```

## 2. 目录结构

```
12-三屏趋势系统/
├── core/                    # 核心算法模块
│   ├── __init__.py
│   ├── config.py            # 配置管理（逐仓/价值风险/风向标）
│   ├── composite_predictor.py # 综合预测引擎（技术基线+基本面三维度调节）
│   ├── dynamic_weights.py   # 动态权重调整
│   ├── fundamental_screen1.py # Path B 核心模块：7维基本面分析（Tavily+算法）
│   ├── fusion.py            # 信号融合（Path A 技术面+基本面撮合）
│   ├── indicators.py        # 技术指标计算
│   ├── least_resistance.py  # Phase 3.5 最小阻力方向引擎（第一性原理）
│   ├── risk_control.py      # 极端行情风控守卫
│   ├── risk_reward.py       # 价值风险评估+仓位+加仓
│   └── trend_consistency.py # 趋势一致性判断
├── data/                    # 数据层
│   ├── __init__.py
│   ├── fundamental_data.py  # Path A 基本面数据（研报系统）
│   ├── market_data.py       # 市场数据
│   └── tavily_data.py       # Path B Tavily 数据采集（矿工/链上/宏观/跨市场）
├── signal_pool/             # Freqtrade信号池
│   ├── pool.json            # 信号池缓存
│   └── scanner.py           # 信号池扫描器
├── backtest/                # 回测引擎
│   ├── engine.py            # 回测核心
│   ├── strategy.py          # 策略定义（含Platt校准集成）
│   ├── metrics.py           # 绩效指标
│   ├── walk_forward.py      # 滚动验证
│   ├── calibration.py       # 置信度校准（Platt/Isotonic）
│   ├── overfitting.py       # 过拟合检测+参数敏感性
│   ├── results.py           # 回测结果封装
│   └── run_backtest.py      # 回测入口
├── ml/                      # 机器学习策略
│   ├── ml_strategy.py       # ML策略核心
│   ├── models.py            # 模型定义
│   ├── tuner.py             # 超参调优
│   └── version_manager.py   # 版本管理
├── tests/                   # 测试
│   ├── __init__.py
│   └── test_core.py         # 核心模块测试
├── docs/                    # 文档
│   ├── ENGINEERING_INDEX.md # 工程索引（本文档）
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档
│   └── trend-screen-system-design.md
├── classic_bridge.py        # 经典指标系统桥接
├── engine.py                # 主引擎
├── exit_integration.py      # 离场系统集成
├── signals.py               # Freqtrade信号读取
├── start_services.sh       # 服务启动脚本
├── README.md
└── __init__.py
```

## 3. 关键文件说明

### 3.1 核心模块

| 文件 | 功能说明 |
|------|----------|
| `core/config.py` | 配置加载与验证（基础+逐仓+价值风险+风向标共20+配置项） |
| `core/indicators.py` | 技术指标计算（MA、EMA、MACD、RSI、KDJ等静态+三维动态） |
| `core/trend_consistency.py` | 三屏趋势一致性判断核心（静态投票+三维动态融合+动态优先） |
| `core/dynamic_weights.py` | 基于趋势强度的动态权重调整 |
| `core/fundamental_screen1.py` | **Path B 核心**：7维基本面分析（Tavily API + 减半周期 + 算法评分） |
| `core/fusion.py` | **Path A 融合**：技术面+基本面撮合（研报数据→最终方向） |
| `core/risk_reward.py` | 价值风险评估、Elder-ray、波动率放大、加仓决策 |
| `core/risk_control.py` | 极端行情风控守卫 |
| `core/least_resistance.py` | **Phase 3.5 第一性原理**：最小阻力方向引擎（5维阻力计算：价格/量能/动量/趋势/基本面） |

### 3.2 数据层

| 文件 | 功能说明 |
|------|----------|
| `data/market_data.py` | 市场行情数据获取与缓存（多周期K线） |
| `data/fundamental_data.py` | **Path A 数据源**：A系列研报读取（周报MD + A1日报JSON） |
| `data/tavily_data.py` | **Path B 数据源**：Tavily API 实时搜索（矿工/链上/宏观/跨市场 4维，30分钟缓存） |

### 3.3 信号与集成模块

| 文件 | 功能说明 |
|------|----------|
| `engine.py` | 主引擎入口。五大算法决策+风向标闸门+价值风险+加仓 |
| `signals.py` | Freqtrade信号读取与对齐（1h/4h多策略） |
| `classic_bridge.py` | 与经典指标系统的桥接接口 |
| `exit_integration.py` | 离场系统集成点（ClassicExitSystem） |
| `signal_pool/scanner.py` | 信号池扫描器，多币种多策略扫描 |

### 3.4 回测与ML

| 文件 | 功能说明 |
|------|----------|
| `backtest/engine.py` | 回测核心引擎 |
| `backtest/strategy.py` | 策略定义（含Platt置信度校准集成、便捷训练方法） |
| `backtest/metrics.py` | 绩效指标计算 |
| `backtest/walk_forward.py` | 滚动向前验证 |
| `backtest/calibration.py` | 置信度校准（Platt缩放 / Isotonic回归 / Beta校准） |
| `backtest/overfitting.py` | 过拟合检测 + 参数敏感性分析 + 置换检验 |
| `backtest/results.py` | 回测结果封装与报告 |
| `ml/ml_strategy.py` | ML策略核心 |
| `ml/version_manager.py` | 模型版本管理 |

## 4. 依赖关系

### 4.1 外部依赖

| 依赖 | 版本要求 | 用途 |
|------|----------|------|
| pandas | >=1.5.0 | 数据处理 |
| numpy | >=1.21.0 | 数值计算 |
| talib | >=0.4.0 | 技术指标计算 |
| requests | >=2.28.0 | HTTP请求 |
| scikit-learn | >=1.0.0 | ML策略（可选） |

### 4.2 内部依赖

| 系统 | 依赖方式 | 用途 |
|------|----------|------|
| 10-经典指标系统 | 桥接调用 | Freqtrade入场信号、离场决策、候选币种 |
| 13-通用风控模块 | 接口调用 | 风控评估、极端行情守卫 |
| 14-V15经典马丁策略 | 执行层对接 | 马丁策略执行参考 |

## 5. 配置管理

### 5.1 配置文件

配置通过 `core/config.py` 加载，支持以下配置项：

#### 基础配置

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `CANDIDATE_COINS` | 见下表 | 候选币种列表（9个高流动性币种） |
| `SCREEN1_INDICATORS` | [EMA, MACD, ...] | Screen1周线指标 |
| `SCREEN2_INDICATORS` | [RSI, KDJ, ...] | Screen2日线指标 |
| `WEEKLY_WEIGHT` | 0.4 | 周线权重 |
| `DAILY_WEIGHT` | 0.6 | 日线权重 |
| `REVERSAL_THRESHOLD` | 60 | 逆转检测阈值 |
| `OPEN_CONFIDENCE_THRESHOLD` | 60 | 开仓置信度阈值 |
| `TRIAL_CONFIDENCE_THRESHOLD` | 45 | 试探仓阈值 |
| `CONFIDENCE_JUMP_THRESHOLD` | 15 | 置信度跳升阈值 |

#### 币种池配置（9个高流动性币种）

| 币种 | 现货交易对 | 永续合约 | 核心 | 说明 |
|------|-----------|---------|------|------|
| BTC | BTC-USDT | BTC-USDT-SWAP | ✅ | 风向标基准币 |
| ETH | ETH-USDT | ETH-USDT-SWAP | ✅ | 市值第二 |
| SOL | SOL-USDT | SOL-USDT-SWAP | ✅ | 高波动 |
| BNB | BNB-USDT | BNB-USDT-SWAP | ✅ | 平台币龙头 |
| HYPE | HYPE-USDT | HYPE-USDT-SWAP | - | Meme赛道 |
| UNI | UNI-USDT | UNI-USDT-SWAP | - | DeFi龙头 |
| ARB | ARB-USDT | ARB-USDT-SWAP | - | L2龙头 |
| ZEC | ZEC-USDT | ZEC-USDT-SWAP | - | 隐私币龙头 |
| DOGE | DOGE-USDT | DOGE-USDT-SWAP | - | Meme龙头 |

#### Phase 3: 逐仓 + 价值风险 + 加仓

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `MARGIN_MODE` | "isolated" | 逐仓模式 |
| `MAX_LEVERAGE` | 5.0 | 最大杠杆 |
| `MAX_POSITION_PCT` | 0.50 | 初始最大仓位 |
| `MAX_ADDON_POSITION_PCT` | 0.70 | 加仓后最大仓位 |
| `BTC_DIVERGENCE_ADDON_PCT` | 0.08 | BTC背离加仓亏损阈值 |
| `BASE_TAKE_PROFIT_PCT` | 0.04 | 基准止盈比例（BTC） |
| `BASE_STOP_LOSS_PCT` | 0.10 | 基准止损比例（BTC） |
| `RISK_REWARD_THRESHOLD` | 1.5 | 风险回报比阈值 |
| `TREND_STRENGTH_ADDON_THRESHOLD` | 65.0 | 顺势加仓趋势强度阈值 |
| `MAX_ADDON_COUNT` | 2 | 最大加仓次数 |

#### Phase 3.1: BTC风向标

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `BTC_WIND_VANE_DAILY_MA` | 128 | 日线MA周期 |
| `BTC_WIND_VANE_WEEKLY_MA` | 200 | 周线MA周期 |
| `BTC_WIND_VANE_BREAK_DAYS` | 3 | 连续跌破确认天数 |
| `BTC_WIND_VANE_ENABLED` | True | 风向标总开关 |

### 5.2 环境变量

暂无专用环境变量，配置通过 `core/config.py` 默认值即可运行。

## 6. 部署与运行

### 6.1 启动方式

```bash
# 直接运行引擎
python engine.py

# 启动服务（含信号池扫描）
./start_services.sh

# 运行回测
python backtest/run_backtest.py
```

### 6.2 运行模式

- **实时模式**：实时获取行情数据，输出趋势信号
- **回测模式**：基于历史数据进行趋势分析验证
- **ML模式**：机器学习策略回测与验证

### 6.3 服务架构

```
12-三屏趋势系统
    ↓（信号输出）
    ↓
experiments/ab-trading/screen_executor.py  ← 执行层
    （逐仓下单、止盈止损、加仓执行）
```

## 7. 测试体系

### 7.1 测试文件

| 文件 | 测试内容 |
|------|----------|
| `tests/test_core.py` | 核心模块单元测试 |

### 7.2 验证场景

BTC风向标闸门验证（6场景全通过）：

| 场景 | 验证点 |
|------|--------|
| 做空闸门打开 | 连续3日<MA128，周线<MA200 |
| 强制做多 | 周收盘>MA200 |
| 优先级验证 | 同时跌破MA128+站上MA200 → force_long优先 |
| 中间状态 | 双向开放，无拦截 |
| 端到端集成 | BTC自身风向标注入结果 |
| 跨币种过滤 | SOL使用BTC风向标数据过滤 |

### 7.3 测试命令

```bash
cd 12-三屏趋势系统 && python -m pytest tests/ -v
```

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 技术设计文档 | `docs/TECHNICAL_DESIGN.md` |
| 主引擎入口 | `engine.py` |
| BTC风向标闸门 | `engine.py` → `evaluate_btc_wind_vane()` |
| 五大算法决策 | `engine.py` → `five_algo_decision()` |
| 趋势一致性核心 | `core/trend_consistency.py` |
| 价值风险评估 | `core/risk_reward.py` |
| 信号融合 | `core/fusion.py` |
| 信号池 | `signal_pool/scanner.py` |
| 回测引擎 | `backtest/engine.py` |
| 单元测试 | `tests/test_core.py` |
| 执行层 | `../experiments/ab-trading/screen_executor.py` |

## 9. 技术债务

| 债务项 | 严重程度 | 说明 |
|--------|----------|------|
| 缺少完整API文档 | 中 | 需要补充接口规范文档 |
| 缺少性能测试不足 | 中 | 需要补充压力测试 |
| ML策略实盘验证 | 高 | ML策略尚未实盘验证 |

---

**文档版本**: v1.4  
**最后更新**: 2026-07-16
