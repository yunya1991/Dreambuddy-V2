# 事件驱动策略系统 — 工程索引

> **版本**：v1.0 | **更新日期**：2026-10-04
> **模块定位**：独立子交易系统（与 BCRM2.0、BDSM 平级）

## 1. 模块概览

事件驱动策略子交易系统，专注离散单点宏观事件（FOMC/非农/CPI/PPI）的冲击响应。

## 2. 核心文件

| 文件 | 职责 | 行数 |
|------|------|------|
| `event_driven/event_driven_strategy.py` | EventDrivenStrategy + EventDrivenTrader + EventSignal + compute_impulse | ~1250 |
| `event_driven/conviction_scorer.py` | ConvictionScorer 6 因子置信度评分 | ~300 |
| `event_driven/event_dominance_controller.py` | EventDominanceController 主导控制 + 降档安全 | ~400 |
| `event_driven/event_case_library.py` | EventCaseLibrary FOMC 案例库 + 自学习 | ~350 |

## 3. 公开 API

### 3.1 策略核心

| 类/函数 | 说明 |
|---------|------|
| `EventDrivenStrategy` | 5 维评分策略引擎 |
| `EventDrivenTrader` | 独立子交易系统执行器 |
| `EventSignal` | 事件信号契约（frozen dataclass） |
| `compute_impulse(event_type, days_since, strength)` | 单点脉冲指数衰减函数 |
| `neutral_event_signal()` | 中性信号工厂 |

### 3.2 置信度

| 类 | 说明 |
|----|------|
| `ConvictionScorer` | 6 因子加权置信度评分 |
| `ConvictionResult` | 评分结果（含 filter_level / position_params） |

### 3.3 主导控制

| 类 | 说明 |
|----|------|
| `EventDominanceController` | 宏观事件主导控制器（双层门控 + 降档） |
| `DominanceDecision` | 主导控制决策 |

### 3.4 案例库

| 类 | 说明 |
|----|------|
| `EventCaseLibrary` | FOMC 事件案例库（检索 + 统计 + 学习） |
| `EventCase` | 单个事件案例 |

## 4. 关键常量

| 常量 | 说明 |
|------|------|
| `PHASE_THRESHOLDS` | 阶段动态信号阈值（pre/event/repricing） |
| `EVENT_HALF_LIFE` | 事件半衰期 τ（fomc=3.0, cpi=2.0, nfp=1.5, ppi=1.0 天） |
| `PHASE_POSITION_MULT` | 阶段仓位乘数 |
| `ELASTICITY_TREND_FOLLOW/MEAN_REVERT/NONE` | 弹性系数常量 |

## 5. 测试

| 测试文件 | 覆盖 |
|----------|------|
| `tests/test_event_driven_strategy.py` | EventDrivenStrategy 5 维评分 |
| `tests/test_event_signal_contract.py` | EventSignal 契约 + EventDrivenTrader |
| `tests/test_phase3_event_driven_upgrade.py` | Phase 3 升级（脉冲/阈值/5维修订） |
| `tests/test_event_case_library.py` | EventCaseLibrary |
| `tests/test_event_dominance_controller.py` | EventDominanceController |

**测试结果**：114 passed（2026-10-04 迁移后验证）

## 6. 依赖关系

### 内部依赖
- 4 个核心文件均为纯标准库依赖，无相互 import

### 外部消费者
- `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/kline_event_handler.py` — 路径发现层注入事件路径
- `23-四层闭环自进化交易架构/dreambuddy_evolution/scripts/backtest_macro_event.py` — 回测脚本

### 兼容层
- `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/` 下保留 4 个 re-export shim，向后兼容

## 7. 迁移记录

2026-10-04：从 `23-四层闭环自进化交易架构/dreambuddy_evolution/engines/` 迁出至本目录，成为独立子交易系统。
