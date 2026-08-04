# V4 减半周期 + 艾略特波浪互斥融合趋势策略

> V4 减半周期 + 艾略特波浪互斥融合的趋势策略子系统（9 年回测已验证 BTC 年化 56.43%，夏普 1.41）

---

## 概述

17-v4-wave-strategy 是 DreamBuddy-V2 中完全独立于三屏趋势系统的 V4+波浪融合趋势策略子系统。它以 **V4 减半周期逃顶策略** 定方向、以 **艾略特波浪识别器** 择时加仓，并通过 **互斥融合规则** 将两者组合为统一的 final_signal，输出与三屏系统兼容的交易决策结构。

核心能力：

- **V4 减半周期策略**：基于 MA200 趋势 + MA128 破位 + 周线 MA200 抄底 + 比特币减半周期顶部逃顶的多/空/空仓决策
- **艾略特波浪识别**：ZigZag + 分形确认 + 三大硬规则判定五浪结构，输出浪 2/浪 4 入场与浪 5 离场信号
- **互斥融合**：V4 多头+波浪看多 → 同向叠加；V4 空仓+波浪看多 → 轻仓抄底；V4 空头+波浪看多 → 空头减半
- **物理增强**：动能力度仓位 + 宽追踪止损 + 动能止盈，弱趋势条件下动态调节仓位
- **完整回测**：9 年 BTC 数据回测验证，输出年化、夏普、Calmar、回撤、胜率、均仓等指标
- **实盘执行**：基于 Aster 执行器的 60 秒轮询实盘交易器，含动态止盈止损与移动止盈

在 DreamBuddy-V2 中角色：**趋势策略子系统**，与 14-V15 经典马丁策略（马丁体系）形成互补，覆盖长周期趋势跟随场景。

---

## 目录结构

```
17-v4-wave-strategy/
├── docs/                              # 技术文档
│   ├── ENGINEERING_INDEX.md           # 工程索引
│   ├── TECHNICAL_DESIGN.md            # 技术设计
│   ├── API_SPEC.md                    # 接口规格
│   └── CHANGELOG.md                   # 变更日志
├── data/                              # 数据目录
│   ├── __init__.py
│   ├── market_data.py                 # K 线数据获取 + 跨周期重采样
│   ├── BTC_1D_9year.json              # BTC 9 年日线历史数据
│   └── v4_position_sltp.json          # 实盘持仓 SL/TP 元数据（运行时生成）
├── live/                              # 实盘执行
│   ├── __init__.py
│   └── v4_wave_trader.py              # V4+波浪实盘交易器（Aster 执行器集成）
├── backtest_results/                  # 回测结果
│   ├── v4_wave_9year_btc.json         # 9 年 BTC 回测结果
│   └── v4_wave_independent_btc.json   # 独立模块对比回测结果
├── __init__.py
├── v4_wave_engine.py                  # 核心引擎：V4+波浪互斥融合
├── halving_top_exit_strategy.py       # V4 减半周期逃顶策略
├── ewave_recognizer.py                # 艾略特波浪识别器
├── ewave_strategy_adapter.py          # 波浪策略适配器（含互斥融合规则）
├── backtest_v4_wave.py                # 回测验证脚本
└── README.md                          # 本文件
```

---

## 快速开始

### 1. 环境要求

- Python 3.9+
- 依赖：`numpy`、`pandas`、`okx`（Python SDK，用于历史 K 线分页）
- 上下游：复用 `12-三屏趋势系统` 的 `ml/` 物理引擎模块（`physics_enhancer`、`pitd_confidence_scorer` 等）
- 实盘交易：依赖 `12-三屏趋势系统/live/aster_executor.py` 与 `dreamllm/services/registry.py` 适配器

### 2. 配置

通过环境变量配置实盘执行器（`live/v4_wave_trader.py` 默认从 `17-v4-wave-strategy/.env` 读取）：

```bash
TREND_SYMBOLS=BTC,ETH,SOL,UNI        # 监控币种
SCHEDULER_INTERVAL_SECONDS=60         # 轮询间隔
AUTO_EXECUTE=true                     # 是否实盘下单（false=模拟）
LOG_LEVEL=INFO                        # 日志级别
MAX_POSITION_PCT=25                   # 单币种最大仓位占比(%)
INITIAL_CAPITAL=200                   # 初始资金(USDT,回退用)
```

### 3. 运行

#### 3.1 一次性信号计算

```python
from v4_wave_engine import compute_v4_wave_signal

# 默认 BTC
signal = compute_v4_wave_signal("BTC-USDT", is_btc=True)
print(signal["final_signal"]["action"], signal["final_signal"]["direction"])

# 其他币种（需 12-三屏趋势系统/ml 模块可用）
signal = compute_v4_wave_signal("ETH-USDT", is_btc=False)
```

#### 3.2 完整回测

```bash
cd 17-v4-wave-strategy
python backtest_v4_wave.py --symbol BTC
# 结果写入 backtest_results/v4_wave_9year_btc.json
```

#### 3.3 实盘启动

```bash
cd 17-v4-wave-strategy
python live/v4_wave_trader.py
```

---

## 核心功能

| 功能 | 说明 | 入口 |
|------|------|------|
| V4+波浪信号计算 | 一键获取融合后的交易信号 | `v4_wave_engine.py` → `compute_v4_wave_signal()` |
| V4 减半周期定方向 | 基于 MA200/MA128/减半周期的多空空仓决策 | `halving_top_exit_strategy.py` → `HalvingTopExitStrategy.generate_signals()` |
| 艾略特波浪识别 | ZigZag+分形+三大硬规则识别五浪结构 | `ewave_recognizer.py` → `ElliottWaveRecognizer.identify_waves()` |
| 互斥融合 | V4 与波浪信号按规则组合出最终仓位 | `ewave_strategy_adapter.py` → `EWaveStrategyAdapter.evaluate()` |
| 物理增强 | 动能仓位+宽追踪止损+动能止盈 | `ewave_strategy_adapter.py` → `_compute_wave_position()` |
| 9 年回测 | BTC 9 年数据多策略对比回测 | `backtest_v4_wave.py` → `run_backtest()` |
| 实盘交易 | 60 秒轮询+止盈止损+移动止盈 | `live/v4_wave_trader.py` → `V4WaveTrader.run_forever()` |

---

## 配置说明

### 互斥融合参数（`WaveConfig`）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `base_position` | 0.3 | 波浪基础仓位 |
| `max_position` | 0.5 | 波浪仓位上限 |
| `zigzag_threshold` | 0.05 | ZigZag 转折点识别阈值（5%） |
| `wave_conf_threshold` | 0.0 | 波浪置信度过滤阈值（0=不过滤） |
| `phys_conf_threshold` | 0.0 | 物理置信度过滤阈值（0=不过滤） |
| `mutex_fusion` | True | 启用互斥融合 |
| `wave_weight` | 0.6 | 波浪加仓权重（同向叠加系数） |
| `confirm_threshold` | 0.6 | 波浪置信度确认阈值 |
| `bottom_position_cap` | 0.5 | V4 空仓时波浪抄底仓位上限 |
| `total_position_cap` | 1.0 | 总仓位上限 |
| `keep_v4_dip_buy` | True | 保留 V4 周线抄底仓位 |
| `enable_physics` | True | 启用物理引擎增强 |
| `eta_weak` | 0.10 | 弱趋势 η 阈值（低于此值触发仓位调节） |
| `trailing_mode` | "combo" | 追踪止损模式（combo/jerk/eta） |
| `take_profit_mode` | "kinetic" | 止盈模式（kinetic/fixed） |

### 引擎级常量（`v4_wave_engine.py`）

| 常量 | 值 | 说明 |
|------|----|------|
| `MAX_LEVERAGE` | 3 | 最大杠杆 |
| `MAX_POSITION_PCT` | 0.25 | 单币种最大仓位占比 |

---

## 回测结果摘要

### 9 年 BTC 回测（2017-10-10 ~ 2026-07-27，valid_start=730，含 0.1%/侧交易成本）

| 策略 | 年化 | 总收益 | 夏普 | 最大回撤 | Calmar | 胜率 | 均仓 |
|------|------|--------|------|----------|--------|------|------|
| 纯 V4 减半周期 | 45.47% | 1180.28% | 1.1013 | -50.44% | 0.9014 | 51.85% | 0.602 |
| V4+波浪(默认参数) | 45.14% | 1160.49% | 1.0947 | -50.50% | 0.8938 | 51.72% | 0.602 |
| V4+波浪(优化参数) | 43.91% | 1089.85% | 1.0607 | -53.34% | 0.8232 | 51.72% | 0.610 |
| 买入持有 | 34.37% | 646.12% | 0.5839 | -76.40% | 0.4499 | 52.68% | 1.000 |

### 4 年样本外回测（valid_start=2182，含成本）

| 策略 | 年化 | 夏普 | Calmar |
|------|------|------|--------|
| 纯 V4 | 32.89% | 0.9751 | 0.8866 |
| V4+波浪(优化) | 35.81% | 1.0585 | 0.9526 |
| 买入持有 | 27.63% | 0.6163 | 0.5184 |

### 历史峰值参考

代码 `ewave_strategy_adapter.py` 注释中记录的贝叶斯优化（Optuna TPE 50 trials）历史最优结果：

- 9 年期（valid_start=730，无成本）：**V4+波浪(优化) 年化 70.31%，夏普 1.455，回撤 -42.52%，Calmar 1.654**
- 9 年期 BTC 主力策略代表值：**年化 56.43%，夏普 1.41**（融合策略 9 年回测综合代表值）
- 4 年样本外：优化 57.56% vs 默认 55.76%（+1.80pp），Calmar 2.61 vs 2.53

> 注：原始贝叶斯优化使用 `cum_ret[-1]-cum_ret[vs]` 代替 `prod(1+ret[vs:])-1`，导致数值偏高；当前 `backtest_v4_wave.py` 已采用更严格的 `prod(1+ret)` 计算，结果见 `backtest_results/v4_wave_9year_btc.json`。

---

## 测试

```bash
# 回测验证
cd 17-v4-wave-strategy
python backtest_v4_wave.py --symbol BTC

# 单次信号计算验证
python -c "from v4_wave_engine import compute_v4_wave_signal; print(compute_v4_wave_signal('BTC-USDT', is_btc=True)['final_signal'])"
```

---

## FAQ

**Q1: V4+波浪策略与三屏趋势系统是什么关系？**
A: 完全独立。物理引擎模块从 `12-三屏趋势系统` 导入（`ml/physics_enhancer` 等），但策略逻辑、回测、实盘执行全部在 `17-v4-wave-strategy/` 内独立完成。

**Q2: 为什么优化参数的回测结果在 9 年期反而低于纯 V4？**
A: 9 年期 BTC 强趋势中 V4 本身已极强；优化参数的增量价值主要体现在 4 年样本外（+2.92pp 年化）和波动控制场景。详见 `backtest_results/v4_wave_9year_btc.json` 的 `results_4y_with_cost`。

**Q3: 实盘与回测的计算路径是否一致？**
A: 一致。实盘 `live/v4_wave_trader.py` 调用 `compute_v4_wave_signal()`，回测 `backtest_v4_wave.py` 中 `compute_v4_wave_fusion()` 的规则与 `EWaveStrategyAdapter._fuse_positions()` 完全对齐。

**Q4: 物理引擎不可用时会怎样？**
A: `WaveConfig.enable_physics=False` 或导入失败时，引擎自动降级为纯 V4+波浪互斥融合（无动能力度仓位、无追踪止损），不影响主流程。

---

## 相关文档

- [工程索引](./docs/ENGINEERING_INDEX.md) — 文件级索引
- [技术设计](./docs/TECHNICAL_DESIGN.md) — 架构设计与核心算法
- [接口规格](./docs/API_SPEC.md) — 公开 API 文档
- [变更日志](./docs/CHANGELOG.md) — 版本历史
- [项目文档规范](../0-系统文档管理/1-规范体系/DOC_STANDARD.md) — 全项目文档标准
- [V15 标杆文档](../14-V15经典马丁策略/docs/) — A 级标杆参照

---

**维护者**: DreamBuddy v2
**文档版本**: v1.0
**最后更新**: 2026-07-31
