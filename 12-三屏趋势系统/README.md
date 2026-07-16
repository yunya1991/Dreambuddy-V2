# 12-三屏趋势系统

> **趋势一致性确定方向，置信度评估确定仓位。**

三屏趋势系统是一个趋势判定 + 置信度评估 + 仓位计算系统，通过周线和日线技术指标的一致性检测，结合 A系列研报基本面数据，输出最终趋势方向、置信度和仓位建议。

## 快速开始

```bash
# 运行测试
cd 12-三屏趋势系统
python3 tests/test_core.py
```

```python
# 完整信号计算（含数据获取）
from engine import compute_full_trading_signal
result = compute_full_trading_signal(spot_inst="BTC-USDT")

# 纯计算入口（数据由调用方提供）
from engine import compute_trend_signal_from_dataframes
result = compute_trend_signal_from_dataframes(
    weekly_df=weekly_df,
    daily_df=daily_df,
    symbol="BTC",
    fundamental_data={"direction": "BULL", "confidence": 65},
)

# 集成推理（LightGBM + LLM 辩证推理）
from ml.algo_ensemble import predict_ensemble
from ml.llm_reasoning import reason_if_needed
ensemble_pred = predict_ensemble(result)           # LightGBM 集成预测
final = reason_if_needed(result, ensemble_pred)    # LLM 辩证推理（按需触发）
```

## 文件索引

| 文件 | 职责 | 核心函数 |
|------|------|---------|
| [engine.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/engine.py) | 主引擎，算法编排 + 公开接口 | `compute_full_trading_signal()`, `compute_trend_signal_from_dataframes()` |
| [signals.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/signals.py) | Freqtrade信号服务 | `fetch_freqtrade_signals()`, `align_freqtrade_with_trend()` |
| [exit_integration.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/exit_integration.py) | 离场决策集成 | `evaluate_exit()` |
| [classic_bridge.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/classic_bridge.py) | 经典系统HTTP桥接 | `_make_request()` |
| [core/config.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/config.py) | 配置常量 | `SCREEN1_INDICATORS`, `POSITION_TIERS` |
| [core/indicators.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/indicators.py) | 指标计算 | `calc_indicator_dynamics()`, `calc_trend_direction_static()` |
| [core/trend_consistency.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/trend_consistency.py) | 趋势一致性检测 | `calc_trend_consistency()`, `calc_trend_direction_dynamic()` |
| [core/dynamic_weights.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/dynamic_weights.py) | 动态权重 + 贝叶斯置信度 | `calc_dynamic_weights()`, `calc_bayesian_confidence()` |
| [core/fusion.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/core/fusion.py) | 技术面+基本面撮合 | `fuse_technical_fundamental()` |
| [ml/algo_ensemble.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/algo_ensemble.py) | **LightGBM 集成推理**（五大算法权重学习） | `predict_ensemble()`, `train_ensemble()`, `collect_sample()` |
| [ml/llm_reasoning.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/llm_reasoning.py) | **LLM 辩证推理**（矛盾信号分析） | `reason_if_needed()`, `should_trigger_llm()` |
| [ml/label_samples.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/label_samples.py) | **样本标注 + 训练工具** | `label_collected_samples()`, `train_from_collected()` |
| [ml/models.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/models.py) | 价格特征ML模型 | `LightGBMModel`, `XGBoostModel` |
| [ml/feature_engineer.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ml/feature_engineer.py) | 价格特征工程 | `TrendFeatureEngineer` |
| [data/market_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/market_data.py) | K线数据获取 | `fetch_candles()`, `resample_candles()` |
| [data/fundamental_data.py](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/data/fundamental_data.py) | 基本面数据获取 | `fetch_fundamental_data()`, `fetch_fundamental_by_timeframe()` |

## 系统边界

| 职责 | 归属 |
|------|------|
| 趋势方向判定 / 置信度评估 / 仓位计算 | **本模块** |
| 入场信号 (Freqtrade 多策略) | **10-经典指标系统** |
| 离场决策 (ClassicExitSystem) | **10-经典指标系统** |
| 基本面数据 (周报 + A1日报) | **A系列研报** |

## 核心数据流

```
技术指标(周线+日线) ──→ 趋势一致性 + 贝叶斯置信度 ──┐
                                                      ├──→ 技术面+基本面撮合 ──→ Freqtrade校准 ──→ 五大算法 final_signal
A系列研报(周报+日报) ──→ 基本面方向 + 置信度 ─────────┘
                                                                    │
                                                                    ▼
                                              ┌─────────────────────────────────┐
                                              │     集成推理层 (新增)             │
                                              │  ┌───────────────────────────┐  │
                                              │  │ LightGBM 集成推理        │  │
                                              │  │ 46维特征 → 权重自适应     │  │
                                              │  │ 模型未训练→fallback       │  │
                                              │  └───────────┬───────────────┘  │
                                              │              │                  │
                                              │  ┌───────────▼───────────────┐  │
                                              │  │ LLM 辩证推理 (按需触发)    │  │
                                              │  │ 低置信/矛盾→DeepSeek       │  │
                                              │  │ 高置信无矛盾→直接用集成    │  │
                                              │  └───────────┬───────────────┘  │
                                              └──────────────┼──────────────────┘
                                                             │
                                                             ▼
                                                    最终决策(方向+置信度+推理依据)
```

## 文档索引

| 文档 | 说明 |
|------|------|
| [ENGINEERING_INDEX.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/ENGINEERING_INDEX.md) | **完整工程索引**（目录结构、API清单、配置参数、依赖关系、外部接口） |
| [docs/trend-screen-system-design.md](file:///Users/zhangjiangtao/WorkBuddy/dreambuddy-v2/12-三屏趋势系统/docs/trend-screen-system-design.md) | 技术设计文档（五大算法、数据流、核心原理） |
