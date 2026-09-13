# 入场侧 BCRM2.0 反向信号分层治理 — 设计文档

> 对称于离场侧规则 2b（partial_close），形成开仓-离场学习闭环。
> 1 页文档，TDD 落地依据。

## 1. 当前状态

`_evolution_build_position`（polling_trader.py#L8401-L8430）中：
- BCRM2.0 反向 + conf > 0.8 → **硬否决**（`return` 跳过建仓）
- BCRM2.0 反向 + conf ≤ 0.8 → 放行（DEBUG 日志）

问题：0.81 与 0.94 被同等对待；evolution 无法学习 BCRM2.0 反向信号的对错；无 outcome 回流。

## 2. 分层治理方案

| BCRM2.0 反向 conf | 处理 | 仓位系数 | outcome 标签（平仓时） |
|------------------|------|---------|---------------------|
| ≥0.95 + BDSM 方向一致 | **硬否决**（保留） | 0（不开仓） | 不学习（灾难性保护） |
| ≥0.95（无 BDSM 一致） | 软权重 | ×0.3 | REDUCE_WEIGHT |
| 0.85-0.95 | 软权重 | ×0.5 | REDUCE_WEIGHT |
| 0.80-0.85 | 软权重 | ×0.7 | REDUCE_WEIGHT |
| <0.80 | 不干预 | ×1.0 | 正常 outcome |

## 3. 数据流

```
开仓时：
  BCRM2.0 反向 conf → 分层判定
  ├ ≥0.95+BDSM一致 → return（硬否决，不学习）
  └ 软权重 → _position_usdt × 系数 → market_open_long/short
            → TradeRecord 新增 2 字段：
              weight_reduce_factor: float  (0.3/0.5/0.7，默认 1.0)
              bcrm_reverse_conf_at_entry: float  (开仓时 BCRM 反向 conf，默认 0)

平仓时（TradeSettlementBridge）：
  读取 TradeRecord.weight_reduce_factor
  ├ = 1.0 → 正常 outcome（TP/SL/partial_close）
  └ < 1.0 → 生成 REDUCE_WEIGHT outcome
      ├ 平仓盈利 → REDUCE_WEIGHT_PREMATURE（减仓早了，踏空）
      └ 平仓亏损 → REDUCE_WEIGHT_CORRECT（减仓对了）

学习（ReflectionEngine.apply_reward）：
  REDUCE_WEIGHT_PREMATURE → ess_delta -0.01（BCRM 反向信号误判）
  REDUCE_WEIGHT_CORRECT   → ess_delta +0.01（BCRM 反向信号正确）
  冷启动期（样本 < 20）→ ess_delta = 0（中性，只收集不调整）
```

## 4. 改动清单

| 文件 | 改动 | 复用离场侧 |
|------|------|-----------|
| trading_utils.py | TradeRecord 新增 2 字段 | — |
| polling_trader.py L8401-L8430 | 硬否决→分层 + 仓位乘数 | 部分复用 |
| polling_trader.py L8469 | `_position_usdt × weight_reduce_factor` | — |
| polling_trader.py 开仓后 | TradeRecord 写入 2 字段 | — |
| trade_settlement_bridge.py | 平仓时读取字段生成 REDUCE_WEIGHT outcome | 模式复用 |
| reflection_engine.py | REDUCE_WEIGHT 奖励路径 + 样本计数 | 模式复用 |
| exit_sample_generator.py | REDUCE_WEIGHT 映射 | 模式复用 |
| subsystem_bridge.py | **直接复用**（离场侧已实现按币查询） | 100% |

## 5. ESS 双轨隔离

- entry-track ESS：REDUCE_WEIGHT outcome 写入
- exit-track ESS：PARTIAL_REDUCE outcome 写入（离场侧已实现）
- 双轨独立，互不污染

## 6. 测试计划（估 8-10 个）

1. conf≥0.95+BDSM一致 → 硬否决，不开仓
2. conf 0.85-0.95 → 仓位 ×0.5，TradeRecord 记录
3. conf 0.80-0.85 → 仓位 ×0.7
4. conf 0.85-0.95 + 缓存过期 → 放行（FAIL-OPEN）
5. conf 0.85-0.95 + 缓存缺失 → 放行（FAIL-OPEN）
6. 平仓盈利 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_PREMATURE
7. 平仓亏损 + weight_reduce_factor=0.5 → REDUCE_WEIGHT_CORRECT
8. weight_reduce_factor=1.0 → 正常 outcome（不触发 REDUCE_WEIGHT）
9. 冷启动期 ess_delta=0（样本 < 20）
10. 样本 ≥20 后 ess_delta ±0.01
