# 23-四层闭环自进化交易架构 — 工程索引

> **版本**: v1.4 | **更新日期**: 2026-09-11
> **定位**: 模块级工程索引（L2），对齐 [DOC_STANDARD.md](../../0-系统文档管理/1-规范体系/DOC_STANDARD.md)

---

## 1. 模块定位

| 属性 | 值 |
|------|-----|
| 模块编号 | 23 |
| 模块名称 | 四层闭环自进化交易架构 |
| 核心职责 | 观察→推断→实验→反思→回馈四层闭环自进化交易策略 |
| 主入口 | `dreambuddy_evolution/evolution_pipeline.py` (EvolutionPipeline)、`dreambuddy_evolution/engines/kline_event_handler.py` (KlineEventHandler) |
| 依赖关系 | 上游：OKX API、data_center.db、SentimentEngine、polling_trader；下游：polling_trader 建仓回调 |
| 文档状态 | ✅完整（SPEC 4 份 + 文档四件套 + 案例库） |

---

## 2. 目录地图

```
23-四层闭环自进化交易架构/
├── docs/                               # 文档目录
│   ├── ENGINEERING_INDEX.md            # 本文件
│   ├── TECHNICAL_DESIGN.md             # 技术设计
│   ├── API_SPEC.md                     # 接口规格
│   ├── CHANGELOG.md                    # 变更日志
│   └── entry_bcrm_soft_weight_design.md # BCRM软权重设计
├── dreambuddy_evolution/
│   ├── engines/                        # 引擎层（核心逻辑）
│   │   ├── kline_event_handler.py     # K线事件处理器（双起点+三层仓位+SL/TP）
│   │   ├── ripple_engine.py            # 涟漪扩散引擎（外察式RI）
│   │   ├── reflection_engine.py        # 反思引擎（CS一致性+ESS奖惩）
│   │   ├── reflection_scanner.py       # 反思学习扫描器（内省式RI）
│   │   ├── trade_index_builder.py     # 系统级交易索引库
│   │   ├── trade_settlement_bridge.py # 平仓反思桥接器
│   │   ├── modifiers.py                # 三修饰子（情绪/资金流/叙事）
│   │   ├── tight_coupling_orchestrator.py # 紧耦合编排器（7步闭环）
│   │   ├── regime_gate.py              # 市场状态路由闸门（TREND/RANGE/CRISIS）
│   │   ├── pattern_detector.py        # 形态检测器（头肩顶等）
│   │   ├── deep_reasoning_engine.py   # 深度推理引擎（Phase2 AGI）
│   │   ├── meta_cognition_gate.py     # 元认知门（Phase5 Conformal）
│   │   ├── entry_signal_governor.py   # 入场信号治理器
│   │   ├── trend_following/            # 趋势跟踪引擎（Donchian+正金字塔）
│   │   │   └── trend_following_engine.py
│   │   ├── grid_trading/               # 网格交易引擎（ATR自适应间距）
│   │   │   └── grid_trading_engine.py
│   │   └── exit_engine/                # 独立离场决策引擎
│   │       ├── exit_engine.py          # EvolutionExitEngine
│   │       ├── exit_decision.py        # ExitDecision 数据类
│   │       └── exit_strategy_params.py # 离场策略参数基因
│   ├── core/                           # 核心计算层
│   │   ├── resistance_vector.py        # L1 5维阻力向量
│   │   ├── level0_path_cost.py         # Level0 路径代价 d*
│   │   ├── strategy_gene.py            # L2 策略基因库（ESS）
│   │   ├── shadow_rl.py                # L3 影子RL追踪器
│   │   ├── shadow_rl_trainer.py        # L3 ShadowRL训练器（REINFORCE+Thompson）
│   │   ├── bellman_tracker.py          # L4 Bellman V(s) 追踪器
│   │   ├── causal_engine.py            # 因果推断引擎（Phase2 AGI）
│   │   ├── counterfactual_evaluator.py # 反事实评估器（Phase2 AGI）
│   │   ├── signature_engine.py         # 签名方法引擎（Phase2.5 AGI）
│   │   ├── path_integral.py            # 路径积分引擎（Phase2.5 AGI）
│   │   ├── neural_sde_model.py        # Neural SDE 连续时间建模（Phase2 AGI）
│   │   ├── uncertainty_quantifier.py  # 不确定性量化（Conformal Prediction）
│   │   ├── regime_classifier.py        # 市场状态分类器
│   │   ├── strategy_synthesizer.py     # 策略合成器（Decision Transformer）
│   │   ├── transfer_learner.py         # 迁移学习器
│   │   ├── garch_fallback.py           # GARCH 波动率兜底
│   │   ├── ess_ema.py                  # ESS EMA 平滑
│   │   ├── exit_sample_generator.py   # 离场样本生成器
│   │   ├── exit_rl_policy.py           # 离场RL策略
│   │   └── exit_reward_calculator.py   # 离场奖励计算器
│   ├── adapters/                       # 数据适配层（20+ 文件，详见 §3.3）
│   ├── scripts/                        # 脚本
│   │   ├── shadow_backtest.py          # 影子验证回测引擎
│   │   ├── train_neural_sde.py         # Neural SDE 训练脚本
│   │   ├── fetch_btc_close.py          # BTC 收盘价拉取
│   │   └── train_exit_policy.py        # 离场策略训练
│   ├── gene_data/                      # 策略基因数据
│   │   ├── candidates/                 # Layer 0 候选基因
│   │   ├── shadow_validation/          # Layer 1 影子验证（3104 样本）
│   │   ├── strategy_genes/             # Layer 2 实盘基因（条件+动作）
│   │   ├── strategy_combinations/      # 组合库+ESS评分
│   │   └── schemas/                    # JSON Schema
│   ├── tests/                          # 测试套件（52 文件，692 测试）
│   ├── evolution_pipeline.py           # 四层闭环pipeline编排器
│   ├── weights.py                      # 权威权重唯一源
│   └── alert_bridge.py                 # Lark告警桥接
├── SPEC-数据管线打通与能力落地.md        # 数据管线SPEC
├── SPEC-金融思维链层FTC设计.md          # FTC设计SPEC
├── SPEC-AGI升级蓝图.md                  # AGI升级蓝图（5 Phase）
└── SPEC-趋势跟踪正金字塔与网格策略落地.md # 趋势跟踪+网格SPEC
```

**代码统计**：`engines/` 15+ 个核心文件（含 3 个子包），`core/` 21 个，`adapters/` 20+ 个，`scripts/` 4 个，`tests/` 52 个文件（692 测试）。

---

## 3. 文件清单与职责

### 3.1 引擎层（engines/）

| 文件 | 类/函数 | 职责 | 关键方法 |
|------|---------|------|----------|
| `kline_event_handler.py` | `KlineEventHandler` | K线收盘事件核心处理器 | `on_kline_close()`, `_trigger_build_position()`, `_store_pre_trade_snapshot()` |
| `ripple_engine.py` | `RippleEngine` | 涟漪扩散引擎（外察式RI） | `detect_ripple_source()`, `compute_ri()`, `get_ri_action()` |
| `reflection_engine.py` | `ReflectionEngine` | 后验反思引擎（CS一致性→ESS奖惩） | `create_snapshot()`, `calculate_cs()`, `apply_reward()` |
| `reflection_scanner.py` | `ReflectionScanner` | 反思学习扫描器（内省式RI） | `scan()`, `get_coin_stats()` |
| `trade_index_builder.py` | `TradeIndexBuilder` | 系统级交易索引库构建器 | `_discover_sources()`, `get_trades()`, `build_index()` |
| `trade_settlement_bridge.py` | `TradeSettlementBridge` | 平仓反思桥接器 | `store_snapshot()`, `retrieve_snapshot()`, `on_trade_settled()` |
| `modifiers.py` | `apply_all_modifiers` 等 | 三修饰子（情绪/资金流/叙事） | `apply_sentiment_modifier()`, `apply_capital_modifier()` |
| `tight_coupling_orchestrator.py` | `TightCouplingOrchestrator` | 紧耦合7步闭环编排器 | `observe()`, `hypothesize()`, `experiment()`, `measure()`, `reflect()`, `learn()`, `feedback()` |
| `regime_gate.py` | `RegimeGateSwitch` | 市场状态路由闸门 | `detect_regime()`, `route_strategy()` |
| `pattern_detector.py` | `PatternDetector` | 形态检测器（头肩顶等） | `detect_head_shoulders()` |
| `deep_reasoning_engine.py` | `DeepReasoningEngine` | 深度推理引擎（Phase2 AGI） | `reason()` |
| `meta_cognition_gate.py` | `MetaCognitionGate` | 元认知门（Phase5 Conformal） | `check_confidence()` |
| `entry_signal_governor.py` | `EntrySignalGovernor` | 入场信号治理器 | `govern()` |
| `trend_following/trend_following_engine.py` | `TrendFollowingEngine`, `DonchianChannel`, `ATRStopCalculator`, `PyramidingPositionSizer` | 趋势跟踪+正金字塔加仓 | `evaluate()`, `calc_stop()`, `calc_position_size()` |
| `grid_trading/grid_trading_engine.py` | `GridTradingEngine`, `GridParameterCalculator`, `GridRiskGate` | 网格交易（ATR自适应间距） | `evaluate()`, `calc_params()`, `check_risk()` |
| `exit_engine/exit_engine.py` | `EvolutionExitEngine` | 独立离场决策引擎 | `decide()`, `adjust_sl_tp()` |
| `exit_engine/exit_decision.py` | `ExitDecision` | 离场决策数据类 | `action`, `reason`, `sl`, `tp` |
| `exit_engine/exit_strategy_params.py` | `ExitStrategyParams` | 离场策略参数基因 | `sl_mult`, `tp_rr`, `trailing_arm` |

### 3.2 核心计算层（core/）

| 文件 | 类/函数 | 职责 | 关键方法 |
|------|---------|------|----------|
| `resistance_vector.py` | `ResistanceVector` | L1 5维阻力向量计算器 | `calculate()` |
| `level0_path_cost.py` | `compute_d_star()`, `compute_g_diag()` | Level0 路径代价计算 | `compute_d_star()` |
| `strategy_gene.py` | `load_gene_library()`, `calculate_ess()`, `top_combinations_by_ess()` | L2 策略基因加载+ESS排序 | `load_gene_library()`, `calculate_ess()` |
| `shadow_rl.py` | `ShadowRLTracker` | L3 影子RL样本追踪+Phase3自动激活 | `record()`, `get_stats()`, `is_phase3_activated()` |
| `shadow_rl_trainer.py` | `ShadowRLTrainer`, `SimplePolicy` | L3 RL训练器（REINFORCE+Thompson+gmax变异） | `train_policy()`, `mutate_gmax()`, `thompson_sample()`, `select_best_gene()` |
| `bellman_tracker.py` | `BellmanVTracker` | L4 Bellman V(s) TD(0)更新 | `td_update()`, `get_ess_adjustment()` |
| `causal_engine.py` | `CausalEngine` | 因果推断引擎（Phase2 AGI） | `estimate_ate()` |
| `counterfactual_evaluator.py` | `CounterfactualEvaluator` | 反事实评估器（Phase2 AGI） | `evaluate()` |
| `signature_engine.py` | `SignatureEngine` | 签名方法引擎（Phase2.5 AGI） | `compute_signature()` |
| `path_integral.py` | `PathIntegralEngine` | 路径积分引擎（Phase2.5 AGI） | `integrate()` |
| `neural_sde_model.py` | `NeuralSDEModel` | Neural SDE 连续时间建模（Phase2 AGI） | `train()`, `simulate()` |
| `uncertainty_quantifier.py` | `UncertaintyQuantifier` | 不确定性量化（Conformal Prediction） | `conformal_predict()` |
| `regime_classifier.py` | `RegimeClassifier` | 市场状态分类器 | `classify()` |
| `strategy_synthesizer.py` | `StrategySynthesizer` | 策略合成器（Decision Transformer） | `synthesize()` |
| `transfer_learner.py` | `TransferLearner` | 迁移学习器 | `transfer()` |
| `garch_fallback.py` | `GARCHFallback` | GARCH 波动率兜底 | `predict_volatility()` |
| `ess_ema.py` | `ESSEMA` | ESS EMA 平滑 | `smooth()` |
| `exit_sample_generator.py` | `ExitSampleGenerator` | 离场样本生成器 | `generate()` |
| `exit_rl_policy.py` | `ExitRLPolicy` | 离场RL策略 | `decide()` |
| `exit_reward_calculator.py` | `ExitRewardCalculator` | 离场奖励计算器 | `calculate()` |

### 3.3 适配层（adapters/）

| 文件 | 类 | 职责 |
|------|-----|------|
| `data_pipeline.py` | `DataPipelineAdapter` | 统一数据管线装配器 |
| `okx_market.py` | `OKXMarketAdapter` | OKX行情适配（K线+Ticker+持仓） |
| `data_center.py` | `DataCenterAdapter` | data_center.db衍生品数据 |
| `sentiment_bridge.py` | `SentimentBridge` | SentimentEngine情绪桥接 |
| `ess_provider.py` | `ESSDirectionProvider` | ESS方向提供器 |
| `subsystem_bridge.py` | `SubSystemBridge` | 子交易系统信号桥接 |
| `coin_scanner.py` | `CoinScanner` | 50币池扫描+美股代币配额 |
| `cognitive_bridge.py` | `CognitiveBridge` | 认知记忆系统桥接（Phase3） |
| `capital_rotation.py` | `CapitalRotationAdapter` | 资金轮动检测 |
| `traditional_finance.py` | `TraditionalFinanceBridge` | 传统金融信号（Regime/Kelly/Vol） |

---

## 4. 核心流程索引

### 4.1 紧耦合7步闭环（TightCouplingOrchestrator）

```
① 观察        ② 推断        ③ 实验        ④ 测量
observe()  →  hypothesize() → experiment() → measure()
  ↓             ↓              ↓             ↓
RippleEngine  RI阈值表     Level0 d*+对齐   TP/SL结算

⑤ 反思        ⑥ 学习        ⑦ 回馈
reflect()  →  learn()    →  feedback()
  ↓             ↓              ↓
CS一致性      ESS delta      ESS→下一轮
```

### 4.2 K线事件主流程（KlineEventHandler.on_kline_close）

```
K线收盘 → L1 R向量 → 三修饰子 → Level0 d* → RippleEngine RI
                                                      ↓
                        ReflectionScanner RI ← 系统级交易索引库
                                    ↓
                    ri = max(ripple_ri, reflection_ri)
                                    ↓
                    三层仓位分级(probe/standard/trend)
                                    ↓
                    建仓回调 + SL/TP兜底 + snapshot持久化
```

### 4.3 四层Pipeline（EvolutionPipeline.run_symbol）

```
L1 状态空间 → Level0 路径代价 → L2 策略匹配 → 对齐决策 → L3 Shadow-RL → L4 Bellman V(s)
```

---

## 5. 配置参数索引

| 文件 | 作用 | 关键参数 |
|------|------|----------|
| `weights.py` | 权威权重唯一源 | `WEIGHTS["ESS"]={H:0.4,S:0.4,N_ratio:0.2}`, `FALLBACK_VALUES={RI:0.29,...}` |
| `kline_event_handler.py` | 三层仓位门槛 | `PROBE_THRESHOLD=0.40`, `STANDARD_THRESHOLD=0.55`, `TREND_THRESHOLD=0.70` |
| `ripple_engine.py` | 涟漪检测门槛 | `vol_ratio_threshold=2.0`, `liq_change_threshold=0.30` |
| `reflection_scanner.py` | 反思学习门槛 | `MIN_WIN_RATE=0.55`, `MAX_HISTORY_DAYS=90` |
| `trade_index_builder.py` | 索引库配置 | `CACHE_TTL=300`, `DISCOVERY_CACHE_TTL=3600`, `MAX_SCAN_DEPTH=5` |

---

## 6. 测试体系

**总计**：52 个测试文件，692 个测试用例，全部通过。

| 文件 | 测试内容 |
|------|----------|
| `test_kline_event_handler.py` | K线事件处理器双起点+三层仓位 |
| `test_tight_coupling.py` | 紧耦合7步闭环 |
| `test_evolution_pipeline.py` | 四层Pipeline |
| `test_resistance_vector.py` | L1 5维阻力向量 |
| `test_strategy_gene.py` | 策略基因加载+ESS |
| `test_weights.py` | 权重一致性+敏感性 |
| `test_data_pipeline.py` | 数据管线装配 |
| `test_okx_market.py` | OKX行情适配 |
| `test_data_center_adapter.py` | data_center适配 |
| `test_sentiment_bridge.py` | 情绪桥接 |
| `test_ess_provider.py` | ESS方向提供器 |
| `test_subsystem_bridge.py` | 子系统桥接 |
| `test_trade_settlement_bridge.py` | 平仓反思桥接 |
| `test_capital_rotation.py` | 资金轮动 |
| `test_cognitive_bridge.py` | 认知桥接 |
| `test_narrative_adapter.py` | 叙事适配 |
| `test_ripple_provider.py` | 涟漪数据提供 |
| `test_modifiers.py` | 三修饰子 |
| `test_v3_backtest.py` | V3回测 |
| `test_trend_following_engine.py` | 趋势跟踪引擎（Donchian+ATR+金字塔） |
| `test_grid_trading_engine.py` | 网格交易引擎（ATR间距+硬止损） |
| `test_regime_gate_switch.py` | RegimeGate路由（TREND/RANGE/CRISIS） |
| `test_evolution_exit_engine.py` | 独立离场引擎 |
| `test_evolution_exit_engine_bcrm_reduce.py` | BCRM反向信号减仓 |
| `test_evolution_entry_bcrm_soft_weight.py` | BCRM软权重入场 |
| `test_exit_sample_generator.py` | 离场样本生成 |
| `test_exit_rl_policy.py` | 离场RL策略 |
| `test_shadow_rl_trainer.py` | ShadowRL训练器（变异+采样+Beta） |
| `test_train_policy.py` | train_policy REINFORCE训练 |
| `test_shadow_bidirectional.py` | 双向回测（long+short） |
| `test_donchian_dynamic_direction.py` | Donchian动态方向突破 |
| `test_shadow_trend_grid.py` | 趋势+网格基因回测 |
| `test_trend_grid_genes.py` | 趋势+网格基因入库 |
| `test_p0_dynamic_direction.py` | P0 方向动态化 |
| `test_p1_weight_adjustment.py` | P1 权重调整 |
| `test_p2_new_signals.py` | P2 新信号（颈线跌破等） |
| `test_p3_adx_threshold.py` | P3 ADX阈值调整 |
| `test_causal_engine.py` | 因果推断引擎 |
| `test_counterfactual_transfer.py` | 反事实评估+迁移 |
| `test_signature_path_integral.py` | 签名方法+路径积分 |
| `test_neural_sde_model.py` | Neural SDE 模型 |
| `test_uncertainty_meta_cognition.py` | 不确定性量化+元认知 |
| `test_deep_reasoning_engine.py` | 深度推理引擎 |
| `test_strategy_synthesizer.py` | 策略合成器 |
| `test_pattern_detector.py` | 形态检测器 |
| `test_rotation_signal_scanner.py` | 轮动信号扫描 |
| `test_ess_adaptive.py` | ESS自适应 |
| `test_pipeline_integration.py` | P0 RegimeGate+策略引擎接入 pipeline |
| `test_p1_integration.py` | P1 PatternDetector+weight 接入 |
| `test_p2_cbr_extension.py` | P2 CBR 扩展（pattern+case_type） |
| `test_p3_agi_pipeline.py` | P3 AGI 模块懒初始化接入 |

**运行命令**：
```bash
cd 23-四层闭环自进化交易架构 && python -m pytest dreambuddy_evolution/tests/ -v
```

---

## 7. 技术债务

| 债务项 | 严重程度 | 说明 | 状态 |
|--------|----------|------|------|
| RegimeGateSwitch 未接入 pipeline | — | ✅ 已接入 evolution_pipeline._discover_paths | **已解决** |
| TrendFollowingEngine/GridTradingEngine 未接入 | — | ✅ 路由路径已接入 pipeline | **已解决** |
| ShadowRLTrainer 未接入决策 | — | ✅ 实例已接入 pipeline | **已解决** |
| PatternDetector 未接入 regime | — | ✅ TOP_DROP 路由已接入 | **已解决** |
| 基因 weight 未参与回测 | — | ✅ load_gene_weight/calc_weighted_pnl/should_trade 已接入 | **已解决** |
| ShadowRL Phase3 | — | ✅ 已激活（3104样本≥2000，REINFORCE训练+Thompson+gmax变异） | **已解决** |
| CBR 案例库未结构化 | — | ✅ CBRCase/CBRQuery 新增 pattern+case_type，相似度权重已加 | **已解决** |
| Phase2 因果+签名 | — | ✅ CausalEngine/SignatureEngine/PathIntegralEngine 懒初始化接入 pipeline | **已解决** |
| Phase2.5 Neural SDE | — | ✅ NeuralSDEModel 已实现，可通过 pipeline 扩展接入 | **已解决** |
| Phase3 策略合成 | — | ✅ StrategySynthesizer 已实现，可通过 pipeline 扩展接入 | **已解决** |
| Phase5 元认知 | — | ✅ MetaCognitionGate/UncertaintyQuantifier 懒初始化接入 pipeline | **已解决** |

详见 [DEBT_INDEX.md](../../DEBT_INDEX.md)。

---

## 8. 快速导航

| 目标 | 路径 |
|------|------|
| 技术设计 | [TECHNICAL_DESIGN.md](./TECHNICAL_DESIGN.md) |
| 接口规格 | [API_SPEC.md](./API_SPEC.md) |
| 变更日志 | [CHANGELOG.md](./CHANGELOG.md) |
| 数据管线SPEC | [SPEC-数据管线打通与能力落地.md](../SPEC-数据管线打通与能力落地.md) |
| FTC设计SPEC | [SPEC-金融思维链层FTC设计.md](../SPEC-金融思维链层FTC设计.md) |
| AGI升级蓝图 | [SPEC-AGI升级蓝图.md](../SPEC-AGI升级蓝图.md) |
| 趋势跟踪+网格SPEC | [SPEC-趋势跟踪正金字塔与网格策略落地.md](../SPEC-趋势跟踪正金字塔与网格策略落地.md) |
| 架构总览 | [四层闭环进化架构-最小阻力路径总览.md](../../2-KNOWLEDGE/1-TRADING/四层闭环进化架构-最小阻力路径总览.md) |
| 项目文档索引 | [0-系统文档管理/INDEX.md](../../0-系统文档管理/INDEX.md) |

---

**文档版本**: v1.4
**最后更新**: 2026-09-11
