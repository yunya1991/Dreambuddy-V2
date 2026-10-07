# 参数中心（Param Center）— 16-调控系统/scripts/

> **版本**: v1.0 | **更新**: 2026-10-07 | **状态**: active（4 个任务全部落地）
> **SPEC**: `param-center-arch-20261007`（三层混合架构 Layer 2）
> **认知记忆**: VM-1791350368266-0cff9fc7 / VM-1791350666257-864caf64 / VM-1791350788450-1f139d63 / VM-1791351023601-85bb8755

## 定位

参数中心是 16-调控系统的子模块（位于 `scripts/` 而非 `core/`，因为它是参数基础设施而非离场决策组件）。提供"参数中心化，执行去中心化"能力：

- **聚合**：BMA + KL散度加权 6 个算法输出
- **验证**：bayes_opt + 回测四条件门禁
- **校准**：影子模式偏差分析 → 校准建议
- **优化**：Ray Tune 大规模并行搜索

## 对外 API（契约）

唯一对外公开入口：

```python
from param_center.api import get_sltp_params

params = get_sltp_params("BTC", market_regime="chop", use_cache=True)
# SLTPParams: sl_floor, tp_floor, atr_mult_range, rr_ratio_target,
#             tp_decay_floor, tp_decay_hours
```

**FAIL-OPEN**：参数中心不可用 → 返回 `_DEFAULT_PARAMS`（SL=4%, TP=12%），不阻塞主流程。

## 模块结构

```
param_center/
├── __init__.py              包入口（__all__ 9 个导出）
├── api.py                   对外 API: get_sltp_params
├── repository.py            ParamRepository 3D 参数表 + 5min 缓存 + FAIL-OPEN
├── aggregator.py            StatAggregator BMA + KL散度 + trigger_recompute
├── verifier.py              BayesianVerifier 四条件门禁
├── calibration.py           CalibrationAnalyzer 影子校准
├── ray_optimizer.py         RayTuneOptimizer 大规模并行优化
├── shadow_integration.py    ParamCenterShadowLogger 影子模式
├── adapters/                6 个算法适配器（HMM/Bagua/Hurst/PMapper/Shadow/CUSUM）
│   └── base.py              BaseAdapter.observe() FAIL-OPEN
└── tests/                   7 个测试文件 45/45 GREEN
```

## 接入点（已落地）

| 子系统 | 路径 | 状态 |
|---|---|---|
| trailing_stop | `16-调控系统/core/trailing_stop/component.py:345` | ✅ 已接入 + FAIL-OPEN |
| polling_trader | `11-易经推理系统/scripts/memory_l4/polling_trader.py:10323` | ✅ 已接入 + 影子模式 |
| 集成测试 | `16-调控系统/tests/trailing_stop/test_param_center_integration.py` | ✅ |

## 依赖

- **上游**：6 个算法适配器（HMM/Hurst/CUSUM/Bagua/PMapper/Shadow）
- **下游**：`memory_l4.bcrm2.sl_tp_config.SLTPParams`（数据结构契约）
- **路径注入**：`__init__.py` 自动注入 `11-易经推理系统/scripts` 到 `sys.path`

## 测试与产物

- 测试：`pytest param_center/tests/` → 45 passed, 0 failed, 0 errors（5.28s）
- 产物：`scripts/artifacts/param_center/ray_tune_results.json`（Ray Tune 50 trials，BTC best_calmar=1.5）
- 校准触发阈值：`MIN_SAMPLE_COUNT=30, DEVIATION_AVG=0.15, DEVIATION_STD=0.10`
- 硬约束兜底：`SL_FLOOR=0.04, TP_FLOOR=0.12, RR_FLOOR=2.0, ATR_MULT=[2.0, 6.0]`

## 触发机制

- **定时**：每日 00:00 UTC 全量归总（HMM/Hurst/Bagua 重新拟合）
- **事件**：CUSUM 检测结构性突变 → 立即触发增量归总
- **API**：`get_sltp_params(symbol, market_regime, use_cache)` 同步查询

## 关联文档

- 所属子系统：[16-调控系统/docs/ENGINEERING_INDEX.md](../../docs/ENGINEERING_INDEX.md) v2.1
- 三层架构 SSoT：[1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md](../../../1-ARCHITECTURE/SYSTEM_ARCHITECTURE_OVERVIEW.md) v3.0
- 验收 SKILL：`dream-module-post-dev-verify-workflow` v1.0.0（本模块为首个验证演练案例）
