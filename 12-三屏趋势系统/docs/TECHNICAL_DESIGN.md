# 技术设计文档 — 三屏趋势系统

> **版本**: v1.0 | **更新日期**: 2026-07-12
> **定位**: 模块级技术设计文档，描述架构、数据流、算法细节

---

## 目录

- [1. 系统架构](#1-系统架构)
- [2. 数据流](#2-数据流)
- [3. 核心算法](#3-核心算法)
- [4. 接口设计](#4-接口设计)
- [5. 配置管理](#5-配置管理)
- [6. 测试体系](#6-测试体系)
- [7. 扩展计划](#7-扩展计划)

---

## 1. 系统架构

### 1.1 模块定位

**模块名称**: 12-三屏趋势系统
**英文代号**: screen-trend
**核心职责**: 周线+日线+4H三重滤网趋势分析，为交易策略提供趋势过滤信号
**设计模式**: 策略模式 + 观察者模式

### 1.2 三层架构

```
┌─────────────────────────────────────────────────────────────┐
│                    入口层 (engine.py)                        │
│   ScreenEngine.run_trend_analysis()                         │
└──────────────────────────────┬──────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                   核心层 (core/)                             │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐       │
│  │ indicators   │  │ trend_       │  │ fusion       │       │
│  │ 技术指标计算 │  │ consistency  │  │ 多周期融合   │       │
│  │              │  │ 趋势一致性   │  │              │       │
│  └──────┬───────┘  └──────┬───────┘  └──────┬───────┘       │
│         │                 │                 │                │
│         └────────┬────────┴────────┬────────┘                │
│                  │                 │                         │
│         ┌────────▼────────┐  ┌─────▼─────┐                  │
│         │dynamic_weights  │  │  config   │                  │
│         │ 动态权重调整    │  │ 配置管理  │                  │
│         └─────────────────┘  └───────────┘                  │
└──────────────────────────────────────────────────────────────┘
                               │
┌──────────────────────────────┴──────────────────────────────┐
│                   数据层 (data/)                             │
│  ┌──────────────┐  ┌──────────────┐                         │
│  │market_data   │  │fundamental_  │                         │
│  │市场数据获取  │  │data          │                         │
│  │              │  │基本面数据    │                         │
│  └──────────────┘  └──────────────┘                         │
└──────────────────────────────────────────────────────────────┘
```

### 1.3 目录结构

```
12-三屏趋势系统/
├── core/                    # 核心模块
│   ├── __init__.py
│   ├── config.py            # 配置管理
│   ├── dynamic_weights.py   # 动态权重调整
│   ├── fusion.py            # 多时间周期融合
│   ├── indicators.py        # 技术指标计算
│   └── trend_consistency.py # 趋势一致性判断
├── data/                    # 数据模块
│   ├── __init__.py
│   ├── fundamental_data.py  # 基本面数据
│   └── market_data.py       # 市场数据获取
├── tests/                   # 测试模块
│   ├── __init__.py
│   └── test_core.py         # 核心测试
├── docs/                    # 技术文档
│   ├── TECHNICAL_DESIGN.md  # 技术设计文档（本文件）
│   ├── ENGINEERING_INDEX.md # 工程索引
│   └── API_SPEC.md          # API规格
├── classic_bridge.py        # 经典指标系统桥接
├── exit_integration.py      # 离场系统集成
├── signals.py               # 信号输出
├── engine.py                # 引擎入口
├── ENGINEERING_INDEX.md
└── README.md
```

---

## 2. 数据流

### 2.1 趋势分析流程

```
run_trend_analysis(symbol):
  │
  ├─→ fetch_market_data(symbol)  ← 获取多周期K线
  │     ├─ 周线K线 (weekly)
  │     ├─ 日线K线 (daily)
  │     └─ 4H K线 (4h)
  │
  ├─→ calc_indicators(klines)    ← 计算技术指标
  │     ├─ MA104 (约5个月均线)
  │     ├─ MA200
  │     ├─ EMA200
  │     └─ 趋势强度指标
  │
  ├─→ check_trend_consistency()  ← 趋势一致性判断
  │     ├─ 周线趋势方向
  │     ├─ 日线趋势方向
  │     └─ 4H趋势方向
  │
  ├─→ fuse_signals()             ← 多周期信号融合
  │     └─ 动态权重分配
  │
  └─→ generate_trend_signal()    ← 生成趋势信号
        └─ 返回: {trend_direction, strength, confidence, mode}
```

### 2.2 信号输出

```python
{
    "symbol": "BTC-USDT",
    "trend_direction": "BULLISH" | "BEARISH" | "SIDEWAYS",
    "strength": 0-100,
    "confidence": 0-100,
    "mode": "both_bear" | "both_bull" | "mixed",
    "weekly_trend": "BULLISH" | "BEARISH",
    "daily_trend": "BULLISH" | "BEARISH",
    "four_hour_trend": "BULLISH" | "BEARISH",
    "weekly_ma104": 60000.0,
    "daily_ma104": 62000.0,
    "timestamp": "2026-07-12T10:30:00Z"
}
```

---

## 3. 核心算法

### 3.1 趋势一致性判断

```python
def check_trend_consistency(weekly_klines, daily_klines, four_hour_klines):
    # 计算各周期MA104
    weekly_ma104 = calc_sma(weekly_closes, 104)
    daily_ma104 = calc_sma(daily_closes, 104)
    four_hour_ma104 = calc_sma(four_hour_closes, 104)
    
    # 判断趋势方向
    weekly_bull = current_price > weekly_ma104
    daily_bull = current_price > daily_ma104
    four_hour_bull = current_price > four_hour_ma104
    
    # 趋势一致性模式
    if weekly_bull and daily_bull:
        return {"mode": "both_bull", "trend_direction": "BULLISH"}
    elif not weekly_bull and not daily_bull:
        return {"mode": "both_bear", "trend_direction": "BEARISH"}
    else:
        return {"mode": "mixed", "trend_direction": "SIDEWAYS"}
```

### 3.2 动态权重调整

```python
def calculate_dynamic_weights(mode):
    """
    根据趋势一致性模式调整各周期权重
    
    - both_bear: 周线权重最高，严格过滤
    - both_bull: 日线权重最高，确认趋势
    - mixed: 均衡权重
    """
    if mode == "both_bear":
        return {"weekly": 0.5, "daily": 0.35, "four_hour": 0.15}
    elif mode == "both_bull":
        return {"weekly": 0.3, "daily": 0.45, "four_hour": 0.25}
    else:
        return {"weekly": 0.33, "daily": 0.34, "four_hour": 0.33}
```

### 3.3 多周期信号融合

```python
def fuse_signals(weekly_signal, daily_signal, four_hour_signal, weights):
    """
    加权融合多周期信号
    
    参数:
        weekly_signal: 周线信号 (-1: 空, 0: 震荡, 1: 多)
        daily_signal: 日线信号
        four_hour_signal: 4H信号
        weights: 权重字典
    
    返回:
        综合趋势方向和强度
    """
    weighted_sum = (
        weekly_signal * weights["weekly"] +
        daily_signal * weights["daily"] +
        four_hour_signal * weights["four_hour"]
    )
    
    if weighted_sum > 0.3:
        return {"direction": "BULLISH", "strength": weighted_sum * 100}
    elif weighted_sum < -0.3:
        return {"direction": "BEARISH", "strength": abs(weighted_sum) * 100}
    else:
        return {"direction": "SIDEWAYS", "strength": 50}
```

---

## 4. 接口设计

### 4.1 核心类

#### ScreenEngine

```python
class ScreenEngine:
    def __init__(self, config=None):
        """初始化趋势引擎"""
    
    def run_trend_analysis(self, symbol):
        """
        运行趋势分析
        
        参数:
            symbol: 币种代码
        
        返回:
            dict: 趋势信号
        """
    
    def get_trend_status(self, symbol):
        """获取趋势状态缓存"""
    
    def check_trend_filter(self, symbol):
        """
        检查趋势过滤（both_bear模式）
        
        返回:
            dict: {blocked: bool, mode: str, ...}
        """
    
    def update_config(self, config):
        """更新配置"""
```

### 4.2 桥接接口

#### classic_bridge.py

```python
def get_classic_system_exit(symbol, position_state):
    """
    调用经典指标系统的离场评估
    
    参数:
        symbol: 币种代码
        position_state: 持仓状态
    
    返回:
        ExitDecision: 离场决策
    """
```

#### exit_integration.py

```python
def evaluate_exit(symbol, position_state, regime="trend"):
    """
    综合离场评估
    
    参数:
        symbol: 币种代码
        position_state: 持仓状态
        regime: 市场状态 (trend/range)
    
    返回:
        ExitDecision: 离场决策
    """
```

---

## 5. 配置管理

### 5.1 配置结构

```python
{
    "indicators": {
        "ma_periods": [104, 200],
        "ema_periods": [200],
        "atr_period": 14
    },
    "trend_filter": {
        "mode": "both_bear",
        "strictness": "high"
    },
    "weights": {
        "weekly": 0.5,
        "daily": 0.35,
        "four_hour": 0.15
    },
    "data": {
        "max_candles": 250,
        "update_interval": 3600
    },
    "logging": {
        "level": "INFO",
        "file_path": "~/.workbuddy/logs/screen_trend.log"
    }
}
```

### 5.2 配置加载

```python
# 配置加载顺序
# 1. core/config.py 默认值
# 2. 环境变量覆盖
# 3. 运行时传入配置
```

---

## 6. 测试体系

### 6.1 测试文件

| 文件 | 测试类 | 测试用例 | 覆盖范围 |
|------|--------|----------|----------|
| tests/test_core.py | TestIndicators | ~5 | 指标计算 |
| tests/test_core.py | TestTrendConsistency | ~3 | 趋势一致性 |
| tests/test_core.py | TestFusion | ~2 | 信号融合 |

### 6.2 测试命令

```bash
cd 12-三屏趋势系统 && python -m pytest tests/ -v
```

---

## 7. 扩展计划

### Phase 1: 核心框架 ✅
- [x] 三层趋势分析引擎
- [x] 趋势一致性判断
- [x] 动态权重调整
- [x] 基础测试

### Phase 2: 深化与扩展
- [ ] 接入通用风控模块
- [ ] RAISE_TP离场动作支持
- [ ] 基本面数据集成
- [ ] 增强测试覆盖

### Phase 3: 系统对接
- [ ] V15马丁策略对接
- [ ] 经典指标系统对接
- [ ] 易经推理系统对接