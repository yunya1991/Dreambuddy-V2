# polling_trader.py 顶层架构文档

> **版本**: v1.0 | **更新日期**: 2026-09-03
> **定位**: 易经推理系统主daemon的模块清单、主循环决策链路、核心方法说明
> **关联**: [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) · [ENGINEERING_INDEX.md](./ENGINEERING_INDEX.md) · [TRADING_CAPITAL_FLOW_MAP.md](../../0-系统文档管理/2-文档地图/TRADING_CAPITAL_FLOW_MAP.md) · [BCRM2_INFERENCE_DEEP_DIVE.md](./BCRM2_INFERENCE_DEEP_DIVE.md)（BCRM2 推理细节 9 章）
> **代码基准**: `11-易经推理系统/scripts/memory_l4/polling_trader.py` 12,763行 · 146方法 · 1个class PollingTrader

---

## 1. 文件定位

`polling_trader.py` 是易经推理系统的**主daemon入口**，封装了从数据采集到交易执行的全链路。运行方式：

```bash
# 单次执行（dry run / 测试）
python -m scripts.memory_l4.polling_trader --once

# 持续轮询（生产实盘）
python -u -m scripts.memory_l4.polling_trader --interval 300 --confidence 0.7955 \
  --max-positions 5 --position-pct 0.20 \
  --enable-cbr-cycle-log --enable-elder-ray-c4 --enable-win-prob-factor \
  --enable-three-layer-weighter --enable-elastic-gate-3l \
  --enable-bcrm-continuity-obs --enable-btc-self-reflex-valve \
  --enable-portfolio-risk-fuses
```

**当前实盘进程**: PID 86382 · 300s轮询 · OKX实盘账户A · 管理5持仓

---

## 2. 模块清单（10层）

按功能分组，共导入约40个模块，146个方法：

### 2.1 基础设施层
| 组件 | 来源 | 职责 |
|------|------|------|
| ProcessGuardian | process_guardian.py | 进程守护 + 异常告警 |
| PositionTracker | trading_utils.py | 持仓追踪 + 冷却期 + L4归档 |
| PerformanceTracker | trading_utils.py | 绩效统计 + PnL持久化 |
| RiskManager | trading_utils.py | 日亏损限制 + 连续亏损熔断 |

### 2.2 数据层
| 组件 | 来源 | 职责 |
|------|------|------|
| _load_kline_from_okx | yijing_trainer.py | OKX K线加载 |
| data_server_fixed.py | 11-易经推理系统/ | 数据服务（PID 53594，1.1GB内存） |
| _kline_to_dataframe | 内部 | K线转pd.DataFrame |

### 2.3 战略层（五域）
| 组件 | 来源 | 职责 |
|------|------|------|
| FiveDomainFeatureComputer | 五域战略层 | 道天地将法五维打分 |
| _run_once_five_domain_daily_update | L1462 | 日级五域打分更新 |
| _apply_fd_shadow_intercept | L1218 | 影子拦截（FAIL-OPEN不阻塞） |
| _init_five_domain_and_strategy_layer | L1235 | 战略层初始化 |

### 2.4 BCRM2决策层
| 组件 | 来源 | 职责 |
|------|------|------|
| BCRM2Adapter | bcrm2_adapter.py | BCRM2适配器 |
| BaguaEngine | bcrm/bagua_engine.py | 八卦力学引擎 |
| BCRMEngine | bcrm/engine.py | BCRM引擎 |
| IncrementalLearner | bcrm2/incremental_learner.py | 增量学习 |
| ShadowLogger | bcrm2/shadow_logger.py | 影子日志 |
| _fetch_and_infer | L3717 | 抓取K线+BCRM2推理（核心入口） |
| _infer_bcrm2 | L3990 | BCRM2推理实现 |
| _infer_regime | L4579 | 市态推理 |

### 2.5 退出系统
| 组件 | 来源 | 职责 |
|------|------|------|
| ClassicExitSystem | classic_exit_system.py | 经典退出 |
| YijingExitSystem | yijing_exit_system.py | 易经退出 |
| _bdsm_check_exit_actions | L5276 | BDSM出场巡检（Phase 2） |
| _exit_confirm | L4793 | 出场确认 |
| _sync_and_repair_sl_tp_for_position | L3350 | SL/TP同步修复 |

### 2.6 BDSM价值建仓
| 组件 | 来源 | 职责 |
|------|------|------|
| bdsm_snapshot_writer.py | force_vector/ | BDSM每日快照 |
| _get_bdsm_snapshot_today | L5017 | 获取今日快照 |
| _apply_bdsm_scaling | L5161 | 仓位缩放（CVS驱动） |
| _apply_bdsm_direction_constraint | L5056 | 方向硬约束 |
| _apply_bdsm_cap_multiplier | L5096 | 上限乘数 |
| _get_bdsm_accumulated_position | L5137 | 已累计仓位 |
| _neutral_bdsm_skeleton | L4995 | 中性兜底骨架 |

### 2.7 风控门禁
| 组件 | 来源 | 职责 |
|------|------|------|
| A7PracticeGate (a7_gate) | L823 | A7审计门禁（开仓必经） |
| RiskManager | trading_utils.py | 风控管理 |
| _portfolio_fuses | 组合熔断组件 | SW-C8（G-04终极/G-02黑天鹅） |
| _adjust_confidence_threshold | 内部 | 置信度阈值动态调整 |

### 2.8 学习进化
| 组件 | 来源 | 职责 |
|------|------|------|
| LearningScheduler | learning_scheduler.py | 学习调度 |
| yijing_trainer | yijing_trainer.py | 易经训练（矛盾构建/快照/检测） |
| _load_evolution_config | 内部 | 进化配置热加载 |
| _on_retrain_complete | L3649 | 重训完成回调 |

### 2.9 增强层
| 组件 | 来源 | 职责 |
|------|------|------|
| RangingMarketEnhancer | ranging_market_enhancer.py | 震荡市增强 |
| KnowledgeBridge | knowledge_bridge.py | 知识桥接 |
| parameter_mapper | bcrm2/parameter_mapper.py | 参数映射 + Alpha Blend |
| HexagramDataDrivenCalibrator | ranging_market_enhancer.py | 卦象数据驱动校准 |

### 2.10 告警
| 组件 | 来源 | 职责 |
|------|------|------|
| notify_model_error | yijing_feishu_alert.py | 模型错误告警 |
| notify_system_error | yijing_feishu_alert.py | 系统错误告警 |

---

## 3. 主循环决策链路（run_once · 17步）

`run_once()` 位于 L11834，约930行，每300秒执行一次。决策链路如下（详见架构图）：

### 3.1 初始化与状态检查（步骤1-2）
1. **币池刷新 + 日期翻转 + 知识加载**：`_maybe_refresh_coins` · `_check_date_rollover` · `_load_external_knowledge` · `_load_evolution_config`
2. **风控状态 + 绩效统计 + 资金调控**：`risk_manager.get_state` · `perf_tracker.get_today_stats` · `_fetch_capital_advice`

### 3.2 战略层与熔断（步骤3-5）
3. **五域战略层日更新**：`_run_once_five_domain_daily_update`（FAIL-OPEN，异常不阻塞）
4. **组合熔断 SW-C8**：`_portfolio_fuses.tick_and_check`（G-04终极熔断24h / G-02黑天鹅1h）
5. **置信度调整 + MODE算力分配**：`_adjust_confidence_threshold` · `_decide_mode_coins`（MODE3_FULL / MODE2_HALF / MODE1_LIGHT）

### 3.3 异常检测与推理（步骤6-7）
6. **异常检测**：遍历 `anom_coins_mode`，`_load_kline_from_okx` → `anomaly_detector.get_summary` → critical/high 标记
7. **BCRM2全推理**：遍历 `infer_full_coins`，`_fetch_and_infer` → `_infer_bcrm2` → 八卦力学+矛盾分析 → confidence/hexagram/方向

### 3.4 门禁与执行（步骤8-11）
8. **A7审计门禁**：`a7_gate.check_before_execute`（开仓必经，risk_manager + current_equity + inference）
9. **开仓/加仓/Topup补仓**：通过A7后执行；Topup对候选币二次推理
10. **BDSM出场巡检**：`_bdsm_check_exit_actions`（Phase 2强耦合，方向硬约束+仓位上限+出场OR检查）
11. **持仓同步 + 冷却期 + 风控开仓检查**：`position_tracker.has_open_position` · `is_in_cooldown` · `risk_manager.can_trade`

### 3.5 汇总（步骤12）
12. **全持仓汇总 + 轮询结束日志**：`position_tracker.all_open_positions` · 日亏损/连亏/仓位日志

---

## 4. 核心方法（8个关键方法）

| 方法 | 行号 | 职责 | 调用频率 |
|------|------|------|---------|
| `run_once` | L11834 | 主循环入口，17步决策链路 | 每300s |
| `_fetch_and_infer` | L3717 | 抓取K线+BCRM2推理核心 | 每轮每币 |
| `_infer_bcrm2` | L3990 | BCRM2推理实现（八卦+矛盾+方向） | 每轮每币 |
| `_run_once_five_domain_daily_update` | L1462 | 五域战略层日级打分 | 每日1次 |
| `_bdsm_check_exit_actions` | L5276 | BDSM出场巡检（Phase 2） | 每轮 |
| `_apply_bdsm_scaling` | L5161 | BDSM仓位缩放（CVS驱动） | 开仓时 |
| `a7_gate.check_before_execute` | L823外部 | A7审计门禁 | 每次开仓 |
| `_portfolio_fuses.tick_and_check` | 组合熔断 | SW-C8组合熔断 | 每轮tick |

---

## 5. 关键配置（生产实盘参数）

来源：`11-易经推理系统/.env` + 启动命令行参数

| 参数 | 值 | 说明 |
|------|-----|------|
| OKX_SIMULATED | false | 实盘模式 |
| --interval | 300 | 轮询间隔5分钟 |
| --confidence | 0.7955 | 开仓置信度阈值 |
| --max-positions | 5 | 最大持仓数 |
| --position-pct | 0.20 | 单仓占比20% |
| --enable-cbr-cycle-log | ✓ | CBR循环日志 |
| --enable-elder-ray-c4 | ✓ | Elder-ray C4 |
| --enable-win-prob-factor | ✓ | 胜率因子 |
| --enable-three-layer-weighter | ✓ | 三层权重 |
| --enable-elastic-gate-3l | ✓ | ElasticGate3L |
| --enable-bcrm-continuity-obs | ✓ | BCRM连续性 |
| --enable-btc-self-reflex-valve | ✓ | BTC自反阀门 |
| --enable-portfolio-risk-fuses | ✓ | 组合熔断（SW-C8） |

---

## 6. 与其他系统的关系

```
                    ┌──────────────────────┐
                    │  认知系统            │
                    │  cognitive_daemon    │
                    │  recall/record/verify│
                    └──────────┬───────────┘
                               │ 经验检索
                               ▼
┌──────────┐    OKX API    ┌──────────────────────┐    持仓文件    ┌──────────────┐
│ OKX实盘A │ ────────────→ │ polling_trader.py   │ ────────────→ │ open_positions│
│ d988a164 │ ←──────────── │ (本文件)            │ ←──────────── │ /BTC.json等  │
└──────────┘    下单       └──────────┬───────────┘    读取       └──────────────┘
                               ↑      │
                               │      │ 止损单管理
                               │      ▼
                    ┌──────────┴───────────┐
                    │ trailing_stop_runner │
                    │ (16-调控系统 PID2003)│
                    └──────────────────────┘
```

---

## 7. 文档对齐清单

- [x] 主循环 run_once 17步决策链路（L11834-12762）
- [x] 10层模块清单（40+组件）
- [x] 8个核心方法定位
- [x] 生产实盘参数（启动命令行）
- [x] 与认知系统/trailing_stop/OKX关系
- [x] **BCRM2推理细节（含五角校验v4/FAIL-CLOSED/字段Schema/溯源链）— 已拆分独立文档 BCRM2_INFERENCE_DEEP_DIVE.md，2026-09-03 完成**
- [ ] 每个核心方法的内部逻辑（P2 待细化，按需补充）

---

## 更新日志

| 日期 | 版本 | 变更 |
|------|------|------|
| 2026-09-03 | v1.0 | 首版，梳理12763行单文件的10层模块、17步主循环、8个核心方法、生产参数 |
