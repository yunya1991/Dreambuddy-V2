# 参数中心（Param Center）— 16-调控系统/scripts/

> **版本**: v2.0 | **更新**: 2026-10-09 | **状态**: active（6 适配器全部激活 + 定时调度 + 跨进程持久化）
> **SPEC**: `param-center-arch-20260707`（三层混合架构 Layer 2）
> **认知记忆**: VM-1791350368266 / VM-1791507639893 / VM-1791508328050 / VM-1791508915835

## 定位

参数中心是 16-调控系统的子模块（位于 `scripts/` 而非 `core/`，因为它是参数基础设施而非离场决策组件）。提供"参数中心化，执行去中心化"能力：

- **聚合**：BMA + KL散度加权 6 个算法输出（归一化距离 + softmax 温度=0.5）
- **验证**：bayes_opt + 回测四条件门禁
- **校准**：影子模式偏差分析 → 校准建议
- **优化**：Ray Tune 大规模并行搜索
- **定时调度**：scheduler.py 每小时自动聚合，JSON 持久化跨进程共享
- **资产差异化**：聚合结果与静态 3D 表按 40:60 混合，适配不同资产类别

## 对外 API（契约）

唯一对外公开入口：

```python
from param_center.api import get_sltp_params

params = get_sltp_params("BTC", market_regime="chop", use_cache=True)
# SLTPParams: sl_floor, tp_floor, atr_mult_range, rr_ratio_target,
#             tp_decay_floor, tp_decay_hours
```

**FAIL-OPEN**：参数中心不可用 → 返回 `_DEFAULT_PARAMS`（SL=4%, TP=12%），不阻塞主流程。

**聚合缓存优先级**：聚合缓存（JSON 持久化）> 静态 3D 表 > FAIL-OPEN 默认值。

## 模块结构

```
param_center/
├── __init__.py              包入口（__all__ 9 个导出 + sys.path 注入）
├── api.py                   对外 API: get_sltp_params
├── repository.py            ParamRepository 3D 参数表 + 聚合缓存 + JSON 持久化
├── aggregator.py            StatAggregator BMA + KL散度(归一化) + softmax(温度=0.5)
├── verifier.py              BayesianVerifier 四条件门禁
├── calibration.py           CalibrationAnalyzer 影子校准
├── ray_optimizer.py         RayTuneOptimizer 大规模并行优化
├── shadow_integration.py    ParamCenterShadowLogger 影子模式
├── scheduler.py             定时调度器（每小时 subprocess 调用 runner.py）
├── runner.py                CLI 聚合入口 + K线数据加载 + 资产混合
├── adapters/                6 个算法适配器（HMM/Bagua/Hurst/PMapper/Shadow/CUSUM）
│   └── base.py              BaseAdapter.observe() FAIL-OPEN
├── data/
│   └── aggregated_params.json  聚合缓存持久化（跨进程共享）
└── tests/                   7 个测试文件 45/45 GREEN
```

## 6 个适配器

| 适配器 | 数据需求 | 数据来源 | 状态 |
|--------|----------|----------|------|
| HMM | `closes` (≥50根) | K线 CSV → BTCRegimeDetector | ✅ 激活 |
| Bagua | `regime_name` | MA斜率+波动率 → 8卦 regime | ✅ 激活 |
| Hurst | `closes` (≥100根) | K线 CSV → compute_hurst_features | ✅ 激活 |
| PMapper | `L/T/C` 标量 | 链上数据（暂无→默认0） | ✅ 激活 |
| CUSUM | `closes` (≥120根) | K线 CSV → StructuralBreakDetector | ✅ 激活 |
| Shadow | DB 查询 | param_center_deviation.db | ⏳ 待积累 |

### 聚合权重（示例：BTC chop regime）

| 适配器 | 权重 | 说明 |
|--------|------|------|
| HMM | 17.8% | 市场状态检测 |
| Bagua | 25.9% | 易经 regime 映射 |
| Hurst | 14.5% | 赫斯特指数 |
| PMapper | 14.5% | 参数映射 |
| CUSUM | 27.3% | 结构突变检测 |

### 资产差异化混合

适配器不区分资产类别，直接用聚合值会导致美股 SL=4.2%（应≈3%）。修复方案：

```
final_sl = static_sl_floor × 0.6 + aggregated_sl × 0.4
final_tp = static_tp_floor × 0.6 + aggregated_tp × 0.4
final_atr = static_atr_mid × 0.6 + aggregated_atr × 0.4
```

| 币种 | 静态 SL | 聚合 SL | 混合 SL | 静态 TP | 混合 TP |
|------|---------|---------|---------|---------|---------|
| BTC | 5.0% | 5.6% | 5.2% | 12.0% | 12.5% |
| NVDA | 3.0% | 4.2% | 3.5% | 12.0% | 13.4% |
| XAU | 3.0% | 4.7% | 3.7% | 12.0% | 12.7% |
| SOL | 5.0% | 4.2% | 4.7% | 15.0% | 15.2% |

## 定时调度

### scheduler.py

每小时自动运行聚合，结果通过 JSON 持久化共享给 polling_trader：

```
scheduler.py (每3600s)
    ↓ subprocess 调用
runner.py --symbol BTC,NVDA,... --regime chop
    ↓ 6 适配器聚合 + 资产混合
ParamRepository.set_aggregated()
    ↓ 持久化
data/aggregated_params.json  ← 跨进程共享
    ↓ polling_trader 启动时/缓存过期时加载
ParamRepository.get() → 聚合缓存优先于静态表
```

### 跨进程缓存

| 机制 | 说明 |
|------|------|
| JSON 持久化 | `data/aggregated_params.json`，scheduler 写入 → polling_trader 读取 |
| 聚合 TTL | 7200s（2小时 > scheduler 1小时间隔，确保不过期） |
| 磁盘加载频率 | 60s（避免每次 get 都读文件） |
| 过期重载 | 聚合缓存过期时自动从磁盘重新加载（`if` 非 `elif`） |

## 接入点（已落地）

| 子系统 | 路径 | 状态 |
|---|---|---|
| trailing_stop | `16-调控系统/core/trailing_stop/component.py:346` | ✅ 已接入 + FAIL-OPEN |
| polling_trader | `11-易经推理系统/scripts/memory_l4/polling_trader.py:10962` | ✅ 已接入 + 影子模式 + NVDA 修复 |
| 集成测试 | `16-调控系统/tests/trailing_stop/test_param_center_integration.py` | ✅ |

## 影子模式

| 项 | 说明 |
|---|---|
| 数据库 | `11-易经推理系统/scripts/memory_l4/data/param_center_deviation.db` |
| Schema | `symbol, timestamp, param_center_recommended, actual_used, deviation_pct, aggregator_weights, confidence, event_type` |
| 集成点 | `polling_trader.py:11032-11044` 调用 `record_deviation()` |
| 偏差样本 | BTC dev=35%, NVDA dev=20%, XAU dev=0% |

## 依赖

- **上游**：6 个算法适配器（HMM/Hurst/CUSUM/Bagua/PMapper/Shadow）
- **K线数据**：`11-易经推理系统/scripts/data/klines/{symbol}_1H.csv`
- **下游**：`memory_l4.bcrm2.sl_tp_config.SLTPParams`（数据结构契约）
- **路径注入**：`__init__.py` 自动注入 `11-易经推理系统/scripts` 到 `sys.path`

## 测试与产物

- 测试：`pytest param_center/tests/` → 45 passed, 0 failed, 0 errors（5.28s）
- 产物：`scripts/artifacts/param_center/ray_tune_results.json`（Ray Tune 50 trials，BTC best_calmar=1.5）
- 校准触发阈值：`MIN_SAMPLE_COUNT=30, DEVIATION_AVG=0.15, DEVIATION_STD=0.10`
- 硬约束兜底：`SL_FLOOR=0.04, TP_FLOOR=0.12, RR_FLOOR=2.0, ATR_MULT=[2.0, 6.0]`

## 触发机制

- **定时**：scheduler.py 每小时自动聚合（subprocess 调用 runner.py）
- **手动**：`python runner.py --symbol BTC,NVDA --regime chop --verbose`
- **事件**：CUSUM 检测结构性突变 → 立即触发增量归总（规划中）
- **API**：`get_sltp_params(symbol, market_regime, use_cache)` 同步查询

## 运行中的进程

| 进程 | PID | 职责 |
|------|-----|------|
| polling_trader | 动态 | 交易执行 + param_center 读取 + NVDA SL/TP 修复 |
| param_center scheduler | 动态 | 每小时聚合 + JSON 持久化 |
| trailing_stop | 动态 | 追踪止损 + param_center ATR 读取 |

## 关联文档

- 所属子系统：[16-调控系统/docs/ENGINEERING_INDEX.md](../../docs/ENGINEERING_INDEX.md) v2.1
- 三层架构 SSoT：[1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0
- 变更记录：[16-调控系统/docs/CHANGELOG.md](../../docs/CHANGELOG.md) v2.1
- 验收 SKILL：`dream-module-post-dev-verify-workflow` v1.0.0

## 变更历史

| 版本 | 日期 | 变更 |
|------|------|------|
| v1.0 | 2026-10-07 | 初始版本：4 个任务落地，BMA + KL散度，3D 参数表 |
| v2.0 | 2026-10-09 | 6 适配器全部激活 + K线数据加载 + 定时调度 + JSON 持久化 + 资产混合 + 归一化距离 + NVDA 修复 |
