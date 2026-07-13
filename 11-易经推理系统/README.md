# 易经推理系统（I Ching Reasoning System）

## 版本：2.0.0 | 2026-07-13

**将易经哲学与现代量化交易深度融合的智能决策系统。**

---

## 系统架构

```
用户交互层 (User Interface)
├── 飞书机器人 / CLI / 前端
└── 任务队列调度

编排层 (Orchestration)
├── A0-A9 决策链 (A0->A1->A2->...->A9)
│   ├── A0: 矛盾分析（坤卦）
│   ├── A1: 深度调研（坎卦）
│   ├── A2: 第一性原理（艮卦）
│   ├── A3: 沙盘推演（巽卦）
│   ├── A4: 战术验证（震卦）
│   ├── A5: 决策执行（离卦）
│   ├── A6: 情报监控（兑卦）
│   ├── A7: 审计门禁（乾卦）
│   ├── A8: 理论实践验证（复卦/渐卦）
│   └── A9: 离场决策（恒卦/归妹卦）
└── 状态机 + 执行循环

决策层 (Decision Engine) - BCRM 2.0
├── 八卦力学引擎 (Bagua Mechanics)
│   ├── 乾(趋势强度) 坤(支撑阻力) 震(动量突破)
│   ├── 巽(波动率) 坎(成交量) 离(蜡烛形态)
│   ├── 艮(市场结构) 兑(多周期共振)
│   └── 多币种L1模型 + 辩证L3裁决
├── 市态切换引擎 (Market Regime Switching)
│   ├── 8种市态分类
│   ├── 自适应参数调整
│   └── 仓位管理 (Position Management)
└── 组合策略 (Portfolio Strategy)
    ├── 资金分配权重
    └── 组合层风险指标

支撑层 (Infrastructure)
├── 特征工程 (Feature Engineering)
│   ├── 经典经验特征 (Classic Experience)
│   ├── 斐波那契扩展/回撤 (Fibonacci)
│   ├── 枢纽点 (Pivot Points)
│   ├── WDH时间维度 (WDH Features)
│   ├── 库存周期特征 (Inventory Cycle)
│   ├── 市值等级特征 (Market Cap)
│   ├── 跨资产特征 (Cross Asset)
│   ├── 美林时钟 (Merrill Lynch Clock)
│   └── Meta-Labeling V2
├── 数据服务 (Data Service)
│   ├── K线数据 (OKX/Binance)
│   └── 实时行情推送
├── 回测引擎 (Backtest Engine)
│   ├── Walk-Forward验证
│   └── 组合回测
└── 增量学习 (Incremental Learning)
    ├── 交易数据自动记录
    ├── 模型版本管理
    └── 再训练触发
```

---

## 基线配置 v2.0.0

### 配置说明

**完整基线配置**：市态切换（含仓位管理）+ auto_mcap + 特征选择 + 组合回测

配置文件：[configs/baseline_config.json](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/11-易经推理系统/configs/baseline_config.json)

### 核心模块

| 模块 | 状态 | 功能说明 |
|------|------|----------|
| **市态切换** | 启用 | 8种市态分类（趋势上/震荡/盘整/突破/FOMO/暴跌/反转），自适应调整止盈止损和置信度阈值 |
| **仓位管理** | 启用 | 通过 `position_factor` 调整置信度阈值：FOMO=1.5(降低阈值)，盘整=0.5(提高阈值) |
| **auto_mcap** | 启用 | 按市值等级自动配置特征开关：大市值(BTC/ETH)→启用库存周期；小市值(UNI)→禁用库存周期 |
| **特征选择** | 启用 | LightGBM重要性过滤(阈值0.05) + 相关性去冗余(阈值0.85)，每折独立选择 |
| **组合回测** | 启用 | 多币种资金分配：大市值40% / 中市值35% / 小市值25% |

### 回测参数

| 参数 | 值 | 说明 |
|------|-----|------|
| K线周期 | 1H | 1小时K线 |
| 数据量 | 6000根 | 约8个月数据 |
| 时间范围 | 2025-11 ~ 2026-07 | 覆盖牛熊转换 |
| Walk-Forward折数 | 5折 | 80%训练/20%验证 |
| 置信度阈值 | 0.40 | 基础阈值 |
| 止盈(TP) | 3.0x ATR | 基于波动率动态止盈 |
| 止损(SL) | 2.0x ATR | 基于波动率动态止损 |
| 最大持仓 | 60根K线 | 约2.5天 |
| 手续费 | 0.05% | OKX实际费率 |
| 滑点 | 0.1% | 模拟实际交易滑点 |

### 回测结果（6000根K线）

#### 单币种表现

| 币种 | 市值等级 | 特征数 | 交易数 | 胜率 | 总收益 | 最大回撤 | 盈亏比 | 夏普 |
|------|----------|--------|--------|------|--------|----------|--------|------|
| **BTC** | 大市值 | 429 | 43 | **81.4%** | **68.52%** | 4.58% | 5.14 | **10.67** |
| **ETH** | 大市值 | 463 | 52 | **71.2%** | **53.79%** | 14.30% | 2.37 | **5.77** |
| **SOL** | 中市值 | 463 | 65 | **75.4%** | **92.92%** | 11.20% | 3.02 | **7.88** |
| **UNI** | 小市值 | 402 | 92 | **60.9%** | **119.48%** | 33.45% | 2.12 | **5.62** |

#### 组合层指标

| 指标 | 数值 |
|------|------|
| 组合总收益 | **86.85%** |
| 组合胜率 | **70.2%** |
| 组合盈亏比 | **2.61** |
| **组合夏普** | **6.61** |
| 组合最大回撤 | **12.75%** |
| 组合总交易数 | **252** |
| **综合夏普（加权）** | **7.45** |

#### 特征配置（按市值等级）

| 特征模块 | BTC(大) | ETH(大) | SOL(中) | UNI(小) |
|----------|---------|---------|---------|---------|
| 八卦特征 | 启用 | 启用 | 启用 | 启用 |
| 经典经验 | 启用 | 启用 | 启用 | 启用 |
| 斐波那契 | 启用 | 启用 | 启用 | 启用 |
| 枢纽点 | 启用 | 启用 | 启用 | 启用 |
| WDH三屏 | 启用 | 启用 | 启用 | 启用 |
| 库存周期 | 启用 | 启用 | 启用 | **禁用** |
| 跨资产 | 启用 | 启用 | 启用 | 启用 |
| 市值特征 | 启用 | 启用 | 启用 | 启用 |
| 美林时钟 | 禁用 | 禁用 | 禁用 | 禁用 |
| Meta-Labeling | 禁用 | 禁用 | 禁用 | 禁用 |

### 执行命令

```bash
cd scripts
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC,ETH,SOL,UNI \
  --timeframe 1H \
  --n-folds 5 \
  --max-bars 6000 \
  --feature-selection \
  --portfolio
```

---

## 核心算法

### 八卦特征引擎

将易经八卦映射为8个市场特征维度，每个卦象对应一组技术指标：

| 卦象 | 特征维度 | 核心指标 |
|------|----------|----------|
| 乾 ☰ | 趋势强度 | MA/EMA/MACD/ADX/均线排列 |
| 坤 ☷ | 支撑阻力 | 布林带/近期高低点/Keltner/VWAP |
| 震 ☳ | 动量突破 | RSI/Stochastic/CCI/ROC/MFI/突破标记 |
| 巽 ☴ | 波动率 | 历史波动率/ATR/波动率锥/BB压缩 |
| 坎 ☵ | 成交量 | 量价比/量价背离/OBV/放量缩量 |
| 离 ☲ | 蜡烛形态 | 阴阳线/十字星/锤子/吞没/跳空 |
| 艮 ☶ | 市场结构 | 趋势vs震荡/Hurst指数/自相关/局部极值 |
| 兑 ☱ | 多周期共振 | 多周期动量一致性/均线排列/RSI共振 |

### 辩证ML引擎

```
L1 主方向模型 (正题) → LightGBM多分类 (UP/DOWN/FLAT)
        ↓
L2 Meta-Labeling (反题) → 对L1信号做"是否盈利"二次判断
        ↓
L3 辩证裁决 (合题) → L1置信度 × L2盈利概率 = 最终置信度
```

卦象映射器：将ML输出映射为易经64卦解释，包含六爻/互卦/变卦。

### 市态切换

8种市场状态自适应参数：

| 市态 | 方向过滤 | 置信度调整 | 止盈止损 | 持仓周期 | 仓位因子 |
|------|----------|------------|----------|----------|----------|
| 强趋势上涨 | 仅多 | -0.08 | 4x/1.5x | 80 | 1.2 |
| 温和趋势上涨 | 仅多 | -0.04 | 3x/1.8x | 70 | 1.0 |
| 震荡区间 | 多空 | +0.05 | 2x/2x | 30 | 0.8 |
| 横盘整理 | 多空 | +0.10 | 2x/2x | 25 | 0.5 |
| 突破 | 多空 | -0.05 | 3.5x/2.5x | 50 | 1.0 |
| FOMO拉盘 | 仅多 | -0.20 | 5x/1.2x | 40 | 1.5 |
| 暴跌 | 仅空 | -0.05 | 2.5x/3x | 40 | 0.8 |
| 反转 | 多空 | +0.05 | 2.5x/2.5x | 35 | 1.0 |

---

## 项目结构

```
11-易经推理系统/
├── configs/                    # 配置文件
│   └── baseline_config.json    # 基线配置 v2.0.0
├── docs/                       # 技术文档
│   ├── README.md               # 本文件
│   ├── TECHNICAL_DESIGN.md     # 技术设计文档
│   ├── architecture.md         # 系统架构图
│   ├── ENGINEERING_INDEX.md    # 工程索引
│   └── superpowers/            # Superpowers集成
├── scripts/                    # 核心代码
│   └── memory_l4/
│       └── bcrm2/              # BCRM 2.0引擎
│           ├── run_phase0_validation.py  # Phase 0回测入口
│           ├── walk_forward_backtester.py # Walk-Forward回测
│           ├── portfolio_backtester.py    # 组合回测
│           ├── bagua_feature_engine.py    # 八卦特征引擎
│           ├── dialectical_ml_engine.py   # 辩证ML引擎
│           ├── market_regime.py           # 市态切换
│           ├── market_cap.py              # 市值等级配置
│           ├── feature_selection.py       # 特征选择
│           ├── wdh_features.py            # WDH时间维度
│           ├── merrill_clock_features.py  # 美林时钟
│           ├── meta_labeling_features_v2.py # Meta-Labeling
│           ├── cross_asset_features.py    # 跨资产特征
│           ├── inventory_cycle_features.py # 库存周期
│           ├── data_fetcher.py            # 数据获取
│           ├── polling_trader.py          # 实盘交易
│           └── incremental_learning.py    # 增量学习
├── data/                       # 数据目录
│   ├── bcrm2_phase0/           # Phase 0回测结果
│   └── training/               # 训练数据
└── models/                     # 模型目录
```

---

## 快速开始

### 环境准备

```bash
pip install pandas numpy lightgbm scikit-learn
```

### 运行回测

```bash
# 单币种回测
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC --timeframe 1H --n-folds 5 --max-bars 6000

# 组合回测（推荐）
python -m memory_l4.bcrm2.run_phase0_validation \
  --symbols BTC,ETH,SOL,UNI --timeframe 1H \
  --n-folds 5 --max-bars 6000 --feature-selection --portfolio
```

### 实盘交易

```bash
python -m memory_l4.bcrm2.polling_trader
```

---

## 技术栈

- **Python 3.9+**
- **LightGBM** (ML模型)
- **Pandas / NumPy** (数据处理)
- **scikit-learn** (特征工程/评估)
- **SQLite** (交易数据存储)
- **OKX API** (行情/交易)

---

## 设计理念

> "易有太极，是生两仪，两仪生四象，四象生八卦。"

将易经的辩证思维（阴阳、八卦、六十四卦）与现代量化交易的特征工程、机器学习深度融合，构建一个既有理论根基又有实战能力的智能交易系统。

---

*Last Updated: 2026-07-13 | BCRM 2.0 Baseline*
